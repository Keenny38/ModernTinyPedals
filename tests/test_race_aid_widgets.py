"""Race aid widgets: delta graph, gap trend, pit lane helper, stint timer, spotter, race notifications,
tyre temperature trend, telemetry comparison. Data logic, then rendering of both designs with empty, normal
& extreme data."""

import math
from importlib import import_module

import pytest
from PySide6.QtCore import QCoreApplication, QPoint, QRectF, Qt, QTimerEvent
from PySide6.QtGui import QColor, QImage, QRegion
from PySide6.QtWidgets import QWidget

from tests.test_widget_benchmark import fill_field
from tinypedal.module_info import minfo
from tinypedal.setting import cfg
from tinypedal.widget._modern import create_widget

NEW_WIDGETS = (
    "delta_graph", "gap_trend", "pit_lane_helper", "stint_timer", "spotter", "race_notifications", "tyre_temp_trend",
    "telemetry_compare",
)
FIELD_ATTRIBUTES = {
    minfo.vehicles: (
        "dataSet", "dataSetVersion", "totalVehicles", "playerIndex", "leaderIndex", "leaderBestLapTime",
        "nearestLine", "nearestTraffic", "totalCompletedLaps", "nearestBlueClass",
    ),
    minfo.relative: ("standings", "drawOrder", "relativeAhead", "relativeBehind"),
}


def is_blank(image: QImage) -> bool:
    """Nothing drawn: widget rendered offscreen leaves unpainted pixels black"""
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            if QColor(image.pixel(x, y)).rgb() & 0xFFFFFF:
                return False
    return True


def set_reader(monkeypatch, group: str, name: str, value):
    """Fake API reader method returning value (or calling it, if callable)"""
    from tinypedal.api_control import api

    func = value if callable(value) else (lambda *args, **kwargs: value)
    monkeypatch.setattr(getattr(api.read, group), name, func)


@pytest.fixture(autouse=True)
def reference_loading():
    """Background thread finding reference lap (telemetry comparison) ended after each test"""
    yield
    from tinypedal.userfile.reference_trace import stop_loading

    stop_loading()


@pytest.fixture
def field(ui_env, bundled_fonts, monkeypatch):
    """Default setting, fake reader, field of 20 cars in minfo (restored after test)"""
    for owner, names in FIELD_ATTRIBUTES.items():
        for name in names:
            monkeypatch.setattr(owner, name, getattr(owner, name))
    fill_field(20)
    return minfo.vehicles


def make(name: str, modern: bool, **options):
    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
    cfg.user.setting[name].update(options)
    return create_widget(import_module(f"tinypedal.widget.{name}"), cfg, name)


def frames(widget, count: int = 3):
    event = QTimerEvent(0)
    for _ in range(count):
        widget.timerEvent(event)


def snapshot(widget) -> QImage:
    """Widget drawing without window background: blank if widget draws nothing"""
    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.black)
    widget.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    return image


def grab(widget) -> QImage:
    """Snapshot, then widget deleted"""
    widget.adjustSize()
    image = snapshot(widget)
    widget.deleteLater()
    QCoreApplication.processEvents()
    return image


# Shared parts
def test_sample_runs_and_lines():
    from tinypedal.widget._race_aids import line_polygons, sample_runs, scale_y, value_range

    values = [1.0, math.nan, 2.0, 3.0, math.inf, 4.0]
    assert sample_runs(values) == [(0, 0), (2, 3), (5, 5)]
    rect = QRectF(0, 0, 100, 50)
    lines = line_polygons(values, rect, 0.0, 4.0)
    assert [line.size() for line in lines] == [2, 2, 2]  # single samples drawn as short lines
    assert line_polygons([], rect, 0, 1) == ()
    assert scale_y(0.0, rect, 0.0, 4.0) == 50 and scale_y(4.0, rect, 0.0, 4.0) == 0
    assert scale_y(99.0, rect, 0.0, 4.0) == 0  # clamped
    assert scale_y(1.0, rect, 1.0, 1.0) == 25  # no range: middle
    assert value_range([], 2.0) == (0.0, 2.0)
    assert value_range([10.0, 10.2], 1.0) == (9.6, 10.6) or value_range([10.0, 10.2], 1.0)[1] - 9.6 < 1.1
    low, high = value_range([81.0, 93.0], 20.0, 5.0)
    assert low % 5 == 0 and high % 5 == 0 and high - low >= 20 and low <= 81 and high >= 93


