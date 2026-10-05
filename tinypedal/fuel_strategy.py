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
Fuel strategy: pit stop plan of a race, lap by lap

Stints are whole laps (a car pits at the end of a lap). Each stint runs until fuel or energy
(whichever runs out first, energy alone if the car uses no fuel) cannot cover one more lap plus
the safety margin, or until the driver limit (stint time, total driving time of the driver), then
the car pits and takes only what it needs: a full tank while more stints follow, a splash for the
last one. Fuel and energy share the same stops. Mandatory stops (and balanced stints) spread the
race laps evenly over the stints.

Each stop costs the pit lane time, plus refuelling (amount / refuel rate), tyre change and
driver change; tyres can be changed while refuelling (longest of both counts). Lap time follows
fuel in tank (heavier car is slower), track evolution, pace of the driver and fuel saving. A time
race lasts the laps that fit in race time with these lap & stop times: race length and stops are
settled together. A safety car period slows laps and consumption, a stop under safety car loses
less time.

Tyres are changed at a stop when the next stint would wear them below the minimum tread.

A plan can also cover the rest of a race under way (live race state, see remaining_input): laps,
race clock, fuel, energy & tread of now, stops & driving time done. Plans are cached (same input,
same plan).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from functools import lru_cache
from math import ceil, floor, inf, isfinite
from statistics import median
from typing import NamedTuple

from .module_info import ConsumptionDataSet

MAX_STOPS = 200  # simulation guard: tank too small for the race
MAX_ROUNDS = 20  # time race: race length & stops settling rounds
FRESH_TREAD = 100.0  # tread of new tyres (%)
EPSILON = 1e-9
MARGIN_UNITS = ("laps", "fuel", "percent")  # safety margin unit, by input index


@dataclass(frozen=True)
class StrategyInput:
    """Race setup, consumption & tyres (fuel in display unit, energy & tread in %)"""

    laptime: float = 0.0  # seconds, at half tank on a fresh track
    race_minutes: float = 0.0  # time race, 0 for lap race
    race_laps: int = 0  # lap race
    formation_laps: float = 0.0  # driven before race clock starts (0.5: rolling start, half a lap of fuel)
    pit_seconds: float = 0.0  # time lost per stop in pit lane (service time added)
    tank_capacity: float = 0.0
    fuel_per_lap: float = 0.0
    energy_per_lap: float = 0.0  # 0 if car has no virtual energy
    fuel_start: float = 0.0  # 0 = full tank
    energy_start: float = 0.0  # 0 = full (100%)
    margin_laps: float = 0.0  # safety margin kept in tank at every stop & at finish (laps)
    margin_fuel: float = 0.0  # safety margin in fuel units (energy: same laps)
    margin_percent: float = 0.0  # safety margin on consumption (% more per lap)
    tread_start: float = FRESH_TREAD
    fresh_tread: float = FRESH_TREAD  # tread of tyres fitted at a stop
    wear_per_lap: float = 0.0
    minimum_tread: float = 0.0  # change tyres before going below
    stop_extra_seconds: tuple[float, ...] = ()  # tyre change time of each stop (tyre plan)
    tyre_change_seconds: float = 0.0  # proposed tyre change (4 tyres) without tyre plan
    refuel_rate: float = 0.0  # fuel unit per second, 0 = refuelling inside pit time
    energy_rate: float = 0.0  # % per second, 0 = inside pit time
    tyres_during_refuel: bool = False  # tyre change & refuelling at the same time
    minimum_stops: int = 0  # mandatory stops
    balanced_stints: bool = False  # race laps spread evenly over the stints (same stops)
    max_stint_minutes: float = 0.0  # driver limit per stint, 0 = none
    drivers: int = 1  # drivers take turns
    driver_change_seconds: float = 0.0
    stints_per_driver: int = 1  # stints driven before next driver takes over
    driver_pace: tuple[float, ...] = ()  # lap time difference of each driver (seconds)
    driver_max_minutes: tuple[float, ...] = ()  # total driving time allowed to each driver, 0 = none
    driver_min_minutes: tuple[float, ...] = ()  # total driving time each driver must reach, 0 = none
    fuel_effect: float = 0.0  # seconds per lap per 10 fuel units in tank (from half tank)
    track_evolution: float = 0.0  # seconds per lap per hour of race (negative = faster)
    saving_seconds: float = 0.0  # lap time lost by fuel saving of this plan
    saving_cost: float = 0.0  # lap time lost per 10% less consumption (lift & coast)
    sc_lap: int = 0  # safety car scenario: first lap under safety car (plan lap), 0 = none
    sc_laps: int = 0  # laps under safety car
    sc_consumption: float = 0.5  # consumption under safety car (fraction of race pace)
    sc_laptime: float = 1.5  # lap time under safety car (factor of race pace)
    sc_pit: bool = False  # stop at end of first lap under safety car
    sc_pit_saving: float = 0.5  # fraction of pit lane time not lost under safety car
    sc_wear: float = 1.0  # tyre wear under safety car (fraction of race pace)
    rain_lap: int = 0  # rain scenario: first lap in the wet (plan lap), 0 = none
    rain_laps: int = 0  # laps in the wet, 0 = until the finish
    rain_consumption: float = 1.0  # consumption in the wet (fraction of race pace)
    rain_laptime: float = 1.1  # lap time in the wet (factor of race pace)
    rain_tyres: bool = False  # tyres changed at end of first & last lap in the wet
    pit_lap_consumption: float = 1.0  # consumption of in & out laps (fraction of race pace)
    extra_laps: int = 0  # time race: laps after the one the timer ends in (leader finishes first)
    lap_offset: int = 0  # race under way: plan laps done (formation included)
    clock_offset: float = 0.0  # race under way: race clock at plan start (seconds)
    stops_done: int = 0  # race under way: stops done
    driver_start: int = 1  # driver of first stint
    driver_stints_done: int = 0  # stints driven by driver_start in current turn
    stint_seconds_done: float = 0.0  # time driven in current stint (driver limit)
    driver_seconds_done: tuple[float, ...] = ()  # driving time done by each driver


@dataclass(frozen=True)
class PitStop:
    """One stop: lap pitted at end of, amounts added, tyres changed, time spent"""

    lap: int
    fuel: float
    energy: float
    tyres: bool
    seconds: float = 0.0  # whole stop: pit lane & service
    refuel_seconds: float = 0.0
    tyre_seconds: float = 0.0
    driver: int = 1  # driver of the next stint
    clock: float = 0.0  # race clock when pitting (seconds from green flag)
    safety_car: bool = False  # stop under safety car
    fuel_after: float = 0.0  # in tank after the stop (pit menu refill)
    energy_after: float = 0.0
    reason: str = ""  # stop set by scenario: "sc" (safety car), "rain" (wet tyres), "dry" (back on slicks)


