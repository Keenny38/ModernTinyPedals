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
to change, stops left, pit menu check (refill set in game against plan) and consumption per lap
to hold until the stop. The race calculator keeps the input of its plan in the config folder
(tyre plan & compounds included), so the widget makes the same plan with the race calculator
closed (no such file: plan made again from the race calculator inputs & tyre plan). During a
race, the rest of the race can be planned again at each lap & stop from the car: laps & time
done, fuel, energy & tyres of now, stops done (see race_live).
"""

import json
import os
from dataclasses import fields
from math import isfinite
from time import monotonic

from .. import units
from ..api_control import api
from ..const_file import FileExt
from ..fuel_strategy import (
    Strategy,
    StrategyInput,
    plan,
    remaining_input,
    strategy_input_from_values,
    target_to_stop,
    whole_laps,
)
from ..module_info import minfo
from ..process.game_info import distance_ahead
from ..race_live import StopCounter
from ..race_live import read_race_state as read_live
from ..setting import cfg
from ..userfile.tyre_strategy import load_tyre_strategy_file, plan_tyre_changes
from ._base import Overlay

PLAN_CHECK_SECONDS = 2.0  # race calculator plan & tyre plan checked for changes
TYRE_PLAN_NAME = "race_calculator_tyres"  # tyre plan kept by race calculator (config folder)
PLAN_FILE = "race_calculator_plan.json"  # plan input kept by race calculator (config folder)
DEFAULT_INPUT = StrategyInput()
MENU_TOLERANCE = 1.0  # fuel unit or % of energy: pit menu refill close enough to plan


def pit_entry_ahead() -> float:
    """Distance to pit lane entry going forward (meters), -1 if unknown (LMU game state only)"""
    return distance_ahead(api.read.lap.pit_entry_distance(), api.read.lap.distance(), api.read.lap.track_length())


def distance_text(meters: float, unit_name: str) -> str:
    """Distance in display unit: whole meters or feet, kilometers or miles with 2 decimals"""
    if meters < 0:
        return "--"
    value = units.set_unit_distance(unit_name)(meters)
    symbol = units.set_symbol_distance(unit_name)
    if unit_name in ("Kilometer", "Mile"):
        return f"{value:.2f}{symbol}"
    return f"{value:.0f}{symbol}"


def load_plan_input(filename: str) -> tuple[StrategyInput, list[int]] | None:
    """Plan input & tyres changed at each stop kept by race calculator, None if missing or wrong"""
    try:
        with open(filename, encoding="utf-8") as file:
            data = json.load(file)
        values = data["setup"]
        kwargs = {}
        for item in fields(StrategyInput):
            if item.name not in values:
                continue
            default = getattr(DEFAULT_INPUT, item.name)
            value = values[item.name]
            if isinstance(default, tuple):
                value = tuple(float(number) for number in value)
            elif isinstance(default, bool):
                value = bool(value)
            elif isinstance(default, int):
                value = int(value)
            else:
                value = float(value)
            if not all(isfinite(number) for number in (value if isinstance(value, tuple) else (value,))):
                raise ValueError
            kwargs[item.name] = value
        changes = [int(count) for count in data.get("tyre_changes", [])]
        return StrategyInput(**kwargs), changes
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


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
        self.unit_fuel = units.set_unit_fuel(cfg.units["fuel_unit"])

        # Plan cache
        self.strategy = Strategy()  # plan of the race
        self.setup = StrategyInput()
        self.tyre_changes: list[int] = []
        self.live: Strategy | None = None  # plan of the rest of the race (live)
        self.live_key: tuple | None = None
        self.formation_laps = 0
        self.plan_key: tuple = ()
        self.next_check = 0.0
        self.stop_counter = StopCounter()

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
        prefix_menu = self.wcfg["prefix_pit_menu"]
        self.bar_pit_menu = add_bar(
            "pit_menu", f"{prefix_menu}--", len(prefix_menu) + 9,
            self.wcfg["display_order_pit_menu"]) if self.wcfg["show_pit_menu"] else None
        prefix_target = self.wcfg["prefix_target"]
        self.bar_target = add_bar(
            "target", f"{prefix_target}-.--", len(prefix_target) + 6,
            self.wcfg["display_order_target"]) if self.wcfg["show_target"] else None
        prefix_entry = self.wcfg["prefix_pit_entry"]
        self.distance_unit = cfg.units["distance_unit"]
        self.bar_pit_entry = add_bar(
            "pit_entry", f"{prefix_entry}--", len(prefix_entry) + 7,
            self.wcfg["display_order_pit_entry"]) if self.wcfg["show_pit_entry"] else None

    def timerEvent(self, event):
        """Update when vehicle on track"""
        now = monotonic()
        if now >= self.next_check:
            self.next_check = now + PLAN_CHECK_SECONDS
            self.refresh_plan()

        live = read_live(self.unit_fuel, self.stop_counter, self.symbol_fuel)
        laps_done = api.read.lap.completed_laps()
        in_pits = live.in_pits
        if self.wcfg["enable_live_replan"]:
            self.replan(live)
        else:
            self.live = None
        strategy = self.live or self.strategy
        lap = laps_done + self.formation_laps  # plan laps count formation laps
        # Stop of the lap just completed still shown while in the pits (line before the pit box)
        index = next((index for index, stop in enumerate(strategy.stops)
                      if stop.lap > lap or (in_pits and stop.lap == lap)), -1)
        stop = strategy.stops[index] if index >= 0 else None

        if self.bar_next_stop:
            if stop is None:
                text = f"{self.wcfg['prefix_next_stop']}{'END' if strategy.ready else '---'}"
                laps_to_go = 99
            else:
                laps_to_go = max(stop.lap - lap, 0)
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
            total = strategy.stops_done + len(strategy.stops)
            left = len(strategy.stops) - index if stop else 0
            self.update_bar(self.bar_stops_left, f"{self.wcfg['prefix_stops_left']}{left}/{total}")
        if self.bar_pit_menu:
            self.update_pit_menu(stop)
        if self.bar_target:
            self.update_target(strategy, stop, lap + api.read.lap.progress())
        if self.bar_pit_entry:
            in_lap = stop is not None and stop.lap - lap <= 1  # stop at end of this lap
            distance = -1.0 if in_pits else pit_entry_ahead()
            self.update_bar(self.bar_pit_entry, f"{self.wcfg['prefix_pit_entry']}"
                            f"{distance_text(distance, self.distance_unit)}", self.wcfg[
                "warning_color_pit_entry" if in_lap and distance >= 0 else "background_color_pit_entry"])

    def update_pit_menu(self, stop):
        """Refill set in game pit menu (fuel, or virtual energy of a car using it) against amount
        after next stop of the plan: OK, or menu > plan"""
        prefix = self.wcfg["prefix_pit_menu"]
        refill = api.read.vehicle.absolute_refill()
        if stop is None or refill <= 0:
            self.update_bar(self.bar_pit_menu, f"{prefix}--", self.wcfg["background_color_pit_menu"])
            return
        if self.setup.energy_per_lap > 0:
            menu, planned, unit = refill, stop.energy_after, "%"
        else:
            menu, planned, unit = self.unit_fuel(refill), stop.fuel_after, self.symbol_fuel
        if abs(menu - planned) <= MENU_TOLERANCE:
            self.update_bar(self.bar_pit_menu, f"{prefix}OK", self.wcfg["background_color_pit_menu"])
        else:
            self.update_bar(self.bar_pit_menu, f"{prefix}{menu:.0f}>{planned:.0f}{unit}",
                            self.wcfg["warning_color_pit_menu"])

    def update_target(self, strategy: Strategy, stop, position: float):
        """Consumption per lap to reach next stop (or the finish) with fuel (or energy) of now,
        warning color when last lap used more"""
        prefix = self.wcfg["prefix_target"]
        end = stop.lap if stop is not None else strategy.last_lap
        laps = end - position
        energy = self.setup.fuel_per_lap <= 0 and self.setup.energy_per_lap > 0
        if energy:
            target = target_to_stop(self.setup, api.read.engine.virtual_energy() * 100, laps, "energy")
            last = minfo.energy.lastLapConsumption
        else:
            target = target_to_stop(self.setup, self.unit_fuel(api.read.engine.fuel()), laps)
            last = self.unit_fuel(minfo.fuel.lastLapConsumption)
        if not strategy.ready or target <= 0:
            self.update_bar(self.bar_target, f"{prefix}-.--", self.wcfg["background_color_target"])
            return
        self.update_bar(self.bar_target, f"{prefix}{target:.2f}", self.wcfg[
            "warning_color_target" if last > target else "background_color_target"])

    def refresh_plan(self):
        """Plan made again when race calculator plan, inputs or tyre plan changed"""
        values = dict(cfg.user.config.get("fuel_calculator", {}))
        filepath, filename = cfg.path.config, f"{TYRE_PLAN_NAME}{FileExt.TYRESTRATEGY}"
        mtimes = []
        for name in (filename, PLAN_FILE):
            try:
                mtimes.append(os.path.getmtime(f"{filepath}{name}"))
            except OSError:
                mtimes.append(0.0)
        key = (tuple(sorted((k, v) for k, v in values.items() if k.startswith(("input_", "enable_")))), *mtimes)
        if key == self.plan_key:
            return
        self.plan_key = key
        loaded = load_plan_input(f"{filepath}{PLAN_FILE}") if mtimes[1] else None
        if loaded is not None:
            setup, counts = loaded
        else:  # no plan input kept: inputs & tyre plan of race calculator
            counts = []
            times: list[float] = []
            full_change = 0.0
            tyre_data = load_tyre_strategy_file(filepath=filepath, filename=filename) if mtimes[0] else None
            if tyre_data:
                counts, times = plan_tyre_changes(tyre_data)
                full_change = float(tyre_data["tyre_rule"].get("tyre_change_time_4", 0.0))
            if tyre_data is None or not any(any(row) for row in tyre_data["tyre_plan"]):
                counts, times = [], []
            setup = strategy_input_from_values(values, tuple(times), full_change)
        strategy = plan(setup)
        if counts:
            strategy.tyre_changes = counts[:len(strategy.stops)]
        self.strategy, self.setup, self.tyre_changes = strategy, setup, counts
        self.formation_laps = whole_laps(setup.formation_laps)
        self.live_key = None  # rest of race planned again

    def replan(self, live):
        """Rest of the race planned again at each lap & stop of a race (kept while in the pits)"""
        state = live.state
        if state is None or not self.strategy.ready:
            self.live = self.live_key = None
            return
        if live.in_pits:
            return
        key = (state.laps_done, state.stops_done, self.plan_key)
        if key == self.live_key:
            return
        self.live_key = key
        rest = plan(remaining_input(self.setup, self.strategy, state))
        if self.tyre_changes:
            rest.tyre_changes = self.tyre_changes[state.stops_done:][:len(rest.stops)]
        self.live = rest if rest.ready else None

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
