"""Halaman Pintasan memperbarui diri saat ShortcutManager berubah (Medium 4).

Jendela pengaturan dibuat sekali lalu hanya disembunyikan, sedangkan pengikatan portal
berjalan setelah startup dan bisa berakhir kapan saja. Tes memakai ``SettingsWindow``
dan ``ShortcutManager`` asli dengan portal palsu, dan membaca tampilan lewat API publik
widget (judul grup, baris) agar gagal secara perilaku pada kode lama.

Memerlukan display (nyata atau Xvfb), seperti ``test_settings_ui.py``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

import pytest

from pinux.configstore import ConfigStore
from pinux.credentials import CredentialStore
from pinux.portal import shortcuts as sc
from pinux.portal.shortcuts import BoundShortcut, ShortcutManager, ShortcutSpec
from pinux.translate.registry import ProviderRegistry
from pinux.ui.settings import SettingsWindow

SPECS = (
    ShortcutSpec("translate", "T", "<Control><Alt>T"),
    ShortcutSpec("ocr", "O", "<Control><Alt>O"),
)
PORTAL_TITLE = "Pintasan Keyboard Global (Portal XDG)"
CLI_TITLE = "Pintasan Keyboard Manual (CLI Mode)"


@pytest.fixture(scope="module", autouse=True)
def init_adw() -> None:
    Adw.init()


class FakePortal:
    """Portal palsu: hasil bind ditentukan tes; callback disimpan agar bisa dipicu."""

    def __init__(self, bound: list[BoundShortcut] | None = None, available: bool = True) -> None:
        self.bound = bound if bound is not None else []
        self.available = available
        self.closed_cb = None
        self.changed_cb = None

    def is_available(self) -> bool:
        return self.available

    def connect_activated(self, cb) -> None:
        pass

    def connect_closed(self, cb) -> None:
        self.closed_cb = cb

    def connect_shortcuts_changed(self, cb) -> None:
        self.changed_cb = cb

    def bind(self, specs, parent_window: str = ""):
        return list(self.bound)

    def close(self) -> None:
        pass


def _bound(*pairs: tuple[str, str]) -> list[BoundShortcut]:
    return [BoundShortcut(id=i, trigger=t, activation_token=i) for i, t in pairs]


def _pump(ms: int = 300) -> None:
    ctx = GLib.MainContext.default()
    end = GLib.get_monotonic_time() + ms * 1000
    while GLib.get_monotonic_time() < end:
        while ctx.pending():
            ctx.iteration(False)
        GLib.usleep(5000)


def _walk(widget: Gtk.Widget) -> Iterator[Gtk.Widget]:
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from _walk(child)
        child = child.get_next_sibling()


def _make_window(tmp_path: Path, manager: ShortcutManager) -> SettingsWindow:
    cred = CredentialStore(tmp_path / "creds.toml", force_fallback=True)
    ocr = MagicMock()
    ocr.is_available.return_value = False
    return SettingsWindow(
        config_store=ConfigStore(tmp_path / "pinux.toml"),
        credential_store=cred,
        provider_registry=ProviderRegistry(credential_store=cred),
        shortcut_manager=manager,
        ocr_client=ocr,
        session_type="wayland",
    )


def _group(win: SettingsWindow) -> Adw.PreferencesGroup:
    groups = [
        w for w in _walk(win)
        if isinstance(w, Adw.PreferencesGroup) and (w.get_title() or "").startswith("Pintasan Keyboard")
    ]
    assert len(groups) == 1
    return groups[0]


def _rows(win: SettingsWindow) -> list[Adw.ActionRow]:
    return [w for w in _walk(_group(win)) if isinstance(w, Adw.ActionRow)]


def _row_texts(win: SettingsWindow) -> list[tuple[str, str]]:
    return [(r.get_title() or "", r.get_subtitle() or "") for r in _rows(win)]


@pytest.fixture
def setup(tmp_path: Path):
    portal = FakePortal(_bound(("translate", "Ctrl+Alt+T"), ("ocr", "Ctrl+Alt+O")))
    manager = ShortcutManager(portal=portal, specs=SPECS)
    win = _make_window(tmp_path, manager)
    yield win, manager, portal
    win.destroy()


def test_page_updates_when_portal_binds_after_window_is_built(setup) -> None:
    win, manager, _portal = setup
    assert _group(win).get_title() == CLI_TITLE  # dibuka sebelum start() selesai

    assert manager.start() == "portal"
    _pump()

    assert _group(win).get_title() == PORTAL_TITLE
    subtitles = [sub for _title, sub in _row_texts(win)]
    assert "Pemicu: Ctrl+Alt+T" in subtitles and "Pemicu: Ctrl+Alt+O" in subtitles


def test_page_falls_back_to_cli_when_session_closes(setup) -> None:
    win, manager, portal = setup
    manager.start()
    _pump()
    assert _group(win).get_title() == PORTAL_TITLE

    portal.closed_cb(sc.REASON_PORTAL_STOPPED)
    _pump()

    group = _group(win)
    assert group.get_title() == CLI_TITLE
    assert "Mulai ulang Pinux" in (group.get_description() or "")
    commands = [sub for _t, sub in _row_texts(win)]
    assert any("--trigger" in c for c in commands) and any("--pick-region" in c for c in commands)


def test_page_shows_new_trigger_after_system_change(setup) -> None:
    win, manager, portal = setup
    manager.start()
    _pump()

    portal.changed_cb(_bound(("translate", "Ctrl+Shift+T")))
    _pump()

    subtitles = [sub for _t, sub in _row_texts(win)]
    assert "Pemicu: Ctrl+Shift+T" in subtitles
    assert "Pemicu: Ctrl+Alt+T" not in subtitles


def test_partial_approval_shows_cli_command_for_missing(tmp_path: Path) -> None:
    portal = FakePortal(_bound(("translate", "Ctrl+Alt+T")))
    manager = ShortcutManager(portal=portal, specs=SPECS)
    win = _make_window(tmp_path, manager)
    try:
        manager.start()
        _pump()
        titles = [t for t, _s in _row_texts(win)]
        assert any("(tidak disetujui)" in t for t in titles)
    finally:
        win.destroy()


def test_refresh_replaces_rows_instead_of_accumulating(setup) -> None:
    win, manager, portal = setup
    manager.start()
    _pump()
    baseline = len(_rows(win))

    for trigger in ("Ctrl+1", "Ctrl+2", "Ctrl+3"):
        portal.changed_cb(_bound(("translate", trigger)))
        _pump()

    assert len(_rows(win)) == baseline, "baris lama harus dibuang, bukan menumpuk"


def test_destroyed_window_is_disconnected_and_ignores_late_changes(tmp_path: Path) -> None:
    portal = FakePortal(_bound(("translate", "Ctrl+Alt+T"), ("ocr", "Ctrl+Alt+O")))
    manager = ShortcutManager(portal=portal, specs=SPECS)
    win = _make_window(tmp_path, manager)
    win.destroy()

    manager.start()  # memberi tahu: tidak boleh menyentuh jendela yang sudah dihancurkan
    _pump()

    assert manager._changed_callbacks == []
    assert win._refresh_shortcuts_page() is False  # tidak melempar dan tidak memperbarui


def test_weak_listener_does_not_keep_window_alive_and_unregisters_itself() -> None:
    import gc

    from pinux.ui.settings import _weak_listener

    class Dummy:
        def __init__(self) -> None:
            self.calls = 0

        def _on_shortcuts_changed(self) -> None:
            self.calls += 1

    manager = MagicMock()
    target = Dummy()
    listener = _weak_listener(target, manager)

    listener()
    assert target.calls == 1
    manager.disconnect_changed.assert_not_called()

    del target
    gc.collect()
    listener()  # target sudah hilang: melepas dirinya dari manajer
    manager.disconnect_changed.assert_called_once_with(listener)


# --- Patch 0007: refresh terkumpul, halaman bernama, status menunggu -------------------


def test_burst_of_changes_rebuilds_the_page_only_once(setup) -> None:
    win, manager, _portal = setup
    manager.start()
    _pump()

    fills: list[int] = []
    original = win._fill_shortcuts_group
    win._fill_shortcuts_group = lambda: (fills.append(1), original())[1]

    for _ in range(10):
        win._on_shortcuts_changed()
    _pump()

    assert fills == [1], "sepuluh pemberitahuan beruntun hanya boleh menyusun ulang sekali"

    win._on_shortcuts_changed()  # penjadwalan berikutnya tetap bekerja
    _pump()
    assert fills == [1, 1]


def test_show_page_opens_the_shortcuts_page(setup) -> None:
    win, _manager, _portal = setup
    assert win.get_visible_page_name() != "shortcuts"

    win.show_page("shortcuts")

    assert win.get_visible_page_name() == "shortcuts"


def test_show_page_ignores_unknown_page(setup) -> None:
    win, _manager, _portal = setup
    win.show_page("tidak-ada")  # tidak boleh melempar


class PumpingPortal(FakePortal):
    """Portal yang memutar main loop di dalam bind(), seperti menunggu dialog desktop."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.win: SettingsWindow | None = None
        self.seen: tuple[str, str] | None = None

    def bind(self, specs, parent_window: str = ""):
        _pump(300)  # UI tetap diproses selama menunggu
        group = self.win._shortcuts_group  # judul status menunggu tak berawalan "Pintasan Keyboard"
        self.seen = (group.get_title() or "", group.get_description() or "")
        return super().bind(specs, parent_window)


