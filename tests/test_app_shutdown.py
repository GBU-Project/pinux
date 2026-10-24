"""Uji do_shutdown: pembersihan tetap berjalan walau ShortcutManager gagal berhenti.

Perujuk: R8.3 pada requirements.md (pelepasan resource saat berhenti).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw

import pytest

from pinux.app import PinuxApp
from pinux.configstore import ConfigStore
from pinux.credentials import CredentialStore


@pytest.fixture(scope="module", autouse=True)
def init_adw() -> None:
    Adw.init()


def _app(tmp_path: Path, shortcut_manager: MagicMock, tray: MagicMock) -> PinuxApp:
    return PinuxApp(
        config_store=ConfigStore(tmp_path / "pinux.toml"),
        credential_store=CredentialStore(tmp_path / "creds.toml", force_fallback=True),
        shortcut_manager=shortcut_manager,
        tray_item=tray,
    )


def test_do_shutdown_stops_shortcut_manager_then_hides_tray(tmp_path: Path) -> None:
    manager, tray = MagicMock(), MagicMock()
    _app(tmp_path, manager, tray).do_shutdown()

    manager.stop.assert_called_once()
    tray.hide.assert_called_once()


def test_do_shutdown_continues_when_shortcut_stop_fails(tmp_path: Path) -> None:
    manager, tray = MagicMock(), MagicMock()
    manager.stop.side_effect = RuntimeError("portal hang")

    _app(tmp_path, manager, tray).do_shutdown()  # tidak boleh melempar

    manager.stop.assert_called_once()
    tray.hide.assert_called_once()
