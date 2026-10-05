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
Tyre wear Widget, modern design

Sections of four tyres: remaining tread (gauge), wear per lap, live wear, flat spot wear,
lifespan in laps & minutes, tread left at end of stint. Values past warning thresholds in red.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import calculation as calc
from ...module_info import minfo
from .base import ModernOverlay
from .quad import QuadMixin, Section, Tile

SECTIONS = (
    ("remaining", "Tread", True),
    ("wear_difference", "Wear/lap", False),
    ("live_wear_difference", "Live", False),
    ("flat_spot", "Flat spot", False),
    ("lifespan_laps", "Laps", False),
    ("lifespan_minutes", "Minutes", False),
    ("end_stint_remaining", "End tread", True),
)


def number(value: float) -> str:
    """Value cut to 4 characters"""
    return f"{value:.2f}"[:4].strip(".")


class Realtime(QuadMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "warning_threshold_remaining", "warning_threshold_wear", "warning_threshold_laps",
        "warning_threshold_minutes", *(f"show_{key}" for key, _, _ in SECTIONS),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.keys = tuple(key for key, _, _ in SECTIONS if wcfg.get(f"show_{key}", False))
        gauges = {key for key, _, gauge in SECTIONS if gauge}
        sections = [
            Section(key, label, "88.8", min_width=3.2 if key in gauges else 0.0)
            for key, label, _ in SECTIONS if key in self.keys
        ]
        self.gauges = gauges
        self.set_size(*self.build_quads(sections, horizontal=wcfg["layout"] != 0))

    def paint_static(self, painter: QPainter):
        self.paint_quads_static(painter)

    def paint(self, painter: QPainter):
        self.draw_quads(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        wcfg = self.wcfg
        wheels = minfo.wheels
        pace = minfo.delta.lapTimePace
        if minfo.energy.available:
            run_laps = min(minfo.fuel.estimatedLaps, minfo.energy.estimatedLaps)
        else:
            run_laps = minfo.fuel.estimatedLaps
        sections = []
        for key in self.keys:
            tiles = []
            for index in range(4):
                tread = wheels.currentTreadDepth[index]
                valid_wear = wheels.estimatedValidTreadWear[index]
                if key == "remaining":
                    value, warn = tread, tread <= wcfg["warning_threshold_remaining"]
                elif key == "wear_difference":
                    value = wheels.estimatedTreadWear[index]
                    warn = value > wcfg["warning_threshold_wear"]
                elif key == "live_wear_difference":
                    value = wheels.currentLapTreadWear[index]
                    warn = value > wcfg["warning_threshold_wear"]
                elif key == "flat_spot":
                    value = wheels.lockingTreadWear[index]
                    warn = value > wcfg["warning_threshold_wear"]
                elif key == "lifespan_laps":
                    value = calc.wear_lifespan_in_laps(tread, valid_wear)
                    warn = value <= wcfg["warning_threshold_laps"]
                elif key == "lifespan_minutes":
                    value = calc.wear_lifespan_in_mins(tread, valid_wear, pace)
                    warn = value <= wcfg["warning_threshold_minutes"]
                else:  # end of stint
                    value = calc.end_stint_tread(tread, valid_wear, run_laps)
                    warn = value <= wcfg["warning_threshold_remaining"]
                tiles.append(self.tile(key, value, warn))
            sections.append(tuple(tiles))
        self.refresh(tuple(sections))

    def tile(self, key: str, value: float, warn: bool) -> Tile:
        """Wheel value, gauge of remaining tread"""
        theme = self.theme
        if key in self.gauges:
            color = theme.negative if warn else theme.positive
            return Tile((number(value),), colors=(theme.negative if warn else theme.text,),
                        level=min(max(value / 100, 0.0), 1.0), level_color=theme.tint(color, 110))
        return Tile((number(value),), colors=(theme.negative if warn else theme.text,))