# Delta graph
def test_delta_trace_laps():
    from tinypedal.widget.delta_graph import DeltaTrace

    trace = DeltaTrace(10)
    assert trace.update(5, 0.05, -0.1)
    trace.update(5, 0.35, -0.4)  # skipped slots filled linearly
    assert math.isclose(trace.current[1], -0.2) and math.isclose(trace.current[2], -0.3)
    assert not trace.update(5, 0.36, -0.5)  # same slot: no change
    assert not trace.update(5, math.nan, 0.1) and not trace.update(5, 0.5, math.inf)
    trace.update(5, 0.95, 0.2)
    trace.update(6, 0.02, 0.0)  # lap completed: current becomes previous
    assert trace.previous[9] == 0.2 and math.isnan(trace.current[5])
    # Finish line crossed before lap counter: rotated once only
    trace.update(6, 0.97, 0.3)
    trace.update(6, 0.01, 0.0)
    assert trace.wrapped and trace.previous[9] == 0.3
    trace.update(7, 0.02, 0.0)
    assert trace.previous[9] == 0.3 and not trace.wrapped
    # Back along lap (garage): current lap restarted
    trace.update(7, 0.6, 0.1)
    trace.update(7, 0.2, 0.0)
    assert math.isnan(trace.current[6])
    # New session: everything cleared
    trace.update(0, 0.5, 0.0)
    assert all(math.isnan(value) for value in trace.previous)


def test_delta_area_split_by_sign():
    from tinypedal.widget.delta_graph import area_polygons

    rect = QRectF(0, 0, 90, 40)
    values = [-1.0, 1.0, math.nan, 0.5]
    gain = area_polygons(values, rect, 2.0, -1)
    loss = area_polygons(values, rect, 2.0, 1)
    assert len(gain) == len(loss) == 2
    assert all(point.y() >= 20 for point in gain[0])  # gain below zero line
    assert all(point.y() <= 20 for point in loss[0])  # loss above zero line


@pytest.mark.parametrize("modern", [True, False])
def test_delta_graph_draws_lap(field, monkeypatch, modern):
    progress = {"value": 0.0}
    set_reader(monkeypatch, "lap", "progress", lambda *args, **kwargs: progress["value"])
    set_reader(monkeypatch, "lap", "completed_laps", 3)
    widget = make("delta_graph", modern)
    for step in range(60):
        progress["value"] = step / 60
        monkeypatch.setattr(minfo.delta, "deltaBest", math.sin(step / 8))
        widget.timerEvent(None)
    assert widget.shapes.gain and widget.shapes.loss and widget.shapes.line
    version, mark_x, _, delta = widget.state
    assert version > 0 and widget.chart.left() < mark_x < widget.chart.right()
    assert widget.delta_text(delta).startswith(("+", "-"))
    assert widget.delta_text(math.nan) == "-.--"
    assert not is_blank(grab(widget))


# Gap trend
def test_gap_series_trend_and_rate():
    from tinypedal.widget.gap_trend import BAD, GOOD, NEUTRAL, GapSeries, rate_meaning, time_gap

    series = GapSeries(5)
    assert series.trend() == [] and math.isnan(series.rate())
    for gap in (3.0, 2.6, 2.2):
        series.add(gap, 7)
    assert math.isclose(series.rate(), -0.4)
    series.add(1.0, 8)  # other car: history starts again
    assert math.isnan(series.trend()[0]) and math.isnan(series.rate())
    series.add(math.nan, 8)  # lapped
    assert math.isnan(series.rate())
    assert rate_meaning(-0.4, ahead=True) == GOOD
    assert rate_meaning(-0.4, ahead=False) == BAD
    assert rate_meaning(0.4, ahead=False) == GOOD
    assert rate_meaning(0.01, ahead=True) == NEUTRAL
    assert rate_meaning(math.nan, ahead=True) == NEUTRAL
    assert math.isnan(time_gap(2)) and time_gap(0) == 0.0 and time_gap(-1.5) == 1.5 and math.isnan(time_gap(math.inf))


