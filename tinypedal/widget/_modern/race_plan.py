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
to add, tyres to change, stops left, pit menu check (refill set in game against plan) and
consumption per lap to hold until the stop, what ends stints (fuel, energy, driver, stops, tyre
life) and consumption estimate in use. Plan made by classic widget code (same plan), rest of
the race planned again at each lap & stop of a race (live replan).
"""

from __future__ import annotations

from time import monotonic

from PySide6.QtGui import QPainter

from ... import units
from ...api_control import api
from ...fuel_strategy import Strategy, StrategyInput, target_to_stop
from ...i18n import tr_overlay
from ...module_info import minfo
from ...race_live import StopCounter
from ...race_live import read_race_state as read_live
from ..race_plan import MENU_TOLERANCE, PLAN_CHECK_SECONDS, distance_text, pit_entry_ahead
from ..race_plan import Realtime as ClassicPlan
from .base import DASH, ModernOverlay
from .stats import Stat, StatsMixin, Value

# What ends stints of plan (Strategy.limit) -> label (English, translated)
LIMIT_LABELS = {"fuel": "Fuel", "energy": "Energy", "stint": "Driver", "stops": "Stops", "tyres": "Tyres"}
# Consumption estimate of fuel & energy modules (consumptionMethod) -> label
ESTIMATE_LABELS = {"game": "Game", "last_lap": "Last lap", "median": "Median"}


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "pit_window_laps", "enable_live_replan", "show_next_stop", "show_refuel",
        "show_energy", "show_tyres", "show_stops_left", "show_pit_menu", "show_target", "show_pit_entry",
        "show_stint_limit", "show_consumption_estimate",
        "display_order_next_stop", "display_order_refuel", "display_order_energy", "display_order_tyres",
        "display_order_stops_left", "display_order_pit_menu", "display_order_target", "display_order_pit_entry",
    )

    def refresh_plan(self):
        """Plan made again when race calculator inputs or its tyre plan changed (classic code)"""
        ClassicPlan.refresh_plan(self)  # type: ignore[arg-type]  # same plan attributes

    def replan(self, live):
        """Rest of the race planned again at each lap & stop of a race (classic code)"""
        ClassicPlan.replan(self, live)  # type: ignore[arg-type]  # same plan attributes

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.symbol_fuel = units.set_symbol_fuel(self.cfg.units["fuel_unit"])
        self.unit_fuel = units.set_unit_fuel(self.cfg.units["fuel_unit"])
        self.strategy = Strategy()  # plan of the race
        self.setup = StrategyInput()
        self.tyre_changes: list[int] = []
        self.live: Strategy | None = None  # plan of the rest of the race (live)
        self.live_key: tuple | None = None
        self.formation_laps = 0
        self.plan_key: tuple = ()
        self.next_check = 0.0
        self.stop_counter = StopCounter()
        stats = []
        if wcfg["show_next_stop"]:
            sample = self.widest("strong", ("L888 (88)", tr_overlay("END")))
            stats.append(Stat("next_stop", "Next stop", sample, "strong", self.theme.accent))
        if wcfg["show_refuel"]:
            stats.append(Stat("refuel", "Refuel", f"+888.8{self.symbol_fuel}"))
        if wcfg["show_energy"]:
            stats.append(Stat("energy", "Energy", "+888%"))
        if wcfg["show_tyres"]:
            stats.append(Stat("tyres", "Tyres", "4"))
        if wcfg["show_stops_left"]:
            stats.append(Stat("stops_left", "Stops", "88/88"))
        if wcfg["show_pit_menu"]:  # menu refill > planned amount after stop
            sample = self.widest("value", (f"888>888{self.symbol_fuel}", "888>888%", tr_overlay("OK")))
            stats.append(Stat("pit_menu", "Pit menu", sample))
        if wcfg["show_target"]:  # consumption per lap
            stats.append(Stat("target", "Target", self.widest("value", (f"88.88{self.symbol_fuel}", "88.88%"))))
        self.distance_unit = self.cfg.units["distance_unit"]
        if wcfg["show_pit_entry"]:  # whole meters or feet (Le Mans: 5 digits), kilometers or miles
            sample = "88.88" if self.distance_unit in ("Kilometer", "Mile") else "88888"
            stats.append(Stat("pit_entry", "Pit entry", sample + units.set_symbol_distance(self.distance_unit)))
        if wcfg["show_stint_limit"]:
            stats.append(Stat("stint_limit", "Stint limit", self.widest("value", map(tr_overlay, LIMIT_LABELS.values()))))
        if wcfg["show_consumption_estimate"]:
            sample = self.widest("value", (*map(tr_overlay, ESTIMATE_LABELS.values()), f"{tr_overlay('Median')} 88"))
            stats.append(Stat("consumption_estimate", "Consumption", sample))
        stats = self.display_ordered(stats)
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
        live = read_live(self.unit_fuel, self.stop_counter, self.symbol_fuel)
        if self.wcfg["enable_live_replan"]:
            self.replan(live)
        else:
            self.live = None
        theme = self.theme
        strategy = self.live or self.strategy
        lap = api.read.lap.completed_laps() + self.formation_laps
        in_pits = live.in_pits
        # Stop of the lap just completed still shown while in the pits (line before the pit box)
        index = next((index for index, stop in enumerate(strategy.stops)
                      if stop.lap > lap or (in_pits and stop.lap == lap)), -1)
        stop = strategy.stops[index] if index >= 0 else None
        values = []
        for key in self.keys:
            if key == "next_stop":
                if stop is None:
                    values.append(Value(tr_overlay("END") if strategy.ready else DASH, theme.text_dim))
                else:
                    to_go = max(stop.lap - lap, 0)
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
                total = strategy.stops_done + len(strategy.stops)
                left = len(strategy.stops) - index if stop else 0
                values.append(Value(f"{left}/{total}", theme.text_dim))
            elif key == "pit_menu":
                values.append(self.pit_menu_value(stop))
            elif key == "target":
                values.append(self.target_value(strategy, stop, lap + api.read.lap.progress()))
            elif key == "pit_entry":
                distance = -1.0 if in_pits else pit_entry_ahead()
                in_lap = stop is not None and stop.lap - lap <= 1 and distance >= 0  # stop at end of this lap
                values.append(Value(distance_text(distance, self.distance_unit).replace("--", DASH),
                                    theme.orange if in_lap else None,
                                    theme.tint(theme.orange, 55) if in_lap else None))
            elif key == "stint_limit":
                values.append(self.limit_value(strategy))
            elif key == "consumption_estimate":
                values.append(self.estimate_value())
        self.refresh(tuple(values))

    def limit_value(self, strategy: Strategy) -> Value:
        """What ends stints of plan, highlighted when tyre life does"""
        limit = getattr(strategy, "limit", "")
        if not strategy.ready or limit not in LIMIT_LABELS:
            return Value(DASH, self.theme.text_faint)
        tyres = limit == "tyres"
        theme = self.theme
        return Value(tr_overlay(LIMIT_LABELS[limit]), theme.warning if tyres else theme.text_dim,
                     theme.tint(theme.warning, 55) if tyres else None)

    def estimate_value(self) -> Value:
        """Consumption estimate used by fuel (or energy) module: game, last lap or median of laps"""
        energy = self.setup.fuel_per_lap <= 0 and self.setup.energy_per_lap > 0
        source = minfo.energy if energy else minfo.fuel
        method = getattr(source, "consumptionMethod", "")  # data module version without it: unknown
        if method not in ESTIMATE_LABELS:
            return Value(DASH, self.theme.text_faint)
        text = tr_overlay(ESTIMATE_LABELS[method])
        laps = getattr(source, "consumptionLaps", 0)
        if method == "median" and laps > 0:
            text = f"{text} {min(laps, 99)}"
        return Value(text, self.theme.text_dim)

    def pit_menu_value(self, stop) -> Value:
        """Refill set in game pit menu (fuel, or virtual energy of a car using it) against amount
        after next stop of the plan: OK, or menu > plan"""
        theme = self.theme
        refill = api.read.vehicle.absolute_refill()
        if stop is None or refill <= 0:
            return Value(DASH, theme.text_faint)
        if self.setup.energy_per_lap > 0:
            menu, planned, unit = refill, stop.energy_after, "%"
        else:
            menu, planned, unit = self.unit_fuel(refill), stop.fuel_after, self.symbol_fuel
        if abs(menu - planned) <= MENU_TOLERANCE:
            return Value(tr_overlay("OK"), theme.positive)
        return Value(f"{menu:.0f}>{planned:.0f}{unit}", theme.negative, theme.tint(theme.negative, 55))

    def target_value(self, strategy: Strategy, stop, position: float) -> Value:
        """Consumption per lap to reach next stop (or the finish) with fuel (or energy) of now,
        warning when last lap used more"""
        theme = self.theme
        end = stop.lap if stop is not None else strategy.last_lap
        energy = self.setup.fuel_per_lap <= 0 and self.setup.energy_per_lap > 0
        if energy:
            target = target_to_stop(self.setup, api.read.engine.virtual_energy() * 100, end - position, "energy")
            last = minfo.energy.lastLapConsumption
            unit = "%"
        else:
            target = target_to_stop(self.setup, self.unit_fuel(api.read.engine.fuel()), end - position)
            last = self.unit_fuel(minfo.fuel.lastLapConsumption)
            unit = self.symbol_fuel
        if not strategy.ready or target <= 0:
            return Value(DASH, theme.text_faint)
        over = last > target
        return Value(f"{target:.2f}{unit}", theme.warning if over else None, theme.tint(theme.warning, 55) if over else None)
