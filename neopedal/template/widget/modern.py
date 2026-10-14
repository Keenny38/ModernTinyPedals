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
Modern overlay design: widgets that have one, and options only modern design reads

A widget declared with a modern design (registry.OverlaySpec.has_modern) is drawn by
neopedal.widget._modern.<name> while overlay modern style is on, unless its "enable_classic_layout"
option is set. Plain data only (no Qt import), so setting templates & config dialog use it without
loading widgets.
"""

from types import MappingProxyType
from typing import Any

from .registry import OVERLAYS, OverlaySpec

# Common option of modern design widgets: keep classic layout (with modern colors)
CLASSIC_LAYOUT_OPTION = "enable_classic_layout"

# Widget name -> options only read by modern design (added to widget default setting),
# widgets of modern design with no such option left out
MODERN_ONLY_OPTIONS: MappingProxyType[str, dict[str, Any]] = MappingProxyType({
    "relative": {
        "column_position": True,
        "column_class": True,
        "column_position_change": False,
        "column_driver_name": True,
        "column_vehicle_name": False,
        "column_brand_logo": True,
        "column_tyre_compound": True,
        "column_pit_status": True,
        "column_pitstop_count": False,
        "column_laptime": True,
        "show_lap_sectors": True,
        "show_lap_delta": True,
        "show_out_and_in_laps": True,
        "show_invalid_lap_in_red": True,
        "show_lap_trend": True,
        "show_running_lap_time": True,
        "column_best_laptime": False,
        "column_average_laptime": False,
        "column_energy_remaining": False,
        "column_vehicle_integrity": False,
        "column_incidents": False,
        "column_stint_laps": False,
        "column_speed_trap": False,
        "column_lift_and_coast_time": False,
        "column_time_gap": True,
        "column_gap_trend": True,
    },
    "standings": {
        "column_position": True,
        "column_class": True,
        "column_position_change": False,
        "column_driver_name": True,
        "column_vehicle_name": False,
        "column_brand_logo": True,
        "column_tyre_compound": True,
        "column_pit_status": True,
        "column_pitstop_count": True,
        "column_laptime": True,
        "show_lap_sectors": True,
        "show_lap_delta": True,
        "show_out_and_in_laps": True,
        "show_invalid_lap_in_red": True,
        "show_lap_trend": True,
        "show_running_lap_time": True,
        "column_best_laptime": False,
        "column_average_laptime": False,
        "column_delta_laptime": False,
        "column_energy_remaining": False,
        "column_vehicle_integrity": False,
        "column_energy_per_lap": False,
        "show_energy_per_lap_average": False,
        "column_incidents": False,
        "column_track_limits": False,
        "column_stint_laps": False,
        "column_speed_trap": False,
        "column_lift_and_coast_time": False,
        "column_time_interval": True,
        "column_time_gap": True,
        "show_lap_difference": True,
        "show_class_header": True,
        "show_column_headers": True,
    },
    "rivals": {
        "column_position": True,
        "column_class": True,
        "column_position_change": False,
        "column_driver_name": True,
        "column_vehicle_name": False,
        "column_brand_logo": True,
        "column_tyre_compound": True,
        "column_pit_status": True,
        "column_pitstop_count": True,
        "column_laptime": True,
        "show_lap_sectors": True,
        "show_lap_delta": True,
        "show_out_and_in_laps": True,
        "show_invalid_lap_in_red": True,
        "show_lap_trend": True,
        "show_running_lap_time": True,
        "column_best_laptime": False,
        "column_average_laptime": False,
        "column_delta_laptime": True,
        "column_energy_remaining": False,
        "column_vehicle_integrity": False,
        "column_incidents": False,
        "column_stint_laps": False,
        "column_speed_trap": False,
        "column_lift_and_coast_time": False,
        "column_time_interval": True,
        "show_player_highlighted": True,
        "show_lap_difference": True,
        "show_highlighted_fastest_last_laptime": True,
    },
    "timing": {"show_invalid_lap_indicator": True},
    "deltabest": {"show_invalid_lap_indicator": True},
    "laps_and_position": {"show_invalid_lap_indicator": True},
    "race_plan": {"show_stint_limit": False, "show_consumption_estimate": False},
    "battery": {"show_state_of_charge": False},  # value scale to check live (LMU), same as battery charge on rF2
    "engine": {"show_game_overheating_warning": True},
    "tyre_temperature": {"enable_heatmap_from_optimal_temperature": False},
    "gear": {"show_speed_limiter_reminder": True},
    "engine_temperature": {"show_game_overheating_warning": True},
    "weather": {"show_wind": True},
    "track_map": {
        "show_sector_performance": True,
        "show_nearby_vehicle_highlight": True,
        "nearby_vehicle_threshold": 1.0,
    },
    "tyre_inner_layer": {"enable_heatmap_from_optimal_temperature": False},
    "tyre_carcass": {"enable_heatmap_from_optimal_temperature": False},
    "ride_height": {"show_axle_ride_height": True},
})


def modern_design_options(overlays: tuple[OverlaySpec, ...] = OVERLAYS) -> dict[str, dict[str, Any]]:
    """Widget name -> options only read by modern design, for every widget having a modern design"""
    unknown = sorted(set(MODERN_ONLY_OPTIONS) - {spec.name for spec in OVERLAYS if spec.has_modern})
    if unknown:
        raise RuntimeError(f"modern options of widgets without modern design: {unknown}")
    return {spec.name: MODERN_ONLY_OPTIONS.get(spec.name, {}) for spec in overlays if spec.has_modern}


# Widget name -> options only read by modern design, every widget having a modern design (display order)
MODERN_DESIGN_OPTIONS: MappingProxyType[str, dict[str, Any]] = MappingProxyType(modern_design_options())
MODERN_DESIGNS = frozenset(MODERN_DESIGN_OPTIONS)


def add_modern_options(defaults: dict, overlays: tuple[OverlaySpec, ...] = OVERLAYS):
    """Add modern design options to widget default settings (classic layout switch first)"""
    for name, options in modern_design_options(overlays).items():
        setting = defaults.get(name)
        if setting is None:
            continue
        merged = {}
        for key, value in setting.items():
            merged[key] = value
            if key == "enable":
                merged[CLASSIC_LAYOUT_OPTION] = False
        merged.update((key, value) for key, value in options.items() if key not in merged)
        setting.clear()
        setting.update(merged)
