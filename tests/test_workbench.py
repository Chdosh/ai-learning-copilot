from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import app.ui.main_window as main_window_module
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollArea

from app.services.history_store import HistoryStore
from app.services.knowledge_base import KnowledgeBase
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
    store.upsert_terms([{"term": "Token", "chinese_name": "文本单位", "beginner_explanation": "计量单位", "examples": []}])
    return capture_id


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


def test_overview_domain_filter_changes_the_visible_session_records(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    medical_id = store.save_capture(
        image_path="",
        source_text="患者需要临床治疗",
        translation="",
        explanation="",
        domain="医学",
    )
    store.save_capture(
        image_path="",
        source_text="Python exception traceback",
        translation="",
        explanation="",
        domain="编程",
    )
    store.save_capture(
        image_path="",
        source_text="普通内容",
        translation="",
        explanation="",
        domain="通用",
    )
    overview = OverviewPage(store, settings_service)
    assert overview.session_list.count() == 3

    overview.domain_filter_combo.setCurrentIndex(
        overview.domain_filter_combo.findData("医学")
    )
    assert overview.session_list.count() == 1
    assert overview.session_list.item(0).data(Qt.ItemDataRole.UserRole) == medical_id

    overview.domain_filter_combo.setCurrentIndex(
        overview.domain_filter_combo.findData("编程")
    )
    assert overview.session_list.count() == 1
    assert "Python" in overview.session_list.item(0).text()

    overview.domain_filter_combo.setCurrentIndex(0)
    assert overview.session_list.count() == 3
    assert settings_service.load().current_context_id is None

    overview.deleteLater()
    app.processEvents()


def test_workbench_save_creates_context_and_sets_current(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    workbench = WorkbenchPage(store, settings_service, KnowledgeBase(store))

    assert settings_service.load().current_context_id is None
    assert "通用" in [workbench.domain_combo.itemText(i) for i in range(workbench.domain_combo.count())]
    assert "生物" in [workbench.domain_combo.itemText(i) for i in range(workbench.domain_combo.count())]

    changed: list = []
    workbench.context_changed.connect(changed.append)

    workbench.domain_combo.setCurrentText("生物")
    workbench.scene_combo.setCurrentText("学术论文")
    workbench.summary_input.setPlainText("CRISPR 基因编辑")
    workbench.instruction_input.setText("术语给中文对照")
    workbench.apply_direction_button.click()

    current = settings_service.load().current_context_id
    assert current is not None
    context = store.get_context(current)
    assert context.domain == "生物"
    assert context.scene == "学术论文"
    assert context.summary == "CRISPR 基因编辑"
    assert context.instruction == "术语给中文对照"
    assert context.name == "生物 · 学术论文"
    assert changed == [current]

    workbench.apply_direction_button.click()
    non_builtin = [c for c in store.list_contexts() if not c.builtin]
    assert len(non_builtin) == 1
    assert non_builtin[0].id == current
    assert changed == [current, current]

    workbench.reset_direction_button.click()
    assert settings_service.load().current_context_id is None
    assert changed[-1] is None

    workbench.deleteLater()
    app.processEvents()


def test_workbench_save_never_updates_unselected_record(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    existing_id = store.save_context(
        name="生物 · 学术论文",
        domain="生物",
        scene="学术论文",
        summary="CRISPR 基因编辑",
    )

    workbench = WorkbenchPage(store, settings_service, KnowledgeBase(store))
    workbench.domain_combo.setCurrentText("生物")
    workbench.scene_combo.setCurrentText("技术文档")
    workbench.summary_input.setPlainText("串口协议手册")
    workbench.apply_direction_button.click()

    non_builtin = [c for c in store.list_contexts() if not c.builtin]
    assert len(non_builtin) == 2
    existing = store.get_context(existing_id)
    assert existing.scene == "学术论文"
    assert existing.summary == "CRISPR 基因编辑"
    assert settings_service.load().current_context_id != existing_id
    workbench.deleteLater()
    app.processEvents()


def test_workbench_same_domain_different_scenes_coexist(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    workbench = WorkbenchPage(store, settings_service, KnowledgeBase(store))

    workbench.domain_combo.setCurrentText("生物")
    workbench.scene_combo.setCurrentText("学术论文")
    workbench.summary_input.setPlainText("CRISPR 基因编辑")
    workbench.apply_direction_button.click()
    paper_id = settings_service.load().current_context_id
    assert store.get_context(paper_id).name == "生物 · 学术论文"

    workbench.scene_combo.setCurrentText("技术文档")
    workbench.summary_input.setPlainText("串口协议手册")
    workbench.save_as_new_button.click()
    doc_id = settings_service.load().current_context_id
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


def test_workbench_direction_fields_load_current_context(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    context_id = store.save_context(
        name="生物论文",
        domain="生物",
        scene="学术论文",
        summary="CRISPR 基因编辑",
        instruction="术语给中文对照",
    )
    settings_service.set_current_context(context_id)

    workbench = WorkbenchPage(store, settings_service, KnowledgeBase(store))
    assert workbench.domain_combo.currentText() == "生物"
    assert workbench.scene_combo.currentText() == "学术论文"
    assert "CRISPR 基因编辑" in workbench.summary_input.toPlainText()
    assert "术语给中文对照" in workbench.instruction_input.text()

    workbench.reset_direction_button.click()
    assert workbench.quick_domain_combo.currentText() == "通用"
    assert workbench.quick_scene_combo.currentText() == "通用"
    assert workbench.domain_combo.currentText() == "生物"
    workbench.deleteLater()
    app.processEvents()


def test_workbench_edit_only_updates_selected_id(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    a_id = store.save_context(
        name="生物 · 学术论文",
        domain="生物",
        scene="学术论文",
        summary="CRISPR 基因编辑",
    )
    b_id = store.save_context(name="编程", domain="编程", scene="通用", summary="Python")
    settings_service.set_current_context(a_id)

    workbench = WorkbenchPage(store, settings_service, KnowledgeBase(store))
    workbench._edit_direction(b_id)
    workbench.domain_combo.setCurrentText("医学")
    workbench.apply_direction_button.click()

    assert settings_service.load().current_context_id == b_id
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
    settings_service = SettingsService(store)
    a_id = store.save_context(
        name="生物 · 学术论文",
        domain="生物",
        scene="学术论文",
        summary="CRISPR 基因编辑",
    )
    b_id = store.save_context(name="编程", domain="编程", scene="通用", summary="Python")
    settings_service.set_current_context(a_id)

    workbench = WorkbenchPage(store, settings_service, KnowledgeBase(store))
    workbench._switch_to(b_id)
    assert settings_service.load().current_context_id == b_id
    assert store.get_context(a_id).summary == "CRISPR 基因编辑"
    assert store.get_context(a_id).domain == "生物"
    assert store.get_context(b_id).domain == "编程"
    assert workbench.direction_status_label.text() == "编程"

    workbench._switch_to(None)
    assert settings_service.load().current_context_id is None
    assert workbench.direction_status_label.text() == "通用"
    workbench.deleteLater()
    app.processEvents()


def test_workbench_draft_does_not_affect_effective_direction(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    workbench = WorkbenchPage(store, settings_service, KnowledgeBase(store))

    workbench.domain_combo.setCurrentText("生物")
    workbench.scene_combo.setCurrentText("学术论文")
    workbench.apply_direction_button.click()
    bio_id = settings_service.load().current_context_id

    workbench.edit_direction_button.click()
    workbench.domain_combo.setCurrentText("医学")

    assert settings_service.load().current_context_id == bio_id
    assert not workbench.draft_warning_label.isHidden()
    assert workbench.direction_status_label.text() == "生物 · 学术论文"
    assert "医学" not in workbench.direction_status_label.text()

    workbench.refresh_directions()
    assert workbench.domain_combo.currentText() == "医学"

    workbench.cancel_edit_button.click()
    assert workbench.domain_combo.currentText() == "生物"
    assert workbench.scene_combo.currentText() == "学术论文"
    assert workbench.draft_warning_label.isHidden()
    assert workbench._form_open
    workbench.deleteLater()
    app.processEvents()


def test_workbench_direction_operations_are_visible_and_selector_switches(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    bio_id = store.save_context(name="生物论文", domain="生物", scene="学术论文")
    code_id = store.save_context(name="Python 文档", domain="编程", scene="技术文档")
    settings_service.set_current_context(bio_id)

    workbench = WorkbenchPage(store, settings_service, KnowledgeBase(store))
    assert workbench.direction_selector.findData(bio_id) >= 0
    assert workbench.direction_selector.findData(code_id) >= 0
    assert workbench.new_direction_button.text() == "新建"
    assert workbench.edit_direction_button.text() == "编辑"
    assert workbench.delete_direction_button.text() == "删除"
    assert workbench.reset_direction_button.text() == "恢复通用"

    workbench.direction_selector.setCurrentIndex(workbench.direction_selector.findData(code_id))
    assert settings_service.load().current_context_id == code_id
    assert workbench.direction_status_label.text() == "编程 · 技术文档"
    assert store.get_context(bio_id).domain == "生物"
    assert store.get_context(code_id).domain == "编程"
    workbench.deleteLater()
    app.processEvents()


def test_workbench_quick_direction_applies_without_creating_custom_record(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    workbench = WorkbenchPage(store, settings_service, KnowledgeBase(store))
    before = [item for item in store.list_contexts() if not item.builtin]

    workbench.quick_domain_combo.setCurrentText("生物")
    workbench.quick_scene_combo.setCurrentText("学术论文")
    workbench.apply_quick_button.click()

    settings = settings_service.load()
    assert settings.current_context_id is None
    assert "领域：生物" in settings.context_block
    assert "场景：学术论文" in settings.context_block
    assert workbench.direction_status_label.text() == "生物 · 学术论文"
    assert [item for item in store.list_contexts() if not item.builtin] == before
    workbench.deleteLater()
    app.processEvents()


def test_main_window_context_change_keeps_applied_quick_direction(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    workbench = WorkbenchPage(store, settings_service, KnowledgeBase(store))

    class ContextChangeReceiver:
        def __init__(self) -> None:
            self.settings_service = settings_service
            self.settings = settings_service.load()

        def _apply_current_context(self) -> None:
            self.settings = self.settings_service.load()

        _on_context_changed = MainWindow._on_context_changed

    receiver = ContextChangeReceiver()
    workbench.context_changed.connect(receiver._on_context_changed)

    workbench.quick_domain_combo.setCurrentText("生物")
    workbench.quick_scene_combo.setCurrentText("学术论文")
    workbench.apply_quick_button.click()

    assert settings_service.get_quick_context() == ("生物", "学术论文")
    assert workbench.direction_status_label.text() == "生物 · 学术论文"
    workbench.deleteLater()
    app.processEvents()


def test_custom_direction_stays_selected_when_clicking_quick_apply(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    context_id = store.save_context(
        name="生物 · 学术论文",
        domain="生物",
        scene="学术论文",
        summary="CRISPR 基因编辑",
    )
    workbench = WorkbenchPage(store, settings_service, KnowledgeBase(store))

    workbench.direction_selector.setCurrentIndex(
        workbench.direction_selector.findData(context_id)
    )
    workbench.apply_quick_button.click()

    assert settings_service.load().current_context_id == context_id
    assert workbench.direction_status_label.text() == "生物 · 学术论文"
    assert workbench.quick_domain_combo.currentText() == "生物"
    assert workbench.quick_scene_combo.currentText() == "学术论文"
    workbench.deleteLater()
    app.processEvents()


def test_custom_direction_can_switch_to_changed_quick_values(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    context_id = store.save_context(
        name="生物 · 学术论文",
        domain="生物",
        scene="学术论文",
        summary="CRISPR 基因编辑",
    )
    workbench = WorkbenchPage(store, settings_service, KnowledgeBase(store))

    workbench.direction_selector.setCurrentIndex(
        workbench.direction_selector.findData(context_id)
    )
    workbench.quick_domain_combo.setCurrentText("医学")
    workbench.apply_quick_button.click()

    assert settings_service.load().current_context_id is None
    assert settings_service.get_quick_context() == ("医学", "学术论文")
    assert workbench.direction_status_label.text() == "医学 · 学术论文"
    workbench.deleteLater()
    app.processEvents()


def test_workbench_abstract_analysis_fills_custom_context_and_enters_prompt(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    workbench = WorkbenchPage(store, settings_service, KnowledgeBase(store))
    abstract = (
        "本研究使用 CRISPR 基因编辑分析细胞 DNA 突变与蛋白质表达。"
        "实验方法、样本、结果和结论显示该基因影响细胞功能。"
    )

    workbench.new_direction_button.click()
    workbench.context_source_input.setPlainText(abstract)
    workbench.analyze_context_button.click()

    assert workbench.domain_combo.currentText() == "生物"
    assert workbench.scene_combo.currentText() == "学术论文"
    assert "核心关键词" in workbench.summary_input.toPlainText()
    assert "摘要概述" in workbench.summary_input.toPlainText()
    assert "保存后才会用于回答" in workbench.context_analysis_label.text()
    assert settings_service.load().current_context_id is None

    workbench.apply_direction_button.click()
    settings = settings_service.load()
    assert settings.current_context_id is not None
    assert "领域：生物" in settings.context_block
    assert "场景：学术论文" in settings.context_block
    assert "核心关键词" in settings.context_block
    assert "CRISPR" in settings.context_block
    workbench.deleteLater()
    app.processEvents()


def test_workbench_editor_keeps_explicit_target_when_current_direction_changes(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    bio_id = store.save_context(name="生物论文", domain="生物", scene="学术论文")
    code_id = store.save_context(name="Python 文档", domain="编程", scene="技术文档")
    settings_service.set_current_context(bio_id)
    workbench = WorkbenchPage(store, settings_service, KnowledgeBase(store))

    workbench.edit_direction_button.click()
    workbench.summary_input.setPlainText("尚未保存的生物草稿")
    workbench.direction_selector.setCurrentIndex(workbench.direction_selector.findData(code_id))

    assert settings_service.load().current_context_id == code_id
    assert workbench._editing_context_id == bio_id
    assert "生物论文" in workbench.editing_target_label.text()
    assert workbench.summary_input.toPlainText() == "尚未保存的生物草稿"
    assert workbench.direction_status_label.text() == "编程 · 技术文档"
    workbench.deleteLater()
    app.processEvents()


def test_workbench_custom_names_and_duplicate_names_remain_distinguishable(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    workbench = WorkbenchPage(store, settings_service, KnowledgeBase(store))

    workbench.new_direction_button.click()
    workbench.name_input.setText("考试重点")
    workbench.domain_combo.setCurrentText("生物")
    workbench.apply_direction_button.click()
    first_id = settings_service.load().current_context_id

    workbench.new_direction_button.click()
    workbench.name_input.setText("考试重点")
    workbench.domain_combo.setCurrentText("医学")
    workbench.apply_direction_button.click()
    second_id = settings_service.load().current_context_id

    assert first_id != second_id
    assert store.get_context(first_id).name == "考试重点"
    assert store.get_context(second_id).name == "考试重点"
    first_label = workbench.direction_selector.itemText(
        workbench.direction_selector.findData(first_id)
    )
    second_label = workbench.direction_selector.itemText(
        workbench.direction_selector.findData(second_id)
    )
    assert first_label != second_label
    assert f"#{first_id}" in first_label
    assert f"#{second_id}" in second_label
    assert not workbench._repair_proposals()
    workbench.deleteLater()
    app.processEvents()


def test_workbench_repairing_current_direction_emits_context_changed(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    context_id = store.save_context(name="生物", domain="通用", scene="技术文档")
    settings_service.set_current_context(context_id)
    workbench = WorkbenchPage(store, settings_service, KnowledgeBase(store))
    changed: list = []
    workbench.context_changed.connect(changed.append)

    proposal = next(
        item for item in workbench._repair_proposals() if item["record"].id == context_id
    )
    workbench._apply_repair([proposal])

    assert changed == [context_id]
    assert workbench.direction_status_label.text() == "生物 · 技术文档"
    workbench.deleteLater()
    app.processEvents()


def test_workbench_mismatch_proposals_and_repair(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    bad_id = store.save_context(name="生物", domain="通用", scene="技术文档")
    parse_id = store.save_context(name="编程 · 学术论文", domain="医学", scene="学术论文")
    good_id = store.save_context(name="化学", domain="化学", scene="通用")

    workbench = WorkbenchPage(store, settings_service, KnowledgeBase(store))
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


def test_workbench_no_longer_contains_recognition_module(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    workbench = WorkbenchPage(store, SettingsService(store), KnowledgeBase(store))

    assert not hasattr(workbench, "learn_stack")
    assert not hasattr(workbench, "mode_screenshot_btn")
    assert hasattr(workbench, "direction_edit_card")

    workbench.deleteLater()
    app.processEvents()


def test_sidebar_screenshot_action_is_below_settings(tmp_path, monkeypatch) -> None:
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
    settings_button = window.nav_buttons[-1]
    capture_button = window.capture_sidebar_button
    sidebar_layout = settings_button.parentWidget().layout()

    assert settings_button.text() == "设置"
    assert capture_button.text() == "按下截图"
    assert capture_button.objectName() == "primaryButton"
    assert capture_button not in window.nav_buttons
    assert sidebar_layout.indexOf(capture_button) > sidebar_layout.indexOf(settings_button)

    capture_button.click()
    assert started == [True]
    window.close()
    app.processEvents()


def test_workbench_shows_current_direction_on_the_left(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    workbench = WorkbenchPage(store, SettingsService(store), KnowledgeBase(store))

    columns = workbench.findChild(QScrollArea).widget().layout()
    assert columns.itemAt(0).widget().layout().itemAt(0).widget() is workbench.direction_status_card
    assert columns.itemAt(1).widget().layout().itemAt(0).widget() is workbench.direction_edit_card

    workbench.deleteLater()
    app.processEvents()


def test_custom_direction_inputs_use_a_full_width_row(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    workbench = WorkbenchPage(store, SettingsService(store), KnowledgeBase(store))

    assert workbench.domain_custom.minimumWidth() >= 120
    assert workbench.scene_custom.minimumWidth() >= 120
    assert workbench.domain_row is not None
    assert workbench.scene_row is not None
    assert workbench.domain_row.__class__.__name__ == "QVBoxLayout"
    assert workbench.scene_row.__class__.__name__ == "QVBoxLayout"

    workbench.deleteLater()
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
