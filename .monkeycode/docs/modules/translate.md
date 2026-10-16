# pinux/translate/

> **Status**: model dan kontrak sudah ada; implementasi provider dan registri masih direncanakan.

Paket ini memuat kontrak mesin penerjemahan beserta model datanya.

## Struktur

```
pinux/translate/
├── __init__.py               # Docstring paket
└── base.py                   # Model data dan Protocol TranslationProvider
```

Berkas berikut masih direncanakan:

```
pinux/translate/
├── google_free.py            # Free_Provider google-free, task 6
├── registry.py               # ProviderRegistry, task 7
└── deepl.py                  # Pola Keyed_Provider, task 7
```

## Berkas Kunci

| Berkas | Kegunaan |
|---|---|
| `base.py` | `Language`, `TranslationRequest`, `TranslationResult`, `TranslationError`, `ERROR_KINDS`, Protocol `TranslationProvider` |

## Dependensi

**Paket ini bergantung pada:**

- `pinux.scheduler` - `CancelToken` yang diterima operasi `translate`

**Bergantung pada paket ini:**

- `pinux.translate.registry` (direncanakan) - memuat dan memilih provider
- `pinux.ui.settings` (direncanakan) - menampilkan daftar provider
- `pinux.scheduler.RequestScheduler` (direncanakan) - memanggil `translate`

Paket ini tidak boleh mengimpor modul GTK.

## Pola Kode

**Setiap kegagalan provider dipetakan ke `TranslationError`:**

```python
try:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = json.load(response)
except urllib.error.HTTPError as exc:
    raise TranslationError(_kind_for_status(exc.code), self.id, str(exc)) from exc
except urllib.error.URLError as exc:
    raise TranslationError("network", self.id, str(exc)) from exc
```

**Pemeriksaan pembatalan di antara tahap permintaan:**

```python
if cancel.cancelled:
    raise TranslationError("cancelled", self.id, "Permintaan dibatalkan")
```

## Penanganan Galat

Seluruh galat keluar sebagai `TranslationError` dengan nilai `kind` pada `ERROR_KINDS`. Pengecualian lain dianggap bug. Lihat `INTERFACES.md` untuk tabel pemetaan kode status HTTP.

## Pengujian

| Berkas | Cakupan |
|---|---|
| `tests/test_models.py` | Bentuk dataclass dan validasi `TranslationError.kind` |
| `tests/test_translate_google_free.py` | Rencana pemetaan galat dan penguraian respons, task 6.1 |
| `tests/test_translate_registry.py` | Rencana isolasi kegagalan impor, task 7.1 |

## Menambahkan Berkas Baru

### Menambahkan provider baru

1. Buat `pinux/translate/<nama>.py` berisi kelas provider.
2. Penuhi seluruh anggota Protocol `TranslationProvider`.
3. Petakan setiap kegagalan ke `TranslationError`.
4. Tambahkan berkas pengujian dengan HTTP yang dipalsukan.

**Daftar periksa:**

- [ ] Nama berkas memakai `snake_case`
- [ ] Modul memakai `from __future__ import annotations` dan mendeklarasikan `__all__`
- [ ] Docstring modul mencantumkan rujukan requirement
- [ ] Tidak ada modul GTK yang diimpor
- [ ] Tersedia berkas pengujian
