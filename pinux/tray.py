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

from pinux import APP_ID, __version__

__all__ = ["TrayItem"]

logger = logging.getLogger("pinux.tray")

SNI_WATCHER_BUS_NAME: Final[str] = "org.kde.StatusNotifierWatcher"
SNI_WATCHER_OBJECT_PATH: Final[str] = "/StatusNotifierWatcher"
SNI_INTERFACE: Final[str] = "org.kde.StatusNotifierItem"
DBUSMENU_INTERFACE: Final[str] = "com.canonical.dbusmenu"


def _make_dbus_dict(d: dict[str, Any]) -> dbus.Dictionary:
    """Konversi dictionary Python ke dbus.Dictionary bersignature 'sv'."""
    res = dbus.Dictionary(signature="sv")
    for k, v in d.items():
        key = dbus.String(str(k))
        if isinstance(v, bool):
            res[key] = dbus.Boolean(v)
        elif isinstance(v, int):
            res[key] = dbus.Int32(v)
        elif isinstance(v, str):
            res[key] = dbus.String(v)
        else:
            res[key] = v
    return res


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
        version_string: str = f"Pinux v{__version__}",
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

    def _get_raw_menu_items(self) -> list[tuple[int, dict[str, Any]]]:
        return [
            (1, {"label": "Terjemahkan Seleksi / Clipboard", "type": "standard", "enabled": True}),
            (2, {"label": "Tangkapan Layar & Terjemah (OCR)", "type": "standard", "enabled": True}),
            (3, {"label": "Input Terjemahan Manual", "type": "standard", "enabled": True}),
            (4, {"label": "Tampilkan Jendela Terjemahan", "type": "standard", "enabled": True}),
            (5, {"type": "separator"}),
            (6, {"label": "Tangkapan Layar & Salin Teks OCR", "type": "standard", "enabled": True}),
            (7, {"type": "separator"}),
            (8, {"label": "Pengaturan...", "type": "standard", "enabled": True}),
            (9, {"type": "separator"}),
            (10, {"label": self._version_string, "type": "standard", "enabled": False}),
            (11, {"label": "Keluar", "type": "standard", "enabled": True}),
        ]

    @dbus.service.method(DBUSMENU_INTERFACE, in_signature="iias", out_signature="u(ia{sv}av)")
    def GetLayout(
        self,
        parent_id: int,
        recursion_depth: int,
        property_names: list[str] | None = None,
    ) -> tuple[int, Any]:
        """Kembalikan struktur menu bertingkat ala Bob."""
        empty_children = dbus.Array([], signature="v")
        raw_items = self._get_raw_menu_items()

        children = dbus.Array(
            [
                dbus.Struct(
                    (
                        dbus.Int32(item_id),
                        _make_dbus_dict(props),
                        empty_children,
                    ),
                    signature="(ia{sv}av)",
                    variant_level=1,
                )
                for item_id, props in raw_items
            ],
            signature="v",
        )

        root_props = _make_dbus_dict({"children-display": "submenu"})
        root = dbus.Struct((dbus.Int32(0), root_props, children), signature="(ia{sv}av)")
        return (dbus.UInt32(1), root)

    @dbus.service.method(DBUSMENU_INTERFACE, in_signature="aias", out_signature="a(ia{sv})")
    def GetGroupProperties(
        self,
        ids: list[int],
        property_names: list[str],
    ) -> list[tuple[int, dict[str, Any]]]:
        """Kembalikan properti untuk sejumlah item id."""
        id_set = set(ids)
        items_dict = dict(self._get_raw_menu_items())
        result: list[tuple[int, dict[str, Any]]] = []
        for item_id in ids:
            if item_id in items_dict:
                result.append((dbus.Int32(item_id), _make_dbus_dict(items_dict[item_id])))
        return result

    @dbus.service.method(DBUSMENU_INTERFACE, in_signature="i", out_signature="b")
    def AboutToShow(self, item_id: int) -> bool:
        """Dipanggil sebelum menu ditampilkan."""
        return False

    @dbus.service.method(DBUSMENU_INTERFACE, in_signature="isvu", out_signature="")
    def Event(self, item_id: int, event_id: str, data: Any, timestamp: int) -> None:
        """Tangani klik pada item menu."""
        from gi.repository import GLib

        if event_id in ("clicked", "activate"):
            if item_id == 1 and self._on_translate_selection is not None:
                GLib.idle_add(self._on_translate_selection)
            elif item_id == 2 and self._on_ocr_translate is not None:
                GLib.idle_add(self._on_ocr_translate)
            elif item_id == 3 and self._on_input_translate is not None:
                GLib.idle_add(self._on_input_translate)
            elif item_id == 4 and self._on_show_popup is not None:
                GLib.idle_add(self._on_show_popup)
            elif item_id == 6 and self._on_ocr_pure is not None:
                GLib.idle_add(self._on_ocr_pure)
            elif item_id == 8 and self._on_settings is not None:
                GLib.idle_add(self._on_settings)
            elif item_id == 11 and self._on_quit is not None:
                GLib.idle_add(self._on_quit)



