# AI Learning Copilot

一个个人自用的轻量桌面工具：一键截图、本地 OCR 识别文字、纯文字 AI 翻译解释、自动记录，帮助英语和计算机基础薄弱的学习者快速理解英文软件界面、报错和 AI 术语。

## 当前方案

当前版本已经从 PaddleOCR 切换为便携优先的 Tesseract OCR：

```text
截图 PNG -> vendor/tesseract 优先识别文字 -> 纯文字 AI 模型翻译解释 -> SQLite 保存记录
```

这个选择的目标是：

- 安装过程更简单
- 本地依赖更小
- 不再下载大型深度学习模型
- 不再依赖 `paddleocr` / `paddlepaddle`
- 优先使用软件自带 OCR，减少用户手动安装和命令行排错
- 方便后续替换为 Windows 系统 OCR 或 RapidOCR

## 当前能力

- PySide6 桌面窗口、托盘常驻、历史记录、术语本、设置页
- 全局快捷键触发截图，默认 `Ctrl + Alt + T`
- 鼠标框选屏幕区域并保存截图
- Tesseract 本地 OCR 识别中英文截图文字
- 使用 `mss` 保存原生分辨率截图，避免高 DPI 屏幕被 Qt 缩放降采样
- OpenAI 兼容 Chat Completions API 解释文本
- SQLite 自动保存截图、原文、翻译、解释、标签和术语
- 历史搜索和术语记录

## 安装 Python 依赖

```powershell
cd ai-learning-copilot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
```

## 便携 OCR

程序会优先查找：

```text
vendor/tesseract/tesseract.exe
```

推荐打包结构：

```text
vendor/tesseract/
  tesseract.exe
  tessdata/
    eng.traineddata
    chi_sim.traineddata
```

设置页有“检测 OCR”按钮，会直接显示 OCR 是否可用、使用哪个路径、缺少哪些语言包。

如果没有放入便携 OCR，程序才会继续查找设置页路径、系统安装路径和 PATH。

开发阶段也可以临时安装系统 Tesseract：

```powershell
winget install --id UB-Mannheim.TesseractOCR -e
```

但最终产品化目标是把 OCR 放进 `vendor/tesseract`，不要求用户手动安装。

如果使用系统安装并且程序提示找不到 Tesseract，可以在设置页填写：

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
```

macOS：

```bash
brew install tesseract
```

Ubuntu/Debian：

```bash
sudo apt install tesseract-ocr tesseract-ocr-eng
```

如果要识别中文，还需要安装中文语言包：

```bash
sudo apt install tesseract-ocr-chi-sim
```

## 运行

```powershell
python -m app
```

首次运行后，打开“设置”页填写：

- API Key：你的纯文字模型 API Key
- Base URL：默认 `https://api.openai.com/v1`
- Model：默认 `gpt-4.1-mini`，可以替换成你账号可用的文字模型
- OCR 语言：默认 `eng+chi_sim`
- Tesseract 路径：如果没有加入 PATH，就填写 `tesseract.exe` 的完整路径
- OCR 状态：点击“检测 OCR”，查看是否缺少 `eng` 或 `chi_sim`

也可以使用环境变量：

```powershell
$env:OPENAI_API_KEY="你的 key"
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
$env:OPENAI_MODEL="gpt-4.1-mini"
$env:TESSERACT_PATH="C:\Program Files\Tesseract-OCR\tesseract.exe"
python -m app
```

## 使用

- `Ctrl + Alt + T`：开始截图翻译
- 截图时右键或 `Esc`：取消截图
- 托盘菜单：开始截图、显示主窗口、退出
- 主窗口：查看历史、搜索记录、管理术语、修改设置
- 结果弹窗：复制翻译、重新解释、更简单解释、举例说明

## OCR 取舍

Tesseract 是轻量优先方案，适合软件按钮、菜单、报错、文档截图。它不追求复杂场景下的最高识别率。

中文识别依赖 `chi_sim.traineddata`。便携方案应直接自带该文件；如果缺失，设置页会显示“缺少语言：chi_sim”。

后续可以保留同一个接口扩展：

- Windows 系统 OCR：更轻，但 Windows 专用
- RapidOCR：准确率更好，但依赖和包体积更大
- 云端视觉 OCR：当前不适用，因为你的云端模型是纯文字模型

## 注意

- API Key 保存在本地 SQLite 数据库 `app/data/app.db`，该文件已加入 `.gitignore`。
- macOS 和部分 Linux 桌面环境可能需要给应用截图权限或辅助功能权限。
- Wayland 环境下全局快捷键和屏幕截图可能受系统限制，仍可使用主窗口按钮触发。
