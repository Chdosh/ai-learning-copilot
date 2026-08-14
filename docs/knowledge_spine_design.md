# 个人知识库前置：知识脊柱实施设计

> 状态：提案，作为全量个人知识库建设前的实施前置。
> 范围：只处理术语、术语来源、学习建议与复习事实；不重建历史记录、会话、方向管理、AI 调用或 UI。
> 相关文档：[terms_knowledge_base_analysis.md](terms_knowledge_base_analysis.md) 描述知识库目标能力，[learning_loop_analysis.md](learning_loop_analysis.md) 描述方向、建议与术语的闭环；本文只回答这些能力应建立在什么数据事实和模块 seam 之上。

---

## 1. 决策摘要

采用一条窄的“知识脊柱”，不做全量数据层重建：

1. 新增 `app/services/knowledge_base.py`，作为术语、来源、建议和复习的唯一外部 interface。
2. 继续复用现有 `HistoryStore` 和 SQLite，不新增 Repository、DAO、事件总线或第二套数据库模型。
3. 修复 `term_captures` 的重复术语回链缺失，使它成为术语出现事实的来源。
4. 新增 `captures.context_id`，从升级后开始保存截图发生时的真实学习方向；旧数据保持 `NULL`，不猜测回填。
5. 新增具体的 `review_events` 表，保存每次复习结果；不设计通用事件表。
6. 继续保留现有 `occurrences`、`review_count` 等字段以兼容旧代码，但未来知识能力不把它们当作不可替代的真相。
7. 不持久化重要度、掌握度、共现关系或成长统计；这些结论以后从事实重算。

这是一轮小型基础建设，不改变当前截图、解释、追问、收藏、复习和工作台的可见行为。

---

## 2. 为什么需要知识脊柱

当前应用可以正常使用，但知识写入规则散在多个调用方：

```
CaptureStreamWorker ──→ save/update capture
                    ├─→ upsert_terms
                    ├─→ save_learning_tip
                    └─→ conversation/message

FollowupWorker ──────→ add_message
                    ├─→ upsert_terms
                    └─→ save_learning_tip

MainWindow ──────────→ list/save/delete term
                    ├─→ toggle favorite
                    └─→ record view

ReviewDialog ────────→ list_due_terms
                    └─→ review_term

Workbench ───────────→ list/update learning tips
```

问题不是 `HistoryStore` 文件大，而是调用方必须知道：

- 术语怎样规范化、过滤和合并；
- 同一术语再次出现时怎样取回 id；
- 什么时候增加出现次数；
- 怎样写 `term_captures`；
- learning tip 是否重复；
- 收藏、复习和调度字段怎样一起变化；
- UI 应怎样重新构造数据对象。

如果直接继续增加掌握态、方向价值、关系推荐和成长看板，这些规则会继续散开。知识脊柱的目标是把这一类复杂度集中到一个模块，同时不扰动已经稳定的历史、会话和 UI 流程。

---

## 3. 设计原则

### 3.1 只保存事实，结论以后计算

不可恢复的事实必须从现在开始保存：

- 某术语在哪条 capture 中出现；
- capture 发生时用户选择了哪个学习方向；
- 用户何时以什么评分复习了某术语；
- 用户明确收藏、编辑或处理了什么。

可重新计算的结论暂不保存：

- 重要度；
- 掌握度；
- 学习优先级；
- 方向相关性；
- 术语共现关系；
- 周/月成长统计。

原则是：

```
事实丢失后无法补回；算法变化后结论可以重算。
```

### 3.2 只切知识垂直模块，不重建整个数据层

知识脊柱只拥有：

- `terms`；
- `term_captures`；
- `learning_tips`；
- 复习调度与 `review_events`；
- 未来由这些事实派生的知识查询。

以下职责继续留在现有实现中：

- capture 原文、翻译、解释和截图路径；
- conversations / messages；
- contexts 的新建、编辑和删除；
- settings、备份恢复、数据清理；
- OCR、AI 请求、流式解析；
- PySide6 页面、弹窗、托盘和结果窗口。

### 3.3 不为单一 SQLite 实现制造抽象层

首版 `KnowledgeBase` 直接依赖现有具体 `HistoryStore`，测试使用临时 SQLite。暂不定义 Repository Protocol、内存 Repository 或 DAO。

如果未来确实出现第二种存储实现，再根据真实变化点引入 adapter；当前不为假设需求增加接口。

### 3.4 保持可见行为不变

知识脊柱阶段不重新定义：

