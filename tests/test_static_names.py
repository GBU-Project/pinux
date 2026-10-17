"""Penjaga statis: nama tak terdefinisi hanya tampak saat jalur kode itu berjalan.

Kode GUI tidak bisa dijalankan di CI tanpa display, jadi pyflakes memeriksa
seluruh paket untuk menangkap NameError (mis. ``import`` yang terlewat).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pyflakes_api = pytest.importorskip("pyflakes.api")
from pyflakes.reporter import Reporter  # noqa: E402


class _Collect:
    def __init__(self) -> None:
        self.problems: list[str] = []

    def write(self, text: str) -> None:
        if "undefined name" in text:
            self.problems.append(text.strip())

    def flush(self) -> None:  # pragma: no cover
        pass


def test_no_undefined_names_in_package() -> None:
    root = Path(__file__).resolve().parent.parent / "pinux"
    sink = _Collect()
    reporter = Reporter(sink, sink)
    for path in sorted(root.rglob("*.py")):
        pyflakes_api.check(path.read_text(encoding="utf-8"), str(path), reporter)
    assert not sink.problems, "\n".join(sink.problems)
