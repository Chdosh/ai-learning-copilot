"""工作台：学习方向。

学习方向：当前生效方向状态卡直接提供切换、新建、编辑、删除；编辑表单只修改
明确选择的记录；草稿与当前生效方向彼此独立，保存绝不隐式覆盖其他记录。
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
    ChevronComboBox,
    DANGER,
    DISABLED,
    FONT_MICRO,
    FONT_TITLE,
    MUTED,
    PRIMARY,
    PRIMARY_DARK,
    RADIUS_LG,
    TEXT,
    TEXT_SECONDARY,
    apply_primary_button_style,
    button_qss,
)

PRESET_DOMAINS = ["通用"] + list(DOMAIN_KEYWORDS.keys())
PRESET_SCENES = ["通用", "其他"] + sorted(SCENE_KEYWORDS.keys())
CUSTOM_ITEM = "自定义…"


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
        self._form_open = True
        self._refreshing_direction_selector = False
        self._build_ui()
        self.refresh_directions()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        columns = QHBoxLayout(content)
        columns.setContentsMargins(20, 16, 20, 16)
        columns.setSpacing(14)

        main_panel = QWidget()
        main_layout = QVBoxLayout(main_panel)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(12)
        self.direction_edit_card = self._build_direction_edit_card()
        main_layout.addWidget(self.direction_edit_card)
        main_layout.addStretch(1)

        side_panel = QWidget()
        side_panel.setFixedWidth(320)
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(12)
        self.direction_status_card = self._build_direction_status_card()
        side_layout.addWidget(self.direction_status_card)
        side_layout.addStretch(1)
        columns.addWidget(side_panel)
        columns.addWidget(main_panel, 1)
        scroll.setWidget(content)
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

    # ---- 当前生效方向：紧凑状态卡 ----

    def _build_direction_status_card(self) -> QFrame:
        card = self._build_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        self.direction_status_title = QLabel("当前学习方向")
        self.direction_status_title.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        layout.addWidget(self.direction_status_title)

        self.direction_status_label = QLabel("通用")
        self.direction_status_label.setStyleSheet(
            f"font-size: {FONT_TITLE}; color: {TEXT}; font-weight: 600;"
        )
        layout.addWidget(self.direction_status_label)

        self.direction_status_hint = QLabel("用于下一次截图识别")
        self.direction_status_hint.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        layout.addWidget(self.direction_status_hint)

        quick_separator = QFrame()
        quick_separator.setFrameShape(QFrame.Shape.HLine)
        quick_separator.setStyleSheet(f"color: {BORDER};")
        layout.addWidget(quick_separator)

        quick_title = QLabel("快速选择")
        quick_title.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 600;")
        layout.addWidget(quick_title)

        domain_label = QLabel("领域")
        domain_label.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        layout.addWidget(domain_label)
        self.quick_domain_combo = ChevronComboBox()
        self.quick_domain_combo.addItems(PRESET_DOMAINS)
        self.quick_domain_combo.setMinimumHeight(32)
        layout.addWidget(self.quick_domain_combo)

        scene_label = QLabel("场景")
        scene_label.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        layout.addWidget(scene_label)
        self.quick_scene_combo = ChevronComboBox()
        self.quick_scene_combo.addItems(PRESET_SCENES[:-1])
        self.quick_scene_combo.setMinimumHeight(32)
        layout.addWidget(self.quick_scene_combo)

        quick_actions = QHBoxLayout()
        quick_actions.setSpacing(8)
        self.apply_quick_button = QPushButton("立即应用")
        apply_primary_button_style(self.apply_quick_button)
        self.apply_quick_button.clicked.connect(self._apply_quick_direction)
        quick_actions.addWidget(self.apply_quick_button, 1)
        self.reset_direction_button = QPushButton("恢复通用")
        self.reset_direction_button.setStyleSheet(button_qss())
        self.reset_direction_button.clicked.connect(self._reset_direction)
        quick_actions.addWidget(self.reset_direction_button)
        layout.addLayout(quick_actions)

        custom_separator = QFrame()
        custom_separator.setFrameShape(QFrame.Shape.HLine)
        custom_separator.setStyleSheet(f"color: {BORDER};")
        layout.addWidget(custom_separator)

        custom_title = QLabel("自定义方向")
        custom_title.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 600;")
        layout.addWidget(custom_title)
        self.direction_selector = ChevronComboBox()
        self.direction_selector.setMinimumHeight(32)
        self.direction_selector.currentIndexChanged.connect(self._on_direction_selected)
        layout.addWidget(self.direction_selector)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self.new_direction_button = QPushButton("新建")
        self.edit_direction_button = QPushButton("编辑")
        self.delete_direction_button = QPushButton("删除")
        for button in (
            self.new_direction_button,
            self.edit_direction_button,
            self.delete_direction_button,
        ):
            button.setStyleSheet(button_qss())
            action_row.addWidget(button, 1)
        self.new_direction_button.clicked.connect(self._new_direction)
        self.edit_direction_button.clicked.connect(self._edit_current_direction)
        self.delete_direction_button.clicked.connect(self._delete_current_direction)
        layout.addLayout(action_row)

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
        layout.addLayout(repair_row)
        return card

    # ---- 自定义方向：常驻编辑区 ----

    def _build_direction_edit_card(self) -> QFrame:
        card = self._build_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(8)

        self.editing_target_label = _card_title("新建学习方向")
        layout.addWidget(self.editing_target_label)

        self.edit_form = QWidget()
        self.edit_form.setStyleSheet(f"background: {CARD};")
        form = QVBoxLayout(self.edit_form)
        form.setContentsMargins(0, 4, 0, 0)
        form.setSpacing(8)

        metadata_row = QHBoxLayout()
        metadata_row.setSpacing(10)

        name_column = QWidget()
        name_layout = QVBoxLayout(name_column)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(4)
        name_title = QLabel("方向名称")
        name_title.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        name_layout.addWidget(name_title)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("留空时自动使用“领域 · 场景”")
        self.name_input.setFixedHeight(32)
        self.name_input.textChanged.connect(self._on_form_edited)
        name_layout.addWidget(self.name_input)
        metadata_row.addWidget(name_column, 2)

        domain_column = QWidget()
        domain_layout = QVBoxLayout(domain_column)
        domain_layout.setContentsMargins(0, 0, 0, 0)
        domain_layout.setSpacing(4)
        domain_label = QLabel("领域")
        domain_label.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        domain_layout.addWidget(domain_label)
        self.domain_row, self.domain_combo, self.domain_custom = self._build_custom_combo(
            PRESET_DOMAINS
        )
        domain_layout.addLayout(self.domain_row)
        metadata_row.addWidget(domain_column, 1)

        scene_column = QWidget()
        scene_layout = QVBoxLayout(scene_column)
        scene_layout.setContentsMargins(0, 0, 0, 0)
        scene_layout.setSpacing(4)
        scene_label = QLabel("场景")
        scene_label.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        scene_layout.addWidget(scene_label)
        self.scene_row, self.scene_combo, self.scene_custom = self._build_custom_combo(PRESET_SCENES)
        scene_layout.addLayout(self.scene_row)
        metadata_row.addWidget(scene_column, 1)
        form.addLayout(metadata_row)

        source_title = QLabel("论文摘要 / 内容概述")
        source_title.setStyleSheet(f"color: {TEXT_SECONDARY};")
        form.addWidget(source_title)
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
        self.context_source_input.setStyleSheet(
            "QTextEdit { border: none; background: transparent; padding: 4px 8px; "
            "selection-background-color: #EFF4FF; }"
        )
        self.context_source_input.setFixedHeight(76)
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
        self.analyze_context_button.setToolTip("分析摘要并填入领域、场景与背景")
        self.analyze_context_button.clicked.connect(self._analyze_context_source)
        composer_layout.addWidget(
            self.analyze_context_button, 0, Qt.AlignmentFlag.AlignBottom
        )
        form.addWidget(source_composer)
        self.context_analysis_label = QLabel("")
        self.context_analysis_label.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        form.addWidget(self.context_analysis_label)

        summary_title = QLabel("提取后的关键背景（会加入每次提问前）")
        summary_title.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        form.addWidget(summary_title)
        self.summary_input = QTextEdit()
        self.summary_input.setPlaceholderText("AI 会结合这些信息理解截图或文本，留空则按通用行为解释。")
        self.summary_input.setFixedHeight(58)
        form.addWidget(self.summary_input)

        instruction_title = QLabel("回答偏好")
        instruction_title.setStyleSheet(f"color: {MUTED}; font-size: {FONT_MICRO};")
        form.addWidget(instruction_title)
        self.instruction_input = QLineEdit()
        self.instruction_input.setPlaceholderText("例如：专业术语附中文解释；长句分步骤说明")
        self.instruction_input.setFixedHeight(32)
        form.addWidget(self.instruction_input)

        self.draft_warning_label = QLabel("有未保存修改，不会用于下一次识别")
        self.draft_warning_label.setStyleSheet(f"color: {DANGER}; font-size: {FONT_MICRO};")
        self.draft_warning_label.setVisible(False)
        form.addWidget(self.draft_warning_label)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.apply_direction_button = QPushButton("新建并应用")
        apply_primary_button_style(self.apply_direction_button)
        self.apply_direction_button.clicked.connect(self._save_and_apply)
        footer.addWidget(self.apply_direction_button)
        self.save_as_new_button = QPushButton("另存为新方向")
        self.save_as_new_button.setStyleSheet(button_qss())
        self.save_as_new_button.clicked.connect(self._save_as_new)
        footer.addWidget(self.save_as_new_button)
        self.cancel_edit_button = QPushButton("取消")
        self.cancel_edit_button.setStyleSheet(button_qss())
        self.cancel_edit_button.clicked.connect(self._cancel_edit)
        footer.addWidget(self.cancel_edit_button)
        footer.addStretch(1)
        form.addLayout(footer)

        layout.addWidget(self.edit_form)
        return card

    def _build_custom_combo(self, presets: list[str]) -> tuple[QVBoxLayout, QComboBox, QLineEdit]:
        row = QVBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        combo = ChevronComboBox()
        combo.addItems(presets)
        combo.addItem(CUSTOM_ITEM)
        combo.setMinimumHeight(32)
        custom = QLineEdit()
        custom.setPlaceholderText("输入自定义值后生效")
        custom.setMinimumWidth(120)
        custom.setMinimumHeight(32)
        custom.hide()
        combo.currentTextChanged.connect(
            lambda text, c=combo, w=custom: self._on_custom_combo_changed(c, w, text)
        )
        combo.currentTextChanged.connect(self._on_form_edited)
        custom.textChanged.connect(self._on_form_edited)
        row.addWidget(combo)
        row.addWidget(custom)
        return row, combo, custom

    def _on_custom_combo_changed(self, combo: QComboBox, custom: QLineEdit, text: str) -> None:
        custom.setVisible(text == CUSTOM_ITEM)
        if text == CUSTOM_ITEM:
            custom.setFocus()

    def _set_combo_value(self, combo: QComboBox, custom: QLineEdit, value: str) -> None:
        if value == CUSTOM_ITEM:
            combo.setCurrentText(CUSTOM_ITEM)
            custom.show()
            return
        if combo.findText(value) < 0:
            combo.insertItem(combo.count() - 1, value)
        combo.setCurrentText(value)
        custom.hide()

    def _set_quick_combo_value(self, combo: QComboBox, value: str) -> None:
        if combo.findText(value) < 0:
            combo.addItem(value)
        combo.setCurrentText(value)

    def _combo_value(self, combo: QComboBox, custom: QLineEdit) -> str:
        if not custom.isHidden():
            typed = custom.text().strip()
            if typed:
                return typed
        text = combo.currentText().strip()
        return "" if text == CUSTOM_ITEM else text

    def _form_values(self) -> tuple[str, str, str, str, str]:
        name = self.name_input.text().strip()
        domain = self._combo_value(self.domain_combo, self.domain_custom).strip() or "通用"
        scene = self._combo_value(self.scene_combo, self.scene_custom).strip() or "通用"
        summary = self.summary_input.toPlainText().strip()
        instruction = self.instruction_input.text().strip()
        return name, domain, scene, summary, instruction

    def _form_dirty(self) -> bool:
        base_name, base_domain, base_scene = "", "通用", "通用"
        base_summary, base_instruction = "", ""
        if self._editing_context_id is not None:
            record = self.history_store.get_context(self._editing_context_id)
            if record is not None:
                base_name = record.name or ""
                base_domain = record.domain or "通用"
                base_scene = record.scene or "通用"
                base_summary = record.summary or ""
                base_instruction = record.instruction or ""
        return self._form_values() != (
            base_name,
            base_domain,
            base_scene,
            base_summary,
            base_instruction,
        )

    def _on_form_edited(self, *args) -> None:
        self.draft_warning_label.setVisible(self._form_open and self._form_dirty())

    def _update_analyze_button_state(self, *args) -> None:
        active = bool(self.context_source_input.toPlainText().strip())
        self.analyze_context_button.setProperty("active", active)
        self.analyze_context_button.style().unpolish(self.analyze_context_button)
        self.analyze_context_button.style().polish(self.analyze_context_button)
        self.analyze_context_button.update()

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
        self._set_combo_value(self.domain_combo, self.domain_custom, domain)
        self._set_combo_value(self.scene_combo, self.scene_custom, scene)
        parts: list[str] = []
        if keywords:
            parts.append("核心关键词：" + "、".join(keywords))
        parts.append("摘要概述：" + source[:1600])
        self.summary_input.setPlainText("\n".join(parts))
        keyword_text = "、".join(keywords) if keywords else "未提取到稳定关键词"
        self.context_analysis_label.setText(
            f"建议：{domain} · {scene}　关键词：{keyword_text}。保存后才会用于回答。"
        )

    def _load_form(self, record: ContextRecord | None) -> None:
        name = record.name if record is not None else ""
        domain = record.domain if record is not None else "通用"
        scene = record.scene if record is not None else "通用"
        summary = record.summary if record is not None else ""
        instruction = record.instruction if record is not None else ""
        self.name_input.setText(name)
        self._set_combo_value(self.domain_combo, self.domain_custom, domain)
        self._set_combo_value(self.scene_combo, self.scene_custom, scene)
        self.summary_input.setPlainText(summary)
        self.instruction_input.setText(instruction)
        self.context_source_input.clear()
        self.context_analysis_label.clear()

    def _current_context(self) -> ContextRecord | None:
        context_id = self.settings_service.load().current_context_id
        if context_id is None:
            return None
        record = self.history_store.get_context(context_id)
        if record is None or record.builtin:
            return None
        return record

    def _open_edit_form(self) -> None:
        self._form_open = True
        self.direction_edit_card.show()
        self.edit_form.show()
        self._refresh_editor_state()
        self.draft_warning_label.setVisible(self._form_dirty())

    def _close_edit_form(self) -> None:
        self._form_open = True
        self.direction_edit_card.show()
        self.edit_form.show()
        self.context_source_input.clear()
        self.context_analysis_label.clear()
        self.draft_warning_label.setVisible(False)

    def _cancel_edit(self) -> None:
        record = None
        if self._editing_context_id is not None:
            record = self.history_store.get_context(self._editing_context_id)
            if record is not None and record.builtin:
                record = None
        self._load_form(record)
        self._close_edit_form()

    def _new_direction(self) -> None:
        self._editing_context_id = None
        self._load_form(None)
        self._open_edit_form()

    def _edit_current_direction(self) -> None:
        current = self._current_context()
        if current is not None:
            self._edit_direction(current.id)

    def _delete_current_direction(self) -> None:
        current = self._current_context()
        if current is not None:
            self._delete_direction(current.id)

    def _refresh_editor_state(self) -> None:
        record = None
        if self._editing_context_id is not None:
            record = self.history_store.get_context(self._editing_context_id)
        if record is None or record.builtin:
            self.editing_target_label.setText("新建学习方向")
            self.save_as_new_button.hide()
            self.apply_direction_button.setText("新建并应用")
        else:
            self.editing_target_label.setText(f"正在编辑：{_record_display(record)}")
            self.save_as_new_button.show()
            self.apply_direction_button.setText("保存修改并应用")

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

    def _save_and_apply(self) -> None:
        """只更新明确选择的记录；无目标时新建。保存后设为当前方向。"""
        _name, domain, scene, summary, instruction = self._form_values()
        name = self._resolved_form_name(domain, scene)
        context_id = self._editing_context_id
        if context_id is not None:
            record = self.history_store.get_context(context_id)
            if record is None or record.builtin:
                context_id = None
        if context_id is None:
            context_id = self.history_store.save_context(
                name=name,
                domain=domain,
                scene=scene,
                summary=summary,
                instruction=instruction,
            )
        else:
            context_id = self.history_store.save_context(
                name=name,
                domain=domain,
                scene=scene,
                summary=summary,
                instruction=instruction,
                context_id=context_id,
            )
        self._editing_context_id = context_id
        self.settings_service.set_current_context(context_id)
        self.context_changed.emit(context_id)
        self.refresh_directions()
        self._close_edit_form()

    def _save_as_new(self) -> None:
        """始终插入新记录，不做隐式领域复用，不覆盖任何已有方向。"""
        _name, domain, scene, summary, instruction = self._form_values()
        name = self._resolved_form_name(domain, scene)
        context_id = self.history_store.save_context(
            name=name,
            domain=domain,
            scene=scene,
            summary=summary,
            instruction=instruction,
        )
        self._editing_context_id = context_id
        self.settings_service.set_current_context(context_id)
        self.context_changed.emit(context_id)
        self.refresh_directions()
        self._close_edit_form()

    def _reset_direction(self) -> None:
        """恢复通用方向：只改当前指向，不删除任何已保存方向。"""
        self.settings_service.set_quick_context("通用", "通用")
        self.context_changed.emit(None)
        self.refresh_directions()

    def _apply_quick_direction(self) -> None:
        domain = self.quick_domain_combo.currentText() or "通用"
        scene = self.quick_scene_combo.currentText() or "通用"
        current = self._current_context()
        if current is not None and (
            domain,
            scene,
        ) == (current.domain or "通用", current.scene or "通用"):
            self.context_changed.emit(current.id)
            self.refresh_directions()
            return
        self.settings_service.set_quick_context(domain, scene)
        self.context_changed.emit(None)
        self.refresh_directions()

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
        self._open_edit_form()

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
        self.refresh_directions()

    def _on_direction_selected(self, index: int) -> None:
        if self._refreshing_direction_selector or index < 0:
            return
        context_id = self.direction_selector.itemData(index)
        if context_id is not None:
            self._switch_to(context_id)

    # ---- 刷新 ----

    def refresh_directions(self) -> None:
        current = self._current_context()
        quick_domain, quick_scene = self.settings_service.get_quick_context()
        if current is not None:
            effective_display = _direction_name(
                current.domain or "通用", current.scene or "通用"
            )
            quick_display_domain = current.domain or "通用"
            quick_display_scene = current.scene or "通用"
        else:
            effective_display = _direction_name(quick_domain, quick_scene)
            quick_display_domain = quick_domain
            quick_display_scene = quick_scene
        self.direction_status_label.setText(effective_display)
        self._set_quick_combo_value(self.quick_domain_combo, quick_display_domain)
        self._set_quick_combo_value(self.quick_scene_combo, quick_display_scene)
        self._rebuild_direction_selector(current)
        self._refresh_repair_notice()
        if not self._form_open or (
            self._editing_context_id is None and not self._form_dirty() and current is not None
        ):
            self._editing_context_id = current.id if current is not None else None
            self._load_form(current)
        self.draft_warning_label.setVisible(self._form_open and self._form_dirty())
        self.direction_edit_card.show()
        self._refresh_editor_state()
        has_current = current is not None
        self.edit_direction_button.setEnabled(has_current)
        self.delete_direction_button.setEnabled(has_current)
        self.reset_direction_button.setEnabled(
            has_current or quick_domain != "通用" or quick_scene != "通用"
        )

    def _rebuild_direction_selector(self, current: ContextRecord | None) -> None:
        current_id = current.id if current is not None else None
        records = [record for record in self.history_store.list_contexts() if not record.builtin]
        name_counts: dict[str, int] = {}
        for record in records:
            label = _record_display(record)
            name_counts[label] = name_counts.get(label, 0) + 1
        self._refreshing_direction_selector = True
        try:
            self.direction_selector.clear()
            self.direction_selector.addItem("选择已保存的自定义方向", None)
            selected_index = 0
            for record in records:
                label = _record_display(record)
                if name_counts[label] > 1:
                    label = f"{label}  ·  #{record.id}"
                self.direction_selector.addItem(label, record.id)
                if record.id == current_id:
                    selected_index = self.direction_selector.count() - 1
            self.direction_selector.setCurrentIndex(selected_index)
        finally:
            self._refreshing_direction_selector = False

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
            if scene_part and scene_part != CUSTOM_ITEM:
                scene = scene_part
        elif name in PRESET_DOMAINS:
            domain = name
        return domain, scene

    def _refresh_repair_notice(self) -> None:
        count = len(self._repair_proposals())
        if count:
            self.repair_notice_label.setText(
                f"发现 {count} 条名称与领域/场景不一致的方向，建议整理。"
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
        self.refresh_directions()
        if current_id is not None and any(item["record"].id == current_id for item in selected):
            self.context_changed.emit(current_id)
        return len(selected)

    def _backup_db(self) -> Path:
        backup_dir = DATA_DIR / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        path = backup_dir / f"app-backup-repair-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.db"
        shutil.copy2(self.history_store.db_path, path)
        return path
