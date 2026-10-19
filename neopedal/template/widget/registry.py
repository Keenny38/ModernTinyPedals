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
Overlay registry: every built-in overlay declared once

OVERLAYS lists every built-in overlay in display order (UI lists, keyboard shortcuts). Display order,
widget default settings (template.setting_widget), modern designs (modern.MODERN_DESIGNS), config
dialog extras, Overlays page categories & simulated race preview feeds are derived from it.
Default options stay in the template module of each group (brakes.py, tyres.py...), found by name.
Plain data only (no Qt import, widget modules never imported): widget "neopedal.widget.<name>" is
loaded by name when the overlay starts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .black_box_ui import BLACK_BOX_UI, OptionUI
from .brakes import WIDGET_BRAKES
from .chassis import WIDGET_CHASSIS
from .driver import WIDGET_DRIVER
from .drivers_ui import RELATIVE_UI, RIVALS_UI, STANDINGS_UI
from .engine import WIDGET_ENGINE
from .fuel import WIDGET_FUEL
from .race_aids import WIDGET_RACE_AIDS
from .standings import WIDGET_STANDINGS
from .timing import WIDGET_TIMING
from .track import WIDGET_TRACK
from .tyres import WIDGET_TYRES

# Template modules holding default options of their overlays: group name -> {overlay name: default options}
TEMPLATE_GROUPS: Mapping[str, dict[str, dict[str, Any]]] = MappingProxyType({
    "brakes": WIDGET_BRAKES,
    "tyres": WIDGET_TYRES,
    "chassis": WIDGET_CHASSIS,
    "engine": WIDGET_ENGINE,
    "fuel": WIDGET_FUEL,
    "timing": WIDGET_TIMING,
    "standings": WIDGET_STANDINGS,
    "track": WIDGET_TRACK,
    "driver": WIDGET_DRIVER,
    "race_aids": WIDGET_RACE_AIDS,
})

# Overlays page categories (chips order) & colors, readable on light & dark theme
TIMING = "Timing"
TYRES = "Tyres & Wheels"
BRAKES = "Brakes"
INPUTS = "Driver Inputs"
ENGINE = "Engine & Energy"
CHASSIS = "Chassis"
TRACK = "Track & Traffic"
OTHER = "Other"  # plugins & overlays of no category
CATEGORY_COLORS: Mapping[str, str] = MappingProxyType({
    TIMING: "#4C8DFF",
    TYRES: "#A371F7",
    BRAKES: "#E5534B",
    INPUTS: "#3FB950",
    ENGINE: "#F0883E",
    CHASSIS: "#22B8C8",
    TRACK: "#D4A72C",
    OTHER: "#8B949E",
})

# Overlay previews on simulated race (see demo_data.update_widget)
DEMO_HISTORY = "history"  # draws recent inputs: fed a corner before drawn
DEMO_LAP = "lap"  # draws delta over the lap: fed last lap and current lap so far
DEMO_SAMPLE = "sample"  # draws a sample of every item before first update (nothing to show on this data)
DEMO_FEEDS = ("", DEMO_HISTORY, DEMO_LAP, DEMO_SAMPLE)


@dataclass(frozen=True)
class OverlaySpec:
    """Built-in overlay

    Args:
        name: Widget name: setting key, "neopedal.widget.<name>" module (and "widget._modern.<name>").
        category: Overlays page category (see CATEGORY_COLORS).
        has_modern: Drawn by modern design while overlay modern style is on (options only read by modern
            design in modern.MODERN_ONLY_OPTIONS).
        demo: Simulated race feed of preview (DEMO_xxx, "" for none).
        option_ui: Config dialog extras for overlays with many options (see black_box_ui.OptionUI).
        template: Template group holding default options (see TEMPLATE_GROUPS).
        defaults: Default options (template dict, modern & common options added by setting_widget).
    """

    name: str
    category: str
    has_modern: bool = True
    demo: str = ""
    option_ui: OptionUI | None = field(default=None, compare=False, repr=False)
    template: str = ""
    defaults: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


def overlay(
    name: str, category: str, *, has_modern: bool = True, demo: str = "", option_ui: OptionUI | None = None,
    groups: Mapping[str, Mapping[str, dict[str, Any]]] = TEMPLATE_GROUPS,
) -> OverlaySpec:
    """Overlay spec, default options found by name in template groups (must be in exactly one)"""
    found = [group for group, widgets in groups.items() if name in widgets]
    if len(found) != 1:
        raise RuntimeError(f"overlay {name} must have default options in one template group, found in {found}")
    if category not in CATEGORY_COLORS or demo not in DEMO_FEEDS:
        raise RuntimeError(f"overlay {name}: unknown category {category!r} or demo feed {demo!r}")
    return OverlaySpec(name, category, has_modern, demo, option_ui, found[0], groups[found[0]][name])


