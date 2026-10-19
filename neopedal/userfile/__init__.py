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
User file access function
"""

from __future__ import annotations

import errno
import io
import json
import logging
import os
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from typing import IO, Any, TextIO

from ..const_app import CONFIG_ID, PLATFORM
from ..validator import load_json_strict

logger = logging.getLogger(__name__)

REPLACE_ATTEMPTS = 5  # attempts of replacing file locked for a moment (antivirus, cloud sync)
REPLACE_RETRY_DELAY = 0.05  # seconds before 2nd attempt, longer before each next one


def app_root_folder() -> str:
    """APP root folder: folder of executable (installed app) or of run.py (source),
    the working folder run.py sets at start"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


APP_ROOT = app_root_folder()


def app_path(filepath: str) -> str:
    """Relative path resolved against APP root folder instead of working folder

    Same folder as before when started from run.py (working folder is APP root), so a relative
    user path keeps pointing to the same place. Empty or absolute path returned unchanged.
    """
    if not filepath or os.path.isabs(filepath):
        return filepath
    return os.path.join(APP_ROOT, filepath)


def set_user_data_path(filepath: str) -> str:
    """Set user data path (relative to APP root folder), create if not exist"""
    full_path = app_path(filepath)
    if not os.path.exists(full_path):
        logger.info("%s folder does not exist, attempt to create", filepath)
        try:
            os.makedirs(full_path, exist_ok=True)
        except OSError:  # also invalid path (Windows "<" in name: WinError 123)
            logger.error("failed to create %s folder", filepath)
            return ""
    return filepath


def flush_to_disk(file: IO) -> None:
    """Flush file data to disk (not only to OS cache), so a power loss never leaves it empty"""
    file.flush()
    os.fsync(file.fileno())


def temp_file_name(filename: str) -> str:
    """Temporary file name of target file, unique per process & thread (writers never share one)"""
    return f"{filename}.{os.getpid()}.{threading.get_ident()}.tmp"


