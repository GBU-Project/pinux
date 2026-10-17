"""Pastikan ID aplikasi konsisten di kode, Flatpak, desktop file, dan metainfo."""

from __future__ import annotations

import re
from pathlib import Path

from pinux import APP_ID

ROOT = Path(__file__).resolve().parent.parent


def test_flatpak_manifest_uses_app_id() -> None:
    text = (ROOT / "flatpak" / f"{APP_ID}.yml").read_text(encoding="utf-8")
    assert re.search(rf"^app-id:\s*{re.escape(APP_ID)}\s*$", text, re.M)


def test_desktop_file_and_metainfo_match() -> None:
    desktop = (ROOT / "data" / f"{APP_ID}.desktop").read_text(encoding="utf-8")
    assert f"Icon={APP_ID}" in desktop
    meta = (ROOT / "data" / f"{APP_ID}.metainfo.xml").read_text(encoding="utf-8")
    assert f"<id>{APP_ID}</id>" in meta
    assert f"{APP_ID}.desktop" in meta


def test_manifest_installs_files_under_app_id() -> None:
    text = (ROOT / "flatpak" / f"{APP_ID}.yml").read_text(encoding="utf-8")
    assert f"/app/share/applications/{APP_ID}.desktop" in text
    assert f"/app/share/metainfo/{APP_ID}.metainfo.xml" in text


def test_pip_installs_are_offline() -> None:
    """Build flatpak-builder tanpa jaringan: pip tidak boleh mengunduh dari PyPI."""
    text = (ROOT / "flatpak" / f"{APP_ID}.yml").read_text(encoding="utf-8")
    for line in text.splitlines():
        if "pip3 install" in line:
            assert "--no-index" in line, line
