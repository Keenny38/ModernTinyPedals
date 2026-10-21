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
Session debrief: what a driving stint gave, from files saved while driving (no game needed)

Built from the stint record of driver history (best lap, laps, distance, result), the stints driven before
on the same track & vehicle (personal best and best of previous stint), and the laps recorded during the
stint (telemetry folder: lap times, game sectors, fuel used). Corners to work on compare two recorded laps
like the Corners tab of the lap viewer: the best lap of the stint against the personal best lap when that
one is older and faster, else a typical lap of the stint against its best lap.

build_debrief reads lap infos only (first line of each lap file, fast). corner_tips loads two laps (a few
hundred ms): run it in background.
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterable, Sequence
from statistics import mean, pstdev
from typing import NamedTuple

from .driver_history import SessionRecord
from .telemetry_lap import LapFile, lap_files, lap_folder_name, lap_number_of, lap_timestamp_of, read_lap_info

STINT_MARGIN = 120  # seconds: laps saved this long before stint start or after its end are of the stint
PACE_WINDOW = 1.03  # valid laps within 103% of best lap count for pace & consistency (slow laps: traffic, spin)
MIN_PACE_LAPS = 2  # pace & consistency need this many laps
TIP_LIMIT = 3  # corners to work on


class DebriefLap(NamedTuple):
    """Lap recorded during stint"""

    path: str
    number: int
    time: float  # lap time (seconds)
    valid: bool
    sectors: tuple[float, ...] = ()  # game sector times (3), empty if unknown
    fuel: float = 0.0  # fuel used (liters), 0 if unknown
    vehicle: str = ""  # vehicle name of lap info


class CornerTip(NamedTuple):
    """Corner where the compared lap loses time: label ("T5" or official name), seconds lost, causes
    (kind, value) most telling first, see corner_analysis.CoachTip"""

    label: str  # translated ("V5" in French)
    loss: float
    causes: tuple[tuple[str, float], ...]
    apex: float = -1.0  # minimum speed point on reference lap (lap distance), -1 if unknown


class Debrief(NamedTuple):
    """Debrief of a stint (lap times in seconds, 0 when unknown)"""

    record: SessionRecord
    laps: tuple[DebriefLap, ...]
    best: float  # best valid lap of stint
    pace: float  # average of valid laps within PACE_WINDOW of best
    consistency: float  # standard deviation of those laps
    pace_laps: int  # number of those laps
    theoretical: float  # sum of best game sectors of valid laps
    previous_best: float  # personal best before stint (track & vehicle)
    previous_stint_best: float  # best lap of previous stint on track & vehicle
    fuel_per_lap: float  # average fuel used by valid laps (liters)
    best_path: str  # lap file of best lap, empty if not recorded
    reference_path: str  # lap compared with: older faster personal best lap, else best lap of stint
    compared_path: str  # lap compared against reference (corner tips), empty if no comparison
    reference_kind: str  # "personal_best" or "stint_best" (tips against which lap), empty if none

    @property
    def new_personal_best(self) -> bool:
        """Stint beat previous personal best (or first lap time ever)"""
        return self.best > 0 and (self.previous_best <= 0 or self.best < self.previous_best - 0.0005)

    @property
    def gain(self) -> float:
        """Best lap of stint minus personal best before it (negative: faster), 0 if unknown"""
        return self.best - self.previous_best if self.best > 0 and self.previous_best > 0 else 0.0


def finite(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value) if math.isfinite(value) else 0.0


def stint_folder(telemetry_path: str, record: SessionRecord) -> str:
    """Recorded laps folder of stint (track & game class), empty if class unknown (older records)"""
    if not record.vehicle_class or not telemetry_path:
        return ""
    return os.path.join(telemetry_path, lap_folder_name(f"{record.track} - {record.vehicle_class}"))


def stint_window(record: SessionRecord) -> tuple[float, float]:
    """Times (seconds since epoch) laps of stint are saved between"""
    start = record.time - max(record.seconds, 0.0) - STINT_MARGIN
    return start, record.time + STINT_MARGIN


def debrief_lap(lap: LapFile, info: dict) -> DebriefLap:
    sectors = info.get("sectors")
    if not (isinstance(sectors, list) and len(sectors) == 3 and all(finite(value) > 0 for value in sectors)):
        sectors = ()
    fuel = finite(info.get("fuel_start")) - finite(info.get("fuel_end"))
    vehicle = info.get("vehicle", "")
    return DebriefLap(
        path=lap.path, number=lap_number_of(lap.filename), time=lap.lap_time, valid=lap.valid,
        sectors=tuple(float(value) for value in sectors), fuel=fuel if fuel > 0 else 0.0,
        vehicle=vehicle if isinstance(vehicle, str) else "",
    )


def stint_laps(folder: str, record: SessionRecord, files: Sequence[LapFile] | None = None) -> list[DebriefLap]:
    """Laps recorded during stint, in driving order"""
    if not folder:
        return []
    start, end = stint_window(record)
    found = [lap for lap in (lap_files(folder) if files is None else files)
             if start <= lap_timestamp_of(lap.filename) <= end and lap.lap_time > 0]
    found.sort(key=lambda lap: (lap_timestamp_of(lap.filename), lap_number_of(lap.filename)))
    return [debrief_lap(lap, read_lap_info(lap.path)) for lap in found]