# Every built-in overlay, in display order (UI lists, keyboard shortcuts)
OVERLAYS: tuple[OverlaySpec, ...] = (
    overlay("acceleration", CHASSIS),
    overlay("battery", ENGINE),
    overlay("brake_bias", BRAKES),
    overlay("brake_performance", BRAKES),
    overlay("brake_pressure", BRAKES),
    overlay("brake_temperature", BRAKES),
    overlay("brake_wear", BRAKES),
    overlay("chat", TRACK, demo=DEMO_SAMPLE),
    overlay("corner_coach", INPUTS),
    overlay("cruise", ENGINE),
    overlay("damage", CHASSIS),
    overlay("damage_stats", CHASSIS),
    overlay("delta_graph", TIMING, demo=DEMO_LAP),
    overlay("deltabest", TIMING),
    overlay("deltabest_extended", TIMING),
    overlay("differential", CHASSIS),
    overlay("driver_rank", TIMING),
    overlay("drs", ENGINE),
    overlay("electric_motor", ENGINE),
    overlay("elevation", TRACK),
    overlay("engine", ENGINE),
    overlay("engine_temperature", ENGINE),
    overlay("flag", TRACK, demo=DEMO_SAMPLE),
    overlay("force", CHASSIS),
    overlay("friction_circle", TYRES, demo=DEMO_HISTORY),
    overlay("fuel", ENGINE),
    overlay("fuel_energy_saver", ENGINE),
    overlay("gap_trend", TIMING),
    overlay("gear", ENGINE),
    overlay("heading", TRACK),
    overlay("instrument", ENGINE),
    overlay("laps_and_position", TIMING),
    overlay("lap_time_history", TIMING),
    overlay("lift_and_coast_led", ENGINE),
    overlay("navigation", TRACK),
    overlay("onboard_setting", INPUTS),
    overlay("pace_notes", TRACK),
    overlay("pedal", INPUTS),
    overlay("pit_lane_helper", TRACK),
    overlay("pit_stop_estimate", TIMING),
    overlay("push_to_pass", ENGINE),
    overlay("race_notifications", TRACK, demo=DEMO_SAMPLE),
    overlay("race_plan", TIMING),
    overlay("radar", TRACK),
    overlay("rake_angle", CHASSIS),
    overlay("relative", TIMING, option_ui=RELATIVE_UI),
    overlay("relative_finish_order", TIMING),
    overlay("ride_height", CHASSIS),
    overlay("rivals", TIMING, option_ui=RIVALS_UI),
    overlay("roll_angle", CHASSIS),
    overlay("rpm_led", ENGINE),
    overlay("sectors", TIMING),
    overlay("session", TIMING),
    overlay("slip_angle", TYRES),
    overlay("slip_ratio", TYRES),
    overlay("speed_delta", TIMING),
    overlay("speedometer", ENGINE),
    overlay("spotter", TRACK, demo=DEMO_SAMPLE),
    overlay("standings", TIMING, option_ui=STANDINGS_UI),
    overlay("steering_angle", INPUTS),
    overlay("steering_meter", INPUTS),
    overlay("steering_wheel", INPUTS),
    overlay("stint_history", TIMING),
    overlay("stint_timer", TIMING),
    overlay("suspension_force", CHASSIS),
    overlay("suspension_position", CHASSIS),
    overlay("suspension_travel", CHASSIS),
    overlay("system_performance", OTHER),
    overlay("telemetry_compare", INPUTS),
    overlay("timing", TIMING),
    overlay("track_clock", TIMING),
    overlay("track_map", TRACK),
    overlay("track_notes", TRACK),
    overlay("traffic", TRACK),
    overlay("trailing", INPUTS, demo=DEMO_HISTORY),
    overlay("tyre_carcass", TYRES),
    overlay("tyre_deflection", TYRES),
    overlay("tyre_inner_layer", TYRES),
    overlay("tyre_load", TYRES),
    overlay("tyre_overview", TYRES),
    overlay("tyre_pressure", TYRES),
    overlay("tyre_temp_trend", TYRES),
    overlay("tyre_temperature", TYRES),
    overlay("tyre_wear", TYRES),
    overlay("virtual_energy", ENGINE),
    overlay("weather", TRACK),
    overlay("weather_forecast", TRACK),
    overlay("weight_distribution", CHASSIS),
    overlay("wheel_camber", TYRES),
    overlay("black_box", TRACK, option_ui=BLACK_BOX_UI),
    overlay("wheel_dimension", TYRES),
    overlay("wheel_toe", TYRES),
    overlay("wind_direction", TRACK),
)


def check_overlays(overlays: tuple[OverlaySpec, ...], groups: Mapping[str, Mapping[str, Any]] = TEMPLATE_GROUPS):
    """Raise if an overlay is declared twice, or has default options but no spec"""
    names = [spec.name for spec in overlays]
    if len(set(names)) != len(names):
        raise RuntimeError(f"overlay declared twice: {sorted({name for name in names if names.count(name) > 1})}")
    missing = sorted(name for widgets in groups.values() for name in widgets if name not in set(names))
    if missing:
        raise RuntimeError(f"overlay default options without spec in registry.OVERLAYS: {missing}")


def display_order(overlays: tuple[OverlaySpec, ...] = OVERLAYS) -> tuple[str, ...]:
    """Overlay names in display order"""
    return tuple(spec.name for spec in overlays)


def category_of(overlays: tuple[OverlaySpec, ...] = OVERLAYS) -> dict[str, str]:
    """Overlays page category by overlay name"""
    return {spec.name: spec.category for spec in overlays}


def demo_names(feed: str, overlays: tuple[OverlaySpec, ...] = OVERLAYS) -> tuple[str, ...]:
    """Overlay names previewed with simulated race feed (see DEMO_xxx), in display order"""
    return tuple(spec.name for spec in overlays if spec.demo == feed)


def option_ui_of(overlays: tuple[OverlaySpec, ...] = OVERLAYS) -> dict[str, OptionUI]:
    """Config dialog extras by overlay name"""
    return {spec.name: spec.option_ui for spec in overlays if spec.option_ui is not None}


check_overlays(OVERLAYS)
