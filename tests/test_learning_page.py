"""学习页（知识资产行动入口）测试：今日复习与学习建议清单。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from app.services.history_store import HistoryStore
from app.services.knowledge_base import (
    KnowledgeBase,
    KnowledgeIngest,
    SaveTermCommand,
    TipQuery,
)
from app.services.settings import SettingsService
from app.ui.learning_page import LearningPage
from app.ui.theme import CARD


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


def _accumulation_source_buttons(page: LearningPage) -> list[QPushButton]:
    return [
        button
        for button in page.accumulation_list.findChildren(QPushButton)
        if button.property("capture_id") is not None
    ]


def test_learning_page_puts_accumulation_before_review_and_tips(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store, service, kb, page = _page(tmp_path)

    assert page.content_layout.indexOf(page.accumulation_card) == 0
    assert page.content_layout.indexOf(page.right_panel) == 1
    assert page.right_layout.indexOf(page.review_card) == 0
    assert page.right_layout.indexOf(page.tips_card) == 1
    assert page.content_widget.maximumWidth() == 1180

    page.deleteLater()
    app.processEvents()


def test_learning_filter_popup_has_explicit_white_background(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store, service, kb, page = _page(tmp_path)
    page.show()
    page.tips_scope_combo.showPopup()
    app.processEvents()

    view = page.tips_scope_combo.view()
    assert view.palette().color(QPalette.ColorRole.Base) == QColor(CARD)
    assert view.viewport().palette().color(QPalette.ColorRole.Base) == QColor(CARD)
    assert CARD in view.window().styleSheet()

    page.tips_scope_combo.hidePopup()
    page.deleteLater()
    app.processEvents()


def test_learning_page_renders_recent_accumulation_and_emits_source(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store, service, kb, page = _page(tmp_path)
    capture_id = store.save_capture(
        image_path="",
        source_text="SQL index avoids a full table scan",
        translation="索引避免全表扫描",
        explanation="数据库索引说明",
        domain="数据库",
    )
    kb.ingest(
        KnowledgeIngest(
            capture_id=capture_id,
            terms=[
                {
                    "term": "Index",
                    "chinese_name": "索引",
                    "beginner_explanation": "帮助数据库更快定位数据。",
                    "domain": "数据库",
                }
            ],
            domain="数据库",
        )
    )

    selected: list[int] = []
    page.capture_selected.connect(selected.append)
    page.refresh()
    app.processEvents()

    visible_text = "\n".join(
        label.text() for label in page.accumulation_list.findChildren(QLabel)
    )
    assert "Index（索引）" in visible_text
    assert "帮助数据库更快定位数据。" in visible_text
    assert "数据库 · 积累于 " in visible_text
    assert "1 条来源" in visible_text
    assert "来自 1 条学习记录" in visible_text

    source_buttons = _accumulation_source_buttons(page)
    assert len(source_buttons) == 1
    assert "SQL index avoids a full table scan" in source_buttons[0].text()
    source_buttons[0].click()
    assert selected == [capture_id]

    page.deleteLater()
    app.processEvents()


def test_learning_page_does_not_repeat_identical_term_names(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store, service, kb, page = _page(tmp_path)
    capture_id = store.save_capture(
        image_path="",
        source_text="重试幂等",
        translation="",
        explanation="",
        domain="计算机科学",
    )
    kb.ingest(
        KnowledgeIngest(
            capture_id=capture_id,
            terms=[
                {
                    "term": "幂等",
                    "chinese_name": "幂等",
                    "beginner_explanation": "重复执行结果一致。",
                    "domain": "计算机科学",
                }
            ],
            domain="计算机科学",
        )
    )

    page.refresh()
    app.processEvents()
    first_row = page.accumulation_list_layout.itemAt(0).widget()
    title = first_row.findChildren(QLabel)[0]
    assert title.text() == "幂等"
    assert "·" not in title.text()
    assert "border: none" in first_row.styleSheet()
    source_button = _accumulation_source_buttons(page)[0]
    assert "border: none" in source_button.styleSheet()

    page.deleteLater()
    app.processEvents()


def test_learning_page_related_terms_expand_and_collapse(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store, service, kb, page = _page(tmp_path)
    capture_id = store.save_capture(
        image_path="",
        source_text="overfitting and regularization",
        translation="过拟合与正则化",
        explanation="",
        domain="AI概念",
    )
    kb.ingest(
        KnowledgeIngest(
            capture_id=capture_id,
            terms=[
                {"term": "overfitting", "chinese_name": "过拟合", "domain": "AI概念"},
                {"term": "regularization", "chinese_name": "正则化", "domain": "AI概念"},
            ],
            domain="AI概念",
        )
    )

    page.show()
    page.refresh()
    app.processEvents()

    related_buttons = [
        button
        for button in page.accumulation_list.findChildren(QPushButton)
        if button.property("related") is True
    ]
    assert len(related_buttons) == 2  # 两条积累各有一个"相关知识"

    related_buttons[0].click()
    app.processEvents()
    # 展开的积累行内出现相关术语与理由
    visible_labels = [
        label.text()
        for label in page.accumulation_list.findChildren(QLabel)
        if label.isVisible()
    ]
    assert any(
        "regularization" in text and "共同出现在 1 条学习记录" in text
        for text in visible_labels
    )
    assert related_buttons[0].text() == "收起相关知识"

    related_buttons[0].click()
    app.processEvents()
    assert related_buttons[0].text() == "相关知识"
    page.deleteLater()
    app.processEvents()


def test_learning_page_recommendations_render_and_ignore(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store, service, kb, page = _page(tmp_path)
    first = store.save_capture(
        image_path="",
        source_text="termA with termB",
        translation="",
        explanation="",
        domain="AI概念",
    )
    second = store.save_capture(
        image_path="",
        source_text="termB with termC",
        translation="",
        explanation="",
        domain="AI概念",
    )
    kb.ingest(
        KnowledgeIngest(
            capture_id=first,
            terms=[
                {"term": "termA", "chinese_name": "甲", "domain": "AI概念"},
                {"term": "termB", "chinese_name": "乙", "domain": "AI概念"},
            ],
            domain="AI概念",
        )
    )
    kb.ingest(
        KnowledgeIngest(
            capture_id=second,
            terms=[
                {"term": "termB", "chinese_name": "乙", "domain": "AI概念"},
                {"term": "termC", "chinese_name": "丙", "domain": "AI概念"},
            ],
            domain="AI概念",
        )
    )

    page.show()
    page.refresh()
    app.processEvents()

    # termA 行展开：推荐区出现二阶推荐 termC
    terma_button = next(
        button
        for button in page.accumulation_list.findChildren(QPushButton)
        if button.property("related") is True
        and button.parentWidget() is not None
        and "termA" in button.parentWidget().findChildren(QLabel)[0].text()
    )
    terma_button.click()
    app.processEvents()

    visible_labels = [
        label.text()
        for label in page.accumulation_list.findChildren(QLabel)
        if label.isVisible()
    ]
    assert any(
        "termC" in text and "通过" in text and "termB" in text
        for text in visible_labels
    )

    ignore_buttons = [
        button
        for button in page.accumulation_list.findChildren(QPushButton)
        if button.property("recommendation_ignore") is True
    ]
    assert ignore_buttons
    ignore_buttons[0].click()
    app.processEvents()
    # 忽略后该推荐行立即消失
    remaining = [
        button
        for button in page.accumulation_list.findChildren(QPushButton)
        if button.property("recommendation_ignore") is True
        and button.isVisible()
    ]
    assert len(remaining) == len(ignore_buttons) - 1
    page.deleteLater()
    app.processEvents()


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


def test_learning_page_all_tips_includes_non_pending_items(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store, service, kb, page = _page(tmp_path)

    for source, tip in (
        ("first", "pending-tip"),
        ("second", "done-tip"),
    ):
        capture_id = store.save_capture(
            image_path="",
            source_text=source,
            translation="test",
            explanation="explanation",
        )
        kb.ingest(
            KnowledgeIngest(
                capture_id=capture_id,
                terms=[],
                learning_tip=tip,
                domain="AI",
            )
        )

    done_tip = next(
        tip
        for tip in kb.list_tips(TipQuery(status="pending"))
        if tip.content == "done-tip"
    )
    kb.set_tip_status(done_tip.id, "done")

    page.tips_scope_combo.setCurrentIndex(page.tips_scope_combo.findData(""))
    visible_text = "\n".join(
        label.text() for label in page.tips_list.findChildren(QLabel)
    )
    assert "pending-tip" in visible_text
    assert "done-tip" in visible_text

    page.deleteLater()
    app.processEvents()


def test_learning_page_has_no_digest_into_direction(tmp_path) -> None:
    """沉淀只进知识库：学习页不得存在任何写回学习方向的自沉淀入口。"""
    app = QApplication.instance() or QApplication([])
    store, service, kb, page = _page(tmp_path)

    for attribute in ("digest_button", "digest_status_label", "_start_digest", "_digest_worker"):
        assert not hasattr(page, attribute), f"learning page still exposes {attribute}"
    page.deleteLater()
    app.processEvents()
