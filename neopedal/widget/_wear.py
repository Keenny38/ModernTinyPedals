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
Tyre & brake wear classic widget base: sections of four wheel values, with caption
"""

from typing import Any

from ..const_common import TEXT_NA
from ._base import Overlay
from ._data import wear_text
from ._painter import RawText


class WearSections(Overlay):
    """Sections of four wheel values (bars_<name>, bar_style_<name>: normal & warning color)"""

    wcfg: Any  # Tyre wear or Brake wear options
    bars_remain: tuple[RawText, ...]
    bars_diff: tuple[RawText, ...]
    bars_live: tuple[RawText, ...]
    bars_lock: tuple[RawText, ...]
    bars_laps: tuple[RawText, ...]
    bars_mins: tuple[RawText, ...]
    bars_end: tuple[RawText, ...]
    bar_style_remain: tuple[str, str]
    bar_style_diff: tuple[str, str]
    bar_style_live: tuple[str, str]
    bar_style_lock: tuple[str, str]
    bar_style_laps: tuple[str, str]
    bar_style_mins: tuple[str, str]
    bar_style_end: tuple[str, str]

    def set_wear_sections(self, sections: tuple[tuple[str, str], ...]):
        """Layout & enabled sections

        Args:
            sections: (bar name, option name) of sections, shown by show_<option name>.
        """
        wcfg = self.wcfg
        layout = self.set_grid_layout(gap=wcfg["bar_gap"])
        self.set_primary_layout(layout=layout)

        # Config font
        font = self.config_font(
            wcfg["font_name"],
            wcfg["font_size"],
            wcfg["font_weight"],
        )
        self.setFont(font)
        font_m = self.get_font_metrics(font)

        if wcfg["show_caption"]:
            font_cap = self.config_font(
                wcfg["font_name"],
                wcfg["font_size"] * wcfg["font_scale_caption"],
                wcfg["font_weight"],
            )
            font_cap_m = self.get_font_metrics(font_cap)

        # Config variable
        bar_padx = self.set_padding(wcfg["font_size"], wcfg["bar_padding"])
        bar_width = font_m.width * 4 + bar_padx

        for name, option in sections:
            if not wcfg[f"show_{option}"]:
                continue
            layout_section = self.set_grid_layout()
            bar_style = (
                wcfg[f"font_color_{option}"],
                wcfg["font_color_warning"],
            )
            bars = self.set_rawtext(
                text=TEXT_NA,
                width=bar_width,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=bar_style[0],
                bg_color=wcfg[f"background_color_{option}"],
                count=4,
                last=0 if name == "remain" else None,
            )
            setattr(self, f"bar_style_{name}", bar_style)
            setattr(self, f"bars_{name}", bars)
            self.set_grid_layout_quad(
                layout=layout_section,
                targets=bars,
            )
            self.set_primary_orient(
                target=layout_section,
                column=wcfg[f"display_order_{option}"],
            )

            if wcfg["show_caption"]:
                cap_section = self.set_rawtext(
                    font=font_cap,
                    text=wcfg[f"caption_text_{option}"],
                    fixed_height=font_cap_m.height,
                    offset_y=font_cap_m.voffset,
                    fg_color=wcfg["font_color_caption"],
                    bg_color=wcfg["background_color_caption"],
                )
                layout_section.addWidget(cap_section, 0, 0, 1, 0)

    # GUI update methods
    @staticmethod
    def set_wear(target, data, style, warn, failed=False):
        """Wheel value, set once changed (warn: warning color, failed: brake failed)"""
        target.last = data
        target.text = "FAIL" if failed else wear_text(data)
        target.fg = style[warn]
        target.update()

    @staticmethod
    def show_wear(target, data, style, warn):
        """Wheel value drawn again once its text or color changes, not on every change of the raw value
        (continuous wear: shown digits move far less often than the value)"""
        text = wear_text(data)
        shown = (text, warn)
        if target.last != shown:
            target.last = shown
            target.text = text
            target.fg = style[warn]
            target.update()
