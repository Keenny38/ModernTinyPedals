"""Overlay audit 2026-10-29 (other categories), group J: driver inputs (corner coach, onboard setting, pedal,
steering angle, steering meter, steering wheel, telemetry compare, trailing) & system performance
(findings 54-70, 103, 104)"""

import pytest

from neopedal import calculation as calc
from neopedal.module_info import minfo
from neopedal.widget._modern.base import DASH
from tests.test_overlay_widget_fixes import reader, stat_value, widgets  # noqa: F401  (fixture)
from tests.test_race_aid_widgets import set_reader


def steering(monkeypatch, steer: float, wheel: float, steering_range: float = 540.0):
    """Steering wheel angle (degrees, half of range at full lock) & average front wheel angle"""
    reader(monkeypatch, "inputs", "steering_range_physical", steering_range)
    reader(monkeypatch, "inputs", "steering_raw", steer / (steering_range * 0.5))
    monkeypatch.setattr(minfo.wheels, "averageFrontToeAngle", wheel)


# --- Steering ratio: none near straight ahead, capped, one decimal (finding 62)
def test_steering_ratio_near_straight_ahead():
    assert calc.steering_ratio(1.198, 0.002) == 0.0  # was 599:1
    assert calc.steering_ratio(30.0, 0.1) == 0.0  # wheel angle too small (toe noise)
    assert calc.steering_ratio(1.5, 0.3) == 0.0  # steering angle too small
    assert calc.steering_ratio(-39.0, -3.0) == pytest.approx(13.0)
    assert calc.steering_ratio(39.0, -3.0) == pytest.approx(13.0)  # absolute
    assert calc.steering_ratio(200.0, 0.5) == 99.9
    assert calc.steering_ratio(float("nan"), 3.0) == 0.0


@pytest.mark.parametrize("modern", [True, False])
def test_steering_ratio_text(widgets, monkeypatch, modern):  # noqa: F811
    widget = widgets("steering_angle", modern=modern, show_steering_ratio=True)
    texts = []
    for steer, wheel in ((1.198, 0.002), (39.0, 3.0), (300.0, 2.0)):
        steering(monkeypatch, steer, wheel)
        widget.timerEvent(None)
        texts.append(stat_value(widget, "steering_ratio").text if modern else widget.bar_steer_ratio.text)
    assert texts == [DASH if modern else "-", "13.0:1", "99.9:1"]  # modern: dash as every missing value


# --- Never -0 around center (finding 63)
@pytest.mark.parametrize("modern", [True, False])
def test_steering_angle_never_negative_zero(widgets, monkeypatch, modern):  # noqa: F811
    keys = ("steering_angle", "front_wheel_angle", "ackermann_percentage", "slip_angle_difference", "yaw_rate")
    widget = widgets("steering_angle", modern=modern, **{f"show_{key}": True for key in keys})
    steering(monkeypatch, -0.3, -0.02)
    monkeypatch.setattr(minfo.wheels, "toeAngle", [-0.02, -0.02, 0.0, 0.0])
    monkeypatch.setattr(minfo.wheels, "slipAngleDifference", -0.01)
    monkeypatch.setattr(minfo.wheels, "yawRate", -0.001)
    widget.timerEvent(None)
    if modern:
        texts = [stat_value(widget, key).text for key in keys]
    else:
        texts = [getattr(widget, name).text for name in (
            "bar_steer_angle", "bar_wheel_angle", "bar_ackermann_percentage", "bar_diff_slip_angle", "bar_yaw_rate")]
    assert not any(text.startswith("-0") for text in texts), texts


# --- Pedal reading: highest of raw & filtered in both designs (finding 60)
def test_modern_pedal_reading_highest_of_raw_and_filtered(widgets, monkeypatch):  # noqa: F811
    widget = widgets("pedal", show_readings=True, show_brake=True, show_brake_filtered=True,
                     show_brake_pressure=False)
    reader(monkeypatch, "inputs", "brake_raw", 0.8)
    reader(monkeypatch, "inputs", "brake", 0.5)
    widget.timerEvent(None)
    index = widget.keys.index("brake")
    assert widget.pedal_key("brake", *widget.state[index])[2] == "80"
    reader(monkeypatch, "inputs", "brake_raw", 0.3)
    widget.timerEvent(None)
    assert widget.pedal_key("brake", *widget.state[index])[2] == "50"


