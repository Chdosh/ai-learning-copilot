from __future__ import annotations

import os
from dataclasses import dataclass

from app.services.history_store import HistoryStore
from app.services.prompt_builder import render_context_block


DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_HOTKEY = "<ctrl>+<alt>+t"
DEFAULT_RESULT_FONT_SIZE = 12
MIN_RESULT_FONT_SIZE = 10
MAX_RESULT_FONT_SIZE = 18


@dataclass(slots=True)
class AppSettings:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    hotkey: str = DEFAULT_HOTKEY
    save_screenshots: bool = True
    context_block: str = ""
    current_context_id: int | None = None
    result_font_size: int = DEFAULT_RESULT_FONT_SIZE

    @classmethod
    def from_mapping(cls, values: dict[str, str]) -> "AppSettings":
        current_context_id: int | None = None
        raw = values.get("current_context_id")
        if raw:
            try:
                current_context_id = int(raw)
            except (TypeError, ValueError):
                current_context_id = None
        try:
            result_font_size = int(values.get("result_font_size") or DEFAULT_RESULT_FONT_SIZE)
        except (TypeError, ValueError):
            result_font_size = DEFAULT_RESULT_FONT_SIZE
        result_font_size = max(MIN_RESULT_FONT_SIZE, min(MAX_RESULT_FONT_SIZE, result_font_size))
        return cls(
            api_key=values.get("api_key") or os.environ.get("OPENAI_API_KEY", ""),
            base_url=values.get("base_url") or os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL),
            model=values.get("model") or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
            hotkey=values.get("hotkey") or DEFAULT_HOTKEY,
            save_screenshots=(values.get("save_screenshots", "true").lower() == "true"),
            context_block=values.get("context_block") or "",
            current_context_id=current_context_id,
            result_font_size=result_font_size,
        )

    def to_mapping(self) -> dict[str, str]:
        return {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "hotkey": self.hotkey,
            "save_screenshots": "true" if self.save_screenshots else "false",
            "context_block": self.context_block,
            "current_context_id": "" if self.current_context_id is None else str(self.current_context_id),
            "result_font_size": str(self.result_font_size),
        }


class SettingsService:
    def __init__(self, store: HistoryStore) -> None:
        self.store = store

    def load(self) -> AppSettings:
        settings = AppSettings.from_mapping(self.store.get_settings())
        settings.context_block = self.resolve_context_block(settings)
        return settings

    def resolve_context_block(self, settings: AppSettings) -> str:
        """Bridge: render the current context record as the prompt block.

        The record is the source of truth; a stale stored ``context_block`` is
        only used as a fallback when no context is selected or it no longer exists.
        """
        if settings.current_context_id is not None:
            context = self.store.get_context(settings.current_context_id)
            if context is not None:
                return render_context_block(
                    domain=context.domain,
                    scene=context.scene,
                    summary=context.summary,
                    instruction=context.instruction,
                )
        return settings.context_block

    def set_current_context(self, context_id: int | None) -> None:
        self.store.set_setting("current_context_id", "" if context_id is None else str(context_id))
        self.store.set_setting("quick_domain", "通用")
        self.store.set_setting("quick_scene", "通用")
        self.store.set_setting("context_block", "")

    def set_quick_context(self, domain: str, scene: str) -> None:
        domain = domain or "通用"
        scene = scene or "通用"
        self.store.set_setting("current_context_id", "")
        self.store.set_setting("quick_domain", domain)
        self.store.set_setting("quick_scene", scene)
        self.store.set_setting("context_block", render_context_block(domain=domain, scene=scene))

    def get_quick_context(self) -> tuple[str, str]:
        values = self.store.get_settings()
        return values.get("quick_domain") or "通用", values.get("quick_scene") or "通用"

    def save(self, settings: AppSettings) -> None:
        for key, value in settings.to_mapping().items():
            self.store.set_setting(key, value)