def replace_retry(src: str, dst: str, attempts: int = REPLACE_ATTEMPTS) -> None:
    """os.replace, retried a few times on PermissionError

    Windows Defender, OneDrive or a search indexer open a just written file for a moment:
    replace fails with WinError 5 or 32 until they release it.

    Raises:
        OSError: last error, if every attempt failed (or any other error at once).
    """
    for attempt in range(1, attempts + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt >= attempts:
                raise
            time.sleep(REPLACE_RETRY_DELAY * attempt)


def atomic_replace(path: str, data: bytes, *, verify: bool = False, fsync: bool = True) -> None:
    """Write bytes to file atomically: temporary file, flushed to disk, then replaces target

    Existing file is never left half-written or empty, temporary file never left on error.

    Args:
        path: target file name (with path).
        data: file content.
        verify: read bytes back before replacing target, OSError (EIO) if they differ.
        fsync: flush data to disk (not only to OS cache) before replacing target.

    Raises:
        OSError: unable to save file (target untouched).
    """
    temp_filename = temp_file_name(path)
    try:
        with open(temp_filename, "wb") as file:
            file.write(data)
            if fsync:
                flush_to_disk(file)
        if verify:
            with open(temp_filename, "rb") as file:
                if file.read() != data:
                    raise OSError(errno.EIO, "file content differs from written data", path)
        replace_retry(temp_filename, path)
    except BaseException:
        with suppress(OSError):
            os.remove(temp_filename)
        raise


def read_json(path: str, *, strict: bool = True, default: Any = None, dict_only: bool = False) -> Any:
    """Read json file (UTF-8, BOM of Notepad or PowerShell allowed), default if missing or invalid

    Args:
        path: file name (with path).
        strict: NaN, Infinity & out of range numbers (1e999) make file invalid.
        default: returned if file missing, unreadable or invalid.
        dict_only: file not holding a JSON object is invalid.
    """
    try:
        with open(path, encoding="utf-8-sig") as file:
            text = file.read()
        data = load_json_strict(text) if strict else json.loads(text)
    except (OSError, ValueError, RecursionError):
        return default
    if dict_only and not isinstance(data, dict):
        return default
    return data


def append_line(path: str, line: bytes) -> None:
    """Add line at end of file, on a line of its own (last line cut short by a crash stays apart)

    Raises:
        OSError: unable to write file.
    """
    with open(path, "ab+") as file:
        file.seek(0, os.SEEK_END)
        separator = b""
        if file.tell() > 0:
            file.seek(-1, os.SEEK_END)
            separator = b"" if file.read(1) == b"\n" else b"\n"
        file.write(separator + line)


@contextmanager
def atomic_write(filename: str, newline: str | None = None, raise_error: bool = False) -> Iterator[TextIO]:
    """Write text file atomically, log error instead of raising

    Data is written to a temporary file first, flushed to disk, then replaces target file,
    so existing file is never left half-written or empty (crash, power loss, full disk, locked file).

    Args:
        filename: target file name (with path).
        newline: newline mode of file.
        raise_error: raise OSError (after logging) instead of discarding data.
    """
    temp_filename = temp_file_name(filename)
    try:
        file = open(temp_filename, "w", newline=newline, encoding="utf-8")  # noqa: SIM115, closed below
    except OSError as error:
        logger.error("USERDATA: failed saving %s: %s", filename, error)
        if raise_error:
            raise
        yield io.StringIO()  # discard data
        return
    try:
        with file:
            yield file
            flush_to_disk(file)
        replace_retry(temp_filename, filename)
    except OSError as error:
        logger.error("USERDATA: failed saving %s: %s", filename, error)
        with suppress(OSError):
            os.remove(temp_filename)
        if raise_error:
            raise
    except BaseException:  # unexpected error while writing, never leave temp file
        with suppress(OSError):
            os.remove(temp_filename)
        raise


@contextmanager
def atomic_path(filename: str) -> Iterator[str]:
    """Temporary file name to write (writer taking a file name: csv, picture), replaces target once written

    Existing file is never left half-written (file open in a spreadsheet, full disk), temporary file never
    left on error.

    Raises:
        OSError: unable to replace target (target untouched), or error of writer.
    """
    temp_filename = temp_file_name(filename)
    try:
        yield temp_filename
        replace_retry(temp_filename, filename)
    except BaseException:
        with suppress(OSError):
            os.remove(temp_filename)
        raise


def write_text_file(filename: str, text: str) -> bool:
    """Write text file atomically, returns True if saved"""
    try:
        atomic_replace(filename, text.encode("utf-8"))
        return True
    except OSError as error:
        logger.error("USERDATA: failed saving %s: %s", filename, error)
        return False


def encode_text(text: str, newline: str | None = None) -> bytes:
    """Bytes of text as written to a text file opened with newline mode"""
    if newline is None:
        newline = os.linesep
    if newline and newline != "\n":
        text = text.replace("\n", newline)
    return text.encode("utf-8")


def write_verified_bytes(filename: str, data: bytes, raise_error: bool = False) -> bool:
    """Write file atomically, verified by reading bytes back before replacing target

    Returns:
        True if saved & verified. Error logged (and raised if raise_error) otherwise.
    """
    try:
        atomic_replace(filename, data, verify=True)
        return True
    except OSError as error:
        logger.error("USERDATA: failed saving %s: %s", filename, error)
        if raise_error:
            raise
        return False


def write_json(
    filename: str, data: Any, indent: int | str | None = None, newline: str | None = None,
    raise_error: bool = False, **kwargs: Any,
) -> bool:
    """Write json file atomically in one write, verified by reading bytes back

    json.dumps encodes in one shot (C encoder if not indented), json.dump to a file always
    encodes in pure Python with many small writes. Output is byte identical to json.dump with
    same arguments to a text file opened with same newline mode.

    Raises:
        TypeError, ValueError: data not serializable (file untouched).
        OSError: unable to save file (logged), only if raise_error.
    """
    text = json.dumps(data, indent=indent, **kwargs)
    return write_verified_bytes(filename, encode_text(text, newline), raise_error)


def set_relative_path(filepath: str) -> str:
    """Convert absolute path to relative if path is inside APP root folder"""
    try:
        rel_path = os.path.relpath(app_path(filepath), APP_ROOT)
        if rel_path.startswith(".."):
            output_path = filepath
        else:
            output_path = rel_path
    except ValueError:
        output_path = filepath
    # Convert backslash to slash
    output_path = output_path.replace("\\", "/")
    # Make sure path end with "/"
    if not output_path.endswith("/"):
        output_path += "/"
    return output_path


def set_global_config_path() -> str:
    """Set path for global configurable user files, create if not exist

    Default to APPDATA folder (AppData/Roaming) on Windows.
    Default to XDG_CONFIG_HOME ($HOME/.config) on Linux.
    """
    if PLATFORM.WINDOWS:
        return set_user_data_path(f"{os.getenv('APPDATA', '.')}\\{CONFIG_ID}\\")
    # Linux
    from xdg import BaseDirectory as BD
    return BD.save_config_path(CONFIG_ID) + "/"


def settings_import_folders() -> tuple[str, str]:
    """Global config folder & Linux data folder (empty on Windows) replaced by a settings import,
    see settings_import.apply_pending_import"""
    if PLATFORM.WINDOWS:
        return f"{os.getenv('APPDATA', '.')}\\{CONFIG_ID}\\", ""
    from xdg import BaseDirectory as BD
    return os.path.join(BD.xdg_config_home, CONFIG_ID), os.path.join(BD.xdg_data_home, CONFIG_ID)


def set_default_config_path(filepath: str) -> str:
    """Set path for default configurable user files

    Default to app local folder (./) on Windows.
    Default to XDG_CONFIG_HOME ($HOME/.config) on Linux.
    """
    if PLATFORM.WINDOWS:
        return filepath
    # Linux
    from xdg import BaseDirectory as BD
    return BD.save_config_path(CONFIG_ID, filepath)


def set_default_data_path(filepath: str) -> str:
    """Set path for default non-configurable data files

    Default to app local folder (./) on Windows.
    Default to XDG_DATA_HOME ($HOME/.local/share) on Linux.
    """
    if PLATFORM.WINDOWS:
        return filepath
    # Linux
    from xdg import BaseDirectory as BD
    return BD.save_data_path(CONFIG_ID, filepath)
