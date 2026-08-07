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

KEYRING_SERVICE = "AI-Learning-Copilot"
KEYRING_API_KEY_USERNAME = "api_key"


class KeyringCredentialStore:
    """API Key lives in the OS credential manager, never in SQLite.

    Fallbacks (in order): system keyring -> ``OPENAI_API_KEY`` env ->
    session memory (keyring unavailable) -> legacy SQLite value (migrated
    out on first load, then the plaintext row is cleared).
    """

    def get_password(self) -> str:
        try:
            import keyring

            return keyring.get_password(KEYRING_SERVICE, KEYRING_API_KEY_USERNAME) or ""
        except Exception:
            return ""

    def set_password(self, value: str) -> None:
        try:
            import keyring

            keyring.set_password(KEYRING_SERVICE, KEYRING_API_KEY_USERNAME, value)
        except Exception:
            return None

    def delete_password(self) -> None:
        try:
            import keyring

            keyring.delete_password(KEYRING_SERVICE, KEYRING_API_KEY_USERNAME)
        except Exception:
            return None


@dataclass(slots=True)
class AppSettings:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    hotkey: str = DEFAULT_HOTKEY
    save_screenshots: bool = False
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
            base_url=values.get("base_url") or os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL),
            model=values.get("model") or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
            hotkey=values.get("hotkey") or DEFAULT_HOTKEY,
            save_screenshots=(values.get("save_screenshots", "false").lower() == "true"),
            context_block=values.get("context_block") or "",
            current_context_id=current_context_id,
            result_font_size=result_font_size,
        )

    def to_mapping(self) -> dict[str, str]:
        # api_key is intentionally absent: it is stored in the OS keyring.
        return {
            "base_url": self.base_url,
            "model": self.model,
            "hotkey": self.hotkey,
            "save_screenshots": "true" if self.save_screenshots else "false",
            "context_block": self.context_block,
            "current_context_id": "" if self.current_context_id is None else str(self.current_context_id),
            "result_font_size": str(self.result_font_size),
        }


class SettingsService:
    def __init__(self, store: HistoryStore, credential_store: KeyringCredentialStore | None = None) -> None:
        self.store = store
        self._credentials = credential_store or KeyringCredentialStore()
        self._session_api_key = ""

    def load(self) -> AppSettings:
        values = self.store.get_settings()
        settings = AppSettings.from_mapping(values)
        api_key = self._credentials.get_password()
        if not api_key:
            api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            api_key = self._session_api_key
        legacy = values.get("api_key") or ""
        if legacy:
            if not api_key:
                api_key = legacy
            self._credentials.set_password(api_key)
            self._session_api_key = api_key
            self.store.set_setting("api_key", "")
        settings.api_key = api_key
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
        # Never persist the API key in SQLite; it lives in the OS keyring.
        self.store.set_setting("api_key", "")
        for key, value in settings.to_mapping().items():
            self.store.set_setting(key, value)
        if settings.api_key:
            self._credentials.set_password(settings.api_key)
            self._session_api_key = settings.api_key
        else:
            self._credentials.delete_password()
            self._session_api_key = ""
