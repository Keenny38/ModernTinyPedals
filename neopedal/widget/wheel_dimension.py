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
Wheel dimension Widget

Front & rear tyre radius measured while driving (wheels module, enable_wheel_dimension_measurement).
"""

from math import isfinite
from typing import TYPE_CHECKING

from ..const_common import TEXT_NA
from ..i18n import tr_overlay as tr
from ..module_info import minfo
from ._base import Overlay

if TYPE_CHECKING:
    from ..template.widget_config_types import WheelDimensionConfig


def radius_text(radius: float) -> str:
    """Tyre radius (millimeters), not available until measured (or invalid reading)"""
    return f"{radius:.0f}mm" if isfinite(radius) and radius > 0 else TEXT_NA


class Realtime(Overlay):
    """Draw widget"""

    wcfg: "WheelDimensionConfig"

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        layout = self.set_grid_layout(gap=self.wcfg["bar_gap"])
        self.set_primary_layout(layout=layout)

        # Config font
        font = self.config_font(
            self.wcfg["font_name"],
            self.wcfg["font_size"],
            self.wcfg["font_weight"],
        )
        self.setFont(font)
        font_m = self.get_font_metrics(font)

        # Config variable
        bar_padx = self.set_padding(self.wcfg["font_size"], self.wcfg["bar_padding"])

        # Front & rear tyre radius, after axle label
        wcfg = self.wcfg
        self.bars_radius = []
        for show, fg_color, bg_color, column, front in (
            (wcfg["show_front_tyre_radius"], wcfg["font_color_front_tyre_radius"],
             wcfg["background_color_front_tyre_radius"], wcfg["display_order_front_tyre_radius"], True),
            (wcfg["show_rear_tyre_radius"], wcfg["font_color_rear_tyre_radius"],
             wcfg["background_color_rear_tyre_radius"], wcfg["display_order_rear_tyre_radius"], False),
        ):
            if not show:
                continue
            prefix = f"{tr('F' if front else 'R')} "
            bar_radius = self.set_rawtext(
                text=f"{prefix}{TEXT_NA}",
                width=font_m.width * (len(prefix) + 6) + bar_padx,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=fg_color,
                bg_color=bg_color,
                last="",
            )
            self.set_primary_orient(
                target=bar_radius,
                column=column,
            )
            self.bars_radius.append((bar_radius, front, prefix))

    def timerEvent(self, event):
        """Update when vehicle on track"""
        wheels = minfo.wheels
        for bar_radius, front, prefix in self.bars_radius:
            self.update_radius(bar_radius, radius_text(wheels.wheelRadiusFront if front else wheels.wheelRadiusRear), prefix)

    # GUI update methods
    def update_radius(self, target, text, prefix):
        """Tyre radius"""
        if target.last != text:
            target.last = text
            target.text = f"{prefix}{text}"
            target.update()
