"""Presets page: rows with tags & content, search & sort, load, auto load, actions (lock, backup, primary tags,
names, delete...), files read only when changed & while shown, Qt Quick page"""

import json
import os
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox

from tinypedal import app_signal
from tinypedal.setting import cfg


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def write_preset(name: str, data: dict | None = None, age: float = 0.0):
    path = f"{cfg.path.settings}{name}"
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data if data is not None else {"speedometer": {"enable": True}, "module_delta": {"enable": True}}, file)
    if age:
        moment = time.time() - age
        os.utime(path, (moment, moment))


@pytest.fixture
def page(ui_env, monkeypatch):
    """Presets page (active) with presets "race" & "practice", questions answered yes"""
    from tinypedal.ui import preset_view

    write_preset("race.json", age=3600)
    write_preset("practice.json", {"speedometer": {"enable": False}}, age=60)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: pytest.fail(f"warning: {args}")))
    monkeypatch.setattr(preset_view, "show_toast", lambda *args, **kwargs: None)
    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)  # no file write
    monkeypatch.setattr(cfg.filename, "setting", "default.json")
    cfg.user.classes = {"GT3": {"color": "#00AA00", "preset": ""}}
    cfg.user.tracks = {"Spa": {"preset": ""}}
    cfg.user.filelock = {}
    widget = preset_view.PresetList(None)
    widget.backend.set_active(True)
    yield widget
    widget.close()
    widget.deleteLater()
    flush()


def rows(page) -> dict[str, dict]:
    return {row["name"]: row for row in page.backend.model.rows}


def test_rows_with_content_and_sort(page):
    assert list(rows(page)) == ["default", "practice", "race"]  # last changed first
    race = rows(page)["race"]
    assert race["overlays"] == 1 and race["modules"] == 1 and not race["loaded"] and not race["unreadable"]
    assert race["changedText"] == "1 h ago" and rows(page)["practice"]["changedText"] == "1 min ago"
    assert rows(page)["default"]["loaded"] and rows(page)["default"]["unreadable"] is False
    page.backend.setSortMode(1)
    assert list(rows(page)) == ["default", "practice", "race"]
    page.backend.setSearch("RACE")
    assert list(rows(page)) == ["race"] and page.backend.shownCount == 1 and page.backend.filtered
    page.backend.setSearch("")
    assert page.backend.presetCount == 3


def test_unreadable_preset_marked(page):
    with open(f"{cfg.path.settings}broken.json", "w", encoding="utf-8") as file:
        file.write("{not json")
    page.refresh()
    assert rows(page)["broken"]["unreadable"] and rows(page)["broken"]["overlays"] == 0


def test_load_and_auto_load(page):
    reloaded = []
    app_signal.reload.connect(reloaded.append)
    try:
        page.backend.load("race.json")
        page.backend.load("missing.json")  # unknown: ignored
    finally:
        app_signal.reload.disconnect(reloaded.append)
    assert reloaded == [True] and cfg._setting_to_load == "race.json"
    page.backend.setAutoLoad(True)
    assert cfg.application["enable_auto_load_preset"] is True and page.backend.autoLoad
    page.toggle_autoload(False)
    assert cfg.application["enable_auto_load_preset"] is False


def test_lock_unlock(page):
    page.backend.toggleLock("race.json")
    assert "race.json" in cfg.user.filelock
    page.refresh()
    assert rows(page)["race"]["locked"] and rows(page)["race"]["lockVersion"]
    assert page.backend.applyName("rename", "race.json", "sprint") == "Unlock the preset to rename it."
    page.backend.toggleLock("race.json")
    assert "race.json" not in cfg.user.filelock


