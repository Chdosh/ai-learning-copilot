# AI Learning Copilot - Project Showcase Overview

## 1. Project Identity

- **Name:** AI Learning Copilot
- **Tagline:** "一键截图、OCR 识别、AI 翻译解释，自动沉淀为个人知识库"
- **Type:** 轻量级跨平台桌面学习助手（Personal Desktop Learning Assistant）
- **Author:** [@Chdosh](https://github.com/Chdosh)
- **Repo:** https://github.com/Chdosh/ai-learning-copilot
- **Language:** Python 3.11+
- **UI Framework:** PySide6 (Qt for Python)
- **License:** MIT (assumed)

## 2. What It Does

核心工作流：

```
用户按 Ctrl+Alt+T → 多屏框选 → MSS 保存截图 → RapidOCR 本地识别文字
→ AI (OpenAI兼容API) 流式返回结构化JSON → 弹窗实时显示翻译/解释
→ SQLite 自动保存完整记录 → 数据统计/术语沉淀/导出
```

解决什么问题：用户在英文软件界面、报错信息、英文文档中看到不认识的英文内容时，传统的"复制→打开翻译软件→粘贴→查看"流程太慢且无法沉淀。本工具让整个过程变成"框选→1秒出结果→自动保存"。

## 3. Key Features

### 核心功能
- **全局热键截图翻译** - Ctrl+Alt+T 在任何软件上方框选即可
- **本地 OCR** - RapidOCR + ONNX Runtime，支持中英文
- **AI 翻译解释** - 小白友好型解释，不只是翻译，更讲"这是什么"
- **术语自动提取** - AI 识别关键术语，按出现次数沉淀
- **追问对话** - 可对结果追问，三种模式：更简单/举例子/重新解释

### 数据功能（个人数据库）
- **自动分类** - 截图自动分为：报错/AI概念/Python/数据库/网络/文档
- **数据统计面板** - 趋势图、分类分布、活跃度热力图
- **术语本收藏** - ★ 标记重要术语
- **历史筛选** - 按今天/本周/本月/有追问/已分类筛选
- **数据管理** - 数据库备份/恢复/清理/优化
- **Anki 导出** - 术语导出为 Anki 兼容 CSV
- **语义搜索基础** - Embedding 存储表 + 服务接口（预留）

### UI 特性
- **7 个页面** - 首页/截图小窗/结果大窗/历史记录/术语本/数据统计/设置
- **系统托盘** - 最小化到托盘，不占任务栏
- **可缩放字体** - A+/A- 调整全局字号
- **自定义图表** - 纯 QPainter 绘制饼图/柱状图/热力图

## 4. Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Language | Python 3.11 | 全栈开发 |
| GUI | PySide6 (Qt 6) | 桌面应用框架 |
| Screen Capture | mss | 原生分辨率截图 |
| Global Hotkey | pynput | Ctrl+Alt+T 系统级热键 |
| OCR Engine | RapidOCR + ONNX Runtime | 本地中英文识别 |
| AI | OpenAI-compatible API | 翻译+解释（默认gpt-4.1-mini） |
| Database | SQLite + FTS5 | 本地存储+全文搜索 |
| Packaging | setuptools | 可编辑安装 |
| Testing | pytest | 32 个自动化测试 |

**Design choices:**
- 无 requests/httpx 依赖，使用 urllib 标准库
- 不依赖 PaddleOCR 或外部 Tesseract 可执行文件
- OCR 模型和运行时由 Python 依赖统一安装

## 5. Architecture

### Directory Structure
```
ai-learning-copilot/
├── app/
│   ├── __main__.py          # python -m app 入口
│   ├── main.py              # QApplication 启动
│   ├── paths.py             # 常量：DATA_DIR, DB_PATH
│   ├── services/            # 业务逻辑层
│   │   ├── ai_client.py     # OpenAI API 客户端 + JSON 解析
│   │   ├── history_store.py # SQLite 数据层 (5表 + FTS5)
│   │   ├── ocr.py           # RapidOCR 服务
│   │   ├── screenshot.py    # 截图子进程调用与错误处理
│   │   ├── screenshot_worker.py # tkinter 多屏选区 + MSS 捕获
│   │   ├── prompt_builder.py# AI 提示词模板
│   │   ├── settings.py      # 应用设置 dataclass
│   │   ├── categorizer.py   # 自动分类（关键词+正则）
│   │   └── embedding.py     # Embedding 服务接口
│   ├── ui/                  # 表示层
│   │   ├── main_window.py   # 主窗口：7页面 + 侧边栏 + 托盘
│   │   ├── result_window.py # 弹窗/大窗：翻译/解释/追问
│   │   ├── theme.py         # QSS 样式 + 颜色常量
│   │   ├── workers.py       # QThread 工作线程
│   │   └── statistics_widgets.py # 自定义图表组件
│   └── data/                # 运行时数据 (gitignore)
├── docs/
│   └── product_plan.md      # 产品计划
├── tests/                   # 27 个 pytest 单元测试
└── pyproject.toml           # 项目配置 [app*] 包
```

### Database Schema (5 表 + 1 FTS 虚拟表)
```
captures          - 主学习记录 (id, created_at, image_path, source_text, translation, explanation, app_name, tags, category)
terms             - 术语本 (id, term UNIQUE, chinese_name, beginner_explanation, examples, first_seen_at, review_count, favorite)
settings          - 键值配置 (key, value)
conversations     - 追问会话 (id, capture_id FK, created_at, title)
messages          - 追问消息 (id, conversation_id FK, role, content, created_at, mode)
capture_embeddings- 语义搜索向量 (capture_id FK, embedding BLOB, model, created_at)
captures_fts      - FTS5 全文搜索 (source_text, translation, explanation, tags)
```

### Color Palette (Design Tokens)
```
BLUE       = #4f7cff   主色/交互高亮
BLUE_SOFT  = #eaf2ff   淡蓝背景
GREEN      = #03989e   成功/完成
RED        = #e5484D   错误/危险
BORDER     = #e5e7eb   边框线
MUTED      = #868e96   次要文字
背景       = #f8fbff   页面背景
卡片       = #ffffff   白色卡片
主文字     = #1a1a2e   深蓝黑
```

## 6. Screenshots Description (for showcase page)

建议展示页面截图的顺序和说明：

1. **首页** - 4 个功能卡片：截图翻译、本地保存、术语本、数据统计
2. **截图翻译弹窗** - 520x330 紧凑弹窗：原文、翻译、小白解释、术语列表、标签
3. **大窗口追问** - 1180x760 带 Tab：翻译/解释/追问，可点击术语查看解释
4. **历史记录** - 左侧列表（缩略图+预览），右侧详情面板，筛选 chip 按钮
5. **术语本** - 术语表格（含★收藏列），详情面板：中文名/解释/例子/出现次数
6. **数据统计** - 上方 6 个统计卡片（今日/本周/总记录/术语/收藏/AI交互），分类饼图 + 标签柱状图
7. **活跃度热力图** - GitHub 风格的 90 天活跃度热力图 + 7 天趋势图
8. **设置页** - 左侧 5 个 tab，右侧内容切换

## 7. Project Selling Points (for portfolio)

1. **第一性原理设计** - 不停留在"能加就加"，每个功能都经过论证（详见 docs/iteration_log.md）
2. **统一 OCR 依赖** - RapidOCR 通过 Python 包安装，无外部可执行文件和语言包配置
3. **自绘制图表** - 无第三方图表库，纯 QPainter 实现饼图/柱状图/热力图
4. **自动分类引擎** - 基于正则 + 关键词权重的轻量级分类器
5. **数据所有权** - 纯本地 SQLite，无账号、无云同步、用户完全掌握数据
6. **测试覆盖** - 32 个自动化测试，覆盖数据层、OCR、截图服务和流式主链路
7. **Schema 迁移** - ALTER TABLE 自动迁移，老用户无感升级
8. **语义搜索预留** - Embedding 表 + 服务接口已就位，后续仅需对接 API

## 8. Setup & Run

```bash
# 克隆
git clone https://github.com/Chdosh/ai-learning-copilot.git
cd ai-learning-copilot

# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate  # Windows

# 安装
pip install -e .

# 运行
python -m app
# 或
ai-learning-copilot

# 测试
pip install pytest
pytest tests/ -v
```

## 9. Design Language for Showcase Page

建议展示网页的设计风格：
- **配色**：主色 #4f7cff，背景 #f8fbff，卡片白色 + 圆角 12px
- **风格**：现代简洁，大量留白，圆角卡片，微阴影
- **字体**：系统默认无衬线，标题 24px bold，正文 14px
- **图标**：使用 Unicode 符号（✧ ▣ ◴ ◔ ⚙）或 Heroicons/Lucide
- **布局**：左侧固定导航 + 右侧内容区（呼应桌面端 UI）
- **动效**：卡片 hover 上浮、按钮颜色过渡

## 10. Stats

- **代码行数:** ~3000 行 Python
- **测试:** 32 个自动化测试，全部通过
- **数据库表:** 5 实体表 + 1 FTS 虚拟表
- **UI 页面:** 7 个主页面 + 弹窗 + 大窗
- **自定义图表:** 4 种（统计卡片/饼图/柱状图/热力图）
- **主要依赖:** PySide6、mss、pynput、rapidocr-onnxruntime
