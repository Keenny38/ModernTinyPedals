"""Lap viewer: units, names, cursor values, axes, corners, map click, lap marks, selection, time axis, CSV..."""

import math
import os
import time

import pytest
from PySide6.QtCore import Qt
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
    for item in viewer.lap_items():
        item.setCheckState(0, Qt.CheckState.Checked if item.data(0, Qt.ItemDataRole.UserRole) in paths
                           else Qt.CheckState.Unchecked)
    wait_loaded(viewer)


# --- 1. Lap names
def test_lap_names(viewer, laps):
    from tinypedal.ui.lap_viewer import lap_label

    assert lap_label(os.path.basename(laps[1])) == "Lap 2 · 1:10.000"
    assert lap_label("other file.csv") == "other file"
    legend = [lap.label for lap in viewer.plot.laps]
    assert legend[0].startswith("Lap 2 · 1:10.000 · Practice 03/10")


# --- 2. Units
def test_values_in_user_units(viewer, monkeypatch):
    monkeypatch.setitem(cfg.units, "speed_unit", "MPH")
    monkeypatch.setitem(cfg.units, "temperature_unit", "Fahrenheit")
    monkeypatch.setitem(cfg.units, "tyre_pressure_unit", "psi")
    viewer.load_laps()
    plot = viewer.plot
    from tinypedal.ui.lap_viewer import CHANNEL_MAP

    speed = CHANNEL_MAP["speed_kph"]
    assert plot.unit_of(speed) == "mph" and plot.unit_of(CHANNEL_MAP["tyre_temp_fl"]) == "°F"
    lap = plot.laps[0]
    assert plot.series(speed, lap)[1][0] == pytest.approx(250 / 1.609344)
    assert plot.series(CHANNEL_MAP["tyre_temp_fl"], lap)[1][0] == pytest.approx(80 * 1.8 + 32)
    assert plot.series(CHANNEL_MAP["tyre_pres_fl"], lap)[1][0] == pytest.approx(170 * 0.145038, abs=0.01)
    viewer.corners.set_laps(plot.lap_a, plot.lap_b)  # corner table in mph too
    assert viewer.corners.speed_unit == "mph" and viewer.corners.speed(160.9344) == pytest.approx(100)


# --- 3 & 6. Cursor values
def test_cursor_values_colored_and_in_charts(viewer):
    plot = viewer.plot
    plot.resize(900, 600)
    plot.cursor_distance = 500.0
    text = plot.cursor_values()
    assert " m " in text and "<span style='color:" in text and plot.laps[0].color.name() in text
    from tinypedal.ui.lap_viewer import CHANNEL_MAP, format_channel_value

    values = plot.values_at(CHANNEL_MAP["throttle"], 500.0)
    assert len(values) == 2 and values[0][1].endswith("%")
    assert format_channel_value(CHANNEL_MAP["delta"], 0.1234) == "+0.123"
    assert not plot.grab().isNull()  # cursor values drawn next to cursor


# --- 4. Added laps grouped by folder
def test_added_laps_grouped_by_folder(viewer, tmp_path):
    first = save(1, 80.0, BASE, folder=str(tmp_path / "log A"))
    second = save(1, 81.0, BASE, folder=str(tmp_path / "log B"))
    viewer.add_external([first, second])
    added = [item for item in viewer.session_items() if "added" in item.text(5)]
    assert [item.text(0) for item in added] == [TRACK, TRACK]  # one group per folder (track folder of each log)
    assert {item.child(0).data(0, Qt.ItemDataRole.UserRole) for item in added} == {os.path.normpath(first), os.path.normpath(second)}


