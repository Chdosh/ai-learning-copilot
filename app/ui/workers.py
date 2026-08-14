from __future__ import annotations

from pathlib import Path
import json

from PySide6.QtCore import QThread, Signal

from app.services.ai_client import (
    AIClient,
    AIClientError,
    AIResult,
    extract_stream_sections,
    extract_stream_terms,
    parse_ai_result,
    parse_json_object,
)
from app.services.categorizer import auto_categorize
from app.services.context_detector import detect_domain, detect_scene
from app.services.history_store import HistoryStore
from app.services.ocr import OCRError, OCRService
from app.services.settings import AppSettings


def _term_dicts(result: AIResult) -> list[dict]:
    return [
        {
            "term": term.term,
            "chinese_name": term.chinese_name,
            "beginner_explanation": term.beginner_explanation,
            "examples": term.examples,
            "domain": term.domain,
        }
        for term in result.terms
    ]


def _resolve_term_domain(settings: AppSettings, store: HistoryStore) -> str:
    """Terms belong to the learning direction active when the explanation ran."""
    context_id = getattr(settings, "current_context_id", None)
    if context_id is not None:
        context = store.get_context(context_id)
        if context is not None and not context.builtin:
            return context.domain or "通用"
    return "通用"


def _resolve_capture_domain(
    settings: AppSettings,
    store: HistoryStore,
    source_text: str,
    result: AIResult,
) -> str:
    configured = _resolve_term_domain(settings, store)
    if configured != "通用":
        return configured
    detected = detect_domain(
        " ".join(
            [source_text, result.translation, result.explanation, " ".join(result.tags)]
        )
    )
    return "通用" if detected == "其他" else detected


