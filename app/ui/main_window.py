from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, QThread, Signal
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QInputDialog,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app import VERSION_LABEL
from app.paths import DATA_DIR, DB_PATH, PROJECT_DIR, SCREENSHOTS_DIR, ensure_app_dirs
from app.services.categorizer import get_all_categories
from app.services.history_store import CaptureRecord, HistoryStore, TermRecord
from app.services.knowledge_base import (
    KnowledgeBase,
    SaveTermCommand,
    TermQuery,
    TermViewItem,
)
from app.services.ocr import OCRService
from app.services.screenshot import ScreenshotError, take_screenshots
from app.services.hotkey import HotkeyManager
from app.services.settings import AppSettings, SettingsService
from app.ui.learning_page import LearningPage
from app.ui.overview import OverviewPage
from app.ui.result_window import ResultWindow
from app.ui.review import ReviewDialog
from app.ui.theme import (
    APP_STYLE,
    BG,
    BORDER,
    BORDER_LIGHT,
    CARD,
    ChevronComboBox,
    DANGER,
    DISABLED,
    FONT_BODY,
    FONT_HEADING,
    FONT_MICRO,
    FONT_TITLE,
    MUTED,
    PRIMARY,
    PRIMARY_DARK,
    PRIMARY_SOFT,
    RADIUS_LG,
    RADIUS_MD,
    RADIUS_PILL,
    RADIUS_SM,
    SUCCESS,
    TEXT,
    TEXT_SECONDARY,
    apply_primary_button_style,
    button_qss,
    card_qss,
    ensure_label_backgrounds_transparent,
    nav_qss,
)
from app.ui.workbench import WorkbenchPage
from app.ui.workers import CaptureStreamWorker, FollowupWorker

TERMS_PAGE_SIZE = 20


def _compact_text(text: str, limit: int) -> str:
    normalized = " ".join((text or "").split())
    return normalized if len(normalized) <= limit else f"{normalized[: limit - 1].rstrip()}…"


