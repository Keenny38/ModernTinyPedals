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
Brake wear Widget, modern design

Sections of four brakes: remaining thickness (gauge, percent or millimeters), wear per lap,
live wear, lifespan in laps & minutes. Values past warning thresholds in red.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import calculation as calc
from ...module_info import minfo
from .base import ModernOverlay
from .quad import QuadMixin, Section, Tile

SECTIONS = (
    ("remaining", "Brake", True),
    ("wear_difference", "Wear/lap", False),
    ("live_wear_difference", "Live", False),
    ("lifespan_laps", "Laps", False),
    ("lifespan_minutes", "Minutes", False),
)


def number(value: float) -> str:
    """Value cut to 4 characters"""
    return f"{value:.2f}"[:4].strip(".")


class Realtime(QuadMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "show_thickness", "warning_threshold_remaining", "warning_threshold_wear",
        "warning_threshold_laps", "warning_threshold_minutes", *(f"show_{key}" for key, _, _ in SECTIONS),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.threshold_remaining = min(max(wcfg["warning_threshold_remaining"], 0), 100) * 0.01
        self.keys = tuple(key for key, _, _ in SECTIONS if wcfg[f"show_{key}"])
        sections = [
            Section(key, label, "88.8", min_width=3.2 if gauge else 0.0)
            for key, label, gauge in SECTIONS if key in self.keys
        ]
        self.set_size(*self.build_quads(sections, horizontal=wcfg["layout"] != 0))

    def paint_static(self, painter: QPainter):
        self.paint_quads_static(painter)

    def paint(self, painter: QPainter):
        self.draw_quads(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        wcfg = self.wcfg
        theme = self.theme
        wheels = minfo.wheels
        thickness = wcfg["show_thickness"]
        values: dict[str, list[Tile]] = {key: [] for key in self.keys}
        for index in range(4):
            current = wheels.currentBrakeThickness[index]
            failed = current <= 0
            failure = wheels.failureBrakeThickness[index]
            max_thickness = wheels.maxBrakeThickness[index] - failure
            current -= failure
            live = wheels.currentlapBrakeWear[index]
            wear = wheels.estimatedBrakeWear[index]
            valid_wear = wheels.estimatedValidBrakeWear[index]
            if max_thickness <= 0:
                max_thickness = 99999999
            live_percent = live * 100 / max_thickness
            wear_percent = wear * 100 / max_thickness
            remaining_percent = current * 100 / max_thickness
            if not thickness:
                current, live, wear, valid_wear = (value * 100 / max_thickness for value in (current, live, wear, valid_wear))
            for key in self.keys:
                if key == "remaining":
                    warn = remaining_percent <= self.threshold_remaining * 100
                    color = theme.negative if warn or failed else theme.positive
                    values[key].append(Tile(
                        ("FAIL" if failed else number(current),), colors=(theme.negative if warn or failed else theme.text,),
                        level=min(max(remaining_percent / 100, 0.0), 1.0), level_color=theme.tint(color, 110)))
                elif key == "wear_difference":
                    values[key].append(self.plain(wear, wear_percent > wcfg["warning_threshold_wear"]))
                elif key == "live_wear_difference":
                    values[key].append(self.plain(live, live_percent > wcfg["warning_threshold_wear"]))
                elif key == "lifespan_laps":
                    laps = calc.wear_lifespan_in_laps(current, valid_wear)
                    values[key].append(self.plain(laps, laps <= wcfg["warning_threshold_laps"]))
                elif key == "lifespan_minutes":
                    minutes = calc.wear_lifespan_in_mins(current, valid_wear, minfo.delta.lapTimePace)
                    values[key].append(self.plain(minutes, minutes <= wcfg["warning_threshold_minutes"]))
        self.refresh(tuple(tuple(values[key]) for key in self.keys))

    def plain(self, value: float, warn: bool) -> Tile:
        """Wheel value, red if past warning threshold"""
        theme = self.theme
        return Tile((number(value),), colors=(theme.negative if warn else theme.text,))
