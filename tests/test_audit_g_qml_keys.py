"""Audit G (QML keys & bindings): segmented controls keep caller bindings, keys of track map pages & lap viewer
side map, preset name dialog focus, number fields (decimals, invalid mark), settings navigation kept, calculator
tab underline, math channel check after insert, session hover bubble, XY tab restored in one computation"""

import math

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QUrl
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest

from neopedal.setting import cfg
from tests.test_lap_viewer_features import laps  # noqa: F401
from tests.test_lap_viewer_fix_qml import (  # noqa: F401
    center_of,
    chart_of,
    evaluate,
    find,
    focused,
    items,
    key,
    named,
    opener,
    track_maps,
    wait,
    warnings,
)


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def inside(item, expression: str):
    """Expression evaluated in the QML file context of item (ids of that file)"""
    run = QQmlExpression(QQmlEngine.contextForObject(item), item, expression)
    value, _undefined = run.evaluate()
    assert not run.hasError(), f"{expression}: {run.error().toString()}"
    return value


def has_property(item, name: str) -> bool:
    return item.metaObject().indexOfProperty(name) >= 0


# --- Small QML components loaded alone (theme & i18n of app)
@pytest.fixture
def component(ui_env, tmp_path):
    from PySide6.QtQuickWidgets import QQuickWidget

    from neopedal.ui.quick import Theme, Translator, qml_folder_imports, register_types, theme_copy

    register_types()
    views = []

    def loading(body: str):
        wrapper = tmp_path / f"wrapper{len(views)}.qml"
        wrapper.write_text(f'import QtQuick\n{qml_folder_imports()}\n{body}\n',
                           encoding="utf-8")
        view = QQuickWidget()
        views.append(view)
        view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        context = view.rootContext()
        context.setContextProperty("theme", theme_copy(view.engine(), Theme(view)))
        context.setContextProperty("i18n", Translator(view))
        view.setSource(QUrl.fromLocalFile(str(wrapper)))
        assert not view.errors(), [error.toString() for error in view.errors()]
        view.resize(600, 120)
        view.show()
        view.activateWindow()
        view.setFocus()
        QCoreApplication.processEvents()
        return view

    yield loading
    for view in views:
        view.close()
        view.setSource(QUrl())
        view.deleteLater()
    flush()


def child(view, name: str):
    return view.rootObject().findChild(object, name)


def option_items(segmented) -> list:
    """Option items of a TpSegmented (row children made by its repeater)"""
    row = next(item for item in segmented.childItems() if "Row" in item.metaObject().className())
    return sorted((item for item in row.childItems() if item.width() > 0), key=lambda item: item.x())


def click(view, item):
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center_of(item))
    QCoreApplication.processEvents()


# --- 4: picking an option never replaces the caller's currentIndex binding
def test_segmented_keeps_caller_binding(component):
    view = component('''Column {
    property int value: 0
    property int chosen: -1
    width: 600; height: 120
    TpSegmented { objectName: "bound"; options: ["A", "B", "C"]; currentIndex: parent.value
                  onActivated: function(index) { parent.value = index } }
    TpSegmented { objectName: "refused"; options: ["A", "B", "C"]; currentIndex: 1
                  onActivated: function(index) { parent.chosen = index } }
}''')
    root = view.rootObject()
    bound, refused = child(view, "bound"), child(view, "refused")
    click(view, option_items(bound)[2])
    assert root.property("value") == 2 and bound.property("currentIndex") == 2
    root.setProperty("value", 0)  # changed by code afterwards: highlight follows (binding kept)
    assert bound.property("currentIndex") == 0
    bound.forceActiveFocus()
    QTest.keyClick(view, Qt.Key.Key_Right)
    QTest.keyClick(view, Qt.Key.Key_End)
    assert root.property("value") == 2 and bound.property("currentIndex") == 2
    root.setProperty("value", 1)
    assert bound.property("currentIndex") == 1
    # Caller keeping its own index (choice refused): highlight stays
    click(view, option_items(refused)[0])
    assert root.property("chosen") == 0 and refused.property("currentIndex") == 1


