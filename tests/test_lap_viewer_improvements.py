"""Lap viewer: packed lap columns, imported lap scaling, clean ideal lap, cache keys, units refresh, coaching,
trash & undo, search, delta best, XY tab, long run, worker jobs, new recorded channels"""

import math
import os
from array import array

import pytest
from PySide6.QtGui import QColor

from tests.test_lap_viewer import wait_loaded
from tests.test_lap_viewer_features import BASE, LENGTH, check_only, laps, rows_by_path, save, viewer  # noqa: F401
from tinypedal.module import module_recorder
from tinypedal.setting import cfg
from tinypedal.userfile.telemetry_lap import LapData


def oval_lap(name: str, lap_time: float, scale: float = 1.0, slow: float = 1.0, samples: int = 400) -> LapData:
    """Lap with 2 corners (speed dips), distances multiplied by scale (imported log on driven distance)"""
    columns: dict[str, list[float]] = {key: [] for key in (
        "distance", "lap_time", "speed_kph", "throttle", "brake", "steering", "gear")}
    for index in range(samples + 1):
        progress = index / samples
        corner = (math.cos(progress * math.tau * 2) + 1) / 2
        braking = 1.0 if 0.25 < corner < 0.7 and math.sin(progress * math.tau * 2) > 0 else 0.0
        columns["distance"].append(progress * LENGTH * scale)
        columns["lap_time"].append(progress * lap_time)
        columns["speed_kph"].append(120 + 130 * corner * slow)
        columns["throttle"].append(0.0 if braking else min(corner * 1.5, 1.0))
        columns["brake"].append(braking)
        columns["steering"].append((1 - corner) * 0.5)
        columns["gear"].append(3 + round(corner * 3))
    return LapData(name, columns, {"kind": "lap"})


# --- Packed columns (memory)
def test_loaded_lap_columns_are_packed(tmp_path):
    from tinypedal.userfile import lap_cache
    from tinypedal.userfile.telemetry_lap import load_lap

    path = tmp_path / "lap.csv"
    path.write_text("time,lap_time,distance,speed_kph\n0,0,0,100\n1,1,10,110.5\n", encoding="utf-8")
    lap = load_lap(str(path))
    assert isinstance(lap.distance, array) and lap.distance.typecode == "d"
    assert lap.columns["speed_kph"].typecode == "f" and list(lap.columns["speed_kph"]) == [100.0, 110.5]
    cached = lap_cache.load_cached_lap(str(tmp_path), str(path))  # saved to binary cache
    again = lap_cache.load_cached_lap(str(tmp_path), str(path))  # read from binary cache: arrays kept
    assert isinstance(again.columns["speed_kph"], array) and list(again.distance) == list(cached.distance)
    lap_cache.remove_cached_lap(str(tmp_path), str(path))
    assert not os.path.exists(lap_cache.cache_file(str(tmp_path), str(path)))


# --- Imported lap measured on another length: every view on reference distance
def test_scaled_lap_aligned_on_reference_distance(ui_env):
    from tinypedal.ui.lap_viewer import CHANNEL_MAP, PlotLap
    from tinypedal.ui.quick.trace_data import TraceData
    from tinypedal.userfile.corner_analysis import compare_corners

    reference = PlotLap("ref", "ref", oval_lap("ref", 70.0), QColor("red"))
    imported = PlotLap("log", "log", oval_lap("log", 71.0, scale=1.04), QColor("blue"))
    data = TraceData()
    data.set_laps([reference, imported], "ref")
    assert data.scale_of(imported) == pytest.approx(1 / 1.04)
    xs, _ = data.series(CHANNEL_MAP["speed_kph"], imported)
    assert xs[-1] == pytest.approx(LENGTH) and data.max_x() == pytest.approx(LENGTH)  # drawn on reference length
    assert data.lap_distance_at_x(imported, 1000.0) == pytest.approx(1040.0)  # its own distance there
    assert data.x_at_lap_distance(imported, 1040.0) == pytest.approx(1000.0)
    rows = compare_corners(reference.data, imported.data, scale=data.scale_of(imported))
    assert rows and all(row.compared is not None for row in rows)
    for row in rows:  # same corners, minimum speed at the same reference distance
        assert row.compared.apex == pytest.approx(row.reference.apex, abs=10)
    unscaled = compare_corners(reference.data, imported.data)
    assert any(abs(row.compared.apex - row.reference.apex) > 20 for row in unscaled if row.compared)


