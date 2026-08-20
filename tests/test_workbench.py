from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import app.ui.main_window as main_window_module
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from app.services.history_store import HistoryStore
from app.services.knowledge_base import KnowledgeBase, KnowledgeIngest, SaveTermCommand
from app.services.settings import SettingsService
from app.ui.main_window import MainWindow
from app.ui.overview import OverviewPage
from app.ui.workbench import WorkbenchPage


def _seed_store(store: HistoryStore) -> int:
    capture_id = store.save_capture(
        image_path="",
        source_text="Token limit exceeded",
        translation="超过 Token 限制",
        explanation="输入内容太长，需要缩短。",
        tags=["AI", "报错"],
        category="报错",
    )
    conv_id = store.create_conversation(capture_id, title="Token limit exceeded")
    store.add_message(conv_id, "user", "Token limit exceeded", mode="capture")
    store.add_message(
        conv_id,
        "assistant",
        '{"translation":"超过 Token 限制","explanation":"输入内容太长。","terms":[],"tags":["AI"]}',
        mode="default",
    )
    store.add_message(conv_id, "user", "怎么解决？", mode="custom")
    store.add_message(
        conv_id,
        "assistant",
        '{"translation":"","explanation":"把长内容拆成几段。","terms":[],"tags":[]}',
        mode="custom",
    )
    store._upsert_terms([{"term": "Token", "chinese_name": "文本单位", "beginner_explanation": "计量单位", "examples": []}])
    return capture_id


# ---------------------------------------------------------------------------
# 概览页（不变）
# ---------------------------------------------------------------------------