def test_lap_viewer_tabs_follow_backend_after_click(opener, warnings):  # noqa: F811
    dialog = opener()
    dialog.resize(1900, 800)  # side panel wide enough for its six tabs (narrower: drop-down list instead)
    wait(0.4)
    view, backend = dialog.view, dialog.backend
    segmented = find(view, lambda item: has_property(item, "options") and has_property(item, "squeezed"))
    tabs = next(item for item in segmented if evaluate(view, item, "options.length") == 6)
    mode = named(view, "viewMode")
    click(view, option_items(tabs)[1])  # G circle
    wait(0.3)
    assert backend.sideTab == 1 and tabs.property("currentIndex") == 1
    backend.setSideTab(0)  # by code (markers set...): highlight follows, no workaround needed
    wait(0.2)
    assert tabs.property("currentIndex") == 0
    backend.setSimpleView(False)
    wait(0.2)
    click(view, option_items(mode)[0])
    wait(0.4)
    assert backend.simpleView and mode.property("currentIndex") == 0
    backend.setSimpleView(False)
    wait(0.2)
    assert mode.property("currentIndex") == 1


# --- 15: number shown again with new decimals (value told before its decimals)
def test_number_field_reformats_when_decimals_change(component):
    view = component('NumberField { objectName: "number"; value: 2; decimals: 0 }')
    field = view.rootObject()
    assert field.property("text") == "2"
    field.setProperty("value", 1.5)
    assert field.property("text") == "2"  # no decimals yet
    field.setProperty("decimals", 1)
    assert field.property("text") == "1.5"
    field.setProperty("decimals", 2)
    assert field.property("text") == "1.50"


# --- 18 & 58: track map viewer keys: left / right step position, Shift moves map, sliders never take them
@pytest.fixture
def map_viewer(ui_env):
    from neopedal.ui.track_map_viewer import TrackMapViewer
    from tests.test_track_map_viewer import wait_jobs, write_map

    write_map(cfg.path.track_map)
    dialog = TrackMapViewer(None, cfg.path.track_map, "Ring")
    dialog.resize(900, 700)
    wait_jobs(dialog.backend)
    dialog.show()
    dialog.view.setFocus()
    wait(0.3)
    yield dialog
    dialog.close()
    flush()


def test_track_map_viewer_arrow_keys(map_viewer):
    view, backend = map_viewer.view, map_viewer.backend
    root = view.rootObject()
    canvas = find(view, lambda item: item.property("targetZoom") is not None)[0]
    sliders = find(view, lambda item: "Slider" in item.metaObject().className() and item.property("stepSize") is not None)
    assert len(sliders) >= 2
    assert all(slider.property("focusPolicy") == Qt.FocusPolicy.TabFocus.value for slider in sliders)  # Tab only
    click(view, sliders[-1])  # position slider clicked: keys stay on page
    wait(0.2)
    assert focused(view) is root
    backend.setPosition(500)
    evaluate(view, canvas, "setView(4, 0, 0, false)")  # zoomed: map can move
    wait(0.2)
    pan = canvas.property("targetPanX")
    key(view, Qt.Key.Key_Right)
    assert backend.position > 500 and canvas.property("targetPanX") == pan  # position stepped, map kept
    position = backend.position
    key(view, Qt.Key.Key_Left)
    assert backend.position < position
    position = backend.position
    key(view, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)  # Shift: map moved, position kept
    assert backend.position == position and canvas.property("targetPanX") != pan
    pan = canvas.property("targetPanX")
    key(view, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)
    assert backend.position == position and canvas.property("targetPanX") != pan


