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
from collections.abc import Iterator, Mapping, Sequence
from contextlib import suppress
from typing import Any

from . import atomic_replace, write_json
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
# Lap columns read at once from cache file (charts, map, driving points & corners of a lap viewer page shown with
# default channels), others when first used (see CachedColumns)
EAGER_COLUMNS = (
    "time", "lap_time", "distance", "speed_kph", "throttle", "brake", "steering", "gear", "sector",
    "pos_x", "pos_y", "pos_z", "accel_lat", "accel_long", "path_lateral", "track_edge", "yaw",
    "tc_level", "abs_level", "engine_map",
    *(f"{name}_{wheel}" for name in ("wheel_speed", "ride_height", "surface") for wheel in ("fl", "fr", "rl", "rr")),
)
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


def write_arrays_file(target: str, values: dict, arrays: Mapping[str, array]) -> None:
    """Write values (JSON) & packed arrays to file atomically (temporary file renamed), raises OSError"""
    names = list(arrays)
    header = json.dumps({"values": values, "arrays": [
        [name, arrays[name].typecode, len(arrays[name])] for name in names]}).encode("utf-8")
    parts = [ARRAYS_HEAD.pack(ARRAYS_MAGIC, ARRAYS_FORMAT, len(header)), header]
    for name in names:
        values_array = arrays[name]
        if sys.byteorder != "little":
            values_array = array(values_array.typecode, values_array)
            values_array.byteswap()
        parts.append(values_array.tobytes())
    atomic_replace(target, b"".join(parts), fsync=False)  # cache: rebuilt if lost


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


def wheel_group(name: str) -> str:
    """Columns read together from a cache file: the 4 wheels of a wheel column (tyre_temp_fl...), else column alone"""
    return name[:-3] if name[-3:-2] == "_" and name[-2:] in ("fl", "fr", "rl", "rr") else name


class CachedColumns(Mapping[str, Column]):
    """Lap columns of a cache file, each read from file when first used (whole lap: several MB, a lap viewer
    page uses about a third of its columns), EAGER_COLUMNS at once

    Missing columns are read under a lock (lap read by page & background threads), wheel columns 4 at a time
    (one file read per panel). Cache file changed or removed meanwhile (pruned, lap file changed): read again
    from lap file. Pickled (worker process) with columns read so far, others read there from file.
    """

    __slots__ = ("_target", "_file", "_lap_path", "_entries", "_loaded", "_lock")

    def __init__(self, target: str, file: tuple[int, int], lap_path: str,
                 entries: dict[str, tuple[int, str, int]], loaded: dict[str, Column]):
        self._target = target  # cache file
        self._file = file  # cache file size & modification time when entries were read
        self._lap_path = lap_path
        self._entries = entries  # column name: offset in file, array type code, value count
        self._loaded = loaded
        self._lock = threading.Lock()

    def __getitem__(self, name: str) -> Column:
        column = self._loaded.get(name)
        if column is not None:
            return column
        if name not in self._entries:
            raise KeyError(name)
        with self._lock:
            if name not in self._loaded:
                group = wheel_group(name)
                self.read_columns([key for key in self._entries
                                   if key not in self._loaded and (key == name or wheel_group(key) == group)])
            return self._loaded[name]

    def __contains__(self, name: object) -> bool:
        return name in self._entries

    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __reduce__(self) -> tuple:
        with self._lock:
            loaded = dict(self._loaded)
        return CachedColumns, (self._target, self._file, self._lap_path, self._entries, loaded)

    def read_columns(self, names: list[str]) -> None:
        """Read columns from cache file (lock held), from lap file if cache file changed"""
        try:
            with open(self._target, "rb") as file:
                stat = os.fstat(file.fileno())
                if (stat.st_size, stat.st_mtime_ns) == self._file:
                    for name in names:
                        offset, typecode, count = self._entries[name]
                        column = array(typecode)
                        file.seek(offset)
                        column.frombytes(file.read(count * column.itemsize))
                        if len(column) != count:
                            raise ValueError("cache file cut short")
                        if sys.byteorder != "little":
                            column.byteswap()
                        self._loaded[name] = column
                    return
        except (OSError, ValueError) as error:
            logger.debug("LAP CACHE: %s not read from cache: %s", self._lap_path, error)
        self.read_from_lap(names)

    def read_from_lap(self, names: list[str]) -> None:
        """Columns read from lap file (cache file gone), zeros if lap file changed meanwhile (other samples)"""
        try:
            columns = load_lap(self._lap_path).columns
        except (OSError, ValueError) as error:
            logger.warning("LAP CACHE: unable to read %s again: %s", self._lap_path, error)
            columns = {}
        for name in self._entries:  # every missing column at once: lap file parsed once
            if name in self._loaded:
                continue
            _, typecode, count = self._entries[name]
            values = columns.get(name)
            self._loaded[name] = (array(typecode, values) if values is not None and len(values) == count
                                  else array(typecode, bytes(count * array(typecode).itemsize)))


