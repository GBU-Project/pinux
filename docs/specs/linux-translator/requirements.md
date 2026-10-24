# Requirements Document

## Introduction

Pinux adalah aplikasi penerjemah desktop untuk Linux yang mengadaptasi alur kerja Bob (macOS): panggil terjemahan dari aplikasi mana pun dengan pintasan keyboard, tampilkan hasil pada jendela popup yang ringan, dan dukung penerjemahan teks di dalam gambar melalui OCR. Pinux berjalan sebagai layanan latar belakang dengan ikon tray, menggunakan GTK4/libadwaita, dan menyediakan arsitektur provider yang dapat diperluas untuk mesin terjemahan maupun mesin OCR.

Rilis v1 mencakup: terjemahan teks dengan popup, OCR terjemahan dari tangkapan layar, satu Free_Provider terjemahan, dan satu OCR_Engine luring. Antarmuka Keyed_Provider disediakan pada v1, sedangkan implementasi Keyed_Provider dijadwalkan pada rilis berikutnya.

## Glossary

- **Pinux**: program penerjemah desktop yang dijelaskan pada dokumen ini. Nama perintah pada Command_Line_Interface adalah `pinux`, nama paket Python adalah `pinux`, dan nama berkas pengaturan adalah `pinux.toml`.
- **Command_Line_Interface**: antarmuka invokasi `pinux` melalui argumen baris perintah.
- **Desktop_Session**: sesi grafis aktif, bernilai Wayland atau X11.
- **Global_Shortcut**: kombinasi tombol yang didaftarkan ke desktop dan aktif ketika fokus berada di aplikasi lain.
- **GlobalShortcuts_Portal**: antarmuka D-Bus `org.freedesktop.portal.GlobalShortcuts`.
- **Screenshot_Portal**: antarmuka D-Bus `org.freedesktop.portal.Screenshot`.
- **Secret_Service**: antarmuka D-Bus `org.freedesktop.secrets` untuk penyimpanan kredensial.
- **Clipboard**: area pertukaran data `wl_data_device` pada Wayland atau `CLIPBOARD` pada X11.
- **Primary_Selection**: area pertukaran data `PRIMARY` pada X11.
- **Source_Text**: teks yang menjadi masukan proses penerjemahan.
- **Source_Language**: bahasa dari Source_Text.
- **Target_Language**: bahasa tujuan penerjemahan.
- **Translation_Provider**: komponen yang menerjemahkan Source_Text menjadi hasil terjemahan.
- **Free_Provider**: Translation_Provider yang tidak memerlukan kredensial.
- **Keyed_Provider**: Translation_Provider yang memerlukan kredensial berupa API key.
- **Credential**: API key milik satu Keyed_Provider.
- **OCR_Engine**: komponen yang mengenali teks di dalam data gambar.
- **Screenshot_Region**: area layar berbentuk persegi yang dipilih pengguna untuk ditangkap.
- **Popup_Window**: jendela GTK4 tanpa dekorasi yang menampilkan Source_Text dan hasil terjemahan.
- **Pinned_State**: keadaan Popup_Window ketika pengguna mengaktifkan aksi pin, sehingga Popup_Window bertahan terhadap kehilangan fokus.
- **Region_Overlay**: jendela transparan layar penuh untuk memilih Screenshot_Region.
- **Tray_Icon**: ikon indikator pada panel desktop.
- **Config_Directory**: direktori `$XDG_CONFIG_HOME` dengan nilai bawaan `~/.config`.

## Requirements

### Requirement 1: Memicu Terjemahan dari Aplikasi Lain

**User Story:** AS pengguna desktop, I want memicu terjemahan tanpa berpindah aplikasi, so that alur kerja menulis tetap terjaga.

#### Acceptance Criteria

1. WHEN pengguna menekan Global_Shortcut, Pinux SHALL menampilkan Popup_Window dalam waktu kurang dari 300 milidetik.
2. WHERE Desktop_Session menyediakan GlobalShortcuts_Portal, Pinux SHALL mendaftarkan Global_Shortcut melalui GlobalShortcuts_Portal.
3. IF GlobalShortcuts_Portal tidak tersedia, Pinux SHALL menyediakan perintah `pinux --trigger` pada Command_Line_Interface yang dapat diikat pengguna pada pintasan keyboard desktop.
4. WHEN Popup_Window ditampilkan, Pinux SHALL menempatkan Popup_Window pada posisi kursor dengan jarak 16 piksel dari tepi kursor.
5. WHILE Popup_Window dalam keadaan terbuka, Pinux SHALL menggunakan kembali Popup_Window yang terbuka.
6. Pinux SHALL menyediakan perintah `pinux --pick-region` pada Command_Line_Interface sebagai pemicu OCR alternatif.

