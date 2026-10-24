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
import os
import shlex
import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, Literal

import dbus
from gi.repository import GLib

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

# Batas waktu (detik) pemanggilan ``Session.Close`` agar shutdown tidak tertahan
# portal yang hang (bawaan dbus-python menunggu hingga 25 detik).
CLOSE_TIMEOUT_S: Final[float] = 2.0


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


def _iter_shortcuts(items: object) -> list[tuple[str, dict]]:
    """Urai daftar ``a(sa{sv})`` dari portal menjadi ``[(id, properti)]``; item rusak dilewati."""
    parsed: list[tuple[str, dict]] = []
    for item in items or []:  # type: ignore[union-attr]
        try:
            parsed.append((str(item[0]), dict(item[1])))
        except (TypeError, IndexError, ValueError):
            continue
    return parsed


class GlobalShortcutsPortal:
    """Klien protokol org.freedesktop.portal.GlobalShortcuts."""

    def __init__(self, bus: dbus.Bus | None = None) -> None:
        self._bus = bus
        self._session_path: str | None = None
        self._activated_callbacks: list[Callable[[str], None]] = []
        self._closed_callbacks: list[Callable[[str], None]] = []
        self._changed_callbacks: list[Callable[[list[BoundShortcut]], None]] = []
        self._signal_match = None
        # Langganan sesi: Closed, ShortcutsChanged, dan pemantau pemilik nama bus portal
        self._session_matches: list = []
        self._owner_watch = None
        self._portal_owner_seen = False

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
        """Daftarkan callback saat shortcut ditekan (sinyal Activated diterima).

        Idempoten: callback yang sama (termasuk bound method yang sama) tidak
        didaftarkan dua kali, agar satu penekanan tombol tidak memicu router ganda.
        """
        if callback in self._activated_callbacks:
            return
        self._activated_callbacks.append(callback)

    def _on_activated(self, session_handle: str, shortcut_id: str, timestamp: int, options: dict) -> None:
        for cb in list(self._activated_callbacks):
            try:
                cb(str(shortcut_id))
            except Exception as exc:
                logger.error(f"Error pada callback Activated: {exc}")

    def connect_closed(self, callback: Callable[[str], None]) -> None:
        """Daftarkan callback saat sesi berakhir di luar kendali Pinux.

        Argumen callback adalah alasan: ``REASON_SESSION_CLOSED`` (sinyal
        ``Session.Closed`` dari desktop) atau ``REASON_PORTAL_STOPPED`` (layanan
        portal berhenti/restart, yang tidak mengirim ``Closed``). Idempoten.
        """
        if callback not in self._closed_callbacks:
            self._closed_callbacks.append(callback)

    def connect_shortcuts_changed(self, callback: Callable[[list[BoundShortcut]], None]) -> None:
        """Daftarkan callback saat pengguna mengubah pemicu pintasan di pengaturan sistem."""
        if callback not in self._changed_callbacks:
            self._changed_callbacks.append(callback)

    def _watch_session(self) -> None:
        """Pasang pemantau akhir-sesi dan perubahan pintasan; idempoten."""
        if self._session_matches or self._owner_watch is not None or self._bus is None:
            return
        bus = self._bus
        try:
            self._session_matches.append(
                bus.add_signal_receiver(
                    self._on_session_closed,
                    signal_name="Closed",
                    dbus_interface=SESSION_INTERFACE,
                    path=self._session_path,
                )
            )
            self._session_matches.append(
                bus.add_signal_receiver(
                    self._on_shortcuts_changed,
                    signal_name="ShortcutsChanged",
                    dbus_interface=GLOBAL_SHORTCUTS_INTERFACE,
                )
            )
            self._portal_owner_seen = False
            self._owner_watch = bus.watch_name_owner(PORTAL_BUS_NAME, self._on_portal_owner_changed)
        except Exception as exc:
            logger.debug(f"Pemantauan sesi portal tidak dapat dipasang: {exc}")

    def _unwatch_session(self) -> None:
        """Lepas semua langganan sinyal sesi dan pemantau nama bus."""
        matches, self._session_matches = self._session_matches, []
        for match in matches:
            try:
                match.remove()
            except Exception:
                pass
        watch, self._owner_watch = self._owner_watch, None
        if watch is not None:
            try:
                watch.cancel()
            except Exception:
                pass

    def _drop_session(self, reason: str) -> None:
        """Sesi sudah mati di sisi portal: bersihkan state lokal lalu beri tahu pendengar."""
        if self._session_path is None:
            return  # sudah kita tutup sendiri atau sudah ditangani
        logger.warning(f"Sesi portal GlobalShortcuts berakhir ({reason})")
        self._session_path = None
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
        self._unwatch_session()
        for cb in list(self._closed_callbacks):
            try:
                cb(reason)
            except Exception as exc:
                logger.error(f"Error pada callback Closed: {exc}")

    def _on_session_closed(self, details: object = None) -> None:
        self._drop_session(REASON_SESSION_CLOSED)

    def _on_portal_owner_changed(self, new_owner: str) -> None:
        """Pemilik nama bus portal berubah; ``new_owner`` kosong berarti portal berhenti.

        dbus-python memanggil callback ini sekali segera dengan pemilik saat ini,
        sehingga panggilan pertama hanya dicatat.
        """
        if new_owner:
            self._portal_owner_seen = True
            return
        if self._portal_owner_seen:
            self._drop_session(REASON_PORTAL_STOPPED)

    def _on_shortcuts_changed(self, session_handle: object, shortcuts: object) -> None:
        if self._session_path is None or str(session_handle) != self._session_path:
            return
        changed = [
            BoundShortcut(
                id=sid,
                trigger=str(props.get("trigger_description") or ""),
                activation_token=sid,
            )
            for sid, props in _iter_shortcuts(shortcuts)
        ]
        if not changed:
            return
        for cb in list(self._changed_callbacks):
            try:
                cb(changed)
            except Exception as exc:
                logger.error(f"Error pada callback ShortcutsChanged: {exc}")

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
        self._watch_session()
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
        for sid, props in _iter_shortcuts(results.get("shortcuts", [])):
            if sid not in wanted:
                continue
            trigger = str(props.get("trigger_description") or wanted[sid].preferred_trigger)
            bound.append(BoundShortcut(id=sid, trigger=trigger, activation_token=sid))
        return bound

    def _portal_version(self) -> int:
        """Baca properti ``version`` portal GlobalShortcuts; 1 bila tidak terbaca."""
        try:
            bus = self._get_bus()
            portal = bus.get_object(PORTAL_BUS_NAME, PORTAL_OBJECT_PATH)
            props = dbus.Interface(portal, "org.freedesktop.DBus.Properties")
            return int(props.Get(GLOBAL_SHORTCUTS_INTERFACE, "version"))
        except Exception as exc:
            logger.debug(f"Versi portal GlobalShortcuts tidak terbaca: {exc}")
            return 1

    def configure_shortcuts(self, parent_window: str = "") -> bool:
        """Buka dialog konfigurasi pintasan milik desktop (``ConfigureShortcuts``).

        Hanya tersedia pada portal GlobalShortcuts versi 2 ke atas dan saat sesi
        aktif. Mengembalikan ``True`` bila permintaan terkirim, ``False`` bila
        tidak didukung atau gagal (tanpa melempar galat).
        """
        if not self._session_path:
            logger.info("ConfigureShortcuts dilewati: belum ada sesi portal aktif")
            return False
        if self._portal_version() < 2:
            logger.info("ConfigureShortcuts dilewati: portal GlobalShortcuts versi < 2")
            return False
        try:
            bus = self._get_bus()
            portal = bus.get_object(PORTAL_BUS_NAME, PORTAL_OBJECT_PATH)
            iface = dbus.Interface(portal, GLOBAL_SHORTCUTS_INTERFACE)
            iface.ConfigureShortcuts(
                dbus.ObjectPath(self._session_path),
                dbus.String(parent_window),
                dbus.Dictionary({}, signature="sv"),
            )
            return True
        except Exception as exc:
            logger.warning(f"ConfigureShortcuts gagal: {exc}")
            return False

    def unbind(self, bindings: Sequence[BoundShortcut]) -> None:
        """Tutup seluruh sesi portal; argumen ``bindings`` tidak dipakai.

        Portal tidak menyediakan pelepasan per-pintasan, sehingga satu-satunya cara
        melepas pengikatan adalah menutup sesi.
        """
        self.close()

    def close(self) -> None:
        """Tutup sesi portal dan bersihkan listener sinyal.

        Aman dipanggil berulang dan tidak pernah melempar galat. Pemanggilan
        ``Session.Close`` dibatasi ``CLOSE_TIMEOUT_S`` dan tanpa introspeksi, agar
        shutdown tidak tertahan portal yang hang.
        """
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
        self._unwatch_session()

        session, self._session_path = self._session_path, None
        if session and self._bus is not None:
            try:
                session_obj = self._bus.get_object(PORTAL_BUS_NAME, session, introspect=False)
                dbus.Interface(session_obj, SESSION_INTERFACE).Close(timeout=CLOSE_TIMEOUT_S)
            except Exception as exc:
                logger.debug(f"Session.Close gagal atau melebihi batas waktu: {exc}")


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