def test_page_shows_waiting_state_while_bind_is_blocked(tmp_path: Path) -> None:
    portal = PumpingPortal(_bound(("translate", "Ctrl+Alt+T"), ("ocr", "Ctrl+Alt+O")))
    manager = ShortcutManager(portal=portal, specs=SPECS)
    win = _make_window(tmp_path, manager)
    portal.win = win
    try:
        manager.start()
        _pump()

        title, description = portal.seen
        assert title == "Menunggu Persetujuan Desktop…"
        assert description.startswith("Menunggu")
        assert _group(win).get_title() == PORTAL_TITLE, "setelah bind selesai halaman menampilkan portal"
    finally:
        win.destroy()


class BlockingPortal(FakePortal):
    """Portal yang ``bind``-nya menahan diri sampai tes melepasnya.

    Berbeda dari :class:`PumpingPortal` (yang memutar main loop di dalam ``bind``
    pada thread utama, sah hanya untuk jalur sinkron ``start()``), ``bind`` di sini
    berjalan pada worker thread milik ``start_async()``. Karena itu ia tidak boleh
    menyentuh GTK sama sekali: ia hanya memberi sinyal "sudah masuk" dan menunggu
    pelepasan.
    """

    def __init__(self, bound=None, available: bool = True) -> None:
        super().__init__(bound, available)
        self.entered = threading.Event()
        self.release = threading.Event()

    def bind(self, specs, parent_window: str = ""):
        self.entered.set()
        self.release.wait(5)
        return super().bind(specs, parent_window)


