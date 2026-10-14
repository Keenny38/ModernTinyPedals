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
"steamId" (profile) or "driverId" (team members), "badge" ("sr-clean"...) of team members, badge &
nationality in "profile" of the driver of an event registration. File is only read, never written; values are those of the last menu visit (updated by
the game while in menus).
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import threading
import time
import zlib
from collections.abc import Callable, Iterator
from typing import Any, NamedTuple

from ..userfile import append_line

STORAGE_FILE = "coherent_local_storage.json"
MAX_FILE_SIZE = 64 * 1024 * 1024  # never read a huge file whole
MAX_DEPTH = 40  # nested items & JSON text values (team members of registered events: 13 levels deep)
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
    badge: str = ""  # game badge ("sr-clean"), empty if none


def parse_rank(value: Any) -> Rank | None:
    """Rank from game data, None if missing or invalid"""
    if not isinstance(value, dict):
        return None
    name = value.get("rank")
    if not isinstance(name, str) or not name.strip():
        return None
    return Rank(name.strip(), _int(value.get("tier")), _int(value.get("progress")))


def _int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return 0  # int() of NaN or infinity raises
    return int(value)


def _text(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(int(value))
    return value.strip() if isinstance(value, str) else ""


def _nodes(value: Any) -> Iterator[dict]:
    """Every object in value (document order, up to MAX_DEPTH levels), JSON text values decoded"""
    stack: list[tuple[Any, int]] = [(value, 0)]
    pop, push = stack.pop, stack.append
    while stack:
        value, depth = pop()
        if isinstance(value, str):
            if "Rank" not in value or depth >= MAX_DEPTH:  # only text that may hold ranks is decoded (no copy)
                continue
            text = value.strip()
            if text[:1] in ("{", "["):
                try:
                    push((json.loads(text), depth + 1))
                except ValueError:
                    continue
            continue
        if isinstance(value, dict):
            yield value
            items: Any = value.values()
        elif isinstance(value, list):
            items = value
        else:
            continue
        if depth < MAX_DEPTH:
            stack.extend([(item, depth + 1) for item in reversed(items) if isinstance(item, (str, dict, list))])


def _has_ranks(text: str | bytes) -> bool:
    """Whether storage text may hold ranks (rank keys present, inside JSON text values too)"""
    if isinstance(text, bytes):
        return b"driverRank" in text or b"safetyRank" in text
    return "driverRank" in text or "safetyRank" in text


def _load(text: str | bytes) -> Any:
    """JSON data of storage text or file content (UTF-8 read without copy, invalid bytes replaced), raises
    ValueError if invalid"""
    try:
        return json.loads(text)
    except UnicodeDecodeError:  # ValueError too: invalid bytes replaced like decoding with errors="replace"
        assert isinstance(text, bytes)
        return json.loads(text.decode("utf-8", errors="replace"))


def parse_storage(text: str | bytes) -> list[DriverRanks]:
    """Drivers with ranks found in storage text or file content (same driver may be found several times)"""
    if not _has_ranks(text):
        return []
    try:
        data = _load(text)
    except ValueError:
        return []
    drivers = []
    for node in _nodes(data):
        if "driverRank" not in node and "safetyRank" not in node:
            continue
        driver, safety = parse_rank(node.get("driverRank")), parse_rank(node.get("safetyRank"))
        name = _text(node.get("name")) or _text(node.get("username"))
        profile = node.get("profile")  # event registration driver
        if not isinstance(profile, dict):
            profile = {}
        if (driver or safety) and name:
            drivers.append(DriverRanks(
                name=name,
                steam_id=_text(node.get("steamId")),
                driver_id=_text(node.get("driverId")),
                nationality=_text(node.get("nationality")) or _text(profile.get("nationality")),
                driver=driver,
                safety=safety,
                badge=_text(node.get("badge")) or _text(profile.get("badge")),
            ))
    return drivers


def read_raw(path: str) -> bytes | None:
    """Content of storage file, empty if too big, None if missing or unreadable (game writing it)"""
    try:
        if os.path.getsize(path) > MAX_FILE_SIZE:
            return b""
        with open(path, "rb") as file:
            return file.read()
    except OSError:
        return None


def parse_raw(raw: bytes | None) -> list[DriverRanks]:
    """Drivers with ranks of storage file content"""
    return parse_storage(raw) if raw else []


def valid_raw(raw: bytes) -> bool:
    """Check storage file content is complete JSON (not half-written by game)"""
    try:
        _load(raw)
    except ValueError:
        return False
    return True


def read_storage(path: str) -> list[DriverRanks]:
    """Drivers with ranks of storage file, empty if missing or unreadable"""
    return parse_raw(read_raw(path))


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
LOCATE_SECONDS = 60.0  # game folder & player looked for again this often while not found (game installed)
LOCATE_FOUND_SECONDS = 600.0  # looked for again this often once found (game moved, other Steam user)


class Located(NamedTuple):
    """Where & who: storage file path ("" if game not found), player Steam ID & names, Steam accounts of this
    computer (SteamID64, name, profile picture), account in use first"""

    path: str
    steam_id: str
    names: tuple[str, ...]
    accounts: tuple[tuple[str, str, str], ...] = ()


class OtherAccount(NamedTuple):
    """Last ranks seen of another game account of this computer (not the one in use)"""

    steam_id: str
    name: str  # Steam name, "" if unknown (account no longer signed in on this computer)
    avatar: str  # Steam profile picture file, "" if none
    ranks: DriverRanks
    time: float  # when ranks were seen (seconds since epoch)


class HistoryEntry(NamedTuple):
    """Ranks of player at a time (seconds since epoch), badge & Steam account ("" if none or not saved: older lines)"""

    time: float
    driver: Rank | None
    safety: Rank | None
    badge: str = ""
    steam_id: str = ""  # game account (several Steam accounts on one computer)


def player_entry(drivers: list[DriverRanks], located: Located) -> DriverRanks | None:
    """Ranks of player: by Steam ID, else by profile names (never an entry of another Steam account: file of the
    game still holds the account used before a switch until the game menu writes it again)"""
    found = find_driver(drivers, steam_id=located.steam_id)
    if found is None:
        own = [entry for entry in drivers
               if not (located.steam_id and entry.steam_id and entry.steam_id != located.steam_id)]
        for name in located.names:
            found = find_driver(own, name=name)
            if found is not None:
                break
    if found is not None and not found.badge:  # same driver found elsewhere in file with a badge
        key = found.name.casefold()
        badge = next((entry.badge for entry in drivers if entry.badge and (
            (found.steam_id and entry.steam_id == found.steam_id) or entry.name.casefold() == key)), "")
        if badge:
            found = found._replace(badge=badge)
    return found


def _rank_list(rank: Rank | None) -> list | None:
    return [rank.name, rank.tier, rank.progress] if rank else None


def _rank_from_list(value: Any) -> Rank | None:
    if isinstance(value, list) and len(value) == 3 and isinstance(value[0], str):
        return Rank(value[0], _int(value[1]), _int(value[2]))
    return None


def append_history(path: str, entry: HistoryEntry) -> bool:
    """Add entry to history file, False if not saved"""
    data: dict[str, Any] = {"time": round(entry.time), "driver": _rank_list(entry.driver),
                            "safety": _rank_list(entry.safety)}
    if entry.badge:
        data["badge"] = entry.badge
    if entry.steam_id:
        data["steam"] = entry.steam_id
    line = json.dumps(data)
    try:
        append_line(path, f"{line}\n".encode())  # never glued to a line cut short by a crash
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
                                                _rank_from_list(data.get("safety")), _text(data.get("badge")),
                                                _text(data.get("steam"))))
    except OSError:
        return []
    return entries


