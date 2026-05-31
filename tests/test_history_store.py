from app.services.history_store import HistoryStore


def test_history_store_saves_and_searches_capture(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")

    capture_id = store.save_capture(
        image_path="capture.png",
        source_text="Token limit exceeded",
        translation="超过 token 限制",
        explanation="内容太长，需要分段。",
        tags=["AI", "报错"],
    )

    record = store.get_capture(capture_id)
    assert record is not None
    assert record.source_text == "Token limit exceeded"
    assert record.tags == ["AI", "报错"]

    results = store.search_captures("token")
    assert len(results) == 1


def test_history_store_upserts_terms(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")

    store.upsert_terms(
        [
            {
                "term": "token",
                "chinese_name": "文本单位",
                "beginner_explanation": "AI 处理文字的计量单位。",
                "examples": ["上下文长度按 token 计算"],
            }
        ]
    )
    store.upsert_terms(
        [
            {
                "term": "token",
                "chinese_name": "文本单位",
                "beginner_explanation": "AI 读文字时用的单位。",
                "examples": ["一个单词可能拆成多个 token"],
            }
        ]
    )

    terms = store.list_terms()
    assert len(terms) == 1
    assert terms[0].review_count == 2
    assert terms[0].term == "token"


def test_history_store_conversation_messages(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")
    capture_id = store.save_capture(
        image_path="capture.png",
        source_text="API key",
        translation="API 密钥",
        explanation="用于调用接口的密钥。",
    )

    conversation_id = store.create_conversation(capture_id, title="API key")
    same_id = store.create_conversation(capture_id, title="ignored")
    store.add_message(conversation_id, "user", "这个是什么意思？", mode="custom")
    store.add_message(conversation_id, "assistant", "这是接口密钥。", mode="custom")

    assert same_id == conversation_id
    assert store.get_conversation_id_for_capture(capture_id) == conversation_id
    messages = store.list_messages(conversation_id)
    assert [message.role for message in messages] == ["user", "assistant"]