@pytest.mark.parametrize("in_class", [True, False])
def test_gap_trend_history(field, monkeypatch, in_class):
    lap = {"value": 10}
    set_reader(monkeypatch, "lap", "completed_laps", lambda *args, **kwargs: lap["value"])
    set_reader(monkeypatch, "vehicle", "slot_id", lambda index=None: index)
    widget = make("gap_trend", True, show_gaps_in_class=in_class, show_driver_name=True)
    cars = field.dataSet
    player = cars[field.playerIndex]
    behind_overall = cars[field.playerIndex + 1]
    for step in range(5):
        player.gapBehindNextInClass = player.gapBehindNext = 3.0 - step * 0.5
        cars[player.classBehindIndex].gapBehindNextInClass = behind_overall.gapBehindNext = 1.0 + step * 0.2
        lap["value"] += 1
        widget.timerEvent(None)
    ahead, behind = widget.read_gaps()
    assert ahead.rate == "-0.50" and ahead.meaning == 1
    assert behind.rate == "+0.20" and behind.meaning == 1
    assert ahead.name.startswith("Driver")
    assert widget.charts[0].lines and widget.charts[0].end is not None
    player.gapBehindNextInClass = player.gapBehindNext = 2  # a lap behind
    assert widget.read_gaps()[0].gap == "+2L"
    lap["value"] = 0  # new session
    widget.timerEvent(None)
    assert not widget.series[0].samples
    assert not is_blank(grab(widget))


def test_gap_trend_without_cars(field, monkeypatch):
    monkeypatch.setattr(minfo.vehicles, "playerIndex", -1)
    widget = make("gap_trend", False)
    frames(widget)
    assert widget.state[1][0].gap == chr(0x2013)
    assert not is_blank(grab(widget))


# Pit lane helper
def test_box_distance():
    from tinypedal.widget.pit_lane_helper import box_distance

    assert box_distance(4900.0, 100.0, 5000.0) == 200.0
    assert box_distance(50.0, 100.0, 5000.0) == 50.0
    assert box_distance(50.0, -1.0, 5000.0) == -1.0
    assert box_distance(math.nan, 100.0, 5000.0) == -1.0


def pit_lane(monkeypatch, position, in_lane=1, requested=False, limiter=True, speed=22.0):
    set_reader(monkeypatch, "lap", "distance", position)
    set_reader(monkeypatch, "lap", "track_length", 5000.0)
    set_reader(monkeypatch, "lap", "pit_box_distance", 200.0)
    set_reader(monkeypatch, "lap", "pit_entry_distance", 4800.0)
    set_reader(monkeypatch, "vehicle", "in_paddock", in_lane)
    set_reader(monkeypatch, "vehicle", "pit_request", requested)
    set_reader(monkeypatch, "vehicle", "speed", speed)
    set_reader(monkeypatch, "switch", "speed_limiter_available", True)
    set_reader(monkeypatch, "switch", "speed_limiter", int(limiter))


@pytest.mark.parametrize("modern", [True, False])
def test_pit_lane_helper_visibility(field, monkeypatch, modern):
    from tinypedal.widget.pit_lane_helper import DANGER, OK, WARNING

    cfg.overlay["fixed_position"] = True  # locked: drawn only while shown
    monkeypatch.setattr(minfo.mapping, "pitSpeedLimit", 80 / 3.6)
    pit_lane(monkeypatch, 1000.0, in_lane=0)
    widget = make("pit_lane_helper", modern)
    frames(widget)
    assert not widget.read_pit().visible
    assert is_blank(snapshot(widget))
    # Approaching pit entry with pit request, limiter off
    pit_lane(monkeypatch, 4500.0, in_lane=0, requested=True, limiter=False, speed=60.0)
    reading = widget.read_pit()
    assert reading.visible and reading.limiter_state == WARNING and reading.speed_state == DANGER
    # In pit lane: speed under limit, box getting closer
    pit_lane(monkeypatch, 4900.0, speed=21.0)
    reading = widget.read_pit()
    assert reading.speed_state == OK and reading.limiter_state == OK and reading.box == "300m"
    pit_lane(monkeypatch, 50.0, speed=21.0)
    assert widget.read_pit().box_fraction == round(1 - 150 / 700, 3)  # 700 m to box when shown
    pit_lane(monkeypatch, 50.0, limiter=False, speed=21.0)
    assert widget.read_pit().limiter_state == DANGER
    pit_lane(monkeypatch, 400.0, speed=21.0)  # drove past box
    assert widget.read_pit().box_fraction == 1.0
    frames(widget)
    assert not is_blank(grab(widget))


