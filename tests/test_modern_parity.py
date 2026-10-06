"""Modern design parity with classic layout & game data in overlays (phase 2, package D2)

Widgets are built on default settings (ui_env) with a neutral API reader, then single readers
and data module outputs are set to the case under test. Every case paints its widget (grab),
so drawing of the new parts runs too.
"""

import math
from importlib import import_module

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QColor, QImage

from tinypedal.api_control import api
from tinypedal.module_info import minfo
from tinypedal.setting import cfg
from tinypedal.widget._modern import create_widget
from tinypedal.widget._modern.base import DASH


@pytest.fixture
def widgets(ui_env, bundled_fonts):
    """Build widgets by name (modern design unless modern=False), deleted after test"""
    created = []

    def make(name: str, modern: bool = True, **options):
        cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
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


def update(widget, frames: int = 1) -> QImage:
    """Update & paint widget, last frame image"""
    image = QImage()
    for _ in range(frames):
        widget.timerEvent(None)
        image = widget.grab().toImage()
    assert not image.isNull()
    return image


@pytest.fixture
def field(monkeypatch):
    """Field of 6 cars in vehicles module output (restored after test)"""
    from tests.test_widget_benchmark import fill_field

    for owner, names in {
        minfo.vehicles: ("dataSet", "totalVehicles", "playerIndex", "leaderIndex", "leaderBestLapTime"),
        minfo.relative: ("standings", "drawOrder", "relativeAhead", "relativeBehind"),
    }.items():
        for name in names:
            monkeypatch.setattr(owner, name, getattr(owner, name))
    fill_field(6)
    return minfo.vehicles.dataSet


# --- Display order: design order kept at default values, option order once changed
def test_display_order_applies_once_changed(widgets):
    widget = widgets("engine", show_turbo_pressure=True, show_rpm=True)
    assert widget.keys.index("oil_temperature") < widget.keys.index("rpm")
    widget = widgets("engine", display_order_rpm=0)
    assert widget.keys[0] == "rpm"
    assert widget.keys.index("oil_temperature") < widget.keys.index("water_temperature")
    update(widget)


@pytest.mark.parametrize("name, option, first", [
    ("timing", "display_order_last", "last"),
    ("pedal", "display_order_throttle", "throttle"),
    ("session", "display_order_estimated_laps", "estimated_laps"),
    ("laps_and_position", "display_order_track_limits_points", "track_limits"),
    ("battery", "display_order_activation_timer", "timer"),
    ("tyre_wear", "display_order_lifespan_laps", "lifespan_laps"),
    ("traffic", "display_order_faster", "faster"),
])
def test_display_order_moves_item_first(widgets, name, option, first):
    options = {key: True for key, value in cfg.default.setting[name].items()
               if key.startswith("show_") and isinstance(value, bool)}
    widget = widgets(name, **options, **{option: -1})
    assert widget.keys[0] == first
    update(widget)


def test_display_order_of_driver_columns_and_gear_bars(widgets, field):
    widget = widgets("relative", column_time_gap=True, display_order_time_gap=0)
    assert widget.table.columns[0].key == "time_gap"
    update(widget)
    gear = widgets("gear", show_consumption_bar=True, display_order_consumption=0)
    assert gear.rect_consumption.top() < gear.rect_rpm.top()
    update(gear)


def test_display_order_options_listed_for_modern_design():
    from tinypedal.widget._modern import modern_module

    for name, key in (("brake_bias", "display_order_brake_bias"), ("relative", "display_order_driver"),
                      ("stint_history", "display_order_consistency"), ("engine", "display_order_rpm")):
        assert key in modern_module(name).Realtime.options


