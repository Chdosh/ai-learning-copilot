"""P1.5-A 学习页积累查询契约与失败测试（docs/personal_knowledge_base_plan.md §7.3）。

这些测试用真实样本锁定"最近积累"的行为契约。P1.5-B 实现聚合查询前，
行为断言全部因 ``query_accumulation`` 的 NotImplementedError 失败（红灯）；
实现后必须全部转绿，且理由格式不得改变（UI 不推导业务事实）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.history_store import HistoryStore
from app.services.knowledge_base import (
    AccumulationQuery,
    KnowledgeBase,
    KnowledgeIngest,
)


def _store(tmp_path: Path) -> HistoryStore:
    return HistoryStore(db_path=tmp_path / "test.db")


def _ingest_term(store: HistoryStore, capture_id: int, term: str, domain: str = "通用") -> None:
    KnowledgeBase(store).ingest(
        KnowledgeIngest(
            capture_id=capture_id,
            terms=[{"term": term, "chinese_name": f"{term} 中文", "domain": domain}],
            domain=domain,
        )
    )


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


def test_contract_types_exist() -> None:
    from app.services.knowledge_base import AccumulationItem, AccumulationPage

    item = AccumulationItem(
        term=None,  # type: ignore[arg-type]
        latest_capture_id=1,
        latest_capture_at="2026-01-01T00:00:00",
        latest_capture_title="标题",
        source_count=1,
        reasons=("来自 1 条学习记录",),
    )
    assert item.latest_capture_id == 1
    page = AccumulationPage(items=[item])
    assert len(page.items) == 1


def test_query_accumulation_rejects_bad_limit(tmp_path: Path) -> None:
    kb = KnowledgeBase(_store(tmp_path))
    with pytest.raises(ValueError):
        kb.query_accumulation(AccumulationQuery(limit=0))


def test_new_capture_produces_accumulation_item(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    capture_id = _capture(store, "Use a transformer model", domain="AI概念")
    _ingest_term(store, capture_id, "transformer", domain="AI概念")

    page = kb.query_accumulation(AccumulationQuery(limit=20))
    assert len(page.items) == 1
    item = page.items[0]
    assert item.term.term == "transformer"
    assert item.latest_capture_id == capture_id
    assert item.latest_capture_title == "Use a transformer model"
    assert item.source_count == 1
    # 每条积累可回看：最近来源必须真实存在
    assert store.get_capture(item.latest_capture_id) is not None


def test_retry_on_same_capture_does_not_inflate(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    capture_id = _capture(store, "token limit exceeded", domain="AI概念")
    _ingest_term(store, capture_id, "token", domain="AI概念")
    _ingest_term(store, capture_id, "token", domain="AI概念")  # 重试 / 追问

    page = kb.query_accumulation(AccumulationQuery(limit=20))
    assert len(page.items) == 1
    assert page.items[0].source_count == 1
    assert page.items[0].latest_capture_id == capture_id


def test_same_term_across_captures_merges_sources(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    first = _capture(store, "first sight of SQL", domain="数据库")
    second = _capture(store, "SQL again", domain="数据库")
    _ingest_term(store, first, "SQL", domain="数据库")
    _ingest_term(store, second, "SQL", domain="数据库")

    page = kb.query_accumulation(AccumulationQuery(limit=20))
    assert len(page.items) == 1
    item = page.items[0]
    assert item.source_count == 2
    assert item.latest_capture_id == second
    assert item.latest_capture_title == "SQL again"


def test_order_follows_real_capture_time_not_term_first_seen(tmp_path: Path) -> None:
    """term 表更新时间不能冒充积累顺序：排序键必须是最新真实来源。"""
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    # 旧积累：术语先入库（first_seen 更早），来源更早
    old_capture = _capture(store, "old source of ORM", domain="数据库")
    _ingest_term(store, old_capture, "ORM", domain="数据库")
    # 新积累：术语后入库，但最新来源更晚 → 必须排在最前
    new_capture = _capture(store, "new sight of Index", domain="数据库")
    _ingest_term(store, new_capture, "Index", domain="数据库")

    page = kb.query_accumulation(AccumulationQuery(limit=20))
    assert [item.term.term for item in page.items] == ["Index", "ORM"]


def test_source_deletion_removes_sole_item(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    capture_id = _capture(store, "fleeting knowledge", domain="编程")
    _ingest_term(store, capture_id, "ephemeral", domain="编程")

    store.delete_capture(capture_id)
    page = kb.query_accumulation(AccumulationQuery(limit=20))
    assert page.items == []


def test_source_deletion_updates_count_and_latest(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    first = _capture(store, "first source", domain="编程")
    second = _capture(store, "second source", domain="编程")
    _ingest_term(store, first, "term", domain="编程")
    _ingest_term(store, second, "term", domain="编程")

    store.delete_capture(second)
    page = kb.query_accumulation(AccumulationQuery(limit=20))
    assert len(page.items) == 1
    item = page.items[0]
    assert item.source_count == 1
    assert item.latest_capture_id == first


def test_reasons_carry_source_evidence_and_direction_facts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kb = KnowledgeBase(store)
    context_id = store.save_context(name="生物", domain="生物", scene="通用")
    exact_capture = _capture(
        store, "CRISPR in gene editing", domain="生物", context_id=context_id
    )
    _ingest_term(store, exact_capture, "CRISPR", domain="生物")
    domain_capture = _capture(store, "plain biology text", domain="生物")
    _ingest_term(store, domain_capture, "genome", domain="生物")
    foreign_capture = _capture(store, "python code", domain="编程")
    _ingest_term(store, foreign_capture, "decorator", domain="编程")

    page = kb.query_accumulation(
        AccumulationQuery(
            limit=20,
            current_context_id=context_id,
            effective_domain="生物",
        )
    )
    by_term = {item.term.term: item for item in page.items}

    assert "来自 1 条学习记录" in by_term["CRISPR"].reasons
    assert any("当前方向" in reason for reason in by_term["CRISPR"].reasons)
    assert "与当前方向同领域" in by_term["genome"].reasons
    # 无方向证据的术语只有来源理由
    assert all("当前方向" not in r and "领域" not in r for r in by_term["decorator"].reasons)
    assert "来自 1 条学习记录" in by_term["decorator"].reasons