def test_pending_state_is_shown_while_bind_runs_async(tmp_path: Path) -> None:
    """Jalur yang dipakai produksi: ``start_async()`` dengan portal yang menunggu.

    ``PumpingPortal`` menguji jalur sinkron ``start()``; tes ini menutup celah
    jalur asinkron yang sebenarnya dipakai ``PinuxApp`` dan ``SettingsWindow``.
    """
    portal = BlockingPortal(_bound(("translate", "Ctrl+Alt+T"), ("ocr", "Ctrl+Alt+O")))
    manager = ShortcutManager(portal=portal, specs=SPECS)
    win = _make_window(tmp_path, manager)
    done: list[str] = []
    try:
        assert manager.start_async(done.append) is True
        assert portal.entered.wait(2), "bind harus berjalan di pekerja latar"

        # start_async() tidak menunggu: callback belum dipanggil, UI sudah "menunggu".
        assert done == []
        _pump()
        # Judul status menunggu tidak berawalan "Pintasan Keyboard", jadi _group()
        # belum bisa dipakai di sini (lihat juga test_page_shows_waiting_state_while_bind_is_blocked).
        assert win._shortcuts_group.get_title() == "Menunggu Persetujuan Desktop…"
        assert manager.active_backend != "portal"
        assert manager.last_reason == sc.REASON_PENDING

        portal.release.set()
        deadline = time.monotonic() + 3
        while not done and time.monotonic() < deadline:
            _pump(50)

        assert done == ["portal"], "on_done dipanggil sekali dengan hasil akhir"
        assert manager.active_backend == "portal"
        assert manager.last_reason is None
        assert _group(win).get_title() == PORTAL_TITLE
    finally:
        portal.release.set()
        win.destroy()


