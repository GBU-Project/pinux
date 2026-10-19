"""Pembantu HTTP JSON untuk provider berbasis REST."""

from __future__ import annotations

import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

from pinux.scheduler import CancelToken
from pinux.translate.base import TranslationError

__all__ = ["http_status_to_kind", "is_local_url", "post_json", "validate_endpoint"]


def is_local_url(url: str) -> bool:
    """True bila host URL adalah localhost atau alamat loopback sungguhan.

    Pencocokan awalan seperti ``startswith("127.")`` salah menerima nama host
    ``127.0.0.1.contoh.com``; alamat IP harus lolos ``ipaddress`` sebagai loopback.
    """
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_endpoint(url: str, *, provider_id: str, secret_present: bool) -> None:
    """Tolak skema tak sah, dan pengiriman kunci rahasia lewat HTTP ke host non-lokal."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise TranslationError(
            "network", provider_id, f"Alamat endpoint '{url}' tidak valid; gunakan http:// atau https://"
        )
    if secret_present and parsed.scheme == "http" and not is_local_url(url):
        raise TranslationError(
            "auth",
            provider_id,
            "Pengiriman API key melalui koneksi HTTP tidak aman ditolak. Gunakan HTTPS.",
        )


def http_status_to_kind(code: int) -> str:
    """Petakan kode status HTTP ke ``TranslationError.kind``."""
    if code in (401, 403):
        return "auth"
    if code in (429, 456):  # 456: kuota DeepL habis
        return "rate_limit"
    if code >= 500:
        return "network"
    return "provider"


def post_json(
    url: str,
    payload: Mapping[str, Any],
    *,
    provider_id: str,
    headers: Mapping[str, str] | None = None,
    timeout_s: float = 15.0,
    cancel: CancelToken | None = None,
) -> Any:
    """Kirim POST JSON dan kembalikan hasil JSON; galat dipetakan ke TranslationError."""
    if cancel is not None and cancel.cancelled:
        raise TranslationError("cancelled", provider_id, "Permintaan terjemahan dibatalkan")

    all_headers = {
        "Content-Type": "application/json",
        "User-Agent": "Pinux-Translator/0.1.0",
        **(headers or {}),
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=all_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as err:
        kind = http_status_to_kind(err.code)
        raise TranslationError(kind, provider_id, f"Galat dari layanan (HTTP {err.code})") from err
    except (socket.timeout, TimeoutError) as err:
        raise TranslationError("timeout", provider_id, f"Koneksi timeout: {err}") from err
    except urllib.error.URLError as err:
        if isinstance(err.reason, (socket.timeout, TimeoutError)):
            raise TranslationError("timeout", provider_id, f"Koneksi timeout: {err.reason}") from err
        raise TranslationError(
            "network", provider_id, f"Layanan tidak dapat dijangkau: {err.reason}"
        ) from err

    if cancel is not None and cancel.cancelled:
        raise TranslationError("cancelled", provider_id, "Permintaan terjemahan dibatalkan")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as err:
        raise TranslationError("provider", provider_id, "Respons layanan bukan JSON valid") from err
