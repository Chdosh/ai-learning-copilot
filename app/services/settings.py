from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.paths import DATA_DIR
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
CREDENTIALS_PATH = DATA_DIR / "credentials.bin"

_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _dpapi_protect(data: bytes) -> bytes:
    """Encrypt bytes with Windows DPAPI (user-bound)."""
    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    blob_out = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptProtectData.restype = ctypes.wintypes.BOOL
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.wintypes.LPWSTR,
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    if not crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(blob_out),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    """Decrypt bytes previously protected by :func:`_dpapi_protect`."""
    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    blob_out = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptUnprotectData.restype = ctypes.wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.POINTER(ctypes.wintypes.LPWSTR),
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    if not crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(blob_out),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


class CredentialStore(Protocol):
    """Interface implemented by all credential storage backends."""

    def get_password(self) -> str: ...

    def set_password(self, value: str) -> None: ...

    def delete_password(self) -> None: ...


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


class DpapiFileCredentialStore:
    """Windows DPAPI-encrypted local file credential store.

    Zero external dependencies (ctypes against Crypt32). The blob is bound
    to the current Windows user account, so it works even in frozen
    one-file builds where ``keyring`` and its backends are unavailable.
    """

    def __init__(self, path: str | Path = CREDENTIALS_PATH) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def get_password(self) -> str:
        try:
            blob = self._path.read_bytes()
            return _dpapi_unprotect(blob).decode("utf-8")
        except Exception:
            return ""

    def set_password(self, value: str) -> None:
        if not value:
            self.delete_password()
            return
        try:
            self._path.write_bytes(_dpapi_protect(value.encode("utf-8")))
        except Exception:
            return None

    def delete_password(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        except Exception:
            return None


class FallbackCredentialStore:
    """Credential store that chains keyring with a DPAPI file fallback.

    ``get_password`` reads keyring first, then the local file; writes go to
    both, so the API key never disappears even when the OS keyring (or its
    backend discovery) fails inside a frozen build.
    """

    def __init__(
        self,
        primary: CredentialStore | None = None,
        fallback: CredentialStore | None = None,
    ) -> None:
        self._primary = primary or KeyringCredentialStore()
        self._fallback = fallback or DpapiFileCredentialStore()

    def get_password(self) -> str:
        return self._primary.get_password() or self._fallback.get_password()

    def set_password(self, value: str) -> None:
        self._primary.set_password(value)
        self._fallback.set_password(value)

    def delete_password(self) -> None:
        self._primary.delete_password()
        self._fallback.delete_password()


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
    show_float_bar: bool = True
    bar_x: int | None = None
    bar_y: int | None = None
    bar_w: int | None = None
    bar_h: int | None = None

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

        def _optional_int(key: str) -> int | None:
            raw_value = values.get(key)
            if not raw_value:
                return None
            try:
                return int(raw_value)
            except (TypeError, ValueError):
                return None

        return cls(
            base_url=values.get("base_url") or os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL),
            model=values.get("model") or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
            hotkey=values.get("hotkey") or DEFAULT_HOTKEY,
            save_screenshots=(values.get("save_screenshots", "false").lower() == "true"),
            context_block=values.get("context_block") or "",
            current_context_id=current_context_id,
            result_font_size=result_font_size,
            show_float_bar=(values.get("show_float_bar", "true").lower() != "false"),
            bar_x=_optional_int("bar_x"),
            bar_y=_optional_int("bar_y"),
            bar_w=_optional_int("bar_w"),
            bar_h=_optional_int("bar_h"),
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
            "show_float_bar": "true" if self.show_float_bar else "false",
            "bar_x": "" if self.bar_x is None else str(self.bar_x),
            "bar_y": "" if self.bar_y is None else str(self.bar_y),
            "bar_w": "" if self.bar_w is None else str(self.bar_w),
            "bar_h": "" if self.bar_h is None else str(self.bar_h),
        }


class SettingsService:
    def __init__(self, store: HistoryStore, credential_store: CredentialStore | None = None) -> None:
        self.store = store
        self._credentials = credential_store or FallbackCredentialStore()
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
