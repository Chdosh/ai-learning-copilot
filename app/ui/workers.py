from __future__ import annotations

from pathlib import Path
import json

from PySide6.QtCore import QThread, Signal

from app.services.ai_client import AIClient, AIClientError, AIResult
from app.services.categorizer import auto_categorize
from app.services.history_store import HistoryStore
from app.services.ocr import OCRError, OCRService
from app.services.settings import AppSettings


class CapturePipelineWorker(QThread):
    completed = Signal(dict)

    def __init__(
        self,
        image_path: str,
        settings: AppSettings,
        ocr_service: OCRService,
        history_store: HistoryStore,
    ) -> None:
        super().__init__()
        self.image_path = image_path
        self.settings = settings
        self.ocr_service = ocr_service
        self.history_store = history_store

    def run(self) -> None:
        source_text = ""
        ocr_error = ""
        try:
            source_text = self.ocr_service.extract_text(self.image_path)
        except OCRError as exc:
            ocr_error = str(exc)
        except Exception as exc:
            ocr_error = f"OCR 发生未知错误: {exc}"

        if source_text.strip():
            try:
                result = AIClient(self.settings).explain_text(source_text)
            except AIClientError as exc:
                result = AIResult.from_error(str(exc))
            except Exception as exc:
                result = AIResult.from_error(f"AI 解释失败: {exc}")
        else:
            message = ocr_error or "OCR 没有识别到文字。你可以手动复制文字后再使用解释功能。"
            result = AIResult.from_error(message)

        term_dicts = [
            {
                "term": term.term,
                "chinese_name": term.chinese_name,
                "beginner_explanation": term.beginner_explanation,
                "examples": term.examples,
            }
            for term in result.terms
        ]
        stored_image_path = self.image_path
        should_delete_screenshot = (
            not self.settings.save_screenshots
            and source_text.strip()
            and not ocr_error
        )
        if should_delete_screenshot:
            try:
                Path(self.image_path).unlink(missing_ok=True)
                stored_image_path = ""
            except OSError:
                stored_image_path = self.image_path

        category = auto_categorize(source_text, result.tags)
        capture_id = self.history_store.save_capture(
            image_path=stored_image_path,
            source_text=source_text,
            translation=result.translation,
            explanation=result.explanation,
            tags=result.tags,
            category=category,
        )
        self.history_store.upsert_terms(term_dicts)
        conversation_id = self.history_store.create_conversation(
            capture_id=capture_id,
            title=(source_text or result.explanation or "截图解释")[:80],
        )
        if source_text.strip():
            self.history_store.add_message(conversation_id, "user", source_text, mode="capture")
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
            mode="default",
        )

        self.completed.emit(
            {
                "capture_id": capture_id,
                "conversation_id": conversation_id,
                "image_path": stored_image_path,
                "source_text": source_text,
                "ocr_error": ocr_error,
                "translation": result.translation,
                "explanation": result.explanation,
                "terms": term_dicts,
                "tags": result.tags,
                "category": category,
                "learning_tip": result.learning_tip,
            }
        )


class TextExplainWorker(QThread):
    completed = Signal(dict)

    def __init__(self, source_text: str, settings: AppSettings, mode: str = "default") -> None:
        super().__init__()
        self.source_text = source_text
        self.settings = settings
        self.mode = mode

    def run(self) -> None:
        try:
            result = AIClient(self.settings).explain_text(self.source_text, mode=self.mode)
        except AIClientError as exc:
            result = AIResult.from_error(str(exc))
        except Exception as exc:
            result = AIResult.from_error(f"AI 解释失败: {exc}")

        self.completed.emit(
            {
                "capture_id": None,
                "image_path": "",
                "source_text": self.source_text,
                "translation": result.translation,
                "explanation": result.explanation,
                "terms": [
                    {
                        "term": term.term,
                        "chinese_name": term.chinese_name,
                        "beginner_explanation": term.beginner_explanation,
                        "examples": term.examples,
                    }
                    for term in result.terms
                ],
                "tags": result.tags,
                "learning_tip": result.learning_tip,
            }
        )


class FollowupWorker(QThread):
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

        try:
            result = AIClient(self.settings).ask_followup(
                source_text=self.source_text,
                question=self.question,
                history=history,
                mode=self.mode,
            )
        except AIClientError as exc:
            result = AIResult.from_error(str(exc))
        except Exception as exc:
            result = AIResult.from_error(f"AI 追问失败: {exc}")

        term_dicts = [
            {
                "term": term.term,
                "chinese_name": term.chinese_name,
                "beginner_explanation": term.beginner_explanation,
                "examples": term.examples,
            }
            for term in result.terms
        ]
        if self.conversation_id:
            self.history_store.add_message(self.conversation_id, "user", self.question, mode=self.mode)
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
            self.history_store.upsert_terms(term_dicts)

        self.completed.emit(
            {
                "conversation_id": self.conversation_id,
                "source_text": self.source_text,
                "question": self.question,
                "translation": result.translation,
                "explanation": result.explanation,
                "terms": term_dicts,
                "tags": result.tags,
                "learning_tip": result.learning_tip,
            }
        )


def normalize_image_path(path: str | Path) -> str:
    return str(Path(path))
