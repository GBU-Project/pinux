"""Alur pengenalan: OCR teks, dengan cadangan pembacaan kode QR."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from pinux.ocr.qr import QrUnavailableError, decode_qr

__all__ = ["Recognized", "recognize_text_or_qr"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Recognized:
    text: str
    source: Literal["ocr", "qr"]


def recognize_text_or_qr(ocr_client: Any, png: bytes) -> Recognized | None:
    """OCR dulu; bila tidak ada teks (atau OCR tidak tersedia), coba baca kode QR.

    Mengembalikan None bila tak ada teks maupun QR. Galat OCR dilempar kembali
    hanya bila QR juga tidak ditemukan, sehingga gambar QR tetap terbaca walau
    paket OCR belum terpasang.
    """
    ocr_error: Exception | None = None
    text = ""
    try:
        text = ocr_client.recognize(png).text.strip()
    except Exception as exc:  # OCR tidak terpasang / worker gagal
        ocr_error = exc
        logger.info("OCR gagal, mencoba QR: %s", exc)
    if text:
        return Recognized(text, "ocr")

    try:
        codes = decode_qr(png)
    except QrUnavailableError:
        codes = []
    if codes:
        return Recognized("\n".join(codes), "qr")
    if ocr_error is not None:
        raise ocr_error
    return None
