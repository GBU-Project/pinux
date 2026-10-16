"""Konversi koordinat seleksi widget ke piksel citra (bebas GTK)."""

from __future__ import annotations

__all__ = ["scale_to_image"]


def scale_to_image(
    rect: tuple[float, float, float, float],
    widget_size: tuple[float, float],
    image_size: tuple[int, int],
) -> tuple[float, float, float, float]:
    """Petakan ``(x, y, w, h)`` pada widget ke piksel citra.

    Widget menampilkan citra dengan mengisi seluruh area, sehingga skala
    horizontal dan vertikal dihitung terpisah. Hasil dijepit ke batas citra.
    Memunculkan ``ValueError`` bila ukuran widget atau citra tidak positif.
    """
    wx, wy = widget_size
    ix, iy = image_size
    if wx <= 0 or wy <= 0 or ix <= 0 or iy <= 0:
        raise ValueError(f"Ukuran tidak valid: widget={widget_size}, citra={image_size}")
    sx, sy = ix / wx, iy / wy
    x, y, w, h = rect
    left = min(max(x * sx, 0.0), ix)
    top = min(max(y * sy, 0.0), iy)
    right = min(max((x + w) * sx, 0.0), ix)
    bottom = min(max((y + h) * sy, 0.0), iy)
    return left, top, right - left, bottom - top
