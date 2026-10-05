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
Race under way, player car: race state for the rest of the race plan (race calculator page &
race plan widget), stops counted, class rivals

Game values used (LMU & rF2 scoring): race clock = session time (mCurrentET) - race start time
(mStartET), as race length of a live race is end time - start time; time left = end time -
session time; tread = mean of tyre wear (fraction of tread left, 1 = new), as other modules
read it. Stops: the game count (mNumPitstops) when the race state is first read, then a stop is
counted when the car stood still in the pits or got fuel, energy or tyres there, so a stop is
counted once leaving the pits (whenever the game counts it) and drive-through penalties are not.
"""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic
from typing import NamedTuple

from .api_control import api
from .fuel_strategy import RaceState

RACE_SESSION = 4
STILL_SPEED = 0.5  # m/s: car standing in pit box
STILL_SECONDS = 1.0


class StopCounter:
    """Stops of the player car in a race (drive-through penalties left out)

    A pit visit seen is counted on leaving the pits when the car was serviced there. A rise of
    the game count without pit visit seen (page or widget not updated meanwhile, opened during
    the race) is a stop missed: the game count is trusted for it.
    """

    def __init__(self):
        self.session: tuple | None = None
        self.baseline = 0  # game count when counting started
        self.counted = 0
        self.last_game = 0
        self.visit_seen = False  # pit visit seen since last rise of game count
        self.in_pits = False
        self.counting = False  # pit visit seen from its start (counted on leaving if serviced)
        self.still_since = 0.0
        self.serviced = False  # stood still, fuel, energy or tyres during this pit visit
        self.amounts = (0.0, 0.0, 0.0)

    def update(self, session: tuple, in_pits: bool, speed: float, fuel: float, energy: float,
               tread: float, game_stops: int, now: float | None = None) -> int:
        """Stops done"""
        now = monotonic() if now is None else now
        if session != self.session:
            self.session = session
            self.baseline = self.last_game = game_stops
            self.counted = 0
            self.visit_seen = False
            self.in_pits = in_pits  # visit under way: the game count is trusted for it
            self.counting = False
        if in_pits and not self.in_pits:  # pit entry (before game count: it may rise at entry)
            self.in_pits = True
            self.counting = True
            self.visit_seen = True
            self.serviced = False
            self.still_since = 0.0
            self.amounts = (fuel, energy, tread)
        if game_stops > self.last_game:
            if not self.visit_seen:
                self.counted += game_stops - self.last_game
            self.visit_seen = False
            self.last_game = game_stops
        if in_pits:
            if speed < STILL_SPEED:
                if not self.still_since:
                    self.still_since = now
                elif now - self.still_since >= STILL_SECONDS:
                    self.serviced = True
            else:
                self.still_since = 0.0
            fuel_before, energy_before, tread_before = self.amounts
            if fuel > fuel_before + 0.5 or energy > energy_before + 1.0 or tread > tread_before + 1.0:
                self.serviced = True
        elif self.in_pits:  # pit exit
            self.in_pits = False
            if self.counting and self.serviced:
                self.counted += 1
            self.counting = False
        return self.baseline + self.counted


class LiveRead(NamedTuple):
    """Race state (None out of a race or before the first lap) & values read, for checking"""

    state: RaceState | None
    in_pits: bool
    text: str


def read_race_state(unit_fuel: Callable[[float], float], counter: StopCounter,
                    symbol_fuel: str = "L") -> LiveRead:
    """Race state of the player car, counter updated"""
    session = api.read.session
    in_pits = api.read.vehicle.in_pits()
    fuel = unit_fuel(api.read.engine.fuel())
    energy = api.read.engine.virtual_energy() * 100
    tread = sum(api.read.tyre.wear()) * 25
    game_stops = api.read.vehicle.number_pitstops()
    stops = counter.update(
        session.identifier(), in_pits, api.read.vehicle.speed(), fuel, energy, tread, game_stops)
    if session.session_type() != RACE_SESSION or not session.in_race():
        return LiveRead(None, in_pits, "")
    laps_done = api.read.lap.completed_laps()
    progress = api.read.lap.progress()
    elapsed = max(session.elapsed() - max(session.start(), 0.0), 0.0)
    seconds_left = session.remaining()
    text = (f"{laps_done} (+{progress:.2f}) · {clock(elapsed)} / {clock(seconds_left)} · "
            f"{fuel:.1f} {symbol_fuel} · {energy:.0f} % · {tread:.0f} % · {stops} ({game_stops})")
    if laps_done <= 0:  # plan made before the start is the plan of the race
        return LiveRead(None, in_pits, text)
    state = RaceState(laps_done, progress, elapsed, seconds_left, fuel, energy, tread, stops)
    return LiveRead(state, in_pits, text)


def clock(seconds: float) -> str:
    """Race time as h:mm:ss"""
    seconds = round(max(seconds, 0))
    return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


class Rival(NamedTuple):
    """Car of the player class: place, driver, laps, stops & lap of last stop"""

    place: int
    driver: str
    laps: int
    stops: int
    last_stop_lap: int  # 0 = no stop seen
    in_pits: bool
    player: bool


class RivalTracker:
    """Stops of the cars of the player class (lap of last stop seen while tracking)"""

    def __init__(self):
        self.session: tuple | None = None
        self.stops: dict[str, tuple[int, int]] = {}  # driver: stops, lap of last stop

    def update(self) -> list[Rival]:
        """Cars of the player class by place"""
        read = api.read
        session = read.session.identifier()
        if session != self.session:
            self.session = session
            self.stops.clear()
        player = read.vehicle.player_index()
        rivals = []
        for index in range(read.vehicle.total_vehicles()):
            if index != player and not read.vehicle.same_class(index):
                continue
            name = read.vehicle.driver_name(index)
            stops = read.vehicle.number_pitstops(index)
            laps = read.lap.completed_laps(index)
            known_stops, last_lap = self.stops.get(name, (stops, 0))
            if stops > known_stops:
                last_lap = laps
            self.stops[name] = (stops, last_lap)
            rivals.append(Rival(read.vehicle.place(index), name, laps, stops, last_lap,
                                read.vehicle.in_pits(index), index == player))
        return sorted(rivals, key=lambda rival: rival.place)
