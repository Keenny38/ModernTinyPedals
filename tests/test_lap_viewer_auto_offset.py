"""Lap viewer: imported lap whose distance zero is not at the start line aligned on reference lap (constant distance
offset found from speed trace or world positions), laps recorded by the app never shifted; MoTeC import puts lap
distance zero at the line (lap number changing late)"""

import math

import pytest
from PySide6.QtGui import QColor

from tests.telemetry_sim import circuit_lap
from tinypedal.userfile.telemetry_lap import LapData, interpolate

LENGTH = 3000.0
RECORDED = {"combo": "Spa - GT3", "track": "Spa", "track_length": LENGTH}


def lap_name(number: int, lap_time: float) -> str:
    minutes, seconds = divmod(lap_time, 60)
    return f"2026-10-06 12-{number:02d}-00 lap{number:03d} {int(minutes)}m{seconds:06.3f}s"


def reference_lap() -> tuple[LapData, float]:
    columns, lap_time = circuit_lap(LENGTH)
    return LapData(lap_name(1, lap_time), columns, dict(RECORDED)), lap_time


def imported_lap(shift: float, pace: float = 1.02, positions: bool = False, number: int = 2,
                 info: dict | None = None) -> tuple[LapData, float]:
    """Lap whose distance zero is shift meters past the start line (MoTeC import), pace: lap time factor"""
    columns, lap_time = circuit_lap(LENGTH, shift, pace, positions=positions)
    meta = info if info is not None else {
        "source": "MoTeC", "imported_from": "spa.ld", "track": "Spa",
        "track_length": math.ceil(round(max(columns["distance"]) * 10, 6)) / 10}
    return LapData(lap_name(number, lap_time), columns, meta), lap_time


def plot_lap(key, data):
    from tinypedal.ui.lap_viewer import PlotLap

    return PlotLap(key, key, data, QColor("red"))


def slowest_point(data, lap, low: float = 1500.0, high: float = 2100.0) -> float:
    """Chart distance of lowest speed in corner around 1800 m"""
    from tinypedal.ui.lap_viewer import CHANNEL_MAP

    xs, ys = data.series(CHANNEL_MAP["speed_kph"], lap)
    return min((y, x) for x, y in zip(xs, ys) if low < x < high)[1]


@pytest.mark.parametrize(("shift", "positions"), [(37.0, False), (120.0, False), (-60.0, False), (37.0, True),
                                                  (120.0, True)])
def test_imported_lap_aligned_on_reference(ui_env, shift, positions):
    from tinypedal.ui.quick.trace_data import TraceData

    reference, reference_time = reference_lap()
    imported, imported_time = imported_lap(shift, positions=positions)
    first, second = plot_lap("ref", reference), plot_lap("imp", imported)
    data = TraceData()
    data.set_laps([first, second], "ref")
    assert data.auto_offsets["imp"] == pytest.approx(shift, abs=1.0)
    shown = data.laps[1]
    assert shown.data is not imported and shown.data.meta["distance_offset"] == pytest.approx(shift, abs=1.0)
    corner = slowest_point(data, data.reference)
    assert slowest_point(data, shown) == pytest.approx(corner, abs=2.0)  # braking & corner at the same place
    # Before alignment the corner was shift meters away
    raw = TraceData()
    raw.set_offsets({})
    raw.laps, raw.reference = [first, second], first
    assert slowest_point(raw, second) == pytest.approx(corner - shift, abs=2.0)
    # Delta: lap 2% slower everywhere, lap time gap at the line
    distances, deltas = data.deltas["imp"]
    assert deltas[-1] == pytest.approx(imported_time - reference_time, abs=0.01)
    ref_distances, ref_times = list(reference.distance), list(reference.columns["lap_time"])
    for target in (300.0, 1000.0, 1800.0, 2600.0):
        expected = 0.02 * interpolate(ref_distances, ref_times, target)
        assert interpolate(distances, deltas, target) == pytest.approx(expected, abs=0.02)
    assert data.lap_times(shown)[1][-1] == pytest.approx(imported_time, abs=0.002)  # official lap time kept


def test_recorded_lap_never_shifted(ui_env):
    from tinypedal.ui.quick.trace_data import TraceData

    reference, _ = reference_lap()
    shifted, _ = imported_lap(37.0, info=dict(RECORDED))  # recorded by the app: game lap distance, kept
    data = TraceData()
    data.set_laps([plot_lap("ref", reference), plot_lap("rec", shifted)], "ref")
    assert data.auto_offsets == {} and data.laps[1].data is shifted
    # Reference itself is never moved, even an imported one
    data.set_laps([plot_lap("ref", reference), plot_lap("rec", shifted)], "rec")
    assert data.auto_offsets == {} and data.laps[0].data is reference


def test_imported_lap_at_the_line_not_shifted(ui_env):
    from tinypedal.ui.quick.trace_data import TraceData

    reference, _ = reference_lap()
    for positions in (False, True):
        imported, _ = imported_lap(0.0, pace=1.03, positions=positions)
        data = TraceData()
        data.set_laps([plot_lap("ref", reference), plot_lap("imp", imported)], "ref")
        assert data.auto_offsets == {} and data.laps[1].data is imported