# --- Brake pressure scale kept across pit stops, found again for next car (finding 103)
@pytest.mark.parametrize("name, modern", [("pedal", True), ("pedal", False), ("trailing", True), ("trailing", False)])
def test_brake_pressure_peak_kept_across_pit_stops(widgets, monkeypatch, name, modern):  # noqa: F811
    from neopedal import realtime_state

    if name == "pedal":
        options = {"show_brake": True, "show_brake_filtered": True, "show_brake_pressure": True}
    else:
        options = {"show_pedal_bars": True, "show_brake_bar": True, "show_pedal_bar_brake_pressure": True}
    widget = widgets(name, modern=modern, **options)
    pressure = {"value": (1.0, 1.0, 1.0, 1.0)}
    set_reader(monkeypatch, "brake", "pressure", lambda: pressure["value"])
    reader(monkeypatch, "inputs", "brake_raw", 1.0)
    widget.timerEvent(None)
    assert widget.max_brake_pressure == 4.0
    widget.post_update()  # pit stop: updates paused
    pressure["value"] = (0.3, 0.3, 0.3, 0.3)  # first light braking after stop
    widget.timerEvent(None)
    assert widget.brake_pressure_share() == pytest.approx(0.3)  # not 100%
    monkeypatch.setattr(realtime_state, "resets", realtime_state.resets + 1)  # next car or session
    widget.timerEvent(None)
    assert widget.max_brake_pressure == pytest.approx(1.2)


# --- Wheel lock: positive slip on every wheel is no lock (finding 104)
def test_wheel_lock_ignores_positive_slip(monkeypatch):
    from neopedal.widget._pedal_alert import wheel_lock

    monkeypatch.setattr(minfo.wheels, "slipRatio", [0.4, 0.5, 0.6, 0.45])  # spin (or radius not calibrated yet)
    assert wheel_lock() == 0.0  # was 0.4: lock alert while braking with throttle
    monkeypatch.setattr(minfo.wheels, "slipRatio", [-0.35, 0.1, 0.0, -2.0])
    assert wheel_lock() == 1.0
    monkeypatch.setattr(minfo.wheels, "slipRatio", [-0.35, 0.1, 0.0, -0.1])
    assert wheel_lock() == pytest.approx(0.35)


@pytest.mark.parametrize("modern", [True, False])
def test_trailing_wheel_lock_hidden_on_positive_slip(widgets, monkeypatch, modern):  # noqa: F811
    from neopedal.widget.trailing import HIDDEN

    widget = widgets("trailing", modern=modern, show_wheel_lock=True, wheel_lock_threshold=0.3)
    reader(monkeypatch, "inputs", "brake_raw", 0.8)
    monkeypatch.setattr(minfo.wheels, "slipRatio", [0.4, 0.5, 0.6, 0.45])
    values = dict(zip(widget.plot_names, widget.read_inputs()))
    assert values["wheel_lock"] == HIDDEN


# --- Corner coach: reference kept while next one prepared, last apex forgotten on reset (findings 54, 55)
class FakeTrace:
    def __init__(self, path: str):
        self.path, self.stamp, self.length, self.name = path, (1, 1), 1000.0, path


