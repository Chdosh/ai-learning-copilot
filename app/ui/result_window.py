from __future__ import annotations

import html
from urllib.parse import unquote

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QResizeEvent, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTextBrowser,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import BLUE, BLUE_SOFT, BORDER, GREEN, MUTED, RED


COMPACT_WIDTH_KEY = "result_window_compact_width"
COMPACT_HEIGHT_KEY = "result_window_compact_height"
DEFAULT_COMPACT_SIZE = QSize(520, 330)


class ResultWindow(QWidget):
    request_followup = Signal(str, str, str)

    def __init__(self, settings_store=None) -> None:
        super().__init__()
        self.setWindowTitle("AI 截图翻译")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setMinimumSize(420, 260)
        self.settings_store = settings_store
        self.payload: dict = {}
        self.term_map: dict[str, str] = {}
        self.tab_buttons: list[QPushButton] = []
        self.text_size = 13
        self._compact_size = self._load_compact_size()
        self._is_compact = True
        self._allow_close = False
        self._resize_save_timer = QTimer(self)
        self._resize_save_timer.setSingleShot(True)
        self._resize_save_timer.timeout.connect(self._save_compact_size)
        self._build_ui()
        self._show_compact()

    def set_loading(self, image_path: str) -> None:
        self.payload = {"image_path": image_path}
        self.term_map = {}
        self.section_title.setText("正在识别")
        self.preview_browser.setHtml(_simple_html("正在 OCR 识别截图文字，并准备发送给 AI 解释。", self.text_size))
        self.term_detail_browser.setHtml("")
        self.translation_view.setPlainText("")
        self.explanation_view.setHtml("")
        self._set_context("", "", "")
        self._render_followup_history()
        self._show_compact()
        self.showNormal()
        self.raise_()

    def set_result(self, payload: dict) -> None:
        self.payload = payload
        self.term_map = _build_term_map(payload.get("terms") or [])
        self.section_title.setText("总解释")
        translation = payload.get("translation") or "无翻译"
        explanation = _compose_explanation(payload)
        self.translation_view.setPlainText(translation)
        self.explanation_view.setHtml(_html_with_terms(explanation, self.term_map, font_size=self.text_size))
        self.preview_browser.setHtml(_html_with_terms(explanation, self.term_map, font_size=self.text_size))
        self.term_detail_browser.setHtml("")
        self._set_context(payload.get("source_text") or "", translation, explanation)
        self._render_followup_history()
        self._show_compact()
        self.showNormal()
        self.raise_()

    def append_followup_result(self, payload: dict) -> None:
        if payload.get("conversation_id"):
            self.payload["conversation_id"] = payload.get("conversation_id")
        if payload.get("translation"):
            self.payload["translation"] = payload.get("translation")
            self.translation_view.setPlainText(payload.get("translation") or "")
        if payload.get("explanation"):
            self.payload["explanation"] = payload.get("explanation")
        if payload.get("terms"):
            self.payload["terms"] = payload.get("terms")
            self.term_map = _build_term_map(payload.get("terms") or [])
        self._replace_pending_ai_line(payload.get("explanation") or payload.get("translation") or "")
        explanation = _compose_explanation(self.payload)
        self.explanation_view.setHtml(_html_with_terms(explanation, self.term_map, font_size=self.text_size))
        self.preview_browser.setHtml(_html_with_terms(explanation, self.term_map, font_size=self.text_size))
        self.term_detail_browser.setHtml("")
        self._set_context(
            self.payload.get("source_text") or "",
            self.payload.get("translation") or "",
            explanation,
        )
        self._show_expanded(2)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._save_compact_size()
        if self._allow_close:
            event.accept()
            return
        event.ignore()
        self.showMinimized()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not hasattr(self, "stack") or not hasattr(self, "_resize_save_timer"):
            return
        if self._is_compact and self.stack.currentIndex() == 0:
            self._compact_size = self.size()
            self._resize_save_timer.start(300)

    def _build_ui(self) -> None:
        self._apply_style()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_compact_page())
        self.stack.addWidget(self._build_expanded_page())
        root.addWidget(self.stack, 1)
        root.addWidget(self._build_footer())

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("headerBar")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(8)
        logo = QLabel("✧")
        logo.setStyleSheet(f"color:{BLUE}; font-size:22px; font-weight:800;")
        title = QLabel("AI 截图翻译")
        title.setObjectName("windowTitle")
        layout.addWidget(logo)
        layout.addWidget(title)
        layout.addStretch()
        minimize = QPushButton("—")
        minimize.setObjectName("linkButton")
        minimize.clicked.connect(self.showMinimized)
        close = QPushButton("×")
        close.setObjectName("linkButton")
        close.setStyleSheet(f"QPushButton#linkButton {{ color:{RED}; font-size:22px; border:0; background:transparent; }}")
        close.clicked.connect(self.close)
        layout.addWidget(minimize)
        layout.addWidget(close)
        return header

    def _build_compact_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        content = QVBoxLayout()
        content.setSpacing(7)
        title_row = QHBoxLayout()
        self.section_title = QLabel("总解释")
        self.section_title.setObjectName("sectionTitle")
        title_row.addWidget(self.section_title)
        title_row.addStretch()
        content.addLayout(title_row)

        self.preview_browser = QTextBrowser()
        self.preview_browser.setObjectName("previewBrowser")
        self.preview_browser.setOpenLinks(False)
        self.preview_browser.setMouseTracking(True)
        self.preview_browser.anchorClicked.connect(lambda url: self._show_term_detail(url.toString()))
        self.preview_browser.viewport().installEventFilter(self)
        self.preview_browser.setHtml(_simple_html("等待截图识别结果...", self.text_size))
        content.addWidget(self.preview_browser, 2)

        term_title = QLabel("关键词解释")
        term_title.setStyleSheet(f"color:{MUTED}; font-weight:700;")
        content.addWidget(term_title)
        self.term_detail_browser = QTextBrowser()
        self.term_detail_browser.setObjectName("termDetail")
        self.term_detail_browser.setOpenLinks(False)
        self.term_detail_browser.setHtml("")
        content.addWidget(self.term_detail_browser, 1)
        layout.addLayout(content, 1)

        action_col = QVBoxLayout()
        action_col.setSpacing(6)
        self.translation_button = _action_button("译", "查看翻译")
        self.explanation_button = _action_button("解", "查看解释")
        self.followup_button = _action_button("问", "继续追问")
        smaller_button = _action_button("A-", "缩小文字")
        bigger_button = _action_button("A+", "放大文字")
        expand_button = _action_button("大窗", "展开大窗口")
        close_button = _action_button("关", "关闭")
        self.translation_button.clicked.connect(lambda: self._show_expanded(0))
        self.explanation_button.clicked.connect(lambda: self._show_expanded(1))
        self.followup_button.clicked.connect(lambda: self._show_expanded(2))
        smaller_button.clicked.connect(lambda: self.adjust_text_size(-1))
        bigger_button.clicked.connect(lambda: self.adjust_text_size(1))
        expand_button.clicked.connect(lambda: self._show_expanded(1))
        close_button.clicked.connect(self.close)
        for button in (
            self.translation_button,
            self.explanation_button,
            self.followup_button,
            smaller_button,
            bigger_button,
            expand_button,
            close_button,
        ):
            action_col.addWidget(button)
        action_col.addStretch()
        layout.addLayout(action_col)
        return page

    def _build_expanded_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tabs = QFrame()
        tabs.setStyleSheet(f"background:#ffffff; border-bottom:1px solid {BORDER};")
        tabs_layout = QHBoxLayout(tabs)
        tabs_layout.setContentsMargins(46, 0, 46, 0)
        tabs_layout.setSpacing(26)
        for label, index in (("翻译", 0), ("解释", 1), ("追问", 2)):
            button = QPushButton(label)
            button.setObjectName("tabButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, idx=index: self._set_detail_tab(idx))
            self.tab_buttons.append(button)
            tabs_layout.addWidget(button)
        tabs_layout.addStretch()
        layout.addWidget(tabs)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(24, 22, 24, 22)
        body_layout.setSpacing(16)

        body_layout.addWidget(self._build_context_panel(), 3)
        body_layout.addWidget(self._build_center_panel(), 7)
        body_layout.addWidget(self._build_action_panel(), 2)
        layout.addWidget(body, 1)
        return page

    def _build_context_panel(self) -> QFrame:
        panel = _panel()
        panel.setMinimumWidth(260)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        title = QLabel("本轮上下文  ⓘ")
        title.setStyleSheet("font-size:17px; font-weight:800;")
        subtitle = QLabel("基于当前截图的内容，供追问参考")
        subtitle.setStyleSheet(f"color:{MUTED};")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        self.source_context = _context_card("OCR 原文", BLUE)
        self.translation_context = _context_card("中文翻译", GREEN)
        self.summary_context = _context_card("总解释", BLUE)
        layout.addWidget(self.source_context)
        layout.addWidget(self.translation_context)
        layout.addWidget(self.summary_context, 1)
        return panel

    def _build_center_panel(self) -> QFrame:
        panel = _panel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        presets = QHBoxLayout()
        for label, question, mode in (
            ("更简单点", "请用更简单的话解释这段内容。", "simple"),
            ("举例说明", "请举几个具体例子说明。", "examples"),
            ("重新解释", "请重新解释这段内容。", "default"),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, q=question, m=mode: self._preset_followup(q, m))
            presets.addWidget(button)
        presets.addStretch()
        layout.addLayout(presets)

        self.detail_stack = QStackedWidget()
        self.translation_view = QTextEdit()
        self.translation_view.setReadOnly(True)
        self.translation_view.setAcceptRichText(False)

        self.explanation_view = QTextBrowser()
        self.explanation_view.setOpenLinks(False)
        self.explanation_view.setMouseTracking(True)
        self.explanation_view.anchorClicked.connect(lambda url: self._show_term_detail(url.toString()))
        self.explanation_view.viewport().installEventFilter(self)

        followup_page = QWidget()
        followup_layout = QVBoxLayout(followup_page)
        followup_layout.setContentsMargins(0, 0, 0, 0)
        followup_layout.setSpacing(10)
        self.followup_history = QTextEdit()
        self.followup_history.setReadOnly(True)
        self.followup_history.setAcceptRichText(False)
        input_row = QHBoxLayout()
        self.followup_input = QLineEdit()
        self.followup_input.setPlaceholderText("继续追问当前截图内容...")
        self.followup_input.returnPressed.connect(lambda: self._send_followup("custom"))
        send_button = QPushButton("发送")
        send_button.setObjectName("primaryButton")
        send_button.clicked.connect(lambda: self._send_followup("custom"))
        input_row.addWidget(self.followup_input, 1)
        input_row.addWidget(send_button)
        followup_layout.addWidget(self.followup_history, 1)
        followup_layout.addLayout(input_row)

        self.detail_stack.addWidget(self.translation_view)
        self.detail_stack.addWidget(self.explanation_view)
        self.detail_stack.addWidget(followup_page)
        layout.addWidget(self.detail_stack, 1)
        return panel

    def _build_action_panel(self) -> QFrame:
        panel = _panel()
        panel.setMinimumWidth(170)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        title = QLabel("操作")
        title.setStyleSheet("font-size:17px; font-weight:800;")
        layout.addWidget(title)
        actions = [
            ("▣  复制回答", self._copy_answer),
            ("▤  切换到解释", lambda: self._set_detail_tab(1)),
            ("☆  收藏术语", self._show_readonly_notice),
            ("⟳  重新生成", lambda: self._preset_followup("请重新解释这段内容。", "default")),
            ("⇩  导出 Markdown", self._copy_markdown),
            ("◴  打开历史", self._show_readonly_notice),
        ]
        for label, callback in actions:
            button = QPushButton(label)
            button.clicked.connect(callback)
            layout.addWidget(button)
        layout.addStretch()
        return panel

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setObjectName("footerBar")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(14, 7, 14, 7)
        self.footer_label = QLabel("识别语言：eng + chi_sim    来源：Tesseract")
        self.footer_label.setStyleSheet(f"color:{MUTED}; font-size:12px;")
        expand_link = QPushButton("展开大窗口 ↗")
        expand_link.setObjectName("linkButton")
        expand_link.clicked.connect(lambda: self._show_expanded(1))
        layout.addWidget(self.footer_label)
        layout.addStretch()
        layout.addWidget(expand_link)
        return footer

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        term_views = {
            view.viewport()
            for view in (getattr(self, "preview_browser", None), getattr(self, "explanation_view", None))
            if view is not None
        }
        if watched in term_views and event.type() == QEvent.Type.MouseMove:
            if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                global_pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
                view = self.preview_browser if watched is self.preview_browser.viewport() else self.explanation_view
                anchor = view.anchorAt(pos)
                if anchor and anchor in self.term_map:
                    QToolTip.showText(global_pos, self.term_map[anchor], view)
                else:
                    QToolTip.hideText()
        return super().eventFilter(watched, event)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"""
            QWidget {{
                background: #ffffff;
                color: #101828;
                font-family: "Microsoft YaHei", "Segoe UI", Arial;
                font-size: {self.text_size}px;
            }}
            QFrame#headerBar {{
                background: #ffffff;
                border-bottom: 1px solid {BORDER};
            }}
            QFrame#footerBar {{
                background: #fbfdff;
                border-top: 1px solid {BORDER};
            }}
            QLabel#windowTitle {{
                font-size: {self.text_size + 2}px;
                font-weight: 800;
            }}
            QLabel#sectionTitle {{
                font-size: {self.text_size + 2}px;
                font-weight: 800;
            }}
            QTextBrowser#previewBrowser {{
                border: 1px solid {BORDER};
                border-radius: 8px;
                background: #ffffff;
                padding: 6px;
            }}
            QTextBrowser#termDetail {{
                border: 1px solid {BORDER};
                border-radius: 8px;
                background: #fbfdff;
                padding: 6px;
            }}
            QTextEdit, QTextBrowser, QLineEdit {{
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 7px;
                background: #ffffff;
                selection-background-color: {BLUE};
            }}
            QPushButton {{
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 7px;
                padding: 6px 10px;
                color: #344054;
            }}
            QPushButton:hover {{
                border-color: #93b4ff;
                background: #f8fbff;
            }}
            QPushButton#actionButton {{
                min-width: 46px;
                max-width: 46px;
                min-height: 30px;
                max-height: 30px;
                padding: 0;
                font-size: {self.text_size}px;
                font-weight: 700;
            }}
            QPushButton#primaryButton {{
                background: {BLUE};
                color: #ffffff;
                border-color: {BLUE};
                font-weight: 700;
            }}
            QPushButton#primaryButton:hover, QPushButton#primaryButton:pressed {{
                background: #1d4ed8;
                color: #ffffff;
                border-color: #1d4ed8;
            }}
            QPushButton:disabled {{
                background: #f2f4f7;
                color: #98a2b3;
                border-color: #e4e7ec;
            }}
            QPushButton#linkButton {{
                border: 0;
                color: {BLUE};
                background: transparent;
                font-weight: 700;
            }}
            QPushButton#tabButton {{
                border: 0;
                border-radius: 0;
                padding: 11px 30px;
                background: transparent;
                font-size: {self.text_size + 1}px;
                color: #344054;
            }}
            QPushButton#tabButton:checked {{
                color: {BLUE};
                font-weight: 800;
                border-bottom: 2px solid {BLUE};
            }}
            """
        )

    def adjust_text_size(self, delta: int) -> None:
        self.text_size = max(11, min(17, self.text_size + delta))
        self._apply_style()
        explanation = _compose_explanation(self.payload)
        if self.payload:
            self.preview_browser.setHtml(_html_with_terms(explanation, self.term_map, font_size=self.text_size))
            self.explanation_view.setHtml(_html_with_terms(explanation, self.term_map, font_size=self.text_size))

    def _show_compact(self) -> None:
        self._is_compact = True
        self.stack.setCurrentIndex(0)
        self.resize(self._compact_size)

    def _show_expanded(self, index: int) -> None:
        if self.stack.currentIndex() == 0:
            self._save_compact_size()
        self._is_compact = False
        self.stack.setCurrentIndex(1)
        self._set_detail_tab(index)
        self.resize(1180, 760)

    def _set_detail_tab(self, index: int) -> None:
        self.detail_stack.setCurrentIndex(index)
        for button_index, button in enumerate(self.tab_buttons):
            button.setChecked(button_index == index)

    def _show_term_detail(self, term: str) -> None:
        key = html.unescape(unquote(term or "")).strip()
        if not key:
            return
        text = self.term_map.get(key, "")
        if not text:
            return
        self.term_detail_browser.setHtml(_simple_html(text, self.text_size))

    def _send_followup(self, mode: str) -> None:
        question = self.followup_input.text().strip()
        if not question:
            return
        self.followup_input.clear()
        self._append_followup_line("我", question)
        self._append_followup_line("AI", "正在回答...")
        self.request_followup.emit(self.payload.get("source_text") or "", question, mode)

    def _preset_followup(self, question: str, mode: str) -> None:
        self.followup_input.setText(question)
        self._send_followup(mode)
        self._show_expanded(2)

    def _render_followup_history(self) -> None:
        self.followup_history.setPlainText("")
        if self.payload.get("source_text"):
            self._append_followup_line("OCR", self.payload.get("source_text") or "")
        if self.payload.get("explanation"):
            self._append_followup_line("AI", self.payload.get("explanation") or "")

    def _append_followup_line(self, role: str, content: str) -> None:
        if not content:
            return
        current = self.followup_history.toPlainText().strip()
        line = f"{role}：{content.strip()}"
        self.followup_history.setPlainText(f"{current}\n\n{line}".strip())
        self.followup_history.moveCursor(QTextCursor.MoveOperation.End)

    def _replace_pending_ai_line(self, content: str) -> None:
        if not content:
            return
        current = self.followup_history.toPlainText().strip()
        pending = "AI：正在回答..."
        final = f"AI：{content.strip()}"
        if pending in current:
            self.followup_history.setPlainText(current.replace(pending, final, 1))
            self.followup_history.moveCursor(QTextCursor.MoveOperation.End)
            return
        self._append_followup_line("AI", content)

    def _copy_answer(self) -> None:
        index = self.detail_stack.currentIndex()
        if index == 0:
            text = self.translation_view.toPlainText()
        elif index == 1:
            text = _compose_explanation(self.payload)
        else:
            text = self.followup_history.toPlainText()
        QApplication.clipboard().setText(text)

    def _copy_markdown(self) -> None:
        QApplication.clipboard().setText(_payload_markdown(self.payload))

    def _show_readonly_notice(self) -> None:
        QToolTip.showText(self.mapToGlobal(self.rect().center()), "这个入口会在历史页/术语页联动后继续完善。", self)

    def _set_context(self, source_text: str, translation: str, explanation: str) -> None:
        _set_context_body(self.source_context, _compact_text(source_text, 220))
        _set_context_body(self.translation_context, _compact_text(translation, 220))
        _set_context_body(self.summary_context, _compact_text(explanation, 260))

    def force_close(self) -> None:
        self._allow_close = True
        self._save_compact_size()
        self.close()

    def _load_compact_size(self) -> QSize:
        if self.settings_store is None:
            return DEFAULT_COMPACT_SIZE
        try:
            values = self.settings_store.get_settings()
            width = int(values.get(COMPACT_WIDTH_KEY, str(DEFAULT_COMPACT_SIZE.width())))
            height = int(values.get(COMPACT_HEIGHT_KEY, str(DEFAULT_COMPACT_SIZE.height())))
        except (TypeError, ValueError, AttributeError):
            return DEFAULT_COMPACT_SIZE
        width = min(max(width, 420), 1200)
        height = min(max(height, 260), 900)
        return QSize(width, height)

    def _save_compact_size(self) -> None:
        if self.settings_store is None or not self._is_compact:
            return
        size = self.size()
        if size.width() < 420 or size.height() < 260:
            return
        self._compact_size = size
        try:
            self.settings_store.set_setting(COMPACT_WIDTH_KEY, str(size.width()))
            self.settings_store.set_setting(COMPACT_HEIGHT_KEY, str(size.height()))
        except AttributeError:
            return


