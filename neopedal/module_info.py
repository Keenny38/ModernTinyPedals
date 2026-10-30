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
Module info
"""

from __future__ import annotations

import threading
from array import array
from collections import deque
from collections.abc import Mapping
from typing import NamedTuple

from .calculation import circular_position_relative, linear_interp
from .const_common import (
    DELTA_DEFAULT,
    EMPTY_DICT,
    MAX_METERS,
    MAX_SECONDS,
    MAX_VEHICLES,
    REL_TIME_DEFAULT,
    WHEELS_ZERO,
)
from .penalty_info import NO_PENALTY, Penalty
from .template.setting_status_colors import SAME_TIME


class ConsumptionDataSet(NamedTuple):
    """Consumption history data set"""

    lapNumber: int = 0
    isValidLap: int = 0
    lapTimeLast: float = 0.0
    lastLapUsedFuel: float = 0.0
    lastLapUsedEnergy: float = 0.0
    batteryDrainLast: float = 0.0
    batteryRegenLast: float = 0.0
    tyreAvgWearLast: float = 0.0
    capacityFuel: float = 0.0


class MapCoords:
    """Map coords data"""

    __slots__ = (
        "coords",
        "dists",
        "sectors",
    )

    def __init__(self, coords=None, dists=None, sectors=None):
        """
        Args:
            coords: x,y coordinates list.
            dists: distance,elevation list.
            sectors: sector node index reference list.
        """
        self.coords = coords
        self.dists = dists
        self.sectors = sectors

    def is_valid(self) -> bool:
        """Is valid data"""
        return all((self.coords, self.dists, self.sectors))

    def clear(self):
        """Clear coords data"""
        self.coords = None
        self.dists = None
        self.sectors = None

    def reset(self):
        """Reset coords data"""
        self.coords = []
        self.dists = []
        self.sectors = [0, 0]


class StintData:
    """Stint data"""

    __slots__ = (
        "totalLaps",
        "totalTime",
        "totalFuel",
        "totalEnergy",
        "totalTyreWear",
        "lapTimeDelta",
        "lapTimeConsistency",
        "tyreCompound",
        "tyreCompoundNames",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        """Reset"""
        self.totalLaps: int = 0
        self.totalTime: float = 0
        self.totalFuel: float = 0.0
        self.totalEnergy: float = 0.0
        self.totalTyreWear: float = 0.0
        self.lapTimeDelta: float = 0.0
        self.lapTimeConsistency: float = 0.0
        self.tyreCompound: str = "----"
        self.tyreCompoundNames: tuple[str, ...] = ()  # compound class of each wheel, for badges


class StintDataSet(NamedTuple):
    """Stint history data set"""

    totalLaps: int = 0
    totalTime: float = 0
    totalFuel: float = 0.0
    totalEnergy: float = 0.0
    totalTyreWear: float = 0.0
    lapTimeDelta: float = 0.0
    lapTimeConsistency: float = 0.0
    tyreCompound: str = "----"
    tyreCompoundNames: tuple[str, ...] = ()


class DeltaTimeInterval:
    """Delta time interval data

    Attributes:
        last: Last time interval.
        long: Average time interval (long duration).
        normal: Average time interval (normal duration).
        short: Average time interval (short duration).
    """

    __slots__ = (
        "last",
        "long",
        "normal",
        "short",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        """Reset delta time interval (new session, other vehicle in slot)"""
        self.last = 0.0
        self.long = 0.0
        self.normal = 0.0
        self.short = 0.0

    def update(self, time_interval: float):
        """Update delta time interval"""
        if self.last != time_interval:
            diff = self.last - time_interval
            if abs(diff) < 3:  # position switch check
                self.long += 0.01 * (diff - self.long)  # 200s
                self.normal += 0.02 * (diff - self.normal)  # 100s
                self.short += 0.065 * (diff - self.short)  # 30s
                # Sync longer duration with short if higher than 0.3 difference
                if abs(self.normal - self.short) > 0.3:
                    self.normal = self.short
                if abs(self.long - self.normal) > 0.3:
                    self.long = self.normal
            self.last = time_interval


class DeltaLapTimeHistory(array):
    """Delta lap time history data

    Attributes:
        best: Best lap time from recent laps.
        last: Last lap time, can be invalid.
        average: Average lap time from recent laps.
    """

    __slots__ = (
        "_last_lap_start",
        "best",
        "last",
        "average",
    )

    def __init__(self, typecode, initializer):
        self._last_lap_start = 0.0
        self.best = 0.0
        self.last = 0.0
        self.average = 0.0

    def update(self, lap_start: float, elapsed_time: float, best_valid: float):
        """Update delta lap time history"""
        if self._last_lap_start != lap_start and elapsed_time - lap_start > 1:
            if 0 < self._last_lap_start < lap_start:
                self[0], self[1], self[2], self[3] = self[1], self[2], self[3], self[4]
                self[4] = lap_start - self._last_lap_start  # last lap time
            else:  # reset all laptime on session change
                self[0] = self[1] = self[2] = self[3] = self[4] = 0.0
            self._last_lap_start = lap_start
            # Recalculate once per lap
            if best_valid <= 0:
                best_recent = MAX_SECONDS
            else:
                # Find best time from recent laps
                best_recent = min(self._filter_laptime(best_valid))
                if best_recent >= MAX_SECONDS:  # fallback to session best
                    best_recent = best_valid
            self.best = best_recent
            self.average = self._average_laptime(self.best)
            self.last = self[4]

    def delta(self, target: DeltaLapTimeHistory, max_output: int):
        """Generate delta from target player's lap time data set"""
        for index in range(5 - max_output, 5):  # max 5 records
            if target[index] > 0 < self[index]:  # check invalid lap time
                yield target[index] - self[index]
            else:
                yield MAX_SECONDS

    def _average_laptime(self, laptime_best: float) -> float:
        """Calculate average lap time"""
        if laptime_best >= MAX_SECONDS:
            return MAX_SECONDS
        laptime_sum = 0
        count = 0
        margin = laptime_best * 1.2
        for laptime in self._filter_laptime(laptime_best):
            # Make sure lap time within 120% of recent best laptime
            if laptime <= margin:
                laptime_sum += laptime
                count += 1
        if count:
            return laptime_sum / count
        return laptime_best

    def _filter_laptime(self, best_valid: float):
        """Filter invalid lap time"""
        best_valid -= 0.01  # compensate precision
        for laptime in self:
            # Make sure lap time is not lower than session best valid lap time
            if laptime >= best_valid > 0:
                yield laptime
            else:
                yield MAX_SECONDS


