"""Uji unit untuk OpenAICompatibleProvider."""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from pinux.scheduler import CancelToken
from pinux.translate.base import TranslationError, TranslationRequest
from pinux.translate.openai_compatible import OpenAICompatibleProvider


def test_openai_provider_attributes() -> None:
    provider = OpenAICompatibleProvider()
    assert provider.id == "openai"
    assert provider.requires_credential() is True
    assert len(provider.list_languages()) >= 10


def test_openai_provider_missing_key_raises_auth() -> None:
    provider = OpenAICompatibleProvider(endpoint_url="https://api.openai.com/v1/chat/completions")
    req = TranslationRequest("Halo", None, "en")
    with pytest.raises(TranslationError) as exc_info:
        provider.translate(req, credential="")
    assert exc_info.value.kind == "auth"


def test_openai_provider_cancelled_token() -> None:
    provider = OpenAICompatibleProvider()
    token = CancelToken()
    token.cancel()
    req = TranslationRequest("Halo", None, "en")
    with pytest.raises(TranslationError) as exc_info:
        provider.translate(req, credential="sk-test", cancel=token)
    assert exc_info.value.kind == "cancelled"


def test_openai_provider_successful_translation() -> None:
    provider = OpenAICompatibleProvider()
    req = TranslationRequest("Selamat pagi", "id", "en")

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Good morning",
                }
            }
        ]
    }).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = provider.translate(req, credential="sk-valid")
        assert res.text == "Good morning"
        assert res.detected_source_lang == "id"
        assert res.provider_id == "openai"


def test_openai_provider_handles_http_errors() -> None:
    provider = OpenAICompatibleProvider()
    req = TranslationRequest("Testing error", None, "en")

    # 401 Auth error
    err_401 = urllib.error.HTTPError("url", 401, "Unauthorized", {}, io.BytesIO(b""))
    with patch("urllib.request.urlopen", side_effect=err_401):
        with pytest.raises(TranslationError) as exc_info:
            provider.translate(req, credential="sk-bad")
        assert exc_info.value.kind == "auth"

    # 429 Rate limit
    err_429 = urllib.error.HTTPError("url", 429, "Too Many Requests", {}, io.BytesIO(b""))
    with patch("urllib.request.urlopen", side_effect=err_429):
        with pytest.raises(TranslationError) as exc_info:
            provider.translate(req, credential="sk-bad")
        assert exc_info.value.kind == "rate_limit"