@dataclass
class Strategy:
    """Pit stop plan"""

    race_laps: int = 0  # whole laps of plan incl. formation laps
    stints: list[int] = field(default_factory=list)  # laps of each stint
    stint_seconds: list[float] = field(default_factory=list)  # driving time of each stint
    stint_drivers: list[int] = field(default_factory=list)  # driver of each stint
    stops: list[PitStop] = field(default_factory=list)
    fuel_needed: float = 0.0  # whole race incl. margin
    energy_needed: float = 0.0
    fuel_load: float = 0.0  # fuel to load at start (start fuel, or exact amount without stop)
    energy_load: float = 0.0
    limit: str = "fuel"  # what ends stints: "fuel", "energy", "stint" (driver limit) or "stops" (mandatory)
    feasible: bool = True
    problem: str = ""  # not feasible: "tank" (full tank below one lap), "start" (start amount), "stops"
    tyre_changes: list[int] = field(default_factory=list)  # tyres changed per stop (tyre plan), empty: proposed
    fitting_laps: int = 0  # time race: laps that fit in race time with these lap & stop times
    race_seconds: float = 0.0  # race clock at finish of plan (laps, stops), from plan start
    first_lap: int = 0  # race under way: laps done before plan, stop laps count them
    stops_done: int = 0  # race under way: stops done before plan
    windows: list[tuple[int, int]] = field(default_factory=list)  # pit window of each stop (laps)
    driver_seconds: list[float] = field(default_factory=list)  # total driving time of each driver
    driver_issues: list[tuple[int, str]] = field(default_factory=list)  # (driver, "min" | "max") not met
    saving_seconds: float = 0.0  # lap time lost by fuel saving
    safety_car: tuple[int, int] = (0, 0)  # first lap & laps under safety car (in the plan)
    rain: tuple[int, int] = (0, 0)  # first & last lap in the wet (in the plan)

    @property
    def ready(self) -> bool:
        """Plan to show: race set up and stints planned"""
        return self.race_laps > 0 and bool(self.stints)

    @property
    def impossible(self) -> bool:
        """Race set up, but no plan: tank or start amount cannot cover one lap plus margin"""
        return self.race_laps > 0 and not self.feasible

    @property
    def last_lap(self) -> int:
        return self.first_lap + self.race_laps

    @property
    def average_fuel(self) -> float:
        """Average fuel added per stop"""
        return sum(stop.fuel for stop in self.stops) / len(self.stops) if self.stops else 0.0

    @property
    def average_energy(self) -> float:
        return sum(stop.energy for stop in self.stops) / len(self.stops) if self.stops else 0.0

    @property
    def max_stint(self) -> int:
        return max(self.stints, default=0)

    @property
    def tyre_stops(self) -> list[int]:
        return [stop.lap for stop in self.stops if stop.tyres]

    @property
    def pit_seconds(self) -> float:
        """Time spent in the pits over the race"""
        return sum(stop.seconds for stop in self.stops)

    def stint_bounds(self) -> list[tuple[int, int]]:
        """First & last lap of each stint (plan laps)"""
        bounds = []
        first = self.first_lap
        for laps in self.stints:
            bounds.append((first + 1, first + laps))
            first += laps
        return bounds

    def driver_of(self, stint_index: int) -> int:
        if 0 <= stint_index < len(self.stint_drivers):
            return self.stint_drivers[stint_index]
        return self.stops[stint_index - 1].driver if 0 < stint_index <= len(self.stops) else 1


def whole_laps(laps: float) -> int:
    """Whole laps of a lap count (0.5 formation lap is one lap driven)"""
    return ceil(laps - EPSILON) if laps > 0 else 0


def race_laps_for(setup: StrategyInput, stops: int) -> int:
    """Whole race laps incl. formation, time race shortened by pit time of stops (constant lap time)"""
    formation = whole_laps(setup.formation_laps)
    if setup.race_minutes > 0:
        if setup.laptime <= 0:
            return 0
        seconds = setup.race_minutes * 60 - stops * setup.pit_seconds - sum(setup.stop_extra_seconds[:stops])
        return formation + max(ceil(seconds / setup.laptime - EPSILON), 0)
    return formation + max(setup.race_laps, 0)


def lap_time(setup: StrategyInput, fuel_in_tank: float, race_clock: float) -> float:
    """Lap time with fuel in tank (from half tank) and track evolution"""
    seconds = setup.laptime
    if setup.fuel_effect and setup.tank_capacity > 0:
        seconds += setup.fuel_effect * 0.1 * (fuel_in_tank - setup.tank_capacity / 2)
    if setup.track_evolution:
        seconds += setup.track_evolution * race_clock / 3600
    return max(seconds, 1.0) if setup.laptime > 0 else 0.0


def consumption(setup: StrategyInput) -> dict[str, float]:
    """Planned consumption per lap of fuel & energy used, safety margin on consumption included"""
    scale = 1 + max(setup.margin_percent, 0.0) / 100
    return {
        name: per_lap * scale for name, per_lap, capacity in (
            ("fuel", setup.fuel_per_lap, setup.tank_capacity), ("energy", setup.energy_per_lap, 100.0))
        if per_lap > 0 and capacity > 0
    }


def reserves(setup: StrategyInput, usage: dict[str, float]) -> dict[str, float]:
    """Amount kept in tank at every stop & at finish (safety margin)"""
    reserve = {name: setup.margin_laps * usage.get(name, 0.0) for name in ("fuel", "energy")}
    if setup.margin_fuel > 0 and "fuel" in usage:
        for name, per_lap in usage.items():  # energy: same laps as fuel margin
            reserve[name] += setup.margin_fuel / usage["fuel"] * per_lap
    return reserve


def stint_laps(amounts: dict[str, float], usage: dict[str, float], reserve: dict[str, float]) -> int:
    """Whole laps until any resource cannot cover one more lap plus its reserve"""
    laps = None
    for name, per_lap in usage.items():
        if per_lap <= 0:
            continue
        fit = floor((amounts[name] - reserve[name]) / per_lap + EPSILON)
        laps = fit if laps is None else min(laps, fit)
    return max(laps, 0) if laps is not None else 0


def full_tank_laps(setup: StrategyInput) -> int:
    """Laps a full refill covers (resource running out first), safety margin kept"""
    usage = consumption(setup)
    return stint_laps({"fuel": setup.tank_capacity, "energy": 100.0}, usage, reserves(setup, usage))


def stop_time(setup: StrategyInput, index: int, fuel: float, energy: float, tyres: bool,
              driver_change: bool | None = None, safety_car: bool = False,
              full_tyre_change: bool = False) -> tuple[float, float, float]:
    """(whole stop, refuelling, tyre change) seconds of stop index, full_tyre_change: 4 tyres
    changed whatever the tyre plan (wet tyres)"""
    refuel = max(fuel / setup.refuel_rate if setup.refuel_rate > 0 else 0.0,
                 energy / setup.energy_rate if setup.energy_rate > 0 else 0.0)
    if setup.stop_extra_seconds:
        tyre = setup.stop_extra_seconds[index] if index < len(setup.stop_extra_seconds) else 0.0
    else:
        tyre = setup.tyre_change_seconds if tyres else 0.0
    if full_tyre_change:
        tyre = max(tyre, setup.tyre_change_seconds)
    service = max(refuel, tyre) if setup.tyres_during_refuel else refuel + tyre
    if driver_change is None:
        driver_change = setup.drivers > 1
    driver = setup.driver_change_seconds if driver_change else 0.0
    pit = setup.pit_seconds * (1 - min(max(setup.sc_pit_saving, 0.0), 1.0)) if safety_car else setup.pit_seconds
    return pit + service + driver, refuel, tyre


class Period(NamedTuple):
    """Scenario period (plan laps): consumption, lap time & tyre wear against race pace"""

    first: int
    last: int
    consumption: float
    laptime: float
    wear: float
    kind: str  # "sc" (safety car) or "rain"