# --- Ideal lap & mini-sectors: invalid, out & in laps never count
def test_ideal_lap_and_mini_sectors_from_clean_laps_only(ui_env):
    from tinypedal.ui.lap_viewer import CHANNEL_MAP, PlotLap
    from tinypedal.ui.quick.trace_data import TraceData

    reference = PlotLap("ref", "ref", oval_lap("ref", 70.0), QColor("red"))
    other = PlotLap("other", "other", oval_lap("other", 71.0), QColor("green"))
    cut = PlotLap("cut", "cut", oval_lap("cut", 60.0), QColor("blue"), clean=False)  # cut track: faster
    data = TraceData()
    data.set_laps([reference, other, cut], "ref")
    mini = data.mini_sectors()
    assert 2 not in mini["winners"] and mini["ideal"] == pytest.approx(70.0, abs=0.01)
    data.set_ideal_mode(True)
    assert data.ideal_time() == pytest.approx(70.0, abs=0.01)
    assert set(data.deltas) == {"ref", "other", "cut"}  # every lap against ideal lap
    assert data.series(CHANNEL_MAP["delta"], reference)[1][-1] == pytest.approx(0.0, abs=0.01)
    assert data.series(CHANNEL_MAP["delta"], cut)[1][-1] == pytest.approx(-10.0, abs=0.05)
    signature = data.signature(CHANNEL_MAP["delta"])
    data.set_ideal_mode(False)
    assert set(data.deltas) == {"other", "cut"} and data.signature(CHANNEL_MAP["delta"]) != signature


def test_backend_ideal_lap_ignores_invalid_lap(viewer, laps):  # noqa: F811
    backend = viewer.backend
    check_only(viewer, [laps[1], laps[2], laps[3]])  # lap 4 invalid
    assert [lap.clean for lap in backend.data.laps] == [True, True, False]
    ideal = backend._ideal
    assert ideal is not None and 2 not in ideal.best
    assert backend.legend[2]["clean"] is False
    backend.setIdealDelta(True)
    assert backend.idealDelta and backend.idealTime
    assert any(panel["column"] == "delta" and len(panel["series"]) == 3 for panel in backend.panels)
    backend.setIdealDelta(False)


# --- Cache keys never compare by id()
def test_keys_match_by_identity():
    from tinypedal.ui.quick.lap_backend import keys_match

    first, second = LapData("a", {"distance": [0.0]}), LapData("a", {"distance": [0.0]})
    assert keys_match((first, 3, "x", (first,)), (first, 3, "x", (first,)))
    assert not keys_match((first, 3), (second, 3))  # equal content, other loaded lap
    assert not keys_match((first, 3), (first, 4)) and not keys_match(None, (first,))


# --- Unit setting changed while page is open
def test_units_refreshed_from_settings(viewer, monkeypatch):  # noqa: F811
    from tinypedal import app_signal
    from tinypedal.ui.lap_viewer import CHANNEL_MAP

    backend = viewer.backend
    lap = backend.data.reference
    kph = backend.data.series(CHANNEL_MAP["speed_kph"], lap)[1][0]
    key = backend.series_key(lap, CHANNEL_MAP["speed_kph"])
    monkeypatch.setitem(cfg.units, "speed_unit", "MPH")
    app_signal.refresh.emit(True)  # settings dialog saved
    assert backend.data.series(CHANNEL_MAP["speed_kph"], lap)[1][0] == pytest.approx(kph / 1.609344)
    assert backend.series_key(lap, CHANNEL_MAP["speed_kph"]) != key  # drawn again
    assert backend.speedUnit == "mph"


# --- Coaching
def test_coaching_tips_causes():
    from tinypedal.userfile.corner_analysis import Corner, CornerComparison, CornerStats, coaching_tips

    corner = Corner(1, 100.0, 200.0, 300.0)
    reference = CornerStats(90.0, 200.0, 150.0, 240.0, 5.0, coasting=0.1, exit_speed=180.0)
    slow = CornerStats(85.0, 205.0, 130.0, 260.0, 5.3, coasting=0.5, exit_speed=170.0)
    fast = CornerStats(91.0, 200.0, 152.0, 238.0, 4.9)
    rows = [CornerComparison(corner, reference, slow), CornerComparison(corner, reference, fast),
            CornerComparison(corner, reference, None)]
    tips = coaching_tips(rows)
    assert len(tips) == 1 and tips[0].row == 0 and tips[0].loss == pytest.approx(0.3)
    kinds = [kind for kind, _ in tips[0].causes]
    assert set(kinds) == {"brake_early", "min_speed", "throttle_late", "coasting", "exit_speed"}
    assert dict(tips[0].causes)["brake_early"] == pytest.approx(20.0)


def test_coaching_in_corner_table(viewer, laps):  # noqa: F811
    backend = viewer.backend
    check_only(viewer, [laps[1], laps[2]])  # lap 3 slower in corners
    assert backend.coaching and backend.coachingLap
    tip = backend.coaching[0]
    assert tip["loss"].startswith("+") and tip["causes"] and 0 <= tip["index"] < len(backend.cornerRanges)


