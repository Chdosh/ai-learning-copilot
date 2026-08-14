"""个人知识库的单一外部 interface（知识脊柱）。

所有术语、术语来源、学习建议与复习行为都通过 ``KnowledgeBase`` 进入系统；
调用方不再需要知道表级写入顺序、去重、回链与调度字段的拼装规则。

设计依据：``docs/knowledge_spine_design.md``。禁止依赖 PySide6、AIClient、OCR。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.history_store import (
    CaptureRecord,
    HistoryStore,
    LearningTip,
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
    view: str = "all"  # all | focus（focus = 折叠无行为信号的 basic 词）
    query: str = ""
    domain: str = ""
    limit: int = 200
    offset: int = 0


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

    def list_terms(self, query: TermQuery) -> list[TermRecord]:
        return self.store.list_terms(
            query=query.query,
            domain=query.domain,
            limit=query.limit,
            offset=query.offset,
            exclude_basic=(query.view == "focus"),
        )

    def count_terms(self, query: TermQuery) -> int:
        return self.store.count_terms(
            query=query.query,
            domain=query.domain,
            exclude_basic=(query.view == "focus"),
        )

    def term_domain_counts(self, query: TermQuery) -> list[tuple[str, int]]:
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
