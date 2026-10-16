"""Klien D-Bus untuk org.freedesktop.portal.Screenshot (task 12).

Mengimplementasikan:
1. Pemeriksaan ketersediaan portal Screenshot (R6.5).
2. Pemanggilan ``org.freedesktop.portal.Screenshot.Screenshot`` dengan opsi
   ``interactive = False`` dan pemantauan sinyal ``Response``.
3. Pengambilan berkas citra PNG melalui URI ``file://`` dan pembersihan berkas sementara.

Perujuk: R6.2, R6.5 pada requirements.md, serta design.md.
"""

from __future__ import annotations

import logging
import os
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Final

import dbus
from pinux.portal.request import portal_request

__all__ = ["ScreenshotPortal"]

logger = logging.getLogger("pinux.portal.screenshot")

PORTAL_BUS_NAME: Final[str] = "org.freedesktop.portal.Desktop"
PORTAL_OBJECT_PATH: Final[str] = "/org/freedesktop/portal/desktop"
SCREENSHOT_INTERFACE: Final[str] = "org.freedesktop.portal.Screenshot"
REQUEST_INTERFACE: Final[str] = "org.freedesktop.portal.Request"


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
        """Lakukan tangkapan layar penuh tanpa dialog interaktif (R6.2).

        Mengembalikan bytes citra PNG. Membersihkan berkas sementara hasil tangkapan.
        Memunculkan RuntimeError jika portal tidak tersedia atau ditolak pengguna.
        """
        if not self.is_available():
            raise RuntimeError("Portal Screenshot tidak tersedia pada sistem ini")

        bus = self._get_bus()
        portal = bus.get_object(PORTAL_BUS_NAME, PORTAL_OBJECT_PATH)
        iface = dbus.Interface(portal, SCREENSHOT_INTERFACE)

        token = "pinux_ss_" + uuid.uuid4().hex[:8]
        options = {
            "handle_token": dbus.String(token),
            "interactive": dbus.Boolean(False),
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

        if response_code != 0:
            raise RuntimeError(f"Tangkapan layar ditolak pengguna atau gagal (kode: {response_code})")

        uri = str(results_dict.get("uri", "")) if results_dict else ""
        if not uri:
            raise RuntimeError("Portal tidak mengembalikan URI citra")

        # Parse URI file://
        parsed = urllib.parse.urlparse(uri)
        if parsed.scheme != "file":
            raise RuntimeError(f"URI bukan file lokal: {uri}")

        file_path = Path(urllib.parse.unquote(parsed.path))
        if not file_path.exists():
            raise FileNotFoundError(f"Berkas citra hasil screenshot tidak ditemukan: {file_path}")

        try:
            image_bytes = file_path.read_bytes()
        finally:
            # Bersihkan berkas sementara hasil screenshot sesuai spesifikasi
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                pass

        return image_bytes
