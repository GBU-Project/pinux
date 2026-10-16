"""Uji unit untuk ConfigStore.

Perujuk: task 4.1 pada tasklist.md, serta R9.1, R9.4, dan R9.5 pada
requirements.md.
"""

from __future__ import annotations

import os
import stat
import tomllib
from pathlib import Path

import pytest

from pinux.config import OcrSettings, PopupSettings, ProviderEntry, Settings
from pinux.configstore import (
    CONFIG_FILE_NAME,
    DEFAULT_SETTINGS,
    ConfigStore,
    _decode_error_position,
    default_config_path,
    render_settings,
)


# --- Pemuatan --------------------------------------------------------------


def test_load_missing_file_returns_defaults(config_store: ConfigStore) -> None:
    settings = config_store.load()

    assert settings == Settings()
    assert config_store.warnings == ()


def test_load_applies_values_from_file(config_store: ConfigStore) -> None:
    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    config_store.path.write_text(
        'target_language = "ja"\n'
        'fallback_language = "de"\n'
        'provider = "deepl"\n'
        "max_chars = 1200\n"
        "request_timeout_s = 4.5\n",
        encoding="utf-8",
    )

    settings = config_store.load()

    assert settings.target_language == "ja"
    assert settings.fallback_language == "de"
    assert settings.provider == "deepl"
    assert settings.max_chars == 1200
    assert settings.request_timeout_s == pytest.approx(4.5)
    assert config_store.warnings == ()


def test_load_invalid_toml_returns_defaults_with_line_number(
    config_store: ConfigStore,
) -> None:
    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    # Kesalahan sengaja diletakkan pada baris 2.
    config_store.path.write_text(
        'target_language = "id"\nmax_chars = = 5\n', encoding="utf-8"
    )

    settings = config_store.load()

    assert settings == Settings()
    assert len(config_store.warnings) == 1
    warning = config_store.warnings[0]
    assert warning.line == 2
    assert warning.column is not None
    assert "tidak valid" in warning.message


def test_decode_error_position_falls_back_to_message() -> None:
    """Jalur cadangan untuk Python 3.11 sampai 3.13 tanpa atribut lineno."""
    error = tomllib.TOMLDecodeError("Gagal mengurai (at line 7, column 3)")

    assert _decode_error_position(error) == (7, 3)


def test_decode_error_position_without_position_returns_none() -> None:
    error = tomllib.TOMLDecodeError("Gagal mengurai tanpa posisi")

    assert _decode_error_position(error) == (None, None)


def test_load_non_utf8_file_warns_and_returns_defaults(
    config_store: ConfigStore,
) -> None:
    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    config_store.path.write_bytes(b"target_language = \xff\xfe\n")

    settings = config_store.load()

    assert settings == Settings()
    assert len(config_store.warnings) == 1
    assert config_store.warnings[0].line is None


def test_load_unreadable_path_warns(config_store: ConfigStore) -> None:
    # Direktori tidak dapat dibaca sebagai berkas.
    config_store.path.mkdir(parents=True)

    settings = config_store.load()

    assert settings == Settings()
    assert len(config_store.warnings) == 1
    assert "tidak dapat dibaca" in config_store.warnings[0].message


def test_warnings_are_cleared_between_loads(config_store: ConfigStore) -> None:
    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    config_store.path.write_text("max_chars = = 5\n", encoding="utf-8")
    config_store.load()
    assert config_store.warnings != ()

    config_store.path.write_text("max_chars = 10\n", encoding="utf-8")
    config_store.load()

    assert config_store.warnings == ()


def test_unknown_top_level_key_warns_and_is_ignored(
    config_store: ConfigStore,
) -> None:
    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    config_store.path.write_text('tema = "gelap"\n', encoding="utf-8")

    settings = config_store.load()

    assert settings == Settings()
    assert any("tidak dikenal" in w.message for w in config_store.warnings)


