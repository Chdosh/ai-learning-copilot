"""Compact floating window for streaming capture results."""
from __future__ import annotations

import html

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QKeyEvent,
    QMouseEvent,
    QTextOption,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.services.ai_client import compact_line_breaks
from app.ui.message_render import (
    DOC_STYLESHEET,
    build_result_html,
    compose_html,
    render_lines,
    split_lead,
)
from app.ui.theme import BLUE, BLUE_DARK, BLUE_SOFT, BORDER, BORDER_LIGHT, MUTED, TEXT


class ResultWindow(QWidget):
    request_followup = Signal(str, str, str)
    request_retry = Signal(int)
    open_history = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.payload: dict = {}
        self._drag_offset: QPoint | None = None
        self._stream_buffers = {"translation": "", "explanation": "", "learning_tip": ""}
        self._followup_anchor: int | None = None
        self._followup_sections = {"translation": "", "explanation": ""}
        self._stream_terms: list[dict] = []
        self._source_text = ""
        self._fit_width_peak = 0
        self._fit_height_peak = 0
        self._busy = False
        self._loading = False
        self.setObjectName("resultWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setMinimumWidth(380)
        self.setMaximumWidth(760)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(6, 6, 6, 6)
        self.card = QFrame()
        self.card.setObjectName("resultCard")
        outer_layout.addWidget(self.card)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(31, 45, 61, 45))
        self.card.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(2)

        header = QHBoxLayout()
        header.setSpacing(4)
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("statusLabel")
        close_button = QPushButton("×")
        close_button.setObjectName("closeButton")
        close_button.setFixedSize(24, 20)
        close_button.clicked.connect(self.close)
        header.addWidget(self.status_label)
        header.addStretch()
        header.addWidget(close_button)
        layout.addLayout(header)

        self.text_browser = QTextBrowser()
        self.text_browser.setObjectName("resultBody")
        self.text_browser.setOpenExternalLinks(False)
        self.text_browser.setFrameShape(QFrame.Shape.NoFrame)
        self.text_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        base_font = self.text_browser.font()
        base_font.setPixelSize(13)
        self.text_browser.setFont(base_font)
        self.text_browser.document().setDocumentMargin(2)
        self.text_browser.setMinimumHeight(40)
        self.text_browser.setMaximumHeight(720)
        self.text_browser.document().setDefaultStyleSheet(DOC_STYLESHEET)
        self.text_browser.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.addWidget(self.text_browser)

        self.tip_toggle = QPushButton("▸ 补充说明")
        self.tip_toggle.setObjectName("tipToggle")
        self.tip_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tip_toggle.clicked.connect(self._toggle_tip)
        self.tip_toggle.hide()
        layout.addWidget(self.tip_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self.tip_content = QLabel()
        self.tip_content.setObjectName("tipContent")
        self.tip_content.setWordWrap(True)
        self.tip_content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.tip_content.hide()
        layout.addWidget(self.tip_content)

        actions = QHBoxLayout()
        actions.setSpacing(4)
        self.followup_input = QLineEdit()
        self.followup_input.setObjectName("followupInput")
        self.followup_input.setPlaceholderText("继续追问...")
        self.followup_input.returnPressed.connect(self._send_followup)
        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("primaryButton")
        self.send_button.clicked.connect(self._send_followup)
        self.retry_button = QPushButton("重试")
        self.retry_button.setObjectName("primaryButton")
        self.retry_button.clicked.connect(self._send_retry)
        self.retry_button.hide()
        more_button = QPushButton("···")
        more_button.setObjectName("moreButton")
        more_button.setFixedWidth(28)
        self.more_button = more_button
        more_menu = QMenu(more_button)
        more_menu.setObjectName("resultMenu")
        font_up = QAction("A+  加大字号", more_menu)
        font_up.triggered.connect(lambda: self.adjust_text_size(1))
        font_down = QAction("A-  缩小字号", more_menu)
        font_down.triggered.connect(lambda: self.adjust_text_size(-1))
        copy_action = QAction("复制结果", more_menu)
        copy_action.triggered.connect(self._copy_text)
        history_action = QAction("打开历史", more_menu)
        history_action.triggered.connect(self.open_history.emit)
        more_menu.addAction(font_up)
        more_menu.addAction(font_down)
        more_menu.addSeparator()
        more_menu.addAction(copy_action)
        more_menu.addAction(history_action)
        more_button.setMenu(more_menu)
        actions.addWidget(self.followup_input, 1)
        actions.addWidget(self.send_button)
        actions.addWidget(self.retry_button)
        actions.addWidget(more_button)
        layout.addLayout(actions)
        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"""
            QWidget#resultWindow {{
                background: transparent;
                color: {TEXT};
                font-family: "Microsoft YaHei", "Segoe UI", Arial;
                font-size: 13px;
            }}
            QFrame#resultCard {{
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 12px;
            }}
            QWidget#resultWindow QLabel {{
                color: {TEXT};
                background: transparent;
                border: 0;
            }}
            QLabel#statusLabel {{
                color: {MUTED};
                background: transparent;
                border: 0;
                padding: 0;
                font-size: 10px;
            }}
            QTextBrowser#resultBody {{
                color: #334155;
                background: transparent;
                border: 0;
                padding: 0 1px 0 1px;
                selection-background-color: {BLUE_SOFT};
            }}
            QPushButton#tipToggle {{
                min-height: 18px;
                color: {MUTED};
                background: transparent;
                border: 0;
                padding: 0;
                font-size: 10px;
                text-align: left;
            }}
            QPushButton#tipToggle:hover {{ color: {BLUE}; }}
            QLabel#tipContent {{
                color: #475467;
                background: #f4f6f8;
                border: 0;
                border-radius: 8px;
                padding: 5px 8px;
                font-size: 12px;
            }}
            QLineEdit#followupInput {{
                color: {TEXT};
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 4px 8px;
                selection-background-color: {BLUE_SOFT};
            }}
            QLineEdit#followupInput:focus {{ border-color: {BLUE}; }}
            QWidget#resultWindow QPushButton {{
                min-height: 24px;
                border-radius: 8px;
                padding: 0 9px;
                font-size: 11px;
            }}
            QPushButton#primaryButton {{
                color: #ffffff;
                background: {BLUE};
                border: 1px solid {BLUE};
            }}
            QPushButton#primaryButton:hover {{ background: {BLUE_DARK}; }}
            QPushButton#moreButton {{
                color: {MUTED};
                background: transparent;
                border: 0;
                padding: 0;
                font-size: 14px;
            }}
            QPushButton#moreButton:hover {{ color: {TEXT}; background: {BORDER_LIGHT}; }}
            QPushButton#moreButton::menu-indicator {{
                image: none;
                width: 0;
                height: 0;
            }}
            QPushButton#closeButton {{
                color: #718096;
                background: transparent;
                border: 0;
                padding: 0;
                min-height: 0;
                font-size: 16px;
            }}
            QPushButton#closeButton:hover {{ color: #b54747; background: #fbeeee; }}
            QMenu#resultMenu {{
                color: #334155;
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 5px;
            }}
            QMenu#resultMenu::item {{
                padding: 6px 18px 6px 10px;
                border-radius: 6px;
            }}
            QMenu#resultMenu::item:selected {{ background: {BLUE_SOFT}; color: {BLUE}; }}
            QTextBrowser#resultBody QScrollBar:vertical {{
                background: transparent;
                width: 7px;
                margin: 2px 0;
            }}
            QTextBrowser#resultBody QScrollBar::handle:vertical {{
                background: #d0d5dd;
                min-height: 24px;
                border-radius: 3px;
            }}
            QTextBrowser#resultBody QScrollBar::handle:vertical:hover {{ background: #98a2b3; }}
            QTextBrowser#resultBody QScrollBar::add-line:vertical,
            QTextBrowser#resultBody QScrollBar::sub-line:vertical {{
                height: 0;
                background: transparent;
            }}
            QTextBrowser#resultBody QScrollBar::add-page:vertical,
            QTextBrowser#resultBody QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
            """
        )

    def show_loading(self) -> None:
        self.payload = {}
        self._stream_buffers = {"translation": "", "explanation": "", "learning_tip": ""}
        self._stream_terms = []
        self._source_text = ""
        self._fit_width_peak = 0
        self._fit_height_peak = 0
        self._followup_anchor = None
        self._followup_sections = {"translation": "", "explanation": ""}
        self.text_browser.setPlainText("")
        self._set_tip("")
        self.followup_input.clear()
        self._enter_loading()
        self._set_busy(True)
        self.status_label.setText("正在识别...")
        self._fit_to_content()
        self._move_near_cursor()
        self.show()
        self.raise_()
        QApplication.processEvents()

    def _enter_loading(self) -> None:
        self._loading = True
        self.text_browser.setVisible(False)
        self.tip_toggle.setVisible(False)
        self.tip_content.setVisible(False)
        self.followup_input.setVisible(False)
        self.send_button.setVisible(False)
        self.retry_button.setVisible(False)
        self.more_button.setVisible(False)

    def _exit_loading(self) -> None:
        if not self._loading:
            return
        self._loading = False
        self.text_browser.setVisible(True)
        self.retry_button.setVisible(False)
        self._set_tip(self.tip_content.text())

    def _show_actions(self) -> None:
        self.followup_input.setVisible(True)
        self.send_button.setVisible(True)
        self.more_button.setVisible(True)

    def set_status(self, status: str) -> None:
        normalized = status.strip()
        if normalized in {"", "完成", "已完成", "就绪"}:
            self.status_label.setText("解析完成")
        else:
            self.status_label.setText(normalized)
        self.status_label.show()
        self._fit_to_content()
        QApplication.processEvents()

    def append_stream_chunk(self, section: str, chunk: str) -> None:
        """Append a real provider delta, re-rendering both visible sections."""
        if section not in self._stream_buffers or not chunk:
            return
        self._exit_loading()
        self._stream_buffers[section] += chunk
        if section == "learning_tip":
            self._set_tip(self._stream_buffers["learning_tip"])
            self._fit_to_content()
            QApplication.processEvents()
            return
        self.text_browser.setHtml(
            build_result_html(
                translation=self._stream_buffers["translation"],
                explanation=self._stream_buffers["explanation"],
                source_text=self._source_text,
                terms=self._stream_terms,
            )
        )
        self._fit_to_content()
        QApplication.processEvents()

    def set_stream_terms(self, terms: list[dict]) -> None:
        if not isinstance(terms, list):
            return
        self._exit_loading()
        self._stream_terms = [term for term in terms if isinstance(term, dict)]
        self.text_browser.setHtml(
            build_result_html(
                translation=self._stream_buffers["translation"],
                explanation=self._stream_buffers["explanation"],
                source_text=self._source_text,
                terms=self._stream_terms,
            )
        )
        self._fit_to_content()
        QApplication.processEvents()

    def set_source_text(self, source_text: str) -> None:
        self._source_text = source_text or ""

    def set_result(self, payload: dict) -> None:
        self.payload = dict(payload)
        self._source_text = str(payload.get("source_text") or "")
        self._exit_loading()
        error = str(payload.get("error") or "").strip()
        if error:
            self._render_error(payload, error)
            self.set_status(error if len(error) <= 60 else error[:57] + "...")
        else:
            self.text_browser.setHtml(
                build_result_html(
                    translation=str(payload.get("translation") or ""),
                    explanation=str(payload.get("explanation") or ""),
                    source_text=str(payload.get("source_text") or ""),
                    terms=payload.get("terms") if isinstance(payload.get("terms"), list) else [],
                )
            )
            self._set_tip(str(payload.get("learning_tip") or ""))
            self.set_status("完成")
        capture_id = self.payload.get("capture_id")
        self.retry_button.setVisible(
            bool(error) and isinstance(capture_id, int) and capture_id > 0
        )
        self._show_actions()
        self._set_busy(False)
        self._fit_to_content()
        if not self.isVisible():
            self._move_near_cursor()
            self.show()
            self.raise_()

    def _render_error(self, payload: dict, error: str) -> None:
        parts = [
            '<div class="meta-label">错误</div>',
            f'<div class="body-line" style="color:#b54747;">{html.escape(error)}</div>',
        ]
        partial_translation = str(payload.get("partial_translation") or "").strip()
        partial_explanation = str(payload.get("partial_explanation") or "").strip()
        if partial_translation:
            parts.append('<div class="meta-label">已获取的翻译</div>')
            parts.append(            render_lines(partial_translation))
        if partial_explanation:
            parts.append('<div class="meta-label">已获取的解释</div>')
            parts.append(            render_lines(partial_explanation))
        source_text = str(payload.get("source_text") or "").strip()
        if source_text:
            parts.append('<div class="meta-label">OCR 原文</div>')
            parts.append(            render_lines(source_text))
        self.text_browser.setHtml("".join(parts))
        self._set_tip("")

    def begin_followup(self) -> None:
        self._followup_sections = {"translation": "", "explanation": ""}
        self.status_label.setText("正在追问...")
        self.status_label.show()
        self.retry_button.hide()
        self._set_busy(True)
        cursor = self.text_browser.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._followup_anchor = cursor.position()
        cursor.insertHtml(self._followup_block_html(pending=True))
        self.text_browser.setTextCursor(cursor)
        self._fit_to_content()
        QApplication.processEvents()

    def append_followup_chunk(self, section: str, chunk: str) -> None:
        if section not in self._followup_sections or not chunk:
            return
        self._followup_sections[section] += chunk
        if self._followup_anchor is None:
            return
        self._update_followup_block(
            translation=self._followup_sections["translation"],
            explanation=self._followup_sections["explanation"],
        )
        self._fit_to_content()
        QApplication.processEvents()

    def show_followup_error(self, message: str) -> None:
        if self._followup_anchor is not None:
            self._update_followup_block(
                translation=self._followup_sections["translation"],
                explanation=self._followup_sections["explanation"],
                error=message,
            )
        else:
            self.set_status(message)
        self.set_status(message if len(message) <= 60 else message[:57] + "...")
        self._set_busy(False)
        self._fit_to_content()
        QApplication.processEvents()

    def append_followup_result(self, payload: dict) -> None:
        self.payload.update(payload)
        if self._followup_anchor is None:
            explanation = str(payload.get("explanation") or "").strip()
            if explanation:
                cursor = self.text_browser.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                cursor.insertBlock()
                cursor.insertHtml(
                    '<div class="meta-label">追问回答</div>'
                    + render_lines(explanation)
                )
                self.text_browser.setTextCursor(cursor)
        else:
            self._update_followup_block(
                translation=str(payload.get("translation") or ""),
                explanation=str(payload.get("explanation") or ""),
            )
        self.set_status("完成")
        self._set_busy(False)
        self._fit_to_content()

    def _followup_block_html(
        self,
        translation: str = "",
        explanation: str = "",
        *,
        pending: bool = False,
        error: str = "",
    ) -> str:
        parts = ['<div class="meta-label">追问回答</div>']
        if translation:
            parts.append('<div class="meta-label">翻译</div>')
            parts.append(render_lines(translation))
        if explanation:
            parts.append(render_lines(explanation))
        if error:
            parts.append(
                f'<div class="body-line" style="color:#b54747;">{html.escape(error)}</div>'
            )
        elif not translation and not explanation:
            if pending:
                parts.append(
                    '<div class="body-line" style="color:#8995a5;">思考中…</div>'
                )
            else:
                parts.append(compose_html("没有可显示的结果。", ""))
        return "".join(parts)

    def _update_followup_block(self, **kwargs) -> None:
        cursor = self.text_browser.textCursor()
        cursor.setPosition(self._followup_anchor)
        cursor.movePosition(cursor.MoveOperation.End, cursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self._followup_anchor = cursor.position()
        cursor.insertHtml(self._followup_block_html(**kwargs))
        self.text_browser.setTextCursor(cursor)

    def adjust_text_size(self, delta: int) -> None:
        font = self.text_browser.font()
        current = font.pixelSize() or 13
        size = max(10, min(18, current + delta))
        font.setPixelSize(size)
        self.text_browser.setFont(font)
        self._fit_width_peak = 0
        self._fit_height_peak = 0
        self._fit_to_content()

    def _copy_text(self) -> None:
        parts = [self.text_browser.toPlainText().strip()]
        if self.tip_content.text().strip():
            parts.append(self.tip_content.text().strip())
        QApplication.clipboard().setText("\n".join(part for part in parts if part))

    def _send_followup(self) -> None:
        if self._busy:
            return
        question = self.followup_input.text().strip()
        source_text = str(self.payload.get("source_text") or "").strip()
        if not question:
            return
        if not source_text:
            self.set_status("当前结果没有可追问的 OCR 原文。")
            return
        self.followup_input.clear()
        self.request_followup.emit(source_text, question, "custom")

    def _send_retry(self) -> None:
        capture_id = self.payload.get("capture_id")
        if isinstance(capture_id, int) and capture_id > 0:
            self.request_retry.emit(capture_id)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.followup_input.setEnabled(not busy)
        self.send_button.setEnabled(not busy)

    def _fit_to_content(self) -> None:
        screen = (
            QApplication.screenAt(self.frameGeometry().center())
            or QApplication.screenAt(QCursor.pos())
            or QApplication.primaryScreen()
        )
        available = screen.availableGeometry() if screen is not None else None
        available_width = available.width() if available is not None else 1280
        available_height = available.height() if available is not None else 800

        if self._loading:
            self.adjustSize()
            width = max(200, min(300, self.sizeHint().width()))
            self.resize(width, self.height())
            return

        # 6 (outer shadow margin) * 2 + 6+6 (card margins) + 2*2 (doc margins)
        horizontal_padding = 28
        document = self.text_browser.document()
        ideal = int(document.idealWidth())
        max_width = min(720, available_width - 40)
        target_width = min(max_width, max(380, ideal + horizontal_padding))
        target_width = max(340, target_width)
        self._fit_width_peak = max(self._fit_width_peak, target_width)
        target_width = self._fit_width_peak

        self.resize(target_width, self.height())
        QApplication.processEvents()
        document.setTextWidth(self.text_browser.viewport().width())
        height = int(document.size().height()) + 4
        max_body_height = max(180, min(560, int(available_height * 0.55)))
        self._fit_height_peak = max(self._fit_height_peak, min(max_body_height, height))
        self.text_browser.setMaximumHeight(max_body_height)
        self.text_browser.setFixedHeight(max(72, self._fit_height_peak))
        QApplication.processEvents()
        self.adjustSize()
        self.resize(target_width, self.height())
        if available is not None and self.isVisible():
            if self.x() + self.width() > available.right():
                self.move(available.right() - self.width() + 1, self.y())
            if self.y() + self.height() > available.bottom():
                self.move(self.x(), available.bottom() - self.height() + 1)

    def _set_tip(self, text: str) -> None:
        tip = compact_line_breaks(text)
        self.tip_content.setText(tip)
        self.tip_content.hide()
        self.tip_toggle.setText("▸ 补充说明")
        self.tip_toggle.setVisible(bool(tip))

    def _toggle_tip(self) -> None:
        expanded = not self.tip_content.isVisible()
        self.tip_content.setVisible(expanded)
        self.tip_toggle.setText("▾ 补充说明" if expanded else "▸ 补充说明")
        self._fit_to_content()

    def _move_near_cursor(self) -> None:
        point = QCursor.pos() + QPoint(16, 18)
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        if screen is None:
            self.move(point)
            return
        geometry = screen.availableGeometry()
        size = self.sizeHint()
        x = min(max(point.x(), geometry.left()), geometry.right() - size.width())
        y = min(max(point.y(), geometry.top()), geometry.bottom() - size.height())
        self.move(x, y)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def force_close(self) -> None:
        self.close()
