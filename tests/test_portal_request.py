"""Uji portal_request: pola Request/Response XDG portal."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest
from gi.repository import GLib

from pinux.portal.request import portal_request, predicted_request_path


def _bus():
    bus = MagicMock()
    bus.get_unique_name.return_value = ":1.42"
    receivers = []
    bus.add_signal_receiver.side_effect = lambda cb, **kw: receivers.append((cb, kw))
    return bus, receivers


def test_predicted_path_format():
    bus, _ = _bus()
    assert predicted_request_path(bus, "tok") == (
        "/org/freedesktop/portal/desktop/request/1_42/tok"
    )


def test_subscribes_before_call_and_survives_early_response():
    """Response yang tiba sebelum call() kembali tidak boleh hilang."""
    bus, receivers = _bus()

    def call():
        assert receivers, "langganan harus dipasang sebelum metode dipanggil"
        receivers[0][0](0, {"x": 1})  # respons datang langsung
        return "/org/freedesktop/portal/desktop/request/1_42/tok"

    code, res = portal_request(bus, call, "tok", timeout_s=1.0)
    assert (code, res) == (0, {"x": 1})
    assert bus.remove_signal_receiver.called


def test_timeout_raises():
    bus, _ = _bus()
    with pytest.raises(TimeoutError):
        portal_request(bus, lambda: "/req/other", "tok", timeout_s=0.05)


def test_worker_thread_waits_for_main_loop_dispatch():
    """Dari thread latar: tunggu Event, sinyal diantar oleh thread utama."""
    bus, receivers = _bus()
    out = {}

    def worker():
        out["r"] = portal_request(
            bus, lambda: "/org/freedesktop/portal/desktop/request/1_42/tok", "tok", timeout_s=3.0
        )
        GLib.idle_add(loop.quit)

    loop = GLib.MainLoop()
    t = threading.Thread(target=worker)
    t.start()

    def deliver():
        if receivers:
            receivers[0][0](0, {"uri": "file:///x.png"})
            return False
        return True  # coba lagi sampai langganan terpasang

    GLib.timeout_add(20, deliver)
    GLib.timeout_add(4000, loop.quit)
    loop.run()
    t.join()
    assert out["r"] == (0, {"uri": "file:///x.png"})
