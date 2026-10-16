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
Black box widget, option data shared by the widget and its config dialog

Plain data and pure functions only (no Qt, no widget import), so the config dialog can use
them without loading any widget: config sections, display profiles, auto compact mode,
compound targets, color themes and the options shown in simple mode.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import NamedTuple

from ...units import kpa_to_bar, kpa_to_psi

# Config dialog sections: title shown before the first option of each section
BLACK_BOX_SECTIONS = {
    "enable": "General",
    "display_profile": "Profile & Data",
    "layout": "Size & Layout",
    "enable_depth_effects": "Visual Style",
    "override_unit_temperature": "Units",
    "show_wheel_angle": "Steering & Wheel Slip",
    "show_tyre_temperature": "Tyre Temperature",
    "show_tyre_pressure": "Tyre Pressure",
    "show_tyre_wear": "Tyre Wear & Status",
    "show_tyre_compound": "Tyre Readings",
    "show_brake_temperature": "Brakes",
    "show_suspension": "Suspension",
    "show_rpm_leds": "RPM LEDs",
    "show_gear": "Gear & Speed",
    "center_column_alignment": "Center Column",
    "show_fuel_gauge": "Fuel & Energy Gauges",
    "show_battery_bar": "Battery",
    "show_damage_panel": "Damage Panel",
    "show_incident_recorder": "Incident Recorder & Event Log",
    "display_order_locking": "Center Column Order",
}

# On/off & choice options shown in simple mode: main items only (89 on/off options in all), details
# (trends, diagnostics, event kinds, effects) stay in advanced mode
BLACK_BOX_SIMPLE_SWITCHES = frozenset((
    "enable", "show_background", "enable_auto_resize", "display_profile", "override_unit_temperature",
    "override_unit_tyre_pressure", "override_unit_speed", "override_unit_fuel",
    "show_wheel_angle", "show_slip_warning", "show_tyre_temperature", "show_tyre_pressure", "show_tyre_wear",
    "show_tyre_status", "show_tyre_compound", "show_brake_temperature", "show_brake_wear", "show_suspension",
    "show_rpm_leds", "show_gear", "show_speed", "show_rpm", "show_pedal_bars", "show_abs_indicator",
    "show_tc_indicator", "show_brake_bias", "show_motor_map", "show_headlights_indicator", "show_wipers_indicator",
    "show_engine_status", "show_delta_best", "show_laptime", "show_pit_limiter_indicator",
    "show_track_limits_points", "show_gap_ahead_behind", "show_lift_and_coast", "show_setting_change_popup",
    "setting_popup_position", "show_fuel_gauge", "show_energy_gauge", "show_stint_comparison", "show_battery_bar",
    "show_damage_panel", "damage_panel_position", "show_incident_recorder", "show_event_log",
))

# Options shown in simple mode besides the on/off & choice options above: the ones people
# commonly adjust. Colors, thresholds, fine scales and labels stay in advanced mode.
BLACK_BOX_BASIC = frozenset((
    "position_x", "position_y", "font_name", "font_size", "font_weight", "opacity",
    "background_color", "font_color", "caption_text",
    "display_scale", "fixed_width", "fixed_height",
    "maximum_wheel_angle", "tyre_pressure_target_minimum", "tyre_pressure_target_maximum",
    "tyre_target_by_compound", "gauge_low_lap_threshold", "suspension_motion_scale",
    "damage_panel_scale", "number_of_event_log_lines", "number_of_rpm_leds", "setting_popup_duration", "layout",
))


PRESSURE_TARGET_PREFIX = "tyre_pressure_target_"  # options read by pressure_target_kpa


def pressure_target_kpa(value: float) -> float:
    """Tyre pressure target in kPa, entered in kPa, psi or bar

    Unit is found from value, as tyre pressure ranges never overlap: bar 1-5, psi 10-60,
    kPa 70 and more. 0 (not set) is kept.
    """
    if value <= 0:
        return value
    if value < 10:
        return value / kpa_to_bar(1)
    if value < 60:
        return value / kpa_to_psi(1)
    return value


