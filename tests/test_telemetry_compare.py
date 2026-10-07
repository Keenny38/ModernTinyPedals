"""Telemetry comparison overlay: reference lap of lap viewer (choice, resampling, background loading),
live trail along driven distance, then both designs drawing current lap against reference lap."""

import json
import math
import os

import pytest

from tests.test_race_aid_widgets import grab, is_blank, make, set_reader
from tinypedal.setting import cfg
from tinypedal.userfile.reference_trace import ReferenceLoader, load_trace, reference_file, stop_loading
from tinypedal.userfile.telemetry_lap import VIEWER_SETTING, lap_files, lap_folder_name, viewer_reference_name
from tinypedal.widget.telemetry_compare import JUMP_AHEAD, TILE_WIDTH, LiveTrail, channel_ranges, reference_line

TRACK = "Track - Class"
LENGTH = 1000.0


def speed_at(distance: float) -> float:
    """Reference speed: slow corner at 500 m"""
    return 120.0 + 80.0 * abs(distance - 500.0) / 500.0


def write_lap(folder, stamp: str, lap_time: float, valid: bool = True, speed=speed_at) -> str:
    """Recorded lap file (recorder format, few channels), returns file name"""
    os.makedirs(folder, exist_ok=True)
    minutes, seconds = divmod(lap_time, 60)
    name = f"2026-10-06 {stamp} lap003 {int(minutes)}m{seconds:06.3f}s{'' if valid else ' invalid'}.csv"
    lines = ["# " + json.dumps({"track": "Track", "combo": TRACK, "track_length": LENGTH}),
             "time,lap_time,distance,speed_kph,throttle,brake,steering,gear"]
    for step in range(201):
        distance = step * 5.0
        braking = 400 <= distance < 480
        lines.append(",".join(str(value) for value in (
            100 + lap_time * distance / LENGTH, lap_time * distance / LENGTH, distance, speed(distance),
            0.0 if braking else 1.0, 0.8 if braking else 0.0, math.sin(distance / 100) * 0.3, 2 if braking else 4,
        )))
    with open(os.path.join(folder, name), "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")
    return name


def wait_reference(loader: ReferenceLoader, track: str = TRACK, now: float = 0.0):
    """Start reference check, wait for it, take result"""
    loader.poll(track, now)
    if loader._job is not None:
        loader._job.result(timeout=10)
    loader.poll(track, now)


@pytest.fixture(autouse=True)
def loading_thread():
    """Background thread of reference lap ended after each test"""
    yield
    stop_loading()


@pytest.fixture
def laps(tmp_path):
    """Telemetry folder with best lap (valid), slower newest lap, faster invalid lap"""
    folder = tmp_path / TRACK
    best = write_lap(folder, "10-00-00", 50.0)
    newest = write_lap(folder, "10-05-00", 52.0, speed=lambda distance: speed_at(distance) - 10)
    write_lap(folder, "10-02-00", 49.0, valid=False)
    return tmp_path, best, newest


# Reference lap
def test_lap_folder_name_of_combo():
    assert lap_folder_name("Spa - Hyper") == "Spa - Hyper"
    assert lap_folder_name("Spa - ") == "Spa"
    assert lap_folder_name("") == "unknown"


def test_reference_lap_choice(laps):
    root, best, newest = laps
    root = str(root)
    assert reference_file(root, TRACK, "Best").filename == best  # invalid faster lap left out
    assert reference_file(root, TRACK, "Last").filename == newest
    assert reference_file(root, TRACK, "Viewer").filename == best  # nothing chosen in viewer: fastest lap
    selections = {"selections": {TRACK: {"checked": [best, newest], "reference": newest}}}
    with open(os.path.join(root, VIEWER_SETTING), "w", encoding="utf-8") as file:
        json.dump(selections, file)
    assert viewer_reference_name(root, TRACK) == newest
    assert reference_file(root, TRACK, "Viewer").filename == newest
    assert reference_file(root, "Other - Class", "Viewer") is None


@pytest.mark.parametrize("content", ["", "[]", '{"selections": []}', '{"selections": {"Track - Class": 3}}'])
def test_viewer_reference_unreadable(tmp_path, content):
    (tmp_path / VIEWER_SETTING).write_text(content, encoding="utf-8")
    assert viewer_reference_name(str(tmp_path), TRACK) == ""


