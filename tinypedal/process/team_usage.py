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
Team usage: fuel, virtual energy & tyre wear per lap of each stint of the team car

From LMU strategy data (Rest API /rest/strategy/usage), which keeps the laps of every driver
of the car (teammates included): {driver name: [{"lap", "stint", "fuel", "ve", "tyres", "pit"}]},
fuel & ve remaining as fraction of full, tyres remaining tread (percent) of each wheel.

Also tyre allocation of the garage tyre screen (/rest/garage/UIScreen/TireManagement) & tank capacity
of the garage repair & refuel screen (/rest/garage/UIScreen/RepairAndRefuel).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from itertools import pairwise
from typing import Any, NamedTuple


class UsageLap(NamedTuple):
    """Team car at end of a lap"""

    driver: str
    stint: int
    lap: int
    fuel: float  # remaining fuel (fraction of tank)
    energy: float  # remaining virtual energy (fraction)
    tread: float  # remaining tread, average of the tyres (percent)
    pit: bool


class StintUsage(NamedTuple):
    """Usage per lap of a stint (or of several stints combined)"""

    driver: str
    stint: int
    first_lap: int
    last_lap: int
    laps: int  # laps measured
    fuel: float  # fuel per lap (fraction of tank)
    energy: float  # virtual energy per lap (fraction)
    wear: float  # tyre wear per lap (percent)


class TyreAllocation(NamedTuple):
    """Tyres of the session"""

    maximum: int  # tyres available
    new_left: int  # new tyres not used yet


def parse_usage(data: Any) -> list[UsageLap]:
    """Laps of every driver in lap order, entries not understood left out"""
    laps: list[UsageLap] = []
    if not isinstance(data, dict):
        return laps
    for driver, entries in data.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            try:
                tyres = [float(tread) for tread in entry.get("tyres") or ()]
                laps.append(UsageLap(
                    driver=str(driver),
                    stint=int(entry["stint"]),
                    lap=int(entry["lap"]),
                    fuel=float(entry.get("fuel") or 0.0),
                    energy=float(entry.get("ve") or 0.0),
                    tread=sum(tyres) / len(tyres) if tyres else 0.0,
                    pit=bool(entry.get("pit")),
                ))
            except (AttributeError, KeyError, TypeError, ValueError):
                continue
    laps.sort(key=lambda usage: usage.lap)
    return laps


def lap_measured(last: UsageLap, lap: UsageLap) -> bool:
    """Usage of lap measured from end of last lap: next lap of same stint, not from the start
    (lap 0: standing start or garage exit), no pit stop on either lap, nothing refilled"""
    return (
        lap.lap == last.lap + 1
        and last.lap > 0
        and lap.stint == last.stint
        and lap.driver == last.driver
        and not (last.pit or lap.pit)
        and lap.fuel <= last.fuel
        and lap.energy <= last.energy
        and lap.tread <= last.tread
    )


def stint_usage(laps: Sequence[UsageLap]) -> list[StintUsage]:
    """Usage per lap of each stint, stints in order they were driven"""
    stints: dict[tuple[str, int], list[UsageLap]] = {}
    for lap in laps:
        stints.setdefault((lap.driver, lap.stint), []).append(lap)
    result = []
    for (driver, stint), stint_laps in stints.items():
        measured = [(last, lap) for last, lap in pairwise(stint_laps) if lap_measured(last, lap)]
        count = len(measured)
        result.append(StintUsage(
            driver=driver,
            stint=stint,
            first_lap=stint_laps[0].lap,
            last_lap=stint_laps[-1].lap,
            laps=count,
            fuel=sum(last.fuel - lap.fuel for last, lap in measured) / count if count else 0.0,
            energy=sum(last.energy - lap.energy for last, lap in measured) / count if count else 0.0,
            wear=sum(last.tread - lap.tread for last, lap in measured) / count if count else 0.0,
        ))
    result.sort(key=lambda usage: usage.first_lap)
    return result


def combine_usage(stints: Iterable[StintUsage], driver: str = "") -> StintUsage:
    """Stints combined, weighted by laps measured (stint 0: several stints)"""
    stints = [usage for usage in stints if usage.laps > 0]
    count = sum(usage.laps for usage in stints)
    if not count:
        return StintUsage(driver, 0, 0, 0, 0, 0.0, 0.0, 0.0)
    return StintUsage(
        driver=driver,
        stint=stints[0].stint if len(stints) == 1 else 0,
        first_lap=min(usage.first_lap for usage in stints),
        last_lap=max(usage.last_lap for usage in stints),
        laps=count,
        fuel=sum(usage.fuel * usage.laps for usage in stints) / count,
        energy=sum(usage.energy * usage.laps for usage in stints) / count,
        wear=sum(usage.wear * usage.laps for usage in stints) / count,
    )


def driver_usage(stints: Sequence[StintUsage]) -> list[StintUsage]:
    """Usage per lap of each driver, drivers in order they first drove"""
    drivers = dict.fromkeys(usage.driver for usage in stints)
    return [combine_usage((usage for usage in stints if usage.driver == driver), driver) for driver in drivers]


def tyre_allocation(data: Any) -> TyreAllocation | None:
    """Tyre allocation of garage tyre screen, None if not given"""
    try:
        maximum = int(data["tireInventory"]["maxAvailableTires"])
        new_left = int(data["tireInvGarageOptions"]["newTiresRemaining"])
    except (KeyError, TypeError, ValueError):
        return None
    if maximum <= 0:
        return None
    return TyreAllocation(maximum, min(max(new_left, 0), maximum))


def tank_capacity(data: Any) -> float:
    """Fuel tank capacity (liters) of garage repair & refuel screen, 0 if not given"""
    try:
        return max(float(data["fuelInfo"]["maxFuel"]), 0.0)
    except (KeyError, TypeError, ValueError):
        return 0.0
