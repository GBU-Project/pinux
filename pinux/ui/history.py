"""Jendela Riwayat & Favorit terjemahan."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

if TYPE_CHECKING:
    from pinux.history import HistoryEntry, HistoryStore

__all__ = ["HistoryWindow"]


def _format_time(ts: float) -> str:
    return time.strftime("%d %b %Y %H:%M", time.localtime(ts))


class HistoryWindow(Adw.Window):
    """Daftar terjemahan terdahulu dengan pencarian, filter favorit, dan hapus."""

    def __init__(
        self,
        *,
        store: "HistoryStore",
        on_select: Callable[["HistoryEntry"], None] | None = None,
        on_favorite_changed: Callable[[int, bool], None] | None = None,
    ) -> None:
        super().__init__()
        self._store = store
        self._on_select = on_select
        self._on_favorite_changed = on_favorite_changed
        self._search_id: int | None = None

        self.set_title("Riwayat Terjemahan")
        self.set_default_size(520, 560)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Adw.HeaderBar()
        self._fav_toggle = Gtk.ToggleButton(icon_name="starred-symbolic")
        self._fav_toggle.set_tooltip_text("Hanya favorit")
        self._fav_toggle.connect("toggled", lambda *_: self.refresh())
        header.pack_start(self._fav_toggle)
        clear_btn = Gtk.Button(icon_name="edit-clear-all-symbolic")
        clear_btn.set_tooltip_text("Hapus riwayat (favorit dipertahankan)")
        clear_btn.connect("clicked", self._on_clear_clicked)
        header.pack_end(clear_btn)
        box.append(header)

        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text("Cari di teks sumber atau hasil")
        self._search.set_margin_start(12)
        self._search.set_margin_end(12)
        self._search.set_margin_top(8)
        self._search.connect("search-changed", self._on_search_changed)
        box.append(self._search)

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.add_css_class("boxed-list")
        self._list.set_margin_start(12)
        self._list.set_margin_end(12)
        self._list.set_margin_top(8)
        self._list.set_margin_bottom(12)
        self._list.connect("row-activated", self._on_row_activated)

        self._empty = Adw.StatusPage()
        self._empty.set_title("Belum ada riwayat")
        self._empty.set_icon_name("document-open-recent-symbolic")

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(self._list)
        self._stack = Gtk.Stack()
        self._stack.add_named(scroller, "list")
        self._stack.add_named(self._empty, "empty")
        box.append(self._stack)
        self.set_content(box)

        self._entries: dict[int, "HistoryEntry"] = {}
        self.refresh()

    # -- Data ---------------------------------------------------------------

    def refresh(self) -> None:
        child = self._list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._list.remove(child)
            child = nxt
        entries = self._store.list(
            query=self._search.get_text(),
            favorites_only=self._fav_toggle.get_active(),
            limit=200,
        )
        self._entries = {e.id: e for e in entries}
        for entry in entries:
            self._list.append(self._build_row(entry))
        self._stack.set_visible_child_name("list" if entries else "empty")

    def _build_row(self, entry: "HistoryEntry") -> Adw.ActionRow:
        row = Adw.ActionRow()
        row.set_activatable(True)
        row.set_title(GLib.markup_escape_text(entry.source_text.replace("\n", " ")))
        row.set_subtitle(GLib.markup_escape_text(entry.result_text.replace("\n", " ")))
        row.set_title_lines(1)
        row.set_subtitle_lines(2)
        row.add_prefix(
            Gtk.Label(label=f"{entry.source_lang}→{entry.target_lang}\n{_format_time(entry.ts)}")
        )
        row._entry_id = entry.id  # type: ignore[attr-defined]

        star = Gtk.ToggleButton(icon_name="starred-symbolic")
        star.set_valign(Gtk.Align.CENTER)
        star.add_css_class("flat")
        star.set_active(entry.favorite)
        star.set_tooltip_text("Favorit")
        star.connect("toggled", self._on_star_toggled, entry.id)
        row.add_suffix(star)

        delete = Gtk.Button(icon_name="user-trash-symbolic")
        delete.set_valign(Gtk.Align.CENTER)
        delete.add_css_class("flat")
        delete.set_tooltip_text("Hapus")
        delete.connect("clicked", self._on_delete_clicked, entry.id)
        row.add_suffix(delete)
        return row

    # -- Event --------------------------------------------------------------

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        # Tunda sebentar agar tidak mengquery setiap ketukan tombol.
        if self._search_id is not None:
            GLib.source_remove(self._search_id)
        self._search_id = GLib.timeout_add(200, self._do_search)

    def _do_search(self) -> bool:
        self._search_id = None
        self.refresh()
        return False

    def _on_row_activated(self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        entry = self._entries.get(getattr(row, "_entry_id", -1))
        if entry is not None and self._on_select is not None:
            self._on_select(entry)
            self.close()

    def _on_star_toggled(self, btn: Gtk.ToggleButton, entry_id: int) -> None:
        self._store.set_favorite(entry_id, btn.get_active())
        if self._on_favorite_changed is not None:
            self._on_favorite_changed(entry_id, btn.get_active())
        if self._fav_toggle.get_active() and not btn.get_active():
            GLib.idle_add(self._refresh_once)

    def _refresh_once(self) -> bool:
        self.refresh()
        return False

    def _on_delete_clicked(self, btn: Gtk.Button, entry_id: int) -> None:
        self._store.delete(entry_id)
        self.refresh()

    def _on_clear_clicked(self, btn: Gtk.Button) -> None:
        self._store.clear(keep_favorites=True)
        self.refresh()