def test_reference_trace_resampled(laps):
    root, best, _ = laps
    lap = next(lap for lap in lap_files(str(root / TRACK)) if lap.filename == best)
    trace = load_trace(str(root), lap, 2.0)
    assert trace.length == LENGTH and trace.step == 2.0 and trace.lap_time == 50.0 and trace.valid
    assert len(trace.channels["speed_kph"]) == 500
    assert trace.value("speed_kph", 500.0) == pytest.approx(120.0, abs=0.5)
    assert trace.value("speed_kph", 1001.0) == pytest.approx(trace.value("speed_kph", 1.0))  # wrapped around lap
    assert trace.at("speed_kph", -1) == trace.channels["speed_kph"][-1]
    assert trace.value("gear", 441.0) == 2.0 and trace.value("gear", 300.0) == 4.0  # whole gears
    assert trace.time_at(500.0) == pytest.approx(25.0, abs=0.05)
    assert math.isnan(trace.time_at(-5.0)) and math.isnan(trace.value("clutch", 10.0))


def test_reference_loader_background(laps):
    root, best, newest = laps
    loader = ReferenceLoader(str(root), "Best", 2.0)
    wait_reference(loader)
    trace = loader.trace
    assert trace is not None and os.path.basename(trace.path).startswith(best[:-4])
    version = loader.version
    wait_reference(loader, now=10.0)  # checked again: same file, same trace
    assert loader.trace is trace and loader.version == version
    assert not loader.poll(TRACK, 11.0)  # next check not due yet
    os.remove(trace.path)  # best lap deleted: next fastest valid lap
    wait_reference(loader, now=20.0)
    assert loader.trace is not None and loader.trace.name.startswith(newest[:-4])
    assert loader.poll("Other - Class", 21.0) and loader.trace is None  # track changed: reference dropped at once
    wait_reference(loader, "Other - Class", 21.0)
    assert loader.trace is None


def test_reference_loader_unreadable_lap(tmp_path):
    folder = tmp_path / TRACK
    folder.mkdir()
    (folder / "2026-10-06 10-00-00 lap001 0m50.000s.csv").write_text("not,a,lap\n1,2,3\n", encoding="utf-8")
    loader = ReferenceLoader(str(tmp_path), "Viewer", 2.0)
    wait_reference(loader)
    assert loader.trace is None and loader._failed is not None
    wait_reference(loader, now=10.0)  # same broken file not read again
    assert loader.trace is None


def test_channel_ranges_from_reference(laps):
    root, best, _ = laps
    lap = next(lap for lap in lap_files(str(root / TRACK)) if lap.filename == best)
    ranges = channel_ranges(load_trace(str(root), lap, 2.0))
    assert ranges["speed_kph"] == (100.0, 220.0)
    assert ranges["steering"] == (-0.35, 0.35)
    assert ranges["gear"] == (0.5, 4.5)
    assert channel_ranges(None)["throttle"] == (0.0, 1.0)


def test_reference_line_wraps_around_lap():
    chart_y = [float(index) for index in range(10)]
    line = reference_line(chart_y, -2, 11, 2.0)
    assert [point.y() for point in line] == [8, 9, *range(10), 0, 1]  # previous & next lap
    assert [point.x() for point in line] == [index * 2.0 for index in range(-2, 12)]  # continuous along lap


@pytest.mark.parametrize("modern", [True, False], ids=["modern", "classic"])
def test_reference_tiles_cached(driving, modern):
    widget = make("telemetry_compare", modern)
    widget.timerEvent(None)
    wait_reference(widget.loader)
    drive(widget, driving, 0.0, 30.0)
    grab(widget)
    tiles = dict(widget.tiles)
    drive(widget, driving, 31.0, 34.0)  # same tiles moved along
    grab(widget)
    assert all(widget.tiles[index] is tile for index, tile in tiles.items())
    drive(widget, driving, 35.0, 990.0)
    grab(widget)
    assert len(widget.tiles) <= widget.tile_cache
    os.remove(widget.reference.path)  # reference lap gone: tiles dropped with it
    widget.loader._next_check = 0.0
    widget.timerEvent(None)
    wait_reference(widget.loader)
    widget.timerEvent(None)
    assert widget.reference.lap_time == 52.0 and not widget.tiles


