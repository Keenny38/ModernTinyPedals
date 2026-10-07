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
Recorded lap marks: laps kept (never removed by recorder) and lap notes

Saved per track folder in MARKS_FILE: {lap file name: {"kept": true, "note": "..."}}.
"""

from __future__ import annotations

import json
import logging
import os

from . import atomic_write

logger = logging.getLogger(__name__)

MARKS_FILE = ".lap_marks.json"


def load_marks(folder: str, strict: bool = False) -> dict[str, dict]:
    """Marks of laps in folder, empty if none

    Args:
        strict: raise OSError or ValueError if file exists but unreadable (locked, damaged), instead of empty
            marks: kept laps would be removed, other marks erased by file saved again.
    """
    try:
        with open(os.path.join(folder, MARKS_FILE), encoding="utf-8") as file:
            marks = json.load(file)
        if not isinstance(marks, dict):
            raise ValueError("not a JSON object")
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        if strict:
            raise
        return {}
    return {name: mark for name, mark in marks.items() if isinstance(name, str) and isinstance(mark, dict)}


def save_marks(folder: str, marks: dict[str, dict]) -> bool:
    """Save marks of folder (file removed if none), False if not saved"""
    path = os.path.join(folder, MARKS_FILE)
    cleaned = {name: mark for name, mark in marks.items() if mark.get("kept") or mark.get("note")}
    try:
        if not cleaned:
            if os.path.exists(path):
                os.remove(path)
            return True
        with atomic_write(path) as file:
            json.dump(cleaned, file, indent=1, ensure_ascii=False)
        return True
    except OSError as error:
        logger.error("LAP MARKS: unable to save %s: %s", path, error)
        return False


def load_marks_to_save(folder: str) -> dict[str, dict] | None:
    """Marks of folder to change & save again, None if file unreadable (never saved over)"""
    try:
        return load_marks(folder, strict=True)
    except (OSError, ValueError) as error:
        logger.error("LAP MARKS: unable to read %s: %s", os.path.join(folder, MARKS_FILE), error)
        return None


def set_mark(path: str, kept: bool | None = None, note: str | None = None) -> bool:
    """Set kept state and/or note of lap file, False if not saved"""
    folder, name = os.path.split(path)
    marks = load_marks_to_save(folder)
    if marks is None:
        return False
    mark = dict(marks.get(name, {}))
    if kept is not None:
        mark["kept"] = kept
    if note is not None:
        mark["note"] = note.strip()
    marks[name] = mark
    return save_marks(folder, marks)


def remove_mark(path: str) -> bool:
    """Forget marks of lap file (deleted lap), False if not saved"""
    folder, name = os.path.split(path)
    marks = load_marks_to_save(folder)
    if marks is None:
        return False
    if marks.pop(name, None) is None:
        return True
    return save_marks(folder, marks)


def kept_laps(folder: str) -> set[str]:
    """File names of kept laps in folder

    Raises:
        OSError, ValueError: marks file unreadable (kept laps unknown).
    """
    return {name for name, mark in load_marks(folder, strict=True).items() if mark.get("kept")}