# Compound targets: "S=160-190/75-100; W=150-175" (pressure kPa, psi or bar, then optional temperature Celsius)
_rex_target = re.compile(
    r"^\s*([^=\s]+)\s*=\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)"
    r"(?:\s*/\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?))?\s*$"
)


def parse_compound_targets(text: str) -> dict[str, tuple[float, float, float | None, float | None]]:
    """Per compound symbol: (pressure min, pressure max, temperature min, temperature max)

    Invalid entries are ignored, so a typo only loses that one compound.
    """
    targets = {}
    for entry in re.split(r"[;,]", text or ""):
        matched = _rex_target.match(entry)
        if not matched:
            continue
        symbol, p_min, p_max, t_min, t_max = matched.groups()
        targets[symbol.upper()] = (
            float(p_min), float(p_max),
            float(t_min) if t_min is not None else None,
            float(t_max) if t_max is not None else None,
        )
    return targets


# Brake targets by car class: "Hypercar=400-950; GT3=250-650" (disc temperature window, Celsius)
_rex_range = re.compile(r"^\s*([^=]+?)\s*=\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*$")


def parse_class_targets(text: str) -> dict[str, tuple[float, float]]:
    """Per car class name: (temperature min, temperature max), invalid entries ignored"""
    targets = {}
    for entry in re.split(r"[;,]", text or ""):
        matched = _rex_range.match(entry)
        if matched:
            name, low, high = matched.groups()
            targets[name.upper()] = (float(low), float(high))
    return targets


def class_target(targets: Mapping[str, tuple[float, float]], class_name: str) -> tuple[float, float] | None:
    """Target of the longest class name found in class_name (case-insensitive), None if none"""
    name = (class_name or "").upper()
    matches = [key for key in targets if key in name]
    return targets[max(matches, key=len)] if matches else None


def format_compound_targets(targets: Mapping[str, tuple]) -> str:
    """Targets back to option text, the reverse of parse_compound_targets"""

    def number(value: float) -> str:
        return f"{value:g}"

    entries = []
    for symbol, (p_min, p_max, t_min, t_max) in targets.items():
        entry = f"{symbol}={number(p_min)}-{number(p_max)}"
        if t_min is not None and t_max is not None:
            entry += f"/{number(t_min)}-{number(t_max)}"
        entries.append(entry)
    return "; ".join(entries)


# Display profiles: override a group of show options at once ("Custom" keeps user values)
_DIAGNOSTICS = (
    "show_tyre_carcass_temperature", "show_tyre_load", "show_tyre_slip_angle",
    "show_wheel_camber", "show_ride_height", "show_tyre_wear_per_lap",
)
DISPLAY_PROFILES: dict[str, dict[str, bool]] = {
    "Minimal": {
        **dict.fromkeys(_DIAGNOSTICS, False),
        "show_tyre_pressure": False, "show_tyre_wear_end_stint": False, "show_tyre_compound": False,
        "show_brake_wear": False, "show_brake_pressure": False, "show_brake_migration": False,
        "show_motor_map": False,
        "show_wheel_locking": False, "show_delta_best": False, "show_laptime": False,
        "show_fuel_gauge": False, "show_energy_gauge": False, "show_stint_comparison": False,
        "show_tyre_temperature_trend": False, "show_tyre_pressure_trend": False,
    },
    "Sprint": {
        **dict.fromkeys(_DIAGNOSTICS, False),
        "show_tyre_pressure": True, "show_tyre_wear": True, "show_tyre_wear_end_stint": False,
        "show_delta_best": True, "show_laptime": True, "show_rpm_leds": True,
        "show_fuel_gauge": False, "show_energy_gauge": False, "show_stint_comparison": False,
    },
    "Endurance": {
        "show_tyre_pressure": True, "show_tyre_wear": True, "show_tyre_wear_end_stint": True,
        "show_tyre_wear_per_lap": True, "show_tyre_compound": True, "show_brake_wear": True,
        "show_fuel_gauge": True, "show_energy_gauge": True, "show_stint_comparison": True,
        "show_tyre_temperature_trend": True, "show_tyre_pressure_trend": True,
    },
}

