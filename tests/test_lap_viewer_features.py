"""Lap viewer: units, names, cursor values, axes, corners, map click, lap marks, selection, time axis, CSV..."""

import math
import os
import time

import pytest
from PySide6.QtWidgets import QMessageBox

from tests.test_lap_viewer import flush_deleted, wait_loaded
from tinypedal.module import module_recorder
from tinypedal.setting import cfg

TRACK = "Atlanta - Hyper"
LENGTH = 2000.0
BASE = time.mktime((2026, 10, 3, 14, 0, 0, 0, 0, -1))


def lap_rows(lap_time: float, slow: float = 1.0, samples: int = 400) -> list[tuple]:
    """Oval lap with 2 corners (speed dips), pedals & steering following them, gears stepping"""
    rows = []
    elapsed = 0.0
    for index in range(samples + 1):
        progress = index / samples
        distance = progress * LENGTH
        corner = (math.cos(progress * math.tau * 2) + 1) / 2  # 1 on straights, 0 at corner apex
        speed = 120 + 130 * corner * slow
        braking = 1.0 if 0.25 < corner < 0.7 and math.sin(progress * math.tau * 2) > 0 else 0.0
        throttle = 0.0 if braking else min(corner * 1.5, 1.0)
        steering = (1 - corner) * 0.5
        gear = 3 + round(corner * 3)
        elapsed = progress * lap_time
        angle = progress * math.tau
        row = [elapsed, elapsed, distance, speed, throttle, braking, 0.0, steering, gear, 7000, 50 - progress,
               80, 82, 78, 79, 170, 171, 169, 170, 300 * math.cos(angle), 200 * math.sin(angle)]
        rows.append(tuple(row + [0.0] * (len(module_recorder.CSV_HEADER) - len(row))))
    return rows


def save(number: int, lap_time: float, timestamp: float, valid: bool = True, session: str = "Practice",
         kind: str = "lap", slow: float = 1.0, folder: str = "") -> str:
    folder = folder or cfg.path.telemetry.rstrip("/")
    info = {"kind": kind, "session": session, "vehicle": "Porsche 963", "session_start": BASE}
    module_recorder.save_lap(f"{folder}/", TRACK, number, lap_time, lap_rows(lap_time, slow), max_saved_laps=99,
                             valid=valid, info=info, timestamp=timestamp)
    name = module_recorder.lap_filename(number, lap_time, valid, timestamp)
    return os.path.join(f"{folder}/{TRACK}", name)  # same path as lap viewer lists


@pytest.fixture
def laps(ui_env, monkeypatch):
    """Practice session: lap 1 out lap, 2 fast, 3 slower, 4 invalid"""
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    return [
        save(1, 95.0, BASE + 100, kind="out", slow=0.8),
        save(2, 70.0, BASE + 200),
        save(3, 72.0, BASE + 300, slow=0.95),
        save(4, 71.0, BASE + 400, valid=False),
    ]


@pytest.fixture
def viewer(laps):
    from tinypedal.ui.lap_viewer import LapViewer

    dialog = LapViewer(None)
    dialog.resize(1300, 800)
    wait_loaded(dialog)
    yield dialog
    import shiboken6

    if shiboken6.isValid(dialog):  # closed by test
        dialog.close()
    flush_deleted()


def check_only(viewer, paths):
    backend = viewer.backend
    for row in backend.lap_rows():
        backend.checked.discard(row["path"])
    backend.checked.update(paths)
    backend.load_laps()
    wait_loaded(viewer)


def rows_by_path(backend) -> dict[str, dict]:
    return {row["path"]: row for row in backend.lap_rows()}


# --- 1. Lap names
def test_lap_names(viewer, laps):
    from tinypedal.ui.lap_viewer import lap_label

    assert lap_label(os.path.basename(laps[1])) == "Lap 2 · 1:10.000"
    assert lap_label("other file.csv") == "other file"
    legend = viewer.backend.legend
    assert legend[0]["full"].startswith("Lap 2 · 1:10.000 · Practice 03/10")
    assert legend[0]["label"] == "Lap 2 · 1:10.000"