def periods_of(setup: StrategyInput, end: int) -> list[Period]:
    """Safety car & rain periods of the scenario (rain without laps lasts until `end`)"""
    periods = []
    if setup.sc_lap > 0 and setup.sc_laps > 0:
        periods.append(Period(setup.sc_lap, setup.sc_lap + setup.sc_laps - 1,
                              setup.sc_consumption, setup.sc_laptime, setup.sc_wear, "sc"))
    if setup.rain_lap > 0:
        last = setup.rain_lap + setup.rain_laps - 1 if setup.rain_laps > 0 else max(end, setup.rain_lap)
        periods.append(Period(setup.rain_lap, last, setup.rain_consumption, setup.rain_laptime, 1.0, "rain"))
    return periods


def simulate(setup: StrategyInput, race_laps: int, stints: int = 0) -> Strategy:
    """Pit stop plan for a race length (laps of plan), at least stints stints when the race is
    long enough (0 = no minimum)"""
    usage = consumption(setup)
    capacity = {"fuel": setup.tank_capacity, "energy": 100.0}
    reserve = reserves(setup, usage)
    first = setup.lap_offset  # plan laps done before (race under way)
    end = first + race_laps
    formation = whole_laps(setup.formation_laps) if not first else 0
    partial = formation - setup.formation_laps if formation else 0.0  # formation lap not driven in full
    if partial < EPSILON:
        partial = 0.0
    pit_factor = max(setup.pit_lap_consumption, 0.0)  # in & out laps
    periods = [period for period in periods_of(setup, end) if period.first <= end and period.last > first]
    last_special = max([formation if partial else 0, *(period.last for period in periods)])
    sc = next((period for period in periods if period.kind == "sc"), None)
    rain = next((period for period in periods if period.kind == "rain"), None)
    forced: dict[int, str] = {}  # stops set by scenario: lap, reason
    if sc is not None and setup.sc_pit and first < sc.first < end:
        forced[sc.first] = "sc"
    if rain is not None and setup.rain_tyres:
        if first < rain.first < end:
            forced[rain.first] = "rain"
        if first < rain.last < end:
            forced[rain.last] = "dry"

    def usage_factor(lap: int) -> float:
        """Consumption of a lap (plan lap number), in laps at race pace"""
        factor = 1.0
        if partial and lap == formation:
            factor -= partial
        for period in periods:
            if period.first <= lap <= period.last:
                factor *= period.consumption
        return factor

    def overlap_units(after: int, until: int, wear: bool) -> float:
        """Laps at race pace saved by periods (consumption or tyre wear) over laps after `after`
        until `until`"""
        saved = 0.0
        for period in periods:
            overlap = min(until, period.last) - max(after + 1, period.first) + 1
            if overlap > 0:
                saved += overlap * (1 - (period.wear if wear else period.consumption))
        return saved

    def units(after: int, until: int) -> float:
        """Consumption of laps after lap `after` until lap `until`, in laps at race pace"""
        count = float(until - after)
        if after >= last_special:
            return count
        if partial and after < formation <= until:
            count -= partial
        return count - overlap_units(after, until, False)

    def wear_units(after: int, until: int) -> float:
        """Tyre wear of laps after `after` until `until`, in laps at race pace"""
        return until - after - overlap_units(after, until, True) if periods else float(until - after)

    def stint_units(lap: int, stint: int, after_stop: bool) -> float:
        """Consumption of a stint, out lap (after a stop) & in lap (stop at its end) included"""
        total = units(lap, lap + stint)
        if pit_factor != 1 and stint > 0:
            if after_stop:
                total -= usage_factor(lap + 1) * (1 - pit_factor)
            if lap + stint < end:
                total -= usage_factor(lap + stint) * (pit_factor if after_stop and stint == 1 else 1) * (1 - pit_factor)
        return total

    amounts = {
        "fuel": setup.fuel_start if setup.fuel_start > 0 else setup.tank_capacity,
        "energy": setup.energy_start if setup.energy_start > 0 else 100.0,
    }
    race_units = units(first, end) if race_laps > 0 else 0.0
    needed = {name: race_units * usage.get(name, 0.0) + reserve[name] for name in capacity}
    strategy = Strategy(
        race_laps=race_laps, fuel_needed=needed["fuel"], energy_needed=needed["energy"],
        first_lap=first, stops_done=setup.stops_done, saving_seconds=setup.saving_seconds,
        safety_car=(sc.first, sc.last - sc.first + 1) if sc else (0, 0),
        rain=(rain.first, min(rain.last, end)) if rain else (0, 0),
    )
    if race_laps <= 0 or not usage:
        return strategy
    # Limit: resource giving fewer laps on a full refill, or driver limit
    full = {name: (capacity[name] - reserve[name]) / per_lap for name, per_lap in usage.items()}
    strategy.limit = min(full, key=lambda name: full[name])
    cap_laps = stint_limit(setup)
    if cap_laps and cap_laps < min(full.values()):
        strategy.limit = "stint"
    drivers = max(setup.drivers, 1)
    max_total = [minutes * 60 for minutes in setup.driver_max_minutes[:drivers]]
    min_total = [minutes * 60 for minutes in setup.driver_min_minutes[:drivers]]
    no_stop = all(needed[name] <= capacity[name] + EPSILON for name in usage)
    constrained = (stints > 1 or setup.max_stint_minutes > 0 or any(max_total) or any(min_total)
                   or bool(forced))
    if no_stop and setup.fuel_start <= 0 and setup.energy_start <= 0 and not constrained:
        amounts = {name: min(needed[name], capacity[name]) for name in amounts}  # exact load
    strategy.fuel_load = amounts["fuel"] if "fuel" in usage else 0.0
    strategy.energy_load = amounts["energy"] if "energy" in usage else 0.0

    fuel_lap = usage.get("fuel", 0.0)
    pace = setup.driver_pace[:drivers]
    time_limit = setup.race_minutes * 60
    stint_cap = setup.max_stint_minutes * 60

    def fuel_in_tank() -> float:  # car using no fuel: no fuel effect on lap time (half tank)
        return amounts["fuel"] if fuel_lap else setup.tank_capacity / 2

    def lap_seconds(lap: int, fuel: float, clock: float, driver: int) -> float:
        seconds = lap_time(setup, fuel, setup.clock_offset + clock)
        if seconds <= 0:
            return 0.0
        seconds += setup.saving_seconds + (pace[driver - 1] if driver <= len(pace) else 0.0)
        for period in periods:
            if period.first <= lap <= period.last:
                seconds *= period.laptime
        return max(seconds, 1.0)

    # Same time every lap: stints driven in one go (no lap by lap simulation)
    constant = (setup.laptime > 0 and not setup.fuel_effect and not setup.track_evolution
                and not periods and not any(pace))
    fixed = lap_seconds(0, 0.0, 0.0, 1) if constant else 0.0
    lap_estimate = fixed or max(setup.laptime, 1.0)
    driven = [0.0] * drivers
    for index, seconds in enumerate(setup.driver_seconds_done[:drivers]):
        driven[index] = seconds

    def others_need(driver: int) -> float:
        """Driving time other drivers still need to reach their minimum"""
        return sum(max(minimum - driven[index], 0.0) for index, minimum in enumerate(min_total)
                   if index != driver - 1)

    def race_time_left(lap: int, clock: float) -> float:
        if time_limit > 0:
            return max(time_limit - clock, 0.0)
        return (end - lap) * lap_estimate

    def time_allowed(driver: int, stint_done: float, lap: int, clock: float) -> float:
        """Driving time left to the driver for a stint: stint limit, total limit, and time
        other drivers need to reach their minimum"""
        allowed = stint_cap - stint_done if stint_cap > 0 else inf
        if driver <= len(max_total) and max_total[driver - 1] > 0:
            allowed = min(allowed, max_total[driver - 1] - driven[driver - 1])
        need = others_need(driver)
        if need > EPSILON:
            allowed = min(allowed, max(race_time_left(lap, clock) - need, lap_estimate))
        return allowed

    def next_special(lap: int) -> float:
        """First lap after `lap` not at race pace consumption (rolling start, scenario period)"""
        laps = [formation] if partial and formation > lap else []
        for period in periods:
            if period.last > lap:
                laps.append(max(period.first, lap + 1))
        return min(laps, default=inf)

    def laps_fitting(lap: int, limit: int, after_stop: bool) -> int:
        """Whole laps after `lap` that fuel & energy cover, safety margin kept (out lap after a
        stop & in lap before the next one at pit lap consumption)"""
        quick = min(stint_laps(amounts, usage, reserve), limit)
        if pit_factor == 1:
            last_checked = lap + quick + (0 if quick == limit else 1)  # laps covered & first lap not covered
            if lap >= last_special or last_checked < next_special(lap):
                return quick  # all at race pace consumption: no lap by lap count needed
        left = {name: amounts[name] - reserve[name] for name in usage}
        used = dict.fromkeys(usage, 0.0)
        count = 0
        while count < limit:
            lap_no = lap + count + 1
            factor = usage_factor(lap_no) * (pit_factor if after_stop and not count else 1.0)
            in_lap = pit_factor if lap_no < end else 1.0  # this lap as last of stint
            if any(used[name] + per_lap * factor * in_lap > left[name] + EPSILON for name, per_lap in usage.items()):
                break
            for name, per_lap in usage.items():
                used[name] += per_lap * factor
            count += 1
        return count

    def stint_length(lap: int, clock: float, driver: int, stint_count: int, after_stop: bool,
                     stint_done: float = 0.0) -> int:
        """Laps of the stint starting after `lap`"""
        laps_left = end - lap
        laps = laps_fitting(lap, laps_left, after_stop)
        stints_left = stints - stint_count
        if stints_left > 1:
            laps = min(laps, ceil(laps_left / stints_left - EPSILON))
        for stop_lap in sorted(forced):  # stop set by scenario
            if lap < stop_lap <= lap + laps:
                laps = stop_lap - lap
                break
        allowed = time_allowed(driver, stint_done, lap, clock)
        if allowed == inf or laps <= 1:
            return laps
        if constant:
            return min(laps, max(floor(allowed / fixed + EPSILON), 1))
        fuel = fuel_in_tank()
        total = 0.0
        for count in range(laps):
            lap_no = lap + count + 1
            seconds = lap_seconds(lap_no, fuel, clock + total, driver)
            if count and total + seconds > allowed + EPSILON:
                return count
            total += seconds
            fuel -= fuel_lap * usage_factor(lap_no)
        return laps

    def next_driver(driver: int, lap: int, clock: float) -> int:
        """Next driver in turn: one short of minimum driving time first, else one with driving time
        left for a whole stint, else the one with most time left (a driver with a few minutes left
        would cost one stop more)"""
        order = [(driver - 1 + step) % drivers + 1 for step in range(1, drivers + 1)]
        for candidate in order:
            if candidate != driver and candidate <= len(min_total) and driven[candidate - 1] < min_total[candidate - 1] - EPSILON:
                return candidate
        stint_time = laps_fitting(lap, end - lap, True) * lap_estimate
        best, best_left = order[0], -inf
        for candidate in order:
            if candidate > len(max_total) or max_total[candidate - 1] <= 0:
                return candidate
            left = max_total[candidate - 1] - driven[candidate - 1]
            if left >= stint_time - EPSILON:
                return candidate
            if left > best_left:
                best, best_left = candidate, left
        return best

    clock = 0.0  # race clock from plan start, runs after formation laps
    tread = setup.tread_start
    driver = min(max(setup.driver_start, 1), drivers)
    turn_stints = setup.driver_stints_done
    stint_done = setup.stint_seconds_done
    lap = first
    while lap < end:
        after_stop = bool(strategy.stops)
        stint = stint_length(lap, clock, driver, len(strategy.stints), after_stop, stint_done)
        stint_done = 0.0
        if stint <= 0:
            strategy.feasible = False
            strategy.problem = "tank" if after_stop or min(full.values()) < 1 - EPSILON else "start"
            break
        if constant and pit_factor == 1:
            seconds = fixed * stint
            clock_laps = min(max(lap + stint - max(lap, formation), 0), stint)  # laps on race clock
            if time_limit and not strategy.fitting_laps and clock_laps:
                need = max(ceil((time_limit - clock) / fixed - EPSILON), 1)
                if need <= clock_laps:  # timer ends during this lap: last lap (and laps after)
                    strategy.fitting_laps = max(lap, formation) + need - first + setup.extra_laps
            clock += fixed * clock_laps
            for name, per_lap in usage.items():
                amounts[name] -= per_lap * stint_units(lap, stint, after_stop)
            lap += stint
        else:
            seconds = 0.0
            stint_end = lap + stint
            for count in range(stint):
                lap += 1
                seconds_lap = lap_seconds(lap, fuel_in_tank(), clock, driver)
                seconds += seconds_lap
                if lap > formation:
                    clock += seconds_lap
                    if time_limit and not strategy.fitting_laps and clock >= time_limit - EPSILON:
                        strategy.fitting_laps = lap - first + setup.extra_laps  # timer ends during this lap
                factor = usage_factor(lap)
                if pit_factor != 1:
                    if after_stop and not count:
                        factor *= pit_factor  # out lap
                    if lap == stint_end and lap < end:
                        factor *= pit_factor  # in lap
                for name, per_lap in usage.items():
                    amounts[name] -= per_lap * factor
        strategy.stints.append(stint)
        strategy.stint_seconds.append(seconds)
        strategy.stint_drivers.append(driver)
        driven[driver - 1] += seconds
        tread -= setup.wear_per_lap * wear_units(lap - stint, lap)
        if lap >= end:
            break
        if len(strategy.stops) >= MAX_STOPS:
            strategy.feasible = False
            strategy.problem = "stops"
            break
        # Pit: take what is needed to finish, at most a full tank
        added = {"fuel": 0.0, "energy": 0.0}
        to_finish = units(lap, end) - ((1 - pit_factor) * usage_factor(lap + 1) if pit_factor != 1 else 0.0)
        for name, per_lap in usage.items():
            want = to_finish * per_lap + reserve[name] - amounts[name]
            added[name] = min(max(want, 0.0), capacity[name] - amounts[name])
            amounts[name] += added[name]
        # Next driver: after stints_per_driver stints, or when another driver needs driving time
        turn_stints += 1
        new_driver = driver
        if drivers > 1 and (turn_stints >= max(setup.stints_per_driver, 1) or others_need(driver) > EPSILON):
            new_driver = next_driver(driver, lap, clock)
        change = new_driver != driver
        if change:
            turn_stints = 0
        # Tyres: wear over the stint actually driven next, new ones for wet & back to slicks
        reason = forced.get(lap, "")
        tyres = reason in ("rain", "dry")
        if setup.wear_per_lap > 0 and not tyres:
            next_stint = stint_length(lap, clock, new_driver, len(strategy.stints), True)
            tyres = tread - setup.wear_per_lap * wear_units(lap, lap + next_stint) < setup.minimum_tread
        if tyres:
            tread = setup.fresh_tread
        under_safety_car = sc is not None and sc.first <= lap <= sc.last
        seconds_stop, refuel, tyre = stop_time(
            setup, len(strategy.stops), added["fuel"], added["energy"], tyres, change, under_safety_car,
            reason in ("rain", "dry"))
        strategy.stops.append(PitStop(
            lap, added["fuel"], added["energy"], tyres, seconds_stop, refuel, tyre, new_driver,
            setup.clock_offset + clock, under_safety_car,
            amounts["fuel"] if "fuel" in usage else 0.0, amounts["energy"] if "energy" in usage else 0.0,
            reason))
        clock += seconds_stop
        driver = new_driver
    strategy.race_seconds = clock
    if time_limit and not strategy.fitting_laps and strategy.feasible:
        # Race time left after planned laps: more laps at last lap time
        last = lap_seconds(end, fuel_in_tank(), clock, driver) or 1.0
        strategy.fitting_laps = race_laps + max(ceil((time_limit - clock) / last - EPSILON), 0) + setup.extra_laps
    strategy.driver_seconds = driven
    for index in range(drivers):
        maximum = max_total[index] if index < len(max_total) else 0.0
        minimum = min_total[index] if index < len(min_total) else 0.0
        if maximum > 0 and driven[index] > maximum + EPSILON:
            strategy.driver_issues.append((index + 1, "max"))
        if minimum > 0 and driven[index] < minimum - EPSILON:
            strategy.driver_issues.append((index + 1, "min"))
    return strategy


