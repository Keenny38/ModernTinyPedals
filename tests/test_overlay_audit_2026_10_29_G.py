"""Overlay audit 2026-10-29, group G (Chassis): acceleration, damage, damage stats, differential, force, rake angle,
ride height, roll angle, suspension force, position & travel, weight distribution, force & wheels modules
(findings 1-18, 99, 100)"""

import math

import pytest

from neopedal.const_common import TEXT_NA, TEXT_PLACEHOLDER
from neopedal.module import module_force
from neopedal.module_info import ForceInfo, minfo
from neopedal.widget._modern.base import DASH
from tests import test_race_aid_widgets
from tests.test_module_timing import tele  # noqa: F401  (fixture)
from tests.test_race_aid_widgets import make, set_reader

field = test_race_aid_widgets.field  # fixture: default setting, fake reader, field of 20 cars


def update(widget, count: int = 1):
    for _ in range(count):
        widget.timerEvent(None)


def texts(widget) -> list[str]:
    """Modern stats texts"""
    return [value.text for value in widget.state]


# --- Force: downforce not provided by game (LMU: always 0) shown n/a (finding 8)
def test_force_module_downforce_missing_while_moving(tele):  # noqa: F811
    output = ForceInfo()
    gen = module_force.calc_force(output, g_accel=9.8, max_g_diff=0.2, max_avg_g_samples=5,
                                  max_g_reset_delay=5, max_avg_g_reset_delay=30, max_braking_rate_reset_delay=60)
    tele.update({"timing.elapsed": 10.0, "vehicle.downforce_front": 0.0, "vehicle.downforce_rear": 0.0,
                 "vehicle.speed": 5.0})
    gen.send(0)
    assert output.downForceFront == 0.0 and output.downForceRatio == 0.0  # standing still: real 0
    tele["vehicle.speed"] = 40.0
    gen.send(0)
    assert math.isnan(output.downForceFront) and math.isnan(output.downForceRear)
    assert math.isnan(output.downForceRatio)
    tele["vehicle.speed"] = 0.0
    gen.send(0)
    assert math.isnan(output.downForceFront)  # known missing, even when stopped
    gen.send(1)  # vehicle reset: checked again
    assert output.downForceFront == 0.0
    # Game giving downforce (rF2): never missing
    tele.update({"vehicle.downforce_front": 3000.0, "vehicle.downforce_rear": 1000.0, "vehicle.speed": 60.0})
    gen.send(1)
    assert output.downForceFront == 3000.0 and output.downForceRatio == pytest.approx(0.75)


@pytest.mark.parametrize("modern", [True, False])
def test_force_overlay_downforce_na(field, monkeypatch, modern):
    for name in ("downForceFront", "downForceRear", "downForceRatio"):
        monkeypatch.setattr(minfo.force, name, math.nan)
    widget = make("force", modern, show_downforce_ratio=True, show_front_downforce=True, show_rear_downforce=True)
    update(widget, 2)
    if modern:
        shown = [texts(widget)[widget.keys.index(key)] for key in ("downforce_ratio", "front_downforce", "rear_downforce")]
        assert shown == [DASH] * 3  # modern: dash as every missing value
    else:
        assert widget.bar_df_ratio.text == TEXT_NA
        assert widget.bar_df_front.text == widget.bar_df_rear.text == TEXT_NA
    monkeypatch.setattr(minfo.force, "downForceFront", 3150.0)
    monkeypatch.setattr(minfo.force, "downForceRear", 3880.0)
    monkeypatch.setattr(minfo.force, "downForceRatio", 0.448)
    update(widget)
    if modern:
        assert texts(widget)[widget.keys.index("front_downforce")] == "3150"
        assert texts(widget)[widget.keys.index("downforce_ratio")] == "44.80%"
    else:
        assert widget.bar_df_front.text == "F 3150" and widget.bar_df_ratio.text == "44.80%"
    widget.deleteLater()


# --- Ride height (modern): axle ride height from wheels when game gives none (finding 13)
def test_modern_axle_ride_height_falls_back_to_wheels(field, monkeypatch):
    set_reader(monkeypatch, "wheel", "ride_height", (40.0, 42.0, 60.0, 64.0))
    set_reader(monkeypatch, "vehicle", "ride_height_front", 0.0)
    set_reader(monkeypatch, "vehicle", "ride_height_rear", 0.0)
    widget = make("ride_height", True, show_axle_ride_height=True, decimal_places=0)
    update(widget)
    assert widget.state[1] == ("41", "62")
    set_reader(monkeypatch, "vehicle", "ride_height_front", 52.0)  # game value (rF2) kept
    set_reader(monkeypatch, "vehicle", "ride_height_rear", 71.0)
    update(widget)
    assert widget.state[1] == ("52", "71")
    widget.deleteLater()