def test_overview_refreshes_with_data(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    _seed_store(store)

    overview = OverviewPage(store, SettingsService(store))
    overview.refresh()

    assert overview.session_list.count() >= 1
    assert overview.domain_filter_combo.itemData(0) == ""
    assert overview.domain_filter_combo.findData("通用") >= 0
    assert not overview.followup_filter_toggle.isHidden()
    assert overview.time_filter_combo.count() == 3
    assert "方向" in overview.direction_label.text()
    overview.deleteLater()
    app.processEvents()


def test_overview_selects_and_renders_conversation(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    capture_id = _seed_store(store)
    settings_service = SettingsService(store)

    overview = OverviewPage(store, settings_service)
    overview.refresh_sessions()
    assert overview.session_list.count() == 1

    overview.select_capture(capture_id)
    text = overview.message_browser.toPlainText()
    assert "Token limit exceeded" in text
    assert "怎么解决？" in text
    assert "把长内容拆成几段。" in text
    assert overview.header_meta.text() != ""
    assert overview.actions_menu_button.isEnabled()
    overview.deleteLater()
    app.processEvents()


def test_overview_delete_capture(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    capture_id = _seed_store(store)
    overview = OverviewPage(store, SettingsService(store))

    # bypass the confirm dialog
    from PySide6.QtWidgets import QMessageBox

    def fake_question(*args, **kwargs):
        return QMessageBox.StandardButton.Yes

    overview.select_capture(capture_id)
    QMessageBox.question = staticmethod(fake_question)
    overview._delete_capture()
    assert store.get_capture(capture_id) is None
    assert overview.session_list.count() == 0
    overview.deleteLater()
    app.processEvents()


# ---------------------------------------------------------------------------
# 工作台（精简版契约）：单一职责 = 学习方向
# ---------------------------------------------------------------------------


def test_workbench_apply_is_temporary_and_save_creates_record(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    workbench = WorkbenchPage(store, service)

    assert service.load().current_context_id is None
    assert workbench.domain_combo.isEditable()  # 领域可自由输入（操作范围拓宽）
    assert workbench.scene_combo.isEditable()

    changed: list = []
    workbench.context_changed.connect(changed.append)

    workbench.domain_combo.setCurrentText("生物")
    workbench.scene_combo.setCurrentText("学术论文")
    workbench.apply_direction_button.click()

    # 应用 = 临时生效，不落库
    assert service.load().current_context_id is None
    assert service.get_quick_context() == ("生物", "学术论文")
    assert [c for c in store.list_contexts() if not c.builtin] == []
    assert "生物 · 学术论文" in workbench.direction_status_label.text()
    assert changed == [None]

    # 保存 = 落库
    workbench.summary_input.setPlainText("CRISPR 基因编辑")
    workbench.instruction_input.setText("术语给中文对照")
    workbench.save_as_new_button.click()
    current = service.load().current_context_id
    assert current is not None
    context = store.get_context(current)
    assert context.domain == "生物"
    assert context.scene == "学术论文"
    assert context.summary == "CRISPR 基因编辑"
    assert context.instruction == "术语给中文对照"
    assert context.name == "生物 · 学术论文"
    assert changed[-1] == current

    # 保存后进入编辑态，再次点应用 = 保存修改，不重复建记录
    workbench.apply_direction_button.click()
    non_builtin = [c for c in store.list_contexts() if not c.builtin]
    assert len(non_builtin) == 1
    assert changed[-1] == current

    workbench.reset_direction_button.click()
    assert service.load().current_context_id is None
    assert changed[-1] is None
    workbench.deleteLater()
    app.processEvents()


def test_workbench_save_never_updates_unselected_record(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    existing_id = store.save_context(
        name="生物 · 学术论文",
        domain="生物",
        scene="学术论文",
        summary="CRISPR 基因编辑",
    )

    workbench = WorkbenchPage(store, service)
    workbench.domain_combo.setCurrentText("生物")
    workbench.scene_combo.setCurrentText("技术文档")
    workbench.summary_input.setPlainText("串口协议手册")
    workbench.save_as_new_button.click()

    non_builtin = [c for c in store.list_contexts() if not c.builtin]
    assert len(non_builtin) == 2
    existing = store.get_context(existing_id)
    assert existing.scene == "学术论文"
    assert existing.summary == "CRISPR 基因编辑"
    assert service.load().current_context_id != existing_id
    workbench.deleteLater()
    app.processEvents()


def test_workbench_same_domain_different_scenes_coexist(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    workbench = WorkbenchPage(store, service)

    workbench.domain_combo.setCurrentText("生物")
    workbench.scene_combo.setCurrentText("学术论文")
    workbench.summary_input.setPlainText("CRISPR 基因编辑")
    workbench.save_as_new_button.click()
    paper_id = service.load().current_context_id
    assert store.get_context(paper_id).name == "生物 · 学术论文"

    workbench.domain_combo.setCurrentText("生物")
    workbench.scene_combo.setCurrentText("技术文档")
    workbench.summary_input.setPlainText("串口协议手册")
    workbench.save_as_new_button.click()
    doc_id = service.load().current_context_id
    assert doc_id != paper_id

    paper = store.get_context(paper_id)
    assert paper.scene == "学术论文"
    assert paper.summary == "CRISPR 基因编辑"
    assert paper.name == "生物 · 学术论文"
    doc = store.get_context(doc_id)
    assert doc.scene == "技术文档"
    assert doc.name == "生物 · 技术文档"

    non_builtin = [c for c in store.list_contexts() if not c.builtin]
    assert len(non_builtin) == 2
    workbench.deleteLater()
    app.processEvents()


def test_workbench_form_loads_current_context(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    context_id = store.save_context(
        name="生物论文",
        domain="生物",
        scene="学术论文",
        summary="CRISPR 基因编辑",
        instruction="术语给中文对照",
    )
    service.set_current_context(context_id)

    workbench = WorkbenchPage(store, service)
    assert workbench.domain_combo.currentText() == "生物"
    assert workbench.scene_combo.currentText() == "学术论文"
    assert "CRISPR 基因编辑" in workbench.summary_input.toPlainText()
    assert "术语给中文对照" in workbench.instruction_input.text()
    assert "生物论文" in workbench.direction_status_label.text()
    assert "已保存" in workbench.direction_status_label.text()
    workbench.deleteLater()
    app.processEvents()


def test_workbench_edit_only_updates_selected_id(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    a_id = store.save_context(
        name="生物 · 学术论文",
        domain="生物",
        scene="学术论文",
        summary="CRISPR 基因编辑",
    )
    b_id = store.save_context(name="编程", domain="编程", scene="通用", summary="Python")
    service.set_current_context(a_id)

    workbench = WorkbenchPage(store, service)
    workbench._edit_direction(b_id)
    assert workbench.apply_direction_button.text() == "保存修改并应用"
    assert not workbench.cancel_edit_button.isHidden()
    workbench.domain_combo.setCurrentText("医学")
    workbench.apply_direction_button.click()

    assert service.load().current_context_id == b_id
    b = store.get_context(b_id)
    assert b.domain == "医学"
    assert b.scene == "通用"
    assert b.name == "医学"
    a = store.get_context(a_id)
    assert a.domain == "生物"
    assert a.scene == "学术论文"
    assert a.summary == "CRISPR 基因编辑"
    workbench.deleteLater()
    app.processEvents()


def test_workbench_switch_does_not_modify_record(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    a_id = store.save_context(
        name="生物 · 学术论文",
        domain="生物",
        scene="学术论文",
        summary="CRISPR 基因编辑",
    )
    b_id = store.save_context(name="编程", domain="编程", scene="通用", summary="Python")
    service.set_current_context(a_id)

    workbench = WorkbenchPage(store, service)
    workbench._switch_to(b_id)
    assert service.load().current_context_id == b_id
    assert store.get_context(a_id).summary == "CRISPR 基因编辑"
    assert store.get_context(a_id).domain == "生物"
    assert store.get_context(b_id).domain == "编程"
    assert workbench.direction_status_label.text() == "当前生效：编程（已保存）"

    workbench._switch_to(None)
    assert service.load().current_context_id is None
    assert workbench.direction_status_label.text() == "当前生效：通用（临时）"
    workbench.deleteLater()
    app.processEvents()


def test_workbench_direction_list_rows_and_click_switches(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    bio_id = store.save_context(name="生物论文", domain="生物", scene="学术论文")
    code_id = store.save_context(name="Python 文档", domain="编程", scene="技术文档")
    service.set_current_context(bio_id)

    workbench = WorkbenchPage(store, service)
    assert workbench.direction_list.count() == 2

    for index in range(workbench.direction_list.count()):
        item = workbench.direction_list.item(index)
        if item.data(Qt.ItemDataRole.UserRole) == code_id:
            workbench._on_direction_item_clicked(item)
    assert service.load().current_context_id == code_id
    assert workbench.direction_status_label.text() == "当前生效：Python 文档（已保存）"
    assert store.get_context(bio_id).domain == "生物"
    assert store.get_context(code_id).domain == "编程"
    workbench.deleteLater()
    app.processEvents()


def test_workbench_draft_does_not_affect_effective_direction(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    workbench = WorkbenchPage(store, service)

    workbench.domain_combo.setCurrentText("生物")
    workbench.scene_combo.setCurrentText("学术论文")
    workbench.save_as_new_button.click()
    bio_id = service.load().current_context_id

    # 保存后处于编辑态：修改字段是草稿，不影响生效方向
    workbench.domain_combo.setCurrentText("医学")
    assert service.load().current_context_id == bio_id
    assert not workbench.draft_warning_label.isHidden()
    assert "生物 · 学术论文" in workbench.direction_status_label.text()
    assert "医学" not in workbench.direction_status_label.text()

    # 刷新不覆盖草稿
    workbench.refresh_directions()
    assert workbench.domain_combo.currentText() == "医学"

    # 取消编辑回到当前方向字段
    workbench.cancel_edit_button.click()
    assert workbench.domain_combo.currentText() == "生物"
    assert workbench.scene_combo.currentText() == "学术论文"
    assert workbench.draft_warning_label.isHidden()
    workbench.deleteLater()
    app.processEvents()


def test_workbench_quick_apply_overrides_saved_current(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    context_id = store.save_context(
        name="生物 · 学术论文",
        domain="生物",
        scene="学术论文",
        summary="CRISPR 基因编辑",
    )
    service.set_current_context(context_id)
    workbench = WorkbenchPage(store, service)

    workbench.domain_combo.setCurrentText("医学")
    workbench.apply_direction_button.click()

    assert service.load().current_context_id is None
    assert service.get_quick_context() == ("医学", "学术论文")
    assert workbench.direction_status_label.text() == "当前生效：医学 · 学术论文（临时）"
    workbench.deleteLater()
    app.processEvents()


def test_workbench_editor_keeps_explicit_target_when_current_direction_changes(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    bio_id = store.save_context(name="生物论文", domain="生物", scene="学术论文")
    code_id = store.save_context(name="Python 文档", domain="编程", scene="技术文档")
    service.set_current_context(bio_id)
    workbench = WorkbenchPage(store, service)

    workbench._edit_direction(bio_id)
    workbench.summary_input.setPlainText("尚未保存的生物草稿")
    workbench._switch_to(code_id)

    assert service.load().current_context_id == code_id
    assert workbench._editing_context_id == bio_id
    assert workbench.summary_input.toPlainText() == "尚未保存的生物草稿"
    assert workbench.direction_status_label.text() == "当前生效：Python 文档（已保存）"
    workbench.deleteLater()
    app.processEvents()


def test_workbench_custom_names_and_duplicate_names_remain_distinguishable(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    workbench = WorkbenchPage(store, service)

    workbench.name_input.setText("考试重点")
    workbench.domain_combo.setCurrentText("生物")
    workbench.save_as_new_button.click()
    first_id = service.load().current_context_id

    workbench.name_input.setText("考试重点")
    workbench.domain_combo.setCurrentText("医学")
    workbench.save_as_new_button.click()
    second_id = service.load().current_context_id

    assert first_id != second_id
    assert store.get_context(first_id).name == "考试重点"
    assert store.get_context(second_id).name == "考试重点"

    labels = []
    for index in range(workbench.direction_list.count()):
        widget = workbench.direction_list.itemWidget(workbench.direction_list.item(index))
        label = widget.findChild(type(widget.layout().itemAt(0).widget()))
        labels.append(label.text())
    assert any(f"#{first_id}" in text for text in labels)
    assert any(f"#{second_id}" in text for text in labels)
    assert not workbench._repair_proposals()
    workbench.deleteLater()
    app.processEvents()


def test_workbench_analysis_apply_and_cancel(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    workbench = WorkbenchPage(store, service)

    workbench._apply_analysis(
        domain="生物",
        scene="学术论文",
        keywords=["CRISPR", "基因"],
        summary_preview="核心关键词：CRISPR、基因\n摘要概述：本研究使用 CRISPR 基因编辑。",
    )
    assert workbench.domain_combo.currentText() == "生物"
    assert workbench.scene_combo.currentText() == "学术论文"
    assert "核心关键词" in workbench.summary_input.toPlainText()
    assert "命中关键词" in workbench.context_analysis_label.text()
    assert service.load().current_context_id is None

    workbench.save_as_new_button.click()
    settings = service.load()
    assert settings.current_context_id is not None
    assert "领域：生物" in settings.context_block
    assert "场景：学术论文" in settings.context_block
    assert "核心关键词" in settings.context_block
    assert "CRISPR" in settings.context_block

    # 预览被取消时不改动表单
    from PySide6.QtWidgets import QDialog

    from app.ui.workbench import DirectionAnalysisPreviewDialog

    original_exec = DirectionAnalysisPreviewDialog.exec

    def rejected_exec(self):
        return int(QDialog.DialogCode.Rejected)

    DirectionAnalysisPreviewDialog.exec = rejected_exec
    try:
        workbench.context_source_input.setPlainText("量子力学 粒子 波函数")
        workbench._analyze_context_source()
    finally:
        DirectionAnalysisPreviewDialog.exec = original_exec
    assert workbench.domain_combo.currentText() == "生物"
    assert "已取消" in workbench.context_analysis_label.text()
    workbench.deleteLater()
    app.processEvents()


def test_workbench_advanced_panel_is_collapsed_by_default(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    workbench = WorkbenchPage(store, SettingsService(store))

    assert workbench.advanced_panel.isHidden()
    assert workbench.advanced_toggle.text() == "自定义方向"
    workbench.advanced_toggle.click()
    assert not workbench.advanced_panel.isHidden()
    assert "收起" in workbench.advanced_toggle.text()
    workbench.deleteLater()
    app.processEvents()


def test_workbench_repairing_current_direction_emits_context_changed(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    context_id = store.save_context(name="生物", domain="通用", scene="技术文档")
    service.set_current_context(context_id)
    workbench = WorkbenchPage(store, service)
    changed: list = []
    workbench.context_changed.connect(changed.append)

    proposal = next(
        item for item in workbench._repair_proposals() if item["record"].id == context_id
    )
    workbench._apply_repair([proposal])

    assert changed == [context_id]
    assert workbench.direction_status_label.text() == "当前生效：生物 · 技术文档（已保存）"
    workbench.deleteLater()
    app.processEvents()


def test_workbench_mismatch_proposals_and_repair(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    bad_id = store.save_context(name="生物", domain="通用", scene="技术文档")
    parse_id = store.save_context(name="编程 · 学术论文", domain="医学", scene="学术论文")
    good_id = store.save_context(name="化学", domain="化学", scene="通用")

    workbench = WorkbenchPage(store, service)
    proposals = workbench._repair_proposals()
    by_id = {int(p["record"].id): p for p in proposals}
    assert bad_id in by_id
    assert parse_id in by_id
    assert good_id not in by_id
    assert by_id[bad_id]["domain"] == "生物"
    assert by_id[bad_id]["scene"] == "技术文档"
    assert by_id[parse_id]["domain"] == "编程"
    assert by_id[parse_id]["scene"] == "学术论文"
    assert workbench._mismatched_contexts()

    applied = workbench._apply_repair([by_id[bad_id], by_id[parse_id]])
    assert applied == 2
    bad = store.get_context(bad_id)
    assert bad.name == "生物 · 技术文档"
    assert bad.domain == "生物"
    assert bad.scene == "技术文档"
    parsed = store.get_context(parse_id)
    assert parsed.name == "编程 · 学术论文"
    assert parsed.domain == "编程"
    assert parsed.scene == "学术论文"
    assert not workbench._repair_proposals()
    assert not workbench._mismatched_contexts()
    assert workbench.repair_notice_label.text() == ""
    workbench.deleteLater()
    app.processEvents()


def test_workbench_no_longer_contains_removed_modules(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    workbench = WorkbenchPage(store, SettingsService(store))

    # 旧的三套入口与知识资产区块已移除
    for attribute in (
        "learn_stack",
        "mode_screenshot_btn",
        "direction_edit_card",
        "direction_status_card",
        "apply_quick_button",
        "direction_selector",
        "new_direction_button",
        "edit_direction_button",
        "delete_direction_button",
        "tips_card",
        "digest_card",
        "domain_custom",
        "scene_custom",
    ):
        assert not hasattr(workbench, attribute), f"workbench still exposes {attribute}"
    assert hasattr(workbench, "direction_list")
    assert hasattr(workbench, "advanced_panel")
    assert hasattr(workbench, "quick_domain_combo")
    assert hasattr(workbench, "quick_scene_combo")
    workbench.deleteLater()
    app.processEvents()


def test_workbench_splits_quick_and_custom_paths(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    workbench = WorkbenchPage(store, SettingsService(store))

    assert workbench.content_widget.maximumWidth() == 1120
    assert workbench.content_layout.indexOf(workbench.quick_card) == 0
    assert workbench.content_layout.indexOf(workbench.custom_card) == 1
    assert not workbench.quick_domain_combo.isEditable()
    assert not workbench.quick_scene_combo.isEditable()
    assert workbench.domain_combo.isEditable()
    assert workbench.scene_combo.isEditable()
    assert "transparent" in workbench.domain_combo.parentWidget().styleSheet()
    assert "transparent" in workbench.scene_combo.parentWidget().styleSheet()
    assert workbench.advanced_panel.isAncestorOf(workbench.apply_direction_button)
    assert workbench.advanced_panel.isAncestorOf(workbench.save_as_new_button)
    assert workbench.advanced_panel.isAncestorOf(workbench.delete_edit_button)

    workbench.show()
    app.processEvents()
    workbench.smart_detect_button.click()
    app.processEvents()
    assert not workbench.advanced_panel.isHidden()
    assert workbench.context_source_input.hasFocus()
    workbench.deleteLater()
    app.processEvents()


def test_workbench_quick_preset_opens_and_applies_immediately(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    workbench = WorkbenchPage(store, service)
    workbench.show()
    app.processEvents()

    QTest.mouseClick(
        workbench.quick_domain_combo,
        Qt.MouseButton.LeftButton,
        pos=workbench.quick_domain_combo.rect().center(),
    )
    app.processEvents()
    assert workbench.quick_domain_combo.view().isVisible()
    workbench.quick_domain_combo.hidePopup()

    domain_index = workbench.quick_domain_combo.findText("生物")
    scene_index = workbench.quick_scene_combo.findText("学术论文")
    workbench.quick_domain_combo.setCurrentIndex(domain_index)
    workbench.quick_domain_combo.activated.emit(domain_index)
    workbench.quick_scene_combo.setCurrentIndex(scene_index)
    workbench.quick_scene_combo.activated.emit(scene_index)

    assert service.load().current_context_id is None
    assert service.get_quick_context() == ("生物", "学术论文")
    assert "生物 · 学术论文" in workbench.direction_status_label.text()
    assert [c for c in store.list_contexts() if not c.builtin] == []
    workbench.deleteLater()
    app.processEvents()


def test_saved_direction_row_uses_click_and_keeps_mutations_in_editor(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    context_id = store.save_context(name="论文精读", domain="生物", scene="学术论文")
    workbench = WorkbenchPage(store, service)

    item = workbench.direction_list.item(0)
    row = workbench.direction_list.itemWidget(item)
    assert [button.text() for button in row.findChildren(QPushButton)] == ["编辑"]

    workbench._on_direction_item_clicked(item)
    assert service.load().current_context_id == context_id
    row.findChildren(QPushButton)[0].click()
    assert not workbench.advanced_panel.isHidden()
    assert not workbench.delete_edit_button.isHidden()
    workbench.deleteLater()
    app.processEvents()


# ---------------------------------------------------------------------------
# 主窗口（导航顺序更新：获取 / 学习 / 术语本 / 工作台 / 设置）
# ---------------------------------------------------------------------------


def test_sidebar_navigation_order_and_screenshot_action(tmp_path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    started: list[bool] = []

    monkeypatch.setattr(main_window_module, "HistoryStore", lambda: store)
    monkeypatch.setattr(main_window_module, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(main_window_module.MainWindow, "_build_tray", lambda self: None)
    monkeypatch.setattr(main_window_module.MainWindow, "_start_hotkey", lambda self: None)
    monkeypatch.setattr(
        main_window_module.MainWindow,
        "start_capture",
        lambda self: started.append(True),
    )

    window = main_window_module.MainWindow()
    labels = [button.text() for button in window.nav_buttons]
    assert labels == ["获取", "学习", "术语本", "工作台", "设置"]
    assert not hasattr(window, "terms_add_button")
    assert not hasattr(window, "terms_review_button")
    assert not hasattr(window, "_terms_view_buttons")
    assert window.terms_time_combo.currentData() == ""
    assert [
        window.terms_time_combo.itemData(index)
        for index in range(window.terms_time_combo.count())
    ] == ["", "today", "7d", "30d"]
    assert not hasattr(window, "terms_direction_combo")
    assert [
        window.terms_domain_combo.itemData(index)
        for index in range(window.terms_domain_combo.count())
    ] == [""]
    assert window.terms_domain_combo.currentData() == ""
    capture_button = window.capture_sidebar_button
    sidebar_layout = window.nav_buttons[-1].parentWidget().layout()

    assert capture_button.text() == "按下截图"
    assert capture_button.objectName() == "primaryButton"
    assert capture_button not in window.nav_buttons
    assert sidebar_layout.indexOf(capture_button) > sidebar_layout.indexOf(window.nav_buttons[-1])

    capture_button.click()
    assert started == [True]
    window.close()
    app.processEvents()


def test_review_lives_on_learning_page_not_terms_page(tmp_path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    knowledge_base = KnowledgeBase(store)
    term = knowledge_base.save_term(SaveTermCommand(term="SVD"))
    knowledge_base.set_favorite(term.id, favorite=True)

    monkeypatch.setattr(main_window_module, "HistoryStore", lambda: store)
    monkeypatch.setattr(main_window_module, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(main_window_module.MainWindow, "_build_tray", lambda self: None)
    monkeypatch.setattr(main_window_module.MainWindow, "_start_hotkey", lambda self: None)

    window = main_window_module.MainWindow()
    assert not hasattr(window, "terms_review_button")

    def review_once(dialog):
        dialog.knowledge_base.review(term.id, 2)
        return 0

    monkeypatch.setattr("app.ui.learning_page.ReviewDialog.exec", review_once)
    window.learning_page._open_review()
    assert knowledge_base.count_due_terms() == 0

    window._switch_page(2)
    assert not hasattr(window, "terms_review_button")

    window.close()
    app.processEvents()


def test_terms_filters_share_one_row_without_overlap(tmp_path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    monkeypatch.setattr(main_window_module, "HistoryStore", lambda: store)
    monkeypatch.setattr(main_window_module, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(main_window_module.MainWindow, "_build_tray", lambda self: None)
    monkeypatch.setattr(main_window_module.MainWindow, "_start_hotkey", lambda self: None)

    window = main_window_module.MainWindow()
    window._switch_page(2)
    window.show()
    for width, height in ((855, 550), (710, 455)):
        window.resize(width, height)
        app.processEvents()
        controls = [
            window.terms_search,
            window.terms_time_combo,
            window.terms_domain_combo,
        ]
        assert len({control.geometry().center().y() for control in controls}) == 1
        assert controls[0].geometry().right() < controls[1].geometry().left()
        assert controls[1].geometry().right() < controls[2].geometry().left()
        assert (
            controls[2].geometry().right()
            <= window.terms_table_card.contentsRect().right()
        )
        assert (
            window.terms_table_card.geometry().right()
            < window.terms_detail_panel.geometry().left()
        )

    window.close()
    app.processEvents()


def test_terms_page_renders_real_source_and_defaults_to_latest(tmp_path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    knowledge_base = KnowledgeBase(store)
    capture_id = store.save_capture(
        image_path="",
        source_text="SQL index avoids a full table scan",
        translation="",
        explanation="",
        domain="数据库",
    )
    knowledge_base.ingest(
        KnowledgeIngest(
            capture_id=capture_id,
            terms=[{"term": "Index", "domain": "数据库"}],
            domain="数据库",
        )
    )

    monkeypatch.setattr(main_window_module, "HistoryStore", lambda: store)
    monkeypatch.setattr(main_window_module, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(main_window_module.MainWindow, "_build_tray", lambda self: None)
    monkeypatch.setattr(main_window_module.MainWindow, "_start_hotkey", lambda self: None)

    window = main_window_module.MainWindow()
    assert window.terms_time_combo.currentData() == ""
    assert window.terms_domain_combo.currentData() == ""
    assert window.terms_domain_combo.findData("数据库") >= 0
    assert window.term_sources_list.count() == 1
    assert "SQL index avoids" in window.term_sources_list.item(0).text()

    window.close()
    app.processEvents()


def test_terms_domain_filter_uses_term_classification(tmp_path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    knowledge_base = KnowledgeBase(store)
    public_capture = store.save_capture(
        image_path="",
        source_text="Emergency management",
        translation="",
        explanation="",
        domain="公共安全",
    )
    other_capture = store.save_capture(
        image_path="",
        source_text="Dependency injection",
        translation="",
        explanation="",
        domain="编程",
    )
    knowledge_base.ingest(
        KnowledgeIngest(
            capture_id=public_capture,
            terms=[{"term": "Emergency", "domain": "公共安全"}],
            domain="公共安全",
        )
    )
    knowledge_base.ingest(
        KnowledgeIngest(
            capture_id=other_capture,
            terms=[{"term": "DependencyInjection", "domain": "编程"}],
            domain="编程",
        )
    )

    monkeypatch.setattr(main_window_module, "HistoryStore", lambda: store)
    monkeypatch.setattr(main_window_module, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(main_window_module.MainWindow, "_build_tray", lambda self: None)
    monkeypatch.setattr(main_window_module.MainWindow, "_start_hotkey", lambda self: None)

    window = main_window_module.MainWindow()
    assert window.terms_table.horizontalHeaderItem(1).text() == "领域"
    assert window.terms_domain_combo.findData("公共安全") >= 0
    assert window.terms_domain_combo.findData("编程") >= 0
    assert window.terms_table.rowCount() == 2

    window.terms_domain_combo.setCurrentIndex(
        window.terms_domain_combo.findData("公共安全")
    )
    app.processEvents()
    assert window.terms_table.rowCount() == 1
    assert window.terms_table.item(0, 0).text() == "Emergency"
    assert window.terms_table.item(0, 1).text() == "公共安全"
    assert window.terms_table.horizontalHeaderItem(1).text() == "领域"

    window.close()
    app.processEvents()


def test_resolve_term_domain_follows_current_context(tmp_path) -> None:
    from app.ui.workers import _resolve_term_domain

    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)

    assert _resolve_term_domain(settings_service.load(), store) == "通用"

    context_id = store.save_context(name="生物", domain="生物", scene="通用")
    settings_service.set_current_context(context_id)
    assert _resolve_term_domain(settings_service.load(), store) == "生物"

    builtin = next(c for c in store.list_contexts() if c.builtin)
    settings_service.set_current_context(builtin.id)
    assert _resolve_term_domain(settings_service.load(), store) == "通用"