# --- Race plan: live replan, pit menu check, consumption target
def plan(widget, monkeypatch, stops_done: int = 0):
    from tinypedal.fuel_strategy import PitStop, Strategy, StrategyInput

    monkeypatch.setattr(widget, "refresh_plan", lambda: None)
    widget.setup = StrategyInput(laptime=100.0, race_laps=30, tank_capacity=100.0, fuel_per_lap=3.0)
    widget.strategy = Strategy(race_laps=30, stints=[10, 10, 10], stops_done=stops_done, stops=[
        PitStop(10, 30.0, 0.0, True, fuel_after=60.0), PitStop(20, 30.0, 0.0, False, fuel_after=50.0)])


def test_race_plan_pit_menu_check(widgets, monkeypatch):
    widget = widgets("race_plan", show_pit_menu=True, enable_live_replan=False)
    plan(widget, monkeypatch)
    reader(monkeypatch, "lap", "completed_laps", 5)
    reader(monkeypatch, "vehicle", "absolute_refill", 60.4)
    update(widget)
    assert stat_value(widget, "pit_menu").text == "OK"
    reader(monkeypatch, "vehicle", "absolute_refill", 80.0)
    update(widget)
    menu = stat_value(widget, "pit_menu")
    assert menu.text == "80>60L" and menu.color == widget.theme.negative
    reader(monkeypatch, "vehicle", "absolute_refill", 0.0)  # menu not set
    update(widget)
    assert stat_value(widget, "pit_menu").text == DASH


def test_race_plan_target_consumption(widgets, monkeypatch):
    widget = widgets("race_plan", show_target=True, enable_live_replan=False)
    plan(widget, monkeypatch)
    reader(monkeypatch, "lap", "completed_laps", 5)
    reader(monkeypatch, "engine", "fuel", 20.0)
    monkeypatch.setattr(minfo.fuel, "lastLapConsumption", 1.0)
    update(widget)
    target = stat_value(widget, "target")
    assert target.text.endswith("L") and target.fill is None
    monkeypatch.setattr(minfo.fuel, "lastLapConsumption", 9.0)  # last lap used more than target
    update(widget)
    assert stat_value(widget, "target").fill is not None


def test_race_plan_live_replan(widgets, monkeypatch):
    from tinypedal.fuel_strategy import PitStop, Strategy
    from tinypedal.race_live import LiveRead
    from tinypedal.widget._modern import race_plan

    widget = widgets("race_plan", enable_live_replan=True, show_next_stop=True, show_stops_left=True)
    plan(widget, monkeypatch)
    live_plan = Strategy(race_laps=30, stints=[12, 18], stops_done=1, stops=[PitStop(22, 40.0, 0.0, True)])
    calls = []

    def replan(live):
        calls.append(live)
        widget.live = live_plan

    monkeypatch.setattr(race_plan, "read_live", lambda *args: LiveRead(None, False, ""))
    monkeypatch.setattr(widget, "replan", replan)
    reader(monkeypatch, "lap", "completed_laps", 12)
    update(widget)
    assert calls and stat_value(widget, "next_stop").text == "L22 (10)"
    assert stat_value(widget, "stops_left").text == "1/2"  # stops done before live plan counted
    widget.wcfg["enable_live_replan"] = False
    update(widget)
    assert widget.live is None and stat_value(widget, "next_stop").text == "L20 (8)"


def test_race_plan_stint_limit_and_consumption_estimate(widgets, monkeypatch):
    from types import SimpleNamespace

    widget = widgets("race_plan", show_stint_limit=True, show_consumption_estimate=True, enable_live_replan=False)
    plan(widget, monkeypatch)
    update(widget)
    assert stat_value(widget, "stint_limit").text == "Fuel"
    assert stat_value(widget, "consumption_estimate").text == "Game"  # fuel module default: game estimate
    widget.strategy.limit = "tyres"  # stints capped by tyre life
    monkeypatch.setattr(minfo, "fuel", SimpleNamespace(
        consumptionMethod="median", consumptionLaps=5, lastLapConsumption=0.0))
    update(widget)
    limit = stat_value(widget, "stint_limit")
    assert limit.text == "Tyres" and limit.fill is not None
    assert stat_value(widget, "consumption_estimate").text == "Median 5"