# --- Damage: light impacts & LMU empty impact updates not shown by impact cone (finding 3)
@pytest.mark.parametrize("modern", [True, False])
def test_damage_impact_cone_ignores_light_and_empty_impacts(field, monkeypatch, modern):
    impact = {"time": 0.0, "magnitude": 0.0, "position": (0.0, 0.0)}
    set_reader(monkeypatch, "vehicle", "impact_time", lambda *args: impact["time"])
    set_reader(monkeypatch, "vehicle", "impact_magnitude", lambda *args: impact["magnitude"])
    set_reader(monkeypatch, "vehicle", "impact_position", lambda *args: impact["position"])
    set_reader(monkeypatch, "timing", "elapsed", 300.0)
    widget = make("damage", modern, show_last_impact_cone=True)

    def cone_shown() -> bool:
        update(widget)
        return widget.impact_visible if modern else not widget.last_impact_expired

    assert not cone_shown()
    impact.update(time=299.0, magnitude=0.0, position=(-0.0, 0.0))  # LMU empty update
    assert not cone_shown()
    impact.update(time=299.5, magnitude=40.0, position=(0.6, -2.7))  # kerb, scraping
    assert not cone_shown()
    impact.update(time=299.8, magnitude=2500.0, position=(-0.4, 2.7))  # real impact
    assert cone_shown()
    angle = widget.impact_position if modern else widget.impact_cone_start
    impact.update(time=299.9, magnitude=0.0, position=(0.0, 0.0))  # empty update: cone kept toward impact
    assert cone_shown()
    assert (widget.impact_position if modern else widget.impact_cone_start) == angle
    widget.vehicle_reset()  # previous car or session impact hidden
    assert not cone_shown()
    widget.deleteLater()


# --- Acceleration: speed range from 0, delta dash before comparison, never -0.00 (findings 1, 2, 99)
def test_acceleration_speed_range_label_starts_at_zero():
    from neopedal import units
    from neopedal.widget.acceleration import AccelTimer, speed_range_text

    kph = units.set_unit_speed("KPH")
    assert speed_range_text(AccelTimer(0.6, 16.55555, 5), kph) == "0-60"
    assert speed_range_text(AccelTimer(0.6, 26.8224, 5), units.set_unit_speed("MPH")) == "0-60"
    assert speed_range_text(AccelTimer(27.77777, 41.66666, 5), kph) == "100-150"


@pytest.mark.parametrize("modern", [True, False])
def test_acceleration_delta_text(field, monkeypatch, modern):
    set_reader(monkeypatch, "engine", "gear", 1)
    set_reader(monkeypatch, "vehicle", "speed", 0.0)
    widget = make("acceleration", modern, decimal_places_delta=2)
    timer = widget.timers[0]

    def delta_shown(delta: float) -> tuple:
        timer.delta = delta
        update(widget)
        if modern:
            return widget.state[0][3:]  # text, sign
        bar = widget.bars_timer_delta[0]
        return bar.text, widget.delta_color.index(bar.fg)  # 0 gain, 1 loss, 2 neutral

    assert delta_shown(0.0)[0] in (TEXT_PLACEHOLDER, DASH)  # no comparison yet: dash in both designs
    assert delta_shown(-0.001) == ("+0.00", 0 if modern else 2)  # neutral, not gain colored -0.00
    assert delta_shown(-0.25) == ("-0.25", -1 if modern else 0)  # gain
    assert delta_shown(0.25) == ("+0.25", 1)  # loss
    widget.deleteLater()


# --- Damage stats: flat tyre shown 0% (finding 6)
@pytest.mark.parametrize("modern", [True, False])
def test_damage_stats_flat_tyre_integrity_zero(field, monkeypatch, modern):
    set_reader(monkeypatch, "tyre", "wear", (0.95, 0.96, 0.97, 0.98))
    set_reader(monkeypatch, "tyre", "flat", (False, True, False, False))
    set_reader(monkeypatch, "tyre", "puncture", (False,) * 4)
    widget = make("damage_stats", modern, show_tyre_integrity=True, decimal_places=0)

    def tyre_text() -> str:
        update(widget)
        return texts(widget)[widget.keys.index("tyre")] if modern else widget.bar_tyre.text

    assert tyre_text() == "0%"
    set_reader(monkeypatch, "tyre", "flat", (False,) * 4)
    assert tyre_text() == "95%"
    widget.deleteLater()


