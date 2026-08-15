# 术语本 → 个人知识库：全方位分析与演进设计

> 分析范围：术语本（terms）在"沉淀个人知识库"方向上的现状、缺口、目标形态与演进路线。
> 依据：`app/services/history_store.py`、`app/ui/main_window.py`、`app/ui/workers.py`、`app/services/prompt_builder.py`、`app/services/embedding.py`、`app/services/context_detector.py`、`docs/embedding_reserved_notes.md`、`docs/ROADMAP.md`、`docs/TODO.md`、`docs/design_system.md`。

---

## 1. 现状盘点

### 1.1 数据模型（`terms` 表）

| 字段 | 实际语义 |
|---|---|
| `term` / `domain` | `UNIQUE(term, domain)`：同一术语在不同领域各占一行 |
| `chinese_name` / `beginner_explanation` / `examples` | AI 提取的白话解释，JSON 数组存例子 |
| `first_seen_at` | 首次入库时间 |
| `review_count` | **名不副实**：实际是"出现次数"（每次 upsert +1），从未被当作复习计数使用 |
| `favorite` | 收藏标记，唯一有用户主动语义的字段 |

### 1.2 产生管道

```
截图/追问 → AI 返回 JSON terms[]（prompt_builder 规则 4）
         → workers.py:285（截图）/ :425（追问）→ upsert_terms(term_dicts, domain)
         → terms 表（冲突则覆盖解释 + review_count+1）
         → 术语本页（分页/搜索/领域筛选）
```

关键事实：**整批术语共用一个 domain**（当前学习方向），AI 返回的 terms 项没有自己的领域字段；领域只有"存储维度"，没有"解释口径维度"。

### 1.3 现有界面与功能

- 列表（术语/领域/中文名/关键词/次数/收藏）+ 详情（中文名、完整解释、当前例子、出现次数）
- 搜索、领域单选筛选、分页；收藏 / 编辑 / 删除；手动新增（`QInputDialog` 四步问答）
- Anki CSV 导出（单向）
- 小偏差：`design_system.md:6.3` 约定"解释/例子用 Tab 互斥阅读"，实现是两个框上下堆叠

### 1.4 已有资产（可直接复用）

| 资产 | 位置 | 状态 |
|---|---|---|
| 停用词表 `_STOPWORDS`（含中英） | `context_detector.py:76` | 已就绪，未用于术语治理 |
| `capture_embeddings` 表 + `EmbeddingService` + `cosine_similarity` | `embedding.py` / `history_store.py:141` | 预留，0 行数据、无任何 import |
| FTS5 全文检索 | `history_store.py:841` | 已用于搜索框 |
| 领域体系 + 学习方向 | `context_detector.py` / `contexts` 表 | 已用于上下文 |
| 平滑迁移框架 | `history_store.py:181 _migrate_schema` | 全 `ALTER TABLE` 模式，可直接沿用 |

---

## 2. 问题诊断（六大缺口）

### 2.1 数据质量：术语污染与解释漂移

- **污染**：提取只靠 prompt 一句话（"必须提取所有影响理解的专业词"），没有停用词过滤与难度分级。简单词/常见词（`the`、`if`、`server` 这类高频词）会反复入库刷屏，淹没真正的生词。
- **漂移**：upsert 是覆盖式写入，后到的解释无条件覆盖先到的。同一个词第 10 次遇到时的解释质量未必比第 1 次好，甚至可能更差；没有版本、没有择优、没有"用户编辑过就保护"的机制。
- **无本地校验**：AI 返回什么存什么，没有规则层的兜底（比如"术语是纯停用词则跳过"）。

### 2.2 记忆系统缺失

- `review_count` 是出现次数，不是复习次数——字段语义与名字矛盾，是历史包袱。
- 没有任何间隔重复（SRS）字段：`due_at` / `interval` / `ease` / `lapses` / `last_review_at` 全无。
- 没有复习入口、没有遗忘曲线、收藏 ≠ 复习计划（ROADMAP 已知限制第 2 条）。

### 2.3 关联断裂：术语是孤岛

- `terms` 与 `captures` 之间**没有关联表**。曾有的 `search_captures_by_term()` 因无调用者被删除（`embedding_reserved_notes.md` 有记录）。
- 后果：点开一个术语，看不到"我第一次在哪张截图里见到它""它在什么上下文里出现过"。术语脱离了它诞生的语境，只是一行字典条目。
- 这与产品原则"会话为核心"直接冲突——学习事件的沉淀物丢掉了事件本身。

### 2.4 领域维度割裂

- `UNIQUE(term, domain)` 让同一术语在"编程/生物"各有一行，但两行之间无关联、无法横向对比（如 `vector`：向量 vs 载体）。
- 提取时整批套用当前学习方向的 domain，术语自身的领域不感知；`prompt_builder` 的 terms 规则也没有"结合学习方向给解释口径"的约束（TODO 明确要求补这一点）。
- UI 领域筛选是单选，跨领域视角缺失。

### 2.5 生命周期缺失

