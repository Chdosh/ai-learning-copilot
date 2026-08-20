from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath


MAIN_EXECUTABLE_NAME = "AI-Learning-Copilot.exe"
UPDATER_EXECUTABLE_NAME = "AI-Learning-Copilot-Updater.exe"
HEALTH_CHECK_SECONDS = 3


def _configure_logging(app_dir: Path) -> logging.Logger:
    log_path = app_dir / "data" / "update.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("ai-learning-copilot-updater")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def _wait_for_process(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x00100000, False, pid)
        if handle:
            try:
                kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
            finally:
                kernel32.CloseHandle(handle)
        return

    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            return
        time.sleep(0.2)


def _safe_relative_path(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    relative = PurePosixPath(normalized)
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"更新包包含不安全路径：{name}")
    if not relative.parts:
        raise RuntimeError("更新包包含空路径。")
    return relative


def _payload_root(names: list[str]) -> tuple[str, ...]:
    for name in names:
        relative = _safe_relative_path(name)
        if relative.name.lower() == MAIN_EXECUTABLE_NAME.lower():
            return relative.parts[:-1]
    raise RuntimeError("更新包缺少主程序。")


def _extract_payload(package_path: Path, staging_dir: Path) -> Path:
    payload_dir = staging_dir / "payload"
    payload_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(package_path) as archive:
            file_infos = [item for item in archive.infolist() if not item.is_dir()]
            root = _payload_root([item.filename for item in file_infos])
            for item in file_infos:
                relative = _safe_relative_path(item.filename)
                if relative.parts[: len(root)] != root:
                    continue
                relative = PurePosixPath(*relative.parts[len(root) :])
                if not relative.parts or relative.parts[0].lower() == "data":
                    continue
                if relative.parts[0].lower() == "__macosx":
                    continue
                destination = payload_dir.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except zipfile.BadZipFile as exc:
        raise RuntimeError("更新包不是有效的 ZIP 文件。") from exc

    main_path = payload_dir / MAIN_EXECUTABLE_NAME
    updater_path = payload_dir / UPDATER_EXECUTABLE_NAME
    if not main_path.is_file():
        raise RuntimeError("更新包缺少主程序。")
    if not updater_path.is_file():
        raise RuntimeError("更新包缺少独立更新器。")
    return payload_dir


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _apply_payload(payload_dir: Path, app_dir: Path, backup_dir: Path) -> list[tuple[Path, Path | None]]:
    changes: list[tuple[Path, Path | None]] = []
    for source in sorted(payload_dir.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(payload_dir)
        if not relative.parts or relative.parts[0].lower() == "data":
            continue
        target = app_dir.joinpath(relative)
        if not _inside(app_dir, target):
            raise RuntimeError(f"更新目标超出程序目录：{relative}")
        target.parent.mkdir(parents=True, exist_ok=True)

        backup: Path | None = None
        if target.exists():
            if not target.is_file():
                raise RuntimeError(f"更新目标不是文件：{target}")
            backup = backup_dir.joinpath(relative)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)

        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.new")
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
        changes.append((target, backup))
    return changes


def _rollback(changes: list[tuple[Path, Path | None]]) -> None:
    for target, backup in reversed(changes):
        try:
            if backup is None:
                target.unlink(missing_ok=True)
            else:
                os.replace(backup, target)
        except OSError:
            continue


def _launch_and_check(app_exe: Path, app_dir: Path) -> None:
    process = subprocess.Popen([str(app_exe)], cwd=str(app_dir), close_fds=True)
    time.sleep(HEALTH_CHECK_SECONDS)
    if process.poll() is not None:
        raise RuntimeError(f"新版本启动后立即退出，退出码：{process.returncode}")


def apply_update(pid: int, package_path: Path, app_dir: Path, app_exe: Path, logger: logging.Logger) -> None:
    _wait_for_process(pid)
    if not app_dir.is_dir():
        raise RuntimeError(f"程序目录不存在：{app_dir}")
    if not package_path.is_file():
        raise RuntimeError(f"更新包不存在：{package_path}")

    staging_dir = Path(tempfile.mkdtemp(prefix="ai-learning-copilot-apply-"))
    backup_dir = Path(tempfile.mkdtemp(prefix="ai-learning-copilot-backup-"))
    changes: list[tuple[Path, Path | None]] = []
    try:
        payload_dir = _extract_payload(package_path, staging_dir)
        changes = _apply_payload(payload_dir, app_dir, backup_dir)
        logger.info("已替换 %s 个程序文件。", len(changes))
        _launch_and_check(app_exe, app_dir)
        logger.info("新版本启动检查通过。")
    except Exception:
        logger.exception("更新失败，开始回滚。")
        _rollback(changes)
        raise
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
        shutil.rmtree(backup_dir, ignore_errors=True)
        try:
            package_path.unlink(missing_ok=True)
        except OSError:
            pass


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Learning Copilot portable updater")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--app-dir", type=Path, required=True)
    parser.add_argument("--app-exe", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    logger = _configure_logging(args.app_dir)
    try:
        apply_update(args.pid, args.package, args.app_dir, args.app_exe, logger)
    except Exception as exc:
        logger.error("更新失败：%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
