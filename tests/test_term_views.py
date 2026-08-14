"""P1 高价值知识视图：查询契约与真实排序样本（方案 docs/personal_knowledge_base_plan.md §6）。

P1-A 契约测试：定义 `KnowledgeBase.query_terms` 的接口行为。当前 `query_terms`
尚未实现（P1-B），除契约形状外全部用例处于红灯状态，实现后转绿。

覆盖方案 §6.11 验收标准：视图范围、基础词规则、方向三级回退、分层排序与封顶、
来源去重、稳定分页、排序理由、领域统计语义。
"""
from __future__ import annotations

from pathlib import Path

from app.services.history_store import HistoryStore
from app.services.knowledge_base import (
    SORT_SOURCE_CAP,
    SORT_VIEW_CAP,
    KnowledgeBase,
    KnowledgeIngest,
    SaveTermCommand,
    TermPage,
    TermQuery,
    TermViewItem,
)

BASIC = {"if": "如果", "file": "文件", "data": "数据"}
TOPIC = {
    "Polymorphism": "多态",
    "Vector": "向量",
    "HTTP": "超文本传输协议",
    "ORM": "对象关系映射",
}


def _kb(tmp_path: Path) -> KnowledgeBase:
    return KnowledgeBase(HistoryStore(db_path=tmp_path / "test.db"))


def _capture(kb: KnowledgeBase, context_id: int | None = None) -> int:
    return kb.store.save_capture(
        image_path="/t.png",
        source_text="text",
        translation="翻译",
        explanation="解释",
        context_id=context_id,
    )


def _ingest_term(
    kb: KnowledgeBase,
    term: str,
    domain: str = "通用",
    capture_id: int | None = None,
    chinese_name: str = "",
) -> int:
    result = kb.ingest(
        KnowledgeIngest(
            capture_id=capture_id,
            terms=[{"term": term, "chinese_name": chinese_name or term}],
            domain=domain,
        )
    )
    return result.term_ids[0]


def _ingest_basic_many_times(kb: KnowledgeBase, term: str, times: int) -> int:
    term_id = 0
    for _ in range(times):
        capture_id = _capture(kb)
        term_id = _ingest_term(kb, term, domain="通用", capture_id=capture_id)
    return term_id


# ---------------------------------------------------------------------------
# 契约形状
# ---------------------------------------------------------------------------


def test_query_contract_defaults() -> None:
    query = TermQuery()
    assert query.view == "focus"
    assert query.limit == 50
    assert query.current_context_id is None
    assert query.effective_domain == "通用"


