"""P1.5-C 证据型相关知识契约测试（docs/personal_knowledge_base_plan.md §7.3）。

锁定同 capture 共现的行为契约：证据只来自真实来源事实，不物化 term_pairs，
共同 capture 删除后共享计数同步下降，理由格式冻结。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.history_store import HistoryStore
from app.services.knowledge_base import (
    KnowledgeBase,
    KnowledgeIngest,
    RelatedTermQuery,
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


def test_query_related_terms_validation(tmp_path: Path) -> None:
    kb = KnowledgeBase(_store(tmp_path))
    with pytest.raises(ValueError):
        kb.query_related_terms(RelatedTermQuery(term_id=0))
    with pytest.raises(ValueError):
        kb.query_related_terms(RelatedTermQuery(term_id=1, limit=0))


def test_shared_capture_links_terms_with_reasons(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    capture_id = _capture(store, "overfitting and regularization", domain="AI概念")
    _ingest(store, capture_id, "overfitting", domain="AI概念")
    _ingest(store, capture_id, "regularization", domain="AI概念")

    page = kb.query_related_terms(
        RelatedTermQuery(term_id=_term_id(store, "overfitting"), limit=5)
    )
    assert [item.term.term for item in page.items] == ["regularization"]
    item = page.items[0]
    assert item.shared_source_count == 1
    assert "AI概念" in item.shared_domains
    assert "共同出现在 1 条学习记录" in item.reasons


def test_self_is_never_related(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    capture_id = _capture(store, "solo term", domain="编程")
    _ingest(store, capture_id, "solo", domain="编程")

    page = kb.query_related_terms(RelatedTermQuery(term_id=_term_id(store, "solo")))
    assert page.items == []


def test_shared_count_orders_and_counts_across_captures(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    first = _capture(store, "first shared source", domain="编程")
    second = _capture(store, "second shared source", domain="编程")
    third = _capture(store, "weak link only", domain="编程")
    _ingest(store, first, "target", domain="编程")
    _ingest(store, second, "target", domain="编程")
    _ingest(store, third, "target", domain="编程")
    _ingest(store, first, "strong", domain="编程")
    _ingest(store, second, "strong", domain="编程")
    _ingest(store, third, "weak", domain="编程")

    page = kb.query_related_terms(RelatedTermQuery(term_id=_term_id(store, "target")))
    names = [item.term.term for item in page.items]
    assert names == ["strong", "weak"]
    assert page.items[0].shared_source_count == 2
    assert page.items[1].shared_source_count == 1
    # 多方向事实进入 shared_domains（这里同为编程）
    assert page.items[0].shared_domains == ("编程",)


def test_retry_on_same_capture_does_not_inflate_shared_count(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    capture_id = _capture(store, "shared source", domain="编程")
    _ingest(store, capture_id, "target", domain="编程")
    _ingest(store, capture_id, "peer", domain="编程")
    _ingest(store, capture_id, "peer", domain="编程")  # 重试 / 追问

    page = kb.query_related_terms(RelatedTermQuery(term_id=_term_id(store, "target")))
    assert len(page.items) == 1
    assert page.items[0].shared_source_count == 1


def test_deleting_shared_capture_reduces_count(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    first = _capture(store, "first shared source", domain="编程")
    second = _capture(store, "second shared source", domain="编程")
    _ingest(store, first, "target", domain="编程")
    _ingest(store, second, "target", domain="编程")
    _ingest(store, first, "peer", domain="编程")
    _ingest(store, second, "peer", domain="编程")

    store.delete_capture(second)
    page = kb.query_related_terms(RelatedTermQuery(term_id=_term_id(store, "target")))
    assert len(page.items) == 1
    assert page.items[0].shared_source_count == 1

    store.delete_capture(first)
    page = kb.query_related_terms(RelatedTermQuery(term_id=_term_id(store, "target")))
    assert page.items == []  # 共同来源归零即消失


def test_shared_domains_span_multiple_domains(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    # capture 的领域不同，但术语行唯一（UNIQUE(term, domain)）
    first = _capture(store, "vector in code", domain="编程")
    second = _capture(store, "vector in biology", domain="生物")
    _ingest(store, first, "vector", domain="编程")
    _ingest(store, second, "vector", domain="编程")
    _ingest(store, first, "matrix", domain="编程")
    _ingest(store, second, "matrix", domain="编程")

    page = kb.query_related_terms(
        RelatedTermQuery(
            term_id=_term_id(store, "vector"),
            effective_domain="编程",
        )
    )
    assert len(page.items) == 1
    assert page.items[0].shared_source_count == 2
    assert set(page.items[0].shared_domains) == {"编程", "生物"}
    # 同领域事实进入理由
    assert "同属 编程 领域" in page.items[0].reasons


def test_unknown_term_returns_empty(tmp_path: Path) -> None:
    kb = KnowledgeBase(_store(tmp_path))
    page = kb.query_related_terms(RelatedTermQuery(term_id=99999))
    assert page.items == []
