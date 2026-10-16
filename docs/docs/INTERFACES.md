# Antarmuka Pinux

Dokumen ini menjelaskan antarmuka yang disediakan Pinux. Setiap bagian ditandai **Sudah ada** bila tersedia di repositori, atau **Direncanakan** bila masih berupa kontrak pada `design.md`.

## Antarmuka Python

### pinux.translate.base — Sudah ada

Modul `pinux/translate/base.py` menetapkan kontrak mesin penerjemahan.

#### Language

```python
@dataclass(frozen=True)
class Language:
    code: str    # kode BCP-47 sederhana, misalnya "id" atau "en"
    name: str    # nama tampilan, misalnya "Indonesia"
```

#### TranslationRequest

```python
@dataclass(frozen=True)
class TranslationRequest:
    text: str
    source_lang: str | None   # None berarti minta deteksi otomatis
    target_lang: str
```

#### TranslationResult

```python
@dataclass(frozen=True)
class TranslationResult:
    text: str
    detected_source_lang: str
    provider_id: str
```

#### TranslationError

```python
class TranslationError(Exception):
    def __init__(self, kind: ErrorKind, provider_id: str, message: str) -> None: ...

    kind: str          # salah satu nilai pada ERROR_KINDS
    provider_id: str
    message: str
```

`kind` hanya menerima nilai berikut. Nilai di luar daftar ditolak dengan `ValueError` pada saat objek dibuat.

| Nilai `kind` | Makna |
|---|---|
| `network` | Sambungan jaringan gagal atau tidak tersedia |
| `timeout` | Permintaan melampaui batas waktu |
| `auth` | Kredensial tidak sah atau tidak diizinkan |
| `rate_limit` | Kuota pemakaian tercapai |
| `provider` | Provider mengembalikan kegagalan lain |
| `cancelled` | Permintaan dibatalkan karena ada permintaan lebih baru |

Kode status HTTP dipetakan ke `kind` dengan aturan berikut: `429` menjadi `rate_limit`; `401` dan `403` menjadi `auth`; status `5xx` dan status galat lain menjadi `provider`; kegagalan DNS dan sambungan menjadi `network`.

#### Protocol TranslationProvider

```python
@runtime_checkable
class TranslationProvider(Protocol):
    id: str
    display_name: str

    def requires_credential(self) -> bool: ...
    def list_languages(self) -> Sequence[Language]: ...
    def translate(
        self,
        request: TranslationRequest,
        credential: str | None,
        cancel: CancelToken,
    ) -> TranslationResult: ...
```

`translate` wajib memunculkan `TranslationError` untuk setiap kegagalan, bukan pengecualian lain.

### pinux.ocr.base — Sudah ada

Modul `pinux/ocr/base.py` menetapkan kontrak mesin OCR. Modul ini tidak mengimpor `onnxruntime` maupun `rapidocr`.

#### OcrLine dan OcrResult

```python
@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float
    box: tuple[float, float, float, float]   # (left, top, right, bottom) dalam piksel

@dataclass(frozen=True)
class OcrResult:
    text: str
    lines: Sequence[OcrLine] = ()
```

#### Protocol OcrEngine

```python
@runtime_checkable
class OcrEngine(Protocol):
    id: str

    def is_available(self) -> bool: ...
    def ensure_model(self, on_progress: Callable[[float], None]) -> None: ...
    def recognize(self, image_png: bytes, cancel: CancelToken) -> OcrResult: ...
```

`on_progress` menerima nilai kemajuan antara `0.0` dan `1.0`.

### pinux.capture — Sudah ada

```python
# pinux/capture/base.py
CaptureOrigin = Literal["clipboard", "primary", "ocr"]

@dataclass(frozen=True)
class CaptureResult:
    text: str
    truncated: bool
    origin: CaptureOrigin
```

`truncated` bernilai `True` jika dan hanya jika teks dipotong karena melebihi `Settings.max_chars`. Nilai `origin` bernilai `"primary"` hanya pada Desktop_Session X11.

### pinux.config — Sudah ada

```python
@dataclass
class PopupSettings:
    pin_default: bool = False
    width: int = 420
    close_on_blur: bool = True

@dataclass
class OcrSettings:
    engine: str = "rapidocr"
    enabled: bool = True

@dataclass(frozen=True)
class ProviderEntry:
    id: str
    module: str     # format "package.module:ClassName"
    label: str

@dataclass
class Settings:
    target_language: str = "id"
    fallback_language: str = "en"
    provider: str = "google-free"
    max_chars: int = 5000
    request_timeout_s: float = 10.0
    shortcuts: dict[str, str] = {"translate": "<Control><Alt>T", "ocr": "<Control><Alt>O"}
    popup: PopupSettings = PopupSettings()
    ocr: OcrSettings = OcrSettings()
    providers: list[ProviderEntry] = []
```

### pinux.scheduler — Sudah ada

```python
class CancelToken:
    def cancel(self) -> None: ...
    @property
    def cancelled(self) -> bool: ...
```

