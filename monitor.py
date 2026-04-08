import os
import subprocess
import time
import re
import json
import base64
import sqlite3
from datetime import datetime
from PIL import Image
import Quartz
import AppKit
from dotenv import load_dotenv
from google import genai
from google.genai import types
from openai import OpenAI
from loguru import logger

# 加载环境变量
load_dotenv()

class MeetingMonitor:
    def __init__(self):
        self.chat_history = [] 
        self.raw_ocr_count = 0
        self.shot_dir = os.path.join(os.path.dirname(__file__), 'screenshot')
        if not os.path.exists(self.shot_dir):
            os.makedirs(self.shot_dir)
        
        # 默认配置 (优先从 .env 读取)
        self.api_key = os.getenv("GOOGLE_API_KEY")
        self.provider = "gemini"
        self.model_name = "gemini-3.1-flash-lite-preview"
        self.base_url = None
        
        # 汉明距离过滤配置 (256位高清指纹适配)
        self.use_hamming = True
        self.hamming_threshold = 1   # 降低阈值以捕捉极小变化 (如 1)
        self.last_hash = None
        self.current_hamming = 0  # 实时显示用
        
        # 上下文参考深度
        self.history_context_count = 10
        self.crop_bottom_height = 600 # 失败后默认裁剪底部高度
        
        # 加载持久化配置
        self.config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        self._load_config()
        
        # 初始化数据库与历史记录
        self._init_db()
        self._init_clients()
        logger.info(f"🚀 MeetingMonitor 核心引擎已就绪 (Config: {self.config_path})")

    def _load_config(self):
        """从 config.json 加载持久化配置"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    conf = json.load(f)
                    self.api_key = conf.get("api_key", self.api_key)
                    self.provider = conf.get("model_provider", self.provider)
                    self.model_name = conf.get("model_name", self.model_name)
                    self.base_url = conf.get("api_base", self.base_url)
                    self.use_hamming = conf.get("use_hamming", self.use_hamming)
                    self.hamming_threshold = conf.get("hamming_threshold", self.hamming_threshold)
                    self.history_context_count = conf.get("history_context_count", self.history_context_count)
                    self.crop_bottom_height = conf.get("crop_bottom_height", self.crop_bottom_height)
                    logger.info("📅 已从 config.json 加载持久化设置")
            except Exception as e:
                logger.error(f"❌ 加载配置文件失败: {e}")

    def _save_config(self):
        """将当前配置保存至 config.json"""
        try:
            conf = {
                "api_key": self.api_key,
                "model_provider": self.provider,
                "model_name": self.model_name,
                "api_base": self.base_url,
                "use_hamming": self.use_hamming,
                "hamming_threshold": self.hamming_threshold,
                "history_context_count": self.history_context_count,
                "crop_bottom_height": self.crop_bottom_height
            }
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(conf, f, indent=4, ensure_ascii=False)
            logger.debug("💾 配置已备份至 config.json")
        except Exception as e:
            logger.error(f"❌ 保存配置文件失败: {e}")

    def _init_db(self):
        """初始化 SQLite 数据库"""
        try:
            self.db_path = 'chat_history.db'
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.cursor = self.conn.cursor()
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    time TEXT,
                    user TEXT,
                    content TEXT
                )
            ''')
            self.conn.commit()
            
            # 开启时加载最后 100 条历史
            self.cursor.execute('SELECT id, time, user, content FROM messages ORDER BY time DESC LIMIT 100')
            rows = self.cursor.fetchall()
            for row in reversed(rows):
                self.chat_history.append({
                    "id": row[0], "time": row[1], "user": row[2], "content": row[3]
                })
            logger.info(f"🗄️ 数据库已准备就绪，载入 {len(self.chat_history)} 条记录")
        except Exception as e:
            logger.error(f"❌ 数据库初始化失败: {e}")

    def _init_clients(self):
        """初始化 AI 客户端"""
        self.gemini_client = None
        self.openai_client = None
        if self.provider == "gemini" and self.api_key:
            self.gemini_client = genai.Client(api_key=self.api_key)
        elif self.provider == "deepseek" and self.api_key:
            self.openai_client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url or "https://api.deepseek.com"
            )

    def update_config(self, api_key, provider, base_url=None, model_name=None, use_hamming=None, hamming_threshold=None, history_context_count=None, crop_bottom_height=None):
        """动态更新配置并持久化"""
        if api_key: self.api_key = api_key
        if provider: self.provider = provider
        if base_url: self.base_url = base_url
        if model_name: self.model_name = model_name
        
        # 更新参数
        if use_hamming is not None: self.use_hamming = use_hamming
        if hamming_threshold is not None: self.hamming_threshold = int(hamming_threshold)
        if history_context_count is not None: self.history_context_count = int(history_context_count)
        if crop_bottom_height is not None: self.crop_bottom_height = int(crop_bottom_height)
        
        self._save_config() # 💾 立即存盘
        logger.warning(f"⚙️ 监控配置热更新并落盘: Hamming={self.use_hamming}, 灵敏度={self.hamming_threshold}")
        self._init_clients()

    def _calculate_hash(self, image_path):
        """生成 256 位高密度感知哈希指纹 (16x16)"""
        try:
            # 升级为 16x16 以捕捉更精细的变化 (如数字 1)
            img = Image.open(image_path).resize((16, 16), Image.Resampling.LANCZOS).convert('L')
            pixels = list(img.getdata())
            avg = sum(pixels) / 256
            hash_bits = "".join(['1' if p > avg else '0' for p in pixels])
            return hash_bits
        except Exception as e:
            logger.error(f"🖼️ 指纹计算异常: {e}")
            return None

    def get_latest_shot_path(self):
        return os.path.join(self.shot_dir, 'latest_chat_full.png')

    def _get_meeting_window_info(self):
        """获取腾讯会议窗口 ID (支持多语和几何比例侦测)"""
        options = Quartz.kCGWindowListOptionOnScreenOnly
        window_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
        
        # 兼容的进程名
        target_pnames = ['腾讯会议', 'Tencent Meeting', 'TencentMeeting', 'Meeting']
        
        candidates = []
        for window in window_list:
            pname = window.get(Quartz.kCGWindowOwnerName, '')
            title = window.get(Quartz.kCGWindowName, '')
            bounds = window.get(Quartz.kCGWindowBounds, {})
            wid = window.get(Quartz.kCGWindowNumber)
            
            # 只要进程名包含关键词
            is_tencent_proc = any(p in pname for p in target_pnames)
            if not is_tencent_proc: continue

            # 方案 A: 标题带“聊天” (最准)
            if title and ('聊天' in title or 'Chat' in title):
                return {'id': wid, 'name': title}
            
            # 方案 B: 进程对，但标题为空，且形状是竖向 (Width < Height) -> 对应弹出聊天窗
            w_val = bounds.get('Width', 0)
            h_val = bounds.get('Height', 0)
            if title == "" and w_val > 0 and h_val > 0:
                if w_val < h_val:  # 典型长条竖窗
                    candidates.append({'id': wid, 'name': f"聊天窗(几何匹配:{int(w_val)}x{int(h_val)})"})

        if candidates:
            # 优先返回第一个竖向窗口
            logger.info(f"📍 找到可能的聊天窗口: {candidates[0]['name']}")
            return candidates[0]
            
        return None

    def get_chat_messages(self):
        self.raw_ocr_count = 0
        info = self._get_meeting_window_info()
        if not info: return self.chat_history
        if not self.api_key: 
            logger.warning("🔑 API Key 缺失，请检查配置")
            return self.chat_history

        wid = info['id']
        tmp_path = self.get_latest_shot_path()
        subprocess.run(['screencapture', '-l', str(wid), '-o', tmp_path], capture_output=True)
        if not os.path.exists(tmp_path): return self.chat_history

        # --- 汉明距离过滤核心逻辑 (256位高密度比对) ---
        if self.use_hamming:
            current_hash = self._calculate_hash(tmp_path)
            if current_hash and self.last_hash:
                dist = sum(x != y for x, y in zip(current_hash, self.last_hash))
                self.current_hamming = dist
                if dist <= self.hamming_threshold:
                    logger.debug(f"🛡️ [Skip] 灵敏度指纹位差 {dist} <= {self.hamming_threshold}，已跳过 OCR")
                    return self.chat_history
            self.last_hash = current_hash
        # ------------------------

        try:
            logger.info(f"⚡ [Recognizing] 正在通过 {self.provider} 执行全量识别...")
            
            prompt = f"""
            你是一个极其严谨的 OCR 数据抓取助手。请按顺序抓取图中【聊天记录区】可见的【所有】聊天气泡。
            
            ⚠️ 关键指令：
            1. 必须识别并输出图中【当前视野内】能看到的所有完整和部分完整的聊天消息。
            2. 如果图中出现极其密集、重复或长文干扰，请保持冷静，优先提取核心的人名和对话内容。
            3. 不要自行去重。仅仅输出图中你肉眼看到的所有真实气泡。
            4. 格式：严格返回 JSON 数组 [{{ "user": "...", "content": "..." }}]。
            5. 如果图中无消息，请返回空数组 []。
            """
            
            text_response = ""
            max_retries = 3
            retry_count = 0
            
            while retry_count < max_retries:
                retry_count += 1
                
                # 🚀 应战模式：首轮失败后（retry_count > 1），后续重试均进行底部聚焦裁剪
                current_shot_path = tmp_path
                if retry_count > 1:
                    try:
                        with Image.open(tmp_path) as full_img:
                            w, h = full_img.size
                            if h > self.crop_bottom_height + 50:
                                logger.info(f"🔍 [Focus Mode] 正在裁剪并识别底部 {self.crop_bottom_height}px (Total: {h}px)")
                                focus_path = tmp_path.replace(".png", "_focus.png")
                                # 裁剪底部区域：(左, 上, 右, 下)
                                full_img.crop((0, h - self.crop_bottom_height, w, h)).save(focus_path)
                                current_shot_path = focus_path
                    except Exception as crop_err:
                        logger.warning(f"⚠️ 视野聚焦裁剪失败: {crop_err}")

                try:
                    if self.provider == "gemini" and self.gemini_client:
                        with open(current_shot_path, "rb") as f:
                            img_data = f.read()
                        response = self.gemini_client.models.generate_content(
                            model=self.model_name,
                            contents=[prompt, types.Part.from_bytes(data=img_data, mime_type="image/png")],
                            config=types.GenerateContentConfig(temperature=0)
                        )
                        text_response = response.text
                    elif self.provider == "deepseek" and self.openai_client:
                        with open(current_shot_path, "rb") as f:
                            base64_image = base64.b64encode(f.read()).decode('utf-8')
                        response = self.openai_client.chat.completions.create(
                            model=self.model_name or "deepseek-chat",
                            messages=[{
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                                ]
                            }],
                            temperature=0
                        )
                        text_response = response.choices[0].message.content
                    
                    if text_response: break # 发现内容即退出循环
                    
                except Exception as api_err:
                    wait_time = 1.5 * retry_count
                    if retry_count < max_retries:
                        logger.warning(f"⚠️ {self.provider} 请求异常: {str(api_err)[:50]}... 正在重试 ({retry_count}/{max_retries}, 等 {wait_time}s)")
                        time.sleep(wait_time)
                    else:
                        raise api_err # 重试耗尽

            if not text_response:
                logger.warning(f"🌙 {self.provider} 多次尝试未返回结果，已优雅跳过")
                return self.chat_history

            text_response = text_response.strip()
            if "```" in text_response:
                text_response = re.sub(r'```json|```', '', text_response).strip()

            all_visible_msgs = json.loads(text_response)
            self.raw_ocr_count = len(all_visible_msgs)

            # --- 🛠️ 序列对齐算法 (Sequence Alignment) ---
            # 目标：寻找 all_visible_msgs 中相对于 self.chat_history 的增量新消息
            
            history_tail = self.chat_history[-15:] # 取最后 15 条历史做重合对比
            match_index = -1
            
            # 尝试在 all_visible_msgs 中找到与历史记录最长的重合后缀
            for i in range(len(all_visible_msgs)):
                # 检查 all_visible_msgs[:i+1] 是否匹配 history_tail 的末尾
                subset_view = all_visible_msgs[:i+1]
                subset_hist = history_tail[-(i+1):]
                
                if len(subset_hist) < len(subset_view):
                    break
                
                # 双重匹配比较 (User + Content)
                match = True
                for v, h in zip(subset_view, subset_hist):
                    if v.get("user") != h.get("user") or v.get("content", "").strip() != h.get("content", "").strip():
                        match = False
                        break
                
                if match:
                    match_index = i # 更新最新的重合断点

            # match_index 之后的消息即为“纯增量”
            new_incremental_msgs = all_visible_msgs[match_index+1:]
            
            for msg in new_incremental_msgs:
                user = msg.get("user", "未知")
                content = msg.get("content", "").strip()
                if not content: continue
                
                # 🛠️ 关键修复：即便是内容相同的消息，也赋予唯一 ID
                new_item = {
                    "id": f"{user}_{content}_{time.time()}", 
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "user": user,
                    "content": content
                }
                self.chat_history.append(new_item)
                logger.info(f"✅ [+Sequence] {user}: {content[:15]}...")
                try:
                    self.cursor.execute('INSERT OR IGNORE INTO messages VALUES (?,?,?,?)', 
                                      (new_item["id"], new_item["time"], new_item["user"], new_item["content"]))
                    self.conn.commit()
                except Exception: pass

        except Exception as e:
            logger.error(f"⚠️ {self.provider} 识别异常: {e}")
            
        if len(self.chat_history) > 200: 
            self.chat_history = self.chat_history[-200:]
        return self.chat_history

    def clear_history(self):
        """清空缓存记录"""
        self.chat_history = []
        try:
            self.cursor.execute('DELETE FROM messages')
            self.conn.commit()
            logger.info("🗑️ 本地数据库已清空")
        except Exception as e:
            logger.error(f"❌ 数据库清空失败: {e}")
