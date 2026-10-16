# pinux/capture/

> **Status**: model sudah ada; TextCapturer dan backend clipboard masih direncanakan.

Paket ini memuat model hasil penangkapan Source_Text dan, nantinya, logika pembacaan Clipboard beserta `Primary_Selection`.

## Struktur

```
pinux/capture/
├── __init__.py               # Mengekspor ulang CaptureResult
└── base.py                   # CaptureOrigin dan CaptureResult
```

Berkas berikut masih direncanakan:

```
pinux/capture/
├── capturer.py               # TextCapturer, task 10
├── clipboard.py              # Abstraksi pembacaan Clipboard, task 10
└── session.py                # Deteksi Desktop_Session, task 10
```

## Berkas Kunci

| Berkas | Kegunaan |
|---|---|
| `base.py` | `CaptureOrigin` dan `CaptureResult` |
| `__init__.py` | Mengekspor ulang `CaptureResult`, sehingga `from pinux.capture import CaptureResult` tetap berlaku sesuai `design.md` |

## Mengapa Berbentuk Paket

`design.md` merujuk modul `pinux.capture`, sedangkan `tasklist.md` meminta subpaket. Bentuk paket dipilih agar keduanya terpenuhi: `pinux.capture` tetap dapat diimpor sebagai paket, sekaligus tersedia ruang untuk memisahkan backend clipboard menurut sesi desktop.

## Dependensi

**Paket ini bergantung pada:** tidak ada modul Pinux lain.

**Bergantung pada paket ini:**

- `pinux.ui.popup` (direncanakan) - menampilkan Source_Text
- `pinux.app` (direncanakan) - merangkai alur pemicu terjemahan

`base.py` tidak boleh mengimpor modul GTK. Abstraksi pembacaan Clipboard berada pada berkas terpisah agar dapat digantikan pada pengujian.

## Aturan menurut Sesi Desktop

| Sesi | Sumber | Deteksi perubahan |
|---|---|---|
| Wayland | `Gdk.Clipboard` | Sinyal `changed` saat popup terbuka |
| X11 | `Gdk.Clipboard` dan `Gdk.Display.get_primary_clipboard()` | Sinyal `changed` pada kedua objek |

## Pengujian

| Berkas | Cakupan |
|---|---|
| `tests/conftest.py` | Fixture `FakeClipboard` yang meniru bagian antarmuka `GdkClipboard` yang dipakai |
| `tests/test_capture.py` | Rencana pengujian pemotongan teks dan pemilihan sumber, task 10.1 |

`FakeClipboard` menyediakan `text`, `set_text`, dan `connect_changed`, sehingga pengujian tidak memerlukan sesi grafis.
