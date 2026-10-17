"""Mode bandingkan: terjemahkan dengan beberapa layanan sekaligus.

``CompareProvider`` memenuhi Protocol ``TranslationProvider``. Layanan utama
menentukan hasil utama (dan galatnya); layanan tambahan berjalan paralel dan
hasilnya disertakan di ``TranslationResult.alternatives``. Galat layanan
tambahan tidak pernah menggagalkan hasil utama.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from collections.abc import Sequence

from pinux.scheduler import CancelToken
from pinux.translate.base import (
    AlternativeResult,
    Language,
    TranslationError,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
)

__all__ = ["CompareProvider"]

logger = logging.getLogger(__name__)


class CompareProvider:
    """Jalankan ``primary`` dan ``extras`` bersamaan; gabungkan hasilnya."""

    def __init__(
        self,
        primary: TranslationProvider,
        extras: Sequence[tuple[TranslationProvider, str | None]],
        *,
        extra_timeout_s: float = 15.0,
    ) -> None:
        self._primary = primary
        self._extras = tuple(extras)
        self._extra_timeout_s = extra_timeout_s
        self.id = primary.id
        self.display_name = primary.display_name

    def requires_credential(self) -> bool:
        return self._primary.requires_credential()

    def list_languages(self) -> Sequence[Language]:
        return self._primary.list_languages()

    def translate(
        self,
        request: TranslationRequest,
        credential: str | None,
        cancel: CancelToken | None = None,
    ) -> TranslationResult:
        slots: list[AlternativeResult | None] = [None] * len(self._extras)

        def run(index: int, provider: TranslationProvider, cred: str | None) -> None:
            try:
                res = provider.translate(request, cred, cancel)  # type: ignore[arg-type]
                slots[index] = AlternativeResult(provider.id, provider.display_name, text=res.text)
            except TranslationError as err:
                slots[index] = AlternativeResult(provider.id, provider.display_name, error=err.message)
            except Exception as exc:  # layanan tambahan tidak boleh merusak hasil utama
                logger.warning("Layanan %s gagal: %s", provider.id, exc)
                slots[index] = AlternativeResult(provider.id, provider.display_name, error=str(exc))

        threads = [
            threading.Thread(target=run, args=(i, p, c), daemon=True)
            for i, (p, c) in enumerate(self._extras)
        ]
        for t in threads:
            t.start()

        # Hasil utama; bila gagal, galatnya diteruskan apa adanya.
        result = self._primary.translate(request, credential, cancel)  # type: ignore[arg-type]

        for t in threads:
            t.join(self._extra_timeout_s)
        alternatives = tuple(
            slot
            or AlternativeResult(p.id, p.display_name, error="Waktu habis")
            for slot, (p, _c) in zip(slots, self._extras)
        )
        return dataclasses.replace(result, alternatives=alternatives)
