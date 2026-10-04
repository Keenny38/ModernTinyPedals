"""Lap viewer: stable colors, computed channels, cursor, selection, range stats, map orientation, live mode..."""

import math
import os

import pytest

from tests.test_lap_viewer import wait_loaded
from tests.test_lap_viewer_features import BASE, check_only, laps, rows_by_path, save, viewer  # noqa: F401
from tinypedal.setting import cfg
from tinypedal.userfile.telemetry_lap import LapData


def lap_data(name: str = "a", length: float = 1000.0, step: float = 10.0, speed: float = 100.0, **columns) -> LapData:
    distance = [index * step for index in range(int(length / step) + 1)]
    data = {"distance": distance, "lap_time": [d / (speed / 3.6) for d in distance], "speed_kph": [speed] * len(distance)}
    data.update({name: values if isinstance(values, list) else [values] * len(distance) for name, values in columns.items()})
    return LapData(name, data)


# --- Data
def test_parse_columns_skips_bad_rows(tmp_path):
    from tinypedal.userfile.telemetry_lap import load_lap, parse_columns

    assert parse_columns([["1", "2"], ["3", "4"]], 2) == [[1.0, 3.0], [2.0, 4.0]]
    assert parse_columns([["1", "2"], ["x", "4"], ["5", "6"]], 2) == [[1.0, 5.0], [2.0, 6.0]]
    assert parse_columns([], 3) == [[], [], []]
    path = tmp_path / "lap.csv"
    path.write_text("lap_time,distance\n0,0\nbad,1\n1,10\n2\n", encoding="utf-8")
    assert load_lap(str(path)).distance == [0.0, 10.0]


def test_delta_scaled_to_reference_length():
    from tinypedal.userfile.telemetry_lap import compute_delta, distance_scale

    reference = lap_data("ref", length=1000.0)
    longer = LapData("log", {"distance": [d * 1.03 for d in reference.distance],  # driven distance 3% longer
                             "lap_time": list(reference.columns["lap_time"])})
    assert distance_scale(reference, longer) == pytest.approx(1 / 1.03)
    assert compute_delta(reference, longer)[-1][1] == pytest.approx(0.0, abs=1e-6)  # same pace: no delta drift
    short = LapData("cut", {"distance": reference.distance[:50], "lap_time": reference.columns["lap_time"][:50]})
    assert distance_scale(reference, short) == 1.0  # lap cut short: not scaled
    assert distance_scale(reference, reference) == 1.0


def test_viewer_setting_written_safely(ui_env, tmp_path):
    from tinypedal.ui.lap_viewer import VIEWER_SETTING, load_viewer_setting, save_viewer_setting

    folder = tmp_path / "viewer"
    folder.mkdir()
    save_viewer_setting(str(folder), channels=["speed_kph"])
    save_viewer_setting(str(folder), smoothing=2)
    assert load_viewer_setting(str(folder)) == {"channels": ["speed_kph"], "smoothing": 2}
    assert sorted(os.listdir(folder)) == [VIEWER_SETTING]  # no temporary file left


def test_map_line_keeps_increasing_distance():
    from tinypedal.ui.quick import lap_map

    lap = LapData("a", {"distance": [0.0, 10.0, 5.0, 20.0, 20.0, 30.0], "pos_x": [1.0, 2, 3, 4, 5, 6],
                        "pos_y": [1.0] * 6})
    line = lap_map.map_line(lap)
    assert line is not None and line.distances == [0.0, 10.0, 20.0, 30.0]


