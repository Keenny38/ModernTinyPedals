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
Brake wear Widget, modern design

Sections of four brakes: remaining thickness (gauge, percent or millimeters), wear per lap,
live wear, lifespan in laps & minutes. Values past warning thresholds in red.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QPainter

from ...i18n import tr_overlay
from ...module_info import minfo
from .._data import brake_wear_data, wear_text
from .base import ModernOverlay, display_order_options
from .draw import fraction
from .quad import QuadMixin, Section, Tile

if TYPE_CHECKING:
    from ...template.widget_config_types import BrakeWearConfig

SECTIONS = (
    ("remaining", "Brake", True),
    ("wear_difference", "Wear/lap", False),
    ("live_wear_difference", "Live", False),
    ("lifespan_laps", "Laps", False),
    ("lifespan_minutes", "Minutes", False),
)


class Realtime(QuadMixin, ModernOverlay):
    """Draw widget"""

    wcfg: BrakeWearConfig

    options = (
        "font_size", "layout", "show_thickness", "warning_threshold_remaining", "warning_threshold_wear",
        "warning_threshold_laps", "warning_threshold_minutes", *(f"show_{key}" for key, _, _ in SECTIONS),
        *display_order_options("brake_wear"),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.threshold_remaining = min(max(wcfg["warning_threshold_remaining"], 0), 100) * 0.01
        self.keys = tuple(self.display_ordered([key for key, _, _ in SECTIONS if wcfg[f"show_{key}"]], key=str))
        items = {key: (label, gauge) for key, label, gauge in SECTIONS}
        sections = [Section(key, items[key][0], "88.8", min_width=3.2 if items[key][1] else 0.0) for key in self.keys]
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
            data = brake_wear_data(wheels, index, thickness, minfo.delta.lapTimePace)
            for key in self.keys:
                if key == "remaining":
                    failed = data.failed
                    warn = data.remaining_percent <= self.threshold_remaining * 100
                    color = theme.negative if warn or failed else theme.positive
                    values[key].append(Tile(
                        (tr_overlay("FAIL") if failed else wear_text(data.remaining),),
                        colors=(theme.negative if warn or failed else theme.text,),
                        level=fraction(data.remaining_percent / 100), level_color=theme.tint(color, 110)))
                elif key == "wear_difference":
                    values[key].append(self.plain(data.wear, data.wear_percent > wcfg["warning_threshold_wear"]))
                elif key == "live_wear_difference":
                    values[key].append(self.plain(data.live, data.live_percent > wcfg["warning_threshold_wear"]))
                elif key == "lifespan_laps":
                    values[key].append(self.plain(data.laps, data.laps <= wcfg["warning_threshold_laps"]))
                elif key == "lifespan_minutes":
                    values[key].append(self.plain(data.minutes, data.minutes <= wcfg["warning_threshold_minutes"]))
        state = tuple(tuple(values[key]) for key in self.keys)
        self.refresh_keyed(state, tuple(self.pixel_key(tiles, [rect.width() for rect in slot.tiles], "level", "mark")
                                        for slot, tiles in zip(self.quad_slots, state)))

    def plain(self, value: float, warn: bool) -> Tile:
        """Wheel value, red if past warning threshold"""
        theme = self.theme
        return Tile((wear_text(value),), colors=(theme.negative if warn else theme.text,))
