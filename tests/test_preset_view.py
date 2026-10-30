"""Presets page: rows with tags & content, search & sort, load, auto load, actions (lock, backup, primary tags,
names, delete...), files read only when changed & while shown, Qt Quick page"""

import json
import os
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox

from neopedal import app_signal
from neopedal.setting import cfg


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def wait_read(page, timeout: float = 10.0):
    """Preset contents read in background handed to the page"""
    deadline = time.monotonic() + timeout
    while page.backend.reading and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    QCoreApplication.processEvents()
    assert not page.backend.reading


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
    from neopedal.ui import preset_view

    write_preset("race.json", age=3600)
    write_preset("practice.json", {"speedometer": {"enable": False}}, age=60)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: pytest.fail(f"warning: {args}")))
    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)  # no file write
    monkeypatch.setattr(cfg.filename, "setting", "default.json")
    cfg.user.classes = {"GT3": {"color": "#00AA00", "preset": ""}}
    cfg.user.tracks = {"Spa": {"preset": ""}}
    cfg.user.filelock = {}
    widget = preset_view.PresetList(None)
    widget.backend.set_active(True)
    wait_read(widget)
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
    assert rows(page)["broken"]["pending"] and not rows(page)["broken"]["unreadable"]  # read in background
    assert rows(page)["broken"]["contentText"] == rows(page)["broken"]["changedText"]
    wait_read(page)
    assert rows(page)["broken"]["unreadable"] and rows(page)["broken"]["overlays"] == 0
    assert rows(page)["broken"]["contentText"].startswith("Unreadable file")


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
    assert row["classes"] == [{"name": "GT3", "color": "#00AA00", "session": ""}] and row["tracks"] == ["Spa"]
    page.backend.select("practice.json")
    details = page.backend.selected
    assert details["classChoices"] == {"": [], "practice": ["GT3"], "qualify": ["GT3"], "race": ["GT3"]}
    assert details["trackChoices"] == []
    page.backend.removePrimaryTrack("Spa")
    assert cfg.user.tracks["Spa"]["preset"] == ""
    page.backend.setPrimaryTrack("practice.json", "Spa")
    page.backend.clearPrimary("practice.json")
    assert cfg.user.classes["GT3"]["preset"] == "" and cfg.user.tracks["Spa"]["preset"] == ""
    page.backend.setPrimaryClass("practice.json", "Unknown class")  # ignored
    assert "Unknown class" not in cfg.user.classes


def test_primary_class_presets_by_session(page):
    """Class preset of one session (GT3 in qualifying): own tag, removed alone, cleared with the preset tags"""
    page.backend.setPrimaryClassSession("race.json", "GT3", "qualify")
    page.backend.setPrimaryClassSession("race.json", "GT3", "race")
    page.backend.setPrimaryClassSession("practice.json", "GT3", "")  # every session
    page.backend.setPrimaryClassSession("race.json", "GT3", "warmup")  # unknown session: ignored
    page.backend.setPrimaryClassSession("race.json", "Unknown class", "race")  # ignored
    page.backend.setPrimaryClassSession("missing.json", "GT3", "practice")  # ignored
    gt3 = cfg.user.classes["GT3"]
    assert (gt3["preset"], gt3.get("preset_practice", ""), gt3["preset_qualify"], gt3["preset_race"]) == (
        "practice", "", "race", "race")
    assert "Unknown class" not in cfg.user.classes
    assert [entry["session"] for entry in rows(page)["race"]["classes"]] == ["qualify", "race"]
    assert [entry["session"] for entry in rows(page)["practice"]["classes"]] == [""]
    page.backend.select("race.json")
    assert page.backend.selected["classChoices"]["race"] == [] and page.backend.selected["classChoices"][""] == ["GT3"]
    page.backend.removePrimaryClassSession("GT3", "qualify")
    assert gt3["preset_qualify"] == "" and gt3["preset_race"] == "race" and gt3["preset"] == "practice"
    page.backend.clearPrimary("race.json")
    assert gt3["preset_race"] == "" and gt3["preset"] == "practice"