# --- 5. Axes
def test_axis_steps_and_labels(viewer):
    from tinypedal.ui.lap_viewer import CHANNEL_MAP, format_axis_time, format_axis_value, nice_step

    assert nice_step(2000, 8) == 500 and nice_step(70, 6) == 20 and nice_step(0.9, 3) == pytest.approx(0.5)
    assert format_axis_time(45) == "45s" and format_axis_time(65) == "1:05"
    assert format_axis_value(CHANNEL_MAP["brake"], 1.0, 1.0) == "100%"
    assert format_axis_value(CHANNEL_MAP["speed_kph"], 251.4, 140) == "251"
    viewer.plot.resize(900, 600)
    assert not viewer.plot.grab().isNull()


# --- 7 & 13. Corners on charts & map, driving analysis
def test_corners_marked_and_driving_analysis(viewer):
    marks = viewer.plot.corner_marks
    assert len(marks) == 2 and marks == viewer.trajectory.corner_marks
    rows = viewer.corners.rows
    assert rows[0].reference.trail_braking >= 0 and rows[0].compared is not None
    item = viewer.corners.table.topLevelItem(0)
    assert item.text(0).startswith("T1") and " / " in item.text(5) and item.text(7).endswith(" s")
    viewer.trajectory.resize(400, 400)
    assert not viewer.trajectory.grab().isNull()


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


# --- 8. Map click
def test_map_click_moves_cursor(viewer):
    trajectory = viewer.trajectory
    trajectory.resize(400, 400)
    distances, xs, ys, _ = trajectory._lines[0]
    index = len(distances) // 3
    trajectory.map_clicked(trajectory.to_screen(xs[index], ys[index]))
    assert viewer.plot.cursor_track_distance() == pytest.approx(distances[index], abs=1)
    assert viewer.trajectory.cursor_distance == pytest.approx(distances[index], abs=1)


# --- 10. Fastest lap star & hidden laps
def test_star_and_hidden_laps(viewer, laps):
    labels = {item.data(0, Qt.ItemDataRole.UserRole): item.text(0) for item in viewer.lap_items()}
    assert labels[laps[1]].startswith("★")
    check_only(viewer, [laps[1]])
    viewer.check_clean.setChecked(True)
    shown = {item.data(0, Qt.ItemDataRole.UserRole) for item in viewer.lap_items()}
    assert laps[0] not in shown and laps[3] not in shown and laps[2] in shown  # out & invalid hidden
    viewer.check_clean.setChecked(False)
    assert len(viewer.lap_items()) == 4


# --- 11 & 19. Keep, note, delete
def test_keep_note_and_delete(viewer, laps, monkeypatch):
    from tinypedal.ui import lap_viewer
    from tinypedal.userfile.lap_marks import kept_laps, load_marks

    folder = os.path.dirname(laps[0])
    viewer.keep_lap(laps[0], True)
    assert kept_laps(folder) == {os.path.basename(laps[0])}
    inputs = []
    monkeypatch.setattr(lap_viewer.TextInputDialog, "show", lambda self: inputs.append(self))
    viewer.edit_note(laps[0])
    assert inputs[0]._on_accept("cold tyres")
    info = {item.data(0, Qt.ItemDataRole.UserRole): item.text(5) for item in viewer.lap_items()}
    assert "kept" in info[laps[0]] and "cold tyres" in info[laps[0]]
    module_recorder.remove_old_laps(folder, 1, keep_best=0)  # recorder cleanup over limit
    assert os.path.exists(laps[0])  # kept lap never removed
    viewer.refresh_tracks()
    remaining = [item.data(0, Qt.ItemDataRole.UserRole) for item in viewer.lap_items()]
    viewer.delete_lap(laps[0])
    assert not os.path.exists(laps[0]) and laps[0] not in [
        item.data(0, Qt.ItemDataRole.UserRole) for item in viewer.lap_items()]
    assert os.path.basename(laps[0]) not in load_marks(folder)
    assert len(remaining) >= 1


