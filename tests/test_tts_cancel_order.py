"""Ucapan baru tidak boleh dibatalkan oleh ``spd-say -C`` milik ucapan lama.

``spd-say`` hanya klien speech-dispatcher: menghentikan prosesnya tidak menghentikan suara
di daemon, sehingga ``TtsEngine`` menjalankan ``spd-say -C`` di thread latar. Dahulu ``-C``
dan ``spd-say`` baru berlomba menuju daemon; bila ``-C`` tiba terakhir, ucapan baru ikut
terbatalkan. Kini teks ucapan baru ditulis ke stdin (saat itulah ``spd-say -e`` mengirim
pesan) hanya setelah pembatalan yang tertunda selesai.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

import pytest

import pinux.tts as tts
from pinux.tts import TtsEngine


class FakeStdin:
    def __init__(self, proc: "FakeProc") -> None:
        self.proc = proc
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        if self.proc.terminated or self.closed:
            raise BrokenPipeError("proses sudah berhenti")
        self.writes.append(data)
        self.proc.events.append(("write", self.proc.name, data))

    def close(self) -> None:
        self.closed = True


class FakeProc:
    def __init__(self, name: str, events: list) -> None:
        self.name = name
        self.events = events
        self.terminated = False
        self.stdin = FakeStdin(self)

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout=None) -> int:
        return 0

    def kill(self) -> None:
        self.terminated = True


class World:
    """subprocess palsu: Popen merekam proses; run (``spd-say -C``) menunggu tes melepasnya."""

    def __init__(self) -> None:
        self.events: list = []
        self.procs: list[FakeProc] = []
        self.cancel_gates: list[threading.Event] = []
        self.cancel_error: Exception | None = None
        self.auto_release = False

    def Popen(self, cmd, **_kw):  # noqa: N802 - meniru subprocess.Popen
        proc = FakeProc(f"p{len(self.procs) + 1}", self.events)
        self.procs.append(proc)
        return proc

    def run(self, cmd, **_kw):
        gate = threading.Event()
        self.cancel_gates.append(gate)
        self.events.append(("cancel-start", len(self.cancel_gates)))
        if not self.auto_release:
            gate.wait(5)
        self.events.append(("cancel-done", len(self.cancel_gates)))
        if self.cancel_error is not None:
            raise self.cancel_error
        return types.SimpleNamespace(returncode=0)


@pytest.fixture
def world(monkeypatch) -> World:
    w = World()
    fake = types.SimpleNamespace(
        Popen=w.Popen,
        run=w.run,
        TimeoutExpired=subprocess.TimeoutExpired,
        DEVNULL=subprocess.DEVNULL,
        PIPE=subprocess.PIPE,
    )
    monkeypatch.setattr(tts, "subprocess", fake)
    return w


def _spd() -> TtsEngine:
    return TtsEngine(which=lambda n: "/bin/spd-say" if n == "spd-say" else None)


def _wait(cond, timeout_s: float = 3.0) -> bool:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return cond()


def test_new_speech_text_waits_for_pending_cancel(world: World) -> None:
    eng = _spd()
    assert eng.speak("A", "id") is True
    assert world.procs[0].stdin.writes == [b"A"], "tanpa ucapan lama, teks langsung ditulis"

    assert eng.speak("B", "id") is True
    assert _wait(lambda: world.cancel_gates), "spd-say -C dijalankan untuk ucapan lama"
    time.sleep(0.1)
    assert world.procs[1].stdin.writes == [], "teks B tidak boleh mendahului pembatalan"

    world.cancel_gates[0].set()
    assert _wait(lambda: world.procs[1].stdin.writes == [b"B"])
    order = [e[0] for e in world.events]
    assert order.index("cancel-done") < order.index("write", order.index("cancel-done")), world.events


def test_speak_returns_without_waiting_for_cancel(world: World) -> None:
    eng = _spd()
    eng.speak("A", "id")

    start = time.monotonic()
    eng.speak("B", "id")

    assert time.monotonic() - start < 0.5, "pemanggil (thread UI) tidak boleh menunggu spd-say -C"
    world.cancel_gates[0].set()


def test_all_older_cancels_are_awaited(world: World) -> None:
    eng = _spd()
    eng.speak("A", "id")
    eng.speak("B", "id")
    eng.speak("C", "id")
    assert _wait(lambda: len(world.cancel_gates) == 2)

    world.cancel_gates[0].set()  # hanya pembatalan pertama selesai
    time.sleep(0.15)
    assert world.procs[2].stdin.writes == [], "C harus menunggu kedua pembatalan"

    world.cancel_gates[1].set()
    assert _wait(lambda: world.procs[2].stdin.writes == [b"C"])


def test_failed_cancel_still_delivers_speech(world: World) -> None:
    world.auto_release = True
    world.cancel_error = subprocess.TimeoutExpired("spd-say", 1)
    eng = _spd()
    eng.speak("A", "id")
    eng.speak("B", "id")

    assert _wait(lambda: world.procs[1].stdin.writes == [b"B"]), "galat pembatalan tidak boleh membisukan B"


def test_hung_cancel_is_bounded(world: World, monkeypatch) -> None:
    monkeypatch.setattr(tts, "CANCEL_WAIT_S", 0.2)
    eng = _spd()
    eng.speak("A", "id")
    eng.speak("B", "id")  # spd-say -C tidak pernah selesai

    assert _wait(lambda: world.procs[1].stdin.writes == [b"B"], 2.0), "batas tunggu harus melepas ucapan"
    world.cancel_gates[0].set()


def test_stop_before_delayed_write_is_harmless(world: World, recwarn) -> None:
    eng = _spd()
    eng.speak("A", "id")
    eng.speak("B", "id")
    eng.stop()  # B dihentikan sebelum teksnya sempat ditulis

    for gate in list(world.cancel_gates):
        gate.set()
    _wait(lambda: len(world.cancel_gates) >= 2)
    for gate in list(world.cancel_gates):
        gate.set()
    time.sleep(0.2)

    assert world.procs[1].stdin.writes == []
    assert not [w for w in recwarn if "thread" in str(w.category).lower()], "thread latar tidak boleh melempar"


def test_non_spd_backend_writes_immediately_and_never_cancels(world: World) -> None:
    eng = TtsEngine(which=lambda n: "/bin/espeak-ng" if n == "espeak-ng" else None)
    eng.speak("A", "id")
    eng.speak("B", "id")

    assert world.procs[1].stdin.writes == [b"B"]
    assert world.cancel_gates == []


# --- Integrasi: spd-say palsu dengan "daemon" bersama (urutan kedatangan di satu log) --------

FAKE_SPD = '''#!{python}
import fcntl, os, sys, time
LOG = os.environ["FAKE_SPD_LOG"]

def append(line):
    with open(LOG, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        n = len(f.read().splitlines())
        f.write(line + "\\n")
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)
    return n

if "-C" in sys.argv:
    append("CANCEL")
    sys.exit(0)

text = sys.stdin.read().strip()
append("SAY " + text)
time.sleep(0.3)
'''


@pytest.mark.parametrize("trial", range(10))
def test_fake_daemon_never_cancels_the_new_speech(tmp_path: Path, monkeypatch, trial: int) -> None:
    script = tmp_path / "spd-say"
    script.write_text(FAKE_SPD.format(python=sys.executable))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "daemon.log"
    log.write_text("")
    monkeypatch.setenv("FAKE_SPD_LOG", str(log))
    eng = TtsEngine(which=lambda n: str(script) if n == "spd-say" else None)

    eng.speak("A", "id")
    assert _wait(lambda: "SAY A" in log.read_text())
    eng.speak("B", "id")
    assert _wait(lambda: "SAY B" in log.read_text(), 5.0)
    time.sleep(0.4)  # beri waktu pembatalan yang terlambat tiba

    lines = log.read_text().splitlines()
    say_b = lines.index("SAY B")
    assert "CANCEL" not in lines[say_b + 1:], f"ucapan B dibatalkan oleh -C lama: {lines}"
