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
the safety margin, or until the stint length limit (driver limit, mandatory stops), then the
car pits and takes only what it needs: a full tank while more stints follow, a splash for the
last one. Fuel and energy share the same stops.

Each stop costs the pit lane time, plus refuelling (amount / refuel rate), tyre change and
driver change; tyres can be changed while refuelling (longest of both counts). Lap time follows
fuel in tank (heavier car is slower) and track evolution. A time race lasts the laps that fit
in race time with these lap & stop times: race length and stops are settled together.

Tyres are changed at a stop when the next stint would wear them below the minimum tread.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import ceil, floor
from statistics import median

from .module_info import ConsumptionDataSet

MAX_STOPS = 200  # simulation guard: tank too small for the race
MAX_ROUNDS = 20  # time race: race length & stops settling rounds
FRESH_TREAD = 100.0  # tread of new tyres (%)
EPSILON = 1e-9


@dataclass(frozen=True)
class StrategyInput:
    """Race setup, consumption & tyres (fuel in display unit, energy & tread in %)"""

    laptime: float = 0.0  # seconds, at half tank on a fresh track
    race_minutes: float = 0.0  # time race, 0 for lap race
    race_laps: int = 0  # lap race
    formation_laps: float = 0.0  # driven before race clock starts
    pit_seconds: float = 0.0  # time lost per stop in pit lane (service time added)
    tank_capacity: float = 0.0
    fuel_per_lap: float = 0.0
    energy_per_lap: float = 0.0  # 0 if car has no virtual energy
    fuel_start: float = 0.0  # 0 = full tank
    energy_start: float = 0.0  # 0 = full (100%)
    margin_laps: float = 0.0  # safety margin kept in tank at every stop & at finish
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
    max_stint_minutes: float = 0.0  # driver limit, 0 = none
    drivers: int = 1  # drivers take turns, one change per stop
    driver_change_seconds: float = 0.0
    fuel_effect: float = 0.0  # seconds per lap per 10 fuel units in tank (from half tank)
    track_evolution: float = 0.0  # seconds per lap per hour of race (negative = faster)


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


@dataclass
class Strategy:
    """Pit stop plan"""

    race_laps: int = 0  # whole laps incl. formation laps
    stints: list[int] = field(default_factory=list)  # laps of each stint
    stint_seconds: list[float] = field(default_factory=list)  # driving time of each stint
    stops: list[PitStop] = field(default_factory=list)
    fuel_needed: float = 0.0  # whole race incl. margin
    energy_needed: float = 0.0
    fuel_load: float = 0.0  # fuel to load at start (start fuel, or exact amount without stop)
    energy_load: float = 0.0
    limit: str = "fuel"  # what ends stints: "fuel", "energy" or "stint" (length limit)
    feasible: bool = True  # False: tank cannot cover one lap plus margin
    tyre_changes: list[int] = field(default_factory=list)  # tyres changed per stop (tyre plan), empty: proposed
    fitting_laps: int = 0  # time race: laps that fit in race time with these lap & stop times
    race_seconds: float = 0.0  # race clock at finish (laps, stops)

    @property
    def ready(self) -> bool:
        """Plan to show: race set up and stints planned"""
        return self.race_laps > 0 and bool(self.stints)

    @property
    def impossible(self) -> bool:
        """Race set up, but tank cannot cover one lap plus margin"""
        return self.race_laps > 0 and not self.feasible

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

    def driver_of(self, stint_index: int) -> int:
        return self.stops[stint_index - 1].driver if 0 < stint_index <= len(self.stops) else 1


def race_laps_for(setup: StrategyInput, stops: int) -> int:
    """Whole race laps incl. formation, time race shortened by pit time of stops (constant lap time)"""
    formation = ceil(setup.formation_laps - EPSILON) if setup.formation_laps > 0 else 0
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


def stint_laps(amounts: dict[str, float], usage: dict[str, float], reserve: dict[str, float]) -> int:
    """Whole laps until any resource cannot cover one more lap plus its reserve"""
    laps = None
    for name, per_lap in usage.items():
        if per_lap <= 0:
            continue
        fit = floor((amounts[name] - reserve[name]) / per_lap + EPSILON)
        laps = fit if laps is None else min(laps, fit)
    return max(laps, 0) if laps is not None else 0


def stop_time(setup: StrategyInput, index: int, fuel: float, energy: float, tyres: bool) -> tuple[float, float, float]:
    """(whole stop, refuelling, tyre change) seconds of stop index"""
    refuel = max(fuel / setup.refuel_rate if setup.refuel_rate > 0 else 0.0,
                 energy / setup.energy_rate if setup.energy_rate > 0 else 0.0)
    if setup.stop_extra_seconds:
        tyre = setup.stop_extra_seconds[index] if index < len(setup.stop_extra_seconds) else 0.0
    else:
        tyre = setup.tyre_change_seconds if tyres else 0.0
    service = max(refuel, tyre) if setup.tyres_during_refuel else refuel + tyre
    driver = setup.driver_change_seconds if setup.drivers > 1 else 0.0
    return setup.pit_seconds + service + driver, refuel, tyre