def test_slip_events_and_map_rotation_helpers():
    from tinypedal.ui.quick import lap_map

    count = 101
    distance = [index * 10.0 for index in range(count)]
    locked = [100.0 if 300 <= d <= 340 else 100.0 + 0 * d for d in distance]
    front = [70.0 if 300 <= d <= 340 else 100.0 for d in distance]  # front wheels 30% slower: lockup
    rear = [130.0 if 700 <= d <= 720 else 100.0 for d in distance]  # rear 30% faster: wheelspin
    lap = LapData("a", {
        "distance": distance, "speed_kph": locked, "brake": [1.0 if 290 <= d <= 350 else 0.0 for d in distance],
        "throttle": [1.0 if d >= 600 else 0.0 for d in distance],
        "wheel_speed_fl": front, "wheel_speed_fr": front, "wheel_speed_rl": rear, "wheel_speed_rr": rear,
    })
    assert lap_map.slip_events(lap) == [(300.0, "lock"), (700.0, "spin")]
    assert lap_map.slip_events(LapData("b", {"distance": distance})) == []
    line = lap_map.MapLine([0.0, 1.0], [10.0, 0.0], [0.0, 0.0])
    turned = lap_map.rotate_line(line, math.pi / 2)
    assert turned.xs[0] == pytest.approx(0.0, abs=1e-9) and turned.ys[0] == pytest.approx(10.0)
    assert lap_map.principal_angle([0.0, 1.0, 2.0, 3.0], [0.0, 1.0, 2.0, 3.0]) == pytest.approx(math.pi / 4)


# --- Corners
def test_corner_stats_extra_values_and_ideal_lap():
    from tests.test_corner_analysis import make_lap
    from tinypedal.userfile.corner_analysis import compare_corners, find_corners, ideal_lap, resample_sorted

    assert resample_sorted([0.0, 10.0], [0.0, 100.0], [-5.0, 0.0, 2.5, 10.0, 20.0]) == [0.0, 0.0, 25.0, 100.0, 100.0]
    reference = make_lap()
    slower = make_lap(((0, 250), (400, 250), (500, 90), (700, 220), (800, 220), (900, 150), (1100, 240), (1500, 240)))
    faster_t2 = make_lap(((0, 250), (400, 250), (500, 95), (700, 220), (800, 220), (900, 170), (1100, 240),
                          (1500, 240)))  # slower than reference in first corner, faster in second
    row = compare_corners(reference, slower)[0]
    assert row.reference.entry_speed == pytest.approx(250, abs=3) and row.reference.peak_brake == 1.0
    assert row.compared.exit_speed <= row.reference.exit_speed + 1
    corners = find_corners(reference)
    ideal = ideal_lap([reference, slower, faster_t2], corners)
    assert ideal is not None and ideal.time < min(reference.lap_time, faster_t2.lap_time) - 0.01
    assert ideal.best[ideal.bounds.index(corners[1].start)] == 2  # third lap fastest in second corner
    assert 1 not in ideal.best  # slower lap never fastest
    assert ideal_lap([reference], corners) is None


# --- Trace data
def test_trace_data_computed_channels_and_smoothing(ui_env):
    from PySide6.QtGui import QColor

    from tinypedal.ui.lap_viewer import CHANNEL_MAP, PlotLap
    from tinypedal.ui.quick.trace_data import TraceData, moving_average

    assert moving_average([0.0, 3.0, 0.0, 3.0, 0.0], 3) == pytest.approx([1.5, 1.0, 2.0, 1.0, 1.5])
    assert moving_average([1.0, 2.0], 5) == [1.0, 2.0]
    count = 101
    lap = lap_data(
        "a", fuel=[50.0 - index * 0.01 for index in range(count)],
        steering=[index / 100 for index in range(count)],
        wheel_speed_fl=110.0, wheel_speed_fr=100.0, wheel_speed_rl=90.0, wheel_speed_rr=100.0,
        tyre_temp_fl=80.0, tyre_temp_fr=90.0, tyre_temp_rl=70.0, tyre_temp_rr=75.0,
    )
    data = TraceData()
    data.set_laps([PlotLap("a", "a", lap, QColor("red"))])
    plot = data.laps[0]
    assert data.series(CHANNEL_MAP["slip_fl"], plot)[1][5] == pytest.approx(10.0)  # 10% faster than car
    assert data.series(CHANNEL_MAP["slip_rl"], plot)[1][5] == pytest.approx(-10.0)
    assert data.series(CHANNEL_MAP["fuel_used"], plot)[1][-1] == pytest.approx(1.0)
    assert data.series(CHANNEL_MAP["tyre_temp_spread"], plot)[1][0] == pytest.approx(20.0)
    rate = data.series(CHANNEL_MAP["steering_rate"], plot)[1][50]
    assert rate == pytest.approx(0.01 / (10 / (100 / 3.6)) * 100)  # 1% steering every 10 m at 100 km/h
    assert data.available(CHANNEL_MAP["slip_fl"]) and not data.available(CHANNEL_MAP["brake"])
    assert not data.available(CHANNEL_MAP["delta"])  # no compared lap
    assert data.available(CHANNEL_MAP["all:tyre_temp"])
    before = data.signature(CHANNEL_MAP["accel_lat"])
    data.set_smoothing(7)
    assert data.signature(CHANNEL_MAP["accel_lat"]) != before  # noisy channel drawn again
    assert data.signature(CHANNEL_MAP["speed_kph"]) == "0"  # others kept


