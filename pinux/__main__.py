"""Titik masuk perintah ``pinux``.

Rangkaian aksi baris perintah (``--trigger``, ``--pick-region``, ``--settings``)
diimplementasikan pada task 19 di dalam :mod:`pinux.app`.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Jalankan Pinux dan kembalikan kode keluar proses."""
    raise NotImplementedError(
        "Antarmuka baris perintah pinux diimplementasikan pada task 19"
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
