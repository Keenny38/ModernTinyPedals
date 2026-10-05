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
Loaded laps kept in binary form (lap viewer): reading a lap again takes a few ms instead of parsing its CSV

One file per lap in a hidden folder of telemetry folder, found by lap file path, valid while lap file
size & modification time are the same (and cache format version). Oldest files removed over size limit.
"""

from __future__ import annotations

import hashlib
import logging
import os
import pickle
import threading
import time
from array import array
from contextlib import suppress

from .telemetry_lap import EXACT_COLUMNS, LapData, column_type, load_lap

logger = logging.getLogger(__name__)

CACHE_FOLDER = ".lap_cache"  # in telemetry folder (hidden: not a track)
CACHE_VERSION = 2  # loaded lap processing changed: cached laps read again from CSV
CACHE_LIMIT = 600 * 1024 * 1024  # bytes kept, oldest used removed over it
STALE_TEMP = 600  # seconds, older temporary files are left over from a crash (newer ones may be written now)
__all__ = ("EXACT_COLUMNS", "load_cached_lap", "prune_cache", "remove_cached_lap")


def cache_file(folder: str, path: str) -> str:
    """Cache file of lap file"""
    name = hashlib.sha1(os.path.normcase(os.path.abspath(path)).encode("utf-8")).hexdigest()
    return os.path.join(folder, CACHE_FOLDER, f"{name}.bin")


def file_stamp(path: str) -> tuple[int, int]:
    stat = os.stat(path)
    return stat.st_size, stat.st_mtime_ns


def load_cached_lap(folder: str, path: str) -> LapData:
    """Lap from cache if lap file did not change, else loaded from CSV & cached, raises OSError or ValueError"""
    stamp = file_stamp(path)
    target = cache_file(folder, path) if folder else ""
    if target:
        with suppress(OSError, ValueError, EOFError, pickle.UnpicklingError, KeyError, TypeError, AttributeError):
            with open(target, "rb") as file:
                saved = pickle.load(file)
            if saved["version"] == CACHE_VERSION and tuple(saved["stamp"]) == stamp:
                with suppress(OSError):
                    os.utime(target)  # recently used: kept when pruning
                return LapData(saved["name"], dict(saved["columns"]), saved["info"])  # packed arrays kept
    lap = load_lap(path)
    if target:
        save_cached_lap(target, stamp, lap)
    return lap


def save_cached_lap(target: str, stamp: tuple[int, int], lap: LapData):
    """Write lap cache file atomically (laps loaded in threads)"""
    temp = f"{target}.{os.getpid()}.{threading.get_ident()}.tmp"  # threads & processes never share one
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(temp, "wb") as file:
            pickle.dump({
                "version": CACHE_VERSION, "stamp": stamp, "name": lap.name, "info": lap.info,
                "columns": {name: values if isinstance(values, array) and values.typecode == column_type(name)
                            else array(column_type(name), values) for name, values in lap.columns.items()},
            }, file, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(temp, target)
    except (OSError, OverflowError, TypeError) as error:
        logger.debug("LAP CACHE: unable to save %s: %s", target, error)
        with suppress(OSError):
            os.remove(temp)


def remove_cached_lap(folder: str, path: str):
    """Forget cached lap (lap file deleted)"""
    with suppress(OSError):
        os.remove(cache_file(folder, path))


def prune_cache(folder: str, limit: int = CACHE_LIMIT) -> int:
    """Remove least recently used cache files over size limit, returns number removed"""
    root = os.path.join(folder, CACHE_FOLDER)
    try:
        entries = [entry for entry in os.scandir(root) if entry.is_file()]
    except OSError:
        return 0
    files = []
    for entry in entries:
        with suppress(OSError):
            stat = entry.stat()
            files.append((stat.st_mtime, stat.st_size, entry.path))
    files.sort(reverse=True)  # newest first
    total = removed = 0
    stale = time.time() - STALE_TEMP
    for modified, size, path in files:
        if path.endswith(".tmp"):
            if modified < stale:
                with suppress(OSError):
                    os.remove(path)
                    removed += 1
            continue
        total += size
        if total > limit:
            with suppress(OSError):
                os.remove(path)
                removed += 1
    return removed
