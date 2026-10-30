"""UI/UX audit 2026-10-29, configuration lot, Presets page: compare, transfer, restore backup & recently deleted
presets as panels of the QML page (no QWidget page opened), Ctrl+F search, plural title, overlay wording"""

import json
import logging
import os
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject
from PySide6.QtWidgets import QMessageBox

from neopedal import i18n
from neopedal.setting import cfg


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


def write_preset(name: str, data: dict | None = None):
    with open(f"{cfg.path.settings}{name}", "w", encoding="utf-8") as file:
        json.dump(data if data is not None else {"speedometer": {"enable": True}}, file)


@pytest.fixture
def page(ui_env, monkeypatch):
    """Presets page (active) with presets "race" & "practice", default preset loaded"""
    from neopedal.ui import preset_view

    write_preset("race.json")
    write_preset("practice.json")
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: pytest.fail(f"warning: {args}")))
    monkeypatch.setattr(cfg.filename, "setting", "default.json")
    cfg.user.filelock = {}
    widget = preset_view.PresetList(None)
    widget.backend.set_active(True)
    widget.toasts = []
    widget.backend.toastShown.connect(lambda text, error, undo: widget.toasts.append((text, error, undo)))
    yield widget
    widget.close()
    widget.deleteLater()
    flush()


def qml_problems(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records
            if record.name.startswith("neopedal.ui.quick") and "QML" in record.getMessage()]


def show(page, width=1200, height=760):
    page.resize(width, height)
    page.show()
    for _ in range(20):
        QCoreApplication.processEvents()
    assert page.view is not None and not page.view.errors(), [error.toString() for error in page.view.errors()]
    return page.view.rootObject()


def panel(root, name: str) -> QObject:
    found = root.findChild(QObject, name)
    assert found is not None, name
    return found


# --- No QWidget page opened from Presets: every tool is a panel of the QML page
def test_no_qwidget_tool_page_left():
    from neopedal.ui import preset_management, preset_view

    for name in ("PresetCompare", "PresetTransfer", "RestoreBackup", "PresetTrash"):
        assert not hasattr(preset_view, name), name  # toasts: show_toast routes to the page TpDialogHost
    for name in ("CreatePreset", "RestoreBackup", "PresetTrash", "PresetTransfer", "ListHeader"):
        assert not hasattr(preset_management, name), name  # dead QWidget code removed


@pytest.mark.parametrize(("language", "size"), [("English", (1200, 760)), ("Français", (700, 520))])
def test_panels_open_without_qml_problems(page, caplog, language, size):
    """Each panel opens over the page (wide & narrow window, English & longer French), no QML error or warning"""
    i18n.set_language(language)
    caplog.set_level(logging.WARNING)
    try:
        root = show(page, *size)
        backend = page.backend
        for name, key in (("compare", "race.json"), ("transfer", ""), ("restore", ""), ("trash", "")):
            if name == "compare":
                backend.compareWith(key)
            else:
                backend.openPage(name)
            for _ in range(10):
                QCoreApplication.processEvents()
            shown = panel(root, {"compare": "comparePanel", "transfer": "transferPanel",
                                 "restore": "backupsPanel", "trash": "deletedPanel"}[name])
            assert shown.property("visible"), name
            wait(lambda: backend.jobs.running > 0)
            shown.setProperty("visible", False)
            for _ in range(10):
                QCoreApplication.processEvents()
        assert not qml_problems(caplog)
    finally:
        i18n.set_language("English")


def test_title_search_hint_and_ctrl_f(page):
    from neopedal.ui.quick import qml_path

    with open(qml_path("Presets.qml"), encoding="utf-8") as file:
        text = file.read()
    assert 'title: i18n.tr("Presets")' in text and 'i18n.tr("Search presets, classes, tracks") + "   Ctrl+F"' in text
    assert "Qt.Key_F && (event.modifiers & Qt.ControlModifier)" in text  # Ctrl+F: search of the page
    assert i18n.tr("Presets") == "Presets"


def test_overlay_wording_in_french():
    i18n.set_language("Français")
    try:
        assert i18n.tr("Ignore overlay positions") == "Ignorer les positions des overlays"
        assert i18n.tr("Presets") == "Presets"
    finally:
        i18n.set_language("English")


# --- Compare panel
@pytest.fixture
def compare(page, monkeypatch):
    from neopedal.ui import preset_compare

    other = {section: dict(options) for section, options in cfg.user.setting.items()}
    other["speedometer"]["font_size"] = 99
    other["speedometer"]["update_interval"] = 123
    other["speedometer"]["position_x"] = 555
    write_preset("other.json", other)
    reloads = []
    monkeypatch.setattr(preset_compare.loader, "reload", lambda **kwargs: reloads.append(kwargs))
    page.refresh()
    panel_backend = page.backend.compare
    panel_backend.start("other.json")
    wait(lambda: panel_backend.loading)
    panel_backend.other = other
    panel_backend.reloads = reloads
    return panel_backend


def keys(compare) -> list[str]:
    return [row["key"] for row in compare.model.rows]


