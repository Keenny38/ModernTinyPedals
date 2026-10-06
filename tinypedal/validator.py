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
Validator function
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Iterable
from functools import wraps
from math import isfinite
from time import monotonic
from typing import Any

from .const_common import MAX_SECONDS
from .const_file import FileExt
from .regex_pattern import CFG_INVALID_FILENAME, rex_hex_color

logger = logging.getLogger(__name__)

SESSION_START_TOLERANCE = 2.0  # seconds, session start time from whole elapsed seconds


# Decorator
def generator_init(func):
    """Initialize generator for send() method, returns None if StopIteration"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        generator = func(*args, **kwargs)
        try:
            next(generator)
        except StopIteration:
            generator = None
        return generator
    return wrapper


# Value validate
def infnan_to_zero(value: Any) -> float:
    """Convert invalid value (inf or nan) to zero"""
    if isfinite(value):
        return value
    return 0


def bytes_to_str(bytestring: bytes | Any, char_encoding: str = "utf-8") -> str:
    """Convert bytes to string"""
    if isinstance(bytestring, bytes):
        return bytestring.decode(encoding=char_encoding, errors="replace").rstrip()
    return ""


def is_allowed_filename(filename: str) -> bool:
    """Is allowed setting file name"""
    return re.search(CFG_INVALID_FILENAME, filename, flags=re.IGNORECASE) is None


def invalid_save_name(name: str) -> bool:
    """Is invalid save name (empty, or track or class name missing in combo name)"""
    return name == "" or name[:3] == " - " or name[-3:] == " - " or name[-2:] == " -"


def is_finite_number(value: Any) -> bool:
    """Is finite number (int or float, not bool, nan or inf)"""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _reject_json_constant(name: str) -> Any:
    """JSON NaN, Infinity, -Infinity are not allowed"""
    raise ValueError(f"invalid JSON number: {name}")


def _finite_json_float(text: str) -> float:
    """JSON float, out of range number (1e999) is not allowed"""
    value = float(text)
    if not isfinite(value):
        raise ValueError(f"invalid JSON number: {text}")
    return value


def load_json_strict(data: str | bytes | bytearray) -> Any:
    """Parse untrusted JSON text (share code, imported file), raise ValueError if invalid

    Unlike json.loads, NaN, Infinity & out of range numbers are rejected, and too deeply nested
    data raises ValueError (not RecursionError).
    """
    try:
        return json.loads(data, parse_constant=_reject_json_constant, parse_float=_finite_json_float)
    except RecursionError as error:
        raise ValueError("JSON data nested too deeply") from error


def is_string_number(value: str) -> bool:
    """Validate string number"""
    try:
        float(value)
        return True
    except ValueError:
        return False


def valid_sectors(sector_time: list | Any, max_time: float = MAX_SECONDS) -> bool:
    """Is valid sector time"""
    if isinstance(sector_time, list):
        return all(0 < sec < max_time for sec in sector_time)
    return 0 < sector_time < max_time


def session_token(session_id: tuple[int, ...], now: float | None = None) -> tuple[float, ...]:
    """Session token: session id (stamp, elapsed seconds, total laps) & time read

    Args:
        session_id: session identifier from API.
        now: time read (seconds), default wall clock (tokens saved to file).
    """
    return (*session_id[:3], time.time() if now is None else now)


def is_same_session(last_token: tuple | None, token: tuple) -> bool:
    """Check if session token belongs to session of last token (read before)

    Same session: same stamp (session length & type), elapsed time & laps not gone back, and
    session running (elapsed time) since before last token was read. A new session of same
    length & type has started after it, so going out later in a restarted session is not taken
    as the same session. Both tokens must be read on the same clock. Game paused (single player)
    longer than the elapsed time of last token counts as new session.
    """
    if not last_token or len(last_token) != 4 or len(token) != 4:
        return False
    stamp, elapsed, laps, read_time = token
    last_stamp, last_elapsed, last_laps, last_read_time = last_token
    return (
        stamp == last_stamp
        and last_elapsed <= elapsed
        and last_laps <= laps
        and read_time - elapsed < last_read_time + SESSION_START_TOLERANCE
    )


def purge_data_key(loaded_dict: dict, ref_keys: Iterable[str]) -> dict:
    """Purge unwanted key from dict"""
    for key in tuple(loaded_dict):
        if key not in ref_keys:
            loaded_dict.pop(key)
    return loaded_dict


# File validate
def file_last_modified(filepath: str = "", filename: str = "", extension: str = "") -> float:
    """Check file last modified time, 0 if file not exist"""
    filename_full = f"{filepath}{filename}{extension}"
    if os.path.exists(filename_full):
        return os.path.getmtime(filename_full)
    return 0


def image_exists(filepath: str, extension: str = FileExt.PNG, max_size: int = 10_240_000) -> bool:
    """Validate image file path, file format (default PNG), max file size (default < 10MB)"""
    return (
        os.path.exists(filepath) and
        os.path.getsize(filepath) < max_size and
        filepath.lower().endswith(extension)
    )


# Delta list validate
def valid_delta_set(data: tuple) -> tuple:
    """Validate delta data set"""
    # Delta list must have at least 10 lines of samples
    if len(data) < 10:
        raise ValueError
    # Final row value(second column) must be higher than previous row
    if data[-1][1] < data[-2][1]:
        raise ValueError
    # Check distance greater than next row for first 10 rows
    for idx in range(min(11, len(data) - 2), 0, -1):
        if data[idx][0] > data[idx + 1][0]:
            raise ValueError
    # Numbers only (no text, nan or inf)
    if not all(is_finite_number(value) for row in data for value in row):
        raise ValueError
    return data


def valid_delta_raw(dataset: list[Any], final: float, column: int) -> bool:
    """Validate raw delta data set"""
    try:
        if len(dataset) <= 1:
            return False
        # Remove rows if source value higher than final value
        while dataset[-1][column] > final:
            dataset.pop()
            if not dataset:
                return False
        return True
    except (AttributeError, TypeError, IndexError):
        return False


# Value type validate
def valid_value_type(value: Any, default: Any) -> Any:
    """Validate if value is same type as default (int accepted as float), return default value if False"""
    if isinstance(default, float):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return default
    if isinstance(value, type(default)):
        return value
    return default


def convert_value_type(value: Any, default: Any, target_type: type) -> Any:
    """Convert any value type to target type, revert to default if fails"""
    try:
        return target_type(value)
    except (TypeError, ValueError, OverflowError):
        return default


def dict_value_type(data: dict, default_data: dict) -> dict:
    """Validate and correct dictionary value type"""
    return {
        key: type(def_value)(data.get(key, def_value))
        for key, def_value in default_data.items()
    }


# Color validate
def is_hex_color(color_str: str | Any) -> bool:
    """Validate HEX color string"""
    if isinstance(color_str, str):
        return rex_hex_color.search(color_str) is not None
    return False


# Time format validate
def is_clock_format(_format: str) -> bool:
    """Validate clock time format"""
    try:
        time.strftime(_format)
        return True
    except ValueError:
        return False


# Timer
def state_timer(interval: float, last: float = 0):
    """State timer

    Args:
        interval: time interval in seconds.
        last: last time stamp in seconds.
    Yields:
        is_timeout: bool.
    """
    while True:
        seconds = monotonic()
        if seconds - last >= interval:
            last = seconds
            yield True
        else:
            yield False


# Desync check
@generator_init
def vehicle_position_sync(max_diff: float = 200, max_desync: int = 20):
    """Vehicle position synchronization

    Args:
        max_diff: max delta position (meters). Exceeding max delta counts as new lap.
        max_desync: max desync counts.

    Sends:
        pos_curr: current position (meters).

    Yields:
        Synchronized position (meters).
    """
    pos_synced = 0
    desync_count = 0

    while True:
        pos_curr = yield pos_synced
        if pos_curr is None:  # reset
            pos_curr = 0
            pos_synced = 0
            desync_count = 0
            continue
        if pos_synced > pos_curr:
            if desync_count > max_desync or pos_synced - pos_curr > max_diff:
                desync_count = 0  # reset
                pos_synced = pos_curr
            else:
                desync_count += 1
        elif pos_synced < pos_curr:
            pos_synced = pos_curr
            if desync_count:
                desync_count = 0


@generator_init
def vehicle_position_interp():
    """Interpolate vehicle traveled distance based on time delta"""
    time_last = 0.0
    dist_last = 0.0
    dist_est = 0.0
    time_delta = 0.0
    dist_delta = 0.0

    while True:
        time_curr, dist_curr = yield dist_est

        if dist_last != dist_curr:
            dist_delta = dist_curr - dist_last
            time_delta = time_curr - time_last
            dist_last = dist_curr
            time_last = time_curr
        elif time_delta > 0 < dist_delta:
            dist_est = dist_last + dist_delta * (time_curr - time_last) / time_delta
