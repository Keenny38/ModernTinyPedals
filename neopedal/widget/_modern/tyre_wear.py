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
Tyre wear Widget, modern design

Sections of four tyres: remaining tread (gauge), wear per lap, live wear, flat spot wear,
lifespan in laps & minutes, tread left at end of stint. Values past warning thresholds in red.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QPainter

from ...module_info import minfo
from .._data import run_laps, tyre_wear_data, wear_text
from .base import ModernOverlay, display_order_options
from .draw import fraction
from .quad import QuadMixin, Section, Tile

if TYPE_CHECKING:
    from ...template.widget_config_types import TyreWearConfig

SECTIONS = (
    ("remaining", "Tread", True),
    ("wear_difference", "Wear/lap", False),
    ("live_wear_difference", "Live", False),
    ("flat_spot", "Flat spot", False),
    ("lifespan_laps", "Laps", False),
    ("lifespan_minutes", "Minutes", False),
    ("end_stint_remaining", "End tread", True),
)


class Realtime(QuadMixin, ModernOverlay):
    """Draw widget"""

    wcfg: TyreWearConfig

    options = (
        "font_size", "layout", "warning_threshold_remaining", "warning_threshold_wear", "warning_threshold_laps",
        "warning_threshold_minutes", *(f"show_{key}" for key, _, _ in SECTIONS),
        *display_order_options("tyre_wear"),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.keys = tuple(self.display_ordered(
            [key for key, _, _ in SECTIONS if wcfg.get(f"show_{key}", False)], key=str))
        gauges = {key for key, _, gauge in SECTIONS if gauge}
        labels = {key: label for key, label, _ in SECTIONS}
        sections = [Section(key, labels[key], "88.8", min_width=3.2 if key in gauges else 0.0) for key in self.keys]
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
        laps_left = run_laps(minfo.fuel, minfo.energy)
        data = [tyre_wear_data(wheels, index, pace, laps_left) for index in range(4)]
        sections = []
        for key in self.keys:
            tiles = []
            for wheel in data:
                if key == "remaining":
                    value, warn = wheel.remaining, wheel.remaining <= wcfg["warning_threshold_remaining"]
                elif key == "wear_difference":
                    value = wheel.wear
                    warn = value > wcfg["warning_threshold_wear"]
                elif key == "live_wear_difference":
                    value = wheel.live
                    warn = value > wcfg["warning_threshold_wear"]
                elif key == "flat_spot":
                    value = wheel.flat_spot
                    warn = value > wcfg["warning_threshold_wear"]
                elif key == "lifespan_laps":
                    value = wheel.laps
                    warn = value <= wcfg["warning_threshold_laps"]
                elif key == "lifespan_minutes":
                    value = wheel.minutes
                    warn = value <= wcfg["warning_threshold_minutes"]
                else:  # end of stint
                    value = wheel.end
                    warn = value <= wcfg["warning_threshold_remaining"]
                tiles.append(self.tile(key, value, warn))
            sections.append(tuple(tiles))
        state = tuple(sections)
        self.refresh_keyed(state, tuple(self.pixel_key(tiles, [rect.width() for rect in slot.tiles], "level", "mark")
                                        for slot, tiles in zip(self.quad_slots, state)))

    def tile(self, key: str, value: float, warn: bool) -> Tile:
        """Wheel value, gauge of remaining tread"""
        theme = self.theme
        if key in self.gauges:
            color = theme.negative if warn else theme.positive
            return Tile((wear_text(value),), colors=(theme.negative if warn else theme.text,),
                        level=fraction(value / 100), level_color=theme.tint(color, 110))
        return Tile((wear_text(value),), colors=(theme.negative if warn else theme.text,))
