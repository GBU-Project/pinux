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
    def _fake_async(cb, max_chars=5000):
        cb(CaptureResult(text="Hello world", truncated=False, origin="clipboard"))

    mock_app.text_capturer.read_source_text_async.side_effect = _fake_async
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


def test_trigger_router_request_ocr_file(tmp_path: Path) -> None:
    """request_ocr_file dengan path memuat berkas dan memanggil handler yang tepat."""
    mock_app = MagicMock()
    mock_popup = MagicMock()
    mock_app.get_popup_window.return_value = mock_popup
    router = TriggerRouter(mock_app)

    with pytest.MonkeyPatch.context() as mp:
        choose_called = False
        mp.setattr(router, "_choose_image_file", lambda copy_only, **kw: setattr(router, "_ch", copy_only))
        router.request_ocr_file(None, copy_only=True)
        assert getattr(router, "_ch", None) is True


    test_img = tmp_path / "test.png"
    from PIL import Image
    Image.new("RGB", (10, 10), (255, 0, 0)).save(test_img, format="PNG")

    from gi.repository import GLib

    def flush_glib(timeout: float = 0.5) -> None:
        import time
        start = time.time()
        ctx = GLib.MainContext.default()
        while time.time() - start < timeout:
            while ctx.iteration(False):
                pass
            time.sleep(0.02)
            if len(ocr_calls) > 0:
                break

    with pytest.MonkeyPatch.context() as mp:
        ocr_calls = []
        mp.setattr(router, "_on_ocr_image", lambda data, **kw: ocr_calls.append(("translate", data)))
        mp.setattr(router, "_on_ocr_pure_image", lambda data, **kw: ocr_calls.append(("copy", data)))


        router.request_ocr_file(str(test_img), copy_only=False)
        flush_glib()
        assert len(ocr_calls) == 1
        assert ocr_calls[0][0] == "translate"
        assert len(ocr_calls[0][1]) > 0

        router.request_ocr_file(str(test_img), copy_only=True)
        # Tunggu call kedua
        import time
        start = time.time()
        ctx = GLib.MainContext.default()
        while time.time() - start < 0.5:
            while ctx.iteration(False):
                pass
            time.sleep(0.02)
            if len(ocr_calls) == 2:
                break
        assert len(ocr_calls) == 2
        assert ocr_calls[1][0] == "copy"


def test_trigger_router_continuous_ocr_append() -> None:
    """Verifikasi bahwa dalam mode kontinu atau append, teks lama di popup diakumulasikan."""
    mock_app = MagicMock()
    mock_app.settings = Settings()
    mock_app.settings.ocr.continuous_ocr = True

    mock_popup = MagicMock()
    mock_popup.continuous_ocr = True
    mock_popup.source_text = "Kalimat awal"
    mock_popup.append_source_text.side_effect = lambda t: f"Kalimat awal\n\n{t}"
    mock_app.get_popup_window.return_value = mock_popup

    router = TriggerRouter(mock_app)

    with pytest.MonkeyPatch.context() as mp:
        executed_translations: list[str] = []
        mp.setattr(router, "_execute_translation", lambda t: executed_translations.append(t))

        # Panggil _on_ocr_image langsung dengan mode append aktif
        with pytest.MonkeyPatch.context() as mp2:
            mp2.setattr(router, "_run_ocr_in_background", lambda png, cb, **kw: cb("Kalimat kedua"))
            router._on_ocr_image(b"fake_png", append=True)

        assert mock_popup.append_source_text.called
        assert len(executed_translations) == 1
        assert executed_translations[0] == "Kalimat awal\n\nKalimat kedua"





def _command_line(*flags: str, cwd: str = "/tmp") -> MagicMock:
    from gi.repository import GLib

    options = GLib.VariantDict.new(None)
    for flag in flags:
        options.insert_value(flag, GLib.Variant.new_boolean(True))
    cmd = MagicMock()
    cmd.get_options_dict.return_value = options
    cmd.get_cwd.return_value = cwd
    return cmd


def test_command_line_ocr_copy_with_append_copies_without_translating(tmp_path: Path) -> None:
    app = PinuxApp(
        config_store=ConfigStore(tmp_path / "pinux.toml"),
        credential_store=CredentialStore(tmp_path / "creds.toml", force_fallback=True),
        shortcut_manager=MagicMock(),
        tray_item=MagicMock(),
    )
    app.trigger_router = MagicMock()
    app.activate_action = MagicMock()  # type: ignore[method-assign]

    assert app.do_command_line(_command_line("ocr-copy", "ocr-append")) == 0
    app.trigger_router.request_ocr_pure.assert_called_once_with(append=True)
    app.activate_action.assert_not_called()

    app.do_command_line(_command_line("ocr-append"))
    app.activate_action.assert_called_once_with("trigger-ocr-append", None)
