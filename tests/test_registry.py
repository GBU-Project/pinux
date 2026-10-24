"""Uji unit dan properti untuk ProviderRegistry.

Perujuk: task 7.1 dan 7.2 pada tasklist.md, R3.3, R3.4, R3.7, R3.8,
serta Properti 9 (pemuatan provider terisolasi) pada design.md.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, strategies as st

from examples.deepl_provider import DeepLProvider
from pinux.config import ProviderEntry
from pinux.credentials import CredentialStore
from pinux.translate.base import (
    Language,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
)
from pinux.translate.registry import (
    ProviderInfo,
    ProviderRegistry,
    load_provider_from_string,
)


class DummyMockProvider:
    id = "dummy-mock"
    display_name = "Dummy Mock"

    def requires_credential(self) -> bool:
        return False

    def list_languages(self) -> list[Language]:
        return [Language("id", "Indonesia")]

    def translate(self, req: TranslationRequest, cred: str | None, cancel: object) -> TranslationResult:
        return TranslationResult("Mock", "en", self.id)


# --- Uji Pemuatan Provider dari String ---------------------------------------


def test_load_provider_from_string_success() -> None:
    provider = load_provider_from_string("examples.deepl_provider:DeepLProvider")
    assert isinstance(provider, TranslationProvider)
    assert provider.id == "deepl"
    assert provider.requires_credential() is True


def test_load_provider_from_string_invalid_format() -> None:
    with pytest.raises(ValueError, match="harus berupa 'module:ClassName'"):
        load_provider_from_string("tanpa_titik_dua")


def test_load_provider_from_string_module_not_found() -> None:
    with pytest.raises(ModuleNotFoundError):
        load_provider_from_string("modul_tidak_ada_xyz:NamaKelas")


def test_load_provider_from_string_class_not_found() -> None:
    with pytest.raises(AttributeError):
        load_provider_from_string("examples.deepl_provider:KelasTidakAda")


# --- Uji ProviderRegistry Dasar & Ketersediaan -------------------------------


def test_registry_has_defaults() -> None:
    reg = ProviderRegistry()
    assert reg.get("google-free") is not None
    assert reg.is_available("google-free") is True

    assert reg.get("openai") is not None
    assert reg.get("openai").requires_credential() is True

    info = reg.get_info("google-free")
    assert info is not None
    assert info.available is True


def test_registry_keyed_provider_availability(tmp_path: Path) -> None:
    creds_file = tmp_path / "credentials.toml"
    cred_store = CredentialStore(creds_file, force_fallback=True)
    reg = ProviderRegistry(credential_store=cred_store)

    deepl = DeepLProvider()
    reg.register(deepl)

    # Tanpa kredensial: tidak tersedia (R3.7)
    assert reg.is_available("deepl") is False
    info = reg.get_info("deepl")
    assert info is not None
    assert info.available is False
    assert "Kredensial belum dikonfigurasi" in (info.reason or "")

    # Setelah kredensial diatur: tersedia
    cred_store.set("deepl", "sk-secret-key")
    assert reg.is_available("deepl") is True
    info2 = reg.get_info("deepl")
    assert info2 is not None
    assert info2.available is True


# --- Uji Isolasi Kegagalan Impor (Properti 9) -------------------------------


def test_load_from_entries_isolated_failure() -> None:
    reg = ProviderRegistry()

    entries = [
        ProviderEntry(id="gagal1", module="modul_rusak_123:Kelas", label="Rusak"),
        ProviderEntry(id="deepl", module="examples.deepl_provider:DeepLProvider", label="DeepL"),
        ProviderEntry(id="gagal2", module="examples.deepl_provider:KelasSalah", label="Salah"),
    ]

    reg.load_from_entries(entries)

    # Modul yang valid (deepl) harus tetap termuat
    assert reg.get("deepl") is not None
    # Yang rusak tidak menyebabkan crash dan dicatat ke warnings
    assert len(reg.warnings) == 2
    assert any("gagal1" in w for w in reg.warnings)
    assert any("gagal2" in w for w in reg.warnings)


# --- Uji Pemuatan Entry Points ----------------------------------------------


def test_load_from_entry_points() -> None:
    mock_ep = MagicMock()
    mock_ep.name = "dummy-ep"
    mock_ep.load.return_value = DummyMockProvider

    with patch("pinux.translate.registry.entry_points", return_value=[mock_ep]):
        reg = ProviderRegistry()
        reg.load_from_entry_points()
        assert reg.get("dummy-mock") is not None
        assert reg.is_available("dummy-mock") is True


# --- Uji Properti 9 (Pemuatan Provider Selalu Terisolasi) -------------------


entry_item_st = st.one_of(
    st.just(("valid", "examples.deepl_provider:DeepLProvider")),
    st.just(("invalid_mod", "tidak_ada_xyz_99:Cls")),
    st.just(("invalid_cls", "examples.deepl_provider:TidakAda")),
    st.just(("bad_format", "tanpatitikdua")),
)


@given(items=st.lists(entry_item_st, min_size=1, max_size=10))
def test_property_9_isolated_provider_loading(items: list[tuple[str, str]]) -> None:
    """Properti 9: Kegagalan impor satu modul tidak pernah menggagalkan pemuatan modul lain yang valid."""
    reg = ProviderRegistry()
    entries = [
        ProviderEntry(id=f"prov_{idx}_{k}", module=mod, label=f"Label {idx}")
        for idx, (k, mod) in enumerate(items)
    ]

    reg.load_from_entries(entries)

    # Selalu pastikan google-free tetap ada
    assert reg.get("google-free") is not None

    # Setiap entri yang valid harus berhasil termuat tanpa terganggu yang gagal
    for idx, (k, mod) in enumerate(items):
        if k == "valid":
            # Karena alias dibungkus dengan ProviderEntry.id
            prov_id = f"prov_{idx}_{k}"
            assert reg.get(prov_id) is not None


def test_provider_alias_overrides_id():
    from pinux.translate.registry import _ProviderAlias

    class DummyProvider:
        id = "dummy"
        display_name = "Dummy"

        def requires_credential(self):
            return False

        def list_languages(self):
            return []

        def translate(self, req, cred, cancel=None):
            return None

    alias = _ProviderAlias(DummyProvider(), "dummy-custom")
    assert alias.id == "dummy-custom"
    assert alias.display_name == "Dummy"
    assert alias.requires_credential() is False
    assert alias.list_languages() == []
