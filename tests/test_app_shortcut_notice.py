"""Notifikasi desktop saat pintasan global hilang mendadak.

Perujuk: R1.2, R1.3 pada requirements.md.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw

import pytest

from pinux.app import PinuxApp
from pinux.configstore import ConfigStore
from pinux.credentials import CredentialStore
from pinux.portal import shortcuts as sc


@pytest.fixture(scope="module", autouse=True)
def init_adw() -> None:
    Adw.init()


def _app(tmp_path: Path, backend: str, reason: str | None):
    manager = MagicMock()
    manager.active_backend = backend
    manager.last_reason = reason
    app = PinuxApp(
        config_store=ConfigStore(tmp_path / "pinux.toml"),
        credential_store=CredentialStore(tmp_path / "creds.toml", force_fallback=True),
        shortcut_manager=manager,
        tray_item=MagicMock(),
    )
    app.send_notification = MagicMock()
    app.withdraw_notification = MagicMock()
    return app, manager


def test_app_listens_to_shortcut_manager_changes(tmp_path: Path) -> None:
    app, manager = _app(tmp_path, "cli", None)
    manager.connect_changed.assert_called_once_with(app._on_shortcut_state_changed)


@pytest.mark.parametrize("reason", [sc.REASON_SESSION_CLOSED, sc.REASON_PORTAL_STOPPED])
def test_unexpected_loss_sends_notification(tmp_path: Path, reason: str) -> None:
    app, _ = _app(tmp_path, "cli", reason)
    app._on_shortcut_state_changed()

    app.send_notification.assert_called_once()
    note_id, note = app.send_notification.call_args.args
    assert note_id == PinuxApp._SHORTCUTS_LOST_NOTIFICATION
    app.withdraw_notification.assert_not_called()


@pytest.mark.parametrize("reason", [None, sc.REASON_PORTAL_UNAVAILABLE, sc.REASON_BIND_FAILED])
def test_expected_cli_fallback_is_silent(tmp_path: Path, reason: str | None) -> None:
    app, _ = _app(tmp_path, "cli", reason)
    app._on_shortcut_state_changed()
    app.send_notification.assert_not_called()


def test_notification_is_withdrawn_when_portal_is_active_again(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, "portal", None)
    app._on_shortcut_state_changed()

    app.withdraw_notification.assert_called_once_with(PinuxApp._SHORTCUTS_LOST_NOTIFICATION)
    app.send_notification.assert_not_called()


def test_notification_failure_never_propagates(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, "cli", sc.REASON_SESSION_CLOSED)
    app.send_notification.side_effect = RuntimeError("tanpa daemon notifikasi")
    app._on_shortcut_state_changed()  # tidak boleh melempar