- 收藏是否自动进入复习；
- 取消收藏是否停止调度；
- 什么叫“掌握”；
- 什么叫“归档”；
- 重要术语怎样排序；
- learning tip 有哪些类型。

这些属于后续个人知识库产品模型。知识脊柱只让它们以后有一个稳定落点。

---

## 4. 目标架构

```
┌───────────────────────────────────────────────────────────┐
│ UI / Workers                                              │
│                                                           │
│ Overview / context editor ─────────────→ HistoryStore      │
│ Term page / review / tip list / ingest ─→ KnowledgeBase    │
└───────────────────────────────────────────────────────────┘
                                         │
                                         ▼
                              concrete HistoryStore
                              SQLite adapter + migrations
                                         │
                  ┌──────────────────────┼───────────────────┐
                  ▼                      ▼                   ▼
              terms              term_captures       review_events
                  │                      │
                  └────────────── captures.context_id
```

`KnowledgeBase` 是外部 seam，隐藏知识规则；`HistoryStore` 暂时继续作为 SQLite adapter。两者不是同名方法的一对一包装：一次知识操作会协调多次存取、校验和返回值。

### 4.1 删除测试

如果删除 `KnowledgeBase`，以下复杂度会重新散落到 workers、主窗口、复习弹窗和工作台：

- 规范化和去重；
- 术语 upsert 及 existing id 获取；
- 来源写入和幂等；
- tip 去重；
- 收藏和复习结果的一致返回；
- 复习事件；
- 未来的重点、方向、易忘和掌握查询。

因此该模块不是传递调用的浅包装，而是能减少调用方知识的深模块。

---

## 5. 数据事实模型

### 5.1 `terms`：当前知识快照

继续保留现有表和字段，不在脊柱阶段重建主表。

职责：

- 保存术语展示文本、领域口径和解释；
- 保存用户编辑、收藏和当前 SRS 快照；
- 为当前 UI 提供兼容查询。

非职责：

- 不作为术语每次出现的历史；
- 不作为每次复习的历史；
- 不保存未来的重要度或掌握度算法结果。

现有 `review_count` 与 `occurrences` 暂时保留。新代码优先使用 `occurrences` 命名；在来源事实稳定后，再单独决定是否移除 `review_count`，不和知识脊柱迁移混做。

### 5.2 `term_captures`：术语出现事实

现有主键：

```sql
PRIMARY KEY (term_id, capture_id)
```

新增反向查询索引：

```sql
CREATE INDEX IF NOT EXISTS idx_term_captures_capture
ON term_captures(capture_id, term_id);
```

不变量：

1. 同一术语、同一 capture 最多一条关系。
2. 同一术语出现在不同 capture 时，每条来源都必须写入。
3. 只有首次建立 `(term_id, capture_id)` 关系时，才增加该来源对应的出现统计。
4. 同一 capture 重试不得虚增来源或出现次数。
5. 删除 capture 或 term 时，相关来源必须清理；在全局启用 SQLite 外键前继续保留显式清理。

后续可从该表推导：

- `COUNT(DISTINCT capture_id)` 形式的出现次数；
- 术语出处；
- 同 capture 共现关系；
- 按 capture 方向计算的方向相关性；
- 最近一次出现时间。

首版不新增 `term_pairs`，避免维护第二份共现真相。

### 5.3 `captures.context_id`：方向事实

增量迁移：

```sql
ALTER TABLE captures ADD COLUMN context_id INTEGER;
CREATE INDEX IF NOT EXISTS idx_captures_context
ON captures(context_id, created_at, id);
```

语义：capture 创建或首次解释时，用户实际选中的自定义学习方向 id。

规则：

- 新 capture 写入当时的 `current_context_id`；
- 快速通用方向或未选择自定义方向时为 `NULL`；
- 重试更新同一 capture 时不静默改写原 `context_id`；
- 旧记录保持 `NULL`，不根据 domain 猜测回填；
- context 删除后 capture 仍保留，现有 `domain` 继续作为可读快照；context 清理策略在迁移实现中明确测试。

`domain` 与 `context_id` 不是冗余：`domain` 是可读领域快照，`context_id` 是用户当时选择的具体方向身份。

### 5.4 `review_events`：复习事实

新增具体事件表：

