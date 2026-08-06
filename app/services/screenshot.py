from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.paths import SCREENSHOTS_DIR


class ScreenshotError(RuntimeError):
    pass


def _worker_command(screenshots_dir: str | Path) -> list[str]:
    target = str(Path(screenshots_dir))
    if getattr(sys, "frozen", False):
        return [sys.executable, "--screenshot-worker", target]
    return [sys.executable, "-m", "app.services.screenshot_worker", target]


def take_screenshots(
    screenshots_dir: str | Path = SCREENSHOTS_DIR,
    timeout_seconds: int = 120,
) -> str | None:
    """Run the selector in a child process and return the saved image path."""
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            _worker_command(screenshots_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            creationflags=creation_flags,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ScreenshotError("截图选择超时，请重新尝试。") from exc
    except OSError as exc:
        raise ScreenshotError(f"无法启动截图进程: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "未知错误").strip()
        raise ScreenshotError(f"截图进程失败: {detail}")

    output = result.stdout.strip()
    if not output:
        return None
    path = Path(output.splitlines()[-1])
    if not path.is_file():
        raise ScreenshotError(f"截图进程未生成文件: {path}")
    return str(path)
