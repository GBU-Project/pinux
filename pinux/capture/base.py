"""Model data hasil penangkapan teks.

Perujuk: R2.1, R2.2, R2.5 pada requirements.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["CaptureOrigin", "CaptureResult"]

#: Asal Source_Text. ``"primary"`` hanya muncul pada Desktop_Session X11.
CaptureOrigin = Literal["clipboard", "primary", "ocr"]


@dataclass(frozen=True)
class CaptureResult:
    """Source_Text beserta asal dan status pemotongannya.

    ``truncated`` bernilai ``True`` jika dan hanya jika teks dipotong karena
    melebihi ``Settings.max_chars``, lihat R2.5.
    """

    text: str
    truncated: bool
    origin: CaptureOrigin
