"""Contoh implementasi Keyed_Provider untuk DeepL API.

Dapat digunakan sebagai acuan penambahan TranslationProvider pihak ketiga
berbasis Credential / API Key (R3.8).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from typing import Final

from pinux.scheduler import CancelToken
from pinux.translate.base import (
    Language,
    TranslationError,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
)

DEEPL_FREE_API: Final[str] = "https://api-free.deepl.com/v2/translate"
DEEPL_PRO_API: Final[str] = "https://api.deepl.com/v2/translate"


class DeepLProvider:
    """Contoh provider DeepL berbasis API Key."""

    id: Final[str] = "deepl"
    display_name: Final[str] = "DeepL"

    def __init__(self, *, timeout_s: float = 10.0) -> None:
        self.timeout_s = timeout_s

    def requires_credential(self) -> bool:
        """DeepL selalu memerlukan API key."""
        return True

    def list_languages(self) -> Sequence[Language]:
        return (
            Language(code="id", name="Indonesian"),
            Language(code="en", name="English"),
            Language(code="de", name="German"),
            Language(code="fr", name="French"),
            Language(code="es", name="Spanish"),
            Language(code="ja", name="Japanese"),
            Language(code="zh", name="Chinese"),
        )

    def translate(
        self,
        request: TranslationRequest,
        credential: str | None = None,
        cancel: CancelToken | None = None,
    ) -> TranslationResult:
        if not credential or not credential.strip():
            raise TranslationError(
                kind="auth",
                provider_id=self.id,
                message="Kredensial API Key DeepL tidak ditemukan. Harap atur di layar pengaturan.",
            )

        if cancel is not None and cancel.cancelled:
            raise TranslationError(
                kind="cancelled",
                provider_id=self.id,
                message="Permintaan penerjemahan dibatalkan",
            )

        endpoint = DEEPL_FREE_API if credential.endswith(":fx") else DEEPL_PRO_API

        data = {
            "text": [request.text],
            "target_lang": request.target_lang.upper(),
        }
        if request.source_lang:
            data["source_lang"] = request.source_lang.upper()

        body = json.dumps(data).encode("utf-8")
        headers = {
            "Authorization": f"DeepL-Auth-Key {credential}",
            "Content-Type": "application/json",
            "User-Agent": "Pinux/0.1.0",
        }

        req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                if cancel is not None and cancel.cancelled:
                    raise TranslationError(
                        kind="cancelled",
                        provider_id=self.id,
                        message="Permintaan penerjemahan dibatalkan",
                    )
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                kind = "auth"
                msg = "Kredensial DeepL salah atau tidak valid (HTTP 403)."
            elif exc.code == 429:
                kind = "rate_limit"
                msg = "Batas kuota / laju permintaan DeepL tercapai (HTTP 429)."
            else:
                kind = "provider"
                msg = f"Galat DeepL HTTP {exc.code}: {exc.reason}"
            raise TranslationError(kind=kind, provider_id=self.id, message=msg) from exc
        except Exception as exc:
            raise TranslationError(
                kind="network",
                provider_id=self.id,
                message=f"Gagal menghubungi DeepL API: {exc}",
            ) from exc

        translations = payload.get("translations", [])
        if not translations:
            raise TranslationError(
                kind="provider",
                provider_id=self.id,
                message="DeepL tidak mengembalikan hasil terjemahan.",
            )

        first = translations[0]
        detected = first.get("detected_source_language", request.source_lang or "auto").lower()
        return TranslationResult(
            text=first.get("text", ""),
            detected_source_lang=detected,
            provider_id=self.id,
        )
