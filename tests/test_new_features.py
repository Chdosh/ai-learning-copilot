from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from app.services.categorizer import auto_categorize, get_all_categories, is_valid_category
from app.services.history_store import HistoryStore


def test_categorize_error():
    result = auto_categorize("Error: Connection refused by host", [])
    assert result == "报错"


def test_categorize_ai():
    result = auto_categorize("This is about LLM training and neural networks", [])
    assert result == "AI概念"


def test_categorize_python():
    result = auto_categorize("import pandas as pd\ndf = pd.DataFrame()", [])
    assert result == "Python"


def test_categorize_database():
    result = auto_categorize("MySQL query failed with SQL syntax error", [])
    assert result == "数据库"


def test_categorize_network():
    result = auto_categorize("HTTP 404 Not Found from REST API endpoint", [])
    assert result == "网络"


def test_categorize_documentation():
    result = auto_categorize("README tutorial for installation guide", [])
    assert result == "文档"


def test_categorize_tag_override():
    result = auto_categorize("random text", ["Python"])
    assert result == "Python"


def test_categorize_empty():
    result = auto_categorize("", [])
    assert result == ""


def test_categories_list():
    cats = get_all_categories()
    assert "报错" in cats
    assert "AI概念" in cats
    assert "Python" in cats
    assert "其他" in cats


def test_is_valid_category():
    assert is_valid_category("Python") is True
    assert is_valid_category("不存在的分类") is False


def test_history_store_save_capture_with_category():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = HistoryStore(db_path=db_path)
        capture_id = store.save_capture(
            image_path="/tmp/test.png",
            source_text="test source",
            translation="测试翻译",
            explanation="test explanation",
            tags=["Python", "test"],
            category="Python",
        )
        record = store.get_capture(capture_id)
        assert record is not None
        assert record.category == "Python"
        assert record.tags == ["Python", "test"]


def test_history_store_toggle_favorite():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = HistoryStore(db_path=db_path)
        term_id = store.save_term(term="API", chinese_name="接口")
        term = store.list_terms()[0]
        assert term.favorite is False

        new_state = store.toggle_term_favorite(term_id)
        assert new_state is True
        term = store.list_terms()[0]
        assert term.favorite is True

        new_state = store.toggle_term_favorite(term_id)
        assert new_state is False


def test_history_store_statistics():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = HistoryStore(db_path=db_path)
        store.save_capture(
            image_path="/tmp/test.png",
            source_text="Error occurred",
            translation="发生错误",
            explanation="解释",
            tags=["报错"],
            category="报错",
        )
        store.save_term(term="Error", chinese_name="错误")

        stats = store.get_statistics()
        assert stats["total_captures"] == 1
        assert stats["total_terms"] >= 1
        assert "报错" in stats["category_distribution"]


def test_history_store_update_capture():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = HistoryStore(db_path=db_path)
        capture_id = store.save_capture(
            image_path="/tmp/fail.png",
            source_text="hello",
            translation="",
            explanation="",
            tags=["待处理"],
            category="",
        )
        ok = store.update_capture(
            capture_id,
            translation="你好",
            explanation="解释",
            tags=["AI"],
            category="AI概念",
        )
        assert ok is True
        record = store.get_capture(capture_id)
        assert record is not None
        assert record.translation == "你好"
        assert record.explanation == "解释"
        assert record.tags == ["AI"]
        assert record.category == "AI概念"
        assert record.image_path == "/tmp/fail.png"
        assert store.update_capture(99999, translation="", explanation="", tags=[], category="") is False


def test_history_store_delete_capture():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = HistoryStore(db_path=db_path)
        capture_id = store.save_capture(
            image_path="/tmp/test.png",
            source_text="test",
            translation="测试",
            explanation="解释",
        )
        store.delete_capture(capture_id)
        assert store.get_capture(capture_id) is None


def test_history_store_delete_captures_before():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = HistoryStore(db_path=db_path)
        store.save_capture(
            image_path="/tmp/test.png",
            source_text="test",
            translation="测试",
            explanation="解释",
        )
        count = store.delete_captures_before("2099-01-01")
        assert count == 1
        count = store.delete_captures_before("2099-01-01")
        assert count == 0


def test_category_auto_assigned_on_save():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = HistoryStore(db_path=db_path)
        category = auto_categorize("Traceback ImportError No module named", ["error"])
        capture_id = store.save_capture(
            image_path="/tmp/test.png",
            source_text="Traceback ImportError No module named",
            translation="导入错误",
            explanation="模块导入失败",
            tags=["error", "Python"],
            category=category,
        )
        record = store.get_capture(capture_id)
        assert record is not None
        assert record.category in ("报错", "Python", "AI概念")


def test_advanced_search_by_date():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = HistoryStore(db_path=db_path)
        store.save_capture(
            image_path="/tmp/test.png",
            source_text="test query content",
            translation="测试",
            explanation="解释",
            tags=["test"],
            category="Python",
        )
        results = store.search_captures_advanced(query="test")
        assert len(results) == 1

        results = store.search_captures_advanced(query="nonexistent")
        assert len(results) == 0


def test_advanced_search_has_category():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = HistoryStore(db_path=db_path)
        store.save_capture(
            image_path="/tmp/test.png",
            source_text="Error occurred",
            translation="错误",
            explanation="解释",
            tags=["error"],
            category="报错",
        )
        store.save_capture(
            image_path="/tmp/test2.png",
            source_text="No category text",
            translation="无分类",
            explanation="解释",
            tags=["test"],
            category="",
        )
        results = store.search_captures_advanced(has_category=True)
        assert len(results) == 1
        assert results[0].category == "报错"


def test_advanced_search_has_followup():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = HistoryStore(db_path=db_path)
        capture_id = store.save_capture(
            image_path="/tmp/test.png",
            source_text="test",
            translation="测试",
            explanation="解释",
        )
        conv_id = store.create_conversation(capture_id, title="test")
        store.add_message(conv_id, "user", "question")
        store.add_message(conv_id, "assistant", '{"answer": "test"}')

        results = store.search_captures_advanced(has_followup=True)
        assert len(results) == 1


def test_advanced_search_has_followup_excludes_capture_message():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = HistoryStore(db_path=db_path)
        capture_id = store.save_capture(
            image_path="/tmp/test.png",
            source_text="test",
            translation="测试",
            explanation="解释",
        )
        conversation_id = store.create_conversation(capture_id, title="test")
        store.add_message(conversation_id, "user", "test", mode="capture")

        results = store.search_captures_advanced(has_followup=True)
        assert results == []