def test_pit_lane_helper_services(field, monkeypatch):
    pit_lane(monkeypatch, 4900.0)
    set_reader(monkeypatch, "vehicle", "pit_stop_time", 34.6)
    set_reader(monkeypatch, "vehicle", "repair_time", 0.0)
    set_reader(monkeypatch, "vehicle", "absolute_refill", 80.0)
    widget = make("pit_lane_helper", True)
    monkeypatch.setattr(minfo.fuel, "amountCurrent", 30.0)
    reading = widget.read_pit()
    assert (reading.stop, reading.repair, reading.refuel) == ("35s", chr(0x2013), "+50L")
    monkeypatch.setattr(minfo.energy, "available", True)
    monkeypatch.setattr(minfo.energy, "amountCurrent", 20.0)
    assert widget.read_pit().refuel == "+60%"
    set_reader(monkeypatch, "switch", "speed_limiter_available", False)
    assert widget.read_pit().limiter == chr(0x2013)
    widget.deleteLater()


def test_pit_lane_entry_unknown(field, monkeypatch):
    pit_lane(monkeypatch, 4700.0, in_lane=0, requested=True)
    set_reader(monkeypatch, "lap", "pit_entry_distance", -1.0)
    monkeypatch.setattr(minfo.mapping, "pitEntryPosition", 0.0)
    widget = make("pit_lane_helper", True, approach_distance=400)
    assert widget.read_pit().visible  # 300 m to finish line
    pit_lane(monkeypatch, 4000.0, in_lane=0, requested=True)
    set_reader(monkeypatch, "lap", "pit_entry_distance", -1.0)
    assert not widget.read_pit().visible
    widget.deleteLater()


# Stint timer
def test_driver_times():
    from tinypedal.widget.stint_timer import DriverTimes

    times = DriverTimes()
    times.update(1, 100.0, "A", True, 0)
    times.update(1, 101.0, "A", True, 1)
    times.update(1, 120.0, "A", True, 1)  # jump (pause, replay): not driving time
    times.update(1, 121.0, "B", True, 2)
    times.update(1, 122.0, "B", False, 2)  # in garage
    assert times.times == {"A": 1.0, "B": 1.0} and times.laps == {"A": 1, "B": 1}
    times.update(1, 50.0, "B", True, 0)  # session restarted
    assert times.times == {"B": 0.0}
    times.update(2, 60.0, "C", True, 0)  # new session
    assert list(times.times) == ["C"]
    times.update(2, math.nan, "C", True, 0)
    assert times.times["C"] == 0.0


@pytest.mark.parametrize("modern", [True, False])
def test_stint_timer_drivers(field, monkeypatch, modern):
    from tinypedal.widget import stint_timer

    monkeypatch.setattr(stint_timer, "DRIVER_TIMES", stint_timer.DriverTimes())
    clock = {"elapsed": 0.0, "driver": "Driver A"}
    set_reader(monkeypatch, "session", "elapsed", lambda: clock["elapsed"])
    set_reader(monkeypatch, "session", "end", 3600.0)
    set_reader(monkeypatch, "session", "identifier", (9, 0, 0))
    set_reader(monkeypatch, "vehicle", "driver_name", lambda index=None: clock["driver"])
    set_reader(monkeypatch, "vehicle", "player_has_vehicle", True)
    monkeypatch.setattr(minfo.history.stintDataCurrent, "totalTime", 3000.0)
    monkeypatch.setattr(minfo.history.stintDataCurrent, "totalLaps", 25)
    widget = make("stint_timer", modern, maximum_stint_minutes=52, number_of_drivers=2)
    for step in range(10):
        clock["elapsed"] = step * 2.0
        if step == 5:
            clock["driver"] = "Driver B"
        widget.timerEvent(None)
    reading = widget.read_stint()
    assert reading.fair_share == "0:30:00" and reading.laps == "25"
    assert reading.countdown == "0:02:00" and reading.countdown_state == stint_timer.WARNING
    assert [row.name for row in reading.drivers] == ["Driver A", "Driver B"]
    assert reading.drivers[1].current and not reading.drivers[0].current
    assert reading.drivers[0].driven == "0:00:08"  # first reading only starts count
    assert widget.driver_rows() == 2
    monkeypatch.setattr(minfo.history.stintDataCurrent, "totalTime", 3200.0)
    assert widget.read_stint().countdown_state == stint_timer.OVER
    set_reader(monkeypatch, "session", "finish_type", 1)  # lap race: no fair share
    assert widget.fair_share() == 0.0
    assert not is_blank(grab(widget))


