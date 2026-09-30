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
User file access function
"""

from __future__ import annotations

import io
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from typing import TextIO

from ..const_app import APP_ID, PLATFORM

logger = logging.getLogger(__name__)


def set_user_data_path(filepath: str) -> str:
    """Set user data path, create if not exist"""
    if not os.path.exists(filepath):
        logger.info("%s folder does not exist, attemp to create", filepath)
        try:
            os.mkdir(filepath)
        except (PermissionError, FileExistsError, FileNotFoundError):
            logger.error("failed to create %s folder", filepath)
            return ""
    return filepath


@contextmanager
def atomic_write(filename: str, newline: str | None = None) -> Iterator[TextIO]:
    """Write text file atomically, log error instead of raising

    Data is written to a temporary file first, then replaces target file,
    so existing file is never left half-written (crash, full disk, locked file).
    """
    temp_filename = f"{filename}.tmp"
    try:
        file = open(temp_filename, "w", newline=newline, encoding="utf-8")  # noqa: SIM115, closed below
    except OSError as error:
        logger.error("USERDATA: failed saving %s: %s", filename, error)
        yield io.StringIO()  # discard data
        return
    try:
        with file:
            yield file
        os.replace(temp_filename, filename)
    except OSError as error:
        logger.error("USERDATA: failed saving %s: %s", filename, error)
        with suppress(OSError):
            os.remove(temp_filename)
    except BaseException:  # unexpected error while writing, never leave temp file
        with suppress(OSError):
            os.remove(temp_filename)
        raise


def write_text_file(filename: str, text: str) -> bool:
    """Write text file atomically, returns True if saved"""
    temp_filename = f"{filename}.tmp"
    try:
        with open(temp_filename, "w", newline="", encoding="utf-8") as file:
            file.write(text)
        os.replace(temp_filename, filename)
        return True
    except OSError as error:
        logger.error("USERDATA: failed saving %s: %s", filename, error)
        with suppress(OSError):
            os.remove(temp_filename)
        return False


def set_relative_path(filepath: str) -> str:
    """Convert absolute path to relative if path is inside APP root folder"""
    try:
        rel_path = os.path.relpath(filepath)
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


def set_global_config_path(filepath: str) -> str:
    """Set path for global configurable user files, create if not exist

    Default to APPDATA folder (AppData/Roaming) on Windows.
    Default to XDG_CONFIG_HOME ($HOME/.config) on Linux.
    """
    if PLATFORM.WINDOWS:
        return set_user_data_path(f"{os.getenv('APPDATA', '.')}\\{filepath}\\")
    # Linux
    from xdg import BaseDirectory as BD
    return BD.save_config_path(filepath) + "/"


def set_default_config_path(filepath: str) -> str:
    """Set path for default configurable user files

    Default to TinyPedal local folder (./) on Windows.
    Default to XDG_CONFIG_HOME ($HOME/.config) on Linux.
    """
    if PLATFORM.WINDOWS:
        return filepath
    # Linux
    from xdg import BaseDirectory as BD
    return BD.save_config_path(APP_ID, filepath)


def set_default_data_path(filepath: str) -> str:
    """Set path for default non-configurable data files

    Default to TinyPedal local folder (./) on Windows.
    Default to XDG_DATA_HOME ($HOME/.local/share) on Linux.
    """
    if PLATFORM.WINDOWS:
        return filepath
    # Linux
    from xdg import BaseDirectory as BD
    return BD.save_data_path(APP_ID, filepath)
