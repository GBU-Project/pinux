"""Tes provider OpenAI-compatible (server HTTP lokal), clean_text, dan config [llm]."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from pinux.capture.capturer import clean_text
from pinux.config import Settings
from pinux.configstore import ConfigStore
from pinux.translate.base import TranslationError, TranslationRequest
from pinux.translate.openai_compatible import OpenAICompatibleProvider


class _Handler(BaseHTTPRequestHandler):
    status = 200
    seen: dict = {}

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        type(self).seen = {
            "auth": self.headers.get("Authorization"),
            "body": json.loads(self.rfile.read(n)),
        }
        body = json.dumps(
            {"choices": [{"message": {"content": "Halo dunia"}}]}
        ).encode()
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    _Handler.status = 200
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1/chat/completions"
    srv.shutdown()


def _req(text="hello"):
    return TranslationRequest(text=text, source_lang="en", target_lang="id")


def test_local_endpoint_needs_no_key(server):
    p = OpenAICompatibleProvider(endpoint_url=server, model="m1")
    assert p.requires_credential() is False
    res = p.translate(_req())
    assert res.text == "Halo dunia"
    assert _Handler.seen["body"]["model"] == "m1"
    assert _Handler.seen["auth"] is None


def test_key_sent_as_bearer(server):
    OpenAICompatibleProvider(endpoint_url=server).translate(_req(), "sk-x")
    assert _Handler.seen["auth"] == "Bearer sk-x"


def test_remote_endpoint_requires_key():
    p = OpenAICompatibleProvider(endpoint_url="https://api.openai.com/v1/chat/completions")
    assert p.requires_credential() is True
    with pytest.raises(TranslationError) as e:
        p.translate(_req())
    assert e.value.kind == "auth"


def test_localhost_lookalike_host_is_not_local():
    p = OpenAICompatibleProvider(endpoint_url="https://localhost.evil.com/v1")
    assert p.requires_credential() is True


@pytest.mark.parametrize("code,kind", [(401, "auth"), (429, "rate_limit"), (503, "network"), (400, "provider")])
def test_http_errors_mapped(server, code, kind):
    _Handler.status = code
    with pytest.raises(TranslationError) as e:
        OpenAICompatibleProvider(endpoint_url=server).translate(_req(), "k")
    assert e.value.kind == kind


def test_connection_refused_is_network():
    p = OpenAICompatibleProvider(endpoint_url="http://127.0.0.1:1/v1", timeout_s=2)
    with pytest.raises(TranslationError) as e:
        p.translate(_req())
    assert e.value.kind == "network"


def test_clean_text_crlf_and_hyphen():
    assert clean_text("a\r\n\r\nb", unwrap_lines=False, remove_hyphens=False, remove_comments=False) == "a\n\nb"
    assert clean_text("trans-\nlation", unwrap_lines=False, remove_hyphens=True, remove_comments=False) == "translation"


def test_unwrap_latin_and_cjk():
    kw = dict(unwrap_lines=True, remove_hyphens=False, remove_comments=False)
    assert clean_text("hello\nworld", **kw) == "hello world"
    assert clean_text("你好\n世界", **kw) == "你好世界"
    assert clean_text("a\r\nb\r\n\r\nc", **kw) == "a b\n\nc"


def test_llm_settings_roundtrip(tmp_path):
    store = ConfigStore(path=tmp_path / "pinux.toml")
    s = Settings()
    s.llm.endpoint_url = "http://localhost:11434/v1/chat/completions"
    s.llm.model = "llama3"
    s.text_processing.unwrap_lines = True
    store.save(s)
    loaded = store.load()
    assert loaded.llm.model == "llama3"
    assert loaded.llm.endpoint_url.startswith("http://localhost")
    assert loaded.text_processing.unwrap_lines is True


def test_invalid_llm_endpoint_falls_back(tmp_path):
    path = tmp_path / "pinux.toml"
    path.write_text('[llm]\nendpoint_url = "ftp://x"\nmodel = "m"\n')
    loaded = ConfigStore(path=path).load()
    assert loaded.llm.endpoint_url.startswith("https://api.openai.com")
    assert loaded.llm.model == "m"
