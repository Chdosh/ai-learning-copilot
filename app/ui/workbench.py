"""工作台：学习方向（精简版）。

单一职责：选择 / 创建 / 编辑学习方向。知识资产（今日复习、学习建议）
已迁移至学习页。

设计要点：
- 领域 / 场景可直接输入（输入即自定义，不再有隐藏的"自定义…"组合）；
- 应用为当前方向 = 临时生效（不落库）；保存为新方向 = 落库并可复用；
- 已保存方向列表：点击切换，行内使用 / 编辑 / 删除；
- 摘要分析结果先预览（含命中依据），确认后才填入表单——自动补充必须人工验证；
- 数据错位整理仅在检测到异常时出现提示。
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.paths import DATA_DIR
from app.services.context_detector import (
    DOMAIN_KEYWORDS,
    SCENE_KEYWORDS,
    detect,
    extract_keywords,
)
from app.services.history_store import ContextRecord, HistoryStore
from app.services.settings import SettingsService
from app.ui.theme import (
    ArrowSendButton,
    BORDER,
    BORDER_LIGHT,
    CARD,
    DANGER,
    DISABLED,
    FONT_MICRO,
    MUTED,
    PRIMARY,
    PRIMARY_DARK,
    PRIMARY_SOFT,
    RADIUS_LG,
    RADIUS_MD,
    TEXT,
    TEXT_SECONDARY,
    apply_primary_button_style,
    button_qss,
)

PRESET_DOMAINS = ["通用"] + list(DOMAIN_KEYWORDS.keys())
PRESET_SCENES = ["通用", "其他"] + sorted(SCENE_KEYWORDS.keys())


def _direction_name(domain: str, scene: str) -> str:
    """已保存方向的名称由领域/场景派生，保存时永远重新生成，不再保留旧名。"""
    return f"{domain} · {scene}" if scene != "通用" else domain


def _record_display(record: ContextRecord | None) -> str:
    if record is None:
        return "通用"
    return (record.name or "").strip() or _direction_name(
        record.domain or "通用", record.scene or "通用"
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


class DirectionRepairDialog(QDialog):
    """错位方向整理预览：逐条勾选，应用前先备份，绝不静默改数据。"""

    def __init__(self, rows: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("整理学习方向")
        self.setMinimumWidth(620)
        self.rows = rows

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        tip = QLabel("以下记录的名称与领域/场景不一致，按「名称优先、场景保留」修复，可逐条取消勾选：")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(tip)

        self.checkboxes: list[QCheckBox] = []
        for item in rows:
            record = item["record"]
            checkbox = QCheckBox(
                f"当前：{record.name} ｜ 领域 {record.domain or '通用'} ｜ 场景 {record.scene or '通用'}\n"
                f"修复：领域 {item['domain']} ｜ 场景 {item['scene']}"
                f" ｜ 名称 {_direction_name(item['domain'], item['scene'])}"
            )
            checkbox.setChecked(True)
            self.checkboxes.append(checkbox)
            layout.addWidget(checkbox)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("应用修复（先备份）")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_rows(self) -> list[dict]:
        return [
            self.rows[i] for i, checkbox in enumerate(self.checkboxes) if checkbox.isChecked()
        ]


class DirectionAnalysisPreviewDialog(QDialog):
    """摘要分析预览：显示识别依据，用户确认后才填入表单。"""

    def __init__(
        self,
        domain: str,
        scene: str,
        keywords: list[str],
        summary_preview: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("分析结果预览")
        self.setMinimumWidth(520)
        self._apply_requested = False

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(_card_title("识别到以下学习方向，确认后填入表单："))

        info = QLabel(
            f"领域：{domain}\n场景：{scene}\n"
            f"命中关键词：{'、'.join(keywords) if keywords else '（无）'}"
        )
        info.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
        layout.addWidget(info)

        summary_title = QLabel("建议背景要点")
        summary_title.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        layout.addWidget(summary_title)
        summary_box = QTextEdit()
        summary_box.setReadOnly(True)
        summary_box.setPlainText(summary_preview)
        summary_box.setMinimumHeight(120)
        layout.addWidget(summary_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("填入表单")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept_apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_apply(self) -> None:
        self._apply_requested = True
        self.accept()

    def apply_requested(self) -> bool:
        return self._apply_requested


_ROW_BUTTON_QSS = f"""
QPushButton {{
    background: transparent;
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD};
    min-width: 36px;
    min-height: 22px;
    padding: 2px 8px;
    color: {TEXT_SECONDARY};
    font-size: 13px;
}}
QPushButton:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; }}
QPushButton:pressed {{ background: {PRIMARY_SOFT}; }}
"""


class WorkbenchPage(QWidget):
    context_changed = Signal(object)

    def __init__(
        self,
        history_store: HistoryStore,
        settings_service: SettingsService,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.history_store = history_store
        self.settings_service = settings_service
        self._editing_context_id: int | None = None
        self._build_ui()
        self.refresh_directions(force=True)

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
        columns = QVBoxLayout(content)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(12)

        card = self._build_card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 16)
        card_layout.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        header_row.addWidget(_card_title("学习方向"))
        header_row.addStretch(1)
        self.direction_status_label = QLabel("当前生效：通用（临时）")
        self.direction_status_label.setStyleSheet(f"color: {MUTED}; font-size: 13px;")
        header_row.addWidget(self.direction_status_label)
        self.reset_direction_button = QPushButton("恢复通用")
        self.reset_direction_button.setStyleSheet(button_qss())
        self.reset_direction_button.setToolTip("清空当前方向，回到通用解释")
        self.reset_direction_button.clicked.connect(self._reset_direction)
        header_row.addWidget(self.reset_direction_button)
        card_layout.addLayout(header_row)

        form_row = QHBoxLayout()
        form_row.setSpacing(12)
        domain_column = QWidget()
        domain_layout = QVBoxLayout(domain_column)
        domain_layout.setContentsMargins(0, 0, 0, 0)
        domain_layout.setSpacing(4)
        domain_title = QLabel("领域")
        domain_title.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        domain_layout.addWidget(domain_title)
        self.domain_combo = self._build_editable_combo(PRESET_DOMAINS, "领域可直接输入自定义值")
        self.domain_combo.setMinimumWidth(180)
        self.domain_combo.setMaximumWidth(220)
        self.domain_combo.currentTextChanged.connect(self._on_form_edited)
        domain_layout.addWidget(self.domain_combo)
        form_row.addWidget(domain_column)
        form_row.addStretch(1)

        scene_column = QWidget()
        scene_layout = QVBoxLayout(scene_column)
        scene_layout.setContentsMargins(0, 0, 0, 0)
        scene_layout.setSpacing(4)
        scene_title = QLabel("场景")
        scene_title.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        scene_layout.addWidget(scene_title)
        self.scene_combo = self._build_editable_combo(PRESET_SCENES, "场景可直接输入自定义值")
        self.scene_combo.setMinimumWidth(180)
        self.scene_combo.setMaximumWidth(220)
        self.scene_combo.currentTextChanged.connect(self._on_form_edited)
        scene_layout.addWidget(self.scene_combo)
        form_row.addWidget(scene_column)
        card_layout.addLayout(form_row)

        self.advanced_toggle = QPushButton("高级选项")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setStyleSheet(button_qss())
        self.advanced_toggle.setToolTip("方向名称 / 摘要分析 / 背景要点 / 回答偏好")
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        card_layout.addWidget(self.advanced_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self.advanced_panel = QWidget()
        self.advanced_panel.setObjectName("advancedPanel")
        self.advanced_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.advanced_panel.setStyleSheet(
            f"QWidget#advancedPanel {{ background: {CARD}; }}"
        )
        advanced_layout = QVBoxLayout(self.advanced_panel)
        advanced_layout.setContentsMargins(0, 2, 0, 0)
        advanced_layout.setSpacing(8)

        name_title = QLabel("方向名称（可选）")
        name_title.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        advanced_layout.addWidget(name_title)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("留空时自动使用“领域 · 场景”")
        self.name_input.setFixedHeight(32)
        self.name_input.textChanged.connect(self._on_form_edited)
        advanced_layout.addWidget(self.name_input)

        source_title = QLabel("论文摘要 / 内容概述（自动分析领域与背景）")
        source_title.setStyleSheet(f"color: {TEXT_SECONDARY};")
        advanced_layout.addWidget(source_title)
        source_composer = QFrame()
        source_composer.setObjectName("sourceComposer")
        source_composer.setStyleSheet(
            f"QFrame#sourceComposer {{ background: {CARD}; border: 1px solid {BORDER}; "
            f"border-radius: {RADIUS_LG}; }}"
        )
        composer_layout = QHBoxLayout(source_composer)
        composer_layout.setContentsMargins(8, 8, 8, 8)
        composer_layout.setSpacing(8)
        self.context_source_input = QTextEdit()
        self.context_source_input.setPlaceholderText(
            "粘贴论文摘要或专业内容概述，用于推荐领域、场景并提取回答上下文"
        )
        self.context_source_input.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.context_source_input.setStyleSheet(
            "QTextEdit { border: none; background: transparent; padding: 4px 8px; "
            "selection-background-color: #EFF4FF; }"
        )
        self.context_source_input.setFixedHeight(64)
        self.context_source_input.textChanged.connect(self._update_analyze_button_state)
        composer_layout.addWidget(self.context_source_input, 1)
        self.analyze_context_button = ArrowSendButton()
        self.analyze_context_button.setStyleSheet(
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
        self.analyze_context_button.setProperty("active", False)
        self.analyze_context_button.setToolTip("分析摘要，预览确认后填入领域、场景与背景")
        self.analyze_context_button.clicked.connect(self._analyze_context_source)
        composer_layout.addWidget(
            self.analyze_context_button, 0, Qt.AlignmentFlag.AlignBottom
        )
        advanced_layout.addWidget(source_composer)
        self.context_analysis_label = QLabel("")
        self.context_analysis_label.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        self.context_analysis_label.setWordWrap(True)
        advanced_layout.addWidget(self.context_analysis_label)

        summary_title = QLabel("提取后的关键背景（会加入每次提问前）")
        summary_title.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        advanced_layout.addWidget(summary_title)
        self.summary_input = QTextEdit()
        self.summary_input.setPlaceholderText("AI 会结合这些信息理解截图或文本，留空则按通用行为解释。")
        self.summary_input.setFixedHeight(58)
        self.summary_input.textChanged.connect(self._on_form_edited)
        advanced_layout.addWidget(self.summary_input)

        instruction_title = QLabel("回答偏好")
        instruction_title.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        advanced_layout.addWidget(instruction_title)
        self.instruction_input = QLineEdit()
        self.instruction_input.setPlaceholderText("例如：专业术语附中文解释；长句分步骤说明")
        self.instruction_input.setFixedHeight(32)
        self.instruction_input.textChanged.connect(self._on_form_edited)
        advanced_layout.addWidget(self.instruction_input)

        self.advanced_panel.setVisible(False)
        card_layout.addWidget(self.advanced_panel)

        self.draft_warning_label = QLabel("有未保存修改，不会用于下一次识别")
        self.draft_warning_label.setStyleSheet(f"color: {DANGER}; font-size: {FONT_MICRO};")
        self.draft_warning_label.setVisible(False)
        card_layout.addWidget(self.draft_warning_label)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        self.apply_direction_button = QPushButton("应用为当前方向")
        apply_primary_button_style(self.apply_direction_button)
        self.apply_direction_button.clicked.connect(self._apply_direction)
        actions_row.addWidget(self.apply_direction_button)
        self.save_as_new_button = QPushButton("保存为新方向")
        self.save_as_new_button.setStyleSheet(button_qss())
        self.save_as_new_button.setToolTip("保存到“已保存的方向”，以后可一键切换")
        self.save_as_new_button.clicked.connect(self._save_as_new)
        actions_row.addWidget(self.save_as_new_button)
        self.cancel_edit_button = QPushButton("取消")
        self.cancel_edit_button.setStyleSheet(button_qss())
        self.cancel_edit_button.clicked.connect(self._cancel_edit)
        self.cancel_edit_button.setVisible(False)
        actions_row.addWidget(self.cancel_edit_button)
        actions_row.addStretch(1)
        card_layout.addLayout(actions_row)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(f"color: {BORDER};")
        card_layout.addWidget(separator)

        saved_title = QLabel("已保存的方向")
        saved_title.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 600;")
        card_layout.addWidget(saved_title)
        self.direction_list = QListWidget()
        self.direction_list.setObjectName("directionList")
        self.direction_list.setFrameShape(QFrame.Shape.NoFrame)
        self.direction_list.setStyleSheet(
            f"""
            QListWidget#directionList {{ background: transparent; border: none; outline: 0; }}
            QListWidget#directionList::item {{
                background: transparent;
                border: none;
                padding: 0;
            }}
            QListWidget#directionList::item:selected {{ background: {PRIMARY_SOFT}; border-radius: 6px; }}
            """
        )
        self.direction_list.setMaximumHeight(180)
        self.direction_list.itemClicked.connect(self._on_direction_item_clicked)
        card_layout.addWidget(self.direction_list)

        repair_row = QHBoxLayout()
        repair_row.setSpacing(8)
        self.repair_notice_label = QLabel("")
        self.repair_notice_label.setStyleSheet(f"color: {DANGER}; font-size: {FONT_MICRO};")
        self.repair_notice_label.setWordWrap(True)
        self.repair_button = QPushButton("整理")
        self.repair_button.setStyleSheet(button_qss())
        self.repair_button.clicked.connect(self._repair_directions)
        self.repair_button.setVisible(False)
        repair_row.addWidget(self.repair_notice_label, 1)
        repair_row.addWidget(self.repair_button)
        card_layout.addLayout(repair_row)

        columns.addWidget(card, 1)
        scroll.setWidget(centered)
        outer.addWidget(scroll)

    def _build_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("workbenchCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(
            f"QFrame#workbenchCard {{ background: {CARD}; border: 1px solid {BORDER}; "
            f"border-radius: {RADIUS_LG}; }}"
        )
        return card

    @staticmethod
    def _build_editable_combo(presets: list[str], tooltip: str) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.addItems(presets)
        combo.setMinimumHeight(32)
        combo.setToolTip(tooltip)
        return combo

    def _toggle_advanced(self, checked: bool) -> None:
        self.advanced_panel.setVisible(checked)
        self.advanced_toggle.setText("收起高级选项" if checked else "高级选项")

    # ---- 表单值 ----

    def _form_values(self) -> tuple[str, str, str, str, str]:
        name = self.name_input.text().strip()
        domain = self.domain_combo.currentText().strip() or "通用"
        scene = self.scene_combo.currentText().strip() or "通用"
        summary = self.summary_input.toPlainText().strip()
        instruction = self.instruction_input.text().strip()
        return name, domain, scene, summary, instruction

    def _resolved_form_name(self, domain: str, scene: str) -> str:
        typed = self.name_input.text().strip()
        if not typed:
            return _direction_name(domain, scene)
        if self._editing_context_id is not None:
            record = self.history_store.get_context(self._editing_context_id)
            if record is not None and typed == (record.name or ""):
                old_derived = _direction_name(record.domain or "通用", record.scene or "通用")
                if typed == old_derived:
                    return _direction_name(domain, scene)
        return typed

    def _form_dirty(self) -> bool:
        return self._form_values() != self._base_values()

    def _base_values(self) -> tuple[str, str, str, str, str]:
        if self._editing_context_id is not None:
            record = self.history_store.get_context(self._editing_context_id)
            if record is not None:
                return (
                    record.name or "",
                    record.domain or "通用",
                    record.scene or "通用",
                    record.summary or "",
                    record.instruction or "",
                )
        current = self._current_context()
        if current is not None:
            return (
                current.name or "",
                current.domain or "通用",
                current.scene or "通用",
                current.summary or "",
                current.instruction or "",
            )
        quick_domain, quick_scene = self.settings_service.get_quick_context()
        return ("", quick_domain, quick_scene, "", "")

    def _on_form_edited(self, *args) -> None:
        self.draft_warning_label.setVisible(self._form_dirty())

    def _update_analyze_button_state(self, *args) -> None:
        active = bool(self.context_source_input.toPlainText().strip())
        self.analyze_context_button.setProperty("active", active)
        self.analyze_context_button.style().unpolish(self.analyze_context_button)
        self.analyze_context_button.style().polish(self.analyze_context_button)
        self.analyze_context_button.update()

    def _load_form(self, record: ContextRecord) -> None:
        self.name_input.setText(record.name or "")
        self.domain_combo.setCurrentText(record.domain or "通用")
        self.scene_combo.setCurrentText(record.scene or "通用")
        self.summary_input.setPlainText(record.summary or "")
        self.instruction_input.setText(record.instruction or "")
        self.context_source_input.clear()
        self.context_analysis_label.clear()
        self.draft_warning_label.setVisible(False)

    def _load_quick_form(self, domain: str, scene: str) -> None:
        self.name_input.clear()
        self.domain_combo.setCurrentText(domain or "通用")
        self.scene_combo.setCurrentText(scene or "通用")
        self.summary_input.clear()
        self.instruction_input.clear()
        self.context_source_input.clear()
        self.context_analysis_label.clear()
        self.draft_warning_label.setVisible(False)

    # ---- 摘要分析（预览确认后填入） ----

    def _analyze_context_source(self) -> None:
        source = self.context_source_input.toPlainText().strip()
        if not source:
            self.context_analysis_label.setText("请先粘贴论文摘要或内容概述。")
            return
        result = detect(source)
        domain = result.get("domain") or "通用"
        if domain == "其他":
            domain = "通用"
        scene = result.get("scene") or "通用"
        source_folded = source.casefold()
        signal_words = [
            word
            for word in DOMAIN_KEYWORDS.get(domain, []) + SCENE_KEYWORDS.get(scene, [])
            if word.casefold() in source_folded
        ]
        keywords = list(dict.fromkeys(signal_words + extract_keywords(source, limit=10)))[:10]
        summary_preview = "\n".join(
            part
            for part in (
                f"核心关键词：{'、'.join(keywords)}" if keywords else "",
                f"摘要概述：{source[:1600]}",
            )
            if part
        )
        dialog = DirectionAnalysisPreviewDialog(
            domain=domain,
            scene=scene,
            keywords=keywords,
            summary_preview=summary_preview,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.apply_requested():
            self.context_analysis_label.setText("已取消，未改动表单。")
            return
        self._apply_analysis(domain, scene, keywords, summary_preview)

    def _apply_analysis(
        self,
        domain: str,
        scene: str,
        keywords: list[str],
        summary_preview: str,
    ) -> None:
        self.domain_combo.setCurrentText(domain)
        self.scene_combo.setCurrentText(scene)
        self.summary_input.setPlainText(summary_preview)
        keyword_text = "、".join(keywords) if keywords else "未提取到稳定关键词"
        self.context_analysis_label.setText(
            f"已填入：{domain} · {scene}　命中关键词：{keyword_text}。保存后才会用于回答。"
        )

    # ---- 动作 ----

    def _apply_direction(self) -> None:
        name, domain, scene, summary, instruction = self._form_values()
        if self._editing_context_id is not None:
            context_id = self.history_store.save_context(
                name=self._resolved_form_name(domain, scene),
                domain=domain,
                scene=scene,
                summary=summary,
                instruction=instruction,
                context_id=self._editing_context_id,
            )
            self._editing_context_id = context_id
            self.settings_service.set_current_context(context_id)
            self.context_changed.emit(context_id)
        else:
            self.settings_service.set_quick_context(domain, scene)
            self.context_changed.emit(None)
        self.refresh_directions(force=True)

    def _save_as_new(self) -> None:
        name, domain, scene, summary, instruction = self._form_values()
        context_id = self.history_store.save_context(
            name=self._resolved_form_name(domain, scene),
            domain=domain,
            scene=scene,
            summary=summary,
            instruction=instruction,
        )
        self._editing_context_id = context_id
        self.settings_service.set_current_context(context_id)
        self.context_changed.emit(context_id)
        self.refresh_directions(force=True)

    def _cancel_edit(self) -> None:
        self._editing_context_id = None
        self.refresh_directions(force=True)

    def _reset_direction(self) -> None:
        """恢复通用方向：只改当前指向，不删除任何已保存方向。"""
        self.settings_service.set_quick_context("通用", "通用")
        self.context_changed.emit(None)
        self.refresh_directions(force=True)

    def _switch_to(self, context_id: int | None) -> None:
        """切换只改当前指向，绝不修改任何记录的领域/场景/背景。"""
        if context_id is not None:
            record = self.history_store.get_context(context_id)
            if record is None or record.builtin:
                context_id = None
        self.settings_service.set_current_context(context_id)
        self.context_changed.emit(context_id)
        self.refresh_directions()

    def _edit_direction(self, context_id: int) -> None:
        record = self.history_store.get_context(context_id)
        if record is None or record.builtin:
            return
        self._editing_context_id = record.id
        self._load_form(record)
        self._sync_action_buttons()

    def _delete_direction(self, context_id: int) -> None:
        record = self.history_store.get_context(context_id)
        if record is None or record.builtin:
            return
        reply = QMessageBox.question(
            self,
            "删除方向",
            f"删除「{_record_display(record)}」？\n已保存的学习记录不受影响。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        settings = self.settings_service.load()
        self.history_store.delete_context(context_id)
        if self._editing_context_id == context_id:
            self._editing_context_id = None
        if settings.current_context_id == context_id:
            self.settings_service.set_current_context(None)
            self.context_changed.emit(None)
        self.refresh_directions(force=True)

    def _current_context(self) -> ContextRecord | None:
        context_id = self.settings_service.load().current_context_id
        if context_id is None:
            return None
        record = self.history_store.get_context(context_id)
        if record is None or record.builtin:
            return None
        return record

    def _sync_action_buttons(self) -> None:
        if self._editing_context_id is not None:
            self.apply_direction_button.setText("保存修改并应用")
            self.save_as_new_button.setText("另存为新方向")
            self.cancel_edit_button.setVisible(True)
        else:
            self.apply_direction_button.setText("应用为当前方向")
            self.save_as_new_button.setText("保存为新方向")
            self.cancel_edit_button.setVisible(False)

    # ---- 已保存方向列表 ----

    def _rebuild_direction_list(self) -> None:
        current = self._current_context()
        current_id = current.id if current is not None else None
        records = [record for record in self.history_store.list_contexts() if not record.builtin]
        name_counts: dict[str, int] = {}
        for record in records:
            label = _record_display(record)
            name_counts[label] = name_counts.get(label, 0) + 1
        self.direction_list.clear()
        if not records:
            placeholder = QListWidgetItem("还没有保存的方向——填好领域 / 场景后点「保存为新方向」")
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.direction_list.addItem(placeholder)
            return
        for record in records:
            display = _record_display(record)
            if name_counts.get(display, 0) > 1:
                display = f"{display}  ·  #{record.id}"
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, record.id)
            row_widget = self._build_direction_row(display, record, record.id == current_id)
            item.setSizeHint(QSize(0, row_widget.sizeHint().height()))
            self.direction_list.addItem(item)
            self.direction_list.setItemWidget(item, row_widget)

    def _build_direction_row(
        self,
        display: str,
        record: ContextRecord,
        is_current: bool,
    ) -> QWidget:
        row = QWidget()
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(6)

        name_label = QLabel(display)
        name_label.setStyleSheet(f"color: {TEXT}; font-size: 13px; background: transparent;")
        layout.addWidget(name_label, 1)

        if is_current:
            badge = QLabel("✓ 当前")
            badge.setStyleSheet(
                f"color: {PRIMARY_DARK}; background: {PRIMARY_SOFT}; "
                f"border-radius: 10px; padding: 2px 8px; font-size: {FONT_MICRO};"
            )
            layout.addWidget(badge)

        use_button = QPushButton("使用")
        use_button.setStyleSheet(_ROW_BUTTON_QSS)
        use_button.clicked.connect(
            lambda checked=False, cid=record.id: self._switch_to(cid)
        )
        layout.addWidget(use_button)

        edit_button = QPushButton("编辑")
        edit_button.setStyleSheet(_ROW_BUTTON_QSS)
        edit_button.clicked.connect(
            lambda checked=False, cid=record.id: self._edit_direction(cid)
        )
        layout.addWidget(edit_button)

        delete_button = QPushButton("删除")
        delete_button.setStyleSheet(_ROW_BUTTON_QSS)
        delete_button.clicked.connect(
            lambda checked=False, cid=record.id: self._delete_direction(cid)
        )
        layout.addWidget(delete_button)
        return row

    def _on_direction_item_clicked(self, item: QListWidgetItem) -> None:
        context_id = item.data(Qt.ItemDataRole.UserRole)
        if context_id is not None:
            self._switch_to(int(context_id))

    # ---- 错位数据整理（预览确认，绝不静默） ----

    def _mismatched_contexts(self) -> list[ContextRecord]:
        return [item["record"] for item in self._repair_proposals()]

    def _repair_proposals(self) -> list[dict]:
        proposals: list[dict] = []
        for record in self.history_store.list_contexts():
            if record.builtin:
                continue
            domain, scene = self._repair_fields(record)
            if domain == (record.domain or "通用") and scene == (record.scene or "通用"):
                continue
            proposals.append({"record": record, "domain": domain, "scene": scene})
        return proposals

    def _repair_fields(self, record: ContextRecord) -> tuple[str, str]:
        """仅整理可确认的旧格式：纯预设领域名或「预设领域 · 场景」。

        其他名称视为用户自定义名称，不能因为它与字段不同就判定为错位。
        """
        domain = record.domain or "通用"
        scene = record.scene or "通用"
        name = (record.name or "").strip()
        if " · " in name:
            parts = name.split(" · ", 1)
            domain_part = parts[0].strip()
            scene_part = parts[1].strip()
            if domain_part in PRESET_DOMAINS:
                domain = domain_part
            if scene_part:
                scene = scene_part
        elif name in PRESET_DOMAINS:
            domain = name
        return domain, scene

    def _refresh_repair_notice(self) -> None:
        count = len(self._repair_proposals())
        if count:
            self.repair_notice_label.setText(
                f"发现 {count} 条方向名称与领域/场景不一致，建议整理。"
            )
            self.repair_button.setVisible(True)
        else:
            self.repair_notice_label.setText("")
            self.repair_button.setVisible(False)

    def _repair_directions(self) -> None:
        rows = self._repair_proposals()
        if not rows:
            QMessageBox.information(self, "整理方向", "没有需要整理的方向。")
            return
        dialog = DirectionRepairDialog(rows, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_rows()
        if not selected:
            return
        backup_path = self._backup_db()
        applied = self._apply_repair(selected)
        QMessageBox.information(
            self, "整理完成", f"已修复 {applied} 条记录。\n修复前备份：{backup_path}"
        )

    def _apply_repair(self, selected: list[dict]) -> int:
        current_id = self.settings_service.load().current_context_id
        for item in selected:
            record = item["record"]
            self.history_store.save_context(
                name=_direction_name(item["domain"], item["scene"]),
                domain=item["domain"],
                scene=item["scene"],
                summary=record.summary or "",
                instruction=record.instruction or "",
                context_id=record.id,
            )
        self.refresh_directions(force=True)
        if current_id is not None and any(item["record"].id == current_id for item in selected):
            self.context_changed.emit(current_id)
        return len(selected)

    def _backup_db(self) -> Path:
        backup_dir = DATA_DIR / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        path = backup_dir / f"app-backup-repair-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.db"
        shutil.copy2(self.history_store.db_path, path)
        return path

    # ---- 刷新 ----

    def refresh_directions(self, force: bool = False) -> None:
        current = self._current_context()
        quick_domain, quick_scene = self.settings_service.get_quick_context()
        if current is not None:
            display = _record_display(current)
            source = "已保存"
        else:
            display = _direction_name(quick_domain, quick_scene)
            source = "临时"
        self.direction_status_label.setText(f"当前生效：{display}（{source}）")
        self.reset_direction_button.setEnabled(
            current is not None or quick_domain != "通用" or quick_scene != "通用"
        )

        if self._editing_context_id is not None:
            record = self.history_store.get_context(self._editing_context_id)
            if record is None:
                self._editing_context_id = None
                self._load_quick_form(quick_domain, quick_scene)
            elif force or not self._form_dirty():
                self._load_form(record)
        elif force or not self._form_dirty():
            if current is not None:
                self._load_form(current)
            else:
                self._load_quick_form(quick_domain, quick_scene)

        self._rebuild_direction_list()
        self._refresh_repair_notice()
        self._sync_action_buttons()
        self.draft_warning_label.setVisible(self._form_dirty())