def test_trace_data_keeps_series_of_shown_laps(ui_env):
    from PySide6.QtGui import QColor

    from tinypedal.ui.lap_viewer import CHANNEL_MAP, PlotLap
    from tinypedal.ui.quick.trace_data import TraceData

    first, second, third = (PlotLap(name, name, lap_data(name, speed=speed), QColor("red"))
                            for name, speed in (("a", 100.0), ("b", 90.0), ("c", 80.0)))
    data = TraceData()
    data.set_laps([first, second], "a")
    speed = CHANNEL_MAP["speed_kph"]
    kept = data.series(speed, second)
    delta = data.deltas["b"]
    data.set_laps([first, second, third], "a")  # lap added: others not computed again
    assert data.series(speed, second) is kept and data.deltas["b"] is delta
    data.set_laps([first, second, third], "c")  # reference changed: deltas computed again
    assert data.deltas["b"] is not delta and "a" in data.deltas
    grid, lows, highs = data.envelope(speed)
    assert grid and lows[0] == pytest.approx(80.0) and highs[0] == pytest.approx(100.0)
    stats = data.range_stats(500.0, 100.0, [speed])  # markers in any order
    assert [row["lap"].key for row in stats] == ["a", "b", "c"]
    assert stats[0]["distance"] == pytest.approx(400.0) and stats[0]["values"][0] == pytest.approx((100, 100, 100))
    assert stats[2]["time"] > stats[0]["time"]  # slower lap takes longer


# --- Viewer page
def test_lap_colors_stay_while_shown(viewer, laps):  # noqa: F811
    backend = viewer.backend
    check_only(viewer, laps[:3])
    colors = {lap.key: lap.color.name() for lap in backend.data.laps}
    backend.setLapChecked(laps[1], False)  # lap in the middle hidden
    assert {lap.key: lap.color.name() for lap in backend.data.laps} == {
        key: color for key, color in colors.items() if key != laps[1]}
    backend.setReference(laps[2])  # reference changed: same colors
    assert {lap.key: lap.color.name() for lap in backend.data.laps}[laps[2]] == colors[laps[2]]


def test_unreadable_lap_flagged(viewer, laps):  # noqa: F811
    backend = viewer.backend
    with open(laps[2], "w", encoding="utf-8") as file:
        file.write("not a lap")
    backend.refresh()
    wait_loaded(viewer)
    check_only(viewer, [laps[1], laps[2]])
    row = rows_by_path(backend)[laps[2]]
    assert row["error"] and row["checked"] and not row["color"]
    assert len(backend.data.laps) == 1


