from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from functools import total_ordering
from pathlib import Path
from typing import Callable

from app import __version__
from app.paths import APP_DIR


REPOSITORY = "Chdosh/ai-learning-copilot"
DEFAULT_RELEASE_API_URL = (
    f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
)
MAIN_EXECUTABLE_NAME = "AI-Learning-Copilot.exe"
UPDATER_EXECUTABLE_NAME = "AI-Learning-Copilot-Updater.exe"
PACKAGE_SUFFIX = "win-x64.zip"
MAX_PACKAGE_BYTES = 512 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 8


class UpdateError(RuntimeError):
    """A user-facing update failure that should not break normal startup."""


@total_ordering
@dataclass(frozen=True, slots=True)
class ParsedVersion:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str | int, ...] = ()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ParsedVersion):
            return NotImplemented
        return (
            self.major,
            self.minor,
            self.patch,
            self.prerelease,
        ) == (
            other.major,
            other.minor,
            other.patch,
            other.prerelease,
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ParsedVersion):
            return NotImplemented
        left_base = (self.major, self.minor, self.patch)
        right_base = (other.major, other.minor, other.patch)
        if left_base != right_base:
            return left_base < right_base
        if not self.prerelease and other.prerelease:
            return False
        if self.prerelease and not other.prerelease:
            return True
        return _compare_prerelease(self.prerelease, other.prerelease) < 0


def _compare_prerelease(
    left: tuple[str | int, ...], right: tuple[str | int, ...]
) -> int:
    for left_item, right_item in zip(left, right):
        if left_item == right_item:
            continue
        if isinstance(left_item, int) and isinstance(right_item, int):
            return -1 if left_item < right_item else 1
        if isinstance(left_item, int) != isinstance(right_item, int):
            return -1 if isinstance(left_item, int) else 1
        left_rank = _prerelease_rank(str(left_item))
        right_rank = _prerelease_rank(str(right_item))
        if left_rank != right_rank:
            return -1 if left_rank < right_rank else 1
        return -1 if str(left_item) < str(right_item) else 1
    if len(left) == len(right):
        return 0
    return -1 if len(left) < len(right) else 1


def _prerelease_rank(value: str) -> tuple[int, str]:
    normalized = value.lower()
    known = {"alpha": 0, "a": 0, "beta": 1, "b": 1, "rc": 2}
    return known.get(normalized, 3), normalized


def parse_version(value: str) -> ParsedVersion:
    """Parse the version formats used by the app and its Git tags."""
    text = str(value or "").strip()
    text = text.lstrip("vV")
    text = re.sub(
        r"^(\d+\.\d+\.\d+)(alpha|a|beta|b|rc)(\d+)$",
        r"\1-\2.\3",
        text,
        flags=re.IGNORECASE,
    )
    match = re.fullmatch(
        r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?", text
    )
    if match is None:
        raise UpdateError(f"无法识别版本号：{value}")

    prerelease: list[str | int] = []
    raw_prerelease = match.group(4) or ""
    if raw_prerelease:
        for item in raw_prerelease.split("."):
            if not item:
                raise UpdateError(f"无法识别版本号：{value}")
            prerelease.append(int(item) if item.isdigit() else item.lower())
    return ParsedVersion(
        major=int(match.group(1)),
        minor=int(match.group(2)),
        patch=int(match.group(3)),
        prerelease=tuple(prerelease),
    )