def pace_of(laps: Iterable[DebriefLap], best: float) -> tuple[float, float, int]:
    """Average & standard deviation of valid laps close to best, number of laps (zeros under MIN_PACE_LAPS)"""
    times = [lap.time for lap in laps if lap.valid and 0 < lap.time <= best * PACE_WINDOW]
    if best <= 0 or len(times) < MIN_PACE_LAPS:
        return 0.0, 0.0, len(times) if best > 0 else 0
    return mean(times), pstdev(times), len(times)


def theoretical_best(laps: Iterable[DebriefLap]) -> float:
    """Sum of best sector times of valid laps, 0 if no valid lap has sectors"""
    sectors = [lap.sectors for lap in laps if lap.valid and len(lap.sectors) == 3]
    if not sectors:
        return 0.0
    return sum(min(lap[index] for lap in sectors) for index in range(3))


def earlier_records(record: SessionRecord, records: Iterable[SessionRecord]) -> list[SessionRecord]:
    """Stints of same track & vehicle driven before record, oldest first"""
    return sorted((other for other in records if other.track == record.track and other.vehicle == record.vehicle
                   and other.time < record.time), key=lambda other: other.time)


def reference_lap(folder: str, laps: Sequence[DebriefLap], record: SessionRecord,
                  files: Sequence[LapFile] | None = None) -> str:
    """Fastest valid lap recorded before stint with same vehicle, empty if none faster than stint best"""
    if not folder:
        return ""
    start, _ = stint_window(record)
    vehicles = {lap.vehicle for lap in laps if lap.vehicle}
    stint_best = min((lap.time for lap in laps if lap.valid), default=0.0)
    older = sorted((lap for lap in (lap_files(folder) if files is None else files)
                    if lap.valid and lap.lap_time > 0 and lap_timestamp_of(lap.filename) < start),
                   key=lambda lap: lap.lap_time)
    for lap in older:
        if stint_best and lap.lap_time >= stint_best:
            return ""  # stint is faster than every older lap
        if not vehicles or read_lap_info(lap.path).get("vehicle", "") in vehicles:
            return lap.path
    return ""


def build_debrief(record: SessionRecord, records: Iterable[SessionRecord], telemetry_path: str,
                  personal_best: float = 0.0) -> Debrief:
    """Debrief of a stint record (lap infos read from telemetry folder)

    Args:
        personal_best: personal best of driver stats (this stint included), 0 if unknown: an older faster lap
            than history knows (records dropped over history limit, imported stats) still counts.
    """
    folder = stint_folder(telemetry_path, record)
    files = lap_files(folder) if folder else []
    laps = stint_laps(folder, record, files)
    valid = [lap for lap in laps if lap.valid]
    best = record.best if record.best > 0 else min((lap.time for lap in valid), default=0.0)
    pace, consistency, pace_laps = pace_of(laps, best)
    earlier = earlier_records(record, records)
    previous_best = min((other.best for other in earlier if other.best > 0), default=0.0)
    if 0 < personal_best < best - 0.0005 and (previous_best <= 0 or personal_best < previous_best):
        previous_best = personal_best  # faster lap than this stint, before it
    previous_stint_best = next((other.best for other in reversed(earlier) if other.best > 0), 0.0)
    fuels = [lap.fuel for lap in valid if lap.fuel > 0]
    best_lap = min(valid, key=lambda lap: lap.time, default=None)
    best_path = best_lap.path if best_lap is not None else ""
    reference_path = compared_path = kind = ""
    if best_lap is not None:
        reference_path = reference_lap(folder, laps, record, files)
        if reference_path:
            compared_path, kind = best_path, "personal_best"
        else:  # typical lap of stint against its best lap
            paced = [lap for lap in valid if lap is not best_lap and lap.time <= best * PACE_WINDOW]
            if len(paced) >= MIN_PACE_LAPS:
                typical = sorted(paced, key=lambda lap: lap.time)[len(paced) // 2]
                reference_path, compared_path, kind = best_path, typical.path, "stint_best"
    return Debrief(
        record=record, laps=tuple(laps), best=best, pace=pace, consistency=consistency, pace_laps=pace_laps,
        theoretical=theoretical_best(laps), previous_best=previous_best, previous_stint_best=previous_stint_best,
        fuel_per_lap=mean(fuels) if fuels else 0.0, best_path=best_path, reference_path=reference_path,
        compared_path=compared_path, reference_kind=kind,
    )


def corner_tips(reference_path: str, compared_path: str, track_name: str, limit: int = TIP_LIMIT) -> list[CornerTip]:
    """Corners where compared lap loses most time against reference lap (loads both laps: background)"""
    from ..i18n import trm
    from .corner_analysis import ResampledLap, coaching_tips, compare_corners
    from .corner_coach import corner_name
    from .lap_geometry import map_line
    from .telemetry_lap import distance_scale, load_lap
    from .track_corners import track_corners

    if not reference_path or not compared_path:
        return []
    try:
        reference, compared = load_lap(reference_path), load_lap(compared_path)
    except (OSError, ValueError, EOFError):
        return []
    if len(reference) < 2 or len(compared) < 2:
        return []
    rows = compare_corners(ResampledLap(reference), ResampledLap(compared, scale=distance_scale(reference, compared)))
    official: Sequence = ()
    numbered = True
    line = map_line(reference)
    if line is not None and track_name:
        official, numbered = track_corners(track_name, line.distances, line.xs, line.ys)
    tips = []
    for tip in coaching_tips(rows, limit):
        corner = rows[tip.row].corner
        label = corner_name(official, numbered, corner.start, corner.apex, corner.end) if official else ""
        tips.append(CornerTip(label or trm(f"T{corner.number}"), tip.loss, tuple(tip.causes), corner.apex))
    return tips