def rank_change(previous: Rank | None, current: Rank | None) -> int:
    """Change between two ranks in percent of a tier (+ better), 0 if either unknown"""
    if previous is None or current is None or previous.level < 0 or current.level < 0:
        return 0
    return round((current.level - previous.level) * 100)


def account_history(history: list[HistoryEntry], steam_id: str) -> list[HistoryEntry]:
    """Entries of one game account (lines of unknown account left out), all if account unknown"""
    return [entry for entry in history if entry.steam_id == steam_id] if steam_id else history


def rank_change_since(history: list[HistoryEntry], field: str, rank: Rank) -> int:
    """Change of rank ("driver" or "safety" field) since the previous different one of history, percent of a tier"""
    previous = next((getattr(entry, field) for entry in reversed(history)
                     if getattr(entry, field) not in (None, rank)), None)
    return rank_change(previous, rank)


class RankWatcher:
    """Player & team members ranks of storage file, read on a background poll thread when file changed

    Args:
        locate: function giving storage file, player Steam ID & names (called in background thread).
        history_path: function giving history file path ("" for no history).
        clock: time function (tests).
    """

    def __init__(self, locate: Callable[[], Located], history_path: Callable[[], str] = lambda: "",
                 clock: Callable[[], float] | None = None, active_account: Callable[[], str] = lambda: ""):
        self._locate = locate
        self._history_path = history_path
        self._active_account = active_account  # account signed in to Steam now (cheap), "" if unknown
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._busy = False  # check waiting or running on poll worker
        self._located: Located | None = None
        self._located_time = -LOCATE_SECONDS
        self._checked_time = -CHECK_SECONDS
        self._mtime = -1.0
        self._content: tuple[int, int] | None = None  # size & CRC of file content of drivers
        self._last_entry: tuple[str, dict[str, HistoryEntry]] | None = None  # history path, last entry of each account
        self.drivers: list[DriverRanks] = []
        self.player: DriverRanks | None = None
        self.updated = 0.0  # storage file modification time of values (seconds since epoch), 0 if none
        # Player not in storage file (game emptied its menu cache): last ranks of history, time they were seen
        self.remembered = False
        self.others: list[OtherAccount] = []  # last ranks of other game accounts of this computer
        self.serial = 0  # incremented each time values change

    def poll(self) -> None:
        """Check file in background if due (non blocking)"""
        now = self._clock()
        with self._lock:
            if self._busy or now - self._checked_time < CHECK_SECONDS:
                return
            self._checked_time = now
            self._busy = True
        from ..game_rest_poll import poll_worker  # shared poll threads, no thread made per check

        poll_worker.submit(self._check_polled)

    def _check_polled(self) -> None:
        try:
            self.check()
        finally:
            self._busy = False

    def check(self) -> None:
        """Locate & read storage file if changed (blocking)"""
        now = self._clock()
        previous = self._located
        # Results folders & Steam users read again only now & then once file found, every minute while missing
        found = previous is not None and bool(previous.path) and self._mtime >= 0
        if self._located is None or now - self._located_time >= (LOCATE_FOUND_SECONDS if found else LOCATE_SECONDS):
            try:
                self._located = self._locate()
            except Exception:  # any locate error: nothing found this time
                self._located = Located("", "", ())
            self._located_time = now
        located = self._located
        try:
            active = self._active_account()
        except Exception:  # unknown: account located kept
            active = ""
        if active and active != located.steam_id and self._located_time != now:  # Steam account switched
            with contextlib.suppress(Exception):  # any locate error: account found before kept
                located = self._located = self._locate()
            self._located_time = now
            self._mtime = -2.0  # ranks of account in use read again
        try:
            mtime = os.path.getmtime(located.path) if located.path else -1.0
        except OSError:
            mtime = -1.0
        if mtime == self._mtime:
            return
        if self._mtime >= 0 and self._located_time != now:  # file written again: game account may have changed
            with contextlib.suppress(Exception):  # any locate error: account found before kept
                located = self._located = self._locate()
            self._located_time = now
        raw = read_raw(located.path) if mtime >= 0 else b""
        if raw is None:  # unreadable (game writing it): values kept, read again next poll
            return
        content = (len(raw), zlib.crc32(raw))
        if content == self._content:  # same content (file saved again unchanged): not parsed again
            drivers = self.drivers
        else:
            drivers = parse_raw(raw)  # parsed only if it holds rank keys
            # Half-written file (no driver & invalid JSON): values kept, read again next poll
            if not drivers and mtime >= 0 and not valid_raw(raw):
                return
            self._content = content
        self._mtime = mtime
        player = player_entry(drivers, located)
        updated = max(mtime, 0.0)
        remembered = False
        if player is None and located.path:  # game found, its menu cache has no ranks now: last known kept
            last = self.last_entry(located.steam_id)
            if last is not None and (last.driver is not None or last.safety is not None):
                player = DriverRanks(located.names[0] if located.names else "", located.steam_id, "", "",
                                     last.driver, last.safety, last.badge)
                updated, remembered = last.time, True
        if player is not None and not remembered:
            self.record(player, mtime, player.steam_id or located.steam_id)
        others = self.other_accounts(located)
        with self._lock:
            changed = (player != self.player or drivers != self.drivers or remembered != self.remembered
                       or others != self.others)
            self.drivers, self.player = drivers, player
            self.updated, self.remembered, self.others = updated, remembered, others
            if changed:
                self.serial += 1

    def other_accounts(self, located: Located) -> list[OtherAccount]:
        """Last ranks of game accounts other than the one in use: Steam accounts of this computer first (in their
        order), then accounts of history no longer signed in here"""
        path = self._history_path()
        if not path or not located.steam_id:
            return []
        if self._last_entry is None or self._last_entry[0] != path:
            self._last_entry = (path, {entry.steam_id: entry for entry in read_history(path)})
        entries = self._last_entry[1]
        known = {steam_id: (name, avatar) for steam_id, name, avatar in located.accounts}
        order = [steam_id for steam_id, _, _ in located.accounts] + sorted(set(entries) - set(known))
        others = []
        for steam_id in order:
            entry = entries.get(steam_id)
            if not steam_id or steam_id == located.steam_id or entry is None or (
                    entry.driver is None and entry.safety is None):
                continue
            name, avatar = known.get(steam_id, ("", ""))
            ranks = DriverRanks(name, steam_id, "", "", entry.driver, entry.safety, entry.badge)
            others.append(OtherAccount(steam_id, name, avatar, ranks, entry.time))
        return others

    def last_entry(self, steam_id: str) -> HistoryEntry | None:
        """Last history entry of game account (history file read once), None if none or account unknown (lines
        of an unknown account never shown as ranks of another one)"""
        path = self._history_path()
        if not path or not steam_id:
            return None
        if self._last_entry is None or self._last_entry[0] != path:
            self._last_entry = (path, {entry.steam_id: entry for entry in read_history(path)})
        return self._last_entry[1].get(steam_id)

    def record(self, player: DriverRanks, mtime: float, steam_id: str) -> None:
        """Add ranks of game account to history when changed since its last entry (badge too: shown while game
        cache is empty)"""
        path = self._history_path()
        if not path:
            return
        last = self.last_entry(steam_id) if steam_id else None
        if (last is not None and last.driver == player.driver and last.safety == player.safety
                and last.badge == player.badge):
            return
        entry = HistoryEntry(mtime, player.driver, player.safety, player.badge, steam_id)
        if append_history(path, entry) and self._last_entry is not None and self._last_entry[0] == path:
            self._last_entry[1][steam_id] = entry

    def team_ranks(self, name: str) -> DriverRanks | None:
        """Ranks of player or team member by name, None if unknown"""
        return find_driver(self.drivers, name=name)
