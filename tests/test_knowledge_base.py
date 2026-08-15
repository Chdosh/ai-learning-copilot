"""个人知识库（0.7）测试：术语治理、回链、间隔重复、学习建议、领域口径。"""
from __future__ import annotations

from pathlib import Path

from app.services.history_store import HistoryStore
from app.services.term_quality import classify_difficulty, is_pure_stopword


def _store(tmp_path: Path) -> HistoryStore:
    return HistoryStore(db_path=tmp_path / "test.db")


def test_pure_stopword_skipped_in_upsert(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = store._upsert_terms(
        [
            {"term": "the", "chinese_name": "这"},
            {"term": "因为", "chinese_name": "because"},
            {"term": "Transformer", "chinese_name": "变换器"},
        ],
        domain="AI概念",
    )
    terms = store.list_terms()
    assert len(ids) == 1
    assert [term.term for term in terms] == ["Transformer"]


def test_upsert_increments_occurrences(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store._upsert_terms(
        [
            {
                "term": "SQL",
                "chinese_name": "结构化查询语言",
                "beginner_explanation": "操作数据库的语言",
                "examples": ["SELECT * FROM users"],
            }
        ],
        domain="数据库",
    )
    store._upsert_terms(
        [{"term": "SQL", "chinese_name": "", "beginner_explanation": "", "examples": []}],
        domain="数据库",
    )
    term = store.list_terms()[0]
    assert term.occurrences == 2
    assert term.review_count == 2
    # 填空优先：第二次的空解释不能覆盖第一次的好解释
    assert term.beginner_explanation == "操作数据库的语言"
    assert term.chinese_name == "结构化查询语言"


def test_upsert_fill_blanks_first(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store._upsert_terms(
        [{"term": "ORM", "chinese_name": "", "beginner_explanation": "", "examples": []}],
        domain="数据库",
    )
    store._upsert_terms(
        [
            {
                "term": "ORM",
                "chinese_name": "对象关系映射",
                "beginner_explanation": "用对象操作数据库",
                "examples": [],
            }
        ],
        domain="数据库",
    )
    term = store.list_terms()[0]
    assert term.chinese_name == "对象关系映射"
    assert term.beginner_explanation == "用对象操作数据库"


def test_user_edited_terms_not_overwritten_by_ai(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store._upsert_terms(
        [{"term": "API", "chinese_name": "接口", "beginner_explanation": "旧解释", "examples": []}],
        domain="编程",
    )
    store.save_term(
        term="API",
        chinese_name="应用程序接口",
        beginner_explanation="我自己的笔记",
        examples=[],
        domain="编程",
    )
    store._upsert_terms(
        [{"term": "API", "chinese_name": "新接口", "beginner_explanation": "AI 新解释", "examples": []}],
        domain="编程",
    )
    term = store.list_terms()[0]
    assert term.user_edited is True
    assert term.chinese_name == "应用程序接口"
    assert term.beginner_explanation == "我自己的笔记"


def test_upsert_backlinks_term_to_capture(tmp_path: Path) -> None:
    store = _store(tmp_path)
    capture_id = store.save_capture(
        image_path="/tmp/test.png",
        source_text="Use a transformer model",
        translation="使用变换器模型",
        explanation="解释",
    )
    store._upsert_terms(
        [{"term": "transformer", "chinese_name": "变换器"}],
        domain="AI概念",
        capture_id=capture_id,
    )
    term = store.list_terms()[0]
    captures = store._list_term_captures(term.id)
    assert [capture.id for capture in captures] == [capture_id]


def test_term_captures_cleaned_on_delete(tmp_path: Path) -> None:
    store = _store(tmp_path)
    capture_id = store.save_capture(
        image_path="/tmp/test.png",
        source_text="test",
        translation="测试",
        explanation="解释",
    )
    store._upsert_terms(
        [{"term": "test", "chinese_name": "测试"}],
        domain="编程",
        capture_id=capture_id,
    )
    term = store.list_terms()[0]
    store.delete_capture(capture_id)
    assert store._list_term_captures(term.id) == []


def test_classify_difficulty() -> None:
    assert classify_difficulty("if") == "basic"
    assert classify_difficulty("the") == ""
    assert classify_difficulty("Transformer") == ""
    assert is_pure_stopword("the") is True
    assert is_pure_stopword("因为") is True
    assert is_pure_stopword("transformer") is False


def test_exclude_basic_folds_unviewed_terms(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store._upsert_terms(
        [
            {"term": "if", "chinese_name": "如果"},
            {"term": "Polymorphism", "chinese_name": "多态"},
        ],
        domain="编程",
    )
    visible = store.list_terms(exclude_basic=True)
    assert [term.term for term in visible] == ["Polymorphism"]
    all_terms = store.list_terms(exclude_basic=False)
    assert len(all_terms) == 2
    # 有查看行为后不再折叠
    hidden = [term for term in all_terms if term.term == "if"][0]
    store._record_term_view(hidden.id)
    visible = store.list_terms(exclude_basic=True)
    assert {term.term for term in visible} == {"Polymorphism", "if"}


def test_favorite_schedules_due_and_review_sm2(tmp_path: Path) -> None:
    store = _store(tmp_path)
    term_id = store.save_term(term="SVD", chinese_name="奇异值分解")
    assert store._count_due_terms() == 0

    assert store._toggle_term_favorite(term_id) is True
    assert store._count_due_terms() == 1

    result = store._review_term(term_id, grade=2)
    assert result is not None
    assert result["interval_days"] == 1  # 第一次答对：1 天
    assert store._count_due_terms() == 0  # 已排期到明天

    # 忘了：重置 1 天 + lapse + ease 下降
    store._review_term(term_id, grade=0)
    term = store.list_terms()[0]
    assert term.lapses == 1
    assert term.interval_days == 1
    assert term.ease < 2.5

    # 连续答对：1 → 6 → round(6 × 2.4) = 14 天
    # （第一步 ease 已到 2.5 上限，忘了后降到 2.3，再答对回到 2.4）
    store._review_term(term_id, grade=2)
    store._review_term(term_id, grade=2)
    term = store.list_terms()[0]
    assert term.interval_days == 14

    assert store._toggle_term_favorite(term_id) is False
    assert store._count_due_terms() == 0


def test_learning_tips_lifecycle(tmp_path: Path) -> None:
    store = _store(tmp_path)
    capture_id = store.save_capture(
        image_path="/tmp/test.png",
        source_text="test",
        translation="测试",
        explanation="解释",
    )
    tip_id = store._save_learning_tip(
        capture_id=capture_id,
        content="延伸概念：正则化——防止过拟合",
        domain="AI概念",
    )
    assert tip_id > 0
    assert store._count_learning_tips() == 1
    tips = store._list_learning_tips(status="pending")
    assert len(tips) == 1
    assert tips[0].content.startswith("延伸概念")

    assert store._set_learning_tip_status(tip_id, "done") is True
    assert store._count_learning_tips() == 0
    assert store._count_learning_tips(status="done") == 1
    done = store._list_learning_tips(status="done")[0]
    assert done.done_at != ""


def test_learning_tips_cleaned_with_capture(tmp_path: Path) -> None:
    store = _store(tmp_path)
    capture_id = store.save_capture(
        image_path="/tmp/test.png",
        source_text="test",
        translation="测试",
        explanation="解释",
    )
    store._save_learning_tip(capture_id=capture_id, content="一条建议")
    store.delete_capture(capture_id)
    assert store._count_learning_tips() == 0


def test_upsert_respects_per_term_domain(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store._upsert_terms(
        [
            {"term": "vector", "chinese_name": "向量", "domain": "编程"},
            {"term": "vector", "chinese_name": "载体", "domain": "生物"},
        ],
        domain="通用",
    )
    terms = {term.domain: term.chinese_name for term in store.list_terms()}
    assert terms == {"编程": "向量", "生物": "载体"}


# ---------------------------------------------------------------------------
# 可靠性修复：删除 capture 时级联清理 conversation/message，兜底历史孤儿
# ---------------------------------------------------------------------------


def _capture_with_conversation(store: HistoryStore) -> tuple[int, int]:
    capture_id = store.save_capture(
        image_path="/tmp/test.png",
        source_text="test source",
        translation="测试",
        explanation="解释",
    )
    conv_id = store.create_conversation(capture_id, title="test")
    store.add_message(conv_id, "user", "question", mode="custom")
    store.add_message(conv_id, "assistant", '{"answer": "ok"}', mode="custom")
    return capture_id, conv_id


def test_delete_capture_cascades_conversation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    capture_id, conv_id = _capture_with_conversation(store)
    assert store.list_messages(conv_id)

    store.delete_capture(capture_id)
    assert store.get_conversation_id_for_capture(capture_id) is None
    assert store.list_messages(conv_id) == []


def test_delete_captures_before_cascades_conversation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    capture_id, conv_id = _capture_with_conversation(store)

    count = store.delete_captures_before("2099-01-01")
    assert count == 1
    assert store.list_messages(conv_id) == []
    assert store.get_conversation_id_for_capture(capture_id) is None


def test_initialize_cleans_historical_orphans(tmp_path: Path) -> None:
    import sqlite3

    store = _store(tmp_path)
    capture_id, conv_id = _capture_with_conversation(store)
    # 模拟旧版本行为：绕过级联直接删 capture，留下孤儿 conversation/message
    conn = sqlite3.connect(store.db_path)
    conn.execute("DELETE FROM captures WHERE id = ?", (capture_id,))
    conn.commit()
    conn.close()

    # 重新初始化触发兜底清理（幂等）
    reopened = HistoryStore(db_path=store.db_path)
    assert reopened.list_messages(conv_id) == []
    conn = sqlite3.connect(store.db_path)
    orphan_convs = conn.execute(
        "SELECT COUNT(*) FROM conversations WHERE capture_id NOT IN (SELECT id FROM captures)"
    ).fetchone()[0]
    orphan_messages = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id NOT IN (SELECT id FROM conversations)"
    ).fetchone()[0]
    conn.close()
    assert orphan_convs == 0
    assert orphan_messages == 0