- 术语只有"出现/收藏"两个被动信号，没有查看次数、复习活动、掌握度等主动信号。
- 没有同义合并（`API` vs `Application Programming Interface`）、没有别名、没有淘汰/归档机制——永远用不到的词无限堆积。
- 术语库只进不出，规模越大噪声占比越高，"个人知识库"会退化成"个人垃圾场"。

### 2.6 检索与知识应用缺失

- embedding 整套代码是预留死代码（`embedding_reserved_notes.md` 已实测确认）。
- 无语义搜索（"过拟合怎么解决"搜不到讲正则化的旧截图）、无相关术语推荐、无知识关联。

---

## 3. 目标形态：术语本要长成什么样的知识库

**一句话定位**：术语本从"词汇列表"升级为**以术语为节点的个人概念网络**——每个词都有出处、有语境、有记忆状态、有关联，可复习、可回溯、可语义检索。

### 3.1 能力分层（L0–L4）

| 层 | 能力 | 对应功能 |
|---|---|---|
| L0 收集 | 从学习事件自动提取 | 已有（AI terms 提取） |
| L1 结构化 | 去噪、分级、领域标注、合并 | **0.7 重点**：停用词/难度分级、per-term 领域 |
| L2 关联 | 术语↔记录回链、术语↔术语关系 | **0.7 回链 + 0.8 相关词** |
| L3 记忆 | 间隔重复、掌握度 | **0.7 重点**：SM-2 简化版 |
| L4 检索/应用 | 语义搜索、知识关联 | **0.8**：embedding 接线 |

### 3.2 三条红线（继承产品计划，任何方案不得违反）

1. **本地优先**：数据全部本地 SQLite；AI 调用可替换（Ollama 也能跑）。
2. **会话为核心**：术语必须保留出处锚点，不是凭空条目。
3. **轻量**：只做"记忆 + 关联 + 检索"三件事；不做笔记系统、不做文档管理、不做知识图谱编辑器。

---

## 4. 演进路线（分期）

### 0.7 数据治理 + 记忆引擎（P0，本轮）

1. 简单词治理：停用词兜底 + 难度分级 + 低价值词默认折叠
2. 间隔重复：SM-2 简化版 + 每日复习卡片 + 托盘提醒
3. 术语↔记录回链：`term_captures` 表 + 详情页"出处"区
4. 领域感知：terms JSON 加可选 `domain` 字段 + prompt 口径约束
5. `review_count` 语义纠正（更名/双字段）

### 0.8 知识关联 + 语义检索（P1）

6. capture 保存后异步生成 embedding（接线现有 `EmbeddingService`）
7. 搜索框"语义搜索"模式（O(n) 现场比对，无需向量库）
8. 相关术语推荐 / 同义合并建议（术语解释的 embedding）

### 1.0 知识库成型（P2）

9. 术语主表/多义项重构（若领域行数膨胀）、掌握度看板
10. 可选本地 embedding 模型（onnxruntime 依赖已在，与 RapidOCR 同源思路）
11. 知识库导出闭环（除 Anki 外评估 Markdown/JSON 全量导出）

---

## 5. 关键设计决策

### 5.1 简单词：分级，而不是过滤

**不要硬删**：`if`、`for`、`server` 对编程新手恰恰是重要术语。正确做法是**标记 + 折叠 + 行为加权**：

- 规则层：复用 `context_detector._STOPWORDS` 并扩充；命中且从未被收藏/复习/查看 → 标 `difficulty='basic'`，列表默认折叠。
- LLM 体检（批量、手动触发）：一次调用评估约 100 个术语的 `{difficulty, is_low_value, needs_merge}`，成本约几万 token，低频运行即可。
- 排序打分：`score = w1·occurrences + w2·views + w3·favorite + w4·review_activity − w5·low_value`，替换现在单一的 `review_count` 排序。

### 5.2 间隔重复：SM-2 简化版（本地纯 SQLite）

评分三档：**0 = 忘了，1 = 模糊，2 = 记得**。

| 评分 | interval | ease |
|---|---|---|
| 0 | 1 天，lapses+1 | −0.2（下限 1.3） |
| 1 | 保持或 ×1.2 | −0.1 |
| 2 | 0→1，1→6，否则 `round(interval × ease)` | +0.1（上限 2.5） |

`due_at = last_review_at + interval_days`。复习入口：术语本页顶部"今日复习 N"卡片 + 托盘气泡；卡片正面 `term`，反面中文名/解释/例子，三个评分按钮。**与 Anki 单向互操作**：保持现有 CSV 导出不变，不引入 anki 调度同步。

### 5.3 术语↔记录回链：`term_captures`

```sql
CREATE TABLE term_captures (
    term_id    INTEGER NOT NULL REFERENCES terms(id)    ON DELETE CASCADE,
    capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (term_id, capture_id)
);
CREATE INDEX idx_term_captures_capture ON term_captures(capture_id);
```

- 写入点：`upsert_terms` 返回/反查 term_id 后，由 workers 写入（追问的术语关联原 capture_id）。
- 详情页新增"出处（N）"区：记录标题 + 时间，点击跳转 `OverviewPage.select_capture()`。

