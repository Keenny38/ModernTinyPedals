"""Overlay audit 2026-10-29, group I: gear, lift and coast LED, speedometer, brake bias, brake performance,
brake pressure, brake temperature & brake wear (numbers of the audit report)"""

import pytest

from neopedal import realtime_state
from neopedal.module.module_wheels import calc_brake_wear
from neopedal.module_info import WheelsInfo, minfo
from neopedal.widget import _data
from neopedal.widget._modern.base import DASH
from tests.test_module_wheels_wear import tele  # noqa: F401  (fixture)
from tests.test_overlay_widget_fixes import reader, widgets  # noqa: F401  (fixture)


def brake_wheels(monkeypatch, current, maximum, failure=0.0):
    for name, value in (("currentBrakeThickness", current), ("maxBrakeThickness", maximum),
                        ("failureBrakeThickness", failure), ("estimatedValidBrakeWear", 0.0)):
        monkeypatch.setattr(minfo.wheels, name, [value] * 4)


# --- 52: brake wear not failed before any game data (start of session, rF2, spectated car)
def test_brake_wear_data_unavailable_not_failed():
    wheels = WheelsInfo()  # no data received: thickness 0
    data = _data.brake_wear_data(wheels, 0, True, 100.0)
    assert not data.available and not data.failed
    wheels.maxBrakeThickness = [30.0] * 4  # data received, brake at 0: failed
    data = _data.brake_wear_data(wheels, 0, True, 100.0)
    assert data.available and data.failed


@pytest.mark.parametrize("modern", [True, False])
def test_brake_wear_shows_unavailable_without_data(widgets, monkeypatch, modern):  # noqa: F811
    brake_wheels(monkeypatch, 0.0, 0.0)
    widget = widgets("brake_wear", modern=modern, show_remaining=True, show_lifespan_laps=True)
    widget.timerEvent(None)
    if modern:
        assert all(tile.texts == (DASH,) for tiles in widget.state for tile in tiles)
    else:
        assert [bar.text for bar in widget.bars_remain + widget.bars_laps] == ["n/a"] * 8
    brake_wheels(monkeypatch, 20.0, 30.0)  # data: shown
    widget.timerEvent(None)
    if modern:
        assert widget.state[widget.keys.index("remaining")][0].texts == ("66.6",)
    else:
        assert widget.bars_remain[0].text == "66.6"
    brake_wheels(monkeypatch, 0.0, 0.0)  # spectated car: unavailable again
    widget.timerEvent(None)
    if modern:
        assert widget.state[widget.keys.index("remaining")][0].texts == (DASH,)
    else:
        assert widget.bars_remain[0].text == "n/a" and widget.bars_laps[0].text == "n/a"
    widget.grab()


def test_brake_wear_module_unavailable_for_spectated_car(tele):  # noqa: F811
    output = WheelsInfo()
    gen = calc_brake_wear(output, min_delta_distance=50)
    tele.update({"timing.start": 0.0, "timing.current_laptime": 5.0, "lap.distance": 100.0,
                 "brake.wear": (0.03,) * 4})
    gen.send(0)
    assert output.maxBrakeThickness[0] == pytest.approx(30.0)
    tele["brake.wear"] = (-1.0,) * 4  # spectated car: REST gives player car only
    gen.send(0)
    assert output.maxBrakeThickness == [0.0] * 4 and output.currentBrakeThickness == [0.0] * 4
    tele["brake.wear"] = (0.029,) * 4  # back on player car (no vehicle reset): max kept
    gen.send(0)
    assert output.maxBrakeThickness[0] == pytest.approx(30.0)
    assert output.currentBrakeThickness[0] == pytest.approx(29.0)


# --- 53: classic brake wear shows failure even with nothing left before
def test_classic_brake_wear_failure_shown_when_nothing_left(widgets, monkeypatch):  # noqa: F811
    brake_wheels(monkeypatch, 4.0, 30.0, failure=5.0)  # worn past failure thickness: 0 left
    widget = widgets("brake_wear", modern=False, show_remaining=True)
    widget.timerEvent(None)
    assert widget.bars_remain[0].text == "0.00"
    brake_wheels(monkeypatch, 0.0, 30.0, failure=5.0)  # brake failed: still 0 left
    widget.timerEvent(None)
    assert widget.bars_remain[0].text == "FAIL"


