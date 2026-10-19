"""Tes GUI riwayat dan favorit: tombol bintang popup, HistoryWindow, dan perekaman hasil.

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

from pinux.history import HistoryStore  # noqa: E402
from pinux.translate.base import TranslationResult  # noqa: E402
from pinux.ui.history import HistoryWindow  # noqa: E402
from pinux.ui.popup import PopupWindow  # noqa: E402


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


# --- Popup: favorit ----------------------------------------------------------------


def test_popup_favorite_button_flow() -> None:
    toggled: list[int] = []

    def on_toggle(entry_id: int) -> bool:
        toggled.append(entry_id)
        return True

    popup = PopupWindow(on_toggle_favorite=on_toggle)
    assert not popup._fav_button.get_sensitive()  # belum ada hasil

    popup.set_current_entry(7, favorite=False)
    assert popup._fav_button.get_sensitive() and not popup._fav_button.get_active()
    popup._fav_button.set_active(True)  # klik pengguna
    assert toggled == [7]

    popup.set_current_entry(8, favorite=True)  # setel dari kode tidak memicu callback
    assert toggled == [7] and popup._fav_button.get_active()

    popup.show_loading()
    assert not popup._fav_button.get_sensitive()


# --- Jendela riwayat -------------------------------------------------------------


def test_history_window_lists_filters_and_reuses() -> None:
    store = HistoryStore(":memory:")
    a = store.add("hello", "halo", "en", "id", "p")
    store.add("goodbye", "selamat tinggal", "en", "id", "p")
    store.set_favorite(a, True)
    picked = []
    win = HistoryWindow(store=store, on_select=picked.append)

    rows = _children(win._list)
    assert len(rows) == 2 and win._stack.get_visible_child_name() == "list"
    assert rows[0].get_title() == "goodbye"  # terbaru dulu

    win._fav_toggle.set_active(True)
    assert [r.get_title() for r in _children(win._list)] == ["hello"]

    win._fav_toggle.set_active(False)
    win._search.set_text("selamat")
    win._do_search()
    assert [r.get_title() for r in _children(win._list)] == ["goodbye"]

    win._search.set_text("")
    win._do_search()
    win._on_row_activated(win._list, _children(win._list)[1])
    assert picked and picked[0].source_text == "hello"


def test_history_window_delete_clear_and_empty_state() -> None:
    store = HistoryStore(":memory:")
    keep = store.add("keep", "tetap", "en", "id", "p")
    store.add("drop", "buang", "en", "id", "p")
    store.set_favorite(keep, True)
    win = HistoryWindow(store=store)

    win._on_clear_clicked(None)  # favorit dipertahankan
    assert [e.source_text for e in store.list()] == ["keep"]
    assert len(_children(win._list)) == 1

    win._on_delete_clicked(None, keep)
    assert win._stack.get_visible_child_name() == "empty"


def test_history_window_escapes_markup_in_titles() -> None:
    store = HistoryStore(":memory:")
    store.add("<b>&x</b>", "<i>y</i>", "en", "id", "p")
    row = _children(HistoryWindow(store=store)._list)[0]
    # Adw.ActionRow menafsirkan markup, jadi judul harus di-escape agar tampil apa adanya.
    assert row.get_title() == "&lt;b&gt;&amp;x&lt;/b&gt;"


def test_app_record_history_links_popup_favorite_button() -> None:
    from types import SimpleNamespace

    from pinux.app import PinuxApp

    popup = MagicMock()
    fake = SimpleNamespace(history=HistoryStore(":memory:"), _popup_window=popup)
    res = TranslationResult("halo", "en", "google-free")
    PinuxApp.record_history(fake, "hello", res, "id")

    saved = fake.history.list()
    assert len(saved) == 1 and saved[0].result_text == "halo" and saved[0].target_lang == "id"
    popup.set_current_entry.assert_called_once_with(saved[0].id, False)

    PinuxApp.record_history(SimpleNamespace(history=None, _popup_window=popup), "x", res, "id")
    assert popup.set_current_entry.call_count == 1  # riwayat nonaktif: tidak ada yang terjadi