class CaptureStreamWorker(QThread):
    """OCR + streaming AI response worker."""

    status = Signal(str)
    stream_chunk = Signal(str, str)
    stream_terms = Signal(list)
    source_ready = Signal(str)
    completed = Signal(dict)

    def __init__(
        self,
        image_path: str,
        settings: AppSettings,
        ocr_service: OCRService,
        history_store: HistoryStore,
        capture_id: int | None = None,
        source_text: str | None = None,
    ) -> None:
        super().__init__()
        self.image_path = image_path
        self.settings = settings
        self.ocr_service = ocr_service
        self.history_store = history_store
        self.capture_id = capture_id
        self.source_text = source_text

    def run(self) -> None:
        source_text = (self.source_text or "").strip()
        ocr_error = ""
        if not source_text:
            self.status.emit("正在识别...")
            try:
                source_text = self.ocr_service.extract_text(self.image_path)
            except OCRError as exc:
                ocr_error = str(exc)
            except Exception as exc:
                ocr_error = f"OCR 发生未知错误: {exc}"

        if not source_text.strip():
            message = ocr_error or "OCR 没有识别到文字。"
            self.status.emit(message)
            self._cleanup_screenshot()
            self.completed.emit({"error": message, "source_text": ""})
            return

        self.source_ready.emit(source_text)
        self.status.emit("正在获取 AI 回答...")
        raw_response = ""
        visible_sections = {"translation": "", "explanation": "", "learning_tip": ""}
        emitted_terms = 0
        try:
            client = AIClient(self.settings)
            for chunk in client.stream_explain(source_text):
                raw_response += chunk
                sections = extract_stream_sections(raw_response)
                for section_name in ("translation", "explanation", "learning_tip"):
                    current = sections[section_name]
                    previous = visible_sections[section_name]
                    if current is None or current == previous:
                        continue
                    if current.startswith(previous):
                        delta = current[len(previous) :]
                    else:
                        delta = current
                    visible_sections[section_name] = current
                    if delta:
                        self.stream_chunk.emit(section_name, delta)
                terms = extract_stream_terms(raw_response)
                if len(terms) > emitted_terms:
                    emitted_terms = len(terms)
                    self.stream_terms.emit(terms)
        except AIClientError as exc:
            message = f"AI 解释失败: {exc}"
            self.status.emit(message)
            self.completed.emit(
                self._fail_payload(
                    source_text=source_text,
                    message=message,
                    partial=extract_stream_sections(raw_response),
                )
            )
            return
        except Exception as exc:
            message = f"AI 解释失败: {exc}"
            self.status.emit(message)
            self.completed.emit(
                self._fail_payload(
                    source_text=source_text,
                    message=message,
                    partial=extract_stream_sections(raw_response),
                )
            )
            return

        partial_response = False
        try:
            result = parse_ai_result(parse_json_object(raw_response))
        except AIClientError as exc:
            sections = extract_stream_sections(raw_response)
            explanation = str(sections.get("explanation") or "").strip()
            translation = str(sections.get("translation") or "").strip()
            if not explanation and not translation:
                message = f"AI 解释失败: {exc}"
                self.status.emit(message)
                self.completed.emit(
                    self._fail_payload(
                        source_text=source_text,
                        message=message,
                        partial={"translation": "", "explanation": ""},
                    )
                )
                return
            partial_response = True
            result = AIResult(
                explanation=explanation or translation,
                translation=translation if explanation else "",
                tags=["未完整解析"],
            )

        try:
            payload = self._persist_result(source_text, result, failed=False)
        except Exception as exc:
            message = f"保存历史记录失败: {exc}"
            self.status.emit(message)
            self.completed.emit(
                self._fail_payload(
                    source_text=source_text,
                    message=message,
                    partial=extract_stream_sections(raw_response),
                )
            )
            return
        if partial_response:
            payload["partial_response"] = True
        self.status.emit("完成")
        self.completed.emit(payload)

    def _fail_payload(
        self,
        source_text: str,
        message: str,
        partial: dict[str, str | None],
    ) -> dict:
        partial_text = str(partial.get("explanation") or "").strip()
        partial_translation = str(partial.get("translation") or "").strip()
        result = AIResult(
            translation=partial_translation,
            explanation=partial_text,
            tags=["待处理"],
        )
        try:
            payload = self._persist_result(source_text, result, failed=True)
        except Exception as exc:
            return {
                "error": f"{message}（保存失败: {exc}）",
                "source_text": source_text,
            }
        payload["error"] = message
        payload["partial_translation"] = partial_translation
        payload["partial_explanation"] = partial_text
        return payload

    def _cleanup_screenshot(self) -> None:
        """When the user disabled screenshot saving, the file must not survive —
        regardless of whether OCR / AI succeeded or failed."""
        if self.settings.save_screenshots or not self.image_path:
            return
        try:
            Path(self.image_path).unlink(missing_ok=True)
        except OSError:
            return None

    def _persist_result(
        self,
        source_text: str,
        result: AIResult,
        *,
        failed: bool,
    ) -> dict:
        term_dicts = _term_dicts(result)
        stored_image_path = self.image_path
        if not self.settings.save_screenshots:
            self._cleanup_screenshot()
            stored_image_path = ""

        category = auto_categorize(source_text, result.tags)
        configured_domain = _resolve_term_domain(self.settings, self.history_store)
        domain = _resolve_capture_domain(
            self.settings,
            self.history_store,
            source_text,
            result,
        )
        detected_domain = detect_domain(source_text)
        detected_scene = detect_scene(source_text)
        detected_clean = "" if detected_domain == "其他" else detected_domain
        scene_clean = "" if detected_scene == "通用" else detected_scene
        direction_conflict = bool(
            configured_domain not in ("通用", "")
            and detected_clean
            and detected_clean != configured_domain
        )
        direction_hint = {
            "detected_domain": detected_clean,
            "detected_scene": scene_clean,
            "current_domain": configured_domain,
            "conflict": direction_conflict,
        }
        if self.capture_id is not None:
            self.history_store.update_capture(
                self.capture_id,
                translation=result.translation,
                explanation=result.explanation,
                tags=result.tags,
                category=category,
                domain=domain,
            )
            conversation_id = self.history_store.get_conversation_id_for_capture(
                self.capture_id
            )
            capture_id = self.capture_id
        else:
            capture_id = self.history_store.save_capture(
                image_path=stored_image_path,
                source_text=source_text,
                translation=result.translation,
                explanation=result.explanation,
                tags=result.tags,
                category=category,
                domain=domain,
            )
            conversation_id = self.history_store.create_conversation(
                capture_id=capture_id,
                title=(source_text or result.explanation or "截图解释")[:80],
            )
            self.history_store.add_message(
                conversation_id, "user", source_text, mode="capture"
            )
        self.history_store.upsert_terms(
            term_dicts,
            domain=domain,
            capture_id=capture_id,
        )
        if result.learning_tip.strip():
            self.history_store.save_learning_tip(
                capture_id=capture_id,
                content=result.learning_tip.strip(),
                tip_type="followup",
                domain=domain,
                context_id=self.settings.current_context_id,
            )
        if not failed and conversation_id:
            self.history_store.add_message(
                conversation_id,
                "assistant",
                json.dumps(
                    {
                        "translation": result.translation,
                        "explanation": result.explanation,
                        "terms": term_dicts,
                        "tags": result.tags,
                        "learning_tip": result.learning_tip,
                    },
                    ensure_ascii=False,
                ),
                mode="retry" if self.capture_id is not None else "default",
            )
        return {
            "capture_id": capture_id,
            "conversation_id": conversation_id,
            "image_path": stored_image_path,
            "source_text": source_text,
            "translation": result.translation,
            "explanation": result.explanation,
            "terms": term_dicts,
            "tags": result.tags,
            "category": category,
            "learning_tip": result.learning_tip,
            "direction_hint": direction_hint,
        }


