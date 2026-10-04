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
Race plan Widget

Next pit stop of the race calculator plan: lap (and laps to go), fuel & energy to add, tyres
to change, stops left. The plan is made again from the race calculator inputs (and its tyre plan)
whenever they change, so it shows with the race calculator closed too.
"""

import os
from time import monotonic

from .. import units
from ..api_control import api
from ..const_file import FileExt
from ..fuel_strategy import Strategy, plan, strategy_input_from_values
from ..setting import cfg
from ..userfile.tyre_strategy import load_tyre_strategy_file, plan_tyre_changes
from ._base import Overlay

PLAN_CHECK_SECONDS = 2.0  # race calculator inputs & tyre plan checked for changes
TYRE_PLAN_NAME = "race_calculator_tyres"  # tyre plan kept by race calculator (config folder)


class Realtime(Overlay):
    """Draw widget"""

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        layout = self.set_grid_layout(gap=self.wcfg["bar_gap"])
        self.set_primary_layout(layout=layout)

        # Config font
        font = self.config_font(
            self.wcfg["font_name"],
            self.wcfg["font_size"],
            self.wcfg["font_weight"],
        )
        self.setFont(font)
        font_m = self.get_font_metrics(font)
        bar_padx = self.set_padding(self.wcfg["font_size"], self.wcfg["bar_padding"])
        self.symbol_fuel = units.set_symbol_fuel(cfg.units["fuel_unit"])

        # Plan cache
        self.strategy = Strategy()
        self.formation_laps = 0
        self.plan_key: tuple = ()
        self.next_check = 0.0

        def add_bar(name: str, text: str, chars: int, order: int):
            bar = self.set_rawtext(
                text=text,
                width=font_m.width * chars + bar_padx,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg[f"font_color_{name}"],
                bg_color=self.wcfg[f"background_color_{name}"],
            )
            self.set_primary_orient(target=bar, column=order)
            return bar

        prefix_stop = self.wcfg["prefix_next_stop"]
        self.bar_next_stop = add_bar(
            "next_stop", f"{prefix_stop}---", len(prefix_stop) + 9,
            self.wcfg["display_order_next_stop"]) if self.wcfg["show_next_stop"] else None
        self.bar_refuel = add_bar(
            "refuel", f"+--.-{self.symbol_fuel}", 7 + len(self.symbol_fuel),
            self.wcfg["display_order_refuel"]) if self.wcfg["show_refuel"] else None
        self.bar_energy = add_bar(
            "energy", "+--%", 6, self.wcfg["display_order_energy"]) if self.wcfg["show_energy"] else None
        prefix_tyres = self.wcfg["prefix_tyres"]
        self.bar_tyres = add_bar(
            "tyres", f"{prefix_tyres}-", len(prefix_tyres) + 1,
            self.wcfg["display_order_tyres"]) if self.wcfg["show_tyres"] else None
        prefix_stops = self.wcfg["prefix_stops_left"]
        self.bar_stops_left = add_bar(
            "stops_left", f"{prefix_stops}-/-", len(prefix_stops) + 5,
            self.wcfg["display_order_stops_left"]) if self.wcfg["show_stops_left"] else None

    def timerEvent(self, event):
        """Update when vehicle on track"""
        now = monotonic()
        if now >= self.next_check:
            self.next_check = now + PLAN_CHECK_SECONDS
            self.refresh_plan()

        strategy = self.strategy
        lap = api.read.lap.completed_laps() + self.formation_laps  # plan laps count formation laps
        index = next((index for index, stop in enumerate(strategy.stops) if stop.lap > lap), -1)
        stop = strategy.stops[index] if index >= 0 else None

        if self.bar_next_stop:
            if stop is None:
                text = f"{self.wcfg['prefix_next_stop']}{'END' if strategy.ready else '---'}"
                laps_to_go = 99
            else:
                laps_to_go = stop.lap - lap
                text = f"{self.wcfg['prefix_next_stop']}L{stop.lap - self.formation_laps}({laps_to_go})"
            window = laps_to_go <= self.wcfg["pit_window_laps"]
            self.update_bar(self.bar_next_stop, text, self.wcfg[
                "warning_color_pit_window" if window else "background_color_next_stop"])
        if self.bar_refuel:
            self.update_bar(self.bar_refuel, f"+{stop.fuel:.1f}{self.symbol_fuel}" if stop else "")
        if self.bar_energy:
            self.update_bar(self.bar_energy, f"+{stop.energy:.0f}%" if stop else "")
        if self.bar_tyres:
            count = strategy.tyre_changes[index] if stop and index < len(strategy.tyre_changes) else (
                4 if stop and stop.tyres else 0)
            self.update_bar(self.bar_tyres, f"{self.wcfg['prefix_tyres']}{count or '-'}", self.wcfg[
                "highlight_color_tyre_change" if count else "background_color_tyres"])
        if self.bar_stops_left:
            total = len(strategy.stops)
            left = total - index if stop else 0
            self.update_bar(self.bar_stops_left, f"{self.wcfg['prefix_stops_left']}{left}/{total}")

    def refresh_plan(self):
        """Plan made again when race calculator inputs or its tyre plan changed"""
        values = dict(cfg.user.config.get("fuel_calculator", {}))
        filepath, filename = cfg.path.config, f"{TYRE_PLAN_NAME}{FileExt.TYRESTRATEGY}"
        try:
            mtime = os.path.getmtime(f"{filepath}{filename}")
        except OSError:
            mtime = 0.0
        key = (tuple(sorted((k, v) for k, v in values.items() if k.startswith(("input_", "enable_")))), mtime)
        if key == self.plan_key:
            return
        self.plan_key = key
        counts: list[int] = []
        times: list[float] = []
        full_change = 0.0
        tyre_data = load_tyre_strategy_file(filepath=filepath, filename=filename) if mtime else None
        if tyre_data:
            counts, times = plan_tyre_changes(tyre_data)
            full_change = float(tyre_data["tyre_rule"].get("tyre_change_time_4", 0.0))
        has_tyres = tyre_data is not None and any(any(row) for row in tyre_data["tyre_plan"])
        setup = strategy_input_from_values(values, tuple(times) if has_tyres else (), full_change)
        strategy = plan(setup)
        if has_tyres:
            strategy.tyre_changes = counts[:len(strategy.stops)]
        self.strategy = strategy
        self.formation_laps = max(int(-(-setup.formation_laps // 1)), 0)

    # GUI update methods
    def update_bar(self, target, text: str, bg_color: str = ""):
        """Bar text & background"""
        data = (text, bg_color)
        if target.last != data:
            target.last = data
            target.text = text
            if bg_color:
                target.bg = bg_color
            target.update()