# --- Trash & undo, bulk actions, session menu
def test_trash_undo_and_bulk_actions(viewer, laps):  # noqa: F811
    from tinypedal.ui.quick.lap_backend import TRASH_FOLDER, purge_trash
    from tinypedal.userfile.lap_marks import kept_laps

    backend = viewer.backend
    folder = os.path.dirname(laps[0])
    check_only(viewer, [laps[1], laps[2]])
    backend.keepChecked(True)
    assert kept_laps(folder) == {os.path.basename(laps[1]), os.path.basename(laps[2])}
    backend.keepChecked(False)
    assert not kept_laps(folder)
    backend.deleteChecked()  # confirmation answered yes (fixture)
    wait_loaded(viewer)
    assert not os.path.exists(laps[1]) and not os.path.exists(laps[2])
    trash = os.path.join(cfg.path.telemetry, TRASH_FOLDER)
    assert len(os.listdir(trash)) == 1 and "2" in backend.undoText
    backend.undoDelete()
    wait_loaded(viewer)
    assert os.path.exists(laps[1]) and os.path.exists(laps[2]) and not os.listdir(trash)
    assert set(backend.ordered_checked()) == {laps[1], laps[2]}  # shown again
    session = rows_by_path(backend)[laps[0]]["session"]
    backend.sessionAction(session, "show")
    wait_loaded(viewer)
    assert len(backend.ordered_checked()) == 4
    backend.sessionAction(session, "delete")
    wait_loaded(viewer)
    assert not any(os.path.exists(path) for path in laps)
    old = os.path.join(trash, "2020-01-01 10-00-00")
    os.makedirs(old)
    assert purge_trash(cfg.path.telemetry) == 1 and not os.path.exists(old)  # older than kept days


# --- Search
def test_lap_list_search(viewer, laps):  # noqa: F811
    backend = viewer.backend
    check_only(viewer, [laps[1]])
    backend.setFilter("out lap")
    paths = set(rows_by_path(backend))
    assert laps[0] in paths and laps[1] in paths  # match, & checked lap kept listed
    assert laps[2] not in paths and laps[3] not in paths
    backend.setFilter("porsche invalid")
    assert set(rows_by_path(backend)) == {laps[1], laps[3]}
    backend.setFilter("")
    assert len(rows_by_path(backend)) == 4


# --- Delta best
def test_lap_as_delta_best(viewer, laps, monkeypatch):  # noqa: F811
    from tinypedal.userfile.delta_best import load_delta_best_file

    backend = viewer.backend
    backend.exportDeltaBest(laps[2])
    track = os.path.basename(os.path.dirname(laps[2]))
    data, best = load_delta_best_file(cfg.path.delta_best, track, ((), 0.0))
    assert best == pytest.approx(72.0) and len(data) > 100 and data[0] == (0.0, 0.0)
    backend.exportDeltaBest(laps[1])
    assert load_delta_best_file(cfg.path.delta_best, track, ((), 0.0))[1] == pytest.approx(70.0)
    assert os.path.exists(os.path.join(cfg.path.delta_best, f"{track}.csv.bak"))  # former file kept


# --- XY tab
def test_scatter_and_histogram(viewer):  # noqa: F811
    from tinypedal.ui.quick.lines import VertexStore

    backend = viewer.backend
    scatter = backend.scatter("speed_kph", "throttle")
    assert len(scatter["laps"]) == len(backend.legend) and scatter["xTicks"] and scatter["yTicks"]
    assert VertexStore.get(scatter["laps"][0]["key"]).vertex_count > 100
    backend.rebuild_chart()
    assert VertexStore.has(scatter["laps"][0]["key"])  # kept while shown
    histogram = backend.histogram("throttle")
    assert len(histogram["bins"]) == 10
    for lap in histogram["laps"]:
        assert sum(lap["values"]) == pytest.approx(100.0)
    gears = backend.histogram("gear")
    assert gears["bins"] == ["3", "4", "5", "6"]
    assert backend.xyChannels and all(not item["column"].startswith("all:") for item in backend.xyChannels)


