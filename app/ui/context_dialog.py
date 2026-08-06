"""新建/编辑学习上下文的对话框：粘贴摘要 → 检测建议 → 保存并设为当前。

复用链路：
- 检测建议来自 `context_detector.suggest_context`（领域/场景/关键词）
- 背景要点可选由 `SummaryWorker` + `AIClient.generate_summary` 生成
- 保存走 `HistoryStore.save_context`，设为当前走 `SettingsService.set_current_context`
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app.services.context_detector import DOMAIN_KEYWORDS, SCENE_KEYWORDS, suggest_context
from app.services.history_store import HistoryStore
from app.services.settings import AppSettings, SettingsService
from app.ui.theme import FONT_BODY, FONT_HEADING, MUTED, TEXT_SECONDARY, apply_primary_button_style
from app.ui.workers import SummaryWorker


def _choice_items(keywords: dict[str, list[str]]) -> list[str]:
    items = ["通用", "其他"]
    items.extend(sorted(keywords.keys()))
    return items


class ContextEditDialog(QDialog):
    context_saved = Signal(int)

    def __init__(
        self,
        history_store: HistoryStore,
        settings_service: SettingsService,
        ai_settings: AppSettings,
        context_id: int | None = None,
        prefill_text: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.history_store = history_store
        self.settings_service = settings_service
        self.ai_settings = ai_settings
        self.context_id = context_id
        self._summary_worker: SummaryWorker | None = None
        self._auto_detected = False

        self.setWindowTitle("编辑学习上下文" if context_id else "新建学习上下文")
        self.setMinimumSize(580, 660)
        self._build_ui()
        if context_id is not None:
            self._auto_detected = True
            self._load_context(context_id)
        if prefill_text.strip():
            self.source_text.setPlainText(prefill_text)
            self._auto_detected = True
            self._apply_suggestion()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 16)
        layout.setSpacing(12)

        title = QLabel("学习上下文 = 领域 + 场景 + 背景要点")
        title.setStyleSheet(f"font-size:{FONT_HEADING};")
        layout.addWidget(title)

        source_title = QLabel("1. 粘贴外部摘要（可选，用于自动检测建议）")
        source_title.setStyleSheet(f"font-size:{FONT_BODY}; color:{TEXT_SECONDARY};")
        layout.addWidget(source_title)
        self.source_text = QPlainTextEdit()
        self.source_text.setPlaceholderText("粘贴论文摘要、文档说明等，会自动检测建议领域/场景/背景要点…")
        self.source_text.setMinimumHeight(160)
        self.source_text.textChanged.connect(self._maybe_auto_detect)
        layout.addWidget(self.source_text)

        hint_row = QHBoxLayout()
        hint_row.setSpacing(8)
        self.detect_button = QPushButton("检测建议")
        self.detect_button.clicked.connect(self._apply_suggestion)
        hint_row.addWidget(self.detect_button)
        self.summary_button = QPushButton("AI 生成背景要点")
        self.summary_button.clicked.connect(self._generate_summary)
        hint_row.addWidget(self.summary_button)
        hint_row.addStretch()
        self.summary_status = QLabel("")
        self.summary_status.setStyleSheet(f"color:{MUTED};")
        hint_row.addWidget(self.summary_status)
        layout.addLayout(hint_row)

        form = QVBoxLayout()
        form.setSpacing(8)

        self.domain_input = QComboBox()
        self.domain_input.setEditable(True)
        self.domain_input.addItems(_choice_items(DOMAIN_KEYWORDS))
        form.addLayout(_labeled("领域", self.domain_input))

        self.scene_input = QComboBox()
        self.scene_input.setEditable(True)
        self.scene_input.addItems(_choice_items(SCENE_KEYWORDS))
        form.addLayout(_labeled("场景", self.scene_input))

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("例如：生物 · 学术论文")
        form.addLayout(_labeled("名称", self.name_input))

        summary_title = QLabel("背景要点（注入提示词的内容，AI 解释会优先结合它）")
        summary_title.setStyleSheet(f"font-size:{FONT_BODY}; color:{TEXT_SECONDARY};")
        form.addWidget(summary_title)
        self.summary_input = QTextEdit()
        self.summary_input.setPlaceholderText("关键词或压缩后的背景要点，留空则按通用行为解释。")
        self.summary_input.setMinimumHeight(120)
        form.addWidget(self.summary_input)

        self.instruction_input = QLineEdit()
        self.instruction_input.setPlaceholderText("自定义说明（可选），例如：专业名词给中文对照")
        form.addLayout(_labeled("自定义说明", self.instruction_input))
        layout.addLayout(form)

        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        self.save_button = QPushButton("保存并设为当前")
        apply_primary_button_style(self.save_button)
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

    def _load_context(self, context_id: int) -> None:
        context = self.history_store.get_context(context_id)
        if context is None:
            return
        self.name_input.setText(context.name)
        self.domain_input.setCurrentText(context.domain)
        self.scene_input.setCurrentText(context.scene)
        self.summary_input.setPlainText(context.summary)
        self.instruction_input.setText(context.instruction)

    def _maybe_auto_detect(self) -> None:
        if self._auto_detected:
            return
        if len(self.source_text.toPlainText().strip()) >= 120:
            self._auto_detected = True
            self._apply_suggestion()

    def _apply_suggestion(self) -> None:
        text = self.source_text.toPlainText().strip()
        if not text:
            self.summary_status.setText("请先粘贴内容。")
            return
        suggestion = suggest_context(text)
        self.domain_input.setCurrentText(suggestion["domain"])
        self.scene_input.setCurrentText(suggestion["scene"])
        keywords = "、".join(suggestion["keywords"])
        if keywords and not self.summary_input.toPlainText().strip():
            self.summary_input.setPlainText(keywords)
        if not self.name_input.text().strip():
            domain = str(suggestion["domain"])
            scene = str(suggestion["scene"])
            if domain != "其他" and scene != "通用":
                self.name_input.setText(f"{domain} · {scene}")
            else:
                self.name_input.setText("新建上下文")
        self.summary_status.setText("已填入检测建议（可手动修改）。")

    def _generate_summary(self) -> None:
        text = self.source_text.toPlainText().strip()
        if not text:
            self.summary_status.setText("请先粘贴需要压缩的内容。")
            return
        if self._summary_worker and self._summary_worker.isRunning():
            return
        self.summary_button.setEnabled(False)
        self.summary_status.setText("生成中…")
        self._summary_worker = SummaryWorker(text, self.ai_settings)
        self._summary_worker.completed.connect(self._on_summary_done)
        self._summary_worker.finished.connect(self._summary_worker.deleteLater)
        self._summary_worker.start()

    def _on_summary_done(self, payload: dict) -> None:
        self.summary_button.setEnabled(True)
        if "error" in payload:
            self.summary_status.setText(str(payload["error"]))
            return
        summary = str(payload.get("summary") or "").strip()
        if summary:
            self.summary_input.setPlainText(summary)
            self.summary_status.setText("已生成背景要点。")
        else:
            self.summary_status.setText("未生成内容，可手动填写。")

    def _save(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            self.name_input.setFocus()
            self.summary_status.setText("请填写名称。")
            return
        domain = self.domain_input.currentText().strip() or "通用"
        scene = self.scene_input.currentText().strip() or "通用"
        summary = self.summary_input.toPlainText().strip()
        instruction = self.instruction_input.text().strip()

        if self.context_id is not None:
            context_id = self.history_store.save_context(
                name=name,
                domain=domain,
                scene=scene,
                summary=summary,
                instruction=instruction,
                context_id=self.context_id,
            )
        else:
            context_id = self.history_store.save_context(
                name=name,
                domain=domain,
                scene=scene,
                summary=summary,
                instruction=instruction,
            )
            self.settings_service.set_current_context(context_id)
        self.context_saved.emit(context_id)
        self.accept()


def _labeled(label: str, widget) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(8)
    text = QLabel(label)
    text.setFixedWidth(96)
    text.setStyleSheet(f"color:{TEXT_SECONDARY};")
    layout.addWidget(text)
    layout.addWidget(widget, 1)
    return layout
