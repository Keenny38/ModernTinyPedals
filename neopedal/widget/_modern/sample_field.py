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
Sample field of driver list widgets (Relative, Standings, Rivals): Overlay Options live preview

Fictional drivers racing in three classes, player third of the last one. Plain data (no Qt):
standings & relative lists are made as the relative module makes them from game data, with the
standings options of the previewed overlay.
"""

from __future__ import annotations

from collections.abc import Mapping
from itertools import chain
from operator import itemgetter
from typing import Any, NamedTuple

from ...module.module_relative import (
    calc_standings_index,
    class_order_rank,
    max_vehicles_in_class,
    min_top_vehicles_in_class,
    other_class_vehicles,
    standings_index_from_all_classes,
    standings_index_from_same_class,
)
from ...module_info import VehicleDataSet, set_class_bests
from ...penalty_info import NO_PENALTY, Penalty

LAP_TIME = 104.0  # estimated lap time (seconds), relative gaps wrap around it
PLAYER = 9
# Driver, vehicle, brand, class, best lap time, gap on track to player (seconds, ahead > 0),
# interval to car ahead in class (seconds)
FIELD = (
    ("M. Laurent", "Ferrari 499P", "Ferrari", "Hypercar", 103.42, 61.0, 0.0),
    ("J. Hartmann", "Porsche 963", "Porsche", "Hypercar", 103.61, 48.5, 1.284),
    ("K. Tanaka", "Toyota GR010", "Toyota", "Hypercar", 103.77, 7.9, 3.902),
    ("S. Dubois", "Alpine A424", "Alpine", "Hypercar", 103.95, -2.4, 0.615),
    ("T. Novak", "Oreca 07", "Oreca", "LMP2", 107.12, 30.2, 0.0),
    ("E. Walsh", "Oreca 07", "Oreca", "LMP2", 107.30, 18.6, 2.471),
    ("P. Moreau", "Oreca 07", "Oreca", "LMP2", 107.58, -21.7, 6.035),
    ("N. Fischer", "Ferrari 296 GT3", "Ferrari", "GT3", 116.84, 4.1, 0.0),
    ("C. Bennett", "Porsche 911 GT3 R", "Porsche", "GT3", 116.97, 1.3, 0.842),
    ("L. Garnier", "McLaren 720S GT3 Evo", "McLaren", "GT3", 117.08, 0.0, 1.517),  # player
    ("H. Lindqvist", "BMW M4 GT3", "BMW", "GT3", 117.21, -0.9, 0.733),
    ("G. Romano", "Aston Martin Vantage AMR", "Aston Martin", "GT3", 117.35, -5.6, 2.958),
    ("F. Martin", "Corvette Z06 GT3.R", "Corvette", "GT3", 117.52, -12.3, 4.120),
    ("B. Clarke", "Lamborghini Huracan GT3", "Lamborghini", "GT3", 117.70, -38.0, 9.306),
)
CLASS_LAPS_DOWN = {"Hypercar": 0, "LMP2": 1, "GT3": 2}  # laps behind overall leader
CLASS_GAP = {"LMP2": 38.62, "GT3": 51.17}  # class leader interval to last car of class ahead
IN_PIT = 6  # car in pit lane
PIT_REQUEST = 11  # car with pit stop requested
PENALTY = 10  # car with a stop & go to serve (ahead of player)
QUALIFY_SHIFT = (0, 1, -1, 0, 2, -1, -1, 0, 1, 2, -2, -1, 0, -1)  # qualify place - race place


class SampleField(NamedTuple):
    """Sample race: vehicle data & relative module outputs"""

    vehicles: tuple[VehicleDataSet, ...]
    player_index: int
    relative_ahead: list[tuple[float, int]]  # (gap, index), farthest first
    relative_behind: list[tuple[float, int]]  # (gap, index), nearest first
    classes: list[tuple[str, int, int, float, float]]  # (class, place, index, best lap, last lap), class sorted


def sample_field() -> SampleField:
    """Sample race in progress"""
    class_members: dict[str, list[int]] = {}
    for index, entry in enumerate(FIELD):
        class_members.setdefault(entry[3], []).append(index)
    vehicles = tuple(VehicleDataSet() for _ in FIELD)
    for index, (driver, vehicle, brand, vclass, best, _, interval) in enumerate(FIELD):
        veh = vehicles[index]
        members = class_members[vclass]
        place_in_class = members.index(index) + 1
        leader = members[0]
        veh.isPlayer = index == PLAYER
        veh.positionOverall = index + 1
        veh.positionInClass = place_in_class
        veh.qualifyOverall = max(index + 1 + QUALIFY_SHIFT[index], 1)
        veh.qualifyInClass = max(place_in_class + QUALIFY_SHIFT[index], 1)
        veh.driverName = driver
        veh.vehicleName = f"{vehicle} #{10 + index * 7}"
        veh.vehicleBrand = brand
        veh.vehicleClass = vclass
        veh.classLeaderIndex = leader
        veh.classAheadIndex = members[place_in_class - 2] if place_in_class > 1 else -1
        veh.classBehindIndex = members[place_in_class] if place_in_class < len(members) else -1
        veh.classBestLapTime = FIELD[leader][4]
        veh.bestLapTime = best
        veh.lastLapTime = best + 0.21 + (index * 7 % 5) * 0.09
        veh.isValidLap = index != 12
        veh.gapBehindNextInClass = interval
        veh.gapBehindLeaderInClass = sum(FIELD[member][6] for member in members[:place_in_class])
        veh.gapBehindNext = CLASS_GAP[vclass] if index == leader and vclass in CLASS_GAP else interval
        laps_down = CLASS_LAPS_DOWN[vclass]
        veh.gapBehindLeader = laps_down if laps_down else veh.gapBehindLeaderInClass
        veh.isLapped = -1 if vclass == "Hypercar" else 0
        veh.inPit = 1 if index == IN_PIT else 0
        veh.pitTimer.pitting = index == IN_PIT
        veh.pitTimer.elapsed = 21.4 if index == IN_PIT else 0.0
        veh.pitRequested = index == PIT_REQUEST
        veh.isClassFastestLastLap = index in (1, 5, 8)
        veh.numPitStops = -1 if index == PENALTY else 2 if index % 3 else 1
        veh.penalty = Penalty(1, "Stop/Go", 10) if index == PENALTY else NO_PENALTY
        compound = "Soft" if index % 4 == 1 else "Medium"
        veh.tireCompoundName = (compound, compound, "Medium", "Medium") if index == 4 else (compound,) * 4
        veh.vehicleIntegrity = 0.82 if index in (3, 12) else 1.0
        veh.incidents = (index * 5) % 9
        veh.trackLimitsPoints = (0.0, 1.25, 0.0, 2.5, 4.25)[index % 5]
        veh.energyRemaining = 0.28 + (index * 13 % 60) / 100
        veh.currentStintLaps = 6 + index % 7
        veh.estimatedStintLaps = 14 + index % 4
        veh.speedTrap.speed = (88.4 if vclass == "Hypercar" else 85.1 if vclass == "LMP2" else 76.3) + index % 4 * 0.4
        veh.licoTimer.elapsed = 1.6 + (index % 3) * 0.7 if vclass == "Hypercar" else 0.0
        for lap in range(5):
            veh.lapTimeHistory[lap] = best + 0.18 + ((index * 5 + lap * 3) ** 2 % 11) * 0.06
        veh.lapTimeHistory.best = best
        veh.lapTimeHistory.last = veh.lastLapTime
        veh.lapTimeHistory.average = best + 0.46
        set_sample_sectors(veh, index, best)
    ahead = []
    behind = []
    for index, entry in enumerate(FIELD):
        if index != PLAYER:
            gap = entry[5] % LAP_TIME
            ahead.append((gap, index))
            behind.append((gap - LAP_TIME, index))
    ahead.sort(reverse=True)
    behind.sort(reverse=True)
    classes = sorted((veh.vehicleClass, veh.positionOverall, index, veh.bestLapTime, veh.lastLapTime)
                     for index, veh in enumerate(vehicles))
    class_best_sectors(vehicles)
    return SampleField(vehicles, PLAYER, ahead, behind, classes)


SECTOR_SHARES = (0.33, 0.35, 0.32)  # sample lap split into sectors
SAMPLE_NOW = 3600.0  # session time of sample race (running lap times)
OUT_LAP = 13  # car on its out lap (last of GT3, away from player)


def set_sample_sectors(veh, index: int, best: float):
    """Sector times of sample car: last lap, sectors of lap being driven, personal bests; out lap"""
    sectors = veh.sectors
    last = veh.lastLapTime
    sectors.best = [best * share - (index % 3) * 0.02 for share in SECTOR_SHARES]
    # Last lap: some sectors are personal bests (green, purple when best of session), others slower (yellow)
    sectors.last = tuple(sectors.best[number] if (index + number) % 3 == 0 else last * share
                         for number, share in enumerate(SECTOR_SHARES))
    sectors.sector = (index + 1) % 3
    first = sectors.best[0] if index % 2 else sectors.best[0] + 0.15  # S1 being driven: personal best or slower
    sectors.current = (first if sectors.sector >= 1 else 0.0, sectors.best[1] + 0.2 if sectors.sector == 2 else 0.0)
    sectors.laps = 12
    sectors.last_kind = "OUT" if index == OUT_LAP else ""
    veh.lapStartTime = SAMPLE_NOW - sample_running(sectors, index == OUT_LAP or not veh.isValidLap)


def sample_running(sectors, lap_shown: bool) -> float:
    """Time into lap being driven of sample car: line just crossed in S1 (completed lap shown, out lap, invalid lap
    too), else completed sectors & half of sector being driven (running time)"""
    if sectors.sector == 0 or lap_shown:
        return 2.5
    return sum(sectors.current[:sectors.sector]) + sectors.best[sectors.sector] * 0.5


def class_best_sectors(vehicles) -> None:
    """Best sectors & best lap of each class told to its cars"""
    set_class_bests(vehicles)


def sample_standings(field: SampleField, setting: Mapping[str, Any]) -> list[int]:
    """Standings index list of sample field (-1: space between classes), as standings options ask"""
    min_top = min_top_vehicles_in_class(setting["minimum_top_vehicles"])
    player = field.vehicles[field.player_index]
    classes = list(field.classes)
    if setting["enable_single_class_exclusive_mode"]:
        return standings_index_from_same_class(
            min_top, classes, player.vehicleClass, player.positionInClass,
            max_vehicles_in_class(setting["maximum_vehicles_exclusive_mode"], min_top, 2))
    if setting["enable_multi_class_split_mode"]:
        return list(chain(*standings_index_from_all_classes(
            min_top, classes, player.vehicleClass, player.positionInClass,
            other_class_vehicles(setting["maximum_vehicles_per_split_others"]),
            max_vehicles_in_class(setting["maximum_vehicles_per_split_player"], min_top, 2),
            class_order_rank(setting.get("class_order", "")))))
    classes.sort(key=itemgetter(1))
    return calc_standings_index(
        min_top, max_vehicles_in_class(setting["maximum_vehicles_combined_mode"], min_top, 2),
        player.positionOverall, classes)
