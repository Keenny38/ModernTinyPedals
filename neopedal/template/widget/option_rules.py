#  NeoPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of NeoPedal.
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Overlay Options page: on/off options really controlling other options, where the automatic sections
(cut from option names & order, see ui.quick.overlay_sections) guess wrong

Plain data only (no Qt). Checked against the overlay code: an option is dimmed only while it does nothing.

- TOGGLE_FIXES: section led by the wrong on/off option, led by the right one instead (wrong one kept in it).
- DEPENDENCY_FIXES: option -> on/off option it is used with ("" if none: used whatever other options are),
  on/off option -> itself: leads a section of its own (cut in the section of a sibling item: early pit stops).
- INACTIVE_RULES: options doing nothing with some values of other options (count, choice, "not while on"),
  see OptionUI.inactive for the states.
- ANY_OF: options used by several parts, each switched by its own on/off option: used while any is on.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import NamedTuple

BOTH = "both"
MODERN = "modern"
CLASSIC = "classic"


class OptionFix(NamedTuple):
    """Fixed sections & dependencies of an overlay, for a design (BOTH, MODERN or CLASSIC)"""

    design: str = BOTH
    toggles: Mapping[str, str] = {}
    dependencies: Mapping[str, str] = {}


_PEDAL_ALERTS = {
    # Each alert of a pedal bar is switched on by its own flash option (not by the one listed first)
    "show_abs_activation_flash": "",
    "show_wheel_slip_flash": "",
    "tc_activation_color": "show_tc_activation_flash",
    "abs_activation_color": "show_abs_activation_flash",
    "wheel_lock_color": "show_wheel_lock_flash",
    "wheel_slip_color": "show_wheel_slip_flash",
    "wheel_lock_threshold": "show_wheel_lock_flash",
    "wheel_slip_threshold": "show_wheel_slip_flash",
}
_NOTES_TEXTS = {
    # Texts shown in pits whether pit notes are shown or not (placeholder without pit notes)
    "pit_notes_text": "",
    "pit_comments_text": "",
}
# Early pit stops: own on/off option & section, not part of pit stops (both words "pitstop count")
_EARLY_PITSTOPS = {
    "show_early_pitstop_count": "show_early_pitstop_count",
    **{f"{prefix}_early_pitstop_count": "show_early_pitstop_count"
       for prefix in ("decimal_places", "font_color", "background_color")},
}
_RPM_MULTIPLIERS = ("rpm_multiplier_low", "rpm_multiplier_safe", "rpm_multiplier_redline", "rpm_multiplier_critical",
                    "rpm_multiplier_over_rev")

