"""Lap viewer audit J (data & calculations): lap scale from lap ends, series of laps scaled again, math channels
over delta & map placement, stints split on pit stops, lap time text, delta rate at lap ends, tyre wear, samples
shared between channels"""

import json
import math
import types
from array import array

import pytest
from PySide6.QtGui import QColor

from tinypedal.userfile.telemetry_lap import LapData, interpolate

TRACK = {"combo": "Track - GT3", "track": "Track", "track_length": 1000.0}  # recorded lap info (game track distance)
WHEELS = ("fl", "fr", "rl", "rr")


def lap_name(number: int, lap_time: float) -> str:
    """Recorded lap file name (official lap time in it)"""
    minutes, seconds = divmod(lap_time, 60)
    return f"2026-10-06 12-{number:02d}-00 lap{number:03d} {int(minutes)}m{seconds:06.3f}s"


def make_lap(number: int, lap_time: float, length: float, last: float, info: dict | None = None,
             pace=None, step: float = 5.0) -> LapData:
    """Lap of length meters timed lap_time, samples every step meters up to last; pace: share of lap time at
    share of lap (constant pace if None)"""
    distances = [step * index for index in range(1, int(last / step + 1e-9) + 1)]
    if distances[-1] < last - 1e-9:
        distances.append(last)
    share = pace or (lambda fraction: fraction)
    columns = {"distance": distances, "lap_time": [share(distance / length) * lap_time for distance in distances],
               "speed_kph": [100.0 + distance / 100 for distance in distances], "throttle": [0.5] * len(distances)}
    return LapData(lap_name(number, lap_time), columns, info)


def write_lap_file(folder, lap: LapData) -> str:
    """Lap saved as recorded lap file (info line, header, samples)"""
    path = folder / f"{lap.name}.csv"
    names = list(lap.columns)
    lines = [f"# {json.dumps(lap.info)}"] if lap.info else []
    lines.append(",".join(names))
    lines += [",".join(f"{lap.columns[name][index]:.6f}" for name in names) for index in range(len(lap))]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


# --- J3 imported lap scaled from lap ends (track length once lap reaches the line)
def test_imported_lap_scaled_from_lap_ends():
    from tinypedal.userfile.telemetry_lap import compute_delta, distance_scale, lap_time_curve

    reference = make_lap(1, 70.0, 1000.0, 990.0, dict(TRACK))  # last sample 10 m before the line
    imported = make_lap(2, 69.5, 992.3, 992.3, {"track_length": 992.3})  # MoTeC log: driven distance 0.77% short
    assert distance_scale(reference, imported) == pytest.approx(1000.0 / 992.3)
    assert compute_delta(reference, imported)[-1] == pytest.approx((1000.0, -0.5))  # delta at the line: lap gap
    longer = make_lap(3, 70.0, 1030.0, 1030.0, {"track_length": 1030.0})
    scale = distance_scale(reference, longer)
    assert scale == pytest.approx(1000.0 / 1030.0)
    assert lap_time_curve(longer)[0][-1] * scale == pytest.approx(1000.0)  # lap end on reference lap end
    cut = make_lap(4, 70.0, 1000.0, 950.0, dict(TRACK))  # stops 50 m (3.5 s) before the line
    assert lap_time_curve(cut)[0][-1] == pytest.approx(950.0)
    assert distance_scale(reference, cut) == 1.0  # recorded on the same track length: never scaled
    assert distance_scale(reference, make_lap(5, 70.0, 1000.0, 950.0, {"track_length": 1000.0})) != 1.0
    assert distance_scale(reference, make_lap(6, 70.0, 800.0, 800.0, {"track_length": 800.0})) == 1.0  # 20%: cut