def test_unavailable_channels_greyed(viewer):  # noqa: F811
    backend = viewer.backend
    check_only(viewer, [backend.reference_key])  # one lap: no delta
    menu = {item["column"]: item for item in backend.channelMenu}
    assert menu["speed_kph"]["available"] and not menu["delta"]["available"]
    assert menu["all:tyre_temp"]["title"] == "All 4 wheels"
    panel = next(panel for panel in backend.panels if panel["column"] == "delta")
    assert not panel["available"] and panel["note"]
    del backend.data.laps[0].data.columns["brake"]  # channel not recorded
    backend.rebuild_chart()
    assert not {item["column"]: item for item in backend.channelMenu}["brake"]["available"]


def test_cursor_state_and_differences(viewer):  # noqa: F811
    backend = viewer.backend
    state = backend.cursorState(500.0)
    assert set(state) == {"title", "values", "map", "g"} and state["title"] == "500 m"
    speed = state["values"][backend.visible.index("speed_kph")]
    assert len(speed) == len(backend.data.laps) and speed[0]["diff"] == "" and speed[1]["diff"]
    beyond = backend.cursorValues(5000.0)[0]  # past end of laps: one empty entry per lap (QML items kept)
    assert len(beyond) == len(backend.data.laps) and all(value["text"] == "" for value in beyond)
    from tinypedal.ui.lap_viewer import CHANNEL_MAP
    from tinypedal.ui.quick.lap_backend import format_diff

    assert format_diff(CHANNEL_MAP["throttle"], 0.25) == "+25%"
    assert format_diff(CHANNEL_MAP["speed_kph"], -4.0) == chr(0x2212) + "4"


def test_time_axis_map_cursor_follows_each_lap(viewer):  # noqa: F811
    backend = viewer.backend
    backend.setTimeAxis(True)
    points = backend.mapCursor(30.0)  # 30 s into each lap: slower lap behind
    reference, compared = backend.data.laps
    assert backend.data.lap_distance_at_x(reference, 30.0) > backend.data.lap_distance_at_x(compared, 30.0)
    assert (points[0]["x"], points[0]["y"]) != (points[1]["x"], points[1]["y"])
    backend.setTimeAxis(False)
    points = backend.mapCursor(500.0)  # distance axis: same place
    assert points[0]["x"] == pytest.approx(points[1]["x"], abs=1) and points[0]["y"] == pytest.approx(points[1]["y"], abs=1)


def test_selection_shortcuts(viewer, laps):  # noqa: F811
    backend = viewer.backend
    backend.selectRange(laps[0], laps[3], True)
    wait_loaded(viewer)
    assert set(backend.ordered_checked()) == set(laps)
    backend.clearSelection()
    assert backend.ordered_checked() == [backend.reference_key]
    backend.compareBestLast()
    wait_loaded(viewer)
    assert backend.reference_key == laps[1] and set(backend.ordered_checked()) == {laps[1], laps[3]}
    backend.compareBest(2)
    wait_loaded(viewer)
    assert set(backend.ordered_checked()) == {laps[1], laps[2]}  # invalid lap 4 left out


def test_presets_options_and_layout_saved(viewer):  # noqa: F811
    from PySide6.QtCore import QByteArray

    from tinypedal.ui.lap_viewer import CHANNEL_PRESETS, load_viewer_setting

    backend = viewer.backend
    backend.applyPreset("Tyres")
    assert backend.visible == list(CHANNEL_PRESETS["Tyres"])
    tyres = next(panel for panel in backend.panels if panel["column"] == "all:tyre_temp")
    assert len(tyres["series"]) == 4 * len(backend.data.laps) and [part["label"] for part in tyres["parts"]] == [
        "FL", "FR", "RL", "RR"]
    backend.applyPreset("Default")
    backend.setPanelWeight("speed_kph", 3.0)
    backend.setSmoothing(2)
    backend.setDeltaWindow(80)
    backend.setEnvelope(True)
    backend.setLayoutState(QByteArray(b"layout"))
    backend.setSideTab(2)
    setting = load_viewer_setting(cfg.path.telemetry)
    assert setting["panel_weights"] == {"speed_kph": 3.0} and setting["smoothing"] == 2
    assert setting["delta_window"] == 80 and setting["envelope"] and setting["side_tab"] == 2
    assert bytes(backend.layoutState.data()) == b"layout"
    assert next(panel for panel in backend.panels if panel["column"] == "speed_kph")["weight"] == 3.0
    backend.resetPanelWeights()
    assert load_viewer_setting(cfg.path.telemetry)["panel_weights"] == {}