class DeltaFuelHistory:
    """Delta fuel history data

    Attributes:
        used: Last lap used fuel.
        last: Last lap remaining fuel.
        laps: Last lap remaining laps.
    """

    __slots__ = (
        "_last_lap_start",
        "_last_remaining",
        "used",
        "laps",
    )

    def __init__(self):
        self._last_lap_start = 0.0
        self._last_remaining = 0.0
        self.used = 0.0
        self.laps = 0.0

    def update(self, lap_start: float, remaining: float):
        """Update delta lap time history"""
        if self._last_lap_start != lap_start:
            if 0 < self._last_lap_start < lap_start:
                if self._last_remaining > remaining:
                    self.used = self._last_remaining - remaining
                self._last_remaining = remaining
                if self.used > 0:
                    self.laps = remaining / self.used
            else:  # reset all laptime on session change
                self.used = self.laps = self._last_remaining = 0.0
            self._last_lap_start = lap_start


class LicoTimer:
    """Lift and coast timer

    Attributes:
        idling: time since last lico.
        elapsed: last recorded lico time.
        input_time: telemetry time of throttle & brake read (unchanged until next telemetry update).
        throttle: last throttle read.
        brake: last brake read.
    """

    __slots__ = (
        "_last_time",
        "_cooldown_time",
        "_warmup_time",
        "idling",
        "elapsed",
        "input_time",
        "throttle",
        "brake",
    )

    def __init__(self):
        self._last_time = 0.0
        self._cooldown_time = 0.0
        self._warmup_time = 0.0
        self.idling = 0.0
        self.elapsed = 0.0
        self.input_time = -1.0
        self.throttle = 0.0
        self.brake = 0.0

    def update(self, elapsed_time: float, throttle_raw: float, brake_raw: float):
        """Update lico timer"""
        braking = brake_raw > 0.01
        delta_time = elapsed_time - self._last_time
        self._last_time = elapsed_time
        if delta_time < 0:
            delta_time = 0
        # Always reset on braking
        if braking:
            self._cooldown_time = 0
        # Count 3s continuous throttling
        elif self._cooldown_time < 3:
            if throttle_raw >= 0.8:  # workaround network inaccuracy
                self._cooldown_time += delta_time
            else:  # reset if released early
                self._cooldown_time = 0
        # Lift and coasting
        if self._cooldown_time >= 3 and not braking and throttle_raw < 0.1:
            if self._warmup_time < 0.5:  # ignore auto-lift from upshifting
                self._warmup_time += delta_time
            else:
                if self.idling:  # reset
                    self.elapsed = self._warmup_time
                    self.idling = 0
                self.elapsed += delta_time
        else:
            if not self.idling:
                self._cooldown_time = 0
            self.idling += delta_time
            self._warmup_time = 0


