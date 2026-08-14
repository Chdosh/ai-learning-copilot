"""个人知识库（0.7）测试：术语治理、回链、间隔重复、学习建议、领域口径。"""
from __future__ import annotations

from pathlib import Path

from app.services.history_store import HistoryStore
from app.services.term_quality import classify_difficulty, is_pure_stopword


def _store(tmp_path: Path) -> HistoryStore:
    return HistoryStore(db_path=tmp_path / "test.db")


def test_pure_stopword_skipped_in_upsert(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = store.upsert_terms(
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
    store.upsert_terms(
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
    store.upsert_terms(
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
    store.upsert_terms(
        [{"term": "ORM", "chinese_name": "", "beginner_explanation": "", "examples": []}],
        domain="数据库",
    )
    store.upsert_terms(
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
    store.upsert_terms(
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
    store.upsert_terms(
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
    store.upsert_terms(
        [{"term": "transformer", "chinese_name": "变换器"}],
        domain="AI概念",
        capture_id=capture_id,
    )
    term = store.list_terms()[0]
    captures = store.list_term_captures(term.id)
    assert [capture.id for capture in captures] == [capture_id]


def test_term_captures_cleaned_on_delete(tmp_path: Path) -> None:
    store = _store(tmp_path)
    capture_id = store.save_capture(
        image_path="/tmp/test.png",
        source_text="test",
        translation="测试",
        explanation="解释",
    )
    store.upsert_terms(
        [{"term": "test", "chinese_name": "测试"}],
        domain="编程",
        capture_id=capture_id,
    )
    term = store.list_terms()[0]
    store.delete_capture(capture_id)
    assert store.list_term_captures(term.id) == []


def test_classify_difficulty() -> None:
    assert classify_difficulty("if") == "basic"
    assert classify_difficulty("the") == ""
    assert classify_difficulty("Transformer") == ""
    assert is_pure_stopword("the") is True
    assert is_pure_stopword("因为") is True
    assert is_pure_stopword("transformer") is False


def test_exclude_basic_folds_unviewed_terms(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert_terms(
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
    store.record_term_view(hidden.id)
    visible = store.list_terms(exclude_basic=True)
    assert {term.term for term in visible} == {"Polymorphism", "if"}


def test_favorite_schedules_due_and_review_sm2(tmp_path: Path) -> None:
    store = _store(tmp_path)
    term_id = store.save_term(term="SVD", chinese_name="奇异值分解")
    assert store.count_due_terms() == 0

    assert store.toggle_term_favorite(term_id) is True
    assert store.count_due_terms() == 1

    result = store.review_term(term_id, grade=2)
    assert result is not None
    assert result["interval_days"] == 1  # 第一次答对：1 天
    assert store.count_due_terms() == 0  # 已排期到明天

    # 忘了：重置 1 天 + lapse + ease 下降
    store.review_term(term_id, grade=0)
    term = store.list_terms()[0]
    assert term.lapses == 1
    assert term.interval_days == 1
    assert term.ease < 2.5

    # 连续答对：1 → 6 → round(6 × 2.4) = 14 天
    # （第一步 ease 已到 2.5 上限，忘了后降到 2.3，再答对回到 2.4）
    store.review_term(term_id, grade=2)
    store.review_term(term_id, grade=2)
    term = store.list_terms()[0]
    assert term.interval_days == 14

    assert store.toggle_term_favorite(term_id) is False
    assert store.count_due_terms() == 0


def test_learning_tips_lifecycle(tmp_path: Path) -> None:
    store = _store(tmp_path)
    capture_id = store.save_capture(
        image_path="/tmp/test.png",
        source_text="test",
        translation="测试",
        explanation="解释",
    )
    tip_id = store.save_learning_tip(
        capture_id=capture_id,
        content="延伸概念：正则化——防止过拟合",
        domain="AI概念",
    )
    assert tip_id > 0
    assert store.count_learning_tips() == 1
    tips = store.list_learning_tips(status="pending")
    assert len(tips) == 1
    assert tips[0].content.startswith("延伸概念")

    assert store.set_learning_tip_status(tip_id, "done") is True
    assert store.count_learning_tips() == 0
    assert store.count_learning_tips(status="done") == 1
    done = store.list_learning_tips(status="done")[0]
    assert done.done_at != ""


def test_learning_tips_cleaned_with_capture(tmp_path: Path) -> None:
    store = _store(tmp_path)
    capture_id = store.save_capture(
        image_path="/tmp/test.png",
        source_text="test",
        translation="测试",
        explanation="解释",
    )
    store.save_learning_tip(capture_id=capture_id, content="一条建议")
    store.delete_capture(capture_id)
    assert store.count_learning_tips() == 0


def test_upsert_respects_per_term_domain(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert_terms(
        [
            {"term": "vector", "chinese_name": "向量", "domain": "编程"},
            {"term": "vector", "chinese_name": "载体", "domain": "生物"},
        ],
        domain="通用",
    )
    terms = {term.domain: term.chinese_name for term in store.list_terms()}
    assert terms == {"编程": "向量", "生物": "载体"}
