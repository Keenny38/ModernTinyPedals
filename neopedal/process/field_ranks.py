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
Driver & Safety Rank of the other drivers of an online session (Le Mans Ultimate), without Qt

While the game is on an online server (any session: practice, daily race, private server), RaceControl
profiles of the drivers are asked by name (POST api/v1/players {"usernames": [...]}, names the game shows
without its "#1234" suffix; checked live 2026-10-17: same values as race entry lists). New drivers asked in
one request as soon as they join the session (leavers: no longer shown, ranks kept if they come back), known
ones again every KEEP_SECONDS, and every driver after each session (ranks, safety & badges
change once RaceControl processed a race: read again at RESULTS_DELAYS). Reads on their own thread.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Iterable
from typing import Any, NamedTuple, Protocol

from .driver_ranks import RANK_ORDER, DriverRanks, Rank
from .raceos import player_ranks

PLAYERS_PATH = "api/v1/players"
BATCH = 50  # names per request
CHECK_SECONDS = 30.0  # server joined & ranks due checked this often
JOIN_SECONDS = 3.0  # driver joining the session asked at once, at most one request this often (arrivals grouped)
KEEP_DRIVERS = 500  # ranks kept of drivers no longer in session (shown at once if they come back), at most
KEEP_SECONDS = 300.0  # ranks of a driver read again this late
RESULTS_DELAYS = (30.0, 120.0, 300.0)  # every driver read again this long after a session ended
MISSING_SECONDS = 600.0  # driver without RaceControl profile (or read failed) asked again this late

logger = logging.getLogger(__name__)
_SUFFIX = re.compile(r"\s*#\d+\s*$")


def strip_suffix(name: str) -> str:
    """Driver name without "#1234" suffix the game adds online"""
    return _SUFFIX.sub("", name)


def driver_key(name: str) -> str:
    """Name compared between game & RaceControl: "#1234" suffix of game left out, case & spaces ignored"""
    return " ".join(strip_suffix(name).split()).casefold()


