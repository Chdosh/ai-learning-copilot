from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeyEvent, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from app.paths import SCREENSHOTS_DIR


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


class ScreenshotSelector(QWidget):
    captured = Signal(str)
    cancelled = Signal()

    def __init__(self, screenshots_dir: str | Path = SCREENSHOTS_DIR) -> None:
        super().__init__()
        self.screenshots_dir = Path(screenshots_dir)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self._virtual_geometry = _virtual_geometry()
        self._desktop = _grab_virtual_desktop(self._virtual_geometry)
        self._start: QPoint | None = None
        self._current: QPoint | None = None
        self._selecting = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(self._virtual_geometry)

    def begin(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._desktop)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))

        selection = self._selection_rect()
        if selection.isValid() and selection.width() > 1 and selection.height() > 1:
            painter.drawPixmap(selection, self._desktop, selection)
            painter.setPen(QPen(QColor(84, 160, 255), 2))
            painter.drawRect(selection.adjusted(0, 0, -1, -1))
            painter.fillRect(selection.adjusted(1, 1, -1, -1), QColor(84, 160, 255, 22))

        painter.setPen(QColor(255, 255, 255))
        painter.drawText(24, 36, "拖拽选择要翻译的区域，右键或 Esc 取消")

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self._cancel()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._start = event.position().toPoint()
        self._current = self._start
        self._selecting = True
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._selecting:
            return
        self._current = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self._cancel()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._current = event.position().toPoint()
        selection = self._selection_rect()
        self._selecting = False

        if selection.width() < 8 or selection.height() < 8:
            self._cancel()
            return

        image_path = self._save_selection(selection)
        self.captured.emit(str(image_path))
        self.close()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()

    def _selection_rect(self) -> QRect:
        if self._start is None or self._current is None:
            return QRect()
        return QRect(self._start, self._current).normalized().intersected(self.rect())

    def _save_selection(self, selection: QRect) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = self.screenshots_dir / f"capture-{timestamp}.png"
        if not _save_native_selection(selection, self._virtual_geometry, path):
            _save_qt_selection_for_ocr(self._desktop, selection, path)
        return path

    def _cancel(self) -> None:
        self.cancelled.emit()
        self.close()


def _virtual_geometry() -> QRect:
    screens = QGuiApplication.screens()
    if not screens:
        return QRect(0, 0, 800, 600)
    geometry = QRect(screens[0].geometry())
    for screen in screens[1:]:
        geometry = geometry.united(screen.geometry())
    return geometry


def _grab_virtual_desktop(virtual_geometry: QRect) -> QPixmap:
    pixmap = QPixmap(virtual_geometry.size())
    pixmap.fill(QColor(0, 0, 0))
    painter = QPainter(pixmap)
    for screen in QGuiApplication.screens():
        screen_pixmap = screen.grabWindow(0)
        target = screen.geometry().translated(-virtual_geometry.topLeft())
        painter.drawPixmap(target, screen_pixmap)
    painter.end()
    return pixmap


def _save_native_selection(selection: QRect, virtual_geometry: QRect, path: Path) -> bool:
    try:
        import mss
        from mss import tools
    except ImportError:
        return False

    try:
        with mss.mss() as screen_capture:
            native_region = _native_region_for_selection(selection, virtual_geometry, screen_capture.monitors)
            if native_region is None:
                return False
            shot = screen_capture.grab(native_region)
            tools.to_png(shot.rgb, shot.size, output=str(path))
        return True
    except Exception:
        return False


def _save_qt_selection_for_ocr(desktop: QPixmap, selection: QRect, path: Path) -> None:
    desktop.copy(selection).save(str(path), "PNG")


def _native_region_for_selection(
    selection: QRect,
    virtual_geometry: QRect,
    native_monitors: list[dict],
) -> dict[str, int] | None:
    selection_global = selection.translated(virtual_geometry.topLeft())
    screens = QGuiApplication.screens()
    monitors = native_monitors[1:]

    for screen, monitor in zip(screens, monitors):
        screen_geometry = screen.geometry()
        intersection = selection_global.intersected(screen_geometry)
        if not intersection.isValid() or intersection.width() <= 0 or intersection.height() <= 0:
            continue

        scale_x = monitor["width"] / max(1, screen_geometry.width())
        scale_y = monitor["height"] / max(1, screen_geometry.height())
        left = monitor["left"] + round((intersection.left() - screen_geometry.left()) * scale_x)
        top = monitor["top"] + round((intersection.top() - screen_geometry.top()) * scale_y)
        width = max(1, round(intersection.width() * scale_x))
        height = max(1, round(intersection.height() * scale_y))
        return {"left": int(left), "top": int(top), "width": int(width), "height": int(height)}

    if not native_monitors:
        return None

    monitor = native_monitors[0]
    scale_x = monitor["width"] / max(1, virtual_geometry.width())
    scale_y = monitor["height"] / max(1, virtual_geometry.height())
    return {
        "left": int(monitor["left"] + round(selection.left() * scale_x)),
        "top": int(monitor["top"] + round(selection.top() * scale_y)),
        "width": max(1, int(round(selection.width() * scale_x))),
        "height": max(1, int(round(selection.height() * scale_y))),
    }