# --- Session long run
def test_session_trend():
    from tinypedal.ui.quick.lap_backend import LapViewerBackend, least_squares, time_weights

    assert least_squares([(0, 1.0), (1, 2.0), (2, 3.0)]) == pytest.approx((1.0, 1.0))
    assert time_weights([0.0, 1.0, 3.0]) == pytest.approx([0.5, 1.5, 1.0])
    times = [90.0, 90.1, 90.2, 99.0, 90.4, 90.5]  # lap 4: traffic
    rows = [{"valid": True, "time": value} for value in times]
    trend = LapViewerBackend.session_trend(rows, [])
    assert rows[3]["outlier"] and not rows[0]["outlier"]
    assert trend["left"] == 1 and trend["slope"] == pytest.approx(0.1, abs=0.01)
    assert trend["pace"] == pytest.approx(sum(times[:3] + times[4:]) / 5)


# --- Heavy jobs in worker process
def test_track_limits_job_in_worker_process(laps):  # noqa: F811
    from tinypedal.ui.quick import lap_backend

    folder = cfg.path.telemetry
    track = os.path.basename(os.path.dirname(laps[1]))
    parts = os.path.join(folder, ".track_limits", f"{track}.laps")
    os.makedirs(parts)
    open(os.path.join(parts, "gone.csv.bin"), "wb").close()
    handle = lap_backend.start_job("track limits", lap_backend.track_limits_job, folder, parts,
                                   os.path.join(folder, track), laps[1:3], None, "lap")
    handle.join()
    result = handle.result()
    assert isinstance(result, dict) and "sectors" in result
    assert not os.listdir(parts)  # placement of removed lap pruned


# --- Recorder channels
def test_recorded_sample_matches_header(ui_env):
    from tinypedal.ui.lap_viewer import CHANNEL_MAP

    sample = module_recorder.read_sample(0.0)
    assert len(sample) == len(module_recorder.CSV_HEADER)
    assert module_recorder.tread_bands(list(range(12))) == (2, 3, 8, 9, 1, 4, 7, 10, 0, 5, 6, 11)
    for column in ("tyre_temp_in_fl", "tyre_load_rr", "brake_bias", "engine_map", "oil_temp"):
        assert column in module_recorder.CSV_HEADER and column in CHANNEL_MAP


def test_new_computed_channels(ui_env):
    from tinypedal.ui.lap_viewer import CHANNEL_MAP, PlotLap
    from tinypedal.ui.quick.trace_data import TraceData

    columns = {"distance": [0.0, 10.0], "tyre_temp_in_fl": [90.0, 92.0], "tyre_temp_out_fl": [80.0, 81.0],
               "vel_lat": [1.0, 0.0], "vel_long": [10.0, 0.5]}
    lap = PlotLap("a", "a", LapData("a", columns), QColor("red"))
    data = TraceData()
    data.set_laps([lap], "a")
    assert data.series(CHANNEL_MAP["camber_spread_fl"], lap)[1] == [10.0, 11.0]
    angles = data.series(CHANNEL_MAP["slip_angle"], lap)[1]
    assert angles[0] == pytest.approx(math.degrees(math.atan2(1.0, 10.0))) and angles[1] == 0.0  # too slow


# --- Passage A-B on time axis: same part of track for every lap
def test_range_stats_on_time_axis_measure_same_track_part(viewer, laps):  # noqa: F811
    backend = viewer.backend
    check_only(viewer, [laps[1], laps[2]])  # 70 s & 72 s laps
    distance_times = [row["time"] for row in backend.passageTimes(500.0, 1500.0)]
    backend.setTimeAxis(True)
    start, end = backend.xAtDistance(500.0), backend.xAtDistance(1500.0)
    assert [row["time"] for row in backend.passageTimes(start, end)] == distance_times
    assert len(set(distance_times)) == 2  # laps take different times there
    stats = backend.rangeStats(start, end)
    assert {lap["distance"] for lap in stats["laps"]} == {"1000 m"}
    backend.setTimeAxis(False)


# --- Worker process stopped with page & app
def test_worker_stopped_with_page_and_hooked_to_app_quit(viewer, laps):  # noqa: F811
    import time

    from tinypedal.ui.quick import lap_backend

    assert lap_backend.worker_pool() is not None and lap_backend._quit_hooked
    handle = lap_backend.start_job("sleep", time.sleep, 10)
    viewer.backend.release()  # page closed: worker & its job dropped
    assert lap_backend._worker is None
    handle.join()
    assert handle.result() in (None, lap_backend.JobHandle.BROKEN)


# --- XY tab choices kept
def test_xy_choices_kept(viewer, laps):  # noqa: F811
    from tests.test_lap_viewer import flush_deleted
    from tinypedal.ui.lap_viewer import LapViewer

    viewer.backend.setXyState("histogram", "speed_kph", "brake", "gear")
    viewer.backend.setXyState("scatter", "unknown", "brake", "gear")  # unknown channel: former one kept
    assert viewer.backend.xyState == {"mode": "scatter", "x": "speed_kph", "y": "brake", "histogram": "gear"}
    viewer.close()
    flush_deleted()
    other = LapViewer(None)
    try:
        assert other.backend.xyState["y"] == "brake" and other.backend.xyState["histogram"] == "gear"
    finally:
        other.close()
        flush_deleted()