# --- Differential: minimum locking restarts from current value, no 100% flash (finding 7)
def test_diff_locking_timer_reset_without_full_lock_flash():
    from neopedal.widget.differential import DiffLockingTimer

    timer = DiffLockingTimer(5)
    assert timer.update(0.4, 0.0) == 0.4
    assert timer.update(0.6, 3.0) == 0.4
    assert timer.update(0.6, 6.0) == 0.6  # cooldown over: current locking, never 1.0
    assert timer.update(0.6, 6.1) == 0.6
    assert timer.update(0.5, 7.0) == 0.5


# --- Rake angle: decimals 0, ride height difference not cut, no -0.00, repaint on text change (11, 12, 99, 100)
def test_rake_angle_classic_format(field, monkeypatch):
    widget = make("rake_angle", False, decimal_places=0, show_ride_height_difference=True, show_degree_sign=False,
                  prefix_rake_angle="")
    assert widget.format_rake(52.0) == "+1(52)"
    assert widget.format_rake(105.0).endswith("(105)")
    widget.deleteLater()
    widget = make("rake_angle", False, decimal_places=2, show_ride_height_difference=False, show_degree_sign=False,
                  prefix_rake_angle="", rake_angle_smoothing_samples=1)
    set_reader(monkeypatch, "wheel", "ride_height", (50.0, 50.0, 49.99, 49.99))
    update(widget)
    assert widget.bar_rake.text == "+0.00" and widget.bar_rake.bg == widget.bar_style_rake[0]
    repaints = []
    monkeypatch.setattr(widget.bar_rake, "update", lambda: repaints.append(1))
    set_reader(monkeypatch, "wheel", "ride_height", (50.0, 50.0, 49.995, 49.995))
    update(widget)
    assert not repaints  # same text: not repainted
    widget.deleteLater()


def test_rake_angle_modern_no_negative_zero(field, monkeypatch):
    set_reader(monkeypatch, "wheel", "ride_height", (50.0, 50.0, 49.99, 49.99))
    widget = make("rake_angle", True, decimal_places=2, show_degree_sign=False, rake_angle_smoothing_samples=1)
    update(widget)
    assert widget.state[0].text == "+0.00" and widget.state[0].color is None
    widget.deleteLater()


# --- Roll angle: same decimals both designs, no -0 (findings 14, 99, 100)
@pytest.mark.parametrize("modern", [True, False])
def test_roll_angle_decimals_and_ratio(field, monkeypatch, modern):
    set_reader(monkeypatch, "wheel", "ride_height", (50.0, 50.001, 60.0, 60.001))
    widget = make("roll_angle", modern, decimal_places=0, show_roll_angle_ratio=True,
                  show_degree_and_percentage_sign=False, roll_angle_smoothing_samples=1,
                  roll_angle_ratio_smoothing_samples=1, prefix_roll_angle_front="", prefix_roll_angle_rear="",
                  prefix_roll_angle_difference="", prefix_roll_angle_ratio="")
    update(widget)
    if modern:
        shown = dict(zip(widget.keys, texts(widget)))
        front, ratio = shown["front"], shown["ratio"]
    else:
        front, ratio = widget.bar_rollf.text.strip(), widget.bar_ratio.text.strip()
    assert front == "+0" and ratio == "50"
    widget.deleteLater()


def test_roll_ratio_classic_full_ratio_fits():
    from types import SimpleNamespace

    from neopedal.widget.roll_angle import Realtime

    owner = SimpleNamespace(decimals=1, percent_sign_text="%")
    assert Realtime.format_ratio(owner, 100.0, "") == "100%"
    assert Realtime.format_ratio(owner, 52.34, "") == "52.3%"


# --- Suspension force: same gauge scale both designs, full at 50% (finding 15)
@pytest.mark.parametrize("modern", [True, False])
def test_suspension_force_gauge_scale(field, monkeypatch, modern):
    set_reader(monkeypatch, "wheel", "suspension_force", (3000.0, 3000.0, 3000.0, 3000.0))
    widget = make("suspension_force", modern, show_force_ratio=True)
    update(widget)
    if modern:
        assert [tile.level for tile in widget.state] == [0.5] * 4
    else:
        bar = widget.bars_force[0]
        assert bar.display_range == 50 and bar.last == 25.0
        assert bar.rect_input.width() == pytest.approx(bar.rect_bg.width() / 2)
    widget.deleteLater()


