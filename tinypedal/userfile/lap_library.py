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
Reference lap library: laps imported from other files (MoTeC logs) & other drivers' folders (foreign laps)

Imported laps are kept in telemetry IMPORT_FOLDER, one sub folder per imported log or folder (group). A group
of laps from another driver's folder (teammate, shared folder) has a FOREIGN_MARK file: its laps are foreign.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from contextlib import suppress

from .telemetry_lap import IMPORT_FOLDER, LapData, LapFile, is_lap_file, lap_files, read_lap_info, same_circuit

logger = logging.getLogger(__name__)

RENAME_RETRIES = 10  # tries 0.1 s apart while a lap file of the log is still open
FOREIGN_MARK = ".foreign.json"  # in group folder: laps imported from another driver's folder
FOREIGN_DEPTH = 3  # sub folder levels searched for lap files (telemetry folder, track folders...)
FOREIGN_MAX_LAPS = 2000  # lap files looked at in a folder

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


def is_foreign(path: str) -> bool:
    """Whether lap was imported from another driver's folder (group folder marked)"""
    return os.path.isfile(os.path.join(os.path.dirname(path), FOREIGN_MARK))


def find_lap_files(folder: str, depth: int = FOREIGN_DEPTH) -> list[str]:
    """Lap files of folder & its sub folders (hidden folders left out: caches, trash, imported laps)"""
    found: list[str] = []
    try:
        entries = sorted(os.scandir(folder), key=lambda entry: entry.name)
    except OSError:
        return found
    for entry in entries:
        if entry.name.startswith(".") or len(found) >= FOREIGN_MAX_LAPS:
            continue
        if entry.is_file() and is_lap_file(entry.name):
            found.append(os.path.normpath(entry.path))
        elif entry.is_dir() and depth > 0:
            found.extend(find_lap_files(entry.path, depth - 1)[:FOREIGN_MAX_LAPS - len(found)])
    return found


def class_of_folder(path: str) -> str:
    """Vehicle class from track folder of lap ("<track> - <class>"), empty if not in such folder"""
    folder = os.path.basename(os.path.dirname(path))
    return folder.rsplit(" - ", 1)[1].strip() if " - " in folder else ""


def compatible_lap(reference: dict, info: dict, vehicle_class: str, path: str = "") -> str:
    """Why lap (info) can not be compared with reference lap: "circuit", "class", or "" if it can

    Same circuit: same game track name & length (see same_circuit). Same vehicle class: game class of lap info,
    else class of lap track folder.
    """
    if not same_circuit(LapData("", {}, reference), LapData("", {}, info)):
        return "circuit"
    lap_class = str(info.get("class", "") or class_of_folder(path))
    if vehicle_class and lap_class and lap_class.lower() != vehicle_class.lower():
        return "class"
    return ""


def foreign_group(filepath: str, source: str) -> str:
    """New group folder name for laps of source folder (name of folder, numbered if taken)"""
    base = _invalid_group_name.sub("_", os.path.basename(os.path.normpath(source)).strip(" .")) or "Laps"
    folder = import_folder(filepath)
    name, number = base, 2
    while os.path.exists(os.path.join(folder, name)):
        name, number = f"{base} ({number})", number + 1
    return name


def import_foreign_job(filepath: str, source: str, reference: dict, vehicle_class: str) -> dict:
    """Copy laps of another driver's folder that can be compared with reference lap (same circuit & class) to a
    new foreign group (worker process job): paths copied, skipped counts by reason, error text"""
    result: dict = {"paths": [], "circuit": 0, "class": 0, "error": ""}
    folder = import_folder(filepath)
    if os.path.normcase(os.path.normpath(source)).startswith(os.path.normcase(os.path.normpath(filepath))):
        result["error"] = "own telemetry folder"
        return result
    laps = []
    for path in find_lap_files(source):
        reason = compatible_lap(reference, read_lap_info(path), vehicle_class, path)
        if reason:
            result[reason] += 1
        else:
            laps.append(path)
    if not laps:
        return result
    group = os.path.join(folder, foreign_group(filepath, source))
    try:
        os.makedirs(group, exist_ok=True)
        with open(os.path.join(group, FOREIGN_MARK), "w", encoding="utf-8") as file:
            json.dump({"source": os.path.normpath(source), "imported": round(time.time())}, file)
        for path in laps:
            target = os.path.join(group, os.path.basename(path))
            if not os.path.exists(target):
                shutil.copy2(path, target)
                result["paths"].append(os.path.normpath(target))
    except OSError as error:
        logger.error("LAP LIBRARY: unable to import laps from %s: %s", source, error)
        result["error"] = error.strerror or str(error)
    return result


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