OPTION_FIXES: dict[str, tuple[OptionFix, ...]] = {
    "gear": (
        # Bars led by "inverted" switches (off by default): every bar option dimmed while the bar is shown
        OptionFix(CLASSIC, toggles={"show_inverted_battery": "show_battery_bar", "show_inverted_rpm": "show_rpm_bar"},
                  dependencies={key: "show_battery_reading" for key in (
                      "decimal_places_battery", "font_color_battery", "battery_reading_offset_x",
                      "battery_reading_text_alignment")}),
        # RPM zones color the RPM bar, flickering or not
        OptionFix(MODERN, dependencies=dict.fromkeys(_RPM_MULTIPLIERS[1:4], "show_rpm_bar")),
    ),
    "rpm_led": (OptionFix(dependencies=dict.fromkeys(_RPM_MULTIPLIERS, "")),),  # zones of every LED
    "pedal": (OptionFix(dependencies=_PEDAL_ALERTS),),
    "elevation": (OptionFix(dependencies={
        "show_zero_elevation_line": "",  # drawn without elevation line
        "zero_elevation_line_color": "show_zero_elevation_line",
        "zero_elevation_line_width": "show_zero_elevation_line",
        "show_elevation_progress_line": "",  # drawn without progress fill
        "elevation_progress_line_color": "show_elevation_progress_line",
        "elevation_progress_line_width": "show_elevation_progress_line",
    }),),
    "fuel": (OptionFix(dependencies={
        "low_fuel_lap_threshold": "",  # low amount color, flashing or not
        "show_refueling_level_mark": "show_fuel_level_bar",
        **_EARLY_PITSTOPS,
    }),),
    "virtual_energy": (OptionFix(dependencies={
        "low_energy_lap_threshold": "",
        "show_refilling_level_mark": "show_energy_level_bar",
        **_EARLY_PITSTOPS,
    }),),
    "track_notes": (OptionFix(dependencies=_NOTES_TEXTS),),
    "pace_notes": (OptionFix(dependencies=_NOTES_TEXTS),),
    "push_to_pass": (OptionFix(dependencies=dict.fromkeys((
        # Activation check of the battery charge (cooldown), not of the activation timer
        "activation_threshold_gear", "activation_threshold_speed", "activation_threshold_throttle",
        "minimum_activation_time_delay", "maximum_activation_time_per_lap"), "show_battery_charge")),),
    "navigation": (OptionFix(CLASSIC, dependencies={
        "show_circle_background": "",  # circle drawn without the background
        "background_color_circle": "show_circle_background",
        "circle_outline_width": "show_circle_background",
        "circle_outline_color": "show_circle_background",
    }),),
    "trailing": (OptionFix(CLASSIC, dependencies={
        "show_pedal_bar_readings": "show_pedal_bars",
        # Font of pedal bar readings only
        **dict.fromkeys(("font_name", "font_size", "font_weight", "enable_auto_font_offset"),
                        "show_pedal_bar_readings"),
    }),),
    "fuel_energy_saver": (OptionFix(dependencies={"remaining_pitstop_threshold": "enable_pit_entry_bias"}),),
    "race_plan": (OptionFix(dependencies={"pit_window_laps": "show_next_stop",
                                          "warning_color_pit_window": "show_next_stop"}),),
    "track_clock": (OptionFix(dependencies={"enable_time_scaled_countdown": "show_sunlight_phase_countdown"}),),
    "lap_time_history": (OptionFix(dependencies={"caption_text_virtual_energy": "show_virtual_energy_if_available"}),),
    "stint_history": (OptionFix(dependencies={"caption_text_virtual_energy": "show_virtual_energy_if_available"}),),
    "steering_meter": (OptionFix(MODERN, dependencies={"scale_mark_degree": "show_scale_mark"}),),
    "tyre_overview": (OptionFix(dependencies={
        "flat_spot_threshold": "show_tyre_alerts",
        "show_inner_center_outer": "show_surface_temperature",
        "show_alert_highlight": "show_tyre_alerts",
        "show_tread_grooves": "show_tyre_graphic",
        "show_pressure_target_range": "enable_tyre_pressure_target",
        "show_wear_per_lap": "",  # own row, with or without tread gauge
        "warning_threshold_remaining": "show_wear",
        "warning_threshold_laps": "show_lifespan_laps",
        # Target ranges & their colors: of pressure target (itself of shown pressure)
        **dict.fromkeys((
            "tyre_pressure_target_minimum", "tyre_pressure_target_maximum", "tyre_pressure_target_rear_minimum",
            "tyre_pressure_target_rear_maximum", "tyre_target_by_compound", "tyre_pressure_low_color",
            "tyre_pressure_high_color"), "enable_tyre_pressure_target"),
    }), OptionFix(MODERN, dependencies={
        "warning_threshold_remaining": "",  # of tread left & tread gauge (see ANY_OF)
    })),
    "track_map": (OptionFix(dependencies={
        "auto_prediction_additional_pitstop_time": "enable_auto_pitout_prediction"}),),
    "corner_coach": (OptionFix(dependencies={"braking_point_tolerance": "show_braking_point"}),),
}


def fixes_of(name: str, modern: bool) -> tuple[dict[str, str], dict[str, str]]:
    """Section toggle & dependency fixes of overlay for design in use"""
    toggles: dict[str, str] = {}
    dependencies: dict[str, str] = {}
    for fix in OPTION_FIXES.get(name, ()):
        if fix.design == BOTH or fix.design == (MODERN if modern else CLASSIC):
            toggles.update(fix.toggles)
            dependencies.update(fix.dependencies)
    return toggles, dependencies


# Inactive rules: option -> (state, control[, value]), states of OptionUI.inactive plus:
# "count": numbered option over count option, "set": used only while control is not 0,
# "value": used only while choice control is value
Inactive = dict[str, tuple[str, ...]]
_rex_numbered = re.compile(r"^prediction_(\d+)_(leader|player)_pit_time$")
_rex_range_start = re.compile(r"^speed_range_(\d+)_start$")


