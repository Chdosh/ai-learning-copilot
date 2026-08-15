"""学习页：个人知识沉淀的行动入口。

承载三个区块（知识资产的 UI 侧）：

- 知识积累：最近进入知识库的术语、真实来源与方向理由；
- 今日复习：间隔重复到期队列入口；
- 学习建议：AI 建议清单，完成 / 忽略状态流转。

沉淀方向：AI 产出的知识只进入术语本与学习建议（个人知识库），
绝不写回学习方向——方向只负责截图识别与解释口径。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services.history_store import HistoryStore, LearningTip
from app.services.knowledge_base import (
    AccumulationItem,
    AccumulationQuery,
    KnowledgeBase,
    TipQuery,
)
from app.services.settings import SettingsService
from app.ui.review import ReviewDialog
from app.ui.theme import (
    BORDER,
    CARD,
    ChevronComboBox,
    FONT_MICRO,
    MUTED,
    PRIMARY,
    RADIUS_LG,
    RADIUS_MD,
    TEXT,
    TEXT_SECONDARY,
    apply_primary_button_style,
    button_qss,
)


def _card_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"color: {TEXT_SECONDARY}; background: transparent; border-left: 3px solid {PRIMARY}; "
        "padding-left: 8px;"
    )
    label.setFixedHeight(22)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return label


class LearningPage(QWidget):
    context_changed = Signal(object)
    capture_selected = Signal(int)

    def __init__(
        self,
        history_store: HistoryStore,
        settings_service: SettingsService,
        knowledge_base: KnowledgeBase,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.history_store = history_store
        self.settings_service = settings_service
        self.knowledge_base = knowledge_base
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        centered = QWidget()
        centered_layout = QHBoxLayout(centered)
        centered_layout.setContentsMargins(20, 16, 20, 16)
        centered_layout.addStretch(1)
        content = QWidget()
        content.setMaximumWidth(640)
        centered_layout.addWidget(content)
        centered_layout.addStretch(1)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.content_layout = layout
        self.accumulation_card = self._build_accumulation_card()
        self.review_card = self._build_review_card()
        self.tips_card = self._build_tips_card()
        layout.addWidget(self.accumulation_card)
        layout.addWidget(self.review_card)
        layout.addWidget(self.tips_card)
        layout.addStretch(1)
        scroll.setWidget(centered)
        outer.addWidget(scroll)

    def _build_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("learningCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(
            f"QFrame#learningCard {{ background: {CARD}; border: 1px solid {BORDER}; "
            f"border-radius: {RADIUS_LG}; }}"
        )
        return card

    # ---- 最近知识积累 ----

    def _build_accumulation_card(self) -> QFrame:
        card = self._build_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(_card_title("知识积累"))

        summary = QLabel("最近从截图与追问中进入个人知识库的内容")
        summary.setStyleSheet(
            f"color: {MUTED}; font-size: {FONT_MICRO}; background: transparent;"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        self.accumulation_list = QWidget()
        self.accumulation_list_layout = QVBoxLayout(self.accumulation_list)
        self.accumulation_list_layout.setContentsMargins(0, 0, 0, 0)
        self.accumulation_list_layout.setSpacing(6)
        layout.addWidget(self.accumulation_list)
        return card

    def refresh_accumulation(self) -> None:
        current_context_id, effective_domain = self._current_direction_facts()
        page = self.knowledge_base.query_accumulation(
            AccumulationQuery(
                limit=20,
                current_context_id=current_context_id,
                effective_domain=effective_domain,
            )
        )
        while self.accumulation_list_layout.count():
            item = self.accumulation_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not page.items:
            empty = QLabel("暂无知识积累。完成截图学习后，术语和真实来源会显示在这里。")
            empty.setStyleSheet(
                f"color: {MUTED}; font-size: {FONT_MICRO}; background: transparent;"
            )
            empty.setWordWrap(True)
            self.accumulation_list_layout.addWidget(empty)
            return
        for item in page.items:
            self.accumulation_list_layout.addWidget(self._build_accumulation_row(item))

    def _current_direction_facts(self) -> tuple[int | None, str]:
        settings = self.settings_service.load()
        context_id = settings.current_context_id
        if context_id is not None:
            context = self.history_store.get_context(context_id)
            if context is not None and not context.builtin:
                return context_id, context.domain or "通用"
        domain, _scene = self.settings_service.get_quick_context()
        return None, domain or "通用"

    def _build_accumulation_row(self, item: AccumulationItem) -> QWidget:
        row = QFrame()
        row.setObjectName("accumulationRow")
        row.setStyleSheet(
            f"QFrame#accumulationRow {{ background: {CARD}; border: 1px solid {BORDER}; "
            f"border-radius: {RADIUS_MD}; }}"
        )
        box = QVBoxLayout(row)
        box.setContentsMargins(10, 9, 10, 9)
        box.setSpacing(5)

        names = [item.term.term.strip(), item.term.chinese_name.strip()]
        title = QLabel(" · ".join(name for name in names if name))
        title.setStyleSheet(
            f"color: {TEXT}; font-size: 14px; font-weight: 600; background: transparent;"
        )
        title.setWordWrap(True)
        box.addWidget(title)

        explanation_text = item.term.beginner_explanation.strip()
        if explanation_text:
            explanation = QLabel(explanation_text)
            explanation.setStyleSheet(
                f"color: {TEXT_SECONDARY}; font-size: 13px; background: transparent;"
            )
            explanation.setWordWrap(True)
            box.addWidget(explanation)

        captured_at = item.latest_capture_at.replace("T", " ")[:16]
        meta = QLabel(
            f"{item.term.domain or '通用'} · 积累于 {captured_at} · {item.source_count} 条来源"
        )
        meta.setStyleSheet(
            f"color: {MUTED}; font-size: {FONT_MICRO}; background: transparent;"
        )
        box.addWidget(meta)

        reason = QLabel(" · ".join(item.reasons))
        reason.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: {FONT_MICRO}; background: transparent;"
        )
        reason.setWordWrap(True)
        box.addWidget(reason)

        source_title = " ".join(item.latest_capture_title.split())
        if len(source_title) > 72:
            source_title = f"{source_title[:71]}…"
        source_button = QPushButton(
            f"来源：{source_title}" if source_title else "查看原学习记录"
        )
        source_button.setProperty("capture_id", item.latest_capture_id)
        source_button.setToolTip("回到这条知识最近出现的学习记录")
        source_button.setStyleSheet(button_qss())
        source_button.clicked.connect(
            lambda checked=False, capture_id=item.latest_capture_id: (
                self.capture_selected.emit(capture_id)
            )
        )
        box.addWidget(source_button)
        return row

    # ---- 今日复习 ----

    def _build_review_card(self) -> QFrame:
        card = self._build_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(_card_title("今日复习"))

        row = QHBoxLayout()
        row.setSpacing(10)
        self.due_label = QLabel("0 个术语待复习")
        self.due_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
        row.addWidget(self.due_label, 1)
        self.review_button = QPushButton("开始复习")
        apply_primary_button_style(self.review_button)
        self.review_button.clicked.connect(self._open_review)
        row.addWidget(self.review_button)
        layout.addLayout(row)
        return card

    def _open_review(self) -> None:
        dialog = ReviewDialog(self.knowledge_base, self)
        dialog.exec()
        self.refresh()

    # ---- 学习建议清单（自沉淀：AI 建议 → 状态流转） ----

    def _build_tips_card(self) -> QFrame:
        card = self._build_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(_card_title("学习建议"))
        header.addStretch(1)
        self.tips_scope_combo = ChevronComboBox()
        self.tips_scope_combo.addItem("待处理", "pending")
        self.tips_scope_combo.addItem("已完成", "done")
        self.tips_scope_combo.addItem("全部", "")
        self.tips_scope_combo.setFixedWidth(88)
        self.tips_scope_combo.setToolTip("按状态筛选建议")
        self.tips_scope_combo.currentIndexChanged.connect(self.refresh_tips)
        header.addWidget(self.tips_scope_combo)
        layout.addLayout(header)

        self.tips_list = QWidget()
        self.tips_list_layout = QVBoxLayout(self.tips_list)
        self.tips_list_layout.setContentsMargins(0, 0, 0, 0)
        self.tips_list_layout.setSpacing(6)
        layout.addWidget(self.tips_list)
        return card

    def refresh_tips(self) -> None:
        scope = "pending"
        if hasattr(self, "tips_scope_combo"):
            selected_scope = self.tips_scope_combo.currentData()
            scope = "pending" if selected_scope is None else str(selected_scope)
        tips = self.knowledge_base.list_tips(TipQuery(status=scope, limit=60))
        while self.tips_list_layout.count():
            item = self.tips_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not tips:
            empty = QLabel("暂无学习建议。截图解释给出的建议会自动沉淀到这里。")
            empty.setStyleSheet(
                f"color: {MUTED}; font-size: {FONT_MICRO}; background: transparent;"
            )
            empty.setWordWrap(True)
            self.tips_list_layout.addWidget(empty)
            return
        for tip in tips:
            self.tips_list_layout.addWidget(self._build_tip_row(tip))

    def _build_tip_row(self, tip: LearningTip) -> QWidget:
        row = QFrame()
        row.setObjectName("tipRow")
        row.setStyleSheet(
            f"QFrame#tipRow {{ background: {CARD}; border: 1px solid {BORDER}; "
            f"border-radius: {RADIUS_MD}; }}"
        )
        box = QVBoxLayout(row)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(6)

        content = QLabel(tip.content)
        content.setWordWrap(True)
        content.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 13px; background: transparent;"
        )
        box.addWidget(content)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)
        meta = QLabel(f"{tip.domain or '通用'} · {tip.created_at.replace('T', ' ')[:16]}")
        meta.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO}; background: transparent;")
        meta_row.addWidget(meta)
        meta_row.addStretch(1)
        if tip.status == "pending":
            done_button = QPushButton("完成")
            done_button.setStyleSheet(button_qss())
            done_button.clicked.connect(
                lambda checked=False, t=tip.id: self._set_tip_status(t, "done")
            )
            ignore_button = QPushButton("忽略")
            ignore_button.setStyleSheet(button_qss())
            ignore_button.clicked.connect(
                lambda checked=False, t=tip.id: self._set_tip_status(t, "ignored")
            )
            meta_row.addWidget(done_button)
            meta_row.addWidget(ignore_button)
        box.addLayout(meta_row)
        return row

    def _set_tip_status(self, tip_id: int, status: str) -> None:
        self.knowledge_base.set_tip_status(tip_id, status)
        self.refresh_tips()

    # ---- 刷新 ----

    def refresh(self) -> None:
        self.refresh_accumulation()
        due = self.knowledge_base.count_due_terms()
        if due > 0:
            self.due_label.setText(f"{due} 个术语待复习")
            self.review_button.setText(f"开始复习 ({due})")
        else:
            self.due_label.setText("今天没有待复习的术语")
            self.review_button.setText("开始复习")
        self.refresh_tips()
