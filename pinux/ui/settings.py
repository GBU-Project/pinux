"""Implementasi SettingsWindow menggunakan libadwaita (Adw.PreferencesWindow).

Menyediakan 4 halaman preferensi sesuai design.md:
1. Umum: Target_Language, bahasa cadangan, batas karakter, pin bawaan,
   serta keterangan penangkapan teks pada Wayland (R11.6).
2. Provider: Daftar TranslationProvider, pilihan provider aktif, dan
   kolom penyimpanan kredensial (API key) untuk Keyed_Provider.
3. Pintasan: Menampilkan status backend pintasan (portal atau instruksi manual CLI) (R1.3).
4. OCR: Status ketersediaan OcrEngine, tombol unduh model, dan progress bar (R7.4).

Menyediakan penanganan peringatan keamanan berkas fallback (R9.3) dan
peringatan konfigurasi tidak valid (R9.5).

Perujuk: R3.4, R3.7, R6.5, R7.4, R9.3, R9.4, R9.5, R11.6.
"""

from __future__ import annotations

import logging
import weakref
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from pinux.portal.shortcuts import CLI_FLAGS, REASON_PENDING, cli_command, describe_fallback

#: Nama halaman Pintasan, untuk membukanya langsung (``SettingsWindow.show_page``).
SHORTCUTS_PAGE_NAME = "shortcuts"

# Judul baris pintasan pada halaman Pintasan (id sesuai ShortcutSpec).
_SHORTCUT_TITLES = {
    "translate": "Penerjemahan Clipboard",
    "ocr": "Seleksi OCR Tangkapan Layar",
}

if TYPE_CHECKING:
    from pinux.config import Settings
    from pinux.configstore import ConfigStore
    from pinux.credentials import CredentialStore
    from pinux.ocr.client import OcrWorkerClient
    from pinux.portal.shortcuts import ShortcutManager
    from pinux.translate.registry import ProviderRegistry

__all__ = ["SettingsWindow"]

logger = logging.getLogger("pinux.ui.settings")


def _weak_listener(window: "SettingsWindow", manager: "ShortcutManager") -> Callable[[], None]:
    """Callback ``connect_changed`` yang tidak menahan ``window`` di memori.

    Bila jendela sudah tidak ada, callback melepas dirinya dari ``manager``.
    """
    ref = weakref.ref(window)

    def listener() -> None:
        target = ref()
        if target is None:
            manager.disconnect_changed(listener)
        else:
            target._on_shortcuts_changed()

    return listener