# --- 12. Selection remembered
def test_selection_remembered(viewer, laps):
    from tinypedal.ui.lap_viewer import LapViewer

    check_only(viewer, [laps[2], laps[3]])
    viewer.set_reference_item(next(item for item in viewer.lap_items()
                                   if item.data(0, Qt.ItemDataRole.UserRole) == laps[3]))
    viewer.close()
    flush_deleted()
    other = LapViewer(None)
    try:
        wait_loaded(other)
        assert set(other.checked_paths()) == {laps[2], laps[3]} and other.reference_key == laps[3]
    finally:
        other.close()
        flush_deleted()


# --- 14. Time gain / loss chart
def test_delta_rate_channel(viewer):
    from tinypedal.ui.lap_viewer import CHANNEL_MAP
    from tinypedal.userfile.telemetry_lap import delta_rate

    assert delta_rate([0, 100, 200], [0.0, 0.5, 1.0], window=100) == pytest.approx([0.25, 0.5, 0.25])
    viewer.toggle_channel("delta_rate", True)
    plot = viewer.plot
    xs, ys = plot.series(CHANNEL_MAP["delta_rate"], plot.compared()[0])
    assert xs and sum(ys) / len(ys) > 0  # compared lap slower: losing time on average
    low, high = plot.value_range(CHANNEL_MAP["delta_rate"])
    assert low == -high


# --- 15. Time axis
def test_time_axis(viewer):
    plot = viewer.plot
    viewer.check_time_axis.setChecked(True)
    assert plot.time_axis and plot.max_distance() == pytest.approx(72.0, abs=0.5)  # slowest lap time
    assert plot.distance_at_x(plot.x_at_distance(800.0)) == pytest.approx(800.0, abs=1)
    plot.set_view_distance(500, 1000)
    start, end = plot.view_track_range()
    assert start == pytest.approx(500, abs=2) and end == pytest.approx(1000, abs=2)
    plot.cursor_distance = 30.0
    assert "0:30" not in plot.cursor_values() and "30s" in plot.cursor_values()
    plot.resize(900, 600)
    assert not plot.grab().isNull()
    viewer.check_time_axis.setChecked(False)
    assert not plot.time_axis and plot.view_track_range()[0] == pytest.approx(500, abs=2)


# --- 16 & 17. Background loading, refresh of changed laps only
def test_background_loading_and_refresh(viewer, laps):
    viewer._lap_cache.clear()
    viewer.lap_list.blockSignals(True)
    for item in viewer.lap_items():
        item.setCheckState(0, Qt.CheckState.Checked)
    viewer.lap_list.blockSignals(False)
    viewer.load_laps()
    assert viewer.is_loading()  # 4 laps read in background
    wait_loaded(viewer)
    assert len(viewer.plot.laps) == 4
    kept = viewer._lap_cache[laps[1]]
    os.utime(laps[2], (time.time() + 5, time.time() + 5))  # file changed
    viewer.refresh_tracks()
    wait_loaded(viewer)
    assert viewer._lap_cache[laps[1]] is kept  # unchanged lap not read again
    assert viewer._lap_cache.get(laps[2]) is not None


# --- 18. CSV export
def test_csv_export(viewer, tmp_path):
    target = tmp_path / "laps.csv"
    assert viewer.write_csv(str(target), decimal_point=",")
    lines = target.read_text(encoding="utf-8-sig").splitlines()
    header = lines[0].split(";")
    assert header[0] == "Distance (m)" and any("Speed (km/h)" in name for name in header)
    assert len(header) == 1 + len(viewer.plot.laps) * len(viewer.plot.channels)
    assert len(lines) == int(LENGTH) + 2 and "," in lines[100]
    assert viewer.write_csv(str(tmp_path / "dot.csv"), decimal_point=".")
    assert (tmp_path / "dot.csv").read_text(encoding="utf-8-sig").splitlines()[0].count(",") == len(header) - 1


def test_gear_drawn_as_steps(viewer):
    viewer.toggle_channel("gear", True)
    viewer.plot.resize(900, 600)
    assert not viewer.plot.grab().isNull()
    viewer.plot.show_distance(10.0)
    assert viewer.plot.cursor_distance == pytest.approx(10.0)