# --- Car settings not recorded (-1)
def test_missing_car_settings_not_drawn(ui_env):
    from tinypedal.ui.lap_viewer import CHANNEL_MAP, PlotLap
    from tinypedal.ui.quick.trace_data import TraceData

    columns = {"distance": [0.0, 10.0, 20.0], "tc_level": [3.0, 3.0, 4.0], "abs_level": [-1.0, -1.0, -1.0]}
    lap = PlotLap("a", "a", LapData("a", columns), QColor("red"))
    data = TraceData()
    data.set_laps([lap], "a")
    assert data.available(CHANNEL_MAP["tc_level"]) and not data.available(CHANNEL_MAP["abs_level"])
    assert data.series(CHANNEL_MAP["abs_level"], lap) == ([], [])


# --- Unit change: lap list tooltips too
def test_units_refresh_lap_list_tooltips(viewer, laps, monkeypatch):  # noqa: F811
    from tinypedal import app_signal

    backend = viewer.backend
    next(entry for entry in backend.entries if entry.file.path == laps[1]).info["track_temperature"] = 25.0
    backend.fill_list()
    assert "25.0°C" in rows_by_path(backend)[laps[1]]["tip"]
    monkeypatch.setitem(cfg.units, "temperature_unit", "Fahrenheit")
    app_signal.refresh.emit(True)
    assert "77.0°F" in rows_by_path(backend)[laps[1]]["tip"]


# --- Corners across start line, braking point after an earlier brake tap
def test_corner_across_start_line_found_once():
    from tinypedal.userfile.corner_analysis import find_corners

    def speed(distance):  # corner apex at the start line, another one mid lap
        if distance < 300:
            return 120 + distance / 300 * 130
        if distance > 1700:
            return 250 - (distance - 1700) / 300 * 130
        return 250 - 130 * max(0.0, 1 - abs(distance - 1000) / 200)

    distances = [float(meter) for meter in range(0, 2001, 2)]
    lap = LapData("a", {"distance": distances, "speed_kph": [speed(distance) for distance in distances],
                        "lap_time": [distance / 50 for distance in distances]})
    corners = find_corners(lap)
    apexes = sorted(corner.apex for corner in corners)
    assert len(corners) == 2 and apexes[0] == pytest.approx(1000, abs=10)
    assert apexes[1] > 1970  # line corner kept once, on its apex side
    assert all(corner.start <= corner.apex <= corner.end for corner in corners)


def test_braking_point_ignores_earlier_brake_tap():
    from tinypedal.userfile.corner_analysis import Corner, corner_stats

    distances = [float(meter) for meter in range(0, 1001, 2)]
    speeds = [250 - 150 * max(0.0, 1 - abs(distance - 500) / 100) for distance in distances]
    brake = [1.0 if 200 <= distance <= 206 or 400 <= distance <= 480 else 0.0 for distance in distances]
    lap = LapData("a", {"distance": distances, "speed_kph": speeds, "brake": brake,
                        "lap_time": [distance / 50 for distance in distances]})
    stats = corner_stats(lap, Corner(1, 100.0, 500.0, 700.0))
    assert stats.brake_point == pytest.approx(400, abs=6)


# --- Lap cache temporary files
def test_lap_cache_prune_keeps_files_being_written(tmp_path):
    import time

    from tinypedal.userfile import lap_cache

    folder = tmp_path / lap_cache.CACHE_FOLDER
    folder.mkdir()
    fresh, stale = folder / "a.bin.1.2.tmp", folder / "b.bin.1.2.tmp"
    fresh.write_bytes(b"x")
    stale.write_bytes(b"x")
    old = time.time() - lap_cache.STALE_TEMP - 10
    os.utime(stale, (old, old))
    assert lap_cache.prune_cache(str(tmp_path)) == 1
    assert fresh.exists() and not stale.exists()


# --- Increasing distances found once per lap
def test_monotonic_distance_without_copy():
    from tinypedal.userfile.telemetry_lap import increasing_indexes, monotonic_distance

    lap = LapData("a", {"distance": array("d", [0.0, 1.0, 2.0]), "speed_kph": array("f", [1.0, 2.0, 3.0])})
    distances, values = monotonic_distance(lap, "speed_kph")
    assert distances is lap.distance and values is lap.columns["speed_kph"]  # every sample forward: no copy
    glitch = LapData("b", {"distance": [0.0, 5.0, 4.0, 6.0], "speed_kph": [1.0, 2.0, 3.0, 4.0]})
    assert increasing_indexes(glitch.distance) == [0, 1, 3]
    assert monotonic_distance(glitch, "speed_kph") == ([0.0, 5.0, 6.0], [1.0, 2.0, 4.0])