def centered_icon(icon: QIcon, size: int = 256) -> QIcon:
    """Crop empty padding from an icon's artwork and center it in the canvas.

    Fixes icons whose glyph is top-left aligned with transparent margins
    (e.g. ``assets/icon.ico``) so the artwork fills the frame everywhere it
    is used (window, tray, floating-bar capture button).
    """
    available = sorted((s.width() for s in icon.availableSizes()), reverse=True)
    source_size = available[0] if available else size
    source = icon.pixmap(source_size, source_size)
    if source.isNull():
        return icon
    image = source.toImage()
    min_x = min_y = max_x = max_y = None
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 0:
                if min_x is None or x < min_x:
                    min_x = x
                if max_x is None or x > max_x:
                    max_x = x
                if min_y is None or y < min_y:
                    min_y = y
                if max_y is None or y > max_y:
                    max_y = y
    if min_x is None:
        return icon
    glyph = source.copy(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
    scaled = glyph.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QPixmap(size, size)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    painter.end()
    return QIcon(canvas)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        ensure_app_dirs()
        self.history_store = HistoryStore()
        self.knowledge_base = KnowledgeBase(self.history_store)
        self.settings_service = SettingsService(self.history_store)
        self.settings = self.settings_service.load()
        self.ocr_service = OCRService()
        self.hotkey_manager: HotkeyManager | None = None
        self.tray: QSystemTrayIcon | None = None
        self._capturing: bool = False
        self._was_visible_before_capture: bool | None = None
        self._result_visible_before_capture: bool = False
        self.capture_worker: CaptureStreamWorker | None = None
        self.followup_worker: FollowupWorker | None = None
        self._history_records: list[CaptureRecord] = []
        self._terms_records: list[TermViewItem] = []
        self._terms_time_range = ""
        self._terms_domain = ""
        self._terms_domain_counts: list[tuple[str, int]] = []
        self._terms_page = 0
        self._terms_query = ""
        self._terms_total = 0
        self._terms_pages = 1
        self._last_payload: dict = {}
        self._active_history_filter: str = "全部"
        self.ui_font_size = 11

        self.result_window = ResultWindow(font_size=self.settings.result_font_size)
        self.result_window.request_followup.connect(self.ask_followup)
        self.result_window.request_retry.connect(self.retry_explain)
        self.result_window.open_history.connect(self.show_overview)
        self.result_window.font_size_changed.connect(self._save_result_font_size)
        self.result_window.request_capture.connect(self.start_capture)
        self.result_window.position_changed.connect(self._save_bar_position)
        self.result_window.set_capture_icon(self._app_icon())
        self.result_window.size_changed.connect(self._save_bar_size)
        self.result_window.size_reset.connect(self._clear_bar_size)
        if self.settings.bar_w is not None and self.settings.bar_h is not None:
            self.result_window.set_manual_size(self.settings.bar_w, self.settings.bar_h)

        self.setWindowTitle("AI Learning Copilot")
        self.resize(855, 550)
        self.setMinimumSize(710, 455)
        self._set_native_titlebar_color()
        self._apply_text_size()
        self._build_ui()
        ensure_label_backgrounds_transparent(self)
        self._build_tray()
        self._start_hotkey()
        self.overview_page.refresh()
        self.refresh_terms()
        self._refresh_sidebar_stats()
        self.refresh_ocr_status()
        self._show_float_bar()

    def start_capture(self) -> None:
        if self._capturing:
            return
        self._capturing = True
        self._was_visible_before_capture = self.isVisible()
        self._result_visible_before_capture = self.result_window.isVisible()
        self.status_label.setText("准备截图，右键或 Esc 可取消。")
        self.hide()
        self.result_window.hide()
        QTimer.singleShot(200, self._run_capture)

    def _restore_window_after_capture(self) -> None:
        if self._was_visible_before_capture is None:
            return
        if self._was_visible_before_capture:
            self.show_normal()
        self._was_visible_before_capture = None
        if (
            self.settings.show_float_bar
            and self._result_visible_before_capture
            and not self.result_window.isVisible()
        ):
            self._show_float_bar()
        self._result_visible_before_capture = False

    def _show_float_bar(self) -> None:
        if not self.settings.show_float_bar:
            return
        self.result_window.set_bar_mode(True)
        self.result_window.set_expanded(False)
        screen = QApplication.primaryScreen()
        if self.settings.bar_x is not None and self.settings.bar_y is not None:
            x, y = self.settings.bar_x, self.settings.bar_y
        else:
            if screen is None:
                x, y = self.result_window.x(), self.result_window.y()
            else:
                geo = screen.availableGeometry()
                x = geo.right() - self.result_window.width() - 24
                y = geo.top() + 24
        if screen is not None:
            geo = screen.availableGeometry()
            x = max(geo.left(), min(int(x), geo.right() - self.result_window.width() + 1))
            y = max(geo.top(), min(int(y), geo.bottom() - self.result_window.height() + 1))
        self.result_window.set_home_position(x, y)
        self.result_window.show()
        self.result_window.raise_()

    def _save_bar_position(self, x: int, y: int) -> None:
        if not self.settings.show_float_bar:
            return
        self.settings.bar_x = int(x)
        self.settings.bar_y = int(y)
        self.history_store.set_setting("bar_x", str(self.settings.bar_x))
        self.history_store.set_setting("bar_y", str(self.settings.bar_y))

    def _save_bar_size(self, width: int, height: int) -> None:
        if not self.settings.show_float_bar:
            return
        self.settings.bar_w = int(width)
        self.settings.bar_h = int(height)
        self.history_store.set_setting("bar_w", str(self.settings.bar_w))
        self.history_store.set_setting("bar_h", str(self.settings.bar_h))

    def _clear_bar_size(self) -> None:
        self.settings.bar_w = None
        self.settings.bar_h = None
        self.history_store.set_setting("bar_w", "")
        self.history_store.set_setting("bar_h", "")

    def _apply_float_bar_setting(self) -> None:
        if self.settings.show_float_bar:
            self._show_float_bar()
        else:
            self.result_window.set_bar_mode(False)
            self.result_window.hide()

    def _run_capture(self) -> None:
        class CaptureThread(QThread):
            completed = Signal(str)
            failed = Signal(str)

            def run(self_):
                try:
                    path = take_screenshots()
                except ScreenshotError as exc:
                    self_.failed.emit(str(exc))
                    return
                except Exception as exc:
                    self_.failed.emit(f"截图发生未知错误: {exc}")
                    return
                self_.completed.emit(path if path else "")

        self._capture_thread = CaptureThread()
        self._capture_thread.completed.connect(self._on_thread_capture_done)
        self._capture_thread.failed.connect(self._on_thread_capture_failed)
        self._capture_thread.finished.connect(self._capture_thread.deleteLater)
        self._capture_thread.start()

    def _on_thread_capture_done(self, image_path: str) -> None:
        if not image_path:
            self._capturing = False
            self._restore_window_after_capture()
            self.status_label.setText("已取消截图。")
            return
        self._on_screenshot_captured(image_path)

    def _on_thread_capture_failed(self, message: str) -> None:
        self._capturing = False
        self._restore_window_after_capture()
        self.status_label.setText(message)
        QMessageBox.warning(self, "截图失败", message)

    def ask_followup(self, source_text: str, question: str, mode: str = "custom") -> None:
        self.status_label.setText("正在追问...")
        conversation_id = self._last_payload.get("conversation_id")
        capture_id = self._last_payload.get("capture_id")
        self.followup_worker = FollowupWorker(
            source_text=source_text,
            question=question,
            settings=self.settings,
            history_store=self.history_store,
            conversation_id=int(conversation_id) if conversation_id else None,
            capture_id=int(capture_id) if capture_id else None,
            mode=mode,
        )
        self.result_window.begin_followup()
        self.followup_worker.status.connect(self.result_window.set_status)
        self.followup_worker.stream_chunk.connect(self.result_window.append_followup_chunk)
        self.followup_worker.completed.connect(self._on_followup_completed)
        self.followup_worker.finished.connect(self.followup_worker.deleteLater)
        self.followup_worker.start()

    def retry_explain(self, capture_id: int) -> None:
        record = self.history_store.get_capture(capture_id)
        if record is None or not record.source_text.strip():
            return
        self.status_label.setText("正在重新获取 AI 回答...")
        self.result_window.show_loading()
        self.result_window.set_status("正在重新获取 AI 回答...")
        self.capture_worker = CaptureStreamWorker(
            image_path=record.image_path or "",
            settings=self.settings,
            ocr_service=self.ocr_service,
            history_store=self.history_store,
            capture_id=capture_id,
            source_text=record.source_text,
        )
        self.capture_worker.status.connect(self.result_window.set_status)
        self.capture_worker.source_ready.connect(self.result_window.set_source_text)
        self.capture_worker.stream_chunk.connect(self.result_window.append_stream_chunk)
        self.capture_worker.stream_terms.connect(self.result_window.set_stream_terms)
        self.capture_worker.completed.connect(self._on_stream_capture_done)
        self.capture_worker.finished.connect(self.capture_worker.deleteLater)
        self.capture_worker.start()

    def refresh_terms(self) -> None:
        query = self.terms_search.text().strip() if hasattr(self, "terms_search") else ""
        if query != self._terms_query:
            self._terms_page = 0
        self._terms_query = query

        current_context_id, effective_domain, _ = self._current_terms_direction()

        page = self._query_term_page(query, current_context_id, effective_domain)
        self._terms_total = page.total
        self._terms_pages = max(1, (page.total + TERMS_PAGE_SIZE - 1) // TERMS_PAGE_SIZE)
        # 过滤结果变少导致当前页越界时，回退到最后一页（只多一次查询）
        if page.total and not page.items and self._terms_page >= self._terms_pages:
            self._terms_page = self._terms_pages - 1
            page = self._query_term_page(query, current_context_id, effective_domain)
        self._terms_records = page.items
        self._terms_domain_counts = page.domain_counts

        table = self.terms_table
        selected_id = None
        current_item = table.currentItem()
        if current_item is not None:
            selected_id = current_item.data(Qt.ItemDataRole.UserRole)

        previous_signals_blocked = table.blockSignals(True)
        table.setUpdatesEnabled(False)
        try:
            table.verticalHeader().setDefaultSectionSize(max(26, self.ui_font_size + 15))
            table.setRowCount(len(page.items))
            for row, view_item in enumerate(page.items):
                term = view_item.term
                values = [
                    term.term,
                    term.domain,
                    term.chinese_name or "-",
                    _term_keywords(term),
                    str(term.review_count),
                    "★" if term.favorite else "",
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    item.setData(Qt.ItemDataRole.UserRole, term.id)
                    table.setItem(row, column, item)

            target_row = next(
                (
                    row
                    for row, view_item in enumerate(page.items)
                    if view_item.term.id == selected_id
                ),
                0 if page.items else -1,
            )
            if target_row >= 0:
                table.selectRow(target_row)
            else:
                table.clearSelection()
        finally:
            table.blockSignals(previous_signals_blocked)
            table.setUpdatesEnabled(True)

        self._show_selected_term()
        self.terms_page_label.setText(f"第 {self._terms_page + 1}/{self._terms_pages} 页")
        self.terms_prev_button.setEnabled(self._terms_page > 0)
        self.terms_next_button.setEnabled(self._terms_page < self._terms_pages - 1)
        self._update_terms_hscroll_buttons()
        self._sync_terms_domain_control()
        if hasattr(self, "sidebar_stats_value"):
            fav_count = self.history_store.count_favorite_terms()
            self.sidebar_stats_value.setText(
                f"截图 {len(self._history_records)} · 术语 {self._terms_total} · 收藏 {fav_count}"
            )

    def _query_term_page(
        self,
        query: str,
        current_context_id: int | None,
        effective_domain: str,
    ):
        return self.knowledge_base.query_terms(
            TermQuery(
                view="all",
                sort="latest",
                query=query,
                domain=self._terms_domain,
                current_context_id=current_context_id,
                effective_domain=effective_domain,
                since_at=self._terms_since_at(),
                limit=TERMS_PAGE_SIZE,
                offset=self._terms_page * TERMS_PAGE_SIZE,
            )
        )

    def _current_terms_direction(self) -> tuple[int | None, str, str]:
        """(current_context_id, effective_domain, display_name)：当前学习方向事实。"""
        settings = self.settings_service.load()
        context_id = settings.current_context_id
        if context_id is not None:
            context = self.history_store.get_context(context_id)
            if context is not None and not context.builtin:
                domain = context.domain or "通用"
                scene = context.scene or "通用"
                display = (context.name or "").strip() or (
                    f"{domain} · {scene}" if scene != "通用" else domain
                )
                return context.id, domain, display
        domain, scene = self.settings_service.get_quick_context()
        display = f"{domain} · {scene}" if scene != "通用" else domain
        return None, domain or "通用", display

    def _set_terms_time_range(self, index: int) -> None:
        time_range = str(self.terms_time_combo.itemData(index) or "")
        if time_range == self._terms_time_range:
            return
        self._terms_time_range = time_range
        self._terms_page = 0
        self.refresh_terms()

    def _set_terms_domain(self, index: int) -> None:
        domain = str(self.terms_domain_combo.itemData(index) or "")
        if domain == self._terms_domain:
            return
        self._terms_domain = domain
        self._terms_page = 0
        self.refresh_terms()

    def _terms_since_at(self) -> str:
        now = datetime.now()
        if self._terms_time_range == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif self._terms_time_range == "7d":
            start = now - timedelta(days=7)
        elif self._terms_time_range == "30d":
            start = now - timedelta(days=30)
        else:
            return ""
        return start.isoformat(timespec="seconds")

    def _sync_terms_domain_control(self) -> None:
        if not hasattr(self, "terms_domain_combo"):
            return
        previous = self.terms_domain_combo.blockSignals(True)
        self.terms_domain_combo.clear()
        self.terms_domain_combo.addItem("全部领域", "")
        for domain, count in self._terms_domain_counts:
            self.terms_domain_combo.addItem(f"{domain} ({count})", domain)
        target = self.terms_domain_combo.findData(self._terms_domain)
        if target < 0:
            self._terms_domain = ""
            target = 0
        self.terms_domain_combo.setCurrentIndex(target)
        self.terms_domain_combo.blockSignals(previous)

    def _terms_goto_page(self, page: int) -> None:
        self._terms_page = max(0, min(page, self._terms_pages - 1))
        self.refresh_terms()

    def _terms_scroll_h(self, direction: int) -> None:
        bar = self.terms_table.horizontalScrollBar()
        bar.setValue(bar.value() + direction * max(100, bar.pageStep() // 2))
        self._update_terms_hscroll_buttons()

    def _update_terms_hscroll_buttons(self) -> None:
        bar = self.terms_table.horizontalScrollBar()
        self.terms_hleft_button.setEnabled(bar.value() > bar.minimum())
        self.terms_hright_button.setEnabled(bar.value() < bar.maximum())

    def _layout_terms_overlay_scrollbar(self) -> None:
        if not hasattr(self, "terms_overlay_scrollbar"):
            return
        rect = self.terms_table.geometry()
        self.terms_overlay_scrollbar.setGeometry(
            rect.x() + rect.width(), rect.top(), 3, rect.height()
        )

    def _set_terms_scrollbar_active(self, active: bool) -> None:
        bar = self.terms_overlay_scrollbar
        if bool(bar.property("active")) != active:
            bar.setProperty("active", active)
            bar.style().unpolish(bar)
            bar.style().polish(bar)

    def _hide_terms_scrollbar(self) -> None:
        if self.terms_overlay_scrollbar.underMouse():
            self._terms_scrollbar_timer.start()
            return
        self._set_terms_scrollbar_active(False)

    def eventFilter(self, obj, event) -> bool:
        if obj is getattr(self, "terms_overlay_scrollbar", None):
            if event.type() == QEvent.Type.Enter:
                self._terms_scrollbar_timer.stop()
                self._set_terms_scrollbar_active(True)
            elif event.type() == QEvent.Type.Leave:
                self._terms_scrollbar_timer.start()
        elif obj is getattr(self, "terms_table_viewport", None):
            if event.type() in (
                QEvent.Type.Wheel,
                QEvent.Type.MouseButtonPress,
            ):
                self._terms_scrollbar_timer.start()
                self._set_terms_scrollbar_active(True)
        elif obj is getattr(self, "terms_table_card", None) and event.type() == QEvent.Type.Resize:
            self._layout_terms_overlay_scrollbar()
        return super().eventFilter(obj, event)

    def save_settings(self) -> None:
        self.settings = AppSettings(
            api_key=self.api_key_input.text().strip(),
            base_url=self.base_url_input.text().strip(),
            model=self.model_input.text().strip(),
            hotkey=self.hotkey_input.text().strip(),
            save_screenshots=self.save_screenshots_checkbox.isChecked(),
            show_float_bar=self.show_float_bar_checkbox.isChecked(),
            context_block=self.settings.context_block,
            current_context_id=self.settings.current_context_id,
            bar_x=self.settings.bar_x,
            bar_y=self.settings.bar_y,
            bar_w=self.settings.bar_w,
            bar_h=self.settings.bar_h,
        )
        self.settings_service.save(self.settings)
        self._apply_float_bar_setting()
        self._start_hotkey()
        self.refresh_ocr_status()
        self.status_label.setText("设置已保存。")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.tray is not None and self.tray.isVisible():
            event.ignore()
            self.hide()
            self.tray.showMessage("AI Learning Copilot", "程序已最小化到托盘。")
            return
        self._shutdown()
        super().closeEvent(event)

    def _build_ui(self) -> None:
        shell = QWidget()
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(116)
        sidebar.setStyleSheet(f"QFrame#sidebar {{ background: {CARD}; }}")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 12, 8, 12)
        sidebar_layout.setSpacing(8)

        self.nav_buttons: list[QPushButton] = []
        self.pages = QStackedWidget()
        self.overview_page = OverviewPage(self.history_store, self.settings_service)
        self.learning_page = LearningPage(
            self.history_store, self.settings_service, self.knowledge_base
        )
        self.learning_page.context_changed.connect(self._on_context_changed)
        self.learning_page.capture_selected.connect(self._open_capture)
        self.workbench_page = WorkbenchPage(self.history_store, self.settings_service)
        self.workbench_page.context_changed.connect(self._on_context_changed)
        self._add_page(sidebar_layout, "获取", self.overview_page)
        self._add_page(sidebar_layout, "学习", self.learning_page)
        self._add_page(sidebar_layout, "术语本", self._build_terms_page())
        self._add_page(sidebar_layout, "工作台", self.workbench_page)
        self._add_page(sidebar_layout, "设置", self._build_settings_page())
        self.capture_sidebar_button = _primary_button("按下截图")
        self.capture_sidebar_button.setFixedHeight(32)
        self.capture_sidebar_button.setToolTip("开始截图并识别")
        self.capture_sidebar_button.clicked.connect(self.start_capture)
        sidebar_layout.addWidget(self.capture_sidebar_button)

        font_row = QHBoxLayout()
        font_row.setContentsMargins(4, 0, 4, 0)
        font_row.setSpacing(8)
        smaller_font = _mini_button("A-")
        larger_font = _mini_button("A+")
        smaller_font.setFixedSize(30, 30)
        larger_font.setFixedSize(30, 30)
        smaller_font.clicked.connect(lambda: self.adjust_text_size(-1))
        larger_font.clicked.connect(lambda: self.adjust_text_size(1))
        font_row.addWidget(smaller_font)
        font_row.addWidget(larger_font)
        sidebar_layout.addLayout(font_row)
        sidebar_layout.addStretch()

        stats_card = QFrame()
        stats_card.setObjectName("sidebarCard")
        stats_card.setStyleSheet(
            f"""
            QFrame#sidebarCard {{
                background: transparent;
                border: none;
                border-radius: 0;
            }}
            """
        )
        stats_grid = QGridLayout(stats_card)
        stats_grid.setContentsMargins(0, 4, 0, 0)
        stats_grid.setHorizontalSpacing(10)
        stats_grid.setVerticalSpacing(1)
        stats_title = QLabel("概览")
        stats_title.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: {FONT_BODY};")
        stats_grid.addWidget(stats_title, 0, 0, 1, 2)
        self.sidebar_stat_labels: dict[str, QLabel] = {}
        stat_items = [
            ("today_captures", "今日"),
            ("week_captures", "本周"),
            ("month_captures", "本月"),
            ("total_terms", "术语"),
            ("favorite_terms", "收藏"),
        ]
        for index, (key, label_text) in enumerate(stat_items):
            row = 1 + (index // 2) * 2
            column = index % 2
            value_label = QLabel("0")
            value_label.setStyleSheet(
                f"color: {TEXT}; font-size: {FONT_BODY};"
            )
            caption = QLabel(label_text)
            caption.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
            stats_grid.addWidget(value_label, row, column)
            stats_grid.addWidget(caption, row + 1, column)
            self.sidebar_stat_labels[key] = value_label
        sidebar_layout.addWidget(stats_card)

        main_area = QWidget()
        main_layout = QVBoxLayout(main_area)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.pages, 1)
        self.status_label = QLabel("就绪")
        self.status_label.setFixedHeight(24)
        self.status_label.setStyleSheet(
            f"background: {BORDER_LIGHT}; color:{MUTED}; padding:0 16px; font-size: {FONT_MICRO};"
        )
        main_layout.addWidget(self.status_label)

        shell_layout.addWidget(sidebar)
        shell_layout.addWidget(main_area, 1)
        self.setCentralWidget(shell)
        self._switch_page(0)

    def _apply_text_size(self) -> None:
        app = QApplication.instance()
        if app is not None:
            font = app.font()
            font.setFamilies(["Microsoft YaHei", "Segoe UI", "Arial"])
            font.setPixelSize(self.ui_font_size)
            app.setFont(font)
        padding = max(3, self.ui_font_size - 7)
        self.setStyleSheet(
            APP_STYLE
            + f"""
            QWidget {{
                font-size: {self.ui_font_size}px;
            }}
            QTextEdit, QTextBrowser, QLineEdit {{
                font-size: {self.ui_font_size}px;
                padding: {padding}px;
            }}
            QTableWidget::item {{
                padding: {padding}px;
            }}
            QHeaderView::section {{
                padding: {padding}px;
            }}
            QLabel#denseDetail {{
                font-size: {self.ui_font_size}px;
            }}
            """
        )

    def _sync_terms_search_height(self) -> None:
        if not hasattr(self, "terms_search"):
            return
        controls = [
            control
            for control in (
                getattr(self, "terms_time_combo", None),
                getattr(self, "terms_domain_combo", None),
            )
            if control is not None
        ]
        if not controls:
            return
        height = max(control.sizeHint().height() for control in controls)
        self.terms_search.setFixedHeight(height)
        self.terms_time_combo.setFixedHeight(height)
        self.terms_domain_combo.setFixedHeight(height)

    def adjust_text_size(self, delta: int) -> None:
        self.ui_font_size = max(10, min(17, self.ui_font_size + delta))
        self._apply_text_size()
        self._sync_terms_search_height()
        self.result_window.adjust_text_size(delta)
        if hasattr(self, "terms_table"):
            self.refresh_terms()
        self.status_label.setText("文字大小已调整。")

    def _save_result_font_size(self, size: int) -> None:
        self.settings.result_font_size = size
        self.settings_service.save(self.settings)

    def _add_page(self, sidebar_layout: QVBoxLayout, title: str, page: QWidget) -> None:
        index = self.pages.addWidget(page)
        button = _nav_button(title)
        button.clicked.connect(lambda checked=False, i=index: self._switch_page(i))
        self.nav_buttons.append(button)
        sidebar_layout.addWidget(button)

    def _switch_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)
        if index == 0:
            self.overview_page.refresh()
        elif index == 1:
            self.learning_page.refresh()
        elif index == 2:
            self.refresh_terms()
        elif index == 4:
            self.refresh_ocr_status()

    def _build_terms_page(self) -> QWidget:
        page = _page()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 10, 20, 12)
        layout.setSpacing(8)

        content = QHBoxLayout()
        content.setSpacing(16)

        table_card = _card()
        table_card.setObjectName("termsTableCard")
        table_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        table_card.setStyleSheet(
            f"""
            QFrame#termsTableCard {{
                background: {CARD};
                border: 1px solid {BORDER};
                border-radius: {RADIUS_LG};
            }}
            """
        )
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(12, 8, 12, 10)
        table_layout.setSpacing(4)
        table_header_row = QHBoxLayout()
        table_header_row.setSpacing(8)
        table_header_row.addWidget(_field_title("术语列表"))
        table_header_row.addStretch(1)
        table_layout.addLayout(table_header_row)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.terms_search = QLineEdit()
        self.terms_search.setPlaceholderText("搜索术语")
        self.terms_search.setMinimumWidth(84)
        self.terms_search.setMaximumWidth(150)
        self.terms_search.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.terms_search.setStyleSheet(
            f"padding: 0 10px; border: 1px solid {BORDER}; "
            f"border-radius: {RADIUS_MD}; background: {CARD};"
        )
        self.terms_search.returnPressed.connect(self.refresh_terms)
        filter_row.addWidget(self.terms_search, 1)
        self.terms_time_combo = ChevronComboBox()
        self.terms_time_combo.addItem("全部时间", "")
        self.terms_time_combo.addItem("今天", "today")
        self.terms_time_combo.addItem("近 7 天", "7d")
        self.terms_time_combo.addItem("近 30 天", "30d")
        self.terms_time_combo.setFixedWidth(92)
        self.terms_time_combo.setToolTip("按最后一次真实学习时间筛选，列表始终按最新积累排序")
        self.terms_time_combo.currentIndexChanged.connect(self._set_terms_time_range)
        filter_row.addWidget(self.terms_time_combo)
        self.terms_domain_combo = ChevronComboBox()
        self.terms_domain_combo.addItem("全部领域", "")
        self.terms_domain_combo.setMinimumWidth(104)
        self.terms_domain_combo.setMaximumWidth(160)
        self.terms_domain_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.terms_domain_combo.setToolTip("按术语自身的领域分类筛选")
        self.terms_domain_combo.currentIndexChanged.connect(self._set_terms_domain)
        filter_row.addWidget(self.terms_domain_combo, 1)
        self._sync_terms_search_height()
        table_layout.addLayout(filter_row)

        self.terms_table = QTableWidget(0, 6)
        self.terms_table.setObjectName("termsTable")
        self.terms_table.setFrameShape(QFrame.Shape.NoFrame)
        self.terms_table.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.terms_table.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.terms_table.viewport().setStyleSheet("background: transparent; border: none;")
        self.terms_table.setStyleSheet(
            f"""
            QTableWidget#termsTable {{
                background: {CARD};
                border: none;
                gridline-color: transparent;
                outline: 0;
            }}
            QTableWidget#termsTable::item {{
                background: {CARD};
                padding: 6px 7px;
                border-bottom: 1px solid {BORDER_LIGHT};
            }}
            QTableWidget#termsTable::item:selected {{
                background: {PRIMARY_SOFT};
                color: {TEXT};
            }}
            QTableWidget#termsTable QHeaderView {{
                background: {CARD};
            }}
            QTableWidget#termsTable QHeaderView::section {{
                background: {CARD};
                border: none;
                border-bottom: 1px solid {BORDER_LIGHT};
                padding: 4px 7px;
                color: {MUTED};
            }}
            """
        )
        self.terms_table.setHorizontalHeaderLabels(["术语", "领域", "中文名", "关键词", "次数", "收藏"])
        self.terms_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.terms_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.terms_table.verticalHeader().setVisible(False)
        self.terms_table.verticalHeader().setDefaultSectionSize(max(26, self.ui_font_size + 15))
        self.terms_table.setShowGrid(False)
        self.terms_table.setWordWrap(False)
        self.terms_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.terms_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.terms_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.terms_table.itemSelectionChanged.connect(self._on_term_row_selected)
        table_header = self.terms_table.horizontalHeader()
        table_header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        table_header.resizeSection(0, 120)
        table_header.resizeSection(1, 60)
        table_header.resizeSection(2, 120)
        table_header.resizeSection(4, 48)
        table_header.resizeSection(5, 48)
        self.terms_table_card = table_card
        self.terms_scrollbar = self.terms_table.verticalScrollBar()
        self.terms_table_viewport = self.terms_table.viewport()
        self.terms_overlay_scrollbar = QScrollBar(Qt.Orientation.Vertical, table_card)
        self.terms_overlay_scrollbar.setObjectName("termsOverlayScrollbar")
        self.terms_overlay_scrollbar.setStyleSheet(
            f"""
            QScrollBar#termsOverlayScrollbar {{
                border: none;
                background: transparent;
                margin: 0;
            }}
            QScrollBar#termsOverlayScrollbar::handle:vertical {{
                background: transparent;
                border-radius: 1px;
                min-height: 24px;
            }}
            QScrollBar#termsOverlayScrollbar::handle:vertical[active="true"] {{
                background: #afc3f4;
            }}
            QScrollBar#termsOverlayScrollbar::add-line:vertical,
            QScrollBar#termsOverlayScrollbar::sub-line:vertical {{
                width: 0;
                height: 0;
                border: none;
            }}
            """
        )
        self.terms_overlay_scrollbar.setProperty("active", False)
        self.terms_overlay_scrollbar.style().unpolish(self.terms_overlay_scrollbar)
        self.terms_overlay_scrollbar.style().polish(self.terms_overlay_scrollbar)
        self.terms_overlay_scrollbar.installEventFilter(self)
        self.terms_overlay_scrollbar.show()
        self.terms_table_viewport.installEventFilter(self)
        table_card.installEventFilter(self)
        self.terms_scrollbar.valueChanged.connect(self.terms_overlay_scrollbar.setValue)
        self.terms_overlay_scrollbar.valueChanged.connect(self.terms_scrollbar.setValue)
        self.terms_scrollbar.rangeChanged.connect(
            lambda _mn, _mx: self.terms_overlay_scrollbar.setRange(_mn, _mx)
        )
        self._terms_scrollbar_timer = QTimer(self)
        self._terms_scrollbar_timer.setSingleShot(True)
        self._terms_scrollbar_timer.setInterval(1800)
        self._terms_scrollbar_timer.timeout.connect(self._hide_terms_scrollbar)
        QTimer.singleShot(0, self._layout_terms_overlay_scrollbar)

        table_layout.addWidget(self.terms_table, 1)
        table_bottom = QHBoxLayout()
        table_bottom.setSpacing(6)
        self.terms_hleft_button = _page_nav_button("<")
        self.terms_hleft_button.clicked.connect(lambda: self._terms_scroll_h(-1))
        table_bottom.addWidget(self.terms_hleft_button)
        self.terms_hright_button = _page_nav_button(">")
        self.terms_hright_button.clicked.connect(lambda: self._terms_scroll_h(1))
        table_bottom.addWidget(self.terms_hright_button)
        table_bottom.addStretch(1)
        self.terms_prev_button = _ghost_button("上一页")
        self.terms_prev_button.clicked.connect(lambda: self._terms_goto_page(self._terms_page - 1))
        table_bottom.addWidget(self.terms_prev_button)
        self.terms_page_label = QLabel("第 1/1 页")
        self.terms_page_label.setStyleSheet(f"color:{MUTED};")
        table_bottom.addWidget(self.terms_page_label)
        self.terms_next_button = _ghost_button("下一页")
        self.terms_next_button.clicked.connect(lambda: self._terms_goto_page(self._terms_page + 1))
        table_bottom.addWidget(self.terms_next_button)
        self.terms_table.horizontalScrollBar().rangeChanged.connect(
            lambda _mn, _mx: self._update_terms_hscroll_buttons()
        )
        table_layout.addLayout(table_bottom)

        detail_panel = QWidget()
        detail_panel.setObjectName("termDetailPanel")
        detail_panel.setStyleSheet(
            "QWidget#termDetailPanel { background: transparent; border: none; }"
        )
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(4, 0, 0, 0)
        detail_layout.setSpacing(10)

        term_header = QHBoxLayout()
        term_header.setContentsMargins(0, 0, 0, 0)
        term_header.setSpacing(8)
        self.term_name_label = QLabel("选择术语")
        self.term_name_label.setStyleSheet(f"font-size:{FONT_TITLE}; color:{TEXT};")
        self.term_name_label.setWordWrap(True)
        self.term_domain_label = QLabel("-")
        self.term_domain_label.setObjectName("termDomainBadge")
        self.term_domain_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom
        )
        self.term_domain_label.setStyleSheet(
            f"QLabel#termDomainBadge {{ color:{PRIMARY_DARK}; background:{PRIMARY_SOFT}; "
            f"border:1px solid #dbe7ff; border-radius:{RADIUS_PILL}; padding:2px 8px; "
            f"font-size:{FONT_MICRO}; }}"
        )
        term_header.addWidget(self.term_name_label, 1, Qt.AlignmentFlag.AlignBottom)
        term_header.addWidget(self.term_domain_label, 0, Qt.AlignmentFlag.AlignBottom)
        detail_layout.addLayout(term_header)

        # P1-C：排序理由（由 KnowledgeBase 生成，UI 只展示，不重算）
        self.term_reasons_label = QLabel("")
        self.term_reasons_label.setWordWrap(True)
        self.term_reasons_label.setStyleSheet(
            f"color:{PRIMARY_DARK}; background:{PRIMARY_SOFT}; border-radius:{RADIUS_SM}; "
            "padding:4px 8px;"
        )
        self.term_reasons_label.setVisible(False)
        detail_layout.addWidget(self.term_reasons_label)
        self.term_chinese_label = QLabel("中文名：-")
        self.term_count_label = QLabel("出现次数：-")
        for label in (
            self.term_chinese_label,
            self.term_count_label,
        ):
            label.setWordWrap(True)
            label.setObjectName("denseDetail")
            label.setStyleSheet("line-height:1.4;")
        detail_layout.addWidget(_field_title("中文名"))
        detail_layout.addWidget(self.term_chinese_label)

        # design_system 6.3：解释 / 例子互斥阅读用 Tab，节省垂直空间
        self.term_detail_tabs = QTabWidget()
        self.term_detail_tabs.setDocumentMode(True)
        self.term_detail_tabs.setStyleSheet(
            f"""
            QTabWidget::pane {{ border: none; }}
            QTabBar::tab {{ padding: 5px 12px; color: {MUTED}; background: transparent; border: none; }}
            QTabBar::tab:selected {{ color: {PRIMARY}; border-bottom: 2px solid {PRIMARY}; }}
            """
        )
        self.term_explanation_label = _readonly_box("完整解释")
        self.term_example_label = _readonly_box("当前例子")
        self.term_detail_tabs.addTab(self.term_explanation_label, "完整解释")
        self.term_detail_tabs.addTab(self.term_example_label, "当前例子")
        self.term_detail_tabs.setMinimumHeight(96)
        detail_layout.addWidget(self.term_detail_tabs, 1)

        detail_layout.addWidget(_field_title("出现次数"))
        detail_layout.addWidget(self.term_count_label)

        detail_layout.addWidget(_field_title("出处"))
        self.term_sources_list = QListWidget()
        self.term_sources_list.setMaximumHeight(84)
        self.term_sources_list.setFrameShape(QFrame.Shape.NoFrame)
        self.term_sources_list.setToolTip("点击可跳转到该术语出现过的学习记录")
        self.term_sources_list.setStyleSheet(
            f"""
            QListWidget {{ background: transparent; border: none; outline: 0; }}
            QListWidget::item {{ padding: 4px 2px; color: {TEXT_SECONDARY}; }}
            QListWidget::item:selected {{ background: {PRIMARY_SOFT}; color: {TEXT}; border-radius: 4px; }}
            """
        )
        self.term_sources_list.itemClicked.connect(self._on_term_source_clicked)
        detail_layout.addWidget(self.term_sources_list)

        term_buttons = QHBoxLayout()
        self.favorite_button = _ghost_button("收藏")
        self.favorite_button.clicked.connect(self._toggle_favorite)
        edit_button = _ghost_button("编辑")
        edit_button.clicked.connect(self._edit_selected_term)
        term_buttons.addWidget(self.favorite_button)
        term_buttons.addWidget(edit_button)
        delete_button = _danger_button("删除")
        delete_button.clicked.connect(self._delete_selected_term)
        term_buttons.addWidget(delete_button)
        term_buttons.addStretch(1)
        detail_layout.addLayout(term_buttons)

        content.addWidget(table_card, 7)
        table_card.setMinimumWidth(330)
        content.addWidget(detail_panel, 4)
        detail_panel.setMinimumWidth(180)
        self.terms_detail_panel = detail_panel
        layout.addLayout(content, 1)
        return page

    def _confirm_data_operation(self, title: str, body: str, confirm_text: str) -> bool:
        """数据管理模块的统一风险确认框：写明操作内容与风险，默认焦点在取消。"""
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(body)
        confirm_button = box.addButton(confirm_text, QMessageBox.ButtonRole.AcceptRole)
        cancel_button = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_button)
        box.exec()
        return box.clickedButton() is confirm_button

    def _backup_database(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "备份数据库", f"app-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db", "SQLite (*.db)"
        )
        if not path:
            return
        import shutil
        try:
            self.history_store.vacuum()
            shutil.copy2(str(DB_PATH), path)
            QMessageBox.information(self, "备份完成", f"数据库已备份到：\n{path}")
        except Exception as exc:
            QMessageBox.warning(self, "备份失败", str(exc))

    def _restore_database(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "恢复数据库", "", "SQLite (*.db *.sqlite *.sqlite3)")
        if not path:
            return
        body = (
            "操作内容：用所选备份文件覆盖当前数据库，当前的学习记录、会话、术语与学习方向"
            "将被整体替换为备份中的内容。\n\n"
            "风险：\n"
            "· 现有数据会被覆盖，操作不可撤销；\n"
            "· 备份文件较旧时，其后新增的记录会丢失；\n"
            "· API Key 保存在系统凭据管理器中，不受此操作影响；\n"
            "· 已保存的截图文件不会被删除。\n\n"
            "建议：恢复前先执行「备份数据库」留存当前数据。"
        )
        if not self._confirm_data_operation("确认恢复数据库", body, "确认恢复"):
            return
        import shutil
        try:
            shutil.copy2(path, str(DB_PATH))
            QMessageBox.information(self, "恢复完成", "数据库已恢复。请重启应用以加载新数据。")
        except Exception as exc:
            QMessageBox.warning(self, "恢复失败", str(exc))

    def _cleanup_old_records(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        days, ok = QInputDialog.getItem(
            self, "清理旧记录", "删除多少天前的记录？",
            ["30 天", "60 天", "90 天", "180 天", "365 天"], 2, False,
        )
        if not ok:
            return
        n = int(days.split()[0])
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=n)).isoformat()
        body = (
            f"操作内容：删除 {days}（{cutoff[:10]}）之前创建的全部截图记录，"
            "删除后从历史列表中消失。\n\n"
            "风险：\n"
            "· 删除后不可恢复，请确认不再需要这些记录；\n"
            "· 关联的会话、消息与术语积累会一并不可见；\n"
            "· 已保存的截图文件不会自动删除（如需清除请手动处理）。\n\n"
            "建议：可先「导出 Markdown」或「备份数据库」留存记录。"
        )
        if not self._confirm_data_operation("确认清理旧记录", body, "确认删除"):
            return
        count = self.history_store.delete_captures_before(cutoff)
        QMessageBox.information(self, "清理完成", f"已删除 {count} 条记录。")
        self.overview_page.refresh()
        self._refresh_sidebar_stats()

    def _export_anki(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 Anki 词表", "anki-vocabulary.csv", "CSV (*.csv)"
        )
        if not path:
            return
        terms = self.knowledge_base.list_terms(TermQuery(view="all", limit=1000))
        import csv
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["term", "chinese_name", "explanation", "examples", "review_count", "favorite"])
                for term in terms:
                    writer.writerow([
                        term.term,
                        term.chinese_name,
                        term.beginner_explanation,
                        "；".join(term.examples),
                        term.review_count,
                        "★" if term.favorite else "",
                    ])
            QMessageBox.information(self, "导出完成", f"已导出 {len(terms)} 个术语到：\n{path}\n\n可直接导入 Anki。")
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))

    def _vacuum_database(self) -> None:
        body = (
            "操作内容：重建数据库文件（VACUUM），压缩体积、整理存储碎片。\n\n"
            "风险：\n"
            "· 记录内容保持不变，通常安全；\n"
            "· 执行期间数据库暂时被占用，请勿同时进行截图或其他数据操作；\n"
            "· 操作完成后原有数据仍然完整可用。"
        )
        if not self._confirm_data_operation("确认优化数据库", body, "开始优化"):
            return
        try:
            self.history_store.vacuum()
            QMessageBox.information(self, "优化完成", "数据库已优化。")
        except Exception as exc:
            QMessageBox.warning(self, "优化失败", str(exc))

    def _show_database_info(self) -> None:
        import os
        stats = self.history_store.get_statistics()
        db_size = os.path.getsize(str(DB_PATH)) if os.path.exists(str(DB_PATH)) else 0
        if db_size > 1024 * 1024:
            size_str = f"{db_size / (1024*1024):.1f} MB"
        elif db_size > 1024:
            size_str = f"{db_size / 1024:.1f} KB"
        else:
            size_str = f"{db_size} B"
        info = (
            f"数据库路径: {DB_PATH}\n"
            f"文件大小: {size_str}\n\n"
            f"总记录数: {stats['total_captures']}\n"
            f"术语总数: {stats['total_terms']}\n"
            f"收藏术语: {stats['favorite_terms']}\n"
            f"AI 交互: {stats['total_conversations']}\n"
            f"今日截图: {stats['today_captures']}\n"
            f"本周截图: {stats['week_captures']}\n"
            f"本月截图: {stats['month_captures']}\n"
            f"平均解释长度: {stats['avg_explanation_length']} 字\n"
            f"最后记录: {stats['last_capture_at'] or '无'}"
        )
        QMessageBox.information(self, "数据库信息", info)

    def _build_settings_page(self) -> QWidget:
        page = _page()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        settings_nav = QFrame()
        settings_nav.setFixedWidth(232)
        settings_nav.setStyleSheet(f"background: {BG};")
        nav_layout = QVBoxLayout(settings_nav)
        nav_layout.setContentsMargins(16, 28, 16, 16)
        nav_layout.setSpacing(4)

        self.settings_pages = QStackedWidget()
        self.settings_nav_buttons: list[QPushButton] = []
        nav_labels = ["AI 配置", "OCR 配置", "快捷键", "保存与导出", "数据管理", "关于"]
        for idx, label in enumerate(nav_labels):
            btn = _nav_button(label)
            btn.setChecked(idx == 0)
            btn.clicked.connect(lambda checked=False, i=idx: self._switch_settings_page(i))
            self.settings_nav_buttons.append(btn)
            nav_layout.addWidget(btn)
        nav_layout.addStretch()
        nav_layout.addWidget(QLabel(VERSION_LABEL))

        self._build_settings_ai_page()
        self._build_settings_ocr_page()
        self._build_settings_hotkey_page()
        self._build_settings_save_page()
        self._build_settings_data_page()
        self._build_settings_about_page()

        outer.addWidget(settings_nav)
        outer.addWidget(self.settings_pages, 1)
        return page

    def _switch_settings_page(self, index: int) -> None:
        self.settings_pages.setCurrentIndex(index)
        for i, btn in enumerate(self.settings_nav_buttons):
            btn.setChecked(i == index)

    def _settings_scroll(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        scroll.setWidget(content)
        return scroll

    def _build_settings_ai_page(self) -> None:
        self._settings_ai_content = QWidget()
        layout = QVBoxLayout(self._settings_ai_content)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        layout.addWidget(_page_title("AI 配置"))

        self.api_key_input = QLineEdit(self.settings.api_key)
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.base_url_input = QLineEdit(self.settings.base_url)
        self.model_input = QLineEdit(self.settings.model)

        ai_card = _settings_card(
            "API 设置",
            [
                ("API Key", self.api_key_input),
                ("Base URL", self.base_url_input),
                ("模型名称", self.model_input),
            ],
            "兼容 OpenAI 接口，可配置 DeepSeek、Kimi、本地 Ollama 等。",
        )
        layout.addWidget(ai_card)

        hint_title = QLabel("常用配置参考")
        hint_title.setStyleSheet(f"color:{TEXT_SECONDARY};")
        layout.addWidget(hint_title)
        hints = [
            "DeepSeek: Base URL=https://api.deepseek.com/v1, model=deepseek-v4-flash",
            "DeepSeek: model=deepseek-v4-pro（更强推理）",
            "Kimi: Base URL=https://api.moonshot.cn/v1, model=kimi-k3",
            "OpenAI: Base URL=https://api.openai.com/v1, model=gpt-4.1-mini",
            "本地 Ollama: Base URL=http://localhost:11434/v1, model=qwen3（API Key 任意填）",
            "本地 LM Studio: Base URL=http://localhost:1234/v1, model=已加载的模型名",
        ]
        for hint in hints:
            lbl = QLabel(f"• {hint}")
            lbl.setStyleSheet(f"color:{MUTED};")
            lbl.setWordWrap(True)
            layout.addWidget(lbl)

        layout.addSpacing(8)
        local_title = QLabel("接入本地模型（Ollama 示例）")
        local_title.setStyleSheet(f"color:{TEXT_SECONDARY};")
        layout.addWidget(local_title)
        local_steps = [
            "1. 安装 Ollama：https://ollama.com/download",
            "2. 拉取模型（终端执行）：ollama pull qwen3",
            "3. 本软件设置页填写：API Key 任意（如 ollama），"
            "Base URL=http://localhost:11434/v1，模型名称=qwen3（或 ollama list 中任意已拉取的模型名）",
            "4. 点击“测试连接”，通过后即可使用，无需联网、无调用费用",
            "5. 其他本地工具（LM Studio 等）：Base URL=http://localhost:1234/v1，模型名填软件里已加载的模型",
        ]
        for step in local_steps:
            lbl = QLabel(step)
            lbl.setStyleSheet(f"color:{MUTED};")
            lbl.setWordWrap(True)
            layout.addWidget(lbl)
        layout.addStretch()

        self._settings_ai_footer = QHBoxLayout()
        self._settings_ai_footer.addStretch()
        test_btn = _ghost_button("测试连接")
        test_btn.clicked.connect(self._test_ai_connection)
        save_btn = _primary_button("保存设置")
        save_btn.clicked.connect(self.save_settings)
        self._settings_ai_footer.addWidget(test_btn)
        self._settings_ai_footer.addWidget(save_btn)
        layout.addLayout(self._settings_ai_footer)

        self.settings_pages.addWidget(self._settings_scroll(self._settings_ai_content))

    def _build_settings_ocr_page(self) -> None:
        self._settings_ocr_content = QWidget()
        layout = QVBoxLayout(self._settings_ocr_content)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        layout.addWidget(_page_title("OCR 配置"))

        self.ocr_status_label = QLabel("")
        self.ocr_status_label.setWordWrap(True)
        self.ocr_status_label.setStyleSheet(f"color:{MUTED};")
        ocr_card = _settings_card(
            "RapidOCR 设置",
            [
                ("OCR 引擎", QLabel("RapidOCR (ONNX Runtime)")),
                ("语言", QLabel("简体中文 + English（内置模型）")),
                ("检测状态", self.ocr_status_label),
            ],
        )
        layout.addWidget(ocr_card)

        lang_title = QLabel("语言说明")
        lang_title.setStyleSheet(f"color:{TEXT_SECONDARY};")
        layout.addWidget(lang_title)
        lang_info = [
            "RapidOCR 使用内置中英文识别模型",
            "无需安装 Tesseract 或额外语言包",
            "模型文件随 Python 依赖一起安装",
        ]
        for info in lang_info:
            lbl = QLabel(f"• {info}")
            lbl.setStyleSheet(f"color:{MUTED};")
            layout.addWidget(lbl)
        layout.addStretch()

        footer = QHBoxLayout()
        footer.addStretch()
        detect_btn = _ghost_button("重新检测")
        detect_btn.clicked.connect(self.refresh_ocr_status)
        footer.addWidget(detect_btn)
        layout.addLayout(footer)

        self.settings_pages.addWidget(self._settings_scroll(self._settings_ocr_content))

    def _build_settings_hotkey_page(self) -> None:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        layout.addWidget(_page_title("快捷键"))

        self.hotkey_input = QLineEdit(self.settings.hotkey)
        hotkey_card = _settings_card(
            "全局快捷键",
            [
                ("截图翻译", self.hotkey_input),
            ],
            "例如：<ctrl>+<alt>+t（pynput 格式，特殊键用尖括号）。修改后自动生效。",
        )
        layout.addWidget(hotkey_card)

        self.show_float_bar_checkbox = QCheckBox("")
        self.show_float_bar_checkbox.setChecked(self.settings.show_float_bar)
        float_bar_card = _settings_card(
            "浮动截图条",
            [
                ("显示浮动条", self.show_float_bar_checkbox),
            ],
            "开启后屏幕角落常驻一条小工具条（截图 / 展开收起 / 拖动）。关闭后恢复为截图后光标处弹窗。",
        )
        layout.addWidget(float_bar_card)

        layout.addStretch()

        footer = QHBoxLayout()
        footer.addStretch()
        save_btn = _primary_button("保存快捷键")
        save_btn.clicked.connect(self.save_settings)
        footer.addWidget(save_btn)
        layout.addLayout(footer)

        self.settings_pages.addWidget(self._settings_scroll(content))

    def _build_settings_save_page(self) -> None:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        layout.addWidget(_page_title("保存与导出"))

        self.save_screenshots_checkbox = QCheckBox("")
        self.save_screenshots_checkbox.setChecked(self.settings.save_screenshots)
        save_card = _settings_card(
            "存储选项",
            [
                ("保存截图文件", self.save_screenshots_checkbox),
                ("自动保存会话", QLabel("开启（默认）")),
                ("数据存储位置", QLabel(str(DATA_DIR))),
            ],
            "截图文件默认不保存（处理完成后自动删除）；开启后截图会保留在本地。",
        )
        layout.addWidget(save_card)

        export_title = QLabel("支持的导出格式")
        export_title.setStyleSheet(f"color:{TEXT_SECONDARY};")
        layout.addWidget(export_title)
        exports = [
            ("Markdown (.md)", "历史记录完整导出，含原文/翻译/解释"),
            ("Anki CSV (.csv)", "术语本导出，可直接导入 Anki 记忆卡"),
        ]
        for fmt, desc in exports:
            row = QHBoxLayout()
            fmt_lbl = QLabel(fmt)
            fmt_lbl.setStyleSheet(" min-width:160px;")
            desc_lbl = QLabel(desc)
            desc_lbl.setStyleSheet(f"color:{MUTED};")
            row.addWidget(fmt_lbl)
            row.addWidget(desc_lbl, 1)
            layout.addLayout(row)
        layout.addStretch()

        footer = QHBoxLayout()
        footer.addStretch()
        save_btn = _primary_button("保存设置")
        save_btn.clicked.connect(self.save_settings)
        footer.addWidget(save_btn)
        layout.addLayout(footer)

        self.settings_pages.addWidget(self._settings_scroll(content))

    def _apply_current_context(self) -> None:
        """Single entry point after any context change: re-resolve settings and refresh UI."""
        self.settings = self.settings_service.load()
        self.workbench_page.refresh_directions()
        self.overview_page.refresh_direction_label()
        self.learning_page.refresh()
        self.refresh_terms()
        self.status_label.setText(f"当前学习方向：{self._current_context_name()}")

    def _current_context_name(self) -> str:
        context_id = self.settings.current_context_id
        if context_id is None:
            domain, scene = self.settings_service.get_quick_context()
            return f"{domain} · {scene}" if scene != "通用" else domain
        context = self.history_store.get_context(context_id)
        return context.name if context is not None else "通用"

    def _build_settings_data_page(self) -> None:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        layout.addWidget(_page_title("数据管理"))

        data_card = _card()
        data_layout = QVBoxLayout(data_card)
        data_layout.setContentsMargins(24, 16, 24, 16)
        data_layout.setSpacing(12)
        actions = [
            ("备份数据库", "把当前数据库复制为备份文件。", self._backup_database),
            ("恢复数据库", "用备份文件覆盖当前数据库（会清空现有数据）。", self._restore_database),
            ("清理旧记录", "删除指定天数之前的全部记录，不可恢复。", self._cleanup_old_records),
            ("导出 Markdown", "把学习记录导出为 Markdown 文件。", self.export_markdown),
            ("导出 Anki 词表", "把术语本导出为 Anki 兼容 CSV。", self._export_anki),
            ("优化数据库", "VACUUM 压缩数据库体积。", self._vacuum_database),
            ("数据库信息", "查看记录数、术语数、数据库大小等。", self._show_database_info),
        ]
        for label, desc, handler in actions:
            row = QHBoxLayout()
            row.setSpacing(12)
            button = _ghost_button(label)
            button.clicked.connect(handler)
            row.addWidget(button)
            desc_label = QLabel(desc)
            desc_label.setStyleSheet(f"color:{MUTED}; font-size:{FONT_MICRO};")
            desc_label.setWordWrap(True)
            row.addWidget(desc_label, 1)
            data_layout.addLayout(row)
        layout.addWidget(data_card)
        layout.addStretch()

        self.settings_pages.addWidget(self._settings_scroll(content))

    def _build_settings_about_page(self) -> None:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        layout.addWidget(_page_title("关于"))

        about_card = _card()
        about_layout = QVBoxLayout(about_card)
        about_layout.setContentsMargins(24, 24, 24, 24)
        about_layout.setSpacing(8)

        logo = QLabel("✧")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(f"font-size:{FONT_HEADING}; color:{PRIMARY};")
        about_layout.addWidget(logo)

        name_lbl = QLabel("AI Learning Copilot")
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet(f"font-size:{FONT_HEADING}; ")
        about_layout.addWidget(name_lbl)

        ver_lbl = QLabel(f"版本 {VERSION_LABEL}")
        ver_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver_lbl.setStyleSheet(f"color:{MUTED}; font-size:{FONT_MICRO};")
        about_layout.addWidget(ver_lbl)

        desc_lbl = QLabel(
            "一个轻量级桌面学习助手，帮助你从英文软件界面、报错、文档中快速学习。"
            "通过截图 OCR + AI 翻译解释，自动沉淀为个人知识库。"
        )
        desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(f"color:{MUTED}; line-height:1.5; padding: 8px 0;")
        about_layout.addWidget(desc_lbl)
        tech_card = _card()
        tech_layout = QVBoxLayout(tech_card)
        tech_layout.setContentsMargins(16, 16, 16, 16)
        tech_title = QLabel("技术栈")
        tech_title.setStyleSheet(f"color:{TEXT_SECONDARY};")
        tech_layout.addWidget(tech_title)
        techs = [
            "Python 3.11 + PySide6 (Qt for Python)",
            "RapidOCR (ONNX Runtime)",
            "OpenAI 兼容 API (Chat Completions)",
            "SQLite + FTS5 全文搜索",
            "mss 原生分辨率截图",
            "pynput 全局热键",
        ]
        for t in techs:
            lbl = QLabel(f"• {t}")
            lbl.setStyleSheet(f"color:{MUTED};")
            tech_layout.addWidget(lbl)
        about_layout.addWidget(tech_card)
        layout.addWidget(about_card)
        layout.addStretch()

        self.settings_pages.addWidget(self._settings_scroll(content))

    def _test_ai_connection(self) -> None:
        from app.services.ai_client import AIClient, AIClientError
        test_settings = AppSettings(
            api_key=self.api_key_input.text().strip(),
            base_url=self.base_url_input.text().strip(),
            model=self.model_input.text().strip(),
        )
        try:
            client = AIClient(test_settings)
            client.explain_text("Hello world")
            QMessageBox.information(self, "连接成功", "AI 接口连接正常！")
        except AIClientError as exc:
            QMessageBox.warning(self, "连接失败", str(exc))
        except Exception as exc:
            QMessageBox.warning(self, "连接失败", f"未知错误: {exc}")

    def refresh_ocr_status(self) -> None:
        if not hasattr(self, "ocr_status_label"):
            return
        status = self.ocr_service.check_status()
        if status.ok:
            self.ocr_status_label.setStyleSheet(f"color: {SUCCESS}; ")
        else:
            self.ocr_status_label.setStyleSheet(f"color: {DANGER}; ")
        details = [
            status.message,
            f"来源：{status.source or '无'}",
        ]
        if status.available_languages:
            details.append("支持语言：" + "、".join(status.available_languages))
        self.ocr_status_label.setText("\n".join(details))

    def _app_icon(self) -> QIcon:
        if getattr(sys, "frozen", False):
            base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        else:
            base = PROJECT_DIR
        icon_path = base / "assets" / "icon.ico"
        if icon_path.exists():
            return centered_icon(QIcon(str(icon_path)))
        return centered_icon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))

    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.setWindowIcon(self._app_icon())
        self.tray = QSystemTrayIcon(self._app_icon(), self)
        menu = QMenu()
        capture_action = QAction("截图翻译", self)
        show_action = QAction("显示主窗口", self)
        quit_action = QAction("退出", self)
        capture_action.triggered.connect(self.start_capture)
        show_action.triggered.connect(self.show_normal)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(capture_action)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        due_count = self.knowledge_base.count_due_terms()
        if due_count > 0:
            self.tray.showMessage(
                "今日复习",
                f"有 {due_count} 个收藏术语待复习。",
                QSystemTrayIcon.MessageIcon.Information,
                6000,
            )

    def _start_hotkey(self) -> None:
        if self.hotkey_manager is not None:
            self.hotkey_manager.stop()
        self.hotkey_manager = HotkeyManager(self.settings.hotkey)
        self.hotkey_manager.hotkey_pressed.connect(self.start_capture)
        self.hotkey_manager.failed.connect(self.status_label.setText)
        self.hotkey_manager.start()

    def _on_screenshot_captured(self, image_path: str) -> None:
        self.result_window.show_loading()
        self.status_label.setText("正在 OCR 识别和 AI 解释...")
        self.capture_worker = CaptureStreamWorker(
            image_path=image_path,
            settings=self.settings,
            ocr_service=self.ocr_service,
            history_store=self.history_store,
        )
        self.capture_worker.status.connect(self.result_window.set_status)
        self.capture_worker.source_ready.connect(self.result_window.set_source_text)
        self.capture_worker.stream_chunk.connect(self.result_window.append_stream_chunk)
        self.capture_worker.stream_terms.connect(self.result_window.set_stream_terms)
        self.capture_worker.completed.connect(self._on_stream_capture_done)
        self.capture_worker.finished.connect(self.capture_worker.deleteLater)
        self.capture_worker.start()

    def _on_stream_capture_done(self, payload: dict) -> None:
        self._capturing = False
        self._restore_window_after_capture()
        if "error" in payload:
            self._last_payload = payload
            self.result_window.set_result(payload)
            self.overview_page.refresh()
            self.status_label.setText(payload["error"])
            return
        self._last_payload = payload
        self.result_window.set_result(payload)
        self.overview_page.refresh()
        self.learning_page.refresh()
        self.refresh_terms()
        self._refresh_sidebar_stats()
        self.status_label.setText("截图翻译已完成并保存。")

        hint = payload.get("direction_hint") or {}
        if hint.get("conflict") and hint.get("detected_domain"):
            message = (
                f"这条内容识别为「{hint['detected_domain']}」方向，与当前学习方向不同。"
                "可在工作台切换方向后重试。"
            )
            self.status_label.setText(message)
            if self.tray is not None:
                self.tray.showMessage(
                    "学习方向提示",
                    message,
                    QSystemTrayIcon.MessageIcon.Information,
                    6000,
                )

    def _on_context_changed(self, _context_id: object) -> None:
        self._apply_current_context()

    def _on_followup_completed(self, payload: dict) -> None:
        if "error" in payload:
            self.result_window.show_followup_error(payload["error"])
            self.status_label.setText(payload["error"])
            return
        self._last_payload.update(payload)
        self.result_window.append_followup_result(payload)
        self.refresh_terms()
        self.learning_page.refresh()
        self.overview_page.refresh()
        self.status_label.setText("追问完成。")

    def _show_selected_term(self) -> None:
        row = self.terms_table.currentRow()
        if row < 0 or row >= len(self._terms_records):
            self.term_name_label.setText("选择术语")
            self.term_domain_label.setText("-")
            self.term_chinese_label.setText("中文名：-")
            self.term_explanation_label.clear()
            self.term_example_label.clear()
            self.term_count_label.setText("出现次数：-")
            if hasattr(self, "term_reasons_label"):
                self.term_reasons_label.setText("")
                self.term_reasons_label.setVisible(False)
            if hasattr(self, "term_sources_list"):
                self.term_sources_list.clear()
            if hasattr(self, "favorite_button"):
                self.favorite_button.setText("收藏")
            return
        view_item = self._terms_records[row]
        term = view_item.term
        self.term_name_label.setText(term.term)
        self.term_domain_label.setText(term.domain or "通用")
        self.term_chinese_label.setText(term.chinese_name or "无")
        self.term_explanation_label.setPlainText(term.beginner_explanation or "无")
        self.term_example_label.setPlainText("；".join(term.examples) if term.examples else "无")
        self.term_count_label.setText(
            f"出现 {term.review_count} 次 · 来自 {view_item.source_count} 条记录"
        )
        if hasattr(self, "term_reasons_label"):
            reasons = view_item.reasons
            self.term_reasons_label.setText("　·　".join(reasons))
            self.term_reasons_label.setVisible(bool(reasons))
        if hasattr(self, "favorite_button"):
            self.favorite_button.setText("已收藏" if term.favorite else "收藏")
        self._load_term_sources(term.id)

    def _load_term_sources(self, term_id: int) -> None:
        if not hasattr(self, "term_sources_list"):
            return
        sources = self.knowledge_base.list_term_sources(term_id, limit=30)
        self.term_sources_list.clear()
        if not sources:
            placeholder = QListWidgetItem("（暂无出处）")
            placeholder.setData(Qt.ItemDataRole.UserRole, None)
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.term_sources_list.addItem(placeholder)
            return
        for capture in sources:
            title = (capture.source_text or capture.translation or "截图").strip().splitlines()
            title = title[0] if title else "截图"
            created = (capture.created_at or "").replace("T", " ")[:16]
            item = QListWidgetItem(f"{_compact_text(title, 24)} · {created}")
            item.setData(Qt.ItemDataRole.UserRole, capture.id)
            self.term_sources_list.addItem(item)

    def _on_term_row_selected(self) -> None:
        self._show_selected_term()
        row = self.terms_table.currentRow()
        if 0 <= row < len(self._terms_records):
            view_item = self._terms_records[row]
            updated = self.knowledge_base.record_view(view_item.term.id)
            self._terms_records[row] = TermViewItem(
                term=updated,
                source_count=view_item.source_count,
                reasons=view_item.reasons,
            )

    def _on_term_source_clicked(self, item: QListWidgetItem) -> None:
        capture_id = item.data(Qt.ItemDataRole.UserRole)
        if capture_id is None:
            return
        self._open_capture(int(capture_id))

    def _open_capture(self, capture_id: int) -> None:
        self._switch_page(0)
        self.overview_page.select_capture(capture_id)

    def _open_review(self) -> None:
        dialog = ReviewDialog(self.knowledge_base, self)
        dialog.exec()
        self.refresh_terms()
        self._refresh_sidebar_stats()

    def _delete_selected_term(self) -> None:
        row = self.terms_table.currentRow()
        if row < 0 or row >= len(self._terms_records):
            return
        term = self._terms_records[row].term
        reply = QMessageBox.question(
            self,
            "删除术语",
            f"确定删除术语“{term.term}”吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.knowledge_base.delete_term(term.id)
        self.refresh_terms()
        self.status_label.setText("术语已删除。")

    def _add_manual_term(self) -> None:
        term, ok = QInputDialog.getText(self, "新增术语", "术语")
        if not ok or not term.strip():
            return
        chinese_name, ok = QInputDialog.getText(self, "新增术语", "中文名")
        if not ok:
            return
        explanation, ok = QInputDialog.getMultiLineText(self, "新增术语", "小白解释")
        if not ok:
            return
        examples_text, ok = QInputDialog.getText(self, "新增术语", "例子（多个例子用；分隔）")
        if not ok:
            return
        examples = [item.strip() for item in examples_text.split("；") if item.strip()]
        self.knowledge_base.save_term(
            SaveTermCommand(
                term=term,
                chinese_name=chinese_name,
                beginner_explanation=explanation,
                examples=examples,
                domain="通用",
            )
        )
        self.refresh_terms()
        self.status_label.setText("术语已新增。")

    def _edit_selected_term(self) -> None:
        row = self.terms_table.currentRow()
        if row < 0 or row >= len(self._terms_records):
            return
        current = self._terms_records[row].term
        term, ok = QInputDialog.getText(self, "编辑术语", "术语", text=current.term)
        if not ok or not term.strip():
            return
        chinese_name, ok = QInputDialog.getText(self, "编辑术语", "中文名", text=current.chinese_name)
        if not ok:
            return
        explanation, ok = QInputDialog.getMultiLineText(
            self,
            "编辑术语",
            "小白解释",
            current.beginner_explanation,
        )
        if not ok:
            return
        examples_text, ok = QInputDialog.getText(
            self,
            "编辑术语",
            "例子（多个例子用；分隔）",
            text="；".join(current.examples),
        )
        if not ok:
            return
        examples = [item.strip() for item in examples_text.split("；") if item.strip()]
        try:
            self.knowledge_base.save_term(
                SaveTermCommand(
                    term=term,
                    chinese_name=chinese_name,
                    beginner_explanation=explanation,
                    examples=examples,
                    term_id=current.id,
                    domain=current.domain,
                )
            )
        except Exception as exc:
            QMessageBox.warning(self, "编辑失败", str(exc))
            return
        self.refresh_terms()
        self.status_label.setText("术语已更新。")

    def _toggle_favorite(self) -> None:
        row = self.terms_table.currentRow()
        if row < 0 or row >= len(self._terms_records):
            return
        view_item = self._terms_records[row]
        term = view_item.term
        updated = self.knowledge_base.set_favorite(term.id, favorite=not term.favorite)
        self._terms_records[row] = TermViewItem(
            term=updated,
            source_count=view_item.source_count,
            reasons=view_item.reasons,
        )
        self._show_selected_term()
        self._refresh_sidebar_stats()
        self.status_label.setText(
            f"术语「{term.term}」{'已收藏' if updated.favorite else '取消收藏'}"
        )

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_normal()

    def show_normal(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def show_overview(self) -> None:
        self._switch_page(0)
        self.show_normal()

    def _set_native_titlebar_color(self) -> None:
        """Tint the native Windows title bar to match the app background (Win11+)."""
        if sys.platform != "win32":
            return

        def colorref(hex_color: str) -> int:
            hex_color = hex_color.lstrip("#")
            red = int(hex_color[0:2], 16)
            green = int(hex_color[2:4], 16)
            blue = int(hex_color[4:6], 16)
            return (blue << 16) | (green << 8) | red

        try:
            import ctypes
            from ctypes import wintypes

            hwnd = wintypes.HWND(int(self.winId()))
            caption = ctypes.c_uint(colorref(CARD))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption)
            )
            border = ctypes.c_uint(colorref(CARD))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 34, ctypes.byref(border), ctypes.sizeof(border)
            )
            text = ctypes.c_uint(colorref(TEXT))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 36, ctypes.byref(text), ctypes.sizeof(text)
            )
        except Exception:
            pass

    def _refresh_sidebar_stats(self) -> None:
        if not hasattr(self, "sidebar_stat_labels"):
            return
        stats = self.history_store.get_statistics()
        for key, label in self.sidebar_stat_labels.items():
            label.setText(str(stats[key]))

    def export_markdown(self) -> None:
        records = self.history_store.search_captures(limit=1000)
        export_dir = DATA_DIR / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        default_name = f"learning-notes-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 Markdown",
            str(export_dir / default_name),
            "Markdown (*.md)",
        )
        if not path:
            return
        if not path.lower().endswith(".md"):
            path += ".md"
        lines = ["# AI Learning Copilot 学习记录", ""]
        for record in records:
            lines.extend(
                [
                    f"## {record.created_at}",
                    "",
                    f"标签：{'、'.join(record.tags) if record.tags else '无'}",
                    "",
                    "### 原文",
                    "",
                    record.source_text or "无",
                    "",
                    "### 翻译",
                    "",
                    record.translation or "无",
                    "",
                    "### 解释",
                    "",
                    record.explanation or "无",
                    "",
                ]
            )
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        QMessageBox.information(self, "导出完成", f"已导出到：\n{path}")

    def quit_app(self) -> None:
        self._shutdown()
        QApplication.quit()

    def _shutdown(self) -> None:
        if self.settings.show_float_bar and self.result_window.isVisible():
            x, y = self.result_window.home_position()
            self._save_bar_position(x, y)
        if self.result_window is not None:
            self.result_window.force_close()
        if self.hotkey_manager is not None:
            self.hotkey_manager.stop()
        if self.tray is not None:
            self.tray.hide()