def stint_limit(setup: StrategyInput) -> int:
    """Stint length limit in laps from driver limit at race pace (0 = none)"""
    if setup.max_stint_minutes > 0 and setup.laptime > 0:
        return max(floor(setup.max_stint_minutes * 60 / setup.laptime + EPSILON), 1)
    return 0


def estimated_stops(setup: StrategyInput, stints: int = 0) -> int:
    """Stops of a time race from fuel & energy on full tanks (constant lap time), to start
    settling race length & stops close to where they agree"""
    usage = consumption(setup)
    laps = race_laps_for(setup, 0) - whole_laps(setup.formation_laps) + setup.formation_laps
    if not usage or laps <= 0:
        return 0
    reserve = reserves(setup, usage)
    start = {"fuel": setup.fuel_start or setup.tank_capacity, "energy": setup.energy_start or 100.0}
    capacity = {"fuel": setup.tank_capacity, "energy": 100.0}
    stops = max(stints - 1, setup.minimum_stops, 0)
    for _ in range(3):  # stops shorten the race: count again with their pit time
        laps = race_laps_for(setup, stops) - whole_laps(setup.formation_laps) + setup.formation_laps
        count = max(stints - 1, setup.minimum_stops, 0)
        for name, per_lap in usage.items():
            usable = capacity[name] - reserve[name]
            if usable <= per_lap:
                return 0
            count = max(count, ceil((laps * per_lap + reserve[name] - start[name]) / usable - EPSILON))
        cap = stint_limit(setup)
        if cap:
            count = max(count, ceil(laps / cap - EPSILON) - 1)
        if count == stops:
            break
        stops = max(count, 0)
    return max(stops, 0)