def test_primary_tags_for_class_and_track(page):
    page.backend.setPrimaryClass("practice.json", "GT3")
    page.backend.setPrimaryTrack("practice.json", "Spa")
    assert cfg.user.classes["GT3"]["preset"] == "practice" and cfg.user.tracks["Spa"]["preset"] == "practice"
    row = rows(page)["practice"]
    assert row["classes"] == [{"name": "GT3", "color": "#00AA00"}] and row["tracks"] == ["Spa"]
    page.backend.select("practice.json")
    details = page.backend.selected
    assert details["classChoices"] == [] and details["trackChoices"] == []
    page.backend.removePrimaryTrack("Spa")
    assert cfg.user.tracks["Spa"]["preset"] == ""
    page.backend.setPrimaryTrack("practice.json", "Spa")
    page.backend.clearPrimary("practice.json")
    assert cfg.user.classes["GT3"]["preset"] == "" and cfg.user.tracks["Spa"]["preset"] == ""
    page.backend.setPrimaryClass("practice.json", "Unknown class")  # ignored
    assert "Unknown class" not in cfg.user.classes


def test_hotkeys_in_row(page):
    cfg.user.shortcuts["preset_3"]["preset"] = "race"
    page.refresh()
    assert rows(page)["race"]["hotkeys"] == [3]
    cfg.user.shortcuts["preset_3"]["preset"] = ""


def test_details_of_selected_preset(page):
    page.backend.select("race.json")
    details = page.backend.selected
    assert details["found"] and details["overlayNames"] == ["Speedometer"] and details["moduleNames"]
    assert details["size"].endswith("bytes") and details["date"]
    page.backend.select("missing.json")  # unknown: selection kept
    assert page.backend.selectedKey == "race.json"


def test_backup_and_delete(page):
    page.backend.backup("race.json")
    assert any(name.startswith("race.json.backup") for name in os.listdir(cfg.path.settings))
    page.backend.remove("practice.json")
    assert not os.path.exists(f"{cfg.path.settings}practice.json") and page.backend.canUndoDelete
    page.backend.undoDelete()
    assert os.path.exists(f"{cfg.path.settings}practice.json") and not page.backend.canUndoDelete


def test_loaded_and_locked_preset_not_deleted(page, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: warnings.append(args[2])))
    monkeypatch.setattr(cfg.filename, "setting", "race.json")
    page.backend.remove("race.json")
    cfg.user.filelock["practice.json"] = {"version": "1.0"}
    page.backend.remove("practice.json")
    assert os.path.exists(f"{cfg.path.settings}race.json") and os.path.exists(f"{cfg.path.settings}practice.json")
    assert "loaded preset cannot be deleted" in warnings[0] and "Unlock" in warnings[1]


def test_names_checked_while_typing_and_applied(page):
    backend = page.backend
    assert backend.nameError("", "", "race") == "Preset already exists."
    assert backend.nameError("", "", "RACE") == "Preset already exists."  # any case
    assert backend.nameError("", "", "a/b") == "Invalid preset name."
    assert backend.nameError("", "", "endurance") == ""
    assert backend.nameError("rename", "race.json", "race") == ""  # same name: no error, nothing to do
    assert backend.nameError("rename", "race.json", "Race") == ""  # case only
    assert backend.suggestName("duplicate", "race.json") == "race (2)"
    assert backend.suggestName("rename", "race.json") == "race"
    assert backend.suggestName("", "") == "New preset"
    assert backend.applyName("", "", "endurance") == ""
    assert backend.applyName("duplicate", "race.json", "race copy") == ""
    assert backend.applyName("rename", "practice.json", "qualy") == ""
    names = set(rows(page))
    assert {"endurance", "race copy", "qualy"} <= names and "practice" not in names
    assert backend.selectedKey == "qualy.json"
    assert backend.applyName("duplicate", "race.json", "qualy") == "Preset already exists."
    assert backend.applyName("rename", "gone.json", "x") == "Preset not found, it may have been renamed or deleted."


def test_name_typed_with_json_extension_used_once(page):
    backend = page.backend
    assert backend.nameError("rename", "race.json", "race.json") == ""  # same name
    assert backend.applyName("rename", "race.json", "race.json") == ""  # nothing to do
    assert os.path.exists(f"{cfg.path.settings}race.json")
    assert backend.applyName("", "", "Endurance.json") == ""
    assert backend.selectedKey == "Endurance.json"  # not "Endurance.json.json"
    assert "Endurance" in rows(page) and not os.path.exists(f"{cfg.path.settings}Endurance.json.json")


