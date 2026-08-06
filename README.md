# AI Learning Copilot

一个轻量桌面学习助手：全局快捷键截图、本地 OCR、AI 流式翻译解释，并将结果保存到本地 SQLite。

## 当前架构

```text
全局热键 / 主窗口按钮
        ↓
独立截图进程（tkinter 选区 + MSS 原生像素截图）
        ↓
RapidOCR（ONNX Runtime，中英文）
        ↓
OpenAI 兼容 Chat Completions 流式响应
        ↓
结果悬浮窗 + SQLite 历史、会话和术语
```

Tesseract 已被完全移除，不需要系统安装、可执行文件路径或语言包。

## 功能

- `Ctrl + Alt + T` 全局快捷键截图
- 多显示器虚拟桌面区域选择，高 DPI 原生像素截图
- RapidOCR 本地中英文识别
- AI 翻译、解释、术语、标签和学习建议
- 结果实时流式展示，可复制、追问、打开历史
- 截图、原文、翻译、解释、会话和术语保存到 SQLite
- 可选择仅保存识别结果、不保留截图图片

## 安装

要求 Python 3.10 或更高版本。截图选择器使用 Python 自带的 tkinter；Linux 如果未预装，需要通过系统包管理器安装 Tk。

```powershell
cd D:\work\work\ai-learning-copilot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

RapidOCR 的模型与 ONNX Runtime 等依赖由 Python 包安装，不会在首次识别时下载 Tesseract 或语言包。

## 配置

启动后在“设置”页填写：

- API Key
- Base URL，默认 `https://api.openai.com/v1`
- Model，默认 `gpt-4.1-mini`
- 全局快捷键
- 是否保存截图文件

也可以通过环境变量提供 AI 配置：

```powershell
$env:OPENAI_API_KEY="your-key"
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
$env:OPENAI_MODEL="gpt-4.1-mini"
```

## 运行

```powershell
python -m app
```

右键或 `Esc` 可以取消截图。关闭主窗口时，应用默认最小化到系统托盘。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app
```

## 数据位置

- 数据库：`app/data/app.db`
- 截图：`app/data/screenshots/`
- Markdown 导出：`app/data/exports/`

API Key 和学习记录保存在本地 SQLite。数据库、截图与导出结果不应提交到 Git。