# --- Driver lists: new columns, per wheel compounds, custom texts, class styled position
def test_driver_columns_brand_logo_average_speed_trap_lico(widgets, field, monkeypatch, tmp_path):
    from PySide6.QtGui import QPixmap

    from tinypedal.widget._modern.table import LOGO

    logo = QPixmap(64, 32)
    logo.fill(QColor("#FF0000"))
    assert logo.save(f"{cfg.path.brand_logo}Brand.png")
    for veh in field:
        veh.lapTimeHistory.average = 101.5
        veh.speedTrap.speed = 80.0  # m/s: 288 km/h
        veh.licoTimer.elapsed = 2.5
        veh.licoTimer.idling = 0.0
    widget = widgets("relative", column_brand_logo=True, column_average_laptime=True, column_speed_trap=True,
                     column_lift_and_coast_time=True)
    image = update(widget)
    keys = [column.key for column in widget.table.columns]
    row = next(row for row in widget.state if row is not None)
    cells = dict(zip(keys, row.cells))
    assert cells["brand_logo"].kind == LOGO and cells["brand_logo"].text == "Brand"
    assert cells["average_laptime"].text == "1:41.500"
    assert cells["speed_trap"].text == "288.0"
    assert cells["lift_and_coast_time"].text == "2.5s" and cells["lift_and_coast_time"].color == widget.theme.warning
    assert cells["brand_logo"].extra.startswith("Car ")  # vehicle name: brand of game car list
    assert not widget.brand_logo("Brand", "", 20, 10).isNull()  # own logo of brand logo folder
    logo_column = widget.table.columns[keys.index("brand_logo")]
    x = round(widget.table.x[keys.index("brand_logo")] + logo_column.width / 2)
    y = round(widget.table.row_rect(0).center().y())
    assert image.pixelColor(x, y).red() > 200  # logo drawn in its cell


def test_compound_cell_per_wheel(ui_env):
    from tinypedal.widget._modern.rows import compound_cell

    assert len(compound_cell(("S", "S", "S", "S")).extra) == 1
    assert len(compound_cell(("S", "S", "M", "M")).extra) == 2
    assert len(compound_cell(("S", "M", "S", "S")).extra) == 4  # left & right differ
    assert len(compound_cell(("S", "M", "S", "S"), per_wheel=False).extra) == 1  # front & rear same
    assert len(compound_cell(("S",)).extra) == 1


def test_driver_list_per_wheel_compounds_drawn(widgets, field):
    for veh in field:
        veh.tireCompoundName = ("S", "M", "S", "S")
    widget = widgets("standings", column_tyre_compound=True, show_compound_for_each_wheel=True)
    update(widget)
    assert "tiny" in widget.fonts
    widget = widgets("standings", column_tyre_compound=True, show_compound_for_each_wheel=False)
    update(widget)


def test_driver_list_custom_pit_and_leader_texts(widgets, field, monkeypatch):
    field[1].inPit = 1
    reader(monkeypatch, "session", "in_race", True)
    widget = widgets("standings", column_pit_status=True, column_time_gap=True, column_time_interval=True)
    update(widget)
    texts = {cell.text for row in widget.state if hasattr(row, "cells") for cell in row.cells}
    assert "PIT" in texts and "Leader" in texts  # design labels at default option values
    widget = widgets("standings", pit_status_text="BOX", time_gap_leader_text="P1", time_interval_leader_text="---")
    update(widget)
    texts = {cell.text for row in widget.state if hasattr(row, "cells") for cell in row.cells}
    assert {"BOX", "P1", "---"} <= texts