def rank_of_level(level: float) -> Rank | None:
    """Rank of a comparable value (see Rank.level), None if negative"""
    if level < 0:
        return None
    index = min(int(level // 3), len(RANK_ORDER) - 1)
    rest = min(level - index * 3, 2.9999)
    tier = int(rest) + 1
    return Rank(RANK_ORDER[index], tier, int((rest - int(rest)) * 100))


class FieldLevel(NamedTuple):
    """Average ranks of drivers of a session whose ranks are known, count of those drivers"""

    driver: Rank | None
    safety: Rank | None
    known: int


def average_level(ranks: Iterable[DriverRanks]) -> FieldLevel:
    """Average Driver & Safety Rank (unknown ranks left out)"""
    drivers, safeties, count = [], [], 0
    for entry in ranks:
        count += 1
        if entry.driver is not None and entry.driver.level >= 0:
            drivers.append(entry.driver.level)
        if entry.safety is not None and entry.safety.level >= 0:
            safeties.append(entry.safety.level)
    return FieldLevel(rank_of_level(sum(drivers) / len(drivers)) if drivers else None,
                      rank_of_level(sum(safeties) / len(safeties)) if safeties else None, count)


class FieldSource(Protocol):
    """RaceControl & game reads (blocking calls, background thread)"""

    def enabled(self) -> bool: ...  # option turned on
    def joined(self) -> bool: ...  # game on an online server
    def post(self, path: str, payload: Any) -> Any: ...  # JSON answer of RaceControl POST, None if not read


def _start_thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, daemon=True, name="Field ranks").start()


class FieldRanks:
    """Ranks of drivers of the online session, read in background when asked for (poll)

    Args:
        source: RaceControl & game reads.
        clock: time function (tests).
        run: function running a read (own thread), tests run it at once.
    """

    def __init__(self, source: FieldSource, clock: Callable[[], float] = time.monotonic,
                 run: Callable[[Callable[[], None]], None] | None = None):
        self._source = source
        self._clock = clock
        self._run = run or _start_thread
        self._lock = threading.Lock()
        self._busy = False
        self._next_check = -1.0  # clock time of next check, -1: at once
        self._ranks: dict[str, DriverRanks] = {}  # driver key -> ranks (replaced whole, never changed in place)
        self._asked: dict[str, float] = {}  # driver key -> clock time asked
        self._names: tuple[str, ...] = ()  # names of drivers of session asked last
        self._wanted: dict[str, str] = {}  # driver key -> name asked (without suffix)
        self._refresh_due: list[float] = []  # clock times every driver is read again (after a session)
        self._joined_check = -1.0  # clock time a driver joining may be asked
        self._new = False  # drivers of session never asked
        self.serial = 0  # incremented each time ranks change

    def session_ended(self) -> None:
        """Every driver read again a moment after a session ended (ranks updated by RaceControl)"""
        now = self._clock()
        with self._lock:
            self._refresh_due = [now + delay for delay in RESULTS_DELAYS]

    def poll(self, names: Iterable[str]) -> None:
        """Read in background if due (non blocking): names of drivers of session"""
        try:
            enabled = self._source.enabled()
        except Exception:  # any setting error: off
            enabled = False
        if not enabled:  # option off: no thread, nothing kept
            self._clear()
            return
        names = tuple(names)
        if names != self._names:  # keys made again only when drivers changed
            self._names = names
            wanted: dict[str, str] = {}
            for name in names:
                key = driver_key(name)
                if key:
                    wanted.setdefault(key, " ".join(strip_suffix(name).split()))
            self._wanted = wanted
            self._new = any(key not in self._asked for key in wanted)
        now = self._clock()
        with self._lock:
            refresh = bool(self._refresh_due) and now >= self._refresh_due[0]
            joining = self._new and now >= self._joined_check  # driver joined: asked without waiting next check
            if self._busy or (now < self._next_check and not refresh and not joining):
                return
            if joining:
                self._joined_check = now + JOIN_SECONDS
                self._new = False
            if refresh:  # every driver read again (asked times forgotten)
                self._refresh_due = [due for due in self._refresh_due if due > now]
                self._asked = {}
            self._busy = True
            self._next_check = now + CHECK_SECONDS
        try:
            self._run(self._update)
        except Exception:  # no thread (interpreter closing)
            self._busy = False

    @property
    def known(self) -> dict[str, DriverRanks]:
        """Ranks by driver key (dict replaced whole when ranks change, serial incremented: never changed in place,
        read without lock)"""
        return self._ranks

    def ranks_of(self, name: str) -> DriverRanks | None:
        """Ranks of a driver of session, None if unknown"""
        return self._ranks.get(driver_key(name))

    def level(self, names: Iterable[str]) -> FieldLevel:
        """Average ranks of drivers of session whose ranks are known"""
        ranks = self._ranks
        return average_level(found for key in {driver_key(name) for name in names}
                             if (found := ranks.get(key)) is not None)

    def _clear(self) -> None:
        with self._lock:
            self._asked = {}
            if self._ranks:
                self._ranks = {}
                self.serial += 1

    def _update(self) -> None:
        try:
            self._check()
        except Exception:  # any error of reads: tried again later
            logger.exception("FIELD RANKS: read failed")
        finally:
            self._busy = False

    def _check(self) -> None:
        source = self._source
        if not source.enabled() or not source.joined():  # offline, menus or option off: nothing kept
            self._clear()
            return
        now = self._clock()
        wanted, asked, ranks = self._wanted, self._asked, self._ranks
        due = [name for key, name in wanted.items() if key not in asked
               or now - asked[key] >= (KEEP_SECONDS if key in ranks else MISSING_SECONDS)]
        if not due:
            return
        found: dict[str, DriverRanks] = {}
        for start in range(0, len(due), BATCH):
            batch = due[start:start + BATCH]
            for name in batch:
                asked[driver_key(name)] = now  # failed read or no profile: asked again later
            data = source.post(PLAYERS_PATH, {"usernames": batch})
            if not isinstance(data, list):
                break
            for player in data:
                entry = player_ranks(player)
                if entry is None or not isinstance(player, dict):
                    continue
                for value in (player.get("username"), player.get("name")):
                    if isinstance(value, str) and value.strip():
                        found[driver_key(value)] = entry
        if found:
            merged = {**ranks, **{key: entry for key, entry in found.items() if key in wanted}}
            if len(merged) > KEEP_DRIVERS:  # drivers gone long ago dropped first (oldest asked)
                gone = sorted((key for key in merged if key not in wanted), key=lambda key: asked.get(key, 0.0))
                for key in gone[:len(merged) - KEEP_DRIVERS]:
                    del merged[key]
            with self._lock:
                if merged != self._ranks:
                    self._ranks = merged
                    self.serial += 1
