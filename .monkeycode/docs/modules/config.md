# pinux/config.py

> **Status**: model dan nilai bawaan sudah ada; pemuatan dan penulisan berkas TOML masih direncanakan.

Modul ini memuat seluruh pengaturan Pinux beserta nilai bawaannya sebagai satu objek yang dapat diteruskan ke komponen lain. Tujuannya memisahkan bentuk data pengaturan dari cara pengaturannya dibaca dan ditulis.

## Struktur

| Simbol | Kegunaan |
|---|---|
| `PopupSettings` | Pengaturan perilaku Popup_Window |
| `OcrSettings` | Pengaturan mesin OCR |
| `ProviderEntry` | Pendaftaran Translation_Provider pihak ketiga dari berkas pengaturan |
| `Settings` | Seluruh pengaturan Pinux |
| `default_shortcuts()` | Mengembalikan pintasan bawaan dalam sintaks GTK |

## Nilai Bawaan

| Bidang | Bawaan | Keterangan |
|---|---|---|
| `target_language` | `"id"` | Bahasa tujuan penerjemahan |
| `fallback_language` | `"en"` | Dipakai ketika Source_Language sama dengan Target_Language |
| `provider` | `"google-free"` | Free_Provider bawaan |
| `max_chars` | `5000` | Batas panjang Source_Text |
| `request_timeout_s` | `10.0` | Batas waktu satu permintaan penerjemahan |
| `shortcuts` | `translate`, `ocr` | Pintasan dalam sintaks GTK |
| `popup.pin_default` | `False` | Keadaan pin awal |
| `popup.width` | `420` | Lebar popup dalam piksel |
| `popup.close_on_blur` | `True` | Menutup popup saat kehilangan fokus |
| `ocr.engine` | `"rapidocr"` | Mesin OCR yang dipakai |
| `ocr.enabled` | `True` | Mengaktifkan aksi OCR |
| `providers` | `[]` | Daftar provider pihak ketiga |

## Bentuk Data

```python
@dataclass(frozen=True)
class ProviderEntry:
    id: str
    module: str     # format "package.module:ClassName"
    label: str

@dataclass
class Settings:
    target_language: str = "id"
    fallback_language: str = "en"
    provider: str = "google-free"
    max_chars: int = 5000
    request_timeout_s: float = 10.0
    shortcuts: dict[str, str] = field(default_factory=default_shortcuts)
    popup: PopupSettings = field(default_factory=PopupSettings)
    ocr: OcrSettings = field(default_factory=OcrSettings)
    providers: list[ProviderEntry] = field(default_factory=list)
```

`ProviderEntry` ditandai `frozen=True` karena mewakili nilai yang tidak berubah. Dataclass lain tidak dibekukan karena diubah oleh jendela pengaturan.

## Dependensi

**Modul ini bergantung pada:** tidak ada modul Pinux lain.

**Bergantung pada modul ini:**

- `pinux.configstore.ConfigStore` (direncanakan) - memuat dan menyimpan berkas TOML, task 4
- `pinux.ui.popup` (direncanakan) - batas karakter dan perilaku pin
- `pinux.ui.settings` (direncanakan) - menampilkan dan mengubah pengaturan
- `pinux.translate.registry` (direncanakan) - provider aktif dan daftar provider pihak ketiga

## Lokasi Berkas

Berkas pengaturan berada pada `$XDG_CONFIG_HOME/pinux/pinux.toml`, dengan nilai bawaan `~/.config/pinux/pinux.toml`.

Berkas ini tidak pernah memuat nilai Credential. Credential disimpan pada Secret Service, atau pada `$XDG_DATA_HOME/pinux/credentials.toml` dengan izin `0600` ketika Secret Service tidak tersedia.

## Pengujian

| Berkas | Cakupan |
|---|---|
| `tests/test_models.py` | Nilai bawaan, kemandirian instance bersarang, dan konstruksi `ProviderEntry` |
| `tests/test_configstore.py` | Rencana pemuatan, penulisan atomik, dan TOML tidak valid, task 4.1 |
| `tests/test_config_properties.py` | Rencana Properti 10, task 4.2 |

## Menambahkan Pengaturan Baru

1. Tambahkan field beserta nilai bawaan pada dataclass terkait.
2. Tambahkan pemetaan kunci TOML beserta validasi rentang nilainya pada `ConfigStore`.
3. Tambahkan pengujian nilai bawaan pada `tests/test_models.py`.
4. Tambahkan kendali pada jendela pengaturan.
5. Perbarui `INTERFACES.md` dan dokumen ini.

**Daftar periksa:**

- [ ] Tersedia nilai bawaan yang aman
- [ ] Ada pemetaan kunci TOML dan validasi
- [ ] Ada pengujian nilai bawaan
- [ ] Dokumentasi diperbarui
