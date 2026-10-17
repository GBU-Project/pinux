"""Rantai fallback antar provider.

``FallbackChain`` memenuhi Protocol ``TranslationProvider`` sehingga dapat dipakai
langsung oleh ``RequestScheduler`` tanpa perubahan: ia mencoba provider utama,
lalu provider berikutnya bila terjadi galat yang layak dicoba ulang.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Final

from pinux.scheduler import CancelToken
from pinux.translate.base import (
    Language,
    TranslationError,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
)

__all__ = ["FALLBACK_KINDS", "FallbackChain"]

logger = logging.getLogger(__name__)

#: Galat yang membuat rantai berpindah ke provider berikutnya. "provider" (mis.
#: format respons) dan "auth" (kunci salah) juga layak: provider lain mungkin bekerja.
FALLBACK_KINDS: Final[frozenset[str]] = frozenset(
    {"network", "timeout", "rate_limit", "auth", "provider"}
)


class FallbackChain:
    """Coba provider berurutan; kembalikan hasil pertama yang berhasil.

    ``members`` berisi pasangan (provider, credential). Bila semuanya gagal,
    galat provider PERTAMA (utama) yang dilempar agar pesan tetap relevan.
    """

    def __init__(self, members: Sequence[tuple[TranslationProvider, str | None]]) -> None:
        if not members:
            raise ValueError("FallbackChain memerlukan sedikitnya satu provider")
        self._members = tuple(members)
        primary = self._members[0][0]
        self.id = primary.id
        self.display_name = primary.display_name

    def requires_credential(self) -> bool:
        # Kredensial sudah dipetakan per anggota saat rantai dibuat.
        return False

    def list_languages(self) -> Sequence[Language]:
        return self._members[0][0].list_languages()

    def translate(
        self,
        request: TranslationRequest,
        credential: str | None = None,
        cancel: CancelToken | None = None,
        *,
        on_fallback: Callable[[str, TranslationError], None] | None = None,
    ) -> TranslationResult:
        first_error: TranslationError | None = None
        for provider, cred in self._members:
            if cancel is not None and cancel.cancelled:
                raise TranslationError("cancelled", provider.id, "Permintaan terjemahan dibatalkan")
            try:
                return provider.translate(request, cred, cancel)  # type: ignore[arg-type]
            except TranslationError as err:
                if err.kind not in FALLBACK_KINDS:
                    raise
                logger.info("Provider %s gagal (%s); mencoba berikutnya", provider.id, err.kind)
                if first_error is None:
                    first_error = err
                if on_fallback is not None:
                    on_fallback(provider.id, err)
        assert first_error is not None
        raise first_error
