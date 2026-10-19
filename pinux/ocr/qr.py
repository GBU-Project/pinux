"""Pengenalan kode QR dari gambar PNG (OpenCV bila tersedia).

OpenCV ikut terpasang bersama ``rapidocr-onnxruntime``; bila tidak ada, fitur QR
dinonaktifkan tanpa mengganggu OCR (``qr_available()`` bernilai False).
"""

from __future__ import annotations

__all__ = ["QrUnavailableError", "decode_qr", "qr_available"]


class QrUnavailableError(RuntimeError):
    """OpenCV/numpy tidak terpasang sehingga QR tidak dapat dibaca."""


def qr_available() -> bool:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        return False
    return True


def decode_qr(png_bytes: bytes) -> list[str]:
    """Kembalikan isi semua kode QR pada gambar (daftar kosong bila tidak ada)."""
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise QrUnavailableError("OpenCV (cv2) tidak terpasang") from exc

    image = cv2.imdecode(np.frombuffer(png_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return []

    detector = cv2.QRCodeDetector()
    found: list[str] = []
    try:
        ok, values, _points, _ = detector.detectAndDecodeMulti(image)
        if ok:
            found = [v for v in values if v]
    except cv2.error:
        found = []
    if not found:
        # detectAndDecodeMulti kadang gagal pada satu kode; coba mode tunggal.
        try:
            value, _points, _ = detector.detectAndDecode(image)
        except cv2.error:
            value = ""
        if value:
            found = [value]
    # Hilangkan duplikat sambil mempertahankan urutan.
    return list(dict.fromkeys(found))
