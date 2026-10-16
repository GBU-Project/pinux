"""Uji unit dan properti untuk tumpukan OCR.

Perujuk: task 13.1 dan 13.2 pada tasklist.md, R7.1, R7.2, R7.3, R7.4, R7.5, R6.5,
serta Properti 7 (inti bebas dependensi OCR) pada design.md.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pinux.ocr.base import OcrLine, OcrResult
from pinux.ocr.client import OcrWorkerClient, is_ocr_available
from pinux.ocr.protocol import (
    decode_message,
    encode_ensure_model_request,
    encode_error_response,
    encode_progress_response,
    encode_recognize_request,
    encode_result_response,
)
from pinux.scheduler import CancelToken


# --- Uji Unit 13.1: Pengodean dan Penguraian Protokol NDJSON ---------------


def test_protocol_encode_decode_ensure_model() -> None:
    encoded = encode_ensure_model_request(42)
    decoded = decode_message(encoded)
    assert decoded == {"id": 42, "method": "ensure_model"}


def test_protocol_encode_decode_recognize() -> None:
    raw_bytes = b"fake_png_data"
    encoded = encode_recognize_request(101, raw_bytes)
    decoded = decode_message(encoded)
    assert decoded["id"] == 101
    assert decoded["method"] == "recognize"
    assert base64.b64decode(decoded["image"]) == raw_bytes


def test_protocol_encode_decode_progress() -> None:
    encoded = encode_progress_response(5, 0.45)
    decoded = decode_message(encoded)
    assert decoded == {"id": 5, "progress": 0.45}


def test_protocol_encode_decode_result() -> None:
    line = OcrLine(text="Contoh", confidence=0.98, box=(10.0, 20.0, 100.0, 50.0))
    res = OcrResult(text="Contoh", lines=(line,))

    encoded = encode_result_response(7, res)
    decoded = decode_message(encoded)
    assert decoded["id"] == 7
    assert decoded["result"]["text"] == "Contoh"
    assert len(decoded["result"]["lines"]) == 1
    assert decoded["result"]["lines"][0]["box"] == [10.0, 20.0, 100.0, 50.0]


def test_protocol_encode_decode_error() -> None:
    encoded = encode_error_response(12, "ocr_error", "Model gagal memproses")
    decoded = decode_message(encoded)
    assert decoded == {"id": 12, "error": {"kind": "ocr_error", "message": "Model gagal memproses"}}


def test_protocol_decode_invalid_json() -> None:
    with pytest.raises(ValueError):
        decode_message("bukan json\n")

    with pytest.raises(ValueError):
        decode_message(json.dumps([1, 2, 3]))

    with pytest.raises(ValueError):
        decode_message(json.dumps({"method": "no_id"}))


# --- Uji OcrWorkerClient dengan Subproses Mock ------------------------------


def test_ocr_worker_client_ensure_model_and_progress(tmp_path: Path) -> None:
    # Buat worker tiruan berbasis python script
    mock_worker_script = tmp_path / "mock_worker.py"
    mock_worker_script.write_text(
        "import sys, json\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    if msg.get('method') == 'ensure_model':\n"
        "        sys.stdout.write(json.dumps({'id': msg['id'], 'progress': 0.5}) + '\\n')\n"
        "        sys.stdout.write(json.dumps({'id': msg['id'], 'progress': 1.0}) + '\\n')\n"
        "        sys.stdout.flush()\n",
        encoding="utf-8",
    )

    client = OcrWorkerClient(worker_cmd=[sys.executable, str(mock_worker_script)])
    progress_values: list[float] = []

    try:
        client.ensure_model(on_progress=progress_values.append)
        assert progress_values == [0.5, 1.0]
    finally:
        client.shutdown()


def test_ocr_worker_client_recognize_success(tmp_path: Path) -> None:
    mock_worker_script = tmp_path / "mock_worker.py"
    mock_worker_script.write_text(
        "import sys, json\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    if msg.get('method') == 'recognize':\n"
        "        res = {'text': 'Hasil Mock', 'lines': [{'text': 'Hasil Mock', 'confidence': 0.95, 'box': [0,0,10,10]}]}\n"
        "        sys.stdout.write(json.dumps({'id': msg['id'], 'result': res}) + '\\n')\n"
        "        sys.stdout.flush()\n",
        encoding="utf-8",
    )

    client = OcrWorkerClient(worker_cmd=[sys.executable, str(mock_worker_script)])

    try:
        result = client.recognize(b"fake_image_bytes")
        assert result.text == "Hasil Mock"
        assert len(result.lines) == 1
        assert result.lines[0].confidence == 0.95
    finally:
        client.shutdown()


def test_ocr_worker_client_handles_error_message(tmp_path: Path) -> None:
    mock_worker_script = tmp_path / "mock_worker.py"
    mock_worker_script.write_text(
        "import sys, json\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    sys.stdout.write(json.dumps({'id': msg['id'], 'error': {'kind': 'test_err', 'message': 'Gagal parah'}}) + '\\n')\n"
        "    sys.stdout.flush()\n",
        encoding="utf-8",
    )

    client = OcrWorkerClient(worker_cmd=[sys.executable, str(mock_worker_script)])

    try:
        with pytest.raises(RuntimeError, match="Galat pengenalan OCR: Gagal parah"):
            client.recognize(b"fake_image_bytes")
    finally:
        client.shutdown()


def test_ocr_worker_client_restart_after_failure(tmp_path: Path) -> None:
    mock_worker_script = tmp_path / "mock_worker.py"
    mock_worker_script.write_text(
        "import sys, json\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    if msg['id'] == 1:\n"
        "        sys.exit(1)\n"  # crash on first request
        "    else:\n"
        "        res = {'text': 'OK', 'lines': []}\n"
        "        sys.stdout.write(json.dumps({'id': msg['id'], 'result': res}) + '\\n')\n"
        "        sys.stdout.flush()\n",
        encoding="utf-8",
    )

    client = OcrWorkerClient(worker_cmd=[sys.executable, str(mock_worker_script)])

    try:
        # Panggilan pertama crash
        with pytest.raises(RuntimeError):
            client.recognize(b"first")

        # Panggilan kedua harus secara otomatis menjalankan ulang (respawn) pekerja
        res = client.recognize(b"second")
        assert res.text == "OK"
    finally:
        client.shutdown()


# --- Uji 13.2 / Properti 7: Inti Bebas Dependensi OCR -----------------------


def test_property_7_core_free_of_ocr_dependencies() -> None:
    """Properti 7: Mengimpor modul domain, translate, dan config berhasil tanpa onnxruntime/rapidocr."""
    # Pastikan modul onnxruntime dan rapidocr diblokir pada sys.modules
    with patch.dict(sys.modules, {"onnxruntime": None, "rapidocr_onnxruntime": None}):
        import pinux.capture
        import pinux.config
        import pinux.configstore
        import pinux.credentials
        import pinux.portal
        import pinux.scheduler
        import pinux.translate

        # Modul ocr.client dan ocr.base juga harus bisa diimpor tanpa onnxruntime
        import pinux.ocr.base
        import pinux.ocr.client
        import pinux.ocr.protocol

        assert pinux.ocr.client.is_ocr_available() is False


def test_recognize_ignores_stale_progress_messages(tmp_path):
    """Regresi: progress basi dari ensure_model tidak boleh terbaca sebagai hasil."""
    script = tmp_path / "stale_worker.py"
    script.write_text(
        "import sys, json\n"
        "for line in sys.stdin:\n"
        "    m = json.loads(line)\n"
        "    if m['method'] == 'ensure_model':\n"
        "        for p in (0.5, 1.0, 1.0):\n"
        "            print(json.dumps({'id': m['id'], 'progress': p}), flush=True)\n"
        "    else:\n"
        "        print(json.dumps({'id': m['id'], 'result': {'text': 'halo', 'lines': []}}), flush=True)\n"
    )
    client = OcrWorkerClient(worker_cmd=[sys.executable, str(script)])
    try:
        client.ensure_model()
        assert client.recognize(b"x").text == "halo"
    finally:
        client.shutdown()
