from __future__ import annotations

import hashlib
import io
import json
import zipfile

from app.services.update import (
    ReleaseUpdateClient,
    UpdateInfo,
    is_newer_version,
    parse_version,
)


class _Response:
    def __init__(self, payload: bytes) -> None:
        self._stream = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def _package_bytes() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("AI-Learning-Copilot.exe", b"main")
        archive.writestr("AI-Learning-Copilot-Updater.exe", b"updater")
    return stream.getvalue()


def test_version_comparison_handles_stable_and_prerelease() -> None:
    assert is_newer_version("0.6.1", "0.6.0")
    assert is_newer_version("0.6.0", "0.6.0-beta.1")
    assert not is_newer_version("0.6.0-beta.1", "0.6.0")
    assert parse_version("v0.5.0b1") < parse_version("0.5.0")


def test_check_for_update_selects_portable_package_and_checksum() -> None:
    payload = {
        "tag_name": "v0.7.0",
        "name": "0.7.0",
        "html_url": "https://github.com/Chdosh/ai-learning-copilot/releases/tag/v0.7.0",
        "body": "更新说明",
        "published_at": "2026-08-17T00:00:00Z",
        "assets": [
            {
                "name": "AI-Learning-Copilot-0.7.0-win-x64.zip",
                "browser_download_url": "https://example.test/app.zip",
            },
            {
                "name": "SHA256SUMS.txt",
                "browser_download_url": "https://example.test/SHA256SUMS.txt",
            },
        ],
    }

    client = ReleaseUpdateClient(
        current_version="0.6.0",
        open_url=lambda request, timeout: _Response(
            json.dumps(payload).encode("utf-8")
        ),
    )

    info = client.check_for_update()

    assert info is not None
    assert info.version == "0.7.0"
    assert info.download_name == "AI-Learning-Copilot-0.7.0-win-x64.zip"
    assert info.checksum_url.endswith("SHA256SUMS.txt")


def test_download_accepts_existing_filename_first_checksum_format(tmp_path) -> None:
    package = _package_bytes()
    info = UpdateInfo(
        version="0.7.0",
        tag_name="v0.7.0",
        release_name="0.7.0",
        release_url="https://example.test/release",
        download_url="https://example.test/app.zip",
        download_name="AI-Learning-Copilot-0.7.0-win-x64.zip",
        checksum_url="https://example.test/SHA256SUMS.txt",
    )
    checksum = (
        f"{info.download_name}  {hashlib.sha256(package).hexdigest()}\n"
    ).encode("utf-8")

    def open_url(request, timeout):
        if request.full_url.endswith("SHA256SUMS.txt"):
            return _Response(checksum)
        return _Response(package)

    downloaded = ReleaseUpdateClient(
        current_version="0.6.0", open_url=open_url
    ).download(info)

    assert downloaded.package_path.is_file()
    assert downloaded.package_path.read_bytes() == package
