# Panduan Pengembang Pinux

## Tujuan Proyek

Pinux adalah aplikasi penerjemah desktop untuk Linux dengan alur kerja menyerupai Bob pada macOS: panggil terjemahan dari aplikasi mana pun melalui pintasan keyboard, tampilkan hasil pada popup ringan, dan terjemahkan teks di dalam gambar melalui OCR.

**Tanggung jawab inti:**

- Menyediakan pemicu terjemahan global yang berfungsi tanpa memindahkan fokus dari aplikasi aktif.
- Menjembatani beberapa mesin penerjemahan dan mesin OCR melalui antarmuka yang seragam.
- Menyajikan hasil terjemahan pada popup yang tidak mengganggu.

**Sistem terkait:**

- Portal XDG D-Bus - sumber pemicu pintasan, tangkapan layar, dan penyimpanan Credential.
- `translate.googleapis.com` - mesin penerjemahan Free_Provider pada rilis pertama.
- `pinux-ocr-worker` - proses terpisah yang menjalankan mesin OCR berat.

## Prasyarat

- Python 3.11 atau lebih baru
- GTK 4.10+, libadwaita 1.4+, dan PyGObject dari distribusi
- Sesi desktop GNOME untuk pengujian integrasi; sesi X11 untuk menguji `Primary_Selection`

```
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
```

Paket `rapidocr-onnxruntime` dan `onnxruntime` bersifat opsional. Pinux dirancang tetap berjalan tanpa keduanya, dengan aksi OCR dalam keadaan tidak aktif.

## Peringatan Lingkungan

Pada mesin pengembangan yang dipakai menyusun Pinux, variabel `PYTHONHOME` dan `PYTHONPATH` mengarah ke sisa ekstraksi paket pada `~/Downloads/squashfs-root/usr/`. Polusi ini membuat `pip3` gagal dengan `Fatal Python error: Failed to import encodings module`, dan `LD_LIBRARY_PATH` yang menyertainya membuat perintah seperti `ls` dan `head` gagal dengan galat versi `libsystemd`. Bersihkan variabel tersebut dari berkas profil shell Anda sebelum bekerja pada proyek ini.

## Penyiapan Lingkungan

Paket `python3-venv` pada sistem target tidak menyertakan `ensurepip`, sehingga `python3 -m venv` menghasilkan venv tanpa `pip`. Karena `pip install --user` juga diblokir oleh PEP 668, gunakan urutan berikut.

```bash
# 1. Buat venv yang memakai paket sistem dan tanpa pip bawaan
python3 -m venv --system-site-packages --without-pip .venv

# 2. Pasang perkakas pengujian ke dalam venv memakai pip sistem
python3 -m pip --python .venv/bin/python3 install pytest hypothesis

# 3. Pasang Pinux dalam mode editable tanpa menyentuh dependensi
#    (PyGObject dipakai dari paket sistem, bukan dibangun ulang)
python3 -m pip --python .venv/bin/python3 install -e . --no-deps
```

Perhatikan bahwa opsi `--python` harus diletakkan sebelum nama subperintah `install`.

## Menjalankan

```bash
# Seluruh pengujian
.venv/bin/python3 -m pytest

# Pengujian dengan keluaran ringkas
.venv/bin/python3 -m pytest -q

# Hanya pengujian integrasi yang memerlukan sesi desktop
.venv/bin/python3 -m pytest -m integration

# Menjalankan aplikasi (belum tersedia, lihat task 19)
.venv/bin/pinux
```

## Alur Kerja Pengembangan

Proyek ini memakai alur Spec-Driven Development. Perubahan dikerjakan satu task pada satu waktu, mengikuti urutan pada `docs/specs/linux-translator/tasklist.md`.

1. Baca `requirements.md` lalu `design.md` sebelum menulis kode.
2. Kerjakan satu task beserta sub-task pengujiannya.
3. Jalankan seluruh pengujian; task tidak boleh ditandai selesai bila ada yang gagal.
4. Tandai checkbox pada `tasklist.md` dengan `[x]`.
5. Perbarui dokumentasi pada `docs/docs/`.

### Perintah pemeriksaan

| Kegunaan | Perintah |
|---|---|
| Menjalankan seluruh pengujian | `.venv/bin/python3 -m pytest` |
| Menjalankan pengujian integrasi | `.venv/bin/python3 -m pytest -m integration` |
| Memeriksa impor modul inti | `.venv/bin/python3 -c "import pinux.config, pinux.translate.base"` |
| Memeriksa ketiadaan dependensi berat | lihat `tests/test_ocr_independence.py` setelah task 13 |

## Konvensi Kode

### Nama berkas

| Jenis | Konvensi | Contoh |
|---|---|---|
| Modul | `snake_case` | `google_free.py`, `configstore.py` |
| Paket | `snake_case` | `translate/`, `ocr/`, `portal/` |
| Pengujian | `test_*.py` pada direktori `tests/` | `test_models.py` |

### Nama simbol

| Jenis | Konvensi | Contoh |
|---|---|---|
| Kelas | `PascalCase` | `TranslationProvider`, `CancelToken` |
| Fungsi dan metode | `snake_case` | `list_languages`, `read_source_text` |
| Konstanta | `SCREAMING_SNAKE_CASE` | `ERROR_KINDS`, `DEFAULT_SETTINGS` |
| Properti dataclass | `snake_case` | `detected_source_lang`, `max_chars` |