def test_lap_rows_gap_and_conditions(viewer, laps):  # noqa: F811
    rows = rows_by_path(viewer.backend)
    assert rows[laps[1]]["gap"] == "" and rows[laps[2]]["gap"] == "+2.000"
    assert "Porsche 963" in rows[laps[1]]["tip"]


def test_sector_and_range_statistics(viewer):  # noqa: F811
    backend = viewer.backend
    assert backend.sectorRange(1) == []  # sectors not recorded by test laps
    stats = backend.rangeStats(200.0, 900.0)
    assert len(stats["laps"]) == 2 and stats["laps"][0]["gap"] == "" and stats["laps"][1]["gap"].startswith("+")
    assert any(row["title"].startswith("Speed") for row in stats["channels"])
    assert stats["title"] == "200 m → 900 m"


def test_corner_compare_lap_sort_and_ideal(viewer, laps):  # noqa: F811
    backend = viewer.backend
    check_only(viewer, [laps[1], laps[2], laps[0]])
    assert len(backend.comparedLaps) == 2
    first = backend.compareKey
    other = next(lap["key"] for lap in backend.comparedLaps if lap["key"] != first)
    backend.setCompareKey(other)
    assert backend.compareKey == other
    backend.setCornerSort("loss")
    corners = [row for row in backend.corners if row["kind"] == "corner"]
    assert [row["bar"] for row in corners] == sorted((row["bar"] for row in corners), reverse=True)
    assert backend.corners[-1]["kind"] == "ideal" and corners[0]["entry"] and corners[0]["gear"]
    backend.setCornerSort("track")
    assert backend.speedUnit == "km/h" and backend.speedScale == 1.0


def test_map_rotation_and_slip_points(viewer):  # noqa: F811
    backend = viewer.backend
    backend.setMapAutoOrient(True)
    backend.setMapAspect(0.5)  # tall map: longest extent vertical
    width = backend.trackMap["maxX"] - backend.trackMap["minX"]
    height = backend.trackMap["maxY"] - backend.trackMap["minY"]
    assert height > width
    backend.setMapAutoOrient(False)
    line = backend._map_lines[0][0]
    x, y = line.xs[10], line.ys[10]
    backend.rotateMap()  # quarter clockwise on screen (y down)
    turned = backend._map_lines[0][0]
    assert turned.xs[10] == pytest.approx(-y, abs=1e-6) and turned.ys[10] == pytest.approx(x, abs=1e-6)
    position = backend.mapPick(turned.xs[10], turned.ys[10], 5.0)
    assert position == pytest.approx(line.distances[10], abs=1)
    for _ in range(3):
        backend.rotateMap()
    assert backend._map_lines[0][0].xs[10] == pytest.approx(x, abs=1e-6)  # full turn
    assert backend.trackMap["slips"] == []  # wheel speeds not recorded by test laps


def test_live_mode_compares_new_lap(viewer, laps):  # noqa: F811
    backend = viewer.backend
    backend.setLiveMode(True)
    assert backend.liveMode
    new = save(5, 69.0, BASE + 500)
    backend.auto_refresh()
    wait_loaded(viewer)
    assert new in rows_by_path(backend) and set(backend.ordered_checked()) == {new}
    assert backend.reference_key == new  # new lap is best lap
    newer = save(6, 75.0, BASE + 600)
    backend.auto_refresh()
    wait_loaded(viewer)
    assert set(backend.ordered_checked()) == {new, newer} and backend.reference_key == new
    assert "New lap" in backend.status
    os.remove(newer)
    backend.auto_refresh()
    wait_loaded(viewer)
    assert newer not in rows_by_path(backend)


