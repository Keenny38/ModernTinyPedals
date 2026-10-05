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
Official circuit geometry from Le Mans Ultimate REST API: track center path & pit lane

Game gives each layout as points (x, elevation, z) every 5 meters, by type: 0 track center path
(the path game lateral position & track edges refer to), 1 pit lane, others grid & pit spots.
Recorded positions are (x, -z): same map coordinates. Layout of a track (several share a name) is
the one closest to recorded positions. Saved in telemetry folder: works afterwards without game.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
from collections.abc import Sequence
from contextlib import suppress
from itertools import pairwise
from typing import NamedTuple

logger = logging.getLogger(__name__)

GEOMETRY_FOLDER = ".track_maps"  # in telemetry folder (hidden: not a track)
CENTER_TYPE = 0
PIT_TYPE = 1
FIT_SAMPLES = 300  # recorded positions compared with each layout
FIT_MAX_ERROR = 15.0  # meters, median distance of recorded positions to center path: farther is another circuit
REQUEST_TIMEOUT = 3.0
VERSION_SUFFIX = re.compile(r"\s+v?\d+(?:\.\d+)*$")


class TrackGeometry(NamedTuple):
    """Official circuit geometry, map coordinates (x, -z) & elevation"""

    layout: str  # game layout (scene) name
    length: float  # meters, game layout length
    center: list[tuple[float, float, float]]  # track center path: x, y, elevation (closed loop, driving order)
    pit: list[tuple[float, float, float]]  # pit lane
    start: tuple[float, float] | None = None  # start line position (first recorded lap position)


def base_name(name: str) -> str:
    """Track name without version number, case ignored: "Circuit de la Sarthe 1.35" -> "circuit de la sarthe" """
    return VERSION_SUFFIX.sub("", str(name).strip()).casefold()


def parse_points(points: Sequence[dict]) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]]:
    """Track center path & pit lane from game trackmap points"""
    center: list[tuple[float, float, float]] = []
    pit: list[tuple[float, float, float]] = []
    for point in points:
        try:
            kind = int(point["type"])
            position = (float(point["x"]), -float(point["z"]), float(point.get("y", 0.0)))
        except (KeyError, TypeError, ValueError):
            continue
        if kind == CENTER_TYPE:
            center.append(position)
        elif kind == PIT_TYPE:
            pit.append(position)
    return center, pit


def path_length(points: Sequence[tuple[float, float, float]]) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in pairwise(points))