# --- 2. Units
def test_values_in_user_units(viewer, monkeypatch):
    monkeypatch.setitem(cfg.units, "speed_unit", "MPH")
    monkeypatch.setitem(cfg.units, "temperature_unit", "Fahrenheit")
    monkeypatch.setitem(cfg.units, "tyre_pressure_unit", "psi")
    backend = viewer.backend
    backend.load_laps()
    data = backend.data
    from tinypedal.ui.lap_viewer import CHANNEL_MAP

    speed = CHANNEL_MAP["speed_kph"]
    assert data.unit_of(speed) == "mph" and data.unit_of(CHANNEL_MAP["tyre_temp_fl"]) == "°F"
    lap = data.laps[0]
    assert data.series(speed, lap)[1][0] == pytest.approx(250 / 1.609344)
    assert data.series(CHANNEL_MAP["tyre_temp_fl"], lap)[1][0] == pytest.approx(80 * 1.8 + 32)
    assert data.series(CHANNEL_MAP["tyre_pres_fl"], lap)[1][0] == pytest.approx(170 * 0.145038, abs=0.01)
    assert next(panel for panel in backend.panels if panel["column"] == "speed_kph")["unit"] == "mph"
    corner = backend.corners[0]  # corner table in mph too
    reference, _ = (float(value) for value in corner["speed"].split(" / "))
    assert reference == pytest.approx(120 / 1.609344, abs=1)


# --- 3 & 6. Cursor values
def test_cursor_values_colored_and_in_charts(viewer):
    backend = viewer.backend
    values = backend.cursorValues(500.0)
    throttle = values[backend.visible.index("throttle")]
    assert len(throttle) == 2 and throttle[0]["text"].endswith("%")
    assert throttle[0]["color"] == backend.data.laps[0].color.name()
    from tinypedal.ui.lap_viewer import CHANNEL_MAP, format_channel_value

    assert format_channel_value(CHANNEL_MAP["delta"], 0.1234) == "+0.123"


# --- 4. Added laps grouped by folder
def test_added_laps_grouped_by_folder(viewer, tmp_path):
    first = save(1, 80.0, BASE, folder=str(tmp_path / "log A"))
    second = save(1, 81.0, BASE, folder=str(tmp_path / "log B"))
    viewer.add_external([first, second])
    rows = viewer.backend.lap_model.rows
    added = [row for row in rows if row["kind"] == "session" and "added" in row["info"]]
    assert [row["title"] for row in added] == [TRACK, TRACK]  # one group per folder (track folder of each log)
    paths = {row["path"] for row in rows if row["kind"] == "lap" and row["session"] in {r["session"] for r in added}}
    assert paths == {os.path.normpath(first), os.path.normpath(second)}


# --- 5. Axes
def test_axis_steps_and_labels():
    from tinypedal.ui.lap_viewer import CHANNEL_MAP, format_axis_time, format_axis_value, nice_step

    assert nice_step(2000, 8) == 500 and nice_step(70, 6) == 20 and nice_step(0.9, 3) == pytest.approx(0.5)
    assert format_axis_time(45) == "45s" and format_axis_time(65) == "1:05"
    assert format_axis_value(CHANNEL_MAP["brake"], 1.0, 1.0) == "100%"
    assert format_axis_value(CHANNEL_MAP["speed_kph"], 251.4, 140) == "251"


# --- 7 & 13. Corners on charts & map, driving analysis
def test_corners_marked_and_driving_analysis(viewer):
    backend = viewer.backend
    marks = backend.cornerMarks
    assert len(marks) == 2 and [mark["label"] for mark in backend.trackMap["corners"]] == ["T1", "T2"]
    assert backend.trackMap["corners"][0]["delta"].startswith("+")  # compared lap slower
    rows = backend.corners
    assert rows[0]["label"] == "T1" and " / " in rows[0]["coast"] and rows[0]["overlap"].endswith(" s")
    assert [row["kind"] for row in rows[-3:]] == ["sum", "total", "ideal"]
    start, end = backend.cornerRange(0)
    assert start < marks[0]["x"] < end


def test_driving_times_counted():
    from tinypedal.userfile.corner_analysis import driving_times
    from tinypedal.userfile.telemetry_lap import LapData

    distance = [float(index) for index in range(0, 101, 10)]
    lap = LapData("x", {"distance": distance, "lap_time": [d / 10 for d in distance],
                        "steering": [0.3] * 11})
    brake = [1.0] * 5 + [0.0] * 6
    throttle = [0.0] * 5 + [0.0, 0.0, 0.5, 0.5, 0.5, 0.5]
    trail, coast, overlap = driving_times(lap, distance, brake, throttle)
    assert trail == pytest.approx(5.0) and coast == pytest.approx(2.0) and overlap == 0.0
    assert driving_times(lap, distance, None, throttle) == (0.0, 0.0, 0.0)


