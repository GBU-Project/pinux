"""Provider penerjemahan berbasis OpenAI-compatible API (ala Bob translator).

Mendukung endpoint lokal (Ollama, LM Studio, vLLM, LocalAI) maupun cloud
(OpenAI, DeepSeek, Groq, OpenRouter, Together AI).
"""

from __future__ import annotations

import json
import socket
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

__all__ = ["OpenAICompatibleProvider"]

DEFAULT_ENDPOINT: Final[str] = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL: Final[str] = "gpt-4o-mini"

SUPPORTED_LANGUAGES: Final[tuple[Language, ...]] = (
    Language(code="id", name="Indonesia"),
    Language(code="en", name="Inggris"),
    Language(code="ja", name="Jepang"),
    Language(code="zh", name="Mandarin"),
    Language(code="ar", name="Arab"),
    Language(code="de", name="Jerman"),
    Language(code="es", name="Spanyol"),
    Language(code="fr", name="Prancis"),
    Language(code="ko", name="Korea"),
    Language(code="ru", name="Rusia"),
    Language(code="pt", name="Portugis"),
    Language(code="it", name="Italia"),
    Language(code="nl", name="Belanda"),
    Language(code="vi", name="Vietnam"),
    Language(code="th", name="Thailand"),
)


class OpenAICompatibleProvider:
    """Provider LLM berbasis format OpenAI Chat Completions API."""

    id: Final[str] = "openai"
    display_name: Final[str] = "OpenAI / LLM Compatible"

    def __init__(
        self,
        endpoint_url: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        *,
        timeout_s: float = 15.0,
    ) -> None:
        self.endpoint_url = endpoint_url
        self.model = model
        self.timeout_s = timeout_s

    def requires_credential(self) -> bool:
        """Memerlukan API key (bisa token sembarang jika Ollama lokal)."""
        return True

    def list_languages(self) -> Sequence[Language]:
        return SUPPORTED_LANGUAGES

    def translate(
        self,
        request: TranslationRequest,
        credential: str | None = None,
        cancel: CancelToken | None = None,
    ) -> TranslationResult:
        if cancel is not None and cancel.cancelled:
            raise TranslationError(
                kind="cancelled",
                provider_id=self.id,
                message="Permintaan terjemahan dibatalkan",
            )

        api_key = credential.strip() if credential else ""
        if not api_key and "localhost" not in self.endpoint_url and "127.0.0.1" not in self.endpoint_url:
            raise TranslationError(
                kind="auth",
                provider_id=self.id,
                message="API key belum diisi. Masukkan API key pada Pengaturan.",
            )

        src_desc = f"from language '{request.source_lang}' " if request.source_lang else ""
        system_prompt = (
            "You are a professional, accurate translator. "
            f"Translate the following text {src_desc}into language '{request.target_lang}'. "
            "Preserve original formatting. Output ONLY the translated text without explanations or markdown quotes."
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.text},
            ],
            "temperature": 0.3,
        }

        body_bytes = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Pinux-Translator/0.1.0",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        req = urllib.request.Request(
            self.endpoint_url,
            data=body_bytes,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                if cancel is not None and cancel.cancelled:
                    raise TranslationError(
                        kind="cancelled",
                        provider_id=self.id,
                        message="Permintaan terjemahan dibatalkan",
                    )
                resp_bytes = resp.read()
                data = json.loads(resp_bytes.decode("utf-8"))
        except urllib.error.HTTPError as err:
            if err.code in (401, 403):
                kind = "auth"
                msg = f"Autentikasi gagal (HTTP {err.code}): Periksa kembali API Key Anda"
            elif err.code == 429:
                kind = "rate_limit"
                msg = "Batas kuota terlampaui (HTTP 429 Rate Limit)"
            elif err.code >= 500:
                kind = "network"
                msg = f"Server LLM bermasalah (HTTP {err.code})"
            else:
                kind = "provider"
                msg = f"Galat dari API (HTTP {err.code})"
            raise TranslationError(kind=kind, provider_id=self.id, message=msg) from err
        except (urllib.error.URLError, socket.timeout, TimeoutError) as err:
            raise TranslationError(
                kind="timeout",
                provider_id=self.id,
                message=f"Koneksi ke endpoint LLM timeout: {err}",
            ) from err
        except Exception as err:
            raise TranslationError(
                kind="provider",
                provider_id=self.id,
                message=f"Gagal memproses respons LLM: {err}",
            ) from err

        try:
            choices = data.get("choices", [])
            if not choices:
                raise ValueError("Tidak ada pilihan terjemahan pada respons.")
            content = choices[0]["message"]["content"].strip()
        except Exception as err:
            raise TranslationError(
                kind="provider",
                provider_id=self.id,
                message=f"Format respons LLM tidak sesuai: {err}",
            ) from err

        detected_src = request.source_lang or "auto"
        return TranslationResult(
            text=content,
            detected_source_lang=detected_src,
            provider_id=self.id,
        )
