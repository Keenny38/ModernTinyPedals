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
Consumption history file function
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Sequence

from ..const_file import FileExt
from ..module_info import ConsumptionDataSet
from ..validator import dict_value_type, invalid_save_name, is_finite_number
from . import atomic_write
from .json_setting import create_backup_file, set_backup_timestamp

logger = logging.getLogger(__name__)


def load_consumption_history_file(
    filepath: str, filename: str, extension: str = FileExt.CONSUMPTION, backup: bool = False
) -> tuple[ConsumptionDataSet, ...]:
    """Load fuel/energy consumption history file (*.consumption)

    Args:
        backup: keep a timestamped backup of a file with content that could not be read
            (own history file only, as next save replaces it). Content means data lines, or a
            header other than the consumption header; empty or header-only file (no data yet)
            and file not accessible (locked: OSError) are never backed up.
    """
    has_content = False  # file has data lines or a foreign header: worth keeping if unreadable
    try:
        with open(f"{filepath}{filename}{extension}", newline="", encoding="utf-8") as csvfile:
            data_reader = csv.DictReader(csvfile, restval="", restkey="unknown")
            fieldnames = data_reader.fieldnames
            has_content = fieldnames is not None and tuple(fieldnames) != ConsumptionDataSet._fields
            default_data = ConsumptionDataSet._field_defaults
            lines = []
            for data in data_reader:
                has_content = True
                lines.append(convert_line(data, default_data))
            dataset = tuple(filter(None, lines))
        # Numbers only (no nan or inf), invalid line left out
        dataset = tuple(data for data in dataset if all(map(is_finite_number, data)))
        if not dataset:
            raise ValueError
        return dataset
    except FileNotFoundError:
        logger.info("MISSING: consumption history (%s) data", extension)
    except OSError:  # not accessible (locked...), file left as is
        logger.info("MISSING: unreadable consumption history (%s) file", extension)
    except (IndexError, KeyError, ValueError, TypeError, csv.Error) as error:
        logger.info("MISSING: invalid consumption history (%s) data", extension)
        # Keep unreadable file, as next save replaces it with new data only
        # (not text or malformed csv: content too, even if failed at first line)
        if backup and (has_content or isinstance(error, (UnicodeDecodeError, csv.Error))):
            create_backup_file(f"{filename}{extension}", filepath, set_backup_timestamp(), show_log=True)
    return (ConsumptionDataSet(),)


def convert_line(data: dict, default_data: dict) -> ConsumptionDataSet | None:
    """Convert consumption history line, None if invalid (left out)"""
    try:
        return ConsumptionDataSet(**dict_value_type(data, default_data))
    except (TypeError, ValueError, OverflowError):
        return None


def save_consumption_history_file(
    dataset: Sequence, filepath: str, filename: str, extension: str = FileExt.CONSUMPTION
) -> bool:
    """Save fuel/energy consumption history file (*.consumption), returns True if written (error logged)"""
    if len(dataset) < 2 or invalid_save_name(filename):
        return False
    try:
        with atomic_write(f"{filepath}{filename}{extension}", newline="", raise_error=True) as csvfile:
            data_writer = csv.writer(csvfile, quoting=csv.QUOTE_NONNUMERIC)
            data_writer.writerow(ConsumptionDataSet._fields)  # write field name as column header
            data_writer.writerows(dataset)
    except OSError:  # logged by atomic_write
        return False
    logger.info("USERDATA: %s%s saved", filename, extension)
    return True