class LapSectors:
    """Sector times of a car as the game live timing shows them: sectors of current & last lap, personal best of
    each sector from completed laps only (a sector beaten during the lap counts once the lap is completed),
    sectors of best lap, pit lane in last lap (in lap, out lap)

    Attributes:
        current: S1, S2 of current lap (0: not completed yet).
        last: S1, S2, S3 of last lap (0: unknown).
        best: personal best of S1, S2, S3 from completed laps (0: none yet).
        best_lap: S1, S2, S3 of best lap (game).
        sector: sector being driven, 0 = S1, 1 = S2, 2 = S3.
        out_lap: current lap started in or left pit lane.
        last_kind: "OUT" (left pit lane in last lap), "IN" (entered it), "" (no pit lane).
        previous_kind: kind of lap before last.
        changed: number of updates that changed sectors (cells made again only then).
    """

    __slots__ = (
        "current",
        "last",
        "best",
        "best_lap",
        "sector",
        "laps",
        "out_lap",
        "last_kind",
        "previous_kind",
        "_pit_in",
        "_in_pit",
        "changed",
    )

    def __init__(self):
        self.current = (0.0, 0.0)
        self.last = (0.0, 0.0, 0.0)
        self.best = [0.0, 0.0, 0.0]
        self.best_lap = (0.0, 0.0, 0.0)
        self.sector = 0
        self.laps = -1
        self.out_lap = False
        self.last_kind = ""
        self.previous_kind = ""
        self._pit_in = False
        self._in_pit = False
        self.changed = 0

    def _better(self, number: int, value: float):
        if 0 < value < MAX_SECONDS and (not self.best[number] or value < self.best[number]):
            self.best[number] = value

    def update(self, laps: int, sector: int, current1: float, current2: float, last1: float, last2: float,
               last_lap: float, in_pit: bool, best1: float = 0.0, best2: float = 0.0, best_lap: float = 0.0):
        """Game timing of car (sector times are cumulative: S1, S1 + S2, lap; best ones of best lap)"""
        old = (self.current, self.last, self.sector, self.last_kind, self.out_lap, self.best_lap)
        if in_pit and not self._in_pit:
            self._pit_in = True
        elif self._in_pit and not in_pit:
            self.out_lap = True
        self._in_pit = in_pit
        self.best_lap = split_sectors(best1, best2, best_lap)
        if laps != self.laps:
            if self.laps >= 0 and laps == self.laps + 1:  # lap completed: its sectors count for bests
                self.previous_kind = self.last_kind
                self.last_kind = "OUT" if self.out_lap else "IN" if self._pit_in else ""
                self.last = split_sectors(last1, last2, last_lap)
                for number, value in enumerate(self.last):
                    self._better(number, value)
            else:  # first update, session change or laps jumped: bests of game best lap meanwhile
                if 0 <= laps < self.laps:  # laps went back: other session, its bests only
                    self.best = [0.0, 0.0, 0.0]
                self.last_kind = self.previous_kind = ""
                self.last = split_sectors(last1, last2, last_lap)
                for number, value in enumerate((*self.best_lap, *self.last)):
                    self._better(number % 3, value)
            self.laps = laps
            self._pit_in = False
            self.out_lap = in_pit  # lap started in pit lane: out lap
        sector1 = current1 if sector >= 1 and 0 < current1 < MAX_SECONDS else 0.0
        sector2 = current2 - current1 if sector == 2 and 0 < current1 < current2 < MAX_SECONDS else 0.0
        self.current = (sector1, sector2)
        self.sector = sector
        if (self.current, self.last, self.sector, self.last_kind, self.out_lap, self.best_lap) != old:
            self.changed += 1

    def best_now(self) -> tuple[float, float, float]:
        """Personal best of each sector with sectors completed in lap being driven (best of class at once)"""
        best1, best2, best3 = self.best
        current1, current2 = self.current  # 0 unless completed in lap being driven
        return (min(best1, current1) if best1 and current1 else best1 or current1,
                min(best2, current2) if best2 and current2 else best2 or current2, best3)

    def recent(self) -> tuple[float, float, float]:
        """Most recent time of each sector: current lap for sectors completed in it, else last lap"""
        return (self.current[0] if self.sector >= 1 else self.last[0],
                self.current[1] if self.sector == 2 else self.last[1], self.last[2])

    def shown(self, in_race: bool, pitting: bool) -> tuple[tuple[float, float, float], int]:
        """Sector times shown as game live timing does & sector being driven (-1: none): last lap while S1 is
        driven, else completed sectors of current lap; outside races, none on an out lap, best lap while pitting"""
        if not in_race:
            if pitting:
                return self.best_lap, -1
            if self.out_lap:
                return (0.0, 0.0, 0.0), -1
        if self.sector == 0:
            return self.last, -1
        return (self.current[0], self.current[1] if self.sector == 2 else 0.0, 0.0), self.sector


# Theme color names, as app pages & stream graphics (setting_status_colors): purple, green, yellow
SECTOR_CLASS_BEST, SECTOR_PERSONAL_BEST, SECTOR_SLOWER = "best", "positive", "caution"


def sector_color(value: float, number: int, sectors: LapSectors, class_best: tuple) -> str | None:
    """Theme color name of a sector time as game live timing: best of class in session (purple, one car only),
    personal best improved or set (green, at once when sector of lap being driven beats it), slower (yellow); None
    if no time"""
    if not 0 < value < MAX_SECONDS:
        return None
    if class_best[number] and value < class_best[number] + SAME_TIME:
        return SECTOR_CLASS_BEST
    best = sectors.best[number]  # completed laps (last lap shown: its sectors included)
    if not best or value < best + SAME_TIME:
        return SECTOR_PERSONAL_BEST
    return SECTOR_SLOWER


def set_class_bests(cars) -> None:
    """Best S1, S2, S3 & best lap of each class in session told to every car of class (purple times as game live
    timing): personal bests of its cars, sectors completed in laps being driven included (a sector beaten during the
    lap is the only purple one at once)"""
    best: dict[str, list[float]] = {}
    for data in cars:
        found = best.setdefault(data.vehicleClass, [0.0, 0.0, 0.0, 0.0])
        lap = data.bestLapTime if 0 < data.bestLapTime < MAX_SECONDS else 0.0
        for number, value in enumerate((*data.sectors.best_now(), lap)):
            if 0 < value < MAX_SECONDS and (not found[number] or value < found[number]):
                found[number] = value
    for data in cars:
        found = best[data.vehicleClass]
        data.classBestSectors = (found[0], found[1], found[2])
        data.classBestLap = found[3]


def split_sectors(sector1: float, sector2: float, laptime: float) -> tuple[float, float, float]:
    """S1, S2, S3 of cumulative game times (S1, S1 + S2, lap), 0 where unknown (invalid lap: no lap time)"""
    valid1 = 0 < sector1 < MAX_SECONDS
    valid2 = valid1 and sector1 < sector2 < MAX_SECONDS
    return (
        sector1 if valid1 else 0.0,
        sector2 - sector1 if valid2 else 0.0,
        laptime - sector2 if valid2 and sector2 < laptime < MAX_SECONDS else 0.0,
    )


class SpeedTrap:
    """Speed trap

    Attributes:
        speed: Speed(m/s) at speed trap.
    """

    __slots__ = (
        "_record_next",
        "_speed_before",
        "_distance_last",
        "_distance_before",
        "speed",
    )

    def __init__(self):
        self._record_next = False
        self._speed_before = 0.0
        self._distance_last = 0.0
        self._distance_before = 0.0
        self.speed = 0.0

    def update(self, speed: float, distance_into: float, speedtrap_distance: float, track_length: float):
        """Update speed trap data"""
        if self._distance_last == distance_into:
            return
        self._distance_last = distance_into

        # Center distance to speed trap position
        distance_into = circular_position_relative(track_length, speedtrap_distance, distance_into)

        if self._record_next:
            # Distance before speed trap
            if distance_into < 0:
                self._distance_before = distance_into
                self._speed_before = speed
            else:
                # Distance after speed trap
                if distance_into - self._distance_before < 200:
                    self.speed = linear_interp(
                        0,
                        self._distance_before,
                        self._speed_before,
                        distance_into,
                        speed,
                    )
                # Turn off record until distance circles back
                self._record_next = False
        elif distance_into < 0:
            self._record_next = True


