# Dokumentasi Pinux

Dokumentasi ini menjelaskan Pinux, aplikasi penerjemah desktop GTK4 untuk Linux. Isinya ditujukan untuk pengembang yang akan melanjutkan implementasi, serta siapa pun yang perlu memahami bagaimana sistem bekerja.

**Tautan cepat**: [Arsitektur](./ARCHITECTURE.md) | [Antarmuka](./INTERFACES.md) | [Panduan Pengembang](./DEVELOPER_GUIDE.md)

---

## Dokumen Utama

### [Arsitektur](./ARCHITECTURE.md)

Desain sistem, tumpukan teknologi, struktur komponen, dan alur data. Mulai dari sini untuk memahami cara kerja Pinux, termasuk pemisahan yang tegas antara bagian yang sudah diimplementasikan dan yang masih direncanakan.

### [Antarmuka](./INTERFACES.md)

Antarmuka Python yang tersedia, kontrak yang harus dipenuhi mesin penerjemahan dan mesin OCR, titik perluasan, rencana antarmuka baris perintah, skema `pinux.toml`, dan protokol pekerja OCR.

### [Panduan Pengembang](./DEVELOPER_GUIDE.md)

Penyiapan lingkungan, alur kerja pengujian, konvensi kode, dan panduan langkah demi langkah untuk tugas yang sering dilakukan. Wajib dibaca sebelum berkontribusi.

---

## Modul

| Modul | Deskripsi | Dokumentasi |
|---|---|---|
| `pinux/translate/` | Model data dan kontrak mesin penerjemahan | [README](./modules/translate.md) |
| `pinux/ocr/` | Model data dan kontrak mesin OCR, terpisah dari dependensi beratnya | [README](./modules/ocr.md) |
| `pinux/capture/` | Model hasil penangkapan Source_Text | [README](./modules/capture.md) |
| `pinux/config.py` | Model pengaturan beserta nilai bawaan | [README](./modules/config.md) |
| `pinux/scheduler.py` | Token pembatalan permintaan yang aman lintas thread | [README](./modules/scheduler.md) |
| `pinux/portal/` | Klien portal D-Bus, direncanakan pada task 11 dan 12 | [README](./modules/portal.md) |
| `pinux/ui/` | Antarmuka GTK4/libadwaita, direncanakan pada task 15 sampai 18 | [README](./modules/ui.md) |
| `tests/` | Pengujian unit dan uji properti | [README](./modules/tests.md) |

---

## Konsep Inti

Memahami konsep berikut memudahkan menavigasi basis kode:

| Konsep | Deskripsi |
|---|---|
| [TranslationProvider](./concepts/TranslationProvider.md) | Kontrak yang harus dipenuhi setiap mesin penerjemahan |
| [OcrEngine](./concepts/OcrEngine.md) | Kontrak mesin OCR beserta pemisahan prosesnya |
| [Source_Text dan CaptureResult](./concepts/Source_Text.md) | Teks masukan penerjemahan beserta asal dan pemotongannya |
| [CancelToken](./concepts/CancelToken.md) | Mekanisme pembatalan permintaan lintas thread |

---

## Mulai dari Mana

### Baru pada proyek ini?

Ikuti urutan berikut:

1. **[Arsitektur](./ARCHITECTURE.md)** - pahami gambaran besar dan status implementasi
2. **[Konsep Inti](#konsep-inti)** - pelajari istilah yang dipakai di seluruh dokumen
3. **[Panduan Pengembang](./DEVELOPER_GUIDE.md)** - siapkan lingkungan
4. **[Rencana implementasi](../specs/linux-translator/tasklist.md)** - lihat task berikutnya yang belum selesai

### Ingin menambah mesin penerjemahan atau OCR?

1. **[Antarmuka](./INTERFACES.md#titik-perluasan)** - kontrak yang harus dipenuhi
2. **[Panduan Pengembang](./DEVELOPER_GUIDE.md#tugas-umum)** - langkah demi langkah

### Perlu memahami kebutuhan produk?

1. **[Kebutuhan fungsional](../specs/linux-translator/requirements.md)** - kebutuhan dalam format EARS
2. **[Desain teknis](../specs/linux-translator/design.md)** - keputusan teknis beserta alasannya

---

## Referensi Cepat

### Perintah

```bash
.venv/bin/python3 -m pytest                 # menjalankan seluruh pengujian
.venv/bin/python3 -m pytest -m integration  # hanya pengujian integrasi
.venv/bin/pinux                             # menjalankan aplikasi, belum tersedia
```

### Berkas penting

| Berkas | Kegunaan |
|---|---|
| `pyproject.toml` | Metadata paket, dependensi, konfigurasi pytest |
| `pinux/translate/base.py` | Model data dan kontrak mesin penerjemahan |
| `pinux/ocr/base.py` | Model data dan kontrak mesin OCR |
| `pinux/config.py` | Model pengaturan |
| `pinux/scheduler.py` | CancelToken |
| `tests/conftest.py` | Fixture bersama dan clipboard palsu |

### Istilah

| Istilah | Arti |
|---|---|
| Free_Provider | Translation_Provider yang tidak memerlukan kredensial |
| Keyed_Provider | Translation_Provider yang memerlukan kredensial berupa API key |
| Credential | API key milik satu Keyed_Provider |
| Source_Text | Teks yang menjadi masukan proses penerjemahan |
| Target_Language | Bahasa tujuan penerjemahan |
| Popup_Window | Jendela GTK4 tanpa dekorasi yang menampilkan hasil terjemahan |
| Region_Overlay | Jendela transparan layar penuh untuk memilih area tangkapan layar |
| Pinned_State | Keadaan popup yang bertahan terhadap kehilangan fokus |
