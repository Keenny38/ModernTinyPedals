"""Overlay widget regressions: wrong values, options without effect, sizing, caches

Widgets are built on default settings (ui_env) with a neutral API reader, then single
readers and data module outputs are set to the case under test.
"""

from collections import deque
from importlib import import_module

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QColor

from tinypedal import i18n
from tinypedal.api_control import api
from tinypedal.module_info import ConsumptionDataSet, minfo
from tinypedal.setting import cfg
from tinypedal.widget._modern import create_widget
from tinypedal.widget._modern.base import DASH


@pytest.fixture
def widgets(ui_env, bundled_fonts):
    """Build widgets by name (modern design unless modern=False), deleted after test"""
    created = []

    def make(name: str, modern: bool = True, **options):
        cfg.user.config["overlay_style"]["enable_modern_style"] = modern
        cfg.user.setting[name].update(options)
        widget = create_widget(import_module(f"tinypedal.widget.{name}"), cfg, name)
        created.append(widget)
        return widget

    yield make
    for widget in created:
        widget.deleteLater()
    QCoreApplication.processEvents()


def reader(monkeypatch, group: str, name: str, value):
    """Neutral API reader returns value"""
    monkeypatch.setattr(getattr(api.read, group), name, lambda *args, **kwargs: value)


def stat_value(widget, key: str):
    return widget.state[widget.keys.index(key)]


# --- Race plan: stop of the lap just completed still shown in the pits
def test_race_plan_shows_current_stop_while_in_pits(widgets, monkeypatch):
    from tinypedal.fuel_strategy import PitStop, Strategy

    widget = widgets("race_plan", show_next_stop=True, show_refuel=True)
    monkeypatch.setattr(widget, "refresh_plan", lambda: None)
    widget.strategy = Strategy(
        race_laps=30, stints=[10, 10, 10],
        stops=[PitStop(10, 55.0, 80.0, True), PitStop(20, 30.0, 50.0, False)],
    )
    reader(monkeypatch, "lap", "completed_laps", 10)
    reader(monkeypatch, "vehicle", "in_pits", True)
    widget.timerEvent(None)
    assert stat_value(widget, "next_stop").text == "L10 (0)"
    assert stat_value(widget, "refuel").text.startswith("+55.0")
    reader(monkeypatch, "vehicle", "in_pits", False)
    widget.timerEvent(None)
    assert stat_value(widget, "next_stop").text == "L20 (10)"
    assert stat_value(widget, "refuel").text.startswith("+30.0")


# --- Deltabest extended (classic): deltalast row follows its own option
@pytest.mark.parametrize("deltalast, stint", [(False, True), (True, False)])
def test_deltabest_extended_deltalast_option(widgets, monkeypatch, deltalast, stint):
    widget = widgets("deltabest_extended", modern=False, show_deltalast=deltalast, show_stint_deltabest=stint)
    monkeypatch.setattr(minfo.delta, "lapTimeCurrent", 100.0)
    monkeypatch.setattr(minfo.delta, "deltaLast", 0.5)
    widget.timerEvent(None)  # deltalast off & stint on: AttributeError before
    if deltalast:
        assert "0.50" in widget.bar_labest.text  # stayed --.--- with stint off before


# --- Modern heatmaps follow heatmap edits & preset switch (widgets created again on reload)
@pytest.mark.parametrize("name", ["tyre_temperature", "brake_temperature"])
def test_modern_heatmap_reloaded_with_widget(widgets, name):
    first = widgets(name)
    heat_name = first.wcfg["heatmap_name"]
    cfg.user.heatmap[heat_name] = {"0.0": "#123456", "500.0": "#654321"}
    second = widgets(name)
    steps = second.compounds.heat[0] if name == "tyre_temperature" else second.heat[0]
    assert [color.name() for _, color in steps] == ["#123456", "#654321"]


# --- Overlay scale: whole widget scales, character counts are not pixels
@pytest.mark.parametrize("name, modern", [
    ("radar", True), ("radar", False), ("pedal", True), ("pedal", False), ("deltabest", True),
    ("damage", False), ("traffic", False), ("virtual_energy", False),
])
def test_overlay_scale_scales_whole_widget(widgets, name, modern):
    sizes = []
    for scale in (1.0, 2.0):
        cfg.user.config["overlay_style"]["overlay_scale"] = scale
        widget = widgets(name, modern=modern)
        widget.adjustSize()
        sizes.append((widget.width(), widget.height()))
    (width, height), (width2, height2) = sizes
    assert 1.6 < width2 / width < 2.4, sizes
    assert 1.6 < height2 / height < 2.4, sizes