class PitTimer:
    """Pit timer

    Attributes:
        elapsed: Total time spent in pit.
        stopped: Total time spent while stopped in pit.
        pitting: Is pitting in or out (in pit lane, or out lap of a pit visit seen by this timer).
        laps: Total laps done since last pit stop (since first seen if no pit stop seen).
    """

    __slots__ = (
        "elapsed",
        "stopped",
        "pitting",
        "laps",
        "_pitin_time",
        "_pitstop_time",
        "_last_state",
        "_last_pit_lap",
        "_pit_seen",
    )

    def __init__(self):
        self.elapsed: float = 0.0
        self.stopped: float = 0.0
        self.pitting: bool = False
        self.laps: int = 0
        self._pitin_time: float = 0.0
        self._pitstop_time: float = 0.0
        self._last_state: int = 0
        self._last_pit_lap: int = 99999  # lap of last pit visit, else lap first seen (stint laps counted from it)
        self._pit_seen: bool = False  # a pit visit set _last_pit_lap: its lap is a pitting (out) lap

    def update(self, in_pit: int, elapsed_time: float, laps_done: int, speed: float):
        """Calculate pit time

        Pit state: 0 = not in pit, 1 = in pit, 2 = in garage.
        """
        # Reset if session changed (or first seen): laps counted from here, no pit visit known
        # (a car on its first lap, from the grid, is not on an out lap)
        if self._last_pit_lap > laps_done:
            self._last_pit_lap = laps_done
            self._pit_seen = False
        # Pit status check
        if self._last_state != in_pit:
            self._last_state = in_pit
            self._pitin_time = elapsed_time
            self._pitstop_time = elapsed_time
            if in_pit:  # reset after enter pit
                self.elapsed = 0.0
                self.stopped = 0.0
        if in_pit:
            # Ignore pit timer in garage
            if in_pit == 2:
                self.elapsed = 0.0
                self.stopped = 0.0
                self._last_pit_lap = laps_done
                self._pit_seen = True
            # Calculating time while in pit
            else:
                # Total elapsed time in pit
                self.elapsed += elapsed_time - self._pitin_time
                # Total stopped time in pit
                if speed < 0.1:
                    self.stopped += elapsed_time - self._pitstop_time
            # Reset delta
            self._pitin_time = elapsed_time
            self._pitstop_time = elapsed_time
            # Save last in pit lap number
            # Pit state can desync, wait minimum 2 seconds before update
            if self.elapsed > 2 and self.stopped > 1:  # stop for more than 1 seconds
                self._last_pit_lap = laps_done
                self._pit_seen = True
        # Check whether is pitting lap: out lap of a pit visit seen, never the first lap seen (grid start)
        self.pitting = in_pit > 0 or (self._pit_seen and laps_done == self._last_pit_lap)
        self.laps = laps_done - self._last_pit_lap


class VehicleDataSet:
    """Vehicle data set"""

    __slots__ = (
        "isPlayer",
        "elapsedTime",
        "speed",
        "positionOverall",
        "positionInClass",
        "qualifyOverall",
        "qualifyInClass",
        "driverName",
        "vehicleName",
        "vehicleBrand",
        "classAheadIndex",
        "classBehindIndex",
        "classLeaderIndex",
        "vehicleClass",
        "classBestLapTime",
        "bestLapTime",
        "lastLapTime",
        "currentLapProgress",
        "totalLapProgress",
        "gapBehindNext",
        "gapBehindNextInClass",
        "gapBehindLeader",
        "gapBehindLeaderInClass",
        "isLapped",
        "isYellow",
        "isValidLap",
        "isFinished",
        "gapsFrozen",
        "inPit",
        "isClassFastestLastLap",
        "numPitStops",
        "pitRequested",
        "tireCompoundName",
        "relativeOrientationRadians",
        "relativeStraightDistance",
        "worldPositionX",
        "worldPositionY",
        "worldVelocityX",
        "worldVelocityY",
        "worldOrientationRadians",
        "worldElevation",
        "relativeRotatedPositionX",
        "relativeRotatedPositionY",
        "relativeElevation",
        "vehicleIntegrity",
        "incidents",
        "trackLimitsPoints",
        "penalty",
        "sectors",
        "classBestSectors",
        "classBestLap",
        "lapStartTime",
        "energyRemaining",
        "estimatedStintLaps",
        "currentStintLaps",
        "licoTimer",
        "pitTimer",
        "speedTrap",
        "fuelHistory",
        "energyHistory",
        "lapTimeHistory",
    )

    def __init__(self):
        self.isPlayer: bool = False
        self.elapsedTime: float = 0.0
        self.speed: float = 0.0
        self.positionOverall: int = 0
        self.positionInClass: int = 0
        self.qualifyOverall: int = 0
        self.qualifyInClass: int = 0
        self.driverName: str = ""
        self.vehicleName: str = ""
        self.vehicleBrand: str = ""
        self.vehicleClass: str = ""
        self.classAheadIndex: int = -1
        self.classBehindIndex: int = -1
        self.classLeaderIndex: int = -1
        self.classBestLapTime: float = MAX_SECONDS
        self.bestLapTime: float = MAX_SECONDS
        self.lastLapTime: float = MAX_SECONDS
        self.currentLapProgress: float = 0.0
        self.totalLapProgress: float = 0.0
        self.gapBehindNext: float = 0.0
        self.gapBehindNextInClass: float = 0.0
        self.gapBehindLeader: float = 0.0
        self.gapBehindLeaderInClass: float = 0.0
        self.isLapped: float = 0.0
        self.isYellow: bool = False
        self.isValidLap: bool = False
        self.isFinished: bool = False
        self.gapsFrozen: bool = False  # race gaps of finished car kept as they were at the line (see update_race_gaps)
        self.inPit: int = 0
        self.isClassFastestLastLap: bool = False
        self.numPitStops: int = 0
        self.pitRequested: bool = False
        self.tireCompoundName: tuple[str, ...] = ("", "", "", "")
        self.relativeOrientationRadians: float = 0.0
        self.relativeStraightDistance: float = 0.0
        self.worldPositionX: float = 0.0
        self.worldPositionY: float = 0.0
        self.worldVelocityX: float = 0.0  # m/s between last two telemetry samples (position extrapolated)
        self.worldVelocityY: float = 0.0
        self.worldOrientationRadians: float = 0.0  # yaw of last telemetry sample
        self.worldElevation: float = 0.0  # vertical position (meters) of last telemetry sample
        self.relativeRotatedPositionX: float = 0.0
        self.relativeRotatedPositionY: float = 0.0
        self.relativeElevation: float = 0.0  # meters above player (negative: below)
        self.vehicleIntegrity: float = 0.0
        self.incidents: int = 0
        self.trackLimitsPoints: float = 0.0  # LMU: track limits points of session
        self.penalty: Penalty = NO_PENALTY  # LMU: penalties of results stream (kind, time, disqualified)
        self.sectors: LapSectors = LapSectors()
        self.classBestSectors: tuple[float, float, float] = (0.0, 0.0, 0.0)  # best S1, S2, S3 of class in session
        self.classBestLap: float = 0.0  # best lap of class in session (0: none)
        self.lapStartTime: float = 0.0  # session time current lap started
        self.energyRemaining: float = 0.0
        self.estimatedStintLaps: float = 0.0
        self.currentStintLaps: int = 0
        self.licoTimer: LicoTimer = LicoTimer()
        self.pitTimer: PitTimer = PitTimer()
        self.speedTrap: SpeedTrap = SpeedTrap()
        self.fuelHistory: DeltaFuelHistory = DeltaFuelHistory()
        self.energyHistory: DeltaFuelHistory = DeltaFuelHistory()
        self.lapTimeHistory: DeltaLapTimeHistory = DeltaLapTimeHistory("d", (0, 0, 0, 0, 0))


