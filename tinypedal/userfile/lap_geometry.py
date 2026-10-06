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
Lap geometry without Qt: driving lines, placement across track, track limits, off track & track limits events

Pure functions on game positions (meters): run in a worker process by the lap viewer (heavy work never
holds the page thread), see track_limits_job & session_values. Drawing & colors are in ui/quick/lap_map.py.
"""

from __future__ import annotations

import bisect
import logging
import math
import os
import time
from array import array
from collections.abc import Sequence
from contextlib import suppress
from itertools import pairwise
from typing import NamedTuple

from .lap_cache import load_cached_lap, read_arrays_file, write_arrays_file
from .telemetry_lap import (
    LapData,
    interpolate,
    lap_files,
    lap_time_curve,
    length_ratio,
    official_sector_times,
    same_track_distance,
    sector_bounds,
)

logger = logging.getLogger(__name__)

LINE_SEARCH = 60.0  # meters of reference line searched around same distance for nearest point
SAME_DISTANCE = 2.0  # meters, distance this far back is a late game update (sample kept), farther a glitch
LIMITS_MIN_LAPS = 3  # laps with positions needed to guess track limits
LIMITS_MARGIN = 1.2  # meters, car half width around driven lines
LIMITS_MIN_WIDTH = 11.0  # meters, narrowest track width guessed
LIMITS_MAX_WIDTH = 20.0  # meters, widest track width guessed (run-offs, pit entry left out)
LIMITS_MAX_OFFSET = 25.0  # meters off base line: off track or pit lane, left out
LIMITS_SMOOTH = 15  # points of edge smoothing
GAME_OFF_TRACK = 6.0  # meters beyond game track edge: pit lane or far off track, sample left out of track edges
GAME_MIN_COVERAGE = 0.25  # share of track points with a game edge needed, else edges estimated from laps
GAME_LATERAL_SIGN = 1.0  # game lateral position toward map left is positive (checked on recorded laps: slope +0.98)
SIGN_MIN_SPREAD = 50.0  # square meters of game lateral spread at same base points needed to find its sign from laps
SIGN_SMOOTHER = 0.5  # else game center path this much smoother along laps with one sign: that sign
LIMITS_VERSION = 2  # track limits algorithm: saved track limits computed again if changed
WIDTH_DEFAULT = 12.0  # meters, track width where no edge is known on either side
CAR_HALF_WIDTH = 1.0  # meters, car center this far beyond track edge: four wheels out (track limits)
OFF_ROAD_SURFACES = (2, 3, 4)  # game wheel surface: grass, dirt, gravel
OFF_TRACK_WHEELS = 2  # wheels on grass / dirt / gravel: off track
EVENT_SAMPLES = 3  # consecutive samples needed for an off-track or track limits event (60 ms)
EVENT_GAP = 30.0  # meters, events closer than this to the previous one are the same event


class MapLine(NamedTuple):
    """Driving line of a lap: positions by increasing distance"""

    distances: list[float]
    xs: list[float]
    ys: list[float]


def map_line(lap: LapData) -> MapLine | None:
    """Every recorded position in driving order, distances strictly increasing (bisect & interpolate)

    A sample whose lap distance did not move forward (game distance updated late) is kept, just after
    the previous one: no position the car went through is left out. Only distance going back (lap
    distance reset glitch) drops a sample.
    """
    found = map_line_indexes(lap)
    return found[0] if found is not None else None


def map_line_indexes(lap: LapData) -> tuple[MapLine, list[int]] | None:
    """Driving line & index in lap columns of each of its points"""
    xs_column, ys_column = lap.columns.get("pos_x"), lap.columns.get("pos_y")
    if not xs_column or not ys_column:
        return None
    distances: list[float] = []
    xs: list[float] = []
    ys: list[float] = []
    indexes: list[int] = []
    last = -math.inf
    for index, (distance, x, y) in enumerate(zip(lap.distance, xs_column, ys_column)):
        if not x and not y:
            continue
        if distance <= last:
            if last - distance > SAME_DISTANCE:  # distance went back: glitch
                continue
            distance = last + 1e-3
        distances.append(distance)
        xs.append(x)
        ys.append(y)
        indexes.append(index)
        last = distance
    if len(distances) < 2:
        return None
    return MapLine(distances, xs, ys), indexes


def lateral_offsets(reference: MapLine, compared: MapLine) -> tuple[list[float], list[int]]:
    """Signed distance of each compared point to reference line (left positive) & nearest reference index

    Nearest point found by walking from the previous one (both lines go the same way): one pass,
    a few steps per point, instead of searching around each point.
    """
    count = len(reference.xs)
    if count < 3 or not compared.xs:
        return [], []
    rx, ry = reference.xs, reference.ys
    offsets: list[float] = []
    indexes: list[int] = []
    nearest = -1
    for distance, x, y in zip(compared.distances, compared.xs, compared.ys):
        if nearest < 0 or abs(reference.distances[nearest] - distance) > LINE_SEARCH:  # start or lost: by distance
            nearest = min(max(bisect.bisect_left(reference.distances, distance), 1), count - 2)
            low = max(bisect.bisect_left(reference.distances, distance - LINE_SEARCH), 1)
            high = min(bisect.bisect_right(reference.distances, distance + LINE_SEARCH), count - 1)
            if low < high:
                nearest = min(range(low, high), key=lambda index: (rx[index] - x) ** 2 + (ry[index] - y) ** 2)
        gap = (rx[nearest] - x) ** 2 + (ry[nearest] - y) ** 2
        while True:  # walk to nearest point
            moved = False
            for step in (1, -1):
                index = nearest + step
                if 1 <= index <= count - 2:
                    candidate = (rx[index] - x) ** 2 + (ry[index] - y) ** 2
                    if candidate < gap:
                        nearest, gap, moved = index, candidate, True
                        break
            if not moved:
                break
        nearest = min(max(nearest, 1), count - 2)
        hx, hy = rx[nearest + 1] - rx[nearest - 1], ry[nearest + 1] - ry[nearest - 1]
        length = math.hypot(hx, hy) or 1.0
        offsets.append((hx * (y - ry[nearest]) - hy * (x - rx[nearest])) / length)
        indexes.append(nearest)
    return offsets, indexes


class TrackLimits(NamedTuple):
    """Approximate track edges along a base driving line (same point count, game coordinates)"""

    left: MapLine
    right: MapLine


class LapOffsets(NamedTuple):
    """Lap placement around base line: offset (left positive) & nearest base point of each lap line point,
    with game lateral position & track edge at each point if recorded (empty otherwise)"""

    sides: list[float]
    indexes: list[int]
    laterals: list[float]
    edges: list[float]


def track_limits(base: MapLine, others: Sequence[MapLine]) -> TrackLimits | None:
    """Track edges from where laps drove around base line (laps spread + margin, at least LIMITS_MIN_WIDTH wide)"""
    return limits_from_offsets(base, [LapOffsets(*lateral_offsets(base, line), [], []) for line in others])


def limits_from_offsets(base: MapLine, laps: Sequence[LapOffsets], base_included: bool = True) -> TrackLimits | None:
    """Track edges from laps spread around base line (base line is a lap itself unless base_included is False)

    Each lap point counts at its nearest base point; outer 5% on each side left out (off track moments).
    """
    count = len(base.xs)
    if count < 10 or len(laps) < LIMITS_MIN_LAPS - (1 if base_included else 0):
        return None
    spread: list[list[float]] = [[0.0] if base_included else [] for _ in range(count)]
    for lap in laps:
        for side, index in zip(lap.sides, lap.indexes):
            if abs(side) < LIMITS_MAX_OFFSET:
                spread[index].append(side)
    lefts: list[float | None] = []
    rights: list[float | None] = []
    for values in spread:
        if not values:
            lefts.append(None)
            rights.append(None)
            continue
        values.sort()
        trim = max(int(len(values) * 0.05), 1) if len(values) > 5 else 0
        low, high = values[trim], values[len(values) - 1 - trim]
        left, right = high + LIMITS_MARGIN, low - LIMITS_MARGIN
        if left - right > LIMITS_MAX_WIDTH:  # one lap far off: kept around base line
            left, right = min(left, LIMITS_MAX_WIDTH / 2), max(right, -LIMITS_MAX_WIDTH / 2)
        if left - right < LIMITS_MIN_WIDTH:  # laps all on the same line here: assumed centered on them
            middle = (left + right) / 2
            left, right = middle + LIMITS_MIN_WIDTH / 2, middle - LIMITS_MIN_WIDTH / 2
        lefts.append(left)
        rights.append(right)
    return limits_at(base, _smooth(_filled(lefts, LIMITS_MIN_WIDTH / 2), LIMITS_SMOOTH),
                     _smooth(_filled(rights, -LIMITS_MIN_WIDTH / 2), LIMITS_SMOOTH))


def limits_at(base: MapLine, lefts: Sequence[float], rights: Sequence[float]) -> TrackLimits:
    """Track edge lines from left & right offsets at each base point"""
    normals = [_normal(base, index) for index in range(len(base.xs))]
    return TrackLimits(
        MapLine(list(base.distances), [x + nx * off for x, (nx, _), off in zip(base.xs, normals, lefts)],
                [y + ny * off for y, (_, ny), off in zip(base.ys, normals, lefts)]),
        MapLine(list(base.distances), [x + nx * off for x, (nx, _), off in zip(base.xs, normals, rights)],
                [y + ny * off for y, (_, ny), off in zip(base.ys, normals, rights)]),
    )


def game_limits(base: MapLine, laps: Sequence[tuple[MapLine, list[float], list[float]]],
                fallback: TrackLimits | None = None) -> TrackLimits | None:
    """Track edges from game data of lap lines (see game_limits_from_offsets)"""
    return game_limits_from_offsets(base, [
        LapOffsets(*lateral_offsets(base, line), laterals, edges) for line, laterals, edges in laps], fallback)


def _game_sample_kept(side: float, lateral: float, edge: float) -> bool:
    """Game sample places track edges: edge known, car not far beyond it (pit lane, big off), near base line"""
    return abs(edge) >= 1.0 and abs(lateral) <= abs(edge) + GAME_OFF_TRACK and abs(side) <= LIMITS_MAX_OFFSET


def lateral_sign(laps: Sequence[LapOffsets], count: int) -> float:
    """Which way game lateral position goes on map: 1 toward left (like base line offsets), -1 toward right

    Found once over all laps: at a same base point, laps lie apart across track by as much as their game lateral
    positions differ (slope of offsets over lateral positions is +1 or -1). Too few laps or too close together:
    sign keeping game center path (offset minus lateral position) far smoother along laps if one does (car
    crossing the track away from base line), else game convention (laps following the base line tell nothing).
    """
    sums = [[0, 0.0, 0.0, 0.0, 0.0] for _ in range(count)]  # samples, offsets, laterals, products, squares
    variations = {1.0: 0.0, -1.0: 0.0}  # center path change along laps with each sign
    for lap in laps:
        previous: tuple[float, float] | None = None
        for side, lateral, edge, index in zip(lap.sides, lap.laterals, lap.edges, lap.indexes):
            if not _game_sample_kept(side, lateral, edge):
                previous = None
                continue
            found = sums[index]
            found[0] += 1
            found[1] += side
            found[2] += lateral
            found[3] += side * lateral
            found[4] += lateral * lateral
            if previous is not None:
                for sign in variations:
                    variations[sign] += abs(side - sign * lateral - previous[0] + sign * previous[1])
            previous = side, lateral
    covariance = spread = 0.0
    for samples, offsets, laterals, products, squares in sums:
        if samples > 1:
            covariance += products - offsets * laterals / samples
            spread += squares - laterals * laterals / samples
    if spread >= SIGN_MIN_SPREAD and abs(covariance / spread) >= 0.5:
        return math.copysign(1.0, covariance)
    smoother = min(variations, key=lambda sign: variations[sign])
    if variations[smoother] < SIGN_SMOOTHER * variations[-smoother]:
        return smoother
    return GAME_LATERAL_SIGN


def game_limits_from_offsets(base: MapLine, laps: Sequence[LapOffsets],
                             fallback: TrackLimits | None = None) -> TrackLimits | None:
    """Track edges from game data: each lap line with game lateral position & track edge at each point

    Game gives where the car is from its own track center path (not the official circuit path, a driving line)
    and how far the track edge is on that side: every sample places the game center path (offset minus lateral
    position, sign found once over all laps) & the edge on the car side. Each edge is the center path plus the
    edge distances seen on that side, else on the other side (track taken as symmetric there). Samples far beyond
    the edge (pit lane, big off) are left out. Where no sample, fallback edges (estimated from laps) are used if
    given. None if game data covers too little of the track and no fallback.
    """
    count = len(base.xs)
    laps = [lap for lap in laps if lap.edges and any(lap.edges)]
    if not laps:
        return None
    sign = lateral_sign(laps, count)
    centers: list[list[float]] = [[] for _ in range(count)]
    lefts: list[list[float]] = [[] for _ in range(count)]  # edge distances seen left of game center path
    rights: list[list[float]] = [[] for _ in range(count)]
    for lap in laps:
        for side, lateral, edge, index in zip(lap.sides, lap.laterals, lap.edges, lap.indexes):
            if not _game_sample_kept(side, lateral, edge):
                continue
            centers[index].append(side - sign * lateral)
            (lefts if sign * (lateral or edge) > 0 else rights)[index].append(abs(edge))  # edge on car side

    def median(values: list[float]) -> float | None:
        return sorted(values)[len(values) // 2] if values else None

    seen = sum(1 for values in centers if values)
    if seen < count * GAME_MIN_COVERAGE and fallback is None:
        return None
    fallback_left, fallback_right = edge_offsets(base, fallback) if fallback is not None else ([], [])
    left_values: list[float | None] = []
    right_values: list[float | None] = []
    for index in range(count):
        center = median(centers[index])
        left_half, right_half = median(lefts[index] or rights[index]), median(rights[index] or lefts[index])
        if center is not None and left_half is not None and right_half is not None:
            left_values.append(center + left_half)
            right_values.append(center - right_half)
        elif fallback is not None:
            left_values.append(fallback_left[index])
            right_values.append(fallback_right[index])
        else:
            left_values.append(None)
            right_values.append(None)
    left = _smooth(_filled(left_values, WIDTH_DEFAULT / 2), LIMITS_SMOOTH)
    right = _smooth(_filled(right_values, -WIDTH_DEFAULT / 2), LIMITS_SMOOTH)
    return limits_at(base, left, right)


def _filled(values: Sequence[float | None], default: float) -> list[float]:
    """Unknown values linearly interpolated between known ones (held at ends), default if none known"""
    known = [index for index, value in enumerate(values) if value is not None]
    if not known:
        return [default] * len(values)
    result = []
    position = 0
    for index in range(len(values)):
        while position + 1 < len(known) and known[position + 1] <= index:
            position += 1
        first = known[position]
        following = known[position + 1] if position + 1 < len(known) else first
        first_value = values[first]
        assert first_value is not None
        if first >= index or following == first:
            result.append(first_value)
        else:
            following_value = values[following]
            assert following_value is not None
            result.append(first_value + (following_value - first_value) * (index - first) / (following - first))
    return result


def edge_offsets(base: MapLine, limits: TrackLimits) -> tuple[list[float], list[float]]:
    """Left & right track edge offsets at each base line point (left positive)"""
    count = len(base.xs)
    sides = []
    for edge in (limits.left, limits.right):
        offsets, indexes = lateral_offsets(base, edge)
        values: list[float | None] = [None] * count
        for offset, index in zip(offsets, indexes):
            values[index] = offset
        sides.append(_filled(values, 0.0))
    return sides[0], sides[1]


def placement(offset: float, left: float, right: float) -> tuple[float, float, float]:
    """Car across track: room to left edge, to right edge (meters, negative beyond), percent (-100 right edge,
    0 track middle, 100 left edge)"""
    middle, half = (left + right) / 2, max((left - right) / 2, 0.5)
    return left - offset, offset - right, (offset - middle) / half * 100


def track_events(distances: Sequence[float], beyond: Sequence[bool]) -> list[float]:
    """Distances where a condition starts holding for EVENT_SAMPLES samples or more, one per episode"""
    events: list[float] = []
    run = 0
    for index, out in enumerate(beyond):
        run = run + 1 if out else 0
        if run == EVENT_SAMPLES:
            start = distances[index - EVENT_SAMPLES + 1]
            if not events or start - events[-1] > EVENT_GAP:
                events.append(start)
    return events


def off_track_events(lap: LapData) -> list[float]:
    """Distances where 2 wheels or more go on grass, dirt or gravel (game wheel surface), empty if not recorded"""
    surfaces = [lap.columns.get(f"surface_{wheel}") for wheel in ("fl", "fr", "rl", "rr")]
    if not all(surfaces):
        return []
    return track_events(lap.distance, [
        sum(int(value) in OFF_ROAD_SURFACES for value in wheels) >= OFF_TRACK_WHEELS
        for wheels in zip(*surfaces)  # type: ignore[arg-type]
    ])


def limits_events(lap: LapData) -> list[float]:
    """Distances where car goes beyond game track edge (four wheels out), empty if not recorded"""
    laterals, edges = lap.columns.get("path_lateral"), lap.columns.get("track_edge")
    if not laterals or not edges or not any(edges):
        return []
    return track_events(lap.distance, [
        abs(edge) >= 1.0 and abs(lateral) - abs(edge) > CAR_HALF_WIDTH for lateral, edge in zip(laterals, edges)
    ])


def _normal(line: MapLine, index: int) -> tuple[float, float]:
    """Unit left normal of line at point"""
    before, after = max(index - 1, 0), min(index + 1, len(line.xs) - 1)
    hx, hy = line.xs[after] - line.xs[before], line.ys[after] - line.ys[before]
    length = math.hypot(hx, hy) or 1.0
    return -hy / length, hx / length


def _smooth(values: list[float], points: int) -> list[float]:
    """Centered moving average"""
    half = points // 2
    count = len(values)
    sums = [0.0]
    for value in values:
        sums.append(sums[-1] + value)
    return [(sums[min(index + half + 1, count)] - sums[max(index - half, 0)])
            / (min(index + half + 1, count) - max(index - half, 0)) for index in range(count)]


# Track limits job: placement of each clean lap around base line (saved per lap), edges from all of them
LIMITS_PARTS_VERSION = 2  # per lap track limits data format: saved parts computed again if changed
YIELD_EVERY = 0.004  # seconds of work between short pauses in threads (page thread gets the interpreter lock)


class Yielder:
    """Short pause now & then in long thread loops: page thread waits less for the interpreter lock"""

    def __init__(self, interval: float = YIELD_EVERY):
        self.interval = interval
        self.last = time.perf_counter()

    def __call__(self):
        now = time.perf_counter()
        if now - self.last >= self.interval:
            time.sleep(0.001)
            self.last = time.perf_counter()


def median_bounds(bounds: list[list[float]]) -> list[float]:
    """Sector 2 & 3 start distances: median over laps (one lap off does not move them)"""
    bounds = [found for found in bounds if len(found) == 2]
    if not bounds:
        return []
    middle = len(bounds) // 2
    return [sorted(values)[middle] if len(bounds) % 2 else sum(sorted(values)[middle - 1:middle + 1]) / 2
            for values in zip(*bounds)]


def limits_part(folder: str, parts_folder: str, path: str, base: MapLine,
                base_key: str) -> tuple[LapOffsets, list[float]] | None:
    """Placement of lap around base line & its sector bounds, from saved part if lap & base did not change"""
    target = os.path.join(parts_folder, os.path.basename(path) + ".bin")
    try:
        stat = os.stat(path)
    except OSError:
        return None
    stamp = (stat.st_size, stat.st_mtime_ns)
    saved_part = read_arrays_file(target)  # plain data (older pickled parts ignored & computed again)
    if saved_part is not None:
        values, saved = saved_part
        sectors = values.get("sectors")
        if (values.get("version") == LIMITS_PARTS_VERSION and values.get("base") == base_key
                and values.get("stamp") == list(stamp) and isinstance(sectors, list)
                and all(isinstance(value, (int, float)) for value in sectors)
                and all(name in saved for name in ("sides", "indexes", "laterals", "edges"))):
            return (LapOffsets(saved["sides"].tolist(), saved["indexes"].tolist(),
                               saved["laterals"].tolist(), saved["edges"].tolist()), [float(value) for value in sectors])
    try:
        lap = load_cached_lap(folder, path)
    except (OSError, ValueError):
        return None
    sectors = sector_bounds(lap) if official_sector_times(lap) else []
    found = map_line_indexes(lap)
    if found is None:
        offsets = LapOffsets([], [], [], [])
    else:
        line, indexes = found
        sides, nearest = lateral_offsets(base, line)
        laterals, edges = lap.columns.get("path_lateral"), lap.columns.get("track_edge")
        if laterals and edges and any(edges):
            offsets = LapOffsets(sides, nearest, [laterals[index] for index in indexes],
                                 [edges[index] for index in indexes])
        else:
            offsets = LapOffsets(sides, nearest, [], [])
    if base_key != "lap":  # placement around a lap line changes with best lap: not saved
        try:
            os.makedirs(parts_folder, exist_ok=True)
            write_arrays_file(target, {"version": LIMITS_PARTS_VERSION, "base": base_key, "stamp": list(stamp),
                                       "sectors": sectors},
                              {"sides": array("f", offsets.sides), "indexes": array("i", offsets.indexes),
                               "laterals": array("f", offsets.laterals), "edges": array("f", offsets.edges)})
        except (OSError, OverflowError, ValueError) as error:
            logger.debug("LAP GEOMETRY: unable to save track limits part %s: %s", target, error)
    return offsets, sectors


def prune_limits_parts(parts_folder: str, track_folder: str) -> int:
    """Remove saved lap placements whose lap file no longer exists (recorder removes oldest laps), returns count"""
    try:
        names = os.listdir(parts_folder)
    except OSError:
        return 0
    laps = {lap.filename for lap in lap_files(track_folder)}
    removed = 0
    for name in names:
        if name.endswith(".bin") and name[:-4] in laps:
            continue
        with suppress(OSError):
            os.remove(os.path.join(parts_folder, name))
            removed += 1
    return removed


def track_limits_job(folder: str, parts_folder: str, track_folder: str, paths: list[str],
                     official: MapLine | None, base_key: str) -> dict:
    """Track limits of track from clean laps (paths, best lap first): limits, source & sector bounds, file names
    of unreadable laps if any ("unreadable": result not to be kept, see check_limits_job)

    Placement around official circuit path (game driving line, not track center) if known, else around best
    readable lap line. Saved placements of laps no longer recorded are removed.
    """
    result: dict = {}
    unreadable: list[str] = []
    prune_limits_parts(parts_folder, track_folder)
    base = official
    base_path = ""
    if base is None:  # no official circuit: placement around best lap line
        for lap_path in paths:
            try:
                base = map_line(load_cached_lap(folder, lap_path))
            except (OSError, ValueError) as error:
                logger.warning("LAP GEOMETRY: unable to read %s: %s", lap_path, error)
                unreadable.append(os.path.basename(lap_path))
                continue
            if base is not None:
                base_path = lap_path
                break
        if base is None:
            if unreadable:
                result["unreadable"] = unreadable
            return result
    parts = []
    bounds = []
    for lap_path in paths:
        part = limits_part(folder, parts_folder, lap_path, base, base_key)
        if part is None:
            if os.path.exists(lap_path) and os.path.basename(lap_path) not in unreadable:
                unreadable.append(os.path.basename(lap_path))
            continue
        offsets, sectors = part
        if sectors:
            bounds.append(sectors)
        if official is not None or lap_path != base_path:  # base lap itself not counted twice
            parts.append(offsets)
    if unreadable:
        result["unreadable"] = unreadable
    result["sectors"] = median_bounds(bounds)
    estimated = limits_from_offsets(base, parts, base_included=official is None)
    game = [part for part in parts if part.edges and any(part.edges)]
    limits = game_limits_from_offsets(base, game, estimated) if game else None
    result["source"] = "game" if limits is not None else "estimated"
    result["limits"] = limits if limits is not None else estimated
    return result


def mini_sector_times(bounds: Sequence[float], distances: Sequence[float], times: Sequence[float]) -> list[float]:
    """Time taken in each mini-sector (lap distances & lap times, same distance scale as bounds)"""
    if len(distances) < 2:
        return []
    distances, times = list(distances), list(times)  # copied once, not for each bound
    at = [interpolate(distances, times, bound) for bound in bounds]
    return [second - first for first, second in pairwise(at)]


def mini_sector_spread(times_by_lap: Sequence[Sequence[float]], minimum: int = 3) -> list[float]:
    """Standard deviation of each mini-sector time over laps (consistency), -1 where under minimum laps have a time"""
    count = max((len(times) for times in times_by_lap), default=0)
    spreads = []
    for index in range(count):
        values = [times[index] for times in times_by_lap if index < len(times) and times[index] > 0]
        if len(values) < minimum:
            spreads.append(-1.0)
            continue
        mean = sum(values) / len(values)
        spreads.append(math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1)))
    return spreads


def mini_sector_job(folder: str, paths: list[str], bounds: list[float], reference_length: float,
                    reference_info: dict | None = None) -> dict[str, list[float]]:
    """Time of each lap in each mini-sector: lap path: times, laps without lap time or unreadable left out

    Args:
        bounds: reference lap distances.
        reference_length: reference lap end distance (see TraceData.lap_end): lap distances scaled to it like
            distance_scale.
        reference_info: reference lap info, laps recorded on the same track length never scaled.
    """
    found = {}
    for path in paths:
        try:
            lap = load_cached_lap(folder, path)
        except (OSError, ValueError):
            continue
        distances, times = lap_time_curve(lap)
        if len(distances) < 2:
            continue
        if not same_track_distance(reference_info or {}, lap.meta):
            ratio = length_ratio(reference_length, distances[-1])  # lap end distance (see lap_end_distance)
            if ratio != 1.0:
                distances = [distance * ratio for distance in distances]
        found[path] = mini_sector_times(bounds, distances, times)
    return found


def session_values(folder: str, todo: list[tuple[str, float]]) -> dict[str, tuple[float, dict]]:
    """Off track & track limits count, tyre wear used of session laps (path, file time): path: (file time, values)"""
    found = {}
    for path, mtime in todo:
        try:
            lap = load_cached_lap(folder, path)
        except (OSError, ValueError):
            continue
        values: dict = {"offtrack": len(off_track_events(lap)) if "surface_fl" in lap.columns else -1,
                        "limits": len(limits_events(lap)) if any(lap.columns.get("track_edge") or ()) else -1}
        wears = [lap.columns.get(f"tyre_wear_{wheel}") or [] for wheel in ("fl", "fr", "rl", "rr")]
        if all(wears) and any(wears[0]) and all(column[0] >= column[-1] for column in wears):  # else tyres changed
            values["wear"] = sum(column[0] - column[-1] for column in wears) / 4
        found[path] = (mtime, values)
    return found