Token aman dipakai lintas thread: `cancel` boleh dipanggil dari thread utama sedangkan `cancelled` dibaca dari worker thread.

## Titik Perluasan

### Menambahkan Translation_Provider — Direncanakan

Provider pihak ketiga didaftarkan melalui salah satu dari dua jalur berikut. Keduanya belum diimplementasikan; pemuatannya berada pada task 7.

**Jalur berkas pengaturan.** Tambahkan entri pada `pinux.toml`:

```toml
[[providers]]
id = "deepl"
module = "pinux_provider_deepl:DeepLProvider"
label = "DeepL"
```

**Jalur entry point.** Distribusikan paket Python yang mendeklarasikan entry point pada grup `pinux.providers`. Nilainya menunjuk ke kelas yang memenuhi Protocol `TranslationProvider`.

Kelas provider harus memenuhi seluruh anggota Protocol `TranslationProvider`. Contoh implementasi berbasis Credential direncanakan pada `examples/deepl_provider.py` (task 7).

### Menambahkan OcrEngine — Direncanakan

Mesin OCR tambahan cukup memenuhi Protocol `OcrEngine`. Pemilihan mesin dilakukan melalui `Settings.ocr["engine"]` yang bernilai `id` mesin tersebut. Klien pekerja OCR berada pada task 13.

## Antarmuka Baris Perintah — Direncanakan

Titik masuk `pinux/__main__.py:main` sudah terdaftar sebagai perintah `pinux`, namun isinya belum diimplementasikan.

| Perintah | Kegunaan |
|---|---|
| `pinux` | Menjalankan Pinux sebagai layanan latar belakang dan mendaftarkan pintasan global |
| `pinux --trigger` | Memicu terjemahan atas isi Clipboard pada instans yang sedang berjalan |
| `pinux --pick-region` | Memicu pemilihan area layar dan OCR pada instans yang sedang berjalan |
| `pinux --settings` | Membuka jendela pengaturan |
| `pinux-ocr-worker` | Menjalankan proses pekerja OCR; dipanggil otomatis oleh Pinux |

`pinux --trigger` dan `pinux --pick-region` adalah jalur yang dipakai ketika portal GlobalShortcuts tidak tersedia. Keduanya dirancang untuk diikat pengguna pada pintasan keyboard desktop.

## Berkas Pengaturan — Direncanakan

Lokasi: `$XDG_CONFIG_HOME/pinux/pinux.toml`, dengan nilai bawaan `~/.config/pinux/pinux.toml`.

```toml
target_language = "id"
fallback_language = "en"
provider = "google-free"
max_chars = 5000
request_timeout_s = 10.0

[shortcuts]
translate = "<Control><Alt>T"
ocr = "<Control><Alt>O"

[popup]
pin_default = false
width = 420
close_on_blur = true

[ocr]
engine = "rapidocr"
enabled = true

[[providers]]
id = "deepl"
module = "pinux_provider_deepl:DeepLProvider"
label = "DeepL"
```

Berkas `pinux.toml` tidak pernah memuat nilai Credential. Credential disimpan pada Secret Service, atau pada berkas `$XDG_DATA_HOME/pinux/credentials.toml` dengan izin `0600` ketika Secret Service tidak tersedia.

## Protokol Pekerja OCR — Direncanakan

Proses `pinux-ocr-worker` berkomunikasi melalui stdin/stdout dengan satu objek JSON per baris.

| Pesan | Arah | Isi |
|---|---|---|
| `{"id": 1, "method": "ensure_model"}` | klien ke worker | memuat atau mengunduh model |
| `{"id": 1, "method": "recognize", "image": "<base64 PNG>"}` | klien ke worker | permintaan pengenalan |
| `{"id": 1, "progress": 0.42}` | worker ke klien | kemajuan unduhan model |
| `{"id": 1, "result": {"text": "...", "lines": []}}` | worker ke klien | hasil pengenalan |
| `{"id": 1, "error": {"kind": "...", "message": "..."}}` | worker ke klien | galat |

Pembatalan dilakukan dengan mengirim `SIGTERM` ke proses pekerja; worker dijalankan ulang pada permintaan berikutnya.

## Antarmuka D-Bus yang Dipakai — Direncanakan

Pinux tidak mengekspos layanan D-Bus miliknya sendiri di luar instans tunggal `GApplication`. Antarmuka D-Bus yang dikonsumsi:

| Antarmuka | Kegunaan |
|---|---|
| `org.freedesktop.portal.GlobalShortcuts` | Mendaftarkan dan menerima pemicu pintasan global |
| `org.freedesktop.portal.Screenshot` | Menangkap layar penuh sebelum dipotong |
| `org.freedesktop.secrets` | Menyimpan dan membaca Credential |
| `org.kde.StatusNotifierWatcher` | Mendaftarkan Tray_Icon |
| `com.canonical.dbusmenu` | Menyediakan menu Tray_Icon |
