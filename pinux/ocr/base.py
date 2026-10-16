"""Model data dan antarmuka OcrEngine.

Perujuk: R7.3 pada requirements.md.

Modul ini hanya memuat tipe data dan Protocol, sehingga tidak mengimpor
``onnxruntime`` maupun ``rapidocr``. Hal ini menjaga Properti 7 pada design.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence, runtime_checkable

from pinux.scheduler import CancelToken

__all__ = ["OcrEngine", "OcrLine", "OcrResult"]


@dataclass(frozen=True)
class OcrLine:
    """Satu baris teks hasil pengenalan.

    ``box`` adalah persegi pembatas dalam koordinat piksel citra, berbentuk
    ``(left, top, right, bottom)``.
    """

    text: str
    confidence: float
    box: tuple[float, float, float, float]


@dataclass(frozen=True)
class OcrResult:
    """Hasil pengenalan satu citra."""

    text: str
    lines: Sequence[OcrLine] = field(default_factory=tuple)


@runtime_checkable
class OcrEngine(Protocol):
    """Antarmuka yang harus dipenuhi setiap mesin OCR.

    Perujuk: R7.3 pada requirements.md.
    """

    #: Pengenal unik mesin OCR, misalnya ``"rapidocr"``.
    id: str

    def is_available(self) -> bool:
        """Kembalikan ``True`` bila mesin OCR beserta dependensinya tersedia."""
        ...

    def ensure_model(self, on_progress: Callable[[float], None]) -> None:
        """Pastikan model tersedia, unduh bila perlu.

        ``on_progress`` menerima nilai kemajuan antara 0.0 dan 1.0, lihat R7.4.
        """
        ...

    def recognize(self, image_png: bytes, cancel: CancelToken) -> OcrResult:
        """Kenali teks pada citra PNG dan kembalikan hasilnya."""
        ...
