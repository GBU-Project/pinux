"""Proses pekerja OCR.

Proses ini dijalankan sebagai subproses terpisah oleh
:class:`pinux.ocr.client.OcrWorkerClient` dan berbicara melalui protokol JSON
per baris pada stdin/stdout sesuai tabel protokol pada design.md.

Pemisahan proses bertujuan memenuhi R7.5: proses utama Pinux tidak pernah
mengimpor ``onnxruntime`` maupun ``rapidocr``.

Implementasi lengkap berada pada task 13.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Jalankan peladen pekerja OCR dan kembalikan kode keluar proses."""
    raise NotImplementedError(
        "Proses pekerja OCR diimplementasikan pada task 13"
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