def read_cached_lap(target: str, stamp: tuple[int, int], lap_path: str) -> LapData | None:
    """Lap of cache file if made from lap file of stamp (columns read when used, EAGER_COLUMNS now), else None"""
    try:
        with open(target, "rb") as file:
            stat = os.fstat(file.fileno())
            head = file.read(ARRAYS_HEAD.size)
            if len(head) < ARRAYS_HEAD.size:
                return None
            magic, version, size = ARRAYS_HEAD.unpack(head)
            if magic != ARRAYS_MAGIC or version != ARRAYS_FORMAT or size > min(MAX_HEADER, stat.st_size):
                return None
            header = json.loads(file.read(size).decode("utf-8"))
            values, listed = header["values"], header["arrays"]
            info = values.get("info")
            if (not isinstance(values, dict) or values.get("version") != CACHE_VERSION
                    or values.get("stamp") != list(stamp) or not isinstance(values.get("name"), str)
                    or not isinstance(info, (dict, type(None))) or not isinstance(listed, list)):
                return None
            entries: dict[str, tuple[int, str, int]] = {}
            offset = ARRAYS_HEAD.size + size
            for name, typecode, count in listed:
                if typecode != column_type(name) or not isinstance(count, int) or count < 0:
                    return None
                entries[str(name)] = (offset, typecode, count)
                offset += count * array(typecode).itemsize
            if offset > stat.st_size:
                return None
            columns = CachedColumns(target, (stat.st_size, stat.st_mtime_ns), lap_path, entries, {})
            eager = [name for name in EAGER_COLUMNS if name in entries]
            columns.read_columns(eager)
    except (OSError, ValueError, TypeError, KeyError):  # UnicodeDecodeError & JSON errors are ValueError
        return None
    with suppress(OSError):
        os.utime(target)  # recently used: kept when pruning
    return LapData(values["name"], columns, info)


def load_cached_lap(folder: str, path: str) -> LapData:
    """Lap from cache if lap file did not change, else loaded from CSV & cached, raises OSError or ValueError

    Lap from cache file reads its columns when used (see CachedColumns).
    """
    stamp = file_stamp(path)
    target = cache_file(folder, path) if folder else ""
    if target:
        lap = read_cached_lap(target, stamp, path)
        if lap is not None:
            return lap
    lap = load_lap(path)
    if target and save_cached_lap(target, stamp, lap):
        return read_cached_lap(target, stamp, path) or lap  # columns parsed now released, read again when used
    return lap


def save_cached_lap(target: str, stamp: tuple[int, int], lap: LapData) -> bool:
    """Write lap cache file atomically (laps loaded in threads), returns whether written"""
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        write_arrays_file(target, {"version": CACHE_VERSION, "stamp": list(stamp), "name": lap.name, "info": lap.info},
                          {name: values if isinstance(values, array) and values.typecode == column_type(name)
                           else array(column_type(name), values) for name, values in lap.columns.items()})
    except (OSError, OverflowError, TypeError, ValueError) as error:
        logger.debug("LAP CACHE: unable to save %s: %s", target, error)
        return False
    return True


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


def keep_parsed(path: str, stamp: tuple[int, int] | None, index: dict) -> None:
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


def save_info_index(path: str, index: dict) -> None:
    """Lap infos of a lap folder saved atomically (temporary file renamed): never read half written, one save at a
    time (thread jobs)"""
    with _index_lock:
        _write_index(path, index)


def save_pending_index(path: str, pending: dict[str, dict]) -> None:
    """Newest index of path waiting in pending saved (thread job), nothing if a job started later saved it already"""
    with _index_lock:
        index = pending.pop(path, None)
        if index is not None:
            _write_index(path, index)


def _write_index(path: str, index: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_json(path, index, newline="\n", raise_error=True, separators=(",", ":"))
        keep_parsed(path, index_stamp(path), index)  # read back without parsing
    except (OSError, TypeError, ValueError) as error:
        logger.warning("LAP CACHE: unable to save lap infos index: %s", error)


def remove_cached_lap(folder: str, path: str) -> None:
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
