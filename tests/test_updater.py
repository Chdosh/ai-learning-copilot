from __future__ import annotations

import zipfile
from pathlib import Path

from app.updater_main import _apply_payload, _extract_payload, _rollback


def test_updater_replaces_program_files_and_preserves_data(tmp_path: Path) -> None:
    package = tmp_path / "package.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("AI-Learning-Copilot.exe", b"new main")
        archive.writestr("AI-Learning-Copilot-Updater.exe", b"new updater")
        archive.writestr("LICENSE.txt", b"license")
        archive.writestr("data/app.db", b"must never be copied")

    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "AI-Learning-Copilot.exe").write_bytes(b"old main")
    (app_dir / "AI-Learning-Copilot-Updater.exe").write_bytes(b"old updater")
    (app_dir / "data").mkdir()
    (app_dir / "data" / "app.db").write_bytes(b"user data")

    staging = tmp_path / "staging"
    backup = tmp_path / "backup"
    payload = _extract_payload(package, staging)
    changes = _apply_payload(payload, app_dir, backup)

    assert (app_dir / "AI-Learning-Copilot.exe").read_bytes() == b"new main"
    assert (app_dir / "AI-Learning-Copilot-Updater.exe").read_bytes() == b"new updater"
    assert (app_dir / "data" / "app.db").read_bytes() == b"user data"

    _rollback(changes)

    assert (app_dir / "AI-Learning-Copilot.exe").read_bytes() == b"old main"
    assert (app_dir / "AI-Learning-Copilot-Updater.exe").read_bytes() == b"old updater"
    assert (app_dir / "data" / "app.db").read_bytes() == b"user data"


def test_updater_rejects_zip_slip_paths(tmp_path: Path) -> None:
    package = tmp_path / "package.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("AI-Learning-Copilot.exe", b"main")
        archive.writestr("AI-Learning-Copilot-Updater.exe", b"updater")
        archive.writestr("../outside.txt", b"unsafe")

    try:
        _extract_payload(package, tmp_path / "staging")
    except RuntimeError as exc:
        assert "不安全路径" in str(exc)
    else:
        raise AssertionError("zip-slip path was accepted")
