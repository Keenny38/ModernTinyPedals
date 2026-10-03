"""Preset management dialogs: create, duplicate, rename, restore backup, transfer settings"""

import json
import os

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox

from tinypedal.setting import cfg
from tinypedal.ui._common import BaseDialog


@pytest.fixture
def presets(ui_env, monkeypatch):
    """Settings folder with presets a & b, questions answered yes, warnings recorded"""
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: warnings.append(args[2])))
    monkeypatch.setattr(BaseDialog, "confirm_operation", lambda self, *args, **kwargs: True)
    folder = cfg.path.settings
    for name in ("a", "b"):
        with open(f"{folder}{name}.json", "w", encoding="utf-8") as file:
            json.dump({"speedometer": {"enable": True, "font_size": 15}}, file)
    return warnings


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def create(mode: str = "", source: str = "", name: str = ""):
    from tinypedal.ui.preset_management import CreatePreset

    dialog = CreatePreset(None, title="Test", mode=mode, source_filename=source)
    dialog.preset_entry.setText(name)
    dialog.create_preset()
    return dialog


def exists(name: str) -> bool:
    return os.path.exists(f"{cfg.path.settings}{name}")


def test_create_preset_checks_name(presets):
    create(name="")
    create(name="A")  # same name as a.json, any case
    assert len(presets) == 2
    create(name="new")
    assert exists("new.json")
    flush()


def test_duplicate_and_rename_preset(presets):
    create(mode="duplicate", source="a.json", name="copy")
    assert exists("copy.json") and exists("a.json")
    create(mode="rename", source="b.json", name="renamed")
    assert exists("renamed.json") and not exists("b.json")
    flush()


def test_rename_locked_file_warns(presets, monkeypatch):
    from tinypedal.ui import preset_management

    def locked(*args):
        raise PermissionError("locked by another program")

    monkeypatch.setattr(preset_management.os, "rename", locked)
    dialog = create(mode="rename", source="b.json", name="other")
    assert presets and exists("b.json")
    dialog.close()
    flush()


def test_restore_backup_list_restore_delete(presets, monkeypatch):
    from tinypedal.ui import preset_management

    folder = cfg.path.settings
    with open(f"{folder}a.json.backup-2026-10-03-12-00-00-000000", "w", encoding="utf-8") as file:
        json.dump({"speedometer": {"enable": False}}, file)
    with open(f"{folder}b.json.backup-2026-10-03-12-00-00-000000", "w", encoding="utf-8") as file:
        file.write("broken")
    opened = []
    monkeypatch.setattr(preset_management.CreatePreset, "open", lambda self: opened.append(self.source_filename))
    dialog = preset_management.RestoreBackup(None)
    try:
        names = [dialog.listbox_backup.item(row).text() for row in range(dialog.listbox_backup.count())]
        assert len(names) == 2  # broken backup listed too (shown in red)
        dialog.restore()  # nothing selected
        assert presets
        rows = {dialog.listbox_backup.item(row).text(): row for row in range(dialog.listbox_backup.count())}
        dialog.listbox_backup.setCurrentRow(rows["b.json.backup-2026-10-03-12-00-00-000000"])
        dialog.restore()  # invalid backup
        assert len(presets) == 2 and not opened
        dialog.listbox_backup.setCurrentRow(rows["a.json.backup-2026-10-03-12-00-00-000000"])
        dialog.restore()  # asks new preset name
        assert opened == ["a.json.backup-2026-10-03-12-00-00-000000"]
        dialog.listbox_backup.setCurrentRow(rows["b.json.backup-2026-10-03-12-00-00-000000"])
        dialog.delete()
        assert not exists("b.json.backup-2026-10-03-12-00-00-000000")
        assert dialog.listbox_backup.count() == 1
    finally:
        dialog.set_unmodified()
        dialog.close()
        flush()


def test_transfer_selected_option_types(presets, monkeypatch):
    from tinypedal.ui import preset_management

    monkeypatch.setattr(preset_management, "show_toast", lambda *args, **kwargs: None)
    monkeypatch.setattr(cfg.filename, "setting", "a.json")
    cfg.user.setting["speedometer"]["font_size"] = 31
    cfg.user.setting["speedometer"]["position_x"] = 444
    dialog = preset_management.PresetTransfer(None)
    try:
        assert "a" not in [dialog.dest_selector.itemText(index) for index in range(dialog.dest_selector.count())]
        dialog.dest_selector.setCurrentText("b")
        dialog.transfer()  # nothing selected
        assert presets

        def check(listbox, keys):
            for row in range(listbox.count()):
                checkbox = listbox.itemWidget(listbox.item(row))
                checkbox.setChecked(checkbox.key_name in keys)

        check(dialog.listbox_setting, {"speedometer"})
        dialog.transfer()  # no option type selected
        assert len(presets) == 2
        check(dialog.listbox_options, {"font"})
        dialog.transfer()
        with open(f"{cfg.path.settings}b.json", encoding="utf-8") as file:
            saved = json.load(file)["speedometer"]
        assert saved["font_size"] == 31  # font transferred
        assert saved.get("position_x") != 444  # position not selected
    finally:
        dialog.set_unmodified()
        dialog.close()
        flush()


def test_list_header_select_all(presets):
    from tinypedal.ui import preset_management

    dialog = preset_management.PresetTransfer(None)
    try:
        header = dialog.findChild(preset_management.ListHeader)
        header.button_select_all()
        assert len(tuple(dialog.get_setting_selection(dialog.listbox_setting))) == dialog.listbox_setting.count()
        header.button_deselect_all()
        assert not tuple(dialog.get_setting_selection(dialog.listbox_setting))
    finally:
        dialog.close()
        flush()