# --- 19: keys the clicked side map leaves go to charts (Space plays, A marker)
def test_side_map_leaves_keys_to_charts(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.setSideTab(0)
    wait(0.3)
    chart = chart_of(view)
    side_map = track_maps(view, False)[0]
    side_map.forceActiveFocus()
    wait(0.1)
    assert focused(view) is side_map
    key(view, Qt.Key.Key_Space)
    assert chart.property("playing") and focused(view) is side_map
    key(view, Qt.Key.Key_Space)
    assert not chart.property("playing")
    key(view, Qt.Key.Key_A)
    assert not math.isnan(chart.property("markerA"))
    key(view, Qt.Key.Key_M)  # map keys still the map's own: ruler
    assert side_map.property("rulerMode")
    key(view, Qt.Key.Key_Escape)  # Esc: ruler ended by map, not markers cleared by charts
    assert not side_map.property("rulerMode") and not math.isnan(chart.property("markerA"))
    key(view, Qt.Key.Key_Escape)
    assert dialog.isVisible() and focused(view) is chart


# --- 48: corner label near right edge of map placed left of its corner
def test_corner_label_kept_inside_map(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.setSideTab(0)
    wait(0.3)
    container = named(view, "cornerLabels")
    labels = [item for item in container.childItems() if item.property("selected") is not None and item.isVisible()]
    if not labels:
        pytest.skip("no corner label shown")
    canvas = find(view, lambda item: item.property("targetZoom") is not None and item.property("feet") is not None)[0]
    label = labels[0]
    anchor = label.property("anchorX")
    assert label.x() == pytest.approx(anchor + 6)  # room on the right: right of corner
    # Map moved so the corner is 10 px from the right edge
    move = canvas.width() - 10 - (container.x() + anchor)
    evaluate(view, canvas, f"setView(targetZoom, targetPanX + {move}, targetPanY, false)")
    wait(0.2)
    assert container.x() + anchor == pytest.approx(canvas.width() - 10, abs=0.5)
    assert label.x() == pytest.approx(anchor - 6 - label.width())
    assert container.x() + label.x() + label.width() <= canvas.width()


# --- 49: hover bubble of session chart never shown for a lap that is not there
def test_session_hover_bubble_out_of_range(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.setSideTab(4)
    wait(0.8)
    session = find(view, lambda item: has_property(item, "hoverIndex") and has_property(item, "sessionState"))[0]
    bubble = next(item for item in items(session) if has_property(item, "lap") and not has_property(item, "grow"))
    count = len(evaluate(view, session, "laps"))
    session.setProperty("hoverIndex", count + 5)
    wait(0.1)
    assert not bubble.isVisible()
    session.setProperty("hoverIndex", 0)
    evaluate(view, session, "refresh()")  # laps read again: hovered lap dropped
    assert session.property("hoverIndex") == -1


# --- 50: XY tab choices restored, one computation for them (none with a default choice)
def test_xy_tab_restored_in_one_update(opener, warnings, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import lap_backend

    dialog = opener()
    backend = dialog.backend
    backend.setXyState("histogram", "steering", "accel_long", "brake")
    asked = []
    original = lap_backend.LapViewerBackend.xy_samples

    def spy(self, column, lap):
        asked.append(column)
        return original(self, column, lap)

    monkeypatch.setattr(lap_backend.LapViewerBackend, "xy_samples", spy)
    backend.setSideTab(5)
    wait(0.8)
    xy = find(dialog.view, lambda item: has_property(item, "histogramColumn"))[0]
    assert xy.property("mode") == "histogram" and xy.property("histogramColumn") == "brake"
    assert set(asked) == {"brake"}  # never the default channel of a half restored state
    assert len(asked) == len(backend.data.laps)  # one histogram (no later refresh for restored channels)


# --- 59: channel name inserted in expression checked again (Save & Enter use its error): TextField.insert()
# sends textEdited (Qt 6.11), the field check runs without a call of its own
def test_math_channel_checked_after_insert(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    editor = view.rootObject().findChild(QObject, "mathEditor")
    evaluate(view, editor, "open()")
    wait(0.4)
    evaluate(view, editor, 'edit({"name": "Test Channel", "expression": "", "unit": ""})')
    evaluate(view, editor, "check()")
    assert editor.property("error") != ""  # no expression yet
    name = backend.math.inputs[0]
    assert backend.math.check("", "Test Channel", name) == ""
    evaluate(view, editor, f'insert("{name}")')
    assert editor.property("error") == ""
    evaluate(view, editor, "close()")
    wait(0.3)


# --- 5: name dialog opened from the preset menu keeps focus (Enter there, preset of list never loaded)
@pytest.fixture
def presets_page(ui_env, monkeypatch):

    from PySide6.QtWidgets import QMessageBox

    from neopedal.ui import preset_view
    from tests.test_preset_view import wait_read, write_preset

    write_preset("race.json", age=3600)
    write_preset("practice.json", {"speedometer": {"enable": False}}, age=60)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: pytest.fail(f"warning: {args}")))
    monkeypatch.setattr(preset_view, "show_toast", lambda *args, **kwargs: None)
    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(cfg.filename, "setting", "default.json")
    cfg.user.filelock = {}
    widget = preset_view.PresetList(None)
    widget.backend.set_active(True)
    wait_read(widget)
    widget.resize(1200, 760)
    widget.show()
    widget.view.setFocus()
    wait(0.4)
    yield widget
    widget.close()
    widget.deleteLater()
    flush()


@pytest.mark.parametrize("action", ["Duplicate…", "Rename…"])
def test_preset_name_dialog_keeps_focus(presets_page, action):
    view, backend = presets_page.view, presets_page.backend
    root = view.rootObject()
    menu = inside(root, "rowMenu")
    inside(root, 'openMenu(presets, 20, 20, "race.json")')
    wait(0.4)
    entries = [inside(menu, f"rowMenu.itemAt({index})") for index in range(inside(menu, "rowMenu.count"))]
    entry = next(item for item in entries if item is not None and str(item.property("text")).startswith(action))
    click(view, entry)
    wait(0.6)  # menu closed after its exit transition
    name_field = inside(root, "nameField")
    assert inside(root, "nameDialog.visible") and name_field.property("activeFocus")
    QTest.keyClick(view, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)  # typed in dialog field
    QTest.keyClick(view, Qt.Key.Key_Escape)  # dialog closed: list has keys again
    wait(0.4)
    assert not inside(root, "nameDialog.visible") and inside(root, "presets.activeFocus")
    assert cfg.filename.setting == "default.json" and backend.selectedKey == "race.json"


# --- 16: number typed out of range, clamped back to the value shown: invalid mark cleared (Apply enabled)
@pytest.fixture
def settings_window(ui_env, monkeypatch):

    from contextlib import suppress

    from PySide6.QtWidgets import QSystemTrayIcon

    from neopedal import app_signal, loader
    from neopedal.ui import app as app_module

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    monkeypatch.setattr(loader, "reload", lambda **kwargs: None)
    monkeypatch.setattr(loader, "restart", lambda *args, **kwargs: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    main = app_module.AppWindow()
    main.resize(1300, 900)
    main.show()
    yield main
    for page in main.centralWidget().dialog_pages():
        if page.dialog is not None:
            backend = getattr(page.dialog, "backend", None)
            if backend is not None and hasattr(backend, "discard"):
                backend.discard()
            page.dialog.close()
    tray = main.findChild(QSystemTrayIcon)
    if tray:
        tray.hide()
    for signal in (app_signal.hotkey, app_signal.refresh, app_signal.quitapp, app_signal.reload, app_signal.updates):
        with suppress(RuntimeError, TypeError):
            signal.disconnect()
    main.deleteLater()
    flush()


def number_row(backend, view) -> tuple[dict, object]:
    """First number option shown with a range, and its number field"""
    for row in backend.model.rows:
        if row["kind"] != "integer" or row["maximum"] <= row["minimum"] or row["maximum"] > 1e6:
            continue
        rows = find(view, lambda item, key=row["key"]: item.property("key") == key and has_property(item, "error"))
        fields = [item for found in rows for item in items(found) if has_property(item, "suffix")]
        if fields and fields[0].isVisible():
            return row, fields[0]
    pytest.skip("no number option shown")


def test_invalid_number_cleared_when_clamped_to_shown_value(settings_window):
    from neopedal.ui.menu import open_config_application

    page = open_config_application(settings_window)
    wait(0.5)
    view, backend = page.view, page.backend
    row, field = number_row(backend, view)
    key_name, maximum, decimals = row["key"], row["maximum"], row["decimals"]
    backend.setNumber(key_name, maximum)
    backend.apply()  # maximum saved: shown value
    wait(0.3)
    assert backend.pendingCount == 0 and field.property("value") == maximum
    field.forceActiveFocus()
    QTest.keyClick(view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(view, str(int(maximum * 10 + 10)))  # out of range while typing: marked
    wait(0.1)
    assert backend.errorCount == 1
    QTest.keyClick(view, Qt.Key.Key_Return)  # clamped to maximum: same as shown, mark cleared
    wait(0.2)
    assert backend.errorCount == 0 and backend.pendingCount == 0
    shown = f"{maximum:.{decimals}f}" if decimals > 0 else str(round(maximum))
    assert field.property("text") == shown


# --- 55: settings navigation kept while typing (no model reset: scroll & delegates kept)
def test_settings_navigation_kept_while_typing(settings_window):
    from neopedal.ui.menu import open_config_application

    page = open_config_application(settings_window)
    wait(0.5)
    view, backend = page.view, page.backend
    root = view.rootObject()

    def entries() -> list:
        return [item for item in items(nav) if has_property(item, "info") and has_property(item, "dimmed")]

    lists = find(view, lambda item: "ListView" in item.metaObject().className())
    nav = next(item for item in lists if any(has_property(child, "dimmed") for child in items(item)))
    assert nav.property("count") == len(root.property("categories"))
    entries()[0].setProperty("auditKept", True)  # dynamic property: gone if delegate made again
    row, _field = number_row(backend, view)
    low, high = int(row["minimum"]), int(row["maximum"])
    typed = [value for value in (low, low + 1, high - 1, high) if value != row["number"]][:2]
    for value in typed:  # keys typed: pending count of category changed (new list each time)
        backend.typeText(row["key"], str(value))
        wait(0.1)
    wait(0.3)  # counts & categories follow typing after TYPING_REFRESH_MS (150 ms, audit PERF-066)
    shown = {entry["key"]: entry["changed"] for entry in root.property("categories")}
    assert shown[backend.category] == 1  # badge of category updated
    assert len([item for item in entries() if item.property("auditKept")]) == 1  # delegate kept, not rebuilt
    selected = [item for item in entries() if item.property("selected")]
    assert len(selected) == 1 and selected[0].property("info")["key"] == backend.category
    backend.discard()


# --- 57: calculator tab underline under current tab from the start
def test_calculator_tab_underline_at_start(ui_env, monkeypatch):
    from neopedal.module_info import minfo
    from neopedal.ui import race_calculator

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    dialog = race_calculator.RaceCalculator(None)
    try:
        dialog.resize(1200, 800)
        dialog.show()
        wait(0.4)
        view = dialog.view
        underline = find(view, lambda item: has_property(item, "target") and item.height() == 2)
        assert underline and underline[0].property("target") is not None and underline[0].width() > 0
        dialog.backend.setTab(2)
        wait(0.6)
        target = underline[0].property("target")
        assert underline[0].x() == pytest.approx(target.x(), abs=0.5)
    finally:
        dialog.set_unmodified()
        dialog.close()
        flush()
