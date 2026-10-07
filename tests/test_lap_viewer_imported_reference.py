"""Lap viewer: imported reference lap (library, MoTeC import) whose distance zero is away from the line aligned first on
a lap recorded by the app (recorded laps never shifted), delta best of an imported lap aligned & scaled to track
length, imported logs with missing positions (NaN) never break loading, live mode after laps of another circuit were
opened, shape checks keep no lap data, slow comparisons of imported laps done in background"""

import math
import os
import threading

import pytest

from tests.test_lap_viewer import wait_loaded
from tests.test_lap_viewer_circuit_shape import COMBO, OTHER, listed_path, make_lap, write_lap
from tinypedal.setting import cfg
from tinypedal.userfile.telemetry_lap import LapData, interpolate


@pytest.fixture
def track(ui_env):
    """Viewer of a track with 2 laps recorded by the app (shown)"""
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.quick.lap_backend import LapViewerBackend

    folder = os.path.join(cfg.path.telemetry.rstrip("/"), COMBO)
    paths = [write_lap(folder, make_lap(number, recorded=True, pace=1 + number / 100)) for number in (1, 2)]
    parent = QWidget()
    backend = LapViewerBackend(parent, cfg.path.telemetry)
    backend.refresh()
    wait_loaded(backend)
    yield backend, [listed_path(backend, path) for path in paths]
    backend.release()
    parent.deleteLater()


def plot_lap(key, data):
    from PySide6.QtGui import QColor

    from tinypedal.ui.lap_viewer import PlotLap

    return PlotLap(key, key, data, QColor("red"))


def corner_distance(data, lap) -> float:
    """Chart distance of lowest speed of lap (slowest corner, same place on every aligned lap)"""
    from tinypedal.ui.lap_viewer import CHANNEL_MAP

    xs, ys = data.series(CHANNEL_MAP["speed_kph"], lap)
    return min((y, x) for x, y in zip(xs, ys) if 100.0 < x < max(xs) - 100.0)[1]


# A) Imported reference lap aligned on a lap recorded by the app
def test_imported_reference_aligned_on_recorded_lap(ui_env):
    from tinypedal.ui.quick.trace_data import TraceData

    recorded = make_lap(1, recorded=True)
    reference = make_lap(2, shift=150.0, pace=0.99)
    other = make_lap(3, shift=-60.0, pace=1.01)
    data = TraceData()
    data.set_laps([plot_lap("ref", reference), plot_lap("rec", recorded), plot_lap("imp", other)], "ref")
    assert data.anchor_key == "rec"
    assert data.auto_offsets["ref"] == pytest.approx(150.0, abs=1.0)  # before: reference never moved
    assert data.auto_offsets["imp"] == pytest.approx(-60.0, abs=1.0)
    assert "rec" not in data.auto_offsets and data.laps[1].data is recorded
    corner = corner_distance(data, data.laps[1])
    for lap in (data.laps[0], data.laps[2]):
        assert corner_distance(data, lap) == pytest.approx(corner, abs=3.0)
    # No recorded lap shown: main lap of track given as anchor
    data = TraceData()
    data.set_laps([plot_lap("ref", reference), plot_lap("imp", other)], "ref", ("main", recorded))
    assert data.anchor_key == "main"
    assert data.auto_offsets["ref"] == pytest.approx(150.0, abs=1.0)
    assert data.auto_offsets["imp"] == pytest.approx(-60.0, abs=1.0)


def test_library_reference_aligned_in_viewer(track, tmp_path):
    backend, paths = track
    imported = write_lap(str(tmp_path / "logs"), make_lap(7, shift=150.0, pace=0.99))
    backend.add_external([imported], [imported])  # library: fastest picked lap as reference
    wait_loaded(backend)
    assert backend.reference_key == imported
    assert backend.data.auto_offsets == {imported: pytest.approx(150.0, abs=1.0)}  # recorded laps never shifted
    shown = {lap.key: lap for lap in backend.data.laps}
    corner = corner_distance(backend.data, shown[paths[0]])
    assert corner_distance(backend.data, shown[imported]) == pytest.approx(corner, abs=3.0)
    # Only the imported lap shown: aligned on main lap of track (not shown)
    for path in paths:
        backend.setLapChecked(path, False)
    wait_loaded(backend)
    assert [lap.key for lap in backend.data.laps] == [imported]
    assert backend.data.anchor_key in paths
    assert backend.data.auto_offsets == {imported: pytest.approx(150.0, abs=1.0)}