```sql
CREATE TABLE IF NOT EXISTS review_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term_id INTEGER NOT NULL,
    grade INTEGER NOT NULL CHECK (grade IN (0, 1, 2)),
    reviewed_at TEXT NOT NULL,
    interval_days INTEGER NOT NULL,
    ease REAL NOT NULL,
    lapses INTEGER NOT NULL,
    term_domain TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(term_id) REFERENCES terms(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_review_events_term_time
ON review_events(term_id, reviewed_at, id);

CREATE INDEX IF NOT EXISTS idx_review_events_time
ON review_events(reviewed_at, id);
```

每条事件保存评分完成后的调度快照。`term_domain` 是复习发生时的领域快照，避免术语以后改领域导致历史统计整体漂移。

不变量：

1. 更新术语 SRS 快照与插入 `review_events` 必须在同一事务中。
2. 一次用户评分恰好产生一条事件。
3. 失败时两者一起回滚。
4. 删除术语时事件随术语清理；在外键未全局启用前由实现显式删除。
5. 不在本表提前保存 `mastered`，掌握判定以后从事件和当前调度快照计算。

### 5.5 `learning_tips`：暂时保留现状

知识脊柱将 tips 的列表与状态操作收口到 `KnowledgeBase`，但不改 AI 的单字符串输出，也不增加 `concept/review/reading` 结构。

首版只补一个幂等规则：同一 capture 下内容、类型和领域都相同的 tip 不因重试重复写入。是否增加唯一索引，应先检查现有数据是否存在重复；没有迁移证据时先使用事务内查询去重。

---

## 6. `KnowledgeBase` 模块设计

文件：`app/services/knowledge_base.py`

依赖：

- 具体 `HistoryStore`；
- 纯函数 `term_quality`；
- 可注入或显式传入的当前时间，用于可重复测试。

禁止依赖：

- PySide6；
- `AIClient`；
- OCR；
- result window；
- settings 的全局读取；
- 文件系统截图清理。

### 6.1 输入和返回对象

```python
@dataclass(slots=True)
class KnowledgeIngest:
    capture_id: int
    terms: list[dict[str, object]]
    learning_tip: str = ""
    tip_type: str = "followup"
    domain: str = "通用"
    context_id: int | None = None


@dataclass(slots=True)
class KnowledgeIngestResult:
    term_ids: list[int]
    new_source_links: int
    tip_id: int = 0


@dataclass(slots=True)
class TermQuery:
    view: str = "all"
    query: str = ""
    domain: str = ""
    limit: int = 200
    offset: int = 0


@dataclass(slots=True)
class ReviewOutcome:
    term: TermRecord
    interval_days: int
    due_at: str
    ease: float
    lapses: int
```

这些对象只表达知识操作，不暴露 SQLite connection、SQL row 或 UI widget。

### 6.2 首版外部 interface

```python
class KnowledgeBase:
    def ingest(self, command: KnowledgeIngest) -> KnowledgeIngestResult: ...

    def list_terms(self, query: TermQuery) -> list[TermRecord]: ...
    def get_term(self, term_id: int) -> TermRecord | None: ...
    def list_term_sources(self, term_id: int, limit: int = 30) -> list[CaptureRecord]: ...

    def save_term(self, command: SaveTermCommand) -> TermRecord: ...
    def delete_term(self, term_id: int) -> None: ...
    def set_favorite(self, term_id: int, favorite: bool) -> TermRecord: ...
    def record_view(self, term_id: int) -> TermRecord: ...

    def list_due_terms(self, limit: int = 100) -> list[TermRecord]: ...
    def review(self, term_id: int, grade: int) -> ReviewOutcome: ...

    def list_tips(self, query: TipQuery) -> list[LearningTip]: ...
    def set_tip_status(self, tip_id: int, status: str) -> LearningTip: ...
```

这里不以“方法越少越好”为目标，而以“调用方不再知道表级写入顺序和状态拼装”为目标。方法均对应明确用例，不提供通用 `execute()` 或任意字段 patch。

### 6.3 内部实现策略

首版可以委托现有 `HistoryStore` 的低层方法，但必须满足：

- 一个外部用例可以组合多次存取和校验；
- 调用方不再直接使用对应低层知识写方法；
- 复习快照和事件在同一事务完成；
- ingest 返回 existing term 的真实 id；
- set/review 操作返回数据库中的完整最新记录，UI 不手工重建实体。

如果低层方法无法共享事务，优先在 `HistoryStore` 内增加接收同一 connection 的私有 helper；不让 `KnowledgeBase` 直接复制 SQL 和 SM-2 算法。

---

## 7. 如何略微降低现有复杂度

