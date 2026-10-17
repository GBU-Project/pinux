"""Uji unit untuk SettingsWindow.

Perujuk: task 18 pada tasklist.md, R3.4, R3.7, R6.5, R7.4, R9.3, R9.4, R9.5, R11.6.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

import pytest

from pinux.config import Settings
from pinux.configstore import ConfigStore
from pinux.credentials import CredentialStore
from pinux.translate.registry import ProviderRegistry
from pinux.ui.settings import SettingsWindow


@pytest.fixture(scope="module", autouse=True)
def init_adw() -> None:
    Adw.init()


def test_settings_window_initialization(tmp_path: Path) -> None:
    cfg_file = tmp_path / "pinux.toml"
    config_store = ConfigStore(cfg_file)
    cred_store = CredentialStore(tmp_path / "creds.toml", force_fallback=True)
    registry = ProviderRegistry(credential_store=cred_store)

    mock_shortcut_mgr = MagicMock()
    mock_shortcut_mgr.active_backend = "cli"
    mock_shortcut_mgr.bound_shortcuts = ()

    mock_ocr_client = MagicMock()
    mock_ocr_client.is_available.return_value = False

    saved_settings: list[Settings] = []

    win = SettingsWindow(
        config_store=config_store,
        credential_store=cred_store,
        provider_registry=registry,
        shortcut_manager=mock_shortcut_mgr,
        ocr_client=mock_ocr_client,
        session_type="wayland",
        on_settings_changed=saved_settings.append,
    )

    assert win.get_title() == "Pengaturan Pinux"

    # Periksa nilai awal baris pengaturan
    assert win._target_lang_row.get_text() == "id"
    assert win._fallback_lang_row.get_text() == "en"

    # Ubah pengaturan dan periksa autosave
    win._target_lang_row.set_text("ja")
    assert len(saved_settings) >= 1
    assert saved_settings[-1].target_language == "ja"

    # Periksa berkas toml tersimpan
    reloaded = config_store.load()
    assert reloaded.target_language == "ja"

    # Periksa hide_on_close aktif dan Escape dapat menutup jendela
    assert win.get_hide_on_close() is True
    from gi.repository import Gdk
    handled = win._on_key_pressed(None, Gdk.KEY_Escape, 0, 0)
    assert handled is True


def test_settings_window_credentials_saving(tmp_path: Path) -> None:
    cfg_file = tmp_path / "pinux.toml"
    config_store = ConfigStore(cfg_file)
    cred_store = CredentialStore(tmp_path / "creds.toml", force_fallback=True)
    registry = ProviderRegistry(credential_store=cred_store)

    from examples.deepl_provider import DeepLProvider
    registry.register(DeepLProvider())

    mock_shortcut_mgr = MagicMock()
    mock_shortcut_mgr.active_backend = "portal"
    mock_shortcut_mgr.bound_shortcuts = ()

    mock_ocr_client = MagicMock()
    mock_ocr_client.is_available.return_value = True

    win = SettingsWindow(
        config_store=config_store,
        credential_store=cred_store,
        provider_registry=registry,
        shortcut_manager=mock_shortcut_mgr,
        ocr_client=mock_ocr_client,
        session_type="x11",
    )

    # Isi API key DeepL
    assert "deepl" in win._cred_entries
    win._cred_entries["deepl"].set_text("sk-deepl-token")

    # Kredensial harus tersimpan di cred_store
    assert cred_store.get("deepl") == "sk-deepl-token"
