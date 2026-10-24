"""Uji akhir sesi portal GlobalShortcuts: Closed, ShortcutsChanged, restart portal, close().

Memakai bus palsu yang merekam langganan sinyal dan pemantau nama bus, sehingga
perilaku sebenarnya (bukan sekadar ``MagicMock``) dapat diperiksa tanpa D-Bus.

Perujuk: R1.2, R1.3, R8.3 pada requirements.md.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from pinux.portal import shortcuts as sc
from pinux.portal.shortcuts import (
    BoundShortcut,
    GlobalShortcutsPortal,
    ShortcutManager,
    ShortcutSpec,
    describe_fallback,
)

SESSION = "/org/freedesktop/portal/desktop/session/1_7/pinux"
SPECS = (
    ShortcutSpec("translate", "T", "<Control><Alt>T"),
    ShortcutSpec("ocr", "O", "<Control><Alt>O"),
)


class FakeMatch:
    def __init__(self) -> None:
        self.removed = False

    def remove(self) -> None:
        self.removed = True


class FakeWatch:
    def __init__(self, callback) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class FakeBus:
    """Bus D-Bus palsu: merekam langganan, pemantau nama, dan panggilan get_object."""

    def __init__(self) -> None:
        self.receivers: list[tuple] = []  # (handler, signal, interface, path, match)
        self.removed_receivers: list[tuple] = []
        self.watches: list[FakeWatch] = []
        self.get_object_calls: list[tuple] = []

    def get_unique_name(self) -> str:
        return ":1.7"

    def add_signal_receiver(self, handler, signal_name=None, dbus_interface=None, path=None):
        match = FakeMatch()
        self.receivers.append((handler, signal_name, dbus_interface, path, match))
        return match

    def remove_signal_receiver(self, handler, signal_name=None, dbus_interface=None, path=None):
        self.removed_receivers.append((signal_name, dbus_interface))

    def watch_name_owner(self, name, callback):
        watch = FakeWatch(callback)
        self.watches.append(watch)
        return watch

    def get_object(self, name, path, introspect=True):
        self.get_object_calls.append((name, path, introspect))
        return object()

    def handler(self, signal_name: str):
        for handler, signal, _iface, _path, _m in self.receivers:
            if signal == signal_name:
                return handler
        raise AssertionError(f"tidak ada penerima untuk sinyal {signal_name}")

    def signals(self) -> list[str]:
        return [signal for _h, signal, *_ in self.receivers]


class SessionRecorder:
    """Pengganti dbus.Interface(Session) yang merekam Close()."""

    def __init__(self, error: Exception | None = None) -> None:
        self.close_calls: list[dict] = []
        self.error = error

    def Close(self, **kwargs) -> None:  # noqa: N802 (nama D-Bus)
        self.close_calls.append(kwargs)
        if self.error is not None:
            raise self.error


def _portal(bus: FakeBus | None = None) -> tuple[GlobalShortcutsPortal, FakeBus]:
    bus = bus or FakeBus()
    portal = GlobalShortcutsPortal(bus=bus)
    portal._ensure_registered = lambda: None
    return portal, bus


def _create(portal: GlobalShortcutsPortal, handle: str = SESSION) -> str | None:
    with patch.object(sc, "portal_request", return_value=(0, {"session_handle": handle})), \
         patch("dbus.Interface"):
        return portal.create_session()


# --- Langganan sesi -------------------------------------------------------------


def test_create_session_watches_closed_changed_and_owner() -> None:
    portal, bus = _portal()
    assert _create(portal) == SESSION

    assert sorted(bus.signals()) == ["Closed", "ShortcutsChanged"]
    closed = next(r for r in bus.receivers if r[1] == "Closed")
    assert closed[2] == sc.SESSION_INTERFACE and closed[3] == SESSION
    assert len(bus.watches) == 1


def test_connect_closed_is_idempotent() -> None:
    portal, _bus = _portal()
    seen: list[str] = []
    portal.connect_closed(seen.append)
    portal.connect_closed(seen.append)
    _create(portal)
    portal._on_session_closed({})
    assert seen == [sc.REASON_SESSION_CLOSED]


# --- Session.Closed ---------------------------------------------------------------


def test_session_closed_signal_notifies_and_clears_state() -> None:
    portal, bus = _portal()
    seen: list[str] = []
    portal.connect_closed(seen.append)
    _create(portal)

    bus.handler("Closed")({"reason": 1})

    assert seen == [sc.REASON_SESSION_CLOSED]
    assert portal._session_path is None
    assert all(r[4].removed for r in bus.receivers), "semua langganan harus dilepas"
    assert bus.watches[0].cancelled


def test_closed_signal_is_ignored_after_our_own_close() -> None:
    portal, bus = _portal()
    seen: list[str] = []
    portal.connect_closed(seen.append)
    _create(portal)

    with patch("dbus.Interface", return_value=SessionRecorder()):
        portal.close()
    bus.handler("Closed")({})  # sinyal susulan tidak boleh dianggap sesi mati mendadak

    assert seen == []


def test_new_session_after_closed_resubscribes() -> None:
    portal, bus = _portal()
    _create(portal)
    bus.handler("Closed")({})
    before = len(bus.receivers)

    assert _create(portal, "/s/baru") == "/s/baru"

    assert len(bus.receivers) == before + 2
    assert len(bus.watches) == 2


# --- Restart portal -----------------------------------------------------------------


def test_portal_restart_detected_via_name_owner() -> None:
    portal, bus = _portal()
    seen: list[str] = []
    portal.connect_closed(seen.append)
    _create(portal)
    owner = bus.watches[0].callback

    owner(":1.5")  # panggilan awal dbus-python dengan pemilik saat ini
    assert seen == []

    owner("")  # portal berhenti tanpa mengirim Closed
    assert seen == [sc.REASON_PORTAL_STOPPED]
    assert portal._session_path is None


def test_owner_initially_empty_is_not_a_restart() -> None:
    portal, bus = _portal()
    seen: list[str] = []
    portal.connect_closed(seen.append)
    _create(portal)

    bus.watches[0].callback("")  # belum pernah melihat pemilik

    assert seen == []


def test_owner_loss_without_session_is_ignored() -> None:
    portal, _bus = _portal()
    seen: list[str] = []
    portal.connect_closed(seen.append)
    portal._on_portal_owner_changed(":1.5")
    portal._on_portal_owner_changed("")
    assert seen == []


def test_closed_callback_error_does_not_break_others() -> None:
    portal, bus = _portal()
    seen: list[str] = []

    def boom(_reason: str) -> None:
        raise RuntimeError("rusak")

    portal.connect_closed(boom)
    portal.connect_closed(seen.append)
    _create(portal)
    bus.handler("Closed")({})
    assert seen == [sc.REASON_SESSION_CLOSED]


# --- ShortcutsChanged -----------------------------------------------------------------


def test_shortcuts_changed_parses_and_filters_by_session() -> None:
    portal, bus = _portal()
    got: list[list[BoundShortcut]] = []
    portal.connect_shortcuts_changed(got.append)
    _create(portal)
    handler = bus.handler("ShortcutsChanged")

    handler("/sesi/lain", [("translate", {"trigger_description": "Ctrl+X"})])
    assert got == []

    handler(SESSION, [("translate", {"trigger_description": "Ctrl+Shift+T"}), "rusak"])
    assert [(b.id, b.trigger) for b in got[0]] == [("translate", "Ctrl+Shift+T")]


def test_shortcuts_changed_without_session_is_ignored() -> None:
    portal, _bus = _portal()
    got: list = []
    portal.connect_shortcuts_changed(got.append)
    portal._on_shortcuts_changed(SESSION, [("translate", {"trigger_description": "x"})])
    assert got == []


# --- close(): berbatas waktu dan idempoten --------------------------------------------


def test_close_is_bounded_without_introspection() -> None:
    portal, bus = _portal()
    _create(portal)
    recorder = SessionRecorder()

    with patch("dbus.Interface", return_value=recorder):
        portal.close()

    assert recorder.close_calls == [{"timeout": sc.CLOSE_TIMEOUT_S}]
    assert bus.get_object_calls[-1] == (sc.PORTAL_BUS_NAME, SESSION, False)
    assert sc.CLOSE_TIMEOUT_S <= 5


def test_close_removes_all_subscriptions() -> None:
    portal, bus = _portal()
    _create(portal)
    with patch("dbus.Interface", return_value=SessionRecorder()):
        portal.close()
    assert all(r[4].removed for r in bus.receivers)
    assert bus.watches[0].cancelled


def test_close_is_idempotent_and_never_raises() -> None:
    portal, _bus = _portal()
    _create(portal)
    recorder = SessionRecorder(error=TimeoutError("portal hang"))

    with patch("dbus.Interface", return_value=recorder):
        portal.close()  # Close gagal: tidak boleh melempar
        portal.close()  # kedua kali: tanpa panggilan lagi

    assert len(recorder.close_calls) == 1
    assert portal._session_path is None


# --- ShortcutManager ---------------------------------------------------------------------


class ManagerPortal:
    """Portal palsu untuk manajer: menyimpan callback agar bisa dipicu tes."""

    def __init__(self, bound: list[BoundShortcut] | None = None) -> None:
        self.bound = bound if bound is not None else []
        self.closed_cb = None
        self.changed_cb = None
        self.close_error: Exception | None = None
        self.bind_calls = 0

    def is_available(self) -> bool:
        return True

    def connect_activated(self, cb) -> None:
        pass

    def connect_closed(self, cb) -> None:
        self.closed_cb = cb

    def connect_shortcuts_changed(self, cb) -> None:
        self.changed_cb = cb

    def bind(self, specs, parent_window: str = ""):
        self.bind_calls += 1
        return list(self.bound)

    def close(self) -> None:
        if self.close_error is not None:
            raise self.close_error


def _bound(*pairs: tuple[str, str]) -> list[BoundShortcut]:
    return [BoundShortcut(id=i, trigger=t, activation_token=i) for i, t in pairs]


def _manager(portal: ManagerPortal | None = None) -> tuple[ShortcutManager, ManagerPortal, list[int]]:
    portal = portal or ManagerPortal(_bound(("translate", "Ctrl+Alt+T"), ("ocr", "Ctrl+Alt+O")))
    manager = ShortcutManager(portal=portal, specs=SPECS)
    notified: list[int] = []
    manager.connect_changed(lambda: notified.append(1))
    return manager, portal, notified


def test_manager_falls_back_to_cli_when_session_closes() -> None:
    manager, portal, notified = _manager()
    assert manager.start() == "portal"

    portal.closed_cb(sc.REASON_SESSION_CLOSED)

    assert manager.active_backend == "cli"
    assert manager.last_reason == sc.REASON_SESSION_CLOSED
    assert manager.bound_shortcuts == ()
    assert manager.missing_shortcuts == ("translate", "ocr")
    assert notified == [1]


def test_manager_reports_portal_stopped_reason() -> None:
    manager, portal, _ = _manager()
    manager.start()
    portal.closed_cb(sc.REASON_PORTAL_STOPPED)
    assert manager.last_reason == sc.REASON_PORTAL_STOPPED


def test_closed_in_cli_mode_is_ignored() -> None:
    portal = ManagerPortal(bound=[])  # bind kosong -> CLI
    manager, _, notified = _manager(portal)
    manager.start()
    reason = manager.last_reason

    portal.closed_cb(sc.REASON_SESSION_CLOSED)

    assert manager.last_reason == reason and notified == []


def test_manager_can_rebind_after_session_closed() -> None:
    manager, portal, _ = _manager()
    manager.start()
    portal.closed_cb(sc.REASON_SESSION_CLOSED)

    assert manager.start() == "portal"
    assert manager.last_reason is None
    assert portal.bind_calls == 2


def test_shortcuts_changed_updates_trigger_and_notifies() -> None:
    manager, portal, notified = _manager()
    manager.start()

    portal.changed_cb(_bound(("translate", "Ctrl+Shift+T")))

    triggers = {b.id: b.trigger for b in manager.bound_shortcuts}
    assert triggers == {"translate": "Ctrl+Shift+T", "ocr": "Ctrl+Alt+O"}
    assert notified == [1]
    assert manager.active_backend == "portal"


def test_shortcuts_changed_ignores_unknown_same_and_empty() -> None:
    manager, portal, notified = _manager()
    manager.start()

    portal.changed_cb(_bound(("tidak-dikenal", "Ctrl+Z")))
    portal.changed_cb(_bound(("translate", "Ctrl+Alt+T")))  # sama
    portal.changed_cb(_bound(("translate", "")))  # kosong

    assert notified == []
    assert {b.id: b.trigger for b in manager.bound_shortcuts}["translate"] == "Ctrl+Alt+T"


def test_changed_not_fired_by_start_or_stop_and_errors_are_contained() -> None:
    manager, portal, notified = _manager()
    manager.connect_changed(lambda: (_ for _ in ()).throw(RuntimeError("rusak")))
    manager.start()
    manager.stop()
    assert notified == []

    manager.start()
    portal.closed_cb(sc.REASON_SESSION_CLOSED)  # callback rusak tidak boleh menghentikan yang lain
    assert notified == [1]


def test_connect_changed_is_idempotent() -> None:
    manager, portal, _ = _manager()
    seen: list[int] = []

    def cb() -> None:
        seen.append(1)

    manager.connect_changed(cb)
    manager.connect_changed(cb)
    manager.start()
    portal.closed_cb(sc.REASON_SESSION_CLOSED)
    assert seen == [1]


def test_stop_swallows_portal_close_error_and_resets_state() -> None:
    manager, portal, _ = _manager()
    manager.start()
    portal.close_error = OSError("bus hilang")

    manager.stop()  # tidak boleh melempar

    assert manager.active_backend == "cli"
    assert manager.bound_shortcuts == ()
    manager.stop()  # idempoten


@pytest.mark.parametrize("reason", ["session_closed", "portal_stopped"])
def test_fallback_text_for_closed_reasons_is_specific(reason: str) -> None:
    text = describe_fallback(reason)
    assert "Mulai ulang Pinux" in text
    assert text != describe_fallback(sc.REASON_BIND_FAILED)
    assert text != describe_fallback(None)
