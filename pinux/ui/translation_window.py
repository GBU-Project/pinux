"""Jendela terjemahan penuh mandiri (Adw.Window) untuk membaca teks panjang.

Fitur P2: resizable, draggable via CSD GNOME, dan tidak tertutup saat kehilangan fokus.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gtk


class TranslationWindow(Adw.Window):
    """Jendela terjemahan terpisah (resizable, draggable) untuk teks panjang."""

    def __init__(self, source_text: str = "", result_text: str = "") -> None:
        super().__init__()
        self.set_title("Pinux — Terjemahan")
        self.set_default_size(600, 600)
        self.set_resizable(True)

        toolbar_view = Adw.ToolbarView()

        # 1. Header Bar dengan Tombol Salin
        header = Adw.HeaderBar()
        self._copy_btn = Gtk.Button(icon_name="edit-copy-symbolic")
        self._copy_btn.set_tooltip_text("Salin hasil terjemahan")
        self._copy_btn.connect("clicked", self._on_copy_clicked, result_text)
        header.pack_end(self._copy_btn)
        toolbar_view.add_top_bar(header)

        # 2. Konten Utama
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main_box.set_margin_top(14)
        main_box.set_margin_bottom(14)
        main_box.set_margin_start(16)
        main_box.set_margin_end(16)

        # 3. Area Sumber (Jelas terbaca dan scrollable)
        src_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        src_title = Gtk.Label(label="Teks Sumber")
        src_title.add_css_class("caption")
        src_title.add_css_class("dim-label")
        src_title.set_xalign(0.0)
        src_header.append(src_title)
        main_box.append(src_header)

        src_scroll = Gtk.ScrolledWindow()
        src_scroll.set_min_content_height(70)
        src_scroll.set_max_content_height(180)
        src_scroll.set_propagate_natural_height(True)
        src_scroll.add_css_class("card")

        # Teks sumber tanpa class dim-label agar kontras terang dan mudah dibaca
        self._src_label = Gtk.Label(label=source_text, wrap=True, selectable=True)
        self._src_label.set_xalign(0.0)
        self._src_label.set_margin_top(10)
        self._src_label.set_margin_bottom(10)
        self._src_label.set_margin_start(12)
        self._src_label.set_margin_end(12)
        src_scroll.set_child(self._src_label)
        main_box.append(src_scroll)

        main_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # 4. Area Hasil Terjemahan (Hero Element - Luas & Kontras)
        res_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        res_title = Gtk.Label(label="Hasil Terjemahan")
        res_title.add_css_class("caption")
        res_title.add_css_class("dim-label")
        res_title.set_xalign(0.0)
        res_header.append(res_title)
        main_box.append(res_header)

        res_scroll = Gtk.ScrolledWindow()
        res_scroll.set_vexpand(True)
        res_scroll.add_css_class("card")

        self._res_label = Gtk.Label(label=result_text, wrap=True, selectable=True)
        self._res_label.set_xalign(0.0)
        self._res_label.set_yalign(0.0)
        self._res_label.set_margin_top(12)
        self._res_label.set_margin_bottom(12)
        self._res_label.set_margin_start(14)
        self._res_label.set_margin_end(14)
        res_scroll.set_child(self._res_label)
        main_box.append(res_scroll)

        toolbar_view.set_content(main_box)
        self.set_content(toolbar_view)

    def _on_copy_clicked(self, btn: Gtk.Button, text: str) -> None:
        """Salin teks hasil ke clipboard sistem."""
        if not text:
            return
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(text)
        btn.set_icon_name("object-select-symbolic")
        # Kembalikan ikon setelah 1.5 detik
        from gi.repository import GLib

        GLib.timeout_add(1500, lambda: btn.set_icon_name("edit-copy-symbolic") and False)