def test_corner_reference_kept_while_new_lap_prepared(monkeypatch):
    import threading

    from neopedal.userfile import corner_coach
    from neopedal.userfile.corner_coach import CoachReference, ReferenceCorners
    from neopedal.userfile.reference_trace import stop_loading

    release = threading.Event()

    def prepare(filepath, trace, folder, coordinates=None, elevations=None):
        if trace.path == "new":
            release.wait(10)
        return CoachReference(trace.path, trace.stamp, trace.length, ())

    monkeypatch.setattr(corner_coach, "prepare_reference", prepare)
    prepared = ReferenceCorners("")
    try:
        old = FakeTrace("old")
        prepared.poll(old, "Track")
        prepared._job.result(timeout=10)
        assert prepared.poll(old, "Track") is True and prepared.reference.path == "old"
        new = FakeTrace("new")  # new record: same track
        assert prepared.poll(new, "Track") is False and prepared.reference.path == "old"  # preparing: old kept
        assert prepared.poll(new, "Track") is False and prepared.reference.path == "old"
        release.set()
        prepared._job.result(timeout=10)
        assert prepared.poll(new, "Track") is True and prepared.reference.path == "new"
        assert prepared.poll(None, "Track") is True and prepared.reference is None  # track changed
    finally:
        release.set()
        stop_loading()


def test_corner_tracker_forgets_last_apex_when_car_moved_elsewhere():
    from neopedal.userfile.corner_coach import CornerTracker
    from tests.test_corner_coach import CORNERS, drive

    tracker = CornerTracker(CORNERS, 1000.0)
    drive(tracker, 0, 320)
    assert tracker.last is not None and tracker.last.label == "T1"
    tracker.update(900.0, 0.0, 0.0)  # garage, reset or restart
    assert tracker.last is None


def test_corner_coach_vehicle_reset_and_new_reference_keep_apex(widgets, monkeypatch):  # noqa: F811
    from neopedal.userfile.corner_coach import CoachReference, CornerResult
    from neopedal.userfile.reference_trace import stop_loading
    from tests.test_corner_coach import CORNERS

    widget = widgets("corner_coach", modern=False)
    try:
        first = CoachReference("a", (1, 1), 1000.0, CORNERS)
        monkeypatch.setattr(widget, "poll_reference", lambda: first)
        widget.read_coach()
        widget.tracker.last = CornerResult("T1", 90.0, 92.0)
        second = CoachReference("b", (1, 1), 1000.0, CORNERS)
        monkeypatch.setattr(widget, "poll_reference", lambda: second)
        widget.read_coach()  # new reference lap (new record): last apex still shown
        assert widget.reference is second and widget.tracker.last is not None
        widget.vehicle_reset()  # next car or session
        assert widget.tracker.last is None and widget.tracker.next == -1
    finally:
        stop_loading()


# --- Corner coach "Now" color, onboard setting colors & captions as classic design (findings 56-58)
def test_modern_corner_coach_now_in_warning_color(widgets):  # noqa: F811
    from neopedal.userfile.reference_trace import stop_loading
    from neopedal.widget.corner_coach import BRAKE_NOW

    widget = widgets("corner_coach")
    try:
        assert widget.brake_color(BRAKE_NOW) == widget.theme.warning
    finally:
        stop_loading()


def test_modern_onboard_setting_colors_and_captions(widgets, monkeypatch):  # noqa: F811
    widget = widgets("onboard_setting", show_abs=True, show_tc=True, caption_text_tc="TCS")
    assert widget.active_colors == {"abs": widget.theme.blue, "tc": widget.theme.warning}
    labels = {slot.stat.key: slot.stat.label for slot in widget.slots}
    assert labels["tc"] == "TCS" and labels["abs"] == "ABS"  # renamed caption shown, design label otherwise
    reader(monkeypatch, "switch", "abs_level", 3)
    reader(monkeypatch, "switch", "abs_active", True)
    widget.timerEvent(None)
    assert stat_value(widget, "abs").color == widget.theme.blue
    bare = widgets("onboard_setting", show_caption=False, layout=0)
    assert all(slot.label.width() == 0 for slot in bare.slots)