# --- Suspension position (modern): maximum position range line (finding 16)
def test_modern_suspension_maximum_range(field, monkeypatch):
    monkeypatch.setattr(minfo.wheels, "currentSuspensionPosition", [20.0, 20.0, 20.0, 60.0])
    monkeypatch.setattr(minfo.wheels, "maxSuspensionPosition", [50.0, 50.0, -5.0, 50.0])
    widget = make("suspension_position", True, show_maximum_position_range=True, position_maximum_range=100)
    update(widget)
    tiles, maximums = widget.state
    assert maximums == (0.5, 0.5, 0.0, 0.5)  # negative (packers): none
    assert tiles[3].colors[0] == widget.theme.negative  # beyond maximum
    assert not widget.grab().isNull()  # line drawn
    widget.deleteLater()


# --- Suspension travel: values fit 4 characters, never -0.00 (finding 99)
def test_suspension_travel_text():
    from neopedal.widget.suspension_travel import travel_text

    assert travel_text(-0.004) == "0.00"
    assert travel_text(-0.04) == "0.0"
    assert travel_text(-1.26) == "-1.3"
    assert travel_text(12.345) == "12.3"
    assert travel_text(0.85) == "0.85"
    assert travel_text(-123.4) == "-123"


# --- Wheels module: suspension travel outputs cleared on reset (finding 17)
def test_suspension_travel_cleared_on_vehicle_reset(ui_env, monkeypatch):
    from neopedal import realtime_state
    from neopedal.module.module_wheels import calc_suspension_travel
    from neopedal.module_info import WheelsInfo

    monkeypatch.setattr(realtime_state, "active", True)
    output = WheelsInfo()
    gen = calc_suspension_travel(output, 20, 1.0, 0.0, True)
    set_reader(monkeypatch, "wheel", "suspension_deflection", (30.0,) * 4)
    set_reader(monkeypatch, "tyre", "vertical_deflection", (5.0,) * 4)
    set_reader(monkeypatch, "wheel", "position_vertical", (0.1,) * 4)
    set_reader(monkeypatch, "wheel", "suspension_force", (3000.0,) * 4)
    set_reader(monkeypatch, "wheel", "offroad", False)
    set_reader(monkeypatch, "vehicle", "speed", 30.0)
    set_reader(monkeypatch, "vehicle", "impact_time", 0.0)
    set_reader(monkeypatch, "inputs", "throttle_raw", 1.0)
    set_reader(monkeypatch, "timing", "elapsed", 100.0)
    gen.send(0)
    assert output.maxSuspensionPosition[0] == 30.0
    output.staticSuspensionPosition[:] = (25.0,) * 4
    output.motionRatio[:] = (0.8,) * 4
    set_reader(monkeypatch, "vehicle", "speed", 0.0)  # stopped: travel not recorded this tick
    gen.send(1)  # previous car values cleared
    assert list(output.maxSuspensionPosition) == list(output.minSuspensionPosition) == [0.0] * 4
    assert list(output.motionRatio) == [0.0] * 4
    assert list(output.staticSuspensionPosition) == [30.0] * 4  # stationary: recorded again


# --- Weight distribution, ride height (classic): repainted on visible change only (finding 100)
def test_weight_distribution_repaints_on_text_change(field, monkeypatch):
    monkeypatch.setattr(minfo.wheels, "frontWeightRatio", 0.5)
    widget = make("weight_distribution", False, show_front_to_rear_distribution=True, smoothing_samples=1)
    update(widget)
    repaints = []
    monkeypatch.setattr(widget.bar_distf, "update", lambda: repaints.append(1))
    monkeypatch.setattr(minfo.wheels, "frontWeightRatio", 0.500001)
    update(widget)
    assert not repaints
    monkeypatch.setattr(minfo.wheels, "frontWeightRatio", 0.52)
    update(widget)
    assert repaints
    widget.deleteLater()


def test_ride_height_classic_repaints_on_visible_change(field, monkeypatch):
    set_reader(monkeypatch, "wheel", "ride_height", (40.0, 40.0, 60.0, 60.0))
    widget = make("ride_height", False, decimal_places=0)
    update(widget)
    bar = widget.bars_rideh[0]
    repaints = []
    monkeypatch.setattr(bar, "update", lambda: repaints.append(1))
    set_reader(monkeypatch, "wheel", "ride_height", (40.001, 40.0, 60.0, 60.0))
    update(widget)
    assert not repaints and isinstance(bar.last, float)
    widget.deleteLater()


# --- Demo data: downforce ratio as fraction, as module output (finding 9)
def test_demo_downforce_ratio_fraction():
    from pathlib import Path

    from neopedal import demo_data

    assert "force.downForceRatio = 0.448" in Path(demo_data.__file__).read_text(encoding="utf-8")
