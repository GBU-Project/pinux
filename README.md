# Pinux

Aplikasi penerjemah desktop GTK4/libadwaita untuk Linux yang mengadaptasi alur
kerja [Bob](https://github.com/ripperhe/Bob) pada macOS.

Pinux berjalan sebagai layanan latar belakang, mendaftarkan pintasan keyboard
global, lalu menampilkan hasil terjemahan pada jendela popup ringan. Pinux juga
menyediakan OCR terjemahan dari tangkapan layar untuk teks yang tidak dapat
disorot.

> Status: tahap awal pengembangan. Lihat `tasklist.md` untuk kemajuan terkini.

## Instalasi via Flatpak (Universal & Direkomendasikan)

Flatpak adalah cara instalasi termudah dan universal untuk semua distribusi Linux (Ubuntu, Fedora, Arch, Debian, openSUSE, dll.), baik di lingkungan sesi **Wayland** maupun **X11**.

### 1. Pasang dari Berkas Rilis (`Pinux.flatpak`)

Unduh berkas `Pinux.flatpak` dari [Halaman Rilis GitHub](https://github.com/GBU-Project/pinux/releases), lalu pasang:

```bash
flatpak install Pinux.flatpak
```

Jalankan Pinux:

```bash
flatpak run io.github.gbu_project.Pinux
```

### 2. Pintasan Keyboard Desktop (Mode Flatpak)

Jika portal pintasan global belum aktif otomatis di desktop Anda, Anda dapat mengaitkan tombol pintasan secara manual pada **Pengaturan Keyboard Desktop**:

- **Penerjemahan Seleksi/Clipboard:** `flatpak run io.github.gbu_project.Pinux --trigger` (rekomendasi: `Ctrl+Alt+T`)
- **Tangkapan Layar & OCR:** `flatpak run io.github.gbu_project.Pinux --pick-region` (rekomendasi: `Ctrl+Alt+O`)
- **Terjemah Input Manual:** `flatpak run io.github.gbu_project.Pinux --input` (rekomendasi: `Ctrl+Alt+A`)
- **OCR Senyap (Salin Teks Saja):** `flatpak run io.github.gbu_project.Pinux --ocr-copy` (rekomendasi: `Ctrl+Alt+C`)
- **Jendela Pengaturan:** `flatpak run io.github.gbu_project.Pinux --settings`

---

## Kebutuhan Sistem (Instalasi Native / Pengembangan)

Bila Anda ingin menjalankan Pinux secara native tanpa Flatpak:

Pinux memerlukan Python 3.11+, GTK 4.10+, libadwaita 1.4+, dan PyGObject dari distribusi:

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 wl-clipboard
```

## Instalasi untuk Pengembangan (Source)

```
python3 -m venv --system-site-packages --without-pip .venv
python3 -m pip --python .venv/bin/python3 install -e . --no-deps
python3 -m pip --python .venv/bin/python3 install pytest hypothesis
```

## Menjalankan pengujian

```
.venv/bin/python3 -m pytest
```

## Menjalankan dan Antarmuka Baris Perintah (CLI)

Pinux dapat dijalankan langsung:

```bash
pinux
```

Bila portal GlobalShortcuts tidak tersedia pada lingkungan desktop Anda, Anda dapat mengikat pintasan keyboard secara manual pada Pengaturan Keyboard desktop (GNOME Settings -> Keyboard Shortcuts):

- **Penerjemahan Clipboard:** `pinux --trigger` (rekomendasi pintasan: `Ctrl+Alt+T`)
- **Tangkapan Layar & OCR:** `pinux --pick-region` (rekomendasi pintasan: `Ctrl+Alt+O`)
- **Terjemah Input:** `pinux --input` (rekomendasi pintasan: `Ctrl+Alt+A`). Ketik teks, tekan Enter untuk menerjemahkan, Shift+Enter untuk baris baru.
- **OCR Senyap:** `pinux --ocr-copy` (rekomendasi pintasan: `Ctrl+Alt+C`). Pilih area layar, teks hasil OCR disalin ke clipboard tanpa terjemahan.
- **Buka Jendela Pengaturan:** `pinux --settings`

## Terjemah seleksi (ala Bob)

Sorot teks di aplikasi mana pun, lalu tekan pintasan terjemahan. Pinux membaca
seleksi (primary selection) lebih dulu; bila Anda baru saja menyalin dengan
Ctrl+C, isi clipboard yang dipakai. Pada Wayland, pasang `wl-clipboard`
(`sudo apt install wl-clipboard`) agar seleksi dapat dibaca dari aplikasi lain.

## Dokumentasi

- `docs/specs/linux-translator/requirements.md` — kebutuhan fungsional
- `docs/specs/linux-translator/design.md` — desain teknis
- `docs/specs/linux-translator/tasklist.md` — rencana implementasi
