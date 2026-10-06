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
Modern overlay design: widgets that have one, and options only modern design reads

A widget listed here is drawn by tinypedal.widget._modern.<name> while overlay modern style
is on, unless its "enable_classic_layout" option is set. Plain data only (no Qt import), so
setting templates & config dialog use it without loading widgets.
"""

from types import MappingProxyType

# Common option of modern design widgets: keep classic layout (with modern colors)
CLASSIC_LAYOUT_OPTION = "enable_classic_layout"

# Widget name -> options only read by modern design (added to widget default setting)
MODERN_DESIGN_OPTIONS = MappingProxyType({
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
        "column_best_laptime": False,
        "column_average_laptime": False,
        "column_energy_remaining": False,
        "column_vehicle_integrity": False,
        "column_incidents": False,
        "column_stint_laps": False,
        "column_speed_trap": False,
        "column_lift_and_coast_time": False,
        "column_time_gap": True,
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
        "column_best_laptime": False,
        "column_average_laptime": False,
        "column_delta_laptime": False,
        "column_energy_remaining": False,
        "column_vehicle_integrity": False,
        "column_incidents": False,
        "column_stint_laps": False,
        "column_speed_trap": False,
        "column_lift_and_coast_time": False,
        "column_time_interval": True,
        "column_time_gap": True,
        "show_lap_difference": True,
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
    "deltabest_extended": {},
    "sectors": {},
    "session": {},
    "track_clock": {},
    "laps_and_position": {"show_invalid_lap_indicator": True},
    "lap_time_history": {},
    "stint_history": {},
    "relative_finish_order": {},
    "traffic": {},
    "fuel": {},
    "virtual_energy": {},
    "fuel_energy_saver": {},
    "pit_stop_estimate": {},
    "race_plan": {"show_stint_limit": False, "show_consumption_estimate": False},
    "battery": {"show_state_of_charge": False},  # value scale to check live (LMU), same as battery charge on rF2
    "engine": {"show_game_overheating_warning": True},
    "electric_motor": {},
    "tyre_temperature": {"enable_heatmap_from_optimal_temperature": False},
    "brake_temperature": {},
    "tyre_wear": {},
    "brake_wear": {},
    "pedal": {},
    "gear": {"show_speed_limiter_reminder": True},
    "rpm_led": {},
    "speedometer": {},
    "brake_bias": {},
    "brake_performance": {},
    "damage": {},
    "cruise": {},
    "engine_temperature": {"show_game_overheating_warning": True},
    "force": {},
    "system_performance": {},
    "drs": {},
    "push_to_pass": {},
    "onboard_setting": {},
    "damage_stats": {},
    "differential": {},
    "weather": {"show_wind": True},
    "rake_angle": {},
    "roll_angle": {},
    "weight_distribution": {},
    "wheel_camber": {},
    "wheel_toe": {},
    "acceleration": {},
    "friction_circle": {},
    "heading": {},
    "elevation": {},
    "trailing": {},
    "radar": {},
    "track_map": {},
    "navigation": {},
    "steering_wheel": {},
    "steering_meter": {},
    "instrument": {},
    "weather_forecast": {},
    "flag": {},
    "pace_notes": {},
    "chat": {},
    "black_box": {},
    "track_notes": {},
    "steering_angle": {},
    "lift_and_coast_led": {},
    "suspension_travel": {},
    "tyre_inner_layer": {"enable_heatmap_from_optimal_temperature": False},
    "tyre_carcass": {"enable_heatmap_from_optimal_temperature": False},
    "tyre_pressure": {},
    "tyre_load": {},
    "tyre_deflection": {},
    "brake_pressure": {},
    "ride_height": {"show_axle_ride_height": True},
    "slip_angle": {},
    "slip_ratio": {},
    "suspension_force": {},
    "suspension_position": {},
    # Race aids (modern design first, classic layout kept simple)
    "delta_graph": {},
    "gap_trend": {},
    "pit_lane_helper": {},
    "stint_timer": {},
    "spotter": {},
    "race_notifications": {},
    "tyre_temp_trend": {},
    "telemetry_compare": {},
})

MODERN_DESIGNS = frozenset(MODERN_DESIGN_OPTIONS)


def add_modern_options(defaults: dict):
    """Add modern design options to widget default settings (classic layout switch first)"""
    for name, options in MODERN_DESIGN_OPTIONS.items():
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
