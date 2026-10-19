"""Uji unit untuk PopupWindow.

Perujuk: task 15.1 pada tasklist.md, R1.4, R1.5, R5.1, R5.2, R5.5, R5.6,
serta Properti 4 (tidak ada keadaan memuat yang tersisa) pada design.md.
"""

from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk

import pytest

from pinux.translate.base import TranslationResult
from pinux.ui.popup import PopupWindow


@pytest.fixture(scope="module", autouse=True)
def init_gtk() -> None:
    """Inisialisasi GTK sebelum pengujian UI berjalan."""
    Gtk.init()


def test_popup_window_initial_state() -> None:
    popup = PopupWindow(pin_default=False, width=450)
    assert popup.pinned is False
    assert popup.get_decorated() is False
    assert popup.get_resizable() is True


def test_popup_window_pin_toggle() -> None:
    popup = PopupWindow(pin_default=False)
    popup.pinned = True
    assert popup.pinned is True
    assert popup._pin_button.get_active() is True

    popup.pinned = False
    assert popup.pinned is False
    assert popup._pin_button.get_active() is False


def test_popup_window_focus_loss_behavior() -> None:
    """R5.1: Bila di luar Pinned_State, kehilangan fokus menutup jendela."""
    popup = PopupWindow(pin_default=False)

    # Ketika tidak aktif dan tidak di-pin -> tertutup (hide dipanggil)
    with pytest.MonkeyPatch.context() as mp:
        hide_called = False

        def mock_hide() -> None:
            nonlocal hide_called
            hide_called = True

        mp.setattr(popup, "hide", mock_hide)
        mp.setattr(popup, "is_active", lambda: False)

        popup._on_is_active_changed(popup, None)
        assert hide_called is True

    # Ketika tidak aktif tetapi popover dropdown sedang terbuka -> TIDAK tertutup
    popup.pinned = False
    with pytest.MonkeyPatch.context() as mp:
        hide_called = False
        mp.setattr(popup, "hide", lambda: setattr(popup, "_test_hidden", True))
        mp.setattr(popup, "is_active", lambda: False)
        mp.setattr(popup, "_has_open_popover", lambda: True)

        popup._on_is_active_changed(popup, None)
        assert getattr(popup, "_test_hidden", False) is False

    # Ketika pinned=True, kehilangan fokus TIDAK menutup jendela (R5.6)
    popup.pinned = True
    with pytest.MonkeyPatch.context() as mp:
        hide_called = False

        def mock_hide() -> None:
            nonlocal hide_called
            hide_called = True

        mp.setattr(popup, "hide", mock_hide)
        mp.setattr(popup, "is_active", lambda: False)

        popup._on_is_active_changed(popup, None)
        assert hide_called is False


def test_popup_window_escape_key_closes_window() -> None:
    """R5.2: Tombol Escape menutup popup."""
    popup = PopupWindow()

    with pytest.MonkeyPatch.context() as mp:
        hide_called = False

        def mock_hide() -> None:
            nonlocal hide_called
            hide_called = True

        mp.setattr(popup, "hide", mock_hide)

        handled = popup._on_key_pressed(None, Gdk.KEY_Escape, 0, 0)
        assert handled is True
        assert hide_called is True


def test_popup_window_loading_and_result_stops_spinner() -> None:
    """Properti 4: show_loading menyalakan spinner, show_result & show_error menghentikannya."""
    popup = PopupWindow()

    # Mulai memuat
    popup.show_loading()
    assert popup._spinner.get_spinning() is True
    assert popup._spinner.get_visible() is True
    assert popup._error_label.get_visible() is False

    # Hasil tiba -> spinner berhenti
    res = TranslationResult("Terjemahan sukses", "en", "google-free")
    popup.show_result(res)
    assert popup._spinner.get_spinning() is False
    assert popup._spinner.get_visible() is False
    assert popup._result_label.get_text() == "Terjemahan sukses"
    assert popup._result_label.get_visible() is True

    # Uji jalur galat: memuat -> show_error -> spinner berhenti
    popup.show_loading()
    assert popup._spinner.get_spinning() is True

    popup.show_error("Koneksi gagal")
    assert popup._spinner.get_spinning() is False
    assert popup._spinner.get_visible() is False
    assert popup._error_label.get_text() == "Koneksi gagal"
    assert popup._error_label.get_visible() is True