def test_resize_handle_scales_radar_and_keeps_character_widths():
    from tinypedal.template.setting_widget import WIDGET_DEFAULT
    from tinypedal.widget._edit_frame import scale_widget_setting
    from tinypedal.widget._style import scale_overrides

    radar = dict(WIDGET_DEFAULT["radar"])
    assert scale_widget_setting(radar, 1.5, "radar") == {"global_scale": 9}
    for name in ("traffic", "virtual_energy"):
        assert "bar_width" not in scale_overrides(dict(WIDGET_DEFAULT[name]), 2.0, name)
    pedal = scale_overrides(dict(WIDGET_DEFAULT["pedal"]), 2.0, "pedal")
    assert {"bar_length", "bar_width_unfiltered", "bar_width_filtered"} <= set(pedal)
    assert "delta_bar_length" in scale_overrides(dict(WIDGET_DEFAULT["deltabest"]), 2.0, "deltabest")
    assert "parts_maximum_width" in scale_overrides(dict(WIDGET_DEFAULT["damage"]), 2.0, "damage")


# --- Track clock: midday & midnight phases named as such
def test_track_clock_names_every_sunlight_phase(widgets, monkeypatch):
    from tinypedal.module.module_mapping import set_sunlight_phase

    widget = widgets("track_clock", show_sunlight_phase_countdown=True)
    monkeypatch.setattr(minfo.mapping, "sunlightPhases", set_sunlight_phase("06:00", "18:00"))
    reader(monkeypatch, "session", "track_time", 8 * 3600.0)
    widget.timerEvent(None)
    countdown = stat_value(widget, "countdown")
    assert countdown.sub == "MIDDAY" and countdown.text == "-4:00:00"
    reader(monkeypatch, "session", "track_time", 20 * 3600.0)
    widget.timerEvent(None)
    assert stat_value(widget, "countdown").sub == "MIDNIGHT"


# --- Peak values found again for next car
def test_modern_engine_and_pedal_reset_peaks(widgets, monkeypatch):
    engine = widgets("engine")
    engine.max_power_kw = 513.0
    engine.post_update()
    assert engine.max_power_kw == 0.0 and engine.ema_power == 0.0
    pedal = widgets("pedal", show_brake=True, show_brake_filtered=True, show_brake_pressure=True)
    reader(monkeypatch, "brake", "pressure", (0.2, 0.2, 0.2, 0.2))
    reader(monkeypatch, "inputs", "brake_raw", 1.0)
    pedal.timerEvent(None)
    assert pedal.state[pedal.keys.index("brake")][0] == 1.0  # full pedal, was 80% of a 1.0 start peak
    pedal.post_update()
    assert pedal.max_brake_pressure == 0.01


# --- Temperature differences in Fahrenheit: scaled, no 32 offset (classic)
def test_classic_rate_of_change_in_fahrenheit(widgets):
    cfg.units["temperature_unit"] = "Fahrenheit"
    carcass = widgets("tyre_carcass", modern=False, show_rate_of_change=True)
    carcass.update_rdiff(carcass.bars_rdiff[0], 0.001)
    assert carcass.bars_rdiff[0].text == "0.0"  # steady, was 32
    carcass.update_rdiff(carcass.bars_rdiff[1], 5.0)
    assert carcass.bars_rdiff[1].text == "9.0"
    engine = widgets("engine_temperature", modern=False, show_rate_of_change=True, show_net_change_per_lap=True)
    engine.update_rate(engine.bar_oil_rate, 5.0)
    assert engine.bar_oil_rate.text == "9.0"
    engine.update_net(engine.bar_oil_net, 95.0, 90.0)
    assert engine.bar_oil_net.text == "9.0"


# --- Rate of change starts from first reading, not from 0 degree
@pytest.mark.parametrize("modern", [True, False])
def test_rate_of_change_has_no_start_spike(widgets, monkeypatch, modern):
    reader(monkeypatch, "engine", "oil_temperature", 90.0)
    reader(monkeypatch, "engine", "water_temperature", 80.0)
    reader(monkeypatch, "tyre", "carcass_temperature", (85.0, 85.0, 85.0, 85.0))
    engine = widgets("engine_temperature", modern=modern, show_rate_of_change=True, show_net_change_per_lap=False)
    carcass = widgets("tyre_carcass", modern=modern, show_rate_of_change=True)
    for elapsed in (10.0, 11.0):
        reader(monkeypatch, "timing", "elapsed", elapsed)
        engine.timerEvent(None)
        carcass.timerEvent(None)
    if modern:
        assert engine.rates == {"oil": 0.0, "water": 0.0}
        assert stat_value(engine, "oil").sub == "0.0"  # steady: no arrow
        assert carcass.rates == [0.0] * 4
        tiles, _ = carcass.state
        assert tiles[0].sub == "0.0" and tiles[0].sub_color is None
    else:
        assert engine.bar_oil_rate.last == 0
        assert all(bar.last == 0 for bar in carcass.bars_rdiff)