def _page() -> QWidget:
    page = QWidget()
    page.setStyleSheet(f"background:{BG};")
    return page


def _card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    frame.setStyleSheet(card_qss())
    return frame


def _card_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"color:{TEXT_SECONDARY}; background: transparent; border-left: 3px solid {PRIMARY}; "
        "padding-left: 8px;"
    )
    label.setFixedHeight(22)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return label


def _page_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"font-size:{FONT_TITLE}; color:{TEXT};")
    return label


def _field_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"color:{TEXT_SECONDARY}; background: transparent; border-left: 3px solid {PRIMARY}; "
        "padding-left: 8px;"
    )
    label.setFixedHeight(22)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return label


def _readonly_box(placeholder: str) -> QTextEdit:
    box = QTextEdit()
    box.setReadOnly(True)
    box.setAcceptRichText(False)
    box.setPlaceholderText(placeholder)
    box.setFrameShape(QTextEdit.Shape.NoFrame)
    box.document().setDocumentMargin(0)
    box.setStyleSheet(
        f"QTextEdit {{ background: transparent; border: none; padding: 0; color: {TEXT_SECONDARY}; }}"
    )
    box.setMinimumHeight(64)
    return box


def _nav_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setCheckable(True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet(nav_qss())
    return button


def _primary_button(text: str) -> QPushButton:
    button = QPushButton(text)
    apply_primary_button_style(button)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _ghost_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _page_nav_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFixedSize(26, 26)
    button.setStyleSheet(
        f"QPushButton {{ background:{CARD}; border:1px solid {BORDER}; "
        f"border-radius:{RADIUS_MD}; padding:0; color:{TEXT_SECONDARY}; "
        f'font-family:"Segoe UI", Arial, sans-serif; font-size:14px; }}'
        f"QPushButton:hover {{ border-color:{PRIMARY}; color:{PRIMARY}; }}"
        f"QPushButton:disabled {{ color:{DISABLED}; border-color:{BORDER_LIGHT}; }}"
    )
    return button


def _danger_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("dangerButton")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _mini_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFixedSize(30, 30)
    button.setStyleSheet(
        f"""
        QPushButton {{
            background: {CARD};
            border: 1px solid {BORDER};
            border-radius: {RADIUS_MD};
            padding: 0;
            min-width: 0;
            color: {TEXT_SECONDARY};
            font-family: "Segoe UI", Arial, sans-serif;
            font-size: 12px;
        }}
        QPushButton:hover {{
            border-color: {PRIMARY};
            color: {PRIMARY};
        }}
        """
    )
    return button



def _settings_card(title: str, rows: list[tuple[str, QWidget]], note: str = "") -> QFrame:
    card = _card()
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(12)
    layout.addWidget(_card_title(title))
    for label_text, field in rows:
        row = QHBoxLayout()
        label = QLabel(label_text)
        label.setFixedWidth(128)
        label.setStyleSheet(f"color:{TEXT_SECONDARY};")
        row.addWidget(label)
        row.addWidget(field, 1)
        layout.addLayout(row)
    if note:
        note_label = QLabel(note)
        note_label.setStyleSheet(f"color:{MUTED}; font-size:{FONT_MICRO};")
        note_label.setWordWrap(True)
        layout.addWidget(note_label)
    return card


def _term_keywords(term: TermRecord) -> str:
    parts: list[str] = []
    for value in term.examples:
        parts.extend(_split_keywords(value))
    if not parts:
        parts.extend(_split_keywords(term.beginner_explanation))
    return " / ".join(parts[:4]) if parts else "-"


def _split_keywords(text: str) -> list[str]:
    normalized = (
        (text or "")
        .replace("，", " ")
        .replace("。", " ")
        .replace("；", " ")
        .replace("、", " ")
        .replace(",", " ")
        .replace(";", " ")
        .replace(".", " ")
    )
    words = [word.strip() for word in normalized.split() if 1 < len(word.strip()) <= 18]
    result: list[str] = []
    for word in words:
        if word not in result:
            result.append(word)
    return result
