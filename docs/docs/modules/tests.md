# tests/

> **Status**: kerangka pengujian dan pengujian lapisan model sudah ada.

Direktori ini memuat pengujian unit, uji properti, dan (nantinya) pengujian integrasi portal.

## Struktur

```
tests/
├── conftest.py               # Fixture bersama dan FakeClipboard
└── test_models.py            # Uji unit lapisan model
```

Berkas berikut masih direncanakan:

```
tests/
├── test_configstore.py       # task 4.1
├── test_config_properties.py # task 4.2
├── test_credentials.py       # task 5.1
├── test_credentials_properties.py  # task 5.2
├── test_translate_google_free.py   # task 6.1
├── test_translate_properties.py    # task 6.2
├── test_translate_registry.py      # task 7.1
├── test_registry_properties.py     # task 7.2
├── test_scheduler.py               # task 8.1
├── test_scheduler_properties.py    # task 8.2 dan 8.3
├── test_capture.py                 # task 10.1
├── test_capture_properties.py      # task 10.2
├── test_ocr_protocol.py            # task 13.1
├── test_ocr_independence.py        # task 13.2
├── test_popup_state.py             # task 15.1
├── test_tray_failure.py            # task 17.1
└── test_portal_integration.py      # task 21.1 sampai 21.4
```

## Menjalankan Pengujian

```bash
.venv/bin/python3 -m pytest                 # seluruh pengujian
.venv/bin/python3 -m pytest -q              # keluaran ringkas
.venv/bin/python3 -m pytest -m integration  # hanya pengujian integrasi
```

## Fixture Bersama

| Fixture | Kegunaan |
|---|---|
| `tmp_config_dir` | Mengarahkan `$XDG_CONFIG_HOME` ke direktori sementara |
| `tmp_data_dir` | Mengarahkan `$XDG_DATA_HOME` ke direktori sementara |
| `fake_clipboard` | Clipboard dalam memori, meniru bagian `GdkClipboard` yang dipakai |

`FakeClipboard` menyediakan `text`, `set_text`, dan `connect_changed`, sehingga pengujian penangkapan teks tidak memerlukan sesi grafis.

Fungsi pembantu `set_xdg_dirs` mengarahkan kedua direktori XDG sekaligus.

## Pengujian Integrasi

Pengujian yang menyentuh sesi desktop nyata ditandai dengan penanda `integration`, dan wajib melewati dirinya sendiri dengan penanda `skip` ketika portal yang dibutuhkan tidak tersedia.

```python
@pytest.mark.integration
def test_bind_shortcuts(portal_available):
    if not portal_available:
        pytest.skip("Portal GlobalShortcuts tidak tersedia")
```

## Uji Properti

Uji properti memakai hypothesis dan mengacu pada properti bernomor pada `design.md`. Setiap properti ditulis pada sub-task tersendiri.

| Properti | Isi | Task |
|---|---|---|
| 3 | Permintaan terbaru menang | 8.2 |
| 4 | Tidak ada keadaan memuat yang tersisa | 8.3 |
| 5 | Panjang Source_Text tidak melebihi batas | 10.2 |
| 6 | Kredensial tidak bocor ke `pinux.toml` | 5.2 |
| 7 | Inti bebas dependensi OCR | 13.2 |
| 8 | Kegagalan tray tidak fatal | 17.1 |
| 9 | Pemuatan provider terisolasi | 7.2 |
| 10 | Pengaturan atomik | 4.2 |

## Cakupan Saat Ini

`tests/test_models.py` memuat 25 pengujian yang mencakup:

- Konstruksi dan kebekuan setiap dataclass
- Nilai bawaan `Settings` beserta kemandirian instance bersarang
- Penerimaan seluruh nilai `ERROR_KINDS` dan penolakan nilai di luar daftar
- Pemeriksaan Protocol terhadap objek yang memenuhi dan yang tidak memenuhi
- Perilaku `CancelToken`
