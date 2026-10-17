"""Penangkapan teks dari Clipboard dan Primary Selection desktop.

Mendukung deteksi sesi Wayland vs X11:
- Wayland: Menggunakan Gdk.Clipboard (default display).
- X11: Menggunakan Gdk.Clipboard dan Gdk.Display.get_primary_clipboard();
  Primary Selection diprioritaskan bila isinya berbeda dari Clipboard biasa.

Mendukung pemotongan teks pada ``max_chars`` dengan penandaan ``truncated``
(R2.5 / Properti 5), pemantauan sinyal perubahan isi (R2.3), serta abstraksi
penyedia clipboard agar dapat diuji tanpa sesi grafis.

Perujuk: R2.1, R2.2, R2.3, R2.5, R5.4 pada requirements.md, serta design.md.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Callable
from typing import Final, Literal, Protocol, runtime_checkable

from pinux.capture.base import CaptureOrigin, CaptureResult

__all__ = [
    "ClipboardBackend",
    "DesktopSessionType",
    "TextCapturer",
    "clean_text",
    "detect_desktop_session",
    "truncate_text",
]

DesktopSessionType = Literal["wayland", "x11"]


def _run_clipboard_tool(cmd: list[str], timeout_s: float = 0.5) -> str:
    """Jalankan alat bantu baris perintah clipboard eksternal (misal wl-paste)."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", errors="replace")


def detect_desktop_session() -> DesktopSessionType:
    """Deteksi jenis Desktop_Session yang sedang berjalan ('wayland' atau 'x11')."""
    xdg_session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if "wayland" in xdg_session:
        return "wayland"
    if "x11" in xdg_session:
        return "x11"

    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"

    # Default fallback aman
    return "wayland"


_CJK = re.compile(
    "[\u2e80-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uff00-\uffef]"
)


def _join_wrapped_lines(lines: list[str]) -> str:
    """Gabungkan baris; spasi hanya disisipkan bila bukan sambungan aksara CJK."""
    out = ""
    for line in lines:
        if out and not (_CJK.match(out[-1]) and _CJK.match(line[0])):
            out += " "
        out += line
    return out


def clean_text(
    text: str,
    *,
    unwrap_lines: bool = False,
    remove_hyphens: bool = False,
    remove_comments: bool = False,
) -> str:
    """Bersihkan teks sumber menurut konfigurasi pemrosesan teks ala Bob.

    - unwrap_lines: gabungkan baris terputus menjadi satu spasi (teks dari PDF/OCR).
    - remove_hyphens: hapus pemisahan kata akibat pergantian baris ('con-\\nnection' -> 'connection').
    - remove_comments: bersihkan penanda komentar baris seperti '#', '//', '/* */'.
    """
    if not text:
        return ""

    # Samakan akhir baris (teks dari Windows/PDF memakai \r\n) agar pemisah
    # paragraf "\n\n" dan pola tanda hubung terdeteksi benar.
    result = text.replace("\r\n", "\n").replace("\r", "\n")

    # 1. Hapus simbol komentar kode pemrograman lebih dulu agar tidak menghalangi deteksi kata/baris
    if remove_comments:
        lines = result.splitlines()
        cleaned_lines = []
        for line in lines:
            # Hapus komentar // dan #
            l = re.sub(r"^\s*(//|#)\s*", "", line)
            # Hapus komentar /* dan */
            l = re.sub(r"^\s*/\*\s*", "", l)
            l = re.sub(r"\s*\*/\s*$", "", l)
            cleaned_lines.append(l)
        result = "\n".join(cleaned_lines)

    # 2. Hapus tanda hubung pergantian baris
    if remove_hyphens:
        result = re.sub(r"(\w+)-\s*\n\s*(\w+)", r"\1\2", result)

    # 3. Gabungkan baris (unwrap newlines)
    if unwrap_lines:
        # Gabungkan baris tunggal, tetapi pertahankan pemisah paragraf ganda (\n\n)
        paragraphs = result.split("\n\n")
        cleaned_paragraphs = []
        for p in paragraphs:
            cleaned = _join_wrapped_lines([ln.strip() for ln in p.splitlines() if ln.strip()])
            if cleaned:
                cleaned_paragraphs.append(cleaned)
        result = "\n\n".join(cleaned_paragraphs)

    return result.strip()


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    """Potong teks jika melebihi ``max_chars``.

    Mengembalikan tuple ``(teks_hasil, apakah_terpotong)``.
    Properti 5: len(text) <= max_chars dan truncated == True iff pemotongan terjadi.
    """
    if max_chars <= 0:
        return "", bool(text)
    if len(text) > max_chars:
        return text[:max_chars], True
    return text, False


@runtime_checkable
class ClipboardBackend(Protocol):
    """Abstraksi akses clipboard untuk memisahkan GDK dari pengujian."""

    def read_clipboard_text(self) -> str:
        """Baca teks dari clipboard standar."""
        ...

    def read_primary_text(self) -> str:
        """Baca teks dari primary selection (khusus X11)."""
        ...

    def write_clipboard_text(self, text: str) -> None:
        """Tulis teks ke clipboard standar."""
        ...

    def connect_clipboard_changed(self, callback: Callable[[], None]) -> None:
        """Daftarkan callback saat isi clipboard berubah."""
        ...

    def connect_primary_changed(self, callback: Callable[[], None]) -> None:
        """Daftarkan callback saat isi primary selection berubah."""
        ...


