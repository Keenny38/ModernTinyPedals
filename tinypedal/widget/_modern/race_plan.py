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
Race plan Widget, modern design

Next pit stop of race calculator plan: lap & laps to go (pit window highlight), fuel & energy
to add, tyres to change, stops left. Plan made by classic widget code (same plan).
"""

from __future__ import annotations

from time import monotonic

from PySide6.QtGui import QPainter

from ... import units
from ...api_control import api
from ...fuel_strategy import Strategy
from ...i18n import tr_overlay
from ..race_plan import PLAN_CHECK_SECONDS, distance_text, pit_entry_ahead
from ..race_plan import Realtime as ClassicPlan
from .base import DASH, ModernOverlay
from .stats import Stat, StatsMixin, Value


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "pit_window_laps", "show_next_stop", "show_refuel", "show_energy",
        "show_tyres", "show_stops_left", "show_pit_entry",
    )

    def refresh_plan(self):
        """Plan made again when race calculator inputs or its tyre plan changed (classic code)"""
        ClassicPlan.refresh_plan(self)  # type: ignore[arg-type]  # same plan attributes

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.symbol_fuel = units.set_symbol_fuel(self.cfg.units["fuel_unit"])
        self.strategy = Strategy()
        self.formation_laps = 0
        self.plan_key: tuple = ()
        self.next_check = 0.0
        stats = []
        if wcfg["show_next_stop"]:
            stats.append(Stat("next_stop", "Next stop", "L888 (88)", "strong", self.theme.accent))
        if wcfg["show_refuel"]:
            stats.append(Stat("refuel", "Refuel", f"+88.8{self.symbol_fuel}"))
        if wcfg["show_energy"]:
            stats.append(Stat("energy", "Energy", "+88%"))
        if wcfg["show_tyres"]:
            stats.append(Stat("tyres", "Tyres", "4"))
        if wcfg["show_stops_left"]:
            stats.append(Stat("stops_left", "Stops", "88/88"))
        self.distance_unit = self.cfg.units["distance_unit"]
        if wcfg["show_pit_entry"]:
            stats.append(Stat("pit_entry", "Pit entry", "8888ft"))
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0)
        self.set_size(width, height)

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        now = monotonic()
        if now >= self.next_check:
            self.next_check = now + PLAN_CHECK_SECONDS
            self.refresh_plan()
        theme = self.theme
        strategy = self.strategy
        lap = api.read.lap.completed_laps() + self.formation_laps
        index = next((index for index, stop in enumerate(strategy.stops) if stop.lap > lap), -1)
        stop = strategy.stops[index] if index >= 0 else None
        values = []
        for key in self.keys:
            if key == "next_stop":
                if stop is None:
                    values.append(Value(tr_overlay("END") if strategy.ready else DASH, theme.text_dim))
                else:
                    to_go = stop.lap - lap
                    window = to_go <= self.wcfg["pit_window_laps"]
                    values.append(Value(f"L{stop.lap - self.formation_laps} ({to_go})",
                                        theme.orange if window else None,
                                        theme.tint(theme.orange, 55) if window else None))
            elif key == "refuel":
                values.append(Value(f"+{stop.fuel:.1f}{self.symbol_fuel}" if stop else DASH))
            elif key == "energy":
                values.append(Value(f"+{stop.energy:.0f}%" if stop else DASH))
            elif key == "tyres":
                if stop and index < len(strategy.tyre_changes):
                    count = strategy.tyre_changes[index]
                else:
                    count = 4 if stop and stop.tyres else 0
                values.append(Value(f"{count}" if count else DASH, theme.warning if count else theme.text_faint))
            elif key == "stops_left":
                total = len(strategy.stops)
                values.append(Value(f"{total - index if stop else 0}/{total}", theme.text_dim))
            elif key == "pit_entry":
                distance = -1.0 if api.read.vehicle.in_pits() else pit_entry_ahead()
                in_lap = stop is not None and stop.lap - lap <= 1 and distance >= 0  # stop at end of this lap
                values.append(Value(distance_text(distance, self.distance_unit).replace("--", DASH),
                                    theme.orange if in_lap else None,
                                    theme.tint(theme.orange, 55) if in_lap else None))
        self.refresh(tuple(values))
