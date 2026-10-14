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
Lap time & stint history classic widget base: columns of current row & history rows, with caption
"""

from typing import Any

from .. import units
from ._base import Overlay
from ._data import cut_number
from ._painter import RawText


class HistoryTable(Overlay):
    """Columns of current (first row, font_color_<option>) & history rows (font_color_last_<option>)"""

    wcfg: Any  # Lap time history or Stint history options
    cap_fuel: RawText

    def set_history_layout(self, slots: int):
        """Layout, font & caption style of history table (slots: history rows)"""
        wcfg = self.wcfg
        self.history_layout = layout = self.set_grid_layout(gap_vert=wcfg["bar_gap"])
        self.set_primary_layout(layout=layout)

        # Config font
        font = self.config_font(
            wcfg["font_name"],
            wcfg["font_size"],
            wcfg["font_weight"],
        )
        self.setFont(font)
        self.font_m = self.get_font_metrics(font)

        if wcfg["show_caption"]:
            self.font_cap = self.config_font(
                wcfg["font_name"],
                wcfg["font_size"] * wcfg["font_scale_caption"],
                wcfg["font_weight"],
            )
            self.font_cap_m = self.get_font_metrics(self.font_cap)

        # Config variable
        self.layout_reversed = wcfg["layout"] != 0
        self.bar_padx = self.set_padding(wcfg["font_size"], wcfg["bar_padding"])
        self.row_count = slots + 1
        self.row_caption = (slots + 2) * wcfg["swap_upper_caption"]

        # Config units
        self.unit_fuel = units.set_unit_fuel(self.cfg.units["fuel_unit"])

    def set_history_column(self, option: str, last_colors: str, text: str, chars: int) -> tuple[RawText, ...]:
        """Column cells & caption

        Args:
            option: option name (font_color_<option>, display_order_<option>, caption_text_<option>).
            last_colors: color option name of history rows.
            text: placeholder text.
            chars: width in characters.
        """
        wcfg = self.wcfg
        font_m = self.font_m
        bars = self.set_rawtext(
            text=text,
            width=font_m.width * chars + self.bar_padx,
            fixed_height=font_m.height,
            offset_y=font_m.voffset,
            fg_color=wcfg[f"font_color_{last_colors}"],
            bg_color=wcfg[f"background_color_{last_colors}"],
            count=self.row_count,
        )
        bars[0].fg = wcfg[f"font_color_{option}"]
        bars[0].bg = wcfg[f"background_color_{option}"]
        self.set_grid_layout_table_column(
            layout=self.history_layout,
            targets=bars,
            row_start=1,
            column=wcfg[f"display_order_{option}"],
            bottom_to_top=self.layout_reversed,
        )

        if wcfg["show_caption"]:
            cap_temp = self.set_rawtext(
                font=self.font_cap,
                text=wcfg[f"caption_text_{option}"],
                fixed_height=self.font_cap_m.height,
                offset_y=self.font_cap_m.voffset,
                fg_color=wcfg["font_color_caption"],
                bg_color=wcfg["background_color_caption"],
            )
            self.history_layout.addWidget(cap_temp, self.row_caption, wcfg[f"display_order_{option}"])
            if option == "fuel":  # fuel or virtual energy caption
                self.cap_fuel = cap_temp
        return bars

    def set_fuel_column(self, last_colors: str):
        """Fuel (or virtual energy) used column, if shown"""
        wcfg = self.wcfg
        if not wcfg["show_fuel"]:
            return
        if wcfg["show_fuel_sign"]:
            self.sign_fuel = units.set_symbol_fuel(self.cfg.units["fuel_unit"])[0].upper()
        else:
            self.sign_fuel = ""
        self.sign_energy = "E" if self.sign_fuel else ""
        decimals_fuel = max(wcfg["decimal_places_fuel"], 1)
        self.width_fuel = 2 + decimals_fuel
        self.bars_fuel = self.set_history_column(
            "fuel", last_colors, f"-.{'-' * decimals_fuel}{self.sign_fuel}", self.width_fuel + len(self.sign_fuel))

    def set_wear_column(self, last_colors: str):
        """Tyre wear column, if shown"""
        wcfg = self.wcfg
        if not wcfg["show_wear"]:
            return
        if wcfg["show_wear_sign"]:
            self.sign_wear = "%"
        else:
            self.sign_wear = ""
        decimals_wear = max(wcfg["decimal_places_wear"], 1)
        self.width_wear = 2 + decimals_wear
        self.bars_wear = self.set_history_column(
            "wear", last_colors, f"-.{'-' * decimals_wear}{self.sign_wear}", self.width_wear + len(self.sign_wear))

    def set_delta_column(self, last_colors: str):
        """Lap time delta column, if shown"""
        wcfg = self.wcfg
        if not wcfg["show_delta"]:
            return
        decimals_delta = max(wcfg["decimal_places_delta"], 1)
        self.width_delta = 3 + decimals_delta
        self.bars_delta = self.set_history_column(
            "delta", last_colors, f"--.{'-' * decimals_delta}", self.width_delta)

    # GUI update methods
    def update_fuel(self, target, data, sign):
        """Fuel data"""
        if target.last != (data, sign):  # unit sign (fuel/energy) changes with same value too
            target.last = data, sign
            target.text = f"{cut_number(data, self.width_fuel)}{sign}"
            target.update()

    def update_fuel_caption(self, target, data):
        """Fuel caption"""
        if target.last != data:
            target.last = data
            if data:
                text_caption = self.wcfg["caption_text_virtual_energy"]
            else:
                text_caption = self.wcfg["caption_text_fuel"]
            target.text = text_caption
            target.update()

    def update_wear(self, target, data):
        """Wear data"""
        if target.last != data:
            target.last = data
            target.text = f"{cut_number(data, self.width_wear)}{self.sign_wear}"
            target.update()