# --- Validasi nilai --------------------------------------------------------


@pytest.mark.parametrize(
    ("snippet", "check"),
    [
        ("max_chars = 0\n", lambda s: s.max_chars == 5000),
        ("max_chars = -5\n", lambda s: s.max_chars == 5000),
        ('max_chars = "banyak"\n', lambda s: s.max_chars == 5000),
        ("max_chars = true\n", lambda s: s.max_chars == 5000),
        ("max_chars = 1.5\n", lambda s: s.max_chars == 5000),
        ("request_timeout_s = 0\n", lambda s: s.request_timeout_s == 10.0),
        ("request_timeout_s = -1\n", lambda s: s.request_timeout_s == 10.0),
        ('request_timeout_s = "lama"\n', lambda s: s.request_timeout_s == 10.0),
        ('target_language = ""\n', lambda s: s.target_language == "id"),
        ("target_language = 5\n", lambda s: s.target_language == "id"),
        ('provider = ""\n', lambda s: s.provider == "google-free"),
        ('fallback_language = ""\n', lambda s: s.fallback_language == "en"),
    ],
)
def test_invalid_value_falls_back_to_default(
    config_store: ConfigStore, snippet: str, check
) -> None:
    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    config_store.path.write_text(snippet, encoding="utf-8")

    settings = config_store.load()

    assert check(settings)
    assert config_store.warnings != ()


def test_valid_timeout_as_integer_is_accepted(config_store: ConfigStore) -> None:
    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    config_store.path.write_text("request_timeout_s = 7\n", encoding="utf-8")

    settings = config_store.load()

    assert settings.request_timeout_s == pytest.approx(7.0)
    assert config_store.warnings == ()


# --- Tabel bersarang -------------------------------------------------------


def test_shortcuts_table_is_parsed(config_store: ConfigStore) -> None:
    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    config_store.path.write_text(
        '[shortcuts]\ntranslate = "<Super>T"\nocr = "<Super>O"\n', encoding="utf-8"
    )

    settings = config_store.load()

    assert settings.shortcuts == {"translate": "<Super>T", "ocr": "<Super>O"}
    assert config_store.warnings == ()


def test_unknown_shortcut_is_kept_with_warning(config_store: ConfigStore) -> None:
    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    config_store.path.write_text(
        '[shortcuts]\ntranslate = "<Super>T"\ncepat = "<Super>C"\n', encoding="utf-8"
    )

    settings = config_store.load()

    assert settings.shortcuts["cepat"] == "<Super>C"
    assert any("tidak dikenal" in w.message for w in config_store.warnings)


def test_shortcut_with_non_string_value_is_dropped(
    config_store: ConfigStore,
) -> None:
    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    config_store.path.write_text(
        '[shortcuts]\ntranslate = 5\nocr = "<Super>O"\n', encoding="utf-8"
    )

    settings = config_store.load()

    assert settings.shortcuts == {"ocr": "<Super>O"}
    assert any("translate" in w.message for w in config_store.warnings)


def test_shortcuts_section_wrong_type_warns(config_store: ConfigStore) -> None:
    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    config_store.path.write_text("shortcuts = 5\n", encoding="utf-8")

    settings = config_store.load()

    assert settings.shortcuts == Settings().shortcuts
    assert any("[shortcuts]" in w.message for w in config_store.warnings)


def test_popup_table_is_parsed(config_store: ConfigStore) -> None:
    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    config_store.path.write_text(
        "[popup]\npin_default = true\nwidth = 640\nclose_on_blur = false\n",
        encoding="utf-8",
    )

    settings = config_store.load()

    assert settings.popup == PopupSettings(
        pin_default=True, width=640, close_on_blur=False
    )
    assert config_store.warnings == ()


def test_popup_invalid_fields_fall_back(config_store: ConfigStore) -> None:
    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    config_store.path.write_text(
        '[popup]\npin_default = "ya"\nwidth = 0\n', encoding="utf-8"
    )

    settings = config_store.load()

    assert settings.popup == PopupSettings()
    assert len(config_store.warnings) == 2


