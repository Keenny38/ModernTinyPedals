"""Settings migration from older versions: renamed options & widgets, robust to incomplete presets"""

import copy

import pytest

from tinypedal.setting_preupdate import preupdate_global_setting, preupdate_user_setting


def old_preset() -> dict:
    """Preset from version 2.35 with options renamed since"""
    return {
        "telemetry_api": {"enable": True, "access_mode": 0},
        "module_vehicles": {"update_interval": 20},
        "wheel_alignment": {"enable": True, "bar_gap": 2, "position_y": 100},
        "suspension_position": {"negative_position_color": "#FF2200"},
        "track_map": {"pitstop_duration_minimum": 20, "map_color": "#FFFFFF", "show_vehicle_standings": True},
        "p2p": {"enable": False},
        "cruise": {"enable": True, "position_y": 10, "font_weight": "bold"},
        "speedometer": {"bkg_color": "#000000", "column_index_speed": 2, "max_speed": 300, "font_weight": "normal"},
        "fuel": {"show_laps": True, "font_color_used": "#FFF"},
        "steering": {"enable": True, "font_color": "#ABC"},
        "flag": {"speed_limiter_text": "LIMITER", "traffic_pitout_duration": 5, "show_startlights": True},
        "laps_and_position": {"prefix_position_overall": "P", "show_lap_number": True},
        "ride_height": {"ride_height_offset": [1, 2]},
        "brake_temperature": {"inner_gap": 3},
        "wheel_status": {"enable_smooth_transition": False, "show_refuel": True},
        "module_recorder": {"enable": False},
        "standings": {"column_brand_logo": False},
    }


def test_full_migration_from_old_version():
    preset = old_preset()
    preupdate_user_setting((2, 35, 0), preset)
    assert preset["api_lmu"] == preset["api_rf2"] == {"enable": True, "access_mode": 0}
    assert preset["module_vehicles"]["update_interval"] == 10
    assert preset["wheel_camber"]["bar_gap"] == 0 and preset["wheel_toe"]["position_y"] == 160
    assert preset["suspension_position"]["negative_position_color"] == "#00AAFF"
    assert preset["track_map"]["pitout_duration_minimum"] == 20
    assert preset["track_map"]["map_color_sector_2"] == "#FFFFFF"
    assert preset["track_map"]["show_vehicle_class_standings"] is True
    assert preset["push_to_pass"] == {"enable": False}
    assert preset["track_clock"]["position_y"] == 40 and preset["track_clock"]["font_weight"] == "Bold"
    speed = preset["speedometer"]
    assert speed["background_color"] == "#000000" and speed["display_order_speed"] == 2
    assert speed["maximum_speed"] == 300 and speed["font_weight"] == "Normal"
    assert preset["fuel"]["show_estimated_laps"] is True
    assert preset["fuel"]["font_color_estimated_consumption"] == "#FFF"
    assert preset["steering_meter"]["font_color_steering_angle"] == "#ABC"
    assert preset["flag"]["speed_limiter_text"] == "L" and preset["flag"]["traffic_extended_duration"] == 5
    assert preset["flag"]["show_start_lights"] is True
    assert preset["laps_and_position"]["prefix_position_overall"] == "P "
    assert preset["laps_and_position"]["show_laps"] is True
    assert preset["ride_height"]["bottoming_height"] == [1, 2]
    assert preset["brake_temperature"]["vertical_gap"] == 3
    box = preset["black_box"]
    assert box["smooth_transition_duration"] == 0 and box["show_fuel_gauge"] is True
    assert preset["module_recorder"]["enable"] is True
    assert preset["standings"]["column_brand_logo"] is True
    assert "rivals" not in preset  # widget not in preset: left out


def test_brand_logo_column_shown_once():
    preset = {"relative": {"column_brand_logo": False}, "rivals": {"column_brand_logo": False}}
    preupdate_user_setting((2, 50, 4), preset)
    assert preset["relative"]["column_brand_logo"] is True and preset["rivals"]["column_brand_logo"] is True
    preset["relative"]["column_brand_logo"] = False  # turned off again by user
    preupdate_user_setting((2, 50, 5), preset)
    assert preset["relative"]["column_brand_logo"] is False


def test_wheel_toe_renamed_options():
    preset = {"wheel_toe": {"caption_text": "toe in", "show_toe_in": True}}
    preupdate_user_setting((2, 49, 0), preset)
    assert preset["wheel_toe"]["caption_text"] == "toe angle" and preset["wheel_toe"]["show_toe_angle"] is True


@pytest.mark.parametrize(("version", "applied"), [
    ((2, 50, 5), False),  # current: nothing changed
    ((2, 50, 1), True),  # only newer updates applied
])
def test_only_newer_updates_applied(version, applied):
    preset = {"module_recorder": {"enable": False}, "steering": {"enable": True}}
    preupdate_user_setting(version, preset)
    assert preset["module_recorder"]["enable"] is applied
    assert "steering_meter" not in preset  # 2.49.9 update not applied


def test_incomplete_or_odd_preset_does_not_break_update():
    preset = {
        "module_vehicles": {},  # option missing
        "suspension_position": {},
        "wheel_alignment": {"enable": True},  # no position
        "cruise": {"enable": True},
        "speedometer": {"font_weight": 600},  # not text
        "notes": "free text",  # not a widget
    }
    original = copy.deepcopy(preset)
    preupdate_user_setting((2, 30, 0), preset)
    assert preset["speedometer"]["font_weight"] == 600
    assert preset["notes"] == original["notes"]
    assert "wheel_toe" in preset and "track_clock" in preset


