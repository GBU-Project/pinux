"""Uji unit untuk TrayItem.

Perujuk: task 17.1 pada tasklist.md, R8.2, R8.4, R8.5 pada requirements.md,
serta Properti 8 (ikon tray tidak fatal) pada design.md.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pinux.tray import TrayItem


def test_tray_item_watcher_available_check() -> None:
    mock_bus = MagicMock()
    mock_bus.name_has_owner.return_value = True

    tray = TrayItem(bus=mock_bus)
    assert tray.is_watcher_available() is True

    mock_bus.name_has_owner.return_value = False
    assert tray.is_watcher_available() is False


def test_property_8_tray_failure_is_non_fatal() -> None:
    """Properti 8: Kegagalan menampilkan tray tidak fatal bagi proses utama."""
    mock_bus = MagicMock()
    mock_bus.name_has_owner.return_value = False

    tray = TrayItem(bus=mock_bus)

    # Ketika watcher tidak tersedia, show() memunculkan RuntimeError yang terkelola
    with pytest.raises(RuntimeError, match="tidak tersedia"):
        tray.show()

    # Aplikasi tetap dapat memanggil hide() tanpa crash
    tray.hide()


def test_tray_item_menu_events() -> None:
    settings_called = False
    ocr_called = False
    quit_called = False

    def on_settings() -> None:
        nonlocal settings_called
        settings_called = True

    def on_ocr() -> None:
        nonlocal ocr_called
        ocr_called = True

    def on_quit() -> None:
        nonlocal quit_called
        quit_called = True

    from pinux.tray import DbusMenuService

    mock_bus = MagicMock()
    service = DbusMenuService(
        bus=mock_bus,
        object_path="/MenuBar",
        on_settings=on_settings,
        on_ocr=on_ocr,
        on_quit=on_quit,
    )

    # Uji GetLayout
    revision, root = service.GetLayout(0, 1)
    assert revision == 1
    assert len(root[2]) == 3

    # Uji klik event
    service.Event(1, "clicked", None, 0)
    assert settings_called is True

    service.Event(2, "clicked", None, 0)
    assert ocr_called is True

    service.Event(3, "clicked", None, 0)
    assert quit_called is True
