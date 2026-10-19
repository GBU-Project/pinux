"""Model data dan antarmuka TranslationProvider.

Perujuk: R3.2, R4.1, R10.3 pada requirements.md.

Antarmuka ``TranslationProvider`` sengaja didefinisikan sebagai ``Protocol``
sehingga provider pihak ketiga tidak perlu mewarisi kelas dasar dari Pinux.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, Sequence, runtime_checkable

from pinux.scheduler import CancelToken

__all__ = [
    "ERROR_KINDS",
    "ErrorKind",
    "AlternativeResult",
    "DictionaryEntry",
    "Language",
    "TranslationError",
    "TranslationProvider",
    "TranslationRequest",
    "TranslationResult",
]


ErrorKind = Literal["network", "timeout", "auth", "rate_limit", "provider", "cancelled"]

#: Himpunan nilai ``kind`` yang sah. Dipakai untuk memvalidasi TranslationError
#: pada saat pembuatan objek, lihat R10.3.
ERROR_KINDS: frozenset[str] = frozenset(
    {"network", "timeout", "auth", "rate_limit", "provider", "cancelled"}
)


@dataclass(frozen=True)
class Language:
    """Satu bahasa yang dikenali Translation_Provider.

    ``code`` memakai kode BCP-47 sederhana, misalnya ``"id"`` atau ``"en"``.
    """

    code: str
    name: str


@dataclass(frozen=True)
class TranslationRequest:
    """Permintaan penerjemahan.

    ``source_lang`` bernilai ``None`` untuk meminta deteksi otomatis, lihat R4.1.
    """

    text: str
    source_lang: str | None
    target_lang: str


@dataclass(frozen=True)
class AlternativeResult:
    """Hasil dari layanan tambahan pada mode bandingkan; ``error`` terisi bila gagal."""

    provider_id: str
    display_name: str
    text: str = ""
    error: str = ""


@dataclass(frozen=True)
class DictionaryEntry:
    """Entri kamus untuk satu kelas kata (noun, verb, dsb.) beserta definisi/sinonimnya."""

    part_of_speech: str
    terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class TranslationResult:
    """Hasil penerjemahan beserta Source_Language yang terdeteksi."""

    text: str
    detected_source_lang: str
    provider_id: str
    #: Hasil layanan tambahan (mode bandingkan); kosong pada penggunaan biasa.
    alternatives: tuple[AlternativeResult, ...] = ()
    #: Simbol fonetik (IPA/pinyin/transliterasi bila tersedia untuk kata tunggal).
    phonetic: str = ""
    #: Entri kamus (kata tunggal): part of speech dan sinonim/artinya.
    dictionary_entries: tuple[DictionaryEntry, ...] = ()



class TranslationError(Exception):
    """Galat dari Translation_Provider.

    ``kind`` hanya menerima nilai pada :data:`ERROR_KINDS`. Nilai di luar itu
    ditolak dengan ``ValueError`` agar pemetaan galat provider tetap konsisten.
    """

    def __init__(
        self,
        kind: ErrorKind,
        provider_id: str,
        message: str,
    ) -> None:
        if kind not in ERROR_KINDS:
            raise ValueError(
                f"TranslationError.kind tidak dikenal: {kind!r}; "
                f"nilai yang sah: {sorted(ERROR_KINDS)}"
            )
        super().__init__(message)
        self.kind: str = kind
        self.provider_id = provider_id
        self.message = message


@runtime_checkable
class TranslationProvider(Protocol):
    """Antarmuka yang harus dipenuhi setiap mesin penerjemahan.

    Perujuk: R3.2 pada requirements.md.
    """

    #: Pengenal unik provider, dipakai pada ``pinux.toml`` dan layar pengaturan.
    id: str

    #: Nama tampilan provider pada layar pengaturan.
    display_name: str

    def requires_credential(self) -> bool:
        """Kembalikan ``True`` bila provider memerlukan Credential."""
        ...

    def list_languages(self) -> Sequence[Language]:
        """Kembalikan daftar bahasa yang didukung provider."""
        ...

    def translate(
        self,
        request: TranslationRequest,
        credential: str | None,
        cancel: CancelToken,
    ) -> TranslationResult:
        """Terjemahkan ``request`` dan kembalikan hasilnya.

        Wajib memunculkan :class:`TranslationError` untuk setiap kegagalan,
        bukan pengecualian lain, lihat R10.3.
        """
        ...
