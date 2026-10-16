"""Subpaket mesin OCR.

Antarmuka :class:`~pinux.ocr.base.OcrEngine` dan model datanya didefinisikan pada
:mod:`pinux.ocr.base`. Proses pekerja OCR berada pada :mod:`pinux.ocr.worker`.

Perujuk: R7.3 pada requirements.md.
"""

from pinux.ocr.base import OcrEngine, OcrLine, OcrResult
from pinux.ocr.client import OcrWorkerClient, is_ocr_available
from pinux.ocr.rapid import RapidOcrEngine

__all__ = [
    "OcrEngine",
    "OcrLine",
    "OcrResult",
    "OcrWorkerClient",
    "RapidOcrEngine",
    "is_ocr_available",
]
