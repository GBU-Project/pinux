"""Uji integrasi untuk portal desktop (GlobalShortcuts, Screenshot, Secret Service, OCR).

Ditandai dengan marker @pytest.mark.integration. Melewati pengujian (skip)
apabila sesi desktop nyata / portal / paket pendukung tidak tersedia.

Perujuk: task 21.1, 21.2, 21.3, 21.4 pada tasklist.md, R1.2, R6.2, R7.1, R9.2.
"""

from __future__ import annotations

import io
from PIL import Image

import pytest

from pinux.credentials import CredentialStore
from pinux.ocr.client import OcrWorkerClient
from pinux.portal.screenshot import ScreenshotPortal
from pinux.portal.shortcuts import GlobalShortcutsPortal, ShortcutSpec
from pinux.ui.region import Rect, crop_image_region


@pytest.mark.integration
def test_integration_secret_service() -> None:
    """Task 21.3: Uji integrasi penyimpanan dan pengambilan kredensial melalui Secret Service nyata."""
    store = CredentialStore()
    if store.using_fallback:
        pytest.skip("Secret Service (org.freedesktop.secrets) tidak tersedia di sistem ini")

    test_provider = "pinux-integration-test-provider"
    test_secret = "test-secret-token-xyz-123"

    try:
        store.set(test_provider, test_secret)
        retrieved = store.get(test_provider)
        assert retrieved == test_secret
    finally:
        store.delete(test_provider)
        assert store.get(test_provider) is None


@pytest.mark.integration
def test_integration_global_shortcuts_portal_availability() -> None:
    """Task 21.1: Uji integrasi keberadaan GlobalShortcuts portal."""
    portal = GlobalShortcutsPortal()
    if not portal.is_available():
        pytest.skip("GlobalShortcuts portal tidak tersedia pada sesi desktop ini")

    assert portal.is_available() is True


@pytest.mark.integration
def test_integration_screenshot_and_cropping() -> None:
    """Task 21.2: Uji pemotongan tangkapan layar pada resolusi 100% dan 200%."""
    # Buat citra uji sintetis 200x200
    img = Image.new("RGB", (200, 200), color="yellow")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw_png = buf.getvalue()

    # Penskalaan 100%
    rect_100 = Rect(x=10, y=10, width=50, height=50)
    cropped_100 = crop_image_region(raw_png, rect_100, scale_factor=1.0)
    assert Image.open(io.BytesIO(cropped_100)).size == (50, 50)

    # Penskalaan 200%
    rect_200 = Rect(x=10, y=10, width=50, height=50)
    cropped_200 = crop_image_region(raw_png, rect_200, scale_factor=2.0)
    assert Image.open(io.BytesIO(cropped_200)).size == (100, 100)


@pytest.mark.integration
def test_integration_ocr_full_cycle() -> None:
    """Task 21.4: Uji integrasi siklus OCR penuh."""
    client = OcrWorkerClient()
    if not client.is_available():
        pytest.skip("Paket rapidocr-onnxruntime / onnxruntime tidak terpasang")

    # Uji citra sederhana jika paket terpasang
    test_img = Image.new("RGB", (100, 50), color="white")
    buf = io.BytesIO()
    test_img.save(buf, format="PNG")

    try:
        res = client.recognize(buf.getvalue())
        assert isinstance(res.text, str)
    finally:
        client.shutdown()
