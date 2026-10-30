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
Modern overlay design: driver row cells shared by list widgets (relative, standings, rivals...)
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from PySide6.QtGui import QColor

from ... import units
from ...formatter import class_style as shared_class_style
from ...formatter import shorten_driver_name
from ...i18n import tr_overlay as tr
from ...penalty_info import NO_PENALTY, Penalty
from ...penalty_info import label as penalty_label
from ...template.setting_status_colors import energy_tone
from ...userfile.heatmap import select_compound_color, select_compound_symbol
from .base import DASH
from .draw import readable_on
from .table import BADGE, COMPOUND, PILL, TEXT, Cell
from .theme import Theme

PIT_STATUS = ("FIN", "PIT", "GAR", "SLOW")  # pit status pill texts (English, translated)
PIT_STATUS_OPTIONS = ("finish_status_text", "pit_status_text", "garage_status_text", "yellow_flag_status_text")


@lru_cache(maxsize=256)
def _qcolor(value: str) -> QColor:
    return QColor(value)


def class_style(config, class_name: str, theme: Theme) -> tuple[str, QColor]:
    """Class alias & color, from vehicle class presets"""
    if not class_name:
        return "", theme.surface_raised
    alias, color = shared_class_style(class_name, config.user.classes)  # same as app pages & stream graphics
    return alias, _qcolor(color)


def compound_badge(name: str) -> tuple[str, QColor]:
    """Compound symbol & color (compound presets may be edited: not cached)"""
    return select_compound_symbol(name), _qcolor(select_compound_color(name, text=False))  # badge


def compound_cell(names: tuple[str, ...], per_wheel: bool = True) -> Cell:
    """Tyre compounds (front left, front right, rear left, rear right): one square if same on
    every wheel, front & rear, or every wheel (per_wheel) when left & right of an axle differ"""
    items = tuple(map(compound_badge, names))
    if not items:
        return Cell(COMPOUND, extra=())
    if per_wheel and len(items) >= 4 and (items[0] != items[1] or items[2] != items[3]):
        return Cell(COMPOUND, extra=items[:4])
    front, rear = items[0], items[2] if len(items) >= 3 else items[-1]
    return Cell(COMPOUND, extra=(front,) if front == rear else (front, rear))


def pit_cell(theme: Theme, in_pit: int, is_yellow: bool, is_finished: bool,
             texts: tuple[str, ...] | None = None) -> Cell:
    """Pit lane, garage, stopped on track (yellow), finished

    Args:
        texts: finish, pit, garage, slow texts (default: translated design labels).
    """
    finish, pit, garage, slow = texts or tuple(map(tr, PIT_STATUS))
    if is_finished:
        return Cell(PILL, finish, color=readable_on(theme.positive), fill=theme.positive)  # as app pages & Director
    if in_pit == 1:
        return Cell(PILL, pit, color=readable_on(theme.warning), fill=theme.warning)
    if in_pit == 2:
        return Cell(PILL, garage, color=theme.text, fill=theme.surface_strong)
    if is_yellow:
        return Cell(PILL, slow, color=readable_on(theme.caution), fill=theme.caution)
    return Cell(PILL)


class RowStyle:
    """Row cell builders that depend on widget options"""

    def __init__(self, widget, wcfg: Mapping[str, Any]):
        self.widget = widget
        self.wcfg = wcfg
        self.theme: Theme = widget.theme
        self.on_accent = readable_on(self.theme.accent)
        # Custom status texts of classic options (FIN, PIT, GAR, SLOW labels while at default)
        self.pit_texts = tuple(
            widget.user_text(key, tr(label)) for key, label in zip(PIT_STATUS_OPTIONS, PIT_STATUS)
        )
        self.unit_speed = units.set_unit_speed(widget.cfg.units["speed_unit"])

    def class_width(self) -> float:
        """Class pill width: alias part & position part"""
        widget = self.widget
        alias_w = widget.text_width("small", "LMP2") + widget.unit * 0.5
        pos_w = widget.digit_width("small") * 2 + widget.unit * 0.4
        return max(alias_w / 0.6, pos_w / 0.4)

    def name_width(self, chars: float, role: str = "value") -> float:
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

    def pitstop_cell(self, count: int, requested: bool, penalty: Penalty = NO_PENALTY) -> Cell:
        """Pit stops done, pit request, penalty: disqualified (DQ), first one to serve (DT, SG10, +10s), number
        to serve when several, time added at finish (+35s); count is penalties to serve (negative) if any"""
        theme = self.theme
        text = penalty_label(penalty, -count if count < 0 else 0)
        if text:
            if text.startswith("PEN"):  # kind unknown (penalty given before app started)
                text = tr("PEN") + text[3:]
            if penalty.disqualified or count < 0 or penalty.pending:  # red as app pages & stream graphics
                fill = theme.negative
            else:  # served by time added at finish
                fill = theme.warning
            return Cell(BADGE, text, "label", readable_on(fill), fill)
        if requested and self.wcfg.get("show_pit_request", True):
            return Cell(BADGE, f"{count}", "small", readable_on(theme.positive), theme.positive)
        if count == 0:
            return Cell(TEXT, DASH, "dim", theme.text_faint)
        return Cell(BADGE, f"{count}", "small", theme.text_dim, theme.surface_raised)

    def energy_text(self, energy: float) -> str:
        """Energy remaining in percent, decimals as set (game gives about 0.4 % steps)"""
        decimals = min(max(int(self.wcfg.get("decimal_places_energy_remaining", 0)), 0), 2)
        return f"{energy:.{decimals}%}"

    def energy_cell(self, energy: float) -> Cell:
        """Virtual energy remaining"""
        theme = self.theme
        if energy <= -1:
            return Cell(TEXT, DASH, "dim", theme.text_faint)
        tone = energy_tone(energy)  # thresholds & colors of every surface
        color = theme.negative if tone == "loss" else theme.warning if tone == "warning" else theme.positive
        return Cell(TEXT, self.energy_text(energy), "dim", color)

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

    def speed_trap_cell(self, speed: float) -> Cell:
        """Speed trap (fastest speed at speed trap line) in speed unit"""
        theme = self.theme
        if not speed > 0:
            return Cell(TEXT, DASH, "dim", theme.text_faint)
        return Cell(TEXT, f"{self.unit_speed(speed):.1f}", "dim", theme.text_dim)

    def lift_and_coast_cell(self, elapsed: float, idling: float) -> Cell:
        """Lift and coast time of current braking zone (reset after idling)"""
        theme = self.theme
        wcfg = self.wcfg
        if idling > wcfg.get("lift_and_coast_reset_threshold", 60) or not elapsed > 0:
            return Cell(TEXT, DASH, "dim", theme.text_faint)
        elapsed = min(elapsed, 99)
        text = f"{elapsed:.1f}s" if elapsed < 9.94 else f"{elapsed:.0f}s"
        high = elapsed > wcfg.get("lift_and_coast_highlight_threshold", 1)
        return Cell(TEXT, text, "dim", theme.warning if high else theme.text_dim)
