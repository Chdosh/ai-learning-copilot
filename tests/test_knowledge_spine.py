"""知识脊柱（knowledge spine）测试：来源完整、重试幂等、方向事实、复习事实与 interface 收口。

与 test_knowledge_base.py 的互补：这里锁定知识脊柱设计（docs/knowledge_spine_design.md）
的数据不变量与 KnowledgeBase 外部 interface；前者保留术语治理规则的存储级验证。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from app.services.history_store import HistoryStore
from app.services.knowledge_base import (
    KnowledgeBase,
    KnowledgeIngest,
    SaveTermCommand,
    TermQuery,
    TipQuery,
)


def _store(tmp_path: Path, db_name: str = "test.db") -> HistoryStore:
    return HistoryStore(db_path=tmp_path / db_name)


def _kb(tmp_path: Path) -> KnowledgeBase:
    return KnowledgeBase(_store(tmp_path))


# ---------------------------------------------------------------------------
# 阶段 A：术语出现事实（跨 capture 来源完整、同一 capture 重试幂等）
# ---------------------------------------------------------------------------


def test_same_term_across_captures_keeps_all_source_links(tmp_path: Path) -> None:
    store = _store(tmp_path)
    c1 = store.save_capture(image_path="/t1.png", source_text="use vector", translation="a", explanation="e")
    c2 = store.save_capture(image_path="/t2.png", source_text="vector again", translation="b", explanation="e")

    store._upsert_terms([{"term": "vector", "chinese_name": "向量"}], domain="编程", capture_id=c1)
    store._upsert_terms([{"term": "vector", "chinese_name": "向量"}], domain="编程", capture_id=c2)

    term = store.list_terms()[0]
    sources = store._list_term_captures(term.id)
    assert {capture.id for capture in sources} == {c1, c2}
    assert term.occurrences == 2


def test_retry_same_capture_does_not_inflate_sources_or_occurrences(tmp_path: Path) -> None:
    store = _store(tmp_path)
    c1 = store.save_capture(image_path="/t1.png", source_text="use vector", translation="a", explanation="e")

    store._upsert_terms([{"term": "vector", "chinese_name": "向量"}], domain="编程", capture_id=c1)
    store._upsert_terms([{"term": "vector", "chinese_name": "向量"}], domain="编程", capture_id=c1)

    term = store.list_terms()[0]
    sources = store._list_term_captures(term.id)
    assert [capture.id for capture in sources] == [c1]
    assert term.occurrences == 1


def test_upsert_without_capture_keeps_legacy_occurrence_counting(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store._upsert_terms([{"term": "vector", "chinese_name": "向量"}], domain="编程")
    store._upsert_terms([{"term": "vector", "chinese_name": "向量"}], domain="编程")
    term = store.list_terms()[0]
    assert term.occurrences == 2


def test_new_source_link_increments_occurrence_exactly_once(tmp_path: Path) -> None:
    store = _store(tmp_path)
    c1 = store.save_capture(image_path="/t1.png", source_text="a", translation="b", explanation="e")
    c2 = store.save_capture(image_path="/t2.png", source_text="c", translation="d", explanation="e")

    store._upsert_terms([{"term": "SQL", "chinese_name": "结构化查询语言"}], domain="数据库", capture_id=c1)
    store._upsert_terms([{"term": "SQL", "chinese_name": "结构化查询语言"}], domain="数据库", capture_id=c2)

    term = store.list_terms()[0]
    assert term.occurrences == 2
    assert term.review_count == 2


# ---------------------------------------------------------------------------
# 阶段 B：方向事实（captures.context_id）与复习事实（review_events）
# ---------------------------------------------------------------------------


def test_new_capture_stores_context_id_when_provided(tmp_path: Path) -> None:
    store = _store(tmp_path)
    context_id = store.save_context(name="深度学习", domain="AI概念", scene="通用")
    capture_id = store.save_capture(
        image_path="/t.png",
        source_text="text",
        translation="翻译",
        explanation="解释",
        context_id=context_id,
    )
    with store._connect() as conn:
        row = conn.execute("SELECT context_id FROM captures WHERE id = ?", (capture_id,)).fetchone()
    assert row["context_id"] == context_id


def test_capture_context_id_is_null_when_not_provided(tmp_path: Path) -> None:
    store = _store(tmp_path)
    capture_id = store.save_capture(image_path="/t.png", source_text="text", translation="翻译", explanation="解释")
    with store._connect() as conn:
        row = conn.execute("SELECT context_id FROM captures WHERE id = ?", (capture_id,)).fetchone()
    assert row["context_id"] is None


def test_update_capture_does_not_overwrite_context_id(tmp_path: Path) -> None:
    store = _store(tmp_path)
    context_id = store.save_context(name="深度学习", domain="AI概念", scene="通用")
    capture_id = store.save_capture(
        image_path="/t.png",
        source_text="text",
        translation="旧",
        explanation="e",
        context_id=context_id,
    )
    store.update_capture(capture_id, translation="新", explanation="e")
    with store._connect() as conn:
        row = conn.execute("SELECT context_id FROM captures WHERE id = ?", (capture_id,)).fetchone()
    assert row["context_id"] == context_id


def test__review_term_writes_exactly_one_review_event(tmp_path: Path) -> None:
    store = _store(tmp_path)
    term_id = store.save_term(term="SVD", chinese_name="奇异值分解", domain="AI概念")
    store._toggle_term_favorite(term_id)

    store._review_term(term_id, grade=2)

    with store._connect() as conn:
        rows = conn.execute("SELECT * FROM review_events WHERE term_id = ?", (term_id,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["grade"] == 2
    assert rows[0]["term_domain"] == "AI概念"
    assert rows[0]["interval_days"] == 1
    assert rows[0]["reviewed_at"]


def test_review_event_and_srs_snapshot_are_atomic(tmp_path: Path) -> None:
    store = _store(tmp_path)
    term_id = store.save_term(term="SVD", chinese_name="奇异值分解", domain="AI概念")
    store._toggle_term_favorite(term_id)

    before = store.list_terms()[0]
    try:
        with store._connect() as conn:
            conn.execute(
                """
                UPDATE terms SET ease = 99, interval_days = 99, due_at = '2099-01-01T00:00:00'
                WHERE id = ?
                """,
                (term_id,),
            )
            conn.execute(
                "INSERT INTO review_events(term_id, grade, reviewed_at, interval_days, ease, lapses, term_domain) "
                "VALUES (?, 2, '2099-01-01T00:00:00', 99, 99, 0, 'AI概念')",
                (term_id,),
            )
            raise RuntimeError("simulated failure before commit")
    except RuntimeError:
        pass

    term = store.list_terms()[0]
    assert term.ease == before.ease
    assert term.interval_days == before.interval_days
    assert term.due_at == before.due_at
    with store._connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM review_events WHERE term_id = ?", (term_id,)).fetchone()[0]
    assert count == 0


def test_delete_term_cleans_review_events(tmp_path: Path) -> None:
    store = _store(tmp_path)
    term_id = store.save_term(term="SVD", chinese_name="奇异值分解")
    store._toggle_term_favorite(term_id)
    store._review_term(term_id, grade=1)
    store.delete_term(term_id)
    with store._connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM review_events WHERE term_id = ?", (term_id,)).fetchone()[0]
    assert count == 0


def test_delete_capture_keeps_terms_with_remaining_sources(tmp_path: Path) -> None:
    store = _store(tmp_path)
    c1 = store.save_capture(image_path="/t1.png", source_text="vector", translation="a", explanation="e")
    c2 = store.save_capture(image_path="/t2.png", source_text="vector", translation="b", explanation="e")
    store._upsert_terms([{"term": "vector", "chinese_name": "向量"}], domain="编程", capture_id=c1)
    store._upsert_terms([{"term": "vector", "chinese_name": "向量"}], domain="编程", capture_id=c2)

    store.delete_capture(c1)

    term = store.list_terms()[0]
    sources = store._list_term_captures(term.id)
    assert [capture.id for capture in sources] == [c2]
    assert term.occurrences == 2  # 事实已发生，不因来源删除重算快照


def test_legacy_schema_upgrades_and_reinit_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE captures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            image_path TEXT NOT NULL,
            source_text TEXT NOT NULL DEFAULT '',
            translation TEXT NOT NULL DEFAULT '',
            explanation TEXT NOT NULL DEFAULT '',
            app_name TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE terms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT NOT NULL,
            domain TEXT NOT NULL DEFAULT '通用',
            chinese_name TEXT NOT NULL DEFAULT '',
            beginner_explanation TEXT NOT NULL DEFAULT '',
            examples TEXT NOT NULL DEFAULT '[]',
            first_seen_at TEXT NOT NULL,
            review_count INTEGER NOT NULL DEFAULT 0,
            favorite INTEGER NOT NULL DEFAULT 0,
            UNIQUE(term, domain)
        )
        """
    )
    conn.execute("INSERT INTO captures(created_at, image_path, source_text) VALUES ('2026-01-01T00:00:00', '/old.png', 'old text')")
    conn.execute("INSERT INTO terms(term, domain, first_seen_at, review_count) VALUES ('legacy', '编程', '2026-01-01T00:00:00', 3)")
    conn.commit()
    conn.close()

    store = HistoryStore(db_path=db_path)

    with store._connect() as conn:
        capture_cols = {row["name"] for row in conn.execute("PRAGMA table_info(captures)")}
        assert "context_id" in capture_cols
        old = conn.execute("SELECT context_id FROM captures").fetchall()
        assert all(row["context_id"] is None for row in old)
        event_cols = {row["name"] for row in conn.execute("PRAGMA table_info(review_events)")}
        assert {"id", "term_id", "grade", "reviewed_at", "interval_days", "ease", "lapses", "term_domain"} <= event_cols

    # 重复初始化幂等
    store.initialize()
    with store._connect() as conn:
        capture_cols = {row["name"] for row in conn.execute("PRAGMA table_info(captures)")}
        assert "context_id" in capture_cols

    # 迁移把历史 review_count 视为出现次数快照，不回填来源
    term = store.list_terms()[0]
    assert term.term == "legacy"
    assert term.occurrences == 3


