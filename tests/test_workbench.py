from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from app.services.history_store import HistoryStore
from app.services.settings import AppSettings, SettingsService
from app.ui.context_dialog import ContextEditDialog
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


def test_context_dialog_detects_and_saves_as_current(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    text = "本研究摘要：我们利用 CRISPR 对细胞进行了基因编辑实验，分析了 DNA 序列与蛋白质表达的关系。" * 3

    dialog = ContextEditDialog(
        store, settings_service, AppSettings(), prefill_text=text
    )
    assert dialog.domain_input.currentText() == "生物"
    assert dialog.scene_input.currentText() == "学术论文"

    dialog._save()
    assert dialog.result() == QDialog.DialogCode.Accepted

    custom = [context for context in store.list_contexts() if not context.builtin]
    assert len(custom) == 1
    assert settings_service.load().current_context_id == custom[0].id
    dialog.deleteLater()
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


def test_workbench_learn_mode_toggle_and_text_learn(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    workbench = WorkbenchPage(store, SettingsService(store))

    received: list[str] = []
    workbench.text_learn.connect(received.append)
    screenshots: list = []
    workbench.request_screenshot.connect(lambda: screenshots.append(1))

    assert workbench.learn_stack.currentIndex() == 0
    assert workbench.mode_screenshot_btn.isChecked()

    workbench.mode_text_btn.click()
    assert workbench.learn_stack.currentIndex() == 1
    assert workbench.mode_text_btn.isChecked()
    assert not workbench.mode_screenshot_btn.isChecked()

    workbench.learn_text_input.setPlainText("hello world")
    workbench.learn_button.click()
    assert received == ["hello world"]
    assert workbench.learn_text_input.toPlainText() == ""

    workbench.mode_screenshot_btn.click()
    assert workbench.learn_stack.currentIndex() == 0
    workbench.screenshot_button.click()
    assert screenshots == [1]

    workbench.deleteLater()
    app.processEvents()


def test_workbench_direction_switch_creates_and_reuses(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    workbench = WorkbenchPage(store, settings_service)

    assert "通用" in [workbench.direction_combo.itemText(i) for i in range(workbench.direction_combo.count())]
    assert "生物" in [workbench.direction_combo.itemText(i) for i in range(workbench.direction_combo.count())]

    changed: list = []
    workbench.context_changed.connect(changed.append)

    bio_index = workbench.direction_combo.findText("生物")
    workbench.direction_combo.setCurrentIndex(bio_index)
    current = settings_service.load().current_context_id
    assert current is not None
    assert store.get_context(current).domain == "生物"
    assert changed == [current]

    workbench._switch_direction("生物")
    bio_domains = [c.domain for c in store.list_contexts() if not c.builtin]
    assert bio_domains.count("生物") == 1

    workbench._switch_direction("通用")
    assert settings_service.load().current_context_id is None

    workbench.deleteLater()
    app.processEvents()


def test_workbench_direction_prefers_existing_context(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "app.db")
    settings_service = SettingsService(store)
    custom = store.save_context(name="生物论文", domain="生物", scene="学术论文")

    workbench = WorkbenchPage(store, settings_service)
    workbench._switch_direction("生物")

    assert settings_service.load().current_context_id == custom
    workbench.deleteLater()
    app.processEvents()


def test_workbench_detail_box_shows_current_context(tmp_path) -> None:
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

    workbench = WorkbenchPage(store, settings_service)
    detail = workbench.context_detail_label.text()
    assert "CRISPR 基因编辑" in detail
    assert "术语给中文对照" in detail

    workbench._switch_direction("通用")
    assert "通用" in workbench.context_detail_label.text()
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
