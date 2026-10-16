"""Uji unit dan properti untuk TranslationProvider google-free.

Perujuk: task 6.1 dan 6.2 pada tasklist.md, R3.1, R4.1, R4.4, R10.1, R10.2, R10.3.
"""

from __future__ import annotations

import io
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, strategies as st

from pinux.scheduler import CancelToken
from pinux.translate.base import (
    ERROR_KINDS,
    TranslationError,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
)
from pinux.translate.google_free import (
    ENDPOINT_URL,
    GoogleFreeProvider,
    SUPPORTED_LANGUAGES,
    build_request_url,
    parse_response,
)


# --- Uji Antarmuka dan Protocol ---------------------------------------------


def test_google_free_implements_protocol() -> None:
    provider = GoogleFreeProvider()
    assert isinstance(provider, TranslationProvider)
    assert provider.id == "google-free"
    assert provider.requires_credential() is False

    languages = provider.list_languages()
    lang_codes = {lang.code for lang in languages}
    # Harus memuat sekurang-kurangnya id, en, ja, zh, ar
    assert {"id", "en", "ja", "zh", "ar"}.issubset(lang_codes)


# --- Uji Penyusunan URL -----------------------------------------------------


def test_build_request_url_query_parameters() -> None:
    url = build_request_url("Halo Dunia", None, "en")
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "translate.googleapis.com"
    assert parsed.path == "/translate_a/single"
    assert params["client"] == ["gtx"]
    assert params["sl"] == ["auto"]
    assert params["tl"] == ["en"]
    assert params["dt"] == ["t"]
    assert params["q"] == ["Halo Dunia"]


def test_build_request_url_with_explicit_source() -> None:
    url = build_request_url("Hello", "en", "id")
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert params["sl"] == ["en"]
    assert params["tl"] == ["id"]


# --- Uji Penguraian Respons JSON -------------------------------------------


def test_parse_response_success() -> None:
    # Format khas respons Google: [[[translated, original, ...], ...], None, "detected_lang"]
    sample_json = json.dumps([
        [
            ["Halo ", "Hello ", None, None],
            ["Dunia", "World", None, None],
        ],
        None,
        "en",
    ])

    result = parse_response(sample_json, "google-free")
    assert result.text == "Halo Dunia"
    assert result.detected_source_lang == "en"
    assert result.provider_id == "google-free"


def test_parse_response_with_fallback_detected_lang() -> None:
    sample_json = json.dumps([
        [["Bonjour", "Hello", None, None]],
    ])

    result = parse_response(sample_json, "google-free", fallback_source_lang="en")
    assert result.text == "Bonjour"
    assert result.detected_source_lang == "en"


def test_parse_response_invalid_json_raises_translation_error() -> None:
    with pytest.raises(TranslationError) as exc_info:
        parse_response("bukan json", "google-free")
    assert exc_info.value.kind == "provider"


def test_parse_response_malformed_structure_raises_translation_error() -> None:
    with pytest.raises(TranslationError) as exc_info:
        parse_response(json.dumps({"error": "not a list"}), "google-free")
    assert exc_info.value.kind == "provider"


# --- Uji Pemanggilan translate dengan urlopen yang dipalsukan ---------------


def test_translate_empty_text_returns_immediately() -> None:
    provider = GoogleFreeProvider()
    result = provider.translate(TranslationRequest(text="   ", source_lang=None, target_lang="id"))
    assert result.text == ""
    assert result.provider_id == "google-free"


def test_translate_success_flow() -> None:
    provider = GoogleFreeProvider()
    sample_json = json.dumps([
        [["Selamat pagi", "Good morning", None, None]],
        None,
        "en",
    ]).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.read.return_value = sample_json
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        req = TranslationRequest(text="Good morning", source_lang=None, target_lang="id")
        result = provider.translate(req)
        assert result.text == "Selamat pagi"
        assert result.detected_source_lang == "en"


def test_translate_cancelled_before_request() -> None:
    provider = GoogleFreeProvider()
    cancel = CancelToken()
    cancel.cancel()

    req = TranslationRequest(text="Good morning", source_lang=None, target_lang="id")
    with pytest.raises(TranslationError) as exc_info:
        provider.translate(req, cancel=cancel)
    assert exc_info.value.kind == "cancelled"


# --- Uji Pemetaan Galat Jaringan dan HTTP -----------------------------------


@pytest.mark.parametrize(
    ("http_code", "expected_kind"),
    [
        (429, "rate_limit"),
        (401, "auth"),
        (403, "auth"),
        (500, "provider"),
        (503, "provider"),
    ],
)
def test_http_errors_mapping(http_code: int, expected_kind: str) -> None:
    provider = GoogleFreeProvider()
    err = urllib.error.HTTPError("http://dummy", http_code, "Err", {}, None)

    with patch("urllib.request.urlopen", side_effect=err):
        req = TranslationRequest(text="Hello", source_lang=None, target_lang="id")
        with pytest.raises(TranslationError) as exc_info:
            provider.translate(req)
        assert exc_info.value.kind == expected_kind


def test_network_timeout_error_mapping() -> None:
    provider = GoogleFreeProvider()
    err = urllib.error.URLError(socket.timeout("waktu habis"))

    with patch("urllib.request.urlopen", side_effect=err):
        req = TranslationRequest(text="Hello", source_lang=None, target_lang="id")
        with pytest.raises(TranslationError) as exc_info:
            provider.translate(req)
        assert exc_info.value.kind == "timeout"


def test_network_unreachable_error_mapping() -> None:
    provider = GoogleFreeProvider()
    err = urllib.error.URLError(OSError("Jaringan tidak terhubung"))

    with patch("urllib.request.urlopen", side_effect=err):
        req = TranslationRequest(text="Hello", source_lang=None, target_lang="id")
        with pytest.raises(TranslationError) as exc_info:
            provider.translate(req)
        assert exc_info.value.kind == "network"


# --- Uji Properti 6.2 (Pemetaan Galat Provider Selalu TranslationError) -----


error_sim_st = st.one_of(
    st.integers(min_value=400, max_value=599).map(
        lambda code: urllib.error.HTTPError("http://dummy", code, f"HTTP {code}", {}, None)
    ),
    st.just(urllib.error.URLError("Network down")),
    st.just(urllib.error.URLError(socket.timeout("Socket timed out"))),
    st.just(TimeoutError("Timeout")),
    st.just(OSError("DNS lookup failed")),
    st.just(ConnectionResetError("Connection reset by peer")),
)


@given(error=error_sim_st)
def test_property_error_mapping_always_yields_valid_translation_error(
    error: Exception,
) -> None:
    """Semua kegagalan jaringan/HTTP harus menghasilkan TranslationError yang valid."""
    provider = GoogleFreeProvider()
    req = TranslationRequest(text="Hello Test", source_lang=None, target_lang="id")

    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(TranslationError) as exc_info:
            provider.translate(req)

        assert exc_info.value.kind in ERROR_KINDS
        assert exc_info.value.provider_id == "google-free"
        assert len(exc_info.value.message) > 0
