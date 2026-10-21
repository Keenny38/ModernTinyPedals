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
Race under way, player car: race state for the rest of the race plan (race calculator page &
race plan widget), stops counted, class rivals

Game values used (LMU & rF2 scoring): race clock = session time (mCurrentET) - race start time
(mStartET), as race length of a live race is end time - start time; time left = end time -
session time; tread = mean of tyre wear (fraction of tread left, 1 = new), as other modules
read it. Stops: the game count (mNumPitstops) when the race state is first read, then a stop is
counted when the car stood still in the pits or got fuel, energy or tyres there, so a stop is
counted once leaving the pits (whenever the game counts it) and drive-through penalties are not.
Lap & race clock of the last stop seen are kept, so the stint in progress is counted from the
real stop (not the one planned). Session change: see validator.is_same_session.

Driver of each stint: driver name of the player car in scoring (the driver in the car, it changes
on a driver swap), read at pit entry (driver of the stint ended) and pit exit (driver of the next
stint) of each stop seen; driving time of a stint: race clock from pit exit to next pit entry. Game strategy data (team usage) is only asked while the race calculator
team tab is shown, so scoring is the source followed all race long.
"""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic
from typing import NamedTuple

from .api_control import api
from .fuel_strategy import RaceState
from .validator import is_same_session, session_token

RACE_SESSION = 4
STILL_SPEED = 0.5  # m/s: car standing in pit box
STILL_SECONDS = 1.0


class StopRecord(NamedTuple):
    """Stop seen, recorded leaving the pits"""

    number: int  # stop of the race (1 = first)
    lap: int  # race laps done
    clock: float  # race clock leaving the pits
    driver_in: str  # driver of the stint ended by the stop (in the car at pit entry), "" unknown
    driver_out: str  # driver of the next stint (in the car leaving the pits), "" unknown
    entry_clock: float = -1.0  # race clock at pit entry, -1 = unknown


class StopCounter:
    """Stops of the player car in a race (drive-through penalties left out)

    A pit visit seen is counted on leaving the pits when the car was serviced there. A rise of
    the game count without pit visit seen (page or widget not updated meanwhile, opened during
    the race) is a stop missed: the game count is trusted for it (lap & clock of it unknown).
    """

    def __init__(self):
        self.session: tuple | None = None  # session token, see validator.session_token
        self.baseline = 0  # game count when counting started
        self.counted = 0
        self.last_game = 0
        self.visit_seen = False  # pit visit seen since last rise of game count
        self.in_pits = False
        self.counting = False  # pit visit seen from its start (counted on leaving if serviced)
        self.still_since = 0.0
        self.serviced = False  # stood still, fuel, energy or tyres during this pit visit
        self.amounts = (0.0, 0.0, 0.0)
        self.last_stop_lap = -1  # race laps done at last stop seen, -1 = unknown
        self.last_stop_clock = -1.0  # race clock leaving the pits after last stop seen, -1 = unknown
        self.stops: list[StopRecord] = []  # stops seen in this session
        self.driver = ""  # driver in the car (last update)
        self.entry_driver = ""  # driver in the car at pit entry
        self.entry_clock = -1.0  # race clock at pit entry

    def update(self, session: tuple, in_pits: bool, speed: float, fuel: float, energy: float,
               tread: float, game_stops: int, now: float | None = None, laps: float = 0.0,
               clock: float = 0.0, driver: str = "") -> int:
        """Stops done

        Args:
            session: session identifier (stamp, elapsed seconds, total laps).
            now: time (seconds), monotonic clock by default.
            laps: race laps done & progress of lap (lap of a stop).
            clock: race clock (seconds).
            driver: driver in the car (scoring driver name), "" unknown.
        """
        now = monotonic() if now is None else now
        token = session_token(session, now)
        if not is_same_session(self.session, token):
            self.baseline = self.last_game = game_stops
            self.counted = 0
            self.visit_seen = False
            self.in_pits = in_pits  # visit under way: the game count is trusted for it
            self.counting = False
            self.last_stop_lap = -1
            self.last_stop_clock = -1.0
            self.stops = []
            self.entry_driver = ""
        self.session = token
        self.driver = driver
        if in_pits and not self.in_pits:  # pit entry (before game count: it may rise at entry)
            self.in_pits = True
            self.counting = True
            self.visit_seen = True
            self.serviced = False
            self.still_since = 0.0
            self.amounts = (fuel, energy, tread)
            self.entry_driver = driver
            self.entry_clock = max(clock, 0.0)
        if game_stops > self.last_game:
            if not self.visit_seen:
                self.counted += game_stops - self.last_game
                self.last_stop_lap = -1
                self.last_stop_clock = -1.0
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
                self.last_stop_lap = max(round(laps), 0)  # stop at end of lap, line crossed in pit lane or not
                self.last_stop_clock = max(clock, 0.0)
                self.stops.append(StopRecord(
                    self.baseline + self.counted, self.last_stop_lap, self.last_stop_clock,
                    self.entry_driver, driver, self.entry_clock))
            self.counting = False
        return self.baseline + self.counted

    def stint_drivers(self) -> tuple[str, ...]:
        """Driver of each stint of the race (first stint first, stint in progress last), "" unknown

        Stint ended by a stop seen: driver at pit entry, else driver leaving the stop before.
        Stint in progress: driver in the car (at pit entry while a stop is under way: the next
        driver may already be in).
        """
        count = self.baseline + self.counted + 1
        names = [""] * count
        for stop in self.stops:
            if 0 < stop.number < count:
                names[stop.number - 1] = stop.driver_in or names[stop.number - 1]
                names[stop.number] = names[stop.number] or stop.driver_out
        names[-1] = (self.entry_driver if self.counting else self.driver) or names[-1]
        return tuple(names)

    def stint_seconds(self) -> tuple[float, ...]:
        """Driving time of each stint ended (first stint first), -1 unknown: race clock from pit
        exit of the stop before (race start for the first stint) to pit entry of the stop ending it,
        both seen"""
        count = self.baseline + self.counted
        seconds = [-1.0] * count
        exits = {stop.number: stop.clock for stop in self.stops}
        for stop in self.stops:
            start = 0.0 if stop.number == 1 else exits.get(stop.number - 1, -1.0)
            if 0 < stop.number <= count and start >= 0 <= stop.entry_clock and stop.entry_clock >= start:
                seconds[stop.number - 1] = stop.entry_clock - start
        return tuple(seconds)


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
    laps_done = api.read.lap.completed_laps()
    progress = api.read.lap.progress()
    elapsed = max(session.elapsed() - max(session.start(), 0.0), 0.0)
    stops = counter.update(
        session.identifier(), in_pits, api.read.vehicle.speed(), fuel, energy, tread, game_stops,
        laps=laps_done + progress, clock=elapsed, driver=api.read.vehicle.driver_name())
    if session.session_type() != RACE_SESSION or not session.in_race():
        return LiveRead(None, in_pits, "")
    seconds_left = session.remaining()
    if seconds_left <= 0 < session.end():  # timer ended: time since (negative)
        seconds_left = min(session.end() - session.elapsed(), 0.0)
    penalty = api.read.vehicle.penalty()
    penalties = max(api.read.vehicle.number_penalties(), penalty.pending, 0)
    stop_go = float(penalty.seconds) if penalties and "stop" in penalty.kind.casefold() else 0.0
    repair = max(api.read.vehicle.repair_time(), 0.0)
    text =(f"{laps_done} (+{progress:.2f}) · {clock(elapsed)} / {clock(seconds_left)} · "
            f"{fuel:.1f} {symbol_fuel} · {energy:.0f} % · {tread:.0f} % · {stops} ({game_stops})")
    if laps_done <= 0:  # plan made before the start is the plan of the race
        return LiveRead(None, in_pits, text)
    state = RaceState(laps_done, progress, elapsed, seconds_left, fuel, energy, tread, stops,
                      counter.last_stop_lap, counter.last_stop_clock, counter.stint_drivers(),
                      counter.stint_seconds(), penalties, stop_go, repair)
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
    progress: float = 0.0  # race distance: laps completed & fraction of lap in progress


class PitExit(NamedTuple):
    """Where the player car rejoins if it stops at the end of this lap: class place, cars just
    ahead & behind (name, seconds), class cars passing during the stop"""

    place: int
    ahead: tuple[str, float] | None
    behind: tuple[str, float] | None
    passed: int
    loss: float  # seconds lost by the stop (pit lane & service)


def pit_exit(rivals: list[Rival], loss: float, laptime: float) -> PitExit | None:
    """Rejoin of the player car after a stop losing `loss` seconds, from the race distance of the
    cars of its class (gaps at the player's lap time, other cars not stopping meanwhile), None
    without player car, lap time or other car"""
    player = next((rival for rival in rivals if rival.player), None)
    others = [rival for rival in rivals if not rival.player]
    if player is None or not others or laptime <= 0 or loss <= 0:
        return None
    after = player.progress - loss / laptime  # race distance once back on track
    ahead = [rival for rival in others if rival.progress > after]
    behind = [rival for rival in others if rival.progress <= after]
    passed = sum(1 for rival in ahead if rival.progress <= player.progress)
    closest_ahead = min(ahead, key=lambda rival: rival.progress, default=None)
    closest_behind = max(behind, key=lambda rival: rival.progress, default=None)
    return PitExit(
        len(ahead) + 1,
        (closest_ahead.driver, (closest_ahead.progress - after) * laptime) if closest_ahead else None,
        (closest_behind.driver, (after - closest_behind.progress) * laptime) if closest_behind else None,
        passed, loss,
    )


class RivalTracker:
    """Stops of the cars of the player class (lap of last stop seen while tracking)"""

    def __init__(self):
        self.session: tuple | None = None  # session token, see validator.session_token
        self.stops: dict[int, tuple[int, int]] = {}  # car slot (same on driver swap): stops, lap of last stop

    def update(self, now: float | None = None) -> list[Rival]:
        """Cars of the player class by place"""
        read = api.read
        token = session_token(read.session.identifier(), monotonic() if now is None else now)
        if not is_same_session(self.session, token):
            self.stops.clear()
        self.session = token
        player = read.vehicle.player_index()
        rivals = []
        for index in range(read.vehicle.total_vehicles()):
            if index != player and not read.vehicle.same_class(index):
                continue
            slot = read.vehicle.slot_id(index)
            stops = read.vehicle.number_pitstops(index)
            laps = read.lap.completed_laps(index)
            known_stops, last_lap = self.stops.get(slot, (stops, 0))
            if stops > known_stops:
                last_lap = laps
            self.stops[slot] = (stops, last_lap)
            rivals.append(Rival(read.vehicle.place(index), read.vehicle.driver_name(index), laps, stops,
                                last_lap, read.vehicle.in_pits(index), index == player,
                                laps + min(max(read.lap.progress(index), 0.0), 1.0)))
        return sorted(rivals, key=lambda rival: rival.place)