def is_newer_version(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    version: str
    tag_name: str
    release_name: str
    release_url: str
    download_url: str
    download_name: str
    checksum_url: str
    release_notes: str = ""
    published_at: str = ""


@dataclass(frozen=True, slots=True)
class DownloadedUpdate:
    info: UpdateInfo
    package_path: Path


def _asset(assets: list[dict], predicate: Callable[[str], bool]) -> dict | None:
    for asset in assets:
        name = str(asset.get("name") or "")
        if predicate(name):
            return asset
    return None


def _package_asset(assets: list[dict], version: str) -> dict | None:
    expected = f"AI-Learning-Copilot-{version}-{PACKAGE_SUFFIX}"
    exact = _asset(assets, lambda name: name.lower() == expected.lower())
    if exact is not None:
        return exact
    return _asset(
        assets,
        lambda name: name.lower().endswith(PACKAGE_SUFFIX.lower())
        and name.lower().startswith("ai-learning-copilot-"),
    )


def _checksum_asset(assets: list[dict]) -> dict | None:
    return _asset(
        assets,
        lambda name: name.lower() in {"sha256sums.txt", "sha256sum.txt"},
    )


class ReleaseUpdateClient:
    """GitHub Releases adapter behind a small check/download interface."""

    def __init__(
        self,
        current_version: str = __version__,
        release_api_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        open_url: Callable[..., object] | None = None,
    ) -> None:
        self.current_version = current_version
        self.release_api_url = release_api_url or os.environ.get(
            "AI_LEARNING_COPILOT_UPDATE_URL", DEFAULT_RELEASE_API_URL
        )
        self.timeout = timeout
        self._open_url = open_url or urllib.request.urlopen

    def check_for_update(self) -> UpdateInfo | None:
        payload = self._get_json(self.release_api_url)
        if payload.get("draft") or payload.get("prerelease"):
            return None

        tag_name = str(payload.get("tag_name") or "").strip()
        version = tag_name.lstrip("vV")
        if not tag_name or not is_newer_version(version, self.current_version):
            return None

        assets = payload.get("assets")
        if not isinstance(assets, list):
            raise UpdateError("更新发布信息缺少资源列表。")
        package = _package_asset(assets, version)
        checksum = _checksum_asset(assets)
        if package is None:
            raise UpdateError(f"版本 {version} 没有 Windows x64 Portable ZIP。")
        if checksum is None:
            raise UpdateError("该版本没有 SHA256SUMS.txt，已停止更新。")

        download_url = str(package.get("browser_download_url") or "").strip()
        checksum_url = str(checksum.get("browser_download_url") or "").strip()
        if not download_url or not checksum_url:
            raise UpdateError("更新资源缺少下载地址。")

        return UpdateInfo(
            version=version,
            tag_name=tag_name,
            release_name=str(payload.get("name") or tag_name),
            release_url=str(payload.get("html_url") or ""),
            download_url=download_url,
            download_name=str(package.get("name") or ""),
            checksum_url=checksum_url,
            release_notes=str(payload.get("body") or "").strip(),
            published_at=str(payload.get("published_at") or ""),
        )

    def download(
        self,
        info: UpdateInfo,
        progress: Callable[[int, int], None] | None = None,
    ) -> DownloadedUpdate:
        update_dir = Path(tempfile.mkdtemp(prefix="ai-learning-copilot-update-"))
        partial_path = update_dir / f".{info.download_name}.part"
        package_path = update_dir / info.download_name
        try:
            request = urllib.request.Request(
                info.download_url,
                headers={
                    "Accept": "application/octet-stream",
                    "User-Agent": f"AI-Learning-Copilot/{self.current_version}",
                },
            )
            response = self._open_url(request, timeout=self.timeout)
            with response:
                total = int(response.headers.get("Content-Length") or 0)
                downloaded = 0
                digest = hashlib.sha256()
                with partial_path.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > MAX_PACKAGE_BYTES:
                            raise UpdateError("更新包超过允许的大小。")
                        digest.update(chunk)
                        output.write(chunk)
                        if progress is not None:
                            progress(downloaded, total)

            expected_hash = self._read_expected_hash(info)
            if expected_hash and digest.hexdigest().lower() != expected_hash.lower():
                raise UpdateError("更新包 SHA-256 校验失败。")
            self._validate_package(partial_path)
            partial_path.replace(package_path)
            return DownloadedUpdate(info=info, package_path=package_path)
        except UpdateError:
            raise
        except (OSError, urllib.error.URLError, ValueError) as exc:
            raise UpdateError(f"下载更新失败：{exc}") from exc
        finally:
            if partial_path.exists():
                partial_path.unlink(missing_ok=True)

    def _read_expected_hash(self, info: UpdateInfo) -> str:
        payload = self._read_bytes(info.checksum_url, max_bytes=128 * 1024)
        for line in payload.decode("utf-8", errors="replace").splitlines():
            parts = line.strip().split()
            if not parts:
                continue
            if len(parts) == 1 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
                return parts[0]
            if len(parts) >= 2:
                expected_hash = next(
                    (
                        part
                        for part in parts
                        if re.fullmatch(r"[0-9a-fA-F]{64}", part)
                    ),
                    None,
                )
                filenames = [part.lstrip("*") for part in parts if part != expected_hash]
                if expected_hash and any(Path(name).name == info.download_name for name in filenames):
                    return expected_hash
        raise UpdateError("SHA256SUMS.txt 中没有找到当前更新包。")

    def _validate_package(self, package_path: Path) -> None:
        try:
            with zipfile.ZipFile(package_path) as archive:
                if archive.testzip() is not None:
                    raise UpdateError("更新 ZIP 文件损坏。")
                names = [item.filename.replace("\\", "/") for item in archive.infolist()]
        except zipfile.BadZipFile as exc:
            raise UpdateError("更新包不是有效的 ZIP 文件。") from exc

        if not _has_basename(names, MAIN_EXECUTABLE_NAME):
            raise UpdateError("更新包缺少主程序。")
        if not _has_basename(names, UPDATER_EXECUTABLE_NAME):
            raise UpdateError("更新包缺少独立更新器。")

    def _get_json(self, url: str) -> dict:
        payload = self._read_bytes(url, max_bytes=2 * 1024 * 1024)
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpdateError("更新服务器返回的数据无效。") from exc
        if not isinstance(data, dict):
            raise UpdateError("更新服务器返回的数据格式无效。")
        return data

    def _read_bytes(self, url: str, max_bytes: int) -> bytes:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": f"AI-Learning-Copilot/{self.current_version}",
            },
        )
        try:
            response = self._open_url(request, timeout=self.timeout)
            with response:
                chunks: list[bytes] = []
                size = 0
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise UpdateError("更新服务器返回的数据过大。")
                    chunks.append(chunk)
                return b"".join(chunks)
        except UpdateError:
            raise
        except urllib.error.HTTPError as exc:
            raise UpdateError(f"更新服务器返回 HTTP {exc.code}。") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise UpdateError(f"无法连接更新服务器：{exc}") from exc


