"""Pembantu permintaan asinkron XDG Desktop Portal (pola Request/Response).

Metode portal seperti ``Screenshot``, ``CreateSession`` dan ``BindShortcuts``
mengembalikan path objek Request, lalu hasil sebenarnya datang lewat sinyal
``org.freedesktop.portal.Request.Response``. Dua jebakan yang ditangani di
sini:

1. Sinyal bisa tiba sebelum pemanggil sempat berlangganan. Path Request dapat
   diprediksi dari nama unik koneksi dan ``handle_token``, sehingga langganan
   dipasang *sebelum* metode dipanggil.
2. Menunggu tidak boleh memutar ``GLib.MainLoop`` baru dari thread latar pada
   konteks utama yang dimiliki thread lain. Dari thread utama dipakai loop
   bersarang; dari thread lain cukup menunggu ``threading.Event``, karena
   callback dbus berjalan di thread utama.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, Final

from gi.repository import GLib

__all__ = ["REQUEST_INTERFACE", "portal_request", "predicted_request_path"]

REQUEST_INTERFACE: Final[str] = "org.freedesktop.portal.Request"


def predicted_request_path(bus: Any, token: str) -> str:
    """Path Request yang akan dipakai portal untuk ``handle_token`` ini."""
    sender = str(bus.get_unique_name()).lstrip(":").replace(".", "_")
    return f"/org/freedesktop/portal/desktop/request/{sender}/{token}"


def portal_request(
    bus: Any,
    call: Callable[[], Any],
    token: str,
    *,
    timeout_s: float,
) -> tuple[int, dict[str, Any]]:
    """Panggil ``call`` lalu tunggu sinyal Response; kembalikan ``(kode, hasil)``.

    ``token`` harus sama dengan ``handle_token`` yang dikirim ``call``.
    Memunculkan ``TimeoutError`` bila tidak ada respons dalam ``timeout_s``.
    """
    done = threading.Event()
    box: dict[str, tuple[int, dict[str, Any]]] = {}
    on_main_thread = threading.current_thread() is threading.main_thread()
    loop = GLib.MainLoop() if on_main_thread else None

    def _on_response(code: int, results: Any) -> None:
        box["r"] = (int(code), dict(results))
        done.set()
        if loop is not None:
            loop.quit()

    paths: list[str] = []

    def _subscribe(path: str) -> None:
        bus.add_signal_receiver(
            _on_response,
            signal_name="Response",
            dbus_interface=REQUEST_INTERFACE,
            path=path,
        )
        paths.append(path)

    expected = predicted_request_path(bus, token)
    timeout_id = None
    _subscribe(expected)
    try:
        actual = str(call())
        if actual != expected:  # portal lama yang tidak memakai handle_token
            _subscribe(actual)

        if not done.is_set():
            if loop is not None:
                def _on_timeout() -> bool:
                    nonlocal timeout_id
                    timeout_id = None  # sumber otomatis hilang saat mengembalikan False
                    loop.quit()
                    return False

                timeout_id = GLib.timeout_add(int(timeout_s * 1000), _on_timeout)
                if not done.is_set():
                    loop.run()
            else:
                done.wait(timeout_s)
    finally:
        if timeout_id is not None:
            GLib.source_remove(timeout_id)
        for path in paths:
            try:
                bus.remove_signal_receiver(
                    _on_response,
                    signal_name="Response",
                    dbus_interface=REQUEST_INTERFACE,
                    path=path,
                )
            except Exception:
                pass

    if "r" not in box:
        raise TimeoutError(f"Portal tidak merespons dalam {timeout_s} detik")
    return box["r"]