def test_export_in_foreground_and_status_cleared(viewer, laps, tmp_path):  # noqa: F811
    backend = viewer.backend
    folder = tmp_path / "export"
    folder.mkdir()
    assert backend.export_many(laps[:2], str(folder), background=False) == 2
    assert len(os.listdir(folder)) == 2 and backend._status_timer.isActive()  # transient message
    backend._status_timer.timeout.emit()
    assert backend.status == ""


def test_g_circle_orientation_and_scale(viewer):  # noqa: F811
    from PySide6.QtGui import QColor

    from tinypedal.ui.lap_viewer import PlotLap

    backend = viewer.backend
    count = 200
    lat = [math.sin(index / 10) for index in range(count)]
    lon = [2.0 * math.cos(index / 10) for index in range(count - 1)] + [9.0]
    lap = lap_data("g", length=1990.0, accel_lat=lat, accel_long=lon)
    backend.data.set_laps([PlotLap("g", "g", lap, QColor("red"))])
    backend.rebuild_chart()
    assert backend.gCircle["limit"] == 3.0  # one 9 G spike left out of scale
    point = backend.gCursor(500.0)[0]  # sample 50
    assert point["x"] == pytest.approx(-math.sin(5)) and point["y"] == pytest.approx(-2 * math.cos(5))  # left turn left, braking down
    from tinypedal.ui.quick.lines import VertexStore

    assert VertexStore.get(backend.gCircle["dots"][0]["envelope"]).vertex_count >= 2


def test_replay_found_for_lap(viewer, monkeypatch):  # noqa: F811
    from tinypedal import replay
    from tinypedal.replay import ReplayInfo
    from tinypedal.userfile.telemetry_lap import lap_timestamp_of

    backend = viewer.backend
    lap = backend.data.reference
    end = lap_timestamp_of(os.path.basename(lap.key))
    created = end - 200
    monkeypatch.setattr(replay, "list_replays", lambda folder: [
        ReplayInfo("other.tpreplay", created - 5000, 0, 100.0, "LMU", {}),
        ReplayInfo("race.tpreplay", created, 0, 1000.0, "LMU", {}),
    ])
    filename, position = backend.replay_target(lap, 0.0)
    assert filename == "race.tpreplay" and position == pytest.approx(200 - lap.data.lap_time, abs=0.5)
    monkeypatch.setattr(replay, "list_replays", lambda folder: [])
    assert backend.replay_target(lap, 0.0) is None
    backend.openReplay(0.0, "")
    assert "No replay" in backend.status


# --- Track map: driving points, coloring modes, sectors, arrows
def test_map_line_helpers():
    from tinypedal.ui.quick import lap_map

    distance = [float(index) for index in range(0, 1001, 10)]
    angles = [d / 1000 * math.pi for d in distance]  # half circle turning left (counterclockwise)
    reference = lap_map.MapLine(distance, [200 * math.cos(a) for a in angles], [200 * math.sin(a) for a in angles])
    inside = lap_map.MapLine(distance, [195 * math.cos(a) for a in angles], [195 * math.sin(a) for a in angles])
    outside = lap_map.MapLine(distance, [204 * math.cos(a) for a in angles], [204 * math.sin(a) for a in angles])
    assert lap_map.line_offsets(reference, inside)[50] == pytest.approx(5.0, abs=0.3)  # inside: positive
    assert lap_map.line_offsets(reference, outside)[50] == pytest.approx(-4.0, abs=0.3)
    colors = lap_map.line_colors([5.0, -5.0, 0.1])
    assert colors[0] == lap_map.LINE_COLORS["inside"] and colors[1] == lap_map.LINE_COLORS["outside"]
    assert colors[2] == lap_map.LINE_COLORS["same"]
    marks = lap_map.direction_marks(reference, 4)
    assert len(marks) == 4 and marks[0][2] == pytest.approx(math.degrees(math.pi / 8 + math.pi / 2), abs=2)
    lap = LapData("a", {"distance": distance, "gear": [3.0] * len(distance), "pos_z": [d / 10 for d in distance]})
    assert {color.name() for color in lap_map.gear_colors(lap, reference)} == {lap_map.GEAR_COLORS[2].name()}
    colors, low, high = lap_map.elevation_colors(lap, reference)
    assert (low, high) == (0.0, 100.0) and colors[0] == lap_map.ELEVATION_COLORS[0]
    flat = LapData("b", {"distance": distance, "pos_z": [0.0] * len(distance)})
    assert lap_map.elevation_colors(flat, reference) == ([], 0.0, 0.0)  # not recorded


