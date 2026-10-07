"""Lap viewer audit 3: comparisons measured in background for one selection never taken for another one picked
while laps were loading (GUI thread never measures them), positions on the map plane (pos_x & pos_y), map line without
non finite positions"""

import threading

import pytest

from tests.test_lap_viewer import wait_loaded
from tests.test_lap_viewer_circuit_shape import make_lap, write_lap
from tests.test_lap_viewer_imported_reference import track  # noqa: F401


def test_selection_changed_while_preparing_compared_in_background(track, tmp_path, monkeypatch):  # noqa: F811
    """Reference changed while imported laps are compared in background: new selection compared in background
    too (before: comparisons of former selection taken as done, new ones measured on GUI thread)"""
    import tinypedal.ui.quick.trace_data as trace_data
    from tinypedal.ui import lap_viewer

    backend, _ = track
    imported = [write_lap(str(tmp_path / "logs"), make_lap(7 + number, shift=40.0 * (number + 1)))
                for number in range(2)]
    backend.add_external(imported)
    wait_loaded(backend)
    assert len(backend.data.laps) == 4
    monkeypatch.setattr(lap_viewer, "BACKGROUND_PREPARE_SAMPLES", 1, raising=False)  # any imported lap
    release = threading.Event()
    threads = []
    original_align = trace_data.aligned_on

    def align(*args):
        threads.append(threading.current_thread())
        if threading.current_thread() is not threading.main_thread():
            release.wait(10)  # first comparison still running while another reference is picked
        return original_align(*args)

    monkeypatch.setattr(trace_data, "aligned_on", align)
    backend.setReference(imported[0])
    assert backend._loader is not None
    backend.setReference(imported[1])  # picked while former selection is compared
    release.set()
    wait_loaded(backend)
    assert backend.reference_key == imported[1]
    assert threads and threading.main_thread() not in threads
    assert len(backend.data.laps) == 4
    assert backend.data.auto_offsets[imported[0]] == pytest.approx(40.0, abs=1.0)  # on new reference (aligned first)


# Map plane of recorded laps: pos_x & pos_y (pos_z is elevation, see module_recorder & lap map elevation mode)
def recorded_plane(lap, start: float = 0.0, track_length: float = 3000.0, hills: float = 1.0):
    """Lap with positions as recorded by the app: plane in pos_x & pos_y, elevation in pos_z (hills: height factor,
    0: flat circuit, start: track distance at lap distance zero)"""
    import math

    from tinypedal.userfile.telemetry_lap import LapData

    columns = dict(lap.columns)  # map plane in pos_x & pos_y already (see telemetry_sim.circuit_lap)
    columns["pos_z"] = [12.0 + hills * (20.0 * math.sin(math.tau * (distance + start) / track_length)
                                + 6.0 * math.sin(3 * math.tau * (distance + start) / track_length))
                        for distance in lap.distance]
    return LapData(lap.name, columns, lap.info)


def test_imported_offset_from_map_plane_positions():
    """Imported lap whose distance zero is 150 m away from the line, flat circuit: offset found from positions on
    the map plane (before: elevation taken as a map axis, no offset found without speed trace)"""
    from tinypedal.userfile.lap_offset import lap_offset

    reference = make_lap(1, recorded=True)
    imported = make_lap(2, shift=150.0, pace=1.01)
    reference, imported = recorded_plane(reference, hills=0.0), recorded_plane(imported, 150.0, hills=0.0)
    for lap in (reference, imported):  # positions alone tell the offset
        del lap.columns["speed_kph"]
    assert lap_offset(reference, imported) == pytest.approx(150.0, abs=2.0)


def test_same_circuit_shape_on_map_plane():
    """Lap of the same circuit with logger coordinates turned & moved on the map plane: same circuit (before:
    elevation taken as a map axis, refused as another circuit); lap of another circuit still refused"""
    from tests.test_lap_viewer_circuit_shape import OTHER
    from tinypedal.userfile.circuit_match import same_shape

    reference = recorded_plane(make_lap(1, recorded=True))
    same = recorded_plane(make_lap(2, turn=1.3, shift=0.0))
    other = recorded_plane(make_lap(3, OTHER, turn=1.3))
    assert same_shape(reference, same) is True
    assert same_shape(reference, other) is False


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_map_line_without_non_finite_positions(value):
    """Imported log with a gap in its positions (NaN, inf): map line leaves the gap out (before: map grid of the
    lap raised ValueError, laps never shown)"""
    import math

    from tinypedal.ui.quick.lap_map import LineGrid
    from tinypedal.userfile.lap_geometry import map_line

    lap = make_lap(2, shift=50.0)
    for index in range(500, 540):
        lap.columns["pos_x"][index] = value
    line = map_line(lap)
    assert line is not None and len(line.xs) == len(lap) - 40
    assert all(math.isfinite(x) and math.isfinite(y) for x, y in zip(line.xs, line.ys))
    LineGrid(line)
