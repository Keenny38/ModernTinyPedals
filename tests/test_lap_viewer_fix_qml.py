"""Lap viewer page keys & charts: keys on charts when shown, combo boxes & sliders never keep them, Ctrl+Z of shown
page only, Esc never closes viewer, map focus mode keys, split sizes restored, playback stopped while hidden,
channel menu kept scrolled, axis labels, digit row of AZERTY keyboards"""

import contextlib
import os
import sys
import time

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, QPoint, QPointF, Qt, qInstallMessageHandler
from PySide6.QtGui import QKeyEvent
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest

from tests.test_lap_viewer import flush_deleted, wait_loaded, write_lap
from tests.test_lap_viewer_features import laps  # noqa: F401
from tinypedal.setting import cfg


def wait(seconds: float = 0.3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.005)


def items(root) -> list:
    stack, found = [root], []
    while stack:
        item = stack.pop()
        found.append(item)
        stack.extend(item.childItems())
    return found


def class_name(item) -> str:
    return item.metaObject().className()


def find(view, test) -> list:
    return [item for item in items(view.quickWindow().contentItem()) if test(item)]


def named(view, name: str):
    return find(view, lambda item: item.objectName() == name)[0]


def chart_of(view):
    return find(view, lambda item: item.property("lodTier") is not None)[0]


def track_maps(view, expanded: bool) -> list:
    return find(view, lambda item: item.property("rulerMode") is not None and item.property("expanded") is expanded)


def focused(view):
    return view.quickWindow().activeFocusItem()


def center_of(item, dx: float = 0.0) -> QPoint:
    point = item.mapToScene(QPointF(item.width() / 2 + dx, item.height() / 2))
    return QPoint(int(point.x()), int(point.y()))


def evaluate(view, scope, expression: str):
    return QQmlExpression(view.rootContext(), scope, expression).evaluate()[0]


def key(view, code, modifiers=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(view, code, modifiers)
    wait(0.15)


@contextlib.contextmanager
def no_qml_warnings():
    """QML warnings meanwhile: none expected"""
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        yield
    finally:
        qInstallMessageHandler(previous)
    qml = [text for text in messages if ".qml" in text or "Connections" in text or "TypeError" in text]
    assert not qml, qml


@pytest.fixture
def warnings():
    """QML warnings while test runs (until fixtures are torn down): none expected"""
    with no_qml_warnings():
        yield


@pytest.fixture
def opener(laps):  # noqa: F811
    from tinypedal.ui.lap_viewer import LapViewer

    dialogs = []

    def opening():
        dialog = LapViewer(None)
        dialogs.append(dialog)
        dialog.resize(1300, 800)
        wait_loaded(dialog)
        dialog.show()  # dialog gives focus to its first control (Tab reason)
        wait(0.4)
        return dialog

    yield opening
    for dialog in dialogs:
        if shiboken6.isValid(dialog):
            dialog.close()
    flush_deleted()


def test_window_keys_on_charts_track_box_never_keeps_them(opener, warnings):
    write_lap(cfg.path.telemetry.rstrip("/"), 1, 90.0)  # second track: arrow keys could switch track
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    chart = chart_of(view)
    assert focused(view) is chart and QCoreApplication.instance().focusWidget() is view
    track_box = named(view, "trackBox")
    assert track_box.property("focusPolicy") == Qt.FocusPolicy.NoFocus.value
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center_of(track_box))
    wait(0.4)
    key(view, Qt.Key.Key_Escape)  # popup closed
    wait(0.3)
    assert dialog.isVisible() and focused(view) is chart
    track = backend.currentTrack
    key(view, Qt.Key.Key_Down)
    assert backend.currentTrack == track
    key(view, Qt.Key.Key_Space)
    assert chart.property("playing")