def fit_error(center: Sequence[tuple[float, float, float]], positions: Sequence[tuple[float, float]]) -> float:
    """Median distance of recorded positions to center path (segments): how well a layout matches laps"""
    if len(center) < 3 or not positions:
        return math.inf
    cell = 50.0
    grid: dict[tuple[int, int], list[int]] = {}  # segments by cell
    for index in range(len(center) - 1):
        (x0, y0, _), (x1, y1, _) = center[index], center[index + 1]
        for cx in range(int(min(x0, x1) // cell), int(max(x0, x1) // cell) + 1):
            for cy in range(int(min(y0, y1) // cell), int(max(y0, y1) // cell) + 1):
                grid.setdefault((cx, cy), []).append(index)
    step = max(len(positions) // FIT_SAMPLES, 1)
    gaps = []
    for x, y in positions[::step]:
        best = math.inf
        cx, cy = int(x // cell), int(y // cell)
        for nx in (cx - 1, cx, cx + 1):
            for ny in (cy - 1, cy, cy + 1):
                for index in grid.get((nx, ny), ()):
                    best = min(best, segment_distance(center[index], center[index + 1], x, y))
        gaps.append(best)
    gaps.sort()
    return gaps[len(gaps) // 2]


def segment_distance(first: tuple[float, float, float], second: tuple[float, float, float], x: float, y: float) -> float:
    dx, dy = second[0] - first[0], second[1] - first[1]
    length = dx * dx + dy * dy
    fraction = 0.0 if length <= 0 else max(0.0, min(1.0, ((x - first[0]) * dx + (y - first[1]) * dy) / length))
    return math.hypot(first[0] + dx * fraction - x, first[1] + dy * fraction - y)


# Cache
def cache_path(folder: str, track: str) -> str:
    return os.path.join(folder, GEOMETRY_FOLDER, f"{track}.json")


def load_geometry(folder: str, track: str) -> TrackGeometry | None:
    """Saved geometry of track, None if never fetched"""
    with suppress(OSError, ValueError, KeyError, TypeError, IndexError):
        with open(cache_path(folder, track), encoding="utf-8") as file:
            saved = json.load(file)
        center = [(float(x), float(y), float(z)) for x, y, z in saved["center"]]
        pit = [(float(x), float(y), float(z)) for x, y, z in saved.get("pit", [])]
        start = saved.get("start")
        if len(center) >= 3:
            return TrackGeometry(str(saved.get("layout", "")), float(saved.get("length", 0.0)), center, pit,
                                 (float(start[0]), float(start[1])) if start else None)
    return None


def save_geometry(folder: str, track: str, geometry: TrackGeometry):
    target = cache_path(folder, track)
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        temp = f"{target}.tmp"
        with open(temp, "w", encoding="utf-8") as file:
            json.dump({
                "layout": geometry.layout, "length": geometry.length,
                "center": [[round(value, 3) for value in point] for point in geometry.center],
                "pit": [[round(value, 3) for value in point] for point in geometry.pit],
                "start": [round(value, 3) for value in geometry.start] if geometry.start else None,
            }, file)
        os.replace(temp, target)
    except OSError as error:
        logger.warning("TRACK GEOMETRY: unable to save %s: %s", target, error)


# Game REST API
def rest_get(host: str, port: int, resource: str, timeout: float = REQUEST_TIMEOUT):
    """Json from game REST API, None if game not running or no answer"""
    from ..async_request import get_response, resolve_hostname, set_header_get

    try:
        address = resolve_hostname(host, port, timeout)
        raw = asyncio.run(get_response(set_header_get(resource, address), address, port, timeout))
        return json.loads(raw) if raw else None
    except (OSError, ValueError, RuntimeError, asyncio.TimeoutError):
        return None


def fetch_geometry(host: str, port: int, track: str, positions: Sequence[tuple[float, float]],
                   lap_length: float = 0.0, tracks: list | None = None) -> TrackGeometry | None:
    """Official geometry of layout matching track name & recorded positions, None if game not running or none

    tracks: layouts list already asked to game (else asked here).
    """
    if tracks is None:
        tracks = rest_get(host, port, "/rest/race/track")
    if not isinstance(tracks, list):
        return None
    wanted = base_name(track)
    candidates: dict[str, dict] = {}  # by layout: several events share a layout
    for item in tracks:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        names = {base_name(item.get("shortName", "")), base_name(item.get("name", "")),
                 base_name(item.get("displayProperties", {}).get("shortName", ""))}
        if wanted in names:
            candidates.setdefault(str(item.get("sceneDesc") or item["id"]), item)
    best: tuple[float, TrackGeometry] | None = None
    for layout, item in candidates.items():
        points = rest_get(host, port, f"/rest/race/track/{item['id']}/trackmap")
        if not isinstance(points, list):
            continue
        center, pit = parse_points(points)
        if len(center) < 3:
            continue
        error = fit_error(center, positions) if positions else 0.0
        length = path_length(center)
        if lap_length > 0 and length > 0:  # same circuit, other layout: length differs
            error += abs(length - lap_length) / lap_length * 50
        try:
            game_length = float(str(item.get("length", "0")).split()[0]) * 1000
        except ValueError:
            game_length = 0.0
        if best is None or error < best[0]:
            best = (error, TrackGeometry(layout, game_length or length, center, pit,
                                         tuple(positions[0]) if positions else None))  # type: ignore[arg-type]
    if best is None or (positions and best[0] > FIT_MAX_ERROR):
        return None
    return best[1]