def test_auto_offset_with_braking_alignment_and_reference_change(ui_env):
    from tinypedal.ui.quick.trace_data import TraceData

    reference, _ = reference_lap()
    imported, _ = imported_lap(80.0)
    other, _ = imported_lap(0.0, pace=0.99, number=3)
    laps = [plot_lap("ref", reference), plot_lap("imp", imported), plot_lap("oth", other)]
    data = TraceData()
    data.set_laps(laps, "ref")
    aligned = data.laps[1].data
    corner = slowest_point(data, data.reference)
    data.set_offsets({"imp": 10.0})  # user alignment on a braking point adds to auto offset
    assert slowest_point(data, data.laps[1], 1500.0, 2150.0) == pytest.approx(corner + 10.0, abs=2.0)
    data.set_laps(laps, "ref")
    assert data.laps[1].data is aligned  # kept while reference & lap stay the same (series & map lines kept)
    data.set_laps(laps, "oth")  # imported reference: lap aligned on it, reference itself never moved
    assert data.laps[2].data is other and data.auto_offsets["imp"] == pytest.approx(80.0, abs=1.0)
    assert data.laps[0].data is reference  # recorded lap never moved


def test_mini_sectors_and_sectors_of_aligned_lap(ui_env):
    from tinypedal.ui.quick.trace_data import TraceData

    reference, reference_time = reference_lap()
    imported, imported_time = imported_lap(120.0, pace=1.0)
    data = TraceData()
    data.set_laps([plot_lap("ref", reference), plot_lap("imp", imported)], "ref")
    times = data.mini_sectors()["times"]
    assert sum(times[1]) == pytest.approx(imported_time, abs=0.01)
    for ref_part, part in zip(times[0], times[1]):  # same pace: same time in every mini-sector
        assert part == pytest.approx(ref_part, abs=0.02)
    assert imported_time == pytest.approx(reference_time, abs=0.01)


# --- MoTeC import: lap distance zero at the line, not at the late lap number change
def write_log(tmp_path, lag: float, odometer: bool, lap_time_channel: bool = True):
    from tests.test_motec_import import write_logger_ld

    lap_seconds, start, rate, distance_rate = 10.0, 3.03, 50, 20
    seconds = 4 * lap_seconds
    count = int(seconds * rate)
    if odometer:  # driven distance since log start
        distance = [(index / distance_rate + start) * 100.0 for index in range(int(seconds * distance_rate))]
    else:
        distance = [((index / distance_rate + start) % lap_seconds) * 100.0
                    for index in range(int(seconds * distance_rate))]
    changes = [k * lap_seconds - start + lag for k in range(1, 5)]
    channels = [
        ("Lap Number", "", rate, [sum(index / rate >= change for change in changes) for index in range(count)],
         32760, 1, 0),
        ("Distance" if odometer else "Lap Distance", "m", distance_rate, distance, 0, 1, 0),
        ("Ground Speed", "km/h", rate, [360.0] * count, 641, 2, 2),
    ]
    if lap_time_channel:
        channels.append(("Lap Time", "s", rate, [(index / rate + start) % lap_seconds for index in range(count)],
                         0, 1, 3))
    filename = str(tmp_path / "lag.ld")
    write_logger_ld(filename, channels)
    return filename, start


@pytest.mark.parametrize(("lag", "odometer"), [(0.3, True), (1.5, True), (1.5, False), (2.5, False)])
def test_motec_lap_distance_zero_at_line(tmp_path, lag, odometer):
    from tinypedal.userfile.motec_import import import_laps

    filename, start = write_log(tmp_path, lag, odometer)
    _, laps = import_laps(filename)
    assert len(laps) == 3
    for lap in laps:
        assert lap.lap_time == pytest.approx(10.0, abs=0.01)
        columns = lap.columns
        for index in (5, len(columns["time"]) // 2, len(columns["time"]) - 5):
            on_track = ((columns["time"][index] + start) % 10.0) * 100.0  # true lap distance (100 m/s)
            assert columns["distance"][index] == pytest.approx(on_track, abs=0.5)
            assert columns["lap_time"][index] == pytest.approx(on_track / 100.0, abs=0.01)
        assert columns["distance"][0] < 3.0 and columns["lap_time"][0] < 0.03  # lap from the line


def test_motec_odometer_without_line_rebased_at_lap_change(tmp_path):
    """No line crossing in the log (odometer, no lap time): lap from lap number change, offset found by viewer"""
    from tinypedal.userfile.motec_import import import_laps

    filename, _ = write_log(tmp_path, 0.3, True, lap_time_channel=False)
    _, laps = import_laps(filename)
    assert len(laps) == 3 and laps[0].columns["distance"][0] == pytest.approx(0.0, abs=0.01)
    assert laps[0].lap_time == pytest.approx(10.0, abs=0.03)


def test_imported_lap_driven_differently_not_shifted(ui_env, monkeypatch):
    """Lap at the line braking later & carrying another speed through a corner: no offset made up"""
    import tests.telemetry_sim as sim
    from tinypedal.ui.quick.trace_data import TraceData

    reference, _ = reference_lap()
    corners = list(sim.CIRCUIT_CORNERS)
    corners[1] = (0.355, 0.015, 42.0)  # later, shorter & slower corner
    corners[3] = (0.85, 0.035, 25.0)
    monkeypatch.setattr(sim, "CIRCUIT_CORNERS", tuple(corners))
    imported, _ = imported_lap(0.0, pace=0.98)
    data = TraceData()
    data.set_laps([plot_lap("ref", reference), plot_lap("imp", imported)], "ref")
    assert data.auto_offsets == {} and data.laps[1].data is imported
