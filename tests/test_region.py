"""Uji unit untuk RegionOverlay dan fungsi pemotongan citra (task 16).

Perujuk: R6.1, R6.2, R6.3, R6.6 pada requirements.md.
"""

from __future__ import annotations

import io
from PIL import Image

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk

import pytest

from pinux.ui.region import Rect, RegionOverlay, crop_image_region


@pytest.fixture(scope="module", autouse=True)
def init_gtk() -> None:
    Gtk.init()


def create_sample_png(width: int = 100, height: int = 100, color: str = "red") -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_crop_image_region_success() -> None:
    png_data = create_sample_png(200, 200, "blue")
    rect = Rect(x=10, y=20, width=50, height=60)

    cropped_png = crop_image_region(png_data, rect, scale_factor=1.0)
    cropped_img = Image.open(io.BytesIO(cropped_png))

    assert cropped_img.size == (50, 60)


def test_crop_image_region_with_scale_factor() -> None:
    png_data = create_sample_png(400, 400, "green")
    # Skala 200% (HiDPI)
    rect = Rect(x=10, y=10, width=50, height=50)

    cropped_png = crop_image_region(png_data, rect, scale_factor=2.0)
    cropped_img = Image.open(io.BytesIO(cropped_png))

    assert cropped_img.size == (100, 100)


def test_crop_image_region_out_of_bounds_raises_error() -> None:
    png_data = create_sample_png(50, 50)
    # Rect di luar dimensi citra
    rect = Rect(x=100, y=100, width=50, height=50)

    with pytest.raises(ValueError, match="Area seleksi di luar cakupan citra"):
        crop_image_region(png_data, rect)


def test_region_overlay_escape_key_cancels() -> None:
    """R6.6: Menekan Escape membatalkan penangkapan dan menutup RegionOverlay."""
    overlay = RegionOverlay()

    cancelled = False

    def on_cancel() -> None:
        nonlocal cancelled
        cancelled = True

    overlay.open(on_selected=lambda r: None, on_cancelled=on_cancel)

    with pytest.MonkeyPatch.context() as mp:
        hide_called = False

        def mock_hide() -> None:
            nonlocal hide_called
            hide_called = True

        mp.setattr(overlay, "hide", mock_hide)

        handled = overlay._on_key_pressed(None, Gdk.KEY_Escape, 0, 0)
        assert handled is True
        assert hide_called is True
        assert cancelled is True


def test_region_overlay_drag_interaction() -> None:
    overlay = RegionOverlay()

    selected_rect: Rect | None = None

    def on_selected(r: Rect) -> None:
        nonlocal selected_rect
        selected_rect = r

    overlay.open(on_selected=on_selected)

    # Simulasi drag gesture
    overlay._on_drag_begin(None, 10.0, 15.0)
    assert overlay._is_dragging is True

    overlay._on_drag_update(None, 40.0, 50.0)
    assert overlay._current_x == 50.0
    assert overlay._current_y == 65.0

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(overlay, "hide", lambda: None)
        overlay._on_drag_end(None, 40.0, 50.0)

    assert selected_rect is not None
    assert selected_rect.x == 10.0
    assert selected_rect.y == 15.0
    assert selected_rect.width == 40.0
    assert selected_rect.height == 50.0
