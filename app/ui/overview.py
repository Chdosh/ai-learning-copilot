"""学习概览页：学习记录索引、阅读面和追问入口。

新建学习入口（截图）在侧栏，本页负责查看与深入学习。
布局：左侧历史记录索引（固定 216px） + 右侧阅读面。
原图和原文位于阅读面上方，解释在其下方，关键词常驻在正文下方。
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
    QScrollArea,
)

from app.services.history_store import HistoryStore
from app.services.settings import SettingsService
from app.ui.message_render import DOC_STYLESHEET, build_result_html, render_lines
from app.ui.theme import (
    ArrowSendButton,
    BG,
    BORDER,
    BORDER_LIGHT,
    CARD,
    ChevronComboBox,
    DANGER,
    DANGER_BORDER,
    DANGER_SOFT,
    DISABLED,
    FONT_BODY,
    FONT_MICRO,
    FONT_TITLE,
    MUTED,
    PRIMARY,
    PRIMARY_DARK,
    PRIMARY_SOFT,
    RADIUS_LG,
    RADIUS_MD,
    RADIUS_SM,
    TEXT,
    TEXT_SECONDARY,
)
from app.ui.workers import FollowupWorker

_OVERVIEW_DOC_STYLESHEET = DOC_STYLESHEET + f"""
body {{ color: {TEXT_SECONDARY}; }}
.meta-label {{
    margin: 14px 0 5px 0;
    color: {MUTED};
    font-size: 0.78em;
}}
.source-block {{
    margin: 0 0 12px 0;
    padding: 12px 14px;
    background: {BORDER_LIGHT};
    border-radius: 8px;
    color: {TEXT_SECONDARY};
    line-height: 1.5;
}}
table.source-block {{
    width: 100%;
    margin: 0 0 12px 0;
    border-collapse: collapse;
    background: {BORDER_LIGHT};
}}
table.source-block td {{
    padding: 12px 14px;
    background: {BORDER_LIGHT};
    color: {TEXT_SECONDARY};
    line-height: 1.5;
}}
.lead {{
    margin: 0 0 6px 0;
    color: {TEXT};
    font-size: 1.12em;
    line-height: 1.55;
}}
.body-line {{
    margin: 2px 0;
    color: {TEXT_SECONDARY};
    line-height: 1.55;
}}
.term-row {{
    margin: 4px 0;
    color: {TEXT_SECONDARY};
    line-height: 1.45;
}}
.followup-block {{
    margin: 18px 0 8px 0;
    padding: 10px 13px;
    background: {PRIMARY_SOFT};
    border-left: 3px solid {PRIMARY};
    border-radius: 0 8px 8px 0;
}}
.followup-block .meta-label {{ margin-top: 0; color: {PRIMARY_DARK}; }}
.followup-answer {{
    margin: 0 0 10px 0;
    padding-left: 16px;
    border-left: 1px solid {BORDER};
}}
.empty-state {{ color: {MUTED}; line-height: 1.6; }}
"""


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
    meta = created
    if record.category:
        meta += f" · {record.category}"
    return f"{_compact(title, 22)}\n{meta}"


def _render_overview_source_block(text: str) -> str:
    if not text or not text.strip():
        return '<table width="100%" class="source-block"><tr><td>（无原文）</td></tr></table>'
    escaped = html.escape(text.strip()).replace("\n", "<br/>")
    return f'<table width="100%" class="source-block"><tr><td>{escaped}</td></tr></table>'


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"color: {TEXT_SECONDARY}; font-size: {FONT_BODY}; "
        f"border-left: 3px solid {PRIMARY}; padding-left: 8px;"
    )
    label.setFixedHeight(22)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return label


class _SessionDelegate(QStyledItemDelegate):
    """Draw the record title and metadata as two deliberate visual levels."""

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: N802
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect.adjusted(4, 2, -4, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hovered:
            fill = PRIMARY_SOFT if selected else CARD
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(fill))
            painter.drawRoundedRect(rect, 8, 8)
        if selected:
            painter.setBrush(QColor(PRIMARY))
            painter.drawRoundedRect(QRect(rect.left(), rect.top(), 3, rect.height()), 1, 1)

        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        title, _, meta = text.partition("\n")
        created, _, category = meta.partition(" · ")
        title_font = QFont(option.font)
        title_font.setBold(selected)
        title_font.setPixelSize(max(12, option.font.pixelSize() + 1))
        category_font = QFont(option.font)
        category_font.setPixelSize(max(10, title_font.pixelSize() - 2))
        meta_font = QFont(option.font)
        meta_font.setPixelSize(max(10, title_font.pixelSize() - 2))

        title_rect = rect.adjusted(12, 5, -8, -rect.height() // 2)
        meta_rect = rect.adjusted(12, rect.height() // 2, -8, -5)
        title_text = QFontMetrics(title_font).elidedText(
            title, Qt.TextElideMode.ElideRight, title_rect.width()
        )
        painter.setFont(title_font)
        painter.setPen(QColor(TEXT))
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
            title_text,
        )
        if category:
            category_x = title_rect.left() + QFontMetrics(title_font).horizontalAdvance(title_text) + 10
            category_rect = QRect(
                category_x,
                title_rect.top(),
                max(0, title_rect.right() - category_x),
                title_rect.height(),
            )
            painter.setFont(category_font)
            painter.setPen(QColor(MUTED))
            painter.drawText(
                category_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                QFontMetrics(category_font).elidedText(
                    category, Qt.TextElideMode.ElideRight, category_rect.width()
                ),
            )
        painter.setFont(meta_font)
        painter.setPen(QColor(MUTED))
        painter.drawText(
            meta_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            QFontMetrics(meta_font).elidedText(
                created, Qt.TextElideMode.ElideRight, meta_rect.width()
            ),
        )
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        size = super().sizeHint(option, index)
        size.setHeight(50)
        return size


class _SendButton(ArrowSendButton):
    """A compact send control with a font-independent arrow glyph."""


class OverviewPage(QWidget):
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

        # The learning direction is global setup state, not part of this reading page.
        self.direction_label = QLabel("")
        self.direction_label.hide()

        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(0)
        columns.addWidget(self._build_session_panel())
        columns.addWidget(self._build_center_panel(), 1)
        layout.addLayout(columns, 1)

    def _build_session_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("sessionPanel")
        panel.setFixedWidth(216)
        panel.setStyleSheet(
            f"QWidget#sessionPanel {{ background: {BG}; border-right: 1px solid {BORDER_LIGHT}; }}"
        )
        v = QVBoxLayout(panel)
        v.setContentsMargins(14, 14, 12, 14)
        v.setSpacing(10)

        session_header = QHBoxLayout()
        session_header.setContentsMargins(2, 0, 2, 0)
        session_header.setSpacing(6)
        session_title = QLabel("历史记录")
        session_title.setStyleSheet(f"font-size: {FONT_TITLE}; color: {TEXT};")
        session_header.addWidget(session_title)
        self.session_count_label = QLabel("0 条")
        self.session_count_label.setStyleSheet(
            f"color: {MUTED}; font-size: {FONT_MICRO};"
        )
        session_header.addWidget(self.session_count_label)
        session_header.addStretch(1)
        v.addLayout(session_header)

        self.session_search = QLineEdit()
        self.session_search.setPlaceholderText("搜索标题或内容")
        self.session_search.setClearButtonEnabled(True)
        self.session_search.setStyleSheet(
            f"padding: 7px 10px; border: 1px solid {BORDER}; border-radius: {RADIUS_MD};"
            f"background: {CARD};"
        )
        self.session_search.textChanged.connect(self.refresh_sessions)
        v.addWidget(self.session_search)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)

        def add_filter_column(label_text: str, widget: QWidget, width: int) -> None:
            column = QWidget()
            column_layout = QVBoxLayout(column)
            column_layout.setContentsMargins(0, 0, 0, 0)
            column_layout.setSpacing(3)
            label = QLabel(label_text)
            label.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
            column_layout.addWidget(label)
            widget.setFixedWidth(width)
            widget.setMinimumHeight(30)
            column_layout.addWidget(widget)
            filter_row.addWidget(column, 0)

        self.time_filter_combo = ChevronComboBox()
        self.time_filter_combo.addItems(["全部", "今天", "本周"])
        self.time_filter_combo.setToolTip("时间范围")
        self.time_filter_combo.currentIndexChanged.connect(self._on_time_filter_changed)
        add_filter_column("时间范围", self.time_filter_combo, 64)

        self.domain_filter_combo = ChevronComboBox()
        self.domain_filter_combo.setMaxVisibleItems(8)
        self.domain_filter_combo.setToolTip("按内容领域筛选学习记录")
        self.domain_filter_combo.currentIndexChanged.connect(self._on_domain_filter_selected)
        add_filter_column("内容领域", self.domain_filter_combo, 64)

        self.followup_filter_toggle = QPushButton("追问")
        self.followup_filter_toggle.setObjectName("followupFilter")
        self.followup_filter_toggle.setCheckable(True)
        self.followup_filter_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.followup_filter_toggle.setToolTip("只显示有过追问的学习记录")
        self.followup_filter_toggle.setFixedHeight(30)
        self.followup_filter_toggle.setStyleSheet(
            f"""
            QPushButton#followupFilter {{
                background: {CARD};
                border: 1px solid {BORDER};
                border-radius: {RADIUS_SM};
                padding: 4px 7px;
                color: {TEXT_SECONDARY};
            }}
            QPushButton#followupFilter:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; }}
            QPushButton#followupFilter:checked {{
                background: {PRIMARY_SOFT};
                border-color: {PRIMARY};
                color: {PRIMARY_DARK};
            }}
            """
        )
        self.followup_filter_toggle.toggled.connect(self._on_followup_filter_toggled)
        add_filter_column("状态", self.followup_filter_toggle, 52)
        v.addLayout(filter_row)

        self.session_list = QListWidget()
        self.session_list.setObjectName("sessionList")
        self.session_list.setSpacing(2)
        self.session_list.setMouseTracking(True)
        self.session_list.setUniformItemSizes(True)
        self.session_list.setItemDelegate(_SessionDelegate(self.session_list))
        self.session_list.setStyleSheet(
            f"""
            QListWidget#sessionList {{
                background: transparent;
                border: none;
                outline: 0;
            }}
            QListWidget#sessionList::item {{
                background: transparent;
                border: none;
            }}
            """
        )
        self.session_list.itemClicked.connect(self._on_session_clicked)
        v.addWidget(self.session_list, 1)
        return panel

    def _build_center_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("readingPanel")
        panel.setStyleSheet(f"QWidget#readingPanel {{ background: {BG}; }}")
        v = QVBoxLayout(panel)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)

        record_header = QWidget()
        record_header_layout = QHBoxLayout(record_header)
        record_header_layout.setContentsMargins(0, 0, 0, 0)
        record_header_layout.setSpacing(12)
        record_title_row = QHBoxLayout()
        record_title_row.setContentsMargins(0, 0, 0, 0)
        record_title_row.setSpacing(8)

        self.header_title = QLabel("选择一条学习记录")
        self.header_title.setStyleSheet(
            f"font-size: {FONT_TITLE}; color: {TEXT};"
        )
        self.header_meta = QLabel("")
        self.header_meta.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        self.header_meta.setWordWrap(False)
        self.header_meta.setVisible(False)
        record_title_row.addWidget(self.header_title)
        record_title_row.addWidget(self.header_meta)
        record_title_row.addStretch(1)
        record_header_layout.addLayout(record_title_row, 1)

        # Delete is the only remaining record-level action, so it stays visible.
        self.actions_menu_button = QPushButton("删除")
        self.actions_menu_button.setObjectName("deleteRecordButton")
        self.actions_menu_button.setStyleSheet(
            f"""
            QPushButton#deleteRecordButton {{
                background: transparent;
                border: 1px solid {DANGER_BORDER};
                border-radius: {RADIUS_MD};
                padding: 6px 12px;
                color: {DANGER};
            }}
            QPushButton#deleteRecordButton:hover {{ background: {DANGER_SOFT}; }}
            QPushButton#deleteRecordButton:disabled {{
                background: transparent;
                color: {DISABLED};
                border-color: {BORDER};
            }}
            """
        )
        self.actions_menu_button.setEnabled(False)
        self.actions_menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.actions_menu_button.setToolTip("删除当前学习记录")
        self.actions_menu_button.clicked.connect(self._delete_capture)
        record_header_layout.addWidget(self.actions_menu_button, 0, Qt.AlignmentFlag.AlignTop)
        v.addWidget(record_header)

        content_row = QWidget()
        content_layout = QHBoxLayout(content_row)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(22)

        self.screenshot_column = QWidget()
        screenshot_layout = QVBoxLayout(self.screenshot_column)
        screenshot_layout.setContentsMargins(0, 0, 0, 0)
        screenshot_layout.setSpacing(10)
        screenshot_layout.addWidget(_section_label("截图"))

        self.center_image = _ClickableLabel("")
        self.center_image.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.center_image.setFixedSize(160, 120)
        self.center_image.setStyleSheet("background: transparent; border: none;")
        self.center_image.setCursor(Qt.CursorShape.PointingHandCursor)
        self.center_image.clicked.connect(self._open_source_image)
        self.center_image.setVisible(False)
        screenshot_layout.addWidget(self.center_image)
        screenshot_layout.addStretch(1)
        content_layout.addWidget(self.screenshot_column, 0, Qt.AlignmentFlag.AlignTop)

        self.source_column = QWidget()
        source_layout = QVBoxLayout(self.source_column)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(2)
        source_layout.addWidget(_section_label("原文"))

        self.source_browser = QTextBrowser()
        self.source_browser.setObjectName("sourceBrowser")
        self.source_browser.setOpenExternalLinks(False)
        self.source_browser.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.source_browser.document().setDocumentMargin(0)
        self.source_browser.document().setDefaultStyleSheet(_OVERVIEW_DOC_STYLESHEET)
        source_font = self.source_browser.font()
        source_font.setPixelSize(14)
        self.source_browser.setFont(source_font)
        self.source_browser.setStyleSheet(
            f"""
            QTextBrowser#sourceBrowser {{
                background: transparent;
                border: none;
            }}
            QTextBrowser#sourceBrowser QScrollBar:vertical {{
                width: 6px;
                background: {PRIMARY_SOFT};
                margin: 0;
            }}
            QTextBrowser#sourceBrowser QScrollBar::handle:vertical {{
                background: #afc3f4;
                border-radius: 3px;
                min-height: 24px;
            }}
            QTextBrowser#sourceBrowser QScrollBar::add-line:vertical,
            QTextBrowser#sourceBrowser QScrollBar::sub-line:vertical {{
                height: 0;
                border: none;
            }}
            """
        )
        self.source_browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.source_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.source_browser.setMinimumHeight(120)
        self.source_browser.setMaximumHeight(180)
        self.source_browser.setVisible(False)
        source_layout.addWidget(self.source_browser, 1)
        content_layout.addWidget(self.source_column, 1)
        self.screenshot_column.setVisible(False)
        self.source_column.setVisible(False)
        v.addWidget(content_row)

        self.explanation_label = _section_label("解释")
        v.addWidget(self.explanation_label)

        self.message_browser = QTextBrowser()
        self.message_browser.setObjectName("readingBrowser")
        self.message_browser.setOpenExternalLinks(False)
        self.message_browser.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.message_browser.document().setDocumentMargin(0)
        self.message_browser.document().setDefaultStyleSheet(_OVERVIEW_DOC_STYLESHEET)
        base_font = self.message_browser.font()
        base_font.setPixelSize(14)
        self.message_browser.setFont(base_font)
        self.message_browser.setStyleSheet(
            f"""
            QTextBrowser#readingBrowser {{
                background: transparent;
                border: none;
            }}
            QTextBrowser#readingBrowser QScrollBar:vertical {{
                width: 6px;
                background: {PRIMARY_SOFT};
                margin: 0;
            }}
            QTextBrowser#readingBrowser QScrollBar::handle:vertical {{
                background: #afc3f4;
                border-radius: 3px;
                min-height: 24px;
            }}
            QTextBrowser#readingBrowser QScrollBar::add-line:vertical,
            QTextBrowser#readingBrowser QScrollBar::sub-line:vertical {{
                height: 0;
                border: none;
            }}
            """
        )
        self.message_browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.message_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.message_browser.setMinimumHeight(160)
        v.addWidget(self.message_browser, 1)

        terms_section = QFrame()
        terms_section.setObjectName("termsSection")
        terms_section.setStyleSheet(
            f"QFrame#termsSection {{ border-top: 1px solid {BORDER}; background: transparent; }}"
        )
        terms_layout = QVBoxLayout(terms_section)
        terms_layout.setContentsMargins(0, 8, 0, 0)
        terms_layout.setSpacing(4)
        terms_layout.addWidget(_section_label("关键词"))
        self.context_terms = QLabel("")
        self.context_terms.setObjectName("contextTerms")
        self.context_terms.setWordWrap(True)
        self.context_terms.setMinimumHeight(28)
        self.context_terms.setMaximumHeight(72)
        self.context_terms.setStyleSheet(
            f"""
            QLabel#contextTerms {{
                background: transparent;
                color: {TEXT_SECONDARY};
                padding: 2px 0;
            }}
            """
        )
        terms_layout.addWidget(self.context_terms)
        v.addWidget(terms_section)

        composer = QFrame()
        composer.setObjectName("followupComposer")
        composer.setStyleSheet(
            f"QFrame#followupComposer {{ background: {CARD}; border: 1px solid {BORDER}; "
            f"border-radius: {RADIUS_LG}; }}"
        )
        input_row = QHBoxLayout(composer)
        input_row.setContentsMargins(8, 5, 8, 5)
        input_row.setSpacing(8)
        composer.setMinimumHeight(42)
        self.followup_input = QLineEdit()
        self.followup_input.setPlaceholderText("继续问这条内容...")
        self.followup_input.setStyleSheet(
            "QLineEdit { padding: 6px 8px; border: none; background: transparent; }"
        )
        self.followup_input.returnPressed.connect(self.send_followup)
        self.send_followup_button = _SendButton()
        self.send_followup_button.setStyleSheet(
            f"""
            QPushButton#primaryButton {{
                background: {BORDER};
                color: {MUTED};
                border: 0;
                border-radius: 15px;
                padding: 0;
            }}
            QPushButton#primaryButton[active="true"] {{ background: {PRIMARY}; color: #fff; }}
            QPushButton#primaryButton[active="true"]:hover {{ background: {PRIMARY_DARK}; }}
            QPushButton#primaryButton:disabled {{ background: {BORDER_LIGHT}; color: {DISABLED}; }}
            """
        )
        self.send_followup_button.setProperty("active", False)
        self.send_followup_button.setToolTip("发送")
        self.send_followup_button.setAccessibleName("发送")
        self.send_followup_button.clicked.connect(self.send_followup)
        self.followup_input.textChanged.connect(self._update_send_button_state)
        input_row.addWidget(self.followup_input, 1)
        input_row.addWidget(self.send_followup_button)
        v.addWidget(composer)
        self.followup_input.setEnabled(False)
        self.send_followup_button.setEnabled(False)
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
        else:
            domain, scene = self.settings_service.get_quick_context()
            name = f"{domain} · {scene}" if scene != "通用" else domain
        self.direction_label.setText(f"学习方向 · {name}")

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

        selected_capture_id = self.current_capture.id if self.current_capture else None
        self.session_list.clear()
        for record in records:
            item = QListWidgetItem(_session_text(record))
            item.setData(Qt.ItemDataRole.UserRole, record.id)
            self.session_list.addItem(item)

        self.session_count_label.setText(f"{len(records)} 条")
        if records:
            target_id = next(
                (record.id for record in records if record.id == selected_capture_id),
                records[0].id,
            )
            self.select_capture(target_id)
        else:
            self._clear_capture_view()

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

        for row in range(self.session_list.count()):
            item = self.session_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == capture_id:
                self.session_list.setCurrentRow(row)
                self.session_list.scrollToItem(item)
                break

        self.current_capture = record
        self.current_conversation_id = self.history_store.get_conversation_id_for_capture(capture_id)
        self._followup_stream = {}
        self.followup_input.setEnabled(True)
        self.send_followup_button.setEnabled(True)
        self._update_send_button_state()
        self.actions_menu_button.setEnabled(True)

        title = (record.source_text or record.translation or "截图").strip().splitlines()
        self.header_title.setText(_compact(title[0] if title else "截图", 50))
        meta_parts: list[str] = []
        if record.category:
            meta_parts.append(record.category)
        if record.tags:
            meta_parts.append("、".join(record.tags[:5]))
        self.header_meta.setText("  ·  ".join(meta_parts))
        self.header_meta.setVisible(bool(meta_parts))

        self._load_center_image(record.image_path or "")
        self._render_source_browser()
        self._render_conversation()
        self._load_context_terms()

    def _clear_capture_view(self) -> None:
        self.current_capture = None
        self.current_conversation_id = None
        self._followup_stream = {}
        self.session_list.clearSelection()
        self.header_title.setText("选择一条学习记录")
        self.header_meta.setText("")
        self.header_meta.setVisible(False)
        self.source_browser.setHtml("")
        self.message_browser.setHtml(
            '<div class="empty-state">从左侧选择一条学习记录开始阅读。</div>'
        )
        self.center_image.setPixmap(QPixmap())
        self.center_image.setVisible(False)
        self.screenshot_column.setVisible(False)
        self.source_column.setVisible(False)
        self.context_terms.setText("")
        self.followup_input.clear()
        self.followup_input.setEnabled(False)
        self.send_followup_button.setEnabled(False)
        self._update_send_button_state()
        self.actions_menu_button.setEnabled(False)

    def _has_source_image(self) -> bool:
        if self.current_capture is None:
            return False
        image_path = self.current_capture.image_path or ""
        return bool(image_path and Path(image_path).exists())

    def _update_send_button_state(self) -> None:
        active = bool(
            self.current_capture is not None
            and self.followup_input.isEnabled()
            and self.followup_input.text().strip()
        )
        self.send_followup_button.setProperty("active", active)
        self.send_followup_button.style().unpolish(self.send_followup_button)
        self.send_followup_button.style().polish(self.send_followup_button)
        self.send_followup_button.update()

    def _load_center_image(self, image_path: str) -> None:
        self.center_image.setPixmap(QPixmap())
        self.center_image.setVisible(False)
        self.screenshot_column.setVisible(False)
        self.source_column.setVisible(False)
        self.source_browser.setVisible(False)
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
                self.screenshot_column.setVisible(True)
                self.source_column.setVisible(True)
                self.source_browser.setVisible(True)
                return

    def _render_source_browser(self) -> None:
        if self.current_capture is None or not self._has_source_image():
            self.source_browser.setHtml("")
            return
        self.source_browser.setHtml(
            _render_overview_source_block(self.current_capture.source_text or "")
        )

    def _open_source_image(self) -> None:
        if self.current_capture is None:
            return
        image_path = self.current_capture.image_path or ""
        if not image_path or not Path(image_path).exists():
            return
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("原始截图")
        dialog.setStyleSheet(f"QDialog {{ background: {BG}; }}")
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(10, 10, 10, 10)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(
            f"QScrollArea {{ background: {BG}; border: none; }}"
        )
        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setPixmap(pixmap)
        image_label.setStyleSheet("background: transparent; border: none;")
        scroll_area.setWidget(image_label)
        dialog_layout.addWidget(scroll_area)

        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            dialog.resize(
                min(max(640, pixmap.width() + 40), int(available.width() * 0.85)),
                min(max(480, pixmap.height() + 40), int(available.height() * 0.85)),
            )
        else:
            dialog.resize(800, 600)
        dialog.exec()

    def _load_context_terms(self) -> None:
        terms = self._capture_terms()
        labels: list[str] = []
        for term in terms[:8]:
            name = str(term.get("term", "")).strip()
            chinese_name = str(term.get("chinese_name", "")).strip()
            label = f"{name} · {chinese_name}" if chinese_name else name
            if label:
                labels.append(label)
        self.context_terms.setText("    ".join(labels) if labels else "暂未提取关键词")

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

    def _render_conversation(self, *, scroll_to_end: bool = False) -> None:
        if self.current_capture is None:
            self.message_browser.setHtml(
                '<div class="empty-state">从左侧选择一条学习记录开始阅读。</div>'
            )
            return
        record = self.current_capture
        parts: list[str] = []
        if not self._has_source_image():
            parts.append('<div class="meta-label">原文</div>')
            parts.append(_render_overview_source_block(record.source_text or ""))
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
                    parts.append('<div class="followup-block">')
                    parts.append('<div class="meta-label">你的追问</div>')
                    parts.append(render_lines(message.content))
                    parts.append('</div>')
                elif message.role == "assistant" and message.mode not in ("default", "retry"):
                    try:
                        data = json.loads(message.content)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    parts.append('<div class="followup-answer">')
                    parts.append(build_result_html(
                        translation=str(data.get("translation") or ""),
                        explanation=str(data.get("explanation") or ""),
                        terms=data.get("terms") or [],
                    ))
                    parts.append('</div>')

        pending = self._followup_stream
        if pending.get("question"):
            parts.append('<div class="followup-block">')
            parts.append('<div class="meta-label">你的追问</div>')
            parts.append(render_lines(pending["question"]))
            parts.append('</div>')
            parts.append('<div class="followup-answer">')
            if pending.get("explanation"):
                parts.append(build_result_html(
                    translation=pending.get("translation", ""),
                    explanation=pending.get("explanation", ""),
                ))
            else:
                parts.append(f'<div class="body-line" style="color:{MUTED};">思考中…</div>')
            parts.append('</div>')

        self.message_browser.setHtml("".join(parts))
        cursor = self.message_browser.textCursor()
        cursor.movePosition(
            cursor.MoveOperation.End if scroll_to_end else cursor.MoveOperation.Start
        )
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
        self.send_followup_button.setEnabled(False)
        self._update_send_button_state()
        self._render_conversation(scroll_to_end=True)
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
            self._render_conversation(scroll_to_end=True)
            QApplication.processEvents()

    def _on_followup_done(self, payload: dict) -> None:
        self._followup_stream = {}
        self.followup_input.setEnabled(True)
        self.send_followup_button.setEnabled(True)
        self._update_send_button_state()
        if payload.get("error"):
            self.message_browser.insertHtml(
                f'<div class="body-line" style="color:{DANGER};">{payload["error"]}</div>'
            )
        else:
            self.refresh_sessions()
            self._render_conversation(scroll_to_end=True)

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
        self._clear_capture_view()
        self.refresh()

    def refresh_domain_filter(self) -> None:
        counts = self.history_store.capture_domain_counts()
        available = {domain for domain, _ in counts}
        if self._domain_filter and self._domain_filter not in available:
            self._domain_filter = ""

        self.domain_filter_combo.blockSignals(True)
        self.domain_filter_combo.clear()
        self.domain_filter_combo.addItem("全部", "")
        for domain, _count in counts:
            self.domain_filter_combo.addItem(domain, domain)
        selected = self.domain_filter_combo.findData(self._domain_filter)
        self.domain_filter_combo.setCurrentIndex(max(0, selected))
        self.domain_filter_combo.blockSignals(False)

    def _on_domain_filter_selected(self, index: int) -> None:
        self._domain_filter = str(self.domain_filter_combo.itemData(index) or "")
        self.refresh_sessions()
