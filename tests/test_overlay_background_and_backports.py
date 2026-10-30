"""Overlay background options (GitHub issue #5), modern only options backported to classic layout,
engine power estimate from energy consumption

- background_opacity_percentage & enable_black_background (overlay style): modern panels, defaults keep
  today's colors (alpha 235, slate surfaces).
- Classic layout gets its own options (default off: classic renders unchanged), modern design keeps its own.
- Power estimated without torque: energy rate clamped (refill) & smoothed.
"""

import math

import pytest
from PySide6.QtGui import QColor

from neopedal.module_info import minfo
from neopedal.setting import cfg
from neopedal.template.option_limits import limit_error, option_limit
from neopedal.template.setting_global import GLOBAL_DEFAULT
from neopedal.template.widget.modern import MODERN_ONLY_OPTIONS
from neopedal.widget._modern import design_option_keys
from neopedal.widget._modern.theme import (
    BLACK_SURFACES,
    DEFAULT_BACKGROUND_OPACITY,
    TOKEN_COLORS,
    background_alpha,
    build_theme,
)
from neopedal.widget.engine import ENERGY_RATE_SMOOTHING, smoothed_energy_rate
from tests.test_audit_sweep_fixes import reader, widgets  # noqa: F401

SURFACES = tuple(name for name in TOKEN_COLORS if name.startswith("surface"))
CLASSIC_OPTIONS = {
    "timing": ("show_invalid_lap_highlight",),
    "deltabest": ("show_invalid_lap_highlight",),
    "laps_and_position": ("show_invalid_lap_highlight", "warning_color_invalid_lap"),
    "weather": ("show_wind_speed", "prefix_wind", "font_color_wind", "background_color_wind"),
    "gear": ("show_speed_limiter_pit_reminder",),
}


def style(**options) -> dict:
    return {**GLOBAL_DEFAULT["overlay_style"], **options}


def rgba(theme) -> dict:
    return {name: getattr(theme, name).rgba() for name in TOKEN_COLORS}


# --- Background options
def test_default_background_keeps_todays_panel():
    default = style()
    assert default["background_opacity_percentage"] == DEFAULT_BACKGROUND_OPACITY
    assert default["enable_black_background"] is False
    assert background_alpha(default) == 235
    # Same colors as before the options existed (style without them)
    before = {key: value for key, value in default.items()
              if key not in ("background_opacity_percentage", "enable_black_background")}
    for theme_name in ("Modern Dark", "Modern Light", "Legacy Dark", "Legacy Light"):
        assert rgba(build_theme({**default, "overlay_theme": theme_name})) == rgba(
            build_theme({**before, "overlay_theme": theme_name})), theme_name
    assert build_theme(default).surface.alpha() == 235


@pytest.mark.parametrize("percent, alpha", [(100, 255), (0, 0), (50, 128), (92.5, 236), (150, 255), (-5, 0)])
def test_background_opacity_percent_to_alpha(percent, alpha):
    assert background_alpha(style(background_opacity_percentage=percent)) == alpha
    assert build_theme(style(background_opacity_percentage=percent)).surface.alpha() == alpha


@pytest.mark.parametrize("value", ["90", None, True, math.nan])
def test_invalid_background_opacity_uses_default(value):
    assert background_alpha(style(background_opacity_percentage=value)) == 235


def test_edit_toolbar_keeps_own_alpha():
    assert build_theme(style(background_opacity_percentage=40), surface_alpha=242).surface.alpha() == 242


def test_background_opacity_range_registered():
    limit = option_limit("background_opacity_percentage")
    assert (limit.minimum, limit.maximum) == (0, 100)
    assert limit_error("background_opacity_percentage", 101)
    assert not limit_error("background_opacity_percentage", 92)


def test_black_background_on_dark_themes_only():
    black = build_theme(style(enable_black_background=True, background_opacity_percentage=80))
    for name in SURFACES:
        assert getattr(black, name).name() == QColor(BLACK_SURFACES[name]).name(), name
    assert black.surface.alpha() == 204
    slate = build_theme(style())
    assert {name: getattr(black, name) for name in TOKEN_COLORS if name not in SURFACES} == {
        name: getattr(slate, name) for name in TOKEN_COLORS if name not in SURFACES}  # text & accents kept
    light = style(overlay_theme="Modern Light")
    assert rgba(build_theme({**light, "enable_black_background": True})) == rgba(build_theme(light))


def test_modern_overlays_use_background_options(widgets):  # noqa: F811
    cfg.user.config["overlay_style"].update(background_opacity_percentage=60, enable_black_background=True)
    timing = widgets("timing")
    assert timing.theme.surface.alpha() == 153
    assert timing.theme.surface.name() == "#000000"
    black_box = widgets("black_box")  # classic drawing restyled: panel color from theme surface
    assert black_box.theme.surface.alpha() == 153