def test_ocr_table_is_parsed(config_store: ConfigStore) -> None:
    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    config_store.path.write_text(
        '[ocr]\nengine = "tesseract"\nenabled = false\n', encoding="utf-8"
    )

    settings = config_store.load()

    assert settings.ocr == OcrSettings(engine="tesseract", enabled=False)
    assert config_store.warnings == ()


def test_ocr_section_wrong_type_warns(config_store: ConfigStore) -> None:
    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    config_store.path.write_text('ocr = "aktif"\n', encoding="utf-8")

    settings = config_store.load()

    assert settings.ocr == OcrSettings()
    assert any("[ocr]" in w.message for w in config_store.warnings)


# --- Provider pihak ketiga -------------------------------------------------


def test_providers_are_parsed(config_store: ConfigStore) -> None:
    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    config_store.path.write_text(
        "[[providers]]\n"
        'id = "deepl"\n'
        'module = "pinux_provider_deepl:DeepLProvider"\n'
        'label = "DeepL"\n',
        encoding="utf-8",
    )

    settings = config_store.load()

    assert settings.providers == [
        ProviderEntry(
            id="deepl",
            module="pinux_provider_deepl:DeepLProvider",
            label="DeepL",
        )
    ]
    assert config_store.warnings == ()


@pytest.mark.parametrize(
    "entry",
    [
        'id = "x"\nmodule = "tanpa_titik_dua"\nlabel = "X"\n',
        'id = "x"\nmodule = "pkg.mod"\nlabel = "X"\n',
        'id = ""\nmodule = "pkg.mod:Cls"\nlabel = "X"\n',
        'id = "x"\nlabel = "X"\n',
    ],
)
def test_invalid_provider_entry_is_skipped(
    config_store: ConfigStore, entry: str
) -> None:
    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    config_store.path.write_text(f"[[providers]]\n{entry}", encoding="utf-8")

    settings = config_store.load()

    assert settings.providers == []
    assert config_store.warnings != ()


def test_providers_section_wrong_type_warns(config_store: ConfigStore) -> None:
    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    config_store.path.write_text('providers = "deepl"\n', encoding="utf-8")

    settings = config_store.load()

    assert settings.providers == []
    assert any("[[providers]]" in w.message for w in config_store.warnings)


# --- Penulisan -------------------------------------------------------------


def test_save_creates_parent_directory(config_store: ConfigStore) -> None:
    assert not config_store.path.parent.exists()

    config_store.save(Settings())

    assert config_store.path.exists()


def test_save_uses_owner_only_permissions(config_store: ConfigStore) -> None:
    config_store.save(Settings())

    mode = stat.S_IMODE(config_store.path.stat().st_mode)

    assert mode == 0o600


def test_saved_file_is_valid_toml_with_header(config_store: ConfigStore) -> None:
    config_store.save(Settings())

    text = config_store.path.read_text(encoding="utf-8")

    assert text.startswith("# Berkas pengaturan Pinux.")
    assert isinstance(tomllib.loads(text), dict)


def test_save_then_load_returns_equal_settings(config_store: ConfigStore) -> None:
    original = Settings(
        target_language="ja",
        fallback_language="de",
        provider="deepl",
        max_chars=900,
        request_timeout_s=3.25,
        shortcuts={"translate": "<Super>T", "ocr": "<Super>O"},
        popup=PopupSettings(pin_default=True, width=700, close_on_blur=False),
        ocr=OcrSettings(engine="tesseract", enabled=False),
        providers=[
            ProviderEntry(id="deepl", module="pkg.mod:Cls", label="DeepL"),
            ProviderEntry(id="lain", module="pkg2.mod2:Cls2", label="Lain"),
        ],
    )

    config_store.save(original)
    loaded = config_store.load()

    assert loaded == original
    assert config_store.warnings == ()