def test_consistency_job_aligns_imported_reference(ui_env, tmp_path):
    from tinypedal.ui.quick.trace_data import TraceData
    from tinypedal.userfile.lap_geometry import mini_sector_job
    from tinypedal.userfile.telemetry_lap import load_lap

    folder = str(tmp_path / COMBO)
    reference_path = write_lap(folder, make_lap(1, shift=120.0, positions=False))
    recorded_path = write_lap(folder, make_lap(2, recorded=True, positions=False))
    imported_path = write_lap(folder, make_lap(3, shift=-50.0, positions=False, pace=1.01))
    laps = [plot_lap(path, load_lap(path)) for path in (reference_path, recorded_path, imported_path)]
    data = TraceData()
    data.set_laps(laps, reference_path)
    assert data.anchor_key == recorded_path
    mini = data.mini_sectors()
    reference = data.reference
    found = mini_sector_job(str(tmp_path), [recorded_path, imported_path], list(mini["bounds"]),
                            data.lap_end(reference), dict(reference.data.meta), reference_path, data.anchor_key)
    for path, times in zip((recorded_path, imported_path), mini["times"][1:]):  # same times as shown laps
        assert found[path] == pytest.approx(times, abs=0.01)


# B) Delta best of an imported lap
@pytest.mark.parametrize("shown", [True, False])
def test_delta_best_of_imported_lap_aligned_and_scaled(track, tmp_path, monkeypatch, shown):
    from PySide6.QtWidgets import QMessageBox

    backend, _ = track
    imported = write_lap(str(tmp_path / "logs"), make_lap(7, shift=150.0, scale=1.04))
    backend.add_external([imported])
    wait_loaded(backend)
    if not shown:
        backend.setLapChecked(imported, False)
        wait_loaded(backend)
        assert imported not in [lap.key for lap in backend.data.laps]
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    backend.exportDeltaBest(imported)
    target = backend.delta_best_file(backend.delta_best_track(imported))
    with open(target, encoding="utf-8") as file:
        rows = [tuple(map(float, line.split(","))) for line in file.read().split() if line[0].isdigit()]
    same = make_lap(7, recorded=True)  # same lap recorded by the app: game track distance from the line
    for distance in (300.0, 1000.0, 1800.0, 2600.0):
        expected = interpolate(list(same.distance), list(same.columns["lap_time"]), distance)
        assert interpolate([row[0] for row in rows], [row[1] for row in rows], distance) == pytest.approx(
            expected, abs=0.05)


# C) World positions missing in an imported log
def gap_lap(lap: LapData, value: float, start: int = 500, count: int = 40) -> LapData:
    columns = {name: list(values) for name, values in lap.columns.items()}
    for index in range(start, start + count):
        columns["pos_x"][index] = value
    return LapData(lap.name, columns, lap.info)


