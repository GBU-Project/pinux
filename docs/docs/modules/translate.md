# pinux/translate/

> **Status**: sudah diimplementasikan — model, kontrak, registri, dan seluruh provider bawaan.

Paket ini memuat kontrak mesin penerjemahan, model datanya, dan provider bawaan.

## Struktur

```
pinux/translate/
├── __init__.py               # Docstring paket
├── base.py                   # Model data + Protocol TranslationProvider
├── _http.py                  # Pembantu POST JSON bersama (validasi endpoint, pemetaan galat)
├── google_free.py            # Free_Provider google-free
├── deepl.py                  # Keyed_Provider DeepL
├── libretranslate.py         # Provider LibreTranslate (instans lokal/host sendiri)
├── openai_compatible.py      # Provider LLM bergaya OpenAI (termasuk server lokal)
├── chain.py                  # FallbackChain: coba provider berurutan
├── compare.py                # CompareProvider: jalankan beberapa provider sekaligus
└── registry.py               # ProviderRegistry + pemuatan provider pihak ketiga
```

## Berkas Kunci

| Berkas | Kegunaan |
|---|---|
| `base.py` | `Language`, `TranslationRequest`, `TranslationResult`, `TranslationError`, `ERROR_KINDS`, `AlternativeResult`, `DictionaryEntry`, Protocol `TranslationProvider` |
| `_http.py` | `post_json`, `validate_endpoint`, `is_local_url`, `http_status_to_kind` — dipakai DeepL dan LibreTranslate |
| `chain.py` | `FallbackChain` — mencoba provider utama lalu cadangan; dipanggil langsung oleh `RequestScheduler` tanpa perubahan kontrak |
| `registry.py` | `ProviderRegistry`, `ProviderInfo`, `load_provider_from_string` untuk provider pihak ketiga (`package.module:ClassName`) |

## Dependensi

**Paket ini bergantung pada:**

- `pinux.scheduler` - `CancelToken` yang diterima operasi `translate`

**Bergantung pada paket ini:**

- `pinux.ui.settings` - menampilkan daftar provider
- `pinux.scheduler.RequestScheduler` - memanggil `translate`

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
