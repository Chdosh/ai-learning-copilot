from __future__ import annotations

import os
from dataclasses import dataclass

from app.services.history_store import HistoryStore


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_HOTKEY = "<ctrl>+<alt>+t"
DEFAULT_OCR_LANG = "eng+chi_sim"


@dataclass(slots=True)
class AppSettings:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    hotkey: str = DEFAULT_HOTKEY
    save_screenshots: bool = True
    ocr_lang: str = DEFAULT_OCR_LANG
    tesseract_path: str = ""

    @classmethod
    def from_mapping(cls, values: dict[str, str]) -> "AppSettings":
        return cls(
            api_key=values.get("api_key") or os.environ.get("OPENAI_API_KEY", ""),
            base_url=values.get("base_url") or os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL),
            model=values.get("model") or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
            hotkey=values.get("hotkey") or DEFAULT_HOTKEY,
            save_screenshots=(values.get("save_screenshots", "true").lower() == "true"),
            ocr_lang=values.get("ocr_lang") or DEFAULT_OCR_LANG,
            tesseract_path=values.get("tesseract_path") or os.environ.get("TESSERACT_PATH", ""),
        )

    def to_mapping(self) -> dict[str, str]:
        return {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "hotkey": self.hotkey,
            "save_screenshots": "true" if self.save_screenshots else "false",
            "ocr_lang": self.ocr_lang,
            "tesseract_path": self.tesseract_path,
        }


class SettingsService:
    def __init__(self, store: HistoryStore) -> None:
        self.store = store

    def load(self) -> AppSettings:
        return AppSettings.from_mapping(self.store.get_settings())

    def save(self, settings: AppSettings) -> None:
        for key, value in settings.to_mapping().items():
            self.store.set_setting(key, value)