# --- 8. Map click, cursor, braking points, color modes
def test_map_click_and_cursor(viewer):
    backend = viewer.backend
    line = backend._map_lines[0][0]
    index = len(line.distances) // 3
    position = backend.mapPick(line.xs[index], line.ys[index], 5.0)
    assert backend.distanceAt(position) == pytest.approx(line.distances[index], abs=1)
    points = backend.mapCursor(position)
    assert len(points) == 2 and points[0]["x"] == pytest.approx(line.xs[index], abs=1)
    braking = [point for point in backend.trackMap["points"] if point["kind"] == "brake"]  # 2 corners, 2 laps
    assert len(braking) == 4 and {point["color"] for point in braking} == {lap.color.name() for lap in backend.data.laps}
    bounds = backend.mapBounds(0.0, 500.0)  # first quarter: right & top of oval
    assert bounds[0] > 0 and bounds[3] > 150


def test_map_color_modes(viewer):
    from tinypedal.ui.quick.lines import VertexStore

    backend = viewer.backend
    colored = backend.trackMap["colored"]
    assert VertexStore.get(colored).vertex_count == 0  # lap colors: no colored line
    for mode in ("gain", "speed", "pedals"):
        backend.setMapMode(mode)
        vertices = VertexStore.get(colored)
        assert vertices.colored and vertices.vertex_count > 10, mode
    assert backend.mapLegend == {}  # pedals: fixed colors
    backend.setMapMode("speed")
    legend = backend.mapLegend
    assert legend["low"] == "120" and legend["high"] == "250" and legend["unit"] == "km/h"
    backend.setMapView(500.0, 1000.0, 2.0)  # zoomed part & thick lines rebuilt for scale
    assert VertexStore.get(backend.trackMap["lines"][0]["highlight"]).vertex_count > 0
    backend.setMapFollow(False)
    backend.setMapBraking(False)
    assert not backend.mapFollow and not backend.mapBraking


# --- 10. Fastest lap star & hidden laps
def test_star_and_hidden_laps(viewer, laps):
    backend = viewer.backend
    assert rows_by_path(backend)[laps[1]]["fastest"]
    check_only(viewer, [laps[1]])
    backend.setHideUnclean(True)
    shown = set(rows_by_path(backend))
    assert laps[0] not in shown and laps[3] not in shown and laps[2] in shown  # out & invalid hidden
    backend.setHideUnclean(False)
    assert len(backend.lap_rows()) == 4


# --- 11 & 19. Keep, note, delete
def test_keep_note_and_delete(viewer, laps, monkeypatch):
    from tinypedal.ui import _common
    from tinypedal.userfile.lap_marks import kept_laps, load_marks

    backend = viewer.backend
    folder = os.path.dirname(laps[0])
    assert backend.lapActions(laps[0]) == {"recorded": True, "kept": False}
    backend.keepLap(laps[0], True)
    assert kept_laps(folder) == {os.path.basename(laps[0])}
    assert backend.lapActions(laps[0])["kept"]
    inputs = []
    monkeypatch.setattr(_common.TextInputDialog, "show", lambda self: inputs.append(self))
    backend.editNote(laps[0])
    assert inputs[0]._on_accept("cold tyres")
    row = rows_by_path(backend)[laps[0]]
    assert "kept" in row["info"] and row["note"] == "cold tyres"
    module_recorder.remove_old_laps(folder, 1, keep_best=0)  # recorder cleanup over limit
    assert os.path.exists(laps[0])  # kept lap never removed
    backend.refresh()
    backend.deleteLap(laps[0])  # lap read by background loading: moved to trash once loaded
    wait_loaded(viewer)
    assert not os.path.exists(laps[0]) and laps[0] not in rows_by_path(backend)
    assert os.path.basename(laps[0]) not in load_marks(folder)
    assert backend.undoText  # moved to trash, can be restored
    backend.undoDelete()
    wait_loaded(viewer)
    assert os.path.exists(laps[0]) and laps[0] in rows_by_path(backend)
    assert os.path.basename(laps[0]) in kept_laps(folder) and not backend.undoText  # marks restored


def test_added_lap_actions(viewer, tmp_path):
    other = save(1, 80.0, BASE, folder=str(tmp_path / "log"))
    viewer.add_external([other])
    assert viewer.backend.lapActions(os.path.normpath(other)) == {"recorded": False, "kept": False}


# --- 12. Selection remembered
def test_selection_remembered(viewer, laps):
    from tinypedal.ui.lap_viewer import LapViewer

    check_only(viewer, [laps[2], laps[3]])
    viewer.backend.setReference(laps[3])
    viewer.close()
    flush_deleted()
    other = LapViewer(None)
    try:
        wait_loaded(other)
        assert set(other.backend.ordered_checked()) == {laps[2], laps[3]}
        assert other.backend.reference_key == laps[3]
    finally:
        other.close()
        flush_deleted()


