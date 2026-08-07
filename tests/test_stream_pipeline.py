from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.services.ai_client import AIClientError, extract_stream_terms
from app.services.history_store import HistoryStore
from app.services.settings import AppSettings
from app.ui import workers
from app.ui.result_window import ResultWindow


class _FakeOCR:
    def extract_text(self, image_path: str) -> str:
        return "Token limit exceeded"


class _FakeFailingOCR:
    def extract_text(self, image_path: str) -> str:
        from app.services.ocr import OCRError

        raise OCRError("OCR 模型加载失败")


class _FakeFailingStreamingClient:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def stream_explain(self, source_text: str, mode: str = "default"):
        yield '{"translation":"部分翻'
        raise AIClientError("AI API HTTP 500: server error")


class _FakeFollowupStreamingClient:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def stream_followup(
        self, source_text, question, history=None, mode="custom"
    ):
        payload = json.dumps(
            {"translation": "", "explanation": "因为缺少依赖，需要先安装。"},
            ensure_ascii=False,
        )
        for start in range(0, len(payload), 5):
            yield payload[start : start + 5]


class _FakeFailingFollowupClient:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def stream_followup(
        self, source_text, question, history=None, mode="custom"
    ):
        raise AIClientError("无法连接 AI API: timeout")


class _FakeStreamingClient:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def stream_explain(self, source_text: str, mode: str = "default"):
        payload = json.dumps(
            {
                "translation": "超过 Token 限制",
                "explanation": "输入内容太长，需要缩短。",
                "terms": [{
                    "term": "Token",
                    "chinese_name": "文本单位",
                    "beginner_explanation": "模型处理文本的计量单位。",
                    "examples": ["上下文长度按 Token 计算"],
                }],
                "tags": ["AI", "报错"],
                "learning_tip": "把长内容拆成几段。",
            },
            ensure_ascii=False,
        )
        for start in range(0, len(payload), 7):
            yield payload[start : start + 7]


class _FakeTruncatedStreamingClient:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def stream_explain(self, source_text: str, mode: str = "default"):
        yield '{"explanation":"已经生成可读内容，但 JSON 没有完整结束'


def test_stream_capture_parses_persists_and_deletes_temporary_image(
    tmp_path, monkeypatch
) -> None:
    image_path = tmp_path / "capture.png"
    image_path.write_bytes(b"fake image")
    store = HistoryStore(tmp_path / "app.db")
    settings = AppSettings(api_key="test-key", save_screenshots=False)
    monkeypatch.setattr(workers, "AIClient", _FakeStreamingClient)
    worker = workers.CaptureStreamWorker(
        image_path=str(image_path),
        settings=settings,
        ocr_service=_FakeOCR(),
        history_store=store,
    )
    stream_chunks: list[tuple[str, str]] = []
    completed: list[dict] = []
    worker.stream_chunk.connect(
        lambda section, chunk: stream_chunks.append((section, chunk))
    )
    worker.completed.connect(completed.append)

    worker.run()

    assert "".join(
        chunk for section, chunk in stream_chunks if section == "translation"
    ) == "超过 Token 限制"
    assert "".join(
        chunk for section, chunk in stream_chunks if section == "explanation"
    ) == "输入内容太长，需要缩短。"
    assert len(stream_chunks) > 2
    payload = completed[0]
    assert payload["translation"] == "超过 Token 限制"
    assert payload["explanation"] == "输入内容太长，需要缩短。"
    assert payload["capture_id"] > 0
    assert payload["conversation_id"] > 0
    assert payload["image_path"] == ""
    assert not image_path.exists()
    record = store.get_capture(payload["capture_id"])
    assert record is not None
    assert record.translation == "超过 Token 限制"
    assert record.tags == ["AI", "报错"]
    assert record.domain == "编程"
    assert store.list_terms()[0].term == "Token"


