# pinux/ui/

> **Status**: hanya docstring paket yang ada. Seluruh jendela masih direncanakan.

Paket ini memuat antarmuka pengguna GTK 4 dan libadwaita.

## Struktur

```
pinux/ui/
└── __init__.py               # Docstring paket
```

Berkas berikut masih direncanakan:

```
pinux/ui/
├── popup.py                  # PopupWindow, task 15
├── region.py                 # RegionOverlay, task 16
└── settings.py               # SettingsWindow, task 17 dan 18
```

## Jendela yang Direncanakan

| Berkas | Tugas | Ringkasan |
|---|---|---|
| `popup.py` | 15 | Jendela tanpa dekorasi berisi Source_Text, hasil terjemahan, indikator kemajuan, dan tombol salin, tukar bahasa, pin, serta OCR |
| `region.py` | 16 | Jendela layar penuh untuk memilih area tangkapan layar, lalu memotong citra |
| `settings.py` | 18 | `Adw.PreferencesWindow` dengan halaman Umum, Provider, Pintasan, dan OCR |

Komponen tray berada pada `pinux/tray.py` (task 17), terpisah dari paket ini karena tidak memakai GTK.

## Perilaku PopupWindow yang Direncanakan

| Peristiwa | Perilaku | Rujukan |
|---|---|---|
| Popup ditampilkan | Ditempatkan 16 piksel dari posisi kursor | R1.4 |
| Popup sudah terbuka | Jendela yang ada dipakai ulang | R1.5 |
| Kehilangan fokus | Ditutup, kecuali berada pada Pinned_State | R5.1 |
| Tombol Escape | Ditutup | R5.2 |
| Penerjemahan berjalan | Indikator kemajuan ditampilkan | R5.5 |
| Penerjemahan selesai | Hasil ditampilkan, indikator berhenti | R5.3 |

## Perilaku RegionOverlay yang Direncanakan

1. Ditampilkan pada monitor tempat kursor berada.
2. Pengguna menyeret untuk memilih area; `Escape` membatalkan.
3. Setelah area dipilih, overlay disembunyikan, layar penuh ditangkap melalui portal Screenshot, lalu citra dipotong dengan Pillow.
4. Koordinat logis dikonversi ke piksel memakai `Gdk.Surface.get_scale_factor()`.

## Mengapa Pemotongan Dilakukan Lokal

Portal Screenshot tidak menyediakan parameter area persegi, sehingga Pinux tidak dapat meminta tangkapan satu area tertentu. Strategi yang dipakai adalah menangkap layar penuh lalu memotongnya secara lokal. Konsekuensinya, konversi koordinat harus benar pada penskalaan fraksional dan pada susunan dua monitor. Keduanya tercatat sebagai risiko terbuka pada `design.md`.

## Dependensi

**Paket ini bergantung pada:**

- `pinux.config` - pengaturan lebar popup dan perilaku pin
- `pinux.capture` - `CaptureResult` yang ditampilkan
- `pinux.translate.base` - `TranslationResult` dan `TranslationError`
- `pinux.portal.screenshot` (direncanakan) - tangkapan layar
- `pinux.ocr.client` (direncanakan) - pengenalan teks

**Bergantung pada paket ini:**

- `pinux.app` (direncanakan) - memiliki dan menampilkan seluruh jendela

## Aturan Implementasi

1. Modul pada paket ini boleh mengimpor GTK; modul di luar paket ini tidak boleh.
2. Tidak ada operasi jaringan, OCR, atau baca-tulis berkas berskala besar pada thread utama GTK.
3. Setiap permintaan berakhir dengan tepat satu dari penampilan hasil atau penampilan galat, dan indikator kemajuan berhenti pada kedua jalur.
