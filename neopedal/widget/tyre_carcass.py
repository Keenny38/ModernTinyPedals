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
Tyre carcass temperature Widget
"""

from typing import TYPE_CHECKING

from ..api_control import api
from ..const_common import TEXT_NA
from ._data import TemperatureRates, rate_text
from ._tyre_temps import TyreTemperatures

if TYPE_CHECKING:
    from ..template.widget_config_types import TyreCarcassConfig


class Realtime(TyreTemperatures):
    """Draw widget"""

    wcfg: "TyreCarcassConfig"
    color_name = "carcass"

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        layout_inner, font_m, bar_padx, text_width = self.set_tyre_layouts()
        # Temperature difference (rate of change): scale only, no offset
        self.temp_scale = 1.8 if self.cfg.units["temperature_unit"] == "Fahrenheit" else 1.0

        # Tyre carcass temperature
        base_row = 1
        self.set_temperature_bars(font_m, bar_padx, text_width, 4)
        # Column 1, 1
        for idx, inner in enumerate(layout_inner):
            inner.addWidget(self.bars_temp[idx], base_row, 1)

        # Tyre compound: column 2, 0
        self.set_compound_bars(layout_inner, font_m, bar_padx, base_row, tuple((1 - idx % 2) * 2 for idx in range(4)))

        # Rate of change
        if self.wcfg["show_rate_of_change"]:
            self.bar_style_rtemp = (
                (
                    (
                        self.wcfg["background_color_rate_of_change"],
                        self.wcfg["font_color_rate_loss"],
                    ),
                    (
                        self.wcfg["background_color_rate_of_change"],
                        self.wcfg["font_color_rate_gain"],
                    ),
                    (
                        self.wcfg["background_color_rate_of_change"],
                        self.wcfg["font_color_rate_of_change"],
                    ),
                )
                if self.wcfg["swap_style"]
                else (
                    (
                        self.wcfg["font_color_rate_loss"],
                        self.wcfg["background_color_rate_of_change"],
                    ),
                    (
                        self.wcfg["font_color_rate_gain"],
                        self.wcfg["background_color_rate_of_change"],
                    ),
                    (
                        self.wcfg["font_color_rate_of_change"],
                        self.wcfg["background_color_rate_of_change"],
                    ),
                )
            )
            self.bars_rdiff = self.set_rawtext(
                text=TEXT_NA,
                width=font_m.width * 3 + bar_padx,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.bar_style_rtemp[2][0],
                bg_color=self.bar_style_rtemp[2][1],
                count=4,
                last=0,
            )
            # Column 0, 2
            for idx, inner in enumerate(layout_inner):
                inner.addWidget(self.bars_rdiff[idx], base_row, 2 * (idx % 2))

        self.rates = TemperatureRates(
            min(max(self.wcfg["rate_of_change_interval"], 1), 60),
            self.wcfg["rate_of_change_smoothing_samples"],
        )

    def post_update(self):
        """Rate of change restarts from next reading (no rate against stale temperature)"""
        self.reset_rates()

    def reset_rates(self):
        """Clear rate of change & last temperature (new session or paused timer)"""
        self.rates.reset()
        self.update_rates()

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.update_compounds()

        # Tyre carcass temperature: 0 - fl, 1 - fr, 2 - rl, 3 - rr
        ctemp = api.read.tyre.carcass_temperature()
        for tyre_idx, bar_ctemp in enumerate(self.bars_temp):
            self.update_temp(bar_ctemp, round(ctemp[tyre_idx]), tyre_idx)

        # Rate of change
        if self.wcfg["show_rate_of_change"] and self.rates.update(ctemp, api.read.timing.elapsed()):
            self.update_rates()

    def update_rates(self):
        """Rate of change cells"""
        if self.wcfg["show_rate_of_change"]:
            for bar_rdiff, rate in zip(self.bars_rdiff, self.rates.rates):
                self.update_rdiff(bar_rdiff, rate)

    # GUI update methods
    def update_rdiff(self, target, data):
        """Rate of change"""
        if target.last != data:
            target.last = data
            target.text = rate_text(data, self.temp_scale)
            target.fg, target.bg = self.bar_style_rtemp[data > 0]
            target.update()
