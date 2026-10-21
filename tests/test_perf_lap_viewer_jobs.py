"""Lap viewer page thread kept free: one charts job at a time (stale ones stop early), live trace data settings kept,
map scale steps built from a frozen frame, lap infos index parsed once, track limits cache read in a job, session
tab state built once, map hover in one call, zoomed XY axis labels cached, corner table model"""

import json
import os
import threading
import time

import pytest

from tests.test_lap_viewer import wait_loaded
from tests.test_lap_viewer_background import off_thread, record_threads
from tests.test_lap_viewer_e2 import TRACK
from tests.test_lap_viewer_features import laps  # noqa: F401
from tests.test_lap_viewer_fix_backend import backend  # noqa: F401
from tests.test_lap_viewer_fix_qml import chart_of, evaluate, find, opener, wait, warnings  # noqa: F401


def show_all(page):
    page.checked = {entry.file.path for entry in page.entries}
    page.load_laps()
    wait_loaded(page)
    page.wait_jobs()


# --- Charts: single flight, stale build stopped, changes kept together
def test_charts_single_flight_and_stale_build_stopped(backend, monkeypatch):  # noqa: F811
    from neopedal.ui import lap_viewer
    from neopedal.ui.lap_viewer import SMOOTHING_LEVELS
    from neopedal.userfile import lap_geometry

    page = backend
    show_all(page)
    monkeypatch.setattr(lap_viewer, "BACKGROUND_CHART_SAMPLES", 1)
    monkeypatch.setattr(lap_geometry, "YIELD_EVERY", 0.0)  # pause checks at every series
    started = threading.Event()
    release = threading.Event()
    original = page.chart_vertices
    builds: list[int] = []

    def slow(data, visible, envelope, have=None, pause=None):
        if data is not page.data:  # background builds (panels use page trace data)
            builds.append(1)
        if len(builds) == 1 and data is not page.data:
            started.set()
            release.wait(5)
        return original(data, visible, envelope, pause=pause) if have is None else original(data, visible, envelope,
                                                                                            have, pause)

    monkeypatch.setattr(page, "chart_vertices", slow)
    page.setSmoothing(1)
    assert started.wait(5)
    for level in (2, 3, 1, 2):  # slider dragged: no new thread while one runs
        page.setSmoothing(level)
    assert len([handle for handle, *_ in page._jobs if handle.name == "charts"]) == 1
    release.set()
    page.wait_jobs()
    assert len(builds) == 2  # stale build stopped, built once more with the newest settings
    assert page.data.smoothing == SMOOTHING_LEVELS[2] and not page.is_loading()


def test_yielder_cancels():
    from neopedal.userfile.lap_geometry import JobCancelled, Yielder

    pause = Yielder(0.0, cancelled=lambda: True)
    with pytest.raises(JobCancelled):
        pause()
    Yielder(0.0, cancelled=lambda: False)()  # goes on


def test_time_axis_toggles_switch_once(backend, monkeypatch):  # noqa: F811
    from neopedal.ui import lap_viewer

    page = backend
    show_all(page)
    monkeypatch.setattr(lap_viewer, "BACKGROUND_CHART_SAMPLES", 1)
    calls: list[bool] = []
    monkeypatch.setattr(page, "axis_switched", lambda enabled: calls.append(enabled))
    page.setTimeAxis(True)
    page.setTimeAxis(False)
    page.setTimeAxis(True)
    assert page._chart_afters.count(page.time_axis_switched) == 1
    page.wait_jobs()
    assert calls == [True] and page.data.time_axis


def test_adopt_keeps_live_sector_lines(ui_env):
    from neopedal.ui.quick.trace_data import TraceData

    data = TraceData()
    snapshot = data.snapshot()
    snapshot.set_smoothing(5)
    data.set_sector_lines([100.0, 200.0])  # set on page thread while snapshot is worked on
    assert data.adopt(snapshot) and data.smoothing == 5 and data.sector_lines == [100.0, 200.0]
    assert "live_base" not in data.__dict__


