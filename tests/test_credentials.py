"""Uji unit dan properti untuk CredentialStore.

Perujuk: task 5.1 dan 5.2 pada tasklist.md, R9.2, R9.3 pada requirements.md,
serta Properti 6 (kredensial tidak bocor) pada design.md.
"""

from __future__ import annotations

import os
import stat
import tomllib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import assume, given, strategies as st

from pinux.config import Settings
from pinux.configstore import ConfigStore
from pinux.credentials import (
    CREDENTIALS_FILE_NAME,
    CredentialStore,
    default_credentials_path,
)


# --- Pengujian Deteksi Backend dan Peringatan Fallback ----------------------


def test_default_credentials_path_uses_xdg_data_home(
    tmp_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = default_credentials_path()
    assert path == tmp_data_dir / "pinux" / CREDENTIALS_FILE_NAME


def test_default_credentials_path_falls_back_to_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    path = default_credentials_path()
    assert path == tmp_path / ".local" / "share" / "pinux" / CREDENTIALS_FILE_NAME


def test_using_fallback_when_forced(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path / "creds.toml", force_fallback=True)
    assert store.using_fallback is True
    assert store.is_available() is True


def test_using_fallback_when_dbus_secret_service_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with patch("pinux.credentials._is_secret_service_available", return_value=False):
        store = CredentialStore(tmp_path / "creds.toml")
        assert store.using_fallback is True


def test_using_secret_service_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with patch("pinux.credentials._is_secret_service_available", return_value=True):
        store = CredentialStore(tmp_path / "creds.toml")
        assert store.using_fallback is False


# --- Pengujian Fallback File Izin 0600 & Operasi CRUD ----------------------


def test_fallback_file_permissions_and_crud(tmp_path: Path) -> None:
    creds_file = tmp_path / "sub" / "credentials.toml"
    store = CredentialStore(creds_file, force_fallback=True)

    # Initial get on missing file
    assert store.get("deepl") is None
    assert any("Secret Service tidak tersedia" in w for w in store.warnings)

    # Set credential
    store.set("deepl", "secret-key-123")
    assert creds_file.exists()

    # Check file permissions (0600)
    mode = stat.S_IMODE(creds_file.stat().st_mode)
    assert mode == 0o600

    # Get credential
    assert store.get("deepl") == "secret-key-123"

    # Set another credential
    store.set("openai", "sk-proj-456")
    assert store.get("openai") == "sk-proj-456"
    assert store.get("deepl") == "secret-key-123"

    # Delete credential
    store.delete("deepl")
    assert store.get("deepl") is None
    assert store.get("openai") == "sk-proj-456"

    # Verify content format is valid TOML
    data = tomllib.loads(creds_file.read_text(encoding="utf-8"))
    assert data == {"credentials": {"openai": "sk-proj-456"}}

    # Delete remaining
    store.delete("openai")
    assert store.get("openai") is None
    data_after = tomllib.loads(creds_file.read_text(encoding="utf-8"))
    assert data_after == {"credentials": {}}


def test_fallback_handles_corrupt_file_gracefully(tmp_path: Path) -> None:
    creds_file = tmp_path / "credentials.toml"
    creds_file.write_text("bukan toml valid = [", encoding="utf-8")

    store = CredentialStore(creds_file, force_fallback=True)
    assert store.get("deepl") is None

    # Mengeset nilai baru menimpa berkas korup secara aman
    store.set("deepl", "new-key")
    assert store.get("deepl") == "new-key"
    assert stat.S_IMODE(creds_file.stat().st_mode) == 0o600


# --- Mocking Secret Service Sync Operations --------------------------------


def test_secret_service_backend_operations(tmp_path: Path) -> None:
    mock_secret = MagicMock()
    mock_secret.password_lookup_sync.return_value = "my-secret-token"

    with patch("pinux.credentials._is_secret_service_available", return_value=True), \
         patch("gi.repository.Secret", mock_secret, create=True), \
         patch("pinux.credentials._get_secret_schema", return_value=MagicMock()):

        store = CredentialStore(tmp_path / "creds.toml")
        assert store.using_fallback is False

        # Get
        val = store.get("deepl")
        assert val == "my-secret-token"

        # Set
        store.set("deepl", "new-secret")
        mock_secret.password_store_sync.assert_called_once()

        # Delete
        store.delete("deepl")
        mock_secret.password_clear_sync.assert_called_once()


# --- Uji Properti 6 (Kredensial Tidak Bocor) --------------------------------

identifier_st = st.from_regex(r"[a-z][a-z0-9_]*", fullmatch=True)
secret_val_st = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc"), blacklist_characters=("\x00", "\n", "\r")),
    min_size=10,
    max_size=50,
)


@given(provider_id=identifier_st, secret=secret_val_st)
def test_property_6_credentials_do_not_leak_into_pinux_toml(
    tmp_path_factory: pytest.TempPathFactory,
    provider_id: str,
    secret: str,
) -> None:
    """Properti 6: Kredensial tidak pernah bocor ke berkas pinux.toml."""
    # Abaikan jika secret yang di-generate secara acak kebetulan substring dari kata kunci konfigurasi standar (seperti 'unwrap_lines' dll)
    assume(secret not in "unwrap_lines remove_hyphens remove_comments auto_copy_result localhost")
    test_dir = tmp_path_factory.mktemp("prop6")
    config_file = test_dir / "pinux.toml"
    creds_file = test_dir / "credentials.toml"

    config_store = ConfigStore(config_file)
    cred_store = CredentialStore(creds_file, force_fallback=True)

    # Simpan kredensial
    cred_store.set(provider_id, secret)

    # Simpan berbagai variasi pengaturan
    settings = Settings(provider=provider_id)
    config_store.save(settings)

    # Periksa isi berkas konfigurasi pinux.toml
    config_text = config_file.read_text(encoding="utf-8")
    assert secret not in config_text

    # Muat dokumen toml dan pastikan tidak ada data kredensial atau api_key
    doc = tomllib.loads(config_text)
    assert "credential" not in doc
    assert "credentials" not in doc
    assert "api_key" not in doc
    assert secret not in str(doc)

    # Pastikan kredensial tersimpan di cred_store
    assert cred_store.get(provider_id) == secret
