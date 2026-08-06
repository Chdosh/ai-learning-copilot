from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class OCRError(RuntimeError):
    pass


@dataclass(slots=True)
class OCRStatus:
    source: str
    available_languages: list[str]
    ok: bool
    message: str


class OCRService:
    """Lightweight OCR service backed by RapidOCR (ONNX Runtime)."""

    def __init__(self, **_kwargs) -> None:
        self._rapid_ocr = None

    def _get_engine(self):
        if self._rapid_ocr is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as exc:
                raise OCRError(
                    "未安装 RapidOCR。请执行: pip install rapidocr-onnxruntime"
                ) from exc

            try:
                self._rapid_ocr = RapidOCR(
                    det_limit_type="min",
                    det_limit_side_len=512,
                )
            except Exception as exc:
                raise OCRError(f"RapidOCR 初始化失败: {exc}") from exc

        return self._rapid_ocr

    def extract_text(self, image_path: str | Path) -> str:
        path = Path(image_path)
        if not path.exists():
            raise OCRError(f"截图文件不存在: {path}")

        engine = self._get_engine()

        try:
            # Screen captures are already upright; skip the per-line 0°/180°
            # classifier while keeping text detection and recognition enabled.
            result, _ = engine(str(path), use_cls=False)
        except Exception as exc:
            raise OCRError(f"RapidOCR 识别失败: {exc}") from exc

        if not result:
            return ""

        texts = []
        for item in result:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                text = item[1]
                if isinstance(text, str) and text.strip():
                    texts.append(text.strip())

        return _clean_text("\n".join(texts))

    def check_status(self) -> OCRStatus:
        available = self._get_available_langs()
        try:
            self._get_engine()
        except OCRError as exc:
            return OCRStatus(
                source="RapidOCR",
                available_languages=available,
                ok=False,
                message=str(exc),
            )

        return OCRStatus(
            source="RapidOCR (ONNX Runtime)",
            available_languages=available,
            ok=True,
            message=f"RapidOCR 可用；模型随依赖安装；支持语言: {', '.join(available)}",
        )

    def _get_available_langs(self) -> list[str]:
        return ["中文 (ch)", "English (en)"]


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