### Requirement 2: Menangkap Teks Sumber

**User Story:** AS pengguna desktop, I want teks yang saya sorot terisi otomatis, so that saya tidak perlu menyalin teks secara manual.

#### Acceptance Criteria

1. WHEN Popup_Window ditampilkan, Pinux SHALL membaca Clipboard dan menetapkan isi Clipboard sebagai Source_Text.
2. WHILE Desktop_Session bernilai X11, Pinux SHALL membaca Primary_Selection dan menetapkan isi Primary_Selection sebagai Source_Text ketika isi Primary_Selection berbeda dari isi Clipboard.
3. WHEN isi Clipboard berubah sementara Popup_Window terbuka, Pinux SHALL menetapkan isi Clipboard yang baru sebagai Source_Text dan memulai penerjemahan baru.
4. WHEN pengguna mengubah Source_Text di dalam Popup_Window, Pinux SHALL memulai penerjemahan atas teks hasil perubahan.
5. IF panjang Source_Text melebihi 5000 karakter, Pinux SHALL memotong Source_Text menjadi 5000 karakter dan menampilkan pemberitahuan pemotongan.

### Requirement 3: Mesin Penerjemahan yang Dapat Dipilih

**User Story:** AS pengguna, I want memilih layanan terjemahan, so that saya dapat menyeimbangkan kualitas hasil dan biaya.

#### Acceptance Criteria

1. Pinux SHALL menyediakan satu Free_Provider bernama `google-free` pada rilis v1.
2. Pinux SHALL menyediakan antarmuka Python `TranslationProvider` dengan operasi `translate`, operasi `list_languages`, dan operasi `requires_credential`.
3. Pinux SHALL memuat Translation_Provider dari modul Python yang terdaftar pada berkas pengaturan, sehingga penambahan Translation_Provider tidak memerlukan perubahan pada kode inti.
4. WHEN pengguna memilih Translation_Provider pada layar pengaturan, Pinux SHALL menggunakan Translation_Provider tersebut untuk penerjemahan berikutnya.
5. WHEN Pinux mengirim permintaan penerjemahan atas teks sepanjang 500 karakter atau kurang melalui sambungan berkecepatan 1 Mbit/s atau lebih, Pinux SHALL menampilkan hasil terjemahan dalam waktu kurang dari 2 detik.
6. IF Translation_Provider mengembalikan galat, Pinux SHALL menampilkan pesan galat di dalam Popup_Window dan mempertahankan Source_Text.
7. IF Keyed_Provider dipilih tanpa Credential, Pinux SHALL menampilkan Keyed_Provider tersebut dengan status tidak tersedia pada layar pengaturan.
8. Pinux SHALL menyediakan contoh implementasi Keyed_Provider pada direktori `examples/` sebagai acuan penambahan Translation_Provider berbasis Credential.

### Requirement 4: Bahasa Sumber dan Bahasa Tujuan

**User Story:** AS pengguna, I want bahasa terdeteksi otomatis dengan sasaran yang dapat diatur, so that saya tidak perlu memilih bahasa setiap kali menerjemahkan.

#### Acceptance Criteria

1. WHEN Pinux menerima Source_Text, Pinux SHALL mendeteksi Source_Language dan menampilkan kode Source_Language pada Popup_Window.
2. WHEN pengguna menetapkan Target_Language pada layar pengaturan, Pinux SHALL menerjemahkan Source_Text ke Target_Language.
3. WHEN pengguna memilih aksi tukar bahasa, Pinux SHALL menerjemahkan hasil terjemahan ke Source_Language.
4. IF Source_Language sama dengan Target_Language, Pinux SHALL menerjemahkan Source_Text ke bahasa cadangan dengan nilai bawaan `en`.

### Requirement 5: Perilaku Jendela Popup

**User Story:** AS pengguna, I want popup yang tidak mengganggu, so that popup menghilang setelah selesai digunakan.

#### Acceptance Criteria

1. WHILE Popup_Window berada di luar Pinned_State, WHEN Popup_Window kehilangan fokus, Pinux SHALL menutup Popup_Window.
2. WHEN pengguna menekan tombol Escape, Pinux SHALL menutup Popup_Window.
3. WHEN penerjemahan selesai, Pinux SHALL menampilkan hasil terjemahan di dalam Popup_Window.
4. WHEN pengguna memilih aksi salin, Pinux SHALL menulis hasil terjemahan ke Clipboard.
5. WHILE permintaan penerjemahan berjalan, Pinux SHALL menampilkan indikator kemajuan pada Popup_Window.
6. WHEN pengguna mengaktifkan aksi pin, Pinux SHALL menetapkan Popup_Window ke Pinned_State dan mempertahankan Popup_Window pada keadaan terbuka sampai pengguna menutup Popup_Window.