知识脊柱不是只为未来加表，也必须在完成后减少当前调用关系。

### 7.1 Workers：两次知识写调用收为一次

当前截图和追问分别调用 `upsert_terms` 与 `save_learning_tip`。迁移后统一为：

```python
knowledge_base.ingest(KnowledgeIngest(...))
```

worker 继续负责 OCR、AI、conversation/message 和 payload；不再知道术语去重、回链、tip 去重细节。

### 7.2 ReviewDialog：不再拥有调度写规则

迁移后：

```python
queue = knowledge_base.list_due_terms()
outcome = knowledge_base.review(term_id, grade)
```

弹窗只展示队列和结果，不直接操作 SRS 字段；未来增加掌握或回炉时不改按钮逻辑。

### 7.3 MainWindow 术语页：不再构造残缺实体

收藏、查看、保存和删除通过 `KnowledgeBase`。例如：

```python
term = knowledge_base.set_favorite(term.id, favorite=True)
```

UI 使用返回的完整记录，不再手工构造 `TermRecord`。后续增加字段时，UI 不会因遗漏字段而产生默认值回退。

### 7.4 Workbench tips：状态流转收口

建议列表和完成/忽略通过 `KnowledgeBase`；digest 和 context 编辑仍留在 Workbench/HistoryStore，不在本轮迁移。

### 7.5 `HistoryStore` 的外部知识接口逐步关闭

生产调用迁移完成后，以下方法只能由 `KnowledgeBase` 使用，或改为私有 helper：

- `upsert_terms`；
- `toggle_term_favorite`；
- `record_term_view`；
- `review_term`；
- `list_due_terms`；
- `save_learning_tip`；
- `set_learning_tip_status`。

不要求立即拆分或重命名 1000 多行的 `history_store.py`。复杂度降低的衡量标准是 UI/worker 不再依赖这些表级方法，而不是文件数量变多。

---

## 8. 迁移步骤

每一步只改变一种事实或一条调用路径，不做双写。

### 阶段 A：锁定行为与修复来源

1. 为同一术语跨两个 capture 的回链补失败测试。
2. 为同一 capture 重试的幂等补失败测试。
3. 修复 existing term id 获取与 `term_captures` 写入。
4. 增加 `idx_term_captures_capture`。
5. 保持 UI 和收藏/复习语义不变。

Gate：一个 term 在 N 个不同 capture 中出现，必须有 N 条唯一来源；重试相同 capture 不增加第 N+1 条来源。

### 阶段 B：增加不可恢复事实

1. 增量增加 `captures.context_id` 和索引。
2. 新 capture 保存当前 `context_id`；旧记录保持 `NULL`。
3. 新建 `review_events` 和索引。
4. 修改 `review_term` 内部事务，使快照与事件原子写入。
5. 为旧 schema、当前 schema 和重复初始化补迁移测试。

Gate：迁移前后旧数据不丢失；一次评分恰好一条事件；模拟事件插入失败时 SRS 快照不变化。

### 阶段 C：建立知识模块并迁移 ingest

1. 新建 `KnowledgeBase` 与输入/返回对象。
2. 截图术语和 tip 写入改走 `ingest`。
3. 追问术语和 tip 写入改走同一 `ingest`。
4. 删除生产代码中的旧双调用，不保留新旧双写。

Gate：截图和追问可见行为不变；worker 不再直接调用 `upsert_terms` 或 `save_learning_tip`。

### 阶段 D：迁移术语、复习和 tips 调用方

1. ReviewDialog 改走 `list_due_terms/review`。
2. MainWindow 术语页改走查询和行为方法。
3. Workbench tips 改走查询和状态方法。
4. UI 移除手工 `TermRecord` 重建。
5. 搜索生产代码，确认低层知识写方法只在 `knowledge_base.py` 或 `history_store.py` 内出现。

Gate：现有页面行为不变；未来知识字段增加不要求 UI 重新拼实体。

### 阶段 E：关闭旧 seam

1. 将已无外部生产调用的低层知识方法改为私有或明确标记为内部。
2. 测试改为主要穿过 `KnowledgeBase` interface；只保留必要的 SQLite 迁移和低层存取测试。
3. 更新 ROADMAP，将知识脊柱标记为个人知识库后续能力的前置 Gate。

不在这一阶段拆 `HistoryStore` 文件；只有当知识 SQL 已完全由明确内部区域拥有、拆分能减少维护成本时，再单独评估文件整理。

---

## 9. 验收标准

