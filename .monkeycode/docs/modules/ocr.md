# pinux/ocr/

> **Status**: model dan kontrak sudah ada; protokol pekerja, peladen, dan mesin RapidOCR masih direncanakan.

Paket ini memuat kontrak mesin OCR beserta model datanya, dan menjadi tempat proses pekerja OCR yang terpisah dari proses utama.

## Struktur

```
pinux/ocr/
├── __init__.py               # Docstring paket
├── base.py                   # Model data dan Protocol OcrEngine
└── worker.py                 # Titik masuk proses pinux-ocr-worker
```

Berkas berikut masih direncanakan:

```
pinux/ocr/
├── protocol.py               # Pengodean dan penguraian pesan JSON per baris, task 13
├── server.py                 # Peladen pekerja, task 13
├── client.py                 # OcrWorkerClient, task 13
└── rapidocr_engine.py        # Implementasi mesin rapidocr, task 13
```

## Berkas Kunci

| Berkas | Kegunaan |
|---|---|
| `base.py` | `OcrLine`, `OcrResult`, Protocol `OcrEngine` |
| `worker.py` | Fungsi `main` yang dipanggil oleh perintah `pinux-ocr-worker` |

## Dependensi

**Paket ini bergantung pada:**

- `pinux.scheduler` - `CancelToken` yang diterima operasi `recognize`

**Bergantung pada paket ini:**

- `pinux.ui.region` (direncanakan) - menjalankan OCR atas citra hasil tangkapan
- `pinux.ui.settings` (direncanakan) - menampilkan status ketersediaan mesin

## Aturan Dependensi

`base.py` tidak boleh mengimpor `onnxruntime` maupun `rapidocr`. Dependensi tersebut hanya boleh diimpor di dalam berkas yang dijalankan pada proses pekerja, yaitu `server.py` dan `rapidocr_engine.py`.

Aturan ini menjaga Properti 7 pada `design.md` dan diverifikasi oleh pengujian yang memblokir impor kedua paket tersebut.

```python
# Disarankan: impor berat hanya di dalam proses pekerja
def recognize(self, image_png: bytes, cancel) -> OcrResult:
    from rapidocr import RapidOCR   # impor lokal

# Hindari: impor berat pada lapisan model
import onnxruntime                 # di pinux/ocr/base.py
```

## Protokol Pekerja

Proses pekerja berbicara melalui stdin/stdout dengan satu objek JSON per baris. Rincian pesan ada pada `INTERFACES.md`.

| Pesan | Arah |
|---|---|
| `ensure_model` | klien ke worker |
| `recognize` | klien ke worker |
| `progress` | worker ke klien |
| `result` | worker ke klien |
| `error` | worker ke klien |

Pembatalan dilakukan dengan mengirim `SIGTERM`; worker dijalankan ulang pada permintaan berikutnya.

## Siklus Hidup Proses Pekerja

| Peristiwa | Perilaku |
|---|---|
| OCR pertama diminta | Proses pekerja dijalankan dan model dimuat |
| Permintaan berikutnya | Proses pekerja yang sama dipakai ulang |
| 5 menit tanpa aktivitas | Proses pekerja dihentikan |
| Pembatalan | Proses pekerja dihentikan, lalu dijalankan ulang sesuai kebutuhan |
| Pinux keluar | Proses pekerja dihentikan |

## Pengujian

| Berkas | Cakupan |
|---|---|
| `tests/test_models.py` | Bentuk dataclass dan pemeriksaan Protocol |
| `tests/test_ocr_protocol.py` | Rencana pengodean dan penguraian pesan, task 13.1 |
| `tests/test_ocr_independence.py` | Rencana verifikasi Properti 7, task 13.2 |

## Menambahkan Berkas Baru

### Menambahkan mesin OCR

1. Buat `pinux/ocr/<nama>.py` berisi kelas mesin.
2. Penuhi Protocol `OcrEngine`.
3. Impor dependensi berat secara lokal, bukan pada tingkat modul.
4. Daftarkan mesin pada peladen pekerja.

**Daftar periksa:**

- [ ] Mengimpor dependensi berat hanya secara lokal
- [ ] Melaporkan kemajuan unduhan pada `ensure_model`
- [ ] `is_available` mengembalikan `False` alih-alih memunculkan pengecualian
- [ ] Tersedia berkas pengujian
