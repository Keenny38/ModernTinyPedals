#  TinyPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of TinyPedal.
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
    "display_order_abs": "Center Column Order",
}

# Options shown in simple mode besides every on/off and choice option: the ones people
# commonly adjust. Colors, thresholds, fine scales and labels stay in advanced mode.
BLACK_BOX_BASIC = frozenset((
    "position_x", "position_y", "font_name", "font_size", "font_weight", "opacity",
    "background_color", "font_color", "caption_text",
    "display_scale", "fixed_width", "fixed_height",
    "maximum_wheel_angle", "tyre_pressure_target_minimum", "tyre_pressure_target_maximum",
    "tyre_target_by_compound", "gauge_low_lap_threshold", "suspension_motion_scale",
    "damage_panel_scale", "number_of_event_log_lines", "number_of_rpm_leds",
))


# Compound targets: "S=160-190/75-100; W=150-175" (pressure kPa, then optional temperature Celsius)
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


def display_overrides(wcfg: Mapping) -> dict[str, bool]:
    """Options overridden by display profile, then by auto compact mode"""
    overrides = dict(DISPLAY_PROFILES.get(wcfg["display_profile"], {}))
    threshold = wcfg["auto_compact_display_scale"]
    if 0 < wcfg["display_scale"] < threshold:
        overrides.update(dict.fromkeys(COMPACT_HIDDEN, False))
    return overrides


# Color themes: each default color mapped to the theme color with the same meaning
# (red warning & hot, cyan cold & low, green good, orange & yellow in between, blue, magenta)
_DEFAULT_ROLES = ("#FF3D3D", "#3DC8FF", "#2FC46A", "#FF9F1C", "#FFC400", "#3D8BFF", "#B0106A")


def _theme(*colors: str) -> dict[str, str]:
    return dict(zip(_DEFAULT_ROLES, colors))


BLACK_BOX_COLOR_THEMES: dict[str, dict[str, str]] = {
    "Default": {},
    "High Contrast": _theme("#FF0000", "#00E5FF", "#00FF55", "#FF8800", "#FFEE00", "#2979FF", "#FF00CC"),
    "Colorblind Safe": _theme("#D55E00", "#56B4E9", "#009E73", "#E69F00", "#F0E442", "#0072B2", "#CC79A7"),
    "Soft": _theme("#E06C75", "#56B6C2", "#98C379", "#D19A66", "#E5C07B", "#61AFEF", "#C678DD"),
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
    "show_tyre_temperature": (
        "tyre_temperature_warning_threshold", "font_color_tyre_temperature_warning",
        "tyre_temperature_cold_threshold", "font_color_tyre_temperature_cold",
        "font_color_tyre_temperature_warming", "show_tyre_temperature_trend",
    ),
    "show_tyre_temperature_trend": ("tyre_heat_trend_threshold",),
    "show_tyre_pressure": (
        "enable_tyre_pressure_target", "tyre_pressure_low_color", "tyre_pressure_high_color",
        "tyre_pressure_warning_background_color", "show_tyre_pressure_trend",
    ),
    "enable_tyre_pressure_target": ("tyre_pressure_target_minimum", "tyre_pressure_target_maximum"),
    "show_tyre_pressure_trend": ("tyre_pressure_trend_threshold",),
    "show_tyre_wear": ("tyre_wear_warning_threshold", "tyre_wear_warning_color", "font_color_tyre_wear_warning"),
    "show_tyre_status": (
        "flat_spot_threshold", "wheel_puncture_color", "wheel_flat_spot_color", "wheel_detached_color",
        "text_puncture", "text_flat_spot", "text_detached",
    ),
    "show_brake_temperature": (
        "brake_temperature_cold_threshold", "brake_temperature_hot_threshold", "brake_target_by_class",
        "show_brake_temperature_trend",
        "font_color_brake_temperature_cold", "font_color_brake_temperature_hot",
    ),
    "show_brake_temperature_trend": ("brake_trend_duration", "brake_heat_trend_threshold"),
    "show_tyre_load": ("tyre_load_display",),
    "show_brake_wear": ("brake_wear_warning_threshold", "font_color_brake_wear_warning"),
    "show_brake_pressure": ("brake_pressure_color",),
    "show_suspension": (
        "suspension_scale", "suspension_motion_scale", "enable_wheel_suspension_motion", "show_coilover_damage",
        "suspension_spring_color", "suspension_compression_color", "suspension_rebound_color",
        "suspension_low_speed_threshold", "suspension_velocity_scale", "suspension_bump_color",
        "suspension_bump_force_margin", "suspension_airborne_color",
    ),
    "show_rpm_leds": (
        "number_of_rpm_leds", "rpm_led_start_ratio", "rpm_led_low_color", "rpm_led_mid_color",
        "rpm_led_high_color", "rpm_led_shift_color",
    ),
    "show_gear": (
        "show_gear_speed_cluster", "font_scale_gear", "font_color_gear", "enable_gear_rpm_color",
        "enable_shift_flash",
    ),
    "enable_gear_rpm_color": ("gear_color_low", "gear_color_mid", "gear_color_shift", "gear_mid_rpm_ratio"),
    "show_speed": ("font_scale_speed", "text_speed"),
    "show_abs_indicator": ("abs_active_color", "text_abs"),
    "show_tc_indicator": ("tc_active_color", "text_tc"),
    "show_brake_bias": ("text_brake_bias",),
    "show_brake_migration": ("text_brake_migration",),
    "show_wheel_locking": ("text_locking",),
    "show_delta_best": ("delta_gain_color", "delta_loss_color", "text_delta"),
    "show_laptime": ("text_laptime",),
    "show_pit_limiter_indicator": ("pit_active_color", "limiter_active_color", "text_pit", "text_limiter"),
    "show_rpm": ("font_scale_rpm", "rpm_bar_color", "rpm_redline_color", "text_rpm"),
    "show_pedal_bars": ("throttle_color", "brake_color"),
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
        "damage_panel_suspension_color_heavy", "damage_panel_suspension_color_totaled",
        "damage_panel_suspension_light_threshold", "damage_panel_suspension_medium_threshold",
        "damage_panel_suspension_heavy_threshold", "damage_panel_suspension_totaled_threshold",
        "damage_panel_wheel_color_detached", "damage_panel_puncture_color", "show_damage_panel_impact_cone",
        "show_damage_panel_integrity",
    ),
    "show_damage_panel_impact_cone": (
        "damage_panel_impact_cone_angle", "damage_panel_impact_cone_duration", "damage_panel_impact_cone_color",
    ),
    "show_damage_panel_integrity": ("show_damage_panel_aero_integrity", "text_integrity_body", "text_integrity_aero"),
    "show_incident_recorder": (
        "recorder_duration", "incident_deceleration_threshold", "incident_display_duration",
        "enable_incident_file_export", "trace_height_scale", "trace_speed_color", "trace_background_color",
        "text_impact",
    ),
    "show_event_log": ("number_of_event_log_lines", "font_color_event_log", "text_damage"),
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
    dependencies: Mapping[str, str] = {}  # option: on/off option it depends on


BLACK_BOX_UI = OptionUI(
    sections=BLACK_BOX_SECTIONS,
    basic=BLACK_BOX_BASIC,
    color_themes=BLACK_BOX_COLOR_THEMES,
    overrides=display_overrides,
    override_source="display_profile",
    dependencies=BLACK_BOX_DEPENDENCIES,
)
