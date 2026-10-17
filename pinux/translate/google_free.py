"""Provider penerjemahan bawaan menggunakan Google Translate web API.

Menggunakan endpoint publik ``https://translate.googleapis.com/translate_a/single``
tanpa memerlukan kunci API / kredensial (Free_Provider).

Perujuk: R3.1, R4.1, R4.4, R10.1, R10.2, R10.3 pada requirements.md,
serta design.md.
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

__all__ = [
    "ENDPOINT_URL",
    "GoogleFreeProvider",
    "SUPPORTED_LANGUAGES",
    "build_request_url",
    "parse_response",
]

ENDPOINT_URL: Final[str] = "https://translate.googleapis.com/translate_a/single"

#: Bahasa yang didukung oleh GoogleFreeProvider (sekurang-kurangnya id, en, ja, zh, ar).
SUPPORTED_LANGUAGES: Final[tuple[Language, ...]] = (
    Language(code="id", name="Indonesia"),
    Language(code="en", name="Inggris"),
    Language(code="ja", name="Jepang"),
    Language(code="zh", name="Mandarin (Sederhana)"),
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


def build_request_url(
    text: str,
    source_lang: str | None,
    target_lang: str,
    *,
    client: str = "gtx",
    base_url: str = ENDPOINT_URL,
) -> str:
    """Susun URL permintaan untuk endpoint Google Translate single."""
    params = [
        ("client", client),
        ("sl", source_lang if source_lang else "auto"),
        ("tl", target_lang),
        ("dt", "t"),
        ("q", text),
    ]
    query = urllib.parse.urlencode(params)
    return f"{base_url}?{query}"


def parse_response(
    raw_json: str,
    provider_id: str,
    *,
    fallback_source_lang: str = "auto",
) -> TranslationResult:
    """Urai respons JSON dari Google Translate menjadi TranslationResult."""
    try:
        data = json.loads(raw_json)
    except Exception as exc:
        raise TranslationError(
            kind="provider",
            provider_id=provider_id,
            message=f"Gagal mengurai respons dari provider: {exc}",
        ) from exc

    if not isinstance(data, list) or len(data) == 0:
        raise TranslationError(
            kind="provider",
            provider_id=provider_id,
            message="Format respons dari provider tidak sesuai (bukan list)",
        )

    # Bagian terjemahan: elemen pertama biasanya list of segments [[translated, original, ...], ...]
    segments = data[0]
    if not isinstance(segments, list):
        raise TranslationError(
            kind="provider",
            provider_id=provider_id,
            message="Format segmen terjemahan tidak valid",
        )

    translated_pieces: list[str] = []
    for seg in segments:
        if isinstance(seg, list) and len(seg) > 0 and isinstance(seg[0], str):
            translated_pieces.append(seg[0])

    full_translated_text = "".join(translated_pieces)

    # Deteksi bahasa sumber: biasanya ada di data[2] atau data[1] jika berupa string
    detected_lang = fallback_source_lang
    if len(data) > 2 and isinstance(data[2], str) and data[2]:
        detected_lang = data[2]
    elif len(data) > 1 and isinstance(data[1], str) and data[1]:
        detected_lang = data[1]

    return TranslationResult(
        text=full_translated_text,
        detected_source_lang=detected_lang,
        provider_id=provider_id,
    )


class GoogleFreeProvider:
    """Implementasi TranslationProvider untuk Google Translate gratis (tanpa API key)."""

    id: Final[str] = "google-free"
    display_name: Final[str] = "Google Terjemahan (Gratis)"

    def __init__(
        self,
        *,
        timeout_s: float = 10.0,
        base_url: str = ENDPOINT_URL,
        retry_delay_s: float = 1.0,
    ) -> None:
        self.timeout_s = timeout_s
        self.base_url = base_url
        #: Jeda sebelum satu putaran ulang bila semua endpoint membalas 429.
        self.retry_delay_s = retry_delay_s

    def requires_credential(self) -> bool:
        """Provider gratis ini tidak memerlukan API key / kredensial."""
        return False

    def list_languages(self) -> Sequence[Language]:
        """Kembalikan daftar bahasa yang didukung."""
        return SUPPORTED_LANGUAGES

    def _cancelled(self) -> TranslationError:
        return TranslationError(
            kind="cancelled",
            provider_id=self.id,
            message="Permintaan penerjemahan dibatalkan",
        )

    def _rate_limited(self) -> TranslationError:
        return TranslationError(
            kind="rate_limit",
            provider_id=self.id,
            message="Batas laju permintaan tercapai (HTTP 429). Silakan tunggu sebentar.",
        )

    def _try_endpoint(
        self,
        req: urllib.request.Request,
        cancel: CancelToken | None,
    ) -> str:
        """Kirim satu permintaan; kembalikan teks respons atau munculkan TranslationError."""
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as response:
                if cancel is not None and cancel.cancelled:
                    raise self._cancelled()
                text = response.read().decode("utf-8")
        except TranslationError:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise self._rate_limited() from exc
            if exc.code in (401, 403):
                raise TranslationError(
                    kind="auth",
                    provider_id=self.id,
                    message=f"Akses ditolak oleh provider (HTTP {exc.code}).",
                ) from exc
            raise TranslationError(
                kind="provider",
                provider_id=self.id,
                message=f"Provider mengembalikan galat HTTP {exc.code}: {exc.reason}",
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise TranslationError(
                kind="timeout",
                provider_id=self.id,
                message=f"Permintaan melebihi batas waktu {self.timeout_s}s: {exc}",
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise TranslationError(
                    kind="timeout",
                    provider_id=self.id,
                    message=f"Permintaan melebihi batas waktu: {exc.reason}",
                ) from exc
            raise TranslationError(
                kind="network",
                provider_id=self.id,
                message=f"Koneksi jaringan tidak tersedia atau gagal: {exc.reason}",
            ) from exc
        except OSError as exc:
            raise TranslationError(
                kind="network",
                provider_id=self.id,
                message=f"Gagal koneksi jaringan sistem: {exc}",
            ) from exc

        if text.strip().startswith("<"):
            # Halaman blokir HTML / CAPTCHA Google dianggap batas laju.
            raise self._rate_limited()
        return text

    def translate(
        self,
        request: TranslationRequest,
        credential: str | None = None,
        cancel: CancelToken | None = None,
    ) -> TranslationResult:
        """Terjemahkan request ke target_lang.

        Teks dikirim lewat badan POST agar teks panjang tidak melampaui batas
        panjang URL. Endpoint cadangan dicoba bila yang pertama gagal; bila
        semuanya membalas batas laju, satu putaran ulang dicoba setelah jeda.
        Semua kegagalan dipetakan ke TranslationError.
        """
        if cancel is not None and cancel.cancelled:
            raise self._cancelled()

        # Jika teks kosong, kembalikan hasil kosong langsung
        if not request.text.strip():
            return TranslationResult(
                text="",
                detected_source_lang=request.source_lang or "auto",
                provider_id=self.id,
            )

        def _endpoint(client: str, base_url: str) -> str:
            return build_request_url(
                text="",
                source_lang=request.source_lang,
                target_lang=request.target_lang,
                client=client,
                base_url=base_url,
            ).rsplit("&q=", 1)[0]

        urls = [_endpoint("gtx", self.base_url)]
        if self.base_url == ENDPOINT_URL:  # cadangan hanya untuk endpoint bawaan
            urls.append(_endpoint("at", "https://translate.google.com/translate_a/single"))

        body = urllib.parse.urlencode({"q": request.text}).encode("utf-8")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        }

        raw_text: str | None = None
        last_error: TranslationError | None = None
        for attempt in range(2):
            if attempt == 1:
                deadline = time.monotonic() + self.retry_delay_s
                while time.monotonic() < deadline:
                    if cancel is not None and cancel.cancelled:
                        raise self._cancelled()
                    time.sleep(0.05)

            for url in urls:
                if cancel is not None and cancel.cancelled:
                    raise self._cancelled()
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
                try:
                    raw_text = self._try_endpoint(req, cancel)
                    break
                except TranslationError as err:
                    if err.kind == "cancelled":
                        raise
                    last_error = err
            if raw_text is not None:
                break
            if not (
                attempt == 0
                and self.retry_delay_s > 0
                and last_error is not None
                and last_error.kind == "rate_limit"
            ):
                break

        if raw_text is None:
            raise last_error or TranslationError(
                kind="provider",
                provider_id=self.id,
                message="Semua endpoint Google Translate gagal merespons",
            )

        if cancel is not None and cancel.cancelled:
            raise self._cancelled()

        return parse_response(
            raw_text,
            provider_id=self.id,
            fallback_source_lang=request.source_lang or "auto",
        )
