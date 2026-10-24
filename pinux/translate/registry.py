"""Registri TranslationProvider untuk Pinux.

Mengelola siklus hidup dan penemuan TranslationProvider dari:
1. Provider bawaan (``google-free``)
2. Berkas konfigurasi ``pinux.toml`` (entri ``[[providers]]`` dengan format ``module:ClassName``)
3. Entry points Python grup ``pinux.providers``

Mendukung isolasi kegagalan impor (Properti 9) dan pemeriksaan ketersediaan
provider berdasarkan kebutuhan kredensial (R3.7).

Perujuk: R3.3, R3.4, R3.7, R3.8 pada requirements.md, serta design.md.
"""

from __future__ import annotations

import importlib
import logging
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

if sys.version_info >= (3, 10):
    from importlib.metadata import entry_points
else:
    from importlib_metadata import entry_points  # type: ignore

from pinux.config import ProviderEntry
from pinux.credentials import CredentialStore
from pinux.translate.base import (
    CancelToken,
    Language,
    TranslationError,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
)
from pinux.translate.chain import FallbackChain
from pinux.translate.compare import CompareProvider
from pinux.translate.deepl import DeepLProvider
from pinux.translate.google_free import GoogleFreeProvider
from pinux.translate.libretranslate import LibreTranslateProvider
from pinux.translate.openai_compatible import OpenAICompatibleProvider

__all__ = [
    "ENTRY_POINT_GROUP",
    "ProviderInfo",
    "ProviderRegistry",
    "load_provider_from_string",
]

ENTRY_POINT_GROUP: Final[str] = "pinux.providers"
logger = logging.getLogger("pinux.translate.registry")


class _ProviderAlias:
    """Alias provider dengan ID yang di-override dari konfigurasi.

    Memungkinkan pengguna mendaftarkan instance kedua provider yang sama
    (mis. dua endpoint DeepL) dengan ID berbeda.
    """

    def __init__(self, inner: TranslationProvider, alias_id: str) -> None:
        self._inner = inner
        self.id = alias_id
        self.display_name = getattr(inner, "display_name", alias_id)

    def requires_credential(self) -> bool:
        return self._inner.requires_credential()

    def list_languages(self) -> Sequence[Language]:
        return self._inner.list_languages()

    def translate(
        self,
        request: TranslationRequest,
        credential: str | None,
        cancel: CancelToken | None = None,
    ) -> TranslationResult:
        return self._inner.translate(request, credential, cancel)


@dataclass(frozen=True)
class ProviderInfo:
    """Informasi dan status ketersediaan TranslationProvider."""

    provider: TranslationProvider
    available: bool
    reason: str | None = None


def load_provider_from_string(module_class_str: str) -> TranslationProvider:
    """Muat instance TranslationProvider dari string dengan format 'package.module:ClassName'.

    Memunculkan ValueError atau ImportError jika format tidak valid atau modul gagal dimuat.
    """
    if ":" not in module_class_str:
        raise ValueError(
            f"Format tidak valid: {module_class_str!r}; harus berupa 'module:ClassName'"
        )

    mod_name, class_name = module_class_str.split(":", 1)
    mod_name = mod_name.strip()
    class_name = class_name.strip()

    if not mod_name or not class_name:
        raise ValueError(
            f"Format tidak valid: {module_class_str!r}; modul dan kelas tidak boleh kosong"
        )

    module = importlib.import_module(mod_name)
    cls = getattr(module, class_name)
    if not isinstance(cls, type):
        raise TypeError(f"{class_name} pada {mod_name} bukan sebuah class/type")

    instance = cls()
    if not isinstance(instance, TranslationProvider):
        raise TypeError(
            f"Instance dari {module_class_str} tidak memenuhi Protocol TranslationProvider"
        )

    return instance