# --- Shapes told about their own vertices only
def test_vertex_store_wakes_only_shapes_of_key(ui_env):
    from tinypedal.ui.quick.lines import GpuShape, VertexStore, line_strip

    first, second = GpuShape(), GpuShape()
    first.setProperty("key", "test|a")
    second.setProperty("key", "test|b")
    calls = []
    first.update = lambda: calls.append("a")
    second.update = lambda: calls.append("b")
    VertexStore.set("test|a", line_strip([0.0, 1.0], [0.0, 1.0]))
    assert calls == ["a"]
    VertexStore.set("test|b", line_strip([0.0, 1.0], [0.0, 1.0]))
    VertexStore.remove_prefix("test|")  # removed vertices: their shapes drawn empty
    assert sorted(calls) == ["a", "a", "b", "b"]


def test_band_part_matches_band():
    from tinypedal.ui.quick.lines import band, band_part, merge_strips, normals

    xs, ys = [0.0, 1.0, 2.0, 3.0], [0.0, 0.5, 0.0, 0.5]
    whole = band(xs, ys, 0.2)
    assert list(band_part(xs, ys, normals(xs, ys), range(4), 0.2).data) == list(whole.data)
    merged = merge_strips([whole])
    assert merged.vertex_count == (whole.vertex_count - 2) * 3
    assert list(merged.data[:6]) == list(whole.data[:6]) and list(merged.data[6:12]) == list(whole.data[2:8])


# --- Per lap results kept when laps change, map scale built in background
def test_lap_results_kept_and_map_scale_in_background(viewer, laps):  # noqa: F811
    from tinypedal.ui.quick import lap_backend
    from tinypedal.ui.quick.lines import VertexStore

    backend = viewer.backend
    check_only(viewer, [laps[1], laps[2]])
    lap = backend.data.laps[0]
    sampled = backend.resampled(lap)
    g_key = backend.gCircle["dots"][0]["key"]
    dots = VertexStore.get(g_key)
    backend.rebuild_chart()
    assert VertexStore.get(g_key) is dots  # G dots not built again
    backend.setHysteresis(backend.hysteresis + 2)
    assert backend.resampled(lap) is sampled  # columns not resampled again for new corners
    backend.setMapView(0, 0, 1.0)
    backend.wait_jobs()
    backend.setMapView(0, 0, 8.0)  # new scale: nearest built one shown, this one built in background
    backend.wait_jobs()
    assert backend._preview_step == lap_backend.scale_step(8.0)


# --- Exports in worker process
def test_exports_in_background(viewer, laps, tmp_path):  # noqa: F811
    backend = viewer.backend
    folder = tmp_path / "motec"
    folder.mkdir()
    assert backend.export_many(laps[1:3], str(folder)) == 0  # background
    assert backend.is_loading()
    backend.wait_jobs()
    assert len(os.listdir(folder)) == 2 and not backend.is_loading()
    target = tmp_path / "laps.csv"
    assert backend.write_csv(str(target), ".", background=True)
    backend.wait_jobs()
    rows = target.read_text(encoding="utf-8-sig").splitlines()
    assert len(rows) > 100 and rows[1].startswith("0,")
    assert "Exported" in backend.status


# --- Recorder keeps binary copy, folder watch ignores hidden files
def test_recorder_writes_lap_cache(ui_env):
    from tinypedal.userfile import lap_cache

    path = save(1, 70.0, BASE)
    assert os.path.exists(lap_cache.cache_file(cfg.path.telemetry, path))


def test_folder_watch_ignores_settings_and_caches(viewer, laps):  # noqa: F811
    backend = viewer.backend
    folder = os.path.dirname(laps[0])
    backend._watch_timer.stop()
    with open(os.path.join(cfg.path.telemetry, ".lap_viewer.json"), "a", encoding="utf-8"):
        pass
    backend.folder_changed(cfg.path.telemetry.rstrip("/"))
    backend.folder_changed(folder)
    assert not backend._watch_timer.isActive()
    save(9, 75.0, BASE + 900)
    backend.folder_changed(folder)
    assert backend._watch_timer.isActive()  # new lap file: list refreshed
    backend._watch_timer.stop()


