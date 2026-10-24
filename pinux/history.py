"""Riwayat dan favorit terjemahan (SQLite, berkas lokal ``$XDG_DATA_HOME/pinux/history.db``).

Berkas dibuat dengan izin 0600 karena memuat teks yang diterjemahkan pengguna.
Entri favorit tidak pernah dihapus oleh pemangkasan otomatis maupun ``clear()``
bawaan. Semua metode aman dipanggil dari thread mana pun.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = ["HistoryEntry", "HistoryStore", "default_history_path"]

HISTORY_FILE_NAME: Final[str] = "history.db"

_SCHEMA: Final[str] = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    source_text TEXT NOT NULL,
    result_text TEXT NOT NULL,
    source_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    favorite INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_entries_ts ON entries(ts DESC);
"""


def default_history_path() -> Path:
    """Lokasi basis data riwayat menurut spesifikasi XDG."""
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home) if data_home and data_home.strip() else Path.home() / ".local" / "share"
    return base / "pinux" / HISTORY_FILE_NAME


@dataclass(frozen=True)
class HistoryEntry:
    id: int
    ts: float
    source_text: str
    result_text: str
    source_lang: str
    target_lang: str
    provider_id: str
    favorite: bool


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class HistoryStore:
    """Penyimpanan riwayat; ``path=":memory:"`` dipakai untuk pengujian."""

    def __init__(self, path: Path | str | None = None, *, max_entries: int = 500) -> None:
        self.max_entries = max(1, int(max_entries))
        self._lock = threading.Lock()
        target = default_history_path() if path is None else path
        if target != ":memory:":
            target = Path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                # Buat berkas dengan izin ketat sebelum SQLite menulis apa pun.
                fd = os.open(target, os.O_CREAT | os.O_WRONLY, 0o600)
                os.close(fd)
        self._conn = sqlite3.connect(str(target), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._closed = False
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)

    @staticmethod
    def _to_entry(row: sqlite3.Row) -> HistoryEntry:
        return HistoryEntry(
            id=row["id"],
            ts=row["ts"],
            source_text=row["source_text"],
            result_text=row["result_text"],
            source_lang=row["source_lang"],
            target_lang=row["target_lang"],
            provider_id=row["provider_id"],
            favorite=bool(row["favorite"]),
        )

    def add(
        self,
        source_text: str,
        result_text: str,
        source_lang: str,
        target_lang: str,
        provider_id: str,
    ) -> int | None:
        """Simpan satu terjemahan; kembalikan id entri (None bila teks kosong).

        Terjemahan identik berturut-turut (teks, bahasa, hasil sama dengan entri
        terbaru) hanya memperbarui waktunya, sehingga debounce/retry tidak menggandakan.
        """
        if not source_text.strip() or not result_text.strip():
            return None
        now = time.time()
        with self._lock, self._conn:
            latest = self._conn.execute(
                "SELECT * FROM entries ORDER BY ts DESC, id DESC LIMIT 1"
            ).fetchone()
            if (
                latest is not None
                and latest["source_text"] == source_text
                and latest["result_text"] == result_text
                and latest["target_lang"] == target_lang
            ):
                self._conn.execute("UPDATE entries SET ts = ? WHERE id = ?", (now, latest["id"]))
                return int(latest["id"])
            cur = self._conn.execute(
                "INSERT INTO entries (ts, source_text, result_text, source_lang, target_lang,"
                " provider_id) VALUES (?, ?, ?, ?, ?, ?)",
                (now, source_text, result_text, source_lang, target_lang, provider_id),
            )
            new_id = int(cur.lastrowid)
            self._prune_locked()
            return new_id

    def _prune_locked(self) -> None:
        self._conn.execute(
            "DELETE FROM entries WHERE favorite = 0 AND id NOT IN ("
            " SELECT id FROM entries WHERE favorite = 0 ORDER BY ts DESC, id DESC LIMIT ?)",
            (self.max_entries,),
        )

    def list(
        self,
        *,
        query: str = "",
        favorites_only: bool = False,
        limit: int = 100,
    ) -> list[HistoryEntry]:
        """Daftar entri terbaru lebih dulu; ``query`` mencari di teks sumber dan hasil."""
        clauses: list[str] = []
        params: list[object] = []
        if favorites_only:
            clauses.append("favorite = 1")
        if query.strip():
            like = f"%{_like_escape(query.strip())}%"
            clauses.append("(source_text LIKE ? ESCAPE '\\' OR result_text LIKE ? ESCAPE '\\')")
            params += [like, like]
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM entries {where} ORDER BY ts DESC, id DESC LIMIT ?", params
            ).fetchall()
        return [self._to_entry(r) for r in rows]

    def get(self, entry_id: int) -> HistoryEntry | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return self._to_entry(row) if row else None

    def set_favorite(self, entry_id: int, favorite: bool) -> bool:
        """Setel status favorit; False bila entri tidak ada."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE entries SET favorite = ? WHERE id = ?", (1 if favorite else 0, entry_id)
            )
            return cur.rowcount > 0

    def toggle_favorite(self, entry_id: int) -> bool | None:
        """Balik status favorit; kembalikan status baru, atau None bila entri tidak ada."""
        entry = self.get(entry_id)
        if entry is None:
            return None
        self.set_favorite(entry_id, not entry.favorite)
        return not entry.favorite

    def delete(self, entry_id: int) -> bool:
        with self._lock, self._conn:
            return self._conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,)).rowcount > 0

    def clear(self, *, keep_favorites: bool = True) -> int:
        """Hapus riwayat; favorit dipertahankan secara bawaan. Kembalikan jumlah terhapus."""
        sql = "DELETE FROM entries WHERE favorite = 0" if keep_favorites else "DELETE FROM entries"
        with self._lock, self._conn:
            return self._conn.execute(sql).rowcount

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0])

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._conn.close()
