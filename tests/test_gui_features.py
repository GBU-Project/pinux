"""Tes GUI untuk fitur baru: TTS, bahasa popup, OCR berkas, dan baris pengaturan.

Berjalan dengan xvfb (``xvfb-run -a pytest``); dilewati bila GTK/libadwaita tidak ada.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

gi = pytest.importorskip("gi")
try:
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
except ValueError:  # pragma: no cover - lingkungan tanpa GTK
    pytest.skip("GTK4/libadwaita tidak tersedia", allow_module_level=True)

from gi.repository import Adw, Gtk  # noqa: E402

from pinux.config import Settings  # noqa: E402
from pinux.configstore import ConfigStore  # noqa: E402
from pinux.credentials import CredentialStore  # noqa: E402
from pinux.translate.base import AlternativeResult, TranslationResult  # noqa: E402
from pinux.translate.registry import ProviderRegistry  # noqa: E402
from pinux.ui.popup import PopupWindow  # noqa: E402
from pinux.ui.settings import SettingsWindow  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def init_adw() -> None:
    Adw.init()


def _children(box: Gtk.Widget) -> list[Gtk.Widget]:
    out, child = [], box.get_first_child()
    while child is not None:
        out.append(child)
        child = child.get_next_sibling()
    return out


def _labels(widget: Gtk.Widget) -> list[str]:
    found: list[str] = []

    def walk(w: Gtk.Widget) -> None:
        if isinstance(w, Gtk.Label):
            found.append(w.get_text())
        c = w.get_first_child()
        while c is not None:
            walk(c)
            c = c.get_next_sibling()

    walk(widget)
    return found


# --- Popup: kartu hasil bandingkan ---------------------------------------------


def test_popup_shows_and_clears_alternative_cards() -> None:
    popup = PopupWindow()
    res = TranslationResult(
        "halo", "en", "google-free",
        alternatives=(
            AlternativeResult("deepl", "DeepL", text="hai"),
            AlternativeResult("openai", "OpenAI", error="HTTP 429"),
        ),
    )
    popup.show_result(res)
    assert popup._alternatives_box.get_visible()
    labels = _labels(popup._alternatives_box)
    assert "DeepL" in labels and "hai" in labels and "Gagal: HTTP 429" in labels
    assert len(_children(popup._alternatives_box)) == 2

    popup.show_loading()  # permintaan baru membersihkan kartu lama
    assert not _children(popup._alternatives_box) and not popup._alternatives_box.get_visible()

    popup.show_result(TranslationResult("x", "en", "google-free"))
    assert not popup._alternatives_box.get_visible()


def test_popup_speak_buttons_use_languages_and_visibility() -> None:
    calls: list[tuple[str, str | None]] = []
    popup = PopupWindow(on_speak=lambda t, lang: calls.append((t, lang)), tts_available=True)
    assert popup._speak_source_button.get_visible() and popup._speak_result_button.get_visible()
    assert not PopupWindow(tts_available=False)._speak_source_button.get_visible()

    popup.set_source_text("hello")
    popup.show_result(TranslationResult("halo", "en", "google-free"))
    popup._speak_source_button.emit("clicked")
    popup._speak_result_button.emit("clicked")
    assert calls[0] == ("hello", "en")  # bahasa terdeteksi karena sumber = otomatis
    assert calls[1][0] == "halo"


def test_popup_language_state_and_buttons_visibility() -> None:
    popup = PopupWindow(on_ocr_file=lambda: None)
    assert popup._ocr_file_button.get_visible()
    assert not PopupWindow()._ocr_file_button.get_visible()

    popup.set_languages_display("auto", "ja")
    assert popup.source_lang is None and popup.target_lang == "ja"
    popup.show_detected_language("en")
    assert popup._lang_label.get_text() == "(terdeteksi: en)"
    popup.set_languages_display("fr", "ja")
    assert popup.source_lang == "fr"
    popup.show_detected_language("en")
    assert popup._lang_label.get_text() == ""  # sumber dikunci pengguna: tanpa label


# --- Jendela pengaturan ----------------------------------------------------------


def _settings_window(tmp_path):
    cfg = ConfigStore(tmp_path / "pinux.toml")
    creds = CredentialStore(tmp_path / "creds.toml", force_fallback=True)
    shortcuts = MagicMock()
    shortcuts.active_backend = "cli"
    shortcuts.bound_shortcuts = ()
    notified = []
    win = SettingsWindow(
        config_store=cfg,
        credential_store=creds,
        provider_registry=ProviderRegistry(credential_store=creds),
        shortcut_manager=shortcuts,
        ocr_client=MagicMock(),
        session_type="x11",
        on_settings_changed=notified.append,
    )
    return win, cfg, notified


def test_settings_llm_libre_fallback_compare_rows_persist(tmp_path) -> None:
    win, cfg, notified = _settings_window(tmp_path)

    win._llm_endpoint_row.set_text("http://localhost:11434/v1/chat/completions")
    win._llm_model_row.set_text("llama3")
    win._libre_endpoint_row.set_text("http://libre.local:5000")
    win._fallback_row.set_text("deepl, libretranslate, deepl")
    win._compare_row.set_text("openai")

    saved = cfg.load()
    assert saved.llm.model == "llama3"
    assert saved.llm.endpoint_url.startswith("http://localhost:11434")
    assert saved.libretranslate.endpoint_url == "http://libre.local:5000"
    assert saved.fallback_providers == ["deepl", "libretranslate"]
    assert saved.compare_providers == ["openai"]
    assert notified


def test_settings_invalid_urls_do_not_overwrite(tmp_path) -> None:
    win, cfg, _ = _settings_window(tmp_path)
    before = Settings().llm.endpoint_url
    win._llm_endpoint_row.set_text("ftp://bad")
    win._libre_endpoint_row.set_text("bukan-url")
    saved = cfg.load()
    assert saved.llm.endpoint_url == before
    assert saved.libretranslate.endpoint_url == Settings().libretranslate.endpoint_url


# --- Alur aplikasi: OCR berkas -----------------------------------------


def _pump(predicate, timeout: float = 3.0) -> bool:
    import time

    from gi.repository import GLib

    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for _ in range(100):
            if not ctx.pending():
                break
            ctx.iteration(False)
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_trigger_router_ocr_file_reports_errors_and_runs_ocr(tmp_path) -> None:
    from PIL import Image

    from pinux.app import TriggerRouter

    popup = MagicMock()
    # Callback idle GLib yang mengembalikan nilai truthy dijadwalkan berulang;
    # popup asli mengembalikan None, jadi tiruannya harus begitu juga.
    popup.show_error.return_value = None
    app = MagicMock()
    app.get_popup_window.return_value = popup
    router = TriggerRouter(app)

    router.request_ocr_file(str(tmp_path / "tidak-ada.png"))
    assert _pump(lambda: popup.show_error.called)
    assert "tidak ditemukan" in popup.show_error.call_args[0][0]

    good = tmp_path / "ok.png"
    Image.new("RGB", (30, 30), "white").save(good)
    seen: list[bytes] = []
    router._on_ocr_image = lambda png, append=None: seen.append(png)  # type: ignore[method-assign]
    router.request_ocr_file(str(good))
    assert _pump(lambda: bool(seen))
    assert seen[0].startswith(b"\x89PNG")

    copied: list[bytes] = []
    router._on_ocr_pure_image = lambda png, append=None: copied.append(png)  # type: ignore[method-assign]
    router.request_ocr_file(str(good), copy_only=True)
    assert _pump(lambda: bool(copied))
