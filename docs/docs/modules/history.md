# pinux/history.py

> **Status**: sudah diimplementasikan (SQLite lokal).

Modul ini menyimpan riwayat terjemahan beserta penandaan favorit. Riwayat memuat teks
yang pernah diterjemahkan pengguna, sehingga berkasnya sengaja dibuat dengan izin ketat
dan tidak pernah dikirim ke mana pun.

## Struktur

| Simbol | Kegunaan |
|---|---|
| `HistoryEntry` | Satu baris riwayat (immutable) |
| `HistoryStore` | Pembaca/penulis basis data riwayat; aman dipakai lintas thread |
| `default_history_path()` | Lokasi basis data menurut spesifikasi XDG |

## Lokasi Berkas

`default_history_path()` mengembalikan `$XDG_DATA_HOME/pinux/history.db`, atau
`~/.local/share/pinux/history.db` bila `XDG_DATA_HOME` tidak disetel.

Berkas dibuat lebih dulu lewat `os.open(..., 0o600)` sebelum SQLite menulis apa pun,
sehingga tidak pernah ada jendela waktu ketika isinya dapat dibaca pengguna lain.
`HistoryStore(path=":memory:")` dipakai oleh pengujian dan tidak menyentuh disk.

## Bentuk Data

```python
@dataclass(frozen=True)
class HistoryEntry:
    id: int
    ts: float
    source_text: str
    result_text: str
    source_lang: str
    target_lang: str
    provider_id: str
    favorite: bool
```

Skema tabel `entries` menyimpan kolom yang sama ditambah indeks `idx_entries_ts` pada
`ts DESC`, karena hampir semua kueri mengurutkan berdasarkan waktu.

## Perilaku Penting

| Perilaku | Rincian |
|---|---|
| Deduplikasi | Terjemahan identik berturut-turut (teks, hasil, dan bahasa tujuan sama dengan entri terbaru) hanya memperbarui `ts`, sehingga debounce/retry tidak menggandakan entri |
| Pemangkasan | `max_entries` bawaan 500; hanya entri non-favorit yang dipangkas, favorit tidak pernah dihapus otomatis |
| `clear()` | Bawaan `keep_favorites=True`; favorit tetap ada kecuali diminta eksplisit `keep_favorites=False` |
| Pencarian | `list(query=...)` mencari di `source_text` dan `result_text` dengan `LIKE ... ESCAPE '\'`, sehingga `%` dan `_` pada kata kunci diperlakukan literal |
| Urutan | Selalu `ts DESC, id DESC` — entri terbaru lebih dulu |

## Keamanan Thread

`sqlite3.connect(..., check_same_thread=False)` dipadukan dengan `threading.Lock`
milik `HistoryStore`. Setiap metode yang menyentuh koneksi mengambil kunci itu, dan
operasi tulis dibungkus `with self._conn` agar commit/rollback konsisten. Dengan begitu
penulisan dari worker thread dan pembacaan dari thread UI tidak saling merusak.

## Dependensi

**Modul ini bergantung pada:** tidak ada modul Pinux lain (hanya pustaka standar).

**Bergantung pada modul ini:**

- `pinux.app` — mencatat setiap terjemahan yang berhasil (`record_history`)
- `pinux.ui.history` — menampilkan, mencari, dan menghapus entri

## Mengapa `HistoryStore` Tidak Dipecah

Analisis graphify pernah menandai modul ini dengan *cohesion* rendah (0.057) dan
menyarankan pemecahan. Angka itu **artefak pengelompokan graph**, bukan tanda desain
buruk:

- Node modul `pinux/history.py` jatuh ke community `app.py`, sedangkan class
  `HistoryStore`, `HistoryEntry`, dan berkas pengujiannya membentuk community
  `HistoryStore` sendiri.
- Metrik kohesi dihitung dari sebaran itu, sehingga modul yang isinya koheren tetap
  terlihat "tersebar".

Isi modul ini hanya satu dataclass nilai dan satu class penyimpanan berukuran ±200
baris dengan satu tanggung jawab: persistensi riwayat. Memecahnya akan memisahkan
skema SQL dari operasi yang memakainya tanpa memberi batas tanggung jawab baru.
Karena itu pemecahan sengaja **tidak** dilakukan.

## Pengujian

| Berkas | Cakupan |
|---|---|
| `tests/test_history.py` | Deduplikasi, pemangkasan, favorit, pencarian, izin berkas, dan penulisan bersamaan |
| `tests/test_gui_history.py` | Integrasi dengan `HistoryWindow`: daftar, filter, hapus, kosongkan, dan escape markup |
