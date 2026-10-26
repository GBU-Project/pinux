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

#: Batas tunggu ``spd-say -C`` sebelum teks ucapan baru tetap dikirim (detik).
CANCEL_WAIT_S: Final[float] = 1.5

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
        # Pembatalan spd-say (-C) yang masih berjalan; ucapan baru menunggunya (lihat speak).
        self._pending_cancels: list[threading.Event] = []
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

    @property
    def is_speaking(self) -> bool:
        """Apakah ada proses TTS yang saat ini sedang berbicara."""
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

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
            # Pembatalan yang dimulai oleh _stop_locked() di atas (dan yang lebih lama).
            waits = [e for e in self._pending_cancels if not e.is_set()]
            self._pending_cancels = waits
        if len(text) > self._max_chars:
            logger.info("Teks TTS dipotong ke %d karakter (dari %d)", self._max_chars, len(text))
        data = text[: self._max_chars].encode("utf-8")
        if waits:
            # spd-say baru mengirim pesan ke daemon setelah membaca stdin, jadi menunda
            # penulisan teks menjamin ``spd-say -C`` milik ucapan lama tiba lebih dulu dan
            # tidak membatalkan ucapan baru, tanpa memblokir thread pemanggil.
            threading.Thread(
                target=self._feed_after, args=(proc, data, waits), daemon=True
            ).start()
        else:
            self._feed(proc, data)
        return True

    @staticmethod
    def _feed(proc: subprocess.Popen[bytes], data: bytes) -> None:
        try:
            assert proc.stdin is not None
            proc.stdin.write(data)
            proc.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            # Proses berhenti sebelum membaca (mis. dihentikan oleh speak berikutnya).
            pass

    def _feed_after(
        self, proc: subprocess.Popen[bytes], data: bytes, waits: Sequence[threading.Event]
    ) -> None:
        for done in waits:
            done.wait(CANCEL_WAIT_S)
        self._feed(proc, data)

    def stop(self) -> None:
        """Hentikan ucapan yang sedang berjalan."""
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            # Hentikan proses secara langsung
            if proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=0.2)
                except (OSError, subprocess.TimeoutExpired):
                    pass

            # Bersihkan dan tunggu proses di thread latar agar UI tidak freeze
            def _reap_proc(p: subprocess.Popen) -> None:
                try:
                    p.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    try:
                        p.kill()
                        p.wait(timeout=1.0)
                    except Exception:
                        pass
                except Exception:
                    pass

            threading.Thread(target=_reap_proc, args=(proc,), daemon=True).start()

            # Pada backend spd-say, proses klien spd-say hanya mengirim pesan ke daemon speech-dispatcher.
            # Untuk menghentikan suara audio yang sedang dimainkan oleh daemon:
            if self._backend is not None and self._backend[0] == "spd-say":
                cancel_done = threading.Event()
                self._pending_cancels.append(cancel_done)

                def _cancel_spd() -> None:
                    try:
                        subprocess.run(
                            [self._binary or "spd-say", "-C"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=1,
                            check=False,
                        )
                    except Exception:
                        pass
                    finally:
                        cancel_done.set()

                threading.Thread(target=_cancel_spd, daemon=True).start()


