"""Uji unit dan properti untuk TextCapturer.

Perujuk: task 10.1 dan 10.2 pada tasklist.md, R2.1, R2.2, R2.3, R2.5, R5.4 pada requirements.md,
serta Properti 5 pada design.md.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import pytest
from hypothesis import given, strategies as st

from pinux.capture import (
    CaptureResult,
    ClipboardBackend,
    TextCapturer,
    detect_desktop_session,
    truncate_text,
)


class MockClipboardBackend:
    """Implementasi tiruan ClipboardBackend untuk pengujian."""

    def __init__(self, clipboard_text: str = "", primary_text: str = "") -> None:
        self._clipboard = clipboard_text
        self._primary = primary_text
        self._clipboard_cbs: list[Callable[[], None]] = []
        self._primary_cbs: list[Callable[[], None]] = []

    def read_clipboard_text(self) -> str:
        return self._clipboard

    def read_primary_text(self) -> str:
        return self._primary

    def write_clipboard_text(self, text: str) -> None:
        self._clipboard = text

    def connect_clipboard_changed(self, callback: Callable[[], None]) -> None:
        self._clipboard_cbs.append(callback)

    def connect_primary_changed(self, callback: Callable[[], None]) -> None:
        self._primary_cbs.append(callback)

    def trigger_clipboard_changed(self, new_text: str) -> None:
        self._clipboard = new_text
        for cb in list(self._clipboard_cbs):
            cb()

    def trigger_primary_changed(self, new_text: str) -> None:
        self._primary = new_text
        for cb in list(self._primary_cbs):
            cb()


# --- Uji Unit 10.1: Pemilihan Sumber Teks dan Sesi --------------------------


def test_detect_desktop_session_wayland(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert detect_desktop_session() == "wayland"


def test_detect_desktop_session_x11(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    assert detect_desktop_session() == "x11"


def test_wayland_also_prefers_selection() -> None:
    """Terjemah seleksi ala Bob: seleksi didahulukan juga pada Wayland."""
    backend = MockClipboardBackend(clipboard_text="Teks Clipboard", primary_text="Teks Primary")
    capturer = TextCapturer(backend=backend, session_type="wayland")

    res = capturer.read_source_text()
    assert res.text == "Teks Primary"
    assert res.origin == "primary"


def test_prioritizes_most_recently_changed_source() -> None:
    backend = MockClipboardBackend(
        clipboard_text="Awal", primary_text="Awal"
    )
    capturer = TextCapturer(backend=backend, session_type="x11")
    backend.trigger_primary_changed("Seleksi lama")
    backend.trigger_clipboard_changed("Baru disalin (Ctrl+C)")
    assert capturer.read_source_text().text == "Baru disalin (Ctrl+C)"
    backend.trigger_primary_changed("Sorotan terbaru")
    assert capturer.read_source_text().text == "Sorotan terbaru"


def test_x11_prioritizes_primary_selection_when_different() -> None:
    backend = MockClipboardBackend(clipboard_text="Teks Clipboard", primary_text="Teks Primary")
    capturer = TextCapturer(backend=backend, session_type="x11")

    res = capturer.read_source_text()
    assert res.text == "Teks Primary"
    assert res.origin == "primary"
    assert res.truncated is False


def test_x11_falls_back_to_clipboard_when_primary_empty_or_same() -> None:
    # Kasus primary sama dengan clipboard
    backend1 = MockClipboardBackend(clipboard_text="Teks Sama", primary_text="Teks Sama")
    capturer1 = TextCapturer(backend=backend1, session_type="x11")
    assert capturer1.read_source_text().origin == "clipboard"

    # Kasus primary kosong
    backend2 = MockClipboardBackend(clipboard_text="Teks Clipboard", primary_text="")
    capturer2 = TextCapturer(backend=backend2, session_type="x11")
    assert capturer2.read_source_text().origin == "clipboard"
    assert capturer2.read_source_text().text == "Teks Clipboard"


def test_clipboard_empty_returns_empty_without_error() -> None:
    backend = MockClipboardBackend(clipboard_text="", primary_text="")
    capturer = TextCapturer(backend=backend, session_type="wayland")

    res = capturer.read_source_text()
    assert res.text == ""
    assert res.truncated is False
    assert res.origin == "clipboard"


def test_clipboard_changed_triggers_callback() -> None:
    backend = MockClipboardBackend(clipboard_text="Awal")
    capturer = TextCapturer(backend=backend, session_type="wayland")

    received: list[CaptureResult] = []
    capturer.connect_changed(received.append)

    backend.trigger_clipboard_changed("Teks Baru")

    assert len(received) == 1
    assert received[0].text == "Teks Baru"


def test_send_to_clipboard() -> None:
    backend = MockClipboardBackend()
    capturer = TextCapturer(backend=backend)
    capturer.send_to_clipboard("Disalin ke sistem")
    assert backend.read_clipboard_text() == "Disalin ke sistem"


# --- Uji Properti 10.2 (Properti 5: Panjang Teks & Penandaan Truncated) -------


@given(
    text=st.text(min_size=0, max_size=10000),
    max_chars=st.integers(min_value=1, max_value=5000),
)
def test_property_5_source_text_length_and_truncation(text: str, max_chars: int) -> None:
    """Properti 5: len(res.text) <= max_chars dan truncated == True iff pemotongan terjadi."""
    backend = MockClipboardBackend(clipboard_text=text)
    capturer = TextCapturer(backend=backend, session_type="wayland")

    res = capturer.read_source_text(max_chars=max_chars)

    assert len(res.text) <= max_chars
    if len(text) > max_chars:
        assert res.truncated is True
        assert res.text == text[:max_chars]
    else:
        assert res.truncated is False
        assert res.text == text


class _FakeAsyncClipboard:
    """Meniru Gdk.Clipboard: hasil dikirim asinkron lewat GLib.idle_add."""

    def __init__(self, text, fail=False):
        self._text, self._fail = text, fail

    def read_text_async(self, cancellable, callback):
        from gi.repository import GLib

        GLib.idle_add(lambda: callback(self, None) and False)

    def read_text_finish(self, result):
        if self._fail:
            raise RuntimeError("tidak ada teks")
        return self._text


def test_gdk_backend_reads_text_asynchronously():
    from pinux.capture.capturer import GdkClipboardBackend

    assert GdkClipboardBackend._read_text(_FakeAsyncClipboard("halo")) == "halo"
    assert GdkClipboardBackend._read_text(_FakeAsyncClipboard("x", fail=True)) == ""
    assert GdkClipboardBackend._read_text(None) == ""
