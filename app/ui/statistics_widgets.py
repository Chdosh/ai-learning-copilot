"""统计图表组件：QPainter 自绘，无第三方图表库。

包含：
- ActivityHeatmap  GitHub 风格活跃度热力图（近 90 天，列=周、行=星期）
- CategoryDonut    分类构成环形图（含右侧图例）

设计要点：
- 颜色全部取自 theme.py token（热力图为 PRIMARY 蓝的 5 级色阶）；
- 数据为空时绘制居中占位文案，不画空坐标轴；
- 热力图单元格带 tooltip；分类超过 5 个时自动合并为"其他"。
"""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from app.ui.theme import (
    BORDER_LIGHT,
    CARD,
    CHART_CATEGORICAL,
    CHART_HEAT_LEVELS,
    FONT_MICRO,
    MUTED,
    TEXT,
    TEXT_SECONDARY,
)

CELL = 13          # 热力图格子边长
GAP = 3            # 格子间距
PITCH = CELL + GAP
WEEKS = 14         # 列数：90 天 ≈ 13 周，留一列余量
LABEL_W = 22       # 左侧星期标签宽
LABEL_H = 16       # 顶部月份标签高

WEEKDAY_LABELS = {0: "一", 2: "三", 4: "五", 6: "日"}

MAX_PIE_SLICES = 5  # 图例最多展示的分类数，其余并入"其他"


def heat_level(count: int, max_count: int) -> int:
    """把某天记录数映射到 0-4 强度档位（0 为空格子）。"""
    if count <= 0 or max_count <= 0:
        return 0
    # 非零天数按最大值均分 4 档，至少落在第 1 档
    return 1 + min(3, (count - 1) * 4 // max(max_count, 1))


def bucket_categories(dist: dict[str, int]) -> list[tuple[str, int]]:
    """按数量降序取前 MAX_PIE_SLICES 个分类，其余合并为"其他"。"""
    items = sorted(
        ((str(k), int(v)) for k, v in dist.items() if int(v) > 0),
        key=lambda kv: kv[1],
        reverse=True,
    )
    if len(items) <= MAX_PIE_SLICES + 1:
        return items
    head, tail = items[:MAX_PIE_SLICES], items[MAX_PIE_SLICES:]
    return [*head, ("其他", sum(v for _, v in tail))]


def learning_streak(daily: dict[str, int]) -> int:
    """从今天往回数连续有记录的天数；今天尚未学习不打断连续。"""
    day = date.today()
    if not daily.get(day.isoformat()):
        day -= timedelta(days=1)
    streak = 0
    while daily.get(day.isoformat()):
        streak += 1
        day -= timedelta(days=1)
    return streak


class _EmptyHintMixin:
    """数据为空时在组件中央绘制占位文案。"""

    data: dict

    def _paint_empty_hint(self, painter: QPainter, hint: str) -> bool:
        if self.data:
            return False
        painter.setPen(QColor(MUTED))
        f = painter.font()
        f.setPixelSize(12)
        painter.setFont(f)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, hint)
        return True


