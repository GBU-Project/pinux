"""Protokol komunikasi antara proses utama Pinux dan pekerja OCR (pinux-ocr-worker).

Komunikasi berbasis JSON per baris (NDJSON) melalui stdin/stdout.

Format pesan sesuai tabel design.md:
- Permintaan ensure_model:
  {"id": 1, "method": "ensure_model"}
- Permintaan recognize:
  {"id": 1, "method": "recognize", "image": "<base64 PNG>"}
- Respons progress:
  {"id": 1, "progress": 0.42}
- Respons result:
  {"id": 1, "result": {"text": "...", "lines": [{"text": "...", "confidence": 0.9, "box": [l, t, r, b]}]}}
- Respons error:
  {"id": 1, "error": {"kind": "...", "message": "..."}}

Perujuk: task 13, R7.1, R7.2, R7.3, R7.4, R7.5, R6.5.
"""

from __future__ import annotations

import base64
import json
from dataclasses import asdict
from typing import Any

from pinux.ocr.base import OcrLine, OcrResult

__all__ = [
    "decode_message",
    "encode_ensure_model_request",
    "encode_error_response",
    "encode_progress_response",
    "encode_recognize_request",
    "encode_result_response",
]


def encode_ensure_model_request(req_id: int) -> str:
    """Susun pesan permintaan ensure_model."""
    return json.dumps({"id": req_id, "method": "ensure_model"}) + "\n"


def encode_recognize_request(req_id: int, image_png: bytes) -> str:
    """Susun pesan permintaan recognize dengan citra terenkode base64."""
    b64_image = base64.b64encode(image_png).decode("ascii")
    return json.dumps({"id": req_id, "method": "recognize", "image": b64_image}) + "\n"


def encode_progress_response(req_id: int, progress: float) -> str:
    """Susun pesan laporan kemajuan unduhan model (0.0 sampai 1.0)."""
    return json.dumps({"id": req_id, "progress": float(progress)}) + "\n"


def encode_result_response(req_id: int, result: OcrResult) -> str:
    """Susun pesan hasil pengenalan OCR."""
    lines_data = [
        {"text": line.text, "confidence": line.confidence, "box": list(line.box)}
        for line in result.lines
    ]
    return json.dumps({"id": req_id, "result": {"text": result.text, "lines": lines_data}}) + "\n"


def encode_error_response(req_id: int, kind: str, message: str) -> str:
    """Susun pesan galat dari pekerja OCR."""
    return json.dumps({"id": req_id, "error": {"kind": kind, "message": message}}) + "\n"


def decode_message(line: str) -> dict[str, Any]:
    """Urai satu baris JSON pesan protokol."""
    line = line.strip()
    if not line:
        raise ValueError("Pesan kosong")
    data = json.loads(line)
    if not isinstance(data, dict):
        raise ValueError(f"Pesan harus berupa objek JSON: {data}")
    if "id" not in data:
        raise ValueError(f"Pesan tidak memiliki 'id': {data}")
    return data