# Alasan pintasan portal tidak aktif (``ShortcutManager.last_reason``).
REASON_PORTAL_UNAVAILABLE: Final[str] = "portal_unavailable"
REASON_BIND_FAILED: Final[str] = "bind_failed"
REASON_SESSION_CLOSED: Final[str] = "session_closed"
REASON_PORTAL_STOPPED: Final[str] = "portal_stopped"
# Bukan kegagalan: pengikatan sedang berjalan dan menunggu persetujuan desktop.
REASON_PENDING: Final[str] = "pending"

# Opsi CLI yang setara dengan tiap id pintasan (R1.3).
CLI_FLAGS: Final[dict[str, str]] = {
    "translate": "--trigger",
    "ocr": "--pick-region",
}

_FALLBACK_INTRO: Final[str] = (
    "Ikat perintah berikut secara manual pada Pengaturan Keyboard desktop Anda:"
)
_FALLBACK_DESCRIPTIONS: Final[dict[str, str]] = {
    REASON_PORTAL_UNAVAILABLE: "Portal GlobalShortcuts tidak tersedia di desktop ini. " + _FALLBACK_INTRO,
    REASON_BIND_FAILED: (
        "Pintasan global tidak aktif: permintaan ke portal ditolak, dibatalkan, "
        "atau tidak dijawab. " + _FALLBACK_INTRO
    ),
    REASON_PENDING: (
        "Menunggu desktop menyetujui pintasan global; dialog persetujuan mungkin sedang "
        "tampil. Sementara itu, " + _FALLBACK_INTRO[0].lower() + _FALLBACK_INTRO[1:]
    ),
    REASON_SESSION_CLOSED: (
        "Sesi pintasan global ditutup oleh desktop. Mulai ulang Pinux untuk mengikat "
        "ulang. " + _FALLBACK_INTRO
    ),
    REASON_PORTAL_STOPPED: (
        "Layanan portal desktop berhenti atau dimulai ulang. Mulai ulang Pinux untuk "
        "mengikat ulang. " + _FALLBACK_INTRO
    ),
}


