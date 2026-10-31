"""UI/UX audit 2026-10-29, destructive actions & feedback lot (D1, D4, D5, D6, D8, V10): one rule for deletions
(reversible: Undo toast & Ctrl+Z, never confirmed; irreversible: red confirmation), number input in the page, menu
shortcut texts, context menu key, last folder of file pickers, tooltip of disabled buttons"""


import os
import sys

import pytest
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest

from tests.test_driver_stats_viewer import OREGA, SPA, backend, dialogs, load_stats, window  # noqa: F401
from tests.test_driver_stats_viewer import settle as stats_settle
from tests.test_game_info import replays_page  # noqa: F401
from tests.test_ui_audit_2026_10_29_foundations import bridged, named, page, settle  # noqa: F401


# --- D6: number input in the page
def test_number_input_in_page_clamped_and_queued(bridged):  # noqa: F811
    from neopedal.ui.quick import dialogs as page_dialogs

    _view, root, bridge, host = bridged
    numbers = []
    page_dialogs.ask_number(host, "Keep Latest Replays", "Number of latest replays kept:", numbers.append, 20, 1, 1000)
    settle()
    dialog, number = named(root, "bridgeDialog"), named(root, "bridgeNumber")
    assert dialog.property("visible") and number.property("visible") and number.property("text") == "20"
    assert not named(root, "bridgeField").property("visible")
    number.setProperty("text", "abc")
    named(root, "host").accept()
    settle()
    assert dialog.property("visible") and bridge.pending == 1 and numbers == []  # not a number: kept open
    number.setProperty("text", "5000")
    named(root, "host").accept()
    QTest.qWait(250)
    settle()
    assert numbers == [1000] and isinstance(numbers[0], int) and bridge.pending == 0  # put back in range
    page_dialogs.ask_number(host, "Offset", "Offset:", numbers.append, 1.5, 0, 10, decimals=1)
    settle()
    assert number.property("text") in ("1.5", "1,5")
    number.setProperty("text", "2,25")  # decimal comma
    named(root, "host").accept()
    QTest.qWait(250)
    settle()
    assert numbers[-1] == 2.2 or numbers[-1] == 2.3


@pytest.mark.skipif(os.environ.get("CI") == "true" and sys.platform == "win32",
                    reason="GitHub Windows runner: popup menus & keyboard focus behave differently there (offscreen); checked locally")
def test_number_input_keys_step_enter_and_escape(bridged):  # noqa: F811
    from neopedal.ui.quick import dialogs as page_dialogs

    view, root, bridge, host = bridged
    view.window().show()
    view.window().activateWindow()
    numbers = []
    page_dialogs.ask_number(host, "Go to lap", "Lap of <b>A</b>:", numbers.append, 3, 1, 9)
    QTest.qWait(250)
    settle()
    number = named(root, "bridgeNumber")
    assert number.property("activeFocus")
    QTest.keyClick(view, Qt.Key.Key_Up)
    settle()
    assert number.property("text") == "4"
    QTest.keyClick(view, Qt.Key.Key_Return)
    QTest.qWait(250)
    settle()
    assert numbers == [4] and bridge.pending == 0
    page_dialogs.ask_number(host, "Go to lap", "Lap:", numbers.append, 3, 1, 9)
    QTest.qWait(250)
    settle()
    QTest.keyClick(view, Qt.Key.Key_Escape)  # cancels the dialog, never accepted
    QTest.qWait(250)
    settle()
    assert numbers == [4] and bridge.pending == 0 and not named(root, "bridgeDialog").property("visible")


