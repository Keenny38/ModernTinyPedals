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
Delta best file function

    <combo>.csv      all time best lap: distance, lap time rows
    <combo>.session  session & stint best laps of last session (JSON), kept while app or
                     delta module restarts during the session (preset reloaded, setting saved...)
"""

from __future__ import annotations

import csv
import json
import logging
from typing import Any

from ..const_common import DELTA_DEFAULT, MAX_SECONDS
from ..const_file import FileExt
from ..validator import invalid_save_name, is_same_session, load_json_strict, valid_delta_set
from . import atomic_write

logger = logging.getLogger(__name__)


def load_delta_best_file(
    filepath: str, filename: str, defaults: tuple, extension: str = FileExt.CSV
) -> tuple[tuple, float]:
    """Load delta best file (*.csv)"""
    try:
        with open(f"{filepath}{filename}{extension}", newline="", encoding="utf-8") as csvfile:
            data_reader = csv.reader(csvfile, quoting=csv.QUOTE_NONNUMERIC)
            temp_list = tuple(tuple(data) for data in data_reader)
        # Validate data
        bestlist = valid_delta_set(temp_list)
        laptime_best = bestlist[-1][1]
        return bestlist, laptime_best
    except FileNotFoundError:
        logger.info("MISSING: delta best (%s) data", extension)
    except (IndexError, ValueError, TypeError, OSError, csv.Error):
        logger.info("MISSING: invalid delta best (%s) data", extension)
    return defaults


def save_delta_best_file(
    filepath: str, filename: str, dataset: tuple, extension: str = FileExt.CSV
) -> None:
    """Save delta best file (*.csv)"""
    if len(dataset) < 10 or invalid_save_name(filename):
        return
    with atomic_write(f"{filepath}{filename}{extension}", newline="") as csvfile:
        data_writer = csv.writer(csvfile)
        data_writer.writerows(dataset)
        logger.info("USERDATA: %s%s saved", filename, extension)


def best_lap(rows: Any) -> tuple[tuple, float]:
    """Delta set & lap time of saved best lap, none (default set) if missing or invalid"""
    if not rows:
        return DELTA_DEFAULT, MAX_SECONDS
    dataset = valid_delta_set(tuple(tuple(row) for row in rows))
    return dataset, dataset[-1][1]


def load_delta_session_file(
    filepath: str, filename: str, session_id: tuple[float, ...], pitstops: int,
    extension: str = FileExt.DELTA_SESSION,
) -> tuple[tuple, float, tuple, float]:
    """Load session & stint best laps (*.session) saved in same session

    Args:
        session_id: session token (see validator.session_token), laps loaded only if same
            session as saved one.
        pitstops: number of pit stops of player now, stint best loaded only if no pit stop since saved.

    Returns:
        Session best delta set & lap time, stint best delta set & lap time (default set &
        MAX_SECONDS if none).
    """
    none = (DELTA_DEFAULT, MAX_SECONDS)
    try:
        with open(f"{filepath}{filename}{extension}", encoding="utf-8") as file:
            data = load_json_strict(file.read())
        if not isinstance(data, dict) or not is_same_session(tuple(data["session"]), session_id):
            return (*none, *none)
        session = best_lap(data.get("session_best"))
        stint = best_lap(data.get("stint_best")) if data.get("pitstops") == pitstops else none
        return (*session, *stint)
    except FileNotFoundError:
        pass
    except (KeyError, IndexError, ValueError, TypeError, OSError):
        logger.info("MISSING: invalid delta session (%s) data", extension)
    return (*none, *none)


def save_delta_session_file(
    filepath: str, filename: str, session_id: tuple[float, ...], pitstops: int,
    session_best: tuple, stint_best: tuple, extension: str = FileExt.DELTA_SESSION,
) -> None:
    """Save session & stint best laps (*.session) with session token & pit stops of player"""
    if len(session_id) != 4 or invalid_save_name(filename):
        return
    data = {
        "session": list(session_id),
        "pitstops": pitstops,
        "session_best": session_best if len(session_best) >= 10 else [],
        "stint_best": stint_best if len(stint_best) >= 10 else [],
    }
    with atomic_write(f"{filepath}{filename}{extension}") as file:
        json.dump(data, file, separators=(",", ":"))
