"""Pemuatan, penulisan, dan pemantauan berkas pengaturan Pinux.

Berkas pengaturan berada pada ``$XDG_CONFIG_HOME/pinux/pinux.toml`` dengan nilai
bawaan ``~/.config/pinux/pinux.toml``.

Tiga sifat penting yang dijaga modul ini:

1. Nilai tidak valid tidak pernah menghentikan Pinux. Setiap nilai yang tidak
   dapat dipakai diganti nilai bawaan disertai peringatan, lihat R9.5.
2. Penulisan bersifat atomik. Penulisan yang gagal tidak merusak berkas
   pengaturan sebelumnya, lihat Properti 10 pada design.md.
3. Pemantauan berkas memungkinkan pengaturan diterapkan tanpa menjalankan ulang
   Pinux, lihat R9.4.

Perujuk: R9.1, R9.4, R9.5 pada requirements.md.
"""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from pinux.config import (
    OcrSettings,
    PopupSettings,
    ProviderEntry,
    Settings,
    TextProcessingSettings,
)

__all__ = [
    "APP_DIR_NAME",
    "CONFIG_FILE_NAME",
    "DEFAULT_SETTINGS",
    "ConfigStore",
    "ConfigWarning",
    "default_config_path",
    "render_settings",
]

#: Nama direktori pengaturan di dalam ``$XDG_CONFIG_HOME``.
APP_DIR_NAME: Final[str] = "pinux"

#: Nama berkas pengaturan.
CONFIG_FILE_NAME: Final[str] = "pinux.toml"

#: Nilai bawaan. Diperlakukan sebagai hanya-baca: :meth:`ConfigStore.load`
#: selalu mengembalikan salinan, sehingga objek ini tidak pernah terubah.
DEFAULT_SETTINGS: Final[Settings] = Settings()

#: Kunci tingkat atas yang dikenali pada berkas pengaturan.
_KNOWN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "target_language",
        "fallback_language",
        "provider",
        "max_chars",
        "request_timeout_s",
        "shortcuts",
        "popup",
        "ocr",
        "text_processing",
        "providers",
    }
)

#: Nama pintasan yang dikenali. Kunci lain tetap disimpan namun diperingatkan.
_KNOWN_SHORTCUTS: Final[frozenset[str]] = frozenset({"translate", "ocr"})

#: Kunci TOML yang boleh ditulis tanpa tanda kutip.
_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")

#: Pola rujukan modul provider, yaitu ``"package.module:ClassName"``.
_MODULE_REFERENCE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")

#: Pengurai posisi pada pesan galat tomllib untuk Python 3.11 sampai 3.13, yang
#: belum menyediakan atribut ``lineno`` dan ``colno``.
_POSITION_IN_MESSAGE = re.compile(r"\(at line (\d+), column (\d+)\)")


@dataclass(frozen=True)
class ConfigWarning:
    """Peringatan atas satu bagian berkas pengaturan yang tidak dapat dipakai.

    ``line`` dan ``column`` bernilai ``None`` bila posisinya tidak diketahui,
    misalnya ketika nilai yang salah tidak berkaitan dengan sintaks TOML.
    """

    message: str
    line: int | None = None
    column: int | None = None


def default_config_path() -> Path:
    """Kembalikan lokasi berkas pengaturan menurut spesifikasi XDG."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_DIR_NAME / CONFIG_FILE_NAME


def _decode_error_position(exc: tomllib.TOMLDecodeError) -> tuple[int | None, int | None]:
    """Ambil nomor baris dan kolom dari TOMLDecodeError.

    Python 3.14 menyediakan atribut ``lineno`` dan ``colno``. Pada versi
    sebelumnya posisi hanya tersedia di dalam pesan galat, sehingga pesan
    tersebut diurai sebagai cadangan.
    """
    line = getattr(exc, "lineno", None)
    column = getattr(exc, "colno", None)
    if line is not None:
        return int(line), int(column) if column is not None else None

    match = _POSITION_IN_MESSAGE.search(str(exc))
    if match is None:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _strip_position_suffix(message: str) -> str:
    """Buang keterangan posisi pada pesan tomllib agar tidak berulang."""
    return _POSITION_IN_MESSAGE.sub("", message).strip()


def _toml_key(key: str) -> str:
    """Tulis kunci TOML, memakai tanda kutip bila bukan kunci sederhana."""
    return key if _BARE_KEY.match(key) else json.dumps(key, ensure_ascii=False)


def _toml_value(value: object) -> str:
    """Tulis satu nilai TOML.

    String dikodekan memakai ``json.dumps`` karena setiap escape yang dihasilkan
    JSON juga sah pada string dasar TOML.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    raise TypeError(f"Tipe nilai tidak dapat ditulis ke TOML: {type(value).__name__}")


