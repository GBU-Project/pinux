"""Klien proses pekerja OCR (OcrWorkerClient).

Mengelola siklus hidup subproses ``pinux-ocr-worker``:
- Penjalanan proses secara malas (lazy spawning)
- Penghentian proses otomatis setelah 5 menit tanpa aktivitas
- Pemeriksaan ketersediaan OCR tanpa mengimpor onnxruntime di proses utama (R7.5 / Properti 7)
- Pembatalan permintaan aktif via SIGTERM dan penjalanan ulang bila perlu
- Penanganan galat proses dan konversi respons JSON ke OcrResult

Perujuk: task 13, R7.1, R7.2, R7.3, R7.4, R7.5, R6.5.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final

from pinux.ocr.base import OcrLine, OcrResult
from pinux.ocr.protocol import (
    decode_message,
    encode_ensure_model_request,
    encode_recognize_request,
)
from pinux.scheduler import CancelToken

__all__ = ["OcrWorkerClient", "is_ocr_available"]

logger = logging.getLogger("pinux.ocr.client")

IDLE_TIMEOUT_SECONDS: Final[float] = 300.0  # 5 menit tanpa aktivitas
#: Batas waktu satu pengenalan, termasuk pemuatan model pada permintaan pertama.
RECOGNIZE_TIMEOUT_SECONDS: Final[float] = 120.0


def is_ocr_available() -> bool:
    """Periksa ketersediaan paket rapidocr-onnxruntime tanpa mengimpornya pada proses utama."""
    rapid_spec = importlib.util.find_spec("rapidocr_onnxruntime")
    onnx_spec = importlib.util.find_spec("onnxruntime")
    return rapid_spec is not None and onnx_spec is not None


class OcrWorkerClient:
    """Klien proses pekerja OCR dengan lazy-spawning dan isolasi dependensi."""

    def __init__(self, worker_cmd: list[str] | None = None) -> None:
        self._worker_cmd = worker_cmd or [sys.executable, "-m", "pinux.ocr.worker"]
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._next_id = 1
        self._last_active_time = time.monotonic()

    def is_available(self) -> bool:
        """Kembalikan True bila paket OCR terpasang pada environment."""
        return is_ocr_available()

    def _ensure_proc(self) -> subprocess.Popen:
        """Pastikan subproses pekerja OCR berjalan."""
        if self._proc is not None and self._proc.poll() is None:
            return self._proc

        logger.info(f"Menjalankan subproses OCR: {' '.join(self._worker_cmd)}")
        self._proc = subprocess.Popen(
            self._worker_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        # stderr harus dikuras agar pekerja tidak macet saat buffer pipa penuh.
        threading.Thread(
            target=self._drain_stderr, args=(self._proc,), daemon=True
        ).start()
        threading.Thread(
            target=self._idle_watchdog, args=(self._proc,), daemon=True
        ).start()
        return self._proc

    @staticmethod
    def _drain_stderr(proc: subprocess.Popen) -> None:
        try:
            assert proc.stderr is not None
            for line in proc.stderr:
                logger.debug("ocr-worker: %s", line.rstrip())
        except Exception:
            pass

    def _idle_watchdog(self, proc: subprocess.Popen) -> None:
        """Hentikan pekerja setelah IDLE_TIMEOUT_SECONDS tanpa aktivitas."""
        while proc.poll() is None:
            time.sleep(min(5.0, IDLE_TIMEOUT_SECONDS))
            if self._proc is not proc:
                return
            if time.monotonic() - self._last_active_time < IDLE_TIMEOUT_SECONDS:
                continue
            if self._lock.acquire(blocking=False):
                try:
                    if self._proc is proc and (
                        time.monotonic() - self._last_active_time >= IDLE_TIMEOUT_SECONDS
                    ):
                        logger.info("Menghentikan pekerja OCR yang menganggur.")
                        self._kill_proc()
                finally:
                    self._lock.release()
                return

    def _kill_proc(self) -> None:
        """Hentikan subproses pekerja dengan SIGTERM."""
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=1.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            for pipe in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
                try:
                    if pipe is not None:
                        pipe.close()
                except Exception:
                    pass
            self._proc = None

    def ensure_model(self, on_progress: Callable[[float], None] | None = None) -> None:
        """Kirim permintaan ensure_model ke pekerja OCR."""
        with self._lock:
            self._last_active_time = time.monotonic()
            proc = self._ensure_proc()
            req_id = self._next_id
            self._next_id += 1

            assert proc.stdin is not None
            assert proc.stdout is not None

            req_line = encode_ensure_model_request(req_id)
            proc.stdin.write(req_line)
            proc.stdin.flush()

            while True:
                line = proc.stdout.readline()
                if not line:
                    raise RuntimeError("Koneksi ke pekerja OCR terputus")

                msg = decode_message(line)
                if msg.get("id") != req_id:
                    continue

                if "error" in msg:
                    err = msg["error"]
                    raise RuntimeError(f"Gagal memuat model OCR: {err.get('message')}")

                if "progress" in msg:
                    p = float(msg["progress"])
                    if on_progress is not None:
                        on_progress(p)
                    if p >= 1.0:
                        break

    def recognize(
        self,
        image_png: bytes,
        cancel: CancelToken | None = None,
        timeout_s: float = RECOGNIZE_TIMEOUT_SECONDS,
    ) -> OcrResult:
        """Kenali teks dari citra PNG melalui pekerja OCR.

        Mendukung pembatalan dengan CancelToken. Jika dibatalkan saat proses
        sedang berlangsung, pekerja di-SIGTERM dan dihentikan.
        """
        if cancel is not None and cancel.cancelled:
            raise RuntimeError("Permintaan OCR dibatalkan")

        with self._lock:
            self._last_active_time = time.monotonic()
            proc = self._ensure_proc()
            req_id = self._next_id
            self._next_id += 1

            assert proc.stdin is not None
            assert proc.stdout is not None

            req_line = encode_recognize_request(req_id, image_png)
            try:
                proc.stdin.write(req_line)
                proc.stdin.flush()
            except BrokenPipeError:
                self._kill_proc()
                raise RuntimeError("Pekerja OCR berhenti tak terduga")

            # Pantau stdout dengan dukungan pembatalan
            result_container: list[dict] = []
            error_container: list[Exception] = []

            def _read_loop() -> None:
                try:
                    while True:
                        line = proc.stdout.readline()
                        if not line:
                            error_container.append(
                                RuntimeError("Koneksi ke pekerja OCR terputus")
                            )
                            return
                        try:
                            msg = decode_message(line)
                        except ValueError:
                            continue
                        # Abaikan pesan basi milik permintaan lain (mis. progress
                        # ensure_model) agar tidak terbaca sebagai hasil.
                        if msg.get("id") != req_id:
                            continue
                        if "result" not in msg and "error" not in msg:
                            continue
                        result_container.append(msg)
                        return
                except Exception as exc:
                    error_container.append(exc)

            reader_thread = threading.Thread(target=_read_loop, daemon=True)
            reader_thread.start()

            deadline = time.monotonic() + timeout_s
            while reader_thread.is_alive():
                if cancel is not None and cancel.cancelled:
                    # Pembatalan via SIGTERM ke pekerja OCR sesuai design.md
                    self._kill_proc()
                    raise RuntimeError("Permintaan OCR dibatalkan")
                if time.monotonic() > deadline:
                    self._kill_proc()
                    raise RuntimeError(f"OCR melebihi batas waktu {timeout_s:.0f} detik")
                reader_thread.join(timeout=0.05)

            if error_container:
                # Pekerja mati/terputus: lepaskan agar panggilan berikutnya
                # menjalankan ulang, tanpa menunggu poll() melihat kematiannya.
                self._kill_proc()
                raise error_container[0]

            if not result_container:
                raise RuntimeError("Pekerja OCR tidak mengembalikan respons")

            msg = result_container[0]
            if "error" in msg:
                err = msg["error"]
                raise RuntimeError(f"Galat pengenalan OCR: {err.get('message')}")

            raw_res = msg.get("result", {})
            text = raw_res.get("text", "")
            raw_lines = raw_res.get("lines", [])

            ocr_lines: list[OcrLine] = []
            for item in raw_lines:
                box = tuple(item.get("box", (0.0, 0.0, 0.0, 0.0)))
                line = OcrLine(
                    text=item.get("text", ""),
                    confidence=float(item.get("confidence", 0.0)),
                    box=(float(box[0]), float(box[1]), float(box[2]), float(box[3])),
                )
                ocr_lines.append(line)

            return OcrResult(text=text, lines=tuple(ocr_lines))

    def shutdown(self) -> None:
        """Hentikan subproses pekerja OCR."""
        with self._lock:
            self._kill_proc()
