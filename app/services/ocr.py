from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.paths import VENDOR_TESSDATA_DIR, VENDOR_TESSERACT_DIR, VENDOR_TESSERACT_EXE


class OCRError(RuntimeError):
    pass


@dataclass(slots=True)
class OCRStatus:
    executable: str
    source: str
    available_languages: list[str]
    missing_languages: list[str]
    ok: bool
    message: str


class OCRService:
    """Lightweight OCR service backed by portable-first Tesseract CLI."""

    def __init__(self, lang: str = "eng+chi_sim", tesseract_path: str = "") -> None:
        self.lang = _normalize_lang(lang)
        self.tesseract_path = tesseract_path.strip()

    def extract_text(self, image_path: str | Path) -> str:
        path = Path(image_path)
        if not path.exists():
            raise OCRError(f"截图文件不存在: {path}")

        status = self.check_status()
        if not status.ok:
            raise OCRError(status.message)

        text = self._run_tesseract(status.executable, path, page_segmentation_mode="6")
        if not text:
            text = self._run_tesseract(status.executable, path, page_segmentation_mode="11")
        return _clean_text(text)

    def check_status(self) -> OCRStatus:
        executable, source = self._find_executable()
        expected = {lang for lang in self.lang.split("+") if lang}
        if not executable:
            return OCRStatus(
                executable="",
                source="",
                available_languages=[],
                missing_languages=sorted(expected),
                ok=False,
                message=(
                    "未找到 OCR 引擎。请把便携版 Tesseract 放到 vendor/tesseract，"
                    "或在设置页填写 tesseract.exe 路径。"
                ),
            )

        available = self._list_languages(executable)
        missing = sorted(lang for lang in expected if lang not in available)
        if missing:
            return OCRStatus(
                executable=executable,
                source=source,
                available_languages=available,
                missing_languages=missing,
                ok=False,
                message=(
                    "OCR 引擎已找到，但缺少语言包: "
                    + ", ".join(missing)
                    + "。便携方案应包含 vendor/tesseract/tessdata/eng.traineddata "
                    + "和 chi_sim.traineddata。"
                ),
            )

        return OCRStatus(
            executable=executable,
            source=source,
            available_languages=available,
            missing_languages=[],
            ok=True,
            message=f"OCR 可用：{source}；语言：{', '.join(available) or '未知'}",
        )

    def _find_executable(self) -> tuple[str, str]:
        candidates = [
            (str(VENDOR_TESSERACT_EXE), "内置便携 OCR"),
            (self.tesseract_path, "设置路径"),
            (r"C:\Program Files\Tesseract-OCR\tesseract.exe", "系统安装"),
            (r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe", "系统安装"),
            (shutil.which("tesseract") or "", "PATH"),
        ]
        for candidate, source in candidates:
            if not candidate:
                continue
            candidate_path = Path(candidate)
            if candidate_path.exists() or shutil.which(candidate):
                return candidate, source
        return "", ""

    def _list_languages(self, executable: str) -> list[str]:
        try:
            completed = subprocess.run(
                [executable, "--list-langs"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                creationflags=_creation_flags(),
                env=_tesseract_env(executable),
            )
        except Exception:
            return []

        if completed.returncode != 0:
            return []

        return sorted(
            line.strip()
            for line in completed.stdout.splitlines()
            if line.strip() and not line.startswith("List of available languages")
        )

    def _run_tesseract(self, executable: str, image_path: Path, page_segmentation_mode: str) -> str:
        command = [
            executable,
            str(image_path),
            "stdout",
            "-l",
            self.lang,
            "--psm",
            page_segmentation_mode,
            "--dpi",
            "300",
            "-c",
            "preserve_interword_spaces=1",
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                creationflags=_creation_flags(),
                env=_tesseract_env(executable),
            )
        except FileNotFoundError as exc:
            raise OCRError("未找到 Tesseract OCR 可执行文件。") from exc
        except subprocess.TimeoutExpired as exc:
            raise OCRError("Tesseract OCR 识别超时。请尝试框选更小的区域。") from exc

        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "").strip()
            if _looks_like_missing_language(message):
                raise OCRError(
                    "Tesseract 缺少 OCR 语言包。便携方案需要 eng 和 chi_sim。"
                )
            raise OCRError(f"Tesseract OCR 识别失败: {message}")
        return completed.stdout.strip()


def _normalize_lang(lang: str) -> str:
    value = (lang or "eng+chi_sim").strip().lower()
    aliases = {
        "en": "eng",
        "english": "eng",
        "zh": "chi_sim",
        "zh-cn": "chi_sim",
        "chinese": "chi_sim",
        "mixed": "eng+chi_sim",
        "zh+en": "eng+chi_sim",
        "en+zh": "eng+chi_sim",
    }
    return aliases.get(value, value)


def _clean_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(_dedupe_preserve_order(lines)).strip()


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = value.casefold()
        if normalized not in seen:
            seen.add(normalized)
            output.append(value)
    return output


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _looks_like_missing_language(message: str) -> bool:
    lowered = message.lower()
    return (
        "failed loading language" in lowered
        or "could not initialize tesseract" in lowered
        or "error opening data file" in lowered
    )


def _tessdata_prefix_for(executable: str) -> Path | None:
    exe_path = Path(executable)
    try:
        if exe_path.resolve() == VENDOR_TESSERACT_EXE.resolve() and VENDOR_TESSDATA_DIR.exists():
            return VENDOR_TESSDATA_DIR
    except OSError:
        pass

    local_tessdata = exe_path.parent / "tessdata"
    if local_tessdata.exists():
        return local_tessdata
    return None


def _tesseract_env(executable: str) -> dict[str, str] | None:
    prefix = _tessdata_prefix_for(executable)
    if not prefix:
        return None
    env = os.environ.copy()
    env["TESSDATA_PREFIX"] = str(prefix)
    return env