def test_empty_providers_are_not_written(config_store: ConfigStore) -> None:
    config_store.save(Settings(providers=[]))

    text = config_store.path.read_text(encoding="utf-8")

    assert "[[providers]]" not in text
    assert config_store.load().providers == []


def test_rendered_settings_omit_credentials(config_store: ConfigStore) -> None:
    """Berkas pengaturan tidak pernah memuat nilai Credential."""
    secret = "sk-rahasia-jangan-tulis"

    config_store.save(Settings(provider="google-free"))

    text = config_store.path.read_text(encoding="utf-8")
    assert secret not in text
    assert "credential" not in text
    assert "api_key" not in text


def test_failed_write_preserves_previous_file(
    config_store: ConfigStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_store.save(Settings(max_chars=111))
    before = config_store.path.read_bytes()

    def explode(*args: object, **kwargs: object) -> None:
        raise OSError("ruang penyimpanan penuh")

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError, match="penuh"):
        config_store.save(Settings(max_chars=222))

    assert config_store.path.read_bytes() == before


def test_failed_write_removes_temporary_file(
    config_store: ConfigStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_store.save(Settings())

    def explode(*args: object, **kwargs: object) -> None:
        raise OSError("ruang penyimpanan penuh")

    monkeypatch.setattr(os, "fsync", explode)
    with pytest.raises(OSError, match="penuh"):
        config_store.save(Settings(max_chars=333))

    leftovers = [path.name for path in config_store.path.parent.iterdir()]
    assert leftovers == [CONFIG_FILE_NAME]


def test_failed_write_keeps_defaults_loadable(
    config_store: ConfigStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_store.save(Settings(max_chars=111))

    def explode(*args: object, **kwargs: object) -> None:
        raise OSError("ruang penyimpanan penuh")

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError):
        config_store.save(Settings(max_chars=222))

    assert config_store.load().max_chars == 111


# --- Pemantauan ------------------------------------------------------------


def test_poll_changes_reports_false_when_file_is_unchanged(
    config_store: ConfigStore,
) -> None:
    config_store.save(Settings())

    assert config_store.poll_changes() is False


def test_poll_changes_notifies_watchers_on_change(config_store: ConfigStore) -> None:
    config_store.save(Settings())
    received: list[Settings] = []
    config_store.watch(received.append)

    config_store.path.write_text('target_language = "ja"\n', encoding="utf-8")
    changed = config_store.poll_changes()

    assert changed is True
    assert len(received) == 1
    assert received[0].target_language == "ja"


def test_unwatch_stops_notification(config_store: ConfigStore) -> None:
    config_store.save(Settings())
    received: list[Settings] = []
    token = config_store.watch(received.append)

    config_store.unwatch(token)
    config_store.path.write_text('target_language = "ja"\n', encoding="utf-8")
    config_store.poll_changes()

    assert received == []


def test_poll_changes_detects_file_creation(config_store: ConfigStore) -> None:
    received: list[Settings] = []
    config_store.watch(received.append)

    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    config_store.path.write_text('max_chars = 123\n', encoding="utf-8")

    assert config_store.poll_changes() is True
    assert [s.max_chars for s in received] == [123]


def test_close_removes_every_watcher(config_store: ConfigStore) -> None:
    received: list[Settings] = []
    config_store.watch(received.append)

    config_store.close()
    config_store.path.parent.mkdir(parents=True, exist_ok=True)
    config_store.path.write_text('max_chars = 5\n', encoding="utf-8")

    assert config_store.poll_changes() is True
    assert received == []


# --- Lokasi berkas dan nilai bawaan ---------------------------------------


def test_default_config_path_uses_xdg_config_home(
    tmp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = default_config_path()

    assert path == tmp_config_dir / "pinux" / CONFIG_FILE_NAME


def test_default_config_path_falls_back_to_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    path = default_config_path()

    assert path == tmp_path / ".config" / "pinux" / CONFIG_FILE_NAME


def test_default_settings_are_not_shared_with_loaded_values() -> None:
    """load selalu mengembalikan salinan, sehingga DEFAULT_SETTINGS utuh."""
    store = ConfigStore(Path("/tidak/ada/pinux.toml"))

    settings = store.load()
    settings.max_chars = 1
    settings.shortcuts["translate"] = "berubah"
    settings.providers.append(ProviderEntry(id="a", module="a.b:C", label="A"))

    assert DEFAULT_SETTINGS.max_chars == 5000
    assert DEFAULT_SETTINGS.shortcuts["translate"] == "<Control><Alt>T"
    assert DEFAULT_SETTINGS.providers == []


def test_render_settings_is_stable_across_repeated_calls() -> None:
    settings = Settings(
        shortcuts={"ocr": "<Super>O", "translate": "<Super>T"},
        providers=[ProviderEntry(id="a", module="a.b:C", label="A")],
    )

    assert render_settings(settings) == render_settings(settings)


def test_render_settings_quotes_keys_that_are_not_bare() -> None:
    rendered = render_settings(Settings(shortcuts={"tombol cepat": "<Super>C"}))

    assert '"tombol cepat" = "<Super>C"' in rendered
    assert tomllib.loads(rendered)["shortcuts"] == {"tombol cepat": "<Super>C"}


# --- Uji Properti (Properti 10: Pengaturan Atomik & Round-trip) ------------

from hypothesis import given, strategies as st

identifier_st = st.from_regex(r"[a-z][a-z0-9_]*", fullmatch=True)
module_ref_st = st.from_regex(
    r"[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*:[a-zA-Z_][a-zA-Z0-9_]*",
    fullmatch=True,
)
safe_text_st = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc"), blacklist_characters=("\x00", "\n", "\r")),
    min_size=1,
    max_size=30,
)

provider_entry_st = st.builds(
    ProviderEntry,
    id=identifier_st,
    module=module_ref_st,
    label=safe_text_st,
)

popup_settings_st = st.builds(
    PopupSettings,
    pin_default=st.booleans(),
    width=st.integers(min_value=100, max_value=2000),
    close_on_blur=st.booleans(),
)

ocr_settings_st = st.builds(
    OcrSettings,
    engine=identifier_st,
    enabled=st.booleans(),
)

settings_st = st.builds(
    Settings,
    target_language=identifier_st,
    fallback_language=identifier_st,
    provider=identifier_st,
    max_chars=st.integers(min_value=1, max_value=50000),
    request_timeout_s=st.floats(min_value=0.1, max_value=120.0, allow_nan=False, allow_infinity=False),
    shortcuts=st.dictionaries(keys=identifier_st, values=safe_text_st, max_size=5),
    popup=popup_settings_st,
    ocr=ocr_settings_st,
    providers=st.lists(provider_entry_st, max_size=5),
)


@given(settings=settings_st)
def test_property_10_settings_round_trip(tmp_path_factory: pytest.TempPathFactory, settings: Settings) -> None:
    """Properti 10: Settings acak tersimpan lalu termuat kembali dan menghasilkan nilai setara."""
    test_dir = tmp_path_factory.mktemp("cfg_prop")
    store = ConfigStore(test_dir / "pinux.toml")

    store.save(settings)
    loaded = store.load()

    assert loaded.target_language == settings.target_language
    assert loaded.fallback_language == settings.fallback_language
    assert loaded.provider == settings.provider
    assert loaded.max_chars == settings.max_chars
    assert loaded.request_timeout_s == pytest.approx(settings.request_timeout_s, rel=1e-5)
    assert loaded.shortcuts == settings.shortcuts
    assert loaded.popup == settings.popup
    assert loaded.ocr == settings.ocr
    assert loaded.providers == settings.providers
