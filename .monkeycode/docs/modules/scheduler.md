# pinux/scheduler.py

> **Status**: `CancelToken` sudah ada; `RequestScheduler` masih direncanakan.

Modul ini memiliki dua tanggung jawab yang berkaitan erat: menyediakan penanda pembatalan permintaan, dan (nantinya) menjadwalkan permintaan penerjemahan di luar thread utama GTK.

## Struktur

| Simbol | Status | Kegunaan |
|---|---|---|
| `CancelToken` | Sudah ada | Penanda pembatalan yang aman dipakai lintas thread |
| `RequestScheduler` | Direncanakan, task 8 | Menjalankan `translate` pada `ThreadPoolExecutor` dan mengembalikan hasil ke thread utama |

## CancelToken

```python
class CancelToken:
    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()
```

Implementasi memakai `threading.Event` sehingga tidak memerlukan kunci tambahan. Rincian konsepnya ada pada [CancelToken](../concepts/CancelToken.md).

## RequestScheduler yang Direncanakan

```python
class RequestScheduler:
    def __init__(self, executor: ThreadPoolExecutor, max_workers: int = 4) -> None: ...

    def submit(
        self,
        request: TranslationRequest,
        provider: TranslationProvider,
        credential: str | None,
        on_result: Callable[[TranslationResult], None],
        on_error: Callable[[TranslationError], None],
    ) -> CancelToken: ...
```

Tanggung jawab yang direncanakan:

1. Menyimpan token permintaan aktif dan membatalkannya sebelum menjalankan permintaan baru.
2. Membungkus `on_result` dan `on_error` dengan `GLib.idle_add` agar kembali ke thread utama.
3. Menerapkan batas waktu dari `Settings.request_timeout_s`.
4. Menjamin tepat satu dari `on_result` atau `on_error` dipanggil untuk setiap permintaan.

## Dependensi

**Modul ini bergantung pada:** tidak ada modul Pinux lain.

**Bergantung pada modul ini:**

- `pinux.translate.base` - `CancelToken` pada operasi `translate`
- `pinux.ocr.base` - `CancelToken` pada operasi `recognize`
- `pinux.ui.popup` (direncanakan) - menerima hasil melalui `on_result`

`CancelToken` sengaja diletakkan pada modul ini alih-alih pada paket `translate` atau `ocr`, agar lapisan domain tidak perlu saling bergantung.

## Invarian

1. **Keadaan awal.** Token baru bernilai `cancelled` `False`.
2. **Idempotensi.** `cancel` dapat dipanggil berkali-kali tanpa mengubah hasil.
3. **Monotonisitas.** `cancelled` tidak pernah kembali `False` setelah bernilai `True`.
4. **Keamanan thread.** Pembacaan dan penulisan dari thread berbeda tidak menimbulkan balapan data.

## Pengujian

| Berkas | Cakupan |
|---|---|
| `tests/test_models.py` | Keadaan awal, idempotensi, dan pelaporan pembatalan |
| `tests/test_scheduler.py` | Rencana pembatalan permintaan sebelumnya dan batas waktu, task 8.1 |
| `tests/test_scheduler_properties.py` | Rencana Properti 3 dan Properti 4, task 8.2 dan 8.3 |
