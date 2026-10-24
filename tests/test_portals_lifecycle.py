"""Uji siklus hidup GlobalShortcutsPortal/ShortcutManager dengan objek palsu.

Berbeda dari ``test_portals.py`` yang banyak memakai ``MagicMock``, di sini portal
palsu merekam panggilan sehingga method yang hilang atau panggilan ganda terdeteksi.

Perujuk: R1.2, R1.3, R8.3 pada requirements.md.
"""

from __future__ import annotations

from unittest.mock import patch

from pinux.portal import shortcuts as sc
from pinux.portal.shortcuts import (
    BoundShortcut,
    GlobalShortcutsPortal,
    ShortcutManager,
)


class FakePortal:
    """Pengganti GlobalShortcutsPortal yang merekam panggilan."""

    def __init__(self, *, available: bool = True, bound=None, bind_error=None) -> None:
        self.available = available
        self.bound = bound if bound is not None else []
        self.bind_error = bind_error
        self.calls: list[str] = []
        self.callbacks: list = []
        self.closed_callbacks: list = []
        self.changed_callbacks: list = []
        self.configure_args: list[str] = []

    def is_available(self) -> bool:
        self.calls.append("is_available")
        return self.available

    def connect_activated(self, callback) -> None:
        self.calls.append("connect_activated")
        self.callbacks.append(callback)

    def connect_closed(self, callback) -> None:
        self.calls.append("connect_closed")
        self.closed_callbacks.append(callback)

    def connect_shortcuts_changed(self, callback) -> None:
        self.calls.append("connect_shortcuts_changed")
        self.changed_callbacks.append(callback)

    def bind(self, specs, parent_window: str = ""):
        self.calls.append("bind")
        if self.bind_error is not None:
            raise self.bind_error
        return list(self.bound)

    def close(self) -> None:
        self.calls.append("close")

    def configure_shortcuts(self, parent_window: str = "") -> bool:
        self.calls.append("configure_shortcuts")
        self.configure_args.append(parent_window)
        return True


def _bound() -> list[BoundShortcut]:
    return [BoundShortcut(id="translate", trigger="<Control><Alt>T", activation_token="translate")]


# --- Bug 1: configure_shortcuts ------------------------------------------------


def test_global_shortcuts_portal_has_configure_shortcuts() -> None:
    # Regresi: ShortcutManager memanggil method ini; dulu tidak ada pada kelas portal.
    assert callable(getattr(GlobalShortcutsPortal, "configure_shortcuts", None))


def test_manager_configure_shortcuts_delegates_when_portal_active() -> None:
    portal = FakePortal(bound=_bound())
    manager = ShortcutManager(portal=portal)
    manager.start()
    manager.configure_shortcuts("wayland:abc")
    assert portal.configure_args == ["wayland:abc"]


def test_manager_configure_shortcuts_noop_in_cli_mode() -> None:
    portal = FakePortal(available=False)
    manager = ShortcutManager(portal=portal)
    manager.start()
    manager.configure_shortcuts()
    assert "configure_shortcuts" not in portal.calls


class _RecordingIface:
    def __init__(self) -> None:
        self.configured: list[tuple] = []

    def ConfigureShortcuts(self, session, parent, options) -> None:  # noqa: N802 (nama D-Bus)
        self.configured.append((str(session), str(parent)))


def _portal_with_version(version: int):
    """GlobalShortcutsPortal dengan bus palsu yang melaporkan ``version`` tertentu."""
    from unittest.mock import MagicMock

    portal = GlobalShortcutsPortal(bus=MagicMock())
    portal._session_path = "/org/freedesktop/portal/desktop/session/1_7/pinux"
    recorder = _RecordingIface()

    class _Props:
        def Get(self, interface, name):  # noqa: N802
            assert name == "version"
            return version

    def iface_factory(obj, iface_name):
        if iface_name == "org.freedesktop.DBus.Properties":
            return _Props()
        return recorder

    return portal, recorder, iface_factory


