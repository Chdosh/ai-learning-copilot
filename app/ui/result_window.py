"""Compact floating window for streaming capture results."""
from __future__ import annotations

import html

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QTextOption,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.services.ai_client import compact_line_breaks
from app.services.settings import (
    DEFAULT_RESULT_FONT_SIZE,
    MAX_RESULT_FONT_SIZE,
    MIN_RESULT_FONT_SIZE,
)
from app.ui.message_render import (
    DOC_STYLESHEET,
    build_result_html,
    compose_html,
    render_lines,
    split_lead,
)
from app.ui.theme import (
    BORDER,
    BORDER_LIGHT,
    CARD,
    DANGER,
    DANGER_SOFT,
    DISABLED,
    MUTED,
    PRIMARY,
    PRIMARY_DARK,
    PRIMARY_SOFT,
    RADIUS_MD,
    RADIUS_LG,
    TEXT,
    TEXT_SECONDARY,
)


BAR_WIDTH = 170
BAR_CONTROL_WIDTH = 22
BAR_HEADER_HEIGHT = 24

MANUAL_MIN_WIDTH = 320
MANUAL_MAX_WIDTH = 500
MANUAL_MIN_HEIGHT = 100
MANUAL_MAX_HEIGHT = 720
_RESIZE_MARGIN = 5

_RESIZE_CURSORS = {
    "left": Qt.CursorShape.SizeHorCursor,
    "right": Qt.CursorShape.SizeHorCursor,
    "top": Qt.CursorShape.SizeVerCursor,
    "bottom": Qt.CursorShape.SizeVerCursor,
    "top-left": Qt.CursorShape.SizeFDiagCursor,
    "bottom-right": Qt.CursorShape.SizeFDiagCursor,
    "top-right": Qt.CursorShape.SizeBDiagCursor,
    "bottom-left": Qt.CursorShape.SizeBDiagCursor,
}


class _ToggleChevronButton(QPushButton):
    """Chevron (down when collapsed, up when expanded) matching app dropdowns."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("barToggleButton")
        self.setFixedSize(BAR_CONTROL_WIDTH, BAR_HEADER_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("展开 / 收起")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.chevron_down = True

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(TEXT if self.isEnabled() and self.underMouse() else MUTED)
        pen = QPen(color, 1.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        cx, cy = self.width() // 2, self.height() // 2
        if self.chevron_down:
            painter.drawLine(cx - 5, cy - 1, cx, cy + 4)
            painter.drawLine(cx, cy + 4, cx + 5, cy - 1)
        else:
            painter.drawLine(cx - 5, cy + 1, cx, cy - 4)
            painter.drawLine(cx, cy - 4, cx + 5, cy + 1)
        painter.end()


class _MoveHandle(QLabel):
    """Drag handle painted as the universal four-direction move arrows."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dragHandle")
        self.setFixedSize(BAR_CONTROL_WIDTH, BAR_HEADER_HEIGHT)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("拖动")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(TEXT if self.underMouse() else MUTED)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        cx, cy = self.width() / 2, self.height() / 2
        radius = 1.8
        for col in (-3, 3):
            for row in (-6, 0, 6):
                painter.drawEllipse(
                    QRectF(
                        cx + col - radius,
                        cy + row - radius,
                        radius * 2,
                        radius * 2,
                    )
                )
        painter.end()


