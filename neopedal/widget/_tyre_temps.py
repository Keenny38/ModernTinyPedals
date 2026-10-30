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
Tyre temperature classic widget base: surface, inner layer & carcass temperature

Four tyre layouts, temperatures in heatmap colors of tyre compound, compound symbols.
"""

from typing import Any

from .. import calculation as calc
from .. import units
from ..api_control import api
from ..const_common import TEXT_NA, TEXT_PLACEHOLDER
from ..userfile.heatmap import (
    HEATMAP_DEFAULT_TYRE,
    load_heatmap_color,
    select_compound_color,
    select_compound_symbol,
    select_tyre_heatmap_name,
)
from ._base import Overlay
from ._data import shown_temperature, temperature_text
from ._painter import RawText


class TyreTemperatures(Overlay):
    """Tyre temperatures of compound heatmaps (colors: font_color_<color_name>, background_color_<color_name>)"""

    wcfg: Any  # Tyre temperature, inner layer or carcass options
    color_name: str
    bars_temp: tuple[RawText, ...]
    bars_tcmpd: tuple[RawText, ...]

    def set_tyre_layouts(self):
        """Layout of four tyres, font & temperature style

        Returns:
            Layouts of tyres (0 fl, 1 fr, 2 rl, 3 rr), font metrics, padding, temperature width (characters).
        """
        wcfg = self.wcfg
        layout = self.set_grid_layout(
            gap_hori=wcfg["horizontal_gap"],
            gap_vert=wcfg["vertical_gap"],
        )
        self.set_primary_layout(layout=layout)

        layout_inner = tuple(self.set_grid_layout(gap=wcfg["inner_gap"]) for _ in range(4))
        self.set_grid_layout_quad(layout=layout, targets=layout_inner)

        # Config font
        font = self.config_font(
            wcfg["font_name"],
            wcfg["font_size"],
            wcfg["font_weight"],
        )
        self.setFont(font)
        font_m = self.get_font_metrics(font)

        # Config variable
        bar_padx = self.set_padding(wcfg["font_size"], wcfg["bar_padding"])
        self.leading_zero = min(max(int(wcfg["leading_zero"]), 1), 3)
        self.sign_text = "°" if wcfg["show_degree_sign"] else ""
        text_width = 3 + len(self.sign_text) + (self.cfg.units["temperature_unit"] == "Fahrenheit")

        # Config units
        self.unit_temp = units.set_unit_temperature(self.cfg.units["temperature_unit"])
        self.temp_scale = 1.8 if self.cfg.units["temperature_unit"] == "Fahrenheit" else 1.0  # degrees of unit per Celsius

        # Heatmap style list: 0 - fl, 1 - fr, 2 - rl, 3 - rr
        self.heatmap_styles = 4 * [
            load_heatmap_color(
                heatmap_name=wcfg["heatmap_name"],
                default_name=HEATMAP_DEFAULT_TYRE,
                swap_style=wcfg["swap_style"],
                fg_color=wcfg[f"font_color_{self.color_name}"],
                bg_color=wcfg[f"background_color_{self.color_name}"],
            )
        ]

        # Last data
        self.last_in_pits = -1
        self.last_compounds: tuple[str, ...] = ("", "", "", "")
        return layout_inner, font_m, bar_padx, text_width

    def set_temperature_bars(self, font_m, bar_padx: int, text_width: int, count: int):
        """Temperature cells"""
        self.bars_temp = self.set_rawtext(
            text=TEXT_NA,
            width=font_m.width * text_width + bar_padx,
            fixed_height=font_m.height,
            offset_y=font_m.voffset,
            fg_color=self.wcfg[f"font_color_{self.color_name}"],
            bg_color=self.wcfg[f"background_color_{self.color_name}"],
            count=count,
            last=0,
        )

    def set_compound_bars(self, layout_inner, font_m, bar_padx: int, row: int, columns: tuple[int, ...]):
        """Tyre compound cells, if shown (columns: of each tyre)"""
        if not self.wcfg["show_tyre_compound"]:
            return
        self.bars_tcmpd = self.set_rawtext(
            text=TEXT_PLACEHOLDER,
            width=font_m.width + bar_padx,
            fixed_height=font_m.height,
            offset_y=font_m.voffset,
            fg_color=self.wcfg["font_color_tyre_compound"],
            bg_color=self.wcfg["background_color_tyre_compound"],
            count=4,
        )
        for idx, inner in enumerate(layout_inner):
            inner.addWidget(self.bars_tcmpd[idx], row, columns[idx])

    def vehicle_reset(self):
        """Compounds read again (followed car changed while spectating, session changed, back to garage)"""
        self.last_in_pits = -1

    def update_compounds(self):
        """Update compound (heatmap & symbol) while in pit (or switched pit state)"""
        in_pits = api.read.vehicle.in_pits()
        if in_pits or self.last_in_pits != in_pits:
            self.last_in_pits = in_pits
            compounds = api.read.tyre.compound_class()

            if self.last_compounds != compounds:
                # Heatmap
                if self.wcfg["enable_heatmap_auto_matching"]:
                    for index, name in enumerate(compounds):
                        if self.last_compounds[index] != name:
                            self.update_heatmap(name, index)
                # Tyre compound
                if self.wcfg["show_tyre_compound"]:
                    for tyre_idx, bar_tcmpd in enumerate(self.bars_tcmpd):
                        self.update_tcmpd(bar_tcmpd, compounds[tyre_idx])
                self.last_compounds = compounds

    # GUI update methods
    def update_temp(self, target, data, index):
        """Tyre temperature (Celsius, rounded as shown: see shown_temperature)"""
        if target.last != data:
            target.last = data
            target.text = temperature_text(data, self.unit_temp, self.leading_zero, self.sign_text, TEXT_PLACEHOLDER)
            target.fg, target.bg = calc.select_grade(self.heatmap_styles[index], data)
            target.update()

    def update_tcmpd(self, target, data):
        """Tyre compound"""
        if target.last != data:
            target.last = data
            target.text = select_compound_symbol(data)
            if self.wcfg["show_compound_color_by_type"]:
                target.fg = select_compound_color(data)
            target.update()

    def update_heatmap(self, compound, index):
        """Heatmap style"""
        self.heatmap_styles[index] = load_heatmap_color(
            heatmap_name=select_tyre_heatmap_name(compound),
            default_name=HEATMAP_DEFAULT_TYRE,
            swap_style=self.wcfg["swap_style"],
            fg_color=self.wcfg[f"font_color_{self.color_name}"],
            bg_color=self.wcfg[f"background_color_{self.color_name}"],
        )


class LayerTemperature(TyreTemperatures):
    """Surface or inner layer temperature: average or inner, center, outer of each tyre"""

    reader_ico: str  # tyre reader of inner, center, outer temperatures
    reader_avg: str  # tyre reader of average temperatures

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        layout_inner, font_m, bar_padx, text_width = self.set_tyre_layouts()

        # Tyre temperature
        base_row = 1
        if self.wcfg["show_inner_center_outer"]:
            temp_count = 3
        else:
            temp_count = 1
        self.set_temperature_bars(font_m, bar_padx, text_width, 4 * temp_count)  # 4 tyres x 3 temps
        # Column 0(,1,2), 1(,2,3)
        for idx, inner in enumerate(layout_inner):
            self.set_grid_layout_table_row(
                layout=inner,
                targets=self.bars_temp[idx * temp_count: idx * temp_count + temp_count],
                column_start=idx % 2,
                row=base_row,
            )

        # Tyre compound: column 1(3), 0
        self.set_compound_bars(layout_inner, font_m, bar_padx, base_row,
                               tuple((1 - idx % 2) * temp_count for idx in range(4)))

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.update_compounds()

        # Temperature: 0 - fl, 3 - fr, 6 - rl, 9 - rr
        scale = self.temp_scale
        if self.wcfg["show_inner_center_outer"]:
            temps = getattr(api.read.tyre, self.reader_ico)()
            for tyre_idx, bar_temp in enumerate(self.bars_temp):
                self.update_temp(bar_temp, shown_temperature(temps[tyre_idx], scale), tyre_idx // 3)
        else:  # 0 - fl, 1 - fr, 2 - rl, 3 - rr
            temps = getattr(api.read.tyre, self.reader_avg)()
            for tyre_idx, bar_temp in enumerate(self.bars_temp):
                self.update_temp(bar_temp, shown_temperature(temps[tyre_idx], scale), tyre_idx)
