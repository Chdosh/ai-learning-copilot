# 预留向量库代码备忘（embedding 现状与原始意图）

> 目的：记录项目中"预留但未接线"的向量（embedding）代码在哪、原来打算干什么、现在处于什么状态，避免下次忘了又要重查。

## 一、原始设计意图（还原结果）

**它的设计用途不是"词条库向量化"，而是"对截图历史做语义搜索"。**

证据来源：

| 来源 | 原文 |
|------|------|
| `docs/product_plan.md:29` | "增加 embedding，把历史记录升级成**可语义搜索的个人知识库**" |
| `docs/showcase_overview.md:42` | "**语义搜索基础** - Embedding 存储表 + 服务接口（预留）" |
| `docs/showcase_overview.md:147` | "Embedding 表 + 服务接口已就位，**后续仅需对接 API**" |
| `docs/ui_refactor_design.md:8` | "后期知识库（**语义检索**）" |
| `docs/ui_refactor_design.md:190` | "**Phase 4（后期）**：embedding 语义搜索 UI、术语复习模式、知识库总结看台" |
| `history_store.py:141` 表结构 | `capture_embeddings` 按 **capture_id** 存 —— 明确绑定"截图记录"，不是术语 |

引入时机：commit `59dfc3a`（"feat: personal database"）。

**用大白话讲**：当时想的是——给每一条截图记录生成一个"语义指纹"存下来，之后你就能**用一句话去搜过去的截图**。比如搜"神经网络过拟合怎么解决"，即使某张截图的文字里没有这几个字，只要意思相关（讲了梯度下降、正则化）也能搜出来。这是对现在"逐字包含匹配"搜索的**升级版**，属于产品计划的后期功能（Phase 4），所以当时只把数据结构和 API 调用写好，UI 和接线一直没做。

## 二、代码位置清单

### 1. `app/services/embedding.py`（整个文件，71 行）—— Embedding 服务

| 行号 | 内容 | 说明 |
|------|------|------|
| 11 | `class EmbeddingService` | 服务类 |
| 12 | `model = "text-embedding-3-small"` | 默认指纹模型 |
| 16-25 | `get_embedding(text)` | 对外入口：调 API → 打包成字节 |
| 27-52 | `_call_api(text)` | POST `{base_url}/v1/embeddings`，超时 30s，异常静默返回 None |
| 54-60 | `_pack_embedding` / `unpack_embedding` | 浮点向量 ↔ 字节序列互转 |
| 62-71 | `cosine_similarity(a, b)` | **相似度计算已写好**，全项目无人调用 |

### 2. `app/services/history_store.py` —— 存储层

| 行号 | 内容 | 说明 |
|------|------|------|
| 139-149 | `capture_embeddings` 表定义 | capture_id 主键外键、embedding BLOB、model、created_at |
| 762-775 | `save_embedding()` | 保存/覆盖指纹 |
| 777-783 | `get_embedding()` | 读取指纹 |

### 3. 已删除的死代码（2026-08-05）

| 原位置 | 内容 | 说明 |
|------|------|------|
| `history_store.py`（原 414-430 行） | `search_captures_by_term()` | 按词条关键词找截图（"知识串联"），无任何调用者，已删除 |

## 三、当前实际状态（2026-08-05 实测）

- `capture_embeddings` 表 **0 行数据**（`app/data/app.db`）
- `EmbeddingService` 全项目**没有任何 import**（搜索仅命中它自己的定义处）
- `save_embedding` / `get_embedding` **无任何调用者**
- 结论：纯预留死代码 —— "接口已就位，接线未做，表是空的"

## 四、与最近讨论的关系（结论备忘）

1. 原始预留代码针对**截图历史语义搜索**，和"词条库显示相关词"是两码事。
2. 若以后真做语义搜索：数据量 1000 条级别，直接用 `embedding.py` 里现成的 `cosine_similarity` 在 SQLite 现场比对即可，**不需要引入向量数据库**。
3. "判断哪些词条没用（存着不显示）"这个需求不归这段代码管，应走"状态列 + 行为打分 + 大模型批量体检"方案。