def test_background_options_listed_in_settings_page():
    from neopedal.ui.quick.settings_backend import CATEGORIES

    category = next(category for category in CATEGORIES if category.key == "overlay_style")
    keys = [key for _, group in category.groups for key in group]
    assert "background_opacity_percentage" in keys
    assert "enable_black_background" in keys


# --- Classic options of modern only options
def test_classic_options_off_by_default_modern_options_kept():
    cfg.default.set_default()
    for name, keys in CLASSIC_OPTIONS.items():
        setting = cfg.default.setting[name]
        assert setting[keys[0]] is False, name
        for key, value in MODERN_ONLY_OPTIONS[name].items():
            assert setting[key] == value, (name, key)  # modern design defaults unchanged


@pytest.mark.parametrize("name", sorted(CLASSIC_OPTIONS))
def test_options_page_shows_each_design_its_options(ui_env, name):
    keys = list(cfg.user.setting[name])
    cfg.user.config["overlay_style"]["overlay_theme"] = "Legacy Dark"
    classic = design_option_keys(cfg, name, keys)
    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
    modern = design_option_keys(cfg, name, keys)
    for key in CLASSIC_OPTIONS[name]:
        assert key in classic and key not in modern, key
    for key in MODERN_ONLY_OPTIONS[name]:
        assert key in modern and key not in classic, key


def image(widget):
    widget.adjustSize()
    return widget.grab().toImage()


@pytest.mark.parametrize("name", ["timing", "deltabest", "laps_and_position"])
def test_classic_invalid_lap_ignored_by_default(widgets, monkeypatch, name):  # noqa: F811
    widget = widgets(name, modern=False)
    widget.timerEvent(None)
    valid = image(widget)
    reader(monkeypatch, "lap", "invalidated", True)
    widget.timerEvent(None)
    assert image(widget) == valid


def test_classic_timing_current_lap_in_invalid_color(widgets, monkeypatch):  # noqa: F811
    widget = widgets("timing", modern=False, show_invalid_lap_highlight=True)
    monkeypatch.setattr(minfo.delta, "lapTimeCurrent", 42.0)
    widget.timerEvent(None)
    assert widget.bar_curr.fg == widget.wcfg["font_color_current"]
    reader(monkeypatch, "lap", "invalidated", True)
    widget.timerEvent(None)
    assert widget.bar_curr.fg == widget.wcfg["font_color_invalid_last"]
    assert widget.bar_curr.text.endswith("42.000")


def test_classic_deltabest_outlined_while_invalid(widgets, monkeypatch):  # noqa: F811
    widget = widgets("deltabest", modern=False, show_invalid_lap_highlight=True)
    widget.timerEvent(None)
    valid = image(widget)
    reader(monkeypatch, "lap", "invalidated", True)
    widget.timerEvent(None)
    assert widget.invalid
    invalid = image(widget)
    assert invalid != valid
    center = widget.rect_delta.center().toPoint()
    assert invalid.pixelColor(center) == valid.pixelColor(center)  # outline only, text area kept


def test_classic_laps_background_while_invalid(widgets, monkeypatch):  # noqa: F811
    widget = widgets("laps_and_position", modern=False, show_invalid_lap_highlight=True)
    reader(monkeypatch, "lap", "completed_laps", 3)
    reader(monkeypatch, "lap", "maximum", 20)
    widget.timerEvent(None)
    assert widget.bar_laps.bg == widget.wcfg["background_color_laps"]
    reader(monkeypatch, "lap", "invalidated", True)
    widget.timerEvent(None)
    assert widget.bar_laps.bg == widget.wcfg["warning_color_invalid_lap"]
    reader(monkeypatch, "lap", "completed_laps", 19)  # last lap: invalid lap shown first
    widget.timerEvent(None)
    assert widget.bar_laps.bg == widget.wcfg["warning_color_invalid_lap"]
    reader(monkeypatch, "lap", "invalidated", False)
    widget.timerEvent(None)
    assert widget.bar_laps.bg == widget.wcfg["warning_color_maximum_laps"]


def test_classic_weather_wind(widgets, monkeypatch):  # noqa: F811
    default = widgets("weather", modern=False)
    default_size = default.sizeHint()
    widget = widgets("weather", modern=False, show_wind_speed=True)
    assert widget.sizeHint().width() > default_size.width()
    assert not hasattr(default, "bar_wind")
    reader(monkeypatch, "session", "wind_velocity", (0.05, 0.0, 0.05))  # calm: no direction
    widget.timerEvent(None)
    assert widget.bar_wind.text == f"Wind -  0{widget.symbol_speed}"
    reader(monkeypatch, "session", "wind_velocity", (6.0, 0.0, 8.0))
    widget.timerEvent(None)
    speed = f"{widget.unit_speed(10.0):>3.0f}"
    assert widget.bar_wind.text[:len("Wind ")] == "Wind "
    assert widget.bar_wind.text[len("Wind ") + 1:] == f"{speed}{widget.symbol_speed}"


