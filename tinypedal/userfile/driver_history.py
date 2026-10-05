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
Driver session history: one record per driving stint (track, vehicle, session, best lap, laps, result)

JSON lines appended by stats module at the end of each stint (driver.history in config folder), next
to cumulated driver stats (driver.stats). Read by driver stats viewer: last driven date, personal best
progression & date, sessions list. Read & written under driver_stats.STATS_LOCK (stats module thread &
viewer page).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterable
from typing import NamedTuple

from ..const_common import MAX_SECONDS
from . import atomic_write
from .driver_stats import STATS_LOCK

logger = logging.getLogger(__name__)

HISTORY_FILE = "driver.history"
MAX_RECORDS = 50000  # oldest records dropped (file rewritten when loaded over limit)
MIN_SESSION_SECONDS = 60  # stint without lap shorter than this not recorded (garage exit...)
# Session filter: all, practice (test day, practice, warmup), qualifying, race
SESSION_GROUPS: tuple[tuple[int, ...], ...] = ((), (0, 1, 3), (2,), (4,))
TEXT_FIELDS = ("vehicle_class",)


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


def history_path(filepath: str) -> str:
    return os.path.join(filepath, HISTORY_FILE)


def parse_record(data) -> SessionRecord | None:
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
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            value = default
        values[name] = type(default)(value)
    time_value = data.get("time")
    if isinstance(time_value, bool) or not isinstance(time_value, (int, float)) or time_value <= 0:
        return None
    return SessionRecord(time=float(time_value), track=track, vehicle=vehicle, **values)


def read_records(filepath: str) -> list[SessionRecord]:
    """Session records of file, oldest first (invalid lines skipped, empty if no file)"""
    records = []
    try:
        with open(history_path(filepath), encoding="utf-8") as file:
            for line in file:
                try:
                    record = parse_record(json.loads(line))
                except ValueError:  # half written line, edited file
                    continue
                if record is not None:
                    records.append(record)
    except FileNotFoundError:
        return []
    except OSError as error:
        logger.error("USERDATA: unable to read %s: %s", HISTORY_FILE, error)
        return []
    records.sort(key=lambda record: record.time)
    return records


def load_history(filepath: str) -> list[SessionRecord]:
    """Session records, oldest first, oldest dropped from file if over MAX_RECORDS"""
    with STATS_LOCK:
        records = read_records(filepath)
        if len(records) > MAX_RECORDS:
            records = records[-MAX_RECORDS:]
            write_records(filepath, records)
    return records


def record_line(record: SessionRecord) -> str:
    data = record._asdict()
    for name in ("best", "meters", "seconds"):
        data[name] = round(data[name], 3)
    if not data["vehicle_class"]:
        del data["vehicle_class"]
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"


def append_record(filepath: str, record: SessionRecord) -> None:
    """Add record at end of history file"""
    with STATS_LOCK:
        try:
            with open(history_path(filepath), "a", encoding="utf-8") as file:
                file.write(record_line(record))
        except OSError as error:
            logger.error("USERDATA: unable to save %s: %s", HISTORY_FILE, error)


def write_records(filepath: str, records: Iterable[SessionRecord]) -> None:
    ordered = sorted(records, key=lambda record: record.time)[-MAX_RECORDS:]
    with atomic_write(history_path(filepath)) as file:
        file.writelines(record_line(record) for record in ordered)


def save_history(filepath: str, records: Iterable[SessionRecord]) -> None:
    """Rewrite history file, oldest first, oldest records over limit dropped"""
    with STATS_LOCK:
        write_records(filepath, records)


def remove_records(filepath: str, match: Callable[[SessionRecord], bool]) -> list[SessionRecord]:
    """Remove matching records from history file, removed records returned (to restore them)"""
    with STATS_LOCK:
        records = read_records(filepath)
        removed = [record for record in records if match(record)]
        if removed:
            write_records(filepath, [record for record in records if not match(record)])
    return removed


def replace_records(filepath: str, removed: Iterable[SessionRecord], added: Iterable[SessionRecord]) -> None:
    """Remove records & add others (undo, redo of an edit), records already there kept once"""
    removed_set = set(removed)
    added = list(added)
    if not removed_set and not added:
        return
    with STATS_LOCK:
        current = [record for record in read_records(filepath) if record not in removed_set]
        known = set(current)
        write_records(filepath, current + [record for record in added if record not in known])


def restore_records(filepath: str, records: list[SessionRecord]) -> None:
    """Put removed records back in history file (undo), records already there kept once"""
    replace_records(filepath, (), records)


def worth_recording(valid: int, invalid: int, seconds: float) -> bool:
    """Stint recorded in history: a lap completed, or driven long enough"""
    return valid + invalid > 0 or seconds >= MIN_SESSION_SECONDS


def session_record(
    track: str, vehicle: str, session: int, best: float, valid: int, invalid: int,
    meters: float, seconds: float, position: int, finish: int, time: float, vehicle_class: str = "",
) -> SessionRecord:
    """Record of a driving stint, invalid best lap time (none) saved as 0"""
    return SessionRecord(
        time=time, track=track, vehicle=vehicle, session=session,
        best=best if 0 < best < MAX_SECONDS else 0.0,
        valid=valid, invalid=invalid, meters=meters, seconds=seconds,
        position=position, finish=finish, vehicle_class=vehicle_class,
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
