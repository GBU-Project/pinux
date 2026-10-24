"""ShortcutManager.start_async: pengikatan portal tidak memblokir thread utama (Medium 8).

Portal palsu menahan ``bind()`` pada ``threading.Event`` sehingga tes dapat mengamati
keadaan selama dialog desktop "terbuka": thread tempat bind berjalan, status menunggu,
pembatalan oleh ``stop()``, dan penolakan pemanggilan ganda.
"""

from __future__ import annotations

import threading

from gi.repository import GLib

from pinux.portal import shortcuts as sc
from pinux.portal.shortcuts import BoundShortcut, ShortcutManager, ShortcutSpec

SPECS = (
    ShortcutSpec("translate", "T", "<Control><Alt>T"),
    ShortcutSpec("ocr", "O", "<Control><Alt>O"),
)


class GatedPortal:
    """Portal yang menahan bind() sampai tes melepaskannya."""

    def __init__(self, bound=None, error=None, available=True) -> None:
        self.bound = bound if bound is not None else [
            BoundShortcut("translate", "Ctrl+Alt+T", "translate"),
            BoundShortcut("ocr", "Ctrl+Alt+O", "ocr"),
        ]
        self.error = error
        self.available = available
        self.gate = threading.Event()
        self.entered = threading.Event()
        self.bind_thread: threading.Thread | None = None
        self.bind_calls = 0
        self.close_calls = 0

    def is_available(self) -> bool:
        return self.available

    def connect_activated(self, cb) -> None:
        pass

    def connect_closed(self, cb) -> None:
        pass

    def connect_shortcuts_changed(self, cb) -> None:
        pass

    def bind(self, specs, parent_window: str = ""):
        self.bind_calls += 1
        self.bind_thread = threading.current_thread()
        self.entered.set()
        assert self.gate.wait(5), "tes tidak melepaskan gerbang"
        if self.error is not None:
            raise self.error
        return list(self.bound)

    def close(self) -> None:
        self.close_calls += 1


def _pump_until(cond, timeout_s: float = 3.0) -> bool:
    ctx = GLib.MainContext.default()
    end = GLib.get_monotonic_time() + int(timeout_s * 1_000_000)
    while GLib.get_monotonic_time() < end:
        while ctx.pending():
            ctx.iteration(False)
        if cond():
            return True
        GLib.usleep(2000)
    return cond()


def _pump(ms: int = 150) -> None:
    _pump_until(lambda: False, ms / 1000)


def _manager(portal) -> tuple[ShortcutManager, list[tuple]]:
    manager = ShortcutManager(portal=portal, specs=SPECS)
    states: list[tuple] = []
    manager.connect_changed(
        lambda: states.append((manager.active_backend, manager.last_reason, threading.current_thread()))
    )
    return manager, states


def test_start_async_returns_immediately_while_bind_is_blocked() -> None:
    portal = GatedPortal()
    manager, _states = _manager(portal)
    done: list[str] = []

    assert manager.start_async(done.append) is True  # kembali walau bind masih menunggu

    assert portal.entered.wait(2)
    assert manager.last_reason == sc.REASON_PENDING
    assert done == []
    portal.gate.set()
    assert _pump_until(lambda: done)
    assert done == ["portal"] and manager.active_backend == "portal"
    assert manager.last_reason is None


def test_bind_runs_off_main_thread_and_state_changes_on_main_thread() -> None:
    portal = GatedPortal()
    manager, states = _manager(portal)
    done: list[str] = []
    manager.start_async(done.append)
    portal.gate.set()
    assert _pump_until(lambda: done)

    assert portal.bind_thread is not threading.main_thread()
    assert [(b, r) for b, r, _t in states] == [("cli", sc.REASON_PENDING), ("portal", None)]
    assert all(t is threading.main_thread() for _b, _r, t in states)