def test_stint_timer_minimum_drive_target(field, monkeypatch):
    from tinypedal.widget import stint_timer

    times = stint_timer.DriverTimes()
    times.times.update({"A": 1800.0, "B": 600.0})
    monkeypatch.setattr(stint_timer, "DRIVER_TIMES", times)
    set_reader(monkeypatch, "session", "identifier", (None, 0, 0))
    widget = make("stint_timer", True, minimum_driving_minutes=20, show_stint_countdown=False)
    rows = widget.read_stint().drivers
    assert rows[0].state == stint_timer.MET and rows[0].remaining == "0:00:00"
    assert rows[1].fraction == 0.5 and rows[1].remaining == "0:10:00"
    widget.deleteLater()


# Spotter
def test_side_overlap():
    from tinypedal.widget.spotter import NO_CAR, side_overlap

    assert side_overlap([], 4.6, 5.0, 2.6) == (NO_CAR, NO_CAR)
    left, right = side_overlap([(-2.0, 2.3), (4.0, 0.0), (8.0, 0.0), (1.0, 9.0), (math.nan, 0.0)], 4.6, 5.0, 2.6)
    assert (left.top, left.bottom, left.critical) == (0.5, 1.0, True)  # behind left, half overlapped
    assert (right.top, right.bottom, right.critical) == (0.0, 1.0, False)  # alongside right
    left, _ = side_overlap([(-3.0, -4.0), (-3.0, 4.0)], 4.6, 5.0, 2.6)  # ahead & behind: both ends lit
    assert left.top < 0.1 and left.bottom > 0.9 and left.lit


@pytest.mark.parametrize("modern", [True, False])
def test_spotter_draws_only_with_car_alongside(field, monkeypatch, modern):
    cfg.overlay["fixed_position"] = True
    widget = make("spotter", modern)
    for car in field.dataSet:
        car.relativeRotatedPositionX = 50.0
    monkeypatch.setattr(minfo.vehicles, "dataSetVersion", 100)
    widget.timerEvent(None)
    assert is_blank(snapshot(widget))
    field.dataSet[0].relativeRotatedPositionX = -2.0
    field.dataSet[0].relativeRotatedPositionY = 1.0
    monkeypatch.setattr(minfo.vehicles, "dataSetVersion", 101)
    widget.timerEvent(None)
    assert widget.state[0].lit and widget.state[0].critical
    assert not is_blank(grab(widget))


def test_spotter_preview_while_unlocked(field):
    cfg.overlay["fixed_position"] = False
    widget = make("spotter", True)
    widget.preview_toggled(False)
    assert not is_blank(grab(widget))


# Race notifications
def test_settled_value():
    from tinypedal.widget.race_notifications import Settled

    settled = Settled(1.0)
    assert settled.update(5, 0.0) is None  # first value
    assert settled.update(4, 1.0) is None  # new candidate
    assert settled.update(5, 1.5) is None  # back: no change
    assert settled.update(4, 2.0) is None
    assert settled.update(4, 3.1) == (5, 4)
    assert settled.update(4, 4.0) is None


def race(monkeypatch, **values):
    defaults = {"in_race": True, "pre_race": False, "identifier": (1, 0, 0), "blue_flag": False,
                "yellow_flag_state": 0}
    for name, value in {**defaults, **values}.items():
        set_reader(monkeypatch, "session", name, value)


