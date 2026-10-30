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
Ride height Widget, modern design

Ride height per wheel with gauge, warning below bottoming height, front & rear ride height
(aero reference, from game; average of wheels if game gives none, LMU) between left & right tiles.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QPainter

from ...api_control import api
from .gauge_quad import GaugeQuad

if TYPE_CHECKING:
    from ...template.widget_config_types import RideHeightConfig

CORNERS = ("front_left", "front_right", "rear_left", "rear_right")


class Realtime(GaugeQuad):
    """Draw widget"""

    wcfg: RideHeightConfig

    options = (
        *GaugeQuad.common_options, "ride_height_maximum_range",
        *(f"bottoming_height_{corner}" for corner in CORNERS), "show_axle_ride_height",
    )
    label = "Ride height"

    def setup(self):
        self.max_range = max(int(self.wcfg["ride_height_maximum_range"]), 10)
        self.bottoming = tuple(self.wcfg[f"bottoming_height_{corner}"] for corner in CORNERS)
        self.show_axle = self.wcfg["show_axle_ride_height"]

    def center_width(self) -> float:
        """Front & rear ride height (aero reference) between left & right tiles"""
        if not self.wcfg["show_axle_ride_height"]:
            return 0.0
        sample = f"888.{'8' * self.decimals}" if self.decimals else "888"
        return self.text_width("small", sample) + self.unit * 0.3

    def paint(self, painter: QPainter):
        tiles, axles = self.state
        self.draw_quads(painter, (tiles,))
        if axles:
            self.draw_center_texts(painter, self.quad_slots[0], axles)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        heights = api.read.wheel.ride_height()
        axles: tuple[str, ...] = ()
        if self.show_axle:
            axles = tuple(f"{value:z.{self.decimals}f}" for value in axle_ride_heights(heights))
        tiles = self.read(heights)
        rects = self.quad_slots[0].tiles if self.quad_slots else ()
        self.refresh_keyed((tiles, axles),
                           (self.pixel_key(tiles, [rect.width() for rect in rects], "level", "mark"), axles))

    def read(self, heights: tuple[float, ...] | None = None) -> tuple:
        theme = self.theme
        return tuple(
            self.gauge(value, value, value / self.max_range, theme.positive, value < bottom)
            for value, bottom in zip(api.read.wheel.ride_height() if heights is None else heights, self.bottoming)
        )


def axle_ride_heights(heights: tuple[float, ...]) -> tuple[float, float]:
    """Front & rear ride height from game, average of axle wheels if game gives none (LMU: always 0)"""
    vehicle = api.read.vehicle
    front = vehicle.ride_height_front() or (heights[0] + heights[1]) * 0.5
    rear = vehicle.ride_height_rear() or (heights[2] + heights[3]) * 0.5
    return front, rear
