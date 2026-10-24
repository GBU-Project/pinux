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
import math
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango

if TYPE_CHECKING:
    from pinux.translate.base import TranslationResult

__all__ = ["PopupWindow"]

logger = logging.getLogger("pinux.ui.popup")


class SourceTextView(Gtk.TextView):
    """Kolom teks sumber multi-baris dengan API mirip ``Gtk.Entry``."""

    def get_text(self) -> str:
        buf = self.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def set_text(self, text: str) -> None:
        self.get_buffer().set_text(text)


class SnapScrolledWindow(Gtk.ScrolledWindow):
    """ScrolledWindow yang memotong area isi di batas baris penuh saat isi meluap.

    Kartu (latar dan bingkai) tetap mengisi seluruh alokasi, sedangkan area gulir
    di dalamnya diperpendek sehingga baris terakhir yang terlihat tidak terpotong;
    sisanya (kurang dari satu baris) menjadi ruang kosong di dalam kartu.

    ``snap_provider`` mengembalikan ``(offset_atas, tinggi_baris, tinggi_isi)`` dalam
    piksel, atau ``None`` bila pemotongan tidak berlaku (isi muat, atau isi bercampur
    baris berukuran berbeda).
    """

    def __init__(self) -> None:
        super().__init__()
        self.snap_provider: Callable[[int], tuple[int, float, int] | None] | None = None

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:
        allocated = height
        info = self.snap_provider(width) if self.snap_provider is not None else None
        if info is not None and height > 0:
            top, line_height, content_height = info
            if line_height > 0 and content_height > height:
                lines = int((height - top) // line_height)
                if lines >= 1:
                    snapped = math.ceil(top + lines * line_height)
                    minimum = self.measure(Gtk.Orientation.VERTICAL, width)[0]
                    allocated = min(height, max(snapped, minimum))
        Gtk.ScrolledWindow.do_size_allocate(self, width, allocated, baseline)


class PopupWindow(Gtk.Window):
    """Jendela popup terjemahan GTK4."""

    #: Batas tinggi (px) kotak teks sumber; di atas batas atas teks digulir.
    SOURCE_MIN_HEIGHT = 70
    SOURCE_MAX_HEIGHT = 140

    #: Jeda (ms) setelah ketukan terakhir sebelum terjemahan dikirim.
    LANGUAGES: list[tuple[str, str]] = [
        ("auto", "Otomatis"),
        ("id", "Indonesia"),
        ("en", "Inggris"),
        ("ja", "Jepang"),
        ("zh", "Mandarin"),
        ("ar", "Arab"),
        ("de", "Jerman"),
        ("es", "Spanyol"),
        ("fr", "Prancis"),
        ("ko", "Korea"),
        ("ru", "Rusia"),
        ("pt", "Portugis"),
        ("it", "Italia"),
        ("nl", "Belanda"),
        ("vi", "Vietnam"),
        ("th", "Thailand"),
    ]

    def __init__(
        self,
        *,
        on_text_changed: Callable[[str], None] | None = None,
        on_swap_languages: Callable[[], None] | None = None,
        on_language_selected: Callable[[str | None, str], None] | None = None,
        on_retry: Callable[[], None] | None = None,
        on_copy_result: Callable[[str], None] | None = None,
        on_trigger_ocr: Callable[[], None] | None = None,
        on_ocr_file: Callable[[], None] | None = None,
        on_speak: Callable[[str, str | None], None] | None = None,
        on_stop_speak: Callable[[], None] | None = None,
        on_toggle_favorite: Callable[[int], bool | None] | None = None,
        on_show_history: Callable[[], None] | None = None,
        tts_available: bool = False,
        pin_default: bool = False,
        close_on_blur: bool = True,
        continuous_ocr_default: bool = False,
        on_continuous_ocr_toggled: Callable[[bool], None] | None = None,
        on_expand: Callable[[str, str], None] | None = None,
        width: int = 420,
    ) -> None:
        super().__init__()

        self._on_text_changed = on_text_changed
        self._on_swap_languages = on_swap_languages
        self._on_language_selected = on_language_selected
        self._on_retry = on_retry
        self._on_copy_result = on_copy_result
        self._on_trigger_ocr = on_trigger_ocr
        self._on_ocr_file = on_ocr_file
        self._on_continuous_ocr_toggled = on_continuous_ocr_toggled
        self._on_expand = on_expand
        self._on_speak = on_speak
        self._on_stop_speak = on_stop_speak
        self._is_speaking_source: bool = False
        self._is_speaking_result: bool = False
        self._on_toggle_favorite = on_toggle_favorite
        self._on_show_history = on_show_history
        self._current_entry_id: int | None = None
        self._tts_available = tts_available
        self._detected_lang: str | None = None

        self._pinned: bool = pin_default
        self._close_on_blur: bool = close_on_blur
        self._continuous_ocr: bool = continuous_ocr_default

        self._ignore_text_changes: bool = False
        self._ignore_lang_changes: bool = False
        self._debounce_id: int | None = None
        self._current_result_text: str = ""
        self._current_source_lang: str | None = None
        self._current_target_lang: str = "id"

        # Pengaturan jendela
        self._default_width: int = width
        self.set_decorated(False)
        self.set_resizable(True)
        self.set_default_size(self._default_width, 420)
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
        self._update_pin_button_style()

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
        main_box.set_size_request(self._default_width, -1)
        main_box.set_hexpand(False)
        main_box.set_margin_top(12)
        main_box.set_margin_bottom(12)
        main_box.set_margin_start(14)
        main_box.set_margin_end(14)

        # 1. Baris Header / Kontrol (Bahasa, Tukar, Deteksi, Refresh, Pengaturan/Info, Jendela Penuh, Pin)
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        # Dropdown Bahasa Sumber
        src_labels = [name for _, name in self.LANGUAGES]
        self._src_dropdown = Gtk.DropDown.new_from_strings(src_labels)
        self._src_dropdown.set_selected(0)  # auto
        self._src_dropdown.set_tooltip_text("Bahasa Sumber")
        self._src_dropdown.connect("notify::selected", self._on_src_lang_changed)
        header_box.append(self._src_dropdown)

        # Tombol Tukar Bahasa
        self._swap_button = Gtk.Button(icon_name="view-refresh-symbolic")
        self._swap_button.set_tooltip_text("Tukar bahasa sumber & tujuan")
        self._swap_button.connect("clicked", self._on_swap_clicked)
        header_box.append(self._swap_button)

        # Dropdown Bahasa Tujuan
        self._target_languages = [lang for lang in self.LANGUAGES if lang[0] != "auto"]
        tgt_labels = [name for _, name in self._target_languages]
        self._tgt_dropdown = Gtk.DropDown.new_from_strings(tgt_labels)
        self._tgt_dropdown.set_selected(0)  # id
        self._tgt_dropdown.set_tooltip_text("Bahasa Tujuan")
        self._tgt_dropdown.connect("notify::selected", self._on_tgt_lang_changed)
        header_box.append(self._tgt_dropdown)

        # Label status / deteksi otomatis / spacer expander
        self._lang_label = Gtk.Label(label="")
        self._lang_label.set_xalign(0.0)
        self._lang_label.set_hexpand(True)
        self._lang_label.add_css_class("caption")
        self._lang_label.add_css_class("dim-label")
        header_box.append(self._lang_label)

        # Tombol Buka sebagai Jendela Penuh (P2)
        self._expand_button = Gtk.Button(icon_name="view-fullscreen-symbolic")
        self._expand_button.set_tooltip_text("Buka sebagai jendela terpisah (untuk teks panjang)")
        self._expand_button.connect("clicked", self._on_expand_clicked)
        header_box.append(self._expand_button)

        # Tombol Pin (kanan atas)
        self._pin_button = Gtk.ToggleButton(icon_name="view-pin-symbolic")
        self._pin_button.set_tooltip_text("Pertahankan jendela tetap terbuka (Ctrl+P)")
        self._pin_button.set_active(self._pinned)
        self._pin_button.connect("toggled", self._on_pin_toggled)
        self._update_pin_button_style()
        header_box.append(self._pin_button)

        main_box.append(header_box)

        # 2. Kotak Teks Sumber (Source) dengan header kecil
        source_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        
        source_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._source_title_label = Gtk.Label(label="Sumber")
        self._source_title_label.add_css_class("caption")
        self._source_title_label.add_css_class("dim-label")
        self._source_title_label.set_xalign(0.0)
        self._source_title_label.set_hexpand(True)
        source_header.append(self._source_title_label)

        # Tombol TTS teks sumber (kontekstual di area sumber)
        self._speak_source_button = Gtk.Button(icon_name="audio-speakers-symbolic")
        self._speak_source_button.set_tooltip_text("Bacakan teks sumber (TTS)")
        self._speak_source_button.connect("clicked", self._on_speak_source_clicked)
        self._speak_source_button.set_visible(self._tts_available)
        self._speak_source_button.add_css_class("flat")
        source_header.append(self._speak_source_button)
        source_container.append(source_header)

        # Input Source_Text (multi-baris)
        self._entry = SourceTextView()
        self._entry.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        # Padding atas/bawah agar baris pertama dan terakhir tidak menempel ke tepi kartu
        self._entry.set_top_margin(6)
        self._entry.set_bottom_margin(6)
        self._entry.set_accepts_tab(False)
        self._entry.set_tooltip_text("Ketik atau sorot teks. Enter: terjemahkan, Shift+Enter: baris baru")
        self._entry.get_buffer().connect("changed", self._on_entry_changed)
        entry_keys = Gtk.EventControllerKey.new()
        entry_keys.connect("key-pressed", self._on_entry_key_pressed)
        self._entry.add_controller(entry_keys)

        self._entry_scroller = Gtk.ScrolledWindow()
        self._entry_scroller.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC,
        )
        self._entry_scroller.set_child(self._entry)
        self._entry_scroller.set_min_content_height(self.SOURCE_MIN_HEIGHT)
        self._entry_scroller.set_max_content_height(self.SOURCE_MAX_HEIGHT)
        self._entry_scroller.set_propagate_natural_height(True)
        self._entry_scroller.add_css_class("card")
        source_container.append(self._entry_scroller)

        # Tinggi kotak sumber tidak mengikuti isi (teks terpotong di tengah baris),
        # sehingga disesuaikan sendiri saat teks atau lebar berubah.
        self._fit_source_id: int | None = None
        self._entry.get_buffer().connect("changed", lambda *_: self._queue_fit_source_height())
        self._entry_scroller.get_hadjustment().connect(
            "notify::page-size", lambda *_: self._queue_fit_source_height()
        )

        main_box.append(source_container)

        # Pemisah visual jelas antara panel Teks Sumber & Hasil Terjemahan
        self._separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        main_box.append(self._separator)

        # Spinner status
        self._spinner = Gtk.Spinner()
        self._spinner.set_spinning(False)
        self._spinner.set_visible(False)
        main_box.append(self._spinner)

        # 3. Kotak Hasil Terjemahan dengan header kontekstual (TTS Hasil & Salin)
        result_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        result_container.set_vexpand(True)

        result_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._result_title_label = Gtk.Label(label="Terjemahan")
        self._result_title_label.add_css_class("caption")
        self._result_title_label.add_css_class("dim-label")
        self._result_title_label.set_xalign(0.0)
        self._result_title_label.set_hexpand(True)
        result_header.append(self._result_title_label)

        # Aksi kontekstual hasil: TTS Hasil
        self._speak_result_button = Gtk.Button(icon_name="audio-volume-high-symbolic")
        self._speak_result_button.set_tooltip_text("Bacakan hasil terjemahan (TTS)")
        self._speak_result_button.connect("clicked", self._on_speak_result_clicked)
        self._speak_result_button.set_visible(self._tts_available)
        self._speak_result_button.add_css_class("flat")
        result_header.append(self._speak_result_button)

        # Aksi kontekstual hasil: Salin
        self._copy_button = Gtk.Button(icon_name="edit-copy-symbolic")
        self._copy_button.set_tooltip_text("Salin hasil terjemahan (Ctrl+Shift+C)")
        self._copy_button.connect("clicked", self._on_copy_clicked)
        self._copy_button.add_css_class("flat")
        result_header.append(self._copy_button)

        result_container.append(result_header)

        # Isi kartu hasil yang dapat discroll
        result_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._result_box = result_box
        result_box.set_margin_top(8)
        result_box.set_margin_bottom(8)
        result_box.set_margin_start(10)
        result_box.set_margin_end(10)

        # Label Fonetik / Simbol Lafal (Kamus ala Bob)
        self._phonetic_label = Gtk.Label(label="")
        self._phonetic_label.set_wrap(True)
        self._phonetic_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self._phonetic_label.set_max_width_chars(45)
        self._phonetic_label.set_xalign(0.0)
        self._phonetic_label.add_css_class("caption")
        self._phonetic_label.add_css_class("dim-label")
        self._phonetic_label.set_visible(False)
        result_box.append(self._phonetic_label)

        # Label Hasil Terjemahan
        self._result_label = Gtk.Label(label="")
        self._result_label.set_wrap(True)
        self._result_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self._result_label.set_max_width_chars(45)
        self._result_label.set_selectable(True)
        self._result_label.set_xalign(0.0)
        self._result_label.set_yalign(0.0)
        self._result_label.set_vexpand(True)
        result_box.append(self._result_label)

        # Kontainer Kamus Kata Tunggal (Part of speech & sinonim)
        self._dict_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._dict_box.set_visible(False)
        result_box.append(self._dict_box)

        # Label Galat
        self._error_label = Gtk.Label(label="")
        self._error_label.set_wrap(True)
        self._error_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self._error_label.set_max_width_chars(45)
        self._error_label.set_xalign(0.0)
        self._error_label.add_css_class("error")
        self._error_label.set_visible(False)
        result_box.append(self._error_label)

        self._result_scroller = SnapScrolledWindow()
        self._result_scroller.snap_provider = self._result_snap_info
        self._result_scroller.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC,
        )
        self._result_scroller.set_child(result_box)
        self._result_scroller.set_min_content_height(80)
        self._result_scroller.set_max_content_height(320)
        self._result_scroller.set_propagate_natural_height(False)
        self._result_scroller.set_vexpand(True)
        self._result_scroller.add_css_class("card")
        result_container.append(self._result_scroller)

        # Kontainer Layanan Tambahan (Mode Bandingkan)
        self._alternatives_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._alternatives_box.set_visible(False)
        result_container.append(self._alternatives_box)

        main_box.append(result_container)

        # 4. Toolbar Bawah untuk OCR & Utilitas (Riwayat, Favorit)
        bottom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        # Tombol OCR Layar
        self._ocr_button = Gtk.Button(icon_name="camera-photo-symbolic")
        self._ocr_button.set_tooltip_text("Pilih area layar untuk OCR")
        self._ocr_button.connect("clicked", self._on_ocr_clicked)
        bottom_box.append(self._ocr_button)

        # Tombol OCR dari berkas gambar
        self._ocr_file_button = Gtk.Button(icon_name="insert-image-symbolic")
        self._ocr_file_button.set_tooltip_text("OCR dari berkas gambar")
        self._ocr_file_button.connect("clicked", self._on_ocr_file_clicked)
        self._ocr_file_button.set_visible(self._on_ocr_file is not None)
        bottom_box.append(self._ocr_file_button)

        # Tombol OCR kontinu (append)
        self._continuous_ocr_button = Gtk.ToggleButton(icon_name="list-add-symbolic")
        self._continuous_ocr_button.set_tooltip_text("Mode OCR kontinu: tambahkan hasil baru ke teks sumber")
        self._continuous_ocr_button.set_active(self._continuous_ocr)
        self._continuous_ocr_button.connect("toggled", self._on_continuous_ocr_toggled_internal)
        bottom_box.append(self._continuous_ocr_button)

        # Spacer expander
        bottom_spacer = Gtk.Box()
        bottom_spacer.set_hexpand(True)
        bottom_box.append(bottom_spacer)

        # Tombol Favorit
        self._fav_button = Gtk.ToggleButton(icon_name="starred-symbolic")
        self._fav_button.set_tooltip_text("Tandai terjemahan ini sebagai favorit")
        self._fav_button.set_sensitive(False)
        self._fav_button.connect("toggled", self._on_fav_toggled)
        bottom_box.append(self._fav_button)

        # Tombol Riwayat
        self._history_button = Gtk.Button(icon_name="document-open-recent-symbolic")
        self._history_button.set_tooltip_text("Riwayat terjemahan")
        self._history_button.connect("clicked", self._on_history_clicked)
        self._history_button.set_visible(self._on_show_history is not None)
        bottom_box.append(self._history_button)

        main_box.append(bottom_box)

        self.set_child(main_box)

    def _update_pin_button_style(self) -> None:
        """Perbarui status visual tombol pin (suggested-action saat aktif)."""
        if not hasattr(self, "_pin_button"):
            return
        if self._pinned:
            self._pin_button.add_css_class("suggested-action")
            self._pin_button.set_tooltip_text("Jendela disematkan (tidak menutup otomatis). Klik untuk melepas (Ctrl+P)")
        else:
            self._pin_button.remove_css_class("suggested-action")
            self._pin_button.set_tooltip_text("Pertahankan jendela tetap terbuka (Ctrl+P)")

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
        # Escape: Tutup popup
        if keyval == Gdk.KEY_Escape:
            self.hide()
            return True

        is_ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        is_shift = bool(state & Gdk.ModifierType.SHIFT_MASK)

        # Ctrl+R: Retry / terjemahkan ulang
        if is_ctrl and keyval in (Gdk.KEY_r, Gdk.KEY_R):
            if self._on_retry is not None:
                self._on_retry()
            elif self._on_text_changed is not None and self.source_text.strip():
                self._on_text_changed(self.source_text.strip())
            return True

        # Ctrl+P: Toggle Pin/Unpin
        if is_ctrl and keyval in (Gdk.KEY_p, Gdk.KEY_P):
            self.pinned = not self.pinned
            return True

        # Ctrl+Shift+C: Salin hasil terjemahan
        if is_ctrl and is_shift and keyval in (Gdk.KEY_c, Gdk.KEY_C):
            if self._current_result_text and self._on_copy_result is not None:
                self._on_copy_result(self._current_result_text)
            return True

        return False

    def _has_open_popover(self, widget: Gtk.Widget | None = None) -> bool:
        """Periksa apakah ada popover turunan (mis. dropdown menu) yang sedang terbuka."""
        target = self if widget is None else widget
        if isinstance(target, Gtk.Popover) and target.get_visible():
            return True
        child = target.get_first_child()
        while child:
            if self._has_open_popover(child):
                return True
            child = child.get_next_sibling()
        return False

    def _on_is_active_changed(self, obj: Any, param: Any) -> None:
        if self._pinned or not self._close_on_blur:
            return
        if not self.is_active():
            # Bila popover dropdown sedang terbuka, GTK memindahkan fokus ke popover.
            # Jangan sembunyikan popup jika popover dropdown aktif.
            if self._has_open_popover():
                return
            self.hide()

    def _on_entry_key_pressed(
        self,
        controller: Gtk.EventControllerKey,
        keyval: int,
        keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        """Enter menerjemahkan segera; Shift+Enter dibiarkan menjadi baris baru."""
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not (
            state & Gdk.ModifierType.SHIFT_MASK
        ):
            if self._debounce_id is not None:
                GLib.source_remove(self._debounce_id)
                self._debounce_id = None
            if self._entry.get_text().strip():
                self._fire_text_changed(self._entry.get_text())
            return True
        return False

    def _result_snap_info(self, width: int) -> tuple[int, float, int] | None:
        """Data pemotongan baris untuk kotak hasil, atau ``None`` bila tidak berlaku.

        Hanya untuk hasil biasa: fonetik, kamus, dan galat memiliki baris dengan
        tinggi berbeda sehingga batas barisnya tidak bisa dihitung dari satu label.
        """
        if (
            self._phonetic_label.get_visible()
            or self._dict_box.get_visible()
            or self._error_label.get_visible()
        ):
            return None
        label = self._result_label
        layout = label.get_layout()
        lines = layout.get_line_count()
        if lines < 1 or not label.get_visible():
            return None
        # Pango menyimpan ukuran dalam satuan Pango.SCALE (1024 unit per piksel)
        pango_h = layout.get_size()[1]
        line_height = max(12.0, (pango_h / Pango.SCALE) / float(lines))
        box = self._result_box
        _, content_height, _, _ = box.measure(Gtk.Orientation.VERTICAL, width)
        return box.get_margin_top(), line_height, content_height

    def _queue_fit_source_height(self) -> None:
        """Jadwalkan penyesuaian batas tinggi kotak sumber setelah tata letak teks selesai."""
        if self._fit_source_id is None:
            self._fit_source_id = GLib.idle_add(self._fit_source_height)

    def _source_max_height(self) -> int:
        """Batas tinggi atas (px) kotak sumber untuk teks saat ini.

        Selama teks muat dalam ``SOURCE_MAX_HEIGHT``, kotak mengikuti tinggi natural
        teks. Bila harus digulir, batasnya diturunkan ke kelipatan baris penuh agar
        baris terakhir tidak terpotong; margin bawah tidak disertakan karena akan
        memperlihatkan sepotong baris berikutnya.

        CATATAN: Kalkulasi ini mengandalkan margin bawaan Gtk.TextView (top_margin &
        bottom_margin), bukan padding CSS luar.
        """
        view = self._entry
        end = view.get_iter_location(view.get_buffer().get_end_iter())
        top = view.get_top_margin()
        bottom = view.get_bottom_margin()
        line_h = max(end.height, 14)  # fallback ke tinggi baris minimum bila teks/emoji bervariasi
        needed = end.y + line_h + top + bottom
        if needed <= self.SOURCE_MAX_HEIGHT or line_h <= 0:
            return self.SOURCE_MAX_HEIGHT
        visible_lines = max(1, (self.SOURCE_MAX_HEIGHT - top) // line_h)
        return max(self.SOURCE_MIN_HEIGHT, top + visible_lines * line_h)

    def _fit_source_height(self) -> bool:
        """Terapkan ``_source_max_height`` pada kotak sumber."""
        self._fit_source_id = None
        if self._entry.get_width() <= 0:
            return GLib.SOURCE_REMOVE  # belum dialokasikan; perubahan lebar memicu ulang
        cap = self._source_max_height()
        if cap != self._entry_scroller.get_max_content_height():
            self._entry_scroller.set_max_content_height(cap)
        return GLib.SOURCE_REMOVE

    def _on_entry_changed(self, buffer: Any) -> None:
        if self._ignore_text_changes:
            return
        if self._on_text_changed is None:
            return
        # Debounce: tunggu pengguna berhenti mengetik agar tidak mengirim satu
        # permintaan jaringan per ketukan (mencegah HTTP 429).
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
        self._debounce_id = GLib.timeout_add(
            self.DEBOUNCE_MS, self._fire_text_changed, self._entry.get_text()
        )

    def _fire_text_changed(self, text: str) -> bool:
        self._debounce_id = None
        if self._on_text_changed is not None:
            self._on_text_changed(text)
        return False  # satu kali

    def _on_swap_clicked(self, btn: Gtk.Button) -> None:
        if self._on_swap_languages is not None:
            self._on_swap_languages()

    def _on_ocr_file_clicked(self, btn: Gtk.Button) -> None:
        if self._on_ocr_file is not None:
            self._on_ocr_file()

    def _on_ocr_clicked(self, btn: Gtk.Button) -> None:
        if self._on_trigger_ocr is not None:
            self._on_trigger_ocr()

    def stop_speaking(self) -> None:
        """Hentikan ucapan yang sedang berjalan dan reset ikon tombol."""
        if self._on_stop_speak is not None:
            self._on_stop_speak()
        self._is_speaking_source = False
        self._is_speaking_result = False
        if hasattr(self, "_speak_source_button"):
            self._speak_source_button.set_icon_name("audio-speakers-symbolic")
            self._speak_source_button.set_tooltip_text("Bacakan teks sumber (TTS)")
        if hasattr(self, "_speak_result_button"):
            self._speak_result_button.set_icon_name("audio-volume-high-symbolic")
            self._speak_result_button.set_tooltip_text("Bacakan hasil terjemahan (TTS)")

    def _on_speak_source_clicked(self, btn: Gtk.Button) -> None:
        if self._is_speaking_source:
            self.stop_speaking()
            return

        text = self.source_text.strip()
        if text and self._on_speak is not None:
            self.stop_speaking()
            self._is_speaking_source = True
            btn.set_icon_name("media-playback-stop-symbolic")
            btn.set_tooltip_text("Hentikan suara (TTS)")
            self._on_speak(text, self._current_source_lang or self._detected_lang)

    def _on_speak_result_clicked(self, btn: Gtk.Button) -> None:
        if self._is_speaking_result:
            self.stop_speaking()
            return

        if self._current_result_text and self._on_speak is not None:
            self.stop_speaking()
            self._is_speaking_result = True
            btn.set_icon_name("media-playback-stop-symbolic")
            btn.set_tooltip_text("Hentikan suara (TTS)")
            self._on_speak(self._current_result_text, self._current_target_lang)

    def set_current_entry(self, entry_id: int | None, favorite: bool = False) -> None:
        """Kaitkan hasil yang tampil dengan entri riwayat (untuk tombol favorit)."""
        self._current_entry_id = entry_id
        self._fav_button.handler_block_by_func(self._on_fav_toggled)
        try:
            self._fav_button.set_active(favorite)
        finally:
            self._fav_button.handler_unblock_by_func(self._on_fav_toggled)
        self._fav_button.set_sensitive(entry_id is not None)

    def _on_fav_toggled(self, btn: Gtk.ToggleButton) -> None:
        if self._current_entry_id is None or self._on_toggle_favorite is None:
            return
        new_state = self._on_toggle_favorite(self._current_entry_id)
        if new_state is not None and new_state != btn.get_active():
            self.set_current_entry(self._current_entry_id, new_state)

    def _on_history_clicked(self, btn: Gtk.Button) -> None:
        if self._on_show_history is not None:
            self._on_show_history()

    def _on_copy_clicked(self, btn: Gtk.Button) -> None:
        if self._current_result_text and self._on_copy_result is not None:
            self._on_copy_result(self._current_result_text)

    def _on_continuous_ocr_toggled_internal(self, btn: Gtk.ToggleButton) -> None:
        self._continuous_ocr = btn.get_active()
        if self._on_continuous_ocr_toggled is not None:
            self._on_continuous_ocr_toggled(self._continuous_ocr)

    @property
    def continuous_ocr(self) -> bool:
        """Apakah mode OCR kontinu (append) sedang aktif."""
        return self._continuous_ocr

    @continuous_ocr.setter
    def continuous_ocr(self, value: bool) -> None:
        self._continuous_ocr = bool(value)
        if hasattr(self, "_continuous_ocr_button"):
            self._continuous_ocr_button.set_active(self._continuous_ocr)

    def _on_pin_toggled(self, btn: Gtk.ToggleButton) -> None:
        self._pinned = btn.get_active()
        self._update_pin_button_style()

    def _on_expand_clicked(self, btn: Gtk.Button) -> None:
        """Buka hasil terjemahan saat ini di jendela terpisah mandiri (P2)."""
        source = self.source_text
        result = self._current_result_text
        if not result and not source:
            return

        if self._on_expand is not None:
            self._on_expand(source, result)
        else:
            from pinux.ui.translation_window import TranslationWindow

            win = TranslationWindow(source, result)
            win.present()

        if not self._pinned:
            self.hide()

    def present_at_cursor(self, x: int, y: int) -> None:
        """Tampilkan jendela popup pada posisi kursor dengan offset 16 piksel, di-clamp ke workarea (R1.4)."""
        offset = 16
        try:
            display = Gdk.Display.get_default()
            if display is not None:
                # Cari monitor terdekat pada koordinat (x, y)
                monitor = display.get_monitor_at_point(x, y) if hasattr(display, "get_monitor_at_point") else None
                if monitor is None:
                    monitors = display.get_monitors()
                    if monitors and monitors.get_n_items() > 0:
                        monitor = monitors.get_item(0)

                if monitor is not None:
                    workarea = monitor.get_geometry()
                    if hasattr(monitor, "get_workarea"):
                        wa = monitor.get_workarea()
                        if wa and wa.width > 0 and wa.height > 0:
                            workarea = wa

                    # Batasi tinggi scroller agar proporsional dan tidak mendorong jendela keluar layar
                    avail_h = workarea.height - (2 * offset)
                    if hasattr(self, "_result_scroller") and avail_h > 200:
                        max_res_h = min(360, max(140, avail_h - 380))
                        self._result_scroller.set_max_content_height(max_res_h)
        except Exception as exc:
            logger.debug(f"Pengecekan workarea monitor dilewati: {exc}")

        # Pastikan ukuran lebar & tinggi kembali proporsional sesuai pengaturan (misal 420x420px)
        self.set_default_size(self._default_width, 420)

        # Tampilkan dan fokuskan jendela
        self.present()

    def focus_input(self) -> None:
        """Pindahkan fokus keyboard ke kolom teks sumber."""
        self._entry.grab_focus()

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

    def append_source_text(self, text: str, sep: str = "\n\n") -> str:
        """Tambahkan teks ke akhir entry (mode kontinu/append) dan kembalikan teks lengkapnya."""
        current = self.source_text.strip()
        new_text = f"{current}{sep}{text.strip()}" if current else text.strip()
        self.set_source_text(new_text)
        return new_text


    def _on_src_lang_changed(self, dropdown: Gtk.DropDown, pspec: Any) -> None:
        if self._ignore_lang_changes:
            return
        idx = dropdown.get_selected()
        code = self.LANGUAGES[idx][0] if 0 <= idx < len(self.LANGUAGES) else "auto"
        self._current_source_lang = None if code == "auto" else code
        if self._on_language_selected is not None:
            self._on_language_selected(self._current_source_lang, self._current_target_lang)

    def _on_tgt_lang_changed(self, dropdown: Gtk.DropDown, pspec: Any) -> None:
        if self._ignore_lang_changes:
            return
        idx = dropdown.get_selected()
        code = self._target_languages[idx][0] if 0 <= idx < len(self._target_languages) else "id"
        self._current_target_lang = code
        if self._on_language_selected is not None:
            self._on_language_selected(self._current_source_lang, self._current_target_lang)

    @property
    def source_lang(self) -> str | None:
        """Bahasa sumber terpilih; None berarti deteksi otomatis."""
        return self._current_source_lang

    @property
    def target_lang(self) -> str:
        """Bahasa tujuan terpilih di dropdown."""
        return self._current_target_lang

    def show_detected_language(self, detected: str | None) -> None:
        """Tampilkan bahasa terdeteksi sebagai label tanpa mengunci dropdown sumber."""
        if self._current_source_lang is None and detected:
            self._lang_label.set_text(f"(terdeteksi: {detected})")
        else:
            self._lang_label.set_text("")

    def set_languages_display(self, source: str, target: str) -> None:
        """Perbarui dropdown dan label bahasa aktif (misal: 'id → en')."""
        self._ignore_lang_changes = True
        try:
            # Cari dan pilih indeks sumber
            src_code = source.lower()
            src_idx = 0  # auto default
            for i, (code, _) in enumerate(self.LANGUAGES):
                if code.lower() == src_code:
                    src_idx = i
                    break
            self._src_dropdown.set_selected(src_idx)
            self._current_source_lang = None if self.LANGUAGES[src_idx][0] == "auto" else self.LANGUAGES[src_idx][0]

            # Cari dan pilih indeks target
            tgt_code = target.lower()
            tgt_idx = 0
            for i, (code, _) in enumerate(self._target_languages):
                if code.lower() == tgt_code:
                    tgt_idx = i
                    break
            self._tgt_dropdown.set_selected(tgt_idx)
            self._current_target_lang = self._target_languages[tgt_idx][0]

            # Tampilkan info jika bahasa terdeteksi otomatis
            if src_idx == 0 and source and source != "auto":
                self._lang_label.set_text(f"({source})")
            else:
                self._lang_label.set_text("")
        finally:
            self._ignore_lang_changes = False

    def _clear_alternatives(self) -> None:
        """Hapus seluruh kartu hasil layanan tambahan dari kontainer."""
        if hasattr(self, "_alternatives_box"):
            while child := self._alternatives_box.get_first_child():
                self._alternatives_box.remove(child)
            self._alternatives_box.set_visible(False)

    def _render_alternatives(self, alternatives: Sequence[Any]) -> None:
        """Tampilkan kartu alternatif hasil layanan tambahan (mode bandingkan)."""
        self._clear_alternatives()
        if not alternatives or not hasattr(self, "_alternatives_box"):
            return

        for alt in alternatives:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            card.add_css_class("card")

            # Header kartu: nama provider
            header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            prov_name = alt.display_name or alt.provider_id
            title_lbl = Gtk.Label(label=prov_name)
            title_lbl.add_css_class("caption")
            title_lbl.add_css_class("dim-label")
            title_lbl.set_xalign(0.0)
            header_box.append(title_lbl)
            card.append(header_box)

            # Isi teks atau galat
            if alt.error:
                err_lbl = Gtk.Label(label=f"Gagal: {alt.error}")
                err_lbl.add_css_class("caption")
                err_lbl.add_css_class("error")
                err_lbl.set_xalign(0.0)
                err_lbl.set_wrap(True)
                err_lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
                err_lbl.set_max_width_chars(45)
                card.append(err_lbl)
            else:
                body_lbl = Gtk.Label(label=alt.text)
                body_lbl.set_wrap(True)
                body_lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
                body_lbl.set_max_width_chars(45)
                body_lbl.set_selectable(True)
                body_lbl.set_xalign(0.0)
                card.append(body_lbl)

            self._alternatives_box.append(card)

        self._alternatives_box.set_visible(True)

    def _clear_dictionary(self) -> None:
        """Hapus entri kamus dan fonetik sebelumnya."""
        if hasattr(self, "_phonetic_label"):
            self._phonetic_label.set_text("")
            self._phonetic_label.set_visible(False)
        if hasattr(self, "_dict_box"):
            while child := self._dict_box.get_first_child():
                self._dict_box.remove(child)
            self._dict_box.set_visible(False)

    def _render_dictionary(self, phonetic: str, entries: Sequence[Any]) -> None:
        """Tampilkan fonetik dan daftar kelas kata/sinonim kamus."""
        self._clear_dictionary()
        has_content = False

        if phonetic and hasattr(self, "_phonetic_label"):
            self._phonetic_label.set_text(f"[{phonetic}]")
            self._phonetic_label.set_visible(True)
            has_content = True

        if entries and hasattr(self, "_dict_box"):
            for entry in entries:
                pos = getattr(entry, "part_of_speech", "")
                terms = getattr(entry, "terms", ())
                if not pos and not terms:
                    continue

                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                if pos:
                    pos_lbl = Gtk.Label(label=pos)
                    pos_lbl.add_css_class("caption")
                    pos_lbl.add_css_class("accent")
                    pos_lbl.set_xalign(0.0)
                    row.append(pos_lbl)

                if terms:
                    terms_lbl = Gtk.Label(label=", ".join(terms))
                    terms_lbl.add_css_class("caption")
                    terms_lbl.add_css_class("dim-label")
                    terms_lbl.set_wrap(True)
                    terms_lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
                    terms_lbl.set_max_width_chars(40)
                    terms_lbl.set_xalign(0.0)
                    terms_lbl.set_hexpand(True)
                    row.append(terms_lbl)

                self._dict_box.append(row)

            self._dict_box.set_visible(True)
            has_content = True

    def show_loading(self) -> None:
        """Tampilkan spinner dan bersihkan label pesan galat (R5.5)."""
        self._spinner.set_visible(True)
        self._spinner.set_spinning(True)
        self._error_label.set_visible(False)
        self._error_label.set_text("")
        self._clear_alternatives()
        self._clear_dictionary()
        self.set_current_entry(None)

    def show_result(self, result: "TranslationResult") -> None:
        """Tampilkan hasil terjemahan dan hentikan indikator kemajuan (Properti 4)."""
        self._spinner.set_spinning(False)
        self._spinner.set_visible(False)
        self._error_label.set_visible(False)

        self._current_result_text = result.text
        self._detected_lang = getattr(result, "detected_source_lang", None)
        self._result_label.set_text(result.text)
        self._result_label.set_visible(True)

        # Perbarui label judul section
        src_tag = (self._detected_lang or self._current_source_lang or "").upper()
        tgt_tag = (self._current_target_lang or "").upper()
        if hasattr(self, "_source_title_label"):
            self._source_title_label.set_text(f"Sumber ({src_tag})" if src_tag else "Sumber")
        if hasattr(self, "_result_title_label"):
            self._result_title_label.set_text(f"Terjemahan ({tgt_tag})" if tgt_tag else "Terjemahan")

        # Tampilkan fonetik & kamus bila tersedia (kata tunggal ala Bob)
        phonetic = getattr(result, "phonetic", "")
        dict_entries = getattr(result, "dictionary_entries", ())
        self._render_dictionary(phonetic, dict_entries)

        # Tampilkan kartu alternatif bila mode bandingkan aktif
        alternatives = getattr(result, "alternatives", ())
        self._render_alternatives(alternatives)

    # Alias agar kompatibel dengan pemanggilan _show_alternatives
    _show_alternatives = _render_alternatives

    def show_error(self, message: str) -> None:
        """Tampilkan pesan galat dan hentikan indikator kemajuan (Properti 4)."""
        self._spinner.set_spinning(False)
        self._spinner.set_visible(False)
        self._clear_alternatives()
        self._clear_dictionary()


        self._error_label.set_text(message)
        self._error_label.set_visible(True)