### Gaya kode

- Seluruh modul memakai `from __future__ import annotations`.
- Docstring dan komentar ditulis dalam bahasa Indonesia; nama simbol dan nama berkas memakai bahasa Inggris.
- Setiap modul mencantumkan rujukan requirement, misalnya `Perujuk: R3.2 pada requirements.md`, pada docstring modul.
- Setiap modul mendeklarasikan `__all__`.
- Dataclass yang mewakili nilai yang tidak berubah ditandai `frozen=True`.
- Kode inti tidak boleh mengimpor `onnxruntime`, `rapidocr`, atau modul GTK pada lapisan model.
- Tidak ada operasi jaringan, OCR, atau baca-tulis berkas berskala besar pada thread utama GTK.

### Penanganan galat

Pemanggilan provider dan mesin OCR selalu memunculkan `TranslationError` dengan `kind` yang tepat, bukan pengecualian umum. Nilai `kind` divalidasi pada saat objek dibuat.

```python
# Disarankan: jenis galat eksplisit
raise TranslationError("rate_limit", self.id, "Kuota harian tercapai")

# Hindari: pengecualian umum tanpa jenis
raise RuntimeError("kuota tercapai")
```

## Tugas Umum

### Menambahkan pengaturan baru

**Berkas yang diubah:**

1. `pinux/config.py` - tambahkan field beserta nilai bawaan pada dataclass terkait
2. `pinux/configstore.py` - tambahkan pemetaan kunci TOML dan validasinya (task 4)
3. `tests/test_models.py` - tambahkan pengujian nilai bawaan
4. `docs/docs/INTERFACES.md` - dokumentasikan field baru

**Langkah:**

1. Tambahkan field dengan nilai bawaan yang aman.
2. Petakan kunci TOML beserta validasi rentang nilainya.
3. Tambahkan pengujian nilai bawaan dan penolakan nilai tidak valid.
4. Tambahkan kendali pada jendela pengaturan (task 18).

### Menambahkan Translation_Provider baru

**Berkas yang diubah:**

1. `pinux/translate/<nama>.py` - implementasi kelas provider
2. `tests/test_translate_<nama>.py` - pengujian unit dengan HTTP yang dipalsukan
3. `pinux.toml` pengguna - entri `[[providers]]`, atau entry point grup `pinux.providers`

**Langkah:**

1. Penuhi seluruh anggota Protocol `TranslationProvider`.
2. Petakan setiap kegagalan ke `TranslationError` dengan `kind` yang sesuai.
3. Periksa `CancelToken.cancelled` di antara tahap permintaan.
4. Kembalikan `TranslationResult` beserta Source_Language yang terdeteksi.
5. Uji pemetaan setiap kode status HTTP galat.

**Contoh pesan commit:** `feat(translate): add DeepL provider`

### Menambahkan mesin OCR baru

**Berkas yang diubah:**

1. `pinux/ocr/<nama>.py` - implementasi kelas mesin
2. `pinux/ocr/worker.py` - pendaftaran mesin pada peladen pekerja
3. `pinux/ocr/registry.py` - pendaftaran menurut `Settings.ocr["engine"]`

**Langkah:**

1. Penuhi Protocol `OcrEngine`.
2. Laporkan kemajuan unduhan model melalui `ensure_model`.
3. Jaga agar dependensi berat hanya diimpor di dalam proses pekerja, bukan pada proses utama.

### Menambahkan pemanggilan portal D-Bus baru

**Berkas yang diubah:**

1. `pinux/portal/<nama>.py` - klien portal
2. `tests/test_portal_<nama>.py` - pengujian dengan bus palsu
3. `tests/test_portal_integration.py` - pengujian integrasi dengan penanda `skip` bila portal tidak tersedia

**Langkah:**

1. Periksa kepemilikan nama D-Bus tujuan sebelum memanggil, lalu sediakan jalur fallback.
2. Tangani sinyal `Response` beserta nilainya.
3. Jalankan pemanggilan yang memunculkan dialog pada worker thread, bukan thread utama.

## Area yang Perlu Kehati-hatian

- **Portal Wayland rapuh.** Dukungan portal berbeda antar versi dan antar desktop. Setiap pemanggilan portal memerlukan jalur fallback yang teruji.
- **Penskalaan fraksional.** Perhitungan koordinat antara overlay logis dan citra piksel perlu diuji pada penskalaan 100%, 125%, dan 200%.
- **Pembatalan permintaan.** Pastikan tidak ada keadaan memuat yang tersisa dan tidak ada hasil permintaan lama yang menimpa hasil permintaan baru.
- **Kredensial.** Jangan pernah menuliskan nilai Credential ke `pinux.toml` atau ke log.

## Rujukan

- [Arsitektur](./ARCHITECTURE.md)
- [Antarmuka](./INTERFACES.md)
- [Kebutuhan fungsional](../specs/linux-translator/requirements.md)
- [Desain teknis](../specs/linux-translator/design.md)
- [Rencana implementasi](../specs/linux-translator/tasklist.md)
