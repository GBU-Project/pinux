"""Memuat berkas gambar pengguna menjadi PNG untuk OCR (OCR dari berkas ala Bob)."""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Final

__all__ = ["ImageFileError", "MAX_BYTES", "MAX_PIXELS", "load_image_as_png"]

MAX_BYTES: Final[int] = 25 * 1024 * 1024
MAX_PIXELS: Final[int] = 50_000_000


class ImageFileError(Exception):
    """Berkas tidak dapat dipakai; ``args[0]`` adalah pesan untuk pengguna."""


def load_image_as_png(path: str | os.PathLike[str]) -> bytes:
    """Baca gambar apa pun yang dikenali Pillow dan kembalikan sebagai PNG."""
    from PIL import Image, UnidentifiedImageError

    p = Path(path).expanduser()
    if not p.is_file():
        raise ImageFileError(f"Berkas tidak ditemukan: {p}")
    size = p.stat().st_size
    if size > MAX_BYTES:
        raise ImageFileError(
            f"Berkas terlalu besar ({size // (1024 * 1024)} MB; batas {MAX_BYTES // (1024 * 1024)} MB)"
        )
    try:
        with Image.open(p) as img:
            if img.width * img.height > MAX_PIXELS:
                raise ImageFileError(f"Resolusi gambar terlalu besar ({img.width}x{img.height})")
            img.load()
            # RGBA/palet/CMYK dinormalkan agar OCR menerima mode yang konsisten.
            converted = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            out = io.BytesIO()
            converted.save(out, format="PNG")
            return out.getvalue()
    except UnidentifiedImageError as exc:
        raise ImageFileError(f"Bukan berkas gambar yang dikenali: {p.name}") from exc
    except (OSError, Image.DecompressionBombError) as exc:
        raise ImageFileError(f"Gambar tidak dapat dibaca: {exc}") from exc