### Requirement 6: OCR Terjemahan dari Tangkapan Layar

**User Story:** AS pengguna, I want menerjemahkan teks di dalam gambar, video, atau aplikasi yang melarang penyalinan teks, so that saya dapat memahami teks yang tidak dapat disorot.

#### Acceptance Criteria

1. WHEN pengguna menekan pintasan OCR, Pinux SHALL menampilkan Region_Overlay.
2. WHEN pengguna menyelesaikan pemilihan area pada Region_Overlay, Pinux SHALL menangkap Screenshot_Region melalui Screenshot_Portal.
3. WHEN Pinux menangkap Screenshot_Region, Pinux SHALL menjalankan OCR_Engine atas citra hasil tangkapan dan menetapkan teks hasil pengenalan sebagai Source_Text.
4. IF OCR_Engine tidak mengenali teks, Pinux SHALL menampilkan pemberitahuan dan mempertahankan Popup_Window pada keadaan terbuka.
5. WHERE OCR_Engine tidak tersedia, Pinux SHALL menampilkan pintasan OCR dengan status tidak aktif.
6. WHEN pengguna menekan tombol Escape selama pemilihan area, Pinux SHALL membatalkan penangkapan dan menutup Region_Overlay.

### Requirement 7: Mesin OCR Luring

**User Story:** AS pengguna, I want OCR tanpa koneksi jaringan, so that teks sensitif tidak meninggalkan komputer.

#### Acceptance Criteria

1. Pinux SHALL menyediakan satu OCR_Engine luring bernama `rapidocr` yang beroperasi tanpa akses jaringan setelah model tersimpan.
2. WHEN Pinux menjalankan OCR_Engine atas Screenshot_Region berukuran 800x600 piksel, Pinux SHALL menghasilkan teks hasil pengenalan dalam waktu kurang dari 3 detik pada prosesor 4 inti.
3. Pinux SHALL menyediakan antarmuka Python `OcrEngine` dengan operasi `recognize`, sehingga pengguna dapat menambahkan mesin OCR lain.
4. IF model OCR_Engine belum tersedia pada saat pertama kali OCR dijalankan, Pinux SHALL mengunduh model dan menampilkan indikator kemajuan unduhan.
5. Pinux SHALL memuat dependensi OCR_Engine secara terpisah dari dependensi inti, sehingga Pinux tetap berjalan tanpa paket OCR terpasang.

### Requirement 8: Operasi Latar Belakang dan Ikon Tray

**User Story:** AS pengguna, I want aplikasi tetap siap di latar belakang, so that pintasan keyboard selalu berfungsi.

#### Acceptance Criteria

1. WHEN pengguna menjalankan `pinux` tanpa argumen, Pinux SHALL berjalan sebagai layanan latar belakang dan mendaftarkan Global_Shortcut.
2. WHILE Pinux berjalan sebagai layanan latar belakang, Pinux SHALL menampilkan Tray_Icon dengan menu Pengaturan, OCR, dan Keluar.
3. WHEN pengguna memilih Keluar pada menu Tray_Icon, Pinux SHALL melepaskan Global_Shortcut dan mengakhiri proses.
4. IF Tray_Icon tidak dapat ditampilkan, Pinux SHALL mempertahankan Global_Shortcut pada keadaan aktif dan menampilkan jendela pengaturan.
5. Pinux SHALL menampilkan Tray_Icon melalui protokol StatusNotifierItem pada D-Bus tanpa ketergantungan pada pustaka AppIndicator.

### Requirement 9: Pengaturan dan Penyimpanan Kredensial

**User Story:** AS pengguna, I want mengatur layanan dan API key, so that kredensial tersimpan dengan aman.

#### Acceptance Criteria

1. Pinux SHALL menyimpan pengaturan pada berkas `pinux.toml` di dalam Config_Directory.
2. WHEN pengguna menyimpan Credential, Pinux SHALL menyimpan Credential ke Secret_Service.
3. IF Secret_Service tidak tersedia, Pinux SHALL menyimpan Credential pada berkas dengan izin 0600 dan menampilkan peringatan kepada pengguna.
4. WHEN pengguna mengubah pengaturan, Pinux SHALL menerapkan pengaturan tersebut tanpa menjalankan ulang Pinux.
5. WHEN Pinux membaca berkas pengaturan yang tidak valid, Pinux SHALL memakai nilai bawaan dan menampilkan peringatan dengan lokasi baris yang tidak valid.

