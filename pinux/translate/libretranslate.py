"""Provider LibreTranslate (self-hosted atau instance publik)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from pinux.scheduler import CancelToken
from pinux.translate._http import post_json, validate_endpoint
from pinux.translate.base import Language, TranslationError, TranslationRequest, TranslationResult
from pinux.translate.openai_compatible import SUPPORTED_LANGUAGES

__all__ = ["LibreTranslateProvider"]

DEFAULT_ENDPOINT: Final[str] = "http://localhost:5000"


class LibreTranslateProvider:
    """LibreTranslate; API key opsional (bergantung instance)."""

    id: Final[str] = "libretranslate"
    display_name: Final[str] = "LibreTranslate"

    def __init__(self, endpoint_url: str = DEFAULT_ENDPOINT, *, timeout_s: float = 15.0) -> None:
        self.endpoint_url = endpoint_url
        self.timeout_s = timeout_s

    def requires_credential(self) -> bool:
        return False

    def list_languages(self) -> Sequence[Language]:
        return SUPPORTED_LANGUAGES

    def translate(
        self,
        request: TranslationRequest,
        credential: str | None = None,
        cancel: CancelToken | None = None,
    ) -> TranslationResult:
        payload: dict[str, object] = {
            "q": request.text,
            "source": request.source_lang or "auto",
            "target": request.target_lang,
            "format": "text",
        }
        key = (credential or "").strip()
        validate_endpoint(self.endpoint_url, provider_id=self.id, secret_present=bool(key))
        if key:
            payload["api_key"] = key

        data = post_json(
            self.endpoint_url.rstrip("/") + "/translate",
            payload,
            provider_id=self.id,
            timeout_s=self.timeout_s,
            cancel=cancel,
        )
        try:
            text = data["translatedText"]
            detected = (data.get("detectedLanguage") or {}).get("language")
        except (KeyError, TypeError, AttributeError) as err:
            raise TranslationError("provider", self.id, "Format respons LibreTranslate tidak dikenal") from err
        if not isinstance(text, str):
            raise TranslationError("provider", self.id, "Format respons LibreTranslate tidak dikenal")
        return TranslationResult(
            text=text,
            detected_source_lang=detected or request.source_lang or "auto",
            provider_id=self.id,
        )