def _has_basename(names: list[str], expected: str) -> bool:
    return any(Path(name).name.lower() == expected.lower() for name in names)


def extract_updater(package_path: Path, target_dir: Path) -> Path:
    """Extract the new updater to a temp directory before the app exits."""
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / UPDATER_EXECUTABLE_NAME
    try:
        with zipfile.ZipFile(package_path) as archive:
            member = next(
                (
                    item
                    for item in archive.infolist()
                    if Path(item.filename.replace("\\", "/")).name.lower()
                    == UPDATER_EXECUTABLE_NAME.lower()
                ),
                None,
            )
            if member is None:
                raise UpdateError("更新包缺少独立更新器。")
            with archive.open(member) as source, target_path.open("wb") as output:
                shutil.copyfileobj(source, output)
    except zipfile.BadZipFile as exc:
        raise UpdateError("更新包不是有效的 ZIP 文件。") from exc
    except OSError as exc:
        raise UpdateError(f"准备更新器失败：{exc}") from exc
    return target_path


def launch_update(
    package_path: Path,
    *,
    app_dir: Path = APP_DIR,
    app_executable: Path | None = None,
    pid: int | None = None,
) -> Path:
    """Start the extracted updater and return its temporary executable path."""
    if not getattr(sys, "frozen", False):
        raise UpdateError("开发模式不会替换源码目录，请在 Portable EXE 中执行更新。")

    app_executable = app_executable or Path(sys.executable).resolve()
    launcher_dir = Path(tempfile.mkdtemp(prefix="ai-learning-copilot-updater-"))
    updater_path = extract_updater(package_path, launcher_dir)
    command = [
        str(updater_path),
        "--pid",
        str(pid or os.getpid()),
        "--package",
        str(Path(package_path).resolve()),
        "--app-dir",
        str(Path(app_dir).resolve()),
        "--app-exe",
        str(app_executable),
    ]
    creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0)
    creation_flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen(
            command,
            cwd=str(launcher_dir),
            close_fds=True,
            creationflags=creation_flags,
        )
    except OSError as exc:
        raise UpdateError(f"无法启动独立更新器：{exc}") from exc
    return updater_path