def test_undo_shortcut_of_shown_page_only(laps, monkeypatch):  # noqa: F811
    from tinypedal.ui import app as app_module
    from tinypedal.ui.tools_view import open_tool

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    main = app_module.AppWindow()
    try:
        with no_qml_warnings():
            main.show()
            main.activateWindow()
            wait(0.3)
            open_tool("lap_viewer.LapViewer", main)
            wait(0.5)
            dialog = main.centralWidget().dialog_pages()[0].dialog
            wait_loaded(dialog)
            wait(0.2)
            backend = dialog.backend
            assert focused(dialog.view) is chart_of(dialog.view)  # page of app window: keys on charts too
            assert QCoreApplication.instance().focusWidget() is dialog.view
            assert not dialog.undo_shortcut.isEnabled()
            backend.deleteLap(laps[1])
            wait_loaded(dialog)
            assert not os.path.exists(laps[1]) and dialog.undo_shortcut.isEnabled()
            main.centralWidget().select_page(0)  # home page shown
            wait(0.3)
            QTest.keyClick(main, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
            wait(0.2)
            assert not os.path.exists(laps[1])  # lap viewer page hidden: its undo never runs
            open_tool("lap_viewer.LapViewer", main)
            wait(0.4)
            QTest.keyClick(main, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
            wait_loaded(dialog)
            assert os.path.exists(laps[1]) and backend.undoText == "" and not dialog.undo_shortcut.isEnabled()
    finally:
        for page in main.centralWidget().dialog_pages():
            if page.dialog is not None:
                page.dialog.close()
        main.deleteLater()
        flush_deleted()
        QCoreApplication.processEvents()


def test_escape_never_closes_viewer(opener, warnings):
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    chart = chart_of(view)
    side_map = track_maps(view, False)[0]
    side_map.forceActiveFocus()
    key(view, Qt.Key.Key_M)  # ruler: first Esc ends it
    assert side_map.property("rulerMode")
    key(view, Qt.Key.Key_Escape)
    assert not side_map.property("rulerMode") and focused(view) is side_map
    key(view, Qt.Key.Key_Escape)
    assert dialog.isVisible() and focused(view) is chart  # keys back to charts
    # Item without Esc handling: page takes it
    split = find(view, lambda item: "SplitView" in class_name(item))[0]
    split.forceActiveFocus()
    key(view, Qt.Key.Key_Escape)
    assert dialog.isVisible() and focused(view) is chart
    # Hysteresis slider & XY channel lists never take keys
    backend.setSideTab(2)
    wait(0.4)
    slider = find(view, lambda item: "Slider" in class_name(item) and item.property("from") == 3.0)[0]
    assert slider.property("focusPolicy") == Qt.FocusPolicy.NoFocus.value
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center_of(slider))
    wait(0.2)
    assert focused(view) is chart
    backend.setSideTab(5)
    wait(0.4)
    boxes = find(view, lambda item: item.property("textRole") == "title" and item.property("column") is not None)
    assert boxes and all(box.property("focusPolicy") == Qt.FocusPolicy.NoFocus.value for box in boxes)
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center_of(boxes[0]))
    wait(0.4)
    key(view, Qt.Key.Key_Escape)  # popup closed
    wait(0.3)
    assert dialog.isVisible() and focused(view) is chart


def test_map_focus_mode_keys(opener, warnings):
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    chart = chart_of(view)
    root = view.rootObject()
    root.setProperty("mapFocus", True)
    wait(0.5)
    large_map = track_maps(view, True)[0]
    assert focused(view) is large_map
    quarters = backend._map_quarters
    key(view, Qt.Key.Key_R)  # map turned, reference lap unchanged
    assert backend._map_quarters == (quarters + 1) % 4
    key(view, Qt.Key.Key_3)
    assert backend.mapMode == "speed"
    key(view, Qt.Key.Key_Space)  # keys map leaves: charts (playback)
    assert chart.property("playing")
    key(view, Qt.Key.Key_Space)
    assert not chart.property("playing")
    key(view, Qt.Key.Key_Escape)  # focus mode left
    wait(0.3)
    assert not root.property("mapFocus") and focused(view) is chart
    key(view, Qt.Key.Key_Space)
    assert chart.property("playing")
    key(view, Qt.Key.Key_Space)
    key(view, Qt.Key.Key_Escape)
    assert dialog.isVisible()