def _panel() -> QFrame:
    panel = QFrame()
    panel.setObjectName("panel")
    panel.setStyleSheet(
        f"""
        QFrame#panel {{
            background: #ffffff;
            border: 1px solid {BORDER};
            border-radius: 12px;
        }}
        """
    )
    return panel


def _context_card(title: str, color: str) -> QFrame:
    card = QFrame()
    card.setObjectName("contextCard")
    card.setMinimumHeight(112)
    card.setStyleSheet(
        f"""
        QFrame#contextCard {{
            background: #ffffff;
            border: 1px solid {BORDER};
            border-radius: 10px;
        }}
        """
    )
    layout = QVBoxLayout(card)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(8)
    header = QLabel(f"▣  {title}")
    header.setStyleSheet(f"color:{color}; font-weight:800;")
    body = QLabel("无")
    body.setObjectName("contextBody")
    body.setWordWrap(True)
    body.setStyleSheet("color:#344054; line-height:1.4;")
    foot = QLabel("共 0 行")
    foot.setObjectName("contextFoot")
    foot.setStyleSheet(f"color:{MUTED};")
    layout.addWidget(header)
    layout.addWidget(body, 1)
    layout.addWidget(foot)
    return card


def _set_context_body(card: QFrame, text: str) -> None:
    body = card.findChild(QLabel, "contextBody")
    foot = card.findChild(QLabel, "contextFoot")
    if body is not None:
        body.setText(text or "无")
    if foot is not None:
        lines = len([line for line in (text or "").splitlines() if line.strip()])
        foot.setText(f"共 {lines or 1} 行" if text else "共 0 行")