def test_stream_capture_emits_terms_before_completion(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    image_path.write_bytes(b"fake image")
    store = HistoryStore(tmp_path / "app.db")
    settings = AppSettings(api_key="test-key", save_screenshots=False)
    monkeypatch.setattr(workers, "AIClient", _FakeStreamingClient)
    worker = workers.CaptureStreamWorker(
        image_path=str(image_path),
        settings=settings,
        ocr_service=_FakeOCR(),
        history_store=store,
    )
    term_batches: list[list[dict]] = []
    worker.stream_terms.connect(term_batches.append)
    worker.completed.connect(lambda payload: None)

    worker.run()

    assert term_batches
    assert any(
        any(term.get("term") == "Token" for term in batch)
        for batch in term_batches
    )


def test_result_window_renders_streamed_terms_during_streaming() -> None:
    app = QApplication.instance() or QApplication([])
    window = ResultWindow()
    window.show_loading()
    window.append_stream_chunk("explanation", "输入内容太长，需要缩短。")
    assert "术语解释" not in window.text_browser.toPlainText()

    window.set_stream_terms(
        [{"term": "Token", "chinese_name": "文本单位", "beginner_explanation": "计量单位。", "examples": []}]
    )
    visible_text = window.text_browser.toPlainText()
    assert "术语解释" in visible_text
    assert "Token" in visible_text
    window.force_close()
    app.processEvents()


def test_result_window_keeps_answer_when_status_changes() -> None:
    app = QApplication.instance() or QApplication([])
    window = ResultWindow()
    window.show_loading()
    window.set_status("正在获取 AI 回答...")
    window.append_stream_chunk("translation", "翻译内容")
    window.append_stream_chunk("explanation", "答案正文")
    window.set_status("完成")
    visible_text = window.text_browser.toPlainText()
    assert "翻译内容" in visible_text
    assert "答案正文" in visible_text
    assert not window.status_label.isHidden()
    window.force_close()
    app.processEvents()


def test_result_window_keeps_translation_while_explanation_streams() -> None:
    app = QApplication.instance() or QApplication([])
    window = ResultWindow()
    window.show_loading()

    window.append_stream_chunk("translation", "缺少")
    window.append_stream_chunk("translation", "依赖")
    assert window.text_browser.toPlainText() == "翻译\n缺少依赖"

    window.append_stream_chunk("explanation", "当前环境")
    visible_text = window.text_browser.toPlainText()
    assert "缺少依赖" in visible_text
    assert "当前环境" in visible_text
    window.append_stream_chunk("explanation", "缺少依赖。")
    visible_text = window.text_browser.toPlainText()
    assert "缺少依赖" in visible_text
    assert "当前环境缺少依赖。" in visible_text

    window.force_close()
    app.processEvents()


def test_result_window_uses_generic_visual_hierarchy() -> None:
    app = QApplication.instance() or QApplication([])
    window = ResultWindow()
    window.set_result(
        {
            "source_text": (
                "D:\\work\\ai-learning-copilot> python -m app\n"
                "ModuleNotFoundError: No module named 'PySide6'"
            ),
            "translation": "Python 未找到 PySide6 模块。",
            "explanation": (
                "当前环境缺少运行所需的依赖。\n"
                "pip install PySide6\n"
                "安装完成后重新运行原命令即可。"
            ),
            "learning_tip": "了解 ModuleNotFoundError 的模块查找规则。",
            "terms": [
                {
                    "term": "ModuleNotFoundError",
                    "chinese_name": "模块未找到错误",
                    "beginner_explanation": "Python 找不到准备导入的模块。",
                    "examples": [],
                }
            ],
        }
    )

    visible_text = window.text_browser.toPlainText()
    assert visible_text.startswith("翻译")
    assert "Python 未找到 PySide6 模块。" in visible_text
    assert "当前环境缺少运行所需的依赖。" in visible_text
    assert "pip install PySide6" in visible_text
    assert "术语解释" in visible_text
    assert "ModuleNotFoundError · 模块未找到错误" in visible_text
    assert "Python 找不到准备导入的模块。" in visible_text
    assert "\n\n" not in visible_text
    assert "学习建议" not in visible_text
    assert window.tip_content.isVisible()
    assert window.tip_content.text() == "了解 ModuleNotFoundError 的模块查找规则。"

    window.append_followup_result({"explanation": "安装后仍有问题时，检查虚拟环境。"})
    assert "\n追问回答\n安装后仍有问题" in window.text_browser.toPlainText()
    assert "\n\n" not in window.text_browser.toPlainText()
    window.force_close()
    app.processEvents()


def test_result_window_expands_body_for_long_content() -> None:
    app = QApplication.instance() or QApplication([])
    window = ResultWindow()
    window.set_result(
        {
            "source_text": "长内容",
            "translation": "",
            "explanation": "\n".join(f"第 {index} 行解释内容" for index in range(40)),
            "terms": [],
        }
    )

    assert 380 <= window.width() <= 760
    assert window.text_browser.height() > 360
    assert window.text_browser.verticalScrollBar().maximum() > 0
    window.force_close()
    app.processEvents()


def test_stream_capture_recovers_readable_text_from_truncated_json(
    tmp_path, monkeypatch
) -> None:
    image_path = tmp_path / "capture.png"
    image_path.write_bytes(b"fake image")
    store = HistoryStore(tmp_path / "app.db")
    settings = AppSettings(api_key="test-key", save_screenshots=False)
    monkeypatch.setattr(workers, "AIClient", _FakeTruncatedStreamingClient)
    worker = workers.CaptureStreamWorker(
        image_path=str(image_path),
        settings=settings,
        ocr_service=_FakeOCR(),
        history_store=store,
    )
    completed: list[dict] = []
    worker.completed.connect(completed.append)

    worker.run()

    payload = completed[0]
    assert "error" not in payload
    assert payload["partial_response"] is True
    assert payload["explanation"] == "已经生成可读内容，但 JSON 没有完整结束"
    record = store.get_capture(payload["capture_id"])
    assert record is not None
    assert record.explanation == payload["explanation"]


def test_stream_capture_saves_source_text_when_ai_fails(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    image_path.write_bytes(b"fake image")
    store = HistoryStore(tmp_path / "app.db")
    settings = AppSettings(api_key="test-key", save_screenshots=False)
    monkeypatch.setattr(workers, "AIClient", _FakeFailingStreamingClient)
    worker = workers.CaptureStreamWorker(
        image_path=str(image_path),
        settings=settings,
        ocr_service=_FakeOCR(),
        history_store=store,
    )
    completed: list[dict] = []
    worker.completed.connect(completed.append)

    worker.run()

    payload = completed[0]
    assert "error" in payload
    assert payload["source_text"] == "Token limit exceeded"
    assert payload["capture_id"] > 0
    assert payload["partial_translation"] == "部分翻"
    record = store.get_capture(payload["capture_id"])
    assert record is not None
    assert record.source_text == "Token limit exceeded"
    assert record.tags == ["待处理"]
    assert not image_path.exists()


def test_stream_capture_deletes_image_when_ocr_fails_and_saving_is_off(
    tmp_path, monkeypatch
) -> None:
    image_path = tmp_path / "capture.png"
    image_path.write_bytes(b"fake image")
    store = HistoryStore(tmp_path / "app.db")
    settings = AppSettings(api_key="test-key", save_screenshots=False)
    worker = workers.CaptureStreamWorker(
        image_path=str(image_path),
        settings=settings,
        ocr_service=_FakeFailingOCR(),
        history_store=store,
    )
    completed: list[dict] = []
    worker.completed.connect(completed.append)

    worker.run()

    assert "error" in completed[0]
    assert not image_path.exists()


def test_stream_capture_keeps_image_when_saving_is_on_and_ai_fails(
    tmp_path, monkeypatch
) -> None:
    image_path = tmp_path / "capture.png"
    image_path.write_bytes(b"fake image")
    store = HistoryStore(tmp_path / "app.db")
    settings = AppSettings(api_key="test-key", save_screenshots=True)
    monkeypatch.setattr(workers, "AIClient", _FakeFailingStreamingClient)
    worker = workers.CaptureStreamWorker(
        image_path=str(image_path),
        settings=settings,
        ocr_service=_FakeOCR(),
        history_store=store,
    )
    completed: list[dict] = []
    worker.completed.connect(completed.append)

    worker.run()

    assert "error" in completed[0]
    assert image_path.exists()


def test_stream_capture_retry_updates_existing_capture(tmp_path, monkeypatch) -> None:
    store = HistoryStore(tmp_path / "app.db")
    capture_id = store.save_capture(
        image_path="/tmp/fail.png",
        source_text="Token limit exceeded",
        translation="",
        explanation="",
        tags=["待处理"],
        category="",
    )
    settings = AppSettings(api_key="test-key", save_screenshots=True)
    monkeypatch.setattr(workers, "AIClient", _FakeStreamingClient)
    worker = workers.CaptureStreamWorker(
        image_path="/tmp/fail.png",
        settings=settings,
        ocr_service=_FakeOCR(),
        history_store=store,
        capture_id=capture_id,
        source_text="Token limit exceeded",
    )
    completed: list[dict] = []
    worker.completed.connect(completed.append)

    worker.run()

    payload = completed[0]
    assert "error" not in payload
    assert payload["capture_id"] == capture_id
    assert len(store.search_captures(limit=10)) == 1
    record = store.get_capture(capture_id)
    assert record is not None
    assert record.translation == "超过 Token 限制"
    assert record.explanation == "输入内容太长，需要缩短。"
    assert record.tags == ["AI", "报错"]


def test_followup_worker_streams_and_persists(tmp_path, monkeypatch) -> None:
    store = HistoryStore(tmp_path / "app.db")
    capture_id = store.save_capture(
        image_path="",
        source_text="hello",
        translation="",
        explanation="",
        tags=[],
        category="",
    )
    conv_id = store.create_conversation(capture_id, title="t")
    settings = AppSettings(api_key="test-key")
    monkeypatch.setattr(workers, "AIClient", _FakeFollowupStreamingClient)
    worker = workers.FollowupWorker(
        source_text="hello",
        question="为什么",
        settings=settings,
        history_store=store,
        conversation_id=conv_id,
        capture_id=capture_id,
    )
    chunks: list[tuple[str, str]] = []
    completed: list[dict] = []
    worker.stream_chunk.connect(lambda section, chunk: chunks.append((section, chunk)))
    worker.completed.connect(completed.append)

    worker.run()

    assert "".join(chunk for section, chunk in chunks if section == "explanation") == (
        "因为缺少依赖，需要先安装。"
    )
    payload = completed[0]
    assert "error" not in payload
    assert payload["explanation"] == "因为缺少依赖，需要先安装。"
    messages = store.list_messages(conv_id)
    assert messages[-2].content == "为什么"
    assert json.loads(messages[-1].content)["explanation"] == "因为缺少依赖，需要先安装。"


def test_followup_worker_does_not_persist_on_failure(tmp_path, monkeypatch) -> None:
    store = HistoryStore(tmp_path / "app.db")
    capture_id = store.save_capture(
        image_path="",
        source_text="hello",
        translation="",
        explanation="",
        tags=[],
        category="",
    )
    conv_id = store.create_conversation(capture_id, title="t")
    settings = AppSettings(api_key="test-key")
    monkeypatch.setattr(workers, "AIClient", _FakeFailingFollowupClient)
    worker = workers.FollowupWorker(
        source_text="hello",
        question="为什么",
        settings=settings,
        history_store=store,
        conversation_id=conv_id,
        capture_id=capture_id,
    )
    completed: list[dict] = []
    worker.completed.connect(completed.append)

    worker.run()

    payload = completed[0]
    assert "error" in payload
    assert store.list_messages(conv_id) == []


def test_extract_stream_terms_partial() -> None:
    content = (
        '{"explanation":"x","terms":['
        '{"term":"Token","chinese_name":"文本单位","beginner_explanation":"计量单位。","examples":[]},'
        '{"term":"HTTP"'
    )
    terms = extract_stream_terms(content)
    assert len(terms) == 1
    assert terms[0]["term"] == "Token"
    assert terms[0]["chinese_name"] == "文本单位"


def test_extract_stream_terms_handles_braces_in_strings() -> None:
    content = '{"terms":[{"term":"dict","beginner_explanation":"形如 {a: 1} 的结构","examples":[]}]}'
    terms = extract_stream_terms(content)
    assert len(terms) == 1
    assert terms[0]["term"] == "dict"


def test_extract_stream_terms_empty() -> None:
    assert extract_stream_terms('{"explanation":"x"}') == []
    assert extract_stream_terms('{"terms":[]}') == []
    assert extract_stream_terms("") == []


def test_looks_like_code_backstop() -> None:
    from app.ui.message_render import looks_like_code

    assert looks_like_code("def foo():\n    return 1\nprint(foo())") is True
    assert looks_like_code("ModuleNotFoundError: No module named 'PySide6'") is False
    assert looks_like_code("This simply means the module is missing.") is False
    assert looks_like_code("") is False


def test_result_window_hides_translation_for_code_source() -> None:
    app = QApplication.instance() or QApplication([])
    window = ResultWindow()
    window.set_result(
        {
            "source_text": "def foo():\n    import os\n    return os.getcwd()",
            "translation": "定义函数 foo",
            "explanation": "这是一个 Python 函数。",
            "terms": [],
        }
    )
    visible_text = window.text_browser.toPlainText()
    assert "定义函数 foo" not in visible_text
    assert "这是一个 Python 函数。" in visible_text
    assert "翻译" not in visible_text
    window.force_close()
    app.processEvents()


def test_result_window_loading_mode_is_compact() -> None:
    app = QApplication.instance() or QApplication([])
    window = ResultWindow()
    window.show_loading()
    assert window._loading is True
    assert window.text_browser.isHidden()
    assert not window.followup_input.isHidden() or not window.followup_input.isVisible()

    window.set_status("正在获取 AI 回答...")
    assert not window.status_label.isHidden()

    window.append_stream_chunk("explanation", "答案")
    assert window._loading is False
    assert not window.text_browser.isHidden()
    assert not window.status_label.isHidden()
    assert "答案" in window.text_browser.toPlainText()
    window.force_close()
    app.processEvents()


def test_result_window_font_buttons_scale_content() -> None:
    app = QApplication.instance() or QApplication([])
    window = ResultWindow()
    window.set_result(
        {"source_text": "x", "translation": "", "explanation": "解释内容\n第二行", "terms": []}
    )
    app.processEvents()
    before = window.text_browser.document().size().height()

    window.adjust_text_size(3)
    app.processEvents()
    after = window.text_browser.document().size().height()

    assert window.text_browser.font().pixelSize() == 15
    assert window.status_label.font().pixelSize() == 13
    assert after > before
    window.force_close()
    app.processEvents()


def test_result_window_actions_appear_only_after_result() -> None:
    app = QApplication.instance() or QApplication([])
    window = ResultWindow()
    window.show_loading()
    assert window.followup_input.isHidden()

    window.append_stream_chunk("explanation", "答案")
    assert window.followup_input.isHidden()
    assert not window.text_browser.isHidden()

    window.set_result({"source_text": "x", "translation": "", "explanation": "答案", "terms": []})
    assert not window.followup_input.isHidden()
    assert not window.send_button.isHidden()
    assert not window.more_button.isHidden()
    window.force_close()
    app.processEvents()


def test_result_window_error_view_shows_retry_button() -> None:
    app = QApplication.instance() or QApplication([])
    window = ResultWindow()
    window.set_result(
        {
            "error": "AI 解释失败: 无法连接 AI API",
            "capture_id": 7,
            "source_text": "hello world",
            "partial_translation": "你好",
        }
    )
    visible_text = window.text_browser.toPlainText()
    assert "无法连接 AI API" in visible_text
    assert "OCR 原文" in visible_text
    assert "hello world" in visible_text
    assert not window.retry_button.isHidden()
    assert window.followup_input.isEnabled()
    window.force_close()
    app.processEvents()


def test_result_window_error_view_hides_retry_without_capture() -> None:
    app = QApplication.instance() or QApplication([])
    window = ResultWindow()
    window.set_result({"error": "OCR 没有识别到文字。", "source_text": ""})
    assert window.retry_button.isHidden()
    window.force_close()
    app.processEvents()


def test_result_window_followup_stream_block() -> None:
    app = QApplication.instance() or QApplication([])
    window = ResultWindow()
    window.show_loading()
    window.begin_followup()
    assert "思考中" in window.text_browser.toPlainText()
    assert not window.followup_input.isEnabled()

    window.append_followup_chunk("explanation", "因为缺")
    assert "因为缺" in window.text_browser.toPlainText()
    window.append_followup_chunk("explanation", "少依赖。")
    assert "因为缺少依赖。" in window.text_browser.toPlainText()

    window.append_followup_result({"explanation": "因为缺少依赖。", "translation": ""})
    visible_text = window.text_browser.toPlainText()
    assert "因为缺少依赖。" in visible_text
    assert "思考中" not in visible_text
    assert window.followup_input.isEnabled()
    window.force_close()
    app.processEvents()