def test_main_loop_keeps_running_while_waiting() -> None:
    portal = GatedPortal()
    manager, _states = _manager(portal)
    manager.start_async()
    portal.entered.wait(2)

    ticks: list[int] = []
    GLib.timeout_add(10, lambda: (ticks.append(1), len(ticks) < 5)[1])
    assert _pump_until(lambda: len(ticks) >= 5), "main loop harus tetap berputar selama bind menunggu"
    portal.gate.set()
    _pump(100)


def test_rejected_bind_falls_back_to_cli_and_releases_session() -> None:
    portal = GatedPortal(bound=[])
    manager, _states = _manager(portal)
    done: list[str] = []
    manager.start_async(done.append)
    portal.gate.set()
    assert _pump_until(lambda: done)

    assert done == ["cli"] and manager.last_reason == sc.REASON_BIND_FAILED
    assert portal.close_calls == 1


def test_bind_exception_falls_back_to_cli() -> None:
    portal = GatedPortal(error=RuntimeError("portal rusak"))
    manager, _states = _manager(portal)
    done: list[str] = []
    manager.start_async(done.append)
    portal.gate.set()
    assert _pump_until(lambda: done)

    assert done == ["cli"] and manager.last_reason == sc.REASON_BIND_FAILED


def test_second_start_async_is_ignored_while_in_flight() -> None:
    portal = GatedPortal()
    manager, _states = _manager(portal)
    done: list[str] = []
    assert manager.start_async(done.append) is True
    portal.entered.wait(2)

    assert manager.start_async(done.append) is False
    assert manager.start() == "cli"  # start() sinkron tidak membuka bind kedua
    portal.gate.set()
    assert _pump_until(lambda: done)

    assert done == ["portal"] and portal.bind_calls == 1


def test_stop_cancels_pending_bind_and_closes_orphan_session() -> None:
    portal = GatedPortal()
    manager, _states = _manager(portal)
    done: list[str] = []
    manager.start_async(done.append)
    portal.entered.wait(2)

    manager.stop()
    closes_after_stop = portal.close_calls
    portal.gate.set()
    _pump(300)

    assert done == [], "hasil dari permintaan yang dibatalkan tidak boleh diterapkan"
    assert manager.active_backend == "cli" and manager.bound_shortcuts == ()
    assert portal.close_calls == closes_after_stop + 1, "sesi yatim ditutup"


def test_restart_after_stop_is_not_closed_by_old_worker() -> None:
    first = GatedPortal()
    manager, _states = _manager(first)
    manager.start_async()
    first.entered.wait(2)
    manager.stop()

    done: list[str] = []
    assert manager.start_async(done.append) is True  # pengikatan baru berjalan
    closes = first.close_calls
    first.gate.set()
    assert _pump_until(lambda: done)

    assert first.close_calls == closes, "pekerja lama tidak boleh menutup sesi milik pengikatan baru"


def test_start_async_without_portal_completes_immediately() -> None:
    portal = GatedPortal(available=False)
    manager, _states = _manager(portal)
    done: list[str] = []

    assert manager.start_async(done.append) is True

    assert done == ["cli"] and portal.bind_calls == 0
    assert manager.last_reason == sc.REASON_PORTAL_UNAVAILABLE


def test_start_async_when_already_active_is_idempotent() -> None:
    portal = GatedPortal()
    portal.gate.set()
    manager, states = _manager(portal)
    manager.start()
    count = len(states)
    done: list[str] = []

    manager.start_async(done.append)

    assert done == ["portal"] and portal.bind_calls == 1 and len(states) == count


def test_on_done_exception_is_contained() -> None:
    portal = GatedPortal()
    portal.gate.set()
    manager, _states = _manager(portal)

    def boom(_backend) -> None:
        raise RuntimeError("callback rusak")

    manager.start_async(boom)
    assert _pump_until(lambda: manager.active_backend == "portal")
    _pump(100)
    assert manager.start_async() is True  # manajer tidak macet setelah callback gagal
