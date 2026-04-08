import streamlit as st
import time
import httpx
import os
import json

# ==========================================
# 基础配置与 API 对接
# ==========================================
API_URL = "http://localhost:8000"

st.set_page_config(
    page_title="Tencent Meeting Monitor Hub",
    page_icon="📟",
    layout="wide"
)

# 统一 API 请求函数
def api_request(method, endpoint, json_data=None):
    try:
        with httpx.Client(timeout=10.0) as client:
            if method == "GET":
                resp = client.get(f"{API_URL}{endpoint}")
            else:
                resp = client.post(f"{API_URL}{endpoint}", json=json_data)
            
            if resp.status_code == 200:
                result = resp.json()
                if result.get("status") == "success":
                    return result.get("data"), result.get("msg")
                else:
                    return None, result.get("msg")
    except Exception as e:
        return None, f"连接后端失败: {e}"
    return None, "未知错误"

# ==========================================
# 页面 1：实时监控
# ==========================================
def monitoring_page():
    st.title("📟 会议实时记录流 (Live Streams)")
    
    # 获取后端状态
    data, error = api_request("GET", "/status")
    if not data:
        st.error(f"❌ {error}")
        st.info("请确保后端服务已启动: `python server.py`")
        return

    is_active = data.get("is_active", False)
    
    # --- 侧边栏控制中心 ---
    st.sidebar.markdown("### 🎛️ 监控控制")
    
    # 1. 开启/关闭截图抓取 (移至侧边栏)
    new_state = st.sidebar.toggle("🚀 开启截图抓取", value=is_active)
    if new_state != is_active:
        api_request("POST", "/toggle", {"enable": new_state})
        st.rerun()

    # 2. 页面刷新频率 (移至侧边栏)
    refresh_sec = st.sidebar.number_input("⏱️ 页面刷新频率 (s)", min_value=1, max_value=60, value=3)

    # 3. 运行诊断
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🔍 运行诊断")
    st.sidebar.info(f"窗口锁定: `{data.get('window_name')}`")
    st.sidebar.metric("累计消息数", data.get("history_count", 0))
    if st.sidebar.button("🗑️ 清空当前历史"):
        api_request("POST", "/clear")
        st.rerun()

    # 读取聊天数据
    chat_list, _ = api_request("GET", "/chat")
    chat_list = chat_list or []

    # 终端风格日志输出
    terminal_output = ""
    display_messages = chat_list[-40:]
    
    for msg in display_messages:
        ts = msg.get("time", "")
        usr = msg.get("user", "未知")
        cont = msg.get("content", "")
        color = "#00FF41" if usr != "我" else "#3399FF"
        terminal_output += f"<p style='color:{color}; font-family:Courier New; margin:0px;'>" \
                          f"[{ts}] <b>{usr}:</b> {cont}</p>"
    
    if not display_messages:
        terminal_output = "<p style='color:#666;'>[WAITING] 正在监听数据流...</p>"

    st.markdown(f"""
        <div style="background-color:#0D0D0D; padding:20px; border-radius:10px; border: 1px solid #333; height: 580px; overflow-y: auto;">
            {terminal_output}
        </div>
    """, unsafe_allow_html=True)

    # 自动化刷新
    time.sleep(refresh_sec)
    st.rerun()

