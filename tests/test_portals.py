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


# --- Alur asinkron CreateSession / BindShortcuts ------------------------------


def _async_portal(responses):
    """GlobalShortcutsPortal dengan bus palsu; ``responses`` = antrean (kode, hasil)."""
    from pinux.portal import shortcuts as sc

    bus = MagicMock()
    bus.get_unique_name.return_value = ":1.7"
    portal = sc.GlobalShortcutsPortal(bus=bus)
    portal.is_available = lambda: True
    portal._ensure_registered = lambda: None
    queue = list(responses)
    return sc, portal, queue


def test_create_session_uses_handle_from_response() -> None:
    sc, portal, queue = _async_portal([(0, {"session_handle": "/real/session/handle"})])
    with patch.object(sc, "portal_request", side_effect=lambda *a, **k: queue.pop(0)), \
         patch("dbus.Interface"):
        assert portal.create_session() == "/real/session/handle"
    assert portal._session_path == "/real/session/handle"


def test_bind_returns_only_approved_shortcuts_with_approved_trigger() -> None:
    sc, portal, queue = _async_portal(
        [
            (0, {"session_handle": "/s"}),
            (0, {"shortcuts": [("translate", {"trigger_description": "Ctrl+Shift+T"})]}),
        ]
    )
    specs = [
        ShortcutSpec("translate", "T", "<Control><Alt>T"),
        ShortcutSpec("ocr", "O", "<Control><Alt>O"),
    ]
    with patch.object(sc, "portal_request", side_effect=lambda *a, **k: queue.pop(0)), \
         patch("dbus.Interface"):
        bound = portal.bind(specs)
    assert [(b.id, b.trigger) for b in bound] == [("translate", "Ctrl+Shift+T")]


def test_bind_rejected_by_user_returns_empty() -> None:
    sc, portal, queue = _async_portal([(0, {"session_handle": "/s"}), (1, {})])
    with patch.object(sc, "portal_request", side_effect=lambda *a, **k: queue.pop(0)), \
         patch("dbus.Interface"):
        assert portal.bind([ShortcutSpec("translate", "T", "<Control><Alt>T")]) == []


def test_specs_from_settings_uses_user_triggers() -> None:
    from pinux.portal.shortcuts import specs_from_settings

    specs = specs_from_settings({"translate": "<Super>T", "ocr": "<Super>O", "lainnya": "x"})
    assert {s.id: s.preferred_trigger for s in specs} == {
        "translate": "<Super>T",
        "ocr": "<Super>O",
    }