def test_compare_lists_differences_without_positions(compare):
    assert compare.presetA == "default.json" and compare.presetB == "other.json"
    assert "speedometer/font_size" in keys(compare) and "speedometer/position_x" not in keys(compare)
    row = compare.model.rows[keys(compare).index("speedometer/font_size")]
    assert row["valueB"] == "99" and row["label"] and row["sectionLabel"]
    compare.setIgnorePositions(False)
    assert "speedometer/position_x" in keys(compare)
    count = compare.diffCount
    compare.setFilter("update interval")
    assert compare.shownCount == count  # applied once typing pauses
    wait(lambda: compare.shownCount == count and compare.diffCount > 1)
    assert keys(compare) == ["speedometer/update_interval"]
    compare.setPresetB("default.json")
    assert compare.samePreset and compare.diffCount == 0


def test_compare_copy_refused_to_locked_preset(compare):
    cfg.user.filelock["other.json"] = {"version": "1.0"}
    compare.setSelected("speedometer/font_size", True)
    assert compare.selectedCount == 1
    assert compare.copySelected(False) == "Changes to locked preset will not be saved."
    assert not compare.modified


def test_compare_save_keeps_changes_made_meanwhile(compare, ui_env):
    compare.setSelected("speedometer/font_size", True)
    assert compare.copySelected(True) == ""  # B -> A (loaded preset)
    assert compare.modified and compare.copiedCount == 1 and "speedometer/font_size" not in keys(compare)
    compare.setSelected("speedometer/update_interval", True)
    assert compare.copySelected(False) == ""  # A -> B (other preset file)
    # Changed after panel opened: overlay moved in loaded preset, other preset edited elsewhere
    cfg.user.setting["speedometer"]["position_x"] = 777
    other = compare.other
    other["speedometer"]["font_size"] = 55
    write_preset("other.json", other)
    assert compare.save() == ""
    assert cfg.user.setting["speedometer"]["font_size"] == 99  # copied value
    assert cfg.user.setting["speedometer"]["position_x"] == 777  # kept
    assert "setting" in ui_env and compare.reloads == [{"reload_preset": True}]
    with open(f"{cfg.path.settings}other.json", encoding="utf-8") as file:
        saved = json.load(file)["speedometer"]
    assert saved["update_interval"] == cfg.user.setting["speedometer"]["update_interval"]  # copied value
    assert saved["font_size"] == 55  # kept
    assert not compare.modified


def test_compare_select_shown_and_discard(compare):
    compare.selectShown(True)
    assert compare.selectedCount == compare.shownCount > 0
    assert all(row["chosen"] for row in compare.model.rows)
    compare.selectShown(False)
    assert compare.selectedCount == 0
    compare.setSelected("speedometer/font_size", True)
    compare.copySelected(True)
    assert compare.modified
    compare.discard()
    wait(lambda: compare.loading)
    assert not compare.modified and "speedometer/font_size" in keys(compare)  # read again
    compare.stop()
    assert compare.diffCount == 0


# --- Plain logic reused by the panels
def test_option_types_and_copy_rules():
    from neopedal.ui.preset_management import OPTION_TYPES, copy_preset_options, option_type

    assert option_type("enable") == "enable_state"
    assert option_type("position_x") == "position" and option_type("font_size") == "font"
    assert option_type("update_interval") == "update_interval" and option_type("whatever") == "other_options"
    assert set(OPTION_TYPES) >= {option_type(name) for name in ("enable", "opacity", "layout", "decimal_places")}
    source = {"speedometer": {"enable": True, "font_size": 30, "position_x": 5}, "fuel": {"font_size": 40}}
    dest = {"speedometer": {"enable": False, "font_size": 10, "position_x": 1}, "fuel": {"font_size": 12}}
    assert copy_preset_options(source, dest, ["speedometer"], ["font"]) == 1
    assert dest == {"speedometer": {"enable": False, "font_size": 30, "position_x": 1}, "fuel": {"font_size": 12}}


def test_plain_messages_for_qml():
    from neopedal.ui.quick.preset_tools_backend import plain

    assert plain("Preset <b>a &amp; b</b> moved<br><br>to trash") == "Preset a & b moved to trash"


def test_delete_toast_offers_undo(page):
    assert page.delete_preset("practice.json")
    text, error, undo = page.toasts[-1]
    assert text == "Preset practice moved to trash" and not error and undo
    page.backend.undoDelete()
    assert os.path.exists(f"{cfg.path.settings}practice.json")
    assert page.toasts[-1][0] == "Preset restored: practice"


def test_restore_mode_of_name_box(page):
    backend = page.backend
    write_preset("race.json.backup-2026-10-03-12-00-00-000000", {"speedometer": {"enable": False}})
    assert backend.applyName("restore", "gone.json.backup-x", "x") == "Preset not found, it may have been renamed or deleted."
    assert backend.nameError("restore", "race.json.backup-2026-10-03-12-00-00-000000", "race") == "Preset already exists."
    assert backend.suggestName("restore", "race.json.backup-2026-10-03-12-00-00-000000") == "race (2)"
    assert backend.applyName("restore", "race.json.backup-2026-10-03-12-00-00-000000", "race old") == ""
    assert os.path.exists(f"{cfg.path.settings}race old.json") and backend.selectedKey == "race old.json"
