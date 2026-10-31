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
Validator function
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Callable, Iterable
from functools import wraps
from math import isfinite
from time import monotonic
from typing import Any

from .const_common import MAX_SECONDS
from .const_file import FileExt
from .regex_pattern import CFG_INVALID_FILENAME, rex_hex_color

logger = logging.getLogger(__name__)

SESSION_START_TOLERANCE = 2.0  # seconds, session start time from whole elapsed seconds
_URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]+:")  # file:, smb:, http: (a single letter is a drive)


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


DECODE_CACHE_SIZE = 1024  # decoded game texts kept per decoder (names of every car: driver, vehicle, class)


def cached_bytes_to_str(char_encoding: str = "utf-8", max_size: int = DECODE_CACHE_SIZE) -> Callable[[Any], str]:
    """Bytes to string decoder (see bytes_to_str) keeping decoded texts, keyed by raw bytes

    Game names are read per car many times a second and rarely change: decoded once. Bounded (cleared once
    full). Thread safe: dict get & set are atomic, a text cleared meanwhile is decoded again.
    """
    cache: dict[bytes, str] = {}

    def tostr(bytestring: bytes | Any) -> str:
        try:
            return cache[bytestring]
        except (KeyError, TypeError):  # not decoded yet, or not bytes (unhashable)
            pass
        if not isinstance(bytestring, bytes):
            return ""
        text = bytestring.decode(encoding=char_encoding, errors="replace").rstrip()
        if len(cache) >= max_size:
            cache.clear()
        cache[bytestring] = text
        return text

    return tostr


def is_allowed_filename(filename: str) -> bool:
    """Is allowed setting file name"""
    return re.search(CFG_INVALID_FILENAME, filename, flags=re.IGNORECASE) is None


# Windows device names: a file named so (any case, any extension, spaces before the dot) opens the device
WINDOWS_RESERVED_NAMES = frozenset((
    "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
    *(f"{device}{index}" for device in ("COM", "LPT") for index in (*range(10), "¹", "²", "³")),
))


def _reserved_stem(name: str) -> str:
    """Part of file name Windows matches against device names (before first dot, spaces stripped)"""
    return name.split(".", 1)[0].strip(" ")


def is_reserved_filename(name: str) -> bool:
    """Is Windows device file name (CON, NUL, COM1, LPT¹, CONIN$...: any case, with any extension, trailing
    dots & spaces), writing such file fails or opens the device"""
    return _reserved_stem(name).upper() in WINDOWS_RESERVED_NAMES


def avoid_reserved_filename(name: str) -> str:
    """File name with "_" after a Windows device name (CON.txt: CON_.txt), other names unchanged"""
    if not is_reserved_filename(name):
        return name
    stem = _reserved_stem(name)
    index = name.index(stem) + len(stem)
    return f"{name[:index]}_{name[index:]}"


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


def load_json_strict(data: str | bytes | bytearray, allow_nan: bool = False) -> Any:
    """Parse untrusted JSON text (imported file), raise ValueError if invalid

    Unlike json.loads, NaN, Infinity & out of range numbers are rejected, and too deeply nested
    data raises ValueError (not RecursionError).

    Args:
        allow_nan: accept NaN & Infinity (files the app writes with json.dumps, such as lap info,
            may hold them), only nesting checked.
    """
    try:
        check_json_nesting(data)
        if allow_nan:
            return json.loads(data)
        return json.loads(data, parse_constant=_reject_json_constant, parse_float=_finite_json_float)
    except RecursionError as error:
        raise ValueError("JSON data nested too deeply") from error


# Arrays & objects nested deeper than this are refused before parsing (check_json_nesting): the data of the app
# (presets, game answers, share codes) nests a few levels. CPython up to 3.13 raised RecursionError itself near
# depth 1000; 3.14 parses as deep as the C stack allows, so the check is explicit and the same on every version.
MAX_JSON_DEPTH = 500
_JSON_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
_JSON_BRACKET = re.compile(r"[\[\]{}]")


def check_json_nesting(data: str | bytes | bytearray, limit: int = MAX_JSON_DEPTH) -> None:
    """Raise RecursionError if JSON text nests arrays or objects deeper than limit

    Called before json.loads of untrusted text. Cheap for usual text (fewer openers than the limit: one count,
    no scan); brackets inside strings are not counted.
    """
    if isinstance(data, (bytes, bytearray)):
        if data.count(b"[") + data.count(b"{") <= limit:
            return
        text = bytes(data).decode("utf-8", errors="replace")
    else:
        if data.count("[") + data.count("{") <= limit:
            return
        text = data
    depth = 0
    for match in _JSON_BRACKET.finditer(_JSON_STRING.sub("", text)):
        if match[0] in "[{":
            depth += 1
            if depth > limit:
                raise RecursionError(f"JSON data nested deeper than {limit}")
        elif depth:
            depth -= 1


def json_loads_checked(data: str | bytes | bytearray, **kwargs: Any) -> Any:
    """json.loads of untrusted text, RecursionError if nested too deeply (on Python 3.14 too)"""
    check_json_nesting(data)
    return json.loads(data, **kwargs)


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


def is_network_path(path: str) -> bool:
    """Path opening a network share, a device or a URL instead of a local file: UNC (\\\\server\\share,
    //server/share), device & NT paths (\\\\?\\UNC\\..., \\\\.\\..., \\??\\...), URL (file:, smb:...)

    A setting value (shared preset, imported settings) holding one would connect to its host as soon as
    the file is checked or opened, sending the Windows sign-in hash (NTLM): never opened automatically.
    Drive letters (C:\\, mapped Z:\\) are local paths.
    """
    if not isinstance(path, str):
        return False
    text = path.strip().replace("/", "\\")
    return text.startswith(("\\\\", "\\??\\")) or bool(_URL_SCHEME.match(text))


def image_exists(
    filepath: str, extension: str = FileExt.PNG, max_size: int = 10_240_000, allow_network: bool = False) -> bool:
    """Validate image file path, file format (default PNG), max file size (default < 10MB), never a network
    path unless allow_network (file listed from a folder the user set in global settings, NAS folder)"""
    return (
        (allow_network or not is_network_path(filepath)) and
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
    # Distance & value in every row (blank or cut line of an edited file): never an IndexError while driving
    if any(len(row) < 2 for row in data):
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
