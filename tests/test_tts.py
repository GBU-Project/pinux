"""Tes TtsEngine dengan perintah palsu (skrip shell yang merekam argumen dan stdin)."""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path

import pytest

from pinux.tts import TtsEngine, build_command


def _fake(bin_dir: Path, name: str, record: Path, *, sleep: float = 0.0) -> None:
    script = bin_dir / name
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{record}.args"\n'
        f'cat > "{record}.stdin"\n'
        f"sleep {sleep}\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def _wait_for(path: Path, timeout: float = 3.0) -> str:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if path.exists() and path.read_text():
            return path.read_text()
        time.sleep(0.02)
    raise AssertionError(f"{path} tidak muncul")


def _which_in(bin_dir: Path):
    def which(name: str) -> str | None:
        p = bin_dir / name
        return str(p) if p.exists() else None

    return which


def test_unavailable_when_no_backend(tmp_path):
    eng = TtsEngine(which=lambda name: None)
    assert not eng.available and eng.backend_name is None
    assert eng.speak("halo", "id") is False


def test_prefers_spd_say_over_espeak(tmp_path):
    for n in ("espeak-ng", "spd-say"):
        (tmp_path / n).write_text("#!/bin/sh\n")
    assert TtsEngine(which=_which_in(tmp_path)).backend_name == "spd-say"
    (tmp_path / "spd-say").unlink()
    assert TtsEngine(which=_which_in(tmp_path)).backend_name == "espeak-ng"


def test_speak_passes_text_via_stdin_and_lang(tmp_path):
    rec = tmp_path / "rec"
    _fake(tmp_path, "spd-say", rec)
    eng = TtsEngine(which=_which_in(tmp_path))
    assert eng.speak("-halo dunia", "id") is True
    assert _wait_for(Path(f"{rec}.stdin")) == "-halo dunia"
    args = _wait_for(Path(f"{rec}.args")).split()
    assert args == ["-e", "-w", "-l", "id"]  # teks tidak muncul sebagai argumen


def test_empty_text_not_spoken(tmp_path):
    _fake(tmp_path, "spd-say", tmp_path / "rec")
    assert TtsEngine(which=_which_in(tmp_path)).speak("   ", "id") is False


def test_text_truncated_to_max_chars(tmp_path):
    rec = tmp_path / "rec"
    _fake(tmp_path, "espeak-ng", rec)
    TtsEngine(which=_which_in(tmp_path), max_chars=5).speak("abcdefghij", "en")
    assert _wait_for(Path(f"{rec}.stdin")) == "abcde"


def test_new_speech_stops_previous_and_stop_kills(tmp_path):
    _fake(tmp_path, "spd-say", tmp_path / "rec", sleep=30)
    eng = TtsEngine(which=_which_in(tmp_path))
    eng.speak("satu", "id")
    first = eng._proc
    assert first is not None
    eng.speak("dua", "id")
    assert first.poll() is not None  # yang lama dihentikan
    second = eng._proc
    eng.stop()
    assert second.poll() is not None and eng._proc is None


@pytest.mark.parametrize(
    "lang,expected",
    [("id", "id"), (None, "en"), ("auto", "en"), ("pt_BR", "pt-br"), ("../x;rm", "en")],
)
def test_lang_is_sanitised(lang, expected):
    assert build_command("spd-say", ("-l", "{lang}"), lang)[-1] == expected


def test_missing_binary_returns_false(tmp_path):
    eng = TtsEngine(which=lambda n: str(tmp_path / "nope") if n == "spd-say" else None)
    assert eng.available and eng.speak("halo", "id") is False