def test_race_events(field, monkeypatch):
    from tinypedal.widget.race_notifications import BEST, GAIN, LOSS, WARNING, RaceEvents

    options = ("show_position_change", "show_position_change_in_class", "show_penalty", "show_class_fastest_lap",
               "show_blue_flag", "show_full_course_yellow", "show_lap_invalidated")
    events = RaceEvents(dict.fromkeys(options, True))
    race(monkeypatch)
    player = field.dataSet[field.playerIndex]
    assert events.poll(0.0) == []  # first reading never notifies
    player.positionOverall -= 1
    events.poll(0.5)
    messages = events.poll(2.0)
    assert [(m.title, m.kind) for m in messages] == [("Position", GAIN)]
    assert messages[0].detail.endswith("1")
    player.positionInClass += 2
    events.poll(2.1)
    assert [m.kind for m in events.poll(3.5)] == [LOSS]
    set_reader(monkeypatch, "vehicle", "number_penalties", 1)
    assert [m.title for m in events.poll(4.0)] == ["Penalty"]
    field.dataSet[0].bestLapTime = 80.0  # same class as player (LMP2): new class best
    messages = events.poll(4.1)
    assert messages[0].kind == BEST and "1:20.000" in messages[0].detail
    race(monkeypatch, blue_flag=True)
    monkeypatch.setattr(minfo.vehicles, "nearestBlueClass", "HY")
    assert events.poll(4.2)[0].detail == "HY"
    race(monkeypatch, yellow_flag_state=2)
    assert [m.title for m in events.poll(4.3)] == ["Full course yellow"]
    race(monkeypatch, yellow_flag_state=0)
    assert [m.title for m in events.poll(4.4)] == ["Green flag"]
    set_reader(monkeypatch, "lap", "invalidated", True)
    assert [(m.title, m.kind) for m in events.poll(4.5)] == [("Lap invalidated", WARNING)]
    race(monkeypatch, identifier=(2, 0, 0))  # new session: no stale message
    assert events.poll(5.0) == []


@pytest.mark.parametrize("modern", [True, False])
@pytest.mark.parametrize("layout", [0, 1])
def test_race_notifications_queue(field, monkeypatch, modern, layout):
    from tinypedal.widget.race_notifications import FADE_STEPS, Message

    cfg.overlay["fixed_position"] = True
    race(monkeypatch)
    widget = make("race_notifications", modern, layout=layout, number_of_notifications=2, display_duration=5)
    clock = {"now": 0.0}
    widget.clock = lambda: clock["now"]
    frames(widget)
    assert is_blank(snapshot(widget))  # no message: nothing drawn
    first, second, third = Message("Penalty"), Message("Blue flag"), Message("Lap invalidated")
    widget.add_messages([first, second, first], 0.0)
    assert len(widget.toasts) == 2  # same message not repeated
    widget.add_messages([third], 1.0)
    assert [toast.message for toast in widget.toasts] == [second, third]  # oldest dropped
    clock["now"] = 4.8
    shown = widget.read_notifications()
    assert shown[0][0] == third and shown[1][1] < FADE_STEPS  # newest first, older fading
    assert widget.slot_order(shown)[0][0] == (third if layout == 0 else second)
    assert widget.first_slot(1) == (0 if layout == 0 else 1)  # newest at bottom: stack from bottom
    widget.timerEvent(None)
    assert not is_blank(snapshot(widget))
    clock["now"] = 7.0
    assert widget.read_notifications() == ()
    widget.deleteLater()


def test_race_notifications_preview(field):
    cfg.overlay["fixed_position"] = False
    for modern in (True, False):
        assert not is_blank(grab(make("race_notifications", modern)))


# Tyre temperature trend
def test_temperature_trend_time_and_lap_modes():
    from tinypedal.widget.tyre_temp_trend import TIME_SAMPLES, TemperatureTrend

    trend = TemperatureTrend(60.0, False, 5)
    for step in range(200):
        trend.update(step * 0.5, 0, (80.0 + step, 81.0, 82.0, 83.0))
    assert len(trend.samples[0]) == TIME_SAMPLES and trend.samples[0][-1] == 278.0
    trend.update(1.0, 0, (80.0,) * 4)  # time went back: cleared
    assert len(trend.samples[0]) == 1
    trend.update(2.0, 0, (math.nan, 0.0, 0.0, 0.0))  # invalid reading skipped
    trend.update(2.5, 0, (-200.0, 0.0, 0.0, 0.0))
    assert len(trend.samples[0]) == 1
    laps = TemperatureTrend(60.0, True, 3)
    for lap in range(5):
        for step in range(4):
            laps.update(lap * 10 + step, lap, (70.0 + lap + step,) * 4)
    assert list(laps.samples[0]) == [72.5, 73.5, 74.5]
    laps.update(100.0, 0, (70.0,) * 4)  # lap counter went back
    assert not laps.samples[0]


