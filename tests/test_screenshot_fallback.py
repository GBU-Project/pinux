"""Uji jalur cadangan ScreenshotPortal: kode 1 vs 2, percobaan interaktif, CLI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pinux.portal import screenshot as ss
from pinux.portal.screenshot import (
    ScreenshotCancelled,
    ScreenshotFailed,
    ScreenshotPortal,
)

PNG = b"\x89PNG\r\n\x1a\nfake"


def _portal(responses: list, tmp_path: Path):
    """ScreenshotPortal dengan portal_request palsu; mengembalikan (portal, panggilan)."""
    portal = ScreenshotPortal(bus=MagicMock())
    portal.is_available = lambda: True  # type: ignore[method-assign]
    calls: list[bool] = []
    queue = list(responses)

    def fake_request(bus, call, token, *, timeout_s):
        call()
        item = queue.pop(0)
        if item == "ok":
            f = tmp_path / f"s{len(calls)}.png"
            f.write_bytes(PNG)
            return 0, {"uri": f.as_uri()}
        return item, {}

    return portal, calls, fake_request


def _run(portal, fake_request):
    with patch.object(ss, "portal_request", side_effect=fake_request), patch("dbus.Interface") as di:
        di.return_value.Screenshot.side_effect = lambda parent, opts: bool(opts["interactive"])
        return portal.capture_fullscreen(timeout_s=1.0), di


def test_code_1_is_cancelled_without_fallback(tmp_path: Path) -> None:
    portal, _, fake = _portal([1], tmp_path)
    with patch.object(portal, "_capture_via_cli") as cli, pytest.raises(ScreenshotCancelled):
        _run(portal, fake)
    cli.assert_not_called()


def test_code_2_retries_interactive_then_succeeds(tmp_path: Path) -> None:
    portal, _, fake = _portal([2, "ok"], tmp_path)
    data, di = _run(portal, fake)
    assert data == PNG
    used = [c.args[1]["interactive"] for c in di.return_value.Screenshot.call_args_list]
    assert [bool(u) for u in used] == [False, True]


def test_both_portal_attempts_fail_falls_back_to_cli(tmp_path: Path) -> None:
    portal, _, fake = _portal([2, 2], tmp_path)
    with patch.object(portal, "_capture_via_cli", return_value=PNG) as cli:
        data, _ = _run(portal, fake)
    assert data == PNG
    cli.assert_called_once()


def test_all_paths_fail_gives_actionable_error(tmp_path: Path) -> None:
    portal, _, fake = _portal([2, 2], tmp_path)
    with patch.object(portal, "_capture_via_cli", return_value=None):
        with pytest.raises(ScreenshotFailed) as info:
            _run(portal, fake)
    msg = str(info.value)
    assert "kode: 2" in msg
    assert "xdg-desktop-portal" in msg
    assert "ditolak pengguna atau gagal" not in msg


def test_portal_unavailable_uses_cli(tmp_path: Path) -> None:
    portal = ScreenshotPortal(bus=MagicMock())
    portal.is_available = lambda: False  # type: ignore[method-assign]
    with patch.object(portal, "_capture_via_cli", return_value=PNG):
        assert portal.capture_fullscreen() == PNG


def test_cli_fallback_runs_first_installed_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(ss.shutil, "which", lambda name: "/usr/bin/grim" if name == "grim" else None)

    def fake_run(cmd, **kwargs):
        assert cmd[0] == "grim"
        Path(cmd[-1]).write_bytes(PNG)
        return MagicMock(returncode=0)

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    assert ScreenshotPortal(bus=MagicMock())._capture_via_cli() == PNG


def test_cli_fallback_returns_none_when_no_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ss.shutil, "which", lambda name: None)
    assert ScreenshotPortal(bus=MagicMock())._capture_via_cli() is None