def is_flatpak() -> bool:
    """Apakah Pinux berjalan di dalam sandbox Flatpak."""
    return bool(os.environ.get("FLATPAK_ID")) or os.path.exists("/.flatpak-info")


def cli_command(flag: str, *, flatpak: bool | None = None) -> str:
    """Perintah shell lengkap untuk ``flag`` (mis. ``--trigger``), siap diikat ke pintasan.

    Di Flatpak perintahnya ``flatpak run <APP_ID> <flag>``, di luar itu ``pinux <flag>``.
    ``flatpak=None`` berarti dideteksi otomatis.
    """
    if flatpak is None:
        flatpak = is_flatpak()
    argv = ["flatpak", "run", APP_ID, flag] if flatpak else ["pinux", flag]
    return shlex.join(argv)


def describe_fallback(reason: object) -> str:
    """Teks penjelasan mode CLI sesuai alasan; nilai tak dikenal memakai teks umum."""
    if isinstance(reason, str) and reason in _FALLBACK_DESCRIPTIONS:
        return _FALLBACK_DESCRIPTIONS[reason]
    return "Pintasan global belum aktif. " + _FALLBACK_INTRO


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
        self._last_reason: str | None = None
        self._changed_callbacks: list[Callable[[], None]] = []
        # Keadaan yang terakhir dilihat pendengar; None setelah stop() atau sebelum
        # pemberitahuan pertama, sehingga start() berikutnya selalu memberi tahu.
        self._ui_snapshot: tuple | None = None
        # Pengikatan asinkron (start_async): token mengenali permintaan yang sudah
        # dibatalkan stop(); None berarti tidak ada pengikatan yang sedang berjalan.
        self._async_token: object | None = None

    @property
    def active_backend(self) -> ShortcutBackend:
        """Backend aktif saat ini: 'portal' atau 'cli'."""
        return self._active_backend

    def connect_changed(self, callback: Callable[[], None]) -> None:
        """Daftarkan callback saat backend, alasan fallback, atau pemicu berubah.

        Dipanggil bila ``start()`` menghasilkan keadaan berbeda (misalnya pengikatan
        portal selesai setelah UI tampil), sesi portal berakhir (backend turun ke
        'cli'), atau pengguna mengubah pemicu di pengaturan sistem. Tidak dipanggil
        oleh ``stop()``, dan tidak bila ``start()`` tidak mengubah apa pun. Idempoten.
        Callback dapat dipanggil dari callback D-Bus pada main loop.
        """
        if callback not in self._changed_callbacks:
            self._changed_callbacks.append(callback)

    def disconnect_changed(self, callback: Callable[[], None]) -> None:
        """Lepas callback perubahan; aman bila callback tidak terdaftar."""
        try:
            self._changed_callbacks.remove(callback)
        except ValueError:
            pass

    def _snapshot(self) -> tuple:
        """Ringkasan keadaan yang tampil di UI, untuk mendeteksi perubahan."""
        return (
            self._active_backend,
            self._last_reason,
            tuple((b.id, b.trigger) for b in self._bound_shortcuts),
        )

    def _notify_changed(self) -> None:
        self._ui_snapshot = self._snapshot()
        for cb in list(self._changed_callbacks):
            try:
                cb()
            except Exception as exc:
                logger.error(f"Error pada callback perubahan pintasan: {exc}")

    def _on_portal_closed(self, reason: str) -> None:
        """Sesi portal berakhir di luar kendali kita: turun ke CLI dengan alasan yang benar."""
        if self._active_backend != "portal":
            return
        logger.warning(f"Pintasan portal tidak lagi aktif ({reason}). Beralih ke mode CLI.")
        self._bound_shortcuts = []
        self._active_backend = "cli"
        self._last_reason = reason
        self._notify_changed()

    def _on_portal_shortcuts_changed(self, changed: Sequence[BoundShortcut]) -> None:
        """Pengguna mengubah pemicu di pengaturan sistem: perbarui pemicu yang kita simpan."""
        if self._active_backend != "portal":
            return
        new_triggers = {c.id: c.trigger for c in changed if c.trigger}
        updated: list[BoundShortcut] = []
        modified = False
        for bound in self._bound_shortcuts:
            trigger = new_triggers.get(bound.id)
            if trigger and trigger != bound.trigger:
                bound = BoundShortcut(id=bound.id, trigger=trigger, activation_token=bound.activation_token)
                modified = True
            updated.append(bound)
        if modified:
            self._bound_shortcuts = updated
            self._notify_changed()

    @property
    def last_reason(self) -> str | None:
        """Alasan portal tidak aktif: ``REASON_*``, atau ``None`` bila aktif/belum dimulai."""
        return self._last_reason

    @property
    def missing_shortcuts(self) -> tuple[str, ...]:
        """Id pintasan yang belum terikat pada portal (ditolak sebagian atau portal mati)."""
        bound_ids = {b.id for b in self._bound_shortcuts}
        return tuple(s.id for s in self._specs if s.id not in bound_ids)

    @property
    def bound_shortcuts(self) -> Sequence[BoundShortcut]:
        """Daftar pintasan terikat jika portal aktif."""
        return tuple(self._bound_shortcuts)

    def configure_shortcuts(self, parent_window: str = "") -> None:
        """Panggil dialog konfigurasi pintasan portal sistem desktop bila backend portal aktif."""
        if self._active_backend == "portal" and self._portal is not None:
            self._portal.configure_shortcuts(parent_window)

    def _release_portal(self) -> None:
        """Tutup sesi portal setelah pengikatan gagal agar tidak bocor.

        Sesi yang dibiarkan terbuka membuat dialog persetujuan bisa disetujui
        belakangan sementara UI sudah menampilkan mode CLI. Keputusan desain:
        pada jalur gagal sesi selalu ditutup.
        """
        try:
            self._portal.close()
        except Exception as exc:
            logger.debug(f"Penutupan sesi portal setelah gagal bind bermasalah: {exc}")
        self._bound_shortcuts = []

    def start(self) -> ShortcutBackend:
        """Mulai manajer pintasan secara sinkron.

        Mengembalikan 'portal' jika portal berhasil diikat, atau 'cli' jika gagal/tidak tersedia.
        Idempoten saat backend portal sudah aktif: pemanggilan ulang tidak membuka
        sesi baru maupun mendaftarkan callback ganda. Pada jalur gagal sesi portal
        ditutup; memanggil ``start()`` lagi dari mode CLI akan mencoba ulang.
        Callback ``connect_changed`` dipanggil bila keadaan berubah. Selama pengikatan
        berjalan ``last_reason`` bernilai ``REASON_PENDING`` dan pendengar diberi tahu
        lebih dulu, sehingga UI dapat menampilkan "menunggu persetujuan" saat dialog
        desktop terbuka.

        Bila dipanggil dari thread utama, pemanggilan ini memutar loop bersarang hingga
        dialog desktop selesai (maks. 120 dtk); aplikasi sebaiknya memakai
        :meth:`start_async`. Bila pengikatan asinkron sedang berjalan, tidak melakukan
        apa pun dan mengembalikan backend saat ini.
        """
        if self._async_token is not None:
            return self._active_backend
        backend = self._begin()
        if backend is None:
            backend = self._complete(*self._bind_blocking())
        self._notify_if_changed()
        return backend

    def start_async(self, on_done: Callable[[ShortcutBackend], None] | None = None) -> bool:
        """Mulai manajer tanpa memblokir thread utama.

        Menunggu dialog persetujuan desktop (bisa berlangsung lama) dilakukan pada
        worker thread, sehingga UI tetap responsif tanpa loop bersarang. Keadaan
        manajer, callback ``connect_changed``, dan ``on_done(backend)`` selalu
        dijalankan pada thread utama (lewat ``GLib.idle_add``); panggil dari thread utama.

        Mengembalikan ``False`` bila pengikatan asinkron sudah berjalan (pemanggilan
        diabaikan, ``on_done`` tidak dipanggil). Bila tidak perlu menunggu portal
        (sudah aktif, atau portal tidak tersedia) hasil langsung tersedia dan
        ``on_done`` dipanggil sebelum fungsi kembali. ``stop()`` membatalkan
        pengikatan yang sedang berjalan: hasilnya dibuang dan sesi yang mungkin sempat
        dibuka ditutup.
        """
        if threading.current_thread() is not threading.main_thread():
            logger.warning("start_async() dipanggil dari bukan thread utama; ini tidak didukung.")
        if self._async_token is not None:
            return False
        backend = self._begin()
        if backend is not None:
            self._notify_if_changed()
            self._call_done(on_done, backend)
            return True

        token = object()
        self._async_token = token

        def _worker() -> None:
            outcome = self._bind_blocking()
            GLib.idle_add(_finish, outcome)

        def _finish(outcome: tuple[list[BoundShortcut] | None, Exception | None]) -> bool:
            if self._async_token is not token:
                # stop() membatalkan permintaan ini: buang hasilnya dan tutup sesi yatim,
                # kecuali pengikatan baru sudah berjalan (sesi itu bukan yatim lagi).
                if self._async_token is None:
                    self._close_portal_quietly()
                return False
            self._async_token = None
            result = self._complete(*outcome)
            self._notify_if_changed()
            self._call_done(on_done, result)
            return False

        threading.Thread(target=_worker, name="pinux-bind-shortcuts", daemon=True).start()
        return True

    @staticmethod
    def _call_done(on_done: Callable[[ShortcutBackend], None] | None, backend: ShortcutBackend) -> None:
        if on_done is None:
            return
        try:
            on_done(backend)
        except Exception as exc:
            logger.error(f"Error pada callback selesai start_async: {exc}")

    def _notify_if_changed(self) -> None:
        # Bandingkan dengan yang terakhir diberitahukan (bukan keadaan sebelum start),
        # agar kembali dari "menunggu" ke hasil yang sama dengan sebelumnya tetap diberi tahu.
        if self._snapshot() != self._ui_snapshot:
            self._notify_changed()

    def _begin(self) -> ShortcutBackend | None:
        """Tahap awal (thread utama): kembalikan backend final, atau ``None`` bila perlu bind."""
        if self._active_backend == "portal" and self._bound_shortcuts:
            return "portal"

        if not self._portal.is_available():
            logger.info("Portal GlobalShortcuts tidak tersedia. Beralih ke mode CLI.")
            self._active_backend = "cli"
            self._last_reason = REASON_PORTAL_UNAVAILABLE
            return "cli"

        if self._on_activated is not None:
            self._portal.connect_activated(self._on_activated)
        self._portal.connect_closed(self._on_portal_closed)
        self._portal.connect_shortcuts_changed(self._on_portal_shortcuts_changed)

        self._last_reason = REASON_PENDING
        self._notify_changed()
        return None

    def _bind_blocking(self) -> tuple[list[BoundShortcut] | None, Exception | None]:
        """Ikat pintasan (memblokir); aman dijalankan pada worker thread, tidak mengubah keadaan.

        Catatan thread: ``stop()`` dan sinyal ``Closed`` (thread utama) boleh datang saat
        ``bind()`` berjalan di sini. Itu disengaja: ``close()`` mengosongkan sesi sehingga
        ``bind()`` gagal atau habis waktu, lalu hasilnya jatuh ke mode CLI atau dibuang
        (``_async_token``), tanpa mengubah keadaan manajer dari thread ini.
        """
        try:
            return self._portal.bind(self._specs), None
        except Exception as exc:
            return None, exc

    def _complete(self, bound: list[BoundShortcut] | None, error: Exception | None) -> ShortcutBackend:
        """Tahap akhir (thread utama): terapkan hasil pengikatan pada keadaan manajer."""
        if error is not None:
            logger.info(f"Pintasan portal tidak aktif ({error}). Beralih ke mode CLI.")
        elif bound:
            self._bound_shortcuts = bound
            self._active_backend = "portal"
            self._last_reason = None
            return "portal"

        # Fallback ke CLI mode jika ditolak pengguna atau error; sesi ditutup dahulu
        self._release_portal()
        logger.info(
            "Menggunakan mode CLI (R1.3: pintasan desktop dapat dipanggil via "
            "'pinux --trigger' dan 'pinux --pick-region')."
        )
        self._active_backend = "cli"
        self._last_reason = REASON_BIND_FAILED
        return "cli"

    def _close_portal_quietly(self) -> None:
        try:
            self._portal.close()
        except Exception as exc:
            logger.debug(f"Penutupan sesi portal yang dibatalkan bermasalah: {exc}")

    def stop(self) -> None:
        """Hentikan dan bersihkan manajer pintasan.

        Aman dipanggil berulang dan tidak melempar galat, agar pembersihan lain saat
        shutdown tetap berjalan walau portal bermasalah.
        """
        self._async_token = None  # batalkan pengikatan asinkron yang masih berjalan
        if self._portal is not None:
            try:
                self._portal.close()
            except Exception as exc:
                logger.warning(f"Penutupan sesi portal gagal saat stop: {exc}")
        self._bound_shortcuts = []
        self._active_backend = "cli"
        self._last_reason = None
        self._ui_snapshot = None  # start() berikutnya selalu memberi tahu pendengar