def _mixed_compound(values: Mapping) -> Inactive:
    """Mixed compound symbol & color: one compound shown per car only (classic driver lists)"""
    inactive: Inactive = {}
    if values.get("show_compound_for_each_wheel", False):
        inactive["mixed_compound_symbol"] = ("off", "show_compound_for_each_wheel")
        inactive["font_color_mixed_compound"] = ("off", "show_compound_for_each_wheel")
    elif not values.get("show_compound_color_by_type", True):
        inactive["font_color_mixed_compound"] = ("on", "show_compound_color_by_type")
    return inactive


def _predictions(values: Mapping) -> Inactive:
    count = values.get("number_of_prediction", 0)
    return {key: ("count", "number_of_prediction") for key in values
            if (matched := _rex_numbered.match(key)) and int(matched.group(1)) > count}


def _speed_ranges(values: Mapping) -> Inactive:
    return {key: ("set", f"speed_range_{matched.group(1)}_end") for key in values
            if (matched := _rex_range_start.match(key)) and not values.get(f"speed_range_{matched.group(1)}_end")}


def _radar(values: Mapping) -> Inactive:
    """Auto hide timer: not used while radar fades with distance"""
    return {"auto_hide_time_threshold": ("off", "enable_radar_fade")} if values.get("enable_radar_fade") else {}


def _black_box(values: Mapping) -> Inactive:
    """Speed & RPM labels: drawn only with justified center column"""
    if values.get("center_column_alignment", "Justified") == "Justified":
        return {}
    return {key: ("value", "center_column_alignment", "Justified") for key in ("text_speed", "text_rpm")}


INACTIVE_RULES: dict[str, Callable[[Mapping], Inactive]] = {
    "relative": _mixed_compound,
    "standings": _mixed_compound,
    "rivals": _mixed_compound,
    "relative_finish_order": _predictions,
    "acceleration": _speed_ranges,
    "radar": _radar,
    "black_box": _black_box,
}


_SETTING_POPUP = "show_setting_change_popup"
_DRIVING_EVENTS = "show_setting_popup_driving_events"  # pop-up of limiter, headlights & wipers states
_ENGINE = ("show_engine_status", "show_engine_overheat_events")
# Option -> on/off options of the parts using it (chains followed: event log events need the event log on)
ANY_OF: dict[str, Mapping[str, tuple[str, ...]]] = {
    "tyre_overview": {
        "show_layer_labels": ("show_carcass_temperature", "show_inner_layer_temperature"),
        # Tread left & tread gauge (modern design only: classic one follows show_wear, see OPTION_FIXES)
        "warning_threshold_remaining": ("show_wear", "show_tread_gauge"),
    },
    "black_box": {
        # Labels of status chips also named by setting change pop-up
        "text_abs": ("show_abs_indicator", _SETTING_POPUP),
        "text_tc": ("show_tc_indicator", _SETTING_POPUP),
        "text_brake_bias": ("show_brake_bias", _SETTING_POPUP),
        "text_brake_migration": ("show_brake_migration", _SETTING_POPUP),
        "text_motor_map": ("show_motor_map", _SETTING_POPUP),
        "text_limiter": ("show_pit_limiter_indicator", _DRIVING_EVENTS),
        **dict.fromkeys(("text_wipers_auto", "text_wipers_slow", "text_wipers_fast"),
                        ("show_wipers_indicator", _DRIVING_EVENTS)),
        # Engine readings & overheat events of event log
        **dict.fromkeys(("text_oil", "text_water", "engine_oil_warning_temperature",
                         "engine_water_warning_temperature"), _ENGINE),
        # Track limits points (center column) & penalty events of event log
        "text_track_limits": ("show_track_limits_points", "show_penalty_events"),
        # Flash over shift point: of RPM LEDs (always) & of gear RPM color (if its shift flash is on)
        "shift_flash_interval": ("show_rpm_leds", "enable_shift_flash"),
    },
}


def font_offset_inactive(values: Mapping) -> Inactive:
    """Font offset set by hand: not used while automatic (every overlay with font options)"""
    if values.get("enable_auto_font_offset"):
        return {"font_offset_vertical": ("off", "enable_auto_font_offset")}
    return {}
