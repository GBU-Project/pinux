"""Tes pemuat berkas gambar dan pembaca QR (QR dilewati bila OpenCV tidak ada)."""

from __future__ import annotations

import io

import pytest

from pinux.ocr.imagefile import MAX_BYTES, ImageFileError, load_image_as_png
from pinux.ocr.qr import decode_qr, qr_available

PIL = pytest.importorskip("PIL.Image")


def _save(tmp_path, name, mode="RGB", size=(20, 10), fmt=None, color=(255, 0, 0)):
    path = tmp_path / name
    PIL.new(mode, size, color).save(path, format=fmt)
    return path


@pytest.mark.parametrize(
    "name,mode,fmt",
    [("a.jpg", "RGB", "JPEG"), ("b.png", "RGBA", "PNG"), ("c.bmp", "RGB", "BMP"), ("d.png", "P", "PNG")],
)
def test_loads_common_formats_as_png(tmp_path, name, mode, fmt):
    color = 1 if mode == "P" else ((255, 0, 0, 128) if mode == "RGBA" else (255, 0, 0))
    data = load_image_as_png(_save(tmp_path, name, mode, fmt=fmt, color=color))
    with PIL.open(io.BytesIO(data)) as img:
        assert img.format == "PNG" and img.size == (20, 10)


def test_missing_and_non_image_files(tmp_path):
    with pytest.raises(ImageFileError, match="tidak ditemukan"):
        load_image_as_png(tmp_path / "nope.png")
    txt = tmp_path / "x.png"
    txt.write_text("bukan gambar")
    with pytest.raises(ImageFileError, match="Bukan berkas gambar"):
        load_image_as_png(txt)


def test_directory_rejected(tmp_path):
    with pytest.raises(ImageFileError):
        load_image_as_png(tmp_path)


def test_too_many_pixels_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr("pinux.ocr.imagefile.MAX_PIXELS", 100)
    with pytest.raises(ImageFileError, match="Resolusi"):
        load_image_as_png(_save(tmp_path, "big.png", size=(50, 50)))


def test_too_large_file_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr("pinux.ocr.imagefile.MAX_BYTES", 10)
    with pytest.raises(ImageFileError, match="terlalu besar"):
        load_image_as_png(_save(tmp_path, "s.png"))
    assert MAX_BYTES > 10


def test_truncated_image_reports_error(tmp_path):
    path = _save(tmp_path, "t.png", size=(200, 200))
    path.write_bytes(path.read_bytes()[:60])
    with pytest.raises(ImageFileError):
        load_image_as_png(path)


needs_cv = pytest.mark.skipif(not qr_available(), reason="OpenCV tidak terpasang")


def _qr_png(text: str) -> bytes:
    import cv2

    img = cv2.QRCodeEncoder_create().encode(text)
    img = cv2.copyMakeBorder(img, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    img = cv2.resize(img, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
    return cv2.imencode(".png", img)[1].tobytes()


@needs_cv
def test_decodes_qr_code():
    assert decode_qr(_qr_png("https://example.com/halo")) == ["https://example.com/halo"]


@needs_cv
def test_no_qr_returns_empty_and_garbage_is_safe(tmp_path):
    blank = load_image_as_png(_save(tmp_path, "w.png", size=(120, 120), color=(255, 255, 255)))
    assert decode_qr(blank) == []
    assert decode_qr(b"bukan png") == []


@needs_cv
def test_decodes_qr_inside_loaded_file(tmp_path):
    path = tmp_path / "q.png"
    path.write_bytes(_qr_png("WIFI:T:WPA;S:Rumah;P:rahasia;;"))
    assert decode_qr(load_image_as_png(path)) == ["WIFI:T:WPA;S:Rumah;P:rahasia;;"]
