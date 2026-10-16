"""Penyimpanan kredensial API Pinux.

Mengimplementasikan penyimpanan kredensial melalui dua backend:
1. Backend utama: ``gi.repository.Secret`` (Secret Service) dengan skema
   ``org.pinux.Credential`` dan atribut ``{"provider": provider_id}``.
2. Backend fallback: berkas ``$XDG_DATA_HOME/pinux/credentials.toml``
   dengan izin ``0600`` bila Secret Service tidak aktif atau tidak tersedia.

Kredensial tidak pernah ditulis ke ``pinux.toml`` (Properti 6).
Perujuk: R9.2, R9.3 pada requirements.md, serta design.md.
"""

from __future__ import annotations

import os
import stat
import tempfile
import tomllib
from pathlib import Path
from typing import Final

__all__ = [
    "CREDENTIALS_FILE_NAME",
    "CredentialStore",
    "default_credentials_path",
]

#: Nama berkas kredensial fallback di dalam ``$XDG_DATA_HOME/pinux``.
CREDENTIALS_FILE_NAME: Final[str] = "credentials.toml"

_SCHEMA = None


def _get_secret_schema() -> object:
    global _SCHEMA
    if _SCHEMA is None:
        import gi
        gi.require_version("Secret", "1")
        from gi.repository import Secret

        _SCHEMA = Secret.Schema.new(
            "org.pinux.Credential",
            Secret.SchemaFlags.NONE,
            {"provider": Secret.SchemaAttributeType.STRING},
        )
    return _SCHEMA


def default_credentials_path() -> Path:
    """Tentukan lokasi berkas kredensial fallback menurut spesifikasi XDG."""
    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home and data_home.strip():
        base = Path(data_home)
    else:
        base = Path.home() / ".local" / "share"
    return base / "pinux" / CREDENTIALS_FILE_NAME


def _is_secret_service_available() -> bool:
    """Periksa apakah Secret Service tersedia dan memiliki pemilik bus."""
    try:
        import dbus
        bus = dbus.SessionBus()
        if not bus.name_has_owner("org.freedesktop.secrets"):
            return False
    except Exception:
        return False

    try:
        import gi
        gi.require_version("Secret", "1")
        from gi.repository import Secret
        return True
    except Exception:
        return False