def test_mini_sector_job_scales_like_viewer(ui_env, tmp_path):
    from tinypedal.ui.lap_viewer import PlotLap
    from tinypedal.ui.quick.trace_data import TraceData
    from tinypedal.userfile.lap_geometry import mini_sector_job
    from tinypedal.userfile.telemetry_lap import load_lap

    paths = [write_lap_file(tmp_path, lap) for lap in (
        make_lap(1, 70.0, 1000.0, 990.0, dict(TRACK)), make_lap(2, 69.5, 992.3, 992.3, {"track_length": 992.3}),
        make_lap(4, 70.0, 1000.0, 950.0, dict(TRACK)))]
    laps = [PlotLap(path, path, load_lap(path), QColor("red")) for path in paths]
    data = TraceData()
    data.set_laps(laps, paths[0])
    mini = data.mini_sectors()
    found = mini_sector_job(str(tmp_path), paths[1:], list(mini["bounds"]), data.lap_end(laps[0]),
                            dict(laps[0].data.meta))
    for path, times in zip(paths[1:], mini["times"][1:]):
        assert found[path] == pytest.approx(times)
    assert sum(found[paths[1]]) == pytest.approx(69.5)  # imported lap ends on reference lap end


# --- J25 lap end added when last samples are a bit past rounded track length (imported lap)
def test_lap_end_added_past_rounded_track_length():
    from tinypedal.userfile.telemetry_lap import lap_time_curve

    lap = make_lap(10, 69.68, 1000.03, 1000.03, {"track_length": 1000.0}, pace=lambda share: share * 69.64 / 69.68)
    distances, times = lap_time_curve(lap)
    assert (distances[-1], times[-1]) == pytest.approx((1000.0, 69.68))  # official lap time at the line
    assert distances[-2] < 1000.0 and times[-2] < 69.64


# --- J4 series of laps scaled again when reference changes
def test_series_scaled_again_when_reference_changes(ui_env):
    from tinypedal.ui.lap_viewer import CHANNEL_MAP, PlotLap
    from tinypedal.ui.quick.trace_data import TraceData

    first = PlotLap("a", "a", make_lap(1, 70.0, 1000.0, 990.0, dict(TRACK)), QColor("red"))
    longer = PlotLap("b", "b", make_lap(2, 70.5, 1050.0, 1050.0, {"track_length": 1050.0}), QColor("blue"))
    speed = CHANNEL_MAP["speed_kph"]
    data = TraceData()
    data.set_laps([first, longer], "a")
    assert data.series(speed, longer)[0][-1] == pytest.approx(1000.0)  # drawn on reference lap length
    keys = data.signature(speed, first), data.signature(speed, longer), data.signature(speed)
    data.set_laps([first, longer], "b")
    assert data.scale_of(first) == pytest.approx(1.05)
    assert data.series(speed, first)[0][-1] == pytest.approx(990.0 * 1.05)  # not the series cached before
    assert data.series(speed, longer)[0][-1] == pytest.approx(1050.0)
    assert data.max_x() == pytest.approx(1050.0)
    assert data.signature(speed, first) != keys[0] and data.signature(speed, longer) != keys[1]  # drawn again
    assert data.signature(speed) != keys[2]  # envelope too


# --- J5 math channels computed again when a computed input changes
def test_math_channel_follows_delta_window_and_placement(ui_env):
    from tinypedal.ui.lap_viewer import CHANNEL_MAP, PlotLap, math_channel, set_math_channels
    from tinypedal.ui.quick.trace_data import TraceData

    def wavy(share):  # time lost & gained along lap
        return share + 0.003 * math.sin(share * math.tau * 3)

    laps = [PlotLap(key, key, make_lap(number, lap_time, 1000.0, 990.0, dict(TRACK), pace=pace), QColor("red"))
            for number, (key, lap_time, pace) in enumerate((("a", 70.0, None), ("b", 71.0, wavy), ("c", 70.4, None)), 1)]
    channel = math_channel("Twice", "s")
    set_math_channels([channel])
    try:
        data = TraceData()
        data.set_math({channel.column: "delta * 2"})
        data.set_laps(laps, "a")

        def check(name: str):  # math channel along its lap samples is twice the channel there
            xs, ys = data.series(channel, laps[1])
            channel_xs, channel_ys = data.series(CHANNEL_MAP[name], laps[1])
            assert list(ys) == pytest.approx([2 * interpolate(channel_xs, channel_ys, x) for x in xs], abs=1e-4)

        check("delta")
        signature = data.signature(channel)
        data.set_laps(laps, "c")  # other reference
        check("delta")
        assert data.signature(channel) != signature
        signature = data.signature(channel)
        data.set_ideal_mode(True)
        check("delta")
        assert data.signature(channel) != signature
        data.set_math({channel.column: "delta_rate * 2"})
        check("delta_rate")
        signature = data.signature(channel)
        data.set_delta_window(200.0)
        check("delta_rate")
        assert data.signature(channel) != signature
        data.set_math({channel.column: "track_position * 2"})
        data.set_placements({"b": ([0.0, 1000.0], [1.0, 1.0], [10.0, 10.0])})  # measured on map
        assert data.series(channel, laps[1])[1][0] == pytest.approx(20.0)
        signature = data.signature(channel)
        data.set_placements({"b": ([0.0, 1000.0], [1.0, 1.0], [30.0, 30.0])})
        assert data.series(channel, laps[1])[1][0] == pytest.approx(60.0) and data.signature(channel) != signature
    finally:
        set_math_channels([])