def constant_laps(setup: StrategyInput) -> bool:
    """Same time every lap (no fuel effect, track evolution, scenario or driver pace)"""
    return (setup.laptime > 0 and not setup.fuel_effect and not setup.track_evolution
            and not (setup.sc_lap > 0 and setup.sc_laps > 0) and not setup.rain_lap
            and not any(setup.driver_pace[:max(setup.drivers, 1)]))


def plan_race(setup: StrategyInput, stints: int = 0) -> Strategy:
    """Pit stop plan, race length and stops agreeing (time race: pit time costs laps)

    More stops shorten a time race, which may need fewer stops. On a back and forth, the longer
    race of the back and forth is kept (its stops cover the shorter one too), so fuel is never
    short. Same time every lap: settling starts from the stops fuel & energy need (one length
    agrees), else from the race without stop (the longest of the lengths agreeing is found).
    """
    if setup.race_minutes <= 0:
        return simulate(setup, race_laps_for(setup, 0), stints)
    laps = race_laps_for(setup, estimated_stops(setup) if constant_laps(setup) and stints <= 1 else 0)
    seen: dict[int, Strategy] = {}
    visited: list[int] = []
    for _ in range(MAX_ROUNDS):
        strategy = simulate(setup, laps, stints)
        seen[laps] = strategy
        visited.append(laps)
        if not strategy.feasible or not strategy.stints:
            return strategy
        if strategy.fitting_laps == laps:
            return strategy
        if strategy.fitting_laps in seen:  # back and forth: longest length of it
            cycle = visited[visited.index(strategy.fitting_laps):]
            return max((seen[count] for count in cycle), key=lambda strategy: strategy.race_laps)
        laps = strategy.fitting_laps
    return max(seen.values(), key=lambda strategy: strategy.race_laps)


def copy_strategy(strategy: Strategy) -> Strategy:
    """Copy free to change (lists not shared with the cached plan)"""
    return replace(
        strategy,
        stints=list(strategy.stints), stint_seconds=list(strategy.stint_seconds),
        stint_drivers=list(strategy.stint_drivers), stops=list(strategy.stops),
        tyre_changes=list(strategy.tyre_changes), windows=list(strategy.windows),
        driver_seconds=list(strategy.driver_seconds), driver_issues=list(strategy.driver_issues),
    )


def plan(setup: StrategyInput) -> Strategy:
    """Pit stop plan with driver limits, mandatory stops & balanced stints, pit windows

    Same input, same plan: plans are cached (saving target, comparison & tyre plan rounds ask
    the same plans again), a copy is returned.
    """
    return copy_strategy(_plan(setup))


@lru_cache(maxsize=512)
def _plan(setup: StrategyInput) -> Strategy:
    strategy = plan_race(setup)
    if setup.minimum_stops > len(strategy.stops) and strategy.ready and strategy.race_laps > setup.minimum_stops:
        # Mandatory stops: race laps spread evenly over one stint more than stops
        strategy = plan_race(setup, setup.minimum_stops + 1)
        if strategy.ready:
            strategy.limit = "stops"
    elif setup.balanced_stints and strategy.ready and strategy.feasible and len(strategy.stints) > 1:
        # Same stops, laps spread evenly: no short splash stint at the end
        balanced = plan_race(setup, len(strategy.stints))
        if balanced.ready and balanced.feasible and len(balanced.stops) <= len(strategy.stops):
            balanced.limit = strategy.limit
            strategy = balanced
    strategy.windows = pit_windows(setup, strategy)
    return strategy