def test_global_setting_update():
    config = {"overlay": {"bkg_color": "#111111"}, "version": "2.40.0"}
    preupdate_global_setting((2, 42, 0), config)
    assert config["overlay"]["background_color"] == "#111111"
    unchanged = {"overlay": {"bkg_color": "#111111"}}
    preupdate_global_setting((2, 43, 0), unchanged)
    assert "background_color" not in unchanged["overlay"]


@pytest.mark.parametrize(("widget", "old", "new"), [
    ("module_sectors", {"enable_all_time_best_sectors": True}, {}),
    ("elevation", {"font_color": "#1"}, {"font_color_elevation_reading": "#1", "font_color_elevation_scale": "#1"}),
    ("force", {"show_g_force": True, "font_color_g_force": "#2", "background_color_g_force": "#3",
               "display_order_long_gforce": 1, "display_order_lat_gforce": 2},
     {"show_lateral_g_force": True, "font_color_longitudinal_g_force": "#2", "background_color_lateral_g_force": "#3",
      "display_order_longitudinal_g_force": 1, "display_order_lateral_g_force": 2}),
    ("pedal", {"background_color": "#4"}, {"background_color_ffb": "#4"}),
    ("instrument", {"background_color": "#5"}, {"background_color_wheel_slip": "#5"}),
    ("gear", {"speed_background_color": "#6"}, {"background_color_speed": "#6"}),
    ("weather_forecast", {"rain_background_color": "#7"}, {"background_color_rain": "#7"}),
    ("weather", {"prefix_dry": "D", "prefix_wet": "W"}, {"prefix_wetness_dry": "D", "prefix_wetness_wet": "W"}),
    ("laps_and_position", {"background_color_maxlap_warn": "#8"}, {"warning_color_maximum_laps": "#8"}),
    ("lap_time_history", {"font_color_invalid_laptime": "#9"}, {"font_color_invalid_time": "#9"}),
    ("timing", {"font_color_invalid_laptime": "#A"}, {"font_color_invalid_last": "#A"}),
    ("virtual_energy", {"show_ratio": True, "show_bias": True, "show_refill": True},
     {"show_fuel_ratio": True, "show_fuel_bias": True, "show_refilling": True}),
    ("track_map", {"enabled_fixed_pitout_prediction": True, "vehicle_outline_player_width": 2,
                   "vehicle_outline_player_color": "#B"},
     {"enable_fixed_pitout_prediction": True, "vehicle_outline_width_player": 2,
      "vehicle_outline_color_player": "#B"}),
    ("navigation", {"show_vehicle_standings": False}, {"show_vehicle_class_standings": False}),
    ("friction_circle", {"font_color": "#C"}, {"font_color_readings": "#C"}),
    ("relative", {"display_order_timegap": 3, "display_order_pitstatus": 4},
     {"display_order_time_gap": 3, "display_order_pit_status": 4}),
    ("rivals", {"display_order_timeinterval": 5, "display_order_pitstatus": 6},
     {"display_order_time_interval": 5, "display_order_pit_status": 6}),
    ("standings", {"min_top_vehicles": 3, "display_order_timeinterval": 1, "display_order_timegap": 2,
                   "display_order_pitstatus": 3},
     {"minimum_top_vehicles": 3, "display_order_time_interval": 1, "display_order_time_gap": 2,
      "display_order_pit_status": 3}),
    ("deltabest", {"background_color_deltabar": "#D", "bar_length": 9, "bar_height": 8, "bar_display_range": 2,
                   "show_animated_deltabest": True},
     {"background_color_delta_bar": "#D", "delta_bar_length": 9, "delta_bar_height": 8,
      "delta_bar_display_range": 2, "enable_animated_deltabest": True}),
    ("radar", {"auto_hide": True, "auto_hide_in_private_qualifying": False},
     {"enable_auto_hide": True, "enable_auto_hide_in_private_qualifying": False}),
    ("pace_notes", {"auto_hide_if_not_available": True}, {"enable_auto_hide_if_not_available": True}),
    ("track_notes", {"auto_hide_if_not_available": False}, {"enable_auto_hide_if_not_available": False}),
    ("trailing", {"draw_order_index_throttle": 1}, {"display_order_throttle": 1}),
    ("speedometer", {"speed_decimal_places": 1}, {"decimal_places_speed": 1}),
])
def test_options_renamed_in_2_43(widget, old, new):
    preset = {widget: dict(old), "sectors": {}}
    preupdate_user_setting((2, 42, 0), preset)
    for key, value in new.items():
        assert preset[widget][key] == value, key
    if widget == "module_sectors":
        assert preset["sectors"]["enable_all_time_best_sectors"] is True


def test_newer_and_misc_updates():
    preset = {"track_map": {"pitstop_duration_increment": 5}, "black_box": {"enable_alert_pulse": False,
              "show_energy_remaining": True}}
    preupdate_user_setting((2, 39, 5), preset)
    assert preset["track_map"]["pitout_duration_increment"] == 5
    assert preset["black_box"]["alert_pulse_frequency"] == 0 and preset["black_box"]["show_energy_gauge"] is True