def test_math_delta_of_scaled_lap(ui_env):
    from tinypedal.ui.lap_viewer import CHANNEL_MAP, PlotLap, math_channel, set_math_channels
    from tinypedal.ui.quick.trace_data import TraceData

    reference = PlotLap("a", "a", make_lap(1, 70.0, 1000.0, 990.0, dict(TRACK)), QColor("red"))
    imported = PlotLap("b", "b", make_lap(2, 72.0, 1040.0, 1040.0, {"track_length": 1040.0},
                                          pace=lambda share: share + 0.01 * share * share), QColor("blue"))
    channel = math_channel("Same", "s")
    set_math_channels([channel])
    try:
        data = TraceData()
        data.set_math({channel.column: "delta * 1"})
        data.set_laps([reference, imported], "a")
        assert data.scale_of(imported) == pytest.approx(1000.0 / 1040.0)
        xs, ys = data.series(channel, imported)  # lap samples on reference distance
        delta_xs, delta_ys = data.series(CHANNEL_MAP["delta"], imported)
        assert list(ys) == pytest.approx([interpolate(delta_xs, delta_ys, x) for x in xs], abs=1e-4)
    finally:
        set_math_channels([])


# --- J24 stints split on pit stops shown in lap info, trend along lap numbers
def stint_lap(number: int, lap_time: float = 70.0, fuel=None, wear=None, compound: str = "", kind: str = "lap"):
    from tinypedal.ui.quick.stint_analysis import StintLap

    return StintLap(lap_time, True, kind, compound, 0.0, "Practice", 0.0, number, fuel, wear)


def test_stints_split_on_pit_stops_between_recorded_laps():
    from tinypedal.ui.quick.stint_analysis import split_stints

    def numbers(laps):
        return [[lap.number for lap in stint] for stint in split_stints(laps)]

    refuel = [stint_lap(3, fuel=(31.9, 30.0)), stint_lap(7, fuel=(48.3, 46.4)),  # laps 4-6 not recorded: refuelled
              stint_lap(10, fuel=(44.0, 42.2)), stint_lap(11, fuel=(42.2, 40.2))]  # laps 8 & 9 used fuel
    assert numbers(refuel) == [[3], [7, 10, 11]]
    garage = [stint_lap(17, fuel=(39.9, 37.7)), stint_lap(19, fuel=(12.3, 10.4)), stint_lap(20, fuel=(10.4, 8.3))]
    assert numbers(garage) == [[17], [19, 20]]  # more fuel gone than one lap can use: taken out in garage
    worn, fresh = ((99.0,) * 4, (98.0,) * 4), ((100.0,) * 4, (99.0,) * 4)
    assert numbers([stint_lap(1, wear=worn), stint_lap(4, wear=fresh)]) == [[1], [4]]  # tyres changed
    assert numbers([stint_lap(1, compound="Soft"), stint_lap(4, compound="Medium")]) == [[1], [4]]
    assert numbers([stint_lap(3, fuel=(30.0, 28.0)), stint_lap(6, fuel=(24.0, 22.0))]) == [[3, 6]]  # laps not saved
    assert numbers([stint_lap(1, fuel=(50.0, 48.0)), stint_lap(2, fuel=(50.0, 48.0))]) == [[1, 2]]  # next lap
    assert numbers([stint_lap(0, fuel=(30.0, 28.0)), stint_lap(0, fuel=(45.0, 43.0))]) == [[0], [0]]  # no number