def _load_icon_pixmap() -> dbus.Array:
    """Muat data piksel ARGB byte-order network dari ikon Pinux untuk IconPixmap.

    Menjamin host tray (AppIndicator / KDE / Waybar) selalu menampilkan ikon
    meskipun tema ikon belum di-cache atau nama ikon tidak ditemukan di sistem host.
    """
    empty_pixmap = dbus.Array([], signature="(iiay)")
    try:
        from pathlib import Path
        from PIL import Image
        import struct

        # Prioritas: cari ikon resolusi 24x24 / 32x32 dari paket Pinux
        candidates = [
            Path("/app/share/icons/hicolor/24x24/apps/pinux.png"),
            Path(__file__).resolve().parent.parent / "data" / "icons" / "hicolor" / "24x24" / "apps" / "pinux.png",
            Path.home() / ".local" / "share" / "icons" / "hicolor" / "24x24" / "apps" / "pinux.png",
        ]
        icon_file: Path | None = None
        for cand in candidates:
            if cand.is_file():
                icon_file = cand
                break

        if icon_file is None:
            return empty_pixmap

        im = Image.open(icon_file).convert("RGBA")
        w, h = im.size
        pixels = bytearray()
        for y in range(h):
            for x in range(w):
                r, g, b, a = im.getpixel((x, y))
                pixels.extend(struct.pack(">I", (a << 24) | (r << 16) | (g << 8) | b))

        return dbus.Array(
            [dbus.Struct((dbus.Int32(w), dbus.Int32(h), dbus.ByteArray(pixels)), signature=None)],
            signature="(iiay)",
        )
    except Exception as exc:
        logger.debug("Gagal membuat IconPixmap dari ikon Pinux: %s", exc)
        return empty_pixmap


class StatusNotifierItemService(dbus.service.Object):
    """Layanan D-Bus untuk StatusNotifierItem."""

    def __init__(
        self,
        bus: dbus.Bus,
        object_path: str,
        menu_path: str,
        on_activate: Callable[[], None] | None = None,
        on_context_menu: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(bus, object_path)
        self._menu_path = menu_path
        self._on_activate = on_activate
        self._on_context_menu = on_context_menu
        self._pixmap = _load_icon_pixmap()

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
            if os.environ.get("FLATPAK_ID"):
                theme_path = "/app/share/icons/hicolor"
            else:
                user_icons = os.path.expanduser("~/.local/share/icons")
                theme_path = user_icons if os.path.isdir(user_icons) else ""
            return {
                "Category": dbus.String("ApplicationStatus"),
                "Id": dbus.String(APP_ID),
                "Title": dbus.String("Pinux"),
                "Status": dbus.String("Active"),
                "IconName": dbus.String("pinux"),
                "IconPixmap": self._pixmap,
                "IconThemePath": dbus.String(theme_path),
                "ItemIsMenu": dbus.Boolean(False),
                "Menu": dbus.ObjectPath(self._menu_path),
                "WindowId": dbus.Int32(0),
                "ToolTip": dbus.Struct(
                    (
                        dbus.String("pinux"),
                        self._pixmap,
                        dbus.String("Pinux Translator"),
                        dbus.String("Klik kanan untuk menu pengaturan / OCR"),
                    ),
                    signature=None,
                ),
            }
        return {}

    @dbus.service.method(SNI_INTERFACE, in_signature="ii", out_signature="")
    def ContextMenu(self, x: int, y: int) -> None:
        """Dipanggil saat klik kanan jika host tidak memakai com.canonical.dbusmenu langsung."""
        from gi.repository import GLib

        if self._on_context_menu is not None:
            GLib.idle_add(self._on_context_menu)

    @dbus.service.method(SNI_INTERFACE, in_signature="ii", out_signature="")
    def Activate(self, x: int, y: int) -> None:
        """Dipanggil saat ikon tray diklik kiri."""
        from gi.repository import GLib

        if self._on_activate is not None:
            GLib.idle_add(self._on_activate)

    @dbus.service.method(SNI_INTERFACE, in_signature="ii", out_signature="")
    def SecondaryActivate(self, x: int, y: int) -> None:
        """Dipanggil saat ikon tray diklik tengah."""
        pass

    @dbus.service.method(SNI_INTERFACE, in_signature="s", out_signature="")
    def ProvideXdgActivationToken(self, token: str) -> None:
        """Terima token aktivasi dari desktop host GNOME/Wayland."""
        pass

    @dbus.service.signal(SNI_INTERFACE)
    def NewTitle(self) -> None:
        pass

    @dbus.service.signal(SNI_INTERFACE)
    def NewIcon(self) -> None:
        pass

    @dbus.service.signal(SNI_INTERFACE)
    def NewStatus(self, status: str) -> None:
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
        version_string: str = f"Pinux v{__version__}",
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
            activate_cb = self._on_show_popup or self._on_translate_selection
            if activate_cb is None:
                logger.debug("TrayItem: Tidak ada callback activate yang terdefinisi")

            self._sni_service = StatusNotifierItemService(
                bus=bus,
                object_path=sni_path,
                menu_path=menu_path,
                on_activate=activate_cb,
                on_context_menu=self._on_settings,
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
        if self._bus_name is not None:
            try:
                # Melepaskan nama D-Bus memberi tahu watcher bahwa item telah hilang
                self._bus_name = None
            except Exception:
                pass
