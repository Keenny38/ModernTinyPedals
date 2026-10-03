"""Preset page: list with tags, load, auto load, context menu actions (lock, backup, primary tags, delete...)"""

import json
import os

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtWidgets import QMenu, QMessageBox

from tinypedal import app_signal
from tinypedal.i18n import untr
from tinypedal.setting import cfg


@pytest.fixture
def page(ui_env, monkeypatch):
    """Preset page with presets "race" & "practice", questions answered yes"""
    from tinypedal.ui import preset_view

    for name in ("race", "practice"):
        with open(f"{cfg.path.settings}{name}.json", "w", encoding="utf-8") as file:
            json.dump({"speedometer": {"enable": True}}, file)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: pytest.fail(f"warning: {args}")))
    monkeypatch.setattr(preset_view, "show_toast", lambda *args, **kwargs: None)
    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)  # no file write
    cfg.user.classes = {"GT3": {"color": "#00AA00", "preset": ""}}
    cfg.user.tracks = {"Spa": {"preset": ""}}
    cfg.user.filelock = {}
    widget = preset_view.PresetList(None)
    widget.refresh()
    yield widget
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def names(page) -> list[str]:
    return [page.listbox_preset.item(row).text() for row in range(page.listbox_preset.count())]


def choose(page, monkeypatch, preset: str, text: str, data=None):
    """Run context menu of preset, picking action by (English) text"""
    page.listbox_preset.setCurrentRow(names(page).index(preset))

    def pick(menu, *args):
        actions = list(menu.actions())
        while actions:
            action = actions.pop(0)
            if action.menu() is not None:
                actions.extend(action.menu().actions())
            elif untr(action.text()) == text and (data is None or action.data() == data):
                return action
        raise AssertionError(f"no action {text}")

    class PickMenu(QMenu):
        def exec(self, *args):
            return pick(self)

    from tinypedal.ui import preset_view

    monkeypatch.setattr(preset_view, "QMenu", PickMenu)
    item = page.listbox_preset.item(names(page).index(preset))
    position = page.listbox_preset.visualItemRect(item).center()
    monkeypatch.setattr(page.listbox_preset, "itemAt", lambda pos: item)
    page.open_context_menu(position if not position.isNull() else QPoint(1, 1))


def test_list_and_load(page, monkeypatch):
    assert {"race", "practice"} <= set(names(page))
    reloaded = []
    app_signal.reload.connect(reloaded.append)
    try:
        page.listbox_preset.setCurrentRow(names(page).index("race"))
        page.load_preset()
    finally:
        app_signal.reload.disconnect(reloaded.append)
    assert reloaded == [True] and cfg._setting_to_load == "race.json"
    page.toggle_autoload(True)
    assert cfg.application["enable_auto_load_preset"] is True


def test_lock_unlock_and_tag(page, monkeypatch):
    from PySide6.QtWidgets import QLabel

    choose(page, monkeypatch, "race", "Lock Preset")
    assert "race.json" in cfg.user.filelock
    page.refresh()
    item = page.listbox_preset.item(names(page).index("race"))
    assert [label.text() for label in page.listbox_preset.itemWidget(item).findChildren(QLabel)]  # version tag
    choose(page, monkeypatch, "race", "Unlock Preset")
    assert "race.json" not in cfg.user.filelock


def test_primary_tags_for_class_and_track(page, monkeypatch):
    from PySide6.QtWidgets import QLabel

    choose(page, monkeypatch, "practice", "GT3")
    choose(page, monkeypatch, "practice", "Spa", data="track")
    assert cfg.user.classes["GT3"]["preset"] == "practice" and cfg.user.tracks["Spa"]["preset"] == "practice"
    page.refresh()
    item = page.listbox_preset.item(names(page).index("practice"))
    tags = [label.text() for label in page.listbox_preset.itemWidget(item).findChildren(QLabel)]
    assert "GT3" in tags and any("Spa" in tag for tag in tags)
    choose(page, monkeypatch, "practice", "Clear Primary Tag")
    assert cfg.user.classes["GT3"]["preset"] == "" and cfg.user.tracks["Spa"]["preset"] == ""


def test_backup_and_delete(page, monkeypatch):
    choose(page, monkeypatch, "race", "Backup Preset")
    assert any(name.startswith("race.json.backup") for name in os.listdir(cfg.path.settings))
    choose(page, monkeypatch, "practice", "Delete")
    assert not os.path.exists(f"{cfg.path.settings}practice.json")


def test_dialog_actions(page, monkeypatch):
    from tinypedal.ui import preset_view

    opened = []
    monkeypatch.setattr(preset_view.CreatePreset, "open", lambda self: opened.append(self.edit_mode))
    monkeypatch.setattr(preset_view, "PresetCompare", lambda *args, **kwargs: type("Shown", (), {"show": lambda self: opened.append("compare")})())
    exported = []
    monkeypatch.setattr(page, "export_package", exported.append)
    monkeypatch.setattr(page, "copy_share_code", exported.append)
    for text in ("Duplicate", "Rename", "Compare with Loaded Preset", "Export Package...", "Copy Share Code"):
        choose(page, monkeypatch, "race", text)
    assert opened == ["duplicate", "rename", "compare"]
    assert exported == ["race.json", "race.json"]


def test_locked_preset_cannot_be_renamed_or_deleted(page, monkeypatch):
    cfg.user.filelock["race.json"] = {"version": "1.0.0"}
    with pytest.raises(AssertionError, match="no action"):
        choose(page, monkeypatch, "race", "Delete")
    with pytest.raises(AssertionError, match="no action"):
        choose(page, monkeypatch, "race", "Rename")