def test_rejected_snapshot_built_again_in_background(backend, monkeypatch):  # noqa: F811
    from neopedal.ui import lap_viewer

    page = backend
    show_all(page)
    monkeypatch.setattr(lap_viewer, "BACKGROUND_CHART_SAMPLES", 1)
    finished: list[bool] = []
    original_finish = page.finish_chart
    monkeypatch.setattr(page, "finish_chart", lambda: (finished.append(True), original_finish()))
    calls: list[bool] = []
    monkeypatch.setattr(page, "chart_vertices", record_threads(page, "chart_vertices", calls,
                                                               lambda data, *_: data is not page.data))
    page.setSmoothing(2)
    page.data.set_offsets({})  # unchanged: same version
    page.data.drop_series(["rpm"])  # trace data changed meanwhile: snapshot refused
    page.wait_jobs()
    assert len(calls) >= 2 and off_thread(calls) and finished == [True]
    assert page.data.smoothing == lap_viewer.SMOOTHING_LEVELS[2]


# --- Simple view series built with charts once it was opened
def test_simple_view_series_warmed_in_background(backend, monkeypatch):  # noqa: F811
    from neopedal.ui import lap_viewer
    from neopedal.ui.lap_viewer import CHANNEL_MAP

    page = backend
    show_all(page)
    monkeypatch.setattr(lap_viewer, "BACKGROUND_CHART_SAMPLES", 1)
    assert page.dashboard.columns() == []  # simple view never opened
    page.setSimpleView(True)
    page.wait_jobs()
    columns = page.dashboard.columns()
    assert "throttle" in columns and "clutch" in columns  # pedal cards read clutch, not charted
    page.setSmoothing(2)
    page.wait_jobs()
    channel = CHANNEL_MAP["clutch"]
    assert all(page.data.series_cached(channel, lap) for lap in page.data.laps)


# --- Lap infos index parsed once while its file stays the same
def test_info_index_parsed_once(backend, monkeypatch):  # noqa: F811
    from neopedal.userfile import lap_cache

    page = backend
    path = page.info_index_path(TRACK)
    assert os.path.isfile(path)
    loads: list[str] = []
    original = json.load
    monkeypatch.setattr(lap_cache.json, "load", lambda file: (loads.append(file.name), original(file))[1])
    first = lap_cache.read_index(path)
    assert lap_cache.read_index(path) is first and not loads  # parsed when written
    os.utime(path, ns=(time.time_ns(), time.time_ns() + 5_000_000))
    assert lap_cache.read_index(path) == first and len(loads) == 1


def test_index_save_always_scheduled(backend):  # noqa: F811
    page = backend
    path = page.info_index_path(TRACK)
    page._index_saves[path] = {"x": [1, 2, {}]}  # an earlier save waiting
    page.save_index_later(path, {"y": [1, 2, {}]})
    assert [handle.name for handle, *_ in page._jobs].count("lap infos index") >= 1
    page.wait_jobs()
    with open(path, encoding="utf-8") as file:
        assert json.load(file) == {"y": [1, 2, {}]}


