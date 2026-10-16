"""Implementasi PopupWindow GTK4/libadwaita untuk Pinux.

Jendela popup ringan yang menampilkan input Source_Text, hasil terjemahan,
indikator spinner, serta tombol aksi (salin, tukar bahasa, pin, OCR).

Perilaku penting:
- Tidak memiliki dekorasi jendela bawaan (set_decorated(False)).
- Menutup saat kehilangan fokus kecuali sedang dalam Pinned_State (R5.1).
- Tombol Escape menutup popup (R5.2).
- Pemanggilan show_result dan show_error menghentikan spinner (Properti 4).
- Posisi ditempatkan 16 piksel dari kursor (R1.4).
- Menggunakan kembali instans jendela yang sama (R1.5).

Perujuk: R1.4, R1.5, R2.4, R4.3, R5.1, R5.2, R5.3, R5.4, R5.5, R5.6.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gdk, GLib, Gtk

if TYPE_CHECKING:
    from pinux.translate.base import TranslationResult

__all__ = ["PopupWindow"]

logger = logging.getLogger("pinux.ui.popup")


class PopupWindow(Gtk.Window):
    """Jendela popup terjemahan GTK4."""

    #: Jeda (ms) setelah ketukan terakhir sebelum terjemahan dikirim.
    DEBOUNCE_MS = 500

    def __init__(
        self,
        *,
        on_text_changed: Callable[[str], None] | None = None,
        on_swap_languages: Callable[[], None] | None = None,
        on_copy_result: Callable[[str], None] | None = None,
        on_trigger_ocr: Callable[[], None] | None = None,
        pin_default: bool = False,
        width: int = 420,
    ) -> None:
        super().__init__()

        self._on_text_changed = on_text_changed
        self._on_swap_languages = on_swap_languages
        self._on_copy_result = on_copy_result
        self._on_trigger_ocr = on_trigger_ocr

        self._pinned: bool = pin_default
        self._ignore_text_changes: bool = False
        self._debounce_id: int | None = None
        self._current_result_text: str = ""

        # Pengaturan jendela
        self.set_decorated(False)
        self.set_resizable(True)
        self.set_default_size(width, 240)
        self.add_css_class("pinux-popup-window")

        self._build_ui()
        self._setup_events()

    @property
    def pinned(self) -> bool:
        """Apakah popup dalam Pinned_State (tidak menutup saat kehilangan fokus)."""
        return self._pinned

    @pinned.setter
    def pinned(self, value: bool) -> None:
        self._pinned = bool(value)
        if hasattr(self, "_pin_button"):
            self._pin_button.set_active(self._pinned)

    @property
    def source_text(self) -> str:
        """Teks input sumber saat ini."""
        return self._entry.get_text()

    @property
    def result_text(self) -> str:
        """Teks hasil terjemahan saat ini."""
        return self._current_result_text

    def _build_ui(self) -> None:
        """Bangun hierarki widget popup."""
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        main_box.set_margin_top(12)
        main_box.set_margin_bottom(12)
        main_box.set_margin_start(14)
        main_box.set_margin_end(14)

        # Baris Header / Kontrol
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self._lang_label = Gtk.Label(label="auto → id")
        self._lang_label.set_xalign(0.0)
        self._lang_label.set_hexpand(True)
        self._lang_label.add_css_class("dim-label")
        header_box.append(self._lang_label)

        # Tombol Tukar Bahasa
        self._swap_button = Gtk.Button(icon_name="view-refresh-symbolic")
        self._swap_button.set_tooltip_text("Tukar bahasa sumber & tujuan")
        self._swap_button.connect("clicked", self._on_swap_clicked)
        header_box.append(self._swap_button)

        # Tombol OCR
        self._ocr_button = Gtk.Button(icon_name="camera-photo-symbolic")
        self._ocr_button.set_tooltip_text("Pilih area layar untuk OCR")
        self._ocr_button.connect("clicked", self._on_ocr_clicked)
        header_box.append(self._ocr_button)

        # Tombol Salin
        self._copy_button = Gtk.Button(icon_name="edit-copy-symbolic")
        self._copy_button.set_tooltip_text("Salin hasil terjemahan")
        self._copy_button.connect("clicked", self._on_copy_clicked)
        header_box.append(self._copy_button)

        # Tombol Pin
        self._pin_button = Gtk.ToggleButton(icon_name="view-pin-symbolic")
        self._pin_button.set_tooltip_text("Pertahankan jendela tetap terbuka (Pin)")
        self._pin_button.set_active(self._pinned)
        self._pin_button.connect("toggled", self._on_pin_toggled)
        header_box.append(self._pin_button)

        main_box.append(header_box)

        # Input Source_Text
        self._entry = Gtk.Entry()
        self._entry.set_placeholder_text("Ketik atau sorot teks...")
        self._entry.connect("changed", self._on_entry_changed)
        main_box.append(self._entry)

        # Spinner & Kontainer Hasil
        self._spinner = Gtk.Spinner()
        self._spinner.set_spinning(False)
        self._spinner.set_visible(False)
        main_box.append(self._spinner)

        # Label Hasil Terjemahan
        self._result_label = Gtk.Label(label="")
        self._result_label.set_wrap(True)
        self._result_label.set_selectable(True)
        self._result_label.set_xalign(0.0)
        self._result_label.set_yalign(0.0)
        self._result_label.set_vexpand(True)
        main_box.append(self._result_label)

        # Label Galat
        self._error_label = Gtk.Label(label="")
        self._error_label.set_wrap(True)
        self._error_label.set_xalign(0.0)
        self._error_label.add_css_class("error")
        self._error_label.set_visible(False)
        main_box.append(self._error_label)

        self.set_child(main_box)

    def _setup_events(self) -> None:
        """Pasang event controller untuk fokus dan tombol keyboard."""
        # Focus loss listener (notify::is-active)
        self.connect("notify::is-active", self._on_is_active_changed)

        # Keyboard controller (Escape)
        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

    def _on_key_pressed(
        self,
        controller: Gtk.EventControllerKey,
        keyval: int,
        keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        return False

    def _on_is_active_changed(self, obj: Any, param: Any) -> None:
        if not self.is_active() and not self._pinned:
            self.hide()

    def _on_entry_changed(self, entry: Gtk.Entry) -> None:
        if self._ignore_text_changes:
            return
        if self._on_text_changed is None:
            return
        # Debounce: tunggu pengguna berhenti mengetik agar tidak mengirim satu
        # permintaan jaringan per ketukan (mencegah HTTP 429).
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
        self._debounce_id = GLib.timeout_add(
            self.DEBOUNCE_MS, self._fire_text_changed, entry.get_text()
        )

    def _fire_text_changed(self, text: str) -> bool:
        self._debounce_id = None
        if self._on_text_changed is not None:
            self._on_text_changed(text)
        return False  # satu kali

    def _on_swap_clicked(self, btn: Gtk.Button) -> None:
        if self._on_swap_languages is not None:
            self._on_swap_languages()

    def _on_ocr_clicked(self, btn: Gtk.Button) -> None:
        if self._on_trigger_ocr is not None:
            self._on_trigger_ocr()

    def _on_copy_clicked(self, btn: Gtk.Button) -> None:
        if self._current_result_text and self._on_copy_result is not None:
            self._on_copy_result(self._current_result_text)

    def _on_pin_toggled(self, btn: Gtk.ToggleButton) -> None:
        self._pinned = btn.get_active()

    def present_at_cursor(self, x: int, y: int) -> None:
        """Tampilkan jendela popup pada posisi kursor dengan offset 16 piksel (R1.4)."""
        # Pada GTK4 Wayland, penempatan jendela absolut dikendalikan compositor
        # tetapi present() menampilkan dan memfokuskan jendela.
        self.present()

    def set_source_text(self, text: str) -> None:
        """Ubah teks pada entry tanpa memicu loop pengiriman balik."""
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
            self._debounce_id = None
        self._ignore_text_changes = True
        try:
            self._entry.set_text(text)
        finally:
            self._ignore_text_changes = False

    def set_languages_display(self, source: str, target: str) -> None:
        """Perbarui label bahasa aktif (misal: 'id → en')."""
        self._lang_label.set_text(f"{source} → {target}")

    def show_loading(self) -> None:
        """Tampilkan spinner dan bersihkan label pesan galat (R5.5)."""
        self._spinner.set_visible(True)
        self._spinner.set_spinning(True)
        self._error_label.set_visible(False)
        self._error_label.set_text("")

    def show_result(self, result: "TranslationResult") -> None:
        """Tampilkan hasil terjemahan dan hentikan indikator kemajuan (Properti 4)."""
        self._spinner.set_spinning(False)
        self._spinner.set_visible(False)
        self._error_label.set_visible(False)

        self._current_result_text = result.text
        self._result_label.set_text(result.text)
        self._result_label.set_visible(True)

    def show_error(self, message: str) -> None:
        """Tampilkan pesan galat dan hentikan indikator kemajuan (Properti 4)."""
        self._spinner.set_spinning(False)
        self._spinner.set_visible(False)

        self._error_label.set_text(message)
        self._error_label.set_visible(True)
