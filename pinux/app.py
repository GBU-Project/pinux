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

from pinux import APP_ID, __version__
from pinux.capture.capturer import TextCapturer, clean_text
from pinux.config import Settings
from pinux.configstore import ConfigStore
from pinux.credentials import CredentialStore
from pinux.ocr.imagefile import ImageFileError, load_image_as_png
from pinux.ocr.pipeline import recognize_text_or_qr
from pinux.ocr.client import OcrWorkerClient
from pinux.portal.screenshot import ScreenshotPortal
from pinux.portal.shortcuts import ShortcutManager, ShortcutSpec, specs_from_settings
from pinux.scheduler import RequestScheduler
from pinux.translate.base import TranslationRequest
from pinux.tts import TtsEngine
from pinux.translate.registry import ProviderRegistry
from pinux.tray import TrayItem
from pinux.ui.popup import PopupWindow
from pinux.ui.region import RegionOverlay
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
        popup.focus_input()

    def show_popup_window(self) -> None:
        """Tampilkan jendela popup yang sedang ada."""
        popup = self.app.get_popup_window()
        popup.present_at_cursor(0, 0)

    def _open_region_picker(self, on_image: Callable[[bytes], None], label: str) -> None:
        """Ambil tangkapan layar, tampilkan sebagai bingkai beku, lalu pilih area.

        ``on_image`` menerima PNG hasil potongan (sudah dalam piksel citra).
        """
        self.app.hide_popup_for_capture()
        overlay = self.app.get_region_overlay()

        def _on_error(exc: Exception) -> None:
            popup = self.app.get_popup_window()
            popup.set_source_text("")
            popup.present_at_cursor(0, 0)
            popup.show_error(f"Tangkapan layar gagal: {exc}")

        overlay.open(
            on_selected=lambda rect: logger.debug("Rect tanpa bingkai beku diabaikan: %s", rect),
            on_cancelled=lambda: logger.info("Seleksi %s dibatalkan pengguna.", label),
            screenshot_provider=self.app.screenshot_portal.capture_fullscreen,
            on_image=on_image,
            on_error=_on_error,
        )

    def _run_ocr_in_background(
        self,
        cropped_png: bytes,
        on_text: Callable[[str], None],
        *,
        append_mode: bool | None = None,
    ) -> None:
        """Jalankan OCR pada thread latar; ``on_text`` dipanggil di thread utama."""
        popup = self.app.get_popup_window()
        # Jika mode kontinu aktif (atau dipaksa via append_mode), pertahankan teks yang ada
        is_continuous = (
            append_mode
            if append_mode is not None
            else (popup.continuous_ocr or self.app.settings.ocr.continuous_ocr)
        )
        if not is_continuous or not popup.source_text.strip():
            popup.set_source_text("Membaca teks dari gambar...")
        popup.show_loading()
        popup.present_at_cursor(0, 0)

        def _bg() -> None:
            try:
                recognized = recognize_text_or_qr(self.app.ocr_client, cropped_png)
                if recognized is None:
                    GLib.idle_add(
                        lambda: popup.show_error(
                            "Tidak ada teks atau kode QR yang terdeteksi pada gambar."
                        )
                    )
                    return
                ocr_text = recognized.text[: self.app.settings.max_chars]
                GLib.idle_add(lambda: on_text(ocr_text))
            except Exception as exc:
                logger.error(f"Kegagalan alur OCR: {exc}")
                message = f"Galat OCR: {exc}"
                GLib.idle_add(lambda: popup.show_error(message))

        import threading
        threading.Thread(target=_bg, daemon=True).start()

    def request_ocr_file(
        self,
        path: str | None = None,
        *,
        copy_only: bool = False,
        append: bool | None = None,
    ) -> None:
        """OCR dari berkas gambar; tanpa ``path`` tampilkan dialog pemilih berkas."""
        if path is None:
            self._choose_image_file(copy_only, append=append)
        else:
            self._ocr_from_file(path, copy_only, append=append)

    def _choose_image_file(self, copy_only: bool, *, append: bool | None = None) -> None:
        if not hasattr(Gtk, "FileDialog"):  # GTK < 4.10
            self.app.get_popup_window().show_error(
                "Dialog berkas memerlukan GTK 4.10+. Gunakan: pinux --ocr-file BERKAS"
            )
            return
        dialog = Gtk.FileDialog()
        dialog.set_title("Pilih gambar untuk OCR")
        image_filter = Gtk.FileFilter()
        image_filter.set_name("Gambar")
        image_filter.add_mime_type("image/*")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(image_filter)
        dialog.set_filters(filters)

        def _done(dlg: Any, result: Any) -> None:
            try:
                picked = dlg.open_finish(result)
            except GLib.Error:
                return  # dibatalkan pengguna
            if picked is not None and picked.get_path():
                self._ocr_from_file(picked.get_path(), copy_only, append=append)

        dialog.open(self.app._popup_window, None, _done)

    def _ocr_from_file(
        self,
        path: str,
        copy_only: bool,
        *,
        append: bool | None = None,
    ) -> None:
        popup = self.app.get_popup_window()
        is_continuous = (
            append
            if append is not None
            else (popup.continuous_ocr or self.app.settings.ocr.continuous_ocr)
        )
        if not is_continuous or not popup.source_text.strip():
            popup.set_source_text("Memuat gambar...")
        popup.show_loading()
        popup.present_at_cursor(0, 0)
        handler = (
            (lambda png: self._on_ocr_pure_image(png, append=append))
            if copy_only
            else (lambda png: self._on_ocr_image(png, append=append))
        )

        def _load() -> None:
            try:
                png = load_image_as_png(path)
            except ImageFileError as exc:
                message = str(exc)
                GLib.idle_add(lambda: popup.show_error(message))
                return
            GLib.idle_add(lambda: handler(png))

        import threading
        threading.Thread(target=_load, daemon=True).start()

    def request_ocr_pure(self, *, append: bool | None = None) -> None:
        """Pilih area layar lalu salin teks OCR ke clipboard tanpa menerjemahkan."""
        self._open_region_picker(
            lambda cropped: self._on_ocr_pure_image(cropped, append=append),
            "OCR murni",
        )

    def _on_ocr_pure_image(self, cropped_png: bytes, *, append: bool | None = None) -> None:
        popup = self.app.get_popup_window()
        is_continuous = (
            append
            if append is not None
            else (popup.continuous_ocr or self.app.settings.ocr.continuous_ocr)
        )

        def _copied(text: str) -> None:
            if is_continuous and popup.source_text.strip() and popup.source_text != "Membaca teks dari gambar...":
                full_text = popup.append_source_text(text)
            else:
                full_text = text
                popup.set_source_text(text)
            self.app.text_capturer.send_to_clipboard(full_text)
            popup.show_error("✓ Teks OCR berhasil disalin ke clipboard.")

        self._run_ocr_in_background(cropped_png, _copied, append_mode=append)

    def request_ocr(self, *, append: bool | None = None) -> None:
        """Pilih area layar, OCR, lalu terjemahkan (R6.1, R6.2, R6.3)."""
        self._open_region_picker(
            lambda cropped: self._on_ocr_image(cropped, append=append),
            "OCR",
        )

    def _on_ocr_image(self, cropped_png: bytes, *, append: bool | None = None) -> None:
        popup = self.app.get_popup_window()
        is_continuous = (
            append
            if append is not None
            else (popup.continuous_ocr or self.app.settings.ocr.continuous_ocr)
        )

        def _translate(text: str) -> None:
            if is_continuous and popup.source_text.strip() and popup.source_text != "Membaca teks dari gambar...":
                full_text = popup.append_source_text(text)
            else:
                full_text = text
                popup.set_source_text(text)
            self._execute_translation(full_text)

        self._run_ocr_in_background(cropped_png, _translate, append_mode=append)


    def _execute_translation(
        self,
        text: str,
        source_lang: str | None = None,
        target_lang: str | None = None,
    ) -> None:
        """Kirim permintaan penerjemahan ke RequestScheduler."""
        popup = self.app.get_popup_window()
        popup.show_loading()

        settings = self.app.settings
        tp = settings.text_processing
        cleaned_text = clean_text(
            text,
            unwrap_lines=tp.unwrap_lines,
            remove_hyphens=tp.remove_hyphens,
            remove_comments=tp.remove_comments,
        ) if text else ""

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

        # Provider cadangan dicoba otomatis bila provider utama gagal; layanan
        # tambahan (mode bandingkan) berjalan paralel dan hasilnya ditampilkan di popup.
        active_provider = (
            self.app.provider_registry.build_active(
                provider.id,
                settings.fallback_providers,
                settings.compare_providers,
                extra_timeout_s=settings.request_timeout_s,
            )
            or provider
        )

        # Bahasa yang dipilih pengguna di dropdown popup berlaku untuk setiap terjemahan.
        if source_lang is None:
            source_lang = popup.source_lang
        # Atur target bahasa (tangani auto dan fallback jika source sama dengan target - R4.4)
        if target_lang is None:
            target_lang = settings.target_language
        req = TranslationRequest(
            text=cleaned_text or text,
            source_lang=source_lang,
            target_lang=target_lang,
        )

        final_target_lang = target_lang

        def _on_result(res: Any) -> None:
            nonlocal final_target_lang
            # Jika bahasa sumber sama dengan target, terjemahkan ke fallback language (R4.4)
            if res.detected_source_lang == target_lang and settings.fallback_language != target_lang:
                final_target_lang = settings.fallback_language
                fallback_req = TranslationRequest(
                    text=cleaned_text or text,
                    source_lang=res.detected_source_lang,
                    target_lang=settings.fallback_language,
                )
                self.app.scheduler.submit(
                    fallback_req,
                    active_provider,
                    cred,
                    on_result=_on_final_result,
                    on_error=_on_error,
                    timeout_s=settings.request_timeout_s,
                )
            else:
                _on_final_result(res)

        def _on_final_result(res: Any) -> None:
            popup.set_languages_display(
                popup.source_lang or "auto", final_target_lang
            )
            popup.show_detected_language(res.detected_source_lang)
            popup.show_result(res)
            # Auto-copy hasil terjemahan jika diaktifkan di pengaturan ala Bob
            if settings.text_processing.auto_copy_result and res.text:
                self.app.text_capturer.send_to_clipboard(res.text)

        def _on_error(err: Any) -> None:
            popup.show_error(err.message)

        self.app.scheduler.submit(
            req,
            active_provider,
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
            application_id=APP_ID,
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
        self.tts = TtsEngine()

        self.settings: Settings = self.config_store.load()
        # Muat provider pihak ketiga dari berkas pengaturan
        self.provider_registry.load_from_entries(self.settings.providers)
        self.provider_registry.apply_llm_settings(
            self.settings.llm.endpoint_url, self.settings.llm.model
        )
        self.provider_registry.apply_libretranslate_settings(
            self.settings.libretranslate.endpoint_url
        )
        self.provider_registry.load_from_entry_points()

        self.trigger_router = TriggerRouter(self)

        self.shortcut_manager = shortcut_manager or ShortcutManager(
            specs=specs_from_settings(self.settings.shortcuts) or None,
            on_activated=self.trigger_router.on_shortcut_activated,
        )

        self.tray_item = tray_item or TrayItem(
            on_translate_selection=self.trigger_router.request_translate,
            on_ocr_translate=self.trigger_router.request_ocr,
            on_input_translate=self.trigger_router.request_input_translate,
            on_show_popup=self.trigger_router.show_popup_window,
            on_ocr_pure=self.trigger_router.request_ocr_pure,
            on_settings=self.show_settings_window,
            on_quit=self.quit_app,
            version_string=f"Pinux v{__version__}",
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
            "input",
            ord("i"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Membuka jendela terjemah input (ketik teks lalu Enter)",
            None,
        )
        self.add_main_option(
            "ocr-copy",
            ord("c"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Pilih area layar lalu salin teks OCR ke clipboard tanpa menerjemahkan",
            None,
        )
        self.add_main_option(
            "ocr-file",
            0,
            GLib.OptionFlags.NONE,
            GLib.OptionArg.FILENAME,
            "OCR dari berkas gambar (gabungkan dengan --ocr-copy untuk hanya menyalin)",
            "BERKAS",
        )
        self.add_main_option(
            "ocr-append",
            0,
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Picu OCR dan tambahkan hasilnya ke teks yang ada di popup (mode kontinu)",
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

        # Set default window icon ke icon 'pinux'
        try:
            Gtk.Window.set_default_icon_name("pinux")
        except Exception:
            pass

        # Daftarkan aksi aplikasi Gio
        self._add_action("trigger-translate", lambda *_: self.trigger_router.request_translate())
        self._add_action("trigger-ocr", lambda *_: self.trigger_router.request_ocr())
        self._add_action("trigger-ocr-append", lambda *_: self.trigger_router.request_ocr(append=True))
        self._add_action("trigger-input", lambda *_: self.trigger_router.request_input_translate())
        self._add_action("trigger-ocr-copy", lambda *_: self.trigger_router.request_ocr_pure())
        self._add_action("settings", lambda *_: self.show_settings_window())
        self._add_action("quit", lambda *_: self.quit_app())


        # Mulai ShortcutManager setelah startup selesai: pengikatan portal dapat
        # menampilkan dialog persetujuan dan menunggu hingga puluhan detik.
        GLib.idle_add(self._start_shortcuts)

        # Tampilkan TrayItem (Properti 8: jika gagal tidak mematikan aplikasi)
        try:
            self.tray_item.show()
        except Exception as exc:
            logger.warning(f"TrayItem gagal ditampilkan: {exc}. Menampilkan jendela pengaturan (R8.4).")
            GLib.idle_add(self.show_settings_window)

        # Pasang watch pada berkas konfigurasi (R9.4)
        self.config_store.watch(self._on_config_changed)

        # Menjaga proses background/daemon tetap hidup walau tanpa jendela menetap
        self.hold()


    def _start_shortcuts(self) -> bool:
        try:
            self.shortcut_manager.start()
        except Exception as exc:
            logger.warning(f"ShortcutManager gagal dimulai: {exc}")
        return False  # sekali jalan

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
        self.show_settings_window()


    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        options = command_line.get_options_dict()

        ocr_file = options.lookup_value("ocr-file", None)
        if ocr_file is not None:
            import os

            raw = ocr_file.get_bytestring().decode(errors="replace")
            cwd = command_line.get_cwd() or os.getcwd()
            self.trigger_router.request_ocr_file(
                os.path.join(cwd, os.path.expanduser(raw)),
                copy_only=options.contains("ocr-copy"),
                append=options.contains("ocr-append") or None,
            )
        elif options.contains("trigger"):
            self.activate_action("trigger-translate", None)
        elif options.contains("ocr-append"):
            self.activate_action("trigger-ocr-append", None)
        elif options.contains("pick-region"):
            self.activate_action("trigger-ocr", None)
        elif options.contains("input"):
            self.activate_action("trigger-input", None)

        elif options.contains("ocr-copy"):
            self.activate_action("trigger-ocr-copy", None)
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
        self.provider_registry.apply_llm_settings(
            new_settings.llm.endpoint_url, new_settings.llm.model
        )
        self.provider_registry.apply_libretranslate_settings(
            new_settings.libretranslate.endpoint_url
        )
        if self._popup_window is not None:
            self._popup_window.pinned = new_settings.popup.pin_default

    def get_popup_window(self) -> PopupWindow:
        """Dapatkan atau buat PopupWindow tunggal (R1.5)."""
        if self._popup_window is None:
            self._popup_window = PopupWindow(
                on_text_changed=lambda t: self.trigger_router._execute_translation(t),
                on_swap_languages=lambda: self._on_swap_languages(),
                on_language_selected=lambda s, t: self._on_language_changed(s, t),
                on_retry=lambda: self._on_retry_translation(),
                on_copy_result=lambda res: self.text_capturer.send_to_clipboard(res),
                on_trigger_ocr=lambda: self.trigger_router.request_ocr(),
                on_ocr_file=lambda: self.trigger_router.request_ocr_file(),
                on_speak=lambda text, lang: self.tts.speak(text, lang),
                tts_available=self.tts.available,
                pin_default=self.settings.popup.pin_default,
                continuous_ocr_default=self.settings.ocr.continuous_ocr,
                on_continuous_ocr_toggled=lambda val: self._on_continuous_ocr_toggled(val),
                width=self.settings.popup.width,
            )
            # Setel bahasa awal sesuai pengaturan
            self._popup_window.set_languages_display("auto", self.settings.target_language)
        return self._popup_window

    def _on_continuous_ocr_toggled(self, active: bool) -> None:
        self.settings.ocr.continuous_ocr = active


    def _on_retry_translation(self) -> None:
        """Picu penerjemahan ulang (Ctrl+R) menggunakan teks yang ada di popup."""
        if self._popup_window is None:
            return
        text = self._popup_window.source_text.strip()
        if text:
            self.trigger_router._execute_translation(
                text,
                source_lang=self._popup_window._current_source_lang,
                target_lang=self._popup_window._current_target_lang,
            )

    def _on_language_changed(self, source_lang: str | None, target_lang: str) -> None:
        """Picu penerjemahan ulang jika pengguna mengubah bahasa dari dropdown popup."""
        self.settings.target_language = target_lang
        try:
            self.config_store.save(self.settings)
        except Exception as exc:
            logger.warning(f"Gagal menyimpan bahasa tujuan: {exc}")
        if self._popup_window is None:
            return
        text = self._popup_window.source_text.strip()
        if text:
            self.trigger_router._execute_translation(
                text,
                source_lang=source_lang,
                target_lang=target_lang,
            )

    def _on_swap_languages(self) -> None:
        """Tukar bahasa sumber & target dan terjemahkan kembali hasil terjemahan jika ada."""
        if self._popup_window is None:
            return

        result_text = self._popup_window.result_text.strip()
        source_text = self._popup_window.source_text.strip()

        # Tukar target_language dan fallback_language pada settings runtime
        curr_target = self.settings.target_language
        curr_fallback = self.settings.fallback_language
        self.settings.target_language = curr_fallback
        self.settings.fallback_language = curr_target

        if result_text:
            # Jika ada hasil terjemahan, jadikan hasil sebagai teks baru di entry
            self._popup_window.set_source_text(result_text)
            self.trigger_router._execute_translation(
                result_text,
                source_lang=curr_target,
                target_lang=curr_fallback,
            )
        elif source_text:
            self.trigger_router._execute_translation(
                source_text,
                target_lang=self.settings.target_language,
            )


    def hide_popup_for_capture(self) -> None:
        """Sembunyikan popup agar tidak ikut tertangkap pada screenshot."""
        popup = self._popup_window
        if popup is not None and popup.is_visible():
            popup.hide()

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
        self.tts.stop()
        self.release()
        self.quit()