# Secondary elements hidden by auto compact mode, when the widget is scaled down
COMPACT_HIDDEN = (
    *_DIAGNOSTICS, "show_tyre_wear_end_stint", "show_tyre_compound", "show_brake_wear",
    "show_brake_pressure", "show_caption", "show_stint_comparison",
    "show_tyre_temperature_trend", "show_tyre_pressure_trend",
)


# User profiles: on/off options saved from the page (Save as Profile), text option of the preset each
USER_PROFILES = {"User 1": "user_profile_1", "User 2": "user_profile_2", "User 3": "user_profile_3"}


def format_user_profile(values: Mapping) -> str:
    """On/off show options of values as profile text, like show_gear:1, show_rpm:0"""
    return ", ".join(f"{key}:{int(value)}" for key, value in values.items()
                     if key.startswith("show_") and isinstance(value, bool))


def parse_user_profile(text: str) -> dict[str, bool]:
    """Profile text back to on/off options (invalid entries ignored)"""
    values = {}
    for entry in (text or "").split(","):
        key, _, state = entry.strip().partition(":")
        if key.startswith("show_") and state in ("0", "1"):
            values[key] = state == "1"
    return values


def profile_overrides(wcfg: Mapping) -> dict[str, bool]:
    """Options set by display profile (built-in or user profile; empty: Custom, or user profile not saved)"""
    name = wcfg["display_profile"]
    if name in USER_PROFILES:
        return parse_user_profile(wcfg.get(USER_PROFILES[name], ""))
    return dict(DISPLAY_PROFILES.get(name, {}))


def display_overrides(wcfg: Mapping) -> dict[str, bool]:
    """Options overridden by display profile, then by auto compact mode"""
    overrides = profile_overrides(wcfg)
    threshold = wcfg["auto_compact_display_scale"]
    if 0 < wcfg["display_scale"] < threshold:
        overrides.update(dict.fromkeys(COMPACT_HIDDEN, False))
    return overrides


def release_profile(wcfg: Mapping) -> dict[str, object]:
    """Options set to edit an option of display profile: profile values kept, profile Custom"""
    profile = profile_overrides(wcfg)
    if not profile:
        return {}
    return {**profile, "display_profile": "Custom"}


# Color themes: each default color mapped to the theme color with the same meaning
# (red warning & hot, cyan cold & low, green good, orange & yellow in between, blue, magenta)
_DEFAULT_ROLES = ("#FF3D3D", "#3DC8FF", "#2FC46A", "#FF9F1C", "#FFC400", "#3D8BFF", "#B0106A")


def _theme(*colors: str) -> dict[str, str]:
    return dict(zip(_DEFAULT_ROLES, colors))


BLACK_BOX_COLOR_THEMES: dict[str, dict[str, str]] = {
    "Default": {},
    "Colorblind Safe": _theme("#D55E00", "#56B4E9", "#009E73", "#E69F00", "#F0E442", "#0072B2", "#CC79A7"),
}


def theme_color(default: str, theme: Mapping[str, str]) -> str:
    """Theme color for a default color, alpha prefix of #AARRGGBB kept"""
    value = default.upper()
    if len(value) == 9:  # #AARRGGBB
        mapped = theme.get("#" + value[3:])
        return value[:3] + mapped[1:] if mapped else value
    return theme.get(value, value)


