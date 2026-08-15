"""学习页（知识资产行动入口）测试：今日复习、学习建议清单、自沉淀。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from app.services.history_store import HistoryStore
from app.services.knowledge_base import (
    KnowledgeBase,
    KnowledgeIngest,
    SaveTermCommand,
    TipQuery,
)
from app.services.settings import SettingsService
from app.ui.learning_page import LearningPage


def _page(tmp_path):
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store)
    knowledge_base = KnowledgeBase(store)
    page = LearningPage(store, service, knowledge_base)
    return store, service, knowledge_base, page


def _tip_buttons(page: LearningPage) -> list[QPushButton]:
    """Pending tips 行的动作按钮（完成/忽略）。"""
    buttons: list[QPushButton] = []
    for index in range(page.tips_list_layout.count()):
        row = page.tips_list_layout.itemAt(index).widget()
        if row is None:
            continue
        buttons.extend(row.findChildren(QPushButton))
    return buttons


def test_learning_page_shows_due_review_count(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store, service, kb, page = _page(tmp_path)

    assert "待复习" in page.due_label.text()
    term = kb.save_term(SaveTermCommand(term="SVD", chinese_name="奇异值分解"))
    kb.set_favorite(term.id, favorite=True)

    page.refresh()
    assert "1 个术语待复习" in page.due_label.text()
    assert page.review_button.text() == "开始复习 (1)"

    kb.set_favorite(term.id, favorite=False)
    page.refresh()
    assert page.review_button.text() == "开始复习"
    page.deleteLater()
    app.processEvents()


def test_learning_page_tips_lifecycle(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store, service, kb, page = _page(tmp_path)

    capture_id = store.save_capture(
        image_path="",
        source_text="test",
        translation="测试",
        explanation="解释",
    )
    kb.ingest(
        KnowledgeIngest(
            capture_id=capture_id,
            terms=[],
            learning_tip="延伸概念：正则化——防止过拟合",
            domain="AI概念",
        )
    )

    page.refresh_tips()
    buttons = _tip_buttons(page)
    assert len(buttons) == 2  # 完成 / 忽略

    tip_id = kb.list_tips(TipQuery(status="pending"))[0].id
    page._set_tip_status(tip_id, "done")
    assert kb.count_tips("pending") == 0
    assert kb.count_tips("done") == 1
    assert _tip_buttons(page) == []  # 已完成的建议不再有操作按钮
    page.deleteLater()
    app.processEvents()


def test_learning_page_digest_requires_saved_direction(tmp_path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    store, service, kb, page = _page(tmp_path)

    messages: list[str] = []

    def fake_information(parent, title, text, *args, **kwargs):
        messages.append((title, text))

    monkeypatch.setattr(QMessageBox, "information", staticmethod(fake_information))

    page._start_digest()
    assert messages
    assert "自沉淀" in messages[0][0]
    assert "学习方向" in messages[0][1]
    assert "已取消" not in page.digest_status_label.text()
    page.deleteLater()
    app.processEvents()


def test_learning_page_digest_with_saved_direction_reports_no_new_content(
    tmp_path, monkeypatch
) -> None:
    app = QApplication.instance() or QApplication([])
    store, service, kb, page = _page(tmp_path)

    context_id = store.save_context(name="生物", domain="生物", scene="通用")
    service.set_current_context(context_id)

    messages: list[str] = []

    def fake_information(parent, title, text, *args, **kwargs):
        messages.append((title, text))

    monkeypatch.setattr(QMessageBox, "information", staticmethod(fake_information))

    page._start_digest()
    assert messages
    assert "暂无新内容" in messages[0][1]
    page.deleteLater()
    app.processEvents()
