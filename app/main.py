from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--screenshot-worker":
        from app.services.screenshot_worker import main as screenshot_worker_main

        return screenshot_worker_main(sys.argv[2:])

    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app.paths import DATA_DIR, ensure_app_dirs
    from app.ui.main_window import MainWindow

    ensure_app_dirs()
    lock = QLockFile(str(DATA_DIR / "app.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.warning(None, "AI Learning Copilot", "程序已在运行，不能重复启动。")
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("AI Learning Copilot")
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow()
    window.show()
    try:
        return app.exec()
    finally:
        lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
