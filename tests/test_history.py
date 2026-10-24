"""Tes HistoryStore (SQLite) dan pengaturan [history]."""

from __future__ import annotations

import os
import stat
import threading

import pytest

from pinux.config import Settings
from pinux.configstore import ConfigStore
from pinux.history import HistoryStore


@pytest.fixture
def store():
    s = HistoryStore(":memory:", max_entries=5)
    yield s
    s.close()


def _add(store, n, **kw):
    return store.add(f"src{n}", f"res{n}", kw.get("sl", "en"), kw.get("tl", "id"), "google-free")


def test_add_and_list_newest_first(store):
    for i in range(3):
        _add(store, i)
    assert [e.source_text for e in store.list()] == ["src2", "src1", "src0"]


def test_blank_text_not_saved(store):
    assert store.add("  ", "x", "en", "id", "p") is None
    assert store.add("x", "", "en", "id", "p") is None
    assert store.count() == 0


def test_consecutive_duplicate_updates_timestamp_only(store):
    a = _add(store, 1)
    b = _add(store, 1)
    assert a == b and store.count() == 1
    _add(store, 2)
    _add(store, 1)  # tidak berturut-turut: entri baru
    assert store.count() == 3


def test_prune_keeps_newest_and_all_favorites(store):
    ids = [_add(store, i) for i in range(5)]
    store.set_favorite(ids[0], True)  # entri tertua jadi favorit
    for i in range(5, 12):
        _add(store, i)
    entries = store.list(limit=100)
    non_fav = [e for e in entries if not e.favorite]
    assert len(non_fav) == 5
    assert any(e.id == ids[0] and e.favorite for e in entries)
    assert non_fav[0].source_text == "src11"


def test_favorites_filter_and_toggle(store):
    a, b = _add(store, 1), _add(store, 2)
    assert store.toggle_favorite(a) is True
    assert [e.id for e in store.list(favorites_only=True)] == [a]
    assert store.toggle_favorite(a) is False
    assert store.list(favorites_only=True) == []
    assert store.toggle_favorite(9999) is None and store.set_favorite(9999, True) is False
    assert b


def test_search_matches_source_or_result_and_escapes_wildcards(store):
    store.add("hello world", "halo dunia", "en", "id", "p")
    store.add("100% sure", "yakin 100%", "en", "id", "p")
    store.add("a_b", "x", "en", "id", "p")
    assert [e.source_text for e in store.list(query="dunia")] == ["hello world"]
    assert [e.source_text for e in store.list(query="100%")] == ["100% sure"]
    assert [e.source_text for e in store.list(query="a_b")] == ["a_b"]
    assert store.list(query="%") == [store.list(query="%")[0]]  # '%' literal, bukan wildcard
    assert len(store.list(query="%")) == 1


def test_delete_and_clear_keep_favorites(store):
    a, b, c = _add(store, 1), _add(store, 2), _add(store, 3)
    store.set_favorite(b, True)
    assert store.delete(a) and not store.delete(a)
    assert store.clear() == 1  # hanya c; b favorit
    assert [e.id for e in store.list()] == [b]
    assert store.clear(keep_favorites=False) == 1 and store.count() == 0
    assert c


def test_persistence_and_private_file_mode(tmp_path):
    path = tmp_path / "sub" / "history.db"
    s1 = HistoryStore(path)
    s1.add("a", "b", "en", "id", "p")
    s1.close()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    s2 = HistoryStore(path)
    assert s2.list()[0].source_text == "a"
    s2.close()


def test_thread_safe_concurrent_adds(tmp_path):
    s = HistoryStore(tmp_path / "h.db", max_entries=1000)

    def work(k):
        for i in range(20):
            s.add(f"t{k}-{i}", "r", "en", "id", "p")

    ts = [threading.Thread(target=work, args=(k,)) for k in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert s.count() == 100
    s.close()


def test_default_path_honours_xdg(monkeypatch, tmp_path):
    from pinux.history import default_history_path

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert default_history_path() == tmp_path / "pinux" / "history.db"


def test_history_settings_roundtrip_and_validation(tmp_path):
    cfg = ConfigStore(path=tmp_path / "pinux.toml")
    s = Settings()
    s.history.enabled = False
    s.history.max_entries = 50
    cfg.save(s)
    loaded = cfg.load()
    assert loaded.history.enabled is False and loaded.history.max_entries == 50

    (tmp_path / "bad.toml").write_text('[history]\nenabled = "ya"\nmax_entries = -3\n')
    bad = ConfigStore(path=tmp_path / "bad.toml")
    loaded = bad.load()
    assert loaded.history.enabled is True and loaded.history.max_entries == 500
    assert len(bad.warnings) >= 2


def test_close_is_idempotent():
    s = HistoryStore(":memory:")
    s.close()
    # Pemanggilan close() kedua tidak boleh melempar exception
    s.close()
    assert s._closed is True
