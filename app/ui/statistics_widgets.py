from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.ui.theme import BLUE, BLUE_SOFT, BORDER, GREEN, MUTED, RED


class StatCard(QWidget):
    def __init__(
        self,
        title: str,
        value: str,
        subtitle: str = "",
        color: str = BLUE,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._value = value
        self._subtitle = subtitle
        self._color = color
        self.setMinimumHeight(90)
        self.setMaximumHeight(120)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"""
            StatCard {{
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 10px;
            }}
            """
        )

    def set_data(self, value: str, subtitle: str = "") -> None:
        self._value = value
        self._subtitle = subtitle
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))

        painter.setPen(QPen(QColor(self._color), 3))
        painter.drawLine(16, 20, 16, self.height() - 20)

        font = QFont()
        font.setPointSize(9)
        font.setWeight(QFont.Weight.Medium)
        painter.setPen(QColor(MUTED))
        painter.setFont(font)
        painter.drawText(28, 24, self._title)

        font.setPointSize(22)
        font.setWeight(QFont.Weight.Bold)
        painter.setPen(QColor("#1a1a2e"))
        painter.setFont(font)
        painter.drawText(28, 56, self._value)

        if self._subtitle:
            font.setPointSize(8)
            font.setWeight(QFont.Weight.Normal)
            painter.setPen(QColor(MUTED))
            painter.setFont(font)
            painter.drawText(28, 78, self._subtitle)

        painter.end()


class BarChartWidget(QWidget):
    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._title = title
        self._data: dict[str, int] = {}
        self._max_value = 1
        self.setMinimumHeight(200)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"""
            BarChartWidget {{
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 10px;
            }}
            """
        )

    def set_data(self, data: dict[str, int]) -> None:
        self._data = data
        self._max_value = max(data.values()) if data else 1
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        margin_left = 40
        margin_right = 16
        margin_top = 40
        margin_bottom = 50

        chart_w = w - margin_left - margin_right
        chart_h = h - margin_top - margin_bottom

        font = QFont()
        font.setPointSize(11)
        font.setWeight(QFont.Weight.Bold)
        painter.setPen(QColor("#1a1a2e"))
        painter.setFont(font)
        painter.drawText(margin_left, 24, self._title)

        if not self._data:
            font.setPointSize(10)
            font.setWeight(QFont.Weight.Normal)
            painter.setPen(QColor(MUTED))
            painter.setFont(font)
            painter.drawText(margin_left, margin_top + chart_h // 2, "暂无数据")
            painter.end()
            return

        painter.setPen(QPen(QColor(BORDER), 1))
        for i in range(5):
            y = margin_top + int(chart_h * i / 4)
            value_at = int(self._max_value * (4 - i) / 4)
            painter.drawLine(margin_left, y, margin_left + chart_w, y)
            font.setPointSize(7)
            font.setWeight(QFont.Weight.Normal)
            painter.setPen(QColor(MUTED))
            painter.setFont(font)
            painter.drawText(4, y + 4, str(value_at))
            painter.setPen(QPen(QColor(BORDER), 1))

        bar_count = len(self._data)
        if bar_count > 0:
            bar_width = min(40, chart_w // bar_count - 4)
            total_bars_width = bar_count * (bar_width + 4) - 4
            start_x = margin_left + (chart_w - total_bars_width) // 2
        else:
            start_x = margin_left

        colors = ["#4f7cff", "#6c5ce7", "#00b894", "#fdcb6e", "#e17055", "#0984e3", "#e84393", "#00cec9"]

        font.setPointSize(7)
        font.setWeight(QFont.Weight.Normal)

        for index, (label, value) in enumerate(self._data.items()):
            bar_h = int(value / self._max_value * chart_h)
            x = start_x + index * (bar_width + 4)
            y = margin_top + chart_h - bar_h

            color = QColor(colors[index % len(colors)])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(x, y, bar_width, bar_h, 3, 3)

            painter.setPen(QColor("#1a1a2e"))
            painter.setFont(font)
            value_text = str(value)
            text_rect = QRect(x - 2, y - 16, bar_width + 4, 14)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, value_text)

            label_text = label if len(label) <= 8 else label[:7] + ".."
            label_rect = QRect(x - 4, margin_top + chart_h + 4, bar_width + 8, 20)
            painter.setPen(QColor(MUTED))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.TextWrapAnywhere, label_text)

        painter.end()