def test_query_terms_returns_term_page(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    _ingest_term(kb, "Vector", domain="编程")
    page = kb.query_terms(TermQuery())
    assert isinstance(page, TermPage)
    assert len(page.items) == 1
    item = page.items[0]
    assert isinstance(item, TermViewItem)
    assert item.direction_level in ("exact", "domain", "none")
    assert item.rank_tier in ("intent", "direction", "evidence", "base")
    assert item.reasons


# ---------------------------------------------------------------------------
# 基础词规则（方案 §6.4 / 验收 6.11）
# ---------------------------------------------------------------------------


def test_all_view_returns_basic_words_without_signals(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    _ingest_basic_many_times(kb, "if", times=3)

    page = kb.query_terms(TermQuery(view="all"))
    assert {item.term.term for item in page.items} == {"if"}


def test_focus_hides_basic_words_without_signals_even_high_occurrence(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    _ingest_basic_many_times(kb, "file", times=10)
    _ingest_term(kb, "Vector", domain="编程")

    page = kb.query_terms(TermQuery(view="focus"))
    assert {item.term.term for item in page.items} == {"Vector"}


def test_focus_shows_basic_with_favorite_signal(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    term_id = _ingest_basic_many_times(kb, "if", times=1)
    kb.set_favorite(term_id, favorite=True)

    page = kb.query_terms(TermQuery(view="focus"))
    assert {item.term.term for item in page.items} == {"if"}


def test_focus_shows_basic_with_user_edited_signal(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    term_id = _ingest_basic_many_times(kb, "file", times=1)
    kb.save_term(
        SaveTermCommand(
            term_id=term_id,
            term="file",
            chinese_name="我自己的笔记",
            domain="通用",
        )
    )

    page = kb.query_terms(TermQuery(view="focus"))
    assert {item.term.term for item in page.items} == {"file"}


def test_focus_shows_basic_with_view_signal(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    term_id = _ingest_basic_many_times(kb, "data", times=1)
    kb.record_view(term_id)

    page = kb.query_terms(TermQuery(view="focus"))
    assert {item.term.term for item in page.items} == {"data"}


def test_search_finds_basic_words_without_signals(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    _ingest_basic_many_times(kb, "if", times=5)

    page = kb.query_terms(TermQuery(view="focus", query="if"))
    assert {item.term.term for item in page.items} == {"if"}


# ---------------------------------------------------------------------------
# 分层排序（方案 §6.6 / 验收 6.11）
# ---------------------------------------------------------------------------


def test_favorited_sorts_above_higher_occurrence_term(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    favorited_id = _ingest_term(kb, "Vector", domain="编程")
    kb.set_favorite(favorited_id, favorite=True)
    for _ in range(SORT_SOURCE_CAP):
        capture_id = _capture(kb)
        _ingest_term(kb, "Polymorphism", domain="编程", capture_id=capture_id)

    page = kb.query_terms(TermQuery(view="focus"))
    assert [item.term.term for item in page.items][0] == "Vector"


def test_direction_levels_rank_exact_above_domain_above_none(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    context_id = kb.store.save_context(name="深度学习", domain="编程", scene="通用")
    other_context = kb.store.save_context(name="网络工程", domain="网络", scene="通用")

    _ingest_term(kb, "Polymorphism", domain="编程", capture_id=_capture(kb, context_id))
    _ingest_term(kb, "Vector", domain="编程", capture_id=_capture(kb, None))
    _ingest_term(kb, "HTTP", domain="网络", capture_id=_capture(kb, other_context))

    page = kb.query_terms(
        TermQuery(view="focus", current_context_id=context_id, effective_domain="编程")
    )
    assert [item.term.term for item in page.items] == ["Polymorphism", "Vector", "HTTP"]
    levels = {item.term.term: item.direction_level for item in page.items}
    assert levels == {"Polymorphism": "exact", "Vector": "domain", "HTTP": "none"}


# ---------------------------------------------------------------------------
# current_direction 视图范围（方案 §6.5 / 验收 6.11）
# ---------------------------------------------------------------------------


def test_current_direction_view_scopes_to_exact_and_legacy_domain(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    context_id = kb.store.save_context(name="深度学习", domain="编程", scene="通用")
    other_context = kb.store.save_context(name="网络工程", domain="网络", scene="通用")

    exact_id = _ingest_term(kb, "Polymorphism", domain="编程", capture_id=_capture(kb, context_id))
    legacy_id = _ingest_term(kb, "Vector", domain="编程", capture_id=_capture(kb, None))
    impostor_id = _ingest_term(kb, "ORM", domain="编程", capture_id=_capture(kb, other_context))
    unrelated_id = _ingest_term(kb, "HTTP", domain="网络", capture_id=_capture(kb, other_context))

    page = kb.query_terms(
        TermQuery(view="current_direction", current_context_id=context_id, effective_domain="编程")
    )
    included = {item.term.id for item in page.items}
    assert exact_id in included
    assert legacy_id in included
    assert impostor_id not in included  # 有非空其他 context 来源，不能凭同 domain 冒充
    assert unrelated_id not in included


def test_current_direction_without_context_filters_by_effective_domain(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    context_id = kb.store.save_context(name="深度学习", domain="编程", scene="通用")
    _ingest_term(kb, "Polymorphism", domain="编程", capture_id=_capture(kb, context_id))
    _ingest_term(kb, "Vector", domain="编程", capture_id=_capture(kb, None))
    _ingest_term(kb, "HTTP", domain="网络", capture_id=_capture(kb, None))

    page = kb.query_terms(
        TermQuery(view="current_direction", current_context_id=None, effective_domain="编程")
    )
    assert {item.term.term for item in page.items} == {"Polymorphism", "Vector"}


# ---------------------------------------------------------------------------
# 来源证据与封顶（方案 §4.3 / §6.6 / 验收 6.11）
# ---------------------------------------------------------------------------


def test_source_count_uses_distinct_captures_not_retries(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    capture_id = _capture(kb)
    _ingest_term(kb, "Vector", domain="编程", capture_id=capture_id)
    _ingest_term(kb, "Vector", domain="编程", capture_id=capture_id)  # 同一 capture 重试

    page = kb.query_terms(TermQuery())
    assert page.items[0].source_count == 1


def test_source_and_view_caps_bound_ranking(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    for _ in range(20):
        _ingest_term(kb, "Polymorphism", domain="编程", capture_id=_capture(kb))
    capped_id = 0
    for _ in range(SORT_SOURCE_CAP + 1):
        capped_id = _ingest_term(kb, "Vector", domain="编程", capture_id=_capture(kb))
    for _ in range(SORT_VIEW_CAP + 1):
        kb.record_view(capped_id)

    page = kb.query_terms(TermQuery(view="focus"))
    order = [item.term.term for item in page.items]
    # 来源数都超过封顶后不再拉开差距，查看次数决定顺序
    assert order[0] == "Vector"
    assert order[1] == "Polymorphism"


# ---------------------------------------------------------------------------
# 分页与理由（方案 §6.6 / §6.7 / 验收 6.11）
# ---------------------------------------------------------------------------


def test_pagination_stable_and_complete(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    for name in sorted(TOPIC):
        _ingest_term(kb, name, domain="编程")

    first = kb.query_terms(TermQuery(view="all", limit=2, offset=0))
    second = kb.query_terms(TermQuery(view="all", limit=2, offset=2))
    third = kb.query_terms(TermQuery(view="all", limit=2, offset=4))
    paged = first.items + second.items + third.items
    ids = [item.term.id for item in paged]
    assert len(ids) == len(set(ids))  # 无重复
    assert len(paged) == 4  # 无跳项


def test_focus_items_carry_reasons(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    context_id = kb.store.save_context(name="深度学习", domain="编程", scene="通用")
    favorited_id = _ingest_term(kb, "Polymorphism", domain="编程", capture_id=_capture(kb, context_id))
    kb.set_favorite(favorited_id, favorite=True)
    _ingest_term(kb, "Vector", domain="编程", capture_id=_capture(kb, None))

    page = kb.query_terms(
        TermQuery(view="focus", current_context_id=context_id, effective_domain="编程")
    )
    by_term = {item.term.term: item for item in page.items}
    assert any("收藏" in reason for reason in by_term["Polymorphism"].reasons)
    assert any("当前方向" in reason for reason in by_term["Polymorphism"].reasons)
    for item in page.items:
        assert item.reasons, f"{item.term.term} 缺少排序理由"


# ---------------------------------------------------------------------------
# 领域统计语义（方案 §6.3）
# ---------------------------------------------------------------------------


def test_domain_counts_ignore_domain_filter_while_items_do_not(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    _ingest_term(kb, "Vector", domain="编程")
    _ingest_term(kb, "ORM", domain="数据库")

    page = kb.query_terms(TermQuery(view="all", domain="编程"))
    assert [item.term.term for item in page.items] == ["Vector"]
    assert page.total == 1
    counts = dict(page.domain_counts)
    assert counts == {"编程": 1, "数据库": 1}