# --- Kept QML models: rows removed, moved, inserted & changed in place (delegates of kept rows stay)
def test_list_model_sync_in_place(ui_env):
    from tinypedal.ui.quick.models import DictListModel

    model = DictListModel(("key", "value"))
    model.sync([{"key": "a", "value": 1}, {"key": "b", "value": 2}, {"key": "c", "value": 3}])
    kept = model.rows[2]
    events: list[str] = []
    model.rowsRemoved.connect(lambda *args: events.append("removed"))
    model.rowsInserted.connect(lambda *args: events.append("inserted"))
    model.rowsMoved.connect(lambda *args: events.append("moved"))
    model.modelReset.connect(lambda: events.append("reset"))
    model.dataChanged.connect(lambda *args: events.append("changed"))
    model.sync([{"key": "c", "value": 3}, {"key": "a", "value": 5}, {"key": "d", "value": 4}])
    assert [(row["key"], row["value"]) for row in model.rows] == [("c", 3), ("a", 5), ("d", 4)]
    assert model.rows[0] is kept  # unchanged row kept as is
    assert sorted(events) == ["changed", "inserted", "moved", "removed"]


# --- Exports: whole files only, failures counted with reason, finished when viewer closes
def test_export_failure_reported(viewer, laps, tmp_path):  # noqa: F811
    from tinypedal.userfile.motec_ld import export_lap_job
    from tinypedal.userfile.telemetry_lap import write_lap_csv

    backend = viewer.backend
    out = tmp_path / "out"
    out.mkdir()
    assert export_lap_job(backend.folder, laps[1], str(out / "lap.ld")) == ""
    assert os.listdir(out) == ["lap.ld"]  # temporary file renamed
    missing = tmp_path / "missing"
    assert backend.export_many(laps[1:3], str(missing), background=False) == 0
    assert "2 failed: " in backend.status and "Exported <b>0</b>" in backend.status
    assert backend.export_many(laps[1:3], str(missing)) == 0  # background
    backend.wait_jobs()
    assert "2 failed: " in backend.status and not backend.is_loading()
    assert write_lap_csv(str(missing / "laps.csv"), ["a"], [0.0], [[1.0]]) != ""
    assert write_lap_csv(str(out / "laps.csv"), ["a"], [0.0], [[1.0]]) == ""
    assert sorted(os.listdir(out)) == ["lap.ld", "laps.csv"]


def test_closing_viewer_lets_exports_finish(viewer, laps, tmp_path, monkeypatch):  # noqa: F811
    from tinypedal.ui.quick import lap_backend

    backend = viewer.backend
    calls: list[tuple] = []
    monkeypatch.setattr(lap_backend, "kill_worker", lambda: calls.append(("kill",)))
    monkeypatch.setattr(lap_backend, "stop_worker", lambda kill=False, finish=False: calls.append(("stop", finish)))
    backend._exports = 1
    backend.release()
    assert calls == [("stop", True)]  # export finishes in worker process
    backend._exports = 0
    backend.release()
    assert calls[-1] == ("kill",)  # nothing to finish: running job dropped


def test_app_exit_waits_for_exports_only(laps):  # noqa: F811
    import time

    from tinypedal.ui.quick import lap_backend

    export = lap_backend.start_job("MoTeC export", time.sleep, 0.3)
    lap_backend.stop_worker(finish=True)  # viewer closed while exporting: export goes on
    other = lap_backend.start_job("sleep", time.sleep, 10)
    start = time.monotonic()
    lap_backend.quit_workers()
    assert export.future.done() and not export.future.cancelled() and export.future.exception() is None
    assert time.monotonic() - start < lap_backend.EXIT_EXPORT_WAIT  # other job not waited for
    other.join()
    assert other.result() in (None, lap_backend.JobHandle.BROKEN)


def test_loading_one_lap_message(viewer, laps, monkeypatch):  # noqa: F811
    backend = viewer.backend
    shown: list[str] = []
    set_status = backend.set_status
    monkeypatch.setattr(backend, "set_status", lambda text, transient=True: (shown.append(text), set_status(text, transient)))
    backend.load_in_background([laps[3]])
    wait_loaded(viewer)
    assert shown[0] == "Loading 1 lap..."


# --- Theme values copied into QML (no Python call per binding), follow palette
def test_theme_copy_follows_palette(ui_env):
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui import set_style_palette
    from tinypedal.ui.quick import Theme, create_quick_view

    parent = QWidget()
    view = create_quick_view(parent, "Card.qml", {})
    theme = view.rootContext().contextProperty("theme")
    original = Theme()
    assert not isinstance(theme, Theme)
    assert theme.property("em") == original.em and theme.property("iconFont") == original.iconFont
    try:
        for name in ("Light", "Dark"):
            set_style_palette(name)
            assert theme.property("dark") == (name == "Dark") == original.dark
            assert theme.property("window") == original.window and theme.property("loss") == original.loss
    finally:
        set_style_palette("Dark")
        parent.deleteLater()


