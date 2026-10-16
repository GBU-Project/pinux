"""Fixture bersama untuk pengujian Pinux.

Perujuk: R9.1, R11.5 pada requirements.md.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest


class FakeClipboard:
    """Clipboard dalam memori untuk menguji TextCapturer tanpa sesi grafis.

    Meniru bagian antarmuka ``GdkClipboard`` yang dipakai Pinux, yaitu
    pembacaan teks dan pemberitahuan perubahan isi.
    """

    def __init__(self, text: str = "") -> None:
        self._text = text
        self._callbacks: list[Callable[[], None]] = []

    @property
    def text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        """Ganti isi clipboard dan beri tahu seluruh pelanggan."""
        self._text = text
        for callback in list(self._callbacks):
            callback()

    def connect_changed(self, callback: Callable[[], None]) -> int:
        """Daftarkan callback untuk perubahan isi clipboard."""
        self._callbacks.append(callback)
        return len(self._callbacks) - 1


@pytest.fixture
def tmp_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Arahkan ``$XDG_CONFIG_HOME`` ke direktori sementara."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))
    yield config_dir


@pytest.fixture
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Arahkan ``$XDG_DATA_HOME`` ke direktori sementara."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(data_dir))
    yield data_dir


@pytest.fixture
def fake_clipboard() -> FakeClipboard:
    """Kembalikan clipboard palsu berisi teks awal kosong."""
    return FakeClipboard()


def set_xdg_dirs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, Any]:
    """Utilitas pembantu untuk mengarahkan kedua direktori XDG sekaligus."""
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir(exist_ok=True)
    data_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_dir))
    return {"config": config_dir, "data": data_dir}
