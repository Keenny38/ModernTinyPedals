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
Whether an imported lap was driven on the circuit of another lap, from lap telemetry

Laps recorded by the app tell their circuit (game track name & track length, see same_circuit). An imported log
measures driven distance (length up to 10% off) and names its venue its own way: a lap of another circuit (or
another layout of the same venue) of about the same length passes those checks. Its telemetry tells more:

- World positions of both laps: driven line of compared lap laid over driven line of reference lap (best rotation
  & move, mirrored or not: logger coordinates may differ from game ones). Same circuit: every point on the other
  line. Another circuit or layout: a long stretch away from it (another corner, a chicane missing).
- Without positions: speed trace along distance (braking zones at the same places on the same circuit, see
  speed_correlation), only trusted when clearly low.
- Venue & track names: only when they confidently match or differ, never alone (names formatted differently).
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence

from .lap_offset import has_positions, is_recorded, positions_on_grid, speed_correlation
from .telemetry_lap import LapData, distance_scale, lap_end_distance, lap_length

SHAPE_POINTS = 400  # driven line points compared (along lap distance)
SHAPE_SHIFT = 0.1  # lap share, distance zero of compared lap searched this far from reference one
LINE_STEP = 2.0  # meters between line points (distance to line)
LINE_CELL = 50.0  # meters, grid cell of line points (nearest point search)
FIT_ROUNDS = 4  # rounds of line fitting on nearest line points
OFF_LINE = 30.0  # meters, point further from the other line is off it (another corner)
OFF_STRETCH = 100.0  # meters, longest stretch off the other line at most this long (or OFF_STRETCH_SHARE of lap)
OFF_STRETCH_SHARE = 0.03
OFF_SHARE = 0.1  # share of points off the other line at most
SPEED_OTHER = 0.3  # speed correlation under it: another circuit (unless names confidently match)
SPEED_UNSURE = 0.6  # speed correlation under it: another circuit if names confidently differ
NAME_FILLERS = frozenset((
    "circuit", "circuito", "circuits", "autodromo", "autodrome", "raceway", "speedway", "motorsport", "motorsports",
    "international", "internacional", "internazionale", "nazionale", "park", "track", "race", "racing", "ring",
    "the", "of", "de", "del", "della", "di", "do", "da", "des", "du", "la", "le", "les", "el", "los", "das", "der",
    "die", "and", "et", "y",
))


def name_tokens(name: str) -> list[str]:
    """Words of a track name telling it apart: accents & case ignored, generic words (circuit, raceway) dropped"""
    plain = unicodedata.normalize("NFKD", name)
    plain = "".join(char for char in plain if not unicodedata.combining(char)).casefold()
    return [token for token in re.findall(r"[a-z0-9]+", plain) if token not in NAME_FILLERS]


def names_match(first: str, second: str) -> bool | None:
    """Whether 2 track names confidently name the same circuit (True), another one (False), None if unsure

    Same: same words (formatting, accents, generic words aside). Another: no word in common, not even inside a
    word ("Spa" & "Spafrancorchamps"). Anything else (layout names, abbreviations) unsure.
    """
    tokens = name_tokens(first), name_tokens(second)
    if not tokens[0] or not tokens[1]:
        return None
    joined = "".join(tokens[0]), "".join(tokens[1])
    if set(tokens[0]) == set(tokens[1]) or joined[0] == joined[1]:
        return True
    if set(tokens[0]) & set(tokens[1]):
        return None
    for token in tokens[0]:
        if len(token) >= 3 and token in joined[1]:
            return None
    for token in tokens[1]:
        if len(token) >= 3 and token in joined[0]:
            return None
    return False


def line_points(lap: LapData, count: int) -> list[complex]:
    """World positions (x + z j) at count equal steps of lap distance from lap start to lap end (samples without a
    finite position left out, see has_positions)"""
    end = lap_end_distance(lap)
    grid = [index * end / count for index in range(count)]
    xs, zs = positions_on_grid(lap, grid)
    return [complex(x, z) for x, z in zip(xs, zs)]


def directions(points: Sequence[complex]) -> list[complex]:
    """Unit heading at each point of a closed line (0 where not moving)"""
    count = len(points)
    result = []
    for index in range(count):
        step = points[(index + 2) % count] - points[index - 2]
        size = abs(step)
        result.append(step / size if size > 0 else 0j)
    return result


def best_shift(reference: Sequence[complex], compare: Sequence[complex], reach: int) -> tuple[int, bool]:
    """Shift (points) & mirroring of compared headings best matching reference headings up to one rotation"""
    count = len(reference)
    best, found = -1.0, (0, False)
    for mirrored in (False, True):
        own = [heading.conjugate() for heading in compare] if mirrored else list(compare)
        for shift in range(-reach, reach + 1):
            start = shift % count
            moved = [*own[start:], *own[:start]]
            score = abs(sum(a * b.conjugate() for a, b in zip(reference, moved)))
            if score > best:
                best, found = score, (shift, mirrored)
    return found


