"""Lap viewer simple view (page mode over charts): pedals & steering wheel of each lap at cursor, channel groups drawn
like overlays (main lap values, other laps as marks), items = channels shown on charts (one Show menu for both views),
only worked out while view is shown"""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QMetaObject

from neopedal.module import module_recorder
from neopedal.ui.lap_viewer import CHANNEL_MAP, load_viewer_setting
from neopedal.ui.quick.lap_backend import pedal_value
from neopedal.ui.quick.lap_dashboard import CARD_CHANNELS, item_columns, other_items, value_text
from tests.test_lap_viewer_features import laps  # noqa: F401
from tests.test_lap_viewer_fix_qml import chart_of, evaluate, find, opener, wait, warnings  # noqa: F401


def test_pedal_value():
    assert pedal_value(None) == -1.0
    assert pedal_value(0.5) == 0.5
    assert pedal_value(1.2) == 1.0 and pedal_value(-0.1) == 0.0


def test_inputs_at_cursor_while_view_shown(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    chart = chart_of(view)
    backend.setSimpleView(False)
    wait(0.2)
    assert backend.cursorState(500.0)["inputs"] == []  # hidden: not worked out
    backend.setSimpleView(True)
    wait(0.5)
    state = backend.cursorState(500.0)["inputs"]
    assert len(state) == len(backend.legend) > 0
    for lap in state:
        assert 0.0 <= lap["throttle"] <= 1.0 and 0.0 <= lap["brake"] <= 1.0
        assert lap["clutch"] == -1.0  # never pressed in test laps: hidden
        assert -1.0 <= lap["steering"] <= 1.0
        assert lap["rotation"] == 0.0 and lap["angle"] == 0.0  # wheel rotation not recorded in test laps
        assert lap["gear"] in {"3", "4", "5", "6"} and lap["speed"] and not lap["ended"]
    evaluate(view, chart, "setCursor(500, 'key')")
    wait(0.3)
    assert evaluate(view, chart, "cursorInputs.length") == len(state)
    gauges = find(view, lambda item: item.property("gaugeHeight") is not None and item.isVisible())
    assert gauges
    wheels = find(view, lambda item: item.property("realAngle") is not None and item.property("turn") is not None)
    assert wheels and all(wheel.property("turn") == pytest.approx(wheel.property("steering") * 225) for wheel in wheels)
    evaluate(view, chart, "setCursor(NaN)")
    assert evaluate(view, chart, "cursorInputs.length") == 0
    backend.setSimpleView(False)  # hidden: cursor moves skip inputs
    wait(0.3)
    evaluate(view, chart, "setCursor(600, 'key')")
    assert evaluate(view, chart, "cursorInputs.length") == 0


def test_steering_angle_from_recorded_rotation(opener, warnings):  # noqa: F811
    dialog = opener()
    backend = dialog.backend
    for lap in backend.data.laps:
        lap.data.meta["steering_range"] = 540.0
    backend.setSimpleView(True)
    for lap in backend.dashboard.inputs_at(500.0):
        assert lap["rotation"] == 540.0 and lap["angle"] == pytest.approx(lap["steering"] * 270)


def test_recorded_lap_info_has_steering_rotation(monkeypatch):
    # Other readers missing (session, vehicle...): steering rotation still saved
    monkeypatch.setattr(module_recorder.api, "read", SimpleNamespace(
        inputs=SimpleNamespace(steering_range_physical=lambda: 540.04)))
    assert module_recorder.lap_info("lap", [])["steering_range"] == 540.0
    monkeypatch.setattr(module_recorder.api, "read", SimpleNamespace(
        inputs=SimpleNamespace(steering_range_physical=lambda: 0.0)))
    assert "steering_range" not in module_recorder.lap_info("lap", [])  # unknown: not saved


def test_clutch_shown_once_used(opener, warnings):  # noqa: F811
    dialog = opener()
    backend = dialog.backend
    lap = backend.data.laps[0]
    clutch = lap.data.columns["clutch"]
    clutch[len(clutch) // 2] = 0.8  # pressed once (start, downshift): gauge shown
    backend.dashboard._clutch_used.clear()
    assert 0.0 <= backend.dashboard.inputs_at(500.0)[0]["clutch"] <= 1.0
    assert backend.dashboard.clutch_used(lap) and backend.dashboard._clutch_used[lap.key][0] is lap.data


def test_value_text():
    assert value_text(CHANNEL_MAP["rpm"], 6483.17) == "6483"
    assert value_text(CHANNEL_MAP["water_temp"], 74.94) in ("74.9", "74,9")
    assert value_text(CHANNEL_MAP["fuel_used"], 0.456) in ("0.46", "0,46")
    assert value_text(CHANNEL_MAP["throttle"], 0.5) == "50%"
    assert value_text(CHANNEL_MAP["tc_level"], 8.0) == "8"


def test_every_channel_in_a_group():
    assert other_items() == []  # new channels: add them to a group (else shown in "Other")


def test_layout_and_values_at_cursor(opener, warnings):  # noqa: F811
    dialog = opener()
    backend = dialog.backend
    backend.setSimpleView(False)
    wait(0.2)
    assert backend.cursorState(500.0)["dashboard"] == []  # hidden: not worked out
    for group in ("engine", "tyres", "brakes", "chassis", "electronics"):
        backend.dashboard.setGroup(group, True)
    backend.setSimpleView(True)
    wait(0.3)
    layout = backend.dashboard.layout
    assert [group["key"] for group in layout][:3] == ["driver", "timing", "engine"]
    items = [item for group in layout for item in group["items"]]
    assert [item["index"] for item in items] == list(range(len(items)))
    shown = {item.key for item, _ in backend.dashboard.items}
    assert all(any(column in backend.visible for column in item_columns(item)) for item, _ in backend.dashboard.items)
    assert {"inputs", "delta", "rpm", "g"} <= shown
    values = backend.cursorState(500.0)["dashboard"]
    assert [value["key"] for value in values] == [item["key"] for item in items]
    lap_count = len(backend.data.laps)
    for item, value in zip(items, values):
        if item["kind"] == "inputs":
            continue
        assert len(value["laps"]) == lap_count
        for entry in value["laps"]:
            if not entry["ok"]:
                continue
            if item["kind"] in ("bar", "number"):
                assert entry["t"] and 0.0 <= entry["a"] <= 1.0
            elif item["kind"] == "center":
                assert entry["t"] and -1.0 <= entry["a"] <= 1.0
            elif item["kind"] == "wheels":
                assert len(entry["t"]) == len(entry["a"]) == 4
            elif item["kind"] == "g":
                assert -1.0 <= entry["x"] <= 1.0 and -1.0 <= entry["y"] <= 1.0 and entry["limit"] >= 1
            else:
                assert isinstance(entry["on"], bool)
    delta = values[next(item["index"] for item in items if item["key"] == "delta")]["laps"]
    reference = backend.data.laps.index(backend.data.reference)
    assert delta[reference]["ok"] and delta[reference]["a"] == 0.0  # no gap to itself
    assert not backend.dashboard.cursor_values(1e6)[1]["laps"][0]["ok"]  # past end of laps


def test_one_selection_for_both_views(opener, warnings):  # noqa: F811
    dialog = opener()
    backend = dialog.backend
    backend.setSimpleView(True)

    def layout_keys() -> set:
        return {item["key"] for group in backend.dashboard.layout for item in group["items"]}

    def catalog() -> dict:
        return {item["key"]: item for group in backend.dashboard.catalog for item in group["items"]}

    backend.setChannelVisible("rpm", True)  # chart channel: simple view item too, saved once
    assert "rpm" in layout_keys() and catalog()["rpm"]["shown"]
    assert "rpm" in load_viewer_setting(backend.folder)["channels"]
    backend.setChannelVisible("rpm", False)
    assert "rpm" not in layout_keys() and not catalog()["rpm"]["shown"]
    backend.setChannelVisible("tyre_temp_fl", True)  # one wheel on charts: 4 wheel tiles in simple view
    assert "all:tyre_temp" in layout_keys() and catalog()["tyre_temp_fl"]["detail"]
    backend.setChannelVisible("accel_lat", True)  # one G channel: G circle
    assert "g" in layout_keys()
    backend.dashboard.setGroup("tyres", True)  # every tyre channel but one wheel ones
    tyres = next(group for group in backend.dashboard.catalog if group["key"] == "tyres")
    assert all(item["shown"] for item in tyres["items"] if not item["detail"])
    assert "tyre_temp_fr" not in backend.visible
    backend.dashboard.setGroup("tyres", False)  # none left, one wheel ones too
    assert not any(column.startswith(("all:tyre", "tyre_")) for column in backend.visible)
    backend.dashboard.setGroup("driver", False)  # pedal cards hidden, pedal charts too
    assert backend.dashboard.layout[0]["key"] != "driver"
    assert not set(CARD_CHANNELS) & set(backend.visible)
    backend.resetChannels()
    assert backend.dashboard.layout[0]["key"] == "driver" and "delta" in layout_keys()
    # Math channels: shown on charts & in simple view at once, hidden from both
    try:
        assert backend.math.save("", "Twice", "speed_kph * 2", "") == ""
        math = next(group for group in backend.dashboard.catalog if group["key"] == "math")
        key = math["items"][0]["key"]
        assert math["items"][0]["shown"] and key in layout_keys()
        backend.setChannelVisible(key, False)
        assert key not in layout_keys() and key not in backend.visible
    finally:
        backend.math.remove("Twice")


def test_view_items_and_picker(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    chart = chart_of(view)
    backend.setSimpleView(True)
    wait(0.5)
    evaluate(view, chart, "setCursor(500, 'key')")
    wait(0.3)
    assert evaluate(view, chart, "cursorDashboard.length") == len(backend.dashboard.cursor_values(500.0))
    cells = find(view, lambda item: item.property("cursorValue") is not None and item.isVisible())
    assert cells and all(cell.property("entries") for cell in cells if cell.property("kind") != "inputs")
    backend.dashboard.setGroup("tyres", True)  # items shown change: values asked again
    wait(0.3)
    assert evaluate(view, chart, "cursorDashboard.length") == len(backend.dashboard.cursor_values(500.0))
    button = find(view, lambda item: item.objectName() == "showButton")[0]
    QMetaObject.invokeMethod(button, "clicked")
    wait(0.4)
    assert button.property("checked")  # Show menu open, simple view shown
    backend.resetChannels()
    wait(0.2)


def test_simple_view_mode_saved_and_old_tab_migrated(opener, warnings):  # noqa: F811
    from neopedal.setting import cfg
    from neopedal.ui.lap_viewer import save_viewer_setting

    save_viewer_setting(cfg.path.telemetry.rstrip("/"), side_tab=6)  # simple view was side tab 6 before
    dialog = opener()
    backend = dialog.backend
    assert backend.simpleView and backend.sideTab == 0
    backend.setSimpleView(False)
    assert not load_viewer_setting(backend.folder)["simple_view"]
    backend.setSideTab(6)  # no such tab anymore
    assert backend.sideTab == 5


def test_simple_view_over_charts(opener, warnings):  # noqa: F811
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from tests.test_lap_viewer_fix_qml import center_of, focused, key, named

    dialog = opener()
    view, backend = dialog.view, dialog.backend
    chart = chart_of(view)
    backend.setSimpleView(False)
    wait(0.4)
    mode = named(view, "viewMode")
    assert mode.property("currentIndex") == 1 and chart.property("chartsShown")
    evaluate(view, mode, "activated(0)")  # simple view picked
    wait(0.6)
    assert backend.simpleView and load_viewer_setting(backend.folder)["simple_view"]
    assert not chart.property("chartsShown") and focused(view) is chart  # charts hidden, keys still theirs
    chips = find(view, lambda item: item.property("pinned") is not None and item.property("gaugeHeight") is None
                 and item.isVisible())
    assert len(chips) == len(backend.legend)  # lap chips of charts still shown above simple view
    simple = find(view, lambda item: item.property("cardsShown") is not None)[0]
    assert simple.isVisible() and evaluate(view, simple, "layout.length") > 0
    # Playback bar moves cursor along lap, values follow
    scrub = named(view, "playbackScrub")
    scrub.setProperty("value", 700.0)
    evaluate(view, scrub, "moved()")
    wait(0.3)
    assert evaluate(view, chart, "cursorX") == pytest.approx(700.0)
    assert evaluate(view, chart, "cursorInputs.length") == len(backend.legend) > 0
    assert scrub.property("value") == pytest.approx(700.0)
    key(view, Qt.Key.Key_Right)  # keys of charts move cursor under simple view
    assert evaluate(view, chart, "cursorX") > 700.0
    assert scrub.property("value") == pytest.approx(evaluate(view, chart, "cursorX"))
    # Lap card clicked: its values shown in groups, clicked again: back to reference lap
    cards = find(view, lambda item: item.property("gaugeHeight") is not None and item.property("pinned") is not None
                 and item.isVisible())
    assert len(cards) == len(backend.legend)
    other = next(card for card in cards if evaluate(view, card, "lap.lap") != evaluate(view, simple, "mainLap.lap"))
    lap_key = evaluate(view, other, "lap.lap")
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center_of(other))
    wait(0.3)
    assert chart.property("pinnedKey") == lap_key and evaluate(view, simple, "mainLap.lap") == lap_key
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center_of(other))
    wait(0.3)
    assert chart.property("pinnedKey") == ""
    # Advanced view again: charts shown, simple view hidden (nothing read)
    evaluate(view, mode, "activated(1)")
    wait(0.6)
    assert not backend.simpleView and chart.property("chartsShown") and not simple.isVisible()
    evaluate(view, chart, "setCursor(500, 'key')")
    assert evaluate(view, chart, "cursorInputs.length") == 0
