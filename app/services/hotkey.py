from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class HotkeyManager(QObject):
    hotkey_pressed = Signal()
    failed = Signal(str)

    def __init__(self, hotkey: str) -> None:
        super().__init__()
        self.hotkey = hotkey
        self._listener = None

    def start(self) -> None:
        try:
            from pynput import keyboard
        except ImportError:
            self.failed.emit("未安装 pynput，全局快捷键不可用。")
            return

        try:
            self._listener = keyboard.GlobalHotKeys({self.hotkey: self.hotkey_pressed.emit})
            self._listener.start()
        except Exception as exc:
            self.failed.emit(f"全局快捷键启动失败: {exc}")

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