def test_split_sizes_restored(opener):
    with no_qml_warnings():
        dialog = opener()
        view = dialog.view
        lap_list = named(view, "lapList")
        width = lap_list.width()
        edge = lap_list.mapToScene(QPointF(lap_list.width(), lap_list.height() / 2))
        start = QPoint(int(edge.x()) + 4, int(edge.y()))  # split handle right of lap list
        QTest.mouseMove(view, start)
        QTest.mousePress(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        for step in range(1, 11):
            QTest.mouseMove(view, start + QPoint(step * 15, 0))
            wait(0.02)
        QTest.mouseRelease(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(150, 0))
        wait(0.3)
        dragged = lap_list.width()
        assert dragged > width + 100 and dialog.backend._layout
    dialog.close()
    flush_deleted()
    with no_qml_warnings():
        reopened = opener()
        assert named(reopened.view, "lapList").width() == pytest.approx(dragged, abs=2)


def test_playback_stops_when_page_hidden(opener):
    dialog = opener()
    chart = chart_of(dialog.view)
    QMetaObject.invokeMethod(chart, "togglePlay")
    wait(0.2)
    assert chart.property("playing")
    dialog.hide()  # page of app window left
    QCoreApplication.processEvents()
    assert not chart.property("playing")


def test_channel_menu_keeps_scroll_and_tells_no_match(opener, warnings):
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    button = find(view, lambda item: item.property("text") == "Channels")[0]
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center_of(button))
    wait(0.5)
    channels = named(view, "channelList")
    assert channels.property("count") == len(backend.channelMenu)
    channels.setProperty("contentY", 800.0)
    wait(0.2)
    target = next(row for row in backend.channelMenu[30:] if not row["visible"])
    backend.setChannelVisible(target["column"], True)
    wait(0.3)
    assert channels.property("contentY") == pytest.approx(800.0)  # list kept, not rebuilt
    row = next(item for item in items(channels) if item.property("column") == target["column"])
    assert row.property("shown")
    empty = find(view, lambda item: item.property("text") == "No channel matches")[0]
    assert not empty.isVisible()
    QTest.keyClicks(view, "zzqq")  # search field has focus while menu is open
    wait(0.2)
    assert channels.property("count") == 0 and empty.isVisible()
    for _ in range(4):
        key(view, Qt.Key.Key_Backspace)
    QTest.keyClicks(view, "speed")
    wait(0.2)
    assert 0 < channels.property("count") < len(backend.channelMenu) and not empty.isVisible()


def test_hysteresis_applied_while_slider_moves(opener):
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.setSideTab(2)
    wait(0.4)
    slider = find(view, lambda item: "Slider" in class_name(item) and item.property("from") == 3.0)[0]
    value = 10 if backend.hysteresis != 10 else 12
    slider.setProperty("value", float(value))
    QMetaObject.invokeMethod(slider, "moved")
    assert backend.hysteresis != value  # applied once value stays a moment
    wait(0.6)
    assert backend.hysteresis == value


def test_axis_labels_follow_tick_step(opener, warnings):
    dialog = opener()
    dialog.resize(2000, 800)  # charts wide enough for ticks every 0.5 m at closest zoom
    wait(0.3)
    view, backend = dialog.view, dialog.backend
    chart = chart_of(view)
    evaluate(view, chart, "setView(1500, 1505, false)")  # closest zoom: 5 m
    wait(0.2)
    step = chart.property("tickStep")
    assert step == 0.5
    assert evaluate(view, chart, "axisText(1500.5)") == "1500.5 m"
    labels = [item.property("text") for item in find(view, lambda item: "QQuickText" in class_name(item))
              if str(item.property("text") or "").endswith(" m") and item.isVisible()
              and item.parentItem() is not None and item.parentItem().property("clip")]
    assert len(labels) > 3 and len(set(labels)) == len(labels)  # every tick its own label
    evaluate(view, chart, "resetView(false)")
    wait(0.2)
    assert evaluate(view, chart, "axisText(1500)") == "1500 m"
    backend.setTimeAxis(True)
    wait(0.2)
    evaluate(view, chart, "resetView(false)")
    wait(0.2)
    assert chart.property("tickStep") >= 1
    assert evaluate(view, chart, "axisText(119.5)") == "2:00"  # never 1:60
    assert evaluate(view, chart, "axisText(59.6)") == "1:00"
    assert evaluate(view, chart, "axisText(12)") == "12s"
    evaluate(view, chart, "setView(119, 119.5, false)")  # closest zoom: 0.5 s
    wait(0.2)
    assert chart.property("tickStep") == pytest.approx(0.05)
    assert evaluate(view, chart, "axisText(119.25)") == "1:59.25"
    assert evaluate(view, chart, "axisText(119.995)") == "2:00.00"
    assert evaluate(view, chart, "axisText(12.05)") == "12.05s"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows scan codes")
