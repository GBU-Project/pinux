# Changelog
 
 Semua perubahan penting pada proyek Pinux akan dicatat dalam berkas ini.
 
 Format dokumen ini mengacu pada [Keep a Changelog](https://keepachangelog.com/id/1.1.0/) dan proyek ini mengikuti kaidah [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
 
 ---
 
 ## [1.1.0] - 2026-10-26

 Rilis perbaikan dan penguatan atas v1.0.0: pengelolaan pintasan global portal yang lebih tangguh, serta perbaikan regresi OCR, lapisan seleksi area, clipboard, dan TTS.

 ### Ditambahkan
 - **Pintasan global (portal GlobalShortcuts)**:
   - Halaman Pengaturan > Pintasan memperbarui dirinya secara langsung saat status portal berubah (pengikatan selesai, sesi berakhir, pengguna mengubah pemicu di pengaturan sistem), tanpa perlu menutup dan membuka ulang jendela.
   - Status "Menunggu Persetujuan Desktop…" selama dialog persetujuan desktop terbuka.
   - Tombol "Coba Ikat Ulang" pada mode CLI untuk mengikat ulang pintasan setelah penolakan, portal dimulai ulang, atau sesi berakhir, tanpa memulai ulang Pinux.
   - Notifikasi saat sesi pintasan global berakhir (portal desktop berhenti atau dimulai ulang); mengetuknya membuka Pengaturan langsung pada halaman Pintasan.
   - API `ShortcutManager`: `start_async()`, `connect_changed()`, dan `disconnect_changed()`.

 ### Diubah
 - Pengikatan pintasan portal (`BindShortcuts`) dijalankan pada worker thread lewat `ShortcutManager.start_async()`. Sebelumnya `start()` memutar loop bersarang di thread utama selama dialog persetujuan terbuka (hingga 120 detik). `start()` sinkron tetap tersedia dan perilakunya tidak berubah.
 - Pembacaan teks clipboard dan primary selection secara asinkron kini dibatasi 1000 ms (setara versi sinkron). Bila pemilik clipboard tidak merespons, pembacaan dibatalkan dan teks dianggap kosong, sehingga popup tidak tertahan di status memuat.
 - Shutdown aplikasi menutup sesi portal dengan batas waktu dan tetap menyelesaikan pembersihan lain walau portal bermasalah.

 ### Diperbaiki
 - **OCR**: dua permintaan OCR bersamaan (misalnya pemicu OCR dua kali beruntun) saling membuang pesan dari pekerja sehingga keduanya habis waktu hingga 120 detik; `ensure_model` dan `shutdown` juga bisa macet. Permintaan kini diserialkan dan antreannya tetap dapat dibatalkan. Regresi ini muncul sejak v1.0.0.
 - **Overlay pemilihan area**: lapisan dim dan seleksi hilang pada tangkapan layar ke-1, ke-3, dan seterusnya karena `DrawingArea` dipasang ulang tanpa dilepas dari induk lamanya. Regresi sejak v1.0.0.
 - **TTS (spd-say)**: pembatalan `spd-say -C` milik ucapan lama dapat tiba di daemon setelah ucapan baru dan ikut membatalkannya. Teks ucapan baru kini dikirim setelah pembatalan yang tertunda selesai. Proses TTS juga dihentikan seketika dengan batas waktu singkat.
 - **Portal GlobalShortcuts**:
   - Sesi yang berakhir (`Session.Closed`) atau portal yang dimulai ulang kini terdeteksi sehingga aplikasi beralih ke mode CLI dengan alasan yang benar, bukan tetap tampak aktif.
   - Pekerja pengikatan asinkron yang basi (dibatalkan oleh `stop()`) tidak lagi menutup sesi milik pengikatan baru yang selesai lebih dulu saat mengikat ulang.
 - **Popup**: kotak teks sumber dan hasil tidak lagi menampilkan potongan separuh baris di batas ketinggian.
 - **Pengujian dan CI**: tes penjadwal dibuat lebih stabil di runner CI, dan `libdbus-1-dev` ditambahkan ke dependensi pengujian.

 ### Catatan peningkatan
 - Default endpoint LLM sudah berubah ke Ollama lokal sejak v1.0.0 (`http://localhost:11434/v1/chat/completions`, model `llama3.2`). Pengguna yang bergantung pada default OpenAI sebelum v1.0.0 dan belum pernah menyimpan pengaturan perlu mengisi ulang endpoint dan model di Pengaturan > Provider.

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
 
 ### Diperbaiki
 - **Sizing & Scrolling Popup**: Memperbaiki masalah jendela popup melebar horizontal secara berlebihan akibat teks fonetik/pinyin panjang tanpa wrapping, serta mengaktifkan scroll vertikal yang mulus pada kontainer hasil terjemahan dan jendela terjemahan penuh (`TranslationWindow`).
 - **Text-to-Speech (TTS)**: Memperbaiki pemanggilan pembatalan daemon `spd-say` agar terisolasi saat ada proses aktif.
 
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
