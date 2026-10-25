"""OcrWorkerClient: permintaan bersamaan harus diserialkan (regresi sejak rilis 1.0.0).

Pekerja palsu (subproses Python sungguhan) memproses satu permintaan pada satu waktu
dan membalas lewat satu pipa stdout, seperti pekerja OCR asli. Tanpa serialisasi di
klien, dua ``recognize`` bersamaan saling membuang pesan dan keduanya habis waktu.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from pinux.ocr.client import OcrWorkerClient
from pinux.scheduler import CancelToken

WORKER = """
import json, sys, time
for line in sys.stdin:
    msg = json.loads(line)
    time.sleep(0.3)
    if msg.get("method") == "ensure_model":
        print(json.dumps({"id": msg["id"], "progress": 1.0}), flush=True)
    else:
        print(json.dumps({"id": msg["id"], "result": {"text": "T%d" % msg["id"], "lines": []}}), flush=True)
"""


@pytest.fixture
def client(tmp_path: Path):
    script = tmp_path / "fake_worker.py"
    script.write_text(WORKER)
    c = OcrWorkerClient(worker_cmd=[sys.executable, str(script)])
    yield c
    # Pada klien yang rusak shutdown() bisa macet menunggu kunci; jangan ikut menggantung.
    closer = threading.Thread(target=c.shutdown, daemon=True)
    closer.start()
    closer.join(3)
    if closer.is_alive() and c._proc is not None:
        c._proc.kill()


def _run_in_thread(fn, out: dict, key: str) -> threading.Thread:
    def _go() -> None:
        try:
            out[key] = fn()
        except Exception as exc:  # noqa: BLE001 - hasil galat dicatat untuk asersi
            out[key] = exc

    t = threading.Thread(target=_go, daemon=True)  # daemon: regresi gagal, bukan menggantung
    t.start()
    return t


ROUNDS = 6  # pembaca mana yang menang membaca pipa bersifat acak; ulangi agar regresi pasti terlihat


def test_concurrent_recognize_requests_both_succeed(client: OcrWorkerClient) -> None:
    for round_no in range(ROUNDS):
        out: dict = {}
        threads = [
            _run_in_thread(lambda: client.recognize(b"x", timeout_s=2).text, out, k) for k in ("a", "b")
        ]
        for t in threads:
            t.join(10)

        assert all(isinstance(v, str) and v.startswith("T") for v in out.values()) and len(out) == 2, (
            f"putaran {round_no}: {out}"  # tidak ada yang habis waktu / terputus
        )


def test_recognize_and_ensure_model_do_not_steal_each_others_messages(client: OcrWorkerClient) -> None:
    for round_no in range(ROUNDS):
        out: dict = {}
        progress: list[float] = []
        t1 = _run_in_thread(lambda: client.recognize(b"x", timeout_s=2).text, out, "r")
        t2 = _run_in_thread(lambda: client.ensure_model(progress.append), out, "m")
        for t in (t1, t2):
            t.join(5)

        assert isinstance(out.get("r"), str) and out["r"].startswith("T"), f"putaran {round_no}: {out}"
        assert out.get("m") is None and progress == [1.0], f"putaran {round_no}: {out} {progress}"


def test_queued_request_can_be_cancelled_without_disturbing_running_one(client: OcrWorkerClient) -> None:
    out: dict = {}
    first = _run_in_thread(lambda: client.recognize(b"x", timeout_s=5).text, out, "first")
    time.sleep(0.1)  # permintaan pertama sudah berjalan
    token = CancelToken()
    second = _run_in_thread(lambda: client.recognize(b"x", cancel=token, timeout_s=5).text, out, "second")
    time.sleep(0.1)
    token.cancel()
    second.join(5)
    first.join(15)

    assert isinstance(out["second"], RuntimeError) and "dibatalkan" in str(out["second"])
    assert out["first"] == "T1", "permintaan yang berjalan tidak boleh terganggu"


def test_shutdown_during_recognize_raises_runtime_error(client: OcrWorkerClient) -> None:
    out: dict = {}
    t = _run_in_thread(lambda: client.recognize(b"x", timeout_s=5).text, out, "r")
    time.sleep(0.1)

    client.shutdown()
    t.join(10)

    assert isinstance(out["r"], RuntimeError), out  # bukan AttributeError dari atribut yang dikosongkan
