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
Weather forecast Widget, modern design

Classic drawing with design font & theme colors (see restyle module).
"""

from __future__ import annotations

from ..weather_forecast import Realtime as Classic
from .restyle import Restyled, restyled_options


class Realtime(Restyled, Classic):
    """Draw widget"""

    color_tokens = {
        "background_color_estimated_time": "surface_raised",
        "font_color_estimated_time": "text_dim",
        "background_color_ambient_temperature": "surface_raised",
        "font_color_ambient_temperature": "text",
        "rain_chance_bar_color": "accent",
    }
    options = restyled_options("weather_forecast", color_tokens)
