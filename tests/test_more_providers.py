"""Tes DeepL, LibreTranslate, rantai fallback, dan konfigurasinya (server HTTP lokal)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from pinux.config import Settings
from pinux.configstore import ConfigStore
from pinux.credentials import CredentialStore
from pinux.translate.base import TranslationError, TranslationRequest, TranslationResult
from pinux.translate.chain import FallbackChain
from pinux.translate.deepl import DeepLProvider, to_deepl_target
from pinux.translate.libretranslate import LibreTranslateProvider
from pinux.translate.registry import ProviderRegistry


class _H(BaseHTTPRequestHandler):
    status = 200
    reply: dict = {}
    seen: dict = {}

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        type(self).seen = {
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "body": json.loads(self.rfile.read(n)),
        }
        body = json.dumps(type(self).reply).encode()
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    _H.status, _H.reply, _H.seen = 200, {}, {}
    srv = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def _req(src="en"):
    return TranslationRequest(text="hello", source_lang=src, target_lang="id")


# --- LibreTranslate ---------------------------------------------------------


def test_libretranslate_auto_detect_and_key(server):
    _H.reply = {"translatedText": "halo", "detectedLanguage": {"language": "en"}}
    p = LibreTranslateProvider(endpoint_url=server + "/")
    res = p.translate(_req(None), "k123")
    assert (res.text, res.detected_source_lang) == ("halo", "en")
    assert _H.seen["path"] == "/translate"
    assert _H.seen["body"]["source"] == "auto"
    assert _H.seen["body"]["api_key"] == "k123"


def test_libretranslate_bad_payload_and_errors(server):
    p = LibreTranslateProvider(endpoint_url=server)
    _H.reply = {"oops": 1}
    with pytest.raises(TranslationError) as e:
        p.translate(_req())
    assert e.value.kind == "provider"
    _H.status, _H.reply = 429, {}
    with pytest.raises(TranslationError) as e:
        p.translate(_req())
    assert e.value.kind == "rate_limit"


def test_libretranslate_unreachable_is_network():
    with pytest.raises(TranslationError) as e:
        LibreTranslateProvider(endpoint_url="http://127.0.0.1:1", timeout_s=2).translate(_req())
    assert e.value.kind == "network"


# --- DeepL --------------------------------------------------------------------


def test_deepl_target_codes():
    assert to_deepl_target("en") == "EN-US"
    assert to_deepl_target("pt") == "PT-BR"
    assert to_deepl_target("id") == "ID"
    assert to_deepl_target("zh") == "ZH"


def test_deepl_translate(server):
    _H.reply = {"translations": [{"detected_source_language": "EN", "text": "halo"}]}
    p = DeepLProvider(endpoint_override=server + "/v2/translate")
    res = p.translate(_req(None), "abc:fx")
    assert (res.text, res.detected_source_lang) == ("halo", "en")
    assert _H.seen["auth"] == "DeepL-Auth-Key abc:fx"
    assert _H.seen["body"] == {"text": ["hello"], "target_lang": "ID"}


def test_deepl_requires_key_and_maps_quota(server):
    p = DeepLProvider(endpoint_override=server)
    with pytest.raises(TranslationError) as e:
        p.translate(_req(), None)
    assert e.value.kind == "auth"
    _H.status = 456
    with pytest.raises(TranslationError) as e:
        p.translate(_req(), "k")
    assert e.value.kind == "rate_limit"


def test_deepl_hides_unsupported_languages():
    codes = {lang.code for lang in DeepLProvider().list_languages()}
    assert "id" in codes and "vi" not in codes


# --- FallbackChain -------------------------------------------------------------


class _Fake:
    def __init__(self, pid, *, error=None, text="ok"):
        self.id, self.display_name = pid, pid
        self.error, self.text, self.calls = error, text, []

    def requires_credential(self):
        return False

    def list_languages(self):
        return ()

    def translate(self, request, credential, cancel):
        self.calls.append(credential)
        if self.error:
            raise TranslationError(self.error, self.id, f"{self.id} gagal")
        return TranslationResult(self.text, "en", self.id)


def test_chain_uses_first_success_with_member_credentials():
    a, b, c = _Fake("a", error="rate_limit"), _Fake("b"), _Fake("c")
    res = FallbackChain([(a, "ka"), (b, "kb"), (c, "kc")]).translate(_req(), None, None)
    assert res.provider_id == "b"
    assert a.calls == ["ka"] and b.calls == ["kb"] and c.calls == []


def test_chain_raises_primary_error_when_all_fail():
    chain = FallbackChain([(_Fake("a", error="timeout"), None), (_Fake("b", error="network"), None)])
    with pytest.raises(TranslationError) as e:
        chain.translate(_req(), None, None)
    assert (e.value.provider_id, e.value.kind) == ("a", "timeout")


def test_chain_does_not_swallow_cancel():
    b = _Fake("b")
    chain = FallbackChain([(_Fake("a", error="cancelled"), None), (b, None)])
    with pytest.raises(TranslationError) as e:
        chain.translate(_req(), None, None)
    assert e.value.kind == "cancelled" and b.calls == []


def test_chain_requires_members():
    with pytest.raises(ValueError):
        FallbackChain([])


# --- Registry & konfigurasi ----------------------------------------------------


def test_registry_registers_new_providers_and_builds_chain(tmp_path):
    creds = CredentialStore(tmp_path / "c.toml", force_fallback=True)
    reg = ProviderRegistry(creds)
    assert reg.get("deepl") and reg.get("libretranslate")

    # DeepL tanpa kunci dilewati; libretranslate tidak butuh kunci; duplikat/ tak dikenal dilewati
    chain = reg.build_chain("google-free", ["deepl", "libretranslate", "libretranslate", "nope"])
    assert isinstance(chain, FallbackChain)
    assert [m[0].id for m in chain._members] == ["google-free", "libretranslate"]

    creds.set("deepl", "k:fx")
    chain = reg.build_chain("google-free", ["deepl"])
    assert [m[0].id for m in chain._members] == ["google-free", "deepl"]

    assert reg.build_chain("google-free", []) is reg.get("google-free")
    assert reg.build_chain("tidak-ada", []) is None


def test_registry_applies_libretranslate_endpoint(tmp_path):
    reg = ProviderRegistry(CredentialStore(tmp_path / "c.toml"))
    reg.apply_libretranslate_settings("http://libre.example:5000")
    assert reg.get("libretranslate").endpoint_url == "http://libre.example:5000"


def test_config_roundtrip_fallbacks_and_libre(tmp_path):
    store = ConfigStore(path=tmp_path / "pinux.toml")
    s = Settings()
    s.fallback_providers = ["deepl", "libretranslate"]
    s.libretranslate.endpoint_url = "http://libre.example:5000"
    store.save(s)
    loaded = store.load()
    assert loaded.fallback_providers == ["deepl", "libretranslate"]
    assert loaded.libretranslate.endpoint_url == "http://libre.example:5000"


def test_config_rejects_bad_fallbacks_and_url(tmp_path):
    path = tmp_path / "pinux.toml"
    path.write_text('fallback_providers = "deepl"\n[libretranslate]\nendpoint_url = "ftp://x"\n')
    store = ConfigStore(path=path)
    loaded = store.load()
    assert loaded.fallback_providers == []
    assert loaded.libretranslate.endpoint_url == "http://localhost:5000"
    assert len(store.warnings) >= 2


# --- Mode bandingkan ------------------------------------------------------------


def test_compare_collects_alternatives_without_breaking_primary():
    from pinux.translate.compare import CompareProvider

    primary = _Fake("a", text="utama")
    ok = _Fake("b", text="alt")
    bad = _Fake("c", error="rate_limit")
    res = CompareProvider(primary, [(ok, "kb"), (bad, None)]).translate(_req(), None, None)
    assert res.text == "utama" and res.provider_id == "a"
    by_id = {a.provider_id: a for a in res.alternatives}
    assert by_id["b"].text == "alt" and not by_id["b"].error
    assert by_id["c"].error == "c gagal" and by_id["c"].text == ""
    assert ok.calls == ["kb"]


def test_compare_primary_error_propagates():
    from pinux.translate.compare import CompareProvider

    cmp_ = CompareProvider(_Fake("a", error="auth"), [(_Fake("b"), None)])
    with pytest.raises(TranslationError) as e:
        cmp_.translate(_req(), None, None)
    assert e.value.kind == "auth"


def test_compare_slow_extra_times_out():
    import time

    from pinux.translate.compare import CompareProvider

    class Slow(_Fake):
        def translate(self, request, credential, cancel):
            time.sleep(0.5)
            return super().translate(request, credential, cancel)

    res = CompareProvider(_Fake("a"), [(Slow("s"), None)], extra_timeout_s=0.05).translate(
        _req(), None, None
    )
    assert res.alternatives[0].error == "Waktu habis"


def test_registry_build_active_filters_extras(tmp_path):
    from pinux.translate.compare import CompareProvider

    reg = ProviderRegistry(CredentialStore(tmp_path / "c.toml", force_fallback=True))
    active = reg.build_active("google-free", [], ["deepl", "libretranslate", "google-free", "x"])
    assert isinstance(active, CompareProvider)
    assert [p.id for p, _ in active._extras] == ["libretranslate"]
    assert reg.build_active("google-free", [], ["deepl"]) is reg.get("google-free")


def test_config_roundtrip_compare_providers(tmp_path):
    store = ConfigStore(path=tmp_path / "pinux.toml")
    s = Settings()
    s.compare_providers = ["deepl", "openai"]
    store.save(s)
    assert store.load().compare_providers == ["deepl", "openai"]
