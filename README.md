# Pinux

Aplikasi penerjemah desktop GTK4/libadwaita untuk Linux yang mengadaptasi alur
kerja [Bob](https://github.com/ripperhe/Bob) pada macOS.

Pinux berjalan sebagai layanan latar belakang, mendaftarkan pintasan keyboard
global, lalu menampilkan hasil terjemahan pada jendela popup ringan. Pinux juga
menyediakan OCR terjemahan dari tangkapan layar untuk teks yang tidak dapat
disorot.

> Status: tahap awal pengembangan. Lihat `tasklist.md` untuk kemajuan terkini.

## Kebutuhan sistem

Pinux memerlukan GTK 4.10+, libadwaita 1.4+, dan PyGObject dari distribusi.
Tidak ada paket sistem lain yang diperlukan.

```
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
```

## Instalasi untuk pengembangan

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
- **Buka Jendela Pengaturan:** `pinux --settings`

## Terjemah seleksi (ala Bob)

Sorot teks di aplikasi mana pun, lalu tekan pintasan terjemahan. Pinux membaca
seleksi (primary selection) lebih dulu; bila Anda baru saja menyalin dengan
Ctrl+C, isi clipboard yang dipakai. Pada Wayland, pasang `wl-clipboard`
(`sudo apt install wl-clipboard`) agar seleksi dapat dibaca dari aplikasi lain.

## Dokumentasi

- `.monkeycode/specs/linux-translator/requirements.md` — kebutuhan fungsional
- `.monkeycode/specs/linux-translator/design.md` — desain teknis
- `.monkeycode/specs/linux-translator/tasklist.md` — rencana implementasi
