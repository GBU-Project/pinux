"""Aplikasi utama Pinux (Adw.Application) dan TriggerRouter (task 19).

Menggabungkan seluruh komponen:
- ConfigStore & CredentialStore
- ProviderRegistry & RequestScheduler
- TextCapturer, GlobalShortcutsPortal & ShortcutManager
- ScreenshotPortal, OcrWorkerClient
- PopupWindow, RegionOverlay, SettingsWindow, TrayItem

Mendukung opsi baris perintah instans tunggal (GApplication):
- ``--trigger`` -> memicu penerjemahan teks clipboard
- ``--pick-region`` -> memicu seleksi area layar & OCR
- ``--settings`` -> membuka jendela preferensi

Perujuk: R1.1, R1.3, R1.6, R6.3, R8.1, R8.3, R8.4, R10.1 pada requirements.md, serta design.md.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from typing import Any, Callable

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from pinux.capture.capturer import TextCapturer
from pinux.config import Settings
from pinux.configstore import ConfigStore
from pinux.credentials import CredentialStore
from pinux.ocr.client import OcrWorkerClient
from pinux.portal.screenshot import ScreenshotPortal
from pinux.portal.shortcuts import ShortcutManager, ShortcutSpec
from pinux.scheduler import RequestScheduler
from pinux.translate.base import TranslationRequest
from pinux.translate.registry import ProviderRegistry
from pinux.tray import TrayItem
from pinux.ui.popup import PopupWindow
from pinux.ui.region import Rect, RegionOverlay, crop_image_region
from pinux.ui.settings import SettingsWindow

__all__ = ["PinuxApp", "TriggerRouter"]

logger = logging.getLogger("pinux.app")


class TriggerRouter:
    """Menyatukan seluruh sumber pemicu (shortcut, CLI, tray, popup) menjadi alur kerja tunggal."""

    def __init__(self, app: "PinuxApp") -> None:
        self.app = app

    def on_shortcut_activated(self, action: str) -> None:
        """Dipanggil saat sinyal Activated dari portal diterima."""
        if action == "translate":
            self.request_translate()
        elif action == "ocr":
            self.request_ocr()

    def request_translate(self) -> None:
        """Alur terjemahan teks penuh dari clipboard (R1.1, R2.1)."""
        # 1. Baca teks dari clipboard
        capture_res = self.app.text_capturer.read_source_text(
            max_chars=self.app.settings.max_chars
        )
        source_text = capture_res.text

        # 2. Tampilkan popup di dekat kursor
        popup = self.app.get_popup_window()
        popup.set_source_text(source_text)
        popup.present_at_cursor(0, 0)

        # 3. Jika teks tidak kosong, kirim ke RequestScheduler
        if source_text.strip():
            self._execute_translation(source_text)
        else:
            popup.show_loading()
            popup._spinner.set_visible(False)

    def request_input_translate(self) -> None:
        """Buka jendela popup kosong yang siap untuk input manual pengguna."""
        popup = self.app.get_popup_window()
        popup.set_source_text("")
        popup.show_loading()
        popup._spinner.set_visible(False)
        popup.present_at_cursor(0, 0)

    def show_popup_window(self) -> None:
        """Tampilkan jendela popup yang sedang ada."""
        popup = self.app.get_popup_window()
        popup.present_at_cursor(0, 0)

    def request_ocr_pure(self) -> None:
        """Alur tangkapan layar dan salin teks OCR ke clipboard tanpa menerjemahkan."""
        overlay = self.app.get_region_overlay()
        overlay.open(
            on_selected=self._on_ocr_pure_region_selected,
            on_cancelled=lambda: logger.info("Seleksi OCR murni dibatalkan pengguna."),
        )

    def _on_ocr_pure_region_selected(self, rect: Rect) -> None:
        popup = self.app.get_popup_window()
        popup.set_source_text("Membaca teks dari gambar...")
        popup.show_loading()
        popup.present_at_cursor(0, 0)

        def _bg_pure_ocr() -> None:
            try:
                raw_png = self.app.screenshot_portal.capture_fullscreen()
                cropped_png = crop_image_region(raw_png, rect)
                ocr_result = self.app.ocr_client.recognize(cropped_png)
                ocr_text = ocr_result.text.strip()

                if not ocr_text:
                    GLib.idle_add(lambda: popup.show_error("Tidak ada teks yang terdeteksi pada area gambar."))
                    return

                max_chars = self.app.settings.max_chars
                if len(ocr_text) > max_chars:
                    ocr_text = ocr_text[:max_chars]

                # Salin hasil OCR ke clipboard
                self.app.text_capturer.send_to_clipboard(ocr_text)

                def _show_copied() -> None:
                    popup.set_source_text(ocr_text)
                    popup.show_error("✓ Teks OCR berhasil disalin ke clipboard.")

                GLib.idle_add(_show_copied)
            except Exception as exc:
                logger.error(f"Kegagalan alur OCR murni: {exc}")
                GLib.idle_add(lambda: popup.show_error(f"Galat OCR: {exc}"))

        import threading
        threading.Thread(target=_bg_pure_ocr, daemon=True).start()

    def request_ocr(self) -> None:
        """Alur tangkapan layar dan OCR terjemahan (R6.1, R6.2, R6.3)."""
        overlay = self.app.get_region_overlay()
        overlay.open(
            on_selected=self._on_ocr_region_selected,
            on_cancelled=lambda: logger.info("Seleksi OCR dibatalkan pengguna."),
        )

    def _on_ocr_region_selected(self, rect: Rect) -> None:
        """Dipanggil setelah pengguna selesai memilih area persegi pada overlay."""
        # 1. Tampilkan popup dengan status memuat
        popup = self.app.get_popup_window()
        popup.set_source_text("Membaca teks dari gambar...")
        popup.show_loading()
        popup.present_at_cursor(0, 0)

        # 2. Jalankan penangkapan layar dan OCR di background thread
        def _bg_ocr() -> None:
            try:
                # Tangkap layar via ScreenshotPortal
                raw_png = self.app.screenshot_portal.capture_fullscreen()
                # Potong citra sesuai rect
                cropped_png = crop_image_region(raw_png, rect)

                # Jalankan OCR melalui worker
                ocr_result = self.app.ocr_client.recognize(cropped_png)
                ocr_text = ocr_result.text.strip()

                if not ocr_text:
                    GLib.idle_add(lambda: popup.show_error("Tidak ada teks yang terdeteksi pada area gambar."))
                    return

                # Potong teks bila melebihi max_chars
                max_chars = self.app.settings.max_chars
                if len(ocr_text) > max_chars:
                    ocr_text = ocr_text[:max_chars]

                # Update popup dan jalankan terjemahan
                def _update_and_translate() -> None:
                    popup.set_source_text(ocr_text)
                    self._execute_translation(ocr_text)

                GLib.idle_add(_update_and_translate)
            except Exception as exc:
                logger.error(f"Kegagalan alur OCR: {exc}")
                GLib.idle_add(lambda: popup.show_error(f"Galat OCR: {exc}"))

        import threading
        threading.Thread(target=_bg_ocr, daemon=True).start()

    def _execute_translation(self, text: str) -> None:
        """Kirim permintaan penerjemahan ke RequestScheduler."""
        popup = self.app.get_popup_window()
        popup.show_loading()

        settings = self.app.settings
        provider = self.app.provider_registry.get(settings.provider)
        if provider is None:
            popup.show_error(f"Provider '{settings.provider}' tidak ditemukan.")
            return

        cred = self.app.credential_store.get(provider.id)
        if provider.requires_credential() and not cred:
            popup.show_error(
                f"Kredensial untuk '{provider.display_name}' belum dikonfigurasi. "
                "Atur API key pada jendela Pengaturan."
            )
            return

        # Atur target bahasa (tangani auto dan fallback jika source sama dengan target - R4.4)
        target_lang = settings.target_language
        req = TranslationRequest(
            text=text,
            source_lang=None,
            target_lang=target_lang,
        )

        final_target_lang = target_lang

        def _on_result(res: Any) -> None:
            nonlocal final_target_lang
            # Jika bahasa sumber sama dengan target, terjemahkan ke fallback language (R4.4)
            if res.detected_source_lang == target_lang and settings.fallback_language != target_lang:
                final_target_lang = settings.fallback_language
                fallback_req = TranslationRequest(
                    text=text,
                    source_lang=res.detected_source_lang,
                    target_lang=settings.fallback_language,
                )
                self.app.scheduler.submit(
                    fallback_req,
                    provider,
                    cred,
                    on_result=_on_final_result,
                    on_error=_on_error,
                    timeout_s=settings.request_timeout_s,
                )
            else:
                _on_final_result(res)

        def _on_final_result(res: Any) -> None:
            popup.set_languages_display(res.detected_source_lang, final_target_lang)
            popup.show_result(res)

        def _on_error(err: Any) -> None:
            popup.show_error(err.message)

        self.app.scheduler.submit(
            req,
            provider,
            cred,
            on_result=_on_result,
            on_error=_on_error,
            timeout_s=settings.request_timeout_s,
        )


class PinuxApp(Adw.Application):
    """Aplikasi utama Pinux GTK4/libadwaita."""

    def __init__(
        self,
        config_store: ConfigStore | None = None,
        credential_store: CredentialStore | None = None,
        provider_registry: ProviderRegistry | None = None,
        scheduler: RequestScheduler | None = None,
        text_capturer: TextCapturer | None = None,
        screenshot_portal: ScreenshotPortal | None = None,
        ocr_client: OcrWorkerClient | None = None,
        shortcut_manager: ShortcutManager | None = None,
        tray_item: TrayItem | None = None,
    ) -> None:
        super().__init__(
            application_id="org.pinux.Pinux",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )

        self.config_store = config_store or ConfigStore()
        self.credential_store = credential_store or CredentialStore()
        self.provider_registry = provider_registry or ProviderRegistry(self.credential_store)
        self.scheduler = scheduler or RequestScheduler()
        # Backend clipboard GDK baru dapat dibuat setelah display tersedia
        # (lihat do_startup), sehingga TextCapturer awal hanya penampung.
        self._owns_text_capturer = text_capturer is None
        self.text_capturer = text_capturer or TextCapturer()
        self.screenshot_portal = screenshot_portal or ScreenshotPortal()
        self.ocr_client = ocr_client or OcrWorkerClient()

        self.settings: Settings = self.config_store.load()
        # Muat provider pihak ketiga dari berkas pengaturan
        self.provider_registry.load_from_entries(self.settings.providers)
        self.provider_registry.load_from_entry_points()

        self.trigger_router = TriggerRouter(self)

        self.shortcut_manager = shortcut_manager or ShortcutManager(
            on_activated=self.trigger_router.on_shortcut_activated
        )

        self.tray_item = tray_item or TrayItem(
            on_translate_selection=self.trigger_router.request_translate,
            on_ocr_translate=self.trigger_router.request_ocr,
            on_input_translate=self.trigger_router.request_input_translate,
            on_show_popup=self.trigger_router.show_popup_window,
            on_ocr_pure=self.trigger_router.request_ocr_pure,
            on_settings=self.show_settings_window,
            on_quit=self.quit_app,
        )

        self._popup_window: PopupWindow | None = None
        self._region_overlay: RegionOverlay | None = None
        self._settings_window: SettingsWindow | None = None

        self._setup_options()

    def _setup_options(self) -> None:
        """Tambahkan opsi baris perintah GApplication."""
        self.add_main_option(
            "trigger",
            ord("t"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Memicu terjemahan atas teks clipboard pada instans aktif",
            None,
        )
        self.add_main_option(
            "pick-region",
            ord("r"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Memicu pemilihan area layar & OCR pada instans aktif",
            None,
        )
        self.add_main_option(
            "settings",
            ord("s"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Membuka jendela pengaturan",
            None,
        )

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)

        if self._owns_text_capturer:
            self._init_clipboard_backend()

        # Daftarkan aksi aplikasi Gio
        self._add_action("trigger-translate", lambda *_: self.trigger_router.request_translate())
        self._add_action("trigger-ocr", lambda *_: self.trigger_router.request_ocr())
        self._add_action("settings", lambda *_: self.show_settings_window())
        self._add_action("quit", lambda *_: self.quit_app())

        # Mulai ShortcutManager
        self.shortcut_manager.start()

        # Tampilkan TrayItem (Properti 8: jika gagal tidak mematikan aplikasi)
        try:
            self.tray_item.show()
        except Exception as exc:
            logger.warning(f"TrayItem gagal ditampilkan: {exc}. Menampilkan jendela pengaturan (R8.4).")
            GLib.idle_add(self.show_settings_window)

        # Pasang watch pada berkas konfigurasi (R9.4)
        self.config_store.watch(self._on_config_changed)

    def _init_clipboard_backend(self) -> None:
        """Pasang backend clipboard GDK setelah Gtk/Adw diinisialisasi."""
        from pinux.capture.capturer import GdkClipboardBackend

        try:
            self.text_capturer = TextCapturer(
                backend=GdkClipboardBackend(),
                session_type=self.text_capturer.session_type,
            )
        except Exception as exc:
            logger.error(f"Backend clipboard GDK gagal dibuat: {exc}")

    def _add_action(self, name: str, callback: Callable[[Gio.SimpleAction, Any], None]) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)

    def do_activate(self) -> None:
        """Dipanggil saat instans utama berjalan tanpa opsi."""
        # Menjaga proses tetap hidup di latar belakang
        self.hold()

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        options = command_line.get_options_dict()

        if options.contains("trigger"):
            self.activate_action("trigger-translate", None)
        elif options.contains("pick-region"):
            self.activate_action("trigger-ocr", None)
        elif options.contains("settings"):
            self.activate_action("settings", None)
        else:
            self.activate()

        return 0

    def do_shutdown(self) -> None:
        """Pelepasan resource saat aplikasi berhenti (R8.3)."""
        logger.info("Menghentikan Pinux...")
        self.shortcut_manager.stop()
        self.tray_item.hide()
        self.scheduler.shutdown(wait=False)
        self.ocr_client.shutdown()
        self.config_store.close()
        Adw.Application.do_shutdown(self)

    def _on_config_changed(self, new_settings: Settings) -> None:
        """Diterapkan otomatis saat file pinux.toml berubah (R9.4)."""
        self.settings = new_settings
        if self._popup_window is not None:
            self._popup_window.pinned = new_settings.popup.pin_default

    def get_popup_window(self) -> PopupWindow:
        """Dapatkan atau buat PopupWindow tunggal (R1.5)."""
        if self._popup_window is None:
            self._popup_window = PopupWindow(
                on_text_changed=lambda t: self.trigger_router._execute_translation(t),
                on_swap_languages=lambda: self._on_swap_languages(),
                on_copy_result=lambda res: self.text_capturer.send_to_clipboard(res),
                on_trigger_ocr=lambda: self.trigger_router.request_ocr(),
                pin_default=self.settings.popup.pin_default,
                width=self.settings.popup.width,
            )
        return self._popup_window

    def _on_swap_languages(self) -> None:
        pass

    def get_region_overlay(self) -> RegionOverlay:
        """Dapatkan atau buat RegionOverlay tunggal."""
        if self._region_overlay is None:
            self._region_overlay = RegionOverlay()
        return self._region_overlay

    def show_settings_window(self) -> None:
        """Tampilkan SettingsWindow."""
        if self._settings_window is None:
            self._settings_window = SettingsWindow(
                config_store=self.config_store,
                credential_store=self.credential_store,
                provider_registry=self.provider_registry,
                shortcut_manager=self.shortcut_manager,
                ocr_client=self.ocr_client,
                session_type=self.text_capturer.session_type,
                on_settings_changed=self._on_config_changed,
            )
        self._settings_window.present()

    def quit_app(self) -> None:
        """Hentikan aplikasi."""
        self.release()
        self.quit()