class ActivityHeatmap(_EmptyHintMixin, QWidget):
    """GitHub 风格活跃度热力图。

    set_data 接收 get_statistics()["daily_activity"]：{"2026-08-22": 3, ...}
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data: dict[str, int] = {}
        self._hover_day: date | None = None
        self.setMouseTracking(True)
        self.setMinimumSize(
            LABEL_W + WEEKS * PITCH + 4,
            LABEL_H + 7 * PITCH + 24,
        )

    def set_data(self, daily: dict[str, int]) -> None:
        self.data = {str(k): int(v) for k, v in daily.items() if int(v) >= 0}
        self.update()

    # ---- 几何 ----

    def _grid_origin(self) -> tuple[int, int]:
        return LABEL_W, LABEL_H

    def _day_at(self, col: int, row: int) -> date | None:
        """第 col 列第 row 行对应的日期；最右列为本周，未来日期返回 None。"""
        today = date.today()
        week_start = today - timedelta(days=today.weekday())          # 本周一
        column_start = week_start - timedelta(days=(WEEKS - 1) * 7)   # 最左列周一
        day = column_start + timedelta(days=col * 7 + row)
        return day if day <= today else None

    def _cell_rect(self, col: int, row: int) -> QRectF:
        x0, y0 = self._grid_origin()
        return QRectF(x0 + col * PITCH, y0 + row * PITCH, CELL, CELL)

    # ---- 绘制 ----

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._paint_empty_hint(painter, "暂无学习记录，截图识别后自动生成"):
            painter.end()
            return

        max_count = max(self.data.values(), default=0)
        today = date.today()

        # 星期标签（一/三/五/日）
        painter.setPen(QColor(MUTED))
        f = painter.font()
        f.setPixelSize(11)
        painter.setFont(f)
        for row, text in WEEKDAY_LABELS.items():
            rect = self._cell_rect(0, row)
            painter.drawText(
                QRectF(0, rect.top(), LABEL_W - 6, rect.height()),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                text,
            )

        # 月份标签：当某列首行日期进入新月的前 7 天时标注，且与上个标签间隔 ≥ 2 列
        last_month_col = -3
        for col in range(WEEKS):
            day = self._day_at(col, 0)
            if day is None:
                continue
            if day.day <= 7 and col - last_month_col >= 2:
                painter.setPen(QColor(MUTED))
                painter.drawText(
                    QRectF(self._cell_rect(col, 0).left(), 0, PITCH * 2, LABEL_H),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    f"{day.month}月",
                )
                last_month_col = col

        # 格子
        for col in range(WEEKS):
            for row in range(7):
                day = self._day_at(col, row)
                if day is None:  # 未来日期不画
                    continue
                count = self.data.get(day.isoformat(), 0)
                color = QColor(CHART_HEAT_LEVELS[heat_level(count, max_count)])
                if day == today and count == 0:
                    color = QColor(BORDER_LIGHT)  # 今天稍亮于空格子
                if self._hover_day == day:
                    painter.setPen(QPen(QColor(TEXT), 1))
                else:
                    painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(self._cell_rect(col, row), 3, 3)

        # 图例：少 □□□□□ 多
        legend_y = LABEL_H + 7 * PITCH + 4
        squares_w = PITCH * 5 - GAP
        x = self.width() - 4 - squares_w - 40
        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(x, legend_y + 1, 16, CELL),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "少")
        square_x = x + 20
        for level in range(5):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(CHART_HEAT_LEVELS[level]))
            painter.drawRoundedRect(
                QRectF(square_x + level * PITCH, legend_y, CELL, CELL), 3, 3
            )
        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(square_x + squares_w + 6, legend_y + 1, 16, CELL),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "多")
        painter.end()

    # ---- 交互 ----

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        col = int((pos.x() - LABEL_W) // PITCH)
        row = int((pos.y() - LABEL_H) // PITCH)
        day = self._day_at(col, row) if 0 <= col < WEEKS and 0 <= row < 7 else None
        if day != self._hover_day:
            self._hover_day = day
            self.update()
        if day is not None:
            count = self.data.get(day.isoformat(), 0)
            tip = f"{day.month}月{day.day}日：{count} 条记录" if count else f"{day.month}月{day.day}日：无记录"
            QToolTip.showText(event.globalPosition().toPoint(), tip, self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_day = None
        self.update()


class CategoryDonut(_EmptyHintMixin, QWidget):
    """分类构成环形图：左侧圆环 + 右侧图例。

    set_data 接收 get_statistics()["category_distribution"]：{"报错": 12, ...}
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data: dict[str, int] = {}
        self.slices: list[tuple[str, int]] = []
        self.setFixedHeight(176)

    def set_data(self, dist: dict[str, int]) -> None:
        self.data = {str(k): int(v) for k, v in dist.items()}
        self.slices = bucket_categories(self.data)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._paint_empty_hint(painter, "暂无分类数据"):
            painter.end()
            return

        total = sum(v for _, v in self.slices)
        side = self.height() - 24
        ring_rect = QRectF(8, 12, side, side)
        hole = side * 0.58

        # 圆环扇区：从 12 点方向顺时针
        start_angle = 90 * 16
        for index, (_, value) in enumerate(self.slices):
            span = int(value / total * 360 * 16)
            color = QColor(CHART_CATEGORICAL[min(index, len(CHART_CATEGORICAL) - 1)])
            painter.setBrush(color)
            painter.setPen(QPen(QColor(CARD), 2))  # 白色分隔缝
            painter.drawPie(ring_rect, start_angle, -span)
            start_angle -= span

        # 中心挖空 + 总数
        center = ring_rect.center()
        painter.setBrush(QColor(CARD))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, hole / 2, hole / 2)
        painter.setPen(QColor(TEXT))
        f = painter.font()
        f.setPixelSize(18)
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(
            QRectF(center.x() - hole / 2, center.y() - 18, hole, 22),
            Qt.AlignmentFlag.AlignCenter,
            str(total),
        )
        painter.setPen(QColor(MUTED))
        f.setPixelSize(11)
        f.setBold(False)
        painter.setFont(f)
        painter.drawText(
            QRectF(center.x() - hole / 2, center.y() + 2, hole, 14),
            Qt.AlignmentFlag.AlignCenter,
            "条记录",
        )

        # 图例
        legend_x = ring_rect.right() + 16
        row_h = 24
        y = (self.height() - len(self.slices) * row_h) / 2
        for index, (name, value) in enumerate(self.slices):
            color = CHART_CATEGORICAL[min(index, len(CHART_CATEGORICAL) - 1)]
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRectF(legend_x, y + 5, 10, 10), 3, 3)
            percent = round(value / total * 100)
            painter.setPen(QColor(TEXT_SECONDARY))
            f.setPixelSize(12)
            painter.setFont(f)
            name_text = painter.fontMetrics().elidedText(
                name, Qt.TextElideMode.ElideRight, 96
            )
            painter.drawText(QRectF(legend_x + 16, y, 96, 20),
                             Qt.AlignmentFlag.AlignVCenter, name_text)
            painter.setPen(QColor(MUTED))
            painter.drawText(
                QRectF(legend_x + 114, y, self.width() - legend_x - 120, 20),
                Qt.AlignmentFlag.AlignVCenter,
                f"{value} · {percent}%",
            )
            y += row_h
        painter.end()