def test_session_class_references_renamed_trashed_restored(ui_env, monkeypatch):
    """Renaming a preset follows its session class presets, deleting clears them, restoring sets them again"""
    from neopedal.ui import preset_management

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    cfg.user.classes = {"GT3": {"preset": "race", "preset_race": "race", "preset_qualify": "quali"},
                        "HY": {"preset": "", "preset_practice": "race"}}
    references = preset_management.preset_references("race")
    assert references["classes"] == ["GT3"]
    assert references[preset_management.CLASS_SESSIONS] == ["preset_race:GT3", "preset_practice:HY"]
    preset_management.update_preset_references("race", "sprint")
    assert cfg.user.classes["GT3"]["preset_race"] == "sprint" and cfg.user.classes["HY"]["preset_practice"] == "sprint"
    assert cfg.user.classes["GT3"]["preset_qualify"] == "quali"
    preset_management.update_preset_references("sprint", "")
    assert cfg.user.classes["GT3"]["preset_race"] == "" and cfg.user.classes["HY"]["preset_practice"] == ""
    cfg.user.classes["HY"]["preset_practice"] = "other"  # set meanwhile: kept
    preset_management.restore_preset_references("race", {**references, preset_management.CLASS_SESSIONS: [
        *references[preset_management.CLASS_SESSIONS], "preset_bad:GT3", "preset_race:Gone"]})
    assert cfg.user.classes["GT3"]["preset_race"] == "race" and cfg.user.classes["GT3"]["preset"] == "race"
    assert cfg.user.classes["HY"]["preset_practice"] == "other" and "Gone" not in cfg.user.classes


def test_tags_of_every_preset_read_once(page, monkeypatch):
    from neopedal.ui.quick import preset_backend

    cfg.user.classes = {"GT3": {"color": "#00AA00", "preset": "race"}, "LMP2": {"color": "#0000FF", "preset": "race"},
                        "HY": {"color": "#FF0000", "preset": "practice"}, "Bad": "not a dict"}
    cfg.user.tracks = {"Spa": {"preset": "race"}, "Monza": {"preset": "race"}, "Imola": {"preset": ["odd"]}}
    calls = []
    original = preset_backend.preset_references
    monkeypatch.setattr(preset_backend, "preset_references", lambda: calls.append(1) or original())
    page.refresh()
    assert len(calls) == 1  # once per refresh, not once per preset
    race, practice = rows(page)["race"], rows(page)["practice"]
    assert [entry["name"] for entry in race["classes"]] == ["GT3", "LMP2"] and race["tracks"] == ["Monza", "Spa"]
    assert practice["classes"] == [{"name": "HY", "color": "#FF0000", "session": ""}] and practice["tracks"] == []
    assert page.backend.trashCount == 0
    page.backend.remove("practice.json")
    page.refresh()
    assert page.backend.trashCount == 1  # trash entries counted, not read
    os.makedirs(os.path.join(cfg.path.settings, "trash", "not an entry"))
    page.refresh()
    assert page.backend.trashCount == 1


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
    calls, panels = [], []
    for name in ("export_package", "import_package", "open_page"):
        monkeypatch.setattr(page, name, lambda *args, _name=name: calls.append((_name, *args)))
    page.backend.panelRequested.connect(lambda name, key: panels.append((name, key)))
    page.backend.exportPackage("race.json")
    page.backend.importPackage()
    page.backend.compareWith("race.json")
    page.backend.compareWith("missing.json")  # unknown: ignored
    page.backend.openPage("trash")
    page.backend.openPage("folder")
    page.backend.exportPackage("missing.json")  # unknown: ignored
    assert calls == [("export_package", "race.json"), ("import_package",), ("open_page", "folder")]
    assert panels == [("compare", "race.json"), ("trash", "")]  # panels of the QML page, no other page opened


def test_files_read_while_shown_and_only_when_changed(page, monkeypatch):
    from neopedal.ui.quick import preset_backend

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
    assert rows(page)["race"]["pending"] and rows(page)["race"]["overlays"] == 0  # read in background
    wait_read(page)
    assert len(parsed) == 1 and rows(page)["race"]["overlays"] == 2 and not rows(page)["race"]["pending"]
    assert rows(page)["race"]["contentText"].endswith("2 overlays  ·  0 modules")