def test_driver_list_class_styled_position(widgets, field):
    from tinypedal.widget._modern.table import CLASS

    widget = widgets("relative", column_class=True, show_class_style_for_position_in_class=True)
    update(widget)
    cells = [cell for row in widget.state if row is not None for cell in row.cells if cell.kind == CLASS]
    assert cells and all(cell.color is not None and cell.color != cell.fill for cell in cells)
    widget = widgets("relative", show_class_style_for_position_in_class=False)
    update(widget)
    cells = [cell for row in widget.state if row is not None for cell in row.cells if cell.kind == CLASS]
    assert all(cell.color is None for cell in cells)


# --- Restyled widgets: colors not set by design stay customizable
def test_restyled_widgets_show_unmapped_colors():
    from tinypedal.widget._modern import modern_module

    black_box = modern_module("black_box").Realtime.options
    assert "background_color" not in black_box and "font_color_temperature" in black_box
    assert "throttle_color" not in black_box and "font_name" not in black_box
    pace_notes = modern_module("pace_notes").Realtime.options
    assert "background_color" not in pace_notes and "font_name" not in pace_notes


# --- Gauges: third spring & brake input marks
def test_suspension_third_spring_mark(widgets, monkeypatch):
    reader(monkeypatch, "wheel", "third_spring_deflection", (25.0, 25.0, 50.0, 50.0))
    widget = widgets("suspension_position", show_third_spring_position_mark=True, position_maximum_range=100)
    update(widget)
    assert [tile.mark for tile in widget.state] == [0.25, 0.25, 0.5, 0.5]
    widget = widgets("suspension_position", show_third_spring_position_mark=False)
    update(widget)
    assert all(tile.mark == -1 for tile in widget.state)


def test_brake_pressure_input_mark(widgets, monkeypatch):
    reader(monkeypatch, "inputs", "brake_raw", 0.8)
    reader(monkeypatch, "brake", "bias_front", 0.6)
    widget = widgets("brake_pressure", show_brake_input=True)
    update(widget)
    assert [tile.mark for tile in widget.state] == pytest.approx([0.48, 0.48, 0.32, 0.32])
    widget = widgets("brake_pressure", show_brake_input=False)
    update(widget)
    assert all(tile.mark == -1 for tile in widget.state)


# --- Gear: readings, custom limiter text, limiter reminder in pit lane
def test_gear_readings_and_limiter(widgets, monkeypatch):
    from tinypedal.widget._modern.gear import LIMITER_OFF, LIMITER_ON, LIMITER_REMINDER

    reader(monkeypatch, "engine", "rpm", 7345.0)
    reader(monkeypatch, "engine", "rpm_max", 8000.0)
    monkeypatch.setattr(minfo.hybrid, "motorState", 1)
    monkeypatch.setattr(minfo.hybrid, "batteryCharge", 55.25)
    widget = widgets("gear", show_rpm_reading=True, show_battery_reading=True, show_battery_bar=True,
                     decimal_places_battery=1, show_consumption_bar=True, show_consumption_reading=True,
                     speed_limiter_text="PIT LIM")
    update(widget, 2)
    assert widget.state[-1][:2] == ("7345", "55.2")
    assert widget.rect_rpm.height() > widget.unit  # bar tall enough for reading
    assert widget.text_limiter == "PIT LIM"
    assert widget.state[6] == LIMITER_OFF
    reader(monkeypatch, "switch", "speed_limiter_available", True)
    reader(monkeypatch, "vehicle", "in_pits", True)
    reader(monkeypatch, "vehicle", "speed", 20.0)
    update(widget)
    assert widget.state[6] == LIMITER_REMINDER
    reader(monkeypatch, "switch", "speed_limiter_active", True)
    update(widget)
    assert widget.state[6] == LIMITER_ON


def test_gear_limiter_default_text_is_design_label(widgets):
    from tinypedal import i18n

    assert widgets("gear").text_limiter == i18n.tr_overlay("LIMIT")