# Live trail
def test_trail_continuous_over_lap_line():
    trail = LiveTrail(behind=100.0, step=2.0)
    values = (100.0, 1.0, 0.0, 0.0, 4.0)
    for distance in (980.0, 990.0, 999.0, 4.0, 14.0):
        trail.update(distance, LENGTH, values)
    assert trail.driven == pytest.approx(34.0)
    assert [sample[0] for sample in trail.samples] == pytest.approx([0.0, 10.0, 19.0, 24.0, 34.0])


def test_trail_keeps_distance_behind_only():
    trail = LiveTrail(behind=50.0, step=2.0)
    for step in range(100):
        trail.update(step * 3.0, LENGTH, (0.0,) * 5)
    assert trail.samples[1][0] >= trail.driven - 50.0 > trail.samples[0][0]


def test_trail_reset_and_corrections():
    trail = LiveTrail(behind=100.0, step=2.0)
    values = (0.0,) * 5
    trail.update(100.0, LENGTH, values)
    trail.update(110.0, LENGTH, values)
    assert not trail.update(105.0, LENGTH, values)  # small move back: ignored until car is past again
    assert not trail.update(111.0, LENGTH, values)  # less than one step from last sample
    trail.update(113.0, LENGTH, values)
    assert trail.driven == pytest.approx(13.0)
    trail.update(113.0 + JUMP_AHEAD + 1, LENGTH, values)  # garage, reset: trail starts again
    assert len(trail.samples) == 1
    assert not trail.update(math.nan, LENGTH, values)


# Widget
@pytest.fixture
def driving(ui_env, bundled_fonts, monkeypatch, laps):
    """Car driving reference track at lap distance state["distance"], lap time from reference pace"""
    root, _, _ = laps
    monkeypatch.setattr(cfg.path, "telemetry", str(root))
    cfg.user.setting["module_delta"]["enable"] = False
    state = {"distance": 0.0, "laptime": 0.0, "speed": 100.0}
    set_reader(monkeypatch, "session", "combo_name", TRACK)
    set_reader(monkeypatch, "lap", "distance", lambda *args, **kwargs: state["distance"])
    set_reader(monkeypatch, "lap", "track_length", LENGTH)
    set_reader(monkeypatch, "timing", "current_laptime", lambda *args, **kwargs: state["laptime"])
    set_reader(monkeypatch, "vehicle", "speed", lambda *args, **kwargs: state["speed"] / 3.6)
    set_reader(monkeypatch, "inputs", "throttle_raw", 1.0)
    set_reader(monkeypatch, "engine", "gear", 4)
    return state


def drive(widget, state, start: float, end: float, slower: float = 1.02):
    """Drive from start to end distance, slower than reference pace"""
    distance = start
    while distance <= end:
        state["distance"] = distance % LENGTH
        state["laptime"] = 50.0 * (distance % LENGTH) / LENGTH * slower
        state["speed"] = speed_at(distance % LENGTH) - 5
        widget.timerEvent(None)
        distance += 3.0