def render_settings(settings: Settings) -> str:
    """Ubah ``settings`` menjadi teks TOML.

    Urutan penulisan penting: kunci bernilai tunggal ditulis lebih dulu,
    kemudian tabel, lalu larik tabel.
    """
    lines: list[str] = [
        "# Berkas pengaturan Pinux.",
        "# Kredensial tidak pernah disimpan di sini; lihat CredentialStore.",
        "",
        f"target_language = {_toml_value(settings.target_language)}",
        f"fallback_language = {_toml_value(settings.fallback_language)}",
        f"provider = {_toml_value(settings.provider)}",
        f"max_chars = {_toml_value(settings.max_chars)}",
        f"request_timeout_s = {_toml_value(settings.request_timeout_s)}",
        "",
        "[shortcuts]",
    ]
    for key in sorted(settings.shortcuts):
        lines.append(f"{_toml_key(key)} = {_toml_value(settings.shortcuts[key])}")

    lines += [
        "",
        "[popup]",
        f"pin_default = {_toml_value(settings.popup.pin_default)}",
        f"width = {_toml_value(settings.popup.width)}",
        f"close_on_blur = {_toml_value(settings.popup.close_on_blur)}",
        "",
        "[ocr]",
        f"engine = {_toml_value(settings.ocr.engine)}",
        f"enabled = {_toml_value(settings.ocr.enabled)}",
        "",
        "[text_processing]",
        f"unwrap_lines = {_toml_value(settings.text_processing.unwrap_lines)}",
        f"remove_hyphens = {_toml_value(settings.text_processing.remove_hyphens)}",
        f"remove_comments = {_toml_value(settings.text_processing.remove_comments)}",
        f"auto_copy_result = {_toml_value(settings.text_processing.auto_copy_result)}",
    ]

    for entry in settings.providers:
        lines += [
            "",
            "[[providers]]",
            f"id = {_toml_value(entry.id)}",
            f"module = {_toml_value(entry.module)}",
            f"label = {_toml_value(entry.label)}",
        ]

    return "\n".join(lines) + "\n"