@pytest.mark.parametrize("value", [math.nan, math.inf])
def test_positions_gap_ignored(value):
    from tinypedal.userfile.circuit_match import same_imported_circuit
    from tinypedal.userfile.lap_offset import aligned_on, has_positions

    reference = make_lap(1, recorded=True)
    imported = gap_lap(make_lap(2, shift=120.0), value)
    assert has_positions(imported)
    assert same_imported_circuit(reference, imported) is True
    assert aligned_on(reference, imported)[1] == pytest.approx(120.0, abs=1.0)
    mostly_missing = gap_lap(make_lap(3, shift=120.0), value, 0, len(imported) // 2)
    assert not has_positions(mostly_missing)  # speed trace used instead
    assert aligned_on(reference, mostly_missing)[1] == pytest.approx(120.0, abs=2.0)


def test_lap_with_nan_positions_shown(track, tmp_path):
    backend, paths = track
    imported = write_lap(str(tmp_path / "logs"), gap_lap(make_lap(7, shift=50.0), math.nan))
    backend.add_external([imported])
    wait_loaded(backend)
    assert imported in [lap.key for lap in backend.data.laps]
    backend.setLapChecked(paths[1], False)  # later loads fine too
    wait_loaded(backend)
    assert imported in [lap.key for lap in backend.data.laps]


def test_comparison_failure_keeps_lap(track, tmp_path, monkeypatch, caplog):
    import tinypedal.ui.quick.lap_backend as lap_backend
    import tinypedal.userfile.lap_offset as lap_offset

    def broken(*args, **kwargs):
        raise ValueError("cannot convert float NaN to integer")

    monkeypatch.setattr(lap_backend, "same_imported_circuit", broken)
    monkeypatch.setattr(lap_offset, "aligned_lap", broken)
    backend, _ = track
    imported = write_lap(str(tmp_path / "logs"), make_lap(7, shift=50.0))
    backend.add_external([imported])
    wait_loaded(backend)
    shown = {lap.key: lap for lap in backend.data.laps}
    assert imported in shown and backend.data.auto_offsets == {}
    assert "unable to align" in caplog.text and "unable to compare circuit" in caplog.text


# D) Live mode after laps of another circuit were opened
def test_live_new_lap_after_other_circuit_opened(track, tmp_path):
    backend, paths = track
    other = write_lap(str(tmp_path / "logs"), make_lap(5, OTHER, turn=0.8))
    backend.add_external([other], [other])  # viewer switches to that circuit
    wait_loaded(backend)
    assert [lap.key for lap in backend.data.laps] == [other] and backend.currentTrack == ""
    backend._live = True
    new = write_lap(os.path.dirname(paths[0]), make_lap(9, recorded=True, pace=1.05))
    backend._new_lap_tracks = {COMBO}
    backend.auto_refresh()
    wait_loaded(backend)
    assert backend.currentTrack == COMBO
    new = listed_path(backend, new)
    assert sorted(lap.key for lap in backend.data.laps) == sorted([paths[0], new])  # compared with best lap
    assert backend.reference_key == paths[0]
    assert "New lap" in backend.status and "another circuit" not in backend.status


# E) Shape checks keep no lap data
def test_shape_checks_keep_no_lap_data(track, tmp_path):
    backend, _ = track
    for number in range(1, 4):
        imported = write_lap(str(tmp_path / "logs"), make_lap(10 + number, shift=30.0 * number))
        backend.add_external([imported])
        wait_loaded(backend)
        backend.setLapChecked(imported, False)
        wait_loaded(backend)
    assert backend._shape_checks
    for value in backend._shape_checks.values():
        assert not any(isinstance(item, LapData) for item in value)
    backend._window.isVisible = lambda: False
    backend.release_laps()
    assert backend._shape_checks == {}


# F) Slow comparisons of imported laps in background
def test_imported_laps_compared_in_background(track, tmp_path, monkeypatch):
    import tinypedal.ui.quick.lap_backend as lap_backend
    import tinypedal.ui.quick.trace_data as trace_data
    from tinypedal.ui import lap_viewer

    backend, _ = track
    imported = [write_lap(str(tmp_path / "logs"), make_lap(7 + number, shift=40.0 * (number + 1)))
                for number in range(2)]
    backend.add_external(imported)
    wait_loaded(backend)
    assert len(backend.data.laps) == 4
    monkeypatch.setattr(lap_viewer, "BACKGROUND_PREPARE_SAMPLES", 1, raising=False)  # any imported lap
    threads = []
    original_check, original_align = lap_backend.same_imported_circuit, trace_data.aligned_on

    def check(*args):
        threads.append(threading.current_thread())
        return original_check(*args)

    def align(*args):
        threads.append(threading.current_thread())
        return original_align(*args)

    monkeypatch.setattr(lap_backend, "same_imported_circuit", check)
    monkeypatch.setattr(trace_data, "aligned_on", align)
    backend.setReference(imported[0])  # laps cached: only alignments measured again
    wait_loaded(backend)
    assert backend.reference_key == imported[0]
    assert threads and threading.main_thread() not in threads
    assert backend.data.auto_offsets[imported[1]] == pytest.approx(80.0, abs=1.0)  # on reference aligned first
    backend._window.isVisible = lambda: False
    backend.release_laps()  # laps & checks released: read & compared again in background
    threads.clear()
    backend.page_shown()
    wait_loaded(backend)
    assert len(backend.data.laps) == 4
    assert threads and threading.main_thread() not in threads
