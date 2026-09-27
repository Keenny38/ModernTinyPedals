"""Config dialog & preset management UI tests (headless)"""

import os

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox

from tinypedal.setting import cfg


@pytest.fixture
def no_message_box(monkeypatch):
    shown = []
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *args, _name=name, **kwargs: shown.append((_name, args))))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    return shown


def close_dialog(dialog):
    """Close & delete dialog now, so singleton dialog can be opened again"""
    dialog.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def open_config(section, reload_calls):
    from tinypedal.const_file import ConfigType
    from tinypedal.ui.config import UserConfig

    return UserConfig(
        parent=None, key_name=section, preset_name="default.json", config_type=ConfigType.WIDGET,
        user_setting=cfg.user.setting, default_setting=cfg.default.setting,
        reload_func=lambda: reload_calls.append(section),
    )


def test_config_dialog_save(ui_env, no_message_box):
    reloads = []
    dialog = open_config("speedometer", reloads)
    try:
        dialog.option_edit["font_size"].setText("21")
        dialog.save_setting()
        assert cfg.user.setting["speedometer"]["font_size"] == 21
        assert reloads == ["speedometer"]
        assert "setting" in ui_env  # saved
    finally:
        close_dialog(dialog)


def test_config_dialog_invalid_value(ui_env, no_message_box):
    reloads = []
    dialog = open_config("speedometer", reloads)
    try:
        before = cfg.user.setting["speedometer"]["font_color_speed"]
        dialog.option_edit["font_color_speed"].setText("not a color")
        dialog.save_setting()
        assert cfg.user.setting["speedometer"]["font_color_speed"] == before
        assert reloads == [] and no_message_box and no_message_box[0][0] == "warning"
    finally:
        close_dialog(dialog)


def test_config_dialog_search_and_french(ui_env):
    from tinypedal.i18n import set_language

    set_language("Français")
    try:
        dialog = open_config("speedometer", [])
        labels = [
            dialog.layout_option.itemAtPosition(row, 0).widget().text()
            for row in range(dialog.layout_option.rowCount())
            if dialog.layout_option.itemAtPosition(row, 0)
        ]
        assert "Couleur du texte : vitesse" in labels
        dialog.edit_search.setText("couleur vitesse")
        shown = [key for key, editor in dialog.option_edit.items() if not editor.isHidden()]
        assert "font_color_speed" in shown and "update_interval" not in shown
        close_dialog(dialog)
    finally:
        set_language("English")


def test_every_widget_config_opens(ui_env):
    """All widget & module config dialogs build without error"""
    from tinypedal.module_control import mctrl, wctrl

    for name in (*wctrl.names, *mctrl.names):
        dialog = open_config(name, [])
        assert dialog.option_edit, name
        close_dialog(dialog)


def test_rename_preset_updates_references(ui_env, no_message_box, monkeypatch):
    from tinypedal.ui.preset_management import CreatePreset

    settings = cfg.path.settings
    for name in ("race.json", "race.json.backup-auto-2026-01-01", "race.json.backup-2026-02-02"):
        with open(f"{settings}{name}", "w", encoding="utf-8") as file:
            file.write("{}")
    cfg.user.tracks["Spa"] = {"preset": "race"}
    cfg.user.classes["GT3"] = {"alias": "GT3", "color": "#FFFFFF", "preset": "race"}
    monkeypatch.setattr(type(cfg), "is_loaded", lambda self, name: False)
    dialog = CreatePreset(None, "Rename", "rename", "race.json")
    dialog.preset_entry.setText("endurance")
    dialog.create_preset()
    assert os.path.exists(f"{settings}endurance.json")
    assert os.path.exists(f"{settings}endurance.json.backup-auto-2026-01-01")
    assert os.path.exists(f"{settings}endurance.json.backup-2026-02-02")
    assert cfg.user.tracks["Spa"]["preset"] == "endurance"
    assert cfg.user.classes["GT3"]["preset"] == "endurance"


def test_rename_locked_file_shows_error(ui_env, no_message_box, monkeypatch):
    from tinypedal.ui import preset_management

    with open(f"{cfg.path.settings}race.json", "w", encoding="utf-8") as file:
        file.write("{}")

    def locked(*args):
        raise PermissionError(13, "file used by another process")

    monkeypatch.setattr(preset_management.os, "rename", locked)
    dialog = preset_management.CreatePreset(None, "Rename", "rename", "race.json")
    dialog.preset_entry.setText("endurance")
    dialog.create_preset()  # must not raise
    assert no_message_box and no_message_box[0][0] == "warning"
    assert os.path.exists(f"{cfg.path.settings}race.json")


def test_duplicate_does_not_create_default(ui_env, no_message_box, monkeypatch):
    from tinypedal.ui.preset_management import CreatePreset

    created = []
    monkeypatch.setattr(type(cfg), "create", lambda self, filename: created.append(filename))
    with open(f"{cfg.path.settings}race.json", "w", encoding="utf-8") as file:
        file.write('{"speedometer": {"font_size": 30}}')
    dialog = CreatePreset(None, "Duplicate", "duplicate", "race.json")
    dialog.preset_entry.setText("race copy")
    dialog.create_preset()
    assert created == []
    with open(f"{cfg.path.settings}race copy.json", encoding="utf-8") as file:
        assert "30" in file.read()


def test_restart_command_keeps_arguments(monkeypatch):
    import sys

    from tinypedal import loader

    monkeypatch.setattr(sys, "argv", ["run.py", "-l", "2"])
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\Python\python.exe")
    assert loader.restart_command() == [r"C:\Program Files\Python\python.exe", "run.py", "-l", "2"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\TinyPedal\tinypedal.exe")
    monkeypatch.setattr(sys, "argv", [r"C:\Program Files\TinyPedal\tinypedal.exe", "-s", "0"])
    assert loader.restart_command() == [r"C:\Program Files\TinyPedal\tinypedal.exe", "-s", "0"]


def test_atomic_write_removes_temp_on_error(tmp_path):
    from tinypedal.userfile import atomic_write

    target = tmp_path / "data.csv"
    with pytest.raises(ValueError), atomic_write(str(target)) as file:
        file.write("partial")
        raise ValueError("boom")
    assert list(tmp_path.iterdir()) == []