def test_host_actions(page, monkeypatch):
    calls = []
    for name in ("export_package", "copy_share_code", "import_package", "import_share_code", "open_page"):
        monkeypatch.setattr(page, name, lambda *args, _name=name: calls.append((_name, *args)))
    page.backend.exportPackage("race.json")
    page.backend.copyShareCode("race.json")
    page.backend.importPackage()
    page.backend.importShareCode()
    page.backend.compare("race.json")
    page.backend.openPage("trash")
    page.backend.exportPackage("missing.json")  # unknown: ignored
    assert calls == [
        ("export_package", "race.json"), ("copy_share_code", "race.json"), ("import_package",),
        ("import_share_code",), ("open_page", "compare", "race.json"), ("open_page", "trash"),
    ]


def test_open_pages(page, monkeypatch):
    from tinypedal.ui import preset_view

    opened = []
    monkeypatch.setattr(preset_view, "PresetCompare", lambda *args, **kwargs: type(
        "Shown", (), {"show": lambda self: opened.append(("compare", kwargs["preset_b"]))})())
    for name in ("PresetTransfer", "RestoreBackup", "PresetTrash"):
        monkeypatch.setattr(preset_view, name, lambda *args, _name=name: type(
            "Shown", (), {"open": lambda self: opened.append(_name)})())
    page.open_page("compare", "race.json")
    for name in ("transfer", "restore", "trash"):
        page.open_page(name)
    assert opened == [("compare", "race.json"), "PresetTransfer", "RestoreBackup", "PresetTrash"]


def test_files_read_while_shown_and_only_when_changed(page, monkeypatch):
    from tinypedal.ui.quick import preset_backend

    parsed = []
    load = json.load
    monkeypatch.setattr(preset_backend.json, "load", lambda file: parsed.append(file.name) or load(file))
    page.refresh()
    assert parsed == []  # unchanged files: cached
    write_preset("race.json", {"speedometer": {"enable": True}, "fuel": {"enable": True}})
    page.backend.set_active(False)
    page.refresh()
    assert parsed == [] and rows(page)["race"]["overlays"] == 1  # hidden: read when shown
    page.backend.set_active(True)
    assert len(parsed) == 1 and rows(page)["race"]["overlays"] == 2


def test_changed_text():
    from tinypedal.ui.quick.preset_backend import changed_text

    now = 1_000_000_000.0
    assert changed_text(now - 5, now) == "Just now"
    assert changed_text(now - 600, now) == "10 min ago"
    assert changed_text(now - 7200, now) == "2 h ago"
    assert changed_text(now - 86400 * 1.5, now) == "Yesterday"
    assert changed_text(now - 86400 * 3, now) == "3 days ago"
    assert "/" in changed_text(now - 86400 * 30, now) or "." in changed_text(now - 86400 * 30, now)


def item_texts(view) -> set[str]:
    texts, stack = set(), [view.rootObject()]
    while stack:
        item = stack.pop()
        text = item.property("text")
        if isinstance(text, str):
            texts.add(text)
        stack.extend(item.childItems())
    return texts


def test_qml_page_created_when_shown(page):
    assert page.view is None
    page.resize(1200, 760)
    page.show()
    assert page.view is not None and not page.view.errors(), [error.toString() for error in page.view.errors()]
    assert page.layout().count() == 1
    for _ in range(20):
        QCoreApplication.processEvents()
    texts = item_texts(page.view)
    assert {"Preset", "race", "practice", "Auto Load Primary Preset"} <= texts
    page.backend.select("race.json")
    for _ in range(10):
        QCoreApplication.processEvents()
    assert "Load Preset" in item_texts(page.view)  # details panel of wide page
    assert not page.view.grabFramebuffer().isNull()


def test_qml_page_translated(page):
    from tinypedal import i18n

    i18n.set_language("Français")
    try:
        page.show()
        for _ in range(10):
            QCoreApplication.processEvents()
        texts = item_texts(page.view)
        assert "Charger automatiquement le preset principal" in texts and "Auto Load Primary Preset" not in texts
    finally:
        i18n.set_language("English")
