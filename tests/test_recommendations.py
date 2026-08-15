"""P1.5-D 延伸推荐契约测试（docs/personal_knowledge_base_plan.md §7.3）。

锁定候选来源（只认真实来源事实）、证据强度排序、理由格式与持久忽略；
不接 embedding、不写入正式术语。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.history_store import HistoryStore
from app.services.knowledge_base import (
    KnowledgeBase,
    KnowledgeIngest,
    RecommendationQuery,
    TipQuery,
)


def _store(tmp_path: Path) -> HistoryStore:
    return HistoryStore(db_path=tmp_path / "test.db")


def _capture(
    store: HistoryStore,
    source_text: str,
    domain: str = "通用",
    context_id: int | None = None,
) -> int:
    return store.save_capture(
        image_path="",
        source_text=source_text,
        translation="",
        explanation="",
        domain=domain,
        context_id=context_id,
    )


def _ingest(store: HistoryStore, capture_id: int, term: str, domain: str = "通用") -> None:
    KnowledgeBase(store).ingest(
        KnowledgeIngest(
            capture_id=capture_id,
            terms=[{"term": term, "chinese_name": f"{term} 中文", "domain": domain}],
            domain=domain,
        )
    )


def _term_id(store: HistoryStore, term: str) -> int:
    match = next(item for item in store.list_terms() if item.term == term)
    return match.id


def test_query_recommendations_validation(tmp_path: Path) -> None:
    kb = KnowledgeBase(_store(tmp_path))
    with pytest.raises(ValueError):
        kb.query_recommendations(RecommendationQuery(term_id=0))
    with pytest.raises(ValueError):
        kb.query_recommendations(RecommendationQuery(term_id=1, limit=0))


def test_bridge_recommendation_via_second_hop(tmp_path: Path) -> None:
    """termA-termB 共现于 capture1，termB-termC 共现于 capture2，A-C 无直接共现 → 推荐 C。"""
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    first = _capture(store, "termA with termB", domain="AI概念")
    second = _capture(store, "termB with termC", domain="AI概念")
    _ingest(store, first, "termA", domain="AI概念")
    _ingest(store, first, "termB", domain="AI概念")
    _ingest(store, second, "termB", domain="AI概念")
    _ingest(store, second, "termC", domain="AI概念")

    page = kb.query_recommendations(
        RecommendationQuery(term_id=_term_id(store, "termA"), limit=5)
    )
    bridge_items = [item for item in page.items if item.kind == "bridge"]
    assert bridge_items
    assert bridge_items[0].term is not None
    assert bridge_items[0].term.term == "termC"
    assert "termB" in bridge_items[0].reason


def test_direct_co_occurrence_is_not_bridge_recommendation(tmp_path: Path) -> None:
    """直接共现属于"相关知识"，绝不能作为延伸推荐重复出现。"""
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    capture_id = _capture(store, "termA with termC directly", domain="AI概念")
    _ingest(store, capture_id, "termA", domain="AI概念")
    _ingest(store, capture_id, "termC", domain="AI概念")

    page = kb.query_recommendations(
        RecommendationQuery(term_id=_term_id(store, "termA"), limit=5)
    )
    assert all(item.kind != "bridge" for item in page.items)


def test_direction_recommendation_without_direct_link(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    context_id = store.save_context(name="生物", domain="生物", scene="通用")
    shared = _capture(store, "termA alone", domain="生物", context_id=context_id)
    other = _capture(store, "termD in same direction", domain="生物", context_id=context_id)
    _ingest(store, shared, "termA", domain="生物")
    _ingest(store, other, "termD", domain="生物")

    page = kb.query_recommendations(
        RecommendationQuery(
            term_id=_term_id(store, "termA"),
            current_context_id=context_id,
            effective_domain="生物",
            limit=10,
        )
    )
    direction_items = [item for item in page.items if item.kind == "direction"]
    assert direction_items
    assert direction_items[0].term.term == "termD"
    assert "同一学习方向" in direction_items[0].reason


def test_no_direction_recommendation_without_context(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    capture_id = _capture(store, "termA in context", domain="生物", context_id=1)
    _ingest(store, capture_id, "termA", domain="生物")

    page = kb.query_recommendations(
        RecommendationQuery(term_id=_term_id(store, "termA"), current_context_id=None)
    )
    assert all(item.kind != "direction" for item in page.items)


def test_domain_recommendation_prefers_valuable_terms(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    capture_id = _capture(store, "termA source", domain="AI概念")
    _ingest(store, capture_id, "termA", domain="AI概念")
    # 同领域两个术语：收藏的优先
    low_id = store.save_term(term="plain", chinese_name="普通", domain="AI概念")
    high_id = store.save_term(term="premium", chinese_name="优质", domain="AI概念")
    kb.set_favorite(high_id, favorite=True)

    page = kb.query_recommendations(
        RecommendationQuery(term_id=_term_id(store, "termA"), limit=10)
    )
    domain_items = [item for item in page.items if item.kind == "domain"]
    assert domain_items
    assert domain_items[0].term.term == "premium"
    assert "同属 AI概念 领域" in domain_items[0].reason
    assert domain_items[0].term.id == high_id
    assert low_id != high_id


def test_tip_recommendation_from_pending_tips(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    capture_id = _capture(store, "termA source", domain="AI概念")
    _ingest(store, capture_id, "termA", domain="AI概念")
    kb.ingest(
        KnowledgeIngest(
            capture_id=capture_id,
            terms=[],
            learning_tip="延伸概念：正则化——防止过拟合",
            domain="AI概念",
        )
    )

    page = kb.query_recommendations(
        RecommendationQuery(term_id=_term_id(store, "termA"), limit=10)
    )
    tip_items = [item for item in page.items if item.kind == "tip"]
    assert tip_items
    assert "正则化" in tip_items[0].reason
    assert tip_items[0].tip_id is not None


def test_ignored_recommendation_is_persistent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    first = _capture(store, "termA with termB", domain="AI概念")
    second = _capture(store, "termB with termC", domain="AI概念")
    _ingest(store, first, "termA", domain="AI概念")
    _ingest(store, first, "termB", domain="AI概念")
    _ingest(store, second, "termB", domain="AI概念")
    _ingest(store, second, "termC", domain="AI概念")
    bridge_id = _term_id(store, "termC")

    before = kb.query_recommendations(
        RecommendationQuery(term_id=_term_id(store, "termA"), limit=10)
    )
    assert any(item.term and item.term.id == bridge_id for item in before.items)

    kb.ignore_recommendation(term_id=bridge_id)
    after = kb.query_recommendations(
        RecommendationQuery(term_id=_term_id(store, "termA"), limit=10)
    )
    assert all(
        item.term is None or item.term.id != bridge_id for item in after.items
    )

    # 新实例（模拟重启）依然生效
    reopened = KnowledgeBase(HistoryStore(db_path=store.db_path))
    page = reopened.query_recommendations(
        RecommendationQuery(term_id=_term_id(store, "termA"), limit=10)
    )
    assert all(
        item.term is None or item.term.id != bridge_id for item in page.items
    )


def test_ignored_tip_recommendation_disappears(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    capture_id = _capture(store, "termA source", domain="AI概念")
    _ingest(store, capture_id, "termA", domain="AI概念")
    kb.ingest(
        KnowledgeIngest(
            capture_id=capture_id,
            terms=[],
            learning_tip="延伸概念：正则化——防止过拟合",
            domain="AI概念",
        )
    )
    tip_id = next(item.id for item in kb.list_tips(TipQuery(status="pending")))

    kb.ignore_recommendation(tip_id=tip_id)
    page = kb.query_recommendations(
        RecommendationQuery(term_id=_term_id(store, "termA"), limit=10)
    )
    assert all(item.kind != "tip" for item in page.items)


def test_evidence_order_bridge_before_direction_before_domain(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    context_id = store.save_context(name="生物", domain="生物", scene="通用")
    first = _capture(store, "termA with termB", domain="生物", context_id=context_id)
    second = _capture(store, "termB with termC", domain="生物", context_id=context_id)
    _ingest(store, first, "termA", domain="生物")
    _ingest(store, first, "termB", domain="生物")
    _ingest(store, second, "termB", domain="生物")
    _ingest(store, second, "termC", domain="生物")
    direction_capture = _capture(store, "termD alone", domain="生物", context_id=context_id)
    _ingest(store, direction_capture, "termD", domain="生物")

    page = kb.query_recommendations(
        RecommendationQuery(
            term_id=_term_id(store, "termA"),
            current_context_id=context_id,
            effective_domain="生物",
            limit=10,
        )
    )
    kinds = [item.kind for item in page.items]
    strength = {"bridge": 0, "direction": 1, "domain": 2, "tip": 3}
    assert kinds == sorted(kinds, key=lambda kind: strength[kind])
    assert "bridge" in kinds
    assert "direction" in kinds
