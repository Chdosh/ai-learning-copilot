from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import mss
import pytest

from app.services import screenshot
from app.services import screenshot_worker
from app.services.screenshot_worker import _selection_to_physical


def test_worker_command_uses_module_in_python_environment(tmp_path) -> None:
    command = screenshot._worker_command(tmp_path)
    assert command[1:3] == ["-m", "app.services.screenshot_worker"]
    assert command[-1] == str(tmp_path)


def test_take_screenshots_returns_existing_output(tmp_path, monkeypatch) -> None:
    output = tmp_path / "capture.png"
    output.write_bytes(b"png")
    completed = SimpleNamespace(returncode=0, stdout=str(output), stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: completed)
    assert screenshot.take_screenshots(tmp_path) == str(output)


def test_take_screenshots_raises_clear_process_error(tmp_path, monkeypatch) -> None:
    completed = SimpleNamespace(returncode=1, stdout="", stderr="tkinter missing")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: completed)
    with pytest.raises(screenshot.ScreenshotError, match="tkinter missing"):
        screenshot.take_screenshots(tmp_path)


def test_selection_coordinates_are_scaled_to_physical_pixels() -> None:
    region = _selection_to_physical(
        start=(100, 50),
        end=(1100, 550),
        canvas_size=(2000, 1000),
        bounds={"left": -100, "top": -50, "width": 3000, "height": 1500},
    )

    assert region == (50, 25, 1500, 750)


def test_cancelled_selection_does_not_capture_pixels(tmp_path, monkeypatch) -> None:
    grab_calls = 0

    class FakeCapture:
        monitors = [
            {},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
        ]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def grab(self, _region):
            nonlocal grab_calls
            grab_calls += 1
            raise AssertionError("取消截图后不应抓取屏幕像素")

    monkeypatch.setattr(mss, "MSS", FakeCapture)
    monkeypatch.setattr(screenshot_worker, "select_region", lambda _bounds: None)

    assert screenshot_worker.run(tmp_path) is None
    assert grab_calls == 0
