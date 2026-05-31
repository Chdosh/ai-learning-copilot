from __future__ import annotations

import ctypes
import os
import sys

from PySide6.QtWidgets import QApplication

from app.paths import ensure_app_dirs
from app.ui.main_window import MainWindow


def main() -> int:
    _enable_high_dpi_awareness()
    ensure_app_dirs()
    app = QApplication(sys.argv)
    app.setApplicationName("AI Learning Copilot")
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow()
    window.show()
    return app.exec()


def _enable_high_dpi_awareness() -> None:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    if sys.platform != "win32":
        return

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