# --- 41, 42: lift and coast LED double vertical sets side by side, same direction (as classic & docs)
@pytest.mark.parametrize("orientation", [1, 3])
def test_modern_lift_and_coast_double_vertical_side_by_side(widgets, orientation):  # noqa: F811
    widget = widgets("lift_and_coast_led", display_orientation=orientation, enable_double_side_led=True,
                     double_side_led_gap=50, number_of_led=4, led_width=20, led_height=10, inner_gap=2)
    first, second = widget.leds[:4], widget.leds[4:]
    assert all(a.y() == b.y() for a, b in zip(first, second))  # same direction, same rows
    assert all(b.x() - a.x() == 70 for a, b in zip(first, second))  # led width + horizontal gap
    if orientation == 1:  # bottom to top
        assert first[0].y() > first[-1].y()
    else:
        assert first[0].y() < first[-1].y()
    assert widget.width() > 90 and widget.height() < 60


def test_modern_lift_and_coast_double_horizontal_mirrored(widgets):  # noqa: F811
    widget = widgets("lift_and_coast_led", display_orientation=0, enable_double_side_led=True,
                     number_of_led=4, led_width=20, led_height=10, inner_gap=2)
    first, second = widget.leds[:4], widget.leds[4:]
    assert first[0].x() < first[-1].x() and second[0].x() > second[-1].x()  # filled towards each other
    assert all(rect.y() == first[0].y() for rect in widget.leds)


def test_modern_lift_and_coast_at_least_3_leds(widgets):  # noqa: F811
    assert widgets("lift_and_coast_led", number_of_led=1).count == 3


def follow_other_car(monkeypatch):
    """Followed car changed (realtime_state.resets): overlays run vehicle_reset before next update"""
    monkeypatch.setattr(realtime_state, "resets", realtime_state.resets + 1)


# --- 40: classic gear gauge repainted only when gear, speed shown or color change
def test_classic_gear_gauge_keyed_on_shown_values(widgets, monkeypatch):  # noqa: F811
    widget = widgets("gear", modern=False, show_rpm_flickering_above_critical=False)
    reader(monkeypatch, "engine", "gear", 3)
    reader(monkeypatch, "engine", "rpm_max", 8000.0)
    reader(monkeypatch, "engine", "rpm", 3000.0)
    reader(monkeypatch, "vehicle", "speed", 30.0)
    widget.timerEvent(None)
    calls = []
    gauge = widget.bar_gauge
    original = gauge.update_input
    monkeypatch.setattr(gauge, "update_input", lambda *args: (calls.append(args), original(*args)))
    reader(monkeypatch, "engine", "rpm", 3010.0)  # same color
    reader(monkeypatch, "vehicle", "speed", 30.001)  # same speed shown
    widget.timerEvent(None)
    assert not calls
    reader(monkeypatch, "vehicle", "speed", 31.0)
    widget.timerEvent(None)
    assert len(calls) == 1 and calls[0][1] == round(widget.unit_speed(31.0))


# --- 43, 102: speedometer dash before first reading, speeds of previous car not kept
def test_modern_speedometer_dash_before_reading_and_reset_on_car_change(widgets, monkeypatch):  # noqa: F811
    widget = widgets("speedometer", show_speed_minimum=True, show_speed_maximum=True, show_speed_fastest=True,
                     off_throttle_threshold=0.2, on_throttle_threshold=0.8)
    keys = widget.keys
    reader(monkeypatch, "timing", "elapsed", 1.0)
    reader(monkeypatch, "inputs", "throttle_raw", 0.5)  # neither off nor on throttle
    reader(monkeypatch, "vehicle", "speed", 80.0)
    reader(monkeypatch, "engine", "gear", 5)
    widget.timerEvent(None)
    texts = {key: value.text for key, value in zip(keys, widget.state)}
    assert texts["speed_minimum"] == DASH and texts["speed_maximum"] == DASH
    assert texts["speed_fastest"] != DASH
    reader(monkeypatch, "vehicle", "speed", 30.0)
    follow_other_car(monkeypatch)
    widget.timerEvent(None)
    texts = {key: value.text for key, value in zip(keys, widget.state)}
    assert texts["speed_fastest"] == texts["speed"]  # top speed of previous car not kept


def test_classic_speedometer_reset_on_car_change(widgets, monkeypatch):  # noqa: F811
    widget = widgets("speedometer", modern=False, show_speed_maximum=True, show_speed_fastest=True,
                     off_throttle_threshold=0.2, on_throttle_threshold=0.8)
    reader(monkeypatch, "timing", "elapsed", 1.0)
    reader(monkeypatch, "inputs", "throttle_raw", 1.0)
    reader(monkeypatch, "vehicle", "speed", 80.0)
    reader(monkeypatch, "engine", "gear", 5)
    widget.timerEvent(None)
    fast = widget.bar_speed_fast.text
    reader(monkeypatch, "inputs", "throttle_raw", 0.5)
    reader(monkeypatch, "vehicle", "speed", 30.0)
    follow_other_car(monkeypatch)
    widget.timerEvent(None)
    assert widget.bar_speed_fast.text != fast and widget.speed_fast == 30.0
    assert widget.bar_speed_max.text == "MAX"  # caption until first reading of followed car


