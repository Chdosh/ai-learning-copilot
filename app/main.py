from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--screenshot-worker":
        from app.services.screenshot_worker import main as screenshot_worker_main

        return screenshot_worker_main(sys.argv[2:])

    from PySide6.QtWidgets import QApplication

    from app.paths import ensure_app_dirs
    from app.ui.main_window import MainWindow

    ensure_app_dirs()
    app = QApplication(sys.argv)
    app.setApplicationName("AI Learning Copilot")
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
