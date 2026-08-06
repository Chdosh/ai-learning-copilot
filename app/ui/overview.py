"""学习概览页：会话学习视图（会话列表 + 会话流 + 术语/标签抽屉）。

新建学习入口（截图/文本）在工作台页，本页负责查看与深入学习。
布局：左侧会话索引（固定 216px） + 右侧会话流（阅读面）。
原图内联在会话流顶部，术语/标签在底部折叠抽屉，操作在页头菜单。
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.history_store import HistoryStore
from app.services.settings import SettingsService
from app.ui.message_render import DOC_STYLESHEET, build_result_html, render_lines, render_source_block
from app.ui.theme import (
    BG,
    BORDER,
    BORDER_LIGHT,
    CARD,
    DANGER,
    DISABLED,
    FONT_BODY,
    FONT_MICRO,
    FONT_TITLE,
    MUTED,
    PRIMARY,
    PRIMARY_SOFT,
    RADIUS_MD,
    TEXT,
    button_qss,
    chip_qss,
)
from app.ui.workers import FollowupWorker

_GHOST_QSS = button_qss()


class _ClickableLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, event):  # noqa: N802
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


def _compact(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def _session_text(record) -> str:
    title = (record.source_text or record.translation or "截图").strip().splitlines()
    title = title[0] if title else "截图"
    created = (record.created_at or "").replace("T", " ")[:16]
    category = f" [{record.category}]" if record.category else ""
    return f"{_compact(title, 22)}\n{created}{category}"


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
        top_layout.setContentsMargins(16, 8, 16, 4)
        self.direction_label = QLabel("")
        self.direction_label.setStyleSheet(
            f"color: {MUTED}; font-size: {FONT_MICRO}; background: {BORDER_LIGHT};"
            f"border-radius: {RADIUS_MD}; padding: 2px 8px;"
        )
        top_layout.addWidget(self.direction_label)
        top_layout.addStretch(1)

        self.actions_menu_button = QPushButton("操作 ▾")
        self.actions_menu_button.setStyleSheet(_GHOST_QSS)
        self.actions_menu_button.setEnabled(False)
        self.actions_menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.actions_menu = QMenu(self.actions_menu_button)
        self.actions_menu.addAction("复制结果", self.copy_result)
        self.actions_menu.addAction("打开弹窗", self._open_popup)
        self.actions_menu.addSeparator()
        delete_action = self.actions_menu.addAction("删除记录")
        delete_action.triggered.connect(self._delete_capture)
        self.actions_menu_button.clicked.connect(self._show_actions_menu)
        top_layout.addWidget(self.actions_menu_button)
        layout.addWidget(top_bar)

        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(0)
        columns.addWidget(self._build_session_panel())
        columns.addWidget(self._build_center_panel(), 1)
        layout.addLayout(columns, 1)

        self.setStyleSheet(
            "QListWidget::item { padding: 7px 8px; }"
            f"QListWidget::item:selected {{ background: {PRIMARY_SOFT}; color: {TEXT}; }}"
        )

    def _show_actions_menu(self) -> None:
        self.actions_menu.exec(self.actions_menu_button.mapToGlobal(self.actions_menu_button.rect().bottomLeft()))

    def _build_session_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(216)
        panel.setStyleSheet(f"background: {CARD};")
        v = QVBoxLayout(panel)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        v.addWidget(QLabel("会话"))

        self.session_search = QLineEdit()
        self.session_search.setPlaceholderText("搜索记录...")
        self.session_search.setStyleSheet(
            f"padding: 3px 2px; border: 1px solid {BORDER}; border-radius: {RADIUS_MD};"
        )
        self.session_search.returnPressed.connect(self.refresh_sessions)
        v.addWidget(self.session_search)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.time_filter_combo = QComboBox()
        self.time_filter_combo.addItems(["全部", "今天", "本周"])
        self.time_filter_combo.currentIndexChanged.connect(self._on_time_filter_changed)
        filter_row.addWidget(self.time_filter_combo, 1)
        self.domain_filter_combo = QComboBox()
        self.domain_filter_combo.setMaxVisibleItems(8)
        self.domain_filter_combo.setToolTip("按内容领域筛选左侧历史记录")
        self.domain_filter_combo.currentIndexChanged.connect(self._on_domain_filter_selected)
        filter_row.addWidget(self.domain_filter_combo, 1)
        v.addLayout(filter_row)

        followup_row = QHBoxLayout()
        followup_row.setSpacing(8)
        self.followup_filter_toggle = QPushButton("有追问")
        self.followup_filter_toggle.setCheckable(True)
        self.followup_filter_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.followup_filter_toggle.setStyleSheet(chip_qss())
        self.followup_filter_toggle.toggled.connect(self._on_followup_filter_toggled)
        followup_row.addWidget(self.followup_filter_toggle)
        followup_row.addStretch(1)
        v.addLayout(followup_row)

        self.session_list = QListWidget()
        self.session_list.itemClicked.connect(self._on_session_clicked)
        v.addWidget(self.session_list, 1)
        return panel

    def _build_center_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet(f"background: {BG};")
        v = QVBoxLayout(panel)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)

        self.center_image = _ClickableLabel("")
        self.center_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_image.setFixedHeight(80)
        self.center_image.setVisible(False)
        self.center_image.setStyleSheet(
            f"background: {BORDER_LIGHT}; border-radius: {RADIUS_MD}; color: {DISABLED}; font-size: {FONT_MICRO};"
        )
        self.center_image.setCursor(Qt.CursorShape.PointingHandCursor)
        self.center_image.setToolTip("点击查看原图")
        self.center_image.clicked.connect(self._open_popup)
        v.addWidget(self.center_image)

        self.header_title = QLabel("选择左侧会话开始学习")
        self.header_title.setStyleSheet(f"font-size: {FONT_TITLE}; ")
        self.header_meta = QLabel("")
        self.header_meta.setStyleSheet(f"color: {MUTED}; ")
        self.header_meta.setWordWrap(True)
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

        terms_label = QLabel("术语")
        terms_label.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        v.addWidget(terms_label)
        self.context_terms = QListWidget()
        self.context_terms.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.context_terms.setMaximumHeight(80)
        self.context_terms.setStyleSheet("QListWidget { background: transparent; }")
        v.addWidget(self.context_terms)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.followup_input = QLineEdit()
        self.followup_input.setPlaceholderText("继续追问...")
        self.followup_input.setStyleSheet(
            f"padding: 8px 10px; border: 1px solid {BORDER}; border-radius: {RADIUS_MD}; background: {CARD};"
        )
        self.followup_input.returnPressed.connect(self.send_followup)
        send_button = QPushButton("发送")
        send_button.setObjectName("primaryButton")
        send_button.setStyleSheet(
            f"QPushButton#primaryButton {{ background: {PRIMARY}; color: #fff; border: 0; "
            f"border-radius: {RADIUS_MD}; padding: 0 16px; }}"
        )
        send_button.clicked.connect(self.send_followup)
        input_row.addWidget(self.followup_input, 1)
        input_row.addWidget(send_button)
        v.addLayout(input_row)
        return panel

    def refresh(self) -> None:
        self.refresh_domain_filter()
        self.refresh_direction_label()
        self.refresh_sessions()

    def refresh_direction_label(self) -> None:
        settings = self.settings_service.load()
        name = "通用"
        if settings.current_context_id is not None:
            context = self.history_store.get_context(settings.current_context_id)
            if context is not None:
                name = context.name
        self.direction_label.setText(f"学习方向：{name}")

    def _on_time_filter_changed(self, index: int) -> None:
        self._active_filter = self.time_filter_combo.itemText(index)
        self.refresh_sessions()

    def _on_followup_filter_toggled(self, checked: bool) -> None:
        self.refresh_sessions()

    def refresh_sessions(self) -> None:
        query = self.session_search.text().strip()
        time_label = self._active_filter
        has_followup = self.followup_filter_toggle.isChecked()
        records = self.history_store.search_captures_advanced(
            query=query,
            domain=self._domain_filter,
            has_followup=has_followup,
            limit=1000,
        )
        if time_label == "今天":
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            records = [r for r in records if (r.created_at or "").startswith(today)]
        elif time_label == "本周":
            from datetime import datetime, timedelta
            week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%Y-%m-%d")
            records = [r for r in records if (r.created_at or "")[:10] >= week_start]

        self.session_list.clear()
        for record in records:
            item = QListWidgetItem(_session_text(record))
            item.setData(Qt.ItemDataRole.UserRole, record.id)
            self.session_list.addItem(item)

        if records:
            self.select_capture(records[0].id)

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
        self.actions_menu_button.setEnabled(True)

        title = (record.source_text or record.translation or "截图").strip().splitlines()
        self.header_title.setText(_compact(title[0] if title else "截图", 50))
        meta = f"{record.created_at}".replace("T", " ")[:16]
        if record.category:
            meta += f"  ·  {record.category}"
        if record.tags:
            meta += f"  ·  {'、'.join(record.tags[:5])}"
        self.header_meta.setText(meta)

        self._load_center_image(record.image_path or "")
        self._render_conversation()
        self._load_context_terms()

    def _load_center_image(self, image_path: str) -> None:
        self.center_image.setPixmap(QPixmap())
        self.center_image.setVisible(False)
        if image_path and Path(image_path).exists():
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self.center_image.width(), self.center_image.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.center_image.setPixmap(scaled)
                self.center_image.setVisible(True)
                return

    def _load_context_terms(self) -> None:
        self.context_terms.clear()
        terms = self._capture_terms()
        for term in terms[:8]:
            item = QListWidgetItem(f"{term.get('term', '')} · {term.get('chinese_name', '')}")
            self.context_terms.addItem(item)
        if not terms:
            placeholder = QListWidgetItem("（无术语）")
            placeholder.setForeground(__import__("PySide6.QtGui", fromlist=["QColor"]).QColor(MUTED))
            self.context_terms.addItem(placeholder)

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
        parts.append(render_source_block(record.source_text or ""))
        parts.append(build_result_html(
            translation=record.translation or "",
            explanation=record.explanation or "",
            source_text=record.source_text or "",
            terms=[],
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
                parts.append(f'<div class="body-line" style="color:{MUTED};">思考中…</div>')

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
                f'<div class="body-line" style="color:{DANGER};">{payload["error"]}</div>'
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
        self.center_image.setPixmap(QPixmap())
        self.center_image.setVisible(False)
        self.context_terms.clear()
        self.actions_menu_button.setEnabled(False)
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