@pytest.mark.parametrize("modern", [True, False])
def test_tyre_temp_trend_charts(field, monkeypatch, modern):
    clock = {"elapsed": 0.0}
    set_reader(monkeypatch, "timing", "elapsed", lambda *args, **kwargs: clock["elapsed"])
    set_reader(monkeypatch, "tyre", "optimal_temperature", (85.0, 85.0, 90.0, 90.0))
    temperatures = {"value": (70.0, 75.0, 80.0, 85.0)}
    set_reader(monkeypatch, "tyre", "surface_temperature_avg", lambda *args, **kwargs: temperatures["value"])
    widget = make("tyre_temp_trend", modern, trend_duration=60, show_degree_sign=False)
    for step in range(30):
        clock["elapsed"] = step * 1.0
        temperatures["value"] = tuple(70.0 + wheel * 5 + step for wheel in range(4))
        widget.timerEvent(None)
    _, texts, colors = widget.state
    assert texts == ("99", "104", "109", "114") and all(color is not None for color in colors)
    assert all(chart.lines and chart.pen is not None and chart.optimal >= 0 for chart in widget.charts)
    temperatures["value"] = (math.nan, -273.0, 80.0, 80.0)
    widget.timerEvent(None)
    assert widget.state[1][:2] == (chr(0x2013), chr(0x2013))
    assert not is_blank(grab(widget))


# Every new widget, both designs: empty data, then extreme data
@pytest.mark.parametrize("modern", [True, False], ids=["modern", "classic"])
@pytest.mark.parametrize("name", NEW_WIDGETS)
def test_new_widgets_render_empty_and_extreme(ui_env, bundled_fonts, monkeypatch, name, modern):
    cfg.overlay["fixed_position"] = False  # unlocked: hidden widgets drawn too
    widget = make(name, modern)
    frames(widget)
    assert not is_blank(grab(widget)), "empty data"
    for value in (math.nan, math.inf, -1e12, 1e12):
        for group_name in ("delta", "fuel", "energy"):
            group = getattr(minfo, group_name)
            for slot in type(group).__slots__:
                if isinstance(getattr(group, slot), float):
                    monkeypatch.setattr(group, slot, value)
        for group, readers in (
            ("lap", ("progress", "distance", "track_length", "pit_box_distance", "pit_entry_distance")),
            ("vehicle", ("speed", "pit_stop_time", "absolute_refill", "repair_time")),
            ("session", ("elapsed", "end")),
            ("timing", ("elapsed",)),
        ):
            for reader in readers:
                set_reader(monkeypatch, group, reader, value)
        set_reader(monkeypatch, "tyre", "surface_temperature_avg", (value,) * 4)
        set_reader(monkeypatch, "tyre", "optimal_temperature", (value,) * 4)
        monkeypatch.setattr(minfo.mapping, "pitSpeedLimit", value)
        widget = make(name, modern, show_always=True) if name == "pit_lane_helper" else make(name, modern)
        frames(widget)
        assert not is_blank(grab(widget)), f"{value} data"


def test_hidden_preview_follows_lock_signal(field):
    from tinypedal import overlay_signal

    widget = make("pit_lane_helper", True)
    calls = []
    widget.update = lambda: calls.append(True)
    widget.start()
    overlay_signal.locked.emit(True)
    assert calls
    widget.stop()
    overlay_signal.locked.emit(False)  # disconnected: no call on closed widget
    QCoreApplication.processEvents()


def test_registered_everywhere():
    from tinypedal.i18n.fr_overlay import OVERLAY_LABELS
    from tinypedal.i18n.options import load_data
    from tinypedal.template.setting_widget import WIDGET_DEFAULT
    from tinypedal.template.widget.modern import MODERN_DESIGNS
    from tinypedal.ui.quick.overlay_backend import CATEGORY_OTHER, widget_category

    labels = load_data("fr_options.json")
    for name in NEW_WIDGETS:
        assert WIDGET_DEFAULT[name]["enable"] is False
        assert name in MODERN_DESIGNS and name in labels
        assert widget_category(name) != CATEGORY_OTHER
    for label in ("Ahead", "Behind", "Fair share", "Full course yellow", "FL", "Pit box"):
        assert label in OVERLAY_LABELS
