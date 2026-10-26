"""Versi rilis harus sama di kode, pyproject, README, metainfo, dan CHANGELOG."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from pinux import APP_ID, __version__

ROOT = Path(__file__).resolve().parent.parent


def _metainfo_latest() -> tuple[str, str]:
    meta = (ROOT / "data" / f"{APP_ID}.metainfo.xml").read_text(encoding="utf-8")
    m = re.search(r'<release version="([^"]+)" date="([^"]+)"', meta)
    assert m, "metainfo tidak memuat <release>"
    return m.group(1), m.group(2)


def test_pyproject_matches_package_version() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == __version__


def test_readme_states_current_version() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"Versi: `{__version__}`" in readme


def test_metainfo_latest_release_is_current_version() -> None:
    version, _date = _metainfo_latest()
    assert version == __version__


def test_changelog_top_entry_matches_version_and_metainfo_date() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^\s*## \[([^\]]+)\] - (\d{4}-\d{2}-\d{2})", text, re.M)
    assert m, "CHANGELOG tidak memuat entri rilis"
    version, date = m.groups()
    assert version == __version__
    assert date == _metainfo_latest()[1], "tanggal rilis CHANGELOG berbeda dengan metainfo"
