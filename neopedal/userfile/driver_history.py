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
Driver session history: one record per driving stint (track, vehicle, session, best lap, laps, result)

JSON lines appended by stats module at the end of each stint (driver.history in config folder), next
to cumulated driver stats (driver.stats). Read by driver stats viewer: last driven date, personal best
progression & date, sessions list. Read & written under driver_stats.STATS_LOCK (stats module thread &
viewer page).

Records read are kept (see read_records): file only appended since (stats module) has its new lines parsed
only, a rewritten file is parsed again.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from collections.abc import Callable, Iterable
from typing import NamedTuple

from ..const_common import MAX_SECONDS
from . import append_line, atomic_write
from .driver_stats import STATS_LOCK

logger = logging.getLogger(__name__)

HISTORY_FILE = "driver.history"
MAX_RECORDS = 50000  # oldest records dropped (file rewritten when loaded over limit)
MIN_SESSION_SECONDS = 60  # stint without lap shorter than this not recorded (garage exit...)
# Session filter: all, practice (test day, practice, warmup), qualifying, race
SESSION_GROUPS: tuple[tuple[int, ...], ...] = ((), (0, 1, 3), (2,), (4,))
TEXT_FIELDS = ("vehicle_class", "game_version")
TAIL_BYTES = 64 * 1024  # end of file read for last record (hundreds of records)
CHECK_BYTES = 512  # start of file & bytes before end of parsed lines compared: file only appended since
_last_records: dict[str, tuple[tuple[int, int], SessionRecord | None]] = {}  # path: file time & size, record
_parsed: dict[str, _ParsedFile] = {}  # path: records read (see read_records)
_parsed_lock = threading.Lock()  # one parse at a time (worker threads)
_cache_lock = threading.Lock()  # _parsed & generation, held briefly: never waits for a parse (UI thread)
_generation = 0  # records dropped (forget_records): parse running meanwhile keeps nothing


class SessionRecord(NamedTuple):
    """Driving stint, saved when back to garage or session changed"""

    time: float  # end of stint (seconds since epoch)
    track: str  # driver stats track key
    vehicle: str  # driver stats vehicle key
    session: int = 0  # 0 = test day, 1 = practice, 2 = qualify, 3 = warmup, 4 = race
    best: float = 0.0  # best valid lap time (seconds), 0 if none
    valid: int = 0
    invalid: int = 0
    meters: float = 0.0
    seconds: float = 0.0
    position: int = 0  # finish position (race), 0 if not finished
    finish: int = 0  # finish state: 0 = none, 1 = finished, 2 = DNF, 3 = DQ
    vehicle_class: str = ""  # game class name (vehicle key may be vehicle name only)
    game_version: str = ""  # game version when driven ("1.42"), "" if unknown (rF2, older records)


def history_path(filepath: str) -> str:
    return os.path.join(filepath, HISTORY_FILE)


def parse_record(data: object) -> SessionRecord | None:
    """Record from decoded JSON line, None if invalid"""
    if not isinstance(data, dict):
        return None
    track, vehicle = data.get("track"), data.get("vehicle")
    if not isinstance(track, str) or not isinstance(vehicle, str) or not track or not vehicle:
        return None
    values = {}
    for name, default in SessionRecord._field_defaults.items():
        value = data.get(name, default)
        if name in TEXT_FIELDS:
            value = value if isinstance(value, str) else default
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            value = default  # Infinity & NaN (accepted by json) too
        values[name] = type(default)(value)
    time_value = data.get("time")
    if (isinstance(time_value, bool) or not isinstance(time_value, (int, float)) or not math.isfinite(time_value)
            or time_value <= 0):
        return None
    return SessionRecord(time=float(time_value), track=track, vehicle=vehicle, **values)


class _ParsedFile(NamedTuple):
    """Records read from a history file: complete lines up to offset, last line without newline apart"""

    stamp: tuple[int, int, int]  # file id, size, modified time (ns)
    offset: int  # bytes of complete lines parsed (end of last newline)
    head: bytes  # first bytes of file (up to CHECK_BYTES before offset)
    tail: bytes  # bytes just before offset (up to CHECK_BYTES)
    lines: list[SessionRecord]  # records of complete lines, sorted
    records: list[SessionRecord]  # with record of unfinished last line, sorted


def by_time(record: SessionRecord) -> float:
    return record.time


def parse_lines(data: bytes) -> list[SessionRecord]:
    """Records of JSON lines in file order (invalid lines skipped), newlines as in text mode (\\n, \\r\\n, \\r)"""
    records = []
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    for line in text.split("\n"):
        if not line:
            continue
        try:
            record = parse_record(json.loads(line))
        except ValueError:  # half written line, edited file
            continue
        if record is not None:
            records.append(record)
    return records