class DeltaInfo:
    """Delta output data"""

    __slots__ = (
        "deltaBestData",
        "deltaBest",
        "deltaLast",
        "deltaSession",
        "deltaStint",
        "isDeltaAvailable",
        "hasLastLap",
        "isValidLap",
        "lapTimeCurrent",
        "lapTimeLast",
        "lapTimeBest",
        "lapTimeEstimated",
        "lapTimeSession",
        "lapTimeStint",
        "lapTimePace",
        "lapDistance",
        "speedDeltaBest",
        "speedDeltaSession",
        "speedDeltaStint",
        "speedDeltaLast",
    )

    def __init__(self):
        self.deltaBestData: tuple[tuple[float, float], ...] = DELTA_DEFAULT
        self.deltaBest: float = 0.0
        self.deltaLast: float = 0.0
        self.deltaSession: float = 0.0
        self.deltaStint: float = 0.0
        # Current lap comparable to reference laps: not an out lap (started in pit lane or garage,
        # time spent there counted), car not before start line in pit lane (negative lap distance)
        self.isDeltaAvailable: bool = False
        self.hasLastLap: bool = False  # last lap recorded & comparable (no pit lane: not in or out lap)
        self.isValidLap: bool = False
        self.lapTimeCurrent: float = 0.0
        self.lapTimeLast: float = 0.0
        self.lapTimeBest: float = 0.0
        self.lapTimeEstimated: float = 0.0
        self.lapTimeSession: float = 0.0
        self.lapTimeStint: float = 0.0
        self.lapTimePace: float = 0.0
        self.lapDistance: float = 0.0
        # Speed difference (m/s, + faster) to reference laps at same lap distance (not smoothed)
        self.speedDeltaBest: float = 0.0
        self.speedDeltaSession: float = 0.0
        self.speedDeltaStint: float = 0.0
        self.speedDeltaLast: float = 0.0


class ForceInfo:
    """Force output data"""

    __slots__ = (
        "lgtGForceRaw",
        "latGForceRaw",
        "maxAvgLatGForce",
        "maxLgtGForce",
        "maxLatGForce",
        "downForceFront",
        "downForceRear",
        "downForceRatio",
        "brakingRate",
        "transientMaxBrakingRate",
        "maxBrakingRate",
        "deltaBrakingRate",
    )

    def __init__(self):
        self.lgtGForceRaw: float = 0.0
        self.latGForceRaw: float = 0.0
        self.maxAvgLatGForce: float = 0.0
        self.maxLgtGForce: float = 0.0
        self.maxLatGForce: float = 0.0
        # Downforce NaN: not provided by game (LMU: always 0 while driving, see module_force)
        self.downForceFront: float = 0.0
        self.downForceRear: float = 0.0
        self.downForceRatio: float = 0.0
        self.brakingRate: float = 0.0
        self.transientMaxBrakingRate: float = 0.0
        self.maxBrakingRate: float = 0.0
        self.deltaBrakingRate: float = 0.0


