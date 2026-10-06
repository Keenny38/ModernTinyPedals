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
Official corner numbers (or names) of circuits, placed on track geometry

Each corner is given at an approximate lap fraction from start line, then placed on the apex of the
nearest bend of actual track geometry (track map or driving line): a global offset is found first
(sources measure laps from slightly different lines), then each corner snaps to its bend.

Sources: F1 circuits from official F1 timing corner positions (MultiViewer circuit API),
other circuits numbered from circuit maps, matched in driving order with bends of in-game geometry.
Le Mans has no official numbering: corners are named. Other layouts of a circuit are not matched
(lap length must be close to full layout length).
"""

from __future__ import annotations

import bisect
import math
import re
import unicodedata
from collections.abc import Sequence
from typing import NamedTuple


class Circuit(NamedTuple):
    """Corners of a circuit layout"""

    keywords: tuple[str, ...]  # words of track name (any matches)
    length: float  # meters, full layout
    corners: tuple[tuple[str, float], ...]  # number (or name) & approximate lap fraction, in driving order
    numbered: bool = True  # False: corners are names
    tolerance: float = 0.03  # lap length difference accepted (fraction)


class TrackCorner(NamedTuple):
    """Official corner placed on track"""

    label: str  # number ("10a") or name
    distance: float  # meters from start line
    x: float
    y: float


CIRCUITS = (
    Circuit(("silverstone",), 5891, (
        ("1", 0.0775), ("2", 0.1047), ("3", 0.1486), ("4", 0.1778), ("5", 0.2106), ("6", 0.3364), ("7", 0.3740),
        ("8", 0.4329), ("9", 0.5229), ("10", 0.6175), ("11", 0.6332), ("12", 0.6580), ("13", 0.6822), ("14", 0.7073),
        ("15", 0.8551), ("16", 0.9324), ("17", 0.9478), ("18", 0.9735))),
    Circuit(("imola", "enzo e dino ferrari"), 4909, (
        ("1", 0.0522), ("2", 0.1817), ("3", 0.1944), ("4", 0.2235), ("5", 0.3121), ("6", 0.3319), ("7", 0.3889),
        ("8", 0.4708), ("9", 0.5216), ("10", 0.5493), ("11", 0.6007), ("12", 0.6201), ("13", 0.6372), ("14", 0.7222),
        ("15", 0.7322), ("16", 0.8454), ("17", 0.8854), ("18", 0.9142), ("19", 0.9778))),
    Circuit(("spa", "francorchamps"), 7004, (
        ("1", 0.0549), ("2", 0.1524), ("3", 0.1687), ("4", 0.1828), ("5", 0.3456), ("6", 0.3569), ("7", 0.3806),
        ("8", 0.4369), ("9", 0.4717), ("10", 0.5458), ("11", 0.5813), ("12", 0.6418), ("13", 0.6645), ("14", 0.7070),
        ("15", 0.7429), ("16", 0.8464), ("17", 0.8858), ("18", 0.9630), ("19", 0.9726))),
    Circuit(("circuit of the americas", "cota", "austin"), 5513, (
        ("1", 0.1183), ("2", 0.1631), ("3", 0.2114), ("4", 0.2274), ("5", 0.2456), ("6", 0.2699), ("7", 0.3120),
        ("8", 0.3403), ("9", 0.3574), ("10", 0.3960), ("11", 0.4664), ("12", 0.6857), ("13", 0.7287), ("14", 0.7421),
        ("15", 0.7793), ("16", 0.8137), ("17", 0.8384), ("18", 0.8639), ("19", 0.9157), ("20", 0.9719))),
    Circuit(("interlagos", "carlos pace"), 4309, (
        ("1", 0.0821), ("2", 0.1054), ("3", 0.1497), ("4", 0.3289), ("5", 0.3675), ("6", 0.4720), ("7", 0.5047),
        ("8", 0.5430), ("9", 0.5729), ("10", 0.6424), ("11", 0.6920), ("12", 0.7613), ("13", 0.7877), ("14", 0.8491),
        ("15", 0.9443))),
    Circuit(("paul ricard",), 5842, (
        ("1", 0.0743), ("2", 0.0918), ("3", 0.1914), ("4", 0.2082), ("5", 0.2275), ("6", 0.2506), ("7", 0.2885),
        ("8", 0.4770), ("9", 0.4913), ("10", 0.6373), ("11", 0.7266), ("12", 0.8020), ("13", 0.8388), ("14", 0.8822),
        ("15", 0.9117)), tolerance=0.008),  # F1 layout only (others differ at Mistral chicane)
    Circuit(("monza",), 5793, (
        ("1", 0.1573), ("2", 0.1672), ("3", 0.2564), ("4", 0.3686), ("5", 0.3776), ("6", 0.4400), ("7", 0.4954),
        ("8", 0.6810), ("9", 0.6968), ("10", 0.7145), ("11", 0.9031))),
    Circuit(("bahrain", "sakhir"), 5412, (
        ("1", 0.1323), ("2", 0.1499), ("3", 0.1709), ("4", 0.2805), ("5", 0.3300), ("6", 0.3476), ("7", 0.3647),
        ("8", 0.4129), ("9", 0.4805), ("10", 0.4985), ("11", 0.6433), ("12", 0.7175), ("13", 0.7584), ("14", 0.9091),
        ("15", 0.9243))),
    Circuit(("algarve", "portimao"), 4653, (
        ("1", 0.1432), ("2", 0.1779), ("3", 0.2111), ("4", 0.2433), ("5", 0.3679), ("6", 0.4176), ("7", 0.4681),
        ("8", 0.5033), ("9", 0.5758), ("10", 0.6318), ("11", 0.6464), ("12", 0.6929), ("13", 0.7353), ("14", 0.7853),
        ("15", 0.8829))),
    Circuit(("lusail", "losail", "qatar"), 5419, (
        ("1", 0.1483), ("2", 0.2023), ("3", 0.2437), ("4", 0.3218), ("5", 0.3509), ("6", 0.4089), ("7", 0.4826),
        ("8", 0.5182), ("9", 0.5407), ("10", 0.5838), ("11", 0.6418), ("12", 0.6988), ("13", 0.7362), ("14", 0.7743),
        ("15", 0.8290), ("16", 0.9173))),
    Circuit(("road atlanta",), 4088, (
        ("1", 0.112), ("2", 0.180), ("3", 0.238), ("4", 0.278), ("5", 0.346), ("6", 0.482), ("7", 0.532),
        ("10a", 0.859), ("10b", 0.876), ("11", 0.921), ("12", 0.960))),
    Circuit(("laguna seca",), 3602, (
        ("1", 0.074), ("2", 0.140), ("3", 0.225), ("4", 0.292), ("5", 0.431), ("6", 0.553), ("7", 0.618),
        ("8", 0.687), ("8a", 0.706), ("9", 0.768), ("10", 0.832), ("11", 0.918))),
    Circuit(("long beach",), 3167, (
        ("1", 0.232), ("2", 0.287), ("3", 0.330), ("4", 0.379), ("5", 0.395), ("6", 0.507), ("7", 0.529),
        ("8", 0.595), ("9", 0.803), ("10", 0.848), ("11", 0.883))),
    Circuit(("sarthe", "le mans"), 13626, (
        # Forest Esses & Indianapolis checked on recorded laps: Esses first bend ~1500 m (not the kink near
        # the Dunlop bridge), Indianapolis apex ~9830 m (not the kink before it)
        ("Dunlop Curve", 0.047), ("Dunlop Chicane", 0.064), ("Forest Esses", 0.110), ("Tertre Rouge", 0.142),
        ("Mulsanne Chicane 1", 0.303), ("Mulsanne Chicane 2", 0.450), ("Mulsanne", 0.568),
        ("Indianapolis", 0.721), ("Arnage", 0.746), ("Porsche Curves", 0.866), ("Maison Blanche", 0.910),
        ("Ford Chicanes", 0.979)), numbered=False),
)

BEND_THRESHOLD = 0.0012  # rad/m, smaller heading change is straight
OFFSET_RANGE = 0.05  # lap fraction, start line difference searched
SNAP_RANGE = 0.015  # lap fraction, corner moved to apex of a bend at most this far


def words(name: str) -> str:
    """Lowercase words without accents, space separated & padded: " circuit de spa francorchamps " """
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return f" {' '.join(re.findall(r'[a-z0-9]+', plain))} "


def find_circuit(track_name: str, lap_length: float) -> Circuit | None:
    """Circuit of track name with matching layout length, None if unknown"""
    text = words(track_name)
    for circuit in CIRCUITS:
        if any(f" {keyword} " in text for keyword in circuit.keywords):
            if lap_length > 0 and abs(lap_length / circuit.length - 1) <= circuit.tolerance:
                return circuit
    return None


def _interpolate(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    index = min(max(bisect.bisect_left(xs, x), 1), len(xs) - 1)
    x0, x1 = xs[index - 1], xs[index]
    if x1 == x0:
        return ys[index]
    return ys[index - 1] + (ys[index] - ys[index - 1]) * (x - x0) / (x1 - x0)


def bends(distances: Sequence[float], xs: Sequence[float], ys: Sequence[float], step: float = 5.0) -> list[float]:
    """Lap fractions of bend apexes: local maximums of heading change"""
    length = distances[-1]
    count = int(length / step)
    if count < 20:
        return []
    grid = [index * step for index in range(count)]
    gx = [_interpolate(distances, xs, distance) for distance in grid]
    gy = [_interpolate(distances, ys, distance) for distance in grid]
    heading = [math.atan2(gy[(index + 1) % count] - gy[index - 1], gx[(index + 1) % count] - gx[index - 1])
               for index in range(count)]
    span = 3  # heading change over +-15 m
    curvature = []
    for index in range(count):
        change = heading[(index + span) % count] - heading[index - span]
        curvature.append(abs((change + math.pi) % math.tau - math.pi) / (2 * span * step))
    radius = 8  # local maximum over +-40 m
    return [
        grid[index] / length for index in range(count)
        if curvature[index] > BEND_THRESHOLD
        and curvature[index] >= max(curvature[(index + offset) % count] for offset in range(-radius, radius + 1))
    ]


def _gap(a: float, b: float) -> float:
    """Distance between lap fractions (lap wraps around)"""
    gap = abs(a - b) % 1.0
    return min(gap, 1.0 - gap)


def place_corners(circuit: Circuit, distances: Sequence[float], xs: Sequence[float],
                  ys: Sequence[float]) -> list[TrackCorner]:
    """Corners of circuit on track geometry (distances increasing from start line), in driving order"""
    if len(distances) < 2:
        return []
    length = distances[-1]
    apexes = bends(distances, xs, ys)
    fractions = [fraction for _, fraction in circuit.corners]
    offset = 0.0
    if apexes:  # start line of source vs game: offset matching most corners with a bend
        def cost(shift: float) -> float:
            return sum(min(min(_gap(fraction + shift, apex) for apex in apexes), 0.02) for fraction in fractions)

        steps = int(OFFSET_RANGE / 0.0005)
        offset = min((index * 0.0005 for index in range(-steps, steps + 1)), key=lambda shift: (cost(shift), abs(shift)))
    used: set[float] = set()
    corners = []
    for label, fraction in circuit.corners:
        target = (fraction + offset) % 1.0
        near = [apex for apex in apexes if apex not in used and _gap(apex, target) <= SNAP_RANGE]
        if near:
            target = min(near, key=lambda apex: _gap(apex, target))
            used.add(target)
        distance = target * length
        corners.append(TrackCorner(
            label, distance, _interpolate(distances, xs, distance), _interpolate(distances, ys, distance)))
    return corners


def track_corners(track_name: str, distances: Sequence[float], xs: Sequence[float],
                  ys: Sequence[float]) -> tuple[list[TrackCorner], bool]:
    """Official corners of track on geometry, and whether they are numbers (else names); empty if unknown"""
    if len(distances) < 2:
        return [], True
    circuit = find_circuit(track_name, distances[-1])
    if circuit is None:
        return [], True
    return place_corners(circuit, distances, xs, ys), circuit.numbered