def stint_time_laps(setup: StrategyInput, fuel: float, seconds: float) -> int:
    """Laps driven in `seconds` from `fuel` in tank (heavier car slower), slowest driver, at
    least one lap"""
    per_lap = consumption(setup).get("fuel", 0.0)
    slowest = max(setup.driver_pace[:max(setup.drivers, 1)], default=0.0)
    total, laps = 0.0, 0
    while laps < 100000:
        lap_seconds = lap_time(setup, fuel if per_lap else setup.tank_capacity / 2, 0.0)
        if lap_seconds <= 0:
            return 100000
        lap_seconds = max(lap_seconds + setup.saving_seconds + max(slowest, 0.0), 1.0)
        if laps and total + lap_seconds > seconds + EPSILON:
            break
        total += lap_seconds
        laps += 1
        fuel -= per_lap
    return max(laps, 1)


def pit_windows(setup: StrategyInput, strategy: Strategy) -> list[tuple[int, int]]:
    """Earliest & latest lap of each stop keeping the same number of stops

    Latest: as late as fuel and stint time (real lap times, slowest driver) allow after the
    stops before at their latest. Earliest: as early as the stints after can still cover the
    race on full tanks. Each stint after keeps one lap at least (mandatory stops).
    """
    if not strategy.ready or not strategy.stops:
        return []
    usage = consumption(setup)
    reserve = reserves(setup, usage)
    full = max(full_tank_laps(setup), 1)
    stint_cap = setup.max_stint_minutes * 60
    if stint_cap > 0:  # heaviest car (full tank) is the slowest: fewest laps in the stint time
        full = min(full, stint_time_laps(setup, setup.tank_capacity, stint_cap))
    formation = whole_laps(setup.formation_laps) if not setup.lap_offset else 0
    partial = formation - setup.formation_laps if formation else 0.0  # fuel of formation lap not used
    start = {"fuel": strategy.fuel_load, "energy": strategy.energy_load}
    start = {name: amount + partial * usage.get(name, 0.0) for name, amount in start.items()}
    first_stint = max(stint_laps(start, usage, reserve), 1)
    if stint_cap > 0:
        first_stint = min(first_stint, stint_time_laps(
            setup, strategy.fuel_load or setup.tank_capacity, stint_cap - setup.stint_seconds_done))
    count = len(strategy.stops)
    end = strategy.last_lap
    lowest = strategy.first_lap + formation + 1  # no stop during formation laps
    windows = []
    earliest_before, latest_before = lowest - 1, strategy.first_lap
    for index, stop in enumerate(strategy.stops):
        stints_after = count - index  # stints after this stop
        latest = min((latest_before + full) if index else strategy.first_lap + first_stint, end - stints_after)
        earliest = max(end - stints_after * full, earliest_before + 1, lowest)
        earliest = min(earliest, stop.lap)
        latest = max(latest, stop.lap)
        if stop.reason:  # stop set by scenario (safety car, wet tyres, slicks): at its lap
            earliest = latest = stop.lap
        windows.append((earliest, latest))
        earliest_before, latest_before = earliest, latest
    return windows


def target_consumption(setup: StrategyInput, laps_per_stint: int) -> tuple[float, float]:
    """(fuel, energy) per lap allowing laps_per_stint laps on a full tank, safety margin kept"""
    if laps_per_stint <= 0:
        return 0.0, 0.0
    scale = 1 + max(setup.margin_percent, 0.0) / 100
    laps = laps_per_stint + setup.margin_laps
    fuel = max(setup.tank_capacity - setup.margin_fuel, 0.0) / laps / scale if setup.fuel_per_lap > 0 else 0.0
    if setup.energy_per_lap > 0:
        margin = setup.margin_fuel / setup.fuel_per_lap * setup.energy_per_lap if setup.fuel_per_lap > 0 else 0.0
        energy = max(100.0 - margin, 0.0) / laps / scale
    else:
        energy = 0.0
    return fuel, energy


def saving_input(setup: StrategyInput, laps_per_stint: int) -> StrategyInput:
    """Input with consumption saved for laps_per_stint laps on a full tank, lap time lost to
    saving (saving cost) added"""
    fuel, energy = target_consumption(setup, laps_per_stint)
    fuel = min(setup.fuel_per_lap, fuel) if setup.fuel_per_lap > 0 else 0.0
    energy = min(setup.energy_per_lap, energy) if setup.energy_per_lap > 0 else 0.0
    ratio = max(1 - fuel / setup.fuel_per_lap if setup.fuel_per_lap > 0 else 0.0,
                1 - energy / setup.energy_per_lap if setup.energy_per_lap > 0 else 0.0, 0.0)
    return replace(setup, fuel_per_lap=fuel, energy_per_lap=energy,
                   saving_seconds=setup.saving_seconds + max(setup.saving_cost, 0.0) * ratio * 10)


class SavingTarget(NamedTuple):
    """Saving for fewer stops: laps per stint on a full tank, consumption per lap, plan"""

    laps: int
    fuel: float
    energy: float
    strategy: Strategy


def target_for_stops(setup: StrategyInput, strategy: Strategy, stops: int) -> SavingTarget | None:
    """Least saving for a plan of at most `stops` stops, None if not possible

    Fewest laps per stint (on a full tank), searched by halving (stops never grow as stints get
    longer). Saving cannot go past driver limits & mandatory stops.
    """
    if not strategy.ready or not strategy.feasible or stops < max(setup.minimum_stops, 0) or len(strategy.stops) <= stops:
        return None

    def attempt(laps_per_stint: int) -> SavingTarget | None:
        target = saving_input(setup, laps_per_stint)
        saving = plan(target)
        if saving.ready and saving.feasible and len(saving.stops) <= stops:
            return SavingTarget(laps_per_stint, target.fuel_per_lap, target.energy_per_lap, saving)
        return None

    low = full_tank_laps(setup) + 1  # fewer laps: no saving
    high = max(strategy.race_laps * 2, low)  # time race: fewer stops, more laps
    found = attempt(high)  # most saving: one tank for everything
    if found is None:
        return None
    high -= 1
    while low <= high:
        middle = (low + high) // 2
        result = attempt(middle)
        if result is None:
            low = middle + 1
        else:
            found, high = result, middle - 1
    return found


def saving_target(setup: StrategyInput, strategy: Strategy) -> SavingTarget | None:
    """Saving for one stop less, None if not possible"""
    stops = len(strategy.stops)
    if not strategy.ready or stops < 1 or stops <= setup.minimum_stops:
        return None
    return target_for_stops(setup, strategy, stops - 1)


class Variant(NamedTuple):
    """Strategy compared: stops, consumption per lap, plan, lap time lost to saving"""

    stops: int
    fuel: float
    energy: float
    strategy: Strategy
    lap_cost: float
    current: bool


def race_result(strategy: Strategy) -> tuple[int, float]:
    """Sort key of a plan, best first: most laps (time race), then least race time"""
    return -strategy.race_laps, strategy.race_seconds


def compare_strategies(setup: StrategyInput, strategy: Strategy, fewer: int = 2) -> list[Variant]:
    """Plan of now, plans with up to `fewer` stops less (fuel saving) & one stop more (lighter
    car, no saving), by stops"""
    if not strategy.ready or not strategy.feasible:
        return []
    count = len(strategy.stops)
    variants = {count: Variant(count, setup.fuel_per_lap, setup.energy_per_lap, strategy, 0.0, True)}
    for stops in range(count - 1, max(count - fewer, setup.minimum_stops, 0) - 1, -1):
        target = target_for_stops(setup, strategy, stops)
        if target is not None and len(target.strategy.stops) not in variants:
            variants[len(target.strategy.stops)] = Variant(
                len(target.strategy.stops), target.fuel, target.energy, target.strategy,
                target.strategy.saving_seconds - setup.saving_seconds, False)
    more = plan(replace(setup, minimum_stops=count + 1))
    if more.ready and more.feasible and len(more.stops) == count + 1:
        variants[count + 1] = Variant(count + 1, setup.fuel_per_lap, setup.energy_per_lap, more, 0.0, False)
    return [variants[stops] for stops in sorted(variants)]


