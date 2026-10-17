"""Text-to-speech lewat perintah sistem (speech-dispatcher atau espeak-ng).

Teks dikirim lewat stdin (bukan argumen) agar teks yang diawali ``-`` tidak
dianggap opsi. Hanya satu ucapan aktif; memulai yang baru menghentikan yang lama.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from collections.abc import Callable, Sequence
from typing import Final

__all__ = ["BACKENDS", "TtsEngine", "build_command"]

logger = logging.getLogger(__name__)

#: Urutan preferensi: (nama perintah, template argumen; ``{lang}`` diganti kode bahasa).
BACKENDS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("spd-say", ("-e", "-w", "-l", "{lang}")),
    ("espeak-ng", ("--stdin", "-v", "{lang}")),
    ("espeak", ("--stdin", "-v", "{lang}")),
)


def _safe_lang(lang: str | None) -> str:
    """Kode bahasa aman untuk argumen (huruf/angka/tanda hubung); bawaan ``en``."""
    code = (lang or "").strip().lower().replace("_", "-")
    if not code or code == "auto" or not all(c.isalnum() or c == "-" for c in code):
        return "en"
    return code


def build_command(binary: str, template: Sequence[str], lang: str | None) -> list[str]:
    """Susun daftar argumen perintah untuk ``binary``."""
    code = _safe_lang(lang)
    return [binary, *(arg.replace("{lang}", code) for arg in template)]


class TtsEngine:
    """Pengucap teks; ``available`` bernilai False bila tak ada perintah TTS terpasang."""

    def __init__(
        self,
        *,
        which: Callable[[str], str | None] = shutil.which,
        max_chars: int = 2000,
    ) -> None:
        self._max_chars = max_chars
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._backend: tuple[str, tuple[str, ...]] | None = None
        self._binary: str | None = None
        for name, template in BACKENDS:
            found = which(name)
            if found:
                self._backend = (name, template)
                self._binary = found
                break

    @property
    def available(self) -> bool:
        return self._backend is not None

    @property
    def backend_name(self) -> str | None:
        return self._backend[0] if self._backend else None

    def speak(self, text: str, lang: str | None = None) -> bool:
        """Ucapkan ``text``; kembalikan False bila tidak ada TTS atau teks kosong."""
        text = text.strip()
        if not text or self._backend is None:
            return False
        name, template = self._backend
        cmd = build_command(self._binary or name, template, lang)
        with self._lock:
            self._stop_locked()
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                logger.warning("TTS gagal dijalankan (%s): %s", name, exc)
                return False
            self._proc = proc
        try:
            assert proc.stdin is not None
            proc.stdin.write(text[: self._max_chars].encode("utf-8"))
            proc.stdin.close()
        except (OSError, ValueError):
            # Proses berhenti sebelum membaca (mis. dihentikan oleh speak berikutnya).
            pass
        return True

    def stop(self) -> None:
        """Hentikan ucapan yang sedang berjalan."""
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
