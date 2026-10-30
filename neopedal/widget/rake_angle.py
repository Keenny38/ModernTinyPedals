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
Rake angle Widget
"""

from typing import TYPE_CHECKING

from .. import calculation as calc
from ..api_control import api
from ._base import Overlay

if TYPE_CHECKING:
    from ..template.widget_config_types import RakeAngleConfig


class Realtime(Overlay):
    """Draw widget"""

    wcfg: "RakeAngleConfig"

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        layout = self.set_grid_layout()
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
        self.prefix_text = self.wcfg["prefix_rake_angle"]
        self.sign_text = "°" if self.wcfg["show_degree_sign"] else ""
        self.decimals = max(int(self.wcfg["decimal_places"]), 0)

        # Rake angle
        self.bar_style_rake = (
            self.wcfg["background_color_rake_angle"],
            self.wcfg["warning_color_negative_rake"],
        )
        text_width = len(self.format_rake(-100))  # widest: 3 digits ride height difference
        self.bar_rake = self.set_rawtext(
            text=self.format_rake(0),
            width=font_m.width * text_width + bar_padx,
            fixed_height=font_m.height,
            offset_y=font_m.voffset,
            fg_color=self.wcfg["font_color_rake_angle"],
            bg_color=self.bar_style_rake[0],
        )
        layout.addWidget(self.bar_rake, 0, 0)
        self.calc_ema_rake = calc.ema_filter(self.wcfg["rake_angle_smoothing_samples"])
        self.ema_rake = 0.0

    def timerEvent(self, event):
        """Update when vehicle on track"""
        # Rake angle
        self.ema_rake = self.calc_ema_rake(self.ema_rake, calc.rake(*api.read.wheel.ride_height()))
        self.update_rake(self.bar_rake, self.ema_rake)

    # GUI update methods
    def update_rake(self, target, data):
        """Rake data, repainted on text change only"""
        text = self.format_rake(data)
        if target.last != text:
            target.last = text
            target.text = text
            target.bg = self.bar_style_rake[self.rounded_angle(data) < 0]  # negative rake as shown
            target.update()

    def rounded_angle(self, rake):
        """Rake angle (degree) rounded to shown decimals"""
        return round(calc.slope_angle(rake, self.wcfg["wheelbase"]), self.decimals)

    def format_rake(self, rake):
        """Format rake"""
        rake_angle = f"{self.rounded_angle(rake):+z.{self.decimals}f}"
        if self.wcfg["show_ride_height_difference"]:
            ride_diff = f"({min(abs(rake), 999):02.0f})"
        else:
            ride_diff = ""
        return f"{self.prefix_text}{rake_angle:.{self.decimals + 3}}{self.sign_text}{ride_diff}"
