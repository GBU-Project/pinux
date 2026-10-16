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

    assert app.get_application_id() == "org.pinux.Pinux"
    assert app.get_flags() & Gio.ApplicationFlags.HANDLES_COMMAND_LINE