# --- Track limits cache read in a job, saved whole
def test_limits_cache_read_in_job(backend, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import lap_loading

    page = backend
    page.wait_jobs()
    while page._limits_job is not None:
        page._limits_job.join()
        page.check_limits_job()
    page.wait_jobs()
    cache = page.limits_cache_path(TRACK)
    assert page._limits is not None and os.path.isfile(cache)
    assert not [name for name in os.listdir(os.path.dirname(cache)) if name.endswith(".tmp")]
    calls: list[bool] = []
    monkeypatch.setattr(lap_loading, "read_limits_cache", record_threads(lap_loading, "read_limits_cache", calls))
    page._limits, page._limits_track = None, ""
    page.start_limits(TRACK)
    assert page._limits is None and page.is_loading()  # read in background
    page.wait_jobs()
    assert off_thread(calls) and page._limits is not None and page._limits_job is None


# --- Undo restores marks with one write per folder
def test_undo_restores_marks_once_per_folder(backend, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import lap_actions
    from neopedal.userfile import lap_marks

    page = backend
    paths = [entry.file.path for entry in page.entries[:2]]
    for path in paths:
        page.keepLap(path, True)
    page.deleteLaps(paths)
    page.wait_jobs()
    saves: list[str] = []
    original = lap_marks.save_marks
    monkeypatch.setattr(lap_marks, "save_marks", lambda folder, marks: (saves.append(folder), original(folder, marks))[1])
    monkeypatch.setattr(lap_actions, "set_mark", lambda *args, **kwargs: pytest.fail("one write per lap"))
    page.undoDelete()
    assert len(saves) == 1
    assert all(page.lap_marks(path).get("kept") for path in paths)


# --- Map: scale steps from frozen frame, caches bounded, mapBounds, hover in one call
def test_map_steps_frozen_and_caches_bounded(backend, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import lap_map_view

    page = backend
    show_all(page)
    assert page._map
    frame = page.map_frame()
    assert not any(key[1] == 32.0 for key in page._lap_shapes)
    shapes = page.scale_shapes(32.0, frame)
    assert shapes and frame["new"]["lap_shapes"]  # results left in frame, page untouched
    assert not any(key[1] == 32.0 for key in page._lap_shapes)
    monkeypatch.setattr(lap_map_view, "BAND_CACHE_STEPS", 3)
    for step in range(12):
        page.setMapView(0, 0, 2 ** (step / 2 - 2))
        page.wait_jobs()
    kept = set(page._band_cache) | {lap_map_view.scale_step(page._map_view[2])}
    assert len(page._band_cache) <= 3
    assert all(lap_map_view.scale_step(key[1]) in kept for key in page._lap_shapes)
    assert all(step in kept for step in page._colored_steps)


def test_stale_map_step_stopped(backend, monkeypatch):  # noqa: F811
    from neopedal.userfile import lap_geometry

    page = backend
    show_all(page)
    monkeypatch.setattr(lap_geometry, "YIELD_EVERY", 0.0)
    results: list = []
    original = page.scale_shapes

    def built_late(meters_per_pixel, frame=None, pause=None):
        page._band_generation += 1  # map built again meanwhile
        try:
            results.append(original(meters_per_pixel, frame, pause))
        except lap_geometry.JobCancelled:
            results.append("cancelled")
            raise
        return results[-1]

    monkeypatch.setattr(page, "scale_shapes", built_late)
    page.prepare_step(3.5)
    page.wait_jobs()
    assert results == ["cancelled"] and 3.5 not in page._band_cache


def test_part_bounds_same_as_part():
    from neopedal.ui.quick import lap_map

    count = 1000
    line = lap_map.MapLine([float(index) for index in range(count)], [(index * 37 % 101) - 50.0 for index in range(count)],
                           [(index * 53 % 89) * 1.5 for index in range(count)])
    boxes = lap_map.chunk_boxes(line)
    for start, end in ((0, 999), (10.5, 20.2), (63, 64), (60, 300), (5, 6), (500, 400), (-10, 2000), (900, 999)):
        part = lap_map.part(line, start, end)
        expected = [min(part.xs), min(part.ys), max(part.xs), max(part.ys)] if len(part.xs) >= 2 else []
        assert lap_map.part_bounds(line, boxes, start, end) == expected


def test_map_hover_one_call_same_results(backend):  # noqa: F811
    page = backend
    show_all(page)
    page.setMapShown(True)
    line = page.reference_map_line()
    assert line is not None
    page.mapPointer.setMapKinds(["brake", "apex"])
    for index in (10, len(line.xs) // 3, len(line.xs) // 2):
        x, y = line.xs[index], line.ys[index]
        hover = page.mapPointer.mapHover(x, y, 5.0, 8.0, "", True)
        assert hover["point"] == page.mapPointer.mapPointAt(x, y, 5.0, ["brake", "apex"])
        position = page.mapPointer.mapPick(x, y, 8.0)
        assert hover["x"] == position and position >= 0
        assert hover["placement"] == ({} if "tip" in hover["point"] else page.placementAt(position, ""))
        assert hover["cursor"] is page.cursorState(position)  # same position & state: cached
    assert "x" not in page.mapPointer.mapHover(line.xs[5], line.ys[5], 5.0, 8.0, "", False)  # no scrub (lap playing)
    state = page.cursorState(300.0)
    assert all("color" not in value for values in state["values"] for value in values)
    assert all("color" not in point and "lap" not in point for point in state["map"])
    page.setMapShown(False)


# --- Session tab: one state built per change
def test_session_state_built_once(backend, monkeypatch):  # noqa: F811
    page = backend
    show_all(page)
    calls: list[int] = []
    session = page.session
    original = session.session_groups
    monkeypatch.setattr(session, "session_groups", lambda: (calls.append(1), original())[1])
    state = session.state
    assert session.sessions is state["sessions"] and session.key == state["key"] and session.values is state["data"]
    assert len(calls) == 1
    session.changed.emit()
    assert session.state is not state and len(calls) == 2


def test_pictures_update_logos_in_place(backend, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import lap_library

    page = backend
    rows = list(page.lap_model.rows)
    monkeypatch.setattr(page, "fill_list", lambda: pytest.fail("list built again"))
    monkeypatch.setattr(lap_library, "brand_logo_url", lambda vehicle: f"logo:{vehicle}")
    page.pictures_changed()
    assert page.lap_model.rows == rows
    assert all(row["logo"] == f"logo:{row['brand']}" for row in rows if row["kind"] == "session" and row.get("brand"))


def test_consistency_file_times_asked_once(backend, monkeypatch):  # noqa: F811
    page = backend
    show_all(page)
    asked: list[str] = []
    original = os.path.getmtime
    monkeypatch.setattr(os.path, "getmtime", lambda path: (asked.append(path), original(path))[1])
    page.mapConsistency.lap_mtime(page.entries[0].file.path)
    page.mapConsistency.lap_mtime(page.entries[0].file.path)
    assert len(asked) == 1
    page.fill_list()  # list filled again: asked again
    asked.clear()
    page.mapConsistency.lap_mtime(page.entries[0].file.path)
    assert len(asked) == 1


def test_axis_labels_same_as_ticks(backend):  # noqa: F811
    page = backend
    for column, low, high in (("speed_kph", 52.3, 87.9), ("throttle", 0.1, 0.4), ("accel_lat", -1.2, 0.3)):
        ticks = page.charts.axisTicks(column, low, high)
        assert page.charts.axisLabels(column, [tick["value"] for tick in ticks], high - low) == [tick["text"] for tick in ticks]


def test_corner_model_follows_corners(backend):  # noqa: F811
    page = backend
    show_all(page)
    rows = page.cornerTable.items
    assert page.cornerTable.row_model.rowCount() == len(rows) and page.cornerTable.count == len(page.cornerTable.rows)
    assert [row["label"] for row in page.cornerTable.row_model.rows] == [row["label"] for row in rows]
    if page.cornerTable.rows:
        assert page.cornerTable.position(0) == next(number for number, row in enumerate(rows)
                                              if row["kind"] == "corner" and row["index"] == 0)
        assert page.cornerTable.maxDelta >= 0.05


# --- QML: side tabs open without warnings, hidden tabs never read backend
def test_side_tabs_open_without_warnings(opener, warnings):  # noqa: F811
    dialog = opener()
    view, page = dialog.view, dialog.backend
    chart = chart_of(view)
    evaluate(view, chart, "setCursor(500, 'key')")
    for tab in (1, 2, 3, 4, 5, 0):
        page.setSideTab(tab)
        wait(0.5)
    page.setSimpleView(True)  # simple view over charts, then hidden again (kept)
    wait(0.5)
    page.setSimpleView(False)
    wait(0.3)
    sessions = find(view, lambda item: item.property("sessionState") is not None)
    assert sessions and sessions[0].property("laps")
    page.setSideTab(0)  # session tab hidden: not read again until shown
    wait(0.3)
    reads: list[int] = []
    original = type(page.session).session_state
    try:
        type(page.session).session_state = lambda self: (reads.append(1), original(self))[1]
        page.session.changed.emit()
        wait(0.2)
        assert not reads and sessions[0].property("stale")
        page.setSideTab(4)
        wait(0.5)
        assert reads and not sessions[0].property("stale")
    finally:
        type(page.session).session_state = original
    simple = find(view, lambda item: item.property("cardsShown") is not None)
    page.setSideTab(5)  # XY: zoomed axis labels asked once per tick set
    wait(0.5)
    xy = find(view, lambda item: item.property("labelCache") is not None)[0]
    evaluate(view, xy, "zoomAt(2, 50, 50)")
    wait(0.1)
    ticks = evaluate(view, xy, "xTicks.length")
    assert ticks > 0
    assert simple and evaluate(view, simple[0], "layout.length") == 0  # simple view hidden: layout not read
    for map_item in find(view, lambda item: item.property("rulerMode") is not None):
        assert map_item.property("kindsShown")


def test_map_hover_scrubs_chart(opener, warnings):  # noqa: F811
    dialog = opener()
    view, page = dialog.view, dialog.backend
    chart = chart_of(view)
    page.setSideTab(0)
    wait(0.4)
    line = page.reference_map_line()
    track_map = next(item for item in find(view, lambda item: item.property("rulerMode") is not None)
                     if item.isVisible())
    index = len(line.xs) // 3
    evaluate(view, track_map, f"hoverPosition = [{line.xs[index]}, {line.ys[index]}]")
    evaluate(view, track_map, "handleHover()")
    wait(0.1)
    assert track_map.property("scrubbing") and chart.property("cursorSource") == "map"
    assert evaluate(view, chart, "cursorMap.length") > 0 and chart.property("cursorTitle")