def _escape_toml_string(value: str) -> str:
    """Ubah string Python ke bentuk literal string TOML dengan tanda kutip."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\b", "\\b")
        .replace("\f", "\\f")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


class CredentialStore:
    """Penyimpan dan pengelola kredensial provider Pinux.

    Secara otomatis menggunakan Secret Service jika tersedia. Jika tidak,
    beralih ke berkas fallback ``$XDG_DATA_HOME/pinux/credentials.toml``
    berizin ``0600``.
    """

    def __init__(
        self,
        fallback_path: Path | None = None,
        *,
        force_fallback: bool = False,
    ) -> None:
        self._fallback_path = (
            Path(fallback_path) if fallback_path is not None else default_credentials_path()
        )
        self._force_fallback = force_fallback
        self._warnings: list[str] = []

    @property
    def fallback_path(self) -> Path:
        """Lokasi berkas fallback yang digunakan."""
        return self._fallback_path

    @property
    def using_fallback(self) -> bool:
        """True jika saat ini beroperasi menggunakan berkas fallback (bukan Secret Service)."""
        if self._force_fallback:
            return True
        return not _is_secret_service_available()

    @property
    def warnings(self) -> tuple[str, ...]:
        """Daftar pesan peringatan saat fallback aktif."""
        return tuple(self._warnings)

    def is_available(self) -> bool:
        """Periksa apakah penyimpanan kredensial dapat digunakan."""
        return True

    def get(self, provider_id: str) -> str | None:
        """Ambil nilai kredensial untuk ``provider_id``."""
        if not self.using_fallback:
            return self._get_secret(provider_id)
        return self._get_fallback(provider_id)

    def set(self, provider_id: str, credential: str) -> None:
        """Simpan nilai kredensial untuk ``provider_id``."""
        if not self.using_fallback:
            self._set_secret(provider_id, credential)
        else:
            self._set_fallback(provider_id, credential)

    def delete(self, provider_id: str) -> None:
        """Hapus kredensial untuk ``provider_id``."""
        if not self.using_fallback:
            self._delete_secret(provider_id)
        else:
            self._delete_fallback(provider_id)

    # -- Implementasi Secret Service ---------------------------------------

    def _attributes(self, provider_id: str) -> dict[str, str]:
        return {"provider": provider_id}

    def _get_secret(self, provider_id: str) -> str | None:
        try:
            import gi
            gi.require_version("Secret", "1")
            from gi.repository import Secret

            schema = _get_secret_schema()
            return Secret.password_lookup_sync(schema, self._attributes(provider_id), None)
        except Exception:
            return self._get_fallback(provider_id)

    def _set_secret(self, provider_id: str, credential: str) -> None:
        try:
            import gi
            gi.require_version("Secret", "1")
            from gi.repository import Secret

            schema = _get_secret_schema()
            label = f"Pinux Provider Credential: {provider_id}"
            Secret.password_store_sync(
                schema,
                self._attributes(provider_id),
                Secret.COLLECTION_DEFAULT,
                label,
                credential,
                None,
            )
        except Exception:
            self._set_fallback(provider_id, credential)

    def _delete_secret(self, provider_id: str) -> None:
        try:
            import gi
            gi.require_version("Secret", "1")
            from gi.repository import Secret

            schema = _get_secret_schema()
            Secret.password_clear_sync(schema, self._attributes(provider_id), None)
        except Exception:
            self._delete_fallback(provider_id)

    # -- Implementasi Fallback Berkas TOML 0600 ------------------------------

    def _record_fallback_warning(self) -> None:
        msg = (
            "Secret Service tidak tersedia. Kredensial disimpan pada berkas "
            f"lokal berizin 0600 ({self._fallback_path})."
        )
        if msg not in self._warnings:
            self._warnings.append(msg)

    def _load_fallback_dict(self) -> dict[str, str]:
        self._record_fallback_warning()
        try:
            raw = self._fallback_path.read_bytes()
        except FileNotFoundError:
            return {}
        except OSError:
            return {}

        try:
            doc = tomllib.loads(raw.decode("utf-8"))
        except Exception:
            return {}

        creds = doc.get("credentials")
        if not isinstance(creds, dict):
            return {}

        result: dict[str, str] = {}
        for k, v in creds.items():
            if isinstance(v, str):
                result[str(k)] = v
        return result

    def _save_fallback_dict(self, data: dict[str, str]) -> None:
        self._record_fallback_warning()
        parent = self._fallback_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        # Pastikan direktori orang tua aman
        try:
            os.chmod(parent, 0o700)
        except OSError:
            pass

        lines = [
            "# Berkas kredensial Pinux (fallback).",
            "# JANGAN bagikan berkas ini kepada pihak lain.",
            "",
            "[credentials]",
        ]
        for k, v in sorted(data.items()):
            lines.append(f"{_escape_toml_string(k)} = {_escape_toml_string(v)}")
        lines.append("")
        content = "\n".join(lines).encode("utf-8")

        # Tulis secara atomik dengan izin 0600
        temp_fd, temp_name = tempfile.mkstemp(
            prefix=".credentials-",
            suffix=".tmp",
            dir=str(parent),
        )
        try:
            os.fchmod(temp_fd, 0o600)
            with os.fdopen(temp_fd, "wb") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_name, self._fallback_path)
            # Pastikan izin 0600 pada target akhir
            os.chmod(self._fallback_path, 0o600)
        except BaseException:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    def _get_fallback(self, provider_id: str) -> str | None:
        creds = self._load_fallback_dict()
        return creds.get(provider_id)

    def _set_fallback(self, provider_id: str, credential: str) -> None:
        creds = self._load_fallback_dict()
        creds[provider_id] = credential
        self._save_fallback_dict(creds)

    def _delete_fallback(self, provider_id: str) -> None:
        creds = self._load_fallback_dict()
        if provider_id in creds:
            del creds[provider_id]
            self._save_fallback_dict(creds)
