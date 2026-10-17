"""Subpaket mesin penerjemahan.

Antarmuka :class:`~pinux.translate.base.TranslationProvider` dan model datanya
didefinisikan pada :mod:`pinux.translate.base`.

Perujuk: R3.2 pada requirements.md.
"""

from pinux.translate.base import (
    Language,
    TranslationError,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
)
from pinux.translate.google_free import GoogleFreeProvider
from pinux.translate.openai_compatible import OpenAICompatibleProvider
from pinux.translate.registry import ProviderRegistry

__all__ = [
    "GoogleFreeProvider",
    "Language",
    "OpenAICompatibleProvider",
    "ProviderRegistry",
    "TranslationError",
    "TranslationProvider",
    "TranslationRequest",
    "TranslationResult",
]
