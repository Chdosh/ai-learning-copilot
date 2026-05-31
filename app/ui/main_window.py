from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QPixmap
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
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.paths import DATA_DIR, ensure_app_dirs
from app.services.history_store import CaptureRecord, HistoryStore, TermRecord
from app.services.ocr import OCRService
from app.services.screenshot import HotkeyManager, ScreenshotSelector
from app.services.settings import AppSettings, SettingsService
from app.ui.result_window import ResultWindow
from app.ui.theme import APP_STYLE, BLUE, BLUE_SOFT, BORDER, GREEN, MUTED, RED
from app.ui.workers import CapturePipelineWorker, FollowupWorker, TextExplainWorker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        ensure_app_dirs()
        self.history_store = HistoryStore()
        self.settings_service = SettingsService(self.history_store)
        self.settings = self.settings_service.load()
        self.ocr_service = OCRService(
            lang=self.settings.ocr_lang,
            tesseract_path=self.settings.tesseract_path,
        )
        self.hotkey_manager: HotkeyManager | None = None
        self.tray: QSystemTrayIcon | None = None
        self.selector: ScreenshotSelector | None = None
        self.capture_worker: CapturePipelineWorker | None = None
        self.text_worker: TextExplainWorker | None = None
        self.followup_worker: FollowupWorker | None = None
        self._history_records: list[CaptureRecord] = []
        self._terms_records: list[TermRecord] = []
        self._last_payload: dict = {}
        self.ui_font_size = 13

        self.result_window = ResultWindow(self.history_store)
        self.result_window.request_followup.connect(self.ask_followup)

        self.setWindowTitle("AI Learning Copilot")
        self.resize(1280, 820)
        self.setMinimumSize(1060, 680)
        self._apply_text_size()
        self._build_ui()
        self._build_tray()
        self._start_hotkey()
        self.refresh_history()
        self.refresh_terms()
        self.refresh_ocr_status()

    def start_capture(self) -> None:
        if self.selector is not None:
            return
        self.status_label.setText("准备截图，右键或 Esc 可取消。")
        self.hide()
        QTimer.singleShot(180, self._open_selector)

    def explain_text(self, source_text: str, mode: str = "default") -> None:
        self.status_label.setText("正在重新解释文本...")
        self.text_worker = TextExplainWorker(source_text, self.settings, mode=mode)
        self.text_worker.completed.connect(self._on_text_explained)
        self.text_worker.finished.connect(self.text_worker.deleteLater)
        self.text_worker.start()

    def ask_followup(self, source_text: str, question: str, mode: str = "custom") -> None:
        self.status_label.setText("正在追问...")
        conversation_id = self.result_window.payload.get("conversation_id")
        capture_id = self.result_window.payload.get("capture_id")
        self.followup_worker = FollowupWorker(
            source_text=source_text,
            question=question,
            settings=self.settings,
            history_store=self.history_store,
            conversation_id=int(conversation_id) if conversation_id else None,
            capture_id=int(capture_id) if capture_id else None,
            mode=mode,
        )
        self.followup_worker.completed.connect(self._on_followup_completed)
        self.followup_worker.finished.connect(self.followup_worker.deleteLater)
        self.followup_worker.start()

    def refresh_history(self) -> None:
        query = self.history_search.text().strip() if hasattr(self, "history_search") else ""
        records = self.history_store.search_captures(query=query, limit=200)
        self._history_records = records
        self.history_list.clear()
        for record in records:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, record.id)
            item.setSizeHint(QSize(420, 92))
            self.history_list.addItem(item)
            self.history_list.setItemWidget(item, self._history_item_widget(record))
        if records and self.history_list.currentRow() < 0:
            self.history_list.setCurrentRow(0)
        self.history_count_label.setText(f"共 {len(records)} 条记录")
        self.sidebar_stats_label.setText(
            f"今日学习统计\n\n截图        {len(records)}\n追问        {_count_followups_hint(records)}\n术语        {len(self._terms_records)}"
        )
        self.status_label.setText(f"历史记录：{len(records)} 条")

    def refresh_terms(self) -> None:
        query = self.terms_search.text().strip() if hasattr(self, "terms_search") else ""
        terms = self.history_store.list_terms(query=query)
        self._terms_records = terms
        self.terms_table.setRowCount(len(terms))
        for row, term in enumerate(terms):
            values = [
                term.term,
                term.chinese_name or "-",
                _term_keywords(term),
                str(term.review_count),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setData(Qt.ItemDataRole.UserRole, term.id)
                item.setToolTip(_format_term_tooltip(term))
                self.terms_table.setItem(row, column, item)
            self.terms_table.setRowHeight(row, max(34, self.ui_font_size + 24))
        if terms and not self.terms_table.selectedItems():
            self.terms_table.selectRow(0)
        self.terms_count_label.setText(f"共 {len(terms)} 条术语")
        if hasattr(self, "sidebar_stats_label"):
            self.sidebar_stats_label.setText(
                f"今日学习统计\n\n截图        {len(self._history_records)}\n追问        {_count_followups_hint(self._history_records)}\n术语        {len(terms)}"
            )

    def save_settings(self) -> None:
        self.settings = AppSettings(
            api_key=self.api_key_input.text().strip(),
            base_url=self.base_url_input.text().strip(),
            model=self.model_input.text().strip(),
            hotkey=self.hotkey_input.text().strip(),
            save_screenshots=self.save_screenshots_checkbox.isChecked(),
            ocr_lang=self.ocr_lang_input.text().strip() or "eng+chi_sim",
            tesseract_path=self.tesseract_path_input.text().strip(),
        )
        self.settings_service.save(self.settings)
        self.ocr_service = OCRService(
            lang=self.settings.ocr_lang,
            tesseract_path=self.settings.tesseract_path,
        )
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
        sidebar.setFixedWidth(218)
        sidebar.setStyleSheet(
            f"""
            QFrame#sidebar {{
                background: #ffffff;
                border-right: 1px solid {BORDER};
            }}
            """
        )
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 18, 14, 18)
        sidebar_layout.setSpacing(10)

        logo = QLabel("✧")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(f"color: {BLUE}; font-size: 42px; font-weight: 700;")
        sidebar_layout.addWidget(logo)

        self.nav_buttons: list[QPushButton] = []
        self.pages = QStackedWidget()
        self._add_page(sidebar_layout, "⌂  首页", self._build_home_page())
        self._add_page(sidebar_layout, "▣  截图/小窗", self._build_capture_page())
        self._add_page(sidebar_layout, "▤  结果/大窗口", self._build_result_page())
        self._add_page(sidebar_layout, "◴  历史记录", self._build_history_page())
        self._add_page(sidebar_layout, "▣  术语本", self._build_terms_page())
        self._add_page(sidebar_layout, "⚙  设置", self._build_settings_page())

        export_button = _side_action("⇩  导出 Markdown")
        export_button.clicked.connect(self.export_markdown)
        sidebar_layout.addWidget(export_button)

        font_row = QHBoxLayout()
        font_row.setContentsMargins(4, 0, 4, 0)
        font_row.setSpacing(6)
        smaller_font = _mini_button("A-")
        larger_font = _mini_button("A+")
        smaller_font.clicked.connect(lambda: self.adjust_text_size(-1))
        larger_font.clicked.connect(lambda: self.adjust_text_size(1))
        font_row.addWidget(smaller_font)
        font_row.addWidget(larger_font)
        sidebar_layout.addLayout(font_row)
        sidebar_layout.addStretch()

        self.sidebar_stats_label = QLabel("今日学习统计\n\n截图        0\n追问        0\n术语        0")
        self.sidebar_stats_label.setObjectName("sidebarCard")
        self.sidebar_stats_label.setStyleSheet(
            f"""
            QLabel#sidebarCard {{
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 10px;
                padding: 14px;
                color: #344054;
                line-height: 1.45;
            }}
            """
        )
        sidebar_layout.addWidget(self.sidebar_stats_label)

        local_label = QLabel("●  本地模式")
        local_label.setStyleSheet(f"color: {MUTED}; padding: 8px;")
        sidebar_layout.addWidget(local_label)

        main_area = QWidget()
        main_layout = QVBoxLayout(main_area)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.pages, 1)
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet(
            f"border-top:1px solid {BORDER}; color:{MUTED}; padding:8px 22px;"
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
            font.setPointSize(self.ui_font_size)
            app.setFont(font)
        padding = max(5, self.ui_font_size - 7)
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

    def adjust_text_size(self, delta: int) -> None:
        self.ui_font_size = max(11, min(17, self.ui_font_size + delta))
        self._apply_text_size()
        self.result_window.adjust_text_size(delta)
        if hasattr(self, "terms_table"):
            self.refresh_terms()
        self.status_label.setText(f"文本大小：{self.ui_font_size}px")

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
        if index == 3:
            self.refresh_history()
        elif index == 4:
            self.refresh_terms()
        elif index == 5:
            self.refresh_ocr_status()

    def _build_home_page(self) -> QWidget:
        page = _page()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(18)
        layout.addWidget(_title_block("AI Learning Copilot", "一键截图、OCR 识别、AI 翻译解释，并自动沉淀为本地学习记录。"))

        cards = QGridLayout()
        cards.setHorizontalSpacing(16)
        cards.setVerticalSpacing(16)
        cards.addWidget(
            _feature_card(
                "截图翻译",
                f"全局快捷键：{self.settings.hotkey}\n右键或 Esc 取消截图。",
                "开始截图",
                self.start_capture,
                primary=True,
            ),
            0,
            0,
        )
        cards.addWidget(
            _feature_card(
                "本地保存",
                "截图解释、追问和术语都保存在 SQLite，可以离线查看。",
                "打开历史",
                lambda: self._switch_page(3),
            ),
            0,
            1,
        )
        cards.addWidget(
            _feature_card(
                "术语本",
                "AI 自动抽取术语，按出现次数沉淀，适合复习。",
                "查看术语",
                lambda: self._switch_page(4),
            ),
            1,
            0,
        )
        cards.addWidget(
            _feature_card(
                "便携 OCR",
                "优先使用项目内置 Tesseract，不要求用户手动配置系统路径。",
                "检查 OCR",
                lambda: self._switch_page(5),
            ),
            1,
            1,
        )
        layout.addLayout(cards)
        layout.addStretch()
        return page

    def _build_capture_page(self) -> QWidget:
        page = _page()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(18)
        layout.addWidget(_title_block("截图/小窗", "核心入口保持简单：快捷键或按钮触发，框选后弹出轻量结果小窗。"))

        card = _card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 24, 28, 24)
        card_layout.setSpacing(18)
        title = QLabel("AI 截图翻译")
        title.setStyleSheet("font-size: 24px; font-weight: 800;")
        desc = QLabel("框选任意软件、网页或文档里的文字区域。完成后会自动 OCR、AI 翻译解释，并写入历史记录。")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {MUTED}; font-size: 15px;")
        shortcut = QLabel(f"当前快捷键：{self.settings.hotkey}    取消截图：右键 / Esc")
        shortcut.setStyleSheet(f"color: {MUTED};")
        button = _primary_button("▣  开始截图翻译")
        button.setFixedHeight(46)
        button.clicked.connect(self.start_capture)
        card_layout.addWidget(title)
        card_layout.addWidget(desc)
        card_layout.addWidget(shortcut)
        card_layout.addWidget(button)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _build_result_page(self) -> QWidget:
        page = _page()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(18)
        layout.addWidget(_title_block("结果/大窗口", "最近一次截图结果可以重新打开，也可以从历史记录继续查看。"))
        card = _card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 20, 22, 20)
        card_layout.setSpacing(12)
        row = QHBoxLayout()
        row.addWidget(_card_title("最近结果"))
        row.addStretch()
        open_button = _primary_button("打开结果窗口")
        open_button.clicked.connect(self._open_last_result)
        row.addWidget(open_button)
        card_layout.addLayout(row)
        self.last_result_detail = QTextEdit()
        self.last_result_detail.setReadOnly(True)
        self.last_result_detail.setAcceptRichText(False)
        self.last_result_detail.setPlaceholderText("截图完成后，这里会显示最近一次原文、翻译和解释摘要。")
        card_layout.addWidget(self.last_result_detail, 1)
        layout.addWidget(card, 1)
        return page

    def _build_history_page(self) -> QWidget:
        page = _page()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.addWidget(_title_block("历史记录", "所有截图解释与追问都会保存在本地 SQLite。"))
        header.addStretch()
        local_badge = QLabel("● 本地保存 · 可离线查看")
        local_badge.setStyleSheet(
            f"background:#eaf8ef; color:{GREEN}; border-radius:14px; padding:6px 12px; font-weight:700;"
        )
        header.addWidget(local_badge)
        reopen_button = _primary_button("⟳  重新打开")
        reopen_button.clicked.connect(self._open_selected_history_result)
        export_button = _ghost_button("⇩  导出 Markdown")
        export_button.clicked.connect(self.export_markdown)
        header.addWidget(reopen_button)
        header.addWidget(export_button)
        layout.addLayout(header)

        filters = _card()
        filters_layout = QHBoxLayout(filters)
        filters_layout.setContentsMargins(12, 10, 12, 10)
        filters_layout.setSpacing(10)
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("搜索原文、翻译、解释或标签")
        self.history_search.returnPressed.connect(self.refresh_history)
        filters_layout.addWidget(self.history_search, 1)
        search_button = _ghost_button("筛选")
        search_button.clicked.connect(self.refresh_history)
        filters_layout.addWidget(search_button)
        for label in ("今天", "本周", "有追问", "已收藏", "全部标签"):
            filters_layout.addWidget(_chip(label, active=(label == "今天")))
        layout.addWidget(filters)

        content = QHBoxLayout()
        content.setSpacing(14)

        list_card = _card()
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(8, 12, 8, 8)
        self.history_count_label = QLabel("共 0 条记录")
        self.history_count_label.setStyleSheet("font-weight:700; padding: 0 10px;")
        self.history_list = QListWidget()
        self.history_list.setSpacing(8)
        self.history_list.currentItemChanged.connect(self._show_history_item)
        self.history_list.itemDoubleClicked.connect(self._open_history_result)
        list_layout.addWidget(self.history_count_label)
        list_layout.addWidget(self.history_list, 1)

        detail_card = _card()
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.setContentsMargins(18, 16, 18, 16)
        detail_layout.setSpacing(10)
        detail_top = QHBoxLayout()
        self.history_title_label = QLabel("选择一条记录")
        self.history_title_label.setStyleSheet("font-size:18px; font-weight:800;")
        self.history_id_label = QLabel("")
        self.history_id_label.setStyleSheet(f"color:{MUTED};")
        detail_top.addWidget(self.history_title_label)
        detail_top.addStretch()
        detail_top.addWidget(self.history_id_label)
        detail_layout.addLayout(detail_top)
        self.history_meta_label = QLabel("时间：-")
        self.history_meta_label.setStyleSheet(f"color:{MUTED};")
        detail_layout.addWidget(self.history_meta_label)
        self.history_path_label = QLabel("截图路径：-")
        self.history_path_label.setStyleSheet(f"color:{MUTED};")
        self.history_path_label.setWordWrap(True)
        detail_layout.addWidget(self.history_path_label)
        self.history_source_box = _readonly_box("原文")
        self.history_translation_box = _readonly_box("翻译")
        self.history_explanation_box = _readonly_box("小白解释")
        detail_layout.addWidget(_field_title("原文"))
        detail_layout.addWidget(self.history_source_box)
        detail_layout.addWidget(_field_title("翻译"))
        detail_layout.addWidget(self.history_translation_box)
        detail_layout.addWidget(_field_title("小白解释"))
        detail_layout.addWidget(self.history_explanation_box, 1)
        self.history_tags_label = QLabel("标签：无")
        self.history_tags_label.setStyleSheet(f"color:{MUTED};")
        detail_layout.addWidget(self.history_tags_label)

        content.addWidget(list_card, 4)
        content.addWidget(detail_card, 6)
        layout.addLayout(content, 1)
        return page

    def _build_terms_page(self) -> QWidget:
        page = _page()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.addWidget(_title_block("术语本", "沉淀你在截图学习中遇到的关键词与术语。"))
        header.addStretch()
        ai_badge = QLabel("✧ 术语可来自 AI 自动提取")
        ai_badge.setStyleSheet(
            f"background:{BLUE_SOFT}; color:{BLUE}; border:1px solid #c7d7fe; border-radius:8px; padding:8px 12px; font-weight:700;"
        )
        header.addWidget(ai_badge)
        self.terms_search = QLineEdit()
        self.terms_search.setPlaceholderText("搜索术语")
        self.terms_search.setFixedWidth(260)
        self.terms_search.returnPressed.connect(self.refresh_terms)
        header.addWidget(self.terms_search)
        add_button = _primary_button("新增术语  +")
        add_button.clicked.connect(self._add_manual_term)
        header.addWidget(add_button)
        layout.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(16)

        table_card = _card()
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(0, 0, 0, 12)
        self.terms_table = QTableWidget(0, 4)
        self.terms_table.setHorizontalHeaderLabels(["术语", "中文名", "关键词", "次数"])
        self.terms_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.terms_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.terms_table.verticalHeader().setVisible(False)
        self.terms_table.setShowGrid(False)
        self.terms_table.setWordWrap(False)
        self.terms_table.itemSelectionChanged.connect(self._show_selected_term)
        self.terms_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.terms_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.terms_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.terms_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table_layout.addWidget(self.terms_table, 1)
        table_bottom = QHBoxLayout()
        self.terms_count_label = QLabel("共 0 条术语")
        self.terms_count_label.setStyleSheet(f"color:{MUTED}; padding-left:14px;")
        table_bottom.addWidget(self.terms_count_label)
        table_bottom.addStretch()
        table_bottom.addWidget(_chip("1", active=True))
        table_bottom.addWidget(_chip("20 条/页"))
        table_layout.addLayout(table_bottom)

        detail_card = _card()
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.setContentsMargins(20, 18, 20, 18)
        detail_layout.setSpacing(12)
        row = QHBoxLayout()
        row.addWidget(_card_title("术语详情"))
        row.addStretch()
        row.addWidget(QLabel("☆"))
        detail_layout.addLayout(row)
        self.term_name_label = QLabel("选择术语")
        self.term_name_label.setStyleSheet("font-size:20px; font-weight:800;")
        self.term_chinese_label = QLabel("中文名：-")
        self.term_explanation_label = _readonly_box("完整解释")
        self.term_explanation_label.setMinimumHeight(160)
        self.term_example_label = _readonly_box("当前例子")
        self.term_example_label.setMinimumHeight(90)
        self.term_count_label = QLabel("出现次数：-")
        for label in (
            self.term_chinese_label,
            self.term_count_label,
        ):
            label.setWordWrap(True)
            label.setObjectName("denseDetail")
            label.setStyleSheet("line-height:1.4;")
        detail_layout.addWidget(self.term_name_label)
        detail_layout.addWidget(_field_title("中文名"))
        detail_layout.addWidget(self.term_chinese_label)
        detail_layout.addWidget(_field_title("完整解释"))
        detail_layout.addWidget(self.term_explanation_label)
        detail_layout.addWidget(_field_title("当前例子"))
        detail_layout.addWidget(self.term_example_label)
        detail_layout.addWidget(_field_title("出现次数"))
        detail_layout.addWidget(self.term_count_label)
        detail_layout.addStretch()
        term_buttons = QHBoxLayout()
        favorite_button = _ghost_button("☆ 收藏")
        favorite_button.clicked.connect(self._show_favorite_hint)
        edit_button = _ghost_button("✎ 编辑")
        edit_button.clicked.connect(self._edit_selected_term)
        term_buttons.addWidget(favorite_button)
        term_buttons.addWidget(edit_button)
        delete_button = _danger_button("删除")
        delete_button.clicked.connect(self._delete_selected_term)
        term_buttons.addWidget(delete_button)
        detail_layout.addLayout(term_buttons)

        content.addWidget(table_card, 7)
        content.addWidget(detail_card, 4)
        layout.addLayout(content, 1)
        foot = QLabel("数据保存在本地 SQLite 数据库")
        foot.setAlignment(Qt.AlignmentFlag.AlignRight)
        foot.setStyleSheet(f"color:{MUTED};")
        layout.addWidget(foot)
        return page

    def _build_settings_page(self) -> QWidget:
        page = _page()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        settings_nav = QFrame()
        settings_nav.setFixedWidth(250)
        settings_nav.setStyleSheet(f"background:#ffffff; border-right:1px solid {BORDER};")
        settings_nav_layout = QVBoxLayout(settings_nav)
        settings_nav_layout.setContentsMargins(18, 28, 18, 18)
        title = QLabel("⚙  设置")
        title.setStyleSheet("font-size:26px; font-weight:800;")
        settings_nav_layout.addWidget(title)
        for label in ("▣  AI 配置", "⌗  OCR 配置", "⌨  快捷键", "▤  保存与导出", "ⓘ  关于"):
            button = _nav_button(label)
            button.setChecked(label.startswith("▣"))
            settings_nav_layout.addWidget(button)
        settings_nav_layout.addStretch()
        settings_nav_layout.addWidget(QLabel("v2.0.0"))

        content_holder = QWidget()
        content_layout = QVBoxLayout(content_holder)
        content_layout.setContentsMargins(34, 28, 34, 18)
        content_layout.setSpacing(14)
        content_layout.addWidget(_title_block("设置", "配置 AI、OCR、快捷键与本地保存选项。"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(14)

        self.api_key_input = QLineEdit(self.settings.api_key)
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.base_url_input = QLineEdit(self.settings.base_url)
        self.model_input = QLineEdit(self.settings.model)
        ai_card = _settings_card(
            "▣  AI 配置",
            [
                ("API Key", self.api_key_input),
                ("Base URL", self.base_url_input),
                ("模型名称", self.model_input),
            ],
            "兼容 OpenAI 接口，可配置 DeepSeek 等纯文本模型。",
        )
        scroll_layout.addWidget(ai_card)

        self.ocr_lang_input = QLineEdit(self.settings.ocr_lang)
        self.tesseract_path_input = QLineEdit(self.settings.tesseract_path)
        self.tesseract_path_input.setPlaceholderText("留空时优先使用 vendor/tesseract/tesseract.exe")
        self.ocr_status_label = QLabel("")
        self.ocr_status_label.setWordWrap(True)
        self.ocr_status_label.setStyleSheet(f"color:{MUTED};")
        detect_button = _ghost_button("自动检测")
        detect_button.clicked.connect(self.refresh_ocr_status)
        ocr_path_row = QWidget()
        ocr_path_layout = QHBoxLayout(ocr_path_row)
        ocr_path_layout.setContentsMargins(0, 0, 0, 0)
        ocr_path_layout.setSpacing(8)
        ocr_path_layout.addWidget(self.tesseract_path_input, 1)
        ocr_path_layout.addWidget(detect_button)
        ocr_card = _settings_card(
            "⌗  OCR 配置",
            [
                ("OCR 引擎", QLabel("Tesseract（本地便携优先）")),
                ("Tesseract 路径", ocr_path_row),
                ("语言", self.ocr_lang_input),
                ("检测状态", self.ocr_status_label),
            ],
        )
        scroll_layout.addWidget(ocr_card)

        self.hotkey_input = QLineEdit(self.settings.hotkey)
        hotkey_card = _settings_card(
            "⌨  快捷键",
            [
                ("截图翻译", self.hotkey_input),
                ("发送追问", QLabel("Ctrl + Enter")),
                ("打开历史", QLabel("Ctrl + H")),
            ],
        )
        scroll_layout.addWidget(hotkey_card)

        self.save_screenshots_checkbox = QCheckBox("")
        self.save_screenshots_checkbox.setChecked(self.settings.save_screenshots)
        save_card = _settings_card(
            "▤  保存与导出",
            [
                ("保存截图", self.save_screenshots_checkbox),
                ("自动保存会话", QLabel("开启")),
                ("默认导出格式", QLabel("Markdown（.md）")),
            ],
        )
        scroll_layout.addWidget(save_card)
        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        content_layout.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        test_button = _ghost_button("⟳  测试连接")
        test_button.clicked.connect(self.refresh_ocr_status)
        save_button = _primary_button("▣  保存设置")
        save_button.clicked.connect(self.save_settings)
        footer.addWidget(test_button)
        footer.addWidget(save_button)
        content_layout.addLayout(footer)

        outer.addWidget(settings_nav)
        outer.addWidget(content_holder, 1)
        return page

    def refresh_ocr_status(self) -> None:
        if not hasattr(self, "ocr_status_label"):
            return
        temp_service = OCRService(
            lang=self.ocr_lang_input.text().strip() or "eng+chi_sim",
            tesseract_path=self.tesseract_path_input.text().strip(),
        )
        status = temp_service.check_status()
        if status.ok:
            self.ocr_status_label.setStyleSheet(f"color: {GREEN}; font-weight: 700;")
        else:
            self.ocr_status_label.setStyleSheet(f"color: {RED}; font-weight: 700;")
        details = [
            status.message,
            f"来源：{status.source or '无'}",
            f"路径：{status.executable or '未找到'}",
        ]
        if status.available_languages:
            details.append("已安装语言：" + "、".join(status.available_languages))
        if status.missing_languages:
            details.append("缺少语言：" + "、".join(status.missing_languages))
        self.ocr_status_label.setText("\n".join(details))

    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray = QSystemTrayIcon(icon, self)
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

    def _start_hotkey(self) -> None:
        if self.hotkey_manager is not None:
            self.hotkey_manager.stop()
        self.hotkey_manager = HotkeyManager(self.settings.hotkey)
        self.hotkey_manager.hotkey_pressed.connect(self.start_capture)
        self.hotkey_manager.failed.connect(self.status_label.setText)
        self.hotkey_manager.start()

    def _open_selector(self) -> None:
        self.selector = ScreenshotSelector()
        self.selector.captured.connect(self._on_screenshot_captured)
        self.selector.cancelled.connect(self._on_screenshot_cancelled)
        self.selector.destroyed.connect(lambda: setattr(self, "selector", None))
        self.selector.begin()

    def _on_screenshot_captured(self, image_path: str) -> None:
        self.result_window.set_loading(image_path)
        self.status_label.setText("正在 OCR 识别和 AI 解释...")
        self.capture_worker = CapturePipelineWorker(
            image_path=image_path,
            settings=self.settings,
            ocr_service=self.ocr_service,
            history_store=self.history_store,
        )
        self.capture_worker.completed.connect(self._on_capture_completed)
        self.capture_worker.finished.connect(self.capture_worker.deleteLater)
        self.capture_worker.start()

    def _on_screenshot_cancelled(self) -> None:
        self.show_normal()
        self.status_label.setText("已取消截图。")

    def _on_capture_completed(self, payload: dict) -> None:
        self._last_payload = payload
        self.result_window.set_result(payload)
        self.last_result_detail.setPlainText(_format_payload(payload))
        self.refresh_history()
        self.refresh_terms()
        self.status_label.setText("截图翻译已完成并保存。")

    def _on_text_explained(self, payload: dict) -> None:
        self._last_payload = payload
        self.result_window.set_result(payload)
        self.last_result_detail.setPlainText(_format_payload(payload))
        self.status_label.setText("重新解释完成。")

    def _on_followup_completed(self, payload: dict) -> None:
        self.result_window.append_followup_result(payload)
        self.refresh_terms()
        self.status_label.setText("追问完成。")

    def _show_history_item(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if current is None:
            self._clear_history_detail()
            return
        record = self.history_store.get_capture(int(current.data(Qt.ItemDataRole.UserRole)))
        if record is None:
            self._clear_history_detail()
            return
        self.history_title_label.setText(_capture_title(record))
        self.history_id_label.setText(f"ID: {record.id}")
        self.history_meta_label.setText(f"时间：{record.created_at}")
        self.history_path_label.setText(f"截图路径：{record.image_path or '未保存'}")
        self.history_source_box.setPlainText(record.source_text or "无")
        self.history_translation_box.setPlainText(record.translation or "无")
        self.history_explanation_box.setPlainText(record.explanation or "无")
        self.history_tags_label.setText(f"标签：{'、'.join(record.tags) if record.tags else '无'}")

    def _clear_history_detail(self) -> None:
        self.history_title_label.setText("选择一条记录")
        self.history_id_label.setText("")
        self.history_meta_label.setText("时间：-")
        self.history_path_label.setText("截图路径：-")
        self.history_source_box.clear()
        self.history_translation_box.clear()
        self.history_explanation_box.clear()
        self.history_tags_label.setText("标签：无")

    def _open_history_result(self, item: QListWidgetItem) -> None:
        record = self.history_store.get_capture(int(item.data(Qt.ItemDataRole.UserRole)))
        if record is None:
            return
        payload = {
            "capture_id": record.id,
            "conversation_id": self.history_store.get_conversation_id_for_capture(record.id),
            "image_path": record.image_path,
            "source_text": record.source_text,
            "translation": record.translation,
            "explanation": record.explanation,
            "terms": [],
            "tags": record.tags,
            "learning_tip": "",
        }
        self._last_payload = payload
        self.result_window.set_result(payload)
        self.last_result_detail.setPlainText(_format_payload(payload))

    def _open_selected_history_result(self) -> None:
        item = self.history_list.currentItem()
        if item is not None:
            self._open_history_result(item)

    def _open_last_result(self) -> None:
        if self._last_payload:
            self.result_window.set_result(self._last_payload)
            return
        item = self.history_list.currentItem()
        if item is not None:
            self._open_history_result(item)
            return
        QMessageBox.information(self, "暂无结果", "还没有可以打开的截图结果。")

    def _show_selected_term(self) -> None:
        row = self.terms_table.currentRow()
        if row < 0 or row >= len(self._terms_records):
            self.term_name_label.setText("选择术语")
            self.term_chinese_label.setText("中文名：-")
            self.term_explanation_label.clear()
            self.term_example_label.clear()
            self.term_count_label.setText("出现次数：-")
            return
        term = self._terms_records[row]
        self.term_name_label.setText(term.term)
        self.term_chinese_label.setText(term.chinese_name or "无")
        self.term_explanation_label.setPlainText(term.beginner_explanation or "无")
        self.term_example_label.setPlainText("；".join(term.examples) if term.examples else "无")
        self.term_count_label.setText(str(term.review_count))

    def _delete_selected_term(self) -> None:
        row = self.terms_table.currentRow()
        if row < 0 or row >= len(self._terms_records):
            return
        term = self._terms_records[row]
        reply = QMessageBox.question(
            self,
            "删除术语",
            f"确定删除术语“{term.term}”吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.history_store.delete_term(term.id)
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
        self.history_store.save_term(
            term=term,
            chinese_name=chinese_name,
            beginner_explanation=explanation,
            examples=examples,
        )
        self.refresh_terms()
        self.status_label.setText("术语已新增。")

    def _edit_selected_term(self) -> None:
        row = self.terms_table.currentRow()
        if row < 0 or row >= len(self._terms_records):
            return
        current = self._terms_records[row]
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
            self.history_store.save_term(
                term=term,
                chinese_name=chinese_name,
                beginner_explanation=explanation,
                examples=examples,
                term_id=current.id,
            )
        except Exception as exc:
            QMessageBox.warning(self, "编辑失败", str(exc))
            return
        self.refresh_terms()
        self.status_label.setText("术语已更新。")

    def _show_favorite_hint(self) -> None:
        QMessageBox.information(self, "收藏术语", "当前数据库还没有收藏字段，后续会作为术语本增强项加入。")

    def _history_item_widget(self, record: CaptureRecord) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)
        thumb = QLabel()
        thumb.setFixedSize(116, 64)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setStyleSheet(f"background:#f6f8fb; border:1px solid {BORDER}; border-radius:6px; color:{MUTED};")
        if record.image_path and Path(record.image_path).exists():
            pixmap = QPixmap(record.image_path)
            if not pixmap.isNull():
                thumb.setPixmap(
                    pixmap.scaled(
                        thumb.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                thumb.setText("截图")
        else:
            thumb.setText("未保存")
        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        title = QLabel(_capture_title(record))
        title.setStyleSheet("font-size:15px; font-weight:800;")
        preview = QLabel(_compact_text(record.translation or record.explanation or record.source_text, 52))
        preview.setStyleSheet(f"color:{MUTED};")
        tags = QLabel("  ".join(record.tags[:3]) if record.tags else "待处理")
        tags.setStyleSheet(f"color:{BLUE};")
        text_col.addWidget(title)
        text_col.addWidget(preview)
        text_col.addWidget(tags)
        layout.addWidget(thumb)
        layout.addLayout(text_col, 1)
        return widget

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_normal()

    def show_normal(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def export_markdown(self) -> None:
        records = self.history_store.search_captures(limit=1000)
        export_dir = DATA_DIR / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / f"learning-notes-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
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
        path.write_text("\n".join(lines), encoding="utf-8")
        QMessageBox.information(self, "导出完成", f"已导出到：\n{path}")

    def quit_app(self) -> None:
        self._shutdown()
        QApplication.quit()

    def _shutdown(self) -> None:
        if self.result_window is not None:
            self.result_window.force_close()
        if self.hotkey_manager is not None:
            self.hotkey_manager.stop()
        if self.tray is not None:
            self.tray.hide()


def _page() -> QWidget:
    page = QWidget()
    page.setStyleSheet("background:#f8fbff;")
    return page


def _card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    frame.setStyleSheet(
        f"""
        QFrame#card {{
            background: #ffffff;
            border: 1px solid {BORDER};
            border-radius: 12px;
        }}
        """
    )
    return frame


def _title_block(title: str, subtitle: str) -> QWidget:
    widget = QWidget()
    widget.setObjectName("titleBlock")
    widget.setStyleSheet("QWidget#titleBlock { background: transparent; }")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    title_label = QLabel(title)
    title_label.setStyleSheet("font-size:24px; font-weight:800;")
    subtitle_label = QLabel(subtitle)
    subtitle_label.setStyleSheet(f"color:{MUTED}; font-size:13px;")
    subtitle_label.setWordWrap(True)
    layout.addWidget(title_label)
    layout.addWidget(subtitle_label)
    return widget


def _card_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-size:16px; font-weight:800;")
    return label


def _field_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-weight:800; color:#344054;")
    return label


def _readonly_box(placeholder: str) -> QTextEdit:
    box = QTextEdit()
    box.setReadOnly(True)
    box.setAcceptRichText(False)
    box.setPlaceholderText(placeholder)
    box.setMinimumHeight(78)
    return box


def _nav_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setCheckable(True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet(
        f"""
        QPushButton {{
            text-align: left;
            padding: 12px 14px;
            border: 0;
            border-radius: 10px;
            background: transparent;
            color: #344054;
            font-size: 14px;
            font-weight: 500;
        }}
        QPushButton:hover {{
            background: #f1f6ff;
            color: {BLUE};
        }}
        QPushButton:checked {{
            background: #eaf2ff;
            color: {BLUE};
            font-weight: 800;
        }}
        """
    )
    return button


def _side_action(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet(
        f"""
        QPushButton {{
            text-align: left;
            padding: 11px 14px;
            border: 0;
            border-radius: 10px;
            background: transparent;
            color: #475467;
            font-size: 14px;
        }}
        QPushButton:hover {{
            background: #f1f6ff;
            color: {BLUE};
        }}
        """
    )
    return button


def _primary_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("primaryButton")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _ghost_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _danger_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("dangerButton")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _mini_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFixedHeight(30)
    button.setStyleSheet(
        f"""
        QPushButton {{
            background: #ffffff;
            border: 1px solid {BORDER};
            border-radius: 8px;
            padding: 2px 8px;
            color: #344054;
            font-weight: 700;
        }}
        QPushButton:hover {{
            border-color: {BLUE};
            color: {BLUE};
        }}
        """
    )
    return button


def _chip(text: str, active: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if active:
        button.setObjectName("primaryButton")
    else:
        button.setStyleSheet(
            f"""
            QPushButton {{
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 17px;
                padding: 7px 16px;
                color: #344054;
            }}
            """
        )
    return button


def _feature_card(
    title: str,
    body: str,
    button_text: str,
    on_click,
    primary: bool = False,
) -> QFrame:
    card = _card()
    card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(12)
    title_label = QLabel(title)
    title_label.setStyleSheet("font-size:18px; font-weight:800;")
    body_label = QLabel(body)
    body_label.setWordWrap(True)
    body_label.setStyleSheet(f"color:{MUTED}; line-height:1.45;")
    button = _primary_button(button_text) if primary else _ghost_button(button_text)
    button.clicked.connect(on_click)
    layout.addWidget(title_label)
    layout.addWidget(body_label)
    layout.addWidget(button)
    return card


def _settings_card(title: str, rows: list[tuple[str, QWidget]], note: str = "") -> QFrame:
    card = _card()
    layout = QVBoxLayout(card)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(12)
    layout.addWidget(_card_title(title))
    for label_text, field in rows:
        row = QHBoxLayout()
        label = QLabel(label_text)
        label.setFixedWidth(130)
        label.setStyleSheet("font-weight:600;")
        row.addWidget(label)
        row.addWidget(field, 1)
        layout.addLayout(row)
    if note:
        note_label = QLabel(f"ⓘ  {note}")
        note_label.setStyleSheet(f"color:{MUTED};")
        layout.addWidget(note_label)
    return card


def _capture_title(record: CaptureRecord) -> str:
    for value in (record.explanation, record.translation, record.source_text):
        text = _compact_text(value, 28)
        if text and text != "无":
            return text
    return "OCR 识别记录"


def _compact_text(value: str, limit: int) -> str:
    text = " ".join((value or "").split())
    if not text:
        return "无"
    return text if len(text) <= limit else f"{text[:limit]}..."


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


def _format_term_tooltip(term: TermRecord) -> str:
    examples = "；".join(term.examples) if term.examples else "无"
    return f"""术语：{term.term}
中文名：{term.chinese_name or "无"}
次数：{term.review_count}

解释：
{term.beginner_explanation or "无"}

例子：
{examples}
"""


def _count_followups_hint(records: list[CaptureRecord]) -> int:
    return sum(1 for record in records if record.explanation or record.translation)


def _format_payload(payload: dict) -> str:
    tags = payload.get("tags") or []
    return f"""截图：{payload.get("image_path") or "未保存"}
标签：{"、".join(tags) if tags else "无"}

原文：
{payload.get("source_text") or "无"}

翻译：
{payload.get("translation") or "无"}

解释：
{payload.get("explanation") or "无"}
"""