### Requirement 10: Penanganan Galat dan Jaringan

**User Story:** AS pengguna, I want pesan galat yang jelas, so that saya tahu tindakan yang perlu dilakukan.

#### Acceptance Criteria

1. IF koneksi jaringan tidak tersedia, Pinux SHALL menampilkan pesan yang menyatakan koneksi jaringan tidak tersedia.
2. IF permintaan penerjemahan berjalan lebih dari 10 detik, Pinux SHALL membatalkan permintaan dan menampilkan pesan batas waktu.
3. WHEN Pinux menerima galat dari Translation_Provider, Pinux SHALL menuliskan nama Translation_Provider dan pesan galat ke `stderr`.
4. IF permintaan penerjemahan sebelumnya belum selesai, Pinux SHALL membatalkan permintaan sebelumnya dan menjalankan permintaan terbaru.

### Requirement 11: Kompatibilitas Lingkungan

**User Story:** AS pengguna Linux, I want aplikasi berjalan pada sesi desktop saya, so that saya dapat memakai aplikasi pada distribusi yang berbeda.

#### Acceptance Criteria

1. Pinux SHALL berjalan pada Desktop_Session bernilai Wayland.
2. Pinux SHALL berjalan pada Desktop_Session bernilai X11 dengan tambahan dukungan Primary_Selection.
3. Pinux SHALL berjalan pada Python versi 3.11 atau lebih baru.
4. Pinux SHALL berjalan pada GTK versi 4.10 atau lebih baru dan libadwaita versi 1.4 atau lebih baru.
5. Pinux SHALL berjalan tanpa paket sistem tambahan di luar paket yang menyediakan GTK4, libadwaita, dan PyGObject.
6. WHILE Desktop_Session bernilai Wayland, Pinux SHALL menampilkan keterangan pada layar pengaturan bahwa penangkapan teks bersumber dari Clipboard.

### Requirement 12: Riwayat Terjemahan dan Favorit

**User Story:** AS pengguna, I want melihat riwayat terjemahan dan menyimpan favorit, so that saya dapat meninjau kembali terjemahan penting sebelumnya.

#### Acceptance Criteria

1. Pinux SHALL menyimpan riwayat masukan dan hasil terjemahan secara lokal dalam database SQLite yang aman.
2. WHEN pengguna membuka jendela riwayat (`pinux --history` atau tombol riwayat pada popup), Pinux SHALL menampilkan daftar riwayat dengan pencarian dan filter favorit.
3. WHEN pengguna menandai entri sebagai favorit, Pinux SHALL mempertahankan status favorit entri tersebut.
4. IF pengguna menonaktifkan fitur riwayat melalui konfigurasi `[history] enabled = false`, Pinux SHALL tidak mencatat terjemahan baru ke dalam database.

### Requirement 13: Text-to-Speech (TTS)

**User Story:** AS pengguna, I want mendengarkan pelafalan teks sumber dan terjemahan, so that saya mengetahui cara membaca dan melafalkan teks tersebut.

#### Acceptance Criteria

1. WHEN pengguna menekan tombol TTS pada Popup_Window, Pinux SHALL melafalkan teks yang bersangkutan menggunakan backend TTS lokal (`spd-say`, `espeak-ng`, `espeak`, atau `say`).
2. Pinux SHALL mengirim teks ke backend TTS secara non-blokir melalui `stdin` guna mencegah command injection dan masalah karakter khusus.
3. WHEN pengguna memicu penghentian atau memulai pelafalan baru, Pinux SHALL menghentikan proses pelafalan sebelumnya secara asinkron tanpa memblokir thread antarmuka.

### Requirement 14: Distribusi Paket Flatpak

**User Story:** AS pengguna Linux berbagai distribusi, I want memasang Pinux dengan mudah melalui Flatpak, so that aplikasi terisolasi dan berjalan secara konsisten di Wayland maupun X11.

#### Acceptance Criteria

1. Pinux SHALL menyediakan berkas manifest Flatpak `io.github.gbu_project.Pinux.yml` yang terintegrasi dengan GNOME Platform Runtime dan XDG Desktop Portal.
2. Pinux Flatpak SHALL mendukung integrasi audio (PulseAudio / Speech Dispatcher), Secret Service, dan tray icon (StatusNotifierItem).

## Non-Goals untuk v1

- Mode kamus multi-bahasa luring dengan unduhan korpus kamus komprehensif berukuran gigabyte.
- Penerjemahan luring teks umum berbasis model neural besar (LLM lokal seperti Ollama tetap didukung melalui protokol API HTTP).
- Dukungan sistem operasi non-Linux (macOS dan Windows).