class FuelInfo:
    """Fuel output data"""

    __slots__ = (
        "available",
        "capacity",
        "amountStart",
        "amountCurrent",
        "amountUsedCurrent",
        "amountEndStint",
        "neededRelative",
        "neededAbsolute",
        "lastLapConsumption",
        "lastLapPartial",
        "estimatedConsumption",
        "estimatedValidConsumption",
        "estimatedLaps",
        "estimatedMinutes",
        "estimatedNumPitStopsEnd",
        "estimatedNumPitStopsEarly",
        "deltaConsumption",
        "oneLessPitConsumption",
        "rateOfConsumption",
        "weight",
        "consumptionMethod",
        "consumptionLaps",
    )

    def __init__(self):
        self.available: bool = False  # set by fuel module each tick, kept by reset (never flickers off)
        self.reset()

    def reset(self):
        """Reset"""
        self.capacity: float = 0.0
        self.amountStart: float = 0.0
        self.amountCurrent: float = 0.0
        self.amountUsedCurrent: float = 0.0
        self.amountEndStint: float = 0.0
        self.neededRelative: float = 0.0
        self.neededAbsolute: float = 0.0
        self.lastLapConsumption: float = 0.0
        self.lastLapPartial: bool = False  # last lap counted from mid-lap (module started on track): no consumption
        self.estimatedConsumption: float = 0.0
        self.estimatedValidConsumption: float = 0.0
        self.estimatedLaps: float = 0.0
        self.estimatedMinutes: float = 0.0
        self.estimatedNumPitStopsEnd: float = 0.0
        self.estimatedNumPitStopsEarly: float = 0.0
        self.deltaConsumption: float = 0.0
        self.oneLessPitConsumption: float = 0.0
        self.rateOfConsumption: float = 0.0
        self.weight: float = 0.0
        # Consumption estimate: "game" (estimate of game), "last_lap" (last valid lap),
        # "median" (median of last valid green flag laps, consumptionLaps laps)
        self.consumptionMethod: str = "game"
        self.consumptionLaps: int = 0


class HistoryInfo:
    """History output data

    Data sets (deque) are iterated by GUI thread: never changed in place, replaced by a new one.
    Consumption data set is replaced & saved holding consumptionLock (stint module adds laps, Race Calculator
    deletes laps): no lap added at the same time lost, no deleted lap saved back.
    """

    __slots__ = (
        "consumptionLock",
        "consumptionDataVersion",
        "consumptionDataSet",
        "stintDataVersion",
        "stintDataCurrent",
        "stintDataSet",
    )

    def __init__(self):
        self.consumptionLock = threading.Lock()
        self.consumptionDataVersion: int = 0
        self.consumptionDataSet: deque[ConsumptionDataSet] = deque([ConsumptionDataSet()], 100)
        self.stintDataVersion: int = 0
        self.stintDataCurrent: StintData = StintData()
        self.stintDataSet: deque[StintDataSet] = deque([StintDataSet()], 100)

    def reset_stint(self):
        """Reset stint data (version changed, never back to a value overlays already drew)"""
        self.stintDataVersion += 1
        self.stintDataCurrent.reset()
        self.stintDataSet = deque([StintDataSet()], self.stintDataSet.maxlen)


class HybridInfo:
    """Hybrid output data"""

    __slots__ = (
        "batteryCharge",
        "batteryDrain",
        "batteryRegen",
        "batteryDrainLast",
        "batteryRegenLast",
        "batteryNetChange",
        "motorActiveTimer",
        "motorInactiveTimer",
        "motorState",
        "fuelEnergyRatio",
        "fuelEnergyBias",
    )

    def __init__(self):
        self.batteryCharge: float = 0.0
        self.batteryDrain: float = 0.0
        self.batteryRegen: float = 0.0
        self.batteryDrainLast: float = 0.0
        self.batteryRegenLast: float = 0.0
        self.batteryNetChange: float = 0.0
        self.motorActiveTimer: float = 0.0
        self.motorInactiveTimer: float = 0.0
        self.motorState: int = 0
        self.fuelEnergyRatio: float = 0.0
        self.fuelEnergyBias: float = 0.0


class TrackMap(NamedTuple):
    """Track map shown by overlays: recorded map, else official circuit of game (see track_map_official)

    Published as a whole (MappingInfo.trackMap replaced, never a field alone): a reader taking trackMap once gets
    coordinates, distances & sectors of the same map, never parts of two maps (mapping module thread).
    """

    coordinates: tuple[tuple[float, float], ...] | None = None  # x, y of each node, from start line
    elevations: tuple[tuple[float, float], ...] | None = None  # lap distance & elevation of each node (None: start
    # line not known yet, official circuit shape only)
    sectors: tuple[int, int] | None = None  # node index before each sector line (None: not known yet)
    lastModified: float = 0.0  # changes with map: map file time, publish time of official circuit

    def start_known(self) -> bool:
        """Whether node 0 is at start line (lap distances known)"""
        return bool(self.coordinates) and bool(self.elevations)


NO_TRACK_MAP = TrackMap()


