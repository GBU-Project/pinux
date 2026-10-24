"""Token pembatalan permintaan dan penjadwal eksekusi penerjemahan.

``CancelToken`` dipakai oleh Translation_Provider dan OcrEngine untuk
mengetahui bahwa permintaan sudah tidak diperlukan lagi, sehingga pekerjaan
jaringan atau pengenalan dapat dihentikan lebih awal.

``RequestScheduler`` mengelola eksekusi tugas penerjemahan pada ThreadPoolExecutor
di luar thread utama (Properti 2), membatalkan permintaan aktif saat permintaan
baru diajukan (Properti 3 / R10.4), memberlakukan batas waktu (R10.2), dan memastikan
tepat satu callback (`on_result` atau `on_error`) dipanggil pada thread utama via
`GLib.idle_add` sehingga tidak ada keadaan memuat yang tersisa (Properti 4).

Perujuk: R10.2, R10.4 pada requirements.md, serta design.md.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING, Callable, Final

from gi.repository import GLib

if TYPE_CHECKING:
    from pinux.translate.base import (
        TranslationError,
        TranslationProvider,
        TranslationRequest,
        TranslationResult,
    )

__all__ = ["CancelToken", "RequestScheduler"]


class CancelToken:
    """Penanda pembatalan yang aman dipakai lintas thread."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Tandai permintaan sebagai dibatalkan."""
        self._event.set()

    @property
    def cancelled(self) -> bool:
        """Kembalikan ``True`` bila permintaan sudah dibatalkan."""
        return self._event.is_set()


class RequestScheduler:
    """Penjadwal permintaan terjemahan non-blokir berbasis ThreadPoolExecutor."""

    def __init__(
        self,
        executor: ThreadPoolExecutor | None = None,
        max_workers: int = 4,
        *,
        default_timeout_s: float = 10.0,
    ) -> None:
        self._owns_executor = executor is None
        self._executor = executor or ThreadPoolExecutor(max_workers=max_workers)
        self._default_timeout_s = default_timeout_s

        self._lock = threading.Lock()
        self._active_token: CancelToken | None = None
        self._active_seq: int = 0

    @property
    def executor(self) -> ThreadPoolExecutor:
        return self._executor

    def shutdown(self, wait: bool = False) -> None:
        """Hentikan eksekutor dan batalkan permintaan yang sedang berjalan."""
        with self._lock:
            if self._active_token is not None:
                self._active_token.cancel()
        if self._owns_executor:
            self._executor.shutdown(wait=wait, cancel_futures=True)

    def cancel_active(self) -> None:
        """Batalkan permintaan yang sedang aktif jika ada."""
        with self._lock:
            if self._active_token is not None:
                self._active_token.cancel()
                self._active_token = None

    def submit(
        self,
        request: "TranslationRequest",
        provider: "TranslationProvider",
        credential: str | None,
        on_result: Callable[["TranslationResult"], None],
        on_error: Callable[["TranslationError"], None],
        *,
        timeout_s: float | None = None,
    ) -> CancelToken:
        """Kirim permintaan penerjemahan ke worker thread.

        Membatalkan permintaan sebelumnya yang masih aktif (R10.4 / Properti 3).
        Mengembalikan CancelToken untuk permintaan ini.
        """
        from pinux.translate.base import TranslationError

        timeout = timeout_s if timeout_s is not None else self._default_timeout_s

        with self._lock:
            # Batalkan permintaan aktif sebelumnya (R10.4)
            if self._active_token is not None:
                self._active_token.cancel()

            token = CancelToken()
            self._active_token = token
            self._active_seq += 1
            seq = self._active_seq

        def _dispatch_result(res: "TranslationResult") -> bool:
            with self._lock:
                if seq != self._active_seq or token.cancelled:
                    return False
            on_result(res)
            return False

        def _dispatch_error(err: "TranslationError") -> bool:
            with self._lock:
                # Jika urutan permintaan sudah berganti, abaikan
                if seq != self._active_seq:
                    return False
                # Sembunyikan error jenis "cancelled" dari UI agar UX tidak terganggu
                if err.kind == "cancelled":
                    return False
                # Jika token dibatalkan bukan karena timeout, abaikan
                if token.cancelled and err.kind != "timeout":
                    return False
            on_error(err)
            return False

        provider_id = getattr(provider, "id", "unknown")
        # ``finished`` menjamin tepat satu callback: pemenang antara hasil
        # provider dan pemicu timeout.
        finished = threading.Event()
        finish_lock = threading.Lock()

        def _claim() -> bool:
            with finish_lock:
                if finished.is_set():
                    return False
                finished.set()
                return True

        def _cancelled_error() -> "TranslationError":
            return TranslationError(
                kind="cancelled", provider_id=provider_id, message="Permintaan dibatalkan"
            )

        def _on_timeout() -> None:
            if _claim():
                token.cancel()
                GLib.idle_add(
                    _dispatch_error,
                    TranslationError(
                        kind="timeout",
                        provider_id=provider_id,
                        message=f"Permintaan melebihi batas waktu {timeout} detik",
                    ),
                )

        # Provider dijalankan langsung pada thread worker (satu slot per
        # permintaan). Batas waktu ditegakkan oleh timer, bukan oleh future
        # bersarang pada kolam yang sama, yang dapat menguras kolam thread.
        timer = threading.Timer(timeout, _on_timeout)
        timer.daemon = True

        def _worker() -> None:
            if token.cancelled:
                if _claim():
                    GLib.idle_add(_dispatch_error, _cancelled_error())
                return

            timer.start()
            try:
                result = provider.translate(request, credential, token)
                outcome: object = _cancelled_error() if token.cancelled else result
            except TranslationError as exc:
                outcome = exc
            except Exception as exc:
                outcome = TranslationError(
                    kind="provider",
                    provider_id=provider_id,
                    message=f"Terjadi kesalahan saat memproses permintaan: {exc}",
                )
            finally:
                timer.cancel()

            if not _claim():
                return  # timeout sudah dilaporkan
            if isinstance(outcome, TranslationError):
                GLib.idle_add(_dispatch_error, outcome)
            else:
                GLib.idle_add(_dispatch_result, outcome)

        self._executor.submit(_worker)
        return token
