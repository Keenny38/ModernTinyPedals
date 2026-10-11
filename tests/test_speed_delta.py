"""Speed delta overlay: speed difference to reference laps at same lap distance (delta module laps)"""

from importlib import import_module

import pytest
from PySide6.QtCore import QTimerEvent

from neopedal import calculation as calc
from neopedal.const_common import MAX_SECONDS


def lap(speed_of):
    """Recorded lap points (distance, lap time) every 5 m, speed_of(distance) m/s"""
    points = [(0.0, 0.0)]
    elapsed = 0.0
    for distance in range(5, 2001, 5):
        elapsed += 5 / speed_of(distance)
        points.append((float(distance), elapsed))
    return tuple(points)


def test_reference_speed_of_recorded_lap():
    steady = lap(lambda distance: 50.0)
    assert calc.reference_speed(steady, 1000.0) == pytest.approx(50.0)
    assert calc.reference_speed(steady, 2.0) == pytest.approx(50.0)  # lap start: points after only
    braking = lap(lambda distance: 80.0 if distance < 1000 else 30.0)
    assert calc.reference_speed(braking, 500.0) == pytest.approx(80.0)
    assert calc.reference_speed(braking, 1500.0) == pytest.approx(30.0)
    assert 30.0 < calc.reference_speed(braking, 1000.0) < 80.0  # around the change: between
    assert calc.reference_speed(steady, 2500.0) == 0.0  # outside lap
    assert calc.reference_speed(((0.0, 0.0), (10.0, 0.0)), 5.0) == 0.0  # no lap recorded


def test_speed_delta_positive_when_faster():
    steady = lap(lambda distance: 50.0)
    assert calc.speed_delta(steady, 1000.0, 52.0) == pytest.approx(2.0)
    assert calc.speed_delta(steady, 1000.0, 47.5) == pytest.approx(-2.5)
    assert calc.speed_delta((), 1000.0, 47.5) == 0.0  # no reference lap


@pytest.fixture
def delta_data(ui_env, monkeypatch):
    """Delta module output: reference laps recorded, current lap comparable, speed differences (m/s)"""
    from neopedal.module_info import minfo

    delta = minfo.delta
    values = {
        "isDeltaAvailable": True, "hasLastLap": True, "lapTimeBest": 100.0, "lapTimeSession": 100.5,
        "lapTimeStint": 101.0, "speedDeltaBest": 1.0, "speedDeltaSession": -2.0, "speedDeltaStint": 0.004,
        "speedDeltaLast": 0.5,
    }
    for name, value in values.items():
        monkeypatch.setattr(delta, name, value)
    return delta


def make(name: str, modern: bool, **options):
    from neopedal.setting import cfg
    from neopedal.widget._modern import create_widget

    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
    cfg.units["speed_unit"] = "KPH"
    cfg.user.setting[name].update(options)
    return create_widget(import_module(f"neopedal.widget.{name}"), cfg, name)


def test_modern_speed_delta_colors_and_dash(delta_data, bundled_fonts, monkeypatch):
    from neopedal.widget._modern.base import DASH

    widget = make("speed_delta", True)
    try:
        widget.timerEvent(QTimerEvent(0))
        theme = widget.theme
        best, session, stint, last = widget.state
        assert best.text == "+3.6" and best.color == theme.positive  # 1 m/s faster: 3.6 km/h
        assert session.text == "-7.2" and session.color == theme.negative
        assert stint.text == "+0.0" and stint.color == theme.text  # steady
        assert last.sub == "km/h"
        monkeypatch.setattr(delta_data, "lapTimeStint", MAX_SECONDS)  # no stint best lap yet
        monkeypatch.setattr(delta_data, "hasLastLap", False)  # last lap was an out lap
        widget.timerEvent(QTimerEvent(0))
        assert widget.state[2].text == widget.state[3].text == DASH
        monkeypatch.setattr(delta_data, "isDeltaAvailable", False)  # out lap: nothing compared
        widget.timerEvent(QTimerEvent(0))
        assert all(value.text == DASH for value in widget.state)
    finally:
        widget.deleteLater()


def test_classic_speed_delta_texts(delta_data, bundled_fonts):
    widget = make("speed_delta", False, show_session_best=False, show_speed_unit=True)
    try:
        widget.timerEvent(QTimerEvent(0))
        texts = {key: bar.text for key, bar in widget.bars.items()}
        assert set(texts) == {"all_time_best", "stint_best", "last_lap"}  # session hidden
        assert texts["all_time_best"].startswith("B ") and texts["all_time_best"].endswith("+3.6 km/h")
        assert texts["last_lap"].endswith("+1.8 km/h")
    finally:
        widget.deleteLater()


@pytest.mark.parametrize("modern", [True, False])
def test_speed_delta_smoothing_option(delta_data, bundled_fonts, monkeypatch, modern):
    """Speed difference eased toward new value (smoothing option), none with 1, smoothing restarted once shown"""

    def best(widget) -> float:
        widget.timerEvent(QTimerEvent(0))
        return widget.speeds.smoothed["all_time_best"]

    smooth = make("speed_delta", modern, speed_delta_smoothing_samples=10)
    raw = make("speed_delta", modern, speed_delta_smoothing_samples=1)
    try:
        assert best(smooth) == best(raw) == pytest.approx(3.6)  # first reading taken as is
        monkeypatch.setattr(delta_data, "speedDeltaBest", 3.0)  # +10.8 km/h
        assert best(raw) == pytest.approx(10.8)  # no smoothing
        eased = best(smooth)
        assert 3.6 < eased < 10.8  # part of the way
        assert best(smooth) > eased  # keeps moving toward new value
        monkeypatch.setattr(delta_data, "isDeltaAvailable", False)  # out lap: nothing shown
        assert best(smooth) is None
        monkeypatch.setattr(delta_data, "isDeltaAvailable", True)
        assert best(smooth) == pytest.approx(10.8)  # shown again: no easing from old value
    finally:
        smooth.deleteLater()
        raw.deleteLater()


def test_overlay_listed_with_both_designs():
    from neopedal.template.setting_widget import WIDGET_DEFAULT
    from neopedal.template.widget import WIDGET_DISPLAY_ORDER
    from neopedal.template.widget.modern import MODERN_DESIGNS

    assert "speed_delta" in WIDGET_DISPLAY_ORDER and "speed_delta" in MODERN_DESIGNS
    assert WIDGET_DEFAULT["speed_delta"]["enable"] is False
