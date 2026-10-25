"""Pembacaan clipboard asinkron punya batas waktu (Gdk ``read_text_async`` tidak punya).

Pemilik clipboard yang tidak merespons tidak boleh membuat popup tertahan di status
memuat: pembacaan dibatalkan dan callback menerima string kosong tepat sekali.
Clipboard palsu mengikuti kontrak ``Gdk.Clipboard``; GLib main loop asli dipakai.
"""

from __future__ import annotations

import time

import pytest
from gi.repository import GLib

from pinux.capture import capturer as cap
from pinux.capture.capturer import GdkClipboardBackend, TextCapturer


def _pump(ms: float) -> None:
    ctx = GLib.MainContext.default()
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(0.002)


def _wait(cond, timeout_s: float = 3.0) -> bool:
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        while ctx.pending():
            ctx.iteration(False)
        if cond():
            return True
        time.sleep(0.002)
    return cond()


class FakeClipboard:
    """Meniru Gdk.Clipboard.read_text_async: balasan hanya datang bila tes memicunya."""

    def __init__(self, text: str | None = None, error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.cancellable = None
        self.on_ready = None

    def connect(self, *_args) -> int:  # TextCapturer memasang sinyal "changed"
        return 1

    def read_text_async(self, cancellable, on_ready) -> None:
        self.cancellable, self.on_ready = cancellable, on_ready

    def read_text_finish(self, result) -> str | None:
        if self.error is not None:
            raise self.error
        return self.text

    def reply(self) -> None:
        self.on_ready(self, object())

    def reply_after(self, ms: int) -> None:
        GLib.timeout_add(ms, lambda: (self.reply(), False)[1])


@pytest.fixture
def backend() -> GdkClipboardBackend:
    return GdkClipboardBackend.__new__(GdkClipboardBackend)  # tanpa display; hanya metode baca


def test_unresponsive_clipboard_returns_empty_once_and_cancels(backend) -> None:
    clip, got = FakeClipboard(), []

    start = time.monotonic()
    backend._read_text_async(clip, got.append, timeout_ms=100)
    assert _wait(lambda: got)

    assert got == [""] and time.monotonic() - start < 1.0
    assert clip.cancellable.is_cancelled(), "pembacaan yang tertahan harus dibatalkan"

    clip.error = RuntimeError("Operation was cancelled")  # GDK membalas setelah dibatalkan
    clip.reply()
    _pump(100)
    assert got == [""], "balasan terlambat tidak boleh memanggil callback lagi"


def test_timely_reply_is_delivered_and_timeout_is_disarmed(backend) -> None:
    clip, got = FakeClipboard(text="halo"), []

    backend._read_text_async(clip, got.append, timeout_ms=150)
    clip.reply_after(30)
    assert _wait(lambda: got)
    _pump(300)  # lewati batas waktu: tidak boleh ada panggilan kedua

    assert got == ["halo"]
    assert not clip.cancellable.is_cancelled()


def test_reply_error_gives_empty_text_once(backend) -> None:
    clip, got = FakeClipboard(error=RuntimeError("rusak")), []

    backend._read_text_async(clip, got.append, timeout_ms=150)
    clip.reply_after(10)
    assert _wait(lambda: got)
    _pump(250)

    assert got == [""]


def test_none_text_becomes_empty_string(backend) -> None:
    clip, got = FakeClipboard(text=None), []

    backend._read_text_async(clip, got.append, timeout_ms=150)
    clip.reply_after(5)

    assert _wait(lambda: got) and got == [""]


def test_missing_clipboard_returns_empty(backend) -> None:
    got: list[str] = []

    backend._read_text_async(None, got.append)

    assert _wait(lambda: got) and got == [""]


def test_callback_returning_truthy_is_not_repeated(backend) -> None:
    clip, calls = FakeClipboard(text="x"), []

    def noisy(text: str) -> bool:
        calls.append(text)
        return True  # GLib.idle_add biasa akan mengulang callback seperti ini

    backend._read_text_async(clip, noisy, timeout_ms=150)
    clip.reply_after(5)
    assert _wait(lambda: calls)
    _pump(100)

    assert calls == ["x"]


def test_default_timeout_matches_sync_read() -> None:
    assert cap.ASYNC_READ_TIMEOUT_MS == 1000


class _SilentBackend(GdkClipboardBackend):
    """Backend Gdk dengan dua clipboard yang tidak pernah menjawab."""

    def __init__(self) -> None:  # noqa: D107 - tanpa display
        self._clipboard = FakeClipboard()
        self._primary = FakeClipboard()


def test_text_capturer_does_not_hang_when_clipboards_are_unresponsive(monkeypatch) -> None:
    monkeypatch.setattr(cap, "ASYNC_READ_TIMEOUT_MS", 100, raising=False)  # raising=False: tetap berjalan pada kode lama
    monkeypatch.setattr(cap, "detect_desktop_session", lambda: "x11")
    capturer = TextCapturer(backend=_SilentBackend(), session_type="x11")
    results = []

    start = time.monotonic()
    capturer.read_source_text_async(results.append)

    assert _wait(lambda: results), "popup tertahan: callback tidak pernah dipanggil"
    assert time.monotonic() - start < 1.5
    assert results[0].text == "" and len(results) == 1
