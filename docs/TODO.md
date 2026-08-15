# 待做事项表

> 按优先级排序的落地清单；版本节奏规划见 [ROADMAP.md](ROADMAP.md)。

> 个人知识库方案以 [personal_knowledge_base_plan.md](personal_knowledge_base_plan.md) 为唯一设计来源；本表只展开当前可领取任务。

## 当前唯一重点：学习页知识积累

- [x] **P1.5-A 积累查询契约与失败测试**
  - [x] `AccumulationQuery / AccumulationItem / AccumulationPage` 契约类型 + `KnowledgeBase.query_accumulation` 统一入口（单次返回积累项、来源事实、方向事实与理由）
  - [x] 排序键锁定为真实 capture 时间（+ 最新来源 id 稳定键），禁止用术语更新时间
  - [x] 7 项红灯行为测试锁定：新截图、追问重试不虚增、跨 capture 合并来源、按真实时间排序、来源删除后项消失/计数与最新来源更新、方向理由（当前方向出现/同领域/无证据）、回看性（tests/test_accumulation.py）
- [x] **P1.5-B 最近积累最小 UI**
  - [x] 学习页顶部增加“知识积累”区，展示术语、解释、方向、积累时间和来源
  - [x] 点击来源可回到原截图；不复制术语本的搜索、筛选和治理功能
  - [x] 现有复习与学习建议下移并保持原逻辑，不在本阶段扩展
- [x] **P1.5-C 证据型相关知识**
  - [x] `RelatedTermQuery / RelatedTermItem / RelatedTermPage` 契约 + `query_related_terms`：基于现有 `term_captures` 单次 SQL 动态计算同 capture 共现，不新增 `term_pairs`
  - [x] 展示相关术语、共同来源数、共同方向（shared_domains）和可理解理由（`共同出现在 N 条学习记录`、`同属 X 领域`）；排序共享数降序 + term.id 稳定键
  - [x] 学习页积累项行内"相关知识"惰性展开面板（点击查询、可收起、无 N+1）；8 项契约测试 + 学习页展开/收起 UI 测试
- [x] **P1.5-D 带理由的延伸推荐**
  - [x] `RecommendationQuery / RecommendationItem / RecommendationPage` 契约 + `query_recommendations`：候选只来自真实事实——bridge（二阶共同来源，排除直接共现）/ direction（同学习方向未共现）/ domain（同领域高价值未共现）/ tip（同领域 pending 学习建议）
  - [x] 每条推荐带可理解理由，按证据强度排序（bridge > direction > domain > tip）；不接 embedding、不写入正式术语
  - [x] 允许忽略且持久生效：术语忽略存 settings 键、建议忽略复用 tips 状态流转；学习页展开面板内展示推荐 + 忽略按钮；10 项契约测试 + UI 忽略交互测试

## 已完成基础

- [x] **术语本优化（结合学习路线）**
  - [x] 高频简单词过滤 / 难度分级：停用词兜底跳过纯功能词，`basic` 词结合行为信号默认折叠（收藏/查看后自动展开）
  - [x] 结合学习方向（领域 / 场景）：术语 per-term 领域字段 + prompt 解释口径跟随当前学习方向，同一术语在不同领域分开存储
  - [x] 术语 ↔ 历史记录关联：`term_captures` 回链表 + 术语详情"出处"区，点击跳转对应学习记录
  - [x] 间隔重复复习计划：SM-2 简化调度（忘了/模糊/记得），收藏术语自动入队，今日复习卡片 + 托盘提醒

- [x] **学习建议沉淀（自沉淀闭环）**
  - [x] `learning_tips` 表 + 截图/追问的 learning_tip 自动入库
  - [x] 学习页"学习建议"清单：按状态筛选（待处理/已完成/全部），完成/忽略流转
  - [x] 知识沉淀边界：术语与学习建议进入个人知识库；学习方向背景要点仅由用户手动编辑
  - [x] 截图方向识别：OCR 文本领域/场景画像，与当前方向冲突时托盘轻提示

## 个人知识库 P1

- [x] **P1-A 查询契约与失败测试**：`TermViewItem/TermPage` 契约、三个视图、方向三级回退、基础词规则、封顶常量、稳定分页与排序理由的 16 项红灯测试（tests/test_term_views.py）
- [x] **P1-B 统一查询实现**：`KnowledgeBase.query_terms` 聚合查询（列表/总数/领域统计/理由一次返回），分层排序与封顶，无 N+1；1000 术语/10000 链接基准 25.5ms（红线 100ms）
- [x] **P1-C 最小 UI 接线**：术语页"重点 / 当前方向 / 全部"视图切换（胶囊控件，默认重点）；当前方向视图显示方向名并接管领域筛选；`refresh_terms` 收敛为单次 `query_terms`；详情区显示排序理由与来源数量；收藏/编辑/删除/查看适配 `TermViewItem`
- [x] **P1-D 验收收口**：知识脊柱回归与 UI 断言通过；真实库副本三视图 8-10ms；1000 术语/10000 链接基准 6-19ms（红线 100ms，`tests/bench_term_query.py` 可复跑）；UI 层对 HistoryStore 术语查询直调清零；离屏渲染 + 视图切换断言通过（真实桌面渲染留待用户目验）
- [x] **独立可靠性修复**：`delete_capture` / `delete_captures_before` 级联清理 conversation/message；初始化时幂等兜底历史孤儿（开发库实测清理 12 条）；回归测试 3 项

## 体验精简

- [x] **学习页 + 工作台精简**：新建独立"学习"页（今日复习 / 学习建议清单）；工作台回归"学习方向"单一职责——领域/场景可直接输入自定义、高级选项折叠（名称/摘要分析/背景要点/回答偏好）、应用（临时）与保存（落库）两动作、已保存方向列表（点击切换、行内编辑/删除）；摘要分析先预览确认（含命中依据）再填入；导航调整为 获取 / 学习 / 术语本 / 工作台 / 设置
- [x] **概念归位：沉淀=知识，方向=识别**：移除"自沉淀进方向"的错误路径（DigestWorker / merge_summary / 学习页自沉淀卡全部删除）；AI 产出的知识只沉淀进术语本与学习建议（个人知识库），学习方向的背景要点回归用户手动锚点，绝不被自动改写

## 暂缓：积累闭环完成前不领取

### 更新与发布

- [ ] **自动检查更新与下载**
  - [ ] 版本清单 `latest.json`（最新版本号 + 下载 URL + SHA-256）
  - [ ] 启动后台检查、有新版本提示，支持"跳过本版本"
  - [ ] 下载后校验 SHA-256；退出后经 .bat 脚本替换 EXE，失败不破坏旧版本
  - [ ] 国内镜像源（Gitee / GitCode Releases）与下载失败自动切换
  - [ ] GitHub Actions 自动打包、生成 SHA256SUMS、发布 Release

### 体验完善

- [ ] 首次启动引导：配置诊断（OCR 可用性、API 连通性）、更清晰的错误提示
- [ ] 截图改用 mss 物理像素，修复高 DPI 缩放导致的 OCR 输入模糊

### 后续

- [ ] embedding 语义搜索与历史知识关联（仅在个人知识库 P3 且结构化检索不足时启动）
- [ ] Windows 安装器、代码签名
- [ ] 接入 Windows 系统 OCR（OCRProvider 边界已预留）
- [ ] macOS / Linux 适配
- [ ] 体验稳定后评估 Tauri + React 重写