# --- 14. Time gain / loss chart
def test_delta_rate_channel(viewer):
    from tinypedal.ui.lap_viewer import CHANNEL_MAP
    from tinypedal.userfile.telemetry_lap import delta_rate

    assert delta_rate([0, 100, 200], [0.0, 0.5, 1.0], window=100) == pytest.approx([0.25, 0.5, 0.25])
    backend = viewer.backend
    backend.setChannelVisible("delta_rate", True)
    data = backend.data
    xs, ys = data.series(CHANNEL_MAP["delta_rate"], data.compared()[0])
    assert xs and sum(ys) / len(ys) > 0  # compared lap slower: losing time on average
    low, high = data.value_range(CHANNEL_MAP["delta_rate"])
    assert low == -high


# --- 15. Time axis
def test_time_axis(viewer):
    backend = viewer.backend
    restored = []
    backend.viewRestored.connect(lambda start, end: restored.append((start, end)))
    backend.setChartView(500.0, 1000.0)  # zoomed on distance axis
    backend.setTimeAxis(True)
    data = backend.data
    assert backend.timeAxis and backend.maxX == pytest.approx(72.0, abs=0.5)  # slowest lap time
    assert data.distance_at_x(data.x_at_distance(800.0)) == pytest.approx(800.0, abs=1)
    start, end = restored[-1]  # same part of lap kept in view
    assert data.distance_at_x(start) == pytest.approx(500, abs=2) and data.distance_at_x(end) == pytest.approx(1000, abs=2)
    assert backend.cursorTitle(30.0).startswith("30s")
    backend.setChartView(*restored[-1])
    backend.setTimeAxis(False)
    assert not backend.timeAxis and restored[-1][0] == pytest.approx(500, abs=2)


# --- 16 & 17. Background loading, refresh of changed laps only
def test_background_loading_and_refresh(viewer, laps):
    backend = viewer.backend
    backend._lap_cache.clear()
    backend.checked.update(row["path"] for row in backend.lap_rows())
    backend.load_laps()
    assert viewer.is_loading() and backend.loading  # 4 laps read in background
    wait_loaded(viewer)
    assert len(backend.data.laps) == 4
    kept = backend._lap_cache[laps[1]]
    os.utime(laps[2], (time.time() + 5, time.time() + 5))  # file changed
    backend.refresh()
    wait_loaded(viewer)
    assert backend._lap_cache[laps[1]] is kept  # unchanged lap not read again
    assert backend._lap_cache.get(laps[2]) is not None


# --- 18. Exports
def test_csv_export(viewer, tmp_path):
    backend = viewer.backend
    target = tmp_path / "laps.csv"
    assert backend.write_csv(str(target), decimal_point=",")
    lines = target.read_text(encoding="utf-8-sig").splitlines()
    header = lines[0].split(";")
    assert header[0] == "Distance (m)" and any("Speed (km/h)" in name for name in header)
    assert len(header) == 1 + len(backend.data.laps) * len(backend.visible)
    assert len(lines) == int(LENGTH) + 2 and "," in lines[100]
    assert backend.write_csv(str(tmp_path / "dot.csv"), decimal_point=".")
    assert (tmp_path / "dot.csv").read_text(encoding="utf-8-sig").splitlines()[0].count(",") == len(header) - 1


def test_motec_export(viewer, laps, tmp_path, monkeypatch):
    from tinypedal.ui.quick import lap_backend
    from tinypedal.userfile.motec_ld import read_ld

    backend = viewer.backend
    target = tmp_path / "reference.ld"
    monkeypatch.setattr(lap_backend.QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(target), ""))
    backend.exportMotec("")  # reference lap
    assert target.exists() and read_ld(str(target))
    assert "Exported" in backend.status
    monkeypatch.setattr(lap_backend.QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(tmp_path / "all"))
    os.makedirs(tmp_path / "all")
    backend.exportMotecMany(True)  # every lap of track, in background
    wait_loaded(viewer)
    assert len(os.listdir(tmp_path / "all")) == len(laps)


def test_gear_drawn_as_steps(viewer):
    from tinypedal.ui.quick.lines import VertexStore

    backend = viewer.backend
    backend.setChannelVisible("gear", True)
    gear = next(panel for panel in backend.panels if panel["column"] == "gear")
    speed = next(panel for panel in backend.panels if panel["column"] == "speed_kph")
    # Steps: 2 vertices per sample
    assert VertexStore.get(gear["series"][0]["key"]).vertex_count == 2 * VertexStore.get(
        speed["series"][0]["key"]).vertex_count