def fitted(pairs: Sequence[tuple[complex, complex]]) -> tuple[complex, complex, complex]:
    """Rotation (unit) & centers moving compared points (second) onto reference points (first) at best"""
    count = len(pairs)
    center_a = sum(pair[0] for pair in pairs) / count
    center_b = sum(pair[1] for pair in pairs) / count
    turn = sum((a - center_a) * (b - center_b).conjugate() for a, b in pairs)
    return (turn / abs(turn) if abs(turn) > 0 else 1 + 0j), center_a, center_b


class Line:
    """Points of a line with a grid for nearest point search"""

    def __init__(self, points: Sequence[complex]):
        self.points = points
        self.cells: dict[tuple[int, int], list[complex]] = {}
        for point in points:
            self.cells.setdefault(self.cell(point), []).append(point)

    @staticmethod
    def cell(point: complex) -> tuple[int, int]:
        return math.floor(point.real / LINE_CELL), math.floor(point.imag / LINE_CELL)

    def nearest(self, point: complex) -> tuple[float, complex | None]:
        """Distance to nearest line point & point, (inf, None) if none within one grid cell"""
        cell_x, cell_z = self.cell(point)
        best, found = math.inf, None
        for near_x in (cell_x - 1, cell_x, cell_x + 1):
            for near_z in (cell_z - 1, cell_z, cell_z + 1):
                for other in self.cells.get((near_x, near_z), ()):
                    gap = abs(other - point)
                    if gap < best:
                        best, found = gap, other
        return best, found


def off_line(points: Sequence[complex], line: Line, spacing: float) -> tuple[float, float]:
    """Longest stretch (meters) of a closed line off the other line & share of its points off it"""
    off = [line.nearest(point)[0] > OFF_LINE for point in points]
    if all(off):
        return spacing * len(off), 1.0
    longest = run = 0
    start = off.index(False)
    for flag in [*off[start:], *off[:start]]:
        run = run + 1 if flag else 0
        longest = max(longest, run)
    return longest * spacing, sum(off) / len(off)


def same_shape(reference: LapData, compare: LapData) -> bool | None:
    """Whether driven lines of both laps are the same circuit (compared line laid on reference one), None if a lap
    has no world positions"""
    if not has_positions(reference) or not has_positions(compare):
        return None
    length = lap_end_distance(reference)
    compare_length = lap_end_distance(compare)
    if not (length > 0 and compare_length > 0):
        return None
    count = SHAPE_POINTS
    ref, own = line_points(reference, count), line_points(compare, count)
    shift, mirrored = best_shift(directions(ref), directions(own), int(SHAPE_SHIFT * count))
    if mirrored:
        own = [point.conjugate() for point in own]
    start = shift % count
    pairs = list(zip(ref, [*own[start:], *own[:start]]))
    ref_line = Line(line_points(reference, max(int(length / LINE_STEP), count)))
    turn, center_a, center_b = fitted(pairs)
    for _ in range(FIT_ROUNDS):  # moved on nearest reference line points (distance measured differently)
        moved = [(point - center_b) * turn + center_a for point in own]
        nearest = [(found, point) for point, near in zip(own, moved)
                   for found in (ref_line.nearest(near)[1],) if found is not None]
        if len(nearest) < count / 2:
            break
        turn, center_a, center_b = fitted(nearest)
    moved = [(point - center_b) * turn + center_a for point in own]
    dense = line_points(compare, max(int(compare_length / LINE_STEP), count))
    if mirrored:
        dense = [point.conjugate() for point in dense]
    own_line = Line([(point - center_b) * turn + center_a for point in dense])
    stretch_limit = max(OFF_STRETCH, OFF_STRETCH_SHARE * length)
    for points, line, spacing in ((moved, ref_line, compare_length / count), (ref, own_line, length / count)):
        stretch, share = off_line(points, line, spacing)
        if stretch > stretch_limit or share > OFF_SHARE:
            return False
    return True


def same_imported_circuit(reference: LapData, compare: LapData) -> bool | None:
    """Whether compared lap was driven on the circuit of reference lap when a lap is not recorded by the app
    (imported log), from telemetry: False if another circuit, True if the same, None if unknown (keep lap)

    Lap infos must already match (see same_circuit): world positions decide, else a clearly different speed trace,
    track names helping only when sure (never deciding alone).
    """
    if is_recorded(reference) and is_recorded(compare):
        return None
    shape = same_shape(reference, compare)
    if shape is not None:
        return shape
    if not all(is_recorded(lap) or lap_length(lap) for lap in (reference, compare)):
        return None  # lap without lap info (older app, other file): circuit of its track folder only
    names = names_match(str(reference.meta.get("track", "")), str(compare.meta.get("track", "")))
    correlation = speed_correlation(reference, compare, distance_scale(reference, compare))
    if correlation is None:
        return names if names else None
    if correlation >= SPEED_UNSURE:
        return True
    if correlation < SPEED_OTHER:  # names match: lap driven another way (spin, traffic), kept
        return None if names else False
    return False if names is False else None

