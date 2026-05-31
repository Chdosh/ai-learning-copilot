from __future__ import annotations

from PySide6.QtWidgets import QFrame, QPushButton


BLUE = "#2563eb"
BLUE_DARK = "#1d4ed8"
BLUE_SOFT = "#eff6ff"
BORDER = "#dbe3ef"
TEXT = "#101828"
MUTED = "#667085"
BG = "#f8fbff"
CARD = "#ffffff"
GREEN = "#16a34a"
RED = "#dc2626"


APP_STYLE = f"""
QMainWindow, QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "Microsoft YaHei", "Segoe UI", Arial;
    font-size: 13px;
}}
QLineEdit, QTextEdit, QTextBrowser {{
    background: #ffffff;
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px;
    selection-background-color: {BLUE};
}}
QPushButton {{
    background: #ffffff;
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 12px;
    color: #344054;
}}
QPushButton:hover {{
    border-color: #93b4ff;
    background: #f8fbff;
}}
QPushButton#primaryButton {{
    background: {BLUE};
    color: #ffffff;
    border-color: {BLUE};
    font-weight: 600;
}}
QPushButton#primaryButton:hover {{
    background: {BLUE_DARK};
    color: #ffffff;
    border-color: {BLUE_DARK};
}}
QPushButton#primaryButton:pressed {{
    background: {BLUE_DARK};
    color: #ffffff;
    border-color: {BLUE_DARK};
}}
QPushButton:disabled {{
    background: #f2f4f7;
    color: #98a2b3;
    border-color: #e4e7ec;
}}
QPushButton#dangerButton {{
    background: #fff5f5;
    color: {RED};
    border-color: #fecaca;
}}
QTableWidget {{
    background: #ffffff;
    border: 1px solid {BORDER};
    border-radius: 10px;
    gridline-color: #e8eef7;
}}
QHeaderView::section {{
    background: #ffffff;
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 7px;
    color: #475467;
    font-weight: 600;
}}
QTableWidget::item {{
    padding: 7px;
    border-bottom: 1px solid #eef2f7;
}}
QTableWidget::item:selected {{
    background: #eff6ff;
    color: {TEXT};
}}
QListWidget {{
    background: #ffffff;
    border: 1px solid {BORDER};
    border-radius: 10px;
    outline: 0;
}}
QListWidget::item {{
    padding: 8px;
    border-bottom: 1px solid #eef2f7;
}}
QListWidget::item:selected {{
    background: #eff6ff;
    color: {TEXT};
    border: 1px solid {BLUE};
    border-radius: 8px;
}}
QScrollBar:vertical {{
    width: 10px;
    background: transparent;
}}
QScrollBar::handle:vertical {{
    background: #cbd5e1;
    border-radius: 5px;
}}
"""


def make_card(object_name: str = "") -> QFrame:
    card = QFrame()
    if object_name:
        card.setObjectName(object_name)
    card.setFrameShape(QFrame.Shape.NoFrame)
    card.setStyleSheet(
        f"""
        QFrame#{object_name or card.objectName()} {{
            background: {CARD};
            border: 1px solid {BORDER};
            border-radius: 12px;
        }}
        """
    )
    return card


def primary_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("primaryButton")
    return button


def ghost_button(text: str) -> QPushButton:
    return QPushButton(text)


def nav_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setCheckable(True)
    button.setStyleSheet(
        f"""
        QPushButton {{
            text-align: left;
            padding: 12px 14px;
            border: 0;
            border-radius: 10px;
            background: transparent;
            color: #344054;
            font-weight: 500;
        }}
        QPushButton:hover {{
            background: #f1f6ff;
            color: {BLUE};
        }}
        QPushButton:checked {{
            background: #eaf2ff;
            color: {BLUE};
            font-weight: 700;
        }}
        """
    )
    return button


def chip(text: str, active: bool = False) -> QPushButton:
    button = QPushButton(text)
    if active:
        button.setObjectName("primaryButton")
    else:
        button.setStyleSheet(
            f"""
            QPushButton {{
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 18px;
                padding: 7px 18px;
                color: #344054;
            }}
            """
        )
    return button