# --- Keyboard focus on charts at opening, side tabs kept once opened
def test_charts_focused_and_tabs_kept(viewer, laps):  # noqa: F811
    from PySide6.QtWidgets import QApplication

    def items(type_name, item=None):  # visual tree (repeater items have no object parent)
        item = item or viewer.view.rootObject()
        found = [item] if item.metaObject().className().startswith(type_name) else []
        for child in item.childItems():
            found += items(type_name, child)
        return found

    chart = items("TraceChart")[0]
    assert chart.hasFocus()  # focus inside page: keys go to charts once window is active
    backend = viewer.backend
    assert not items("XYView")  # created when first shown
    backend.setSideTab(5)
    QApplication.processEvents()
    xy = items("XYView")
    assert len(xy) == 1
    backend.setSideTab(0)
    QApplication.processEvents()
    backend.setSideTab(5)
    QApplication.processEvents()
    assert items("XYView") == xy  # same tab shown again, not created again


# --- Playback: back / forward in time, speed steps
def test_playback_skip_and_speed(viewer, laps):  # noqa: F811
    from PySide6.QtCore import Q_ARG, QMetaObject

    def find(item):
        if item.metaObject().className().startswith("TraceChart"):
            return item
        return next((found for child in item.childItems() if (found := find(child)) is not None), None)

    chart = find(viewer.view.rootObject())
    backend = viewer.backend

    def call(name, *args):
        QMetaObject.invokeMethod(chart, name, *(Q_ARG("QVariant", arg) for arg in args))

    assert backend.referenceLapTime > 0
    middle = backend.referenceTimeAt(chart.property("maxX") / 2)
    call("skipTime", 2.0)  # no cursor: from view center
    assert backend.referenceTimeAt(chart.property("cursorX")) == pytest.approx(middle + 2, abs=0.05)
    call("skipTime", -4.0)
    assert backend.referenceTimeAt(chart.property("cursorX")) == pytest.approx(middle - 2, abs=0.05)
    call("skipTime", -1000.0)  # kept inside lap
    assert chart.property("cursorX") == pytest.approx(0.0, abs=1.0)
    call("togglePlay")
    assert chart.property("playing")
    call("skipTime", 5.0)
    assert chart.property("playTime") == pytest.approx(5.0, abs=0.1)  # played time moved
    call("skipTime", -100.0)
    assert chart.property("playTime") == pytest.approx(chart.property("playFrom"))
    call("togglePlay")
    speeds = chart.property("playSpeeds").toVariant()
    assert chart.property("playSpeed") == 1 and 1 in speeds
    call("changeSpeed", 1)
    assert chart.property("playSpeed") == speeds[speeds.index(1) + 1]
    for _ in speeds:
        call("changeSpeed", -1)
    assert chart.property("playSpeed") == speeds[0]


# --- Cursor value bubbles: rows placed by bindings, not Column / Row (positioners lay out while frame is drawn and
# ask for a second frame each cursor move: playback stutters), empty values skipped, bubble as wide as widest row
def test_value_bubbles_without_positioners(viewer, laps):  # noqa: F811
    from PySide6.QtCore import Q_ARG, QMetaObject
    from PySide6.QtWidgets import QApplication

    def tree(item):
        yield item
        for child in item.childItems():
            yield from tree(child)

    check_only(viewer, [laps[1], laps[2]])
    chart = next(item for item in tree(viewer.view.rootObject())
                 if item.metaObject().className().startswith("TraceChart"))
    QMetaObject.invokeMethod(chart, "setCursor", Q_ARG("QVariant", chart.property("maxX") / 2),
                             Q_ARG("QVariant", "pin"))
    QApplication.processEvents()
    bubbles = [item for item in tree(chart) if item.property("panelIndex") is not None]
    assert bubbles
    assert not any(item.metaObject().className().startswith(("QQuickColumn", "QQuickRow"))
                   for bubble in bubbles for item in tree(bubble))
    shown = 0
    for bubble in bubbles:
        if not bubble.isVisible():  # panel too small: values under channel name
            continue
        column = bubble.childItems()[0]
        row_height = column.property("rowHeight")
        rows = sorted((row for row in column.childItems()  # delegates of rows repeater, empty values hidden
                       if row.isVisible() and not row.metaObject().className().startswith("QQuickRepeater")),
                      key=lambda row: row.y())
        assert [row.y() for row in rows] == pytest.approx([index * row_height for index in range(len(rows))])
        assert column.height() == pytest.approx(len(rows) * row_height)
        assert column.width() == pytest.approx(max((row.width() for row in rows), default=0))
        shown += len(rows)
    assert shown >= 2  # a value of each lap at least