def merged(records: list[SessionRecord], added: list[SessionRecord]) -> list[SessionRecord]:
    """Sorted records & records of following lines, as sorting all lines (equal times: file order)"""
    if not added:
        return records
    result = records + added
    if (records and added[0].time < records[-1].time) or any(
            added[index].time < added[index - 1].time for index in range(1, len(added))):
        result.sort(key=by_time)  # stable: equal times kept in file order
    return result


def kept_records(path: str) -> _ParsedFile | None:
    with _cache_lock:
        return _parsed.get(path)


def keep_records(path: str, parsed: _ParsedFile, generation: int) -> None:
    """Records kept unless dropped since generation (page closed meanwhile)"""
    with _cache_lock:
        if generation == _generation:
            _parsed[path] = parsed


def records_generation() -> int:
    with _cache_lock:
        return _generation


def parse_file(path: str) -> list[SessionRecord]:
    """Sorted records of file (_parsed_lock held): kept, only lines appended since parsed next time

    File appended (same file, larger, start & bytes before parsed end unchanged): new lines parsed,
    else (rewritten, edited) whole file parsed again.
    """
    generation = records_generation()
    with open(path, "rb") as file:
        stat = os.fstat(file.fileno())
        stamp = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
        cached = kept_records(path)
        if cached is not None and cached.stamp == stamp:
            return list(cached.records)
        lines: list[SessionRecord] = []
        offset = 0
        if (cached is not None and cached.stamp[0] == stamp[0] and cached.stamp[1] != stat.st_size
                and cached.offset <= stat.st_size and file.read(len(cached.head)) == cached.head):
            file.seek(cached.offset - len(cached.tail))
            if file.read(len(cached.tail)) == cached.tail:
                lines, offset = cached.lines, cached.offset
        file.seek(offset)
        added: list[SessionRecord] = []
        unfinished: list[SessionRecord] = []
        for line in file:
            if line.endswith(b"\n"):
                added += parse_lines(line)
                offset += len(line)
            else:  # last line being written (or no newline at end): parsed again next time
                unfinished = parse_lines(line)
        file.seek(0)
        head = file.read(min(offset, CHECK_BYTES))
        file.seek(max(offset - CHECK_BYTES, 0))
        tail = file.read(min(offset, CHECK_BYTES))
    lines = merged(lines, added)
    records = merged(lines, unfinished)
    keep_records(path, _ParsedFile(stamp, offset, head, tail, lines, records), generation)
    return list(records)


def forget_records(filepath: str = "") -> None:
    """Records kept for history file (all files if empty) dropped: memory freed (viewer closed)

    Never waits for a parse running (UI thread): that parse keeps nothing.
    """
    global _generation
    with _cache_lock:
        _generation += 1
        if filepath:
            _parsed.pop(history_path(filepath), None)
        else:
            _parsed.clear()


def read_records(filepath: str, strict: bool = False) -> list[SessionRecord]:
    """Session records of file, oldest first (invalid lines skipped, empty if no file)

    Bytes that are not UTF-8 replaced (line skipped if broken): a damaged file never stops the viewer.
    Records kept until file changes, lines appended since parsed only (see parse_file); list is a copy.

    Args:
        strict: raise OSError if file exists but unreadable (locked...), instead of empty records:
            file rewritten from records would lose all history.
    """
    path = history_path(filepath)
    with _parsed_lock:
        try:
            return parse_file(path)
        except FileNotFoundError:
            with _cache_lock:
                _parsed.pop(path, None)
            return []
        except OSError as error:
            logger.error("USERDATA: unable to read %s: %s", HISTORY_FILE, error)
            if strict:
                raise
            return []


def latest_record(lines: Iterable[bytes]) -> SessionRecord | None:
    """Newest valid record of JSON lines (latest time, last line of equal times: as read_records sorts)"""
    latest = None
    for line in lines:
        try:
            record = parse_record(json.loads(line.decode("utf-8", errors="replace")))
        except ValueError:  # half written line, cut line, empty line
            continue
        if record is not None and (latest is None or record.time >= latest.time):
            latest = record
    return latest


