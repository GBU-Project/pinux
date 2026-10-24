# Changelog
 
 Semua perubahan penting pada proyek Pinux akan dicatat dalam berkas ini.
 
 Format dokumen ini mengacu pada [Keep a Changelog](https://keepachangelog.com/id/1.1.0/) dan proyek ini mengikuti kaidah [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
 
 ---
 
 ## [1.0.0] - 2026-10-24
 
 Rilis stabil v1.0.0 menghadirkan arsitektur penerjemah desktop Linux yang matang, tangguh, dan terisolasi dengan performa tinggi untuk sesi Wayland dan X11.
 
 ### Ditambahkan
 - **Arsitektur Provider & Multi-Instance**:
   - Pembungkus `_ProviderAlias` untuk mendukung pendaftaran multi-instance provider kustom dengan ID unik pada `ProviderRegistry`.
   - In-memory credential caching dengan invalidasi otomatis berbasis event observer (`CredentialStore.connect_changed`).
   - Default LLM Settings ramah privasi menggunakan Ollama lokal (`http://localhost:11434/v1/chat/completions` dengan model `llama3.2`).
 - **UI & Pengalaman Pengguna (GTK4 / Libadwaita)**:
   - Dukungan penuh opsi `close_on_blur` pada popup terjemahan.
   - Peningkatan visual `RegionOverlay` dengan efek dim cutout dan *frozen frame* berpresisi piksel tinggi.
   - Penanganan pembatalan pemilihan region berbasis token pembatalan unik.
   - Integrasi Text-to-Speech (TTS) dengan proteksi karakter khusus, pemotongan teks panjang, dan background reaper thread non-blokir.
 - **Konkurensi & Siklus Hidup**:
   - Pembacaan teks clipboard dan primary selection yang sepenuhnya asinkron tanpa busy-wait GLib loop.
   - Pembersihan proses asinkron aktif via `scheduler.cancel_active()` saat shutdown aplikasi.
   - Pelepasan nama bus Tray Icon yang aman dan penutupan database riwayat (`HistoryStore`) yang idempoten.
 - **Pengemasan & Lingkungan**:
   - Manifest Flatpak universal terverifikasi (`io.github.gbu_project.Pinux.yml`).
   - Dokumentasi spesifikasi arsitektur (`design.md` dan `requirements.md`) disinkronkan ke v1.0.0.
 
 ### Diubah
 - Default endpoint LLM dialihkan dari OpenAI ke Ollama lokal agar pengguna dapat langsung memakai fitur AI tanpa konfigurasi API key berbayar.
 - Penanganan galat soket level rendah (`OSError`) pada client HTTP kini dipetakan dengan aman ke `TranslationError("network", ...)`.
 
 ---
 
 ## [0.2.0] - 2026-10-19
 
 ### Ditambahkan
 - Dukungan OCR dari berkas gambar lokal dan pembacaan kode QR (`pinux --ocr-file`).
 - Mode OCR kontinu / penambahan teks (`pinux --ocr-append`).
 - Fitur kamus kata tunggal dan simbol fonetik.
 - Fitur riwayat pencarian terjemahan dan penanda favorit berbasis SQLite.
 - Akselerasi perangkat keras DRI dan integrasi speech-dispatcher pada sandbox Flatpak.
 
 ---
 
 ## [0.1.0] - 2026-10-17
 
 ### Ditambahkan
 - Rilis perdana Pinux sebagai penerjemah desktop Linux ala Bob.
 - Integrasi terjemahan popup instan via Global Shortcut Portal dan X11.
 - Layanan latar belakang dengan tray icon StatusNotifierItem.
 - Mesin terjemahan Google Translate gratis dan OCR luring berbasis RapidOCR (ONNX).