def test_stint_and_session_trend_along_lap_numbers():
    from tinypedal.ui.quick.lap_session import SessionTab
    from tinypedal.ui.quick.stint_analysis import stint_summary, trend_positions

    times = {1: 70.0, 2: 70.1, 5: 70.4, 6: 70.5}  # 0.1 s slower each lap, laps 3 & 4 not recorded
    assert stint_summary([stint_lap(number, lap_time) for number, lap_time in times.items()])["slope"] == (
        pytest.approx(0.1))
    assert trend_positions([1, 0, 5], [0, 1, 2]) == [0.0, 1.0, 2.0]  # a number unknown: position among laps
    assert trend_positions([7, 2], [0, 1]) == [0.0, 1.0]  # numbers going back
    rows = [{"time": lap_time, "valid": True, "number": number} for number, lap_time in times.items()]
    trend = SessionTab.session_trend(rows, [])
    assert trend["slope"] == pytest.approx(0.1) and (trend["x0"], trend["x1"]) == (0, 3)  # line ends on rows
    assert (trend["y0"], trend["y1"]) == pytest.approx((70.0, 70.5))


# --- J37 lap time text rounded before minutes are split
def test_lap_time_text_rounded_first():
    from tinypedal.ui.lap_viewer import format_laptime

    assert format_laptime(119.9996) == "2:00.000"
    assert format_laptime(59.9997) == "1:00.000"
    assert format_laptime(71.19) == "1:11.190" and format_laptime(9.5) == "9.500" and format_laptime(0.0) == "-"


# --- J42 setup differences show lap times timed by game
def test_setup_diff_shows_official_lap_times(ui_env):
    from tinypedal.ui.lap_viewer import PlotLap
    from tinypedal.ui.quick.lap_conditions import LapConditions

    laps = [PlotLap("a", "a", make_lap(5, 70.495, 1000.0, 990.0, dict(TRACK)), QColor("red")),  # last sample 0.7 s
            PlotLap("b", "b", make_lap(6, 71.2, 1000.0, 990.0, dict(TRACK)), QColor("blue"))]  # before the line
    page = types.SimpleNamespace(data=types.SimpleNamespace(laps=laps, reference=laps[0]), all_entries=list,
                                 short_label=lambda key: key)
    result = LapConditions.setupDiff(page, "a", "b")
    assert (result["timeA"], result["timeB"]) == ("1:10.495", "1:11.200")


# --- J43 time gain rate over the part of window inside lap
def test_delta_rate_at_lap_ends():
    from tinypedal.userfile.telemetry_lap import delta_rate

    distances = [float(meter) for meter in range(0, 1001, 10)]
    deltas = [distance * 0.002 for distance in distances]  # 0.2 s lost every 100 m
    assert delta_rate(distances, deltas, 40.0) == pytest.approx([0.2] * len(distances))
    assert delta_rate([5.0], [0.1]) == [0.0]


