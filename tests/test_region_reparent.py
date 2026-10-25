"""RegionOverlay: DrawingArea harus selalu terpasang pada tampilan aktif (regresi 1.0.0).

Rilis 1.0.0 memasang ``_drawing_area`` ke ``Gtk.Overlay`` baru tanpa melepasnya dari induk
lama. GTK menolak ("Can't set new parent ... which already has parent"), sehingga lapisan
dim/seleksi hilang pada tangkapan ke-1, ke-3, dst., dan mode tanpa screenshot sesudah
tangkapan beku juga gagal memasang kembali.

Memerlukan display (nyata atau Xvfb).
"""

from __future__ import annotations

import io

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw

import pytest
from PIL import Image

from pinux.ui.region import RegionOverlay


@pytest.fixture(scope="module", autouse=True)
def init_adw() -> None:
    Adw.init()


@pytest.fixture
def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), "white").save(buf, "PNG")
    return buf.getvalue()


def test_drawing_area_is_in_every_frozen_frame(png: bytes) -> None:
    overlay = RegionOverlay()
    try:
        for n in range(1, 6):
            overlay._show_frozen_frame(overlay._capture_token, png)
            assert overlay._drawing_area.get_parent() is overlay._shot_root, f"tangkapan ke-{n}"
            assert overlay.get_child() is overlay._shot_root
    finally:
        overlay.destroy()


def test_plain_mode_after_frozen_frame_gets_drawing_area_back(png: bytes) -> None:
    overlay = RegionOverlay()
    try:
        overlay._show_frozen_frame(overlay._capture_token, png)
        assert overlay._drawing_area.get_parent() is overlay._shot_root

        overlay.open(lambda rect: None)  # mode tanpa screenshot_provider

        assert overlay.get_child() is overlay._drawing_area
        assert overlay._drawing_area.get_parent() is overlay
    finally:
        overlay.destroy()


def test_open_doc_has_no_typo() -> None:
    assert "setafter" not in (RegionOverlay.open.__doc__ or "")