def test_page_returns_from_waiting_to_cli_when_bind_is_rejected(tmp_path: Path) -> None:
    portal = PumpingPortal(bound=[])
    manager = ShortcutManager(portal=portal, specs=SPECS)
    win = _make_window(tmp_path, manager)
    portal.win = win
    try:
        manager.start()
        _pump()
        assert portal.seen[0] == "Menunggu Persetujuan Desktop…"
        assert _group(win).get_title() == CLI_TITLE
        assert "ditolak" in (_group(win).get_description() or "")
    finally:
        win.destroy()


# --- Patch 0009: tombol "Coba Ikat Ulang" -----------------------------------------------


def _retry_buttons(win: SettingsWindow) -> list[Gtk.Button]:
    return [
        w for w in _walk(win._shortcuts_group)  # judul status menunggu tak berawalan "Pintasan Keyboard"
        if isinstance(w, Gtk.Button) and w.get_label() == "Coba Lagi"
    ]


def _wait(cond, timeout_s: float = 3.0) -> bool:
    ctx = GLib.MainContext.default()
    end = GLib.get_monotonic_time() + int(timeout_s * 1_000_000)
    while GLib.get_monotonic_time() < end:
        while ctx.pending():
            ctx.iteration(False)
        if cond():
            return True
        GLib.usleep(2000)
    return cond()


def test_retry_button_shown_in_cli_mode_only(setup) -> None:
    win, manager, _portal = setup
    assert len(_retry_buttons(win)) == 1  # belum dimulai: mode CLI

    manager.start()
    _pump()
    assert _retry_buttons(win) == [], "pada mode portal tombol tidak ada"


def test_retry_button_hidden_while_pending(tmp_path: Path) -> None:
    portal = FakePortal(_bound(("translate", "Ctrl+Alt+T"), ("ocr", "Ctrl+Alt+O")))
    manager = ShortcutManager(portal=portal, specs=SPECS)
    win = _make_window(tmp_path, manager)
    seen: list[int] = []

    def bind(specs, parent_window: str = ""):
        _pump(200)  # UI memproses pemberitahuan "menunggu"
        seen.append(len(_retry_buttons(win)))
        return _bound(("translate", "Ctrl+Alt+T"), ("ocr", "Ctrl+Alt+O"))

    portal.bind = bind
    try:
        manager.start()
        assert seen == [0], "selama menunggu persetujuan tombol tidak boleh tampil"
    finally:
        win.destroy()


def test_retry_after_rejection_binds_without_blocking(tmp_path: Path) -> None:
    portal = FakePortal(bound=[])  # pertama ditolak
    manager = ShortcutManager(portal=portal, specs=SPECS)
    win = _make_window(tmp_path, manager)
    try:
        manager.start()
        _pump()
        assert _group(win).get_title() == CLI_TITLE
        buttons = _retry_buttons(win)
        assert len(buttons) == 1

        portal.bound = _bound(("translate", "Ctrl+Alt+T"), ("ocr", "Ctrl+Alt+O"))  # kini disetujui
        buttons[0].emit("clicked")

        assert _wait(lambda: _group(win).get_title() == PORTAL_TITLE)
        assert manager.active_backend == "portal"
        assert _retry_buttons(win) == []
    finally:
        win.destroy()


def test_retry_after_session_loss_rebinds(setup) -> None:
    win, manager, portal = setup
    manager.start()
    _pump()
    portal.closed_cb(sc.REASON_PORTAL_STOPPED)
    _pump()
    buttons = _retry_buttons(win)
    assert len(buttons) == 1

    buttons[0].emit("clicked")

    assert _wait(lambda: _group(win).get_title() == PORTAL_TITLE)


def test_retry_button_reenabled_when_start_is_refused(setup) -> None:
    win, manager, _portal = setup
    button = _retry_buttons(win)[0]
    manager.start_async = MagicMock(return_value=False)  # mis. pengikatan lain sedang berjalan

    button.emit("clicked")

    assert button.get_sensitive() is True
    manager.start_async.assert_called_once()


def test_retry_button_reenabled_when_start_raises(setup) -> None:
    win, manager, _portal = setup
    button = _retry_buttons(win)[0]
    manager.start_async = MagicMock(side_effect=RuntimeError("rusak"))

    button.emit("clicked")  # tidak boleh melempar

    assert button.get_sensitive() is True