# --- 47, 48, 102: brake bias
def test_classic_brake_migration_without_decimals(widgets, monkeypatch):  # noqa: F811
    widget = widgets("brake_bias", modern=False, show_brake_migration=True, decimal_places_brake_migration=0)
    reader(monkeypatch, "brake", "migration", 1.5)
    widget.timerEvent(None)
    assert widget.bar_bmigt.text == f"{widget.wcfg['prefix_brake_migration']}2F"


def test_modern_brake_migration_suffix_option(widgets, monkeypatch):  # noqa: F811
    widget = widgets("brake_bias", show_brake_migration=True, suffix_brake_migration="AV")
    reader(monkeypatch, "brake", "migration", 1.5)
    widget.timerEvent(None)
    assert widget.state[widget.keys.index("migration")].text == "1.5AV"
    assert "suffix_brake_migration" in widget.options


@pytest.mark.parametrize("modern", [True, False])
def test_brake_bias_baseline_reset_on_car_change(widgets, monkeypatch, modern):  # noqa: F811
    widget = widgets("brake_bias", modern=modern, show_baseline_bias_delta=True, decimal_places_baseline_bias_delta=2)
    reader(monkeypatch, "vehicle", "in_pits", False)
    reader(monkeypatch, "vehicle", "speed", 50.0)
    reader(monkeypatch, "brake", "bias_front", 0.56)
    widget.timerEvent(None)  # baseline of first car
    reader(monkeypatch, "brake", "bias_front", 0.52)  # followed car with another bias
    follow_other_car(monkeypatch)
    widget.timerEvent(None)
    text = widget.state[widget.keys.index("delta")].text if modern else widget.bar_delta.text
    assert text.endswith("+0.00")  # not -4.00 against previous car


# --- 49: brake performance delta colored as shown
def test_modern_brake_performance_delta_neutral_when_shown_zero(widgets, monkeypatch):  # noqa: F811
    widget = widgets("brake_performance", show_delta_braking_rate=True, show_delta_braking_rate_in_percentage=False)
    monkeypatch.setattr(minfo.force, "maxBrakingRate", 2.0)
    monkeypatch.setattr(minfo.force, "deltaBrakingRate", -0.001)
    widget.timerEvent(None)
    value = widget.state[widget.keys.index("delta_braking_rate")]
    assert value.text == "+0.00" and value.color == widget.theme.text_dim


# --- 50: classic brake pressure input mark follows pedal at a held pressure (pit auto-hold)
def test_classic_brake_pressure_input_mark_at_held_pressure(widgets, monkeypatch):  # noqa: F811
    widget = widgets("brake_pressure", modern=False, show_brake_input=True)
    reader(monkeypatch, "brake", "pressure", (49.0,) * 4)
    reader(monkeypatch, "brake", "bias_front", 0.5)
    reader(monkeypatch, "inputs", "brake_raw", 0.8)
    widget.timerEvent(None)
    mark = widget.bars_bpres[0].rect_max.width()
    reader(monkeypatch, "inputs", "brake_raw", 0.0)  # pedal released, pressure held
    widget.timerEvent(None)
    assert widget.bars_bpres[0].rect_max.width() != mark


# --- 51: classic brake temperature cell fits 4 digits in Celsius
def test_classic_brake_temperature_fits_1000_celsius(widgets):  # noqa: F811
    from PySide6.QtGui import QFontMetrics

    widget = widgets("brake_temperature", modern=False, show_degree_sign=True)
    assert widget.bars_btemp[0].width() >= QFontMetrics(widget.font()).horizontalAdvance("1000°")


# --- 102: brake temperature average of previous car not kept
@pytest.mark.parametrize("modern", [True, False])
def test_brake_temperature_average_reset_on_car_change(widgets, monkeypatch, modern):  # noqa: F811
    widget = widgets("brake_temperature", modern=modern, show_average=True)
    reader(monkeypatch, "timing", "elapsed", 10.0)
    reader(monkeypatch, "inputs", "brake_raw", 1.0)
    reader(monkeypatch, "brake", "temperature", (600.0,) * 4)
    widget.timerEvent(None)
    reader(monkeypatch, "timing", "elapsed", 10.1)
    reader(monkeypatch, "inputs", "brake_raw", 0.0)
    reader(monkeypatch, "brake", "temperature", (300.0,) * 4)
    follow_other_car(monkeypatch)
    widget.timerEvent(None)  # just off brake: average restarts from followed car reading
    if modern:
        assert widget.averages == [300.0] * 4
    else:
        assert widget.bars_btavg[0].last == 300.0
