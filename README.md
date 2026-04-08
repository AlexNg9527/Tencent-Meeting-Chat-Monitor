# Tencent Meeting Chat Monitor (腾讯会议聊天实时监控器)

一个基于 AI OCR 技术的腾讯会议聊天记录实时监控工具。它能够自动捕获腾讯会议的聊天窗口，利用 Gemini 或 DeepSeek 的多模态识别能力提取文字，并提供一个可视化的 Web 仪表盘。

## 🌟 核心功能

- **自动化截图识别**: 自动寻找并定位腾讯会议聊天窗口，无需手动截屏。
- **多模态 AI 驱动**: 支持 Google Gemini 1.5 Flash/Pro 和 DeepSeek-V3/R1 进行高精度 OCR。
- **感知哈希过滤**: 使用汉明距离比对算法，只有在画面发生变化时才触发 AI 识别，大幅节省 Token 消耗。
- **序列对齐算法**: 智能去重，确保即便视野滚动也能精准续接聊天记录。
- **可视化仪表盘**: 基于 Streamlit 构建，实时展示监控流、硬件诊断及系统配置。
- **数据库持久化**: 聊天记录自动存储至本地 SQLite 数据库。

## 🛠️ 技术栈

- **后端**: FastAPI, Uvicorn
- **前端**: Streamlit
- **核心逻辑**: Python, Quartz (macOS 窗口管理), PIL
- **模型支持**: Google GenAI SDK, OpenAI API (DeepSeek 适配)

## 🚀 快速开始

### 1. 克隆项目
```bash
git clone <your-repo-url>
cd codex_workspace
```

### 2. 安装依赖
建议使用虚拟环境：
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. 配置环境变量
在根目录下创建 `.env` 文件，并添加你的 API Key：
```env
GOOGLE_API_KEY=你的_GEMINI_API_KEY
```

### 4. 运行服务
需要同时启动后端服务和前端界面：

**启动后端 (API & 监控引擎):**
```bash
python server.py
```

**启动前端 (Streamlit 仪表盘):**
```bash
streamlit run app.py
```

## ⚙️ 配置说明

1. **窗口要求**: 请确保腾讯会议的聊天窗口已打开且处于在屏状态（可以是弹出独立窗口）。
2. **频率调整**: 可在仪表盘中动态修改截图频率（默认 4s）。
3. **灵敏度**: 汉明距离阈值越小，对像素级变化的捕捉越灵敏。

## ⚠️ 注意事项

- **平台限制**: 目前由于使用 `Quartz` 库，该工具仅支持 **macOS** 系统。
- **权限说明**: 首次运行截图功能时，macOS 会提示分配“屏幕录制”权限给终端或 Python。

## 📄 开源协议
[MIT License](LICENSE)
