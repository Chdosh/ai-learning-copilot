"""设计系统：统一 token + 组件样式。

规则：
- 所有颜色/圆角/间距/字号都从这里取，禁止在业务代码里写裸值。
- 圆角 3 级：sm(6, 输入框/小控件) / md(8, 按钮/列表项) / lg(12, 卡片) / pill(16, chips)
- 字号 4 级：micro(12 元数据) / body(13 正文) / title(16 页头) / heading(20 卡片标题)
- 间距走 8pt 网格（8/16/24/32）。
"""
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QWidget

# ---- 色板（clean 风格） ----
PRIMARY = "#3B82F6"          # 主色
PRIMARY_DARK = "#1D4ED8"     # 主色按下
PRIMARY_SOFT = "#EFF4FF"     # 主色浅底（选中态/悬停底）
TEXT = "#111827"             # 主文字
TEXT_SECONDARY = "#344054"   # 次级文字
MUTED = "#667085"            # 元数据/说明
DISABLED = "#98A2B3"         # 禁用文字
BORDER = "#E4E7EC"           # 边框
BORDER_LIGHT = "#EEF1F4"     # 弱分隔线
BG = "#F6F7F9"               # 页面底色
CARD = "#FFFFFF"             # 卡片/面板底色
DANGER = "#DC2626"           # 危险
DANGER_SOFT = "#FFF5F5"      # 危险浅底
DANGER_BORDER = "#FECACA"    # 危险边框
SUCCESS = "#16A34A"          # 成功

# ---- 圆角 ----
RADIUS_SM = "6px"            # 输入框、小控件
RADIUS_MD = "8px"            # 按钮、列表项
RADIUS_LG = "12px"           # 卡片
RADIUS_PILL = "16px"         # chips

# ---- 字号 ----
FONT_MICRO = "12px"          # 元数据/状态
FONT_BODY = "13px"           # 正文
FONT_TITLE = "16px"          # 页头/标题
FONT_HEADING = "20px"        # 卡片主标题


def button_qss(base: str = "#ffffff") -> str:
    """通用按钮：白底、灰边、圆角 md。"""
    return f"""
    QPushButton {{
        background: {base};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_MD};
        padding: 6px 14px;
        color: {TEXT_SECONDARY};
    }}
    QPushButton:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; }}
    QPushButton:pressed {{ background: {PRIMARY_SOFT}; }}
    QPushButton:disabled {{ background: #f2f4f7; color: {DISABLED}; border-color: {BORDER}; }}
    """


def chip_qss() -> str:
    """筛选 chips：胶囊、选中变主色。"""
    return f"""
    QPushButton {{
        border: 1px solid {BORDER};
        border-radius: {RADIUS_PILL};
        padding: 3px 12px;
        background: {CARD};
        color: {TEXT_SECONDARY};
    }}
    QPushButton:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; }}
    QPushButton:checked {{ background: {PRIMARY}; color: #ffffff; border-color: {PRIMARY}; }}
    """


def nav_qss() -> str:
    """侧边导航按钮：左对齐、无边框、选中主色浅底。"""
    return f"""
    QPushButton {{
        text-align: left;
        padding: 8px 10px;
        border: 0;
        border-radius: {RADIUS_MD};
        background: transparent;
        color: {TEXT_SECONDARY};
    }}
    QPushButton:hover {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; }}
    QPushButton:checked {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; }}
    """


def card_qss() -> str:
    """卡片容器：白底、灰边、圆角 lg。"""
    return f"""
    QFrame#card {{
        background: {CARD};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_LG};
    }}
    """


def input_qss() -> str:
    """输入控件：白底、灰边、圆角 sm。"""
    return f"""
    QLineEdit, QTextEdit, QTextBrowser, QPlainTextEdit {{
        background: {CARD};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM};
        padding: 5px 8px;
        selection-background-color: {PRIMARY};
    }}
    QLineEdit:focus, QTextEdit:focus, QTextBrowser:focus, QPlainTextEdit:focus {{
        border: 1px solid {PRIMARY};
    }}
    """


APP_STYLE = f"""
QMainWindow, QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "Microsoft YaHei", "Segoe UI", Arial;
}}
QLabel {{
    background: transparent;
}}
{input_qss()}
QComboBox {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SM};
    padding: 4px 8px;
}}
QComboBox:focus {{ border: 1px solid {PRIMARY}; }}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
{button_qss()}
QPushButton#primaryButton {{
    background: {PRIMARY};
    color: #ffffff;
    border: 1px solid {PRIMARY};
}}
QPushButton#primaryButton:hover {{
    background: {PRIMARY_DARK};
    border-color: {PRIMARY_DARK};
    color: #ffffff;
}}
QPushButton#primaryButton:pressed {{
    background: {PRIMARY_DARK};
    color: #ffffff;
}}
QPushButton#primaryButton:disabled {{
    background: #f2f4f7;
    color: {DISABLED};
    border-color: {BORDER};
}}
QPushButton#dangerButton {{
    background: {DANGER_SOFT};
    color: {DANGER};
    border-color: {DANGER_BORDER};
}}
QTableWidget {{
    background: {CARD};
    border: none;
    gridline-color: transparent;
}}
QHeaderView::section {{
    background: {CARD};
    border: none;
    border-bottom: 1px solid {BORDER_LIGHT};
    padding: 8px 7px;
    color: {MUTED};
}}
QTableWidget::item {{
    padding: 7px;
    border-bottom: 1px solid {BORDER_LIGHT};
}}
QTableWidget::item:selected {{
    background: {PRIMARY_SOFT};
    color: {TEXT};
}}
QListWidget {{
    background: {CARD};
    border: none;
    outline: 0;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: {RADIUS_MD};
}}
QListWidget::item:selected {{
    background: {PRIMARY_SOFT};
    color: {TEXT};
}}
QScrollBar:vertical, QScrollBar:horizontal {{
    border: none;
    background: transparent;
    margin: 4px;
}}
QScrollBar:vertical {{ width: 8px; }}
QScrollBar:horizontal {{ height: 8px; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: #d0d5dd;
    border-radius: 4px;
    min-height: 28px;
    min-width: 28px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background: {DISABLED};
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
QScrollBar::corner {{ background: transparent; }}
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
            background: {PRIMARY};
            border: 1px solid {PRIMARY};
            border-radius: {RADIUS_MD};
            padding: 6px 14px;
            color: #ffffff;
        }}
        QPushButton#primaryButton:hover {{
            background: {PRIMARY_DARK};
            border-color: {PRIMARY_DARK};
            color: #ffffff;
        }}
        QPushButton#primaryButton:pressed {{
            background: {PRIMARY_DARK};
            border-color: {PRIMARY_DARK};
            color: #ffffff;
        }}
        QPushButton#primaryButton:disabled {{
            background: #f2f4f7;
            border-color: {BORDER};
            color: {DISABLED};
        }}
        """
    )
    return button
