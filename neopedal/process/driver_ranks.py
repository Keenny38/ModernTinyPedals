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
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any, NamedTuple

STORAGE_FILE = "coherent_local_storage.json"
MAX_FILE_SIZE = 64 * 1024 * 1024  # never read a huge file whole
MAX_DEPTH = 12  # nested items & JSON text values
RANK_ORDER = ("Bronze", "Silver", "Gold", "Platinum")  # lowest first
RANK_COLORS = {"bronze": "#CD8A4B", "silver": "#C9CED6", "gold": "#E8C14A", "platinum": "#7FD6DF"}  # readable on dark
RANK_COLORS_LIGHT = {"bronze": "#9A5B22", "silver": "#6B7380", "gold": "#A07A00", "platinum": "#1C8A96"}  # on light


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


# Player ranks: storage file watched in background (read again only when changed), history of changes
HISTORY_FILE = "driver_ranks.history"  # JSON lines in config folder: one line each time a rank changed
CHECK_SECONDS = 5.0  # storage file modification time checked this often
LOCATE_SECONDS = 60.0  # game folder & player looked for again this often (game installed or moved)


class Located(NamedTuple):
    """Where & who: storage file path ("" if game not found), player Steam ID & names"""

    path: str
    steam_id: str
    names: tuple[str, ...]


class HistoryEntry(NamedTuple):
    """Ranks of player at a time (seconds since epoch)"""

    time: float
    driver: Rank | None
    safety: Rank | None


def player_entry(drivers: list[DriverRanks], located: Located) -> DriverRanks | None:
    """Ranks of player: by Steam ID, else by profile names"""
    found = find_driver(drivers, steam_id=located.steam_id)
    for name in located.names:
        if found is not None:
            break
        found = find_driver(drivers, name=name)
    return found


def _rank_list(rank: Rank | None) -> list | None:
    return [rank.name, rank.tier, rank.progress] if rank else None


def _rank_from_list(value: Any) -> Rank | None:
    if isinstance(value, list) and len(value) == 3 and isinstance(value[0], str):
        return Rank(value[0], _int(value[1]), _int(value[2]))
    return None


def append_history(path: str, entry: HistoryEntry) -> bool:
    """Add entry to history file, False if not saved"""
    line = json.dumps({"time": round(entry.time), "driver": _rank_list(entry.driver),
                       "safety": _rank_list(entry.safety)})
    try:
        with open(path, "a", encoding="utf-8") as file:
            file.write(line + "\n")
    except OSError:
        return False
    return True


def read_history(path: str) -> list[HistoryEntry]:
    """History entries, oldest first (invalid lines skipped)"""
    entries = []
    try:
        with open(path, encoding="utf-8", errors="replace") as file:
            for line in file:
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                if isinstance(data, dict) and isinstance(data.get("time"), (int, float)):
                    entries.append(HistoryEntry(float(data["time"]), _rank_from_list(data.get("driver")),
                                                _rank_from_list(data.get("safety"))))
    except OSError:
        return []
    return entries


def rank_change(previous: Rank | None, current: Rank | None) -> int:
    """Change between two ranks in percent of a tier (+ better), 0 if either unknown"""
    if previous is None or current is None or previous.level < 0 or current.level < 0:
        return 0
    return round((current.level - previous.level) * 100)


class RankWatcher:
    """Player & team members ranks of storage file, read in a background thread when file changed

    Args:
        locate: function giving storage file, player Steam ID & names (called in background thread).
        history_path: function giving history file path ("" for no history).
        clock: time function (tests).
    """

    def __init__(self, locate: Callable[[], Located], history_path: Callable[[], str] = lambda: "",
                 clock: Callable[[], float] | None = None):
        self._locate = locate
        self._history_path = history_path
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._located: Located | None = None
        self._located_time = -LOCATE_SECONDS
        self._checked_time = -CHECK_SECONDS
        self._mtime = -1.0
        self.drivers: list[DriverRanks] = []
        self.player: DriverRanks | None = None
        self.updated = 0.0  # storage file modification time of values (seconds since epoch), 0 if none
        self.serial = 0  # incremented each time values change

    def poll(self) -> None:
        """Check file in background if due (non blocking)"""
        now = self._clock()
        with self._lock:
            if now - self._checked_time < CHECK_SECONDS or (self._thread is not None and self._thread.is_alive()):
                return
            self._checked_time = now
            self._thread = threading.Thread(target=self.check, name="Driver ranks", daemon=True)
            self._thread.start()

    def check(self) -> None:
        """Locate & read storage file if changed (blocking)"""
        now = self._clock()
        if self._located is None or now - self._located_time >= LOCATE_SECONDS:
            try:
                self._located = self._locate()
            except Exception:  # any locate error: nothing found this time
                self._located = Located("", "", ())
            self._located_time = now
        located = self._located
        try:
            mtime = os.path.getmtime(located.path) if located.path else -1.0
        except OSError:
            mtime = -1.0
        if mtime == self._mtime:
            return
        self._mtime = mtime
        drivers = read_storage(located.path) if mtime >= 0 else []
        player = player_entry(drivers, located)
        with self._lock:
            changed = player != self.player or drivers != self.drivers
            self.drivers, self.player = drivers, player
            self.updated = max(mtime, 0.0)
            if changed:
                self.serial += 1
        if player is not None:
            self.record(player, mtime)

    def record(self, player: DriverRanks, mtime: float) -> None:
        """Add ranks to history when changed since last entry"""
        path = self._history_path()
        if not path:
            return
        history = read_history(path)
        if history and history[-1].driver == player.driver and history[-1].safety == player.safety:
            return
        append_history(path, HistoryEntry(mtime, player.driver, player.safety))

    def team_ranks(self, name: str) -> DriverRanks | None:
        """Ranks of player or team member by name, None if unknown"""
        return find_driver(self.drivers, name=name)
