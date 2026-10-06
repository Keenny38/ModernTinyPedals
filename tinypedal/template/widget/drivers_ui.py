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
Driver list widgets (Relative, Standings, Rivals): columns of modern design & Overlay Options layout

Plain data only (no Qt): the modern widgets take their columns from here, the Overlay Options page its
sections. Page layout: rows shown, columns as one list (each column switched on or off and moved),
then options of each column (dimmed while the column is hidden).
"""

from __future__ import annotations

from .black_box_ui import ORDER_LIST, OptionUI

# Columns of modern design, in design order (shown left to right while no display order was changed)
RELATIVE_COLUMNS = (
    "position", "class", "position_change", "driver_name", "vehicle_name", "brand_logo", "tyre_compound",
    "pit_status", "pitstop_count", "laptime", "best_laptime", "average_laptime", "energy_remaining",
    "vehicle_integrity", "incidents", "stint_laps", "speed_trap", "lift_and_coast_time", "time_gap",
)
STANDINGS_COLUMNS = (
    "position", "class", "position_change", "driver_name", "vehicle_name", "brand_logo", "tyre_compound",
    "pit_status", "pitstop_count", "laptime", "best_laptime", "average_laptime", "delta_laptime",
    "energy_remaining", "vehicle_integrity", "incidents", "stint_laps", "speed_trap", "lift_and_coast_time",
    "time_interval", "time_gap",
)
RIVALS_COLUMNS = (
    "position", "class", "position_change", "driver_name", "vehicle_name", "brand_logo", "tyre_compound",
    "pit_status", "pitstop_count", "laptime", "best_laptime", "average_laptime", "delta_laptime",
    "energy_remaining", "vehicle_integrity", "incidents", "stint_laps", "speed_trap", "lift_and_coast_time",
    "time_interval",
)
# Column key -> display order option suffix, if different
DISPLAY_ORDER_NAMES = {"driver_name": "driver", "vehicle_name": "vehicle"}

# Column names (English, translated on page): column list items & titles of column options
COLUMN_TITLES = {
    "position": "Position",
    "class": "Class",
    "position_change": "Position Change",
    "driver_name": "Driver Name",
    "vehicle_name": "Vehicle Name",
    "brand_logo": "Brand Logo",
    "tyre_compound": "Tyre Compound",
    "pit_status": "Pit Status",
    "pitstop_count": "Pit Stops",
    "laptime": "Last Lap Time",
    "best_laptime": "Best Lap Time",
    "average_laptime": "Average Lap Time",
    "delta_laptime": "Delta Lap Time",
    "energy_remaining": "Energy Remaining",
    "vehicle_integrity": "Vehicle Integrity",
    "incidents": "Incidents",
    "stint_laps": "Stint Laps",
    "speed_trap": "Speed Trap",
    "lift_and_coast_time": "Lift & Coast",
    "time_interval": "Interval",
    "time_gap": "Time Gap",
}
# Options of each column (column, options), shown after the column list
COLUMN_OPTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("position_change", ("show_position_change_in_class",)),
    ("driver_name", ("driver_name_shorten", "driver_name_uppercase", "driver_name_width")),
    ("vehicle_name", ("show_vehicle_brand_as_name", "vehicle_name_width")),
    ("brand_logo", ("brand_logo_width",)),
    ("tyre_compound", ("show_compound_for_each_wheel",)),
    ("pit_status", ("pit_status_text", "garage_status_text", "yellow_flag_status_text", "finish_status_text")),
    ("pitstop_count", ("show_pit_request",)),
    ("laptime", ("show_highlighted_fastest_last_laptime", "show_pitstop_duration_while_requested_pitstop")),
    ("best_laptime", ("show_best_laptime_from_recent_laps_in_race",)),
    ("delta_laptime", ("number_of_delta_laptime",)),
    ("incidents", ("incidents_high_threshold", "incidents_extreme_threshold")),
    ("lift_and_coast_time", ("lift_and_coast_reset_threshold", "lift_and_coast_highlight_threshold")),
    ("time_interval", ("show_time_interval_from_same_class", "decimal_places_time_interval",
                       "time_interval_leader_text")),
    ("time_gap", ("show_time_gap_sign", "show_time_gap_from_same_class", "decimal_places_time_gap",
                  "time_gap_leader_text", "show_highlighted_nearest_time_gap", "nearest_time_gap_threshold_front",
                  "nearest_time_gap_threshold_behind")),
)
LAYOUT_SECTION = ("Position & Layout", ("position_x", "position_y", "opacity", "font_size"))
ROW_OPTIONS = ("show_player_highlighted", "show_lap_difference", "show_class_style_for_position_in_class")


def order_option(column: str) -> str:
    """Display order option of column"""
    return f"display_order_{DISPLAY_ORDER_NAMES.get(column, column)}"


def driver_list_ui(columns: tuple[str, ...], rows: tuple[tuple[str, tuple[str, ...]], ...]) -> OptionUI:
    """Overlay Options layout of a driver list widget: rows sections, column list, column options"""
    column_sections = tuple((COLUMN_TITLES[column], options) for column, options in COLUMN_OPTIONS
                            if column in columns)
    dependencies = {option: f"column_{column}" for column, options in COLUMN_OPTIONS if column in columns
                    for option in options}
    return OptionUI(
        sections={},
        basic=frozenset(),
        color_themes={},
        dependencies=dependencies,
        layout=(LAYOUT_SECTION, *rows, ("Columns", (ORDER_LIST,)), *column_sections),
        order_title="Columns",
        order_toggles={order_option(column): f"column_{column}" for column in columns},
        design_order=tuple(order_option(column) for column in columns),
        order_labels={order_option(column): COLUMN_TITLES[column] for column in columns},
        simple_mode=False,
        modern_only=True,
    )


RELATIVE_UI = driver_list_ui(RELATIVE_COLUMNS, (
    ("Rows", ("additional_players_front", "additional_players_behind", "show_vehicle_in_garage", *ROW_OPTIONS)),
))
STANDINGS_UI = driver_list_ui(STANDINGS_COLUMNS, (
    ("Rows", ROW_OPTIONS),
    ("Classes & Number of Cars", (
        "enable_multi_class_split_mode", "maximum_vehicles_split_mode", "maximum_vehicles_per_split_player",
        "maximum_vehicles_per_split_others", "enable_single_class_exclusive_mode", "maximum_vehicles_exclusive_mode",
        "maximum_vehicles_combined_mode", "minimum_top_vehicles",
    )),
))
# Car counts used in their multi class mode only
STANDINGS_UI = STANDINGS_UI._replace(dependencies={
    **STANDINGS_UI.dependencies,
    "maximum_vehicles_split_mode": "enable_multi_class_split_mode",
    "maximum_vehicles_per_split_player": "enable_multi_class_split_mode",
    "maximum_vehicles_per_split_others": "enable_multi_class_split_mode",
    "maximum_vehicles_exclusive_mode": "enable_single_class_exclusive_mode",
})
RIVALS_UI = driver_list_ui(RIVALS_COLUMNS, (
    ("Rows", ROW_OPTIONS),
))