class GdkClipboardBackend:
    """Implementasi ClipboardBackend menggunakan GDK4."""

    def __init__(self) -> None:
        import gi
        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk

        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("Gdk.Display default tidak tersedia")

        self._display = display
        self._clipboard = display.get_clipboard()
        self._primary = display.get_primary_clipboard()

    def read_clipboard_text(self) -> str:
        return self._read_text(self._clipboard)

    def read_primary_text(self) -> str:
        # Pada Wayland, klien tanpa fokus tidak menerima isi seleksi primer
        # dari GDK; ``wl-paste`` (wl-clipboard) menanganinya bila terpasang.
        if detect_desktop_session() == "wayland":
            text = _run_clipboard_tool(["wl-paste", "--primary", "--no-newline"])
            if text:
                return text
        return self._read_text(self._primary)

    @staticmethod
    def _read_text(clipboard: object, timeout_ms: int = 1000) -> str:
        """Baca teks dari ``Gdk.Clipboard`` secara sinkron.

        GDK4 hanya menyediakan ``read_text_async``. Konteks utama GLib diputar
        sementara hingga hasil tiba atau ``timeout_ms`` habis, sehingga harus
        dipanggil dari thread utama.
        """
        if clipboard is None:
            return ""
        from gi.repository import GLib

        context = GLib.MainContext.default()
        state: dict[str, object] = {"done": False, "text": ""}

        def _on_ready(source: object, result: object) -> None:
            try:
                state["text"] = source.read_text_finish(result) or ""
            except Exception:
                state["text"] = ""
            state["done"] = True

        deadline = GLib.get_monotonic_time() + timeout_ms * 1000
        clipboard.read_text_async(None, _on_ready)
        while not state["done"] and GLib.get_monotonic_time() < deadline:
            context.iteration(False)
            if not state["done"]:
                GLib.usleep(2000)
        return str(state["text"])

    def write_clipboard_text(self, text: str) -> None:
        if self._clipboard is not None:
            self._clipboard.set(text)

    def connect_clipboard_changed(self, callback: Callable[[], None]) -> None:
        if self._clipboard is not None:
            self._clipboard.connect("changed", lambda *_: callback())

    def connect_primary_changed(self, callback: Callable[[], None]) -> None:
        if self._primary is not None:
            self._primary.connect("changed", lambda *_: callback())


class TextCapturer:
    """Pengelola penangkapan teks dari Clipboard dan Primary Selection."""

    def __init__(
        self,
        backend: ClipboardBackend | None = None,
        session_type: DesktopSessionType | None = None,
    ) -> None:
        self._session_type: DesktopSessionType = (
            session_type if session_type is not None else detect_desktop_session()
        )
        self._backend = backend
        self._callbacks: list[Callable[[CaptureResult], None]] = []

        # Waktu perubahan terakhir tiap sumber, dipakai untuk memilih antara
        # seleksi (primary) dan clipboard: yang terbaru dianggap yang dimaksud.
        self._changed_at: dict[str, float] = {"clipboard": 0.0, "primary": 0.0}

        if self._backend is not None:
            self._backend.connect_clipboard_changed(
                lambda: self._on_source_changed("clipboard")
            )
            self._backend.connect_primary_changed(
                lambda: self._on_source_changed("primary")
            )

    @property
    def session_type(self) -> DesktopSessionType:
        """Jenis Desktop_Session saat ini ('wayland' atau 'x11')."""
        return self._session_type

    def connect_changed(self, callback: Callable[[CaptureResult], None]) -> None:
        """Daftarkan callback untuk perubahan teks clipboard."""
        self._callbacks.append(callback)

    def _on_source_changed(self, source: str) -> None:
        self._changed_at[source] = time.monotonic()
        if not self._callbacks:
            return  # hindari membaca clipboard bila tak ada pelanggan
        self._on_clipboard_changed()

    def _on_clipboard_changed(self) -> None:
        res = self.read_source_text()
        for cb in list(self._callbacks):
            try:
                cb(res)
            except Exception:
                pass

    def read_source_text(self, *, max_chars: int = 5000) -> CaptureResult:
        """Baca teks sumber aktif menurut Desktop_Session dan potong ke max_chars."""
        if self._backend is None:
            return CaptureResult(text="", truncated=False, origin="clipboard")

        clipboard_text = self._backend.read_clipboard_text() or ""
        primary_text = self._backend.read_primary_text() or ""

        # Terjemah seleksi ala Bob: teks yang baru disorot didahulukan. Bila
        # clipboard diubah lebih baru daripada seleksi (mis. Ctrl+C), clipboard
        # yang dipakai. Tanpa riwayat perubahan, seleksi didahulukan (R2.2).
        # Primary selection hanya ada di X11 (R2.2); di Wayland origin "primary" tidak sah.
        use_primary = (
            bool(primary_text)
            and primary_text != clipboard_text
            and self._session_type == "x11"
        )
        if use_primary and self._changed_at["clipboard"] > self._changed_at["primary"]:
            use_primary = False

        if use_primary:
            final_text, truncated = truncate_text(primary_text, max_chars)
            return CaptureResult(text=final_text, truncated=truncated, origin="primary")

        final_text, truncated = truncate_text(clipboard_text, max_chars)
        return CaptureResult(text=final_text, truncated=truncated, origin="clipboard")

    def send_to_clipboard(self, text: str) -> None:
        """Kirim teks ke clipboard (aksi salin)."""
        if self._backend is not None:
            self._backend.write_clipboard_text(text)