class ProviderRegistry:
    """Registri untuk mendaftarkan dan menemukan TranslationProvider."""

    def __init__(self, credential_store: CredentialStore | None = None) -> None:
        self._providers: dict[str, TranslationProvider] = {}
        self._credential_store = credential_store
        self._warnings: list[str] = []

        # Cache kredensial agar is_available()/get_info() tidak memanggil
        # Secret Service (D-Bus sinkron) berulang kali di main thread.
        # Invalidasi dilakukan lewat invalidate_credential_cache().
        self._credential_cache: dict[str, str | None] = {}
        self._credential_cache_lock = threading.Lock()

        # Daftarkan provider bawaan
        self.register(GoogleFreeProvider())
        self.register(OpenAICompatibleProvider())
        self.register(LibreTranslateProvider())
        self.register(DeepLProvider())

        if self._credential_store is not None and hasattr(self._credential_store, "connect_changed"):
            self._credential_store.connect_changed(self.invalidate_credential_cache)

    def invalidate_credential_cache(self, provider_id: str | None = None) -> None:
        """Invalidasi cache kredensial.

        Dipanggil setelah pengguna menyimpan/menghapus kredensial di UI,
        atau setelah ConfigStore berubah, agar is_available() akurat.
        ``provider_id=None`` membersihkan seluruh cache.
        """
        with self._credential_cache_lock:
            if provider_id is None:
                self._credential_cache.clear()
            else:
                self._credential_cache.pop(provider_id, None)

    def _get_credential_cached(self, provider_id: str) -> str | None:
        with self._credential_cache_lock:
            if provider_id in self._credential_cache:
                return self._credential_cache[provider_id]
        cred = self._credential_store.get(provider_id) if self._credential_store else None
        with self._credential_cache_lock:
            self._credential_cache[provider_id] = cred
        return cred

    def apply_llm_settings(self, endpoint_url: str, model: str) -> None:
        """Terapkan endpoint/model LLM dari pengaturan ke provider 'openai'."""
        provider = self._providers.get(OpenAICompatibleProvider.id)
        if isinstance(provider, OpenAICompatibleProvider):
            provider.endpoint_url = endpoint_url
            provider.model = model

    def apply_libretranslate_settings(self, endpoint_url: str) -> None:
        """Terapkan alamat instance LibreTranslate dari pengaturan."""
        provider = self._providers.get(LibreTranslateProvider.id)
        if isinstance(provider, LibreTranslateProvider):
            provider.endpoint_url = endpoint_url

    def build_chain(
        self, primary_id: str, fallback_ids: Sequence[str]
    ) -> TranslationProvider | None:
        """Bangun provider utama beserta cadangannya.

        Cadangan yang tidak terdaftar, duplikat, atau belum siap (tanpa kredensial)
        dilewati. Mengembalikan provider utama apa adanya bila tidak ada cadangan.
        """
        primary = self.get(primary_id)
        if primary is None:
            return None
        store = self._credential_store
        members: list[tuple[TranslationProvider, str | None]] = [
            (primary, store.get(primary.id) if store else None)
        ]
        seen = {primary.id}
        for fid in fallback_ids:
            if fid in seen:
                continue
            seen.add(fid)
            candidate = self.get(fid)
            if candidate is None or not self.is_available(candidate):
                continue
            members.append((candidate, store.get(candidate.id) if store else None))
        return primary if len(members) == 1 else FallbackChain(members)

    def build_active(
        self,
        primary_id: str,
        fallback_ids: Sequence[str],
        compare_ids: Sequence[str],
        *,
        extra_timeout_s: float = 15.0,
    ) -> TranslationProvider | None:
        """Provider aktif: rantai fallback, ditambah layanan bandingkan bila ada."""
        base = self.build_chain(primary_id, fallback_ids)
        if base is None:
            return None
        store = self._credential_store
        extras: list[tuple[TranslationProvider, str | None]] = []
        seen = {primary_id}
        for cid in compare_ids:
            if cid in seen:
                continue
            seen.add(cid)
            candidate = self.get(cid)
            if candidate is None or not self.is_available(candidate):
                continue
            extras.append((candidate, store.get(candidate.id) if store else None))
        if not extras:
            return base
        return CompareProvider(base, extras, extra_timeout_s=extra_timeout_s)

    @property
    def warnings(self) -> tuple[str, ...]:
        """Peringatan kegagalan impor atau pendaftaran."""
        return tuple(self._warnings)

    def register(self, provider: TranslationProvider) -> None:
        """Daftarkan objek provider ke dalam registri."""
        self._providers[provider.id] = provider

    def get(self, provider_id: str) -> TranslationProvider | None:
        """Ambil provider berdasarkan ID-nya."""
        return self._providers.get(provider_id)

    def all(self) -> Sequence[TranslationProvider]:
        """Kembalikan seluruh provider yang terdaftar."""
        return tuple(self._providers.values())

    def is_available(self, provider: TranslationProvider | str) -> bool:
        """Periksa apakah provider siap digunakan.

        Jika provider memerlukan kredensial (Keyed_Provider), kredensial harus tersedia.
        """
        if isinstance(provider, str):
            p = self.get(provider)
            if p is None:
                return False
            provider = p

        if not provider.requires_credential():
            return True

        if self._credential_store is None:
            return False

        cred = self._get_credential_cached(provider.id)
        return bool(cred and cred.strip())

    def get_info(self, provider_id: str) -> ProviderInfo | None:
        """Kembalikan ProviderInfo berisi status ketersediaan provider."""
        provider = self.get(provider_id)
        if provider is None:
            return None

        if not provider.requires_credential():
            return ProviderInfo(provider=provider, available=True)

        if self._credential_store is None:
            return ProviderInfo(
                provider=provider,
                available=False,
                reason="CredentialStore tidak dikonfigurasi",
            )

        cred = self._get_credential_cached(provider.id)
        if not cred or not cred.strip():
            return ProviderInfo(
                provider=provider,
                available=False,
                reason="Kredensial belum dikonfigurasi (memerlukan API key)",
            )

        return ProviderInfo(provider=provider, available=True)

    def all_info(self) -> Sequence[ProviderInfo]:
        """Kembalikan daftar ProviderInfo untuk seluruh provider terdaftar."""
        results: list[ProviderInfo] = []
        for p in self._providers.values():
            info = self.get_info(p.id)
            if info is not None:
                results.append(info)
        return tuple(results)

    def load_from_entries(self, entries: Sequence[ProviderEntry]) -> None:
        """Muat provider dari entri konfigurasi [[providers]].

        Setiap kegagalan impor diisolasi agar provider lain tetap termuat (Properti 9).
        """
        for entry in entries:
            try:
                provider = load_provider_from_string(entry.module)
                if entry.id != provider.id:
                    logger.warning(
                        "Konfigurasi [[providers]] id=%r berbeda dengan provider.id=%r; "
                        "menggunakan entry.id sebagai alias kunci registri.",
                        entry.id,
                        provider.id,
                    )
                provider = _ProviderAlias(provider, entry.id)
                self.register(provider)
            except Exception as exc:
                msg = f"Gagal memuat provider '{entry.id}' dari {entry.module}: {exc}"
                logger.warning(msg)
                self._warnings.append(msg)

    def load_from_entry_points(self) -> None:
        """Muat provider dari entry point grup 'pinux.providers'."""
        try:
            eps = entry_points(group=ENTRY_POINT_GROUP)
        except Exception as exc:
            msg = f"Gagal membaca entry points grup {ENTRY_POINT_GROUP}: {exc}"
            logger.warning(msg)
            self._warnings.append(msg)
            return

        for ep in eps:
            try:
                cls = ep.load()
                instance = cls()
                if isinstance(instance, TranslationProvider):
                    self.register(instance)
                else:
                    msg = f"Entry point {ep.name} bukan implementasi TranslationProvider"
                    logger.warning(msg)
                    self._warnings.append(msg)
            except Exception as exc:
                msg = f"Gagal memuat entry point provider {ep.name}: {exc}"
                logger.warning(msg)
                self._warnings.append(msg)