def test_configure_shortcuts_calls_portal_when_version_2() -> None:
    portal, recorder, factory = _portal_with_version(2)
    with patch("dbus.Interface", side_effect=factory):
        assert portal.configure_shortcuts("x11:1") is True
    assert recorder.configured == [("/org/freedesktop/portal/desktop/session/1_7/pinux", "x11:1")]


def test_configure_shortcuts_skipped_on_version_1() -> None:
    portal, recorder, factory = _portal_with_version(1)
    with patch("dbus.Interface", side_effect=factory):
        assert portal.configure_shortcuts() is False
    assert recorder.configured == []


def test_configure_shortcuts_skipped_without_session() -> None:
    portal, recorder, factory = _portal_with_version(2)
    portal._session_path = None
    with patch("dbus.Interface", side_effect=factory):
        assert portal.configure_shortcuts() is False
    assert recorder.configured == []


# --- Bug 2: sesi ditutup pada jalur gagal -------------------------------------


def test_start_closes_session_when_bind_returns_empty() -> None:
    portal = FakePortal(bound=[])
    manager = ShortcutManager(portal=portal)
    assert manager.start() == "cli"
    assert "close" in portal.calls


def test_start_closes_session_when_bind_raises() -> None:
    portal = FakePortal(bind_error=TimeoutError("tidak merespons"))
    manager = ShortcutManager(portal=portal)
    assert manager.start() == "cli"
    assert portal.calls.count("close") == 1
    assert manager.bound_shortcuts == ()


def test_start_does_not_close_when_portal_unavailable() -> None:
    portal = FakePortal(available=False)
    manager = ShortcutManager(portal=portal)
    manager.start()
    assert "close" not in portal.calls


def test_start_does_not_close_on_success() -> None:
    portal = FakePortal(bound=_bound())
    manager = ShortcutManager(portal=portal)
    assert manager.start() == "portal"
    assert "close" not in portal.calls


def test_start_retries_from_cli_mode() -> None:
    portal = FakePortal(bind_error=RuntimeError("ditolak"))
    manager = ShortcutManager(portal=portal)
    assert manager.start() == "cli"

    portal.bind_error = None
    portal.bound = _bound()
    assert manager.start() == "portal"


# --- Bug 3: start() idempoten ---------------------------------------------------


def test_start_twice_does_not_rebind_or_duplicate_callback() -> None:
    portal = FakePortal(bound=_bound())
    manager = ShortcutManager(portal=portal, on_activated=lambda _sid: None)
    assert manager.start() == "portal"
    assert manager.start() == "portal"
    assert portal.calls.count("bind") == 1
    assert portal.calls.count("connect_activated") == 1


def test_connect_activated_ignores_duplicate_bound_method() -> None:
    class Router:
        def __init__(self) -> None:
            self.got: list[str] = []

        def on_shortcut(self, sid: str) -> None:
            self.got.append(sid)

    router = Router()
    portal = GlobalShortcutsPortal(bus=object())
    # Bound method dibuat baru pada tiap akses, tetapi sama menurut ``==``.
    portal.connect_activated(router.on_shortcut)
    portal.connect_activated(router.on_shortcut)

    portal._on_activated("/s", "translate", 1, {})
    assert router.got == ["translate"]


def test_stop_then_start_works_again() -> None:
    portal = FakePortal(bound=_bound())
    manager = ShortcutManager(portal=portal, on_activated=lambda _sid: None)
    manager.start()
    manager.stop()
    assert manager.active_backend == "cli"
    assert manager.start() == "portal"
    assert portal.calls.count("bind") == 2


def test_module_exports_unchanged() -> None:
    # API publik tidak boleh berubah (batasan sesi review).
    assert set(sc.__all__) == {
        "BoundShortcut",
        "GlobalShortcutsPortal",
        "ShortcutBackend",
        "ShortcutManager",
        "ShortcutSpec",
        "specs_from_settings",
    }
