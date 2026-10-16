"""Uji unit untuk GlobalShortcutsPortal, ShortcutManager, dan ScreenshotPortal.

Perujuk: task 11 dan task 12 pada tasklist.md, R1.2, R1.3, R6.2, R6.5, R8.4.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import dbus
import pytest
from gi.repository import GLib

from pinux.portal.screenshot import ScreenshotPortal
from pinux.portal.shortcuts import (
    BoundShortcut,
    GlobalShortcutsPortal,
    ShortcutManager,
    ShortcutSpec,
)


# --- Uji GlobalShortcutsPortal & ShortcutManager -----------------------------


def test_global_shortcuts_portal_availability_check() -> None:
    mock_bus = MagicMock()
    mock_bus.name_has_owner.return_value = True

    mock_portal = MagicMock()
    mock_intf = MagicMock()
    mock_intf.Introspect.return_value = '<interface name="org.freedesktop.portal.GlobalShortcuts" />'
    mock_bus.get_object.return_value = mock_portal

    with patch("dbus.Interface", return_value=mock_intf):
        portal = GlobalShortcutsPortal(bus=mock_bus)
        assert portal.is_available() is True

    # Jika nama bus tidak punya pemilik
    mock_bus.name_has_owner.return_value = False
    assert portal.is_available() is False


def test_shortcut_manager_fallback_to_cli_when_portal_unavailable() -> None:
    mock_portal = MagicMock()
    mock_portal.is_available.return_value = False

    manager = ShortcutManager(portal=mock_portal)
    backend = manager.start()

    assert backend == "cli"
    assert manager.active_backend == "cli"
    assert manager.bound_shortcuts == ()


def test_shortcut_manager_success_portal_binding() -> None:
    mock_portal = MagicMock()
    mock_portal.is_available.return_value = True
    mock_portal.bind.return_value = [
        BoundShortcut(id="translate", trigger="<Control><Alt>T", activation_token="translate"),
        BoundShortcut(id="ocr", trigger="<Control><Alt>O", activation_token="ocr"),
    ]

    activated_calls: list[str] = []
    manager = ShortcutManager(
        portal=mock_portal,
        on_activated=activated_calls.append,
    )

    backend = manager.start()
    assert backend == "portal"
    assert manager.active_backend == "portal"
    assert len(manager.bound_shortcuts) == 2

    manager.stop()
    mock_portal.close.assert_called_once()
    assert manager.active_backend == "cli"


def test_shortcut_manager_fallback_when_bind_fails() -> None:
    mock_portal = MagicMock()
    mock_portal.is_available.return_value = True
    mock_portal.bind.side_effect = RuntimeError("Ditolak pengguna")

    manager = ShortcutManager(portal=mock_portal)
    backend = manager.start()

    assert backend == "cli"
    assert manager.active_backend == "cli"


def test_portal_activated_signal_dispatch() -> None:
    portal = GlobalShortcutsPortal(bus=MagicMock())
    received: list[str] = []
    portal.connect_activated(received.append)

    # Simulasi sinyal D-Bus masuk
    portal._on_activated("session_handle", "translate", 123456, {})
    assert received == ["translate"]

    portal._on_activated("session_handle", "ocr", 123457, {})
    assert received == ["translate", "ocr"]


# --- Uji ScreenshotPortal ---------------------------------------------------


def test_screenshot_portal_availability_check() -> None:
    mock_bus = MagicMock()
    mock_bus.name_has_owner.return_value = True

    mock_portal = MagicMock()
    mock_intf = MagicMock()
    mock_intf.Introspect.return_value = '<interface name="org.freedesktop.portal.Screenshot" />'
    mock_bus.get_object.return_value = mock_portal

    with patch("dbus.Interface", return_value=mock_intf):
        ss_portal = ScreenshotPortal(bus=mock_bus)
        assert ss_portal.is_available() is True

    mock_bus.name_has_owner.return_value = False
    assert ss_portal.is_available() is False


def test_screenshot_portal_capture_flow(tmp_path: Path) -> None:
    # Buat file dummy PNG sementara
    fake_png = tmp_path / "screenshot.png"
    fake_png.write_bytes(b"\x89PNG\r\n\x1a\nfakeimagebytes")

    mock_bus = MagicMock()
    mock_bus.name_has_owner.return_value = True

    mock_portal = MagicMock()
    mock_intf = MagicMock()
    mock_intf.Introspect.return_value = '<interface name="org.freedesktop.portal.Screenshot" />'

    mock_req_iface = MagicMock()
    mock_req_iface.Screenshot.return_value = "/req/path/123"

    with patch("dbus.Interface") as mock_dbus_iface:
        def iface_factory(obj: object, iface_name: str) -> MagicMock:
            if iface_name == "org.freedesktop.portal.Screenshot":
                return mock_req_iface
            return mock_intf

        mock_dbus_iface.side_effect = iface_factory
        mock_bus.get_object.return_value = mock_portal

        ss_portal = ScreenshotPortal(bus=mock_bus)

        # Trigger response callback asynchronously via GLib.idle_add
        def fake_response_trigger() -> None:
            # Ambil callback yang didaftarkan ke add_signal_receiver
            args, kwargs = mock_bus.add_signal_receiver.call_args
            on_response_cb = args[0]
            # Simulasi respons berhasil (code 0) dengan file URI
            on_response_cb(0, {"uri": fake_png.as_uri()})

        GLib.idle_add(lambda: (fake_response_trigger(), False)[1])

        image_bytes = ss_portal.capture_fullscreen(timeout_s=2.0)

        assert image_bytes == b"\x89PNG\r\n\x1a\nfakeimagebytes"
        # Berkas sementara harus dibersihkan setelah dibaca
        assert not fake_png.exists()
