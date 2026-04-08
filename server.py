import asyncio
import uvicorn
import json
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from monitor import MeetingMonitor
from pydantic import BaseModel
from typing import List, Optional
from loguru import logger

app = FastAPI(title="Tencent Meeting Chat API")

# 允许跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局状态
logger.info("📡 初始化监控后端服务...")
monitor = MeetingMonitor()
is_running = True        # 服务生命周期
run_monitor = False      # 采集开关 (默认关闭)
monitor_interval = 4.0   # 后端截图频率 (默认 4 秒)

# 数据模型
class ChatMessage(BaseModel):
    id: str
    time: str
    user: str
    content: str

class ConfigModel(BaseModel):
    api_key: str
    model_provider: str  # "gemini" or "deepseek"
    api_base: Optional[str] = None
    model_name: Optional[str] = None
    capture_interval: Optional[float] = 4.0
    use_hamming: Optional[bool] = False
    hamming_threshold: Optional[int] = 3
    history_context_count: Optional[int] = 10
    crop_bottom_height: Optional[int] = 600

# 统一响应包装器
def response_wrapper(status="success", data=None, msg=""):
    content = {
        "status": status,
        "data": data,
        "msg": msg
    }
    return JSONResponse(content=content, media_type="application/json; charset=utf-8")

@app.on_event("startup")
async def startup_event():
    """服务器启动时开启后台监控任务"""
    logger.success("🚀 腾讯会议监控后端已就绪 | 监听端口: 8000")
    asyncio.create_task(background_monitoring_loop())

async def background_monitoring_loop():
    """无限循环采集任务 (异步非阻塞模式)"""
    global is_running, run_monitor, monitor_interval
    logger.info("🔄 后台采集引擎已进入非阻塞轮询状态")
    while is_running:
        if run_monitor:
            try:
                # 🛠️ 核心优化：将同步 OCR 识别推送到线程池运行，确保 FastAPI 事件循环不卡死
                await asyncio.to_thread(monitor.get_chat_messages)
            except Exception as e:
                logger.error(f"❌ 异步采集循环发生异常: {e}")
        
        # 使用动态频率
        await asyncio.sleep(monitor_interval if run_monitor else 2.0)

@app.get("/chat")
async def get_chat():
    """实时读取当前会议的聊天记录"""
    return response_wrapper(data=monitor.chat_history)

@app.get("/status")
async def get_status():
    """读取监控状态"""
    info = monitor._get_meeting_window_info()
    data = {
        "is_active": run_monitor,
        "is_locked": info is not None,
        "window_name": info.get("name") if info else "未找到会议窗口",
        "raw_ocr_count": monitor.raw_ocr_count,
        "history_count": len(monitor.chat_history),
        "current_hamming": monitor.current_hamming,
        "use_hamming": monitor.use_hamming,
        "hamming_threshold": monitor.hamming_threshold,
        "crop_bottom_height": monitor.crop_bottom_height,
        "history_context_count": monitor.history_context_count,
        "model_provider": monitor.provider,
        "model_name": monitor.model_name
    }
    return response_wrapper(data=data)

@app.post("/toggle")
async def toggle_monitor(request: Request):
    """开启/关闭 截图识别"""
    global run_monitor
    try:
        body = await request.json()
        run_monitor = body.get("enable", False)
        state_str = "开启" if run_monitor else "关闭"
        level = "SUCCESS" if run_monitor else "WARNING"
        logger.log(level, f"🔌 采集开关切换: {state_str}")
        return response_wrapper(msg=f"采集已{state_str}")
    except Exception as e:
        logger.error(f"🔌 开关切换失败: {e}")
        return response_wrapper(status="error", msg=str(e))

@app.post("/config")
async def update_config(conf: ConfigModel):
    """接收前端下发的模型配置"""
    global monitor_interval
    try:
        if conf.capture_interval:
            monitor_interval = float(conf.capture_interval)
            logger.warning(f"⏱️ 截图采集频率热更新: {monitor_interval}s")
            
        # 更新 monitor 实例的配置
        monitor.update_config(
            api_key=conf.api_key,
            provider=conf.model_provider,
            base_url=conf.api_base,
            model_name=conf.model_name,
            use_hamming=conf.use_hamming,
            hamming_threshold=conf.hamming_threshold,
            history_context_count=conf.history_context_count,
            crop_bottom_height=conf.crop_bottom_height
        )
        return response_wrapper(msg="后端配置已更新并落盘")
    except Exception as e:
        logger.error(f"⚙️ 配置更新发生异常: {e}")
        return response_wrapper(status="error", msg=str(e))

@app.post("/clear")
async def clear_history():
    """清空记录"""
    monitor.clear_history()
    logger.info("🗑️ 收到清空历史记录请求")
    return response_wrapper(msg="历史记录已清空")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
