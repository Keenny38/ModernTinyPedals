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
Sector best file function
"""

from __future__ import annotations

import csv
import logging
from typing import Any

from ..const_common import MAX_SECONDS
from ..const_file import FileExt
from ..validator import invalid_save_name, is_finite_number, is_same_session
from . import atomic_write

logger = logging.getLogger(__name__)


def valid_sector_row(row: list[Any], defaults: tuple[float, float, float]) -> list[float]:
    """Sector times of row, invalid time (not a positive number) replaced by default"""
    return [
        value if is_finite_number(value) and value > 0 else default
        for value, default in zip(row[:3], defaults)
    ] + list(defaults[len(row):])


def load_sector_best_file(
    filepath: str,
    filename: str,
    session_id: tuple[float, ...],
    defaults: tuple[float, float, float],
    extension: str = FileExt.SECTOR,
) -> tuple[list, list, list, list]:
    """Load sector best file (*.sector)

    Args:
        session_id: session token (see validator.session_token), session best data loaded
            only if same session as saved one.
    """
    try:
        with open(f"{filepath}{filename}{extension}", newline="", encoding="utf-8") as csvfile:
            temp_list: list[list[Any]] = list(csv.reader(csvfile, quoting=csv.QUOTE_NONNUMERIC))
        # Session best data, if same session
        if is_same_session(tuple(temp_list[0]), session_id):
            best_s_tb = valid_sector_row(temp_list[1], defaults)
            best_s_pb = valid_sector_row(temp_list[2], defaults)
        else:
            best_s_tb = list(defaults)
            best_s_pb = list(defaults)
        # All time best data
        all_best_s_tb = valid_sector_row(temp_list[3], defaults)
        all_best_s_pb = valid_sector_row(temp_list[4], defaults)
        return best_s_tb, best_s_pb, all_best_s_tb, all_best_s_pb
    except FileNotFoundError:
        logger.info("MISSING: sector best (%s) data", extension)
    except (IndexError, ValueError, TypeError, OSError, csv.Error):
        logger.info("MISSING: invalid sector best (%s) data", extension)
    return list(defaults), list(defaults), list(defaults), list(defaults)


def load_theoretical_best(filepath: str, filename: str, extension: str = FileExt.SECTOR) -> float:
    """All time theoretical best lap time (sum of all time best sectors), 0 if unknown"""
    try:
        with open(f"{filepath}{filename}{extension}", newline="", encoding="utf-8") as csvfile:
            rows: list[list[Any]] = list(csv.reader(csvfile, quoting=csv.QUOTE_NONNUMERIC))
        sectors = rows[3][:3]
    except (IndexError, ValueError, TypeError, OSError, csv.Error):  # no file, invalid data
        return 0.0
    if len(sectors) != 3 or not all(isinstance(value, float) and 0 < value < MAX_SECONDS for value in sectors):
        return 0.0
    return sum(sectors)


def save_sector_best_file(
    filepath: str,
    filename: str,
    session_id: tuple[float, ...],
    session_best_tb: list[float],
    session_best_pb: list[float],
    alltime_best_tb: list[float],
    alltime_best_pb: list[float],
    extension: str = FileExt.SECTOR,
) -> None:
    """Save sector best file (*.sector)

    Sector(CSV) file structure:
        Line 0: session stamp, session elapsed time, session total laps, time read (session token)
        Line 1: session theoretical best sector time
        Line 2: session personal best sector time
        Line 3: all time theoretical best sector time
        Line 4: all time personal best sector time
    """
    if len(session_id) not in (3, 4) or invalid_save_name(filename):
        return
    with atomic_write(f"{filepath}{filename}{extension}", newline="") as csvfile:
        data_writer = csv.writer(csvfile)
        # Session stamp
        data_writer.writerow(session_id)
        # session best sector time
        data_writer.writerow(session_best_tb)
        data_writer.writerow(session_best_pb)
        # All time best sector time
        data_writer.writerow(alltime_best_tb)
        data_writer.writerow(alltime_best_pb)
        logger.info("USERDATA: %s%s saved", filename, extension)
