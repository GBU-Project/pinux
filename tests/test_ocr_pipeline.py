"""Tes alur OCR dengan cadangan QR (klien OCR palsu)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pinux.ocr.pipeline import Recognized, recognize_text_or_qr
from pinux.ocr.qr import QrUnavailableError


class _Client:
    def __init__(self, text="", error=None):
        self.text, self.error = text, error

    def recognize(self, png):
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text)


def test_text_wins_over_qr():
    with patch("pinux.ocr.pipeline.decode_qr") as qr:
        assert recognize_text_or_qr(_Client("  halo "), b"x") == Recognized("halo", "ocr")
    qr.assert_not_called()


def test_empty_ocr_falls_back_to_qr():
    with patch("pinux.ocr.pipeline.decode_qr", return_value=["a", "b"]):
        assert recognize_text_or_qr(_Client(""), b"x") == Recognized("a\nb", "qr")


def test_ocr_unavailable_but_qr_present():
    with patch("pinux.ocr.pipeline.decode_qr", return_value=["https://x"]):
        res = recognize_text_or_qr(_Client(error=RuntimeError("rapidocr tidak ada")), b"x")
    assert res == Recognized("https://x", "qr")


def test_ocr_error_reraised_when_no_qr():
    with patch("pinux.ocr.pipeline.decode_qr", return_value=[]):
        with pytest.raises(RuntimeError, match="rapidocr"):
            recognize_text_or_qr(_Client(error=RuntimeError("rapidocr tidak ada")), b"x")


def test_nothing_found_returns_none_and_missing_cv_is_ignored():
    with patch("pinux.ocr.pipeline.decode_qr", side_effect=QrUnavailableError("no cv2")):
        assert recognize_text_or_qr(_Client(""), b"x") is None
        with pytest.raises(RuntimeError):
            recognize_text_or_qr(_Client(error=RuntimeError("x")), b"x")