class HeatmapWidget(QWidget):
    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._title = title
        self._data: dict[str, int] = {}
        self._max_value = 1
        self.setMinimumHeight(180)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"""
            HeatmapWidget {{
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 10px;
            }}
            """
        )

    def set_data(self, data: dict[str, int]) -> None:
        self._data = data
        self._max_value = max(data.values()) if data else 1
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        margin_left = 40
        margin_top = 40
        margin_bottom = 20

        font = QFont()
        font.setPointSize(11)
        font.setWeight(QFont.Weight.Bold)
        painter.setPen(QColor("#1a1a2e"))
        painter.setFont(font)
        painter.drawText(margin_left, 24, self._title)

        if not self._data:
            font.setPointSize(10)
            font.setWeight(QFont.Weight.Normal)
            painter.setPen(QColor(MUTED))
            painter.setFont(font)
            painter.drawText(margin_left, 80, "暂无数据")
            painter.end()
            return

        sorted_days = sorted(self._data.keys())
        weeks: list[list[tuple[str, int]]] = []
        week: list[tuple[str, int]] = []
        for day in sorted_days:
            week.append((day, self._data[day]))
            if len(week) == 7:
                weeks.append(week)
                week = []
        if week:
            weeks.append(week)

        cell_size = 14
        gap = 3

        start_x = margin_left
        start_y = margin_top + 10

        font.setPointSize(7)
        font.setWeight(QFont.Weight.Normal)
        painter.setPen(QColor(MUTED))
        painter.setFont(font)
        painter.drawText(4, start_y + 10, "一")
        painter.drawText(4, start_y + 10 + (cell_size + gap) * 2, "三")
        painter.drawText(4, start_y + 10 + (cell_size + gap) * 4, "五")
        painter.drawText(4, start_y + 10 + (cell_size + gap) * 6, "日")

        for week_idx, week_data in enumerate(weeks):
            for day_idx, (day, value) in enumerate(week_data):
                x = margin_left + 12 + week_idx * (cell_size + gap)
                y = start_y + day_idx * (cell_size + gap)

                intensity = value / self._max_value if self._max_value > 0 else 0
                if intensity > 0.75:
                    color = QColor("#2d6a4f")
                elif intensity > 0.5:
                    color = QColor("#40916c")
                elif intensity > 0.25:
                    color = QColor("#74c69d")
                elif intensity > 0:
                    color = QColor("#b7e4c7")
                else:
                    color = QColor("#e9ecef")

                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(x, y, cell_size, cell_size, 2, 2)

        legend_y = start_y + 7 * (cell_size + gap) + 14
        painter.setPen(QColor(MUTED))
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(margin_left, legend_y, "少")
        legend_items = ["#e9ecef", "#b7e4c7", "#74c69d", "#40916c", "#2d6a4f"]
        for i, c in enumerate(legend_items):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c))
            painter.drawRoundedRect(margin_left + 24 + i * 20, legend_y - 10, 12, 12, 2, 2)
        painter.drawText(margin_left + 24 + len(legend_items) * 20 + 4, legend_y, "多")

        painter.end()


class PieChartWidget(QWidget):
    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._title = title
        self._data: dict[str, int] = {}
        self.setMinimumHeight(220)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"""
            PieChartWidget {{
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 10px;
            }}
            """
        )

    def set_data(self, data: dict[str, int]) -> None:
        self._data = data
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        margin_top = 40
        margin_left = 16
        margin_right = 16

        font = QFont()
        font.setPointSize(11)
        font.setWeight(QFont.Weight.Bold)
        painter.setPen(QColor("#1a1a2e"))
        painter.setFont(font)
        painter.drawText(margin_left, 24, self._title)

        if not self._data:
            font.setPointSize(10)
            font.setWeight(QFont.Weight.Normal)
            painter.setPen(QColor(MUTED))
            painter.setFont(font)
            painter.drawText(margin_left, 80, "暂无数据")
            painter.end()
            return

        total = sum(self._data.values())
        if total == 0:
            painter.end()
            return

        colors = ["#4f7cff", "#6c5ce7", "#00b894", "#fdcb6e", "#e17055", "#0984e3", "#e84393", "#00cec9", "#fd79a8", "#a29bfe"]

        pie_size = min(h - margin_top - 20, (w - margin_left - margin_right) * 0.55)
        pie_x = margin_left + 10
        pie_y = margin_top + 10

        start_angle = 0
        legend_x = pie_x + pie_size + 30
        legend_y = pie_y + 10

        font.setPointSize(9)
        font.setWeight(QFont.Weight.Normal)

        for index, (label, value) in enumerate(self._data.items()):
            span = int(value / total * 360 * 16)
            color = QColor(colors[index % len(colors)])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawPie(pie_x, pie_y, pie_size, pie_size, start_angle, span)
            start_angle += span

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors[index % len(colors)]))
            painter.drawRoundedRect(legend_x, legend_y + index * 22, 12, 12, 2, 2)

            painter.setPen(QColor("#1a1a2e"))
            pct = f"{value}/{total} ({value * 100 // total}%)"
            display_label = label if len(label) <= 6 else label[:5] + ".."
            painter.drawText(legend_x + 18, legend_y + index * 22 + 10, f"{display_label} {pct}")

        painter.end()
