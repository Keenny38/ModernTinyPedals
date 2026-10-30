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
Fuel & virtual energy classic widget base

Upper row: remaining, refill, consumption (+ pit stops, delta, widget own cells), lower row:
estimated laps & minutes, saving target (+ early pit stops, end remaining...), level bar between.
Each cell is shown by its own option ("show_<cell name>"): a hidden cell leaves its place empty while
the cell above or below it is shown (columns of both rows stay aligned), a column with no cell is left out.
"""

from collections.abc import Callable
from typing import Any, NamedTuple

from PySide6.QtWidgets import QGridLayout

from ._base import Overlay
from ._common import warning_flash
from ._data import consumption_data, level_data
from ._painter import FuelLevelBar

TEXT_DEFAULT = "-.--"
LOW_PADDING = 0.00000001  # value padding while low warning shown (cell drawn again on switch)


class Shown(NamedTuple):
    """Options of warning & level bar shown"""

    flash: bool  # low amount warning flash
    absolute: bool  # absolute refill amount
    level: bool  # level bar


Cell = tuple[str, str]  # cell name (option names: decimal_places_<name>...), option showing it


class ConsumptionBars(Overlay):
    """Fuel or virtual energy cells

    Option names differ by kind: refill ("refueling", "refilling") and amount ("fuel", "energy").
    """

    wcfg: Any  # Fuel or Virtual energy options
    refill: str  # refill option name
    amount: str  # amount option name

    def set_consumption_bars(self, extra_columns: tuple[tuple[Cell, Cell], ...] = ()):
        """Cells, captions & level bar

        Args:
            extra_columns: widget own cells after common ones, (upper cell, lower cell) of each column.
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
        self.font_m = font_m = self.get_font_metrics(font)

        # Config variable
        bar_padx = self.set_padding(wcfg["font_size"], wcfg["bar_padding"])
        self.bar_width = max(wcfg["bar_width"], 3)
        self.style_width = font_m.width * self.bar_width + bar_padx
        self.cells: dict[str, Any] = {}  # shown value cells by name

        # Create layout
        self.layout_upper = self.set_grid_layout()
        self.layout_lower = self.set_grid_layout()
        layout.addLayout(self.layout_upper, wcfg["display_order_upper"], 0)
        layout.addLayout(self.layout_lower, wcfg["display_order_lower"], 0)

        # Caption style
        if wcfg["show_caption"]:
            self.font_cap = self.config_font(
                wcfg["font_name"],
                wcfg["font_size"] * wcfg["font_scale_caption"],
                wcfg["font_weight"],
            )
            self.font_cap_m = self.get_font_metrics(self.font_cap)
            self.row_idx_upper = 2 * wcfg["swap_upper_caption"]
            self.row_idx_lower = 2 - 2 * wcfg["swap_lower_caption"]

        refill = self.refill
        low_color = wcfg[f"warning_color_low_{self.amount}"]
        self.bar_style_curr = (wcfg["background_color_remaining"], low_color)
        self.bar_style_need = (wcfg[f"background_color_{refill}"], low_color)
        caption_need = (f"caption_text_absolute_{refill}" if wcfg[f"show_absolute_{refill}"]
                        else f"caption_text_{refill}")
        backgrounds = {"remaining": self.bar_style_curr[0], refill: self.bar_style_need[0]}
        captions = {refill: caption_need}
        columns: tuple[tuple[Cell, Cell], ...] = (
            # Estimate pit stop counts when pitting at end of current stint, or end of current lap
            (("pitstop_count", "show_estimated_pitstop_count"), ("early_pitstop_count", "show_early_pitstop_count")),
            (("remaining", "show_remaining"), ("estimated_laps", "show_estimated_laps")),
            ((refill, f"show_{refill}"), ("estimated_minutes", "show_estimated_minutes")),
            (("estimated_consumption", "show_estimated_consumption"), ("saving_target", "show_saving_target")),
            (("delta_consumption", "show_delta_consumption"), ("end_remaining", "show_end_remaining")),
            *extra_columns,
        )
        column = 0
        for pair in columns:
            shown = tuple(bool(wcfg[option]) for _, option in pair)
            if not any(shown):  # column left out
                continue
            for lower, ((name, _), cell_shown) in enumerate(zip(pair, shown)):
                if cell_shown:
                    self.cells[name] = self.set_cell(name, bool(lower), column, backgrounds.get(name, ""),
                                                     captions.get(name, ""))
            column += 1
        self.column_count = column
        # Empty place of a hidden cell (row showing any cell): columns of both rows aligned
        for row_layout in (self.layout_upper, self.layout_lower):
            if row_layout.count():
                fill_columns(row_layout, column, self.style_width)

        # Level bar
        amount = self.amount
        if wcfg[f"show_{amount}_level_bar"]:
            self.bar_level = FuelLevelBar(
                self,
                width=(font_m.width * self.bar_width + bar_padx) * max(self.column_count, 1),  # one cell wide if none
                height=max(wcfg[f"{amount}_level_bar_height"], 1),
                start_mark_width=max(wcfg[f"starting_{amount}_level_mark_width"], 1),
                refill_mark_width=max(wcfg[f"{refill}_level_mark_width"], 1),
                input_color=wcfg[f"highlight_color_{amount}_level"],
                bg_color=wcfg[f"background_color_{amount}_level"],
                start_mark_color=wcfg[f"starting_{amount}_level_mark_color"],
                refill_mark_color=wcfg[f"{refill}_level_mark_color"],
                show_start_mark=wcfg[f"show_starting_{amount}_level_mark"],
                show_refill_mark=wcfg[f"show_{refill}_level_mark"],
            )
            layout.addWidget(self.bar_level, wcfg["display_order_middle"], 0)

        # Options read on every update
        self.low_threshold = wcfg[f"low_{amount}_lap_threshold"]
        self.shown = Shown(
            wcfg[f"show_low_{amount}_warning_flash"],
            wcfg[f"show_absolute_{refill}"],
            wcfg[f"show_{amount}_level_bar"],
        )
        if self.shown.flash:
            self.warn_flash = warning_flash(
                wcfg["warning_flash_highlight_duration"],
                wcfg["warning_flash_interval"],
                wcfg["number_of_warning_flashes"],
            )

    def set_cell(self, name: str, lower: bool, column: int, bg_color: str = "", caption: str = ""):
        """Value cell & caption (upper row cells set level bar width)"""
        wcfg = self.wcfg
        font_m = self.font_m
        bar = self.set_rawtext(
            text=TEXT_DEFAULT,
            fixed_width=self.style_width,
            fixed_height=font_m.height,
            offset_y=font_m.voffset,
            fg_color=wcfg[f"font_color_{name}"],
            bg_color=bg_color or wcfg[f"background_color_{name}"],
        )
        bar.decimals = max(wcfg[f"decimal_places_{name}"], 0)
        layout = self.layout_lower if lower else self.layout_upper
        layout.addWidget(bar, 1, column)
        if wcfg["show_caption"]:
            font_cap_m = self.font_cap_m
            cap_temp = self.set_rawtext(
                font=self.font_cap,
                text=wcfg[caption or f"caption_text_{name}"],
                fixed_height=font_cap_m.height,
                offset_y=font_cap_m.voffset,
                fg_color=wcfg["font_color_caption"],
                bg_color=wcfg["background_color_caption"],
            )
            layout.addWidget(cap_temp, self.row_idx_lower if lower else self.row_idx_upper, column)
        return bar

    def update_consumption(self, source: Any, convert: Callable[[float], float]):
        """Update cells & level bar from fuel or energy module output"""
        shown = self.shown
        # No consumption estimate yet (0 laps): not a low amount
        is_low = source.estimatedValidConsumption > 0 and source.estimatedLaps <= self.low_threshold
        if shown.flash and source.estimatedValidConsumption:
            is_low = self.warn_flash.send(is_low)
            padding = LOW_PADDING if is_low else 0
        else:
            padding = 0
        absolute = shown.absolute
        data = consumption_data(source, convert, absolute)
        update = self.update_cell

        # Remaining & total needed
        update("remaining", data.remaining + padding, self.bar_style_curr[is_low])
        update(self.refill, data.needed + padding, self.bar_style_need[is_low], "" if absolute else "+")
        # Estimated laps & minutes can last, consumption, one less pit consumption
        update("estimated_laps", data.laps)
        update("estimated_minutes", data.minutes)
        update("estimated_consumption", data.used)
        update("saving_target", data.save)
        # Estimate pit stop counts when pitting at end of current stint, or current lap
        update("pitstop_count", data.pits_end)
        update("early_pitstop_count", data.pits_early)
        # Delta consumption & estimated end remaining
        update("delta_consumption", data.delta, None, "+")
        update("end_remaining", data.end)

        # Level bar
        if shown.level:
            level_capacity = source.capacity
            level_curr, level_start, level_refill = level_data(source)
            level_state = round(level_curr + level_start + level_refill, 3)
            if level_capacity and self.bar_level.last != level_state:
                self.bar_level.last = level_state
                self.bar_level.update_input(
                    level_curr / level_capacity,
                    level_start / level_capacity,
                    level_refill / level_capacity,
                )

    # GUI update methods
    def update_cell(self, name: str, data, color=None, sign=""):
        """Update value cell by name, if shown"""
        target = self.cells.get(name)
        if target is not None:
            self.update_value(target, data, color, sign)

    def update_value(self, target, data, color=None, sign=""):
        """Update value cell (color: background of low amount warning)

        Drawn again once its text or color changes, not on every change of the raw amount (continuous value
        of the fuel module: a repaint of every cell on every update while the shown digits do not move).
        """
        text = f"{data:{sign}z.{target.decimals}f}"[:self.bar_width].strip(".")
        shown = (text, color)
        if target.last != shown:
            target.last = shown
            target.text = text
            if color:  # low amount warning
                target.bg = color
            target.update()


def fill_columns(layout: QGridLayout, count: int, width: int):
    """Keep place of hidden cells in a row: every column of row at least cell wide"""
    for column in range(count):
        layout.setColumnMinimumWidth(column, width)