def test_modern_carcass_heating_and_cooling_colors(widgets, monkeypatch):
    carcass = widgets("tyre_carcass", show_rate_of_change=True)
    for elapsed, temps in ((10.0, (85.0,) * 4), (11.0, (95.0, 75.0, 85.0, 85.0))):
        reader(monkeypatch, "timing", "elapsed", elapsed)
        reader(monkeypatch, "tyre", "carcass_temperature", temps)
        carcass.timerEvent(None)
    tiles, _ = carcass.state
    assert tiles[0].sub.startswith("▲") and tiles[0].sub_color == carcass.theme.orange
    assert tiles[1].sub.startswith("▼") and tiles[1].sub_color == carcass.theme.lap_behind
    carcass.grab()  # colored rate drawn on chip over heat colored tile


# --- Brake wear lifespan never negative after brake failure, DRS starts not available
@pytest.mark.parametrize("modern", [True, False])
def test_brake_wear_lifespan_clamped(widgets, monkeypatch, modern):
    for name, value in (("currentBrakeThickness", 5.0), ("failureBrakeThickness", 10.0),
                        ("maxBrakeThickness", 30.0), ("estimatedValidBrakeWear", 1.0)):
        monkeypatch.setattr(minfo.wheels, name, [value] * 4)
    widget = widgets("brake_wear", modern=modern, show_lifespan_laps=True, show_thickness=True)
    widget.timerEvent(None)
    if modern:
        tiles = widget.state[widget.keys.index("lifespan_laps")]
        assert [tile.texts[0] for tile in tiles] == ["0.00"] * 4  # was -5
    else:
        assert [bar.text for bar in widget.bars_laps] == ["0.00"] * 4


def test_classic_drs_starts_not_available(widgets):
    widget = widgets("drs", modern=False)
    widget.adjustSize()
    color = widget.grab().toImage().pixelColor(1, 1)
    assert color.name() == QColor(widget.wcfg["background_color_not_available"]).name()


# --- Options modern design reads are shown & stored
def test_modern_driver_list_options_shown():
    from tinypedal.template.setting_widget import WIDGET_DEFAULT
    from tinypedal.widget._modern import modern_module

    assert "show_vehicle_in_garage" in modern_module("relative").Realtime.options
    for name, keys in (
        ("standings", ("show_lap_difference",)),
        ("rivals", ("show_player_highlighted", "show_lap_difference", "show_highlighted_fastest_last_laptime")),
    ):
        options = modern_module(name).Realtime.options
        for key in keys:
            assert key in WIDGET_DEFAULT[name] and key in options


def test_restyled_options_keep_switches_named_color():
    from tinypedal.widget._modern import modern_module

    options = modern_module("track_map").Realtime.options
    assert "show_custom_player_color_in_multi_class" in options
    # Colors set by design hidden, other colors stay customizable
    assert "background_color" not in options and "background_color_map" not in options
    assert "start_line_color" in options and "map_outline_color" in options
    assert not any(key.endswith(("font_name", "font_weight")) for key in options)


def test_unused_stop_go_penalty_option_dropped_from_presets():
    from tinypedal.setting_validator import PresetValidator
    from tinypedal.template.setting_widget import WIDGET_DEFAULT

    default = WIDGET_DEFAULT["pit_stop_estimate"]
    assert "stop_go_penalty_time" not in default
    user = {**default, "stop_go_penalty_time": 20}  # saved by older version
    PresetValidator.validate_key_pair(user, default)
    assert "stop_go_penalty_time" not in user


# --- Downforce keeps its sign: lift highlighted
def test_modern_force_shows_lift(widgets, monkeypatch):
    widget = widgets("force", show_front_downforce=True, show_rear_downforce=True)
    monkeypatch.setattr(minfo.force, "downForceFront", -1234.4)
    monkeypatch.setattr(minfo.force, "downForceRear", 2345.6)
    widget.timerEvent(None)
    front = stat_value(widget, "front_downforce")
    assert front.text == "-1234" and front.color == widget.theme.negative
    assert stat_value(widget, "rear_downforce").text == "2346"