def _action_card(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("actionCard")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return button


def _action_button(text: str, tooltip: str = "") -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("actionButton")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if tooltip:
        button.setToolTip(tooltip)
    return button


def _compose_explanation(payload: dict) -> str:
    explanation = payload.get("explanation") or ""
    learning_tip = payload.get("learning_tip") or ""
    if learning_tip:
        explanation = f"{explanation}\n\n学习建议：{learning_tip}".strip()
    terms = [str(item.get("term") or "").strip() for item in payload.get("terms") or []]
    terms = [term for term in terms if term]
    if terms:
        explanation = f"{explanation}\n\n关键词：{'、'.join(terms)}".strip()
    return explanation or "无解释"


def _build_term_map(terms: list[dict]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in terms:
        term = str(item.get("term") or "").strip()
        if not term:
            continue
        name = str(item.get("chinese_name") or "").strip()
        explanation = str(item.get("beginner_explanation") or "").strip()
        examples = item.get("examples") or []
        text = term
        if name:
            text += f" / {name}"
        if explanation:
            text += f"\n{explanation}"
        if examples:
            text += "\n" + "\n".join(f"- {example}" for example in examples)
        mapping[term] = text
    return mapping


def _html_with_terms(text: str, term_map: dict[str, str], font_size: int = 13) -> str:
    escaped = html.escape(text or "")
    for term in sorted(term_map, key=len, reverse=True):
        safe_term = html.escape(term)
        escaped = escaped.replace(
            safe_term,
            f'<a href="{html.escape(term, quote=True)}" style="color:{BLUE}; text-decoration: underline;">{safe_term}</a>',
        )
    return f"<div style='font-size:{font_size}px; line-height:1.55; white-space:pre-wrap; color:#1f2a44;'>{escaped}</div>"


def _simple_html(text: str, font_size: int = 13) -> str:
    return f"<div style='font-size:{font_size}px; line-height:1.55; color:#1f2a44; white-space:pre-wrap;'>{html.escape(text)}</div>"


def _compact_text(value: str, limit: int) -> str:
    text = " ".join((value or "").split())
    if not text:
        return ""
    return text if len(text) <= limit else f"{text[:limit]}..."


def _payload_markdown(payload: dict) -> str:
    tags = payload.get("tags") or []
    return f"""# AI 截图解释

截图：{payload.get("image_path") or "未保存"}
标签：{"、".join(tags) if tags else "无"}

## 原文

{payload.get("source_text") or "无"}

## 翻译

{payload.get("translation") or "无"}

## 解释

{_compose_explanation(payload)}
"""
