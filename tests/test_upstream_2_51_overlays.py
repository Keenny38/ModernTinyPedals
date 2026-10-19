"""TinyPedal 2.51 features: Wheel dimension & Wind direction overlays, engine off ignition, default heatmaps,
wind speed unit"""

from importlib import import_module
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal.api_control import api
from neopedal.module_info import minfo
from neopedal.setting import cfg
from neopedal.widget._modern import create_widget


@pytest.fixture
def make(ui_env, bundled_fonts):
    """Overlay of modern or classic design"""
    created = []

    def build(name: str, modern: bool, **options):
        cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
        cfg.user.setting[name].update(options)
        widget = create_widget(import_module(f"neopedal.widget.{name}"), cfg, name)
        created.append(widget)
        return widget

    yield build
    for widget in created:
        widget.deleteLater()
    QCoreApplication.processEvents()


# --- Wheel dimension
def test_radius_text():
    from neopedal.widget.wheel_dimension import radius_text

    assert radius_text(338.4) == "338mm"
    assert radius_text(0.0) == radius_text(-1.0) == "n/a"  # not measured yet
    assert radius_text(float("nan")) == radius_text(float("inf")) == "n/a"  # invalid reading


@pytest.mark.parametrize("modern", [True, False], ids=["modern", "classic"])
def test_wheel_dimension_shows_measured_radius(make, monkeypatch, modern):
    monkeypatch.setattr(minfo.wheels, "wheelRadiusFront", 337.6)
    monkeypatch.setattr(minfo.wheels, "wheelRadiusRear", 0.0)
    widget = make("wheel_dimension", modern, display_order_front_tyre_radius=2, display_order_rear_tyre_radius=1)
    widget.timerEvent(None)
    if modern:
        assert [value.text for value in widget.state] == ["n/a", "338mm"]  # display order: rear first
    else:
        assert [bar.text for bar, _ in widget.bars_radius] == ["338mm", "n/a"]
    assert widget.grab().width() > 0


@pytest.mark.parametrize("modern", [True, False], ids=["modern", "classic"])
def test_wheel_dimension_hidden_axle(make, modern):
    widget = make("wheel_dimension", modern, show_front_tyre_radius=False)
    widget.timerEvent(None)
    count = len(widget.state) if modern else len(widget.bars_radius)
    assert count == 1


# --- Wind direction
def test_compass_marks():
    from neopedal.widget.wind_direction import compass_marks

    minor, major, north = compass_marks(40.0, 2.0, (0.9, 0.8, 0.7))
    assert len(minor) == 8 and len(major) == 3  # every 30 degrees between cardinals, east south west
    assert north.y1() == pytest.approx(-38.0) and north.y2() == pytest.approx(-38.0 * 0.7)
    assert major[0].x1() == pytest.approx(38.0) and major[0].y1() == pytest.approx(0.0, abs=1e-9)  # east


@pytest.fixture
def wind(ui_env, monkeypatch):
    """Wind blowing toward world x, car heading set by yaw"""
    state = {"wind": (5.0, 0.0, 0.0), "yaw": 0.0}
    monkeypatch.setattr(api.read.session, "wind_velocity", lambda *args: state["wind"])
    monkeypatch.setattr(api.read.vehicle, "orientation_yaw_radians", lambda *args: state["yaw"])
    return state


@pytest.mark.parametrize("modern", [True, False], ids=["modern", "classic"])
def test_wind_direction_arrow_strength_and_calm(make, wind, modern):
    widget = make("wind_direction", modern)
    widget.timerEvent(None)
    state = widget.state if modern else widget.wind_state
    _, text, angle, level = state
    assert text == "5.0m/s" if not modern else text == "5.0 m/s"
    assert angle is not None
    assert level == 2  # light wind (2 to 6 m/s)
    assert widget.grab().width() > 0
    wind["wind"] = (0.05, 0.0, 0.0)  # below calm threshold: dot, no direction
    widget.timerEvent(None)
    state = widget.state if modern else widget.wind_state
    assert state[2] is None and state[3] == 1
    assert widget.grab().width() > 0


def test_wind_strength_levels(make, wind):
    widget = make("wind_direction", False)
    assert [widget.strength_level(speed) for speed in (0.5, 2.0, 7.0, 12.0, 20.0, 30.0)] == [1, 2, 3, 4, 5, 6]
    widget = make("wind_direction", False, show_wind_strength_color=False)
    widget.timerEvent(None)
    assert widget.wind_state[3] == 0  # arrow color


