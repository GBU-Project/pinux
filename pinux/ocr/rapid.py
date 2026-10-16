"""Implementasi RapidOcrEngine yang membungkus pustaka rapidocr_onnxruntime.

Dijalankan di dalam proses pekerja OCR terpisah (worker process), BUKAN
di dalam proses utama GTK (R7.5 / Properti 7).
"""

from __future__ import annotations

import io
from collections.abc import Callable, Sequence
from typing import Final

from pinux.ocr.base import OcrEngine, OcrLine, OcrResult
from pinux.scheduler import CancelToken

__all__ = ["RapidOcrEngine", "is_rapidocr_available"]


def is_rapidocr_available() -> bool:
    """Periksa apakah dependensi rapidocr-onnxruntime dan onnxruntime dapat diimpor."""
    try:
        import rapidocr_onnxruntime  # noqa: F401
        import onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


class RapidOcrEngine:
    """Mesin OCR luring menggunakan rapidocr-onnxruntime."""

    id: Final[str] = "rapidocr"

    def __init__(self) -> None:
        self._engine = None

    def is_available(self) -> bool:
        return is_rapidocr_available()

    def ensure_model(self, on_progress: Callable[[float], None] | None = None) -> None:
        """Muat model RapidOCR ke memori."""
        if not self.is_available():
            raise RuntimeError(
                "Paket 'rapidocr-onnxruntime' dan 'onnxruntime' tidak terpasang. "
                "Pasang dependensi dengan: pip install pinux[ocr]"
            )

        if on_progress is not None:
            on_progress(0.1)

        from rapidocr_onnxruntime import RapidOCR
        self._engine = RapidOCR()

        if on_progress is not None:
            on_progress(1.0)

    def recognize(self, image_png: bytes, cancel: CancelToken | None = None) -> OcrResult:
        """Lakukan pengenalan karakter dari citra PNG."""
        if cancel is not None and cancel.cancelled:
            raise RuntimeError("Pengenalan OCR dibatalkan")

        if self._engine is None:
            self.ensure_model()

        from PIL import Image
        img = Image.open(io.BytesIO(image_png)).convert("RGB")

        if cancel is not None and cancel.cancelled:
            raise RuntimeError("Pengenalan OCR dibatalkan")

        ocr_results, _ = self._engine(img)

        if cancel is not None and cancel.cancelled:
            raise RuntimeError("Pengenalan OCR dibatalkan")

        if not ocr_results:
            return OcrResult(text="", lines=())

        lines: list[OcrLine] = []
        texts: list[str] = []

        for item in ocr_results:
            # item format: [box, text, score]
            # box is [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            box_points, text, score = item
            xs = [p[0] for p in box_points]
            ys = [p[1] for p in box_points]
            left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)

            line = OcrLine(
                text=str(text),
                confidence=float(score),
                box=(float(left), float(top), float(right), float(bottom)),
            )
            lines.append(line)
            texts.append(str(text))

        full_text = "\n".join(texts)
        return OcrResult(text=full_text, lines=tuple(lines))
