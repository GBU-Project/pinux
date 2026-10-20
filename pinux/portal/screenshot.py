"""Klien D-Bus untuk org.freedesktop.portal.Screenshot (task 12).

Mengimplementasikan:
1. Pemeriksaan ketersediaan portal Screenshot (R6.5).
2. Pemanggilan ``org.freedesktop.portal.Screenshot.Screenshot`` dengan opsi
   ``interactive = False`` dan pemantauan sinyal ``Response``.
3. Pengambilan berkas citra PNG melalui URI ``file://`` dan pembersihan berkas sementara.
4. Cadangan bertahap bila portal menjawab "gagal" (kode 2): ulangi dengan
   ``interactive = True`` (agar dialog izin/pemilih bawaan desktop muncul),
   lalu coba alat CLI (grim, spectacle, gnome-screenshot, maim, scrot).

Kode respons portal: 0 = sukses, 1 = dibatalkan pengguna, 2 = gagal/ditolak
karena sebab lain (backend tidak ada, izin ditolak, app-id tidak dikenal).

Perujuk: R6.2, R6.5 pada requirements.md, serta design.md.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import urllib.parse
import uuid
from pathlib import Path
from typing import Final

import dbus
from pinux.portal.request import portal_request

__all__ = [
    "ScreenshotCancelled",
    "ScreenshotError",
    "ScreenshotFailed",
    "ScreenshotPortal",
]

logger = logging.getLogger("pinux.portal.screenshot")

PORTAL_BUS_NAME: Final[str] = "org.freedesktop.portal.Desktop"
PORTAL_OBJECT_PATH: Final[str] = "/org/freedesktop/portal/desktop"
SCREENSHOT_INTERFACE: Final[str] = "org.freedesktop.portal.Screenshot"
REQUEST_INTERFACE: Final[str] = "org.freedesktop.portal.Request"

# Waktu tunggu minimum untuk percobaan interaktif (pengguna perlu memilih/mengizinkan).
INTERACTIVE_TIMEOUT_S: Final[float] = 60.0
CLI_TIMEOUT_S: Final[float] = 15.0

_PORTAL_HINT: Final[str] = (
    "pastikan xdg-desktop-portal dan backend desktop Anda terpasang "
    "(xdg-desktop-portal-gnome / -kde / -wlr), jalankan Pinux lewat desktop file "
    "agar app-id dikenal, atau pasang alat tangkap layar seperti gnome-screenshot, "
    "grim, spectacle, maim, atau scrot"
)


class ScreenshotError(RuntimeError):
    """Galat dasar untuk tangkapan layar."""


class ScreenshotCancelled(ScreenshotError):
    """Pengguna membatalkan tangkapan layar (kode respons portal 1)."""


class ScreenshotFailed(ScreenshotError):
    """Portal gagal atau menolak (kode respons portal selain 0 dan 1)."""


def _cli_commands(path: str) -> list[list[str]]:
    """Daftar perintah CLI cadangan, berurutan menurut jenis sesi."""
    wayland = os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    grim = ["grim", path]
    spectacle = ["spectacle", "-b", "-n", "-f", "-o", path]
    gnome = ["gnome-screenshot", "-f", path]
    maim = ["maim", path]
    scrot = ["scrot", "-o", path]
    if wayland:
        return [grim, spectacle, gnome, maim, scrot]
    return [maim, scrot, gnome, spectacle, grim]


class ScreenshotPortal:
    """Klien protokol org.freedesktop.portal.Screenshot."""

    def __init__(self, bus: dbus.Bus | None = None) -> None:
        self._bus = bus

    def _get_bus(self) -> dbus.Bus:
        if self._bus is None:
            self._bus = dbus.SessionBus()
        return self._bus

    def is_available(self) -> bool:
        """Periksa apakah portal Screenshot tersedia pada bus sesi (R6.5)."""
        try:
            bus = self._get_bus()
            if not bus.name_has_owner(PORTAL_BUS_NAME):
                return False
            portal = bus.get_object(PORTAL_BUS_NAME, PORTAL_OBJECT_PATH)
            intf = dbus.Interface(portal, "org.freedesktop.DBus.Introspectable")
            xml = intf.Introspect()
            return SCREENSHOT_INTERFACE in xml
        except Exception as exc:
            logger.debug(f"Pemeriksaan portal Screenshot gagal: {exc}")
            return False

    def capture_fullscreen(
        self,
        parent_window: str = "",
        *,
        timeout_s: float = 15.0,
    ) -> bytes:
        """Lakukan tangkapan layar penuh dan kembalikan bytes citra PNG.

        Urutan percobaan:
        1. Portal tanpa dialog (``interactive=False``).
        2. Bila portal menjawab gagal (kode 2): portal dengan ``interactive=True``.
        3. Bila masih gagal atau portal tidak ada: alat CLI yang terpasang.

        Pembatalan pengguna (kode 1) langsung dilempar sebagai
        ``ScreenshotCancelled`` tanpa mencoba cadangan. ``TimeoutError`` dari
        percobaan pertama juga diteruskan apa adanya. Bila semua jalur gagal,
        dilempar ``ScreenshotFailed`` dengan petunjuk perbaikan.
        """
        failures: list[str] = []

        if self.is_available():
            try:
                return self._capture_via_portal(
                    parent_window, interactive=False, timeout_s=timeout_s
                )
            except ScreenshotFailed as exc:
                logger.warning(f"Portal Screenshot non-interaktif gagal: {exc}")
                failures.append(str(exc))

            try:
                return self._capture_via_portal(
                    parent_window,
                    interactive=True,
                    timeout_s=max(timeout_s, INTERACTIVE_TIMEOUT_S),
                )
            except ScreenshotFailed as exc:
                logger.warning(f"Portal Screenshot interaktif gagal: {exc}")
                failures.append(str(exc))
        else:
            failures.append("Portal Screenshot tidak tersedia pada sistem ini")

        data = self._capture_via_cli()
        if data is not None:
            return data

        detail = failures[-1] if failures else "tidak ada penyebab terekam"
        raise ScreenshotFailed(f"Tangkapan layar gagal: {detail}. Saran: {_PORTAL_HINT}.")

    def _capture_via_portal(
        self,
        parent_window: str,
        *,
        interactive: bool,
        timeout_s: float,
    ) -> bytes:
        bus = self._get_bus()
        portal = bus.get_object(PORTAL_BUS_NAME, PORTAL_OBJECT_PATH)
        iface = dbus.Interface(portal, SCREENSHOT_INTERFACE)

        token = "pinux_ss_" + uuid.uuid4().hex[:8]
        options = {
            "handle_token": dbus.String(token),
            "interactive": dbus.Boolean(interactive),
        }

        try:
            response_code, results_dict = portal_request(
                bus,
                lambda: iface.Screenshot(dbus.String(parent_window), options),
                token,
                timeout_s=timeout_s,
            )
        except TimeoutError as exc:
            raise TimeoutError(
                f"Tangkapan layar melebihi batas waktu {timeout_s} detik"
            ) from exc

        if response_code == 1:
            raise ScreenshotCancelled("Tangkapan layar dibatalkan pengguna")
        if response_code != 0:
            raise ScreenshotFailed(
                f"Portal screenshot gagal (kode: {response_code}); "
                "izin ditolak atau backend portal bermasalah"
            )

        uri = str(results_dict.get("uri", "")) if results_dict else ""
        if not uri:
            raise ScreenshotFailed("Portal tidak mengembalikan URI citra")

        # Parse URI file://
        parsed = urllib.parse.urlparse(uri)
        if parsed.scheme != "file":
            raise ScreenshotFailed(f"URI bukan file lokal: {uri}")

        file_path = Path(urllib.parse.unquote(parsed.path))
        if not file_path.exists():
            raise FileNotFoundError(f"Berkas citra hasil screenshot tidak ditemukan: {file_path}")

        try:
            return file_path.read_bytes()
        finally:
            # Bersihkan berkas sementara hasil screenshot sesuai spesifikasi
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _capture_via_cli(self) -> bytes | None:
        """Coba alat CLI yang terpasang; ``None`` bila semuanya gagal/tidak ada."""
        with tempfile.TemporaryDirectory(prefix="pinux_ss_") as tmp:
            out = os.path.join(tmp, "shot.png")
            for cmd in _cli_commands(out):
                if shutil.which(cmd[0]) is None:
                    continue
                try:
                    subprocess.run(
                        cmd,
                        check=True,
                        capture_output=True,
                        timeout=CLI_TIMEOUT_S,
                    )
                except (subprocess.SubprocessError, OSError) as exc:
                    logger.debug(f"Alat {cmd[0]} gagal: {exc}")
                    continue
                path = Path(out)
                if path.exists() and path.stat().st_size > 0:
                    logger.info(f"Tangkapan layar memakai cadangan CLI: {cmd[0]}")
                    return path.read_bytes()
        return None