@pytest.mark.parametrize("modern", [True, False], ids=["modern", "classic"])
def test_widget_compares_with_reference(driving, modern):
    widget = make("telemetry_compare", modern, show_steering=True, show_gear=True)
    widget.timerEvent(None)
    wait_reference(widget.loader)
    assert widget.reference is not None and widget.reference_text().endswith("0:50.000")
    drive(widget, driving, 200.0, 420.0)
    assert set(widget.reference_y) == {"speed_kph", "throttle", "brake", "steering", "gear"}
    lines = dict(widget.lines)
    assert set(lines) == {"speed_kph", "throttle", "brake", "steering", "gear"}
    current = lines["speed_kph"]
    assert current.last().x() == pytest.approx(widget.car_x)
    assert all(point.x() <= widget.car_x + 0.01 for point in current)
    assert set(widget.fills) == ({"speed_kph", "throttle", "brake"} if modern else set())
    _, delta, speed_difference = widget.state
    assert delta == pytest.approx(50.0 * 0.419 * 0.02, abs=0.02)  # 2% slower at 419 m
    assert speed_difference == -5
    assert widget.delta_text(delta).startswith("+") and widget.speed_text(speed_difference).startswith("-5 ")
    left = widget.window_left
    assert left == pytest.approx((419.0 - widget.behind) * widget.meter_px)  # last position: 419 m
    assert not is_blank(grab(widget))
    width = widget.chart_right - widget.chart_left
    assert list(widget.tiles) == list(range(int(left // TILE_WIDTH), int((left + width) // TILE_WIDTH) + 1))


@pytest.mark.parametrize("modern", [True, False], ids=["modern", "classic"])
def test_widget_over_lap_line(driving, modern):
    widget = make("telemetry_compare", modern)
    widget.timerEvent(None)
    wait_reference(widget.loader)
    drive(widget, driving, 700.0, 1060.0)  # window wraps around lap line
    current = dict(widget.lines)["speed_kph"]
    xs = [point.x() for point in current]
    assert xs == sorted(xs) and xs[0] < widget.chart_left  # trail goes on back over lap line, past chart edge
    assert widget.window_left < 0
    grab(widget)
    assert min(widget.tiles) < 0  # tile before lap start: end of previous lap
    driving["laptime"] = 0.0  # lap time reset before lap distance (game updates it later)
    driving["distance"] = 999.0
    widget.timerEvent(None)
    assert widget.state[1] is None  # no delta of a whole lap


def test_trail_lines_follow_samples(driving):
    widget = make("telemetry_compare", True)
    widget.timerEvent(None)
    drive(widget, driving, 100.0, 600.0)  # samples added & removed, reference found meanwhile (chart ranges)
    wait_reference(widget.loader)
    drive(widget, driving, 601.0, 700.0)
    drive(widget, driving, 900.0, 950.0)  # moved elsewhere: trail started again

    def points(channel: str) -> list[tuple[float, float]]:
        return [(round(point.x(), 6), round(point.y(), 6)) for point in widget.trail_lines[channel]]

    incremental = {channel: points(channel) for _, channel in widget.trail_channels}
    widget.trail_synced = None
    widget.sync_trail_lines()
    assert incremental == {channel: points(channel) for _, channel in widget.trail_channels}
    assert len(incremental["speed_kph"]) == len(widget.trail.samples) > 10


@pytest.mark.parametrize("modern", [True, False], ids=["modern", "classic"])
def test_widget_without_reference_lap(ui_env, bundled_fonts, monkeypatch, modern):
    widget = make("telemetry_compare", modern)
    widget.timerEvent(None)
    wait_reference(widget.loader, "test")
    widget.timerEvent(None)
    assert widget.reference is None and widget.reference_text() == "No reference lap"
    assert widget.state[1] is None and widget.delta_text(None) == "-.--"
    assert not widget.reference_y
    assert not is_blank(grab(widget)) and not widget.tiles


def test_modern_options_hide_classic_colors(ui_env):
    from tinypedal.widget._modern import design_option_keys

    keys = list(cfg.user.setting["telemetry_compare"])
    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
    shown = design_option_keys(cfg, "telemetry_compare", keys)
    assert "reference_lap_source" in shown and "distance_ahead" in shown
    assert "line_color_brake" not in shown and "font_name" not in shown


@pytest.mark.parametrize("modern", [True, False])
@pytest.mark.parametrize("decimals", [0, 1, 2, 3])
def test_largest_delta_fits_its_width(driving, monkeypatch, modern, decimals):
    """Delta near 99.99 never rounds to 100 (0-1 decimals): text as wide as measured
    (was: "+100.0" drawn in a "+88.8" wide cell)"""
    from types import SimpleNamespace

    from tests.test_race_aid_widgets import make

    widget = make("telemetry_compare", modern, decimal_places=decimals)
    try:
        trace = SimpleNamespace(time_at=lambda distance: 400.0, lap_time=500.0)
        for laptime in (499.995, 300.005):  # delta +99.995, -99.995
            driving["laptime"] = laptime
            text = widget.delta_text(widget.delta_at(trace, 0.0))
            assert len(text) == len(f"{88.0:+.{decimals}f}"), text
            if modern:
                assert widget.text_width("value", text) <= widget.delta_w + 0.01
    finally:
        widget.deleteLater()
