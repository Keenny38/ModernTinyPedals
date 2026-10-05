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
Tyre inner layer Widget, modern design

Same as tyre temperature widget, with inner layer temperature.
"""

from __future__ import annotations

from ...api_control import api
from .tyre_temperature import Realtime as SurfaceTemperature


class Realtime(SurfaceTemperature):
    """Draw widget"""

    def read_temperatures(self) -> tuple:
        if self.ico:
            return api.read.tyre.inner_temperature_ico()
        return api.read.tyre.inner_temperature_avg()
