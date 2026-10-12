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
Le Mans Ultimate Driver Rank (DR) & Safety Rank (SR), without Qt

The game menu keeps the online data it shows (profile, teams) in "coherent_local_storage.json"
in the game folder: a JSON object of stored items, values being JSON text themselves. Driver
entries hold "driverRank" ({"rank": "Silver", "tier": 2, "progress": 40, "elo": 0}) and
"safetyRank" ({"rank": "Platinum", "tier": 3, "progress": 50, "rating": 0, ...}), with name,
"steamId" (profile) or "driverId" (team members). File is only read, never written; values are
those of the last menu visit (updated by the game while in menus).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any, NamedTuple

STORAGE_FILE = "coherent_local_storage.json"
MAX_FILE_SIZE = 64 * 1024 * 1024  # never read a huge file whole
MAX_DEPTH = 12  # nested items & JSON text values
RANK_ORDER = ("Bronze", "Silver", "Gold", "Platinum")  # lowest first


class Rank(NamedTuple):
    """Driver or safety rank: name (Bronze...Platinum), tier (1-3), progress to next tier (percent)"""

    name: str
    tier: int
    progress: int

    @property
    def text(self) -> str:
        """Rank & tier: "Silver 2" """
        return f"{self.name} {self.tier}" if self.tier else self.name

    @property
    def short(self) -> str:
        """Short rank: "S2" (first letter of rank, tier)"""
        return f"{self.name[:1].upper()}{self.tier}" if self.tier else self.name[:1].upper()

    @property
    def level(self) -> float:
        """Comparable value (rank, tier & progress): higher is better, -1 if rank unknown"""
        try:
            index = RANK_ORDER.index(self.name.capitalize())
        except ValueError:
            return -1.0
        return index * 3 + max(self.tier - 1, 0) + max(min(self.progress, 100), 0) / 100


class DriverRanks(NamedTuple):
    """Ranks of one driver"""

    name: str
    steam_id: str
    driver_id: str
    nationality: str
    driver: Rank | None
    safety: Rank | None


def parse_rank(value: Any) -> Rank | None:
    """Rank from game data, None if missing or invalid"""
    if not isinstance(value, dict):
        return None
    name = value.get("rank")
    if not isinstance(name, str) or not name.strip():
        return None
    return Rank(name.strip(), _int(value.get("tier")), _int(value.get("progress")))


def _int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _text(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(int(value))
    return value.strip() if isinstance(value, str) else ""


def _nodes(value: Any, depth: int = 0) -> Iterator[dict]:
    """Every object in value, JSON text values decoded"""
    if depth > MAX_DEPTH:
        return
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in ("{", "[") and ("Rank" in text):  # only text that may hold ranks is decoded
            try:
                yield from _nodes(json.loads(text), depth + 1)
            except ValueError:
                return
    elif isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _nodes(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from _nodes(item, depth + 1)


def parse_storage(text: str) -> list[DriverRanks]:
    """Drivers with ranks found in storage text (same driver may be found several times)"""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    drivers = []
    for node in _nodes(data):
        if "driverRank" not in node and "safetyRank" not in node:
            continue
        driver, safety = parse_rank(node.get("driverRank")), parse_rank(node.get("safetyRank"))
        name = _text(node.get("name")) or _text(node.get("username"))
        if (driver or safety) and name:
            drivers.append(DriverRanks(
                name=name,
                steam_id=_text(node.get("steamId")),
                driver_id=_text(node.get("driverId")),
                nationality=_text(node.get("nationality")),
                driver=driver,
                safety=safety,
            ))
    return drivers


def read_storage(path: str) -> list[DriverRanks]:
    """Drivers with ranks of storage file, empty if missing or unreadable"""
    try:
        if os.path.getsize(path) > MAX_FILE_SIZE:
            return []
        with open(path, encoding="utf-8", errors="replace") as file:
            return parse_storage(file.read())
    except OSError:
        return []


def find_driver(drivers: list[DriverRanks], name: str = "", steam_id: str = "") -> DriverRanks | None:
    """Ranks of driver: by Steam ID first (player profile), else by name (case ignored)"""
    if steam_id:
        for entry in drivers:
            if entry.steam_id == steam_id:
                return entry
    key = name.strip().casefold()
    if key:
        for entry in drivers:
            if entry.name.casefold() == key:
                return entry
    return None