def simulate(setup: StrategyInput, race_laps: int, stint_cap: int = 0) -> Strategy:
    """Pit stop plan for a race length, stints at most stint_cap laps (0 = no limit)"""
    usage = {
        name: per_lap for name, per_lap, capacity in (
            ("fuel", setup.fuel_per_lap, setup.tank_capacity), ("energy", setup.energy_per_lap, 100.0))
        if per_lap > 0 and capacity > 0
    }
    capacity = {"fuel": setup.tank_capacity, "energy": 100.0}
    reserve = {name: setup.margin_laps * usage.get(name, 0.0) for name in capacity}
    amounts = {
        "fuel": setup.fuel_start if setup.fuel_start > 0 else setup.tank_capacity,
        "energy": setup.energy_start if setup.energy_start > 0 else 100.0,
    }
    needed = {name: race_laps * usage.get(name, 0.0) + reserve[name] for name in capacity}
    strategy = Strategy(race_laps=race_laps, fuel_needed=needed["fuel"], energy_needed=needed["energy"])
    if race_laps <= 0 or not usage:
        return strategy
    # Limit: resource giving fewer laps on a full refill, or stint length limit
    full = {name: (capacity[name] - reserve[name]) / per_lap for name, per_lap in usage.items()}
    strategy.limit = min(full, key=lambda name: full[name])
    if stint_cap and stint_cap < min(full.values()):
        strategy.limit = "stint"
    no_stop = all(needed[name] <= capacity[name] + EPSILON for name in usage)
    if no_stop and setup.fuel_start <= 0 and setup.energy_start <= 0 and not stint_cap:
        amounts = {name: min(needed[name], capacity[name]) for name in amounts}  # exact load
    strategy.fuel_load = amounts["fuel"] if "fuel" in usage else 0.0
    strategy.energy_load = amounts["energy"] if "energy" in usage else 0.0

    formation = ceil(setup.formation_laps - EPSILON) if setup.formation_laps > 0 else 0
    time_limit = setup.race_minutes * 60
    clock = 0.0  # race clock, starts after formation laps
    tread = setup.tread_start
    driver = 1
    lap = 0
    while lap < race_laps:
        stint = min(stint_laps(amounts, usage, reserve), race_laps - lap)
        if stint_cap:
            stint = min(stint, stint_cap)
        if stint <= 0 and strategy.stops and strategy.stops[-1].lap == lap:
            strategy.feasible = False  # refilled and still not one lap
            break
        if stint > 0:
            seconds = 0.0
            for _ in range(stint):
                seconds_lap = lap_time(setup, amounts["fuel"], clock)
                seconds += seconds_lap
                lap += 1
                if lap > formation:
                    clock += seconds_lap
                    if time_limit and not strategy.fitting_laps and clock >= time_limit - EPSILON:
                        strategy.fitting_laps = lap  # timer ends during this lap: last lap
                for name, per_lap in usage.items():
                    amounts[name] -= per_lap
            strategy.stints.append(stint)
            strategy.stint_seconds.append(seconds)
            tread -= stint * setup.wear_per_lap
            if lap >= race_laps:
                break
        if len(strategy.stops) >= MAX_STOPS:
            strategy.feasible = False
            break
        # Pit: take what is needed to finish, at most a full tank
        laps_left = race_laps - lap
        added = {"fuel": 0.0, "energy": 0.0}
        for name, per_lap in usage.items():
            want = laps_left * per_lap + reserve[name] - amounts[name]
            added[name] = min(max(want, 0.0), capacity[name] - amounts[name])
            amounts[name] += added[name]
        next_stint = min(stint_laps(amounts, usage, reserve), laps_left)
        tyres = setup.wear_per_lap > 0 and tread - next_stint * setup.wear_per_lap < setup.minimum_tread
        if tyres:
            tread = setup.fresh_tread
        if setup.drivers > 1:
            driver = driver % setup.drivers + 1
        seconds_stop, refuel, tyre = stop_time(setup, len(strategy.stops), added["fuel"], added["energy"], tyres)
        clock += seconds_stop
        strategy.stops.append(PitStop(
            lap, added["fuel"], added["energy"], tyres, seconds_stop, refuel, tyre, driver))
    strategy.race_seconds = clock
    if time_limit and not strategy.fitting_laps and strategy.feasible:
        # Race time left after planned laps: more laps at last lap time
        last = lap_time(setup, amounts.get("fuel", 0.0), clock) or 1.0
        strategy.fitting_laps = lap + max(ceil((time_limit - clock) / last - EPSILON), 0)
    return strategy