# --- Pedal: 100% indicator
def test_pedal_full_travel_indicator(widgets, monkeypatch):
    for horizontal in (False, True):
        widget = widgets("pedal", enable_horizontal_style=horizontal, maximum_indicator_height=5)
        assert set(widget.max_rects) == set(widget.keys)
        reader(monkeypatch, "inputs", "throttle_raw", 1.0)
        reader(monkeypatch, "inputs", "throttle", 1.0)
        update(widget)
    assert not widgets("pedal", maximum_indicator_height=0).max_rects


# --- Session: custom session names
def test_session_custom_names(widgets, monkeypatch):
    reader(monkeypatch, "session", "session_type", 4)
    widget = widgets("session", show_session_name=True)
    update(widget)
    assert stat_value(widget, "session_name").text == "RACE"
    widget = widgets("session", session_text_race="COURSE 24H")
    update(widget)
    assert stat_value(widget, "session_name").text == "COURSE 24H"


# --- Deltabest: swap style, game delta, invalid lap
def test_deltabest_swap_style_game_delta_and_invalid_lap(widgets, monkeypatch):
    monkeypatch.setattr(minfo.delta, "lapTimeCurrent", 50.0)
    monkeypatch.setattr(minfo.delta, "deltaBest", 0.4)
    reader(monkeypatch, "timing", "delta_best", -0.25)
    widget = widgets("deltabest", swap_style=True)
    update(widget)
    assert widget.state == (0.4, False)  # app delta by default
    widget = widgets("deltabest", show_game_deltabest_if_available=True)
    reader(monkeypatch, "lap", "invalidated", True)
    update(widget)
    assert widget.state == (-0.25, True)
    reader(monkeypatch, "timing", "delta_best", 0.0)  # game gives none: app delta
    update(widget)
    assert widget.state[0] == 0.4
    widget = widgets("deltabest", show_invalid_lap_indicator=False)
    update(widget)
    assert widget.state[1] is False


def test_classic_deltabest_game_delta(widgets, monkeypatch):
    monkeypatch.setattr(minfo.delta, "lapTimeCurrent", 50.0)
    monkeypatch.setattr(minfo.delta, "deltaBest", 0.4)
    monkeypatch.setattr(minfo.delta, "deltaSession", 0.3)
    reader(monkeypatch, "timing", "delta_best", -0.25)
    widget = widgets("deltabest", modern=False, show_game_deltabest_if_available=True)
    update(widget)
    assert widget.delta_best == -0.25
    extended = widgets("deltabest_extended", modern=False, show_game_deltabest_if_available=True)
    update(extended)
    assert "0.250" in extended.bar_ssbest.text


def test_deltabest_extended_game_delta(widgets, monkeypatch):
    monkeypatch.setattr(minfo.delta, "lapTimeCurrent", 50.0)
    monkeypatch.setattr(minfo.delta, "deltaSession", 0.3)
    reader(monkeypatch, "timing", "delta_best", -0.25)
    widget = widgets("deltabest_extended", show_session_deltabest=True, show_game_deltabest_if_available=True)
    update(widget)
    assert stat_value(widget, "session_deltabest").text.startswith("-0.25")


# --- Invalid lap on timing overlays
def test_invalid_lap_highlight(widgets, monkeypatch):
    reader(monkeypatch, "lap", "invalidated", True)
    timing = widgets("timing", show_current=True)
    update(timing)
    assert stat_value(timing, "current").color == timing.theme.negative
    laps = widgets("laps_and_position", show_laps=True)
    update(laps)
    assert stat_value(laps, "laps").color == laps.theme.negative
    timing = widgets("timing", show_invalid_lap_indicator=False)
    update(timing)
    assert stat_value(timing, "current").color is None