def test_delete_context_keeps_captures_without_context_id_backfill(tmp_path: Path) -> None:
    store = _store(tmp_path)
    context_id = store.save_context(name="深度学习", domain="AI概念", scene="通用")
    capture_id = store.save_capture(
        image_path="/t.png", source_text="text", translation="翻译", explanation="解释", context_id=context_id
    )
    assert store.delete_context(context_id)
    capture = store.get_capture(capture_id)
    assert capture is not None
    assert capture.domain == "通用"


# ---------------------------------------------------------------------------
# 阶段 C：KnowledgeBase ingest（术语 + 回链 + tip 一次收口）
# ---------------------------------------------------------------------------


def _capture_for_ingest(kb: KnowledgeBase) -> int:
    return kb.store.save_capture(image_path="/t.png", source_text="vector", translation="向量", explanation="e")


def test_ingest_creates_terms_sources_and_tip(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    capture_id = _capture_for_ingest(kb)

    result = kb.ingest(
        KnowledgeIngest(
            capture_id=capture_id,
            terms=[{"term": "vector", "chinese_name": "向量", "beginner_explanation": "有方向的量"}],
            learning_tip="延伸概念：梯度——函数变化最快的方向",
            domain="编程",
        )
    )

    assert result.term_ids
    assert result.new_source_links == 1
    assert result.tip_id > 0
    term = kb.get_term(result.term_ids[0])
    assert term is not None
    assert term.occurrences == 1
    sources = kb.list_term_sources(result.term_ids[0])
    assert [capture.id for capture in sources] == [capture_id]
    tips = kb.list_tips(TipQuery(status="pending"))
    assert len(tips) == 1
    assert tips[0].content.startswith("延伸概念")


def test_ingest_retry_is_idempotent(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    capture_id = _capture_for_ingest(kb)
    ingest = KnowledgeIngest(
        capture_id=capture_id,
        terms=[{"term": "vector", "chinese_name": "向量"}],
        learning_tip="建议 A",
        domain="编程",
    )

    first = kb.ingest(ingest)
    second = kb.ingest(ingest)

    assert first.term_ids == second.term_ids
    assert second.new_source_links == 0
    assert first.tip_id == second.tip_id
    term = kb.get_term(first.term_ids[0])
    assert term is not None and term.occurrences == 1
    tips = kb.list_tips(TipQuery(status="pending"))
    assert len(tips) == 1


def test_ingest_across_captures_links_all_sources(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    c1 = _capture_for_ingest(kb)
    c2 = _capture_for_ingest(kb)

    kb.ingest(KnowledgeIngest(capture_id=c1, terms=[{"term": "vector", "chinese_name": "向量"}], domain="编程"))
    kb.ingest(KnowledgeIngest(capture_id=c2, terms=[{"term": "vector", "chinese_name": "向量"}], domain="编程"))

    term = kb.list_terms(TermQuery())[0]
    sources = kb.list_term_sources(term.id)
    assert {capture.id for capture in sources} == {c1, c2}
    assert term.occurrences == 2


def test_ingest_skips_pure_stopwords_and_returns_real_ids(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    capture_id = _capture_for_ingest(kb)
    result = kb.ingest(
        KnowledgeIngest(
            capture_id=capture_id,
            terms=[
                {"term": "the", "chinese_name": "这"},
                {"term": "因为", "chinese_name": "because"},
                {"term": "Transformer", "chinese_name": "变换器"},
            ],
            domain="AI概念",
        )
    )
    assert len(result.term_ids) == 1
    assert kb.get_term(result.term_ids[0]).term == "Transformer"  # type: ignore[union-attr]


def test_ingest_merge_still_fills_blanks_and_protects_user_edits(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    capture_id = _capture_for_ingest(kb)
    kb.ingest(
        KnowledgeIngest(
            capture_id=capture_id,
            terms=[{"term": "ORM", "chinese_name": "", "beginner_explanation": "", "examples": []}],
            domain="数据库",
        )
    )
    term = kb.list_terms(TermQuery())[0]
    kb.save_term(
        SaveTermCommand(
            term_id=term.id,
            term="ORM",
            chinese_name="对象关系映射",
            beginner_explanation="我自己的笔记",
            examples=[],
            domain="数据库",
        )
    )
    kb.ingest(
        KnowledgeIngest(
            capture_id=capture_id,
            terms=[{"term": "ORM", "chinese_name": "AI 新名", "beginner_explanation": "AI 新解释", "examples": []}],
            domain="数据库",
        )
    )
    term = kb.list_terms(TermQuery())[0]
    assert term.chinese_name == "对象关系映射"
    assert term.beginner_explanation == "我自己的笔记"


# ---------------------------------------------------------------------------
# 阶段 D：复习与行为 interface
# ---------------------------------------------------------------------------


def test_kb_set_favorite_returns_complete_record(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    capture_id = _capture_for_ingest(kb)
    term_id = kb.ingest(
        KnowledgeIngest(capture_id=capture_id, terms=[{"term": "SVD", "chinese_name": "奇异值分解"}], domain="AI概念")
    ).term_ids[0]

    record = kb.set_favorite(term_id, favorite=True)
    assert record.favorite is True
    assert record.term == "SVD"
    assert record.due_at != ""

    record = kb.set_favorite(term_id, favorite=False)
    assert record.favorite is False


def test_kb_review_roundtrip_and_outcome(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    capture_id = _capture_for_ingest(kb)
    term_id = kb.ingest(
        KnowledgeIngest(capture_id=capture_id, terms=[{"term": "SVD", "chinese_name": "奇异值分解"}], domain="AI概念")
    ).term_ids[0]
    kb.set_favorite(term_id, favorite=True)

    due = kb.list_due_terms()
    assert [term.id for term in due] == [term_id]

    outcome = kb.review(term_id, grade=2)
    assert outcome.interval_days == 1
    assert outcome.due_at
    assert kb.count_due_terms() == 0


def test_kb_record_view_returns_updated_record(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    capture_id = _capture_for_ingest(kb)
    term_id = kb.ingest(
        KnowledgeIngest(capture_id=capture_id, terms=[{"term": "if", "chinese_name": "如果"}], domain="编程")
    ).term_ids[0]

    before = kb.get_term(term_id)
    after = kb.record_view(term_id)
    assert after.views == before.views + 1  # type: ignore[union-attr]


def test_kb_tip_status_roundtrip(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    capture_id = _capture_for_ingest(kb)
    result = kb.ingest(
        KnowledgeIngest(capture_id=capture_id, terms=[], learning_tip="建议 B", domain="编程")
    )

    tip = kb.set_tip_status(result.tip_id, "done")
    assert tip.status == "done"
    assert tip.done_at != ""
    assert kb.count_tips("pending") == 0
    assert kb.count_tips("done") == 1


def test_term_query_view_folds_basic_words(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    capture_id = _capture_for_ingest(kb)
    kb.ingest(
        KnowledgeIngest(
            capture_id=capture_id,
            terms=[
                {"term": "if", "chinese_name": "如果"},
                {"term": "Polymorphism", "chinese_name": "多态"},
            ],
            domain="编程",
        )
    )

    visible = kb.list_terms(TermQuery(view="focus"))
    assert {term.term for term in visible} == {"Polymorphism"}

    all_terms = kb.list_terms(TermQuery(view="all"))
    assert {term.term for term in all_terms} == {"if", "Polymorphism"}