# --- Steering meter (classic, rounded style): right turn bar rounded as left one (finding 64)
def test_fill_rect_normalizes_negative_rect(ui_env, monkeypatch):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter

    from neopedal.widget import _painter

    monkeypatch.setattr(_painter.OverlayStyle, "corner_scale", 0.5)
    monkeypatch.setattr(_painter.OverlayStyle, "depth_effects", False)
    images = []
    for rect in (QRectF(10, 10, 40, 20), QRectF(50, 10, -40, 20)):
        image = QImage(60, 40, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        _painter.fill_rect(painter, rect, "#FF0000")
        painter.end()
        images.append(image)
    for image in images:  # both rounded (negative width was a flat fill), same place
        assert QColor.fromRgba(image.pixel(10, 10)).alpha() < 128 and QColor.fromRgba(image.pixel(49, 29)).alpha() < 128
        assert QColor.fromRgba(image.pixel(30, 20)).name() == "#ff0000" and QColor.fromRgba(image.pixel(5, 20)).alpha() == 0


# --- Steering wheel reading decimals (finding 65)
def test_modern_steering_wheel_two_decimals(widgets, monkeypatch):  # noqa: F811
    widget = widgets("steering_wheel", decimal_places=2, show_steering_angle=True, manual_steering_range=540)
    reader(monkeypatch, "inputs", "steering_raw", 12.345 / 270)
    widget.timerEvent(None)
    assert widget.state[0] == pytest.approx(12.35)
    widget = widgets("steering_wheel", decimal_places=0, show_steering_angle=True, manual_steering_range=540)
    widget.timerEvent(None)
    assert widget.state[0] == pytest.approx(12.3)  # rotation still drawn by 0.1 degree


# --- Telemetry comparison delta never -0.00 (finding 66)
def test_telemetry_compare_delta_never_negative_zero(widgets):  # noqa: F811
    from neopedal.userfile.reference_trace import stop_loading

    widget = widgets("telemetry_compare", modern=False, decimal_places=2)
    try:
        assert widget.delta_text(round(-0.004, 2)) == "+0.00"
        assert widget.delta_text(-0.25) == "-0.25"
    finally:
        stop_loading()


# --- Trailing: solid mark line broken where mark hidden, equal display orders (finding 67)
def test_trailing_mark_solid_line_broken(widgets):  # noqa: F811
    from PySide6.QtCore import QPointF

    widget = widgets("trailing", modern=False, show_wheel_lock=True, wheel_lock_line_style=0,
                     display_order_wheel_lock=1, display_order_throttle=1)
    lines, points = [], []

    class Painter:
        def drawLine(self, start, end):
            lines.append((start.x(), end.x()))

        def drawPoint(self, point):
            points.append(point.x())

    margin = widget.margin
    data = (QPointF(0, margin + 5), QPointF(1, margin + 6), QPointF(2, -999.0), QPointF(3, margin), QPointF(4, -50.0))
    widget.draw_mark_line(Painter(), data)
    assert lines == [(0.0, 1.0)] and points == [0.0, 3.0]
    widget.draw_plot_section()  # mark plot drawn as broken line


# --- System performance: CPU starts at first reading, readings never cut (findings 69, 70)
def test_cpu_average_starts_from_first_reading():
    from neopedal.widget.system_performance import CpuAverage, fit_number

    average = CpuAverage(40)
    assert average.update(37.0) == 37.0
    assert 37.0 < average.update(80.0) < 80.0
    assert fit_number(100.0, 4, 2) == " 100" and fit_number(5.5, 4, 2) == "5.50" and fit_number(42.42, 4, 2) == "42.4"
    assert fit_number(1234.5, 5, 1) == " 1234" and fit_number(12.34, 5, 1) == " 12.3"


@pytest.mark.parametrize("modern", [True, False])
def test_system_performance_first_update_shows_cpu(widgets, monkeypatch, modern):  # noqa: F811
    import psutil

    from neopedal.widget import system_performance
    from neopedal.widget._modern import system_performance as modern_performance

    monkeypatch.setattr(psutil, "cpu_percent", lambda *args, **kwargs: 100.0)
    for module in (system_performance, modern_performance):
        monkeypatch.setattr(module, "app_cpu_percent", lambda process, count: 100.0)
    widget = widgets("system_performance", modern=modern, show_system_performance=True, show_neopedal_performance=True)
    widget.timerEvent(None)
    if modern:
        assert [value.text for value in widget.state] == ["100.00%", "100.00%"]
    else:
        assert widget.bar_system.text.startswith(f"{widget.prefix_sys} 100%")
        assert widget.bar_app.text.startswith(f"{widget.prefix_app} 100%")
