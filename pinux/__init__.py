"""Pinux, aplikasi penerjemah desktop GTK4 untuk Linux."""

from __future__ import annotations

__all__ = ["APP_ID", "__version__"]

__version__ = "1.1.0"

# Harus sama dengan app-id Flatpak, nama desktop file, dan metainfo; sandbox Flatpak
# hanya mengizinkan memiliki nama bus yang diawali ID ini.
APP_ID = "io.github.gbu_project.Pinux"
