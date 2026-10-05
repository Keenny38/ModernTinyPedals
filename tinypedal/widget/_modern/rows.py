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
Modern overlay design: driver row cells shared by list widgets (relative, standings, rivals...)
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QColor

from ... import calculation as calc
from ...const_common import MAX_SECONDS, TEXT_NOLAPTIME
from ...formatter import random_color_class, shorten_driver_name
from ...userfile.heatmap import select_compound_color, select_compound_symbol
from .base import DASH
from .draw import readable_on
from .table import BADGE, COMPOUND, PILL, TEXT, Cell
from .theme import Theme


@lru_cache(maxsize=256)
def _qcolor(value: str) -> QColor:
    return QColor(value)


def class_style(config, class_name: str, theme: Theme) -> tuple[str, QColor]:
    """Class alias & color, from vehicle class presets"""
    style = config.user.classes.get(class_name)
    if style is not None:
        return style["alias"], _qcolor(style["color"])
    if class_name:
        return class_name, _qcolor(random_color_class(class_name))
    return "", theme.surface_raised


def laptime_text(laptime: float, valid: bool = True) -> str:
    """Lap time, * prefix if invalid"""
    if 0 < laptime < MAX_SECONDS:
        text = calc.sec2laptime_full(laptime)
        return text if valid else f"*{text}"
    return TEXT_NOLAPTIME


def compound_cell(names: tuple[str, ...]) -> Cell:
    """Tyre compounds: one square per distinct compound, front first"""
    compounds = []
    for name in names:
        item = (select_compound_symbol(name), _qcolor(select_compound_color(name)))
        if item not in compounds:
            compounds.append(item)
    return Cell(COMPOUND, extra=tuple(compounds[:2]))


def pit_cell(theme: Theme, in_pit: int, is_yellow: bool, is_finished: bool) -> Cell:
    """Pit lane, garage, stopped on track (yellow), finished"""
    if is_finished:
        return Cell(PILL, "FIN", color=readable_on(theme.text), fill=theme.text)
    if in_pit == 1:
        return Cell(PILL, "PIT", color=readable_on(theme.accent), fill=theme.accent)
    if in_pit == 2:
        return Cell(PILL, "GAR", color=theme.text, fill=theme.surface_strong)
    if is_yellow:
        return Cell(PILL, "SLOW", color=readable_on(theme.caution), fill=theme.caution)
    return Cell(PILL)


class RowStyle:
    """Row cell builders that depend on widget options"""

    def __init__(self, widget, wcfg: dict):
        self.widget = widget
        self.wcfg = wcfg
        self.theme: Theme = widget.theme
        self.on_accent = readable_on(self.theme.accent)

    def class_width(self) -> float:
        """Class pill width: alias part & position part"""
        widget = self.widget
        alias_w = widget.text_width("small", "LMP2") + widget.unit * 0.5
        pos_w = widget.digit_width("small") * 2 + widget.unit * 0.4
        return max(alias_w / 0.6, pos_w / 0.4)

    def name_width(self, chars: int, role: str = "value") -> float:
        """Name column width for number of characters"""
        chars = max(int(chars), 1)
        return self.widget.metrics[role].averageCharWidth() * chars * 1.12

    def driver_name(self, name: str) -> str:
        """Driver name, shortened or upper case by options"""
        if self.wcfg.get("driver_name_shorten", False):
            name = shorten_driver_name(name)
        if self.wcfg.get("driver_name_uppercase", False):
            name = name.upper()
        return name

    def lap_color(self, lap_difference: float, player: bool) -> QColor:
        """Name color: laps ahead or behind player"""
        theme = self.theme
        if player or not self.wcfg.get("show_lap_difference", True):
            return theme.text
        if lap_difference > 0:
            return theme.lap_ahead
        if lap_difference < 0:
            return theme.lap_behind
        return theme.text

    def pitstop_cell(self, count: int, requested: bool) -> Cell:
        """Pit stops done, pit request, penalty"""
        theme = self.theme
        if count < 0:
            return Cell(BADGE, "PEN", "label", readable_on(theme.best), theme.best)
        if requested and self.wcfg.get("show_pit_request", True):
            return Cell(BADGE, f"{count}", "small", readable_on(theme.positive), theme.positive)
        if count == 0:
            return Cell(TEXT, DASH, "dim", theme.text_faint)
        return Cell(BADGE, f"{count}", "small", theme.text_dim, theme.surface_raised)

    def energy_cell(self, energy: float) -> Cell:
        """Virtual energy remaining"""
        theme = self.theme
        if energy <= -1:
            return Cell(TEXT, DASH, "dim", theme.text_faint)
        if energy <= 0.1:
            color = theme.negative
        elif energy <= 0.3:
            color = theme.warning
        else:
            color = theme.positive
        return Cell(TEXT, f"{energy:.0%}", "dim", color)

    def integrity_cell(self, integrity: float) -> Cell:
        """Vehicle integrity"""
        theme = self.theme
        if integrity >= 1:
            return Cell(TEXT, DASH, "dim", theme.text_faint)
        color = theme.negative if integrity <= 0.5 else theme.warning
        return Cell(TEXT, f"{max(integrity, 0):.0%}", "dim", color)

    def incidents_cell(self, score: int) -> Cell:
        """Incident points"""
        theme = self.theme
        if score <= 0:
            return Cell(TEXT, DASH, "dim", theme.text_faint)
        if score >= self.wcfg.get("incidents_extreme_threshold", 20):
            color = theme.negative
        elif score >= self.wcfg.get("incidents_high_threshold", 10):
            color = theme.warning
        else:
            color = theme.text_dim
        return Cell(TEXT, f"x{score}", "dim", color)

    def stint_cell(self, done: float, estimated: float) -> Cell:
        """Laps done in stint / estimated stint laps"""
        theme = self.theme
        text_done = f"{done:.0f}" if done > 0 else DASH
        text_est = f"{estimated // 1:.0f}" if estimated > 0 else DASH
        return Cell(TEXT, f"{text_done}/{text_est}", "dim", theme.text_dim)
