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
Loaded laps kept in binary form (lap viewer): reading a lap again takes a few ms instead of parsing its CSV

One file per lap in a hidden folder of telemetry folder, found by lap file path, valid while lap file
size & modification time are the same (and cache format version). Oldest files removed over size limit.

File format (also used for track limits parts, see lap_geometry): magic, format version & JSON header length,
JSON header (values, then name, type & length of each array), then raw little endian arrays. Plain data only:
a cache file from a shared telemetry folder never runs code (older pickled caches are ignored & rebuilt).
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import os
import struct
import sys
import threading
import time
from array import array
from collections.abc import Mapping, Sequence
from contextlib import suppress
from typing import Any

from .telemetry_lap import EXACT_COLUMNS, Column, LapData, LapFile, column_type, load_lap, read_lap_info

logger = logging.getLogger(__name__)

CACHE_FOLDER = ".lap_cache"  # in telemetry folder (hidden: not a track)
INFO_FOLDER = "info"  # in lap cache folder: lap infos of each lap folder (first line of lap files), see indexed_infos
INFO_READERS = 8  # threads reading infos of new lap files (first open of a file waits for antivirus scan)
_index_lock = threading.Lock()  # info index saved by one thread at a time (newest index written last)
PARSED_INDEXES = 16  # lap infos indexes kept parsed (file stamp checked)
_parsed_indexes: dict[str, tuple[tuple[int, int], dict]] = {}  # index path: file stamp, parsed index
_parsed_lock = threading.Lock()
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


FileStamp = tuple[int, int, float]  # lap file size, modification time (ns) & modification time (s)
IndexedInfos = tuple[dict[str, FileStamp], dict, dict[str, dict], list[LapFile]]


def info_index_path(folder: str, name: str) -> str:
    """Lap infos index of a lap folder (track folder name, imported log group...) of telemetry folder"""
    return os.path.join(folder, CACHE_FOLDER, INFO_FOLDER, f"{name}.json")


def index_stamp(path: str) -> tuple[int, int] | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def read_index(path: str) -> dict:
    """Saved lap infos index (empty if none or damaged), parsed once while its file stays the same (shared: never
    changed by callers)"""
    stamp = index_stamp(path)
    if stamp is None:
        return {}
    with _parsed_lock:
        cached = _parsed_indexes.get(path)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    saved: Any = {}
    with suppress(OSError, ValueError), open(path, encoding="utf-8") as file:
        saved = json.load(file)
    saved = saved if isinstance(saved, dict) else {}  # damaged index ignored
    keep_parsed(path, stamp, saved)
    return saved


def keep_parsed(path: str, stamp: tuple[int, int] | None, index: dict):
    if stamp is None:
        return
    with _parsed_lock:
        _parsed_indexes.pop(path, None)
        _parsed_indexes[path] = (stamp, index)
        while len(_parsed_indexes) > PARSED_INDEXES:
            _parsed_indexes.pop(next(iter(_parsed_indexes)))


def indexed_infos(lap_folder: str, index_path: str, laps: Sequence[LapFile],
                  memory: Mapping[str, tuple[float, dict]] | None = None) -> IndexedInfos:
    """Lap file stamps of lap folder, saved index, infos known (memory: lap path: file time & info, or index) & laps
    whose info must be read from file (no lap file opened: one directory scan & index file read)"""
    stamps: dict[str, FileStamp] = {}
    if not laps:
        return stamps, {}, {}, []
    with suppress(OSError), os.scandir(lap_folder) as found:
        for item in found:
            stat = item.stat()
            stamps[item.name] = (stat.st_size, stat.st_mtime_ns, stat.st_mtime)
    saved = read_index(index_path)
    known: dict[str, dict] = {}
    missing: list[LapFile] = []
    memory = memory or {}
    for lap in laps:
        stamp = stamps.get(lap.filename)
        if stamp is None:  # removed meanwhile
            continue
        cached = memory.get(lap.path)
        indexed = saved.get(lap.filename)
        if cached is not None and cached[0] == stamp[2]:
            known[lap.filename] = cached[1]
        elif (isinstance(indexed, list) and len(indexed) == 3 and indexed[:2] == list(stamp[:2])
              and isinstance(indexed[2], dict)):
            known[lap.filename] = indexed[2]
        else:
            missing.append(lap)
    return stamps, saved, known, missing


def read_infos(paths: Sequence[str]) -> list[tuple[str, float, dict] | None]:
    """Path, file time & lap info of each lap file (None if removed), files read together: each new file is scanned
    by antivirus on first open (thread job)"""

    def read(path: str) -> tuple[str, float, dict] | None:
        try:
            mtime = os.path.getmtime(path)
        except OSError:  # removed meanwhile
            return None
        return path, mtime, read_lap_info(path)

    if len(paths) <= 2:
        return [read(path) for path in paths]
    with concurrent.futures.ThreadPoolExecutor(INFO_READERS, "Lap infos") as pool:
        return list(pool.map(read, paths))


def save_info_index(path: str, index: dict):
    """Lap infos of a lap folder saved atomically (temporary file renamed): never read half written, one save at a
    time (thread jobs)"""
    with _index_lock:
        _write_index(path, index)


def save_pending_index(path: str, pending: dict[str, dict]):
    """Newest index of path waiting in pending saved (thread job), nothing if a job started later saved it already"""
    with _index_lock:
        index = pending.pop(path, None)
        if index is not None:
            _write_index(path, index)


def _write_index(path: str, index: dict):
    temp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(temp, "w", encoding="utf-8", newline="\n") as file:
            json.dump(index, file, separators=(",", ":"))
        os.replace(temp, path)
        keep_parsed(path, index_stamp(path), index)  # read back without parsing
    except (OSError, TypeError, ValueError) as error:
        logger.warning("LAP CACHE: unable to save lap infos index: %s", error)
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
