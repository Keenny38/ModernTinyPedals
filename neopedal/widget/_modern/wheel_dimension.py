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
Wheel dimension Widget, modern design

Front & rear tyre radius measured while driving, in display order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QPainter

from ...module_info import minfo
from ..wheel_dimension import radius_text
from .base import ModernOverlay
from .stats import Stat, StatsMixin, Value

if TYPE_CHECKING:
    from ...template.widget_config_types import WheelDimensionConfig


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    wcfg: WheelDimensionConfig

    options = (
        "font_size", "layout", "show_front_tyre_radius", "show_rear_tyre_radius",
        "display_order_front_tyre_radius", "display_order_rear_tyre_radius",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        axles = sorted(
            (order, front, label) for show, order, front, label in (
                (wcfg["show_front_tyre_radius"], wcfg["display_order_front_tyre_radius"], True, "Front radius"),
                (wcfg["show_rear_tyre_radius"], wcfg["display_order_rear_tyre_radius"], False, "Rear radius"),
            ) if show
        )
        self.fronts = tuple(front for _, front, _ in axles)
        stats = [Stat(label.split()[0].lower(), label, "888mm", "strong") for _, _, label in axles]
        self.set_size(*self.build_stats(stats, vertical=wcfg["layout"] == 0))

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        wheels = minfo.wheels
        self.refresh(tuple(
            Value(radius_text(wheels.wheelRadiusFront if front else wheels.wheelRadiusRear))
            for front in self.fronts
        ))