# --- J44 tyre wear unknown when tyres were changed during lap
def test_tyre_wear_unknown_when_tyres_changed_during_lap(ui_env, tmp_path):
    from tinypedal.ui.lap_viewer import LapEntry
    from tinypedal.ui.quick.lap_session import SessionTab
    from tinypedal.userfile.lap_geometry import session_values
    from tinypedal.userfile.telemetry_lap import LapFile

    worn, changed = make_lap(1, 70.0, 1000.0, 990.0, dict(TRACK)), make_lap(2, 70.0, 1000.0, 990.0, dict(TRACK))
    count = len(worn)
    for wheel in WHEELS:
        worn.columns[f"tyre_wear_{wheel}"] = [99.0 - index / count for index in range(count)]
        changed.columns[f"tyre_wear_{wheel}"] = [60.0 if index < count // 2 else 100.0 for index in range(count)]
    paths = [write_lap_file(tmp_path, lap) for lap in (worn, changed)]
    found = session_values(str(tmp_path), [(path, 1.0) for path in paths])
    assert found[paths[0]][1]["wear"] == pytest.approx(1.0, abs=0.02)
    assert "wear" not in found[paths[1]][1]  # unknown, not -40%
    infos = [{**TRACK, "wear_start": [99.0] * 4, "wear_end": [98.0] * 4},
             {**TRACK, "wear_start": [60.0] * 4, "wear_end": [99.5] * 4}]
    group = [LapEntry(LapFile(f"{lap_name(number, 70.0)}.csv", f"p{number}", True, 70.0), info)
             for number, info in enumerate(infos, 1)]
    page = types.SimpleNamespace(
        session_key=lambda: "s", session_groups=lambda: [("s", "Session", group)], data=types.SimpleNamespace(laps=[]),
        _session_extra={"p2": (1.0, {"wear": -39.5})}, reference_key="", _session_busy=False,
        session_trend=SessionTab.session_trend)
    rows = SessionTab.session_data(page)["laps"]
    assert rows[0]["wear"] == pytest.approx(1.0) and rows[1]["wear"] == -1.0


# --- J57 lap samples shared between channels, series values packed
def test_lap_samples_shared_between_channels(ui_env):
    from tinypedal.ui.lap_viewer import CHANNEL_MAP, PlotLap
    from tinypedal.ui.quick.trace_data import TraceData
    from tinypedal.userfile.telemetry_lap import increasing_indexes, monotonic_distance, pack_columns

    glitch = LapData("g", pack_columns({"distance": [0.0, 5.0, 4.0, 6.0, 8.0], "lap_time": [0.0, 0.5, 0.6, 0.7, 0.9],
                                        "speed_kph": [1.0, 2.0, 3.0, 4.0, 5.0], "throttle": [0.1, 0.2, 0.3, 0.4, 0.5]}))
    speed_distances, speeds = monotonic_distance(glitch, "speed_kph")
    throttle_distances, _ = monotonic_distance(glitch, "throttle")
    assert speed_distances is throttle_distances and list(speed_distances) == [0.0, 5.0, 6.0, 8.0]  # one copy
    assert isinstance(speeds, array) and speeds.typecode == "f" and list(speeds) == [1.0, 2.0, 4.0, 5.0]
    assert increasing_indexes(glitch.distance) == [0, 1, 3, 4]
    reference = PlotLap("a", "a", make_lap(1, 70.0, 1000.0, 990.0, dict(TRACK)), QColor("red"))
    log = make_lap(2, 70.0, 1030.0, 1030.0, {"track_length": 1030.0})
    log.columns["fuel"] = [50.0 - index * 0.01 for index in range(len(log))]
    imported = PlotLap("b", "b", log, QColor("blue"))
    data = TraceData()
    data.set_laps([reference, imported], "a")
    speed_xs, _ = data.series(CHANNEL_MAP["speed_kph"], imported)
    throttle_xs, _ = data.series(CHANNEL_MAP["throttle"], imported)
    fuel_xs, used = data.series(CHANNEL_MAP["fuel_used"], imported)
    assert speed_xs is throttle_xs is fuel_xs and isinstance(speed_xs, array)  # scaled once for every channel
    assert isinstance(used, array) and used[-1] == pytest.approx(0.01 * (len(log) - 1))
    data.set_offsets({"b": 12.0})  # aligned on a braking point: shifted once too
    assert data.series(CHANNEL_MAP["speed_kph"], imported)[0] is data.series(CHANNEL_MAP["throttle"], imported)[0]
    assert data.series(CHANNEL_MAP["speed_kph"], imported)[0][0] == pytest.approx(speed_xs[0] + 12.0)