# --- Lap time history: no delta for oldest lap, recent laps drawn in static layer
def test_lap_time_history_oldest_delta_and_static_rows(widgets, monkeypatch):
    widget = widgets("lap_time_history", show_delta=True, show_empty_history=False)
    laps = deque([ConsumptionDataSet(lapNumber=2, isValidLap=1, lapTimeLast=89.3),
                  ConsumptionDataSet(lapNumber=1, isValidLap=1, lapTimeLast=89.9)])
    monkeypatch.setattr(minfo.history, "consumptionDataSet", laps)
    monkeypatch.setattr(minfo.history, "consumptionDataVersion", 5)
    widget.timerEvent(None)
    column = [column.key for column in widget.table.columns].index("delta")
    newest, oldest = widget.history_rows
    assert newest.cells[column].text == "-0.60"
    assert oldest.cells[column].text == DASH  # was +89.90 against empty placeholder lap
    _current, version = widget.state  # current lap repainted each update, history only in background
    assert version == widget.history_version == 1
    widget.grab()
    widget.timerEvent(None)
    assert widget.history_version == 1 and widget._static_layer is not None  # unchanged: kept


# --- Damage colors from theme (Colorblind Safe recolors green & red)
def test_modern_damage_colors_follow_theme(widgets):
    cfg.user.config["overlay_style"]["overlay_theme"] = "Colorblind Safe"
    widget = widgets("damage")
    assert widget.wcfg["damage_panel_suspension_color"] == widget.theme.positive
    assert widget.theme.positive.name().upper() != "#2FB36A"
    widget.timerEvent(None)
    widget.grab()


# --- Gear: battery bar only for hybrid car
def test_modern_gear_battery_bar_only_with_motor(widgets, monkeypatch):
    widget = widgets("gear", show_battery_bar=True)
    monkeypatch.setattr(minfo.hybrid, "motorState", 0)
    widget.timerEvent(None)
    height = widget.height()
    assert widget.rect_battery.isNull()
    monkeypatch.setattr(minfo.hybrid, "motorState", 1)
    widget.timerEvent(None)
    assert not widget.rect_battery.isNull() and widget.height() > height
    widget.grab()


# --- Overlay labels translated
def test_overlay_labels_translated():
    from tinypedal.widget._modern.drivers import pit_time_text
    from tinypedal.widget._modern.rows import pit_cell
    from tinypedal.widget._modern.theme import build_theme

    theme = build_theme(cfg.default.config["overlay_style"])
    i18n.set_language("Français")
    try:
        assert pit_cell(theme, 1, False, False).text == "STAND"
        assert pit_time_text(1, 123.4) == "STAND 123.4"
        assert i18n.tr_overlay("FAIL") == "HS" and i18n.tr_overlay("now") == "act."
    finally:
        i18n.set_language("English")
    assert pit_cell(theme, 1, False, False).text == "PIT"


# --- Caches: text layouts least recently used, shared colors
def test_text_cache_keeps_recently_drawn(widgets, monkeypatch):
    from tinypedal.widget._modern import base

    widget = widgets("session")
    widget._text_cache.clear()
    monkeypatch.setattr(base, "TEXT_CACHE_SIZE", 3)
    for text in ("a", "b", "c", "a", "d"):
        widget.static_text("value", text)
    assert ("value", "a") in widget._text_cache  # drawn again: kept
    assert ("value", "b") not in widget._text_cache


def test_shared_colors_cached():
    from tinypedal.widget._modern.draw import fraction, readable_on
    from tinypedal.widget._modern.theme import build_theme

    theme = build_theme(cfg.default.config["overlay_style"])
    assert readable_on(QColor("#FFFFFF")) is readable_on(QColor("#FFFFFF"))
    assert theme.tint(theme.accent, 50) is theme.tint(theme.accent, 50)
    assert theme.tint(theme.accent, 50).alpha() == 50
    assert fraction(0.12345) == 0.123 and fraction(float("nan")) == 0.0 and fraction(3.0) == 1.0


def test_sub_pixel_change_does_not_repaint(widgets, monkeypatch):
    widget = widgets("weight_distribution", show_front_to_rear_distribution=True)
    for name in ("frontWeightRatio", "leftWeightRatio", "crossWeightRatio"):
        monkeypatch.setattr(minfo.wheels, name, 0.5)
    widget.timerEvent(None)
    repaints = []
    monkeypatch.setattr(widget, "update", lambda: repaints.append(1))
    monkeypatch.setattr(minfo.wheels, "frontWeightRatio", 0.5000001)
    widget.timerEvent(None)
    assert not repaints


def test_app_memory_read_every_few_seconds(monkeypatch):
    from tinypedal.widget import system_performance

    class Process:
        reads = 0

        def memory_full_info(self):
            Process.reads += 1
            return type("Info", (), {"uss": 256 * 1024 * 1024})()

    clock = [100.0]
    monkeypatch.setattr(system_performance, "monotonic", lambda: clock[0])
    memory = system_performance.AppMemory(Process())
    assert memory.megabytes() == 256.0
    clock[0] += 1
    memory.megabytes()
    assert Process.reads == 1
    clock[0] += system_performance.MEMORY_READ_INTERVAL
    memory.megabytes()
    assert Process.reads == 2