class _CloseButton(QPushButton):
    """Painted close ``x`` matching the other painted header glyphs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("closeButton")
        self.setFixedSize(BAR_CONTROL_WIDTH, BAR_HEADER_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("关闭")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(TEXT if self.underMouse() else MUTED)
        painter.setPen(QPen(color, 1.2))
        cx = self.width() / 2
        cy = self.height() / 2
        m = 4.5
        painter.drawLine(cx - m, cy - m, cx + m, cy + m)
        painter.drawLine(cx + m, cy - m, cx - m, cy + m)
        painter.end()


class ResultWindow(QWidget):
    request_followup = Signal(str, str, str)
    request_retry = Signal(int)
    open_history = Signal()
    font_size_changed = Signal(int)
    request_capture = Signal()
    position_changed = Signal(int, int)
    size_changed = Signal(int, int)
    size_reset = Signal()

    def __init__(self, parent=None, font_size: int = DEFAULT_RESULT_FONT_SIZE) -> None:
        super().__init__(parent)
        self._font_size = max(MIN_RESULT_FONT_SIZE, min(MAX_RESULT_FONT_SIZE, int(font_size)))
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
        self._bar_mode = False
        self._expanded = True
        self._has_result = False
        self._show_retry = False
        self._bar_anchor_rect = None
        self._width_locked = False
        self._manual_size: tuple[int, int] | None = None
        self._resize_edge: str | None = None
        self._resize_start: tuple[QPoint, ...] | None = None
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
        self.setMouseTracking(True)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        self._outer_layout = outer_layout
        self.card = QFrame()
        self.card.setObjectName("resultCard")
        outer_layout.addWidget(self.card)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(4)
        self._card_layout = layout

        self.header_widget = QWidget()
        self.header_widget.setObjectName("barHeader")
        self.header_widget.setFixedHeight(BAR_HEADER_HEIGHT)
        header = QHBoxLayout(self.header_widget)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)
        self.bar_capture_button = QPushButton("")
        self.bar_capture_button.setObjectName("barCaptureButton")
        self.bar_capture_button.setFixedSize(BAR_HEADER_HEIGHT, BAR_HEADER_HEIGHT)
        self.bar_capture_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bar_capture_button.setToolTip("截图识别")
        self.bar_capture_button.clicked.connect(self.request_capture.emit)
        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setMinimumWidth(0)
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.bar_toggle_button = _ToggleChevronButton()
        self.bar_toggle_button.clicked.connect(self.toggle_expanded)
        self.drag_handle = _MoveHandle()
        self.close_button = _CloseButton()
        self.close_button.clicked.connect(self.close)
        header.addWidget(self.bar_capture_button)
        header.addWidget(self.status_label, 1)
        header.addWidget(self.bar_toggle_button)
        header.addWidget(self.drag_handle)
        header.addWidget(self.close_button)
        layout.addWidget(self.header_widget)

        self.text_browser = QTextBrowser()
        self.text_browser.setObjectName("resultBody")
        self.text_browser.setOpenExternalLinks(False)
        self.text_browser.setFrameShape(QFrame.Shape.NoFrame)
        self.text_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        base_font = self.text_browser.font()
        base_font.setPixelSize(self._font_size)
        self.text_browser.setFont(base_font)
        self.text_browser.document().setDefaultFont(base_font)
        self.text_browser.document().setDocumentMargin(2)
        self.text_browser.setMinimumHeight(40)
        self.text_browser.setMaximumHeight(720)
        self.text_browser.document().setDefaultStyleSheet(self._document_stylesheet())
        self.text_browser.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.addWidget(self.text_browser)

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
        self.retry_button.clicked.connect(self._send_retry)
        self.retry_button.hide()
        more_button = QPushButton("···")
        more_button.setObjectName("moreButton")
        more_button.setMinimumWidth(28)
        more_button.setMaximumWidth(44)
        more_button.setFixedHeight(24)
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
        reset_size_action = QAction("重置窗口大小", more_menu)
        reset_size_action.triggered.connect(self.reset_size)
        more_menu.addAction(font_up)
        more_menu.addAction(font_down)
        more_menu.addSeparator()
        more_menu.addAction(copy_action)
        more_menu.addAction(history_action)
        more_menu.addSeparator()
        more_menu.addAction(reset_size_action)
        more_button.setMenu(more_menu)
        actions.addWidget(self.followup_input, 1)
        actions.addWidget(self.send_button)
        actions.addWidget(self.retry_button)
        actions.addWidget(more_button)
        layout.addLayout(actions)
        self._apply_style()
        self._install_resize_filter()

    def _install_resize_filter(self) -> None:
        """Track mouse movement over children so edge resize works everywhere."""
        for target in (self.card, self.text_browser, self.header_widget):
            target.setMouseTracking(True)
            target.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if not (self._bar_mode and self._expanded):
            return super().eventFilter(obj, event)
        if event.type() == QEvent.Type.MouseMove:
            if self._resize_edge is not None:
                self._apply_resize(event.globalPosition().toPoint())
                return True
            if self._drag_offset is None:
                edge = self._hit_resize_edge(obj.mapTo(self, event.position().toPoint()))
                self.setCursor(self._resize_cursor(edge) if edge else Qt.CursorShape.ArrowCursor)
        elif event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                edge = self._hit_resize_edge(obj.mapTo(self, event.position().toPoint()))
                if edge:
                    self._start_resize(edge, event.globalPosition().toPoint())
                    return True
        elif event.type() == QEvent.Type.MouseButtonRelease and self._resize_edge is not None:
            self._finish_resize()
            return True
        return super().eventFilter(obj, event)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"""
            QWidget#resultWindow {{
                background: transparent;
                color: {TEXT};
                font-family: "Microsoft YaHei", "Segoe UI", Arial;
                font-size: {self._font_size}px;
            }}
            QFrame#resultCard {{
                background: {CARD};
                border: 1px solid {BORDER};
                border-radius: {RADIUS_LG};
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
                font-size: {max(MIN_RESULT_FONT_SIZE, self._font_size - 2)}px;
            }}
            QTextBrowser#resultBody {{
                color: {TEXT_SECONDARY};
                background: transparent;
                border: 0;
                padding: 0 1px 0 1px;
                selection-background-color: {PRIMARY_SOFT};
            }}
            QLabel#tipContent {{
                color: {TEXT_SECONDARY};
                background: {BORDER_LIGHT};
                border: 0;
                border-radius: {RADIUS_MD};
                padding: 5px 8px;
                font-size: {self._font_size}px;
            }}
            QLineEdit#followupInput {{
                color: {TEXT};
                background: {CARD};
                border: 1px solid {BORDER};
                border-radius: {RADIUS_MD};
                padding: 4px 8px;
                selection-background-color: {PRIMARY_SOFT};
            }}
            QLineEdit#followupInput:focus {{ border-color: {PRIMARY}; }}
            QWidget#resultWindow QPushButton {{
                min-height: 24px;
                border-radius: {RADIUS_MD};
                padding: 0 9px;
                font-size: 12px;
            }}
            QWidget#resultWindow QPushButton#barCaptureButton,
            QWidget#resultWindow QPushButton#barToggleButton,
            QWidget#resultWindow QPushButton#closeButton,
            QLabel#dragHandle {{
                min-height: 0;
                max-height: 24px;
                padding: 0;
            }}
            QPushButton#primaryButton {{
                color: #ffffff;
                background: {PRIMARY};
                border: 1px solid {PRIMARY};
            }}
            QPushButton#primaryButton:hover {{ background: {PRIMARY_DARK}; }}
            QWidget#resultWindow QPushButton#moreButton {{
                color: {MUTED};
                background: transparent;
                border: 0;
                padding: 0 2px;
                font-size: 14px;
            }}
            QWidget#resultWindow QPushButton#moreButton:hover {{ color: {TEXT}; background: {BORDER_LIGHT}; }}
            QPushButton#moreButton::menu-indicator {{
                image: none;
                width: 0;
                height: 0;
            }}
            QPushButton#closeButton {{
                background: transparent;
                border: 0;
                padding: 0;
                min-height: 0;
            }}
            QPushButton#closeButton:hover {{ background: {BORDER_LIGHT}; }}
            QPushButton#barCaptureButton {{
                background: transparent;
                border: 0;
                padding: 0;
                min-height: 0;
            }}
            QPushButton#barCaptureButton:hover {{ background: {BORDER_LIGHT}; border-radius: {RADIUS_MD}; }}
            QPushButton#barCaptureButton:disabled {{ background: transparent; }}
            QPushButton#barToggleButton {{
                background: transparent;
                border: 0;
                padding: 0;
                min-height: 0;
            }}
            QPushButton#barToggleButton:hover {{ background: {BORDER_LIGHT}; }}
            QPushButton#barToggleButton:disabled {{ background: transparent; }}
            QLabel#dragHandle {{
                background: transparent;
                border: 0;
                padding: 0;
            }}
            QMenu#resultMenu {{
                color: {TEXT_SECONDARY};
                background: {CARD};
                border: 1px solid {BORDER};
                border-radius: {RADIUS_MD};
                padding: 5px;
            }}
            QMenu#resultMenu::item {{
                padding: 6px 18px 6px 10px;
                border-radius: 6px;
            }}
            QMenu#resultMenu::item:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; }}
            QTextBrowser#resultBody QScrollBar:vertical {{
                background: transparent;
                width: 7px;
                margin: 2px 0;
            }}
            QTextBrowser#resultBody QScrollBar::handle:vertical {{
                background: {DISABLED};
                min-height: 24px;
                border-radius: 3px;
            }}
            QTextBrowser#resultBody QScrollBar::handle:vertical:hover {{ background: {MUTED}; }}
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

    def _document_stylesheet(self) -> str:
        # No per-class font-size overrides: the stylesheet's em units resolve
        # against the document's default font at layout time, so everything
        # (including the explanation's lead line) scales with A+/A-.
        return DOC_STYLESHEET

    def _refresh_document_font(self) -> None:
        document = self.text_browser.document()
        document.setDefaultStyleSheet(self._document_stylesheet())
        document.markContentsDirty(0, document.characterCount())

    def set_capture_icon(self, icon: QIcon) -> None:
        """Use the app icon on the bar's capture button (icon-only, compact)."""
        self.bar_capture_button.setIcon(icon)
        self.bar_capture_button.setIconSize(QSize(20, 20))

    def set_bar_mode(self, enabled: bool) -> None:
        """Switch between the classic popup and the persistent floating bar.

        Enabling does not change the expand state; callers decide whether the
        bar should start collapsed (see ``_show_float_bar``).
        """
        self._bar_mode = bool(enabled)
        if enabled:
            # Identical margins in both states keep the title-bar icons at the
            # exact same screen position while the window grows.
            self._outer_layout.setContentsMargins(0, 4, 0, 4)
            self._card_layout.setContentsMargins(6, 4, 6, 4)
            self._apply_width_bounds()
        else:
            self._expanded = True
            self._outer_layout.setContentsMargins(8, 8, 8, 8)
            self._card_layout.setContentsMargins(8, 4, 8, 8)
            self._apply_width_bounds()
        self._update_bar_ui()

    def _apply_width_bounds(self) -> None:
        if not self._bar_mode:
            self.setMaximumWidth(760)
            self.setMinimumWidth(380)
        elif self._expanded:
            if self._manual_size is not None:
                self.setMinimumWidth(MANUAL_MIN_WIDTH)
                self.setMaximumWidth(MANUAL_MAX_WIDTH)
            else:
                self.setMaximumWidth(760)
                self.setMinimumWidth(380)
        else:
            self.setMinimumWidth(BAR_WIDTH)
            self.setMaximumWidth(BAR_WIDTH)

    def set_expanded(self, expanded: bool) -> None:
        if not self._bar_mode:
            return
        self._expanded = bool(expanded)
        self._apply_width_bounds()
        if self._expanded and self._manual_size is not None:
            self.resize(*self._manual_size)
        self._update_bar_ui()
        self._fit_to_content()

    def toggle_expanded(self) -> None:
        if not self._has_result:
            return
        self.set_expanded(not self._expanded)

    def _update_bar_ui(self) -> None:
        if not self._bar_mode:
            self.bar_capture_button.setVisible(True)
            self.bar_toggle_button.hide()
            self.drag_handle.hide()
            self.status_label.setVisible(not self._loading)
            self.text_browser.setVisible(not self._loading)
            self.tip_content.setVisible(not self._loading and bool(self.tip_content.text()))
            self.followup_input.setVisible(True)
            self.send_button.setVisible(True)
            self.retry_button.setVisible(self._show_retry)
            self.more_button.setVisible(True)
            return
        expanded = self._expanded
        self.status_label.setVisible(True)
        self.text_browser.setVisible(expanded)
        self.tip_content.setVisible(expanded and bool(self.tip_content.text()))
        self.followup_input.setVisible(expanded)
        self.send_button.setVisible(expanded)
        self.retry_button.setVisible(expanded and self._show_retry)
        self.more_button.setVisible(expanded)
        self.bar_capture_button.setVisible(True)
        self.bar_capture_button.setEnabled(not self._busy)
        self.bar_toggle_button.setVisible(True)
        self.bar_toggle_button.setEnabled(self._has_result)
        self.bar_toggle_button.chevron_down = not expanded
        self.bar_toggle_button.update()
        self.drag_handle.setVisible(True)

    def show_loading(self) -> None:
        self.payload = {}
        self._stream_buffers = {"translation": "", "explanation": "", "learning_tip": ""}
        self._stream_terms = []
        self._source_text = ""
        self._fit_width_peak = 0
        self._fit_height_peak = 0
        self._followup_anchor = None
        self._followup_sections = {"translation": "", "explanation": ""}
        self.text_browser.document().setTextWidth(-1)
        self.text_browser.setPlainText("")
        self._set_tip("")
        self.followup_input.clear()
        self._enter_loading()
        self._set_busy(True)
        self._has_result = False
        self._show_retry = False
        self._width_locked = False
        if self._bar_mode:
            self.set_expanded(False)
        self.status_label.setText("正在识别...")
        self._fit_to_content()
        if not self._bar_mode:
            self._move_near_cursor()
        self.show()
        self.raise_()

    def _enter_loading(self) -> None:
        self._loading = True
        self.text_browser.setVisible(False)
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
        self.status_label.setVisible(True)
        self._fit_to_content()

    def append_stream_chunk(self, section: str, chunk: str) -> None:
        """Append a real provider delta, re-rendering both visible sections."""
        if section not in self._stream_buffers or not chunk:
            return
        self._stream_buffers[section] += chunk
        if section == "learning_tip":
            self._set_tip(self._stream_buffers["learning_tip"])
            self._fit_to_content()
            return
        if self._bar_mode and not self._expanded:
            self.set_expanded(True)
        self._exit_loading()
        self.text_browser.document().setTextWidth(-1)
        self.text_browser.setHtml(
            build_result_html(
                translation=self._stream_buffers["translation"],
                explanation=self._stream_buffers["explanation"],
                source_text=self._source_text,
                terms=self._stream_terms,
            )
        )
        self._fit_to_content()

    def set_stream_terms(self, terms: list[dict]) -> None:
        if not isinstance(terms, list):
            return
        self._stream_terms = [term for term in terms if isinstance(term, dict)]
        if self._bar_mode and not self._expanded:
            self.set_expanded(True)
        self._exit_loading()
        self.text_browser.document().setTextWidth(-1)
        self.text_browser.setHtml(
            build_result_html(
                translation=self._stream_buffers["translation"],
                explanation=self._stream_buffers["explanation"],
                source_text=self._source_text,
                terms=self._stream_terms,
            )
        )
        self._fit_to_content()

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
            self.text_browser.document().setTextWidth(-1)
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
        self._show_retry = bool(error) and isinstance(capture_id, int) and capture_id > 0
        self._set_busy(False)
        self._has_result = True
        if self._bar_mode:
            self.set_expanded(True)
        else:
            self._update_bar_ui()
            self._show_actions()
        self._fit_to_content()
        if not self.isVisible():
            self._move_near_cursor()
            self.show()
            self.raise_()

    def _render_error(self, payload: dict, error: str) -> None:
        parts = [
            '<div class="meta-label">错误</div>',
            f'<div class="body-line" style="color:{DANGER};">{html.escape(error)}</div>',
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
        self.text_browser.document().setTextWidth(-1)
        self.text_browser.setHtml("".join(parts))
        self._set_tip("")

    def begin_followup(self) -> None:
        self._followup_sections = {"translation": "", "explanation": ""}
        self.status_label.setText("正在追问...")
        self.status_label.show()
        self.retry_button.hide()
        self._set_busy(True)
        self._width_locked = True
        cursor = self.text_browser.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._followup_anchor = cursor.position()
        cursor.insertHtml(self._followup_block_html(pending=True))
        self.text_browser.setTextCursor(cursor)
        self._fit_to_content()

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
                f'<div class="body-line" style="color:{DANGER};">{html.escape(error)}</div>'
            )
        elif not translation and not explanation:
            if pending:
                parts.append(
                    f'<div class="body-line" style="color:{MUTED};">思考中…</div>'
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
        current = self._font_size
        size = max(MIN_RESULT_FONT_SIZE, min(MAX_RESULT_FONT_SIZE, current + delta))
        if size == current:
            return
        self._font_size = size
        font = self.text_browser.font()
        font.setPixelSize(size)
        self.text_browser.setFont(font)
        self.text_browser.document().setDefaultFont(font)
        self._refresh_document_font()
        self._apply_style()
        self.font_size_changed.emit(size)
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
        self.bar_capture_button.setEnabled(not busy)

    def _fit_to_content(self) -> None:
        screen = (
            QApplication.screenAt(self.frameGeometry().center())
            or QApplication.screenAt(QCursor.pos())
            or QApplication.primaryScreen()
        )
        available = screen.availableGeometry() if screen is not None else None
        available_width = available.width() if available is not None else 1280
        available_height = available.height() if available is not None else 800
        old_rect = self.geometry()

        if self._bar_mode and not self._expanded:
            anchor = self._bar_anchor_rect or old_rect
            self._outer_layout.activate()
            self._card_layout.activate()
            self.adjustSize()
            height = max(30, min(48, self.sizeHint().height()))
            x = anchor.left()
            y = anchor.top()
            if available is not None:
                x = max(available.left(), min(x, available.right() - BAR_WIDTH + 1))
                y = max(available.top(), min(y, available.bottom() - height + 1))
            self.setGeometry(x, y, BAR_WIDTH, height)
            if self._bar_anchor_rect is None:
                self._bar_anchor_rect = self.geometry()
            return

        if self._loading:
            self._outer_layout.activate()
            self._card_layout.activate()
            self.adjustSize()
            width = max(200, min(300, self.sizeHint().width()))
            self.resize(width, self.height())
            return

        if self._manual_size is not None:
            # User-sized: keep the geometry; just re-wrap at the viewport
            # width so streaming content never fights the manual size.
            self.text_browser.setMinimumHeight(40)
            self.text_browser.setMaximumHeight(720)
            self._outer_layout.activate()
            self._card_layout.activate()
            self.text_browser.document().setTextWidth(
                max(1, self.text_browser.viewport().width())
            )
            return

        # 6 (outer shadow margin) * 2 + 6+6 (card margins) + 2*2 (doc margins)
        horizontal_padding = 28
        document = self.text_browser.document()
        max_width = min(500, available_width - 40)
        anchor_ref = self._bar_anchor_rect or old_rect
        if self._width_locked:
            # Follow-ups keep the settled width; only the height may grow.
            target_width = self._fit_width_peak
        else:
            ideal = int(document.idealWidth())
            target_width = min(max_width, max(380, ideal + horizontal_padding))
            target_width = max(340, target_width)
            self._fit_width_peak = max(self._fit_width_peak, target_width)
            target_width = self._fit_width_peak

        # Resize and lay out synchronously, then expose only the final geometry
        # to Qt's normal event loop. Pumping the event loop between these steps
        # both flashes the translucent window on every chunk and can re-enter
        # this method recursively via queued stream signals (stack overflow).
        # ``adjustSize()`` is also avoided: it resizes to the layout's
        # totalSizeHint (narrower than the target width), causing a shrink/
        # regrow flash on every chunk.
        self.resize(target_width, self.height())
        self._outer_layout.activate()
        self._card_layout.activate()
        viewport_width = self.text_browser.viewport().width()
        document.setTextWidth(max(1, viewport_width or target_width - horizontal_padding))
        height = int(document.size().height()) + 4
        max_body_height = max(180, min(560, int(available_height * 0.55)))
        self._fit_height_peak = max(self._fit_height_peak, min(max_body_height, height))
        self.text_browser.setMaximumHeight(max_body_height)
        self.text_browser.setFixedHeight(max(72, self._fit_height_peak))
        self._card_layout.invalidate()
        card_hint = self._card_layout.totalSizeHint()
        final_height = (
            self._outer_layout.contentsMargins().top()
            + self._outer_layout.contentsMargins().bottom()
            + card_hint.height()
        )
        self.resize(target_width, final_height)
        if available is not None and self.isVisible():
            if self._bar_mode:
                self._anchor_to_edges(anchor_ref, available)
            else:
                if self.x() + self.width() > available.right():
                    self.move(available.right() - self.width() + 1, self.y())
                if self.y() + self.height() > available.bottom():
                    self.move(self.x(), available.bottom() - self.height() + 1)

    def _anchor_to_edges(self, ref_rect, available) -> None:
        """Keep the bar's top-left anchored; clamp only to stay on screen.

        No edge-reversal: the window always grows right/down from the bar, and
        the user positions the bar wherever the window should appear.
        """
        x = ref_rect.left()
        y = ref_rect.top()
        x = max(available.left(), min(x, available.right() - self.width() + 1))
        y = max(available.top(), min(y, available.bottom() - self.height() + 1))
        self.move(x, y)

    def _set_tip(self, text: str) -> None:
        tip = compact_line_breaks(text)
        self.tip_content.setText(tip)
        self.tip_content.setVisible(
            bool(tip)
            and not self._loading
            and (not self._bar_mode or self._expanded)
        )
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
            if self._bar_mode and self._expanded:
                edge = self._hit_resize_edge(event.position().toPoint())
                if edge:
                    self._start_resize(edge, event.globalPosition().toPoint())
                    return
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._resize_edge is not None:
            self._apply_resize(event.globalPosition().toPoint())
            return
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            return
        if self._bar_mode and self._expanded:
            edge = self._hit_resize_edge(event.position().toPoint())
            self.setCursor(self._resize_cursor(edge) if edge else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._resize_edge is not None:
            self._finish_resize()
            return
        if self._drag_offset is not None:
            if self._bar_mode and not self._expanded:
                self._bar_anchor_rect = self.geometry()
                self.position_changed.emit(self.x(), self.y())
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def _hit_resize_edge(self, pos: QPoint) -> str | None:
        rect = self.rect()
        left = pos.x() <= rect.left() + _RESIZE_MARGIN
        right = pos.x() >= rect.right() - _RESIZE_MARGIN
        top = pos.y() <= rect.top() + _RESIZE_MARGIN
        bottom = pos.y() >= rect.bottom() - _RESIZE_MARGIN
        if top and left:
            return "top-left"
        if top and right:
            return "top-right"
        if bottom and left:
            return "bottom-left"
        if bottom and right:
            return "bottom-right"
        if left:
            return "left"
        if right:
            return "right"
        if top:
            return "top"
        if bottom:
            return "bottom"
        return None

    def _resize_cursor(self, edge: str | None):
        return _RESIZE_CURSORS.get(edge, Qt.CursorShape.ArrowCursor)

    def _start_resize(self, edge: str, global_pos: QPoint) -> None:
        self._resize_edge = edge
        self._resize_start = (global_pos, self.geometry())
        self.setCursor(self._resize_cursor(edge))

    def _apply_resize(self, global_pos: QPoint) -> None:
        if self._resize_edge is None or self._resize_start is None:
            return
        start_pos, start_geo = self._resize_start
        delta = global_pos - start_pos
        edge = self._resize_edge
        x, y, w, h = start_geo.x(), start_geo.y(), start_geo.width(), start_geo.height()
        if "left" in edge:
            w -= delta.x()
        if "right" in edge:
            w += delta.x()
        if "top" in edge:
            h -= delta.y()
        if "bottom" in edge:
            h += delta.y()
        w = max(MANUAL_MIN_WIDTH, min(MANUAL_MAX_WIDTH, w))
        h = max(MANUAL_MIN_HEIGHT, min(MANUAL_MAX_HEIGHT, h))
        if "left" in edge:
            x = start_geo.right() - w + 1
        if "top" in edge:
            y = start_geo.bottom() - h + 1
        self.setGeometry(x, y, w, h)

    def _finish_resize(self) -> None:
        if self._resize_edge is None:
            return
        self._resize_edge = None
        self._resize_start = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._manual_size = (self.width(), self.height())
        self._apply_width_bounds()
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            g = self.geometry()
            x = max(avail.left(), min(g.x(), avail.right() - g.width() + 1))
            y = max(avail.top(), min(g.y(), avail.bottom() - g.height() + 1))
            self.move(x, y)
        self.size_changed.emit(self.width(), self.height())

    def set_manual_size(self, width: int, height: int) -> None:
        """Apply a persisted manual size (loaded from settings)."""
        self._manual_size = (int(width), int(height))
        self._apply_width_bounds()
        if self._bar_mode and self._expanded:
            self.resize(*self._manual_size)
            self._fit_to_content()

    def reset_size(self) -> None:
        """Return to auto-fitting the window to the content."""
        if self._manual_size is None:
            return
        self._manual_size = None
        self._fit_width_peak = 0
        self._fit_height_peak = 0
        self._apply_width_bounds()
        if self._bar_mode and self._expanded:
            self._fit_to_content()
        self.size_reset.emit()

    def home_position(self) -> tuple[int, int]:
        """The collapsed bar's stable home position (fallback: current)."""
        if self._bar_anchor_rect is not None:
            return self._bar_anchor_rect.x(), self._bar_anchor_rect.y()
        return self.x(), self.y()

    def set_home_position(self, x: int, y: int) -> None:
        """Move the collapsed bar and record it as the stable home."""
        self.move(int(x), int(y))
        if self._bar_mode and not self._expanded:
            self._bar_anchor_rect = self.geometry()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def force_close(self) -> None:
        self.close()