class ConfigStore:
    """Pembaca dan penulis berkas pengaturan Pinux.

    ``path`` dapat diberikan pada pengujian; bila tidak, lokasi ditentukan
    menurut spesifikasi XDG.
    """

    def __init__(self, path: Path | None = None, *, poll_interval_ms: int = 1000) -> None:
        self._path = Path(path) if path is not None else default_config_path()
        self._poll_interval_ms = poll_interval_ms
        self._warnings: list[ConfigWarning] = []
        self._watchers: dict[int, Callable[[Settings], None]] = {}
        self._next_token = 1
        self._timeout_id: int | None = None
        self._signature: tuple[int, int] | None = None

    @property
    def path(self) -> Path:
        """Lokasi berkas pengaturan yang dipakai."""
        return self._path

    @property
    def warnings(self) -> Sequence[ConfigWarning]:
        """Peringatan yang dihasilkan pemuatan terakhir."""
        return tuple(self._warnings)

    # -- Pemuatan ----------------------------------------------------------

    def load(self) -> Settings:
        """Muat pengaturan dari berkas.

        Bila berkas tidak ada atau tidak dapat dipakai, nilai bawaan
        dikembalikan. Setiap nilai yang ditolak tercatat pada
        :attr:`warnings`.
        """
        self._warnings.clear()
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        document = self._read_document()
        if document is not None:
            self._apply(document, settings)
        self._signature = self._current_signature()
        return settings

    def _read_document(self) -> dict[str, Any] | None:
        """Baca dan urai berkas menjadi peta nilai, atau ``None`` bila gagal."""
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            self._warn(f"Berkas pengaturan tidak dapat dibaca: {exc}")
            return None

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            self._warn(f"Berkas pengaturan bukan teks UTF-8 yang sah: {exc}")
            return None

        try:
            return tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            line, column = _decode_error_position(exc)
            self._warn(
                f"Berkas pengaturan tidak valid: {_strip_position_suffix(str(exc))}",
                line=line,
                column=column,
            )
            return None

    def _apply(self, document: Mapping[str, Any], settings: Settings) -> None:
        """Terapkan nilai dari ``document`` ke ``settings`` sambil memvalidasi."""
        settings.target_language = self._read_str(
            document, "target_language", settings.target_language
        )
        settings.fallback_language = self._read_str(
            document, "fallback_language", settings.fallback_language
        )
        settings.provider = self._read_str(document, "provider", settings.provider)
        settings.max_chars = self._read_positive_int(
            document, "max_chars", settings.max_chars
        )
        settings.request_timeout_s = self._read_positive_float(
            document, "request_timeout_s", settings.request_timeout_s
        )

        shortcuts = document.get("shortcuts")
        if shortcuts is not None:
            settings.shortcuts = self._read_shortcuts(shortcuts, settings.shortcuts)

        popup = document.get("popup")
        if popup is not None:
            self._read_popup(popup, settings.popup)

        ocr = document.get("ocr")
        if ocr is not None:
            self._read_ocr(ocr, settings.ocr)

        text_processing = document.get("text_processing")
        if text_processing is not None:
            self._read_text_processing(text_processing, settings.text_processing)

        providers = document.get("providers")
        if providers is not None:
            settings.providers = self._read_providers(providers)

        for key in document:
            if key not in _KNOWN_KEYS:
                self._warn(f"Kunci pengaturan tidak dikenal diabaikan: {key}")

    # -- Pembacaan nilai bertipe ------------------------------------------

    def _read_str(
        self,
        document: Mapping[str, Any],
        key: str,
        current: str,
        *,
        min_length: int = 1,
    ) -> str:
        if key not in document:
            return current
        value = document[key]
        if not isinstance(value, str):
            self._warn(f"Nilai {key} harus berupa teks; nilai bawaan dipakai")
            return current
        if len(value) < min_length:
            self._warn(f"Nilai {key} tidak boleh kosong; nilai bawaan dipakai")
            return current
        return value

    def _read_positive_int(
        self, document: Mapping[str, Any], key: str, current: int
    ) -> int:
        if key not in document:
            return current
        value = document[key]
        # bool adalah subclass int; nilai true dan false tidak sah di sini.
        if isinstance(value, bool) or not isinstance(value, int):
            self._warn(f"Nilai {key} harus berupa bilangan bulat; nilai bawaan dipakai")
            return current
        if value <= 0:
            self._warn(f"Nilai {key} harus lebih besar dari nol; nilai bawaan dipakai")
            return current
        return value

    def _read_positive_float(
        self, document: Mapping[str, Any], key: str, current: float
    ) -> float:
        if key not in document:
            return current
        value = document[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self._warn(f"Nilai {key} harus berupa bilangan; nilai bawaan dipakai")
            return current
        if value <= 0:
            self._warn(f"Nilai {key} harus lebih besar dari nol; nilai bawaan dipakai")
            return current
        return float(value)

    def _read_bool(
        self, table: Mapping[str, Any], key: str, current: bool, prefix: str
    ) -> bool:
        if key not in table:
            return current
        value = table[key]
        if not isinstance(value, bool):
            self._warn(f"Nilai {prefix}{key} harus berupa boolean; nilai bawaan dipakai")
            return current
        return value

    def _read_shortcuts(
        self, table: Any, current: dict[str, str]
    ) -> dict[str, str]:
        if not isinstance(table, Mapping):
            self._warn("Bagian [shortcuts] harus berupa tabel; nilai bawaan dipakai")
            return current
        result: dict[str, str] = {}
        for raw_key, value in table.items():
            key = str(raw_key)
            if not isinstance(value, str) or not value:
                self._warn(
                    f"Pintasan {key} harus berupa teks yang tidak kosong; diabaikan"
                )
                continue
            if key not in _KNOWN_SHORTCUTS:
                self._warn(f"Pintasan {key} tidak dikenal; tetap disimpan")
            result[key] = value
        return result

    def _read_popup(self, table: Any, popup: PopupSettings) -> None:
        if not isinstance(table, Mapping):
            self._warn("Bagian [popup] harus berupa tabel; nilai bawaan dipakai")
            return
        popup.pin_default = self._read_bool(table, "pin_default", popup.pin_default, "popup.")
        popup.close_on_blur = self._read_bool(
            table, "close_on_blur", popup.close_on_blur, "popup."
        )
        popup.width = self._read_positive_int(table, "width", popup.width)

    def _read_ocr(self, table: Any, ocr: OcrSettings) -> None:
        if not isinstance(table, Mapping):
            self._warn("Bagian [ocr] harus berupa tabel; nilai bawaan dipakai")
            return
        ocr.engine = self._read_str(table, "engine", ocr.engine)
        ocr.enabled = self._read_bool(table, "enabled", ocr.enabled, "ocr.")

    def _read_text_processing(self, table: Any, tp: TextProcessingSettings) -> None:
        if not isinstance(table, Mapping):
            self._warn("Bagian [text_processing] harus berupa tabel; nilai bawaan dipakai")
            return
        tp.unwrap_lines = self._read_bool(table, "unwrap_lines", tp.unwrap_lines, "text_processing.")
        tp.remove_hyphens = self._read_bool(table, "remove_hyphens", tp.remove_hyphens, "text_processing.")
        tp.remove_comments = self._read_bool(table, "remove_comments", tp.remove_comments, "text_processing.")
        tp.auto_copy_result = self._read_bool(table, "auto_copy_result", tp.auto_copy_result, "text_processing.")

    def _read_providers(self, table: Any) -> list[ProviderEntry]:
        if not isinstance(table, list):
            self._warn("Bagian [[providers]] harus berupa larik tabel; diabaikan")
            return []

        entries: list[ProviderEntry] = []
        for index, item in enumerate(table):
            label = f"providers[{index}]"
            if not isinstance(item, Mapping):
                self._warn(f"Entri {label} harus berupa tabel; diabaikan")
                continue

            fields: dict[str, str] = {}
            valid = True
            for field_name in ("id", "module", "label"):
                value = item.get(field_name)
                if not isinstance(value, str) or not value:
                    self._warn(
                        f"Entri {label} memerlukan {field_name} berupa teks "
                        "yang tidak kosong; entri diabaikan"
                    )
                    valid = False
                    break
                fields[field_name] = value
            if not valid:
                continue

            if not _MODULE_REFERENCE.match(fields["module"]):
                self._warn(
                    f"Entri {label} memakai module {fields['module']!r} yang tidak "
                    "sesuai bentuk package.module:ClassName; entri diabaikan"
                )
                continue

            entries.append(
                ProviderEntry(
                    id=fields["id"],
                    module=fields["module"],
                    label=fields["label"],
                )
            )
        return entries

    # -- Penulisan ---------------------------------------------------------

    def save(self, settings: Settings) -> None:
        """Tulis pengaturan secara atomik.

        Isi ditulis lebih dulu ke berkas sementara pada direktori yang sama,
        lalu dipindahkan menimpa berkas tujuan dengan ``os.replace``. Bila
        penulisan gagal, berkas tujuan tidak tersentuh dan berkas sementara
        dibersihkan.
        """
        payload = render_settings(settings).encode("utf-8")
        self._path.parent.mkdir(parents=True, exist_ok=True)

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{CONFIG_FILE_NAME}.",
            suffix=".tmp",
            dir=self._path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            # mkstemp membuat berkas dengan izin 0600, dan os.replace membawa
            # izin tersebut ke berkas tujuan.
            os.replace(temporary_path, self._path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise

        self._signature = self._current_signature()

    # -- Pemantauan --------------------------------------------------------

    def watch(self, callback: Callable[[Settings], None]) -> int:
        """Daftarkan ``callback`` untuk dipanggil ketika berkas berubah.

        Kembalikan token yang dapat dipakai pada :meth:`unwatch`. Pemeriksaan
        berkala dijalankan melalui GLib hanya bila ada pelanggan, sehingga
        modul ini tetap dapat dipakai tanpa loop utama.
        """
        token = self._next_token
        self._next_token += 1
        self._watchers[token] = callback
        self._ensure_polling()
        return token

    def unwatch(self, token: int) -> None:
        """Hentikan pemantauan yang terdaftar dengan ``token``."""
        self._watchers.pop(token, None)
        if not self._watchers:
            self._stop_polling()

    def poll_changes(self) -> bool:
        """Periksa perubahan berkas sekali dan beri tahu pelanggan.

        Kembalikan ``True`` bila berkas berubah sejak pembacaan terakhir.
        Metode ini terpisah dari penjadwalan GLib agar dapat dipanggil langsung
        pada pengujian.
        """
        current = self._current_signature()
        if current == self._signature:
            return False

        settings = self.load()
        for callback in list(self._watchers.values()):
            callback(settings)
        return True

    def close(self) -> None:
        """Hentikan pemantauan dan lepaskan seluruh pelanggan."""
        self._watchers.clear()
        self._stop_polling()

    def _ensure_polling(self) -> None:
        if self._timeout_id is not None or not self._watchers:
            return
        # Impor ditunda agar modul ini dapat dipakai tanpa PyGObject.
        from gi.repository import GLib

        self._timeout_id = GLib.timeout_add(self._poll_interval_ms, self._poll)

    def _stop_polling(self) -> None:
        if self._timeout_id is None:
            return
        from gi.repository import GLib

        GLib.source_remove(self._timeout_id)
        self._timeout_id = None

    def _poll(self) -> bool:
        """Callback GLib; selalu mengembalikan ``True`` agar terus berulang."""
        self.poll_changes()
        return True

    def _current_signature(self) -> tuple[int, int] | None:
        try:
            stat = self._path.stat()
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    # -- Peringatan --------------------------------------------------------

    def _warn(
        self, message: str, *, line: int | None = None, column: int | None = None
    ) -> None:
        self._warnings.append(ConfigWarning(message=message, line=line, column=column))
