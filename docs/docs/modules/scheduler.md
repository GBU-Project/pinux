# pinux/scheduler.py

> **Status**: sudah diimplementasikan (`CancelToken` dan `RequestScheduler`).

Modul ini punya dua tanggung jawab yang berkaitan erat: menyediakan penanda pembatalan
permintaan, dan menjalankan permintaan penerjemahan di luar thread utama GTK sambil
menjamin tepat satu callback kembali ke thread utama.

## Struktur

| Simbol | Status | Kegunaan |
|---|---|---|
| `CancelToken` | Sudah ada | Penanda pembatalan yang aman dipakai lintas thread |
| `RequestScheduler` | Sudah ada | Menjalankan `translate` pada `ThreadPoolExecutor` dan mengembalikan hasil ke thread utama |

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

Implementasi memakai `threading.Event` sehingga tidak memerlukan kunci tambahan.
Pembatalan bersifat kooperatif — batasan per jalur I/O dijelaskan pada
[CancelToken](../concepts/CancelToken.md#batasan-pembatalan-hanya-kooperatif).

## RequestScheduler

```python
class RequestScheduler:
    def __init__(
        self,
        executor: ThreadPoolExecutor | None = None,
        max_workers: int = 4,
        *,
        default_timeout_s: float = 10.0,
    ) -> None: ...

    @property
    def executor(self) -> ThreadPoolExecutor: ...

    def submit(
        self,
        request: TranslationRequest,
        provider: TranslationProvider,
        credential: str | None,
        on_result: Callable[[TranslationResult], None],
        on_error: Callable[[TranslationError], None],
        *,
        timeout_s: float | None = None,
    ) -> CancelToken: ...

    def cancel_active(self) -> None: ...
    def shutdown(self, wait: bool = False) -> None: ...
```

`executor` yang diberikan tetap dimiliki pemanggil; `shutdown()` hanya menutup executor
bila `RequestScheduler` yang membuatnya (`_owns_executor`). Hal ini mencegah penjadwal
menutup kolam thread milik pemanggil.

### Tanggung jawab

1. **Membatalkan permintaan sebelumnya.** `submit()` menandai token aktif sebelum membuat
   token baru, sehingga permintaan lama tidak lagi boleh menimpa UI (R10.4 / Properti 3).
2. **Menjalankan provider di worker thread.** Provider dipanggil langsung di dalam
   `_worker`, satu slot per permintaan — bukan lewat future bersarang pada kolam yang sama,
   yang dapat menguras kolam thread.
3. **Menegakkan batas waktu dengan `threading.Timer`.** Bukan dengan `future.result(timeout)`,
   sehingga timeout tetap bekerja meskipun semua worker sedang sibuk.
4. **Menjamin tepat satu callback.** Pemenang antara hasil provider dan pemicu timeout
   ditentukan `_claim()`, yang membungkus `threading.Event` + `Lock`:

   ```python
   def _claim() -> bool:
       with finish_lock:
           if finished.is_set():
               return False
           finished.set()
           return True
   ```

   Yang kalah `_claim()` tidak memanggil callback apa pun.
5. **Mengembalikan ke thread utama.** `on_result`/`on_error` selalu dipanggil lewat
   `GLib.idle_add`.
6. **Membuang hasil usang.** Callback hanya dijalankan bila `seq` masih aktif; galat
   berjenis `cancelled` disembunyikan agar UI tidak berkedip, sedangkan `timeout` tetap
   dilaporkan.

### Batas waktu

`timeout_s` pada `submit()` menimpa `default_timeout_s` milik penjadwal. `PinuxApp`
selalu mengirim `settings.request_timeout_s`, sehingga nilai di `pinux.toml` berlaku per
permintaan. Pesan galat timeout menyertakan durasi yang dipakai.

### Siklus hidup

- `cancel_active()` membatalkan token aktif dan mengosongkannya.
- `shutdown()` membatalkan token aktif lalu menutup executor dengan
  `cancel_futures=True` bila penjadwal pemiliknya.
- `PinuxApp.do_shutdown()` memanggil keduanya (`app.py`), sehingga tidak ada pekerja yang
  tertinggal saat aplikasi keluar.

## Dependensi

**Modul ini bergantung pada:** `gi.repository.GLib` (marshal callback ke thread utama),
`concurrent.futures`, dan `threading`. Tipe `TranslationRequest`, `TranslationProvider`,
`TranslationResult`, dan `TranslationError` hanya diimpor untuk keperluan `TYPE_CHECKING`
(kecuali `TranslationError`, yang diimpor di dalam fungsi untuk menghindari siklus).

**Bergantung pada modul ini:**

- `pinux.app` — membuat `RequestScheduler()` dan mengirim setiap permintaan penerjemahan
- `pinux.translate.base` — menerima `CancelToken` pada operasi `translate`
- `pinux.ocr.base` — menerima `CancelToken` pada operasi `recognize`
- `pinux.translate.chain` — dipanggil langsung oleh penjadwal tanpa perubahan kontrak

`CancelToken` sengaja diletakkan pada modul ini alih-alih pada paket `translate` atau
`ocr`, agar lapisan domain tidak perlu saling bergantung.

## Invarian

1. **Keadaan awal.** Token baru bernilai `cancelled` `False`.
2. **Idempotensi.** `cancel` dapat dipanggil berkali-kali tanpa mengubah hasil.
3. **Monotonisitas.** `cancelled` tidak pernah kembali `False` setelah bernilai `True`.
4. **Keamanan thread.** Pembacaan dan penulisan dari thread berbeda tidak menimbulkan
   balapan data.
5. **Tepat satu callback.** Untuk setiap `submit()`, paling banyak satu dari `on_result`
   atau `on_error` dipanggil, dan hanya bila permintaan itu masih yang terbaru.

## Pengujian

| Berkas | Cakupan |
|---|---|
| `tests/test_scheduler.py` | Eksekusi di latar, pembatalan permintaan sebelumnya, timeout, Properti 3 dan 4, serta galat `cancelled` yang tidak dilaporkan |