def test_wind_speed_unit(make, wind, monkeypatch):
    monkeypatch.setitem(cfg.user.setting["units"], "wind_speed_unit", "KPH")
    widget = make("wind_direction", False, decimal_places=0)
    widget.timerEvent(None)
    assert widget.wind_state[1] == "18km/h"
    weather = make("weather", True, show_wind=True)
    assert weather.symbol_speed == "km/h"  # weather wind reading in wind speed unit too


def test_wind_angle_relative_to_car(wind):
    from neopedal.widget.weather import wind_reading

    speed, angle = wind_reading(0.1)
    assert speed == pytest.approx(5.0) and angle is not None
    wind["yaw"] = 3.14159265 / 2  # car turned a quarter: wind turns the other way relative to car
    _, turned = wind_reading(0.1)
    assert abs((turned - angle + 180) % 360 - 180) == pytest.approx(90.0, abs=0.1)
    assert wind_reading(10.0)[1] is None  # calm threshold


# --- Instrument: ignition states
@pytest.mark.parametrize("starter, rpm, expected", [(0, 0, 0), (1, 50, 1), (1, 3000, 2), (2, 50, 1), (2, 3000, 2)])
def test_read_ignition_with_starter_cranking(ui_env, monkeypatch, starter, rpm, expected):
    from neopedal.widget.instrument import InstrumentMixin

    monkeypatch.setattr(api.read.switch, "ignition_starter", lambda *args: starter)
    monkeypatch.setattr(api.read.engine, "rpm", lambda *args: rpm)
    widget = SimpleNamespace(wcfg={"stalling_rpm_threshold": 100})
    assert InstrumentMixin.read_ignition(widget) == expected  # game value 2 (starter) never read as 4


@pytest.mark.parametrize("modern", [True, False], ids=["modern", "classic"])
def test_engine_off_ignition_color(make, monkeypatch, modern):
    monkeypatch.setattr(api.read.switch, "ignition_starter", lambda *args: 0)
    widget = make("instrument", modern, warning_color_engine_off="#CC0000")
    widget.timerEvent(None)
    if modern:
        light = widget.state[widget.keys.index("ignition")]
        assert light.fill == widget.theme.negative and not light.lit
    else:
        assert widget.bar_ignition.bg == widget.color_ignition[0]
        assert widget.color_ignition[0] != widget.color_ignition[2]


# --- Heatmaps & units
def test_default_heatmaps():
    from neopedal.template.setting_compounds import COMPOUNDINFO_DEFAULT
    from neopedal.template.setting_heatmap import HEATMAP_DEFAULT, HEATMAP_DEFAULT_BRAKE, HEATMAP_DEFAULT_TYRE

    assert (HEATMAP_DEFAULT_TYRE, HEATMAP_DEFAULT_BRAKE) == ("tyre_optimal_80", "brake_optimal_400")
    assert HEATMAP_DEFAULT_TYRE in HEATMAP_DEFAULT and HEATMAP_DEFAULT_BRAKE in HEATMAP_DEFAULT
    assert HEATMAP_DEFAULT["thermal_infrared"]["80"] == "#F48"  # colors of former tyre_default
    assert COMPOUNDINFO_DEFAULT["heatmap"] == HEATMAP_DEFAULT_TYRE


def test_user_heatmaps_kept_by_validator():
    from neopedal.setting_validator import StyleValidator

    user = {"tyre_default": {"-273": "#44F", "80": "#F48"}}
    StyleValidator.heatmap(user)
    assert "tyre_default" in user and "thermal_infrared" in user  # former default kept, new ones added
    assert list(user)[-1] == "tyre_default"  # user heatmaps after defaults


def test_wind_speed_unit_choices():
    from neopedal.regex_pattern import CHOICE_UNITS
    from neopedal.template.setting_common import COMMON_DEFAULT
    from neopedal.ui.setup_wizard import UNIT_SYSTEMS

    assert COMMON_DEFAULT["units"]["wind_speed_unit"] == "m/s"
    assert CHOICE_UNITS["wind_speed_unit"] == ("m/s", "KPH", "MPH")
    assert UNIT_SYSTEMS["Imperial"]["wind_speed_unit"] == "MPH"
