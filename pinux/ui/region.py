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
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk
from PIL import Image

from pinux.capture.geometry import scale_to_image

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


_OVERLAY_CSS = b"""
window.pinux-region-overlay { background: black; }
.pinux-selection {
    border: 2px solid #3399ff;
    background-color: rgba(51, 153, 255, 0.18);
}
"""
_css_installed = False


def _install_overlay_css() -> None:
    """Pasang CSS overlay satu kali pada display default."""
    global _css_installed
    if _css_installed:
        return
    display = Gdk.Display.get_default()
    if display is None:
        return
    provider = Gtk.CssProvider()
    if hasattr(provider, "load_from_string"):  # GTK 4.12+
        provider.load_from_string(_OVERLAY_CSS.decode())
    else:
        provider.load_from_data(_OVERLAY_CSS)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _css_installed = True


class RegionOverlay(Gtk.Window):
    """Jendela transparan layar penuh untuk memilih Screenshot_Region."""

    def __init__(self) -> None:
        super().__init__()

        self.set_decorated(False)
        self.set_resizable(False)
        self.add_css_class("pinux-region-overlay")

        self._on_selected: Callable[[Rect], None] | None = None
        self._on_cancelled: Callable[[], None] | None = None
        self._on_image: Callable[[bytes], None] | None = None
        self._on_error: Callable[[Exception], None] | None = None

        # Mode "bingkai beku": tangkapan layar diambil lebih dulu lalu
        # ditampilkan sebagai latar, sehingga koordinat seleksi sama persis
        # dengan piksel citra (tanpa transparansi, offset panel, atau skala).
        self._shot_png: bytes | None = None
        self._shot_size: tuple[int, int] = (0, 0)
        self._picture: Gtk.Picture | None = None
        self._selection_box: Gtk.Box | None = None
        self._shot_root: Gtk.Overlay | None = None
        self._capture_token: object = object()

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

    def _detach_drawing_area(self) -> None:
        """Lepaskan DrawingArea dari induknya (jendela atau overlay lama) sebelum dipasang ulang.

        GTK menolak memasang widget yang masih punya induk ("Can't set new parent ...");
        tanpa ini lapisan dim/seleksi hilang pada setiap tangkapan ke-1, ke-3, dst.
        """
        parent = self._drawing_area.get_parent()
        if parent is None:
            return
        if parent is self:
            self.set_child(None)
        elif isinstance(parent, Gtk.Overlay):
            parent.remove_overlay(self._drawing_area)

    def open(
        self,
        on_selected: Callable[[Rect], None],
        on_cancelled: Callable[[], None] | None = None,
        *,
        screenshot_provider: Callable[[], bytes] | None = None,
        on_image: Callable[[bytes], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        capture_delay_s: float = 0.2,
    ) -> None:
        """Buka overlay pemilihan area.

        Tanpa ``screenshot_provider``: overlay maximized lama, ``on_selected``
        menerima ``Rect`` koordinat jendela.

        Dengan ``screenshot_provider``: tangkapan layar diambil dahulu di thread
        latar (setelah ``capture_delay_s`` agar jendela lain sempat hilang),
        ditampilkan layar penuh sebagai latar, dan ``on_image`` menerima PNG
        hasil potongan yang sudah dalam piksel citra.
        """
        self._on_selected = on_selected
        self._on_cancelled = on_cancelled
        self._on_image = on_image
        self._on_error = on_error
        self._is_dragging = False

        if screenshot_provider is None:
            self._shot_png = None
            self._detach_drawing_area()  # bisa masih menempel pada overlay tangkapan sebelumnya
            self.set_child(self._drawing_area)
            self.maximize()
            self.present()
            return

        token = object()
        self._capture_token = token

        def _capture() -> None:
            try:
                time.sleep(capture_delay_s)
                png = screenshot_provider()
            except Exception as exc:  # galat portal, izin ditolak, dsb.
                logger.error(f"Tangkapan layar gagal: {exc}")
                GLib.idle_add(self._capture_failed, token, exc)
                return
            GLib.idle_add(self._show_frozen_frame, token, png)

        threading.Thread(target=_capture, daemon=True).start()

    def _capture_failed(self, token: object, exc: Exception) -> bool:
        if token is self._capture_token and self._on_error is not None:
            self._on_error(exc)
        return False

    def _show_frozen_frame(self, token: object, png: bytes) -> bool:
        if token is not self._capture_token:
            return False  # dibatalkan/digantikan selagi menunggu
        try:
            _install_overlay_css()
            texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(png))
        except Exception as exc:
            logger.error(f"Citra tangkapan layar tidak dapat dimuat: {exc}")
            if self._on_error is not None:
                self._on_error(exc)
            return False

        self._shot_png = png
        self._shot_size = (texture.get_width(), texture.get_height())

        picture = Gtk.Picture.new_for_paintable(texture)
        picture.set_content_fit(Gtk.ContentFit.FILL)
        picture.set_can_shrink(True)

        box = Gtk.Box()
        box.add_css_class("pinux-selection")
        box.set_visible(False)
        fixed = Gtk.Fixed()
        fixed.put(box, 0, 0)

        # Letakkan DrawingArea di atas Picture agar efek dim cutout tetap aktif
        root = Gtk.Overlay()
        root.set_child(picture)
        self._detach_drawing_area()
        root.add_overlay(self._drawing_area)
        root.add_overlay(fixed)
        self._picture, self._selection_box, self._shot_root = picture, box, root
        self._fixed = fixed

        self.set_child(root)
        self.fullscreen()
        # Berikan 1 tick main loop agar fullscreen terpetakan sempurna di Wayland
        GLib.idle_add(self.present)
        return False

    def _finish_frozen_selection(self, rect: "Rect") -> None:
        """Ubah ``rect`` (koordinat widget) ke piksel citra, potong, kirim."""
        assert self._shot_png is not None and self._picture is not None
        try:
            scaled = Rect(
                *scale_to_image(
                    (rect.x, rect.y, rect.width, rect.height),
                    (self._picture.get_width(), self._picture.get_height()),
                    self._shot_size,
                )
            )
            cropped = crop_image_region(self._shot_png, scaled)
        except Exception as exc:
            logger.error(f"Pemotongan citra gagal: {exc}")
            if self._on_error is not None:
                self._on_error(exc)
            return
        if self._on_image is not None:
            self._on_image(cropped)

    def _update_selection_box(self) -> None:
        if self._selection_box is None:
            return
        rect = self._current_rect()
        if not (self._is_dragging and rect.is_valid):
            self._selection_box.set_visible(False)
            return
        self._fixed.move(self._selection_box, rect.x, rect.y)
        self._selection_box.set_size_request(int(rect.width), int(rect.height))
        self._selection_box.set_visible(True)

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
        self._update_selection_box()

    def _on_drag_update(self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float) -> None:
        self._current_x = self._start_x + offset_x
        self._current_y = self._start_y + offset_y
        self._drawing_area.queue_draw()
        self._update_selection_box()

    def _on_drag_end(self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float) -> None:
        self._is_dragging = False
        rect = self._current_rect()
        self._update_selection_box()
        self.hide()

        if self._shot_png is not None:
            if rect.is_valid:
                self._finish_frozen_selection(rect)
            elif self._on_cancelled is not None:
                self._on_cancelled()
            return

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
            self._capture_token = object()  # batalkan tangkapan yang masih berjalan
            self.hide()
            if self._on_cancelled is not None:
                self._on_cancelled()
            return True
        return False
