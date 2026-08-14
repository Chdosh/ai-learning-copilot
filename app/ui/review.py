"""间隔重复复习卡片：三档评分（忘了 / 模糊 / 记得），SM-2 简化调度。

复习队列 = 已收藏且到期的术语；评分后由 HistoryStore.review_term 更新
间隔 / 难易度 / 下次到期时间，全部本地 SQLite，无外部依赖。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.history_store import TermRecord
from app.services.knowledge_base import KnowledgeBase
from app.ui.theme import (
    BORDER,
    CARD,
    DANGER,
    DANGER_BORDER,
    MUTED,
    PRIMARY,
    RADIUS_LG,
    SUCCESS,
    TEXT,
    TEXT_SECONDARY,
    apply_primary_button_style,
    button_qss,
)

_GRADE_STYLES = {
    "forgot": f"""
        QPushButton {{ background: #ffffff; border: 1px solid {DANGER_BORDER}; border-radius: 8px;
                      padding: 8px 14px; color: {DANGER}; }}
        QPushButton:hover {{ background: #FFF5F5; }}
    """,
    "fuzzy": button_qss(),
    "remember": f"""
        QPushButton {{ background: #ffffff; border: 1px solid #BBF7D0; border-radius: 8px;
                      padding: 8px 14px; color: {SUCCESS}; }}
        QPushButton:hover {{ background: #F0FDF4; }}
    """,
}


class ReviewDialog(QDialog):
    """One term at a time: front shows the term, reveal shows the answer."""

    def __init__(self, knowledge_base: KnowledgeBase, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.knowledge_base = knowledge_base
        self.setWindowTitle("今日复习")
        self.setMinimumSize(480, 400)
        self._queue = knowledge_base.list_due_terms(limit=100)
        self._index = 0
        self._reviewed = 0
        self._current: TermRecord | None = None
        self._build_ui()
        self._show_current()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        self.progress_label = QLabel("")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_label.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        layout.addWidget(self.progress_label)

        card = QFrame()
        card.setObjectName("reviewCard")
        card.setStyleSheet(
            f"QFrame#reviewCard {{ background: {CARD}; border: 1px solid {BORDER}; "
            f"border-radius: {RADIUS_LG}; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        card_layout.setSpacing(10)

        self.term_label = QLabel("")
        self.term_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.term_label.setWordWrap(True)
        self.term_label.setStyleSheet(f"font-size: 22px; color: {TEXT}; font-weight: 600;")
        card_layout.addWidget(self.term_label)

        self.domain_label = QLabel("")
        self.domain_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.domain_label.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        card_layout.addWidget(self.domain_label)

        self.answer_panel = QWidget()
        answer_layout = QVBoxLayout(self.answer_panel)
        answer_layout.setContentsMargins(0, 8, 0, 0)
        answer_layout.setSpacing(6)
        self.chinese_label = QLabel("")
        self.chinese_label.setWordWrap(True)
        self.chinese_label.setStyleSheet(f"color: {TEXT}; font-size: 14px;")
        answer_layout.addWidget(self.chinese_label)
        self.explanation_label = QLabel("")
        self.explanation_label.setWordWrap(True)
        self.explanation_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
        answer_layout.addWidget(self.explanation_label)
        self.example_label = QLabel("")
        self.example_label.setWordWrap(True)
        self.example_label.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        answer_layout.addWidget(self.example_label)
        self.answer_panel.hide()
        card_layout.addWidget(self.answer_panel)
        card_layout.addStretch(1)
        layout.addWidget(card, 1)

        self.reveal_button = QPushButton("显示答案")
        apply_primary_button_style(self.reveal_button)
        self.reveal_button.clicked.connect(self._reveal)
        layout.addWidget(self.reveal_button)

        grade_row = QHBoxLayout()
        grade_row.setSpacing(8)
        self.forgot_button = QPushButton("忘了")
        self.fuzzy_button = QPushButton("模糊")
        self.remember_button = QPushButton("记得")
        self.forgot_button.setStyleSheet(_GRADE_STYLES["forgot"])
        self.fuzzy_button.setStyleSheet(_GRADE_STYLES["fuzzy"])
        self.remember_button.setStyleSheet(_GRADE_STYLES["remember"])
        self.forgot_button.clicked.connect(lambda: self._grade(0))
        self.fuzzy_button.clicked.connect(lambda: self._grade(1))
        self.remember_button.clicked.connect(lambda: self._grade(2))
        for button in (self.forgot_button, self.fuzzy_button, self.remember_button):
            button.setMinimumHeight(36)
            grade_row.addWidget(button, 1)
        layout.addLayout(grade_row)

    def _show_current(self) -> None:
        if self._index >= len(self._queue):
            self._finish()
            return
        term = self._queue[self._index]
        self._current = term
        self.progress_label.setText(
            f"{self._index + 1} / {len(self._queue)}　·　已复习 {self._reviewed}"
        )
        self.term_label.setText(term.term)
        self.domain_label.setText(f"{term.domain or '通用'} · 已出现 {term.occurrences or term.review_count} 次")
        self.chinese_label.setText(f"中文名：{term.chinese_name or '—'}")
        self.explanation_label.setText(term.beginner_explanation or "无解释")
        examples = "；".join(term.examples) if term.examples else ""
        self.example_label.setText(f"例子：{examples}" if examples else "")
        self.answer_panel.hide()
        self.reveal_button.setVisible(True)
        self._set_grade_enabled(False)

    def _reveal(self) -> None:
        self.answer_panel.show()
        self.reveal_button.setVisible(False)
        self._set_grade_enabled(True)

    def _grade(self, grade: int) -> None:
        if self._current is None:
            return
        self.knowledge_base.review(self._current.id, grade)
        self._reviewed += 1
        self._index += 1
        self._show_current()

    def _set_grade_enabled(self, enabled: bool) -> None:
        for button in (self.forgot_button, self.fuzzy_button, self.remember_button):
            button.setEnabled(enabled)

    def _finish(self) -> None:
        if self._reviewed > 0:
            self.progress_label.setText(f"今日复习完成，共复习 {self._reviewed} 个术语。")
        else:
            self.progress_label.setText("今天没有待复习的术语。收藏术语后会按遗忘曲线安排复习。")
        self.term_label.setText("🎉")
        self.term_label.setStyleSheet(f"font-size: 28px; color: {PRIMARY};")
        self.domain_label.setText("")
        self.answer_panel.hide()
        self.reveal_button.setText("关闭")
        self.reveal_button.setVisible(True)
        try:
            self.reveal_button.clicked.disconnect()
        except RuntimeError:
            pass
        self.reveal_button.clicked.connect(self.accept)
        self._set_grade_enabled(False)
