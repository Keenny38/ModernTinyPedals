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

Since 2026-10 the game no longer keeps ranks in that file (written at game exit only): player ranks are read
online from RaceControl when enabled (see raceos.py, RankWatcher online source).
"""

from __future__ import annotations

import contextlib
import functools
import json
import logging
import math
import os
import threading
import time
import zlib
from collections.abc import Callable, Iterator, Sequence
from typing import Any, NamedTuple, Protocol

from ..userfile import append_line, atomic_replace
from ..validator import load_json_strict

logger = logging.getLogger(__name__)

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
                except (ValueError, RecursionError):  # RecursionError: nested too deeply
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
        return load_json_strict(text, allow_nan=True)  # nested too deeply: ValueError
    except UnicodeDecodeError:  # ValueError too: invalid bytes replaced like decoding with errors="replace"
        assert isinstance(text, bytes)
        return load_json_strict(text.decode("utf-8", errors="replace"), allow_nan=True)


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
    """Ranks of driver: by Steam ID first (player profile), else by name (case ignored), see name_index too"""
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


def name_index(drivers: list[DriverRanks]) -> dict[str, DriverRanks]:
    """Drivers by case folded name, first one kept (same as find_driver by name): name.strip().casefold() key"""
    index: dict[str, DriverRanks] = {}
    for entry in drivers:
        index.setdefault(entry.name.casefold(), entry)
    return index


# Player ranks: storage file watched in background (read again only when changed), history of changes
HISTORY_FILE = "driver_ranks.history"  # JSON lines in config folder: one line each time a rank changed
HISTORY_KEEP = 1000  # newest lines kept once history file trimmed (last line of each account kept too)
HISTORY_SLACK = 100  # file trimmed once it holds this many lines more than kept (never rewritten for each line)
CHECK_SECONDS = 5.0  # storage file modification time checked this often
LOCATE_SECONDS = 60.0  # game folder & player looked for again this often while not found (game installed)
LOCATE_FOUND_SECONDS = 600.0  # looked for again this often once found (game moved, other Steam user)
# Online ranks (RaceControl): read at start, after each session (new results file: ranks computed by the service
# a moment later, read 3 times), else this often while game runs (sign in with a new game ticket each read)
ONLINE_RESULTS_DELAYS = (30.0, 120.0, 300.0)
ONLINE_SECONDS = 300.0
ONLINE_GAME_SECONDS = 60.0  # game looked for this often while not running
ONLINE_RETRY_SECONDS = 300.0  # read again this late once a read failed (offline)


class Located(NamedTuple):
    """Where & who: storage file path ("" if game not found), player Steam ID & names, Steam accounts of this
    computer (SteamID64, name, profile picture), account in use first"""

    path: str
    steam_id: str
    names: tuple[str, ...]
    accounts: tuple[tuple[str, str, str], ...] = ()
    results: str = ""  # race results folder of game ("" if unknown): a file added there = a session ended


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


def history_line(entry: HistoryEntry) -> str:
    """Line of history file of entry (JSON, ends with newline)"""
    data: dict[str, Any] = {"time": round(entry.time), "driver": _rank_list(entry.driver),
                            "safety": _rank_list(entry.safety)}
    if entry.badge:
        data["badge"] = entry.badge
    if entry.steam_id:
        data["steam"] = entry.steam_id
    return f"{json.dumps(data)}\n"


def append_history(path: str, entry: HistoryEntry) -> bool:
    """Add entry to history file, False if not saved"""
    try:
        append_line(path, history_line(entry).encode())  # never glued to a line cut short by a crash
    except OSError:
        return False
    return True


def trim_history(entries: Sequence[HistoryEntry], keep: int = HISTORY_KEEP) -> list[HistoryEntry]:
    """Newest keep entries, with the last entry of every account (older ones too: last ranks of an account never
    lost), in history order"""
    entries = list(entries)
    start = len(entries) - keep
    if start <= 0:
        return entries
    last = {entry.steam_id: index for index, entry in enumerate(entries)}  # last index of each account
    return [entries[index] for index in sorted(index for index in last.values() if index < start)] + entries[start:]


def write_history(path: str, entries: Sequence[HistoryEntry]) -> bool:
    """History file written again with entries (atomically: never left half-written), False if not saved"""
    try:
        atomic_replace(path, "".join(history_line(entry) for entry in entries).encode())
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
                except (ValueError, RecursionError):  # RecursionError: nested too deeply
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
    """Entries of one game account (lines of unknown account left out), all if account unknown (see
    RankWatcher.history_of: kept in memory)"""
    return [entry for entry in history if entry.steam_id == steam_id] if steam_id else history


def rank_change_since(history: Sequence[HistoryEntry], field: str, rank: Rank) -> int:
    """Change of rank ("driver" or "safety" field) since the previous different one of history, percent of a tier"""
    previous = next((getattr(entry, field) for entry in reversed(history)
                     if getattr(entry, field) not in (None, rank)), None)
    return rank_change(previous, rank)


def _start_thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, daemon=True, name="Online ranks").start()


def _local_day(stamp: float) -> tuple[int, ...] | None:
    """Local calendar day of time (seconds since epoch), None if none or out of range"""
    if stamp <= 0:
        return None
    try:
        return tuple(time.localtime(stamp)[:3])
    except (OverflowError, OSError, ValueError):
        return None


class _History(NamedTuple):
    """History file in memory (never changed once made: replaced whole, read without lock by any thread)"""

    path: str
    entries: tuple[HistoryEntry, ...]  # every entry, oldest first
    accounts: dict[str, tuple[HistoryEntry, ...]]  # entries of each account ("": lines without account), oldest first

    @classmethod
    def of(cls, path: str, entries: Sequence[HistoryEntry]) -> _History:
        accounts: dict[str, list[HistoryEntry]] = {}
        for entry in entries:
            accounts.setdefault(entry.steam_id, []).append(entry)
        return cls(path, tuple(entries), {steam_id: tuple(found) for steam_id, found in accounts.items()})

    def added(self, entry: HistoryEntry) -> _History:
        return _History(self.path, (*self.entries, entry),
                        {**self.accounts, entry.steam_id: (*self.accounts.get(entry.steam_id, ()), entry)})

    def last(self, steam_id: str) -> HistoryEntry | None:
        found = self.accounts.get(steam_id)
        return found[-1] if found else None


class OnlineSource(Protocol):
    """Player ranks of an online service (blocking calls, background thread)"""

    def enabled(self) -> bool: ...  # option turned on
    def game_running(self) -> bool: ...
    def fetch(self, account: str) -> DriverRanks | None: ...  # ranks of game account (SteamID64), None if not read
    def forget(self) -> None: ...  # option turned off: sign in dropped


class RankWatcher:
    """Player & team members ranks of storage file, read on a background poll thread when file changed

    Args:
        locate: function giving storage file, player Steam ID & names (called in background thread).
        history_path: function giving history file path ("" for no history).
        clock: time function (tests).
        online: online ranks, preferred to those of storage file once read (newer), None for none.
        wall_clock: time function giving seconds since epoch (tests).
        run_online: function running an online read (own thread: network requests never hold a shared poll
            thread), tests run it at once.
        session_ended: called when a session ended (new race results file) while online ranks are on.
    """

    def __init__(self, locate: Callable[[], Located], history_path: Callable[[], str] = lambda: "",
                 clock: Callable[[], float] | None = None, active_account: Callable[[], str] = lambda: "",
                 online: OnlineSource | None = None, wall_clock: Callable[[], float] = time.time,
                 run_online: Callable[[Callable[[], None]], None] | None = None,
                 session_ended: Callable[[], None] = lambda: None):
        self._locate = locate
        self._session_ended = session_ended
        self._online_source = online
        self._wall_clock = wall_clock
        self._run_online = run_online or _start_thread
        self._online_busy = False  # online read running
        self._online_generation = 0  # incremented when online ranks dropped: read running then ignored
        self._online_ranks: tuple[DriverRanks, float] | None = None  # last online ranks read & when (epoch)
        self._online_pending = False  # online ranks changed, not applied yet
        self._online_next = -math.inf  # clock time of next periodic online read
        self._online_due: list[float] = []  # clock times of online reads after a session ended
        self._results_mtime: float | None = None  # modification time of results folder, None if not seen yet
        self._history_path = history_path
        self._active_account = active_account  # account signed in to Steam now (cheap), "" if unknown
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._busy = False  # check waiting or running on poll worker
        self._located: Located | None = None
        self._located_time = -LOCATE_SECONDS
        self._switch_seen = ""  # active Steam account a switch was last looked for (never again for the same one)
        self._checked_time = -CHECK_SECONDS
        self._mtime = -1.0
        self._content: tuple[int, int] | None = None  # size & CRC of file content of drivers
        self._file_drivers: list[DriverRanks] = []  # drivers of storage file (online player not added)
        self._file_key: tuple[str, float] | None = None  # storage file path & modification time of _file_drivers
        self._history: _History | None = None  # history file in memory, None until read
        self._history_lock = threading.Lock()  # history read or written (never held by readers once read)
        self.drivers: list[DriverRanks] = []
        self._by_name: tuple[list[DriverRanks], dict[str, DriverRanks]] = (self.drivers, {})  # drivers & name_index
        self.player: DriverRanks | None = None
        self.updated = 0.0  # storage file modification time of values (seconds since epoch), 0 if none
        # Player not in storage file (game emptied its menu cache): last ranks of history, time they were seen
        self.remembered = False
        self.online = False  # player ranks read online (RaceControl), not from storage file
        self.others: list[OtherAccount] = []  # last ranks of other game accounts of this computer
        # Incremented each time values change (drivers, player...), "updated" time only when its day changed (dates
        # shown): an online read giving the same ranks changes nothing
        self.serial = 0

    @property
    def account(self) -> str:
        """Game account in use (SteamID64), "" if unknown"""
        located = self._located
        return located.steam_id if located is not None else ""

    def poll(self) -> None:
        """Check file in background if due (non blocking)"""
        now = self._clock()
        with self._lock:
            if self._busy or now - self._checked_time < CHECK_SECONDS:
                return
            self._checked_time = now
            self._busy = True
        from ..game_rest_poll import FileRead, poll_worker  # shared poll threads, no thread made per check

        poll_worker.submit(FileRead(self._check_polled))  # file lane: a 64 MB read never delays route reads

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
        relocated = False  # located in this check (flag, not clock: a coarse clock gives the same time twice)
        if self._located is None or now - self._located_time >= (LOCATE_FOUND_SECONDS if found else LOCATE_SECONDS):
            try:
                self._located = self._locate()
            except Exception:  # any locate error: nothing found this time
                self._located = Located("", "", ())
            self._located_time = now
            relocated = True
        located = self._located
        try:
            active = self._active_account()
        except Exception:  # unknown: account located kept
            active = ""
        # Steam account switched: looked for once per active account (none found, or LMU not found: steam_id "",
        # never located again on every check)
        if active and active != located.steam_id and active != self._switch_seen and not relocated:
            self._switch_seen = active
            with contextlib.suppress(Exception):  # any locate error: account found before kept
                located = self._located = self._locate()
            self._located_time = now
            relocated = True
            self._mtime = -2.0  # ranks of account in use read again
        if active and active == located.steam_id:  # account in use found: a later switch looked for again
            self._switch_seen = ""
        self.check_online(now, located)
        try:
            mtime = os.path.getmtime(located.path) if located.path else -1.0
        except OSError:
            mtime = -1.0
        if mtime == self._mtime and not self._online_pending:
            return
        if mtime != self._mtime and self._mtime >= 0 and not relocated:  # file written again: game account may
            with contextlib.suppress(Exception):  # have changed (any locate error: account found before kept)
                located = self._located = self._locate()
            self._located_time = now
        file_key = (located.path, mtime)
        if file_key == self._file_key:  # file unchanged since read (online ranks to apply): not read again
            drivers = self._file_drivers
        elif (self._file_key is not None and self._file_key[0] == located.path and not self._file_drivers
              and self._online_ranks is not None):
            # Online ranks used & file without ranks when read (game no longer keeps them there): file written again
            # only tells the game ran, never read again (up to 64 MB) until online ranks dropped (option turned off)
            drivers = self._file_drivers
        else:
            raw = read_raw(located.path) if mtime >= 0 else b""
            if raw is None:  # unreadable (game writing it): values kept, read again next poll
                return
            content = (len(raw), zlib.crc32(raw))
            if content == self._content:  # same content (file saved again unchanged): not parsed again
                drivers = self._file_drivers
            else:
                drivers = parse_raw(raw)  # parsed only if it holds rank keys
                # Half-written file (no driver & invalid JSON): values kept, read again next poll
                if not drivers and mtime >= 0 and not valid_raw(raw):
                    return
                self._content = content
            self._file_key = file_key
        self._mtime = mtime
        self._file_drivers = drivers
        with self._lock:  # online read ends on its own thread
            online_ranks, self._online_pending = self._online_ranks, False
        player = player_entry(drivers, located)
        updated = max(mtime, 0.0)
        remembered = online = False
        if online_ranks is not None and (player is None or online_ranks[1] >= mtime):  # newer online
            ranks, read_time = online_ranks
            badge = ranks.badge or (player.badge if player is not None else "")
            if not badge:  # service gives no badge: last one seen kept
                last = self.last_entry(ranks.steam_id or located.steam_id)
                badge = last.badge if last is not None else ""
            name = ranks.name or (player.name if player is not None else "") or (
                located.names[0] if located.names else "")
            player = ranks._replace(name=name, steam_id=ranks.steam_id or located.steam_id, badge=badge)
            key = name.casefold()
            drivers = [player] + [entry for entry in drivers if not (
                (player.steam_id and entry.steam_id == player.steam_id) or entry.name.casefold() == key)]
            updated, online = read_time, True
        if player is None and located.path:  # game found, its menu cache has no ranks now: last known kept
            last = self.last_entry(located.steam_id) or self.adopt_unknown_account(located.steam_id)
            if last is not None and (last.driver is not None or last.safety is not None):
                player = DriverRanks(located.names[0] if located.names else "", located.steam_id, "", "",
                                     last.driver, last.safety, last.badge)
                updated, remembered = last.time, True
        if player is not None and not remembered:
            self.record(player, updated if online else mtime, player.steam_id or located.steam_id)
        others = self.other_accounts(located)
        self._loaded_history()  # read here (worker) once, not by the first page showing ranks
        same_drivers = drivers == self.drivers
        index = {} if same_drivers else name_index(drivers)  # made here (worker), not by the first lookup
        with self._lock:
            # Time of an online read giving the same ranks: no change (pages made again), but for its day (date shown)
            changed = (player != self.player or not same_drivers or remembered != self.remembered
                       or others != self.others or online != self.online
                       or (online and _local_day(updated) != _local_day(self.updated)))
            if not same_drivers:  # list kept when equal: index & lookups of readers stay valid
                self.drivers = drivers
                self._by_name = (drivers, index)
            self.player = player
            self.updated, self.remembered, self.others, self.online = updated, remembered, others, online
            if changed:
                self.serial += 1

    def check_online(self, now: float, located: Located) -> None:
        """Start online read if due (own thread, applied by a later check): at start, after a session ended, else
        every ONLINE_SECONDS while game runs"""
        source = self._online_source
        try:
            enabled = source is not None and source.enabled()
        except Exception:  # any setting error: off
            enabled = False
        if source is None or not enabled:
            if self._online_ranks is not None or self._online_next != -math.inf:  # turned off: file ranks again
                with self._lock:
                    self._online_generation += 1
                    self._online_ranks, self._online_pending = None, True
                    self._online_next, self._online_due, self._results_mtime = -math.inf, [], None
                if source is not None:
                    with contextlib.suppress(Exception):
                        source.forget()
            return
        with self._lock:
            if self._online_ranks is not None and located.steam_id and self._online_ranks[0].steam_id not in (
                    "", located.steam_id):  # Steam account switched: ranks of other account dropped, read again
                self._online_generation += 1
                self._online_ranks, self._online_pending, self._online_next = None, True, -math.inf
        try:
            results_mtime = os.path.getmtime(located.results) if located.results else None
        except OSError:
            results_mtime = None
        if results_mtime is not None and results_mtime != self._results_mtime:
            if self._results_mtime is not None:  # not first seen: a session ended
                self._online_due = [now + delay for delay in ONLINE_RESULTS_DELAYS]
                try:
                    self._session_ended()
                except Exception:  # any error of listener: own ranks read anyway
                    logger.exception("RANKS: session end listener failed")
            self._results_mtime = results_mtime
        with self._lock:
            due = bool(self._online_due) and now >= self._online_due[0]
            if self._online_busy or (not due and now < self._online_next):
                return
            self._online_due = [time_due for time_due in self._online_due if time_due > now]
            self._online_busy = True
            self._online_next = now + ONLINE_RETRY_SECONDS  # until read ends
            generation = self._online_generation
        work = functools.partial(self._read_online, source, located.steam_id, now, due, generation)
        try:
            self._run_online(work)
        except Exception:  # no thread (interpreter closing)
            self._online_busy = False

    def _read_online(self, source: OnlineSource, account: str, now: float, due: bool, generation: int) -> None:
        ranks = None
        wait = ONLINE_RETRY_SECONDS
        try:
            if not due and not source.game_running():  # periodic read only while game runs
                wait = ONLINE_GAME_SECONDS
            else:
                ranks = source.fetch(account)
        except Exception:  # any error of online source: read again later
            logger.exception("RANKS: online read failed")
        with self._lock:
            self._online_busy = False
            if generation != self._online_generation:  # turned off or account switched meanwhile
                return
            if ranks is None:
                self._online_next = now + wait
                return
            self._online_next = now + ONLINE_SECONDS
            self._online_ranks, self._online_pending = (ranks, self._wall_clock()), True
            self._checked_time = -CHECK_SECONDS  # applied by next poll

    def other_accounts(self, located: Located) -> list[OtherAccount]:
        """Last ranks of game accounts other than the one in use: Steam accounts of this computer first (in their
        order), then accounts of history no longer signed in here"""
        if not located.steam_id:
            return []
        history = self._loaded_history()
        if history is None:
            return []
        known = {steam_id: (name, avatar) for steam_id, name, avatar in located.accounts}
        order = [steam_id for steam_id, _, _ in located.accounts] + sorted(set(history.accounts) - set(known))
        others = []
        for steam_id in order:
            entry = history.last(steam_id)
            if not steam_id or steam_id == located.steam_id or entry is None or (
                    entry.driver is None and entry.safety is None):
                continue
            name, avatar = known.get(steam_id, ("", ""))
            ranks = DriverRanks(name, steam_id, "", "", entry.driver, entry.safety, entry.badge)
            others.append(OtherAccount(steam_id, name, avatar, ranks, entry.time))
        return others

    def _loaded_history(self) -> _History | None:
        """History file in memory (read once, again if its path changed), None if no history"""
        path = self._history_path()
        if not path:
            return None
        history = self._history
        if history is not None and history.path == path:
            return history
        with self._history_lock:
            return self._history_locked(path)

    def _history_locked(self, path: str) -> _History:
        """History of path in memory, read if not yet (history lock held)"""
        history = self._history
        if history is None or history.path != path:
            history = self._history = _History.of(path, read_history(path))
        return history

    def _add_history(self, path: str, entry: HistoryEntry, keep_unsaved: bool = False) -> bool:
        """Entry added to history file & memory (memory only if not saved & keep_unsaved), file trimmed to newest
        lines once too long, False if not saved"""
        with self._history_lock:  # readers never see the file holding the entry & memory without it
            history = self._history_locked(path)
            saved = append_history(path, entry)
            if saved or keep_unsaved:
                history = history.added(entry)
            if saved and len(history.entries) > HISTORY_KEEP + HISTORY_SLACK:
                entries = read_history(path)  # file read again: memory alone never written over it
                kept = trim_history(entries, HISTORY_KEEP)
                if len(kept) < len(entries) and write_history(path, kept):
                    entries = kept
                history = _History.of(path, entries)
            self._history = history
        return saved

    def history_of(self, steam_id: str) -> tuple[HistoryEntry, ...]:
        """History entries of game account, oldest first, every entry if account unknown ("") like account_history
        of history file (kept in memory: never read again by pages), empty if no history"""
        history = self._loaded_history()
        if history is None:
            return ()
        return history.accounts.get(steam_id, ()) if steam_id else history.entries

    def last_entry(self, steam_id: str) -> HistoryEntry | None:
        """Last history entry of game account (history file read once), None if none or account unknown (lines
        of an unknown account never shown as ranks of another one)"""
        if not steam_id:
            return None
        history = self._loaded_history()
        return history.last(steam_id) if history is not None else None

    def adopt_unknown_account(self, steam_id: str) -> HistoryEntry | None:
        """Last entry of unknown account (lines saved before accounts were, version < 0.24) given to game account
        in use when no other account has lines, saved again with account (never given to a second one later), None
        if none"""
        history = self._loaded_history()
        if history is None or not steam_id or history.last(steam_id) is not None:
            return None
        unknown = history.last("")
        if unknown is None or any(history.accounts):  # any(): account of a line known
            return None
        entry = unknown._replace(steam_id=steam_id)
        # Not saved: kept in memory, given again next time (same account if still the only one)
        self._add_history(history.path, entry, keep_unsaved=True)
        return entry

    def record(self, player: DriverRanks, mtime: float, steam_id: str) -> None:
        """Add ranks of game account to history when changed since its last entry (badge too: shown while game
        cache is empty)"""
        path = self._history_path()
        if not path:
            return
        if steam_id:
            last = self.last_entry(steam_id)
        else:  # account unknown: compared with last line of no account (never a line added on every check)
            history = self._loaded_history()
            last = history.last("") if history is not None else None
        if (last is not None and last.driver == player.driver and last.safety == player.safety
                and last.badge == player.badge):
            return
        self._add_history(path, HistoryEntry(mtime, player.driver, player.safety, player.badge, steam_id))

    def team_ranks(self, name: str) -> DriverRanks | None:
        """Ranks of player or team member by name, None if unknown"""
        return self.find_name(name)

    def find_name(self, name: str) -> DriverRanks | None:
        """Ranks of player or team member by name (case ignored, first one like find_driver), None if unknown: index
        made once per drivers list (any thread: list & index replaced together, never changed)"""
        key = name.strip().casefold()
        if not key:
            return None
        drivers = self.drivers
        index = self._by_name
        if index[0] is not drivers:  # drivers set without check (tests) or index not made yet
            index = self._by_name = (drivers, name_index(drivers))
        return index[1].get(key)