class MappingInfo:
    """Mapping output data"""

    __slots__ = (
        "trackMap",
        "speedTrapPosition",
        "pitEntryPosition",
        "pitExitPosition",
        "pitLaneLength",
        "pitSpeedLimit",
        "pitPassTime",
        "sunlightPhases",
        "orientation",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        """Reset"""
        self.reset_map()
        self.speedTrapPosition: float = 0.0
        self.pitEntryPosition: float = 0.0
        self.pitExitPosition: float = 0.0
        self.pitLaneLength: float = 0.0
        self.pitSpeedLimit: float = 0.0
        self.pitPassTime: float = 0.0
        self.sunlightPhases: tuple[tuple[float, int], ...] | None = None
        self.orientation: float = 0.0  # track map overlay orientation of track (degrees, track info)

    def reset_map(self):
        """Reset track map only (track info fields owned by track info recording)"""
        self.trackMap: TrackMap = NO_TRACK_MAP

    # Fields of current map, each read on its own: take trackMap once to read several of the same map
    @property
    def coordinates(self) -> tuple[tuple[float, float], ...] | None:
        return self.trackMap.coordinates

    @property
    def elevations(self) -> tuple[tuple[float, float], ...] | None:
        return self.trackMap.elevations

    @property
    def sectors(self) -> tuple[int, int] | None:
        return self.trackMap.sectors

    @property
    def lastModified(self) -> float:
        return self.trackMap.lastModified


class NotesData:
    """Notes data"""

    __slots__ = (
        "currentIndex",
        "currentNote",
        "nextIndex",
        "nextNote",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        """Reset"""
        self.currentIndex: int = 0
        self.currentNote: Mapping[str, float | str] = EMPTY_DICT
        self.nextIndex: int = 0
        self.nextNote: Mapping[str, float | str] = EMPTY_DICT


class NotesInfo:
    """Notes output data"""

    __slots__ = (
        "out",
        "pit",
    )

    def __init__(self):
        self.out: NotesData = NotesData()
        self.pit: NotesData = NotesData()


class RelativeInfo:
    """Relative output data"""

    __slots__ = (
        "relativeAhead",
        "relativeBehind",
        "standings",
        "drawOrder",
        "relativeDeltaAhead",
        "relativeDeltaBehind",
    )

    def __init__(self):
        self.relativeAhead: list[tuple[float, int]] = [REL_TIME_DEFAULT]
        self.relativeBehind: list[tuple[float, int]] = [REL_TIME_DEFAULT]
        self.standings: list[int] = [-1]
        self.drawOrder: list = [0]
        self.relativeDeltaAhead: tuple[DeltaTimeInterval, ...] = tuple(
            DeltaTimeInterval() for _ in range(MAX_VEHICLES)
        )
        self.relativeDeltaBehind: tuple[DeltaTimeInterval, ...] = tuple(
            DeltaTimeInterval() for _ in range(MAX_VEHICLES)
        )


class SectorData:
    """Sector data set"""

    __slots__ = (
        "noDeltaSector",
        "noDeltaSectorPB",
        "sectorIndex",
        "recordedIndex",
        "sectorPrev",
        "sectorBestTB",
        "sectorBestPB",
        "deltaSectorBestPB",
        "deltaSectorBestTB",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        """Reset"""
        self.noDeltaSector: bool = True  # no theoretical best of last sector recorded (no gap to it)
        self.noDeltaSectorPB: bool = True  # no personal best lap sector of last sector recorded
        self.sectorIndex: int = -1
        # Sector index when time of sector before it was last recorded (equal to sectorIndex once
        # sector just finished is recorded: game may report its time after the sector index)
        self.recordedIndex: int = -1
        self.sectorPrev: list[float] = [MAX_SECONDS] * 3
        self.sectorBestTB: list[float] = [MAX_SECONDS] * 3
        self.sectorBestPB: list[float] = [MAX_SECONDS] * 3
        self.deltaSectorBestPB: list[float] = [0.0] * 3
        self.deltaSectorBestTB: list[float] = [0.0] * 3


class SectorsInfo:
    """Sectors output data"""

    __slots__ = (
        "allTimeBest",
        "sessionBest",
    )

    def __init__(self):
        self.allTimeBest: SectorData = SectorData()
        self.sessionBest: SectorData = SectorData()


class StatsInfo:
    """Stats output data"""

    __slots__ = (
        "metersDriven",
    )

    def __init__(self):
        self.metersDriven: float = 0.0


class ScoringSnapshot(NamedTuple):
    """Scoring data of every car read by vehicles module, one game scoring sample (relative module reads it
    instead of reading & decoding the same data again)

    Attributes:
        scoringTime: session time of scoring sample (session elapsed).
        rows: per car index: (in garage, in pit lane or garage, estimated time into lap, class name,
            overall place, best lap time, last lap time).
    """

    scoringTime: float
    rows: tuple[tuple[bool, bool, float, str, int, float, float], ...]


class VehiclesInfo:
    """Vehicles output data

    Attributes:
        dataSetVersion: changes only when vehicles module updated dataSet with new game data (overlays skip
            redraw while unchanged), -1 after reset.
        scoringSnapshot: scoring data of last low priority update (None until then, see ScoringSnapshot).
        leaderIndex: index of overall leader (place 1) in last scoring update, -1 if none (new session,
            no place 1 in scoring).
    """

    __slots__ = (
        "dataSet",
        "dataSetVersion",
        "scoringSnapshot",
        "leaderIndex",
        "playerIndex",
        "totalOutPits",
        "totalInPits",
        "totalStoppedPits",
        "totalPitRequests",
        "totalCompletedLaps",
        "totalVehicles",
        "nearestLine",
        "nearestTraffic",
        "nearestYellowAhead",
        "nearestYellowBehind",
        "nearestBlueClass",
        "nearestBlueGap",
        "leaderBestLapTime",
        "finishTimeOffset",
        "finishAsLap",
        "finishLapOffset",
        "finishLapOffsetLeader",
    )

    def __init__(self):
        self.dataSet: tuple[VehicleDataSet, ...] = tuple(
            VehicleDataSet() for _ in range(MAX_VEHICLES)
        )
        self.dataSetVersion: int = -1
        self.scoringSnapshot: ScoringSnapshot | None = None
        self.leaderIndex: int = -1
        self.playerIndex: int = -1
        self.totalOutPits: int = 0
        self.totalInPits: int = 0
        self.totalStoppedPits: int = 0
        self.totalPitRequests: int = 0
        self.totalCompletedLaps: int = 0
        self.totalVehicles: int = 0
        self.nearestLine: float = MAX_METERS
        self.nearestTraffic: float = MAX_SECONDS
        self.nearestYellowAhead: float = MAX_METERS
        self.nearestYellowBehind: float = -MAX_METERS
        self.nearestBlueClass: str = ""  # class of nearest car behind lapping player (any faster car outside race)
        self.nearestBlueGap: float = MAX_SECONDS  # time gap (seconds) of that same car
        self.leaderBestLapTime: float = MAX_SECONDS
        self.finishTimeOffset: float = 0.0
        self.finishAsLap: bool = True
        self.finishLapOffset: float = 0.0
        self.finishLapOffsetLeader: float = 0.0  # part of finishLapOffset from leader finishing first


class WheelsInfo:
    """Wheels output data"""

    __slots__ = (
        "lockingPercentFront",
        "lockingPercentRear",
        "lockingTime",
        "yawRate",
        "currentTreadDepth",
        "currentLapTreadWear",
        "lastLapTreadWear",
        "estimatedTreadWear",
        "estimatedValidTreadWear",
        "lockingTreadWear",
        "maxBrakeThickness",
        "failureBrakeThickness",
        "currentBrakeThickness",
        "currentlapBrakeWear",
        "lastLapBrakeWear",
        "estimatedBrakeWear",
        "estimatedValidBrakeWear",
        "currentSuspensionPosition",
        "staticSuspensionPosition",
        "minSuspensionPosition",
        "maxSuspensionPosition",
        "motionRatio",
        "wheelRadius",
        "wheelRadiusFront",
        "wheelRadiusRear",
        "minimumStaticWeight",
        "totalStaticWeight",
        "totalDynamicWeight",
        "frontWeightRatio",
        "leftWeightRatio",
        "crossWeightRatio",
        "slipRatio",
        "slipAngle",
        "averageFrontSlipAngle",
        "averageRearSlipAngle",
        "slipAngleDifference",
        "toeAngle",
        "averageFrontToeAngle",
        "averageRearToeAngle",
        "frontToeAngleDifference",
        "rearToeAngleDifference",
        "camberAngle",
        "frontCamberAngleDifference",
        "rearCamberAngleDifference",
    )

    def __init__(self):
        # Rotation
        self.lockingPercentFront: float = 0.0
        self.lockingPercentRear: float = 0.0
        self.lockingTime: list[float] = list(WHEELS_ZERO)
        self.yawRate: float = 0.0
        # Tyre wear
        self.currentTreadDepth: list[float] = list(WHEELS_ZERO)
        self.currentLapTreadWear: list[float] = list(WHEELS_ZERO)
        self.lastLapTreadWear: list[float] = list(WHEELS_ZERO)
        self.estimatedTreadWear: list[float] = list(WHEELS_ZERO)
        self.estimatedValidTreadWear: list[float] = list(WHEELS_ZERO)
        self.lockingTreadWear: list[float] = list(WHEELS_ZERO)
        # Brake wear
        self.maxBrakeThickness: list[float] = list(WHEELS_ZERO)
        self.failureBrakeThickness: list[float] = list(WHEELS_ZERO)
        self.currentBrakeThickness: list[float] = list(WHEELS_ZERO)
        self.currentlapBrakeWear: list[float] = list(WHEELS_ZERO)
        self.lastLapBrakeWear: list[float] = list(WHEELS_ZERO)
        self.estimatedBrakeWear: list[float] = list(WHEELS_ZERO)
        self.estimatedValidBrakeWear: list[float] = list(WHEELS_ZERO)
        # Suspension
        self.currentSuspensionPosition: list[float] = list(WHEELS_ZERO)
        self.staticSuspensionPosition: list[float] = list(WHEELS_ZERO)
        self.minSuspensionPosition: list[float] = list(WHEELS_ZERO)
        self.maxSuspensionPosition: list[float] = list(WHEELS_ZERO)
        self.motionRatio: list[float] = list(WHEELS_ZERO)
        self.wheelRadius: list[float] = list(WHEELS_ZERO)  # rolling radius (meters), 0 until learned
        # Measured tyre radius per axle (millimeters), 0 until learned or measurement disabled
        self.wheelRadiusFront: float = 0.0
        self.wheelRadiusRear: float = 0.0
        # Weight
        self.minimumStaticWeight: float = 0.0
        self.totalStaticWeight: float = 0.0
        self.totalDynamicWeight: float = 0.0
        self.frontWeightRatio: float = 0.0
        self.leftWeightRatio: float = 0.0
        self.crossWeightRatio: float = 0.0
        # Slip ratio
        self.slipRatio: list[float] = list(WHEELS_ZERO)
        # Slip angle
        self.slipAngle: list[float] = list(WHEELS_ZERO)
        self.averageFrontSlipAngle: float = 0.0
        self.averageRearSlipAngle: float = 0.0
        self.slipAngleDifference: float = 0.0
        # Toe angle
        self.toeAngle: list[float] = list(WHEELS_ZERO)
        self.averageFrontToeAngle: float = 0.0
        self.averageRearToeAngle: float = 0.0
        self.frontToeAngleDifference: float = 0.0
        self.rearToeAngleDifference: float = 0.0
        # Camber angle
        self.camberAngle: list[float] = list(WHEELS_ZERO)
        self.frontCamberAngleDifference: float = 0.0
        self.rearCamberAngleDifference: float = 0.0


class ModuleInfo:
    """Modules output data"""

    __slots__ = (
        "delta",
        "energy",
        "force",
        "fuel",
        "history",
        "hybrid",
        "mapping",
        "relative",
        "sectors",
        "stats",
        "pacenotes",
        "tracknotes",
        "vehicles",
        "wheels",
    )

    def __init__(self):
        self.delta = DeltaInfo()
        self.energy = FuelInfo()
        self.force = ForceInfo()
        self.fuel = FuelInfo()
        self.history = HistoryInfo()
        self.hybrid = HybridInfo()
        self.mapping = MappingInfo()
        self.relative = RelativeInfo()
        self.sectors = SectorsInfo()
        self.stats = StatsInfo()
        self.pacenotes = NotesInfo()
        self.tracknotes = NotesInfo()
        self.vehicles = VehiclesInfo()
        self.wheels = WheelsInfo()


minfo = ModuleInfo()
