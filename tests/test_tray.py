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
    events_called: dict[str, bool] = {
        "translate_selection": False,
        "ocr_translate": False,
        "input_translate": False,
        "show_popup": False,
        "ocr_pure": False,
        "settings": False,
        "quit": False,
    }

    from pinux.tray import DbusMenuService

    mock_bus = MagicMock()
    service = DbusMenuService(
        bus=mock_bus,
        object_path="/MenuBar",
        on_translate_selection=lambda: events_called.__setitem__("translate_selection", True),
        on_ocr_translate=lambda: events_called.__setitem__("ocr_translate", True),
        on_input_translate=lambda: events_called.__setitem__("input_translate", True),
        on_show_popup=lambda: events_called.__setitem__("show_popup", True),
        on_ocr_pure=lambda: events_called.__setitem__("ocr_pure", True),
        on_settings=lambda: events_called.__setitem__("settings", True),
        on_quit=lambda: events_called.__setitem__("quit", True),
        version_string="Pinux v0.1.0",
    )

    # Uji GetLayout
    revision, root = service.GetLayout(0, 1)
    assert revision == 1
    # 11 item (termasuk separator dan versi info)
    assert len(root[2]) == 11

    from gi.repository import GLib

    def run_idle() -> None:
        ctx = GLib.MainContext.default()
        while ctx.iteration(False):
            pass

    # Uji seluruh event klik
    service.Event(1, "clicked", None, 0)
    run_idle()
    assert events_called["translate_selection"] is True

    service.Event(2, "clicked", None, 0)
    run_idle()
    assert events_called["ocr_translate"] is True

    service.Event(3, "clicked", None, 0)
    run_idle()
    assert events_called["input_translate"] is True

    service.Event(4, "clicked", None, 0)
    run_idle()
    assert events_called["show_popup"] is True

    service.Event(6, "clicked", None, 0)
    run_idle()
    assert events_called["ocr_pure"] is True

    service.Event(8, "clicked", None, 0)
    run_idle()
    assert events_called["settings"] is True

    service.Event(11, "clicked", None, 0)
    run_idle()
    assert events_called["quit"] is True


def test_tray_item_sni_properties_and_version() -> None:
    from pinux import APP_ID, __version__
    from pinux.tray import DbusMenuService, StatusNotifierItemService

    mock_bus = MagicMock()
    sni = StatusNotifierItemService(mock_bus, "/StatusNotifierItem", "/MenuBar")
    props = sni.GetAll("org.kde.StatusNotifierItem")

    assert str(props["Id"]) == APP_ID
    assert str(props["IconName"]) in (APP_ID, "pinux")
    assert "IconPixmap" in props
    assert "ToolTip" in props

    # Test DbusMenu default version
    menu = DbusMenuService(bus=mock_bus, object_path="/MenuBar")
    _, root = menu.GetLayout(0, 1)
    # Item index 9 adalah label versi
    version_item = root[2][9]
    assert version_item[1]["label"] == f"Pinux v{__version__}"