# On/off option: options that only matter while it is on (greyed out while it is off)
_CONTROLS: dict[str, tuple[str, ...]] = {
    "show_background": ("background_color",),
    "show_caption": ("caption_text", "font_color_caption", "background_color_caption"),
    "show_module_warning": ("font_color_module_warning",),
    "enable_auto_resize": ("resize_delay", "resize_anchor"),
    "show_wheel_angle": ("maximum_wheel_angle",),
    "show_slip_warning": (
        "wheel_lock_threshold", "wheel_locked_threshold", "wheel_spin_threshold", "slip_warning_minimum_speed",
        "warning_outline_width", "wheel_lock_color", "wheel_spin_color",
    ),
    "show_tyre_temperature": (  # warning color also used by surface overheat strip & bottoming: no control
        "tyre_temperature_warning_threshold",
        "tyre_temperature_cold_threshold", "font_color_tyre_temperature_cold",
        "font_color_tyre_temperature_warming", "show_tyre_temperature_trend",
    ),
    "show_tyre_temperature_trend": ("tyre_heat_trend_threshold",),
    "show_tyre_pressure": ("enable_tyre_pressure_target", "show_tyre_pressure_trend"),
    "enable_tyre_pressure_target": (  # pressure colors: outside target only
        "tyre_pressure_target_minimum", "tyre_pressure_target_maximum",
        "tyre_pressure_target_rear_minimum", "tyre_pressure_target_rear_maximum",
        "tyre_pressure_low_color", "tyre_pressure_high_color", "tyre_pressure_warning_background_color",
    ),
    "show_tyre_pressure_trend": ("tyre_pressure_trend_threshold",),
    "show_tyre_wear": ("tyre_wear_warning_threshold", "tyre_wear_warning_color", "font_color_tyre_wear_warning"),
    "show_tyre_status": (
        "flat_spot_threshold", "wheel_puncture_color", "wheel_flat_spot_color", "wheel_detached_color",
        "text_puncture", "text_flat_spot", "text_detached",
    ),
    "show_brake_temperature": (
        "brake_temperature_cold_threshold", "brake_temperature_hot_threshold", "brake_target_by_class",
        "show_brake_temperature_trend", "show_brake_peak_temperature", "brake_imbalance_threshold",
        "font_color_brake_temperature_cold", "font_color_brake_temperature_hot",
    ),
    "show_brake_temperature_trend": ("brake_trend_duration", "brake_heat_trend_threshold"),
    "show_ride_height_minimum": ("ride_height_bottoming_threshold",),
    "show_brake_heat_balance": ("text_brake_heat",),
    "show_motor_map": ("motor_map_color",),  # label also used by setting change pop-up
    "show_headlights_indicator": ("headlights_active_color", "status_icons_side", "status_icon_scale"),
    "show_wipers_indicator": ("wipers_active_color",),  # wipers labels also used by setting change pop-up
    "show_track_limits_points": ("track_limits_warning_color", "track_limits_penalty_color"),
    "show_gap_ahead_behind": ("text_gap",),
    "show_lift_and_coast": ("lift_and_coast_color", "text_lift_and_coast"),
    "show_engine_status": (  # oil & water warning temperatures & labels also used by engine overheat events
        "stalling_rpm_threshold",
        "engine_running_color", "engine_warning_color", "engine_off_color", "engine_ignition_color",
        "font_scale_engine", "text_engine_off", "text_ignition",
    ),
    "show_tyre_wear_end_stint": ("tyre_wear_forecast_laps",),
    "show_tyre_load": ("tyre_load_display",),
    "show_brake_wear": ("brake_wear_warning_threshold", "font_color_brake_wear_warning", "brake_wear_display"),
    "show_brake_pressure": ("brake_pressure_color",),
    "show_suspension": (
        "suspension_scale", "suspension_motion_scale", "enable_wheel_suspension_motion", "show_coilover_damage",
        "suspension_spring_color", "suspension_compression_color", "suspension_rebound_color",
        "suspension_low_speed_threshold", "suspension_velocity_scale", "suspension_bump_color",
        "suspension_bump_force_margin", "suspension_airborne_color", "show_suspension_lap_stats",
        "show_damper_histogram",
    ),
    "show_rpm_leds": (
        "number_of_rpm_leds", "rpm_led_start_ratio", "rpm_led_low_color", "rpm_led_mid_color",
        "rpm_led_high_color", "rpm_led_shift_color",
    ),
    "show_gear": ("show_gear_speed_cluster", "font_scale_gear", "font_color_gear", "enable_gear_rpm_color"),
    "enable_gear_rpm_color": (  # shift flash: of gear RPM color
        "gear_color_low", "gear_color_mid", "gear_color_shift", "gear_mid_rpm_ratio", "enable_shift_flash",
    ),
    "show_speed": ("font_scale_speed", "text_speed"),
    # Labels of ABS, TC, brake bias & migration, limiter also used by setting change pop-up: no control
    "show_abs_indicator": ("abs_active_color",),
    "show_tc_indicator": ("tc_active_color",),
    "show_brake_bias": ("brake_bias_color",),
    "show_brake_migration": ("enable_brake_bias_migration_merge",),
    "show_wheel_locking": ("text_locking",),
    "show_delta_best": ("deltabest_source", "delta_gain_color", "delta_loss_color", "text_delta"),
    "show_laptime": ("text_laptime",),
    "show_pit_limiter_indicator": ("pit_active_color", "limiter_active_color", "text_pit"),
    "show_rpm": ("font_scale_rpm", "rpm_bar_color", "rpm_redline_color", "text_rpm"),
    "show_pedal_bars": ("pedal_input_source", "show_clutch_bar", "throttle_color", "brake_color"),
    "show_setting_change_popup": (
        "setting_popup_duration", "setting_popup_position", "setting_popup_color", "font_color_setting_popup",
        "show_setting_popup_maximum", "enable_setting_popup_direction_color", "show_setting_popup_driving_events",
        "text_tc_slip", "text_tc_cut", "text_front_arb", "text_rear_arb",
    ),
    "enable_setting_popup_direction_color": ("setting_popup_increase_color", "setting_popup_decrease_color"),
    "show_setting_popup_driving_events": ("text_headlights", "text_wipers", "text_state_on", "text_state_off"),
    "show_clutch_bar": ("clutch_color",),
    "show_fuel_gauge": ("fuel_gauge_color", "text_fuel"),
    "show_energy_gauge": ("energy_gauge_color", "text_energy"),
    "show_gauge_start_mark": ("gauge_start_mark_color",),
    "show_gauge_refill_mark": ("gauge_refill_mark_color",),
    "show_stint_comparison": ("text_stint_wear", "text_stint_pressure"),
    "show_battery_bar": (
        "show_battery_percentage", "battery_bar_position", "battery_bar_scale", "font_scale_battery",
        "enable_battery_bar_animation", "battery_idle_color", "battery_charge_color",
        "battery_discharge_color", "show_battery_warning_flash", "battery_low_threshold",
        "battery_high_threshold", "warning_color_low_battery", "warning_color_high_battery",
    ),
    "show_battery_percentage": ("font_scale_battery",),
    "enable_battery_bar_animation": ("battery_bar_animation_speed",),
    "show_battery_warning_flash": (
        "number_of_battery_warning_flashes", "battery_warning_flash_duration", "battery_warning_flash_interval",
    ),
    "show_damage_panel": (
        "damage_panel_position", "damage_panel_scale", "damage_panel_body_color", "damage_panel_body_color_light",
        "damage_panel_body_color_heavy", "damage_panel_body_color_detached", "damage_panel_suspension_color",
        "damage_panel_suspension_color_light", "damage_panel_suspension_color_medium",
        "damage_panel_suspension_color_heavy",  # totaled color also used by coilover damage of suspension view
        "damage_panel_suspension_light_threshold", "damage_panel_suspension_medium_threshold",
        "damage_panel_suspension_heavy_threshold", "damage_panel_suspension_totaled_threshold",
        "damage_panel_wheel_color_detached", "damage_panel_puncture_color", "show_damage_panel_impact_cone",
        "show_damage_panel_integrity",
    ),
    "show_damage_panel_impact_cone": (
        "damage_panel_impact_cone_angle", "damage_panel_impact_cone_duration", "damage_panel_impact_cone_color",
    ),
    "show_damage_panel_integrity": ("show_damage_panel_aero_integrity", "text_integrity_body"),
    "show_damage_panel_aero_integrity": ("text_integrity_aero",),
    "show_incident_recorder": (
        "recorder_duration", "incident_deceleration_threshold", "incident_display_duration",
        "enable_incident_file_export", "incident_export_format", "trace_height_scale", "trace_speed_color",
        "trace_steering_color", "trace_background_color",
        "text_impact", "enable_incident_replay", "show_previous_incident_trace",
    ),
    "show_event_log": (
        "number_of_event_log_lines", "font_color_event_log", "text_damage",
        "show_flag_events", "show_pit_events", "show_penalty_events", "show_engine_overheat_events",
        "show_contact_events",
    ),
    "show_flag_events": ("text_yellow_flag", "text_blue_flag"),
    "show_pit_events": ("text_pit_in", "text_pit_out"),
    "show_penalty_events": ("text_penalty",),  # track limits label also used by track limits points
    "show_engine_overheat_events": ("text_overheat",),
    "show_contact_events": ("text_contact", "text_wall"),
    "enable_incident_file_export": ("incident_export_format",),
}
# Option: on/off option it depends on
BLACK_BOX_DEPENDENCIES = {option: control for control, options in _CONTROLS.items() for option in options}


