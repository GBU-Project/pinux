"""Penangkapan Source_Text dari Clipboard dan Primary_Selection.

:class:`~pinux.capture.base.CaptureResult` didefinisikan pada
:mod:`pinux.capture.base` dan diekspor ulang di sini, sehingga
``from pinux.capture import CaptureResult`` tetap berlaku sesuai design.md.

Perujuk: R2.1, R2.2 pada requirements.md.
"""

from __future__ import annotations

from pinux.capture.base import CaptureOrigin, CaptureResult
from pinux.capture.capturer import (
    ClipboardBackend,
    DesktopSessionType,
    GdkClipboardBackend,
    TextCapturer,
    detect_desktop_session,
    truncate_text,
)

__all__ = [
    "CaptureOrigin",
    "CaptureResult",
    "ClipboardBackend",
    "DesktopSessionType",
    "GdkClipboardBackend",
    "TextCapturer",
    "detect_desktop_session",
    "truncate_text",
]
