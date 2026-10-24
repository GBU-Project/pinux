"""Uji unit dan properti untuk RequestScheduler.

Perujuk: task 8.1, 8.2, 8.3 pada tasklist.md, R10.2, R10.4 pada requirements.md,
serta Properti 2, 3, 4 pada design.md.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest
from gi.repository import GLib
from hypothesis import given, settings as hyp_settings, strategies as st

from pinux.scheduler import CancelToken, RequestScheduler
from pinux.translate.base import (
    Language,
    TranslationError,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
)


class MockSlowProvider:
    id = "slow-provider"
    display_name = "Slow Provider"

    def __init__(self, delay_s: float = 0.05, should_fail: bool = False) -> None:
        self.delay_s = delay_s
        self.should_fail = should_fail
        self.called_threads: list[int] = []

    def requires_credential(self) -> bool:
        return False

    def list_languages(self) -> list[Language]:
        return [Language("id", "Indonesia")]

    def translate(
        self,
        request: TranslationRequest,
        credential: str | None,
        cancel: CancelToken,
    ) -> TranslationResult:
        self.called_threads.append(threading.get_ident())
        start = time.monotonic()
        while time.monotonic() - start < self.delay_s:
            if cancel.cancelled:
                raise TranslationError("cancelled", self.id, "Dibatalkan saat loop")
            time.sleep(0.005)

        if cancel.cancelled:
            raise TranslationError("cancelled", self.id, "Dibatalkan setelah delay")

        if self.should_fail:
            raise TranslationError("network", self.id, "Simulasi kegagalan jaringan")

        return TranslationResult(f"Hasil: {request.text}", "en", self.id)


def run_glib_loop(timeout_s: float = 2.0, condition: Callable[[], bool] | None = None) -> None:
    """Jalankan iterasi main loop GLib sebentar untuk mengalirkan callback idle_add."""
    ctx = GLib.MainContext.default()
    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        ctx.iteration(False)
        if condition is not None and condition():
            break
        time.sleep(0.01)


# --- Uji Unit 8.1 -----------------------------------------------------------


def test_request_scheduler_runs_in_background_thread() -> None:
    """Properti 2: Tidak ada operasi jaringan/terjemahan yang berjalan pada thread pemanggil."""
    scheduler = RequestScheduler(max_workers=2)
    provider = MockSlowProvider(delay_s=0.02)
    caller_thread = threading.get_ident()

    results: list[TranslationResult] = []
    errors: list[TranslationError] = []

    req = TranslationRequest("Halo", None, "en")
    scheduler.submit(req, provider, None, results.append, errors.append)

    run_glib_loop(2.0, condition=lambda: len(results) > 0 or len(errors) > 0)

    scheduler.shutdown(wait=True)
    assert len(results) == 1
    assert len(errors) == 0
    assert provider.called_threads[0] != caller_thread


def test_new_request_cancels_previous_request() -> None:
    """Permintaan baru membatalkan permintaan sebelumnya (R10.4)."""
    scheduler = RequestScheduler(max_workers=2)
    provider = MockSlowProvider(delay_s=0.1)

    results: list[TranslationResult] = []
    errors: list[TranslationError] = []

    # Submit permintaan 1 (lambat)
    tok1 = scheduler.submit(
        TranslationRequest("Req 1", None, "en"),
        provider,
        None,
        results.append,
        errors.append,
    )
    time.sleep(0.01)
    assert not tok1.cancelled

    # Submit permintaan 2 (akan membatalkan permintaan 1)
    tok2 = scheduler.submit(
        TranslationRequest("Req 2", None, "en"),
        provider,
        None,
        results.append,
        errors.append,
    )
    assert tok1.cancelled
    assert not tok2.cancelled

    run_glib_loop(0.3)
    scheduler.shutdown(wait=True)

    # Hanya permintaan 2 yang hasilnya diterima
    assert len(results) == 1
    assert results[0].text == "Hasil: Req 2"


def test_request_timeout_produces_timeout_error() -> None:
    """Permintaan yang melewati batas waktu menghasilkan TranslationError kind='timeout' (R10.2)."""
    scheduler = RequestScheduler(max_workers=2, default_timeout_s=0.05)
    provider = MockSlowProvider(delay_s=0.2)

    results: list[TranslationResult] = []
    errors: list[TranslationError] = []

    scheduler.submit(
        TranslationRequest("Timeout test", None, "en"),
        provider,
        None,
        results.append,
        errors.append,
    )

    run_glib_loop(0.2)
    scheduler.shutdown(wait=True)

    assert len(results) == 0
    assert len(errors) == 1
    assert errors[0].kind == "timeout"


# --- Uji Properti 8.2 (Properti 3: Permintaan Terbaru Menang) ---------------


def test_property_3_latest_request_wins() -> None:
    """Properti 3: Hasil akhir selalu berasal dari permintaan terbaru yang diajukan."""
    scheduler = RequestScheduler(max_workers=4)
    provider = MockSlowProvider(delay_s=0.03)

    results: list[TranslationResult] = []
    errors: list[TranslationError] = []

    for i in range(5):
        scheduler.submit(
            TranslationRequest(f"Pesan {i}", None, "en"),
            provider,
            None,
            results.append,
            errors.append,
        )
        time.sleep(0.005)

    run_glib_loop(0.3)
    scheduler.shutdown(wait=True)

    assert len(results) >= 1
    # Hasil terakhir yang masuk harus 'Hasil: Pesan 4'
    assert results[-1].text == "Hasil: Pesan 4"


# --- Uji Properti 8.3 (Properti 4: Tepat satu jalur selesai) -----------------


def test_property_4_single_request_exact_one_callback_called() -> None:
    """Properti 4: Setiap permintaan terisolasi memicu tepat satu dari on_result atau on_error."""
    for fail in (False, True):
        scheduler = RequestScheduler(max_workers=2)
        provider = MockSlowProvider(delay_s=0.02, should_fail=fail)

        results: list[TranslationResult] = []
        errors: list[TranslationError] = []

        scheduler.submit(
            TranslationRequest("Test", None, "en"),
            provider,
            None,
            results.append,
            errors.append,
        )

        run_glib_loop(0.1)
        scheduler.shutdown(wait=True)

        if not fail:
            assert len(results) == 1
            assert len(errors) == 0
        else:
            assert len(results) == 0
            assert len(errors) == 1


def test_superseded_request_does_not_report_cancelled_error() -> None:
    """Regresi: permintaan lama yang digantikan tidak boleh memunculkan galat
    'dibatalkan' yang menimpa hasil permintaan terbaru."""
    import time

    from gi.repository import GLib

    from pinux.translate.base import TranslationRequest, TranslationResult

    class Slow:
        id = "slow"

        def translate(self, req, cred, cancel):
            time.sleep(0.3)
            return TranslationResult(req.text, "en", "slow")

    events: list[tuple] = []
    scheduler = RequestScheduler()
    loop = GLib.MainLoop()

    def submit(text: str) -> None:
        scheduler.submit(
            TranslationRequest(text, None, "id"),
            Slow(),
            None,
            on_result=lambda r: events.append(("ok", r.text)),
            on_error=lambda e: events.append(("err", text, e.kind)),
        )

    submit("A")
    time.sleep(0.05)
    submit("B")
    GLib.timeout_add(900, loop.quit)
    loop.run()
    scheduler.shutdown()

    assert events == [("ok", "B")]