class OptionUI(NamedTuple):
    """Config dialog extras of a widget with many options"""

    sections: Mapping[str, str]  # first option of section: section title
    basic: frozenset[str]  # options shown in simple mode, besides on/off and choice options
    color_themes: Mapping[str, Mapping[str, str]]  # theme name: default color to theme color
    overrides: Callable[[Mapping], Mapping[str, bool]] | None = None  # options set by a profile
    override_source: str = ""  # option whose value causes the overrides, named in tooltips
    # Values ending the overrides of override source (option set by it edited: its values kept, then edited)
    release: Callable[[Mapping], Mapping[str, object]] | None = None
    dependencies: Mapping[str, str] = {}  # option: on/off option it depends on
    # Sections in page order (title, options), instead of first options of sections; ORDER_LIST among
    # options places the display order list (others: after the last section)
    layout: tuple[tuple[str, tuple[str, ...]], ...] = ()
    order_title: str = ""  # title of display order list (default: "Display Order")
    order_toggles: Mapping[str, str] = {}  # display order option: on/off option of item, switched in the list
    design_order: tuple[str, ...] = ()  # display order options in modern design order (while none changed)
    order_labels: Mapping[str, str] = {}  # display order option: English label of item in the list
    simple_mode: bool = True  # simple mode switch (basic options only)
    # On/off & choice options shown in simple mode (None: every one), see shown_in_mode
    simple_switches: frozenset[str] | None = None
    hidden: frozenset[str] = frozenset()  # options never shown (set by page tools: user profiles...)
    # User profiles: profile name (value of override source): option holding it, saved by profile_text
    user_profiles: Mapping[str, str] = {}
    profile_text: Callable[[Mapping], str] | None = None  # values (overrides applied) as user profile text
    # Part of overlay picture (see black box regions): option shown when clicked in the page preview
    part_options: Mapping[str, str] = {}
    modern_only: bool = False  # declared sections for modern design only (classic: automatic sections)
    # Options doing nothing with these values (dimmed with a note): option -> ("on", control) used only while
    # control is on, or ("off", control) not used while control is on
    inactive: Callable[[Mapping], Mapping[str, tuple[str, str]]] | None = None


ORDER_LIST = "display_order_*"  # layout option standing for the display order list


BLACK_BOX_UI = OptionUI(
    sections=BLACK_BOX_SECTIONS,
    basic=BLACK_BOX_BASIC,
    color_themes=BLACK_BOX_COLOR_THEMES,
    overrides=display_overrides,
    override_source="display_profile",
    release=release_profile,
    dependencies=BLACK_BOX_DEPENDENCIES,
    simple_switches=BLACK_BOX_SIMPLE_SWITCHES,
    hidden=frozenset(USER_PROFILES.values()),
    user_profiles=USER_PROFILES,
    profile_text=format_user_profile,
    part_options={
        "leds": "show_rpm_leds", "wheel0": "show_tyre_temperature", "wheel1": "show_tyre_temperature",
        "wheel2": "show_tyre_temperature", "wheel3": "show_tyre_temperature", "center": "center_column_alignment",
        "status": "show_headlights_indicator", "side_rows": "show_brake_bias", "battery": "show_battery_bar",
        "fuel": "show_fuel_gauge", "energy": "show_energy_gauge", "stint": "show_stint_comparison",
        "damper": "show_damper_histogram", "damage": "show_damage_panel", "trace": "show_incident_recorder",
        "events": "show_event_log",
    },
)
