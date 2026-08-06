"""学习概览页：会话学习视图（会话列表 + 会话流 + 上下文面板 + 学习上下文切换）。

新建学习入口（截图/文本）在工作台页，本页负责查看与深入学习。
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.history_store import HistoryStore
from app.services.settings import SettingsService
from app.ui.message_render import DOC_STYLESHEET, build_result_html, render_lines
from app.ui.theme import BG, BLUE, BORDER, BORDER_LIGHT, MUTED
from app.ui.workers import FollowupWorker

FILTERS = ["全部", "今天", "本周", "有追问"]


def _compact(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def _session_text(record) -> str:
    title = (record.source_text or record.translation or "截图").strip().splitlines()
    title = title[0] if title else "截图"
    preview = record.translation or record.explanation or record.source_text
    category = f"  [{record.category}]" if record.category else ""
    return f"{_compact(title, 30)}\n{_compact(preview, 34)}{category}"


class OverviewPage(QWidget):
    open_popup = Signal(int)

    def __init__(self, history_store: HistoryStore, settings_service: SettingsService) -> None:
        super().__init__()
        self.history_store = history_store
        self.settings_service = settings_service
        self.current_capture = None
        self.current_conversation_id = None
        self._followup_worker = None
        self._followup_stream: dict[str, str] = {}
        self._active_filter = "全部"
        self._domain_filter = ""
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        top_bar = QWidget()
        top_bar.setStyleSheet(f"background: {BG};")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(18, 12, 18, 4)
        top_layout.addStretch(1)
        self.domain_filter_label = QLabel("记录筛选")
        self.domain_filter_label.setStyleSheet(f"color: {MUTED}; font-size: 13px;")
        top_layout.addWidget(self.domain_filter_label)
        self.domain_filter_combo = QComboBox()
        self.domain_filter_combo.setMinimumWidth(180)
        self.domain_filter_combo.setMaxVisibleItems(8)
        self.domain_filter_combo.setToolTip("按内容领域筛选左侧历史记录")
        self.domain_filter_combo.currentIndexChanged.connect(self._on_domain_filter_selected)
        top_layout.addWidget(self.domain_filter_combo)
        layout.addWidget(top_bar)

        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(0)
        columns.addWidget(self._build_session_panel())
        columns.addWidget(self._build_center_panel(), 1)
        columns.addWidget(self._build_context_panel())
        layout.addLayout(columns, 1)

        self.setStyleSheet(
            "QListWidget::item { padding: 7px 8px; }"
            "QListWidget::item:selected { background: #eff4ff; color: #101828; }"
        )

    def _build_session_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(280)
        panel.setStyleSheet(f"background: #ffffff; border-right: 1px solid {BORDER};")
        v = QVBoxLayout(panel)
        v.setContentsMargins(10, 12, 10, 12)
        v.setSpacing(8)

        v.addWidget(QLabel("会话"))

        self.session_search = QLineEdit()
        self.session_search.setPlaceholderText("搜索记录...")
        self.session_search.setStyleSheet(f"padding: 6px 8px; border: 1px solid {BORDER}; border-radius: 8px;")
        self.session_search.returnPressed.connect(self.refresh_sessions)
        v.addWidget(self.session_search)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.filter_buttons: dict[str, QPushButton] = {}
        for label in FILTERS:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setChecked(label == self._active_filter)
            button.setStyleSheet(
                f"QPushButton {{ border: 1px solid {BORDER}; border-radius: 16px; padding: 3px 12px; background: #fff; }}"
                f"QPushButton:checked {{ background: {BLUE}; color: #fff; border-color: {BLUE}; }}"
            )
            button.clicked.connect(lambda checked=False, l=label: self._apply_filter(l))
            self.filter_buttons[label] = button
            chips.addWidget(button)
        v.addLayout(chips)

        self.session_list = QListWidget()
        self.session_list.itemClicked.connect(self._on_session_clicked)
        v.addWidget(self.session_list, 1)
        return panel

    def _build_center_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet(f"background: {BG};")
        v = QVBoxLayout(panel)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(8)

        self.header_title = QLabel("选择左侧会话开始学习")
        self.header_title.setStyleSheet("font-size: 16px; ")
        self.header_meta = QLabel("")
        self.header_meta.setStyleSheet(f"color: {MUTED}; ")
        v.addWidget(self.header_title)
        v.addWidget(self.header_meta)

        self.message_browser = QTextBrowser()
        self.message_browser.setOpenExternalLinks(False)
        self.message_browser.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.message_browser.document().setDocumentMargin(12)
        self.message_browser.document().setDefaultStyleSheet(DOC_STYLESHEET)
        base_font = self.message_browser.font()
        base_font.setPixelSize(13)
        self.message_browser.setFont(base_font)
        self.message_browser.setStyleSheet(
            f"QTextBrowser {{ background: transparent; border: none; }}"
        )
        v.addWidget(self.message_browser, 1)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.followup_input = QLineEdit()
        self.followup_input.setPlaceholderText("继续追问...")
        self.followup_input.setStyleSheet(
            f"padding: 8px 10px; border: 1px solid {BORDER}; border-radius: 8px; background: #fff;"
        )
        self.followup_input.returnPressed.connect(self.send_followup)
        send_button = QPushButton("发送")
        send_button.setStyleSheet(
            f"background: {BLUE}; color: #fff; border: 0; border-radius: 8px; padding: 0 16px; "
        )
        send_button.clicked.connect(self.send_followup)
        input_row.addWidget(self.followup_input, 1)
        input_row.addWidget(send_button)
        v.addLayout(input_row)
        return panel

    def _build_context_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(250)
        panel.setStyleSheet(f"background: #ffffff; border-left: 1px solid {BORDER};")
        v = QVBoxLayout(panel)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(8)

        v.addWidget(self._label("上下文"))

        self.context_image = QLabel("截图预览")
        self.context_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.context_image.setFixedHeight(110)
        self.context_image.setStyleSheet(f"background: {BORDER_LIGHT}; border-radius: 8px; color: #9ca3af; ")
        v.addWidget(self.context_image)

        self.context_source = QTextEdit()
        self.context_source.setReadOnly(True)
        self.context_source.setPlaceholderText("OCR 原文")
        self.context_source.setMaximumHeight(150)
        self.context_source.setStyleSheet(f"border: 1px solid {BORDER}; border-radius: 8px; ")
        v.addWidget(self.context_source)

        v.addWidget(self._label("术语"))
        self.context_terms = QListWidget()
        self.context_terms.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.context_terms.setMaximumHeight(180)
        v.addWidget(self.context_terms, 1)

        self.context_tags = QLabel("")
        self.context_tags.setWordWrap(True)
        self.context_tags.setStyleSheet(f"color: {MUTED}; ")
        v.addWidget(self.context_tags)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        copy_button = QPushButton("复制")
        copy_button.clicked.connect(self.copy_result)
        popup_button = QPushButton("弹窗")
        popup_button.clicked.connect(self._open_popup)
        delete_button = QPushButton("删除")
        delete_button.setStyleSheet("color: #b54747;")
        delete_button.clicked.connect(self._delete_capture)
        for button in (copy_button, popup_button, delete_button):
            button.setStyleSheet(
                f"{button.styleSheet()}border: 1px solid {BORDER}; border-radius: 8px; padding: 5px 10px; background: #fff; "
            )
        actions.addWidget(copy_button)
        actions.addWidget(popup_button)
        actions.addWidget(delete_button)
        v.addLayout(actions)
        return panel

    @staticmethod
    def _label(text: str) -> QLabel:
        return QLabel(text)

    def refresh(self) -> None:
        self.refresh_domain_filter()
        self.refresh_sessions()

    def _apply_filter(self, label: str) -> None:
        self._active_filter = label
        for name, button in self.filter_buttons.items():
            button.setChecked(name == label)
        self.refresh_sessions()

    def refresh_sessions(self) -> None:
        query = self.session_search.text().strip()
        filter_label = self._active_filter
        records = self.history_store.search_captures_advanced(
            query=query,
            domain=self._domain_filter,
            has_followup=(filter_label == "有追问"),
            limit=1000,
        )
        if filter_label == "今天":
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            records = [r for r in records if (r.created_at or "").startswith(today)]
        elif filter_label == "本周":
            from datetime import datetime, timedelta
            week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%Y-%m-%d")
            records = [r for r in records if (r.created_at or "")[:10] >= week_start]

        self.session_list.clear()
        for record in records:
            item = QListWidgetItem(_session_text(record))
            item.setData(Qt.ItemDataRole.UserRole, record.id)
            self.session_list.addItem(item)

    def _on_session_clicked(self, item: QListWidgetItem) -> None:
        capture_id = item.data(Qt.ItemDataRole.UserRole)
        if capture_id:
            self.select_capture(int(capture_id))

    def select_capture(self, capture_id: int) -> None:
        record = self.history_store.get_capture(capture_id)
        if record is None:
            return
        if self._followup_worker and self._followup_worker.isRunning():
            return
        self.current_capture = record
        self.current_conversation_id = self.history_store.get_conversation_id_for_capture(capture_id)
        self._followup_stream = {}
        self.followup_input.setEnabled(True)

        title = (record.source_text or record.translation or "截图").strip().splitlines()
        self.header_title.setText(_compact(title[0] if title else "截图", 50))
        meta = f"{record.created_at}"
        if record.category:
            meta += f"  ·  {record.category}"
        self.header_meta.setText(meta)

        self.context_source.setPlainText(record.source_text or "（无）")
        self._load_context_image(record.image_path or "")
        self._render_conversation()
        self._load_context_terms()

    def _load_context_image(self, image_path: str) -> None:
        self.context_image.setPixmap(QPixmap())
        if image_path and Path(image_path).exists():
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self.context_image.width(), self.context_image.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.context_image.setPixmap(scaled)
                self.context_image.setText("")
                return
        self.context_image.setText("无截图")

    def _load_context_terms(self) -> None:
        self.context_terms.clear()
        terms = self._capture_terms()
        for term in terms[:8]:
            item = QListWidgetItem(f"{term.get('term', '')} · {term.get('chinese_name', '')}")
            self.context_terms.addItem(item)

    def _capture_terms(self) -> list[dict]:
        if self.current_capture is None:
            return []
        conversation_id = self.current_conversation_id
        if not conversation_id:
            return []
        for message in self.history_store.list_messages(conversation_id, limit=50):
            if message.role != "assistant":
                continue
            try:
                data = json.loads(message.content)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(data.get("terms"), list):
                return data["terms"]
        return []

    def _render_conversation(self) -> None:
        if self.current_capture is None:
            self.message_browser.setHtml("")
            return
        record = self.current_capture
        parts: list[str] = []
        parts.append('<div class="meta-label">原文</div>')
        parts.append(render_lines(record.source_text or "（无）"))
        parts.append(build_result_html(
            translation=record.translation or "",
            explanation=record.explanation or "",
            source_text=record.source_text or "",
            terms=self._capture_terms(),
        ))

        conversation_id = self.current_conversation_id
        if conversation_id:
            for message in self.history_store.list_messages(conversation_id, limit=100):
                if message.role == "user" and message.mode != "capture":
                    parts.append('<div class="meta-label">追问</div>')
                    parts.append(render_lines(message.content))
                elif message.role == "assistant" and message.mode not in ("default", "retry"):
                    try:
                        data = json.loads(message.content)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    parts.append(build_result_html(
                        translation=str(data.get("translation") or ""),
                        explanation=str(data.get("explanation") or ""),
                        terms=data.get("terms") or [],
                    ))

        pending = self._followup_stream
        if pending.get("question"):
            parts.append('<div class="meta-label">追问</div>')
            parts.append(render_lines(pending["question"]))
            if pending.get("explanation"):
                parts.append(build_result_html(
                    translation=pending.get("translation", ""),
                    explanation=pending.get("explanation", ""),
                ))
            else:
                parts.append('<div class="body-line" style="color:#8995a5;">思考中…</div>')

        self.message_browser.setHtml("".join(parts))
        cursor = self.message_browser.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.message_browser.setTextCursor(cursor)

    def send_followup(self) -> None:
        if self.current_capture is None:
            return
        question = self.followup_input.text().strip()
        if not question:
            return
        if self._followup_worker and self._followup_worker.isRunning():
            return
        self._followup_stream = {"question": question, "translation": "", "explanation": ""}
        self.followup_input.clear()
        self.followup_input.setEnabled(False)
        self._render_conversation()
        self._followup_worker = FollowupWorker(
            source_text=self.current_capture.source_text,
            question=question,
            settings=self.settings_service.load(),
            history_store=self.history_store,
            conversation_id=self.current_conversation_id,
            capture_id=self.current_capture.id,
        )
        self._followup_worker.stream_chunk.connect(self._on_followup_chunk)
        self._followup_worker.completed.connect(self._on_followup_done)
        self._followup_worker.finished.connect(self._followup_worker.deleteLater)
        self._followup_worker.start()

    def _on_followup_chunk(self, section: str, chunk: str) -> None:
        if section in self._followup_stream:
            self._followup_stream[section] += chunk
            self._render_conversation()
            QApplication.processEvents()

    def _on_followup_done(self, payload: dict) -> None:
        self._followup_stream = {}
        if payload.get("error"):
            self.message_browser.insertHtml(
                f'<div class="body-line" style="color:#b54747;">{payload["error"]}</div>'
            )
        else:
            self.followup_input.setEnabled(True)
            self._render_conversation()
            self.refresh_sessions()

    def copy_result(self) -> None:
        QApplication.clipboard().setText(self.message_browser.toPlainText())

    def _open_popup(self) -> None:
        if self.current_capture is not None:
            self.open_popup.emit(self.current_capture.id)

    def _delete_capture(self) -> None:
        if self.current_capture is None:
            return
        reply = QMessageBox.question(
            self, "删除记录",
            "确定删除这条记录吗？不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.history_store.delete_capture(self.current_capture.id)
        self.current_capture = None
        self.current_conversation_id = None
        self.header_title.setText("选择左侧会话开始学习")
        self.header_meta.setText("")
        self.message_browser.setHtml("")
        self.context_source.clear()
        self.context_terms.clear()
        self.context_tags.setText("")
        self.context_image.setText("无截图")
        self.refresh()

    def refresh_domain_filter(self) -> None:
        counts = self.history_store.capture_domain_counts()
        available = {domain for domain, _ in counts}
        if self._domain_filter and self._domain_filter not in available:
            self._domain_filter = ""

        self.domain_filter_combo.blockSignals(True)
        self.domain_filter_combo.clear()
        self.domain_filter_combo.addItem(
            f"全部记录 ({sum(count for _, count in counts)})",
            "",
        )
        for domain, count in counts:
            self.domain_filter_combo.addItem(f"{domain} ({count})", domain)
        selected = self.domain_filter_combo.findData(self._domain_filter)
        self.domain_filter_combo.setCurrentIndex(max(0, selected))
        self.domain_filter_combo.blockSignals(False)

    def _on_domain_filter_selected(self, index: int) -> None:
        self._domain_filter = str(self.domain_filter_combo.itemData(index) or "")
        self.refresh_sessions()
