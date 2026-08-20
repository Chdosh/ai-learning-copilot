"""个人知识库的单一外部 interface（知识脊柱）。

所有术语、术语来源、学习建议与复习行为都通过 ``KnowledgeBase`` 进入系统；
调用方不再需要知道表级写入顺序、去重、回链与调度字段的拼装规则。

设计依据：``docs/knowledge_spine_design.md``。禁止依赖 PySide6、AIClient、OCR。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.services.history_store import (
    AccumulationAggregate,
    CaptureRecord,
    HistoryStore,
    LearningTip,
    RelatedAggregate,
    TermAggregate,
    TermRecord,
)


@dataclass(slots=True)
class KnowledgeIngest:
    """一次截图 / 追问产出的知识增量：术语 + 可选学习建议 + 方向事实。"""

    capture_id: int | None = None
    terms: list[dict[str, Any]] = field(default_factory=list)
    learning_tip: str = ""
    tip_type: str = "followup"
    domain: str = "通用"
    context_id: int | None = None


@dataclass(slots=True)
class KnowledgeIngestResult:
    term_ids: list[int] = field(default_factory=list)
    new_source_links: int = 0
    tip_id: int = 0


@dataclass(slots=True)
class TermQuery:
    view: str = "focus"  # focus | current_direction | all
    sort: str = "latest"  # latest | oldest | ranked
    query: str = ""
    domain: str = ""
    current_context_id: int | None = None
    effective_domain: str = "通用"
    since_at: str = ""
    limit: int = 50
    offset: int = 0


@dataclass(slots=True)
class TermViewItem:
    """术语视图项：仅暴露 UI 需要的事实，排序内部状态（方向级别、分层键）不外泄。"""

    term: TermRecord
    source_count: int
    reasons: tuple[str, ...]


@dataclass(slots=True)
class TermPage:
    items: list[TermViewItem]
    total: int
    domain_counts: list[tuple[str, int]]


# ---------------------------------------------------------------------------
# P1.5 学习页知识积累：契约（docs/personal_knowledge_base_plan.md §7.3 P1.5-A）
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AccumulationQuery:
    """一次"刷新学习页积累"的查询请求。

    - 最近积累必须按真实 capture 时间排序，禁止用术语表更新时间猜测；
    - 当前方向事实由调用方传入，KnowledgeBase 不读取 UI 设置。
    """

    limit: int = 20
    current_context_id: int | None = None
    effective_domain: str = "通用"


@dataclass(slots=True)
class AccumulationItem:
    """一条最近积累：术语 + 真实来源事实 + 展示理由。

    不变量（P1.5-B 实现时必须满足，测试已锁定）：
    - ``latest_capture_id`` 指向真实存在、未删除的 capture，可回看；
    - ``latest_capture_at`` 是该术语所有来源 capture 中最新的创建时间；
    - ``source_count`` 按不同 capture 计数；同 capture 的重试/追问不虚增；
    - 术语的所有来源 capture 被删除后，该积累项必须消失。
    """

    term: TermRecord
    latest_capture_id: int
    latest_capture_at: str
    latest_capture_title: str
    source_count: int
    reasons: tuple[str, ...]


@dataclass(slots=True)
class AccumulationPage:
    items: list[AccumulationItem]


@dataclass(slots=True)
class RelatedTermQuery:
    """一次"查看某条积累的相关知识"的查询请求（方案 §7.3 P1.5-C）。

    关联证据只来自真实来源事实（同 capture 共现），禁止文本相似或
    embedding 冒充关联；不新增 term_pairs 物化表。
    """

    term_id: int
    limit: int = 5
    current_context_id: int | None = None
    effective_domain: str = "通用"


@dataclass(slots=True)
class RelatedTermItem:
    """一条相关知识：术语 + 共同来源证据 + 展示理由。

    不变量（测试已锁定）：
    - ``shared_source_count`` 按不同共同 capture 计数，同 capture 重试不虚增；
    - 结果不包含查询术语自身；
    - 共同 capture 被删除后，共享计数随之减少，归零即消失；
    - 理由必须可理解：共同来源证据 + 方向事实。
    """

    term: TermRecord
    shared_source_count: int
    shared_domains: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(slots=True)
class RelatedTermPage:
    items: list[RelatedTermItem]


@dataclass(slots=True)
class RecommendationQuery:
    """一次"延伸推荐"查询（方案 §7.3 P1.5-D）。

    候选只来自真实事实：二阶共同来源（bridge）、同学习方向（direction）、
    同领域（domain）、现有 pending 学习建议（tip）。禁止文本相似或
    embedding 冒充证据，不写入正式术语。
    """

    term_id: int
    current_context_id: int | None = None
    effective_domain: str = "通用"
    limit: int = 5


@dataclass(slots=True)
class RecommendationItem:
    """一条延伸推荐：候选 + 类型 + 可理解理由。

    不变量（测试已锁定）：
    - kind ∈ {"bridge", "direction", "domain", "tip"}，按证据强度排序；
    - bridge 不得与目标术语存在直接共现（那是"相关知识"的范畴）；
    - 每条推荐必须携带可理解理由，且允许用户忽略（持久生效）。
    """

    term: TermRecord | None
    kind: str
    reason: str
    tip_id: int | None = None


@dataclass(slots=True)
class RecommendationPage:
    items: list[RecommendationItem]


# 排序封顶常量：高频只证明“多次出现”，不能无限放大价值（方案 §6.6）。
# 私有常量，由排序契约测试固定，不属于外部 interface。
_SORT_SOURCE_CAP = 5
_SORT_VIEW_CAP = 3


@dataclass(slots=True)
class TipQuery:
    status: str = "pending"  # pending | done | ''（全部）
    domain: str = ""
    limit: int = 100


@dataclass(slots=True)
class SaveTermCommand:
    term: str
    chinese_name: str = ""
    beginner_explanation: str = ""
    examples: list[str] = field(default_factory=list)
    domain: str = "通用"
    term_id: int | None = None


@dataclass(slots=True)
class ReviewOutcome:
    term: TermRecord
    interval_days: int
    due_at: str
    ease: float
    lapses: int


class KnowledgeBase:
    """知识脊柱 seam：协调 HistoryStore 的低层存取，隐藏知识规则。"""

    def __init__(self, store: HistoryStore) -> None:
        self.store = store

    # ------------------------------------------------------------------
    # 摄入（ingest）：一次 AI 结果 = 一次知识摄入
    # ------------------------------------------------------------------

    def ingest(self, command: KnowledgeIngest) -> KnowledgeIngestResult:
        term_ids, new_source_links = self.store._ingest_terms(
            command.terms,
            domain=command.domain,
            capture_id=command.capture_id,
        )
        tip_id = 0
        if command.learning_tip.strip() and command.capture_id:
            tip_id = self.store._save_tip_if_absent(
                capture_id=command.capture_id,
                content=command.learning_tip.strip(),
                tip_type=command.tip_type,
                domain=command.domain,
                context_id=command.context_id,
            )
        return KnowledgeIngestResult(
            term_ids=term_ids,
            new_source_links=new_source_links,
            tip_id=tip_id,
        )

    # ------------------------------------------------------------------
    # 术语查询与维护
    # ------------------------------------------------------------------

    def query_terms(self, query: TermQuery) -> TermPage:
        """一次请求返回完整术语页：列表 + 总数 + 领域统计 + 排序理由。

        视图规则（方案 §6.4-§6.6）：
        - ``focus`` / ``current_direction`` 折叠无显式信号的基础词，搜索时绕过；
        - ``current_direction`` 只认 capture 绑定的 exact 方向，不按领域回退；
        - 默认按最新真实学习来源时间排序；无来源术语回退到首次入库时间；
        - ranked 保留可解释分层：显式意图 > 方向相关性 > 来源/查看证据。
        """
        self._validate_term_query(query)
        search = query.query.strip()
        fold_basic = query.view in ("focus", "current_direction") and not search
        scope_current_direction = query.view == "current_direction"
        aggregates = self.store._fetch_term_aggregates(
            search=search,
            domain=query.domain.strip(),
            fold_basic=fold_basic,
            scope_current_direction=scope_current_direction,
            current_context_id=query.current_context_id,
            effective_domain=query.effective_domain,
        )
        if query.since_at:
            aggregates = [
                aggregate
                for aggregate in aggregates
                if self._aggregate_activity_at(aggregate) >= query.since_at
            ]
        total = len(aggregates)
        if query.sort == "ranked":
            self._sort_aggregates(aggregates, query.effective_domain)
        else:
            self._sort_aggregates_by_time(aggregates, oldest=query.sort == "oldest")
        page = aggregates[query.offset : query.offset + query.limit]
        items = [
            TermViewItem(
                term=aggregate.term,
                source_count=aggregate.source_count,
                reasons=self._build_reasons(aggregate, query.effective_domain),
            )
            for aggregate in page
        ]
        domain_counts = self.store._fetch_term_domain_counts(
            search=search,
            fold_basic=fold_basic,
        )
        return TermPage(items=items, total=total, domain_counts=domain_counts)

    def query_accumulation(self, query: AccumulationQuery) -> AccumulationPage:
        """一次请求返回学习页"最近积累"完整数据（方案 §7.3 P1.5-A/B）。

        契约要点：
        - 积累事件 = 术语通过 capture 进入知识库（term_captures），
          排序键 = 该术语最新的真实 capture 时间；
        - 同 capture 的重试 / 追问不产生新的积累项，也不虚增来源数；
        - 每条积累附最近来源（可回看）与展示理由；
        - 理由格式由 P1.5-A 测试冻结：来源证据 + 当前方向事实。
        """
        if query.limit <= 0:
            raise ValueError("limit 必须大于 0")
        aggregates = self.store._fetch_accumulation_aggregates(
            current_context_id=query.current_context_id,
            limit=query.limit,
        )
        return AccumulationPage(
            items=[
                AccumulationItem(
                    term=aggregate.term,
                    latest_capture_id=aggregate.latest_capture_id,
                    latest_capture_at=aggregate.latest_capture_at,
                    latest_capture_title=aggregate.latest_capture_title,
                    source_count=aggregate.source_count,
                    reasons=self._build_accumulation_reasons(
                        aggregate,
                        current_context_id=query.current_context_id,
                        effective_domain=query.effective_domain,
                    ),
                )
                for aggregate in aggregates
            ]
        )

    @staticmethod
    def _build_accumulation_reasons(
        aggregate: AccumulationAggregate,
        *,
        current_context_id: int | None,
        effective_domain: str,
    ) -> tuple[str, ...]:
        reasons = [f"来自 {aggregate.source_count} 条学习记录"]
        if current_context_id is not None and aggregate.exact_count > 0:
            reasons.append(f"当前方向出现 {aggregate.exact_count} 次")
        elif (
            aggregate.term.domain == effective_domain
            and effective_domain != "通用"
            and (current_context_id is None or aggregate.other_count == 0)
        ):
            reasons.append("与当前方向同领域")
        return tuple(reasons)

    def query_related_terms(self, query: RelatedTermQuery) -> RelatedTermPage:
        """返回某条积累的"相关知识"（方案 §7.3 P1.5-C）。

        契约要点：
        - 关联证据 = 与目标术语出现在同一 capture 的其它术语（动态共现，
          不物化 term_pairs）；
        - 排序：共同来源数降序，term.id 升序稳定键；
        - 结果排除目标术语自身；共同 capture 删除后共享计数同步下降；
        - 理由格式由 P1.5-C 测试冻结：共同来源证据 + 方向事实。
        """
        if query.term_id <= 0:
            raise ValueError("term_id 必须大于 0")
        if query.limit <= 0:
            raise ValueError("limit 必须大于 0")
        aggregates = self.store._fetch_related_term_facts(
            term_id=query.term_id,
            limit=query.limit,
        )
        return RelatedTermPage(
            items=[
                RelatedTermItem(
                    term=aggregate.term,
                    shared_source_count=aggregate.shared_source_count,
                    shared_domains=aggregate.shared_domains,
                    reasons=self._build_related_reasons(
                        aggregate, effective_domain=query.effective_domain
                    ),
                )
                for aggregate in aggregates
            ]
        )

    @staticmethod
    def _build_related_reasons(
        aggregate: RelatedAggregate,
        *,
        effective_domain: str,
    ) -> tuple[str, ...]:
        reasons = [f"共同出现在 {aggregate.shared_source_count} 条学习记录"]
        if aggregate.term.domain == effective_domain and effective_domain != "通用":
            reasons.append(f"同属 {effective_domain} 领域")
        return tuple(reasons)

    # ------------------------------------------------------------------
    # P1.5-D 延伸推荐：只认真实来源事实，可忽略，不写正式术语
    # ------------------------------------------------------------------

    _IGNORED_RECOMMENDATION_KEY = "ignored_recommendation_terms"

    def query_recommendations(self, query: RecommendationQuery) -> RecommendationPage:
        """返回与目标积累相关的延伸推荐（方案 §7.3 P1.5-D）。

        候选顺序即证据强度：bridge（二阶共同来源）→ direction（同一学习
        方向但未共现）→ domain（同领域高价值但未共现）→ tip（同领域
        pending 学习建议）。用户已忽略的术语与建议不再出现。
        """
        if query.term_id <= 0:
            raise ValueError("term_id 必须大于 0")
        if query.limit <= 0:
            raise ValueError("limit 必须大于 0")

        ignored = self._ignored_recommendation_term_ids()
        target = self.store.get_term(query.term_id)
        target_domain = (target.domain if target is not None else "") or "通用"

        items: list[RecommendationItem] = []
        for row in self.store._fetch_bridge_recommendations(
            term_id=query.term_id,
            limit=query.limit,
        ):
            if row["term_id"] in ignored:
                continue
            items.append(
                RecommendationItem(
                    term=self.store.get_term(int(row["term_id"])),
                    kind="bridge",
                    reason=(
                        f"通过「{row['bridge_name']}」关联——它与当前知识的学习同源"
                        f"（{row['shared_with_bridge']} 次），值得延伸了解"
                    ),
                )
            )
        if query.current_context_id is not None:
            for row in self.store._fetch_direction_recommendations(
                term_id=query.term_id,
                current_context_id=query.current_context_id,
                limit=query.limit,
            ):
                if row["term_id"] in ignored:
                    continue
                items.append(
                    RecommendationItem(
                        term=self.store.get_term(int(row["term_id"])),
                        kind="direction",
                        reason=(
                            f"同一学习方向（{row['source_count']} 条记录），"
                            "还没在同一来源遇到"
                        ),
                    )
                )
        if target_domain != "通用":
            for row in self.store._fetch_domain_recommendations(
                term_id=query.term_id,
                domain=target_domain,
                limit=query.limit,
            ):
                if row["term_id"] in ignored:
                    continue
                items.append(
                    RecommendationItem(
                        term=self.store.get_term(int(row["term_id"])),
                        kind="domain",
                        reason=f"同属 {target_domain} 领域，值得延伸了解",
                    )
                )
        for tip in self.store._list_learning_tips(
            status="pending",
            domain=target_domain,
            limit=query.limit,
        ):
            items.append(
                RecommendationItem(
                    term=None,
                    kind="tip",
                    reason=f"学习建议：{tip.content}",
                    tip_id=tip.id,
                )
            )
        # 去重（同术语可能命中多类候选，保留最强证据类）
        seen_terms: set[int] = set()
        deduped: list[RecommendationItem] = []
        for item in items:
            if item.term is not None:
                if item.term.id in seen_terms:
                    continue
                seen_terms.add(item.term.id)
            deduped.append(item)
            if len(deduped) >= query.limit:
                break
        return RecommendationPage(items=deduped)

    def ignore_recommendation(
        self,
        term_id: int | None = None,
        tip_id: int | None = None,
    ) -> None:
        """忽略一条推荐：术语进本地忽略列表，建议走状态流转（持久生效）。"""
        if tip_id is not None:
            self.store._set_learning_tip_status(tip_id, "ignored")
            return
        if term_id is None:
            return
        raw = self.store.get_settings().get(self._IGNORED_RECOMMENDATION_KEY, "[]")
        try:
            ids = json.loads(raw)
            if not isinstance(ids, list):
                ids = []
        except (TypeError, json.JSONDecodeError):
            ids = []
        if term_id not in ids:
            ids.append(term_id)
        self.store.set_setting(
            self._IGNORED_RECOMMENDATION_KEY,
            json.dumps(ids, ensure_ascii=False),
        )

    def _ignored_recommendation_term_ids(self) -> set[int]:
        raw = self.store.get_settings().get(self._IGNORED_RECOMMENDATION_KEY, "[]")
        try:
            ids = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return set()
        if not isinstance(ids, list):
            return set()
        return {int(term_id) for term_id in ids if str(term_id).strip().isdigit()}

    @staticmethod
    def _direction_level(aggregate: TermAggregate, effective_domain: str) -> int:
        """0 = exact，1 = domain 回退，2 = 无方向证据。

        domain 回退只允许「来源全为 NULL 或没有来源」的术语；已有其他
        非空 context 来源的术语不能凭同领域冒充当前具体方向（方案 §6.5）。
        """
        if aggregate.exact_count > 0:
            return 0
        if aggregate.other_count == 0 and aggregate.term.domain == effective_domain:
            return 1
        return 2

    @classmethod
    def _sort_aggregates(cls, aggregates: list[TermAggregate], effective_domain: str) -> None:
        """稳定多趟排序：从最弱键到最强键，实现分层可解释排序（方案 §6.6）。"""
        aggregates.sort(key=lambda aggregate: aggregate.term.id)
        aggregates.sort(
            key=lambda aggregate: aggregate.latest_source_at,
            reverse=True,
        )
        aggregates.sort(
            key=lambda aggregate: min(aggregate.term.views, _SORT_VIEW_CAP),
            reverse=True,
        )
        aggregates.sort(
            key=lambda aggregate: min(aggregate.source_count, _SORT_SOURCE_CAP),
            reverse=True,
        )
        aggregates.sort(
            key=lambda aggregate: cls._direction_level(aggregate, effective_domain)
        )
        aggregates.sort(
            key=lambda aggregate: 0
            if (aggregate.term.favorite or aggregate.term.user_edited)
            else 1
        )

    @staticmethod
    def _aggregate_activity_at(aggregate: TermAggregate) -> str:
        """术语最后积累时间；无真实来源时回退到首次入库时间。"""
        return aggregate.latest_source_at or aggregate.term.first_seen_at

    @staticmethod
    def _sort_aggregates_by_time(
        aggregates: list[TermAggregate],
        *,
        oldest: bool,
    ) -> None:
        """按真实学习来源时间排序；手动/无来源术语回退到首次入库时间。"""
        aggregates.sort(key=lambda aggregate: aggregate.term.id)
        aggregates.sort(
            key=KnowledgeBase._aggregate_activity_at,
            reverse=not oldest,
        )

    @staticmethod
    def _build_reasons(aggregate: TermAggregate, effective_domain: str) -> tuple[str, ...]:
        """最多 3 条最有解释力的理由（方案 §6.7），按意图 > 方向 > 证据排序。"""
        term = aggregate.term
        reasons: list[str] = []
        if term.favorite:
            reasons.append("用户已收藏")
        if term.user_edited:
            reasons.append("用户编辑过解释")
        if aggregate.exact_count > 0:
            reasons.append(f"当前方向出现 {aggregate.exact_count} 次")
        elif (
            aggregate.other_count == 0
            and term.domain == effective_domain
            and effective_domain != "通用"
        ):
            reasons.append("与当前方向同领域")
        if aggregate.source_count > 0:
            reasons.append(f"来自 {aggregate.source_count} 条学习记录")
        if term.views > 0:
            reasons.append("用户查看过")
        if not reasons:
            reasons.append(f"已出现 {term.occurrences} 次")
        return tuple(reasons[:3])

    @staticmethod
    def _validate_term_query(query: TermQuery) -> None:
        if query.view not in ("focus", "current_direction", "all"):
            raise ValueError(f"未知术语视图: {query.view!r}")
        if query.sort not in ("latest", "oldest", "ranked"):
            raise ValueError(f"未知术语排序: {query.sort!r}")
        if query.since_at:
            try:
                datetime.fromisoformat(query.since_at)
            except ValueError as exc:
                raise ValueError(f"无效的时间筛选起点: {query.since_at!r}") from exc
        if query.limit <= 0:
            raise ValueError("limit 必须大于 0")
        if query.offset < 0:
            raise ValueError("offset 不能为负")

    @staticmethod
    def _require_browsing_view(query: TermQuery) -> None:
        if query.view not in ("all", "focus"):
            raise ValueError(
                f"视图 {query.view!r} 仅支持 query_terms()，"
                "list_terms/count_terms/term_domain_counts 只处理 all/focus"
            )

    def list_terms(self, query: TermQuery) -> list[TermRecord]:
        self._require_browsing_view(query)
        return self.store.list_terms(
            query=query.query,
            domain=query.domain,
            limit=query.limit,
            offset=query.offset,
            exclude_basic=(query.view == "focus"),
        )

    def count_terms(self, query: TermQuery) -> int:
        self._require_browsing_view(query)
        return self.store.count_terms(
            query=query.query,
            domain=query.domain,
            exclude_basic=(query.view == "focus"),
        )

    def term_domain_counts(self, query: TermQuery) -> list[tuple[str, int]]:
        self._require_browsing_view(query)
        return self.store.term_domain_counts(
            query=query.query,
            exclude_basic=(query.view == "focus"),
        )

    def get_term(self, term_id: int) -> TermRecord | None:
        return self.store.get_term(term_id)

    def list_term_sources(self, term_id: int, limit: int = 30) -> list[CaptureRecord]:
        return self.store._list_term_captures(term_id, limit=limit)

    def save_term(self, command: SaveTermCommand) -> TermRecord:
        term_id = self.store.save_term(
            term=command.term,
            chinese_name=command.chinese_name,
            beginner_explanation=command.beginner_explanation,
            examples=command.examples,
            term_id=command.term_id,
            domain=command.domain,
        )
        record = self.store.get_term(term_id)
        if record is None:
            raise RuntimeError(f"术语保存后无法读取: id={term_id}")
        return record

    def delete_term(self, term_id: int) -> None:
        self.store.delete_term(term_id)

    def set_favorite(self, term_id: int, favorite: bool) -> TermRecord:
        self.store._set_term_favorite(term_id, favorite)
        record = self.store.get_term(term_id)
        if record is None:
            raise RuntimeError(f"术语不存在: id={term_id}")
        return record

    def record_view(self, term_id: int) -> TermRecord:
        self.store._record_term_view(term_id)
        record = self.store.get_term(term_id)
        if record is None:
            raise RuntimeError(f"术语不存在: id={term_id}")
        return record

    # ------------------------------------------------------------------
    # 复习
    # ------------------------------------------------------------------

    def list_due_terms(self, limit: int = 100) -> list[TermRecord]:
        return self.store._list_due_terms(limit=limit)

    def count_due_terms(self) -> int:
        return self.store._count_due_terms()

    def review(self, term_id: int, grade: int) -> ReviewOutcome:
        result = self.store._review_term(term_id, grade)
        record = self.store.get_term(term_id)
        if result is None or record is None:
            raise RuntimeError(f"复习失败: 术语不存在 id={term_id}")
        return ReviewOutcome(
            term=record,
            interval_days=int(result["interval_days"]),
            due_at=str(result["due_at"]),
            ease=float(result["ease"]),
            lapses=int(result["lapses"]),
        )

    # ------------------------------------------------------------------
    # 学习建议
    # ------------------------------------------------------------------

    def list_tips(self, query: TipQuery) -> list[LearningTip]:
        return self.store._list_learning_tips(
            status=query.status,
            domain=query.domain,
            limit=query.limit,
        )

    def count_tips(self, status: str = "pending") -> int:
        return self.store._count_learning_tips(status=status)

    def set_tip_status(self, tip_id: int, status: str) -> LearningTip:
        self.store._set_learning_tip_status(tip_id, status)
        tip = self.store._get_learning_tip(tip_id)
        if tip is None:
            raise RuntimeError(f"学习建议不存在: id={tip_id}")
        return tip
