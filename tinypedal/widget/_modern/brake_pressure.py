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
Brake pressure Widget, modern design

Brake pressure per wheel with gauge, mark of raw brake input split by brake bias (pressure
asked by pedal, compare with pressure applied).
"""

from __future__ import annotations

from ...api_control import api
from .gauge_quad import GaugeQuad


class Realtime(GaugeQuad):
    """Draw widget"""

    options = (*GaugeQuad.common_options, "show_brake_input")
    label = "Brake pressure"

    def read(self) -> tuple:
        theme = self.theme
        marks: tuple[float, ...] = (-1.0,) * 4
        if self.wcfg["show_brake_input"]:
            brake = max(api.read.inputs.brake_raw(), 0.0)
            bias = api.read.brake.bias_front()
            marks = (brake * bias, brake * bias, brake * (1 - bias), brake * (1 - bias))
        return tuple(
            self.gauge(value, value, value / 100, theme.accent, mark=mark)
            for value, mark in zip(api.read.brake.pressure(scale=100), marks)
        )
