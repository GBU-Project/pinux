"""Integrasi TTS: ``spd-say`` palsu dengan "daemon" bersama.

Dipisahkan dari ``test_tts_cancel_order.py`` karena tes ini menjalankan proses
sungguhan (skrip ``spd-say`` di ``tmp_path``) dan mengulang 10 kali untuk
memburu balapan urutan. Tes unit di berkas pasangannya cukup memakai subprocess
palsu, sehingga cepat dan deterministik.

Berkas ini mandiri: tidak mengimpor apa pun dari ``test_tts_cancel_order.py``.
"""

from __future__ import annotations

import stat
import sys
import time
from pathlib import Path

import pytest

from pinux.tts import TtsEngine

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


def _wait(cond, timeout_s: float = 3.0) -> bool:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return cond()


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
