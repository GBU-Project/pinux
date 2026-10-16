"""Uji unit untuk model data dasar dan Protocol inti.

Perujuk: task 3.1 pada tasklist.md, serta R3.2, R7.3, dan R10.3 pada
requirements.md.
"""

from __future__ import annotations

import dataclasses

import pytest

from pinux.capture import CaptureResult
from pinux.config import OcrSettings, PopupSettings, ProviderEntry, Settings
from pinux.ocr.base import OcrEngine, OcrLine, OcrResult
from pinux.scheduler import CancelToken
from pinux.translate.base import (
    ERROR_KINDS,
    Language,
    TranslationError,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
)


class _StubProvider:
    """Provider minimal untuk memverifikasi pemeriksaan Protocol."""

    id = "stub"
    display_name = "Stub"

    def requires_credential(self) -> bool:
        return False

    def list_languages(self) -> list[Language]:
        return [Language(code="id", name="Indonesia")]

    def translate(
        self,
        request: TranslationRequest,
        credential: str | None,
        cancel: CancelToken,
    ) -> TranslationResult:
        return TranslationResult(
            text=request.text,
            detected_source_lang="en",
            provider_id=self.id,
        )


class _StubOcrEngine:
    """Mesin OCR minimal untuk memverifikasi pemeriksaan Protocol."""

    id = "stub-ocr"

    def is_available(self) -> bool:
        return True

    def ensure_model(self, on_progress) -> None:
        on_progress(1.0)

    def recognize(self, image_png: bytes, cancel: CancelToken) -> OcrResult:
        return OcrResult(text="")


# --- Pengujian dataclass ---------------------------------------------------


def test_language_is_frozen() -> None:
    language = Language(code="id", name="Indonesia")

    with pytest.raises(dataclasses.FrozenInstanceError):
        language.code = "en"  # type: ignore[misc]


def test_translation_request_accepts_auto_detect() -> None:
    request = TranslationRequest(text="halo", source_lang=None, target_lang="en")

    assert request.source_lang is None
    assert request.target_lang == "en"


def test_translation_result_keeps_detected_language() -> None:
    result = TranslationResult(
        text="hello",
        detected_source_lang="id",
        provider_id="google-free",
    )

    assert result.detected_source_lang == "id"
    assert result.provider_id == "google-free"


def test_ocr_line_holds_box_and_confidence() -> None:
    line = OcrLine(text="halo", confidence=0.92, box=(0.0, 0.0, 10.0, 20.0))

    assert line.box == (0.0, 0.0, 10.0, 20.0)
    assert line.confidence == pytest.approx(0.92)


def test_ocr_result_lines_default_to_empty() -> None:
    result = OcrResult(text="halo")

    assert result.text == "halo"
    assert list(result.lines) == []


def test_capture_result_records_truncation_and_origin() -> None:
    result = CaptureResult(text="halo", truncated=True, origin="primary")

    assert result.truncated is True
    assert result.origin == "primary"


def test_provider_entry_uses_module_reference() -> None:
    entry = ProviderEntry(
        id="deepl",
        module="pinux_provider_deepl:DeepLProvider",
        label="DeepL",
    )

    assert entry.module == "pinux_provider_deepl:DeepLProvider"


# --- Pengujian nilai bawaan Settings ---------------------------------------


def test_settings_defaults_match_design() -> None:
    settings = Settings()

    assert settings.target_language == "id"
    assert settings.fallback_language == "en"
    assert settings.provider == "google-free"
    assert settings.max_chars == 5000
    assert settings.request_timeout_s == pytest.approx(10.0)
    assert settings.providers == []


def test_settings_default_shortcuts_cover_translate_and_ocr() -> None:
    settings = Settings()

    assert settings.shortcuts == {
        "translate": "<Control><Alt>T",
        "ocr": "<Control><Alt>O",
    }


def test_settings_nested_defaults_are_independent_instances() -> None:
    first = Settings()
    second = Settings()

    assert isinstance(first.popup, PopupSettings)
    assert isinstance(first.ocr, OcrSettings)
    assert first.popup is not second.popup
    assert first.ocr is not second.ocr
    assert first.shortcuts is not second.shortcuts


def test_popup_and_ocr_settings_defaults() -> None:
    assert PopupSettings().pin_default is False
    assert PopupSettings().width == 420
    assert PopupSettings().close_on_blur is True
    assert OcrSettings().engine == "rapidocr"
    assert OcrSettings().enabled is True


# --- Pengujian TranslationError -------------------------------------------


@pytest.mark.parametrize("kind", sorted(ERROR_KINDS))
def test_translation_error_accepts_every_defined_kind(kind: str) -> None:
    error = TranslationError(kind=kind, provider_id="google-free", message="gagal")

    assert error.kind == kind
    assert error.provider_id == "google-free"
    assert error.message == "gagal"
    assert str(error) == "gagal"


def test_translation_error_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="tidak dikenal"):
        TranslationError(kind="unknown", provider_id="google-free", message="gagal")


def test_translation_error_rejects_empty_kind() -> None:
    with pytest.raises(ValueError):
        TranslationError(kind="", provider_id="google-free", message="gagal")


# --- Pengujian pemeriksaan Protocol ---------------------------------------


def test_stub_provider_satisfies_translation_provider_protocol() -> None:
    assert isinstance(_StubProvider(), TranslationProvider)


def test_stub_ocr_engine_satisfies_ocr_engine_protocol() -> None:
    assert isinstance(_StubOcrEngine(), OcrEngine)


def test_object_without_translate_does_not_satisfy_provider_protocol() -> None:
    class _Incomplete:
        id = "incomplete"
        display_name = "Incomplete"

        def requires_credential(self) -> bool:
            return False

        def list_languages(self) -> list[Language]:
            return []

    assert not isinstance(_Incomplete(), TranslationProvider)


# --- Pengujian CancelToken -------------------------------------------------


def test_cancel_token_starts_uncancelled() -> None:
    token = CancelToken()

    assert token.cancelled is False


def test_cancel_token_reports_cancellation() -> None:
    token = CancelToken()
    token.cancel()

    assert token.cancelled is True


def test_cancel_token_cancel_is_idempotent() -> None:
    token = CancelToken()
    token.cancel()
    token.cancel()

    assert token.cancelled is True