def target_to_stop(setup: StrategyInput, amount: float, laps: float, name: str = "fuel") -> float:
    """Consumption per lap (fuel or energy) to cover `laps` with `amount` in tank, safety margin
    kept, 0 when not used"""
    usage = consumption(setup)
    if name not in usage or laps <= 0:
        return 0.0
    scale = 1 + max(setup.margin_percent, 0.0) / 100
    return max(amount - reserves(setup, usage)[name], 0.0) / laps / scale


class RaceState(NamedTuple):
    """Race under way (live): laps & time done, amounts of now (fuel in display unit)"""

    laps_done: int  # race laps completed (formation laps not included)
    lap_progress: float  # fraction of lap in progress driven
    elapsed: float  # race clock (seconds from green flag)
    seconds_left: float  # time race: race time left
    fuel: float
    energy: float  # %
    tread: float  # % (average of 4 tyres), 0 = unknown
    stops_done: int


def remaining_input(setup: StrategyInput, base: Strategy, state: RaceState) -> StrategyInput:
    """Input of the rest of a race under way, from start of lap in progress

    Laps, stops & driving time of the drivers done are taken from the race state and the plan
    made before the race (base): driver in the car, its stints & stint time.
    """
    done = whole_laps(setup.formation_laps) + max(state.laps_done, 0)
    progress = min(max(state.lap_progress, 0.0), 0.99)
    fuel = state.fuel + progress * setup.fuel_per_lap
    energy = state.energy + progress * setup.energy_per_lap
    stint_index = min(max(state.stops_done, 0), max(len(base.stints) - 1, 0))
    driver = base.driver_of(stint_index) if base.stints else 1
    turn = 0
    for index in range(stint_index - 1, -1, -1):  # stints of this driver before, same turn
        if base.driver_of(index) != driver:
            break
        turn += 1
    drivers = max(setup.drivers, 1)
    seconds_done = [0.0] * drivers
    stint_start = base.stops[stint_index - 1].lap if 0 < stint_index <= len(base.stops) else base.first_lap
    for index, seconds in enumerate(base.stint_seconds[:stint_index]):
        seconds_done[min(base.driver_of(index), drivers) - 1] += seconds
    in_stint = max(done - stint_start, 0) * setup.laptime
    seconds_done[min(driver, drivers) - 1] += in_stint
    if setup.race_minutes > 0:
        seconds_left = max(state.seconds_left, 0.0) + progress * setup.laptime
        race_minutes, race_laps = seconds_left / 60, 0
    else:
        race_minutes, race_laps = 0.0, max(setup.race_laps - max(state.laps_done, 0), 0)
    return replace(
        setup,
        race_minutes=race_minutes,
        race_laps=race_laps,
        formation_laps=0.0,
        fuel_start=min(max(fuel, 1e-6), setup.tank_capacity) if setup.tank_capacity > 0 else 0.0,
        energy_start=min(max(energy, 1e-6), 100.0),
        tread_start=state.tread if state.tread > 0 else setup.tread_start,
        minimum_stops=max(setup.minimum_stops - state.stops_done, 0),
        stop_extra_seconds=setup.stop_extra_seconds[state.stops_done:],
        lap_offset=done,
        clock_offset=max(state.elapsed - progress * setup.laptime, 0.0),
        stops_done=state.stops_done,
        driver_start=driver,
        driver_stints_done=turn,
        stint_seconds_done=in_stint,
        driver_seconds_done=tuple(seconds_done),
    )


def history_laps(dataset) -> list[ConsumptionDataSet]:
    """Recorded laps, placeholder entry (nothing driven yet, invalid file) left out"""
    return [lap for lap in dataset
            if lap.lapTimeLast > 0 or lap.lastLapUsedFuel > 0 or lap.lastLapUsedEnergy > 0]


def representative_laps(dataset, count: int = 5, tolerance: float = 1.05) -> list[ConsumptionDataSet]:
    """Latest valid laps at race pace: in & out laps, incidents (slower than median by tolerance) left out"""
    valid = [lap for lap in history_laps(dataset)
             if lap.isValidLap and lap.lapTimeLast > 0 and (lap.lastLapUsedFuel > 0 or lap.lastLapUsedEnergy > 0)
             ][:count * 3]
    if not valid:
        return []
    pace = median(lap.lapTimeLast for lap in valid)
    return [lap for lap in valid if lap.lapTimeLast <= pace * tolerance][:count]


class PaceEstimate(NamedTuple):
    """Estimates from consumption history, 0 laps (or stops) used: not enough data"""

    pit_seconds: float  # time lost per stop (in & out laps against race pace)
    pit_stops: int
    fuel_effect: float  # seconds per lap per 10 fuel units (fuel & tyre trend over a stint together)
    fuel_laps: int
    track_evolution: float  # seconds per lap per hour
    track_laps: int


def estimate_pace(dataset, fuel_unit: Callable[[float], float] = float, tolerance: float = 1.05) -> PaceEstimate:
    """Pit time lost, fuel effect & track evolution from laps of a consumption history

    Stops: two slow laps in a row (in & out laps), time lost against race pace. Stints: runs of
    race pace laps between stops. Lap time is fitted to fuel burned since stint start (fuel
    effect, tyre wear trend included) and race time (track evolution, needs 2 stints or more).
    """
    laps = [lap for lap in history_laps(dataset) if lap.lapTimeLast > 0]
    laps.reverse()  # oldest first
    valid = [lap.lapTimeLast for lap in laps if lap.isValidLap]
    if len(valid) < 4:
        return PaceEstimate(0.0, 0, 0.0, 0, 0.0, 0)
    pace = median(valid)
    slow = [lap.lapTimeLast > pace * tolerance for lap in laps]
    losses = []
    for index in range(len(laps) - 1):
        if (slow[index] and slow[index + 1] and (index == 0 or not slow[index - 1])
                and laps[index + 1].lapNumber == laps[index].lapNumber + 1):
            loss = laps[index].lapTimeLast + laps[index + 1].lapTimeLast - 2 * pace
            if 5 <= loss <= 600:
                losses.append(loss)
    # Stints: new one after a stop (out lap: second slow lap in a row) or a break in lap numbers
    points: list[tuple[int, float, float, float]] = []  # stint, fuel burned, hours, lap time
    stint = 0
    burned = hours = 0.0
    for index, lap in enumerate(laps):
        if index and (lap.lapNumber != laps[index - 1].lapNumber + 1 or (slow[index] and slow[index - 1])):
            stint += 1
            burned = 0.0
        if not slow[index] and lap.isValidLap:
            points.append((stint, burned, hours, lap.lapTimeLast))
        burned += fuel_unit(lap.lastLapUsedFuel)
        hours += lap.lapTimeLast / 3600
    fuel_effect, fuel_laps, track, track_laps = _fit_pace(points)
    return PaceEstimate(median(losses) if losses else 0.0, len(losses), fuel_effect, fuel_laps, track, track_laps)