# --- Damage: inverted integrity, flash timing, puncture from game flat state
def test_damage_inverted_integrity_and_flash(widgets, monkeypatch):
    from tinypedal.widget._modern import damage

    reader(monkeypatch, "vehicle", "damage_severity", (2, 2, 0, 0, 0, 0, 0, 0))
    widget = widgets("damage", show_inverted_integrity=True, warning_flash_highlight_duration=0.4,
                     warning_flash_interval=0.6)
    update(widget)
    assert widget.integrity_text(0.75) == "25%"
    assert widgets("damage", show_inverted_integrity=False).integrity_text(0.75) == "75%"
    monkeypatch.setattr(damage, "monotonic", lambda: 10.2)  # middle of highlight part
    assert widget.pulse() == pytest.approx(1.0)
    monkeypatch.setattr(damage, "monotonic", lambda: 10.7)  # interval part
    assert widget.pulse() == pytest.approx(0.35)


def test_puncture_from_game_flat_state(widgets, monkeypatch):
    from tinypedal.widget._common import tyre_punctured

    reader(monkeypatch, "tyre", "flat", (False, True, False, False))
    reader(monkeypatch, "tyre", "puncture", (False, False, False, True))  # worn through: fallback
    assert tyre_punctured() == (False, True, False, True)
    widget = widgets("damage")
    update(widget)
    assert widget.damage_puncture == (False, True, False, True)
    classic = widgets("damage", modern=False)
    update(classic)
    assert tuple(classic.damage_tyre) == (False, True, False, True)


# --- Tyres: per wheel compound badges, heatmap around game optimal temperature
def test_tyre_widgets_left_right_compound_badges(widgets, monkeypatch):
    reader(monkeypatch, "vehicle", "in_pits", True)
    reader(monkeypatch, "tyre", "compound_class", ("GT3 - Soft", "GT3 - Medium", "GT3 - Soft", "GT3 - Soft"))
    for name in ("tyre_temperature", "tyre_pressure", "tyre_carcass", "tyre_inner_layer"):
        widget = widgets(name, show_tyre_compound=True)
        update(widget)
        front, rear = widget.compounds.badges
        assert len(front) == 2 and len(rear) == 1


def test_heatmap_from_game_optimal_temperature(widgets, monkeypatch):
    from tinypedal import calculation as calc
    from tinypedal.widget._modern.wheels import heatmap_around

    reader(monkeypatch, "tyre", "optimal_temperature", (90.0, 90.0, 0.0, 0.0))  # rear: unavailable
    widget = widgets("tyre_temperature", enable_heatmap_from_optimal_temperature=True)
    update(widget)
    heat = widget.compounds.heat
    assert heat[0] == heatmap_around(90) and heat[2] != heat[0]
    assert calc.select_grade(heat[0], 90.0).name() == QColor("#4F4").name()  # ideal: green
    assert calc.select_grade(heat[0], 65.0).name() == QColor("#48F").name()  # cold: blue
    assert calc.select_grade(heat[0], 135.0).name() == QColor("#F44").name()  # hot: red
    widget = widgets("tyre_carcass", enable_heatmap_from_optimal_temperature=True)
    update(widget)
    assert widget.compounds.heat[1] == heatmap_around(90)
    widget = widgets("tyre_temperature", enable_heatmap_from_optimal_temperature=False)
    update(widget)
    assert widget.compounds.heat[0] != heatmap_around(90)


# --- Battery: state of charge from game
def test_battery_state_of_charge(widgets, monkeypatch):
    reader(monkeypatch, "emotor", "state_of_charge", 62.5)
    monkeypatch.setattr(minfo.hybrid, "motorState", 0)
    widget = widgets("battery", show_state_of_charge=True)
    update(widget)
    assert stat_value(widget, "soc").text == DASH  # no electric motor
    monkeypatch.setattr(minfo.hybrid, "motorState", 1)
    update(widget)
    soc = stat_value(widget, "soc")
    assert soc.text == "62.5%" and soc.bar == 0.625
    assert "soc" not in widgets("battery", show_state_of_charge=False).keys


