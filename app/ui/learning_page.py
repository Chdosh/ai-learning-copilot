"""学习页：知识资产的行动入口（自沉淀 / 自学习闭环的 UI 侧）。

承载三个区块，全部由工作台迁入，让工作台回归"学习方向"单一职责：

- 今日复习：间隔重复到期队列入口；
- 学习建议：AI 建议清单，完成 / 忽略状态流转；
- 自沉淀：把最近学到的内容合并进当前学习方向的背景要点（预览确认，绝不静默改写）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.history_store import ContextRecord, HistoryStore, LearningTip
from app.services.knowledge_base import KnowledgeBase, TipQuery
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
from app.ui.workers import DigestWorker


def _card_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"color: {TEXT_SECONDARY}; background: transparent; border-left: 3px solid {PRIMARY}; "
        "padding-left: 8px;"
    )
    label.setFixedHeight(22)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return label


class SummaryPreviewDialog(QDialog):
    """沉淀预览：原要点与合并后要点并排，用户确认后才写入。"""

    def __init__(self, old_summary: str, new_summary: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("确认沉淀")
        self.setMinimumSize(560, 420)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        tip = QLabel("将把以下合并后的背景要点写入当前学习方向（原内容会被替换）：")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(tip)

        old_title = QLabel("当前背景要点")
        old_title.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        layout.addWidget(old_title)
        old_box = QTextEdit()
        old_box.setReadOnly(True)
        old_box.setPlainText(old_summary or "（空）")
        old_box.setMaximumHeight(84)
        layout.addWidget(old_box)

        new_title = QLabel("合并后的背景要点")
        new_title.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        layout.addWidget(new_title)
        new_box = QTextEdit()
        new_box.setReadOnly(True)
        new_box.setPlainText(new_summary)
        layout.addWidget(new_box, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("应用")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class LearningPage(QWidget):
    context_changed = Signal(object)

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
        self._digest_worker = None
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
        layout.addWidget(self._build_review_card())
        layout.addWidget(self._build_tips_card())
        layout.addWidget(self._build_digest_card())
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
            scope = str(self.tips_scope_combo.currentData() or "pending")
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

    # ---- 自沉淀：把最近内容合并进当前学习方向 ----

    def _build_digest_card(self) -> QFrame:
        card = self._build_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(_card_title("自沉淀"))
        hint = QLabel(
            "把最近学到的内容合并进当前学习方向的背景要点，让 AI 解释越用越懂你。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        layout.addWidget(hint)
        self.digest_button = QPushButton("把最近内容沉淀进当前方向")
        self.digest_button.setStyleSheet(button_qss())
        self.digest_button.setToolTip("合并后需人工确认才会写入，绝不静默修改")
        self.digest_button.clicked.connect(self._start_digest)
        layout.addWidget(self.digest_button)
        self.digest_status_label = QLabel("")
        self.digest_status_label.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        self.digest_status_label.setWordWrap(True)
        layout.addWidget(self.digest_status_label)
        return card

    def _current_context(self) -> ContextRecord | None:
        context_id = self.settings_service.load().current_context_id
        if context_id is None:
            return None
        record = self.history_store.get_context(context_id)
        if record is None or record.builtin:
            return None
        return record

    def _digest_cursor(self, context_id: int) -> int:
        raw = self.history_store.get_settings().get(f"digest_after_{context_id}", "")
        return int(raw) if str(raw).strip().isdigit() else 0

    def _set_digest_cursor(self, context_id: int, capture_id: int) -> None:
        self.history_store.set_setting(f"digest_after_{context_id}", str(capture_id))

    def _start_digest(self) -> None:
        context = self._current_context()
        if context is None:
            QMessageBox.information(
                self,
                "自沉淀",
                "请先在工作台新建或选择一个学习方向，才能把内容沉淀进它的背景要点。",
            )
            return
        domain = context.domain or "通用"
        captures = self.history_store.search_captures_advanced(domain=domain, limit=200)
        cursor = self._digest_cursor(context.id)
        new_captures = sorted(
            (capture for capture in captures if capture.id > cursor),
            key=lambda capture: capture.id,
        )[:15]
        if not new_captures:
            QMessageBox.information(self, "自沉淀", "当前方向暂无新内容可沉淀。")
            return
        items: list[str] = []
        for capture in new_captures:
            text = " ".join(
                part for part in (capture.translation, capture.explanation) if part
            )
            if text.strip():
                items.append(text.strip()[:300])
        if not items:
            QMessageBox.information(self, "自沉淀", "当前方向暂无新内容可沉淀。")
            return
        self.digest_status_label.setText(f"正在合并 {len(items)} 条新内容…")
        self.digest_button.setEnabled(False)
        self._digest_worker = DigestWorker(
            existing_summary=context.summary or "",
            new_items="\n".join(items),
            settings=self.settings_service.load(),
            last_capture_id=new_captures[-1].id,
        )
        self._digest_worker.completed.connect(self._on_digest_done)
        self._digest_worker.finished.connect(self._digest_worker.deleteLater)
        self._digest_worker.start()

    def _on_digest_done(self, payload: dict) -> None:
        self.digest_button.setEnabled(True)
        if payload.get("error"):
            self.digest_status_label.setText(str(payload["error"]))
            return
        merged = str(payload.get("summary") or "").strip()
        if not merged:
            self.digest_status_label.setText("生成失败：AI 未返回内容，背景要点未改动。")
            return
        context = self._current_context()
        if context is None:
            self.digest_status_label.setText("当前学习方向已变化，背景要点未改动。")
            return
        dialog = SummaryPreviewDialog(context.summary or "", merged, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.digest_status_label.setText("已取消，背景要点未改动。")
            return
        self.history_store.save_context(
            name=context.name,
            domain=context.domain or "通用",
            scene=context.scene or "通用",
            summary=merged,
            instruction=context.instruction or "",
            context_id=context.id,
        )
        self._set_digest_cursor(context.id, int(payload.get("last_capture_id") or 0))
        self.digest_status_label.setText("已沉淀到当前学习方向。")
        self.context_changed.emit(context.id)

    # ---- 刷新 ----

    def refresh(self) -> None:
        due = self.knowledge_base.count_due_terms()
        if due > 0:
            self.due_label.setText(f"{due} 个术语待复习")
            self.review_button.setText(f"开始复习 ({due})")
        else:
            self.due_label.setText("今天没有待复习的术语")
            self.review_button.setText("开始复习")
        self.refresh_tips()