def _fit_pace(points: list[tuple[int, float, float, float]]) -> tuple[float, int, float, int]:
    """Least squares: lap time = a + b x fuel burned (+ c x hours with 2 stints or more)"""
    counts: dict[int, int] = {}
    for stint, *_ in points:
        counts[stint] = counts.get(stint, 0) + 1
    points = [point for point in points if counts[point[0]] >= 3]
    if len(points) < 3:
        return 0.0, 0, 0.0, 0
    stints = {point[0] for point in points}
    count = len(points)
    mean_x = sum(point[1] for point in points) / count
    mean_z = sum(point[2] for point in points) / count
    mean_y = sum(point[3] for point in points) / count
    sxx = sum((point[1] - mean_x) ** 2 for point in points)
    szz = sum((point[2] - mean_z) ** 2 for point in points)
    sxz = sum((point[1] - mean_x) * (point[2] - mean_z) for point in points)
    sxy = sum((point[1] - mean_x) * (point[3] - mean_y) for point in points)
    szy = sum((point[2] - mean_z) * (point[3] - mean_y) for point in points)
    if sxx <= EPSILON:
        return 0.0, 0, 0.0, 0
    determinant = sxx * szz - sxz * sxz
    if len(stints) >= 2 and szz > EPSILON and determinant > EPSILON * max(sxx * szz, 1.0):
        slope_x = (sxy * szz - szy * sxz) / determinant
        slope_z = (szy * sxx - sxy * sxz) / determinant
        track, track_laps = min(max(slope_z, -9.0), 9.0), count
    else:
        slope_x = sxy / sxx
        track, track_laps = 0.0, 0
    # Lap time falls as fuel burns: effect per 10 units in tank is minus the slope
    fuel_effect = min(max(-slope_x * 10, 0.0), 9.0)
    return fuel_effect, count, track, track_laps


MAX_DRIVERS = 9


def parse_driver_table(text: str) -> list[tuple[float, float, float]]:
    """Driver table saved as text "pace:min:max,..." (seconds, minutes), wrong values 0"""
    rows = []
    for row in str(text).split(",")[:MAX_DRIVERS]:
        values = []
        for item in [*row.split(":"), "0", "0", "0"][:3]:
            try:
                value = float(item)
            except ValueError:
                value = 0.0
            values.append(value if isfinite(value) else 0.0)
        rows.append((values[0], values[1], values[2]))
    return rows if any(any(row) for row in rows) else []


def driver_table_text(rows) -> str:
    """Driver table as text (rows of nothing set at the end left out), empty when nothing set"""
    rows = list(rows)
    while rows and not any(rows[-1]):
        rows.pop()
    return ",".join(f"{pace:g}:{minimum:g}:{maximum:g}" for pace, minimum, maximum in rows)


def driver_fields(setup: StrategyInput, rows) -> StrategyInput:
    """Input with driver table (pace, min, max of each driver), for drivers taking turns"""
    rows = list(rows)[:setup.drivers] if setup.drivers > 1 else []
    return replace(
        setup,
        driver_pace=tuple(row[0] for row in rows),
        driver_min_minutes=tuple(row[1] for row in rows),
        driver_max_minutes=tuple(row[2] for row in rows),
    )


def margin_values(setup: StrategyInput, unit: int, value: float) -> StrategyInput:
    """Input with safety margin (unit: index of MARGIN_UNITS)"""
    kind = MARGIN_UNITS[unit] if 0 <= unit < len(MARGIN_UNITS) else MARGIN_UNITS[0]
    return replace(
        setup,
        margin_laps=value if kind == "laps" else 0.0,
        margin_fuel=value if kind == "fuel" else 0.0,
        margin_percent=value if kind == "percent" else 0.0,
    )


def strategy_input_from_values(values: dict, stop_extra_seconds: tuple[float, ...] = (),
                               tyre_change_seconds: float = 0.0) -> StrategyInput:
    """Strategy input from race calculator inputs (config "fuel_calculator" or race plan file),
    as the race calculator builds it (race plan widget plans with calculator closed)"""
    def number(key: str) -> float:  # wrong type & nan / infinity (hand edited file): 0
        value = values.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            return 0.0
        return float(value)

    def percent(key: str, default: float) -> float:
        return number(key) / 100 if key in values else default

    lap_race = values.get("enable_lap_race") is True
    safety_car = values.get("enable_safety_car") is True
    rain = values.get("enable_rain") is True
    drivers = max(int(number("input_drivers")), 1)
    table = values.get("input_driver_table", "")
    setup = StrategyInput(
        laptime=number("input_lap_time"),
        race_minutes=0.0 if lap_race else number("input_race_minutes"),
        race_laps=int(number("input_race_laps")) if lap_race else 0,
        formation_laps=number("input_formation_laps"),
        pit_seconds=number("input_pit_seconds"),
        tank_capacity=number("input_tank_capacity"),
        fuel_per_lap=number("input_fuel_per_lap"),
        energy_per_lap=number("input_energy_per_lap"),
        fuel_start=number("input_fuel_start"),
        energy_start=number("input_energy_start"),
        tread_start=number("input_tread_start") or FRESH_TREAD,
        wear_per_lap=number("input_wear_per_lap"),
        minimum_tread=number("input_minimum_tread"),
        stop_extra_seconds=stop_extra_seconds,
        tyre_change_seconds=tyre_change_seconds,
        refuel_rate=number("input_refuel_rate"),
        energy_rate=number("input_energy_rate"),
        tyres_during_refuel=values.get("enable_tyres_during_refuel") is True,
        minimum_stops=int(number("input_minimum_stops")),
        balanced_stints=values.get("enable_balanced_stints") is True,
        max_stint_minutes=number("input_max_stint_minutes"),
        drivers=drivers,
        driver_change_seconds=number("input_driver_change_seconds"),
        stints_per_driver=max(int(number("input_stints_per_driver")), 1),
        fuel_effect=number("input_fuel_effect"),
        track_evolution=number("input_track_evolution"),
        saving_cost=number("input_saving_cost"),
        sc_lap=int(number("input_sc_lap")) if safety_car else 0,
        sc_laps=int(number("input_sc_laps")) if safety_car else 0,
        sc_consumption=percent("input_sc_consumption", 0.5),
        sc_laptime=percent("input_sc_laptime", 1.5),
        sc_pit=safety_car and values.get("enable_sc_pit") is True,
        sc_pit_saving=percent("input_sc_pit_saving", 0.5),
        sc_wear=percent("input_sc_wear", 1.0),
        rain_lap=int(number("input_rain_lap")) if rain else 0,
        rain_laps=int(number("input_rain_laps")) if rain else 0,
        rain_consumption=percent("input_rain_consumption", 1.0),
        rain_laptime=percent("input_rain_laptime", 1.1),
        rain_tyres=rain and values.get("enable_rain_tyres") is True,
        pit_lap_consumption=percent("input_pit_lap_consumption", 1.0),
        extra_laps=1 if not lap_race and values.get("enable_leader_finish") is True else 0,
    )
    setup = margin_values(setup, int(number("input_safety_margin_kind")), number("input_safety_margin"))
    return driver_fields(setup, parse_driver_table(table if isinstance(table, str) else ""))
