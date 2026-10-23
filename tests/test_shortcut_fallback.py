"""Uji pesan fallback CLI, perintah Flatpak, dan pintasan yang disetujui sebagian.

Logika dipisah dari UI (fungsi murni di ``pinux.portal.shortcuts``) agar dapat diuji
tanpa GTK.

Perujuk: R1.3 pada requirements.md.
"""

from __future__ import annotations

from pinux import APP_ID
from pinux.portal import shortcuts as sc
from pinux.portal.shortcuts import (
    BoundShortcut,
    ShortcutManager,
    ShortcutSpec,
    cli_command,
    describe_fallback,
)

SPECS = (
    ShortcutSpec("translate", "T", "<Control><Alt>T"),
    ShortcutSpec("ocr", "O", "<Control><Alt>O"),
)


class FakePortal:
    def __init__(self, *, available=True, bound=None, bind_error=None) -> None:
        self.available = available
        self.bound = bound or []
        self.bind_error = bind_error

    def is_available(self) -> bool:
        return self.available

    def connect_activated(self, callback) -> None:
        pass

    def bind(self, specs, parent_window: str = ""):
        if self.bind_error is not None:
            raise self.bind_error
        return list(self.bound)

    def close(self) -> None:
        pass


def _bound(*ids: str) -> list[BoundShortcut]:
    return [BoundShortcut(id=i, trigger="x", activation_token=i) for i in ids]


# --- Perintah CLI ---------------------------------------------------------------


def test_cli_command_plain() -> None:
    assert cli_command("--trigger", flatpak=False) == "pinux --trigger"
    assert cli_command("--pick-region", flatpak=False) == "pinux --pick-region"


def test_cli_command_flatpak_uses_app_id() -> None:
    assert cli_command("--trigger", flatpak=True) == f"flatpak run {APP_ID} --trigger"
    assert APP_ID == "io.github.gbu_project.Pinux"


def test_cli_command_autodetect_uses_is_flatpak(monkeypatch) -> None:
    monkeypatch.setattr(sc, "is_flatpak", lambda: True)
    assert cli_command("--trigger").startswith("flatpak run ")
    monkeypatch.setattr(sc, "is_flatpak", lambda: False)
    assert cli_command("--trigger") == "pinux --trigger"


def test_is_flatpak_detects_env_and_marker_file(monkeypatch) -> None:
    monkeypatch.setenv("FLATPAK_ID", APP_ID)
    assert sc.is_flatpak() is True

    monkeypatch.delenv("FLATPAK_ID")
    monkeypatch.setattr(sc.os.path, "exists", lambda p: p == "/.flatpak-info")
    assert sc.is_flatpak() is True

    monkeypatch.setattr(sc.os.path, "exists", lambda p: False)
    assert sc.is_flatpak() is False


def test_cli_flags_cover_default_specs() -> None:
    assert sc.CLI_FLAGS == {"translate": "--trigger", "ocr": "--pick-region"}


# --- Pesan fallback -------------------------------------------------------------


def test_describe_fallback_distinguishes_reasons() -> None:
    unavailable = describe_fallback(sc.REASON_PORTAL_UNAVAILABLE)
    failed = describe_fallback(sc.REASON_BIND_FAILED)
    assert "tidak tersedia" in unavailable
    assert "ditolak" in failed and "tidak tersedia" not in failed
    assert unavailable != failed


def test_describe_fallback_unknown_reason_is_generic() -> None:
    # Termasuk objek bukan-str (mis. MagicMock pada tes UI) tidak boleh melempar galat.
    for reason in (None, "aneh", object()):
        text = describe_fallback(reason)
        assert text.startswith("Pintasan global belum aktif")
        assert "tidak tersedia" not in text


# --- last_reason & missing_shortcuts pada manajer -------------------------------


def test_last_reason_portal_unavailable() -> None:
    manager = ShortcutManager(portal=FakePortal(available=False), specs=SPECS)
    assert manager.last_reason is None
    manager.start()
    assert manager.last_reason == sc.REASON_PORTAL_UNAVAILABLE


def test_last_reason_bind_failed_for_empty_and_error() -> None:
    m1 = ShortcutManager(portal=FakePortal(bound=[]), specs=SPECS)
    m1.start()
    assert m1.last_reason == sc.REASON_BIND_FAILED

    m2 = ShortcutManager(portal=FakePortal(bind_error=TimeoutError("lama")), specs=SPECS)
    m2.start()
    assert m2.last_reason == sc.REASON_BIND_FAILED


def test_last_reason_cleared_on_success_and_retry() -> None:
    portal = FakePortal(bind_error=RuntimeError("ditolak"))
    manager = ShortcutManager(portal=portal, specs=SPECS)
    manager.start()
    assert manager.last_reason == sc.REASON_BIND_FAILED

    portal.bind_error = None
    portal.bound = _bound("translate", "ocr")
    assert manager.start() == "portal"
    assert manager.last_reason is None

    manager.stop()
    assert manager.last_reason is None


def test_missing_shortcuts_reports_partial_approval() -> None:
    manager = ShortcutManager(portal=FakePortal(bound=_bound("translate")), specs=SPECS)
    assert manager.start() == "portal"
    assert manager.missing_shortcuts == ("ocr",)


def test_missing_shortcuts_all_when_cli_and_none_when_full() -> None:
    cli = ShortcutManager(portal=FakePortal(available=False), specs=SPECS)
    cli.start()
    assert cli.missing_shortcuts == ("translate", "ocr")

    full = ShortcutManager(portal=FakePortal(bound=_bound("translate", "ocr")), specs=SPECS)
    full.start()
    assert full.missing_shortcuts == ()
