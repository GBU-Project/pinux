"""Provider DeepL API (Free dan Pro)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from pinux.scheduler import CancelToken
from pinux.translate._http import post_json
from pinux.translate.base import (
    Language,
    TranslationError,
    TranslationRequest,
    TranslationResult,
)
from pinux.translate.openai_compatible import SUPPORTED_LANGUAGES

__all__ = ["DeepLProvider", "to_deepl_target"]

FREE_ENDPOINT: Final[str] = "https://api-free.deepl.com/v2/translate"
PRO_ENDPOINT: Final[str] = "https://api.deepl.com/v2/translate"

#: DeepL membedakan varian untuk bahasa tujuan tertentu.
_TARGET_VARIANTS: Final[dict[str, str]] = {"en": "EN-US", "pt": "PT-BR"}
#: Bahasa yang tidak didukung DeepL.
_UNSUPPORTED: Final[frozenset[str]] = frozenset({"vi", "th"})


def to_deepl_target(code: str) -> str:
    """Kode bahasa tujuan Pinux → DeepL (``en`` → ``EN-US``, ``zh`` → ``ZH``)."""
    low = code.lower()
    return _TARGET_VARIANTS.get(low, low.upper())


class DeepLProvider:
    """DeepL; kunci berakhiran ``:fx`` memakai endpoint Free, selain itu Pro."""

    id: Final[str] = "deepl"
    display_name: Final[str] = "DeepL"

    def __init__(self, *, timeout_s: float = 15.0, endpoint_override: str | None = None) -> None:
        self.timeout_s = timeout_s
        #: Hanya untuk pengujian (server lokal); None memakai endpoint resmi.
        self.endpoint_override = endpoint_override

    def requires_credential(self) -> bool:
        return True

    def list_languages(self) -> Sequence[Language]:
        return tuple(lang for lang in SUPPORTED_LANGUAGES if lang.code not in _UNSUPPORTED)

    def translate(
        self,
        request: TranslationRequest,
        credential: str | None = None,
        cancel: CancelToken | None = None,
    ) -> TranslationResult:
        key = (credential or "").strip()
        if not key:
            raise TranslationError("auth", self.id, "API key DeepL belum diisi. Masukkan pada Pengaturan.")

        payload: dict[str, object] = {
            "text": [request.text],
            "target_lang": to_deepl_target(request.target_lang),
        }
        if request.source_lang:
            payload["source_lang"] = request.source_lang.upper()

        endpoint = FREE_ENDPOINT if key.endswith(":fx") else PRO_ENDPOINT
        data = post_json(
            self.endpoint_override or endpoint,
            payload,
            provider_id=self.id,
            headers={"Authorization": f"DeepL-Auth-Key {key}"},
            timeout_s=self.timeout_s,
            cancel=cancel,
        )
        try:
            item = data["translations"][0]
            text = item["text"]
            detected = str(item.get("detected_source_language") or "").lower()
        except (KeyError, IndexError, TypeError, AttributeError) as err:
            raise TranslationError("provider", self.id, "Format respons DeepL tidak dikenal") from err
        return TranslationResult(
            text=text,
            detected_source_lang=detected or request.source_lang or "auto",
            provider_id=self.id,
        )