def last_record(filepath: str) -> SessionRecord | None:
    """Last driven session, as read_records(filepath)[-1], None if none

    Only end of file read (records appended in time order, file rewritten sorted), whole file if no valid
    record there; result kept until file changes (time & size).
    """
    path = history_path(filepath)
    try:
        stat = os.stat(path)
    except FileNotFoundError:
        return None
    except OSError as error:
        logger.error("USERDATA: unable to read %s: %s", HISTORY_FILE, error)
        return None
    key = (stat.st_mtime_ns, stat.st_size)
    cached = _last_records.get(path)
    if cached is not None and cached[0] == key:
        return cached[1]
    start = max(stat.st_size - TAIL_BYTES, 0)
    try:
        with open(path, "rb") as file:
            file.seek(start)
            lines = file.read().split(b"\n")
    except OSError as error:
        logger.error("USERDATA: unable to read %s: %s", HISTORY_FILE, error)
        return None
    if start > 0:
        del lines[0]  # cut line
    record = latest_record(lines)
    if record is None and start > 0:  # no valid record at end of file
        records = read_records(filepath)
        record = records[-1] if records else None
    _last_records[path] = (key, record)
    return record


def load_history(filepath: str, strict: bool = False) -> list[SessionRecord]:
    """Session records, oldest first, oldest dropped from file if over MAX_RECORDS (strict: see read_records)"""
    with STATS_LOCK:
        records = read_records(filepath, strict)
        if len(records) > MAX_RECORDS:
            records = records[-MAX_RECORDS:]
            write_records(filepath, records)
    return records


def record_line(record: SessionRecord) -> str:
    data = record._asdict()
    for name in ("best", "meters", "seconds"):
        data[name] = round(data[name], 3)
    for name in TEXT_FIELDS:
        if not data[name]:
            del data[name]
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"


def append_record(filepath: str, record: SessionRecord) -> None:
    """Add record at end of history file, on a line of its own (last line cut short by a crash stays apart)"""
    with STATS_LOCK:
        try:
            append_line(history_path(filepath), record_line(record).encode("utf-8"))
        except OSError as error:
            logger.error("USERDATA: unable to save %s: %s", HISTORY_FILE, error)


def write_records(filepath: str, records: Iterable[SessionRecord], raise_error: bool = False,
                  ) -> list[SessionRecord]:
    """Rewrite history file, records written returned (sorted, oldest over limit dropped)"""
    ordered = sorted(records, key=by_time)[-MAX_RECORDS:]
    path = history_path(filepath)
    with _cache_lock:
        generation = _generation
        _parsed.pop(path, None)
    text = "".join(record_line(record) for record in ordered)
    with atomic_write(path, raise_error=raise_error) as file:
        file.write(text)
    keep_written(path, text.replace("\n", os.linesep).encode("utf-8"), ordered, generation)
    return ordered


def as_read_back(record: SessionRecord) -> SessionRecord | None:
    """Record as parsed from its line (lap time, distance & driving time rounded), None if not read back alike"""
    if (not isinstance(record.track, str) or not isinstance(record.vehicle, str) or not record.track
            or not record.vehicle or not isinstance(record.time, (int, float)) or isinstance(record.time, bool)
            or not math.isfinite(record.time) or record.time <= 0):
        return None
    if any(type(getattr(record, name)) is not int for name in ("session", "valid", "invalid", "position", "finish")):
        return None
    if any(not isinstance(getattr(record, name), str) for name in TEXT_FIELDS):
        return None
    values = (record.best, record.meters, record.seconds)
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        return None
    rounded = tuple(round(float(value), 3) for value in values)
    if rounded != values or any(type(value) is not float for value in values):
        record = record._replace(best=rounded[0], meters=rounded[1], seconds=rounded[2])
    return record


def keep_written(path: str, data: bytes, records: list[SessionRecord], generation: int) -> None:
    """Records just written kept as parsed (next read parses nothing), if file holds data written (text mode
    newlines), every record reads back alike & records not dropped meanwhile"""
    kept = []
    for record in records:
        read_back = as_read_back(record)
        if read_back is None:
            return  # parsed again next time
        kept.append(read_back)
    try:
        with open(path, "rb") as file:
            stat = os.fstat(file.fileno())
            if stat.st_size != len(data):
                return  # not saved (error logged), or changed meanwhile
            head = file.read(min(len(data), CHECK_BYTES))
            file.seek(max(len(data) - CHECK_BYTES, 0))
            tail = file.read(CHECK_BYTES)
    except OSError:
        return
    if head != data[:CHECK_BYTES] or tail != data[-CHECK_BYTES:]:
        return
    keep_records(path, _ParsedFile((stat.st_ino, stat.st_size, stat.st_mtime_ns), len(data), head, tail, kept,
                                   kept), generation)


def save_history(filepath: str, records: Iterable[SessionRecord]) -> None:
    """Rewrite history file, oldest first, oldest records over limit dropped"""
    with STATS_LOCK:
        write_records(filepath, records)


def remove_records(filepath: str, match: Callable[[SessionRecord], bool]) -> list[SessionRecord]:
    """Remove matching records from history file, removed records returned (to restore them)

    Raises:
        OSError: history file unreadable or not saved (file kept as it was).
    """
    with STATS_LOCK:
        records = read_records(filepath, strict=True)
        removed = [record for record in records if match(record)]
        if removed:
            write_records(filepath, [record for record in records if not match(record)], raise_error=True)
    return removed


