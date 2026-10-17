"""Model pengaturan Pinux.

Perujuk: R9.1 pada requirements.md.

``Settings`` dan dataclass turunannya hanya berisi data dan nilai bawaan.
Pemuatan, penulisan, dan validasi berkas TOML diimplementasikan pada
:class:`pinux.configstore.ConfigStore` (task 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "LibreTranslateSettings",
    "LlmSettings",
    "OcrSettings",
    "PopupSettings",
    "ProviderEntry",
    "Settings",
    "TextProcessingSettings",
    "default_shortcuts",
]


def default_shortcuts() -> dict[str, str]:
    """Kembalikan pintasan bawaan dalam sintaks GTK."""
    return {"translate": "<Control><Alt>T", "ocr": "<Control><Alt>O"}


@dataclass
class PopupSettings:
    """Pengaturan perilaku Popup_Window."""

    pin_default: bool = False
    width: int = 420
    close_on_blur: bool = True


@dataclass
class OcrSettings:
    """Pengaturan mesin OCR."""

    engine: str = "rapidocr"
    enabled: bool = True


@dataclass(frozen=True)
class ProviderEntry:
    """Pendaftaran Translation_Provider pihak ketiga dari berkas pengaturan.

    ``module`` memakai format ``"package.module:ClassName"``, lihat R3.3.
    """

    id: str
    module: str
    label: str


@dataclass
class LlmSettings:
    """Endpoint dan model untuk provider OpenAI-compatible (Ollama, OpenAI, dll.)."""

    endpoint_url: str = "https://api.openai.com/v1/chat/completions"
    model: str = "gpt-4o-mini"


@dataclass
class LibreTranslateSettings:
    """Alamat instance LibreTranslate (self-hosted atau publik)."""

    endpoint_url: str = "http://localhost:5000"


@dataclass
class TextProcessingSettings:
    """Pengaturan pembersihan teks sebelum penerjemahan ala Bob."""

    unwrap_lines: bool = False
    remove_hyphens: bool = True
    remove_comments: bool = False
    auto_copy_result: bool = False


@dataclass
class Settings:
    """Seluruh pengaturan Pinux beserta nilai bawaannya."""

    target_language: str = "id"
    fallback_language: str = "en"
    provider: str = "google-free"
    max_chars: int = 5000
    request_timeout_s: float = 10.0
    shortcuts: dict[str, str] = field(default_factory=default_shortcuts)
    popup: PopupSettings = field(default_factory=PopupSettings)
    ocr: OcrSettings = field(default_factory=OcrSettings)
    text_processing: TextProcessingSettings = field(default_factory=TextProcessingSettings)
    llm: LlmSettings = field(default_factory=LlmSettings)
    libretranslate: LibreTranslateSettings = field(default_factory=LibreTranslateSettings)
    #: Provider cadangan berurutan bila provider utama gagal (jaringan/kuota/kunci).
    fallback_providers: list[str] = field(default_factory=list)
    #: Layanan tambahan yang hasilnya ditampilkan berdampingan dengan provider utama.
    compare_providers: list[str] = field(default_factory=list)
    providers: list[ProviderEntry] = field(default_factory=list)
