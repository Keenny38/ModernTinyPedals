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
Regular expression, pattern, string constants
"""

import re
from types import MappingProxyType

from PySide6.QtGui import QFont

from .const_api import API_MAP_ALIAS

# Compiled regex function
rex_hex_color = re.compile(r"^#[0-9A-F]{3}$|^#[0-9A-F]{6}$|^#[0-9A-F]{8}$", flags=re.IGNORECASE)
rex_invalid_char = re.compile(r'[\\/:*?"<>|]')
rex_special_char = re.compile(r'[\\/:*?"<>|!@#$%^&\'{}~`;]')
rex_number_extract = re.compile(r"\d*\.?\d+")
rex_lmu_brand_extract = re.compile(r"^([a-zA-Z-]{2,})(\s[A-Z][a-z]{2,}\s)?")

# Group key, for splitting and display option group name
CFG_GROUP_KEY = (
    "^decimal_places_|"
    "^display_order_|"
    "^enable_|"
    "^notify_|"
    "^prefix_|"
    "^show_"
)

# Bool
CFG_BOOL = (
    # Exact match
    "^active_state$|"
    "^auto_hide$|"
    "^check_for_updates_on_startup$|"
    "^fixed_position$|"
    "^global$|"
    "^minimize_to_tray$|"
    "^remember_position$|"
    "^remember_size$|"
    "^save_invalid_laps$|"
    "^vr_compatibility$|"
    # Partial match
    "^notify_|"
    "align_center|"
    "enable|"
    "shorten|"
    "show|"
    "swap_upper_caption|"
    "swap_lower_caption|"
    "swap_style|"
    "uppercase"
)

# String with unique validator
CFG_COLOR = "color"
CFG_CLOCK_FORMAT = "clock_format"

# String choice
CFG_API_NAME = "api_name"
CFG_BAR_POSITION = "bar_position"
CFG_CHARACTER_ENCODING = "character_encoding"
CFG_COLUMN_ALIGNMENT = "column_alignment"
CFG_DELTABEST_SOURCE = "deltabest_source"
CFG_FONT_WEIGHT = "font_weight"
CFG_TARGET_LAPTIME = "target_laptime"
CFG_TEXT_ALIGNMENT = "text_alignment"
CFG_STATS_CLASSIFICATION = "vehicle_classification"
CFG_WINDOW_COLOR_THEME = "window_color_theme"
CFG_OVERLAY_THEME = "^overlay_theme$"  # built-in & custom theme names, see widget._style
CFG_WIDGET_THEME = "^widget_theme$"  # per widget theme, "Global" = use overlay theme
CFG_LANGUAGE = "^language$"

# String common
CFG_FONT_NAME = "font_name"
CFG_HEATMAP = "heatmap"
CFG_USER_PATH = "_path"
CFG_USER_IMAGE = "_image_file"
CFG_STRING = (
    # Exact match
    "^bind$|"
    "^preset$|"
    "^process_id$|"
    "^version$|"
    # Partial match
    "by_class|"
    "by_compound|"
    "file_name|"
    "prefix|"
    "repository|"
    "sound_format|"
    "suffix|"
    "symbol|"
    "text|"
    "unit|"
    "url_host"
)

# Integer
CFG_INTEGER = (
    # Exact match
    "^access_mode$|"
    "^display_orientation$|"
    "^electric_braking_allocation$|"
    "^grid_move_size$|"
    "^lap_time_history_count$|"
    "^leading_zero$|"
    "^manual_steering_range$|"
    "^maximum_loading_attempts$|"
    "^maximum_saving_attempts$|"
    "^player_index$|"
    "^parts_width$|"
    "^parts_maximum_height$|"
    "^parts_maximum_width$|"
    "^position_x$|"
    "^position_y$|"
    "^remote_control_port$|"
    "^snap_distance$|"
    "^snap_gap$|"
    "^stint_history_count$|"
    "^tyre_compound_spacing$|"
    "^window_width$|"
    "^window_height$|"
    "^last_page_index$|"
    # Partial match
    "area_margin|"
    "area_size|"
    "bar_edge_width|"
    "bar_gap|"
    "bar_height|"
    "bar_length|"
    "bar_width|"
    "display_order|"
    "decimal_places|"
    "digits|"
    "display_detail_level|"
    "display_height|"
    "display_margin|"
    "display_size|"
    "display_width|"
    "draw_order_index|"
    "font_size|"
    "horizontal_gap|"
    "icon_size|"
    "inner_gap|"
    "double_side_led_gap|"
    "layout|"
    "maximum_paused_frames|"
    "maximum_queue|"
    "number_of|"
    "samples|"
    "sampling_interval|"
    "sound_volume|"
    "split_gap|"
    "update_interval|"
    "url_port|"
    "vehicles|"
    "vertical_gap"
)

# Filename
CFG_INVALID_FILENAME = (
    # Exact match
    "^$|"
    "^brakes$|"
    "^brands$|"
    "^classes$|"
    "^compounds$|"
    "^config$|"
    "^heatmap$|"
    "^shortcuts$|"
    "^tracks$|"
    # Partial match
    "backup"
)

# Abbreviation
ABBR_PATTERN = "|".join(
    f"\\b{abbr}\\b"
    for abbr in (
        "id",
        "ui",
        "vr",
        "led",
        "tc",
        "abs",
        "arb",
        "api",
        "dpi",
        "drs",
        "ffb",
        "lmu",
        "rpm",
        "rf2",
        "url",
    )
)


# Font weight
FONT_WEIGHT_MAP = MappingProxyType({
    "Thin": QFont.Weight.Thin,
    "Extra Light": QFont.Weight.ExtraLight,
    "Light": QFont.Weight.Light,
    "Normal": QFont.Weight.Normal,
    "Medium": QFont.Weight.Medium,
    "Semi Bold": QFont.Weight.DemiBold,
    "Bold": QFont.Weight.Bold,
    "Extra Bold": QFont.Weight.ExtraBold,
    "Black": QFont.Weight.Black,
})

# Choice dictionary
CHOICE_UNITS = MappingProxyType({
    "distance_unit": ("Meter", "Feet"),
    "fuel_unit": ("Liter", "Gallon"),
    "odometer_unit": ("Kilometer", "Mile", "Meter"),
    "power_unit": ("Kilowatt", "Horsepower", "Metric Horsepower"),
    "speed_unit": ("KPH", "MPH", "m/s"),
    "temperature_unit": ("Celsius", "Fahrenheit"),
    "turbo_pressure_unit": ("bar", "psi", "kPa"),
    "tyre_pressure_unit": ("kPa", "psi", "bar"),
    "weight_unit": ("Kilogram", "Pound"),
})
CHOICE_COMMON = MappingProxyType({
    CFG_API_NAME: tuple(API_MAP_ALIAS),
    CFG_BAR_POSITION: ("Left", "Right"),
    CFG_CHARACTER_ENCODING: ("UTF-8", "ISO-8859-1"),
    CFG_COLUMN_ALIGNMENT: ("Centered", "Justified"),
    CFG_DELTABEST_SOURCE: ("Best", "Session", "Stint", "Last"),
    CFG_FONT_WEIGHT: tuple(FONT_WEIGHT_MAP),
    CFG_TARGET_LAPTIME: ("Theoretical", "Personal"),
    CFG_TEXT_ALIGNMENT: ("Left", "Center", "Right"),
    CFG_STATS_CLASSIFICATION: ("Class - Brand", "Class", "Vehicle"),
    CFG_WINDOW_COLOR_THEME: ("Light", "Dark", "System"),
    CFG_LANGUAGE: ("English", "Français"),
    "^display_profile$": ("Custom", "Minimal", "Sprint", "Endurance"),
    "^tyre_temperature_source$": ("Inner layer", "Carcass", "Surface"),
    "^tyre_load_display$": ("Percent", "Kilogram", "Newton"),
    "^brake_wear_display$": ("Percent", "Laps"),
    "^pedal_input_source$": ("Raw", "Filtered"),
    "^incident_export_format$": ("JSON", "CSV", "Both"),
    "^status_icons_side$": ("Left", "Right"),
    "^damage_panel_position$": ("Bottom Right", "Bottom Left", "Top Right", "Top Left"),
    "^resize_anchor$": ("Top Left", "Top Center", "Top Right", "Bottom Left", "Bottom Center", "Bottom Right"),
    # Per widget unit, "Global" = use Units setting
    "^override_unit_temperature$": ("Global", *CHOICE_UNITS["temperature_unit"]),
    "^override_unit_tyre_pressure$": ("Global", *CHOICE_UNITS["tyre_pressure_unit"]),
    "^override_unit_speed$": ("Global", *CHOICE_UNITS["speed_unit"]),
    "^override_unit_fuel$": ("Global", *CHOICE_UNITS["fuel_unit"]),
})

# Misc
COMMON_TYRE_COMPOUNDS = (
    ("super", "Q"),  # super soft
    ("inter", "I"),  # intermediate
    ("soft", "S"),
    ("med", "M"),  # medium
    ("hard", "H"),
    ("rain|wet", "W"),
    ("slick|dry", "S"),
    ("oval", "O"),
    ("road|radial|tread", "R"),
    ("bias", "B"),  # bias ply
)