# --- Flag: sector yellow flags & full course yellow (classic layout, modern design: test_modern_overlays_more)
def test_flag_sector_yellow_and_full_course_yellow(widgets, monkeypatch):
    reader(monkeypatch, "session", "sector_yellow_flags", (True, False, True))
    reader(monkeypatch, "session", "yellow_flag_state", 4)
    widget = widgets("flag", modern=False)
    widget.show()
    update(widget)
    assert widget.bar_sector_yellow.text == "SEC 1-3" and not widget.bar_sector_yellow.isHidden()
    assert widget.bar_fcy.text == "FCY PIT" and not widget.bar_fcy.isHidden()
    reader(monkeypatch, "session", "sector_yellow_flags", (False, False, False))
    reader(monkeypatch, "session", "yellow_flag_state", 0)
    update(widget)
    assert widget.bar_sector_yellow.isHidden() and widget.bar_fcy.isHidden()
    widget.hide()


def test_flag_limiter_active_state(widgets, monkeypatch):
    reader(monkeypatch, "switch", "speed_limiter_active", True)
    widget = widgets("flag", modern=False)
    widget.show()
    update(widget)
    assert not widget.bar_limiter.isHidden()
    widget.hide()


# --- Weather: wind speed & direction
def test_weather_wind(widgets, monkeypatch):
    reader(monkeypatch, "session", "wind_velocity", (3.0, 0.0, 4.0))  # 5 m/s
    reader(monkeypatch, "vehicle", "orientation_yaw_radians", 0.0)
    widget = widgets("weather", show_wind=True)
    update(widget)
    text, angle = widget.state[1]
    assert text == "18 km/h" and angle is not None
    reader(monkeypatch, "vehicle", "orientation_yaw_radians", math.pi / 2)  # car turned: wind angle turns
    update(widget)
    assert widget.state[1][1] != angle
    reader(monkeypatch, "session", "wind_velocity", (0.0, 0.0, 0.1))
    update(widget)
    assert widget.state[1] == ("0 km/h", None)  # calm: no arrow
    assert "wind" not in widgets("weather", show_wind=False).keys


def test_wind_arrow_relative_to_car(widgets, monkeypatch):
    """Wind blowing where car heads: arrow up (tailwind), opposite: down (headwind)"""
    widget = widgets("weather", show_wind=True)
    yaw = 0.7
    # Car forward in world x, z for orientation yaw (same as radar: opponent ahead drawn above player)
    forward_x, forward_z = math.sin(yaw), -math.cos(yaw)
    reader(monkeypatch, "vehicle", "orientation_yaw_radians", yaw)
    reader(monkeypatch, "session", "wind_velocity", (forward_x * 5, 0.0, forward_z * 5))
    assert widget.wind()[1] % 360 == pytest.approx(0, abs=5)
    reader(monkeypatch, "session", "wind_velocity", (-forward_x * 5, 0.0, -forward_z * 5))
    assert widget.wind()[1] % 360 == pytest.approx(180, abs=5)

# --- Ride height: front & rear from game
def test_ride_height_axles(widgets, monkeypatch):
    reader(monkeypatch, "vehicle", "ride_height_front", 52.4)
    reader(monkeypatch, "vehicle", "ride_height_rear", 71.6)
    widget = widgets("ride_height", show_axle_ride_height=True)
    update(widget)
    assert widget.state[1] == ("52", "72")
    narrow = widgets("ride_height", show_axle_ride_height=False)
    update(narrow)
    assert narrow.state[1] == () and narrow.width() < widget.width()


# --- Engine overheating warning from game
@pytest.mark.parametrize("name", ["engine_temperature", "engine"])
def test_engine_overheating_warning(widgets, monkeypatch, name):
    reader(monkeypatch, "engine", "oil_temperature", 90.0)
    reader(monkeypatch, "engine", "water_temperature", 80.0)
    reader(monkeypatch, "engine", "overheating", True)
    widget = widgets(name, show_oil_temperature=True, show_water_temperature=True)
    update(widget)
    assert all(value.color == widget.theme.negative for value in widget.state[:2])
    widget = widgets(name, show_game_overheating_warning=False)
    update(widget)
    assert all(value.color is None for value in widget.state[:2])
