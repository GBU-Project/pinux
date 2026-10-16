"""Token pembatalan permintaan.

``CancelToken`` dipakai oleh Translation_Provider dan OcrEngine untuk
mengetahui bahwa permintaan sudah tidak diperlukan lagi, sehingga pekerjaan
jaringan atau pengenalan dapat dihentikan lebih awal.

Perujuk: R10.4 pada requirements.md.

Catatan implementasi: token aman dipakai lintas thread. ``cancel`` boleh
dipanggil dari thread utama sedangkan ``cancelled`` dibaca dari worker thread.
"""

from __future__ import annotations

import threading

__all__ = ["CancelToken"]


class CancelToken:
    """Penanda pembatalan yang aman dipakai lintas thread."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Tandai permintaan sebagai dibatalkan."""
        self._event.set()

    @property
    def cancelled(self) -> bool:
        """Kembalikan ``True`` bila permintaan sudah dibatalkan."""
        return self._event.is_set()
