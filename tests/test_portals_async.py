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


class SequencedPortal(GatedPortal):
    """Portal dengan gerbang terpisah untuk tiap panggilan bind(): urutan selesai ditentukan tes."""

    def __init__(self, calls: int = 2, **kwargs) -> None:
        super().__init__(**kwargs)
        self.gates = [threading.Event() for _ in range(calls)]
        self.entered_n = [threading.Event() for _ in range(calls)]
        self._n = 0
        self._n_lock = threading.Lock()

    def bind(self, specs, parent_window: str = ""):
        with self._n_lock:
            n = self._n
            self._n += 1
        self.bind_calls += 1
        self.entered_n[n].set()
        assert self.gates[n].wait(5), f"tes tidak melepaskan gerbang {n}"
        return list(self.bound)


def _restart_during_pending_bind(portal: SequencedPortal):
    """Bind #1 tertahan, stop(), lalu start_async() kedua: dua pekerja hidup bersamaan."""
    manager, _states = _manager(portal)
    manager.start_async()
    assert portal.entered_n[0].wait(2)
    manager.stop()
    done: list[str] = []
    assert manager.start_async(done.append) is True
    assert portal.entered_n[1].wait(2)
    return manager, done


def test_stale_worker_finishing_first_does_not_close_newer_bind() -> None:
    portal = SequencedPortal()
    manager, done = _restart_during_pending_bind(portal)
    closes = portal.close_calls

    portal.gates[0].set()  # pekerja lama selesai lebih dulu, pengikatan baru masih berjalan
    _pump(150)
    assert portal.close_calls == closes, "pekerja lama tidak boleh menutup sesi milik pengikatan baru"
    assert done == []

    portal.gates[1].set()
    assert _pump_until(lambda: done)
    assert done == ["portal"] and manager.active_backend == "portal"
    assert portal.close_calls == closes


def test_stale_worker_finishing_after_newer_bind_succeeded_keeps_session() -> None:
    portal = SequencedPortal()
    manager, done = _restart_during_pending_bind(portal)

    portal.gates[1].set()  # pengikatan baru selesai lebih dulu dan berhasil
    assert _pump_until(lambda: done)
    assert manager.active_backend == "portal"
    closes = portal.close_calls

    portal.gates[0].set()  # pekerja lama baru selesai: hasilnya hanya dibuang
    _pump(300)

    assert portal.close_calls == closes, "sesi yang baru berhasil diikat tidak boleh ditutup pekerja lama"
    assert manager.active_backend == "portal" and len(manager.bound_shortcuts) == 2


def test_stale_worker_after_newer_bind_failed_still_cleans_up_quietly() -> None:
    portal = SequencedPortal(bound=[])
    manager, done = _restart_during_pending_bind(portal)

    portal.gates[1].set()
    assert _pump_until(lambda: done)
    assert done == ["cli"]

    portal.gates[0].set()
    _pump(200)

    assert manager.active_backend == "cli"  # tidak melempar dan keadaan tetap konsisten


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


def test_start_async_from_worker_thread_warns(caplog) -> None:
    import logging

    portal = GatedPortal(available=False)
    manager, _states = _manager(portal)

    with caplog.at_level(logging.WARNING, logger="pinux.portal.shortcuts"):
        t = threading.Thread(target=manager.start_async)
        t.start()
        t.join(2)

    assert any("bukan thread utama" in r.getMessage() for r in caplog.records)
