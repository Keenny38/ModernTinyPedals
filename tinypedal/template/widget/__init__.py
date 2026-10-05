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
Default widget setting templates, grouped by category

Each module holds default options of its widgets, merged here into WIDGET_CATEGORIES.
WIDGET_DISPLAY_ORDER sets the order of widget list in UI & keybinding, and must list every widget.
"""

from .black_box_ui import BLACK_BOX_UI
from .brakes import WIDGET_BRAKES
from .chassis import WIDGET_CHASSIS
from .driver import WIDGET_DRIVER
from .engine import WIDGET_ENGINE
from .fuel import WIDGET_FUEL
from .standings import WIDGET_STANDINGS
from .timing import WIDGET_TIMING
from .track import WIDGET_TRACK
from .tyres import WIDGET_TYRES

WIDGET_CATEGORIES = (
    WIDGET_BRAKES,
    WIDGET_TYRES,
    WIDGET_CHASSIS,
    WIDGET_ENGINE,
    WIDGET_FUEL,
    WIDGET_TIMING,
    WIDGET_STANDINGS,
    WIDGET_TRACK,
    WIDGET_DRIVER,
)

# Config dialog extras for widgets with many options: sections, simple mode, color themes,
# profile overrides (see black_box_ui.OptionUI)
WIDGET_OPTION_UI = {
    "black_box": BLACK_BOX_UI,
}
# Config dialog sections per widget: {widget: {first option of section: section title}}
WIDGET_OPTION_SECTIONS = {name: ui.sections for name, ui in WIDGET_OPTION_UI.items()}

# Display order of widget list (UI, keyboard shortcuts)
WIDGET_DISPLAY_ORDER = (
    "acceleration",
    "battery",
    "brake_bias",
    "brake_performance",
    "brake_pressure",
    "brake_temperature",
    "brake_wear",
    "chat",
    "cruise",
    "damage",
    "damage_stats",
    "deltabest",
    "deltabest_extended",
    "differential",
    "drs",
    "electric_motor",
    "elevation",
    "engine",
    "engine_temperature",
    "flag",
    "force",
    "friction_circle",
    "fuel",
    "fuel_energy_saver",
    "gear",
    "heading",
    "instrument",
    "laps_and_position",
    "lap_time_history",
    "lift_and_coast_led",
    "navigation",
    "onboard_setting",
    "pace_notes",
    "pedal",
    "pit_stop_estimate",
    "push_to_pass",
    "race_plan",
    "radar",
    "rake_angle",
    "relative",
    "relative_finish_order",
    "ride_height",
    "rivals",
    "roll_angle",
    "rpm_led",
    "sectors",
    "session",
    "slip_angle",
    "slip_ratio",
    "speedometer",
    "standings",
    "steering_angle",
    "steering_meter",
    "steering_wheel",
    "stint_history",
    "suspension_force",
    "suspension_position",
    "suspension_travel",
    "system_performance",
    "timing",
    "track_clock",
    "track_map",
    "track_notes",
    "traffic",
    "trailing",
    "tyre_carcass",
    "tyre_deflection",
    "tyre_inner_layer",
    "tyre_load",
    "tyre_pressure",
    "tyre_temperature",
    "tyre_wear",
    "virtual_energy",
    "weather",
    "weather_forecast",
    "weight_distribution",
    "wheel_camber",
    "black_box",
    "wheel_toe",
)
