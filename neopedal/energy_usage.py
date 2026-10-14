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
Virtual energy used per lap by every driver (Le Mans Ultimate), from the game Rest API

GET /rest/strategy/usage: {"<driver name>": [{"lap", "pit", "stint", "ve", "fuel"?, "tyres"?}, ...]}, one
entry per lap with virtual energy left at its end ("ve", fraction; 0 for cars without virtual energy),
fuel & tyres for player only. As the game standings panel does: energy used in a lap = energy left at end
of lap before - at end of lap, laps with a pit stop left out (refill), read every 10 seconds.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, NamedTuple

from .game_rest_poll import RoutePoller

ROUTE = "/rest/strategy/usage"
CHECK_SECONDS = 10.0
# Body bytes read per second at most: body grows to ~1.3 MB in a 24 hours race (~17 ms to parse),
# read every 26 seconds then (data changes once per lap)
CHECK_BYTES_PER_SECOND = 50_000
AVERAGE_LAPS = 5


class LapUsage(NamedTuple):
    """Energy used (fraction of full): last lap, average of last laps (up to AVERAGE_LAPS), -1 if none"""

    last: float
    average: float


def lap_usages(laps: list, count: int = 0) -> list[float]:
    """Energy used in each lap (last count laps used, all if 0), oldest first: laps with a pit stop or refill
    (energy not lower) left out; laps walked from the last one"""
    used: list[float] = []
    later = None  # energy left at end of next lap, None if unknown (or pit stop in it)
    for lap in reversed(laps):
        if not isinstance(lap, dict):
            continue
        energy = lap.get("ve")
        if not isinstance(energy, (int, float)) or isinstance(energy, bool):
            later = None
            continue
        if later is not None and later < energy:
            used.append(energy - later)
            if len(used) == count:
                break
        later = None if lap.get("pit") else energy
    used.reverse()
    return used


@lru_cache(maxsize=512)
def driver_key(name: str) -> str:
    """Driver name as usage is keyed"""
    return name.strip().casefold()


def parse_usage(data: Any) -> dict[str, LapUsage]:
    """Energy usage of each driver name (casefold), drivers without any lap used left out"""
    found: dict[str, LapUsage] = {}
    if not isinstance(data, dict):
        return found
    for name, laps in data.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(laps, list):
            continue
        used = lap_usages(laps, AVERAGE_LAPS)
        if not used:
            continue
        found[driver_key(name)] = LapUsage(used[-1], sum(used) / len(used))
    return found


class EnergyUsage(RoutePoller[dict[str, LapUsage]]):
    """Energy used per lap by drivers of session, read in background (see RoutePoller)"""

    def __init__(self, fetch=None, clock=None):
        super().__init__(ROUTE, parse_usage, {}, CHECK_SECONDS, fetch, clock, CHECK_BYTES_PER_SECOND)

    def usage(self, name: str) -> LapUsage | None:
        """Energy usage of driver by name, None if unknown"""
        return self.value.get(driver_key(name))


energy_usage = EnergyUsage()
