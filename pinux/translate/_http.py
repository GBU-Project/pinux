"""Pembantu HTTP JSON untuk provider berbasis REST."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

from pinux.scheduler import CancelToken
from pinux.translate.base import TranslationError

__all__ = ["http_status_to_kind", "post_json"]


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