def test_wind_arrow_matches_modern_angle(widgets, monkeypatch):  # noqa: F811
    from neopedal.widget.weather import WIND_ARROWS

    classic = widgets("weather", modern=False, show_wind_speed=True)
    modern = widgets("weather")
    reader(monkeypatch, "vehicle", "orientation_yaw_radians", 0.4)
    for wind in ((3.0, 0.0, 0.0), (0.0, 0.0, 3.0), (-3.0, 0.0, 0.0), (0.0, 0.0, -3.0), (2.0, 0.0, 2.5)):
        reader(monkeypatch, "session", "wind_velocity", wind)
        _, angle = modern.wind()
        classic.timerEvent(None)
        assert angle is not None
        assert WIND_ARROWS[round(angle / 90) % 4] in classic.bar_wind.text, wind


def pit_lane_without_limiter(monkeypatch):
    reader(monkeypatch, "switch", "speed_limiter", False)
    reader(monkeypatch, "switch", "speed_limiter_available", True)
    reader(monkeypatch, "vehicle", "in_pits", True)
    reader(monkeypatch, "vehicle", "speed", 15.0)


def test_classic_gear_limiter_reminder(widgets, monkeypatch):  # noqa: F811
    pit_lane_without_limiter(monkeypatch)
    default = widgets("gear", modern=False)
    default.timerEvent(None)
    assert default.bar_limiter.isHidden()
    widget = widgets("gear", modern=False, show_speed_limiter_pit_reminder=True)
    widget.timerEvent(None)
    assert not widget.bar_limiter.isHidden()
    wcfg = widget.wcfg
    assert (widget.bar_limiter.fg, widget.bar_limiter.bg) == (
        wcfg["background_color_speed_limiter"], wcfg["font_color_speed_limiter"])
    reader(monkeypatch, "switch", "speed_limiter", True)  # limiter switched on: usual colors
    widget.timerEvent(None)
    assert (widget.bar_limiter.fg, widget.bar_limiter.bg) == (
        wcfg["font_color_speed_limiter"], wcfg["background_color_speed_limiter"])
    reader(monkeypatch, "switch", "speed_limiter", False)
    reader(monkeypatch, "vehicle", "in_pits", False)
    widget.timerEvent(None)
    assert widget.bar_limiter.isHidden()


@pytest.mark.parametrize("name, bars", [
    ("engine", ("bar_oil", "bar_water")),
    ("engine_temperature", ("bar_oil_temp", "bar_water_temp")),
])
def test_classic_game_overheating_warning(widgets, monkeypatch, name, bars):  # noqa: F811
    reader(monkeypatch, "engine", "oil_temperature", 90.0)
    reader(monkeypatch, "engine", "water_temperature", 85.0)
    reader(monkeypatch, "engine", "overheating", True)
    widget = widgets(name, modern=False)  # same option as modern design, on by default
    widget.timerEvent(None)
    off = widgets(name, modern=False, show_game_overheating_warning=False)
    off.timerEvent(None)
    for bar in bars:
        assert getattr(off, bar).bg != widget.wcfg["warning_color_overheat"]
        assert getattr(widget, bar).bg == widget.wcfg["warning_color_overheat"]
    reader(monkeypatch, "engine", "overheating", False)
    widget.timerEvent(None)
    assert getattr(widget, bars[0]).bg != widget.wcfg["warning_color_overheat"]


# --- Engine power estimate without torque
def test_smoothed_energy_rate_clamped_and_smoothed():
    assert smoothed_energy_rate(0.0, -3.0) == 0.0  # refill: no consumption
    assert smoothed_energy_rate(1.0, -3.0) == pytest.approx(1.0 - ENERGY_RATE_SMOOTHING)
    assert smoothed_energy_rate(0.0, 2.0) == pytest.approx(2.0 * ENERGY_RATE_SMOOTHING)
    ema = 0.0
    for _ in range(100):
        ema = smoothed_energy_rate(ema, 2.0)
    assert ema == pytest.approx(2.0)


@pytest.mark.parametrize("modern", [True, False])
def test_power_estimate_never_negative(widgets, monkeypatch, modern):  # noqa: F811
    widget = widgets("engine", modern=modern)
    reader(monkeypatch, "engine", "torque", 0.0)
    reader(monkeypatch, "engine", "rpm", 6000.0)
    reader(monkeypatch, "engine", "max_virtual_energy", 100_000.0)  # power kW = rate
    monkeypatch.setattr(minfo.energy, "rateOfConsumption", -50.0)
    widget.timerEvent(None)
    assert widget.ema_energy_rate == 0.0
    monkeypatch.setattr(minfo.energy, "rateOfConsumption", 300.0)
    widget.timerEvent(None)
    assert widget.ema_energy_rate == pytest.approx(300.0 * ENERGY_RATE_SMOOTHING)  # one sample: smoothed
    if not modern:
        assert widget.bar_power.text == " 60.00kW"  # 300 x ENERGY_RATE_SMOOTHING
    widget.post_update()
    assert widget.ema_energy_rate == 0.0
