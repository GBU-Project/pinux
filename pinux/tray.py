"""Implementasi ikon tray menggunakan StatusNotifierItem dan com.canonical.dbusmenu.

Dijalankan langsung di atas D-Bus tanpa dependensi AppIndicator:
- Mendaftarkan nama unik ``org.kde.StatusNotifierItem-<pid>-1`` dan path ``/StatusNotifierItem``
- Memanggil ``org.kde.StatusNotifierWatcher.RegisterStatusNotifierItem``
- Menyediakan objek menu ``com.canonical.dbusmenu`` di path ``/MenuBar`` dengan entri:
  1. Pengaturan
  2. OCR
  3. Keluar
- Properti 8: Kegagalan menampilkan tray tidak fatal dan tidak membatalkan Global_Shortcut (R8.4).

Perujuk: R8.2, R8.4, R8.5 pada requirements.md, serta design.md.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any, Final

import dbus
import dbus.service

__all__ = ["TrayItem"]

logger = logging.getLogger("pinux.tray")

SNI_WATCHER_BUS_NAME: Final[str] = "org.kde.StatusNotifierWatcher"
SNI_WATCHER_OBJECT_PATH: Final[str] = "/StatusNotifierWatcher"
SNI_INTERFACE: Final[str] = "org.kde.StatusNotifierItem"
DBUSMENU_INTERFACE: Final[str] = "com.canonical.dbusmenu"


class DbusMenuService(dbus.service.Object):
    """Implementasi com.canonical.dbusmenu untuk menu tray Pinux bergaya Bob."""

    def __init__(
        self,
        bus: dbus.Bus,
        object_path: str,
        on_translate_selection: Callable[[], None] | None = None,
        on_ocr_translate: Callable[[], None] | None = None,
        on_input_translate: Callable[[], None] | None = None,
        on_show_popup: Callable[[], None] | None = None,
        on_ocr_pure: Callable[[], None] | None = None,
        on_settings: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
        version_string: str = "Pinux v0.1.0",
    ) -> None:
        super().__init__(bus, object_path)
        self._on_translate_selection = on_translate_selection
        self._on_ocr_translate = on_ocr_translate
        self._on_input_translate = on_input_translate
        self._on_show_popup = on_show_popup
        self._on_ocr_pure = on_ocr_pure
        self._on_settings = on_settings
        self._on_quit = on_quit
        self._version_string = version_string

    @dbus.service.method(DBUSMENU_INTERFACE, in_signature="ii", out_signature="u(ia{sv}av)")
    def GetLayout(self, parent_id: int, recursion_depth: int) -> tuple[int, Any]:
        """Kembalikan struktur menu bertingkat ala Bob:
        - Terjemahkan Seleksi / Clipboard (Ctrl+Alt+T)
        - Tangkapan Layar & Terjemah (OCR) (Ctrl+Alt+O)
        - Input Terjemahan Manual
        - Tampilkan Jendela Terjemahan
        --- (separator)
        - Tangkapan Layar & Salin Teks OCR
        --- (separator)
        - Pengaturan
        --- (separator)
        - Pinux v... (disabled/info)
        - Keluar
        """
        empty_children = dbus.Array([], signature="v")
        items = [
            (1, {"label": "Terjemahkan Seleksi / Clipboard", "type": "standard", "enabled": True}, empty_children),
            (2, {"label": "Tangkapan Layar & Terjemah (OCR)", "type": "standard", "enabled": True}, empty_children),
            (3, {"label": "Input Terjemahan Manual", "type": "standard", "enabled": True}, empty_children),
            (4, {"label": "Tampilkan Jendela Terjemahan", "type": "standard", "enabled": True}, empty_children),
            (5, {"type": "separator"}, empty_children),
            (6, {"label": "Tangkapan Layar & Salin Teks OCR", "type": "standard", "enabled": True}, empty_children),
            (7, {"type": "separator"}, empty_children),
            (8, {"label": "Pengaturan...", "type": "standard", "enabled": True}, empty_children),
            (9, {"type": "separator"}, empty_children),
            (10, {"label": self._version_string, "type": "standard", "enabled": False}, empty_children),
            (11, {"label": "Keluar", "type": "standard", "enabled": True}, empty_children),
        ]
        root = (0, {"children-display": "submenu"}, items)
        return (1, root)

    @dbus.service.method(DBUSMENU_INTERFACE, in_signature="isvu", out_signature="")
    def Event(self, item_id: int, event_id: str, data: Any, timestamp: int) -> None:
        """Tangani klik pada item menu."""
        if event_id == "clicked":
            if item_id == 1 and self._on_translate_selection is not None:
                self._on_translate_selection()
            elif item_id == 2 and self._on_ocr_translate is not None:
                self._on_ocr_translate()
            elif item_id == 3 and self._on_input_translate is not None:
                self._on_input_translate()
            elif item_id == 4 and self._on_show_popup is not None:
                self._on_show_popup()
            elif item_id == 6 and self._on_ocr_pure is not None:
                self._on_ocr_pure()
            elif item_id == 8 and self._on_settings is not None:
                self._on_settings()
            elif item_id == 11 and self._on_quit is not None:
                self._on_quit()


class StatusNotifierItemService(dbus.service.Object):
    """Layanan D-Bus untuk StatusNotifierItem."""

    def __init__(self, bus: dbus.Bus, object_path: str, menu_path: str) -> None:
        super().__init__(bus, object_path)
        self._menu_path = menu_path

    @dbus.service.method("org.freedesktop.DBus.Properties", in_signature="ss", out_signature="v")
    def Get(self, interface_name: str, property_name: str) -> Any:
        props = self.GetAll(interface_name)
        if property_name in props:
            return props[property_name]
        raise dbus.exceptions.DBusException(
            f"Properti {property_name} tidak ditemukan pada {interface_name}",
            name="org.freedesktop.DBus.Error.InvalidArgs",
        )

    @dbus.service.method("org.freedesktop.DBus.Properties", in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface_name: str) -> dict[str, Any]:
        if interface_name == SNI_INTERFACE:
            return {
                "Category": dbus.String("ApplicationStatus"),
                "Id": dbus.String("pinux"),
                "Title": dbus.String("Pinux"),
                "Status": dbus.String("Active"),
                "IconName": dbus.String("accessories-dictionary-symbolic"),
                "IconThemePath": dbus.String(""),
                "ItemIsMenu": dbus.Boolean(False),
                "Menu": dbus.ObjectPath(self._menu_path),
                "WindowId": dbus.Int32(0),
                "ToolTip": dbus.Struct(
                    (
                        dbus.String("accessories-dictionary-symbolic"),
                        dbus.Array([], signature="(iiay)"),
                        dbus.String("Pinux Translator"),
                        dbus.String("Klik kanan untuk menu pengaturan / OCR"),
                    ),
                    signature=None,
                ),
            }
        return {}

    @dbus.service.method(SNI_INTERFACE, in_signature="ii", out_signature="")
    def ContextMenu(self, x: int, y: int) -> None:
        pass

    @dbus.service.method(SNI_INTERFACE, in_signature="ii", out_signature="")
    def Activate(self, x: int, y: int) -> None:
        pass


class TrayItem:
    """Ikon indikator baki desktop (StatusNotifierItem)."""

    def __init__(
        self,
        bus: dbus.Bus | None = None,
        on_translate_selection: Callable[[], None] | None = None,
        on_ocr_translate: Callable[[], None] | None = None,
        on_input_translate: Callable[[], None] | None = None,
        on_show_popup: Callable[[], None] | None = None,
        on_ocr_pure: Callable[[], None] | None = None,
        on_settings: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
        on_ocr: Callable[[], None] | None = None,  # Backward compatibility
        version_string: str = "Pinux v0.1.0",
    ) -> None:
        self._bus = bus
        self._on_translate_selection = on_translate_selection
        self._on_ocr_translate = on_ocr_translate or on_ocr
        self._on_input_translate = on_input_translate
        self._on_show_popup = on_show_popup
        self._on_ocr_pure = on_ocr_pure
        self._on_settings = on_settings
        self._on_quit = on_quit
        self._version_string = version_string

        self._sni_service: StatusNotifierItemService | None = None
        self._menu_service: DbusMenuService | None = None
        self._bus_name: dbus.service.BusName | None = None
        self._shown: bool = False

    def _get_bus(self) -> dbus.Bus:
        if self._bus is None:
            self._bus = dbus.SessionBus()
        return self._bus

    def is_watcher_available(self) -> bool:
        """Periksa apakah StatusNotifierWatcher tersedia pada D-Bus."""
        try:
            bus = self._get_bus()
            return bus.name_has_owner(SNI_WATCHER_BUS_NAME)
        except Exception:
            return False

    def show(self) -> None:
        """Daftarkan StatusNotifierItem ke StatusNotifierWatcher.

        Properti 8 / R8.4: Jika watcher tidak tersedia, lemparkan RuntimeError
        sehingga pemanggil dapat menampilkan SettingsWindow sebagai fallback.
        """
        if not self.is_watcher_available():
            raise RuntimeError(
                f"Layanan baki '{SNI_WATCHER_BUS_NAME}' tidak tersedia pada bus sesi."
            )

        bus = self._get_bus()
        pid = os.getpid()
        service_name = f"org.kde.StatusNotifierItem-{pid}-1"

        try:
            self._bus_name = dbus.service.BusName(service_name, bus)
            menu_path = "/MenuBar"
            sni_path = "/StatusNotifierItem"

            self._menu_service = DbusMenuService(
                bus=bus,
                object_path=menu_path,
                on_translate_selection=self._on_translate_selection,
                on_ocr_translate=self._on_ocr_translate,
                on_input_translate=self._on_input_translate,
                on_show_popup=self._on_show_popup,
                on_ocr_pure=self._on_ocr_pure,
                on_settings=self._on_settings,
                on_quit=self._on_quit,
                version_string=self._version_string,
            )
            self._sni_service = StatusNotifierItemService(
                bus=bus,
                object_path=sni_path,
                menu_path=menu_path,
            )

            # Panggil RegisterStatusNotifierItem pada watcher
            watcher = bus.get_object(SNI_WATCHER_BUS_NAME, SNI_WATCHER_OBJECT_PATH)
            iface = dbus.Interface(watcher, SNI_WATCHER_BUS_NAME)
            iface.RegisterStatusNotifierItem(service_name)
            self._shown = True
            logger.info(f"TrayItem berhasil didaftarkan: {service_name}")
        except Exception as exc:
            logger.warning(f"Gagal mendaftarkan TrayItem: {exc}")
            raise RuntimeError(f"Gagal mendaftarkan StatusNotifierItem: {exc}") from exc

    def hide(self) -> None:
        """Sembunyikan dan bersihkan objek baki."""
        self._shown = False
        self._sni_service = None
        self._menu_service = None
        self._bus_name = None
