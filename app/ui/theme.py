from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QWidget


BLUE = "#2563eb"
BLUE_DARK = "#1d4ed8"
BLUE_HOVER = "#3b82f6"
BLUE_SOFT = "#eff4ff"
BORDER = "#e4e7ec"
BORDER_LIGHT = "#eef1f4"
TEXT = "#101828"
MUTED = "#667085"
BG = "#f6f7f9"
CARD = "#ffffff"
GREEN = "#16a34a"
RED = "#dc2626"


APP_STYLE = f"""
QMainWindow, QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "Microsoft YaHei", "Segoe UI", Arial;
}}
QLabel {{
    background: transparent;
}}
QLineEdit, QTextEdit, QTextBrowser, QPlainTextEdit {{
    background: #ffffff;
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 8px;
    selection-background-color: {BLUE};
}}
QLineEdit:focus, QTextEdit:focus, QTextBrowser:focus, QPlainTextEdit:focus {{
    border: 1px solid {BLUE};
}}
QComboBox {{
    background: #ffffff;
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px 8px;
}}
QComboBox:focus {{
    border: 1px solid {BLUE};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QPushButton {{
    background: #ffffff;
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 14px;
    color: #344054;
}}
QPushButton:hover {{
    border-color: {BLUE_HOVER};
    color: {BLUE};
}}
QPushButton:pressed {{
    background: {BLUE_SOFT};
}}
QPushButton#primaryButton {{
    background: {BLUE};
    color: #ffffff;
    border: 1px solid {BLUE};
}}
QPushButton#primaryButton:hover {{
    background: {BLUE_DARK};
    border-color: {BLUE_DARK};
    color: #ffffff;
}}
QPushButton#primaryButton:pressed {{
    background: {BLUE_DARK};
    color: #ffffff;
}}
QPushButton:disabled {{
    background: #f2f4f7;
    color: #98a2b3;
    border-color: {BORDER};
}}
QPushButton#dangerButton {{
    background: #fff5f5;
    color: {RED};
    border-color: #fecaca;
}}
QTableWidget {{
    background: #ffffff;
    border: none;
    gridline-color: transparent;
}}
QHeaderView::section {{
    background: #ffffff;
    border: none;
    border-bottom: 1px solid {BORDER_LIGHT};
    padding: 8px 7px;
    color: #667085;
}}
QTableWidget::item {{
    padding: 7px;
    border-bottom: 1px solid {BORDER_LIGHT};
}}
QTableWidget::item:selected {{
    background: {BLUE_SOFT};
    color: {TEXT};
}}
QListWidget {{
    background: #ffffff;
    border: none;
    outline: 0;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 8px;
}}
QListWidget::item:selected {{
    background: {BLUE_SOFT};
    color: {TEXT};
}}
QScrollBar:vertical, QScrollBar:horizontal {{
    border: none;
    background: transparent;
    margin: 4px;
}}
QScrollBar:vertical {{
    width: 8px;
}}
QScrollBar:horizontal {{
    height: 8px;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: #d0d5dd;
    border-radius: 4px;
    min-height: 28px;
    min-width: 28px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background: #98a2b3;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
    height: 0;
    border: none;
    background: transparent;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}
QScrollBar::corner {{
    background: transparent;
}}
"""


def ensure_label_backgrounds_transparent(root: QWidget) -> None:
    """Remove inherited widget fills from labels without an intentional background."""
    labels = [root] if isinstance(root, QLabel) else []
    labels.extend(root.findChildren(QLabel))
    for label in labels:
        style = label.styleSheet()
        normalized = style.lower()
        if any(
            property_name in normalized
            for property_name in ("background:", "background-color:", "background-image:")
        ):
            continue
        suffix = "background: transparent;"
        label.setStyleSheet(f"{style.rstrip()}\n{suffix}" if style.strip() else suffix)


def apply_primary_button_style(button: QPushButton) -> QPushButton:
    """Apply the primary button style directly to avoid parent QSS scope issues."""
    button.setObjectName("primaryButton")
    button.setStyleSheet(
        f"""
        QPushButton#primaryButton {{
            background: {BLUE};
            border: 1px solid {BLUE};
            border-radius: 8px;
            padding: 6px 14px;
            color: #ffffff;
        }}
        QPushButton#primaryButton:hover {{
            background: {BLUE_DARK};
            border-color: {BLUE_DARK};
            color: #ffffff;
        }}
        QPushButton#primaryButton:pressed {{
            background: {BLUE_DARK};
            border-color: {BLUE_DARK};
            color: #ffffff;
        }}
        QPushButton#primaryButton:disabled {{
            background: #f2f4f7;
            border-color: #e4e7ec;
            color: #98a2b3;
        }}
        """
    )
    return button