def test_number_input_without_host_or_patched(page, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QInputDialog

    from neopedal.ui.quick import dialogs as page_dialogs

    view, _root, _warnings = page("    Item {}")
    asked, numbers = [], []
    monkeypatch.setattr(QInputDialog, "getInt", lambda *args: asked.append(args) or (7, True))
    page_dialogs.ask_number(view.parentWidget(), "Days", "Days:", numbers.append, 30, 1, 3650)
    assert numbers == [7] and asked[0][3:] == (30, 1, 3650)
    monkeypatch.setattr(QInputDialog, "getDouble", lambda *args: (0.5, False))  # cancelled
    page_dialogs.ask_number(view.parentWidget(), "Gap", "Gap:", numbers.append, 1.0, 0, 5, decimals=2)
    assert numbers == [7]


def test_patched_number_input_wins_over_the_page(bridged, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QInputDialog

    from neopedal.ui.quick import dialogs as page_dialogs

    _view, _root, bridge, host = bridged
    numbers = []
    monkeypatch.setattr(QInputDialog, "getInt", lambda *args: (12, True))
    page_dialogs.ask_number(host, "Days", "Days:", numbers.append, 30, 1, 3650)
    assert numbers == [12] and bridge.pending == 0


# --- D8: tooltip of disabled buttons, shortcut texts of buttons & menu entries
def test_disabled_button_tooltip_shown_on_hover(page):  # noqa: F811
    view, root, warnings = page('''
    property bool tipShown: disabledButton.ToolTip.visible
    property string tipText: disabledButton.ToolTip.text
    property string saveTipText: saveButton.ToolTip.text
    Row {
        x: 100; y: 100; spacing: 40
        TpButton {
            id: disabledButton; objectName: "disabledButton"; text: "Apply"; enabled: false
            tip: "Apply changes"; disabledTip: "Nothing to apply: change an option first"
        }
        TpButton { id: saveButton; objectName: "saveButton"; text: "Save"; shortcut: "Ctrl+S" }
    }
''')
    view.window().show()
    button = named(root, "disabledButton")
    QTest.mouseMove(view, button.mapToScene(button.boundingRect().center()).toPoint())
    QTest.qWait(1200)  # tooltip delay
    settle()
    assert root.property("tipShown") and root.property("tipText") == "Nothing to apply: change an option first"
    assert button.property("hovered")  # Qt 6 Controls: disabled buttons are hovered too
    button.setProperty("enabled", True)
    settle()
    assert root.property("tipText") == "Apply changes"
    save = named(root, "saveButton")
    QTest.mouseMove(view, save.mapToScene(save.boundingRect().center()).toPoint())
    settle()
    assert save.property("hovered") and root.property("saveTipText") == "Save  (Ctrl+S)"  # key after the text
    assert warnings == []


def test_menu_item_shortcut_right_aligned_and_dim(page):  # noqa: F811
    view, root, warnings = page('''
    TpButton { id: opener; objectName: "opener"; text: "More"; onClicked: menu.toggleBelow(opener) }
    TpMenu {
        id: menu
        objectName: "menu"
        TpMenuItem { objectName: "renameItem"; text: "Rename…"; shortcut: "F2" }
        TpMenuItem { objectName: "deleteItem"; text: "Delete"; shortcut: "Del" }
        TpMenuItem { objectName: "plainItem"; text: "Load" }
    }
''')
    menu = named(root, "menu")
    menu.setProperty("visible", True)
    QTest.qWait(250)
    settle()
    rename = named(root, "renameItem")
    keys = [item for item in rename.findChildren(QObject) if item.objectName() == "menuShortcut"]
    assert len(keys) == 1 and keys[0].property("text") == "F2" and keys[0].property("visible")
    theme = view.rootContext().contextProperty("theme")
    assert keys[0].property("color") == theme.property("dimText")
    assert "F2" not in rename.property("text")  # never in the label
    right = keys[0].mapToItem(rename, QPointF(keys[0].property("width"), 0)).x()
    assert right > rename.property("width") * 0.8  # at the right of the entry
    plain = named(root, "plainItem")
    assert not [item for item in plain.findChildren(QObject)
                if item.objectName() == "menuShortcut" and item.property("visible")]
    assert rename.property("implicitWidth") > plain.property("implicitWidth")  # room kept for the key
    assert warnings == []


# --- D1 / D4: reversible = Undo toast & Ctrl+Z, never confirmed
def test_tyre_plan_deletions_never_confirmed_undo_in_toast(ui_env, monkeypatch):
    """Delete Row, Remove from Stock, Remove All, Proposed changes & New plan: done at once (undo history), toast
    with Undo, one wording per object (row: delete, stock: remove, wheel: take off)"""
    from neopedal.module_info import minfo
    from neopedal.setting import cfg
    from neopedal.ui import race_calculator
    from tests.test_race_calculator import Host

    found = Host()
    undo_toasts = []
    monkeypatch.setattr(race_calculator.RaceCalculator, "warn", lambda self, text: found.warnings.append(text))
    monkeypatch.setattr(race_calculator.RaceCalculator, "toast", lambda self, text: found.toasts.append(text))
    monkeypatch.setattr(race_calculator.RaceCalculator, "toast_undo", lambda self, text: undo_toasts.append(text))
    monkeypatch.setattr(race_calculator.RaceCalculator, "confirm", lambda self, text: found.asked.append(text) or True)
    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    monkeypatch.setitem(cfg.user.config["fuel_calculator"], "show_quick_setup", False)
    calculator = race_calculator.RaceCalculator(None)
    try:
        monkeypatch.setitem(cfg.user.config["fuel_calculator"], "enable_game_data", True)  # calculator on: undo kept
        backend = calculator.backend
        backend.newTyrePlan()
        backend.setStockCompound("Soft")
        backend.addTyre()
        backend.addTyre()
        backend.addRow()
        backend.addRow()
        backend.assignTyre(0, 0, "Soft #1")
        calculator.record_change()
        rows = len(backend.tyres.rows)
        backend.deleteRow(rows - 1)
        assert len(backend.tyres.rows) == rows - 1 and undo_toasts[-1] == "Row deleted"
        calculator.undo()
        assert len(backend.tyres.rows) == rows
        backend.removeTyre("Soft #1")
        assert backend.tyres.stock == ["Soft #2"] and backend.tyres.rows[0][0] == ""
        assert undo_toasts[-1] == "<b>Soft #1</b> removed from stock"
        calculator.undo()  # Undo of the toast (= Ctrl+Z): tyre back in stock & on its wheel
        assert backend.tyres.stock == ["Soft #1", "Soft #2"] and backend.tyres.rows[0][0] == "Soft #1"
        backend.clearTyres()
        assert not backend.tyres.stock and undo_toasts[-1] == "All tyres removed from stock"
        calculator.undo()
        assert len(backend.tyres.stock) == 2
        backend.newTyrePlan()
        assert not backend.tyres.stock and undo_toasts[-1] == "New tyre plan started"
        calculator.undo()
        assert len(backend.tyres.stock) == 2
        assert found.asked == []  # never a confirmation
    finally:
        calculator.set_unmodified()
        calculator.close()
        calculator.deleteLater()
    with open(os.path.join("neopedal", "ui", "qml", "analysis", "RaceTyreTab.qml"), encoding="utf-8") as file:
        source = file.read()
    assert 'i18n.tr("Remove Tyre")' not in source and 'i18n.tr("Take Tyre Off")' in source
    assert 'i18n.tr("Clear All")' not in source and 'i18n.tr("Remove All from Stock")' in source
    assert 'i18n.tr("Delete: remove from stock")' not in source


def test_overlays_page_ctrl_z_undoes_switches_batch_and_moves(ui_env):
    from neopedal.setting import cfg
    from neopedal.ui.quick.overlay_backend import OverlayBackend
    from tests.test_overlay_view import FakeControl

    control = FakeControl(("brake_wear", "fuel", "relative"))
    for name in control.names:
        cfg.user.setting[name]["enable"] = name == "relative"
    overlays = OverlayBackend(None, control, lambda name: None, lambda text: False)
    try:
        assert not overlays.canUndo
        overlays.toggle("fuel")
        assert cfg.user.setting["fuel"]["enable"] and overlays.canUndo
        overlays.enableShown()
        assert all(cfg.user.setting[name]["enable"] for name in control.names)
        overlays.undo()  # Ctrl+Z: last change first (batch switch)
        assert [name for name in control.names if cfg.user.setting[name]["enable"]] == ["fuel", "relative"]
        overlays.undo()  # then the switch
        assert [name for name in control.names if cfg.user.setting[name]["enable"]] == ["relative"]
        assert not overlays.canUndo
        overlays.undo()  # nothing left: nothing done
        overlays.enableShown()
        overlays.undoBulk()  # Undo of its toast: that change only, once
        overlays.undo()
        assert [name for name in control.names if cfg.user.setting[name]["enable"]] == ["relative"]
    finally:
        overlays.deleteLater()


def test_overlays_page_has_ctrl_z_shortcut(ui_env):
    from PySide6.QtGui import QKeySequence, QShortcut

    from neopedal.ui.overlay_view import OverlayView

    view = OverlayView(None)
    try:
        shortcuts = [item for item in view.findChildren(QShortcut)
                     if item.key() == QKeySequence(QKeySequence.StandardKey.Undo)]
        assert len(shortcuts) == 1 and shortcuts[0].context() == Qt.ShortcutContext.WidgetWithChildrenShortcut
    finally:
        view.deleteLater()


def test_whats_new_try_undone_by_ctrl_z(ui_env, monkeypatch):
    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtWidgets import QWidget

    from neopedal import module_control
    from neopedal.ui.quick.release_backend import ReleaseNotesBackend

    enabled = {"fuel": False, "relative": False}

    class Control:
        names = list(enabled)

        @staticmethod
        def set_enabled(names, state):
            for name in names:
                enabled[name] = state
            return True

    monkeypatch.setattr(module_control, "wctrl", Control())
    host = QWidget()
    notes = ReleaseNotesBackend(host, [], False, False, False, False, False)
    try:
        shortcut = next(item for item in host.findChildren(QShortcut)
                        if item.key() == QKeySequence(QKeySequence.StandardKey.Undo))
        assert not shortcut.isEnabled()
        notes.tryOverlay("fuel")
        notes.tryOverlay("relative")
        assert enabled == {"fuel": True, "relative": True} and shortcut.isEnabled()
        shortcut.activated.emit()  # Ctrl+Z: last Try first
        assert enabled == {"fuel": True, "relative": False}
        notes.undo_tried("relative")  # toast of a Try undone already: nothing
        notes.undoLastTry()
        assert enabled == {"fuel": False, "relative": False} and not shortcut.isEnabled()
    finally:
        notes.deleteLater()
        host.deleteLater()


def test_stats_edits_never_confirmed_undo_in_toast(backend, monkeypatch):  # noqa: F811
    """Delete Track, Remove Vehicle, Reset Lap Time: saved at once (undo history), toast with Undo (as Ctrl+Z)"""
    from neopedal.ui import toast as toast_module
    from neopedal.ui.quick import dialogs as page_dialogs

    asked, toasts = [], []
    monkeypatch.setattr(page_dialogs, "confirm", lambda *args, **kwargs: asked.append(args))
    monkeypatch.setattr(toast_module, "show_toast", lambda widget, text, **kwargs: toasts.append((text, kwargs)))
    backend.deleteTrack(SPA)
    stats_settle(backend)
    assert SPA not in load_stats() and not asked
    text, kwargs = toasts[-1]
    assert text == f"Stats of <b>{SPA}</b> deleted" and kwargs["action_text"] == "Undo"
    kwargs["action"]()  # Undo of the toast
    stats_settle(backend)
    assert SPA in load_stats()
    backend.selectTrack(SPA)
    backend.selectRow("Hyper - Ferrari")
    backend.removeVehicle()
    stats_settle(backend)
    assert "Hyper - Ferrari" not in load_stats()[SPA] and toasts[-1][0] == "Stats of <b>Hyper - Ferrari</b> removed"
    backend.resetLapTime(OREGA, "qb")
    stats_settle(backend)
    assert toasts[-1][0].startswith("Lap time <b>") and not asked
    backend.undo()  # Ctrl+Z
    stats_settle(backend)
    assert load_stats()[SPA][OREGA]["qb"] == 122.4


# --- D8: last folder of file pickers
def test_last_folder_of_pickers_kept_per_kind(ui_env, tmp_path):
    from PySide6.QtCore import QCoreApplication

    from neopedal.ui.quick import last_folder, page_settings

    first, second = tmp_path / "exports", tmp_path / "logos"
    first.mkdir()
    second.mkdir()
    assert last_folder.start_folder("test_export", str(tmp_path)) == str(tmp_path)  # nothing kept: default
    last_folder.remember("test_export", str(first / "lap.ld"))  # file: its folder
    last_folder.remember("test_logo", str(second))  # folder picker: the folder itself
    last_folder.remember("test_cancel", "")  # cancelled: nothing
    page_settings.flush_all(last_folder.FOLDERS_FILE)
    QCoreApplication.processEvents()
    assert last_folder.start_folder("test_export") == str(first)
    assert last_folder.start_path("test_logo", "logo.png") == os.path.join(str(second), "logo.png")
    assert last_folder.start_folder("test_cancel", "x") == "x"
    second.rmdir()  # folder gone since: default again
    assert last_folder.start_folder("test_logo", str(tmp_path)) == str(tmp_path)


def test_replays_inputs_asked_in_page(replays_page, monkeypatch):  # noqa: F811
    """Rename, Delete Older Than, Keep Latest & Go to lap: inputs of the page (TpDialogHost), not QInputDialog;
    deletions to the recycle bin confirmed in red (the app cannot undo them)"""
    from types import SimpleNamespace

    from neopedal.ui.quick import dialogs as page_dialogs
    from neopedal.ui.quick import replays_backend as rb

    replays = replays_page.backend
    asked, confirmed = [], []
    monkeypatch.setattr(page_dialogs, "ask_number", lambda parent, title, label, on_accept, value, low, high, **kw:
                        asked.append((title, value, low, high)) or on_accept(value))
    monkeypatch.setattr(page_dialogs, "confirm", lambda *args, **kwargs: confirmed.append(kwargs.get("danger")))
    monkeypatch.setattr(rb.QInputDialog, "getInt", lambda *args, **kwargs: pytest.fail("native input"))
    monkeypatch.setattr(replays, "replay_folder", lambda: "C:/replays")
    replays.replays = [rb.GameReplay(0, "Old", "", "", "", 1.0, 1), rb.GameReplay(1, "New", "", "", "", 2.0, 1)]
    replays.deleteOlderThan()
    replays.keepLatest()
    assert [entry[0] for entry in asked] == ["Delete Old Replays", "Keep Latest Replays"]
    assert confirmed == [True]  # Old (older than 30 days) confirmed in red; Keep Latest: nothing beyond 20
    monkeypatch.setattr(replays, "car_of", lambda key: SimpleNamespace(laps=2, driver="A <b>", slot=1))
    replays.state = rb.REPLAY
    sent = []
    monkeypatch.setattr(replays, "send", lambda *commands: sent.extend(commands))
    monkeypatch.setattr(replays, "selectCar", lambda key: None)
    replays.goToLap("1")
    assert asked[-1] == ("Go to lap", 3, 1, rb.MAX_GO_TO_LAP) and sent


# --- D8: context menu by keyboard (Menu key, Shift+F10), keys of menu entries at their right
def test_presets_menu_by_shift_f10_with_keys_at_the_right(ui_env, monkeypatch):
    from PySide6.QtCore import QCoreApplication

    from neopedal.setting import cfg
    from neopedal.ui import preset_view
    from tests.test_ui_audit_2026_10_29_config_presets import show, write_preset

    write_preset("race.json")
    write_preset("practice.json")
    monkeypatch.setattr(cfg.filename, "setting", "default.json")
    cfg.user.filelock = {}
    widget = preset_view.PresetList(None)
    try:
        widget.backend.set_active(True)
        root = show(widget)
        widget.activateWindow()
        presets = root.findChild(QObject, "presetList")
        presets.forceActiveFocus()
        presets.setProperty("currentIndex", 0)
        for _ in range(10):
            QCoreApplication.processEvents()
        items = {item.property("text"): item for item in root.findChildren(QObject)
                 if item.property("shortcut") is not None and item.metaObject().className().startswith("TpMenuItem")}
        delete, rename = items["Delete"], items["Rename…"]  # never "\tDel" / "\tF2" in the label
        assert delete.property("shortcut") == "Del" and rename.property("shortcut") == "F2"
        assert not delete.isVisible()  # menu closed
        QTest.keyClick(widget.view, Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
        QTest.qWait(250)
        assert delete.isVisible()  # menu of the current preset open
        QTest.keyClick(widget.view, Qt.Key.Key_Escape)
    finally:
        widget.close()
        widget.deleteLater()
