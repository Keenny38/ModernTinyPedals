"""Preset management: create, duplicate, rename, restore backup, transfer settings (Presets page panels)"""

import json
import os
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from neopedal.setting import cfg


class Host:
    """Presets page host: questions answered yes, warnings recorded"""

    def __init__(self):
        self.warnings = []

    def confirm_operation(self, title="Confirm", message=""):
        return True

    def warn(self, text):
        self.warnings.append(text)

    def delete_preset(self, preset_filename):
        return False

    def undo_delete(self, entry=None):
        return False

    def export_package(self, preset_filename):
        pass

    def import_package(self):
        pass

    def open_page(self, name):
        pass


@pytest.fixture
def presets(ui_env, monkeypatch):
    """Settings folder with presets a & b, toasts of the page recorded"""
    from neopedal.ui.quick.preset_backend import PresetBackend

    folder = cfg.path.settings
    for name in ("a", "b"):
        with open(f"{folder}{name}.json", "w", encoding="utf-8") as file:
            json.dump({"speedometer": {"enable": True, "font_size": 15}}, file)
    os.utime(f"{folder}default.json", (1, 1))  # oldest: b first in destinations (newest first), whatever the clock
    backend = PresetBackend(None, Host())
    backend.toasts = []
    backend.toastShown.connect(lambda text, error, undo: backend.toasts.append((text, error)))
    backend.set_active(True)
    yield backend
    backend.release()
    backend.deleteLater()
    flush()


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def wait(busy, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while busy() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    QCoreApplication.processEvents()
    assert not busy()


def create(mode: str = "", source: str = "", name: str = "") -> str:
    from neopedal.ui.preset_management import apply_preset_name

    return apply_preset_name(name, mode, source)


def exists(name: str) -> bool:
    return os.path.exists(f"{cfg.path.settings}{name}")


def test_create_preset_checks_name(presets):
    assert create(name="") == "Invalid preset name."
    assert create(name="A") == "Preset already exists."  # same name as a.json, any case
    assert create(name="new") == ""
    assert exists("new.json")


def test_duplicate_and_rename_preset(presets):
    assert create(mode="duplicate", source="a.json", name="copy") == ""
    assert exists("copy.json") and exists("a.json")
    assert create(mode="rename", source="b.json", name="renamed") == ""
    assert exists("renamed.json") and not exists("b.json")


def test_rename_locked_file_told(presets, monkeypatch):
    from neopedal.ui import preset_management

    def locked(*args):
        raise PermissionError("locked by another program")

    monkeypatch.setattr(preset_management, "replace_retry", locked)  # held after every retry
    error = create(mode="rename", source="b.json", name="other")
    assert "locked by another program" in error and exists("b.json")


def test_restore_backup_list_restore_delete(presets):
    backups = presets.backups
    folder = cfg.path.settings
    with open(f"{folder}a.json.backup-2026-10-03-12-00-00-000000", "w", encoding="utf-8") as file:
        json.dump({"speedometer": {"enable": False}}, file)
    with open(f"{folder}b.json.backup-2026-10-03-12-00-00-000000", "w", encoding="utf-8") as file:
        file.write("broken")
    backups.refresh()
    names = [row["key"] for row in backups.model.rows]
    assert len(names) == 2 and backups.count == 2  # broken backup listed too (marked once checked)
    assert all(row["status"] == "checking" for row in backups.model.rows) or backups.checking
    assert backups.prepareRestore("b.json.backup-2026-10-03-12-00-00-000000") == ""  # invalid: told
    assert presets.toasts[-1] == ("Selected backup file is invalid and cannot be restored.", True)
    assert backups.prepareRestore("a.json.backup-2026-10-03-12-00-00-000000") == "preset"  # name asked by page
    assert presets.suggestName("restore", "a.json.backup-2026-10-03-12-00-00-000000") == "a (2)"
    assert presets.applyName("restore", "a.json.backup-2026-10-03-12-00-00-000000", "a restored") == ""
    assert exists("a restored.json") and not exists("a.json.backup-2026-10-03-12-00-00-000000")
    assert presets.toasts[-1] == ("Preset restored: a restored", False)
    assert [row["key"] for row in backups.model.rows] == ["b.json.backup-2026-10-03-12-00-00-000000"]
    wait(lambda: backups.checking)
    assert backups.model.rows[0]["status"] == "invalid"
    backups.remove("b.json.backup-2026-10-03-12-00-00-000000")
    assert not exists("b.json.backup-2026-10-03-12-00-00-000000") and backups.count == 0


def transfer_ready(presets, settings=("speedometer",), types=("font",)):
    transfer = presets.transfer
    transfer.start()
    transfer.setDestination("b")
    for key in settings:
        transfer.toggleSetting(key)
    for key in types:
        transfer.toggleType(key)
    return transfer


def test_transfer_selected_option_types(presets, monkeypatch):
    monkeypatch.setattr(cfg.filename, "setting", "a.json")
    cfg.user.setting["speedometer"]["font_size"] = 31
    cfg.user.setting["speedometer"]["position_x"] = 444
    transfer = presets.transfer
    transfer.start()
    assert transfer.source == "a" and "a" not in transfer.destinations and transfer.destination == "b"
    assert not transfer.transfer()  # nothing selected
    assert transfer.error == "No preset setting selected. Select at least one setting and try again."
    transfer.toggleSetting("speedometer")
    assert not transfer.transfer() and transfer.error.startswith("No option type selected.")
    transfer.toggleType("font")
    assert transfer.settingCount == 1 and transfer.typeCount == 1 and transfer.error == ""
    assert transfer.confirmText.startswith("Transfer selected settings from a.json to b.json?")
    assert transfer.transfer()
    with open(f"{cfg.path.settings}b.json", encoding="utf-8") as file:
        saved = json.load(file)["speedometer"]
    assert saved["font_size"] == 31  # font transferred
    assert saved.get("position_x") != 444  # position not selected
    assert presets.toasts[-1] == ("Settings are transferred from a.json to b.json.", False)


@pytest.mark.parametrize("name", [
    "CON", "con", "nul.json", "Aux.txt", "prn ", "COM1", "lpt9", "a\x01b", "tab\tname"])
def test_reserved_and_control_character_names_refused(presets, name):
    from neopedal.ui.preset_management import check_preset_name
    from neopedal.validator import is_allowed_filename

    assert check_preset_name(name) == "Invalid preset name."
    assert not is_allowed_filename(name.removesuffix(".json"))


@pytest.mark.parametrize("name", ["console", "com10", "lpt", "nullable", "aux race"])
def test_names_close_to_reserved_allowed(presets, name):
    from neopedal.ui.preset_management import check_preset_name

    assert check_preset_name(name) == ""


@pytest.fixture
def loaded_a(presets, monkeypatch):
    """Preset a loaded, flush & reload recorded (reload refused: nothing loaded)"""
    from neopedal import app_signal

    calls = []
    monkeypatch.setattr(cfg.filename, "setting", "a.json")
    monkeypatch.setattr(cfg, "_setting_to_load", "")
    monkeypatch.setattr(type(cfg), "flush", lambda self, *args, **kwargs: calls.append("flush") or True)
    reloaded = []
    app_signal.reload.connect(reloaded.append)
    yield calls, reloaded
    app_signal.reload.disconnect(reloaded.append)


def test_rename_loaded_preset_follows_new_name(loaded_a, monkeypatch):
    from neopedal.ui import preset_management

    calls, reloaded = loaded_a
    rename = os.replace
    monkeypatch.setattr(preset_management, "replace_retry", lambda *args: calls.append("rename") or rename(*args))
    create(mode="rename", source="a.json", name="renamed")
    assert calls == ["flush", "rename"]  # queued save written before rename, not re-creating a.json
    assert exists("renamed.json") and not exists("a.json")
    # Even if reload is refused (config page with unsaved changes), saves go to renamed preset
    assert cfg.filename.setting == "renamed.json" and reloaded == [True]


def test_duplicate_loaded_preset_flushes_first(loaded_a):
    calls, _ = loaded_a
    create(mode="duplicate", source="a.json", name="copy")
    assert calls == ["flush"] and exists("copy.json") and cfg.filename.setting == "a.json"
    create(mode="duplicate", source="b.json", name="copy b")  # not loaded: no flush needed
    assert calls == ["flush"]


@pytest.mark.parametrize("change", ["loaded", "locked"])
def test_transfer_refused_if_destination_loaded_or_locked_meanwhile(presets, monkeypatch, change):
    monkeypatch.setattr(cfg.filename, "setting", "a.json")
    monkeypatch.setattr(cfg.user, "filelock", {})
    transfer = presets.transfer
    transfer.start()
    transfer.setDestination("b")
    transfer.setAllSettings(True)
    transfer.setAllTypes(True)
    with open(f"{cfg.path.settings}b.json", encoding="utf-8") as file:
        before = file.read()
    if change == "loaded":  # auto-loaded since panel was opened
        monkeypatch.setattr(cfg.filename, "setting", "b.json")
    else:
        cfg.user.filelock["b.json"] = {"version": "1.0"}
    assert not transfer.transfer()
    assert transfer.error == "Destination preset is now loaded or locked, choose another preset."
    with open(f"{cfg.path.settings}b.json", encoding="utf-8") as file:
        assert file.read() == before
    assert "b" not in transfer.destinations
    assert transfer.source == cfg.filename.setting[:-5]


def test_transfer_select_all_and_none(presets):
    transfer = presets.transfer
    transfer.start()
    transfer.setAllSettings(True)
    assert transfer.settingCount == transfer.settingTotal == len(cfg.user.setting)
    transfer.setAllSettings(False)
    assert transfer.settingCount == 0
    transfer.setAllTypes(True)
    assert transfer.typeCount == transfer.typeTotal
    transfer.setAllTypes(False)
    assert transfer.typeCount == 0
