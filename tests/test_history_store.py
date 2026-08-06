import pytest

from app.services.history_store import HistoryStore
from app.services.settings import AppSettings, SettingsService


def test_contexts_seeded_and_crud(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")

    contexts = store.list_contexts()
    assert any(context.builtin and context.name == "通用" for context in contexts)

    context_id = store.save_context(
        name="生物论文",
        domain="生物",
        scene="学术论文",
        summary="CRISPR 基因编辑 / 细胞生物学",
        instruction="专业名词给中文对照和通俗解释",
    )
    saved = store.get_context(context_id)
    assert saved is not None
    assert saved.name == "生物论文"
    assert saved.domain == "生物"
    assert saved.scene == "学术论文"
    assert saved.summary == "CRISPR 基因编辑 / 细胞生物学"
    assert not saved.builtin

    updated = store.save_context(
        name="生物论文",
        domain="生物",
        scene="学术论文",
        summary="CRISPR 基因编辑 / 细胞生物学 / 转录",
        instruction="专业名词给中文对照和通俗解释",
        context_id=context_id,
    )
    assert updated == context_id
    assert store.get_context(context_id).summary.endswith("转录")

    assert store.delete_context(context_id) is True
    assert store.get_context(context_id) is None


def test_builtin_context_cannot_be_deleted(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")
    builtin = next(context for context in store.list_contexts() if context.builtin)
    assert store.delete_context(builtin.id) is False
    assert store.get_context(builtin.id) is not None


def test_builtin_context_cannot_be_updated(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")
    builtin = next(context for context in store.list_contexts() if context.builtin)
    with pytest.raises(ValueError):
        store.save_context(name="改了", context_id=builtin.id)
    assert store.get_context(builtin.id).name == "通用"


def test_settings_roundtrip_with_context_block(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")
    store.set_setting("context_block", "领域：生物\n场景：学术论文")
    values = store.get_settings()
    assert values["context_block"] == "领域：生物\n场景：学术论文"


def test_settings_roundtrip_current_context_id(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")
    assert AppSettings.from_mapping({}).current_context_id is None
    store.set_setting("current_context_id", "3")
    settings = AppSettings.from_mapping(store.get_settings())
    assert settings.current_context_id == 3


def test_settings_service_bridges_context_record_to_block(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    context_id = store.save_context(
        name="生物论文",
        domain="生物",
        scene="学术论文",
        summary="CRISPR 基因编辑",
        instruction="术语给中文对照",
    )
    service.set_current_context(context_id)

    settings = service.load()
    assert settings.current_context_id == context_id
    assert "领域：生物" in settings.context_block
    assert "场景：学术论文" in settings.context_block
    assert "CRISPR 基因编辑" in settings.context_block
    assert "术语给中文对照" in settings.context_block


def test_settings_service_falls_back_to_stored_block(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    store.set_setting("context_block", "领域：法律\n场景：合同")

    settings = service.load()
    assert settings.context_block == "领域：法律\n场景：合同"


def test_settings_service_falls_back_when_context_deleted(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    context_id = store.save_context(name="临时", domain="法律", scene="合同")
    service.set_current_context(context_id)
    store.delete_context(context_id)

    settings = service.load()
    assert settings.context_block == ""


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


def test_terms_store_by_domain_separately(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")
    base = {"chinese_name": "向量", "beginner_explanation": "解释", "examples": []}

    store.upsert_terms([{"term": "向量", **base}], domain="编程")
    store.upsert_terms([{"term": "向量", **base}], domain="数学")

    terms = store.list_terms()
    assert len(terms) == 2
    assert {term.domain for term in terms} == {"编程", "数学"}

    programming = store.list_terms(domain="编程")
    assert len(programming) == 1 and programming[0].domain == "编程"
    assert len(store.list_terms(domain="数学")) == 1

    store.upsert_terms([{"term": "向量", **base}], domain="编程")
    assert len(store.list_terms(domain="编程")) == 1
    assert store.list_terms(domain="编程")[0].review_count == 2


def test_terms_pagination_and_count(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")
    for index in range(25):
        store.upsert_terms(
            [{"term": f"term-{index}", "chinese_name": "", "beginner_explanation": "", "examples": []}]
        )

    assert store.count_terms() == 25
    first = store.list_terms(limit=20, offset=0)
    second = store.list_terms(limit=20, offset=20)
    assert len(first) == 20
    assert len(second) == 5
    all_names = {t.term for t in first} | {t.term for t in second}
    assert all_names == {f"term-{i}" for i in range(25)}
    assert store.count_terms(query="term-2") >= 1
    assert store.count_favorite_terms() == 0


def test_terms_migration_adds_domain_column(tmp_path) -> None:
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE terms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT NOT NULL UNIQUE,
            chinese_name TEXT NOT NULL DEFAULT '',
            beginner_explanation TEXT NOT NULL DEFAULT '',
            examples TEXT NOT NULL DEFAULT '[]',
            first_seen_at TEXT NOT NULL,
            review_count INTEGER NOT NULL DEFAULT 0,
            favorite INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        "INSERT INTO terms (term, chinese_name, beginner_explanation, examples, first_seen_at, review_count, favorite) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("向量", "向量", "旧解释", "[]", "2026-01-01", 3, 1),
    )
    conn.commit()
    conn.close()

    store = HistoryStore(db)
    terms = store.list_terms()
    assert len(terms) == 1
    assert terms[0].domain == "通用"
    assert terms[0].favorite is True
    assert terms[0].review_count == 3


def test_capture_domain_filter_and_counts(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")
    store.save_capture(
        image_path="",
        source_text="患者临床治疗",
        translation="",
        explanation="",
        domain="医学",
    )
    store.save_capture(
        image_path="",
        source_text="Python exception",
        translation="",
        explanation="",
        domain="编程",
    )
    store.save_capture(
        image_path="",
        source_text="另一个 Python error",
        translation="",
        explanation="",
        domain="编程",
    )

    medical = store.search_captures_advanced(domain="医学")
    assert [record.source_text for record in medical] == ["患者临床治疗"]
    assert store.capture_domain_counts() == [("编程", 2), ("医学", 1)]


def test_capture_domain_migration_classifies_legacy_records(tmp_path) -> None:
    import sqlite3

    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
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
                tags TEXT NOT NULL DEFAULT '[]',
                category TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO captures
                (created_at, image_path, source_text, translation, explanation, app_name, tags, category)
            VALUES ('2026-08-05', '', ?, '', '', '', '[]', '')
            """,
            [
                ("患者正在接受临床药物治疗",),
                ("Python exception traceback",),
                ("没有明显领域信号",),
            ],
        )

    store = HistoryStore(db_path)
    records = {record.source_text: record.domain for record in store.search_captures(limit=10)}
    assert records == {
        "患者正在接受临床药物治疗": "医学",
        "Python exception traceback": "编程",
        "没有明显领域信号": "通用",
    }