def test_popup_window_set_source_text_does_not_loop() -> None:
    changed_texts: list[str] = []
    popup = PopupWindow(on_text_changed=changed_texts.append)

    # set_source_text tidak boleh memicu callback on_text_changed
    popup.set_source_text("Teks dari clipboard")
    assert changed_texts == []
    assert popup._entry.get_text() == "Teks dari clipboard"


def test_popup_window_actions() -> None:
    swapped = False
    ocr_triggered = False
    copied_text = ""

    def on_swap() -> None:
        nonlocal swapped
        swapped = True

    def on_ocr() -> None:
        nonlocal ocr_triggered
        ocr_triggered = True

    def on_copy(t: str) -> None:
        nonlocal copied_text
        copied_text = t

    popup = PopupWindow(
        on_swap_languages=on_swap,
        on_trigger_ocr=on_ocr,
        on_copy_result=on_copy,
    )

    popup.show_result(TranslationResult("Hasil Terjemah", "en", "dummy"))

    popup._swap_button.emit("clicked")
    assert swapped is True

    popup._ocr_button.emit("clicked")
    assert ocr_triggered is True

    popup._copy_button.emit("clicked")
    assert copied_text == "Hasil Terjemah"


def test_popup_window_language_selection() -> None:
    selected_source = None
    selected_target = None

    def on_lang(src: str | None, tgt: str) -> None:
        nonlocal selected_source, selected_target
        selected_source = src
        selected_target = tgt

    popup = PopupWindow(on_language_selected=on_lang)
    popup.set_languages_display("en", "id")

    # Pilih bahasa target ke 'en' (indeks 1 pada target_languages)
    popup._tgt_dropdown.set_selected(1)
    assert selected_target == "en"

    # Pilih bahasa sumber ke 'ja' (indeks 3 pada LANGUAGES: auto=0, id=1, en=2, ja=3)
    popup._src_dropdown.set_selected(3)
    assert selected_source == "ja"


def test_popup_window_internal_keyboard_shortcuts() -> None:
    retry_called = False
    copied_text = ""

    def on_retry() -> None:
        nonlocal retry_called
        retry_called = True

    def on_copy(t: str) -> None:
        nonlocal copied_text
        copied_text = t

    popup = PopupWindow(
        on_retry=on_retry,
        on_copy_result=on_copy,
        pin_default=False,
    )
    popup.show_result(TranslationResult("Teks hasil", "en", "openai"))

    # Test Ctrl+P (toggle pin)
    assert popup.pinned is False
    popup._on_key_pressed(None, Gdk.KEY_p, 0, Gdk.ModifierType.CONTROL_MASK)
    assert popup.pinned is True
    popup._on_key_pressed(None, Gdk.KEY_p, 0, Gdk.ModifierType.CONTROL_MASK)
    assert popup.pinned is False

    # Test Ctrl+R (retry)
    popup._on_key_pressed(None, Gdk.KEY_r, 0, Gdk.ModifierType.CONTROL_MASK)
    assert retry_called is True

    # Test Ctrl+Shift+C (copy result)
    popup._on_key_pressed(
        None,
        Gdk.KEY_c,
        0,
        Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK,
    )
    assert copied_text == "Teks hasil"


def test_popup_renders_compare_alternative_cards() -> None:
    """Regresi: kartu mode bandingkan memakai AlternativeResult.display_name."""
    from pinux.translate.base import AlternativeResult

    popup = PopupWindow()
    popup.show_result(
        TranslationResult(
            "halo",
            "en",
            "google-free",
            alternatives=(
                AlternativeResult("deepl", "DeepL", text="hai"),
                AlternativeResult("openai", "OpenAI", error="HTTP 429"),
            ),
        )
    )
    assert popup._alternatives_box.get_visible()

    texts: list[str] = []

    def walk(widget: Gtk.Widget) -> None:
        if isinstance(widget, Gtk.Label):
            texts.append(widget.get_text())
        child = widget.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(popup._alternatives_box)
    assert "DeepL" in texts and "hai" in texts
    assert "OpenAI" in texts and "Gagal: HTTP 429" in texts

    popup.show_loading()
    assert popup._alternatives_box.get_first_child() is None