def test_map_driving_points_and_options(viewer):  # noqa: F811
    from tinypedal.ui.lap_viewer import load_viewer_setting

    backend = viewer.backend
    points = backend.trackMap["points"]
    kinds = {kind: [point for point in points if point["kind"] == kind] for kind in ("brake", "apex", "exit")}
    assert all(len(found) == 4 for found in kinds.values())  # 2 corners, 2 laps
    reference_key = backend.data.reference.key
    compared = next(point for point in kinds["apex"] if point["lap"] != reference_key)
    reference = next(point for point in kinds["apex"] if point["lap"] == reference_key and
                     point["corner"] == compared["corner"])
    assert "T1" in compared["tip"] or "T2" in compared["tip"]
    assert "(" in compared["tip"] and "(" not in reference["tip"]  # differences for compared lap only
    assert compared["value"].isdigit() and reference["value"].isdigit()  # speed shown next to point
    assert backend.mapOptions == {"apex": True, "exit": True, "arrows": True, "sectors": True, "values": False,
                                  "track": True}
    backend.setMapOption("values", True)
    backend.setMapOption("unknown", True)  # ignored
    assert backend.mapOptions["values"] and load_viewer_setting(cfg.path.telemetry)["map_options"]["values"]
    assert len(backend.trackMap["arrows"]) == 14
    backend.setHysteresis(200)  # no corner found: no driving point
    assert backend.trackMap["points"] == []


def test_map_modes_cursor_gap_and_sectors(viewer):  # noqa: F811
    from PySide6.QtGui import QColor

    from tinypedal.ui.lap_viewer import PlotLap
    from tinypedal.ui.quick.lines import VertexStore

    backend = viewer.backend
    for mode, filled in (("line", True), ("gear", True), ("elevation", False)):  # elevation not recorded
        backend.setMapMode(mode)
        assert (VertexStore.get(backend.trackMap["colored"]).vertex_count > 0) == filled, mode
    assert backend.mapLegend == {}
    gap = backend.mapCursor(1000.0)[1]["gap"]
    assert gap.startswith("+") and gap.endswith(" s")  # compared lap behind
    backend.setTimeAxis(True)
    assert backend.mapCursor(30.0)[1]["gap"].endswith(" m")
    backend.setTimeAxis(False)
    # Sector times from lap info: reference sector time & gap of compared lap
    distance = [float(index) for index in range(0, 3001, 10)]
    columns = {"distance": distance, "lap_time": [d / 30 for d in distance], "pos_x": [d + 1 for d in distance],
               "pos_y": [1.0] * len(distance), "speed_kph": [100.0] * len(distance)}
    reference = LapData("a", columns, {"sectors": [33.0, 34.0, 33.0]})
    compared = LapData("b", dict(columns), {"sectors": [33.5, 33.0, 33.0]})
    backend.data.set_laps([PlotLap("a", "a", reference, QColor("red")), PlotLap("b", "b", compared, QColor("blue"))], "a")
    backend.rebuild_chart()
    sectors = backend.trackMap["sectors"]
    assert [sector["label"] for sector in sectors] == ["S1", "S2", "S3"]
    assert sectors[0]["delta"] == "+0.500" and sectors[0]["deltaColor"] == "loss" and sectors[1]["deltaColor"] == "gain"