def replace_records(filepath: str, removed: Iterable[SessionRecord], added: Iterable[SessionRecord],
                    records: Iterable[SessionRecord] | None = None) -> list[SessionRecord] | None:
    """Remove records & add others (undo, redo of an edit), records already there kept once

    Args:
        records: records of file loaded already (STATS_LOCK held since), else file read.

    Returns:
        Records written, None if nothing to change.

    Raises:
        OSError: history file unreadable or not saved (file kept as it was, never rewritten as empty).
    """
    removed_set = set(removed)
    added = list(added)
    if not removed_set and not added:
        return None
    with STATS_LOCK:
        if records is None:
            records = read_records(filepath, strict=True)
        current = [record for record in records if record not in removed_set]
        known = set(current)
        return write_records(filepath, current + [record for record in added if record not in known],
                             raise_error=True)


def restore_records(filepath: str, records: list[SessionRecord]) -> None:
    """Put removed records back in history file (undo), records already there kept once"""
    replace_records(filepath, (), records)


def worth_recording(valid: int, invalid: int, seconds: float) -> bool:
    """Stint recorded in history: a lap completed, or driven long enough"""
    return valid + invalid > 0 or seconds >= MIN_SESSION_SECONDS


def session_record(
    track: str, vehicle: str, session: int, best: float, valid: int, invalid: int,
    meters: float, seconds: float, position: int, finish: int, time: float, vehicle_class: str = "",
    game_version: str = "",
) -> SessionRecord:
    """Record of a driving stint, invalid best lap time (none) saved as 0"""
    return SessionRecord(
        time=time, track=track, vehicle=vehicle, session=session,
        best=best if 0 < best < MAX_SECONDS else 0.0,
        valid=valid, invalid=invalid, meters=meters, seconds=seconds,
        position=position, finish=finish, vehicle_class=vehicle_class, game_version=game_version,
    )


def index_history(records: Iterable[SessionRecord]) -> dict[tuple[str, str], list[SessionRecord]]:
    """Records of each (track, vehicle), oldest first"""
    index: dict[tuple[str, str], list[SessionRecord]] = {}
    for record in records:
        index.setdefault((record.track, record.vehicle), []).append(record)
    return index


def vehicle_classes(records: Iterable[SessionRecord]) -> dict[str, str]:
    """Game class of each vehicle key, from latest record that has it"""
    return {record.vehicle: record.vehicle_class for record in records if record.vehicle_class}


def last_driven(records: Iterable[SessionRecord]) -> dict[tuple[str, str], float]:
    """Last driven time of each (track, vehicle)"""
    result: dict[tuple[str, str], float] = {}
    for record in records:
        key = (record.track, record.vehicle)
        if record.time > result.get(key, 0.0):
            result[key] = record.time
    return result


def track_last_driven(records: Iterable[SessionRecord]) -> dict[str, float]:
    """Last driven time of each track"""
    result: dict[str, float] = {}
    for record in records:
        if record.time > result.get(record.track, 0.0):
            result[record.track] = record.time
    return result


def filter_sessions(records: Iterable[SessionRecord], group: int) -> list[SessionRecord]:
    """Records of a session group (SESSION_GROUPS index, 0 = all)"""
    sessions = SESSION_GROUPS[group] if 0 < group < len(SESSION_GROUPS) else ()
    return [record for record in records if not sessions or record.session in sessions]


def is_reset_best(record: SessionRecord, best: float) -> bool:
    """Session best faster than personal best now: lap time reset in viewer since"""
    return best > 0 and 0 < record.best < best - 0.0005


def best_progression(records: Iterable[SessionRecord], best: float = 0.0) -> list[tuple[SessionRecord, float]]:
    """Sessions with a lap time, oldest first, each with personal best so far

    Args:
        best: personal best now, faster session bests (lap time reset since) left out.
    """
    progression = []
    best_so_far = 0.0
    for record in sorted(records, key=lambda record: record.time):
        if record.best <= 0 or is_reset_best(record, best):
            continue
        if not best_so_far or record.best < best_so_far:
            best_so_far = record.best
        progression.append((record, best_so_far))
    return progression


def best_lap_date(records: Iterable[SessionRecord], best: float) -> float:
    """Time of first session with personal best lap time, 0 if not in history"""
    if best <= 0:
        return 0.0
    for record in sorted(records, key=lambda record: record.time):
        if 0 < record.best <= best + 0.0005 and not is_reset_best(record, best):
            return record.time
    return 0.0
