"""Subpaket antarmuka pengguna GTK4/libadwaita.

Jendela yang disediakan:

- :mod:`pinux.ui.popup` untuk Popup_Window, lihat task 15.
- :mod:`pinux.ui.region` untuk Region_Overlay, lihat task 16.
- :mod:`pinux.ui.settings` untuk jendela pengaturan, lihat task 18.

Perujuk: R5.1, R6.1, R9.4 pada requirements.md.
"""

from pinux.ui.popup import PopupWindow
from pinux.ui.region import Rect, RegionOverlay, crop_image_region
from pinux.ui.settings import SettingsWindow

__all__ = [
    "PopupWindow",
    "Rect",
    "RegionOverlay",
    "SettingsWindow",
    "crop_image_region",
]
