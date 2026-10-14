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
Tyre temperature Widget
"""

from typing import TYPE_CHECKING

from ._tyre_temps import LayerTemperature

if TYPE_CHECKING:
    from ..template.widget_config_types import TyreTemperatureConfig


class Realtime(LayerTemperature):
    """Draw widget"""

    wcfg: "TyreTemperatureConfig"
    color_name = "surface"
    reader_ico = "surface_temperature_ico"
    reader_avg = "surface_temperature_avg"
