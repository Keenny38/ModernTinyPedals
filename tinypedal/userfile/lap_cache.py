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

File format (also used for track limits parts, see lap_geometry): magic, format version & JSON header length,
JSON header (values, then name, type & length of each array), then raw little endian arrays. Plain data only:
a cache file from a shared telemetry folder never runs code (older pickled caches are ignored & rebuilt).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import struct
import sys
import threading
import time
from array import array
from collections.abc import Mapping
from contextlib import suppress

from .telemetry_lap import EXACT_COLUMNS, Column, LapData, column_type, load_lap

logger = logging.getLogger(__name__)

CACHE_FOLDER = ".lap_cache"  # in telemetry folder (hidden: not a track)
CACHE_VERSION = 3  # loaded lap processing or file format changed: cached laps read again from CSV
CACHE_LIMIT = 600 * 1024 * 1024  # bytes kept, oldest used removed over it
STALE_TEMP = 600  # seconds, older temporary files are left over from a crash (newer ones may be written now)
ARRAYS_MAGIC = b"TPLA"  # arrays file: header & packed arrays
ARRAYS_FORMAT = 1
ARRAYS_HEAD = struct.Struct("<4sII")  # magic, format version, JSON header length
ARRAY_TYPES = ("d", "f", "i")  # array type codes stored (8, 4 & 4 bytes)
MAX_HEADER = 16 * 1024 * 1024  # bytes, larger header: not an arrays file
__all__ = ("EXACT_COLUMNS", "load_cached_lap", "prune_cache", "read_arrays_file", "remove_cached_lap",
           "write_arrays_file")


def cache_file(folder: str, path: str) -> str:
    """Cache file of lap file"""
    name = hashlib.sha1(os.path.normcase(os.path.abspath(path)).encode("utf-8")).hexdigest()
    return os.path.join(folder, CACHE_FOLDER, f"{name}.bin")


def file_stamp(path: str) -> tuple[int, int]:
    stat = os.stat(path)
    return stat.st_size, stat.st_mtime_ns


def write_arrays_file(target: str, values: dict, arrays: Mapping[str, array]):
    """Write values (JSON) & packed arrays to file atomically (temporary file renamed), raises OSError"""
    names = list(arrays)
    header = json.dumps({"values": values, "arrays": [
        [name, arrays[name].typecode, len(arrays[name])] for name in names]}).encode("utf-8")
    temp = f"{target}.{os.getpid()}.{threading.get_ident()}.tmp"  # threads & processes never share one
    try:
        with open(temp, "wb") as file:
            file.write(ARRAYS_HEAD.pack(ARRAYS_MAGIC, ARRAYS_FORMAT, len(header)))
            file.write(header)
            for name in names:
                values_array = arrays[name]
                if sys.byteorder != "little":
                    values_array = array(values_array.typecode, values_array)
                    values_array.byteswap()
                file.write(values_array.tobytes())
        os.replace(temp, target)
    except OSError:
        with suppress(OSError):
            os.remove(temp)
        raise


def read_arrays_file(path: str) -> tuple[dict, dict[str, array]] | None:
    """Values & packed arrays of file written by write_arrays_file, None if missing, damaged or another format"""
    try:
        with open(path, "rb") as file:
            data = file.read()
    except OSError:
        return None
    if len(data) < ARRAYS_HEAD.size:
        return None
    magic, version, size = ARRAYS_HEAD.unpack_from(data, 0)
    if magic != ARRAYS_MAGIC or version != ARRAYS_FORMAT or size > min(MAX_HEADER, len(data) - ARRAYS_HEAD.size):
        return None
    offset = ARRAYS_HEAD.size + size
    try:
        header = json.loads(data[ARRAYS_HEAD.size:offset].decode("utf-8"))
        values, entries = header["values"], header["arrays"]
        if not isinstance(values, dict) or not isinstance(entries, list):
            return None
        arrays: dict[str, array] = {}
        view = memoryview(data)
        for name, typecode, count in entries:
            if typecode not in ARRAY_TYPES or not isinstance(count, int) or count < 0:
                return None
            column = array(typecode)
            end = offset + count * column.itemsize
            if end > len(data):
                return None
            column.frombytes(view[offset:end])
            if sys.byteorder != "little":
                column.byteswap()
            arrays[str(name)] = column
            offset = end
    except (ValueError, TypeError, KeyError):  # UnicodeDecodeError & JSON errors are ValueError
        return None
    return values, arrays


def load_cached_lap(folder: str, path: str) -> LapData:
    """Lap from cache if lap file did not change, else loaded from CSV & cached, raises OSError or ValueError"""
    stamp = file_stamp(path)
    target = cache_file(folder, path) if folder else ""
    if target:
        found = read_arrays_file(target)
        if found is not None:
            values, arrays = found
            info = values.get("info")
            if (values.get("version") == CACHE_VERSION and values.get("stamp") == list(stamp)
                    and isinstance(values.get("name"), str) and isinstance(info, (dict, type(None)))
                    and all(column.typecode == column_type(name) for name, column in arrays.items())):
                with suppress(OSError):
                    os.utime(target)  # recently used: kept when pruning
                columns: dict[str, Column] = dict(arrays)
                return LapData(values["name"], columns, info)  # packed arrays kept
    lap = load_lap(path)
    if target:
        save_cached_lap(target, stamp, lap)
    return lap


def save_cached_lap(target: str, stamp: tuple[int, int], lap: LapData):
    """Write lap cache file atomically (laps loaded in threads)"""
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        write_arrays_file(target, {"version": CACHE_VERSION, "stamp": list(stamp), "name": lap.name, "info": lap.info},
                          {name: values if isinstance(values, array) and values.typecode == column_type(name)
                           else array(column_type(name), values) for name, values in lap.columns.items()})
    except (OSError, OverflowError, TypeError, ValueError) as error:
        logger.debug("LAP CACHE: unable to save %s: %s", target, error)


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