### 5.4 领域感知：per-term domain + prompt 口径

- AI 返回的 terms 项增加**可选** `domain` 字段（AI 自行判断该术语属于哪个领域），缺省回落到当前学习方向；不再整批一刀切。
- `prompt_builder.build_user_prompt` 的 terms 规则追加："术语解释结合学习上下文的领域口径；同一术语在本领域的含义优先"。
- 存储保持 `UNIQUE(term, domain)` 不变（主表/多义项重构推迟到 1.0，避免大迁移）。

### 5.5 解释合并策略（防漂移）

- 新增 `user_edited INTEGER DEFAULT 0`：用户手动编辑过的术语，AI 覆盖时跳过。
- 覆盖规则从"无条件覆盖"改为"填空优先"：新解释非空且旧解释为空才覆盖；旧解释存在时仅更新 `examples`（合并去重）与 `occurrences`。
- 这是最小成本、最大收益的一行 SQL 改动。

### 5.6 embedding 接线：O(n) 现场比对（0.8）

- 已实测结论（`embedding_reserved_notes.md`）：1000 条级别直接用现成 `cosine_similarity` 全表比对即可，**不引入向量数据库**。
- 接线点：capture 保存后在 `QThread` 异步生成 embedding → `save_embedding`；搜索框加"语义"开关；查询时全表比对取 top-k。
- 术语侧：用 `beginner_explanation` 生成 embedding（新增 `term_embeddings` 表）→ 相关术语推荐与合并建议。
- 1 万条级别再考虑 numpy 矩阵缓存/降维；当前阶段不做。

### 5.7 平滑迁移（全部 ALTER TABLE）

```sql
ALTER TABLE terms ADD COLUMN difficulty     TEXT    NOT NULL DEFAULT '';
ALTER TABLE terms ADD COLUMN status         TEXT    NOT NULL DEFAULT 'new';  -- new|learning|review|archived
ALTER TABLE terms ADD COLUMN notes          TEXT    NOT NULL DEFAULT '';
ALTER TABLE terms ADD COLUMN last_review_at TEXT    NOT NULL DEFAULT '';
ALTER TABLE terms ADD COLUMN due_at         TEXT    NOT NULL DEFAULT '';
ALTER TABLE terms ADD COLUMN interval_days  INTEGER NOT NULL DEFAULT 0;
ALTER TABLE terms ADD COLUMN ease           REAL    NOT NULL DEFAULT 2.5;
ALTER TABLE terms ADD COLUMN lapses         INTEGER NOT NULL DEFAULT 0;
ALTER TABLE terms ADD COLUMN views          INTEGER NOT NULL DEFAULT 0;
ALTER TABLE terms ADD COLUMN occurrences    INTEGER NOT NULL DEFAULT 0;
ALTER TABLE terms ADD COLUMN user_edited    INTEGER NOT NULL DEFAULT 0;
UPDATE terms SET occurrences = review_count;   -- 历史数据一次性纠正
```

沿用 `_migrate_schema` 的 try/except 模式；升级前已有数据库备份流程兜底。

---

## 6. 风险与取舍

| 风险 | 评估 | 对策 |
|---|---|---|
| AI 提取质量波动 | 高 | 5.5 合并策略 + 5.1 体检兜底；用户编辑优先 |
| 复杂度失控（知识库功能膨胀） | 高 | 3.2 三条红线；每次加功能都回答"这是记忆/关联/检索的哪一件" |
| 老用户数据库迁移 | 中 | 全 `ALTER TABLE` + 默认值；备份/恢复已存在 |
| 语义搜索 API 成本与延迟 | 中 | 异步 + 可选 Ollama/本地模型；搜索限流 |
| 全表 cosine 比对性能 | 低（当前量级） | 1000 条毫秒级；1 万条再优化 |
| 复习功能使用率低（做了没人用） | 中 | 托盘提醒 + 零门槛三键评分；0.7 末尾用数据验证留存再决定 1.0 投入 |

---

## 7. 优先级建议与验收标准

**P0（0.7 内做，顺序即优先级）**

1. 数据治理：停用词兜底 + `occurrences`/`user_edited` 字段 + 合并策略（改动小、立竿见影）
2. 回链：`term_captures` + 详情页出处区（补齐"会话为核心"的架构欠账）
3. 间隔重复：SM-2 字段 + 复习卡片 + 托盘提醒（用户价值最高）
4. 领域感知：per-term domain + prompt 口径（小改动）

**P1（0.8）**：embedding 接线、语义搜索、相关术语/合并建议。

**P2（1.0）**：主表重构、掌握度看板、本地 embedding、导出闭环。

**量化验收**

- 低价值词占比（体检后可测）< 10%
- 每日待复习完成率 ≥ 80%，积压 < 20 条
- 新术语 100% 具备 `term_captures` 回链
- 语义搜索小样本（20 query）top-5 召回率（人工评测）
- 性能红线：启动增量 < 200ms；1000 条级数据库操作均 < 50ms
