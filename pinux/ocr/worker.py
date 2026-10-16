"""Titik masuk peladen pekerja OCR (pinux-ocr-worker).

Membaca permintaan JSON per baris dari stdin, memproses menggunakan
RapidOcrEngine, dan menulis respons JSON per baris ke stdout.
"""

from __future__ import annotations

import base64
import sys
from collections.abc import Sequence

from pinux.ocr.protocol import (
    decode_message,
    encode_error_response,
    encode_progress_response,
    encode_result_response,
)
from pinux.ocr.rapid import RapidOcrEngine


def main(argv: Sequence[str] | None = None) -> int:
    """Jalankan loop pekerja OCR melalui stdin/stdout."""
    engine = RapidOcrEngine()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            msg = decode_message(line)
        except Exception as exc:
            err_line = encode_error_response(0, "parse_error", str(exc))
            sys.stdout.write(err_line)
            sys.stdout.flush()
            continue

        req_id = msg.get("id", 0)
        method = msg.get("method")

        if method == "ensure_model":
            try:
                done = False

                def _on_prog(p: float) -> None:
                    nonlocal done
                    done = done or p >= 1.0
                    sys.stdout.write(encode_progress_response(req_id, p))
                    sys.stdout.flush()

                engine.ensure_model(on_progress=_on_prog)
                if not done:  # kirim progress 1.0 tepat satu kali
                    _on_prog(1.0)
            except Exception as exc:
                sys.stdout.write(encode_error_response(req_id, "model_error", str(exc)))
                sys.stdout.flush()

        elif method == "recognize":
            b64_image = msg.get("image", "")
            try:
                image_bytes = base64.b64decode(b64_image)
                res = engine.recognize(image_bytes)
                sys.stdout.write(encode_result_response(req_id, res))
                sys.stdout.flush()
            except Exception as exc:
                sys.stdout.write(encode_error_response(req_id, "ocr_error", str(exc)))
                sys.stdout.flush()

        else:
            sys.stdout.write(
                encode_error_response(req_id, "unknown_method", f"Method tidak dikenal: {method}")
            )
            sys.stdout.flush()

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
