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
Race history of every driver from the race results files of the game, for the Broadcast Director commentators

Races (results files of race sessions) read once in background, again only when changed: starts, wins &
podiums in class, best class finish on a track, last races, and races two drivers ran together (who finished
ahead). Team cars count for every driver of the car (driver swaps). No Qt.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Sequence
from typing import NamedTuple

from . import results_file as rf

RACE_CODE = "R"
MAX_FILES = 2000  # newest race files read


class RaceRecord(NamedTuple):
    """A race of a driver"""

    path: str
    time: float  # race start, Unix time
    track: str
    car_class: str
    class_position: int
    finished: bool
    class_cars: int


class DriverStats(NamedTuple):
    starts: int
    wins: int
    podiums: int
    best_here: int  # best class finish on the track, 0 if never raced there
    last: tuple[RaceRecord, ...]  # newest first


def fold(name: str) -> str:
    """Driver key: case & spaces ignored, online tag dropped ("Name#1234")"""
    return " ".join(name.split("#", 1)[0].split()).casefold()


def race_file(path: str) -> bool:
    """Results file of a race session ("...-70R1.xml")"""
    stem = os.path.splitext(os.path.basename(path))[0].rstrip("0123456789")
    return stem.endswith(RACE_CODE)


def same_track(first: str, second: str) -> bool:
    a, b = first.casefold().strip(), second.casefold().strip()
    return bool(a and b) and (a == b or a in b or b in a)


class DriverHistory:
    """Races of every driver (thread safe: scan in a worker thread, read from the page)"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._files: dict[str, tuple[tuple[int, float], dict[str, RaceRecord]]] = {}  # path: stamp, driver key
        self._drivers: dict[str, list[RaceRecord]] = {}
        self._generation = 0  # cleared while a scan runs: its tables dropped
        self.version = 0

    def scan(self, folders: Sequence[str]) -> bool:
        """Race files of folders read (new or changed ones only), True if anything changed (worker thread)"""
        paths = [path for folder in folders for path in rf.results_files(folder) if race_file(path)][:MAX_FILES]
        with self._lock:
            known = dict(self._files)
            generation = self._generation
        files: dict[str, tuple[tuple[int, float], dict[str, RaceRecord]]] = {}
        changed = False
        for path in paths:
            try:
                stat = os.stat(path)
            except OSError:
                continue
            stamp = (stat.st_size, stat.st_mtime)
            cached = known.get(path)
            if cached is not None and cached[0] == stamp:
                files[path] = cached
                continue
            files[path] = (stamp, self.read(path))
            changed = True
        if set(files) != set(known):
            changed = True
        if changed:
            drivers: dict[str, list[RaceRecord]] = {}
            for _, records in files.values():
                for key, record in records.items():
                    drivers.setdefault(key, []).append(record)
            for driver_records in drivers.values():
                driver_records.sort(key=lambda record: record.time, reverse=True)
            with self._lock:
                if generation != self._generation:  # cleared meanwhile (page closed): nothing kept
                    return False
                self._files = files
                self._drivers = drivers
                self.version += 1
        return changed

    @staticmethod
    def read(path: str) -> dict[str, RaceRecord]:
        """Race of every driver of a file, empty if not readable (being written: read again once changed)"""
        try:
            result = rf.read_results(path, keep=False)  # bulk scan: only records kept
        except (OSError, ValueError):
            return {}
        if result.kind != "Race" or result.most_laps <= 0:
            return {}
        counts: dict[str, int] = {}
        for entry in result.entries:
            counts[entry.car_class] = counts.get(entry.car_class, 0) + 1
        records: dict[str, RaceRecord] = {}
        for entry in result.entries:
            record = RaceRecord(path, result.time, result.track, entry.car_class, entry.class_position,
                                entry.status.upper() == "FINISHED" or entry.finish_time > 0,
                                counts[entry.car_class])
            for name in {entry.name, *(swap.driver for swap in entry.swaps)}:
                if name:
                    records[fold(name)] = record
        return records

    def records(self, driver: str) -> list[RaceRecord]:
        with self._lock:
            return list(self._drivers.get(fold(driver), ()))

    def stats(self, driver: str, track: str = "", last: int = 3) -> DriverStats | None:
        """Races of a driver, None if none known"""
        records = self.records(driver)
        if not records:
            return None
        finished = [record for record in records if record.finished and record.class_position > 0]
        here = [record.class_position for record in finished if same_track(record.track, track)]
        return DriverStats(
            len(records), sum(1 for record in finished if record.class_position == 1),
            sum(1 for record in finished if record.class_position <= 3), min(here, default=0),
            tuple(records[:last]))

    def head_to_head(self, first: str, second: str) -> tuple[int, int]:
        """Races two drivers ran in the same class: how many times each finished ahead"""
        with self._lock:
            mine = {record.path: record for record in self._drivers.get(fold(first), ())}
            theirs = self._drivers.get(fold(second), ())
        ahead = behind = 0
        for record in theirs:
            other = mine.get(record.path)
            if other is None or other.car_class != record.car_class:
                continue
            first_place = other.class_position if other.finished else 10_000
            second_place = record.class_position if record.finished else 10_000
            if first_place < second_place:
                ahead += 1
            elif second_place < first_place:
                behind += 1
        return ahead, behind

    def clear(self) -> None:
        """Tables released (Broadcast Director page closed), read again on next scan"""
        with self._lock:
            self._generation += 1
            self._files = {}
            self._drivers = {}
            self.version += 1


def results_folders() -> tuple[str, ...]:
    """Results folders read (folder chosen on the race results page, else every game found)"""
    from ..setting import cfg

    return rf.results_folders(rf.chosen_results_folder(cfg.path.config))



history = DriverHistory()
