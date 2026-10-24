"""Uji tata letak kotak teks sumber pada PopupWindow.

Regresi: bila teks sumber lebih tinggi dari batas atas kotak (140 px), kotak
terpotong di tengah baris karena batas itu bukan kelipatan tinggi baris. Kini
kotak berhenti tepat di batas baris penuh. Teks yang muat tidak boleh digulir.

Tes hanya memeriksa geometri widget yang sebenarnya (bukan konstanta kelas),
sehingga gagal secara perilaku pada kode lama. Memerlukan display (nyata atau
Xvfb), seperti ``test_popup.py``.
"""

from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

import pytest

from pinux.ui.popup import PopupWindow

# Batas tinggi kotak sumber yang dirancang (px).
MIN_H, MAX_H = 70, 140

SENTENCE = (
    "For power and utility planners modeling feedback, delay, and accumulation rather "
    "than a single forecast, three classes of system dynamics software serve distinct needs. "
)


@pytest.fixture(scope="module", autouse=True)
def init_gtk() -> None:
    Gtk.init()


def _pump(ms: int = 500) -> None:
    """Jalankan main loop sebentar agar alokasi dan callback idle selesai."""
    ctx = GLib.MainContext.default()
    end = GLib.get_monotonic_time() + ms * 1000
    while GLib.get_monotonic_time() < end:
        while ctx.pending():
            ctx.iteration(False)
        GLib.usleep(5000)


@pytest.fixture
def popup():
    win = PopupWindow()
    win.present()
    _pump()
    yield win
    win.destroy()


def _line_height(win: PopupWindow) -> int:
    view = win._entry
    return view.get_iter_location(view.get_buffer().get_start_iter()).height


def _box_height(win: PopupWindow) -> int:
    return win._entry_scroller.get_height()


def _fill(win: PopupWindow, text: str) -> None:
    win.set_source_text(text)
    _pump()


def test_short_text_uses_minimum_height(popup: PopupWindow) -> None:
    _fill(popup, "Hello world")
    assert _box_height(popup) == MIN_H


def test_text_that_fits_is_not_scrolled(popup: PopupWindow) -> None:
    _fill(popup, SENTENCE)
    adj = popup._entry_scroller.get_vadjustment()
    assert MIN_H <= _box_height(popup) <= MAX_H
    assert adj.get_upper() <= adj.get_page_size(), "teks yang muat tidak boleh perlu digulir"


def test_long_text_stops_on_a_whole_line(popup: PopupWindow) -> None:
    _fill(popup, SENTENCE * 6)
    height, top, line = _box_height(popup), popup._entry.get_top_margin(), _line_height(popup)

    assert height <= MAX_H
    assert (height - top) % line == 0, (
        f"tinggi {height}px memotong baris (margin atas {top}px, tinggi baris {line}px)"
    )
    adj = popup._entry_scroller.get_vadjustment()
    assert adj.get_upper() > adj.get_page_size(), "teks panjang harus bisa digulir"


def test_box_follows_text_growth_and_shrink(popup: PopupWindow) -> None:
    _fill(popup, "Hello")
    small = _box_height(popup)

    _fill(popup, SENTENCE * 6)
    big = _box_height(popup)
    assert big > small

    _fill(popup, "Hello")
    assert _box_height(popup) == small


def test_text_set_before_present_is_also_fitted() -> None:
    win = PopupWindow()
    win.set_source_text(SENTENCE * 6)
    win.present()
    _pump()
    try:
        height, top, line = _box_height(win), win._entry.get_top_margin(), _line_height(win)
        assert (height - top) % line == 0
    finally:
        win.destroy()


def test_wider_window_needs_less_height() -> None:
    # Lebar bertambah -> baris lebih sedikit -> kotak tidak boleh tertahan tinggi lama.
    # Diukur satu per satu: popup menutup sendiri saat kehilangan fokus (close_on_blur).
    def measure(width: int) -> int:
        win = PopupWindow(width=width)
        win.present()
        _pump()
        try:
            _fill(win, SENTENCE * 2)
            return _box_height(win)
        finally:
            win.destroy()

    narrow, wide = measure(420), measure(900)
    assert narrow > 0 and wide > 0
    assert wide <= narrow
    assert wide < narrow or narrow == MIN_H, "kotak lebar semestinya lebih pendek"


# --- Kotak hasil terjemahan -----------------------------------------------------

from types import SimpleNamespace  # noqa: E402

RESULT_TEXT = (
    "Bagi perencana listrik dan utilitas yang memodelkan umpan balik, penundaan, dan "
    "akumulasi, bukan perkiraan tunggal, tiga kelas perangkat lunak dinamika sistem "
    "melayani kebutuhan yang berbeda. "
) * 4


def _show(win: PopupWindow, text: str, phonetic: str = "") -> None:
    win.show_result(
        SimpleNamespace(
            text=text,
            detected_source_lang="en",
            phonetic=phonetic,
            dictionary_entries=(),
            alternatives=(),
        )
    )
    _pump()


# Margin atas isi kartu hasil (px); mencerminkan ``result_box.set_margin_top(8)``.
RESULT_TOP = 8


def _result_geometry(win: PopupWindow) -> tuple[int, int, float, int]:
    """(tinggi kartu, tinggi area gulir, tinggi baris, offset atas isi)."""
    card = win._result_scroller
    viewport = card.get_child()
    layout = win._result_label.get_layout()
    line = layout.get_size()[1] / 1024 / layout.get_line_count()
    return card.get_height(), viewport.get_height(), line, RESULT_TOP


def test_overflowing_result_stops_on_a_whole_line(popup: PopupWindow) -> None:
    _show(popup, RESULT_TEXT)
    card, area, line, top = _result_geometry(popup)

    adj = popup._result_scroller.get_vadjustment()
    assert adj.get_upper() > card, "contoh harus meluap agar perlu digulir"
    lines = (area - top) / line
    assert abs(lines - round(lines)) < 0.05, (
        f"area gulir {area}px memotong baris ({lines:.2f} baris; offset {top}px, baris {line}px)"
    )


def test_result_card_still_fills_and_gap_is_under_one_line(popup: PopupWindow) -> None:
    _show(popup, RESULT_TEXT)
    card, area, line, _ = _result_geometry(popup)
    assert 0 <= card - area < line, "kartu tetap penuh; sisa di dalam kartu kurang dari satu baris"


def test_result_that_fits_is_not_snapped(popup: PopupWindow) -> None:
    popup.set_default_size(450, 800)
    _pump()
    _show(popup, "Halo dunia")
    card, area, _, _ = _result_geometry(popup)
    assert area == card


def test_result_with_phonetic_is_not_snapped(popup: PopupWindow) -> None:
    # Baris fonetik berukuran lain: batas baris tak bisa dihitung, jadi tidak dipotong.
    _show(popup, RESULT_TEXT, phonetic="/ˈhɛloʊ/")
    card, area, _, _ = _result_geometry(popup)
    assert area == card


def test_result_snap_follows_text_changes(popup: PopupWindow) -> None:
    _show(popup, RESULT_TEXT)
    _, snapped_area, _, _ = _result_geometry(popup)

    _show(popup, "Halo dunia")
    card, area, _, _ = _result_geometry(popup)
    assert area == card, "teks pendek tidak boleh mewarisi pemotongan sebelumnya"

    _show(popup, RESULT_TEXT)
    assert _result_geometry(popup)[1] == snapped_area
