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


# --- Patch 0007: rantai ujung ke ujung dan klik notifikasi ------------------------------

from pinux.portal.shortcuts import BoundShortcut, ShortcutManager, ShortcutSpec  # noqa: E402

SPECS = (
    ShortcutSpec("translate", "T", "<Control><Alt>T"),
    ShortcutSpec("ocr", "O", "<Control><Alt>O"),
)


class _ChainPortal:
    """Portal palsu untuk ShortcutManager asli; callback disimpan agar bisa dipicu."""

    def __init__(self) -> None:
        self.closed_cb = None
        self.bound = [
            BoundShortcut(id="translate", trigger="Ctrl+Alt+T", activation_token="translate"),
            BoundShortcut(id="ocr", trigger="Ctrl+Alt+O", activation_token="ocr"),
        ]

    def is_available(self) -> bool:
        return True

    def connect_activated(self, cb) -> None:
        pass

    def connect_closed(self, cb) -> None:
        self.closed_cb = cb

    def connect_shortcuts_changed(self, cb) -> None:
        pass

    def bind(self, specs, parent_window: str = ""):
        return list(self.bound)

    def close(self) -> None:
        pass


def _real_chain(tmp_path: Path):
    import uuid

    portal = _ChainPortal()
    manager = ShortcutManager(portal=portal, specs=SPECS)
    app = PinuxApp(
        config_store=ConfigStore(tmp_path / "pinux.toml"),
        credential_store=CredentialStore(tmp_path / "creds.toml", force_fallback=True),
        shortcut_manager=manager,
        tray_item=MagicMock(),
    )
    # Gunakan ID unik agar tidak menjadi instans remote saat ada Pinux lain di D-Bus sesi.
    app.set_application_id(f"io.github.gbu_project.Pinux.Test_{uuid.uuid4().hex[:8]}")
    app.send_notification = MagicMock()
    app.withdraw_notification = MagicMock()
    return app, manager, portal


def test_full_chain_real_manager_to_notification(tmp_path: Path) -> None:
    app, manager, portal = _real_chain(tmp_path)

    manager.start()  # menunggu -> portal: bukan kehilangan, tidak boleh ada notifikasi
    app.send_notification.assert_not_called()

    portal.closed_cb(sc.REASON_PORTAL_STOPPED)  # portal restart
    app.send_notification.assert_called_once()
    assert app.send_notification.call_args.args[0] == PinuxApp._SHORTCUTS_LOST_NOTIFICATION

    app.withdraw_notification.reset_mock()
    manager.start()  # mengikat ulang: notifikasi ditarik
    app.withdraw_notification.assert_called_with(PinuxApp._SHORTCUTS_LOST_NOTIFICATION)
    app.send_notification.assert_called_once()


def test_pending_state_does_not_notify(tmp_path: Path) -> None:
    app, manager, portal = _real_chain(tmp_path)
    portal.bound = []  # bind ditolak: fallback yang diharapkan

    manager.start()

    app.send_notification.assert_not_called()


def test_notification_click_action_opens_shortcuts_page(tmp_path: Path) -> None:
    app, _manager, _portal = _real_chain(tmp_path)
    app.register(None)  # menjalankan do_startup: aksi aplikasi terdaftar
    app.show_settings_window = MagicMock()

    assert app.lookup_action("settings-shortcuts") is not None
    app.activate_action("settings-shortcuts", None)

    app.show_settings_window.assert_called_once_with(page="shortcuts")


def test_show_settings_window_selects_requested_page(tmp_path: Path, monkeypatch) -> None:
    class FakeSettings:
        instances: list = []

        def __init__(self, **kwargs) -> None:
            self.pages: list[str] = []
            self.presented = 0
            FakeSettings.instances.append(self)

        def show_page(self, name: str) -> None:
            self.pages.append(name)

        def present(self) -> None:
            self.presented += 1

    monkeypatch.setattr("pinux.app.SettingsWindow", FakeSettings)
    app, _manager, _portal = _real_chain(tmp_path)

    app.show_settings_window()
    win = FakeSettings.instances[0]
    assert win.pages == [] and win.presented == 1

    app.show_settings_window(page="shortcuts")
    assert win.pages == ["shortcuts"] and win.presented == 2
    assert len(FakeSettings.instances) == 1, "jendela yang sama dipakai ulang"


# --- Medium 8: startup memakai pengikatan asinkron --------------------------------------


def test_start_shortcuts_uses_async_start(tmp_path: Path) -> None:
    app, manager, _portal = _real_chain(tmp_path)
    manager.start = MagicMock(side_effect=AssertionError("start() sinkron memblokir UI"))
    manager.start_async = MagicMock(return_value=True)

    assert app._start_shortcuts() is False  # sekali jalan untuk GLib.idle_add

    manager.start_async.assert_called_once_with()


def test_start_shortcuts_contains_failure(tmp_path: Path) -> None:
    app, manager, _portal = _real_chain(tmp_path)
    manager.start_async = MagicMock(side_effect=RuntimeError("rusak"))

    assert app._start_shortcuts() is False  # tidak melempar
