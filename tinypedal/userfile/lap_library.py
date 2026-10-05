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
Reference lap library: laps imported from other files (MoTeC logs)

Imported laps are kept in telemetry IMPORT_FOLDER, one sub folder per imported log (group).
"""

from __future__ import annotations

import os
import re
import shutil
import time
from contextlib import suppress

from .telemetry_lap import IMPORT_FOLDER, LapFile, lap_files

RENAME_RETRIES = 10  # tries 0.1 s apart while a lap file of the log is still open

_invalid_group_name = re.compile(r'[\\/:*?"<>|]')


def import_folder(filepath: str) -> str:
    """Folder of imported laps in telemetry folder"""
    return os.path.normpath(os.path.join(filepath, IMPORT_FOLDER))


def list_imported(filepath: str) -> list[tuple[str, list[LapFile]]]:
    """Imported log groups by name, with their laps in lap order (empty groups left out)"""
    folder = import_folder(filepath)
    try:
        names = [name for name in os.listdir(folder) if os.path.isdir(os.path.join(folder, name))]
    except OSError:
        return []
    groups = []
    for name in sorted(names, key=str.lower):
        laps = sorted(lap_files(os.path.join(folder, name)), key=lambda lap: lap.filename)
        if laps:
            groups.append((name, [lap._replace(path=os.path.normpath(lap.path)) for lap in laps]))
    return groups


def group_name_error(filepath: str, old: str, new: str) -> str:
    """Why group can not be renamed: "invalid", "exists", or "" if allowed"""
    if not new or new != new.strip() or new.startswith(".") or _invalid_group_name.search(new):
        return "invalid"
    if new.lower() != old.lower() and os.path.exists(os.path.join(import_folder(filepath), new)):
        return "exists"
    return ""


def rename_group(filepath: str, old: str, new: str) -> dict[str, str]:
    """Rename imported log group, returns moved lap paths (old: new)"""
    folder = import_folder(filepath)
    source, target = os.path.join(folder, old), os.path.join(folder, new)
    laps = lap_files(source)
    for attempt in range(RENAME_RETRIES):
        try:
            os.rename(source, target)
            break
        except PermissionError:  # Windows: a lap file still read (lap viewer loading it): retried a moment later
            if attempt == RENAME_RETRIES - 1:
                raise
            time.sleep(0.1)
    return {
        os.path.normpath(lap.path): os.path.normpath(os.path.join(target, lap.filename))
        for lap in laps
    }


def delete_laps(filepath: str, paths: list[str]) -> dict[str, str]:
    """Delete imported laps (files outside library left untouched), empty groups removed too

    Returns:
        Deleted lap paths (path: "").
    """
    folder = import_folder(filepath)
    deleted: dict[str, str] = {}
    parents = set()
    for path in paths:
        path = os.path.normpath(path)
        if os.path.dirname(os.path.dirname(path)) != folder:
            continue
        with suppress(FileNotFoundError):
            os.remove(path)
        deleted[path] = ""
        parents.add(os.path.dirname(path))
    for parent in parents:
        if not lap_files(parent):
            shutil.rmtree(parent, ignore_errors=True)
    return deleted
