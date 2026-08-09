# AI Learning Copilot

Windows 桌面截图翻译 / 学习助手：框选屏幕任意区域，本地 OCR 提取文字（中英文），调用 OpenAI 兼容 API 返回翻译与解释，并把每次识别的原文、结果、追问自动存成本地历史。

## 功能

- **截图**：全局快捷键框选任意区域（Windows 10 / 11）
- **本地 OCR**：RapidOCR 在本机运行，截图图像不出本机
- **AI 翻译与解释**：流式返回翻译、小白向解释、关键术语、学习建议
- **追问对话**：对每条截图记录连续提问
- **术语积累**：自动提取术语与中文名，支持收藏和 Anki 导出
- **学习方向**：按领域 / 场景配置回答背景与偏好
- **悬浮结果窗**：截图后结果以悬浮条出现，可展开 / 收起 / 拖动 / 手动调整大小

## 隐私

- OCR 在本地完成，截图图像默认不上传。
- 使用 AI 功能时，OCR 提取的文本会发送到你配置的 API 服务商（默认 DeepSeek；支持任意 OpenAI 兼容接口，包括本地 Ollama）。
- 历史、术语、学习方向保存在程序目录 `data/` 下的本地 SQLite 数据库。
- 截图默认不保存，处理完即删除；如需留档，在「设置 → 保存与导出」中开启。
- API Key 保存在 Windows 凭据管理器，不写入数据库。

## 安装（Windows）

从 [Releases](https://github.com/Chdosh/ai-learning-copilot/releases) 下载最新的 Portable 压缩包，解压后运行 `AI-Learning-Copilot.exe`。程序未签名，SmartScreen 可能提示“未知发布者”，属正常现象。

首次使用：

1. 打开「设置 → AI 配置」，填写 API Key、Base URL 与模型（默认 DeepSeek）。
2. 确认「设置 → 快捷键」中的全局快捷键（默认 `Ctrl+Alt+T`）。
3. 按快捷键框选区域即可开始。

### 便携数据

所有数据保存在 EXE 同目录的 `data/`。升级时替换 EXE 并保留 `data/`；移动程序请移动整个文件夹（只移动 EXE 会在新位置生成空数据库）。换电脑后需重新填写 API Key。

## 支持平台

Windows 10 / 11 x64。目前未签名、无自动更新；macOS / Linux 暂不支持。后续计划见 [路线图](docs/ROADMAP.md)。

## 从源码运行

```powershell
git clone https://github.com/Chdosh/ai-learning-copilot.git
cd ai-learning-copilot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m app
```

运行说明：框选截图时按 `Esc` 或右键取消；关闭主窗口默认最小化到系统托盘，从托盘菜单退出。

测试：

```powershell
python -m pytest -q
```

## 数据位置

- 数据库：`data/app.db`
- 截图（仅开启保存时）：`data/screenshots/`
- 导出：`data/exports/`

## License

MIT