class FollowupWorker(QThread):
    status = Signal(str)
    stream_chunk = Signal(str, str)
    completed = Signal(dict)

    def __init__(
        self,
        source_text: str,
        question: str,
        settings: AppSettings,
        history_store: HistoryStore,
        conversation_id: int | None,
        capture_id: int | None = None,
        mode: str = "custom",
    ) -> None:
        super().__init__()
        self.source_text = source_text
        self.question = question
        self.settings = settings
        self.history_store = history_store
        self.conversation_id = conversation_id
        self.capture_id = capture_id
        self.mode = mode

    def run(self) -> None:
        if not self.conversation_id and self.capture_id:
            self.conversation_id = self.history_store.create_conversation(
                self.capture_id,
                title=(self.source_text or self.question)[:80],
            )
        history = []
        if self.conversation_id:
            history = [
                {"role": message.role, "content": message.content}
                for message in self.history_store.list_messages(self.conversation_id, limit=12)
            ]

        self.status.emit("正在追问...")
        raw_response = ""
        visible_sections = {"translation": "", "explanation": ""}
        try:
            client = AIClient(self.settings)
            for chunk in client.stream_followup(
                source_text=self.source_text,
                question=self.question,
                history=history,
                mode=self.mode,
            ):
                raw_response += chunk
                sections = extract_stream_sections(raw_response)
                for section_name in ("translation", "explanation"):
                    current = sections[section_name]
                    previous = visible_sections[section_name]
                    if current is None or current == previous:
                        continue
                    if current.startswith(previous):
                        delta = current[len(previous) :]
                    else:
                        delta = current
                    visible_sections[section_name] = current
                    if delta:
                        self.stream_chunk.emit(section_name, delta)
        except AIClientError as exc:
            self.completed.emit({"error": f"追问失败: {exc}"})
            return
        except Exception as exc:
            self.completed.emit({"error": f"追问失败: {exc}"})
            return

        partial_response = False
        try:
            result = parse_ai_result(parse_json_object(raw_response))
        except AIClientError as exc:
            sections = extract_stream_sections(raw_response)
            explanation = str(sections.get("explanation") or "").strip()
            translation = str(sections.get("translation") or "").strip()
            if not explanation and not translation:
                self.completed.emit({"error": f"追问失败: {exc}"})
                return
            partial_response = True
            result = AIResult(
                explanation=explanation or translation,
                translation=translation if explanation else "",
                tags=["未完整解析"],
            )

        term_dicts = _term_dicts(result)
        if self.conversation_id:
            self.history_store.add_message(
                self.conversation_id, "user", self.question, mode=self.mode
            )
            self.history_store.add_message(
                self.conversation_id,
                "assistant",
                json.dumps(
                    {
                        "translation": result.translation,
                        "explanation": result.explanation,
                        "terms": term_dicts,
                        "tags": result.tags,
                        "learning_tip": result.learning_tip,
                    },
                    ensure_ascii=False,
                ),
                mode=self.mode,
            )
            self.history_store.upsert_terms(
                term_dicts,
                domain=_resolve_term_domain(self.settings, self.history_store),
                capture_id=self.capture_id,
            )
            if result.learning_tip.strip() and self.capture_id:
                self.history_store.save_learning_tip(
                    capture_id=self.capture_id,
                    content=result.learning_tip.strip(),
                    tip_type="followup",
                    domain=_resolve_term_domain(self.settings, self.history_store),
                    context_id=self.settings.current_context_id,
                )

        payload = {
            "conversation_id": self.conversation_id,
            "source_text": self.source_text,
            "question": self.question,
            "translation": result.translation,
            "explanation": result.explanation,
            "terms": term_dicts,
            "tags": result.tags,
            "learning_tip": result.learning_tip,
        }
        if partial_response:
            payload["partial_response"] = True
        self.status.emit("完成")
        self.completed.emit(payload)


class SummaryWorker(QThread):
    """Compress pasted text into a background-summary anchor (best effort)."""

    completed = Signal(dict)

    def __init__(self, source_text: str, settings: AppSettings, max_chars: int = 400) -> None:
        super().__init__()
        self.source_text = source_text
        self.settings = settings
        self.max_chars = max_chars

    def run(self) -> None:
        try:
            summary = AIClient(self.settings).generate_summary(
                self.source_text, max_chars=self.max_chars
            )
        except Exception as exc:
            self.completed.emit({"error": f"生成背景要点失败: {exc}"})
            return
        self.completed.emit({"summary": summary})


class DigestWorker(QThread):
    """Merge recent learning items into a direction's background summary (自沉淀)."""

    completed = Signal(dict)

    def __init__(
        self,
        existing_summary: str,
        new_items: str,
        settings: AppSettings,
        last_capture_id: int = 0,
    ) -> None:
        super().__init__()
        self.existing_summary = existing_summary
        self.new_items = new_items
        self.settings = settings
        self.last_capture_id = last_capture_id

    def run(self) -> None:
        try:
            summary = AIClient(self.settings).merge_summary(
                self.existing_summary, self.new_items
            )
        except Exception as exc:
            self.completed.emit({"error": f"生成背景要点失败: {exc}"})
            return
        self.completed.emit(
            {"summary": summary, "last_capture_id": self.last_capture_id}
        )


