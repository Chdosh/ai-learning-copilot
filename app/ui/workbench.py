"""工作台：识别学习（截图/文本识别）+ 学习方向（预置方向一键切换）。

识别学习：把截图或粘贴文本交给 AI 按当前方向解释。
学习方向：决定按哪个领域解释，预置方向一键切换，或用摘要新建自定义方向。
查看/深入学习在"学习概览"页。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.context_detector import DOMAIN_KEYWORDS
from app.services.history_store import HistoryStore
from app.services.settings import SettingsService
from app.ui.theme import BG, BLUE, BORDER, MUTED

PRESET_DOMAINS = ["通用"] + list(DOMAIN_KEYWORDS.keys())

_DIRECTION_QSS = (
    f"QPushButton {{ border: 1px solid {BORDER}; border-radius: 16px; padding: 5px 14px; background: #fff; }}"
    f"QPushButton:hover {{ border-color: {BLUE}; }}"
    f"QPushButton:checked {{ background: {BLUE}; color: #fff; border-color: {BLUE}; }}"
)


class WorkbenchPage(QWidget):
    request_screenshot = Signal()
    text_learn = Signal(str)
    context_changed = Signal(object)
    open_summary_dialog = Signal()

    def __init__(
        self,
        history_store: HistoryStore,
        settings_service: SettingsService,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.history_store = history_store
        self.settings_service = settings_service
        self._direction_buttons: dict[str, QPushButton] = {}
        self._build_ui()
        self.refresh_directions()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(10)

        layout.addWidget(self._build_learn_card())
        layout.addWidget(self._build_direction_card())
        layout.addStretch(1)

        self.setStyleSheet(
            f"QWidget#workbenchCard {{ background: #ffffff; border: 1px solid {BORDER}; border-radius: 12px; }}"
        )

    def _build_learn_card(self) -> QWidget:
        card = QWidget()
        card.setObjectName("workbenchCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        layout.addWidget(QLabel("识别学习"))

        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)
        self.mode_screenshot_btn = QPushButton("截图识别")
        self.mode_text_btn = QPushButton("文本识别")
        for button in (self.mode_screenshot_btn, self.mode_text_btn):
            button.setCheckable(True)
            button.setStyleSheet(
                f"QPushButton {{ border: 1px solid {BORDER}; border-radius: 16px; padding: 3px 12px; background: #fff; }}"
                f"QPushButton:checked {{ background: {BLUE}; color: #fff; border-color: {BLUE}; }}"
            )
        self.mode_screenshot_btn.setChecked(True)
        self.mode_screenshot_btn.clicked.connect(lambda: self._switch_learn_mode(0))
        self.mode_text_btn.clicked.connect(lambda: self._switch_learn_mode(1))
        mode_row.addWidget(self.mode_screenshot_btn)
        mode_row.addWidget(self.mode_text_btn)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self.learn_stack = QStackedWidget()
        screenshot_page = QWidget()
        screenshot_layout = QHBoxLayout(screenshot_page)
        screenshot_layout.setContentsMargins(0, 0, 0, 0)
        screenshot_layout.addStretch(1)
        self.screenshot_button = QPushButton("开始截图翻译")
        self.screenshot_button.setFixedHeight(40)
        self.screenshot_button.setStyleSheet(
            f"background: {BLUE}; color: #fff; border: 0; border-radius: 8px; padding: 0 18px; "
        )
        self.screenshot_button.clicked.connect(self.request_screenshot)
        screenshot_layout.addWidget(self.screenshot_button)
        screenshot_layout.addStretch(1)
        self.learn_stack.addWidget(screenshot_page)

        text_page = QWidget()
        text_layout = QHBoxLayout(text_page)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(8)
        self.learn_text_input = QTextEdit()
        self.learn_text_input.setPlaceholderText("粘贴文本，走与截图相同的 AI 解释管线")
        self.learn_text_input.setFixedHeight(64)
        self.learn_text_input.setStyleSheet(
            f"padding: 8px 10px; border: 1px solid {BORDER}; border-radius: 8px; background: #fff;"
        )
        self.learn_button = QPushButton("学习")
        self.learn_button.setFixedWidth(72)
        self.learn_button.setStyleSheet(
            f"background: {BLUE}; color: #fff; border: 0; border-radius: 8px; "
        )
        self.learn_button.clicked.connect(self._submit_text_learn)
        text_layout.addWidget(self.learn_text_input, 1)
        text_layout.addWidget(self.learn_button)
        self.learn_stack.addWidget(text_page)
        layout.addWidget(self.learn_stack)
        return card

    def _build_direction_card(self) -> QWidget:
        card = QWidget()
        card.setObjectName("workbenchCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(QLabel("学习方向"))
        self.current_direction_label = QLabel("")
        self.current_direction_label.setStyleSheet(f"color: {MUTED};")
        header.addStretch(1)
        header.addWidget(self.current_direction_label)
        layout.addLayout(header)

        for row_domains in self._chunk(PRESET_DOMAINS, 5):
            row = QHBoxLayout()
            row.setSpacing(8)
            for domain in row_domains:
                button = QPushButton(domain)
                button.setCheckable(True)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setStyleSheet(_DIRECTION_QSS)
                button.clicked.connect(lambda checked=False, d=domain: self._switch_direction(d))
                self._direction_buttons[domain] = button
                row.addWidget(button)
            row.addStretch(1)
            layout.addLayout(row)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        summary_button = QPushButton("自定义方向")
        summary_button.setStyleSheet(
            f"QPushButton {{ border: 1px solid {BORDER}; border-radius: 8px; padding: 5px 12px; background: #fff; }}"
        )
        summary_button.clicked.connect(self.open_summary_dialog)
        footer.addWidget(summary_button)
        footer.addStretch(1)
        layout.addLayout(footer)

        self.context_detail_box = QTextEdit()
        self.context_detail_box.setReadOnly(True)
        self.context_detail_box.setPlaceholderText("当前方向详情（导入的摘要、背景要点会显示在这里）")
        self.context_detail_box.setMinimumHeight(96)
        self.context_detail_box.setStyleSheet(
            f"border: 1px solid {BORDER}; border-radius: 8px; padding: 6px; background: {BG};"
        )
        layout.addWidget(self.context_detail_box)
        return card

    @staticmethod
    def _chunk(items: list[str], size: int) -> list[list[str]]:
        return [items[index : index + size] for index in range(0, len(items), size)]

    def _switch_learn_mode(self, index: int) -> None:
        self.mode_screenshot_btn.setChecked(index == 0)
        self.mode_text_btn.setChecked(index == 1)
        self.learn_stack.setCurrentIndex(index)

    def _submit_text_learn(self) -> None:
        text = self.learn_text_input.toPlainText().strip()
        if not text:
            return
        self.learn_text_input.clear()
        self.text_learn.emit(text)

    def refresh_directions(self) -> None:
        settings = self.settings_service.load()
        current_id = settings.current_context_id
        current_domain = "通用"
        if current_id is not None:
            context = self.history_store.get_context(current_id)
            if context is not None and not context.builtin:
                current_domain = context.domain or "通用"
                lines = [
                    f"学习方向：{context.domain} · {context.name}",
                    f"场景：{context.scene}",
                ]
                if context.summary:
                    lines.append(f"背景要点：{context.summary}")
                if context.instruction:
                    lines.append(f"自定义说明：{context.instruction}")
                self.context_detail_box.setPlainText("\n".join(lines))
            else:
                self.context_detail_box.setPlainText("学习方向：通用（不限制解释领域）")
        else:
            self.context_detail_box.setPlainText("学习方向：通用（不限制解释领域）")
        for domain, button in self._direction_buttons.items():
            button.setChecked(domain == current_domain)
        self.current_direction_label.setText(f"当前：{current_domain}")

    def _switch_direction(self, domain: str) -> None:
        if domain == "通用":
            self.settings_service.set_current_context(None)
            context_id = None
        else:
            target = None
            for context in self.history_store.list_contexts():
                if not context.builtin and context.domain == domain:
                    target = context.id
                    break
            if target is None:
                target = self.history_store.save_context(name=domain, domain=domain, scene="通用")
            self.settings_service.set_current_context(target)
            context_id = target
        self.context_changed.emit(context_id)
        self.refresh_directions()