### 9.1 数据不变量

- 同一术语跨 capture 的来源完整。
- 同一 capture 重试不虚增来源。
- 新 capture 保存当时的 `context_id`；旧记录不伪造方向。
- 一次复习评分恰好产生一条事件。
- SRS 快照和事件原子提交。
- 用户编辑的术语不被 AI 覆盖。
- 删除 capture/term 后不留下知识孤儿记录。
- 相同 tip 不因相同结果重试重复写入。

### 9.2 复杂度收口

- worker 每次 AI 结果只调用一次知识 ingest。
- ReviewDialog 不直接调用低层复习存取方法。
- MainWindow 不手工构造持久化实体。
- Workbench 不直接写 tip 状态。
- UI/worker 不直接写 `occurrences`、`due_at`、`ease`、`lapses`。
- `KnowledgeBase` 不 import PySide6、AIClient 或 OCR。
- 不存在新旧知识路径双写。

### 9.3 回归验证

1. 知识脊柱 interface 的临时 SQLite 集成测试。
2. 现有 `test_knowledge_base.py`、`test_history_store.py`、`test_stream_pipeline.py`、`test_workbench.py`。
3. 因为修改共享数据 seam，最终运行完整测试套件。
4. 桌面 smoke：截图保存、术语出处、追问、重试、收藏、今日复习、建议完成/忽略。
5. 不涉及 UI 样式修改，因此不在本 Gate 做视觉重设计；若意外触碰布局或结果窗，必须另行进行真实渲染验证。

---

## 10. 风险与控制

| 风险 | 控制方式 |
|---|---|
| `KnowledgeBase` 变成同名转发层 | 外部用例必须隐藏去重、来源、事务或返回拼装；通过删除测试审查 |
| 新旧路径同时写导致重复 | 每迁移一条调用路径立即删除该路径旧调用，不使用长期 feature flag 双写 |
| schema 迁移影响旧用户 | 全部为 additive migration；旧值保持默认/NULL；准备旧 schema fixture |
| 外键声明没有实际生效 | 在全局启用外键前保留显式清理并运行 `foreign_key_check`，不假设 CASCADE 已生效 |
| `context_id` 与 domain 看似重复 | 前者保存方向身份，后者保留可读领域快照；分别承担不同语义 |
| 事件表膨胀 | 复习事件体积很小；按时间和 term 建索引，暂不做预聚合 |
| 同一分数固化错误模型 | 脊柱阶段不保存 score，后续从事实重算 |
| 重构范围扩散到 UI/AI | 明确禁止 result window、prompt、OCR、方向编辑和 digest 进入本 Gate |

---

## 11. 知识脊柱完成后的演进顺序

知识脊柱 Gate 通过后，再分批建设个人知识库：

### P1：高价值知识视图

- 全部 / 重点 / 当前方向；
- 基础词降权；
- 用户行为与方向相关性排序；
- 排序理由可解释；
- score 实时计算，不持久化。

### P2：学习生命周期与成长

- 收藏与加入学习的语义拆分；
- `new / learning / mastered` 判定；
- 遗忘回炉；
- 周期成长统计；
- digest 使用已掌握术语和完成建议。

### P3：关联与方向反馈

- 从 `term_captures` 动态计算共现；
- 用户纠正方向的反馈记录；
- tips 结构化并转为术语候选；
- 结构化关联不足时再接 embedding。

主表/多义项重构、通用事件模型、物化 `term_pairs` 等大迁移，只有真实规模和需求证明必要时再做。

---

## 12. 实施前检查清单

- [ ] 明确本 Gate 不改变收藏、复习和 UI 可见行为。
- [ ] 为已确认的重复术语回链缺失建立失败测试。
- [ ] 确认旧数据库备份/恢复路径可用。
- [ ] 确认 `captures.context_id` 旧数据保持 `NULL`。
- [ ] 确认 `review_events` 与 SRS 更新共用事务。
- [ ] 确认 `KnowledgeBase` 不依赖 PySide6 或 AIClient。
- [ ] 确认迁移调用方时不保留双写。
- [ ] 确认 Gate 结束后低层知识写方法不再被 UI/worker 直接调用。
- [ ] 完成窄测试、完整测试和桌面 smoke 后再开始 P1。

这条知识脊柱的成功标准不是“新增了多少表或模块”，而是：从此以后，任何个人知识库能力都建立在完整来源、真实方向和可追溯复习事实之上；同时现有调用方需要知道的知识规则比现在更少。
