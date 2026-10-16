"""Implementasi RegionOverlay untuk seleksi area persegi tangkapan layar (OCR).

Menampilkan jendela transparan layar penuh tanpa dekorasi pada monitor aktif,
menangani gestur drag pemilihan area, menggambar persegi seleksi pada Gtk.DrawingArea,
membatalkan dengan tombol Escape (R6.6), serta memotong citra hasil ScreenshotPortal
secara lokal menggunakan Pillow berdasarkan faktor skala (scale factor).

Perujuk: R6.1, R6.2, R6.3, R6.6 pada requirements.md, serta design.md.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk
from PIL import Image

__all__ = ["Rect", "RegionOverlay", "crop_image_region"]

logger = logging.getLogger("pinux.ui.region")


@dataclass(frozen=True)
class Rect:
    """Persegi area pilihan dalam koordinat logis."""

    x: float
    y: float
    width: float
    height: float

    @property
    def is_valid(self) -> bool:
        """Area valid jika lebar dan tinggi positif (> 2px)."""
        return self.width > 2.0 and self.height > 2.0

    def to_ltrb(self) -> tuple[float, float, float, float]:
        """Kembalikan tuple (left, top, right, bottom)."""
        return (self.x, self.y, self.x + self.width, self.y + self.height)


def crop_image_region(
    image_png: bytes,
    rect: Rect,
    scale_factor: float = 1.0,
) -> bytes:
    """Potong citra PNG sesuai Rect dan scale_factor.

    Mengonversi koordinat logis ke piksel fisik citra:
    left = rect.x * scale_factor, etc.
    """
    img = Image.open(io.BytesIO(image_png))
    img_w, img_h = img.size

    left = max(0, int(rect.x * scale_factor))
    top = max(0, int(rect.y * scale_factor))
    right = min(img_w, int((rect.x + rect.width) * scale_factor))
    bottom = min(img_h, int((rect.y + rect.height) * scale_factor))

    if right <= left or bottom <= top:
        raise ValueError(
            f"Area seleksi di luar cakupan citra: crop=({left}, {top}, {right}, {bottom}), "
            f"ukuran citra=({img_w}, {img_h})"
        )

    cropped = img.crop((left, top, right, bottom))
    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()


class RegionOverlay(Gtk.Window):
    """Jendela transparan layar penuh untuk memilih Screenshot_Region."""

    def __init__(self) -> None:
        super().__init__()

        self.set_decorated(False)
        self.set_resizable(False)
        self.add_css_class("pinux-region-overlay")

        self._on_selected: Callable[[Rect], None] | None = None
        self._on_cancelled: Callable[[], None] | None = None

        self._start_x: float = 0.0
        self._start_y: float = 0.0
        self._current_x: float = 0.0
        self._current_y: float = 0.0
        self._is_dragging: bool = False

        self._drawing_area = Gtk.DrawingArea()
        self._drawing_area.set_draw_func(self._draw_func)
        self.set_child(self._drawing_area)

        # Gestur seret (Drag)
        drag_gesture = Gtk.GestureDrag.new()
        drag_gesture.connect("drag-begin", self._on_drag_begin)
        drag_gesture.connect("drag-update", self._on_drag_update)
        drag_gesture.connect("drag-end", self._on_drag_end)
        self.add_controller(drag_gesture)

        # Keyboard controller (Escape)
        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

    def open(
        self,
        on_selected: Callable[[Rect], None],
        on_cancelled: Callable[[], None] | None = None,
    ) -> None:
        """Buka jendela overlay dalam keadaan maximized."""
        self._on_selected = on_selected
        self._on_cancelled = on_cancelled
        self._is_dragging = False

        self.maximize()
        self.present()

    def _draw_func(
        self,
        drawing_area: Gtk.DrawingArea,
        cr: Any,
        width: int,
        height: int,
    ) -> None:
        """Gambar latar belakang gelap tembus pandang dan persegi seleksi terang."""
        # Latar belakang gelap tembus pandang (50% hitam)
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.45)
        cr.paint()

        if self._is_dragging:
            rect = self._current_rect()
            if rect.is_valid:
                # Bersihkan (cut out) area yang dipilih agar terang
                cr.set_operator(0)  # CAIRO_OPERATOR_CLEAR
                cr.rectangle(rect.x, rect.y, rect.width, rect.height)
                cr.fill()

                cr.set_operator(2)  # CAIRO_OPERATOR_OVER
                # Garis tepi persegi seleksi warna biru/aksen
                cr.set_source_rgba(0.2, 0.6, 1.0, 0.9)
                cr.set_line_width(2.0)
                cr.rectangle(rect.x, rect.y, rect.width, rect.height)
                cr.stroke()

    def _current_rect(self) -> Rect:
        x = min(self._start_x, self._current_x)
        y = min(self._start_y, self._current_y)
        w = abs(self._current_x - self._start_x)
        h = abs(self._current_y - self._start_y)
        return Rect(x=x, y=y, width=w, height=h)

    def _on_drag_begin(self, gesture: Gtk.GestureDrag, start_x: float, start_y: float) -> None:
        self._start_x = start_x
        self._start_y = start_y
        self._current_x = start_x
        self._current_y = start_y
        self._is_dragging = True
        self._drawing_area.queue_draw()

    def _on_drag_update(self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float) -> None:
        self._current_x = self._start_x + offset_x
        self._current_y = self._start_y + offset_y
        self._drawing_area.queue_draw()

    def _on_drag_end(self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float) -> None:
        self._is_dragging = False
        rect = self._current_rect()
        self.hide()

        if rect.is_valid and self._on_selected is not None:
            self._on_selected(rect)
        elif self._on_cancelled is not None:
            self._on_cancelled()

    def _on_key_pressed(
        self,
        controller: Gtk.EventControllerKey,
        keyval: int,
        keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.hide()
            if self._on_cancelled is not None:
                self._on_cancelled()
            return True
        return False
