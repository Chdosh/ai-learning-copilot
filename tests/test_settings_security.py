from __future__ import annotations

import os

from app.services.history_store import HistoryStore
from app.services.settings import (
    AppSettings,
    DpapiFileCredentialStore,
    FallbackCredentialStore,
    SettingsService,
)


class _FakeCredentialStore:
    """Dict-backed stand-in for the OS keyring used in tests."""

    def __init__(self, values: dict[str, str] | None = None, *, failing: bool = False) -> None:
        self.values = dict(values or {})
        self.failing = failing

    def get_password(self) -> str:
        if self.failing:
            return ""
        return self.values.get("api_key", "")

    def set_password(self, value: str) -> None:
        if self.failing:
            return
        self.values["api_key"] = value

    def delete_password(self) -> None:
        if self.failing:
            return
        self.values.pop("api_key", None)


def test_api_key_is_not_written_to_sqlite(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")
    credentials = _FakeCredentialStore()
    service = SettingsService(store, credential_store=credentials)

    settings = AppSettings(api_key="sk-secret-key", base_url="https://x", model="m")
    service.save(settings)

    assert "sk-secret-key" not in str(store.get_settings())
    assert store.get_settings().get("api_key") == ""
    assert credentials.values["api_key"] == "sk-secret-key"
    assert service.load().api_key == "sk-secret-key"


def test_api_key_roundtrip_through_credential_store(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")
    credentials = _FakeCredentialStore({"api_key": "sk-secret-key"})
    service = SettingsService(store, credential_store=credentials)

    assert service.load().api_key == "sk-secret-key"


def test_legacy_plaintext_api_key_is_migrated_and_cleared(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")
    store.set_setting("api_key", "sk-legacy-key")
    credentials = _FakeCredentialStore()
    service = SettingsService(store, credential_store=credentials)

    settings = service.load()

    assert settings.api_key == "sk-legacy-key"
    assert credentials.values["api_key"] == "sk-legacy-key"
    assert store.get_settings().get("api_key") == ""


def test_api_key_cleared_when_saved_empty(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")
    credentials = _FakeCredentialStore({"api_key": "sk-old"})
    service = SettingsService(store, credential_store=credentials)

    service.save(AppSettings(api_key=""))

    assert credentials.values.get("api_key") is None
    assert service.load().api_key == ""


def test_api_key_falls_back_to_env_variable(tmp_path, monkeypatch) -> None:
    store = HistoryStore(tmp_path / "app.db")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")
    service = SettingsService(store, credential_store=_FakeCredentialStore())

    assert service.load().api_key == "sk-env-key"


def test_dpapi_file_store_roundtrip(tmp_path) -> None:
    path = tmp_path / "credentials.bin"
    store = DpapiFileCredentialStore(path)

    store.set_password("sk-秘密-123")
    assert store.get_password() == "sk-秘密-123"
    assert path.read_bytes() != "sk-秘密-123".encode("utf-8")

    store.set_password("")
    assert store.get_password() == ""
    assert not path.exists()


def test_dpapi_file_store_delete_removes_file(tmp_path) -> None:
    path = tmp_path / "credentials.bin"
    store = DpapiFileCredentialStore(path)
    store.set_password("sk-1")
    store.delete_password()
    assert store.get_password() == ""
    assert not path.exists()


def test_float_bar_settings_roundtrip(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store, credential_store=_FakeCredentialStore())

    settings = service.load()
    assert settings.show_float_bar is True
    assert settings.bar_x is None
    assert settings.bar_y is None
    assert settings.bar_w is None
    assert settings.bar_h is None

    settings.show_float_bar = False
    settings.bar_x = 1234
    settings.bar_y = 567
    settings.bar_w = 452
    settings.bar_h = 210
    service.save(settings)

    reloaded = service.load()
    assert reloaded.show_float_bar is False
    assert reloaded.bar_x == 1234
    assert reloaded.bar_y == 567
    assert reloaded.bar_w == 452
    assert reloaded.bar_h == 210


def test_fallback_store_uses_dpapi_when_keyring_fails(tmp_path) -> None:
    store = FallbackCredentialStore(
        primary=_FakeCredentialStore(failing=True),
        fallback=DpapiFileCredentialStore(tmp_path / "credentials.bin"),
    )

    store.set_password("sk-fallback")
    assert store.get_password() == "sk-fallback"

    store.delete_password()
    assert store.get_password() == ""


def test_service_persists_key_via_dpapi_when_keyring_unavailable(tmp_path) -> None:
    db_store = HistoryStore(tmp_path / "app.db")
    dpapi = DpapiFileCredentialStore(tmp_path / "credentials.bin")
    service = SettingsService(
        db_store,
        credential_store=FallbackCredentialStore(
            primary=_FakeCredentialStore(failing=True),
            fallback=dpapi,
        ),
    )

    service.save(AppSettings(api_key="sk-dpapi"))

    reloaded = SettingsService(
        db_store,
        credential_store=FallbackCredentialStore(
            primary=_FakeCredentialStore(failing=True),
            fallback=DpapiFileCredentialStore(tmp_path / "credentials.bin"),
        ),
    )
    assert reloaded.load().api_key == "sk-dpapi"


def test_api_key_kept_in_session_when_keyring_unavailable(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")
    credentials = _FakeCredentialStore(failing=True)
    service = SettingsService(store, credential_store=credentials)

    service.save(AppSettings(api_key="sk-session-key"))
    assert store.get_settings().get("api_key") == ""

    settings = service.load()
    assert settings.api_key == "sk-session-key"


def test_save_screenshots_defaults_to_off(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")
    settings = AppSettings.from_mapping(store.get_settings())
    assert settings.save_screenshots is False

    service = SettingsService(store, credential_store=_FakeCredentialStore())
    service.save(AppSettings())
    assert service.load().save_screenshots is False


def test_regular_settings_still_roundtrip_via_sqlite(tmp_path) -> None:
    store = HistoryStore(tmp_path / "app.db")
    service = SettingsService(store, credential_store=_FakeCredentialStore())
    settings = service.load()
    settings.base_url = "https://api.example.com/v1"
    settings.model = "some-model"
    settings.hotkey = "<ctrl>+<alt>+x"
    settings.save_screenshots = True
    service.save(settings)

    reloaded = service.load()
    assert reloaded.base_url == "https://api.example.com/v1"
    assert reloaded.model == "some-model"
    assert reloaded.hotkey == "<ctrl>+<alt>+x"
    assert reloaded.save_screenshots is True
    assert "api_key" not in store.get_settings() or not store.get_settings().get("api_key")