class SettingsWindow(Adw.PreferencesWindow):
    """Jendela pengaturan Pinux berbasis libadwaita."""

    def __init__(
        self,
        config_store: "ConfigStore",
        credential_store: "CredentialStore",
        provider_registry: "ProviderRegistry",
        shortcut_manager: "ShortcutManager",
        ocr_client: "OcrWorkerClient",
        session_type: str = "wayland",
        *,
        on_settings_changed: Callable[["Settings"], None] | None = None,
    ) -> None:
        super().__init__()

        self._config_store = config_store
        self._credential_store = credential_store
        self._provider_registry = provider_registry
        self._shortcut_manager = shortcut_manager
        self._ocr_client = ocr_client
        self._session_type = session_type
        self._on_settings_changed = on_settings_changed

        self._settings: Settings = self._config_store.load()

        self.set_title("Pengaturan Pinux")
        self.set_default_size(600, 520)
        self.set_hide_on_close(True)

        self._build_pages()
        self._setup_window_controls()

    def _setup_window_controls(self) -> None:
        """Tambahkan tombol tutup eksplisit pada header dan dukung tombol Escape."""
        # Tombol Escape untuk menutup jendela
        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

        # Cari Adw.HeaderBar bawaan untuk menyematkan tombol tutup yang pasti terlihat
        def _find_header(widget: Gtk.Widget) -> Adw.HeaderBar | None:
            if isinstance(widget, Adw.HeaderBar):
                return widget
            child = widget.get_first_child()
            while child:
                found = _find_header(child)
                if found:
                    return found
                child = child.get_next_sibling()
            return None

        header = _find_header(self)
        if header is not None:
            close_btn = Gtk.Button(icon_name="window-close-symbolic")
            close_btn.set_tooltip_text("Tutup pengaturan (Esc)")
            close_btn.add_css_class("flat")
            close_btn.connect("clicked", lambda _: self.close())
            header.pack_end(close_btn)

    def _on_key_pressed(
        self,
        controller: Gtk.EventControllerKey,
        keyval: int,
        keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _build_pages(self) -> None:
        self._build_general_page()
        self._build_provider_page()
        self._build_shortcuts_page()
        self._build_ocr_page()

    # -- Halaman Umum ---------------------------------------------------------

    def _build_general_page(self) -> None:
        page = Adw.PreferencesPage()
        page.set_title("Umum")
        page.set_icon_name("preferences-system-symbolic")

        # Peringatan konfigurasi / kredensial jika ada
        if self._credential_store.using_fallback:
            banner_group = Adw.PreferencesGroup()
            banner = Adw.Banner.new(
                "Peringatan: Secret Service tidak aktif. Kredensial disimpan pada berkas lokal (0600)."
            )
            banner.set_revealed(True)
            banner_group.add(banner)
            page.add(banner_group)

        group = Adw.PreferencesGroup()
        group.set_title("Bahasa dan Terjemahan")

        # Keterangan Wayland (R11.6)
        if self._session_type == "wayland":
            group.set_description(
                "Sesi Wayland aktif: teks yang disorot diambil dari Clipboard saat popup terbuka."
            )

        # Target language
        self._target_lang_row = Adw.EntryRow()
        self._target_lang_row.set_title("Bahasa Tujuan")
        self._target_lang_row.set_text(self._settings.target_language)
        self._target_lang_row.connect("changed", self._on_general_changed)
        group.add(self._target_lang_row)

        # Fallback language
        self._fallback_lang_row = Adw.EntryRow()
        self._fallback_lang_row.set_title("Bahasa Cadangan (Bila sama dengan sumber)")
        self._fallback_lang_row.set_text(self._settings.fallback_language)
        self._fallback_lang_row.connect("changed", self._on_general_changed)
        group.add(self._fallback_lang_row)

        # Batas karakter
        self._max_chars_row = Adw.SpinRow.new_with_range(100, 10000, 100)
        self._max_chars_row.set_title("Batas Maksimal Karakter")
        self._max_chars_row.set_value(float(self._settings.max_chars))
        self._max_chars_row.connect("notify::value", self._on_general_changed)
        group.add(self._max_chars_row)

        # Pin default
        self._pin_default_row = Adw.SwitchRow()
        self._pin_default_row.set_title("Buka Popup dalam Keadaan Pin")
        self._pin_default_row.set_active(self._settings.popup.pin_default)
        self._pin_default_row.connect("notify::active", self._on_general_changed)
        group.add(self._pin_default_row)

        page.add(group)

        # Kelompok Pemrosesan Teks & Otomatisasi (ala Bob)
        text_group = Adw.PreferencesGroup()
        text_group.set_title("Pemrosesan Teks dan Otomatisasi")
        text_group.set_description(

            "Optimasi teks sebelum diterjemahkan (berguna untuk PDF, kode sumber, atau OCR)."
        )

        self._unwrap_lines_row = Adw.SwitchRow()
        self._unwrap_lines_row.set_title("Gabungkan Baris Terputus (Unwrap)")
        self._unwrap_lines_row.set_subtitle("Menghapus pemisah baris tunggal di tengah paragraf (teks PDF/OCR)")
        self._unwrap_lines_row.set_active(self._settings.text_processing.unwrap_lines)
        self._unwrap_lines_row.connect("notify::active", self._on_text_processing_changed)
        text_group.add(self._unwrap_lines_row)

        self._remove_hyphens_row = Adw.SwitchRow()
        self._remove_hyphens_row.set_title("Hapus Tanda Hubung Pergantian Baris")
        self._remove_hyphens_row.set_subtitle("Menggabungkan kata yang terpotong tanda '-' di akhir baris")
        self._remove_hyphens_row.set_active(self._settings.text_processing.remove_hyphens)
        self._remove_hyphens_row.connect("notify::active", self._on_text_processing_changed)
        text_group.add(self._remove_hyphens_row)

        self._remove_comments_row = Adw.SwitchRow()
        self._remove_comments_row.set_title("Hapus Simbol Komentar Kode")
        self._remove_comments_row.set_subtitle("Membersihkan awalan komentar bahasa pemrograman (//, #, /* */)")
        self._remove_comments_row.set_active(self._settings.text_processing.remove_comments)
        self._remove_comments_row.connect("notify::active", self._on_text_processing_changed)
        text_group.add(self._remove_comments_row)

        self._auto_copy_result_row = Adw.SwitchRow()
        self._auto_copy_result_row.set_title("Salin Otomatis Hasil Terjemahan")
        self._auto_copy_result_row.set_subtitle("Menyalin hasil terjemahan langsung ke clipboard setelah selesai")
        self._auto_copy_result_row.set_active(self._settings.text_processing.auto_copy_result)
        self._auto_copy_result_row.connect("notify::active", self._on_text_processing_changed)
        text_group.add(self._auto_copy_result_row)

        page.add(text_group)
        self.add(page)

    # -- Halaman Provider -----------------------------------------------------

    def _build_provider_page(self) -> None:
        page = Adw.PreferencesPage()
        page.set_title("Provider")
        page.set_icon_name("network-wired-symbolic")

        group = Adw.PreferencesGroup()
        group.set_title("Pilihan Mesin Penerjemah")

        self._provider_rows: dict[str, Adw.ActionRow] = {}
        self._cred_entries: dict[str, Adw.PasswordEntryRow] = {}

        for info in self._provider_registry.all_info():
            p = info.provider
            row = Adw.ActionRow()
            row.set_title(p.display_name)
            row.set_subtitle(f"ID: {p.id}")

            # Radio-like or activate button
            check = Gtk.CheckButton()
            check.set_active(p.id == self._settings.provider)
            check.connect("toggled", lambda btn, pid=p.id: self._on_provider_selected(btn, pid))
            row.add_prefix(check)

            # Jika provider butuh kredensial (R3.7)
            if p.id == "openai":
                # Endpoint & model dapat diubah (Ollama, LM Studio, OpenAI, dll.)
                group.add(row)
                self._llm_endpoint_row = Adw.EntryRow()
                self._llm_endpoint_row.set_title("Endpoint (…/v1/chat/completions)")
                self._llm_endpoint_row.set_text(self._settings.llm.endpoint_url)
                self._llm_endpoint_row.connect("changed", self._on_llm_changed)
                group.add(self._llm_endpoint_row)
                self._llm_model_row = Adw.EntryRow()
                self._llm_model_row.set_title("Model")
                self._llm_model_row.set_text(self._settings.llm.model)
                self._llm_model_row.connect("changed", self._on_llm_changed)
                group.add(self._llm_model_row)

            if p.id == "libretranslate":
                group.add(row)
                self._libre_endpoint_row = Adw.EntryRow()
                self._libre_endpoint_row.set_title("Alamat instance LibreTranslate")
                self._libre_endpoint_row.set_text(self._settings.libretranslate.endpoint_url)
                self._libre_endpoint_row.connect("changed", self._on_libre_changed)
                group.add(self._libre_endpoint_row)

            if p.requires_credential() or p.id in ("openai", "libretranslate"):
                cred_row = Adw.PasswordEntryRow()
                cred_row.set_title(f"API Key ({p.display_name})")
                current_cred = self._credential_store.get(p.id) or ""
                cred_row.set_text(current_cred)
                cred_row.connect("changed", lambda entry, pid=p.id: self._on_credential_changed(entry, pid))

                if p.id not in ("openai", "libretranslate"):
                    group.add(row)
                group.add(cred_row)
                self._cred_entries[p.id] = cred_row
            else:
                group.add(row)

            self._provider_rows[p.id] = row

        page.add(group)

        fallback_group = Adw.PreferencesGroup()
        fallback_group.set_title("Provider Cadangan")
        fallback_group.set_description(
            "Dicoba berurutan bila provider utama gagal (jaringan, kuota, atau kunci). "
            "Tulis ID provider dipisah koma, mis. deepl, libretranslate."
        )
        self._fallback_row = Adw.EntryRow()
        self._fallback_row.set_title("Urutan cadangan")
        self._fallback_row.set_text(", ".join(self._settings.fallback_providers))
        self._fallback_row.connect("changed", self._on_fallback_changed)
        fallback_group.add(self._fallback_row)
        page.add(fallback_group)

        compare_group = Adw.PreferencesGroup()
        compare_group.set_title("Bandingkan Layanan")
        compare_group.set_description(
            "Layanan tambahan yang hasilnya ditampilkan berdampingan di popup. "
            "Tulis ID provider dipisah koma, mis. deepl, openai."
        )
        self._compare_row = Adw.EntryRow()
        self._compare_row.set_title("Layanan tambahan")
        self._compare_row.set_text(", ".join(self._settings.compare_providers))
        self._compare_row.connect("changed", self._on_compare_changed)
        compare_group.add(self._compare_row)
        page.add(compare_group)
        self.add(page)

    # -- Halaman Pintasan -----------------------------------------------------

    def _build_shortcuts_page(self) -> None:
        page = Adw.PreferencesPage()
        page.set_title("Pintasan")
        page.set_name(SHORTCUTS_PAGE_NAME)
        page.set_icon_name("preferences-desktop-keyboard-shortcuts-symbolic")

        self._shortcuts_group = Adw.PreferencesGroup()
        self._shortcuts_rows: list[Gtk.Widget] = []
        self._shortcuts_destroyed = False
        self._shortcuts_refresh_scheduled = False
        self._fill_shortcuts_group()

        page.add(self._shortcuts_group)
        self.add(page)

        # Pengikatan portal berjalan setelah startup dan dapat berakhir kapan saja
        # (restart portal, perubahan pemicu), jadi halaman memperbarui diri. Callback
        # memegang referensi lemah agar manajer tidak menahan jendela di memori.
        self._shortcut_listener = _weak_listener(self, self._shortcut_manager)
        self._shortcut_manager.connect_changed(self._shortcut_listener)

    def destroy(self) -> None:
        """Hancurkan jendela dan lepas pendengar ShortcutManager.

        Di GTK4 sinyal ``destroy`` tidak dipancarkan selama masih ada referensi Python,
        sehingga pelepasan dilakukan di sini.
        """
        self._shortcuts_destroyed = True
        listener = getattr(self, "_shortcut_listener", None)
        if listener is not None:
            self._shortcut_manager.disconnect_changed(listener)
        super().destroy()

    def _on_shortcuts_changed(self) -> None:
        # Dijadwalkan lewat main loop agar aman dipanggil dari thread mana pun, dan
        # dikumpulkan: pemberitahuan beruntun hanya menyusun ulang halaman sekali.
        if self._shortcuts_refresh_scheduled:
            return
        self._shortcuts_refresh_scheduled = True
        GLib.idle_add(self._refresh_shortcuts_page)

    def _refresh_shortcuts_page(self) -> bool:
        self._shortcuts_refresh_scheduled = False
        if not self._shortcuts_destroyed:
            self._fill_shortcuts_group()
        return GLib.SOURCE_REMOVE

    def show_page(self, name: str) -> None:
        """Buka halaman berdasarkan namanya (mis. ``SHORTCUTS_PAGE_NAME``)."""
        try:
            self.set_visible_page_name(name)
        except Exception as exc:
            logger.debug(f"Halaman '{name}' tidak dapat dibuka: {exc}")

    def _add_shortcut_row(self, row: Gtk.Widget) -> None:
        self._shortcuts_group.add(row)
        self._shortcuts_rows.append(row)

    def _fill_shortcuts_group(self) -> None:
        """Isi ulang grup Pintasan sesuai keadaan ShortcutManager saat ini."""
        group = self._shortcuts_group
        for row in self._shortcuts_rows:
            group.remove(row)
        self._shortcuts_rows.clear()

        backend = self._shortcut_manager.active_backend

        if backend == "portal":
            group.set_title("Pintasan Keyboard Global (Portal XDG)")
            group.set_description("Pintasan diatur dan disetujui melalui sistem desktop.")

            for s in self._shortcut_manager.bound_shortcuts:
                row = Adw.ActionRow()
                row.set_title(s.id.capitalize())
                escaped_trigger = GLib.markup_escape_text(s.trigger)
                row.set_subtitle(f"Pemicu: {escaped_trigger}")
                self._add_shortcut_row(row)

            btn_row = Adw.ActionRow()
            btn_row.set_title("Ubah Kombinasi Tombol Pintasan")
            btn_row.set_subtitle("Buka dialog konfigurasi pintasan resmi desktop GNOME")
            cfg_btn = Gtk.Button(label="Ubah di Sistem")
            cfg_btn.connect("clicked", lambda _: self._shortcut_manager.configure_shortcuts())
            btn_row.add_suffix(cfg_btn)
            self._add_shortcut_row(btn_row)

            # Pintasan yang tidak disetujui portal tetap perlu jalur CLI (R1.3)
            for sid in tuple(self._shortcut_manager.missing_shortcuts):
                flag = CLI_FLAGS.get(sid)
                if flag is None:
                    continue
                missing_row = Adw.ActionRow()
                missing_row.set_title(f"{_SHORTCUT_TITLES.get(sid, sid.capitalize())} (tidak disetujui)")
                missing_row.set_subtitle(GLib.markup_escape_text(cli_command(flag)))
                missing_row.set_subtitle_selectable(True)
                self._add_shortcut_row(missing_row)
        else:
            reason = self._shortcut_manager.last_reason
            group.set_title(
                "Menunggu Persetujuan Desktop…" if reason == REASON_PENDING
                else "Pintasan Keyboard Manual (CLI Mode)"
            )
            group.set_description(describe_fallback(reason))

            for sid in ("translate", "ocr"):
                row = Adw.ActionRow()
                row.set_title(_SHORTCUT_TITLES[sid])
                row.set_subtitle(GLib.markup_escape_text(cli_command(CLI_FLAGS[sid])))
                row.set_subtitle_selectable(True)
                self._add_shortcut_row(row)

    # -- Halaman OCR ----------------------------------------------------------

    def _build_ocr_page(self) -> None:
        page = Adw.PreferencesPage()
        page.set_title("OCR")
        page.set_icon_name("camera-photo-symbolic")

        group = Adw.PreferencesGroup()
        group.set_title("Mesin OCR Luring")

        is_avail = self._ocr_client.is_available()

        status_row = Adw.ActionRow()
        status_row.set_title("Status Paket OCR")
        status_row.set_subtitle("Tersedia" if is_avail else "Paket 'pinux[ocr]' belum terpasang")
        group.add(status_row)

        if is_avail:
            download_row = Adw.ActionRow()
            download_row.set_title("Model OCR RapidOCR")
            download_row.set_subtitle("Unduh atau muat model ke memori")

            btn = Gtk.Button(label="Muat Model")
            btn.connect("clicked", self._on_load_model_clicked)
            download_row.add_suffix(btn)
            group.add(download_row)

            self._ocr_progress_bar = Gtk.ProgressBar()
            self._ocr_progress_bar.set_fraction(0.0)
            self._ocr_progress_bar.set_visible(False)
            group.add(self._ocr_progress_bar)

        page.add(group)
        self.add(page)

    # -- Event Handlers -------------------------------------------------------

    def _on_general_changed(self, *args: Any) -> None:
        self._settings.target_language = self._target_lang_row.get_text()
        self._settings.fallback_language = self._fallback_lang_row.get_text()
        self._settings.max_chars = int(self._max_chars_row.get_value())
        self._settings.popup.pin_default = self._pin_default_row.get_active()

        self._save_and_notify()

    def _on_text_processing_changed(self, *args: Any) -> None:
        self._settings.text_processing.unwrap_lines = self._unwrap_lines_row.get_active()
        self._settings.text_processing.remove_hyphens = self._remove_hyphens_row.get_active()
        self._settings.text_processing.remove_comments = self._remove_comments_row.get_active()
        self._settings.text_processing.auto_copy_result = self._auto_copy_result_row.get_active()

        self._save_and_notify()

    def _on_libre_changed(self, *args: Any) -> None:
        url = self._libre_endpoint_row.get_text().strip()
        if url.startswith(("http://", "https://")):
            self._settings.libretranslate.endpoint_url = url
            self._save_and_notify()

    def _on_fallback_changed(self, *args: Any) -> None:
        ids = [i.strip() for i in self._fallback_row.get_text().split(",") if i.strip()]
        self._settings.fallback_providers = list(dict.fromkeys(ids))
        self._save_and_notify()

    def _on_compare_changed(self, *args: Any) -> None:
        ids = [i.strip() for i in self._compare_row.get_text().split(",") if i.strip()]
        self._settings.compare_providers = list(dict.fromkeys(ids))
        self._save_and_notify()

    def _on_llm_changed(self, *args: Any) -> None:
        endpoint = self._llm_endpoint_row.get_text().strip()
        model = self._llm_model_row.get_text().strip()
        # Simpan hanya bila valid; kolom kosong/setengah diketik tidak menimpa.
        if endpoint.startswith(("http://", "https://")) and model:
            self._settings.llm.endpoint_url = endpoint
            self._settings.llm.model = model
            self._save_and_notify()

    def _on_provider_selected(self, btn: Gtk.CheckButton, provider_id: str) -> None:
        if btn.get_active():
            self._settings.provider = provider_id
            self._save_and_notify()

    def _on_credential_changed(self, entry: Adw.PasswordEntryRow, provider_id: str) -> None:
        secret = entry.get_text()
        self._credential_store.set(provider_id, secret)
        if hasattr(self._provider_registry, "invalidate_credential_cache"):
            self._provider_registry.invalidate_credential_cache(provider_id)

    def _on_load_model_clicked(self, btn: Gtk.Button) -> None:
        if hasattr(self, "_ocr_progress_bar"):
            self._ocr_progress_bar.set_visible(True)

            def _prog(p: float) -> None:
                GLib.idle_add(lambda: self._ocr_progress_bar.set_fraction(p))

            def _bg() -> None:
                try:
                    self._ocr_client.ensure_model(on_progress=_prog)
                except Exception as exc:
                    logger.error(f"Gagal memuat model: {exc}")

            import threading
            threading.Thread(target=_bg, daemon=True).start()

    def _save_and_notify(self) -> None:
        try:
            self._config_store.save(self._settings)
            if self._on_settings_changed is not None:
                self._on_settings_changed(self._settings)
        except Exception as exc:
            logger.error(f"Gagal menyimpan pengaturan: {exc}")
