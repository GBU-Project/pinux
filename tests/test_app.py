"""Uji unit untuk PinuxApp dan TriggerRouter (task 19).

Perujuk: R1.1, R1.6, R6.3, R8.1, R8.3, R8.4, R10.1, serta Properti 1.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk

import pytest

from pinux import APP_ID
from pinux.app import PinuxApp, TriggerRouter
from pinux.capture.base import CaptureResult
from pinux.config import Settings
from pinux.configstore import ConfigStore
from pinux.credentials import CredentialStore
from pinux.translate.base import TranslationResult
from pinux.translate.registry import ProviderRegistry


@pytest.fixture(scope="module", autouse=True)
def init_adw() -> None:
    Adw.init()


def test_trigger_router_request_translate() -> None:
    mock_app = MagicMock()
    mock_app.settings = Settings()
    mock_app.text_capturer.read_source_text.return_value = CaptureResult(
        text="Hello world",
        truncated=False,
        origin="clipboard",
    )

    mock_popup = MagicMock()
    mock_app.get_popup_window.return_value = mock_popup

    router = TriggerRouter(mock_app)
    router.request_translate()

    mock_popup.set_source_text.assert_called_once_with("Hello world")
    mock_popup.present_at_cursor.assert_called_once()
    mock_app.scheduler.submit.assert_called_once()


def test_trigger_router_on_shortcut_activated() -> None:
    mock_app = MagicMock()
    mock_app.settings = Settings()
    router = TriggerRouter(mock_app)

    with pytest.MonkeyPatch.context() as mp:
        trig_called = False
        ocr_called = False

        mp.setattr(router, "request_translate", lambda: setattr(router, "_trig", True))
        mp.setattr(router, "request_ocr", lambda: setattr(router, "_ocr", True))

        router.on_shortcut_activated("translate")
        assert getattr(router, "_trig", False) is True

        router.on_shortcut_activated("ocr")
        assert getattr(router, "_ocr", False) is True


def test_pinux_app_singleton_and_options(tmp_path: Path) -> None:
    cfg = ConfigStore(tmp_path / "pinux.toml")
    creds = CredentialStore(tmp_path / "creds.toml", force_fallback=True)

    app = PinuxApp(
        config_store=cfg,
        credential_store=creds,
        shortcut_manager=MagicMock(),
        tray_item=MagicMock(),
    )

    assert app.get_application_id() == APP_ID
    assert app.get_flags() & Gio.ApplicationFlags.HANDLES_COMMAND_LINE


def test_trigger_router_input_translate_and_show() -> None:
    mock_app = MagicMock()
    mock_popup = MagicMock()
    mock_app.get_popup_window.return_value = mock_popup

    router = TriggerRouter(mock_app)
    router.request_input_translate()
    mock_popup.set_source_text.assert_called_with("")
    mock_popup.present_at_cursor.assert_called_with(0, 0)

    mock_popup.reset_mock()
    router.show_popup_window()
    mock_popup.present_at_cursor.assert_called_once_with(0, 0)


def test_trigger_router_request_ocr_pure() -> None:
    mock_app = MagicMock()
    mock_overlay = MagicMock()
    mock_app.get_region_overlay.return_value = mock_overlay

    router = TriggerRouter(mock_app)
    router.request_ocr_pure()
    mock_overlay.open.assert_called_once()


def test_pinux_app_swap_languages(tmp_path: Path) -> None:
    cfg = ConfigStore(tmp_path / "pinux.toml")
    creds = CredentialStore(tmp_path / "creds.toml", force_fallback=True)

    app = PinuxApp(
        config_store=cfg,
        credential_store=creds,
        shortcut_manager=MagicMock(),
        tray_item=MagicMock(),
    )
    app.settings.target_language = "id"
    app.settings.fallback_language = "en"

    mock_popup = MagicMock()
    mock_popup.result_text = "Halo dunia"
    mock_popup.source_text = "Hello world"
    app._popup_window = mock_popup

    with pytest.MonkeyPatch.context() as mp:
        executed_calls: list[tuple[str, str | None, str | None]] = []

        def mock_exec(t: str, source_lang: str | None = None, target_lang: str | None = None) -> None:
            executed_calls.append((t, source_lang, target_lang))

        mp.setattr(app.trigger_router, "_execute_translation", mock_exec)

        app._on_swap_languages()

        # Bahasa target dan fallback bertukar
        assert app.settings.target_language == "en"
        assert app.settings.fallback_language == "id"
        # Hasil terjemahan dipasang ke popup dan diterjemahkan kembali
        mock_popup.set_source_text.assert_called_once_with("Halo dunia")
        assert len(executed_calls) == 1
        assert executed_calls[0] == ("Halo dunia", "id", "en")


def test_app_on_language_changed() -> None:
    app = PinuxApp.__new__(PinuxApp)
    app.settings = Settings()
    app.settings.target_language = "id"
    app.trigger_router = MagicMock()

    mock_popup = MagicMock()
    mock_popup.source_text = "Testing sentence"
    app._popup_window = mock_popup

    app._on_language_changed("en", "ja")
    assert app.settings.target_language == "ja"
    app.trigger_router._execute_translation.assert_called_once_with(
        "Testing sentence",
        source_lang="en",
        target_lang="ja",
    )




def test_request_ocr_uses_frozen_frame_picker() -> None:
    """OCR memakai tangkapan layar lebih dulu (bingkai beku), bukan overlay transparan."""
    mock_app = MagicMock()
    mock_overlay = MagicMock()
    mock_app.get_region_overlay.return_value = mock_overlay

    TriggerRouter(mock_app).request_ocr()

    mock_app.hide_popup_for_capture.assert_called_once()
    kwargs = mock_overlay.open.call_args.kwargs
    assert kwargs["screenshot_provider"] is mock_app.screenshot_portal.capture_fullscreen
    assert callable(kwargs["on_image"]) and callable(kwargs["on_error"])
