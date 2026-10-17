"""Klien D-Bus untuk org.freedesktop.portal.GlobalShortcuts dan ShortcutManager.

Menyediakan:
1. ``ShortcutSpec`` dan ``BoundShortcut`` sesuai design.md.
2. ``GlobalShortcutsPortal`` untuk interaksi dengan portal D-Bus XDG:
   - ``CreateSession`` dan pemantauan Response
   - ``BindShortcuts`` dengan preferred_trigger sintaks GTK
   - Menghubungkan sinyal ``Activated``
   - Penutupan sesi (``Close``) saat shutdown
3. ``ShortcutManager`` untuk memilih backend portal jika tersedia, atau fallback CLI
   (``pinux --trigger`` / ``pinux --pick-region``) bila portal tidak tersedia atau ditolak.

Perujuk: R1.2, R1.3, R8.1, R8.3, R8.4 pada requirements.md, serta design.md.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, Literal

import dbus

from pinux import APP_ID
from pinux.portal.request import portal_request

__all__ = [
    "BoundShortcut",
    "GlobalShortcutsPortal",
    "ShortcutBackend",
    "ShortcutManager",
    "ShortcutSpec",
    "specs_from_settings",
]

logger = logging.getLogger("pinux.portal.shortcuts")

PORTAL_BUS_NAME: Final[str] = "org.freedesktop.portal.Desktop"
PORTAL_OBJECT_PATH: Final[str] = "/org/freedesktop/portal/desktop"
GLOBAL_SHORTCUTS_INTERFACE: Final[str] = "org.freedesktop.portal.GlobalShortcuts"
HOST_REGISTRY_INTERFACE: Final[str] = "org.freedesktop.host.portal.Registry"
REQUEST_INTERFACE: Final[str] = "org.freedesktop.portal.Request"
SESSION_INTERFACE: Final[str] = "org.freedesktop.portal.Session"

ShortcutBackend = Literal["portal", "cli"]


@dataclass(frozen=True)
class ShortcutSpec:
    """Spesifikasi pintasan yang diajukan ke portal."""

    id: str                     # "translate" | "ocr"
    description: str
    preferred_trigger: str      # sintaks GTK, misalnya "<Control><Alt>T"


@dataclass(frozen=True)
class BoundShortcut:
    """Hasil pengikatan pintasan yang disetujui pengguna/portal."""

    id: str
    trigger: str
    activation_token: str


class GlobalShortcutsPortal:
    """Klien protokol org.freedesktop.portal.GlobalShortcuts."""

    def __init__(self, bus: dbus.Bus | None = None) -> None:
        self._bus = bus
        self._session_path: str | None = None
        self._activated_callbacks: list[Callable[[str], None]] = []
        self._signal_match = None

    def _get_bus(self) -> dbus.Bus:
        if self._bus is None:
            self._bus = dbus.SessionBus()
        return self._bus

    def is_available(self) -> bool:
        """Periksa apakah portal GlobalShortcuts tersedia pada sesi D-Bus."""
        try:
            bus = self._get_bus()
            if not bus.name_has_owner(PORTAL_BUS_NAME):
                return False
            portal = bus.get_object(PORTAL_BUS_NAME, PORTAL_OBJECT_PATH)
            intf = dbus.Interface(portal, "org.freedesktop.DBus.Introspectable")
            xml = intf.Introspect()
            return GLOBAL_SHORTCUTS_INTERFACE in xml
        except Exception as exc:
            logger.debug(f"Pemeriksaan portal GlobalShortcuts gagal: {exc}")
            return False

    def connect_activated(self, callback: Callable[[str], None]) -> None:
        """Daftarkan callback saat shortcut ditekan (sinyal Activated diterima)."""
        self._activated_callbacks.append(callback)

    def _on_activated(self, session_handle: str, shortcut_id: str, timestamp: int, options: dict) -> None:
        for cb in list(self._activated_callbacks):
            try:
                cb(str(shortcut_id))
            except Exception as exc:
                logger.error(f"Error pada callback Activated: {exc}")

    def _ensure_registered(self) -> None:
        """Daftarkan app_id pada org.freedesktop.host.portal.Registry bila tersedia."""
        try:
            bus = self._get_bus()
            portal = bus.get_object(PORTAL_BUS_NAME, PORTAL_OBJECT_PATH)
            registry = dbus.Interface(portal, HOST_REGISTRY_INTERFACE)
            # Di luar Flatpak, app_id harus cocok dengan nama desktop file.
            try:
                registry.Register(APP_ID, {})
            except Exception:
                pass
        except Exception:
            pass

    def create_session(self, *, timeout_s: float = 15.0) -> str | None:
        """Buat sesi portal GlobalShortcuts dan kembalikan ``session_handle``.

        ``CreateSession`` bersifat asinkron: handle sesi yang sah hanya ada pada
        hasil sinyal ``Response``, bukan hasil tebakan path.
        """
        self._ensure_registered()

        bus = self._get_bus()
        portal = bus.get_object(PORTAL_BUS_NAME, PORTAL_OBJECT_PATH)
        iface = dbus.Interface(portal, GLOBAL_SHORTCUTS_INTERFACE)

        token = "pinux_session_" + uuid.uuid4().hex[:8]
        options = {
            "session_handle_token": dbus.String(token),
            "handle_token": dbus.String(token + "_req"),
        }

        try:
            code, results = portal_request(
                bus,
                lambda: iface.CreateSession(options),
                token + "_req",
                timeout_s=timeout_s,
            )
        except Exception as exc:
            logger.info(f"Portal GlobalShortcuts tidak dapat membuat sesi: {exc}")
            return None

        handle = results.get("session_handle")
        if code != 0 or not handle:
            logger.info(f"CreateSession ditolak atau tanpa handle (kode {code})")
            return None
        self._session_path = str(handle)
        return self._session_path

    def bind(
        self,
        shortcuts: Sequence[ShortcutSpec],
        parent_window: str = "",
        *,
        timeout_s: float = 120.0,
    ) -> list[BoundShortcut]:
        """Ikat pintasan global pada portal.

        Mengembalikan hanya pintasan yang benar-benar disetujui portal beserta
        pemicu yang disetujui (bisa berbeda dari ``preferred_trigger``).
        Daftar kosong berarti ditolak atau gagal.
        """
        if not self.is_available():
            raise RuntimeError("Portal GlobalShortcuts tidak tersedia")

        bus = self._get_bus()
        if not self._session_path:
            self.create_session()

        if not self._session_path:
            raise RuntimeError("Gagal membuat sesi GlobalShortcuts")

        # Dengarkan sinyal Activated pada interface portal
        if self._signal_match is None:
            self._signal_match = bus.add_signal_receiver(
                self._on_activated,
                signal_name="Activated",
                dbus_interface=GLOBAL_SHORTCUTS_INTERFACE,
            )

        portal = bus.get_object(PORTAL_BUS_NAME, PORTAL_OBJECT_PATH)
        iface = dbus.Interface(portal, GLOBAL_SHORTCUTS_INTERFACE)

        dbus_shortcuts = []
        for s in shortcuts:
            opts = {
                "description": dbus.String(s.description),
                "preferred_trigger": dbus.String(s.preferred_trigger),
            }
            dbus_shortcuts.append((s.id, opts))

        token = "bind_" + uuid.uuid4().hex[:8]
        options = {"handle_token": dbus.String(token)}

        try:
            code, results = portal_request(
                bus,
                lambda: iface.BindShortcuts(
                    dbus.ObjectPath(self._session_path),
                    dbus_shortcuts,
                    dbus.String(parent_window),
                    options,
                ),
                token,
                timeout_s=timeout_s,
            )
        except Exception as exc:
            logger.warning(f"BindShortcuts gagal atau ditolak: {exc}")
            return []

        if code != 0:
            logger.warning(f"BindShortcuts ditolak pengguna (kode {code})")
            return []

        wanted = {s.id: s for s in shortcuts}
        bound: list[BoundShortcut] = []
        for item in results.get("shortcuts", []):
            try:
                sid, props = str(item[0]), dict(item[1])
            except (TypeError, IndexError, ValueError):
                continue
            if sid not in wanted:
                continue
            trigger = str(props.get("trigger_description") or wanted[sid].preferred_trigger)
            bound.append(BoundShortcut(id=sid, trigger=trigger, activation_token=sid))
        return bound

    def unbind(self, bindings: Sequence[BoundShortcut]) -> None:
        """Lepaskan pintasan atau tutup sesi."""
        self.close()

    def close(self) -> None:
        """Tutup sesi portal dan bersihkan listener sinyal."""
        if self._signal_match is not None and self._bus is not None:
            try:
                self._bus.remove_signal_receiver(
                    self._on_activated,
                    signal_name="Activated",
                    dbus_interface=GLOBAL_SHORTCUTS_INTERFACE,
                )
            except Exception:
                pass
            self._signal_match = None

        if self._session_path and self._bus is not None:
            try:
                session_obj = self._bus.get_object(PORTAL_BUS_NAME, self._session_path)
                session_iface = dbus.Interface(session_obj, SESSION_INTERFACE)
                session_iface.Close()
            except Exception:
                pass
            self._session_path = None


_SPEC_DESCRIPTIONS: Final[dict[str, str]] = {
    "translate": "Penerjemahan teks dari Clipboard",
    "ocr": "Tangkapan layar dan OCR terjemahan",
}


def specs_from_settings(shortcuts: dict[str, str]) -> tuple[ShortcutSpec, ...]:
    """Susun ShortcutSpec dari ``Settings.shortcuts`` (sintaks GTK)."""
    return tuple(
        ShortcutSpec(id=sid, description=_SPEC_DESCRIPTIONS[sid], preferred_trigger=trigger)
        for sid, trigger in shortcuts.items()
        if sid in _SPEC_DESCRIPTIONS and trigger
    )


class ShortcutManager:
    """Manajer pintasan: memilih portal bila tersedia, dan fallback CLI bila tidak (R1.3)."""

    def __init__(
        self,
        portal: GlobalShortcutsPortal | None = None,
        specs: Sequence[ShortcutSpec] | None = None,
        on_activated: Callable[[str], None] | None = None,
    ) -> None:
        self._portal = portal or GlobalShortcutsPortal()
        self._specs = specs or (
            ShortcutSpec(
                id="translate",
                description="Penerjemahan teks dari Clipboard",
                preferred_trigger="<Control><Alt>T",
            ),
            ShortcutSpec(
                id="ocr",
                description="Tangkapan layar dan OCR terjemahan",
                preferred_trigger="<Control><Alt>O",
            ),
        )
        self._on_activated = on_activated
        self._active_backend: ShortcutBackend = "cli"
        self._bound_shortcuts: list[BoundShortcut] = []

    @property
    def active_backend(self) -> ShortcutBackend:
        """Backend aktif saat ini: 'portal' atau 'cli'."""
        return self._active_backend

    @property
    def bound_shortcuts(self) -> Sequence[BoundShortcut]:
        """Daftar pintasan terikat jika portal aktif."""
        return tuple(self._bound_shortcuts)

    def configure_shortcuts(self, parent_window: str = "") -> None:
        """Panggil dialog konfigurasi pintasan portal sistem desktop bila backend portal aktif."""
        if self._active_backend == "portal" and self._portal is not None:
            self._portal.configure_shortcuts(parent_window)

    def start(self) -> ShortcutBackend:
        """Mulai manajer pintasan.

        Mengembalikan 'portal' jika portal berhasil diikat, atau 'cli' jika gagal/tidak tersedia.
        """
        if not self._portal.is_available():
            logger.info("Portal GlobalShortcuts tidak tersedia. Beralih ke mode CLI.")
            self._active_backend = "cli"
            return "cli"

        if self._on_activated is not None:
            self._portal.connect_activated(self._on_activated)

        try:
            bound = self._portal.bind(self._specs)
            if bound:
                self._bound_shortcuts = bound
                self._active_backend = "portal"
                return "portal"
        except Exception as exc:
            logger.info(f"Pintasan portal tidak aktif ({exc}). Beralih ke mode CLI.")

        # Fallback ke CLI mode jika ditolak pengguna atau error
        logger.info("Menggunakan mode CLI (R1.3: pintasan desktop dapat dipanggil via 'pinux --trigger').")
        self._active_backend = "cli"
        return "cli"

    def stop(self) -> None:
        """Hentikan dan bersihkan manajer pintasan."""
        if self._portal is not None:
            self._portal.close()
        self._bound_shortcuts = []
        self._active_backend = "cli"