def test_azerty_digit_row(opener, warnings):
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    chart = chart_of(view)
    side_map = track_maps(view, False)[0]
    side_map.forceActiveFocus()
    wait(0.1)
    canvas = find(view, lambda item: item.property("targetZoom") is not None and item.property("feet") is not None)[0]
    zoom = canvas.property("targetZoom")

    def press(code, scan, text):
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QCoreApplication.sendEvent(view, QKeyEvent(kind, code, Qt.KeyboardModifier.NoModifier, scan, 0, 0, text))
        wait(0.15)

    press(Qt.Key.Key_Minus, 0x07, "-")  # 6 key of AZERTY keyboard: coloring 6, not zoom out
    assert backend.mapMode == "gear" and canvas.property("targetZoom") == zoom
    press(Qt.Key.Key_Eacute, 0x03, "é")  # 2 key
    assert backend.mapMode == "gain"
    chart.forceActiveFocus()
    evaluate(view, chart, "setView(500, 900, false)")
    wait(0.1)
    assert chart.property("zoomed")
    press(Qt.Key.Key_Agrave, 0x0B, "à")  # 0 key: whole lap
    wait(0.3)
    assert not chart.property("zoomed")


def test_reference_lap_cursor_largest_on_map(opener, warnings):
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    chart = chart_of(view)
    evaluate(view, chart, "setCursor(500, 'key')")
    wait(0.3)
    cars = [item for item in find(view, lambda item: item.property("size") is not None and item.property("z") == 4.0)
            if item.isVisible()]
    reference = next(item["key"] for item in backend.legend if item["reference"])
    sizes = {evaluate(view, car, "point.lap"): car.property("size") for car in cars}
    assert len(sizes) > 1 and max(sizes, key=lambda lap: sizes[lap]) == reference


def test_markers_cleared_for_another_track(opener, warnings):
    write_lap(cfg.path.telemetry.rstrip("/"), 1, 90.0)  # second track
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    chart = chart_of(view)
    evaluate(view, chart, "setMarker('A', 500); setMarker('B', 900)")
    wait(0.1)
    assert chart.property("hasRange")
    backend.refresh()  # same track listed again: markers kept
    wait_loaded(dialog)
    assert chart.property("hasRange")
    track = backend.currentTrack
    backend.currentTrack = next(name for name in backend.tracks if name != track)
    wait_loaded(dialog)
    wait(0.2)
    assert not chart.property("hasRange") and backend._map_range == (-1.0, -1.0)


def test_g_circle_follows_shown_laps(opener, warnings):
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.setSideTab(1)
    wait(0.4)
    circle = find(view, lambda item: item.property("gScale") is not None)[0]

    def dots() -> int:
        return int(evaluate(view, circle, "(info.dots || []).length"))

    shown = [item["key"] for item in backend.legend]
    assert len(shown) > 1 and dots() == len(shown)
    backend.toggleLap(shown[-1])  # tab shown: built at once
    wait_loaded(dialog)
    wait(0.2)
    assert dots() == len(shown) - 1
    backend.setSideTab(0)
    wait(0.3)
    backend.toggleLap(shown[-1])  # tab hidden: built once shown again
    wait_loaded(dialog)
    backend.setSideTab(1)
    wait(0.3)
    assert dots() == len(shown)


def test_closed_without_qml_warnings(laps):  # noqa: F811
    from tinypedal.ui.lap_viewer import LapViewer

    dialog = LapViewer(None)
    wait_loaded(dialog)
    dialog.show()
    wait(0.3)
    with no_qml_warnings():  # page source dropped before the backend its bindings read
        dialog.close()
        flush_deleted()
        wait(0.2)
