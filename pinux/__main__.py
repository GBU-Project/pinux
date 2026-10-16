"""Titik masuk baris perintah ``pinux`` (task 19).

Menjalankan :class:`pinux.app.PinuxApp` dan meneruskan argumen CLI.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from pinux.app import PinuxApp


def main(argv: Sequence[str] | None = None) -> int:
    """Jalankan aplikasi Pinux dan kembalikan kode keluar."""
    if argv is None:
        argv = sys.argv[1:]

    try:
        from gi.repository import GLib
        GLib.set_prgname("pinux")
        GLib.set_application_name("Pinux")
    except Exception:
        pass

    try:
        import dbus.mainloop.glib
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    except Exception:
        pass

    app = PinuxApp()
    # Adw.Application.run menerima list of strings termasuk nama program di posisi 0
    cmd_args = [sys.argv[0]] + list(argv)
    return int(app.run(cmd_args))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
