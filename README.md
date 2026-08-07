# AI Learning Copilot

一键截图、本地 OCR、AI 翻译解释，自动沉淀为个人知识库。面向英文软件界面、报错信息、英文文档的学习场景。

```
快捷键截图 → 本地 OCR → AI（OpenAI 兼容 API）→ 悬浮窗结果 + 本地知识库
```

## 核心能力

- **截图**：全局快捷键框选任意区域（Windows 10 / 11）
- **本地 OCR**：RapidOCR 在本机完成，截图图像不出本机
- **AI 翻译与解释**：流式返回翻译、小白解释、关键术语与学习建议
- **追问对话**：对每一条截图记录连续提问
- **术语积累**：自动提取术语、中文名与解释，支持收藏与 Anki 导出
- **学习方向**：为不同领域 / 场景配置回答偏好与背景上下文

## 隐私说明

- **OCR 在本机运行**：截图图像默认在本地处理，不会上传。
- **发送给 AI 的内容**：仅当使用 AI 翻译 / 解释 / 追问时，OCR 提取的**文本**及相关提示信息会发送至你在设置中配置的 AI API 服务商（默认 DeepSeek，可在设置中换成任何 OpenAI 兼容接口，包括本地 Ollama）。
- **数据存储位置**：历史记录、术语、学习方向保存在本地 SQLite 数据库，位于程序目录下 `data/`。
- **截图文件**：默认**不保存**——截图处理完成后（无论成功或失败）自动删除。如需要截图留档，请在「设置 → 保存与导出」中开启。
- **API Key**：保存在 Windows 凭据管理器（Credential Manager）中，不写入数据库，导出 / 备份的数据库文件也不包含凭据。

## 快速开始（Windows Beta）

1. 从 [Releases](https://github.com/Chdosh/ai-learning-copilot/releases) 下载 `AI-Learning-Copilot-0.5.0-beta.1-win-x64.zip`（Portable 版，未签名，Windows 可能提示"未知发布者"，属预期行为）。
2. 解压到任意目录，运行 `AI-Learning-Copilot.exe`。
3. 打开「设置 → AI 配置」，填写自己的 API Key 与模型。
4. 设置全局快捷键（默认 `<ctrl>+<alt>+t`）。
5. 开始使用。

> **Portable 说明**：所有本地数据保存在 EXE 同目录的 `data/` 文件夹中。移动时请移动整个程序文件夹；如果只移动 EXE，程序会在新位置创建新的空数据库。升级时替换 EXE 并保留原 `data/`，删除程序文件夹前请先备份 `data/app.db`。API Key 保存在 Windows 凭据管理器中，换电脑后需要重新填写。

## 支持平台

当前 Beta 主要在 **Windows 10 / 11** 上测试（全局快捷键、截图、OCR、托盘均已验证）。macOS / Linux 适配尚在计划中。

当前未实现的能力与后续计划见 [路线图](docs/ROADMAP.md)。

## 源码开发

```powershell
git clone https://github.com/Chdosh/ai-learning-copilot.git
cd ai-learning-copilot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## 运行

```powershell
python -m app
```

右键或 `Esc` 可以取消截图。关闭主窗口时，应用默认最小化到系统托盘。

## 测试

```powershell
python -m pytest -q
python -m compileall -q app
```

## 数据位置

- 数据库：`data/app.db`
- 截图（仅开启保存时）：`data/screenshots/`
- Markdown 导出：`data/exports/`

## License

MIT