# ==========================================
# 页面 2：截图调试
# ==========================================
def debug_page():
    st.title("🔍 截图调试与视野检测")
    
    data, _ = api_request("GET", "/status")
    if data:
        use_ham = data.get("use_hamming", False)
        curr_ham = data.get("current_hamming", 0)
        thresh = data.get("hamming_threshold", 3)
        
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            st.metric("实时汉明距离 (感知差异)", curr_ham)
        with col_s2:
            if use_ham:
                if curr_ham <= thresh:
                    st.success(f"🛡️ 识别熔断：开启 (差异 {curr_ham} <= {thresh})")
                else:
                    st.info(f"⚡ 识别触发：开启 (差异 {curr_ham} > {thresh})")
            else:
                st.warning("🛡️ 汉明过滤：未开启")

    # 获取截图路径
    shot_path = os.path.join(os.path.dirname(__file__), "screenshot", "latest_chat_full.png")
    if os.path.exists(shot_path):
        st.image(shot_path, caption="当前扫描视野原始画面", use_container_width=True)
        st.success(f"截图时间: {datetime.fromtimestamp(os.path.getmtime(shot_path)).strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        st.warning("暂无截图数据，请先开启抓取。")

# ==========================================
# 页面 3：系统配置
# ==========================================
def config_page():
    st.title("⚙️ 系统配置")
    
    # 🌟 核心改进：进入页面时首先同步后端真实状态
    data, error = api_request("GET", "/status")
    backend_conf = data or {}

    # 初始化本地会话状态 (如果不存在则从后端或预设加载)
    if "config_state" not in st.session_state:
        st.session_state.config_state = {
            "api_key": os.getenv("GOOGLE_API_KEY", ""),
            "model_provider": backend_conf.get("model_provider", "gemini"),
            "api_base": backend_conf.get("api_base", ""),
            "model_name": backend_conf.get("model_name", "gemini-3.1-flash-lite-preview"),
            "capture_interval": float(backend_conf.get("capture_interval", 4.0)),
            "use_hamming": backend_conf.get("use_hamming", True),
            "hamming_threshold": int(backend_conf.get("hamming_threshold", 1)),
            "history_context_count": int(backend_conf.get("history_context_count", 10)),
            "crop_bottom_height": int(backend_conf.get("crop_bottom_height", 600))
        }

    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🤖 模型配置")
        provider = st.selectbox("选择模型服务商", ["gemini", "deepseek"], 
                               index=0 if st.session_state.config_state["model_provider"] == "gemini" else 1)
        api_key = st.text_input("API Key", type="password", value=st.session_state.config_state["api_key"])
        model_name = st.text_input("模型名称", value=st.session_state.config_state["model_name"])
        api_base = st.text_input("API 地址 (可选)", value=st.session_state.config_state["api_base"])
    
    with col2:
        st.markdown("### ⏱️ 频率与性能过滤")
        capture_int = st.number_input("后端截图频率 (s)", min_value=1, max_value=60, value=int(st.session_state.config_state["capture_interval"]))
        
        # 🌟 此处使用 session_state 确保开关状态持久化且可被正确关闭
        use_ham = st.toggle("启用汉明距离过滤 (节约 Token)", value=st.session_state.config_state["use_hamming"])
        
        hamming_thresh = st.slider("汉明距离阈值 (阈值越小越灵敏)", 0, 10, 
                                   value=st.session_state.config_state["hamming_threshold"], 
                                   disabled=not use_ham)
        
        history_cnt = st.slider("上下文参考数量 (条)", 0, 50, 
                               value=st.session_state.config_state["history_context_count"])
        
        # 🚀 新增：失败后裁剪高度配置
        crop_h = st.slider("识别失败后裁剪高度 (px)", 400, 1000, 
                          value=st.session_state.config_state["crop_bottom_height"],
                          help="当全量识别失败时，系统将自动裁剪底部此高度的区域进行重试。建议 600px。")

    # 底部右对齐保存按钮
    _, btn_col = st.columns([5, 1])
    with btn_col:
        submitted = st.button("💾 保存并应用配置", use_container_width=True, type="primary")

    if submitted:
        # 更新本地状态记录
        st.session_state.config_state.update({
            "api_key": api_key,
            "model_provider": provider,
            "api_base": api_base,
            "model_name": model_name,
            "capture_interval": capture_int,
            "use_hamming": use_ham,
            "hamming_threshold": hamming_thresh,
            "history_context_count": history_cnt,
            "crop_bottom_height": crop_h
        })
        
        # 同步至后端
        _, msg = api_request("POST", "/config", {
            "api_key": api_key,
            "model_provider": provider,
            "api_base": api_base if api_base else None,
            "model_name": model_name if model_name else None,
            "capture_interval": capture_int,
            "use_hamming": use_ham,
            "hamming_threshold": hamming_thresh,
            "history_context_count": history_cnt
        })
        if msg:
            st.success(f"✅ {msg}")
        else:
            st.success("✅ 配置已同步到后端")
            st.rerun()

    st.markdown("---")
    st.markdown("""
    **配置说明：**
    1. **Gemini**: 推荐使用 `gemini-3.1-flash-lite-preview`，识别率最高。
    2. **DeepSeek**: 响应速度快，建议使用 `deepseek-chat` (OpenAI 兼容模式)。
    """)

# ==========================================
# 导航入口 (使用 st.navigation)
# ==========================================
from datetime import datetime

pg = st.navigation([
    st.Page(monitoring_page, title="实时监控", icon="📟"),
    st.Page(debug_page, title="调试视野", icon="🔍"),
    st.Page(config_page, title="系统配置", icon="⚙️"),
])
pg.run()