def stint_limit(setup: StrategyInput) -> int:
    """Stint length limit in laps from driver limit (0 = none)"""
    if setup.max_stint_minutes > 0 and setup.laptime > 0:
        return max(floor(setup.max_stint_minutes * 60 / setup.laptime + EPSILON), 1)
    return 0


def plan_race(setup: StrategyInput, stint_cap: int) -> Strategy:
    """Pit stop plan, race length and stops agreeing (time race: pit time costs laps)

    More stops shorten a time race, which may need fewer stops. On a back and forth, the longer
    race is kept (its stops cover the shorter one too), so fuel is never short.
    """
    laps = race_laps_for(setup, 0)
    if setup.race_minutes <= 0:
        return simulate(setup, laps, stint_cap)
    seen: dict[int, Strategy] = {}
    for _ in range(MAX_ROUNDS):
        strategy = simulate(setup, laps, stint_cap)
        seen[laps] = strategy
        if not strategy.feasible or not strategy.stints:
            return strategy
        if strategy.fitting_laps == laps or strategy.fitting_laps in seen:
            break
        laps = strategy.fitting_laps
    agreeing = [strategy for count, strategy in seen.items() if strategy.fitting_laps == count]
    return max(agreeing or seen.values(), key=lambda strategy: strategy.race_laps)


def plan(setup: StrategyInput) -> Strategy:
    """Pit stop plan with stint length limit (driver limit) and mandatory stops"""
    cap = stint_limit(setup)
    strategy = plan_race(setup, cap)
    if setup.minimum_stops > len(strategy.stops) and strategy.ready and strategy.race_laps > setup.minimum_stops:
        # Mandatory stops: stints shortened evenly until enough stops
        even = ceil(strategy.race_laps / (setup.minimum_stops + 1))
        strategy = plan_race(setup, min(cap, even) if cap else even)
    return strategy


def target_consumption(setup: StrategyInput, laps_per_stint: int) -> tuple[float, float]:
    """(fuel, energy) per lap allowing laps_per_stint laps on a full tank, safety margin kept"""
    if laps_per_stint <= 0:
        return 0.0, 0.0
    laps = laps_per_stint + setup.margin_laps
    fuel = setup.tank_capacity / laps if setup.fuel_per_lap > 0 else 0.0
    energy = 100.0 / laps if setup.energy_per_lap > 0 else 0.0
    return fuel, energy


def saving_target(setup: StrategyInput, strategy: Strategy) -> tuple[int, float, float, Strategy] | None:
    """Saving for one stop less: (laps per stint, fuel, energy per lap, plan), None if not possible"""
    stops = len(strategy.stops)
    if not strategy.ready or stops < 1 or stops <= setup.minimum_stops:
        return None
    laps = strategy.race_laps
    for laps_per_stint in range(strategy.max_stint + 1, laps + 1):
        fuel, energy = target_consumption(setup, laps_per_stint)
        target = replace(
            setup,
            fuel_per_lap=min(setup.fuel_per_lap, fuel) if setup.fuel_per_lap > 0 else 0.0,
            energy_per_lap=min(setup.energy_per_lap, energy) if setup.energy_per_lap > 0 else 0.0,
        )
        saving = plan(target)
        if saving.ready and len(saving.stops) < stops:
            return laps_per_stint, target.fuel_per_lap, target.energy_per_lap, saving
    return None


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


def strategy_input_from_values(values: dict, stop_extra_seconds: tuple[float, ...] = (),
                               tyre_change_seconds: float = 0.0) -> StrategyInput:
    """Strategy input from race calculator inputs (config "fuel_calculator" or race plan file),
    as the race calculator builds it (race plan widget plans with calculator closed)"""
    def number(key: str) -> float:
        value = values.get(key, 0)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0

    lap_race = values.get("enable_lap_race") is True
    return StrategyInput(
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
        margin_laps=number("input_safety_margin"),
        tread_start=number("input_tread_start") or FRESH_TREAD,
        wear_per_lap=number("input_wear_per_lap"),
        minimum_tread=number("input_minimum_tread"),
        stop_extra_seconds=stop_extra_seconds,
        tyre_change_seconds=tyre_change_seconds,
        refuel_rate=number("input_refuel_rate"),
        energy_rate=number("input_energy_rate"),
        tyres_during_refuel=values.get("enable_tyres_during_refuel") is True,
        minimum_stops=int(number("input_minimum_stops")),
        max_stint_minutes=number("input_max_stint_minutes"),
        drivers=max(int(number("input_drivers")), 1),
        driver_change_seconds=number("input_driver_change_seconds"),
        fuel_effect=number("input_fuel_effect"),
        track_evolution=number("input_track_evolution"),
    )
