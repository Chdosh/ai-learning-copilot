"""统计图表组件测试：纯函数映射 + offscreen 渲染冒烟。"""
from __future__ import annotations

import os
from datetime import date, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.statistics_widgets import (
    ActivityHeatmap,
    CategoryDonut,
    bucket_categories,
    heat_level,
    learning_streak,
)


def test_heat_level_mapping():
    assert heat_level(0, 10) == 0
    assert heat_level(5, 0) == 0  # 无数据时全为空格子
    assert heat_level(1, 8) == 1
    assert heat_level(8, 8) == 4
    assert heat_level(4, 8) == 2
    # 超出最大值也封顶在第 4 档
    assert heat_level(99, 8) == 4


def test_bucket_categories_merges_tail():
    small = {"报错": 3, "Python": 2}
    assert bucket_categories(small) == [("报错", 3), ("Python", 2)]

    many = {f"分类{i}": 10 - i for i in range(9)}
    merged = bucket_categories(many)
    assert len(merged) == 6
    assert merged[-1][0] == "其他"
    assert merged[-1][1] == sum(10 - i for i in range(5, 9))
    # 除"其他"外保持降序
    head = [v for _, v in merged[:-1]]
    assert head == sorted(head, reverse=True)


def test_bucket_categories_zero_values_dropped():
    assert bucket_categories({"报错": 0, "Python": 2}) == [("Python", 2)]


def test_learning_streak_counts_backwards():
    today = date.today()
    daily = {
        (today - timedelta(days=0)).isoformat(): 1,
        (today - timedelta(days=1)).isoformat(): 2,
        (today - timedelta(days=2)).isoformat(): 3,
        # days 3/4 空档
        (today - timedelta(days=5)).isoformat(): 1,
    }
    assert learning_streak(daily) == 3


def test_learning_streak_today_gap_does_not_break():
    yesterday = date.today() - timedelta(days=1)
    daily = {yesterday.isoformat(): 1}
    assert learning_streak(daily) == 1
    assert learning_streak({}) == 0


def test_heatmap_set_data_and_render():
    app = QApplication.instance() or QApplication([])
    widget = ActivityHeatmap()
    today = date.today()
    data = {(today - timedelta(days=i)).isoformat(): i % 7 for i in range(90)}
    widget.set_data(data)
    widget.resize(widget.minimumSize())
    pixmap = widget.grab()  # 强制执行 paintEvent
    assert not pixmap.isNull()
    assert app is not None


def test_donut_set_data_and_render_empty_and_full():
    app = QApplication.instance() or QApplication([])
    widget = CategoryDonut()
    widget.resize(360, 176)
    assert not widget.grab().isNull()  # 空数据占位文案路径

    widget.set_data({"报错": 12, "AI概念": 8, "文档": 3})
    assert widget.slices[0] == ("报错", 12)
    assert not widget.grab().isNull()
    assert app is not None