def test_contents_read_off_ui_thread(page, monkeypatch):
    """Changed presets read on a job thread, details & loaded card told when done"""
    import threading

    from neopedal.ui.quick import preset_backend

    threads = []
    read = preset_backend.read_summary
    monkeypatch.setattr(preset_backend, "read_summary", lambda *args: threads.append(threading.current_thread()) or read(*args))
    write_preset("race.json", {"speedometer": {"enable": True}, "fuel": {"enable": True}})
    page.backend.select("race.json")
    told = []
    page.backend.selectionChanged.connect(lambda: told.append(page.backend.selected["overlays"]))
    page.refresh()
    assert page.backend.selected["pending"] and page.backend.selected["overlayNames"] == []
    wait_read(page)
    assert threads and all(thread is not threading.main_thread() for thread in threads)
    assert told[-1] == 2 and page.backend.selected["overlayNames"] == ["Fuel", "Speedometer"]


def test_changed_text():
    from neopedal.ui.quick.preset_backend import changed_text

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
    assert {"Presets", "race", "practice", "Auto Load Primary Preset"} <= texts
    page.backend.select("race.json")
    for _ in range(10):
        QCoreApplication.processEvents()
    assert "Load Preset" in item_texts(page.view)  # details panel of wide page
    assert not page.view.grabFramebuffer().isNull()


def test_qml_class_session_tags_and_menus(page):
    """Class preset of a session shown as "GT3 · Race" tag, class menus by session filled, no QML warning"""
    from PySide6.QtCore import QObject, QtMsgType, qInstallMessageHandler

    messages = []

    def handler(kind, _context, text):
        if kind != QtMsgType.QtDebugMsg:
            messages.append(text)

    previous = qInstallMessageHandler(handler)
    try:
        page.resize(1200, 760)
        page.show()
        page.backend.setPrimaryClassSession("race.json", "GT3", "race")
        page.backend.select("race.json")
        for _ in range(10):
            QCoreApplication.processEvents()
        assert "GT3  ·  Race" in item_texts(page.view)
        root = page.view.rootObject()
        root.setProperty("menuInfo", page.backend.selected)
        for _ in range(10):
            QCoreApplication.processEvents()
        # Every session, practice & qualifying offer GT3 (row menu & details menu); race already set
        actions = [obj for obj in root.findChildren(QObject) if obj.property("text") == "GT3"
                   and obj.metaObject().className().startswith("Action_")]
        assert len(actions) == 6
    finally:
        qInstallMessageHandler(previous)
    assert not [text for text in messages if "qml" in text.lower()], messages


def test_qml_page_translated(page):
    from neopedal import i18n

    i18n.set_language("Français")
    try:
        page.show()
        for _ in range(10):
            QCoreApplication.processEvents()
        texts = item_texts(page.view)
        assert "Charger automatiquement le preset principal" in texts and "Auto Load Primary Preset" not in texts
    finally:
        i18n.set_language("English")


def test_check_preset_lists_and_repairs(page, monkeypatch):
    toasts, questions = [], []
    page.backend.toastShown.connect(lambda text, error, undo: toasts.append(text))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *args, **kwargs: questions.append(args[2]) or QMessageBox.StandardButton.Yes))
    page.backend.checkPreset("practice.json")
    assert toasts == ["No problem found"] and not questions
    write_preset("race.json", {"speedometer": {"enable": True, "font_size": 99999, "removed_option": 1}})
    page.backend.checkPreset("race.json")
    assert "font_size 99999 -> 200" in questions[0] and "removed_option" in questions[0]
    assert toasts[-1] == "Preset repaired"
    with open(f"{cfg.path.settings}race.json", encoding="utf-8") as file:
        repaired = json.load(file)["speedometer"]
    assert repaired["font_size"] == 200 and "removed_option" not in repaired
    page.backend.checkPreset("race.json")
    assert toasts[-1] == "No problem found"


def test_locked_preset_checked_not_repaired(page, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: warnings.append(args[2])))
    write_preset("race.json", {"speedometer": {"font_size": -5}})
    cfg.user.filelock["race.json"] = {"version": "1.0"}
    page.backend.checkPreset("race.json")
    assert "locked preset, not changed" in warnings[0]
    with open(f"{cfg.path.settings}race.json", encoding="utf-8") as file:
        assert json.load(file)["speedometer"]["font_size"] == -5
