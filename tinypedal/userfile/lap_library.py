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
Deleted laps are moved to a trash batch folder (lap viewer trash), so they can be restored.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from collections.abc import Callable, Iterator
from contextlib import suppress
from typing import NamedTuple

from .lap_cache import remove_cached_lap
from .telemetry_lap import (
    IMPORT_FOLDER,
    LapData,
    LapFile,
    is_lap_file,
    lap_files,
    lap_time_of,
    lap_timestamp_of,
    read_lap_info,
    same_circuit,
)

logger = logging.getLogger(__name__)

RENAME_RETRIES = 10  # tries 0.1 s apart while a lap file of the log is still open
FOREIGN_MARK = ".foreign.json"  # in group folder: laps imported from another driver's folder
FOREIGN_DEPTH = 3  # sub folder levels searched for lap files (telemetry folder, track folders...)
FOREIGN_MAX_LAPS = 2000  # laps of current track & class copied from a folder
FOREIGN_MAX_FILES = 20000  # lap files looked at in a folder (folders of current track first)

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
    """Rename imported log group, returns moved lap paths (old: new), lap caches of old paths removed"""
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
    for lap in laps:
        remove_cached_lap(filepath, lap.path)
    return {
        os.path.normpath(lap.path): os.path.normpath(os.path.join(target, lap.filename))
        for lap in laps
    }


def is_foreign(path: str) -> bool:
    """Whether lap was imported from another driver's folder (group folder marked)"""
    return os.path.isfile(os.path.join(os.path.dirname(path), FOREIGN_MARK))


def inside(path: str, folder: str) -> bool:
    """Whether path is folder or inside it"""
    path, folder = (os.path.normcase(os.path.abspath(name)) for name in (path, folder))
    try:
        return os.path.commonpath([path, folder]) == folder
    except ValueError:  # other drive
        return False


def find_lap_files(folder: str, depth: int = FOREIGN_DEPTH, skip: str = "",
                   first: Callable[[str], bool] | None = None) -> Iterator[str]:
    """Lap files of folder & its sub folders, sub folders whose name matches first (current track) searched first

    Hidden folders (caches, trash, imported laps) & skip folder (own telemetry folder) left out.
    """
    try:
        entries = sorted(os.scandir(folder), key=lambda entry: (
            first is not None and entry.is_dir() and not first(entry.name), entry.name))
    except OSError:
        return
    for entry in entries:
        if entry.name.startswith("."):
            continue
        if entry.is_file() and is_lap_file(entry.name):
            yield os.path.normpath(entry.path)
        elif entry.is_dir() and depth > 0 and not (skip and inside(entry.path, skip)):
            yield from find_lap_files(entry.path, depth - 1, skip, first)


def is_recorded_lap(path: str, info: dict) -> bool:
    """Whether file is a lap recorded by the app: lap info naming its circuit, or recorder file name (older laps)
    (any other CSV file is not: notes, viewer exports)"""
    if info.get("track") or info.get("track_length"):
        return True
    name = os.path.basename(path)
    return lap_timestamp_of(name) > 0 and lap_time_of(name) > 0


def class_of_folder(path: str) -> str:
    """Vehicle class from track folder of lap ("<track> - <class>"), empty if not in such folder"""
    folder = os.path.basename(os.path.dirname(path))
    return folder.rsplit(" - ", 1)[1].strip() if " - " in folder else ""


def track_of_folder(path: str) -> str:
    """Track name from track folder of lap ("<track> - <class>"), empty if not in such folder"""
    folder = os.path.basename(os.path.dirname(path))
    return folder.rsplit(" - ", 1)[0].strip() if " - " in folder else ""


def compatible_lap(reference: dict, info: dict, vehicle_class: str, path: str = "") -> str:
    """Why lap (info) can not be compared with reference lap: "circuit", "class", or "" if it can

    Same circuit: same game track name & length (see same_circuit), track of lap track folder for older laps
    without info. Same vehicle class: game class of lap info, else class of lap track folder.
    """
    if not same_circuit(LapData("", {}, reference), LapData("", {}, info)):
        return "circuit"
    if not (info.get("track") or info.get("track_length")):  # circuit unknown: track folder must be reference one
        track, folder_track = str(reference.get("track", "")), track_of_folder(path)
        if not folder_track or (track and folder_track.lower() != track.lower()):
            return "circuit"
    lap_class = str(info.get("class", "") or class_of_folder(path))
    if vehicle_class and lap_class and lap_class.lower() != vehicle_class.lower():
        return "class"
    return ""


def foreign_source(group: str) -> str:
    """Folder laps of foreign group were imported from (normalized), empty if not a foreign group"""
    try:
        with open(os.path.join(group, FOREIGN_MARK), encoding="utf-8") as file:
            mark = json.load(file)
    except (OSError, ValueError):
        return ""
    source = mark.get("source") if isinstance(mark, dict) else None
    return os.path.normcase(os.path.normpath(source)) if isinstance(source, str) and source else ""


def foreign_group(filepath: str, source: str) -> str:
    """Group folder name for laps of source folder: group imported from it before (renamed or not), else new one
    (name of folder, numbered if taken)"""
    folder = import_folder(filepath)
    wanted = os.path.normcase(os.path.normpath(source))
    try:
        names = sorted(os.listdir(folder))
    except OSError:  # nothing imported yet
        names = []
    for name in names:
        if foreign_source(os.path.join(folder, name)) == wanted:
            return name
    base = _invalid_group_name.sub("_", os.path.basename(os.path.normpath(source)).strip(" .")) or "Laps"
    name, number = base, 2
    while os.path.exists(os.path.join(folder, name)):
        name, number = f"{base} ({number})", number + 1
    return name


def copy_file(source: str, target: str):
    """Copy file to a temporary file renamed once complete (copy stopped at app exit leaves no partial lap)"""
    temporary = f"{target}.tmp"
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    except OSError:
        with suppress(OSError):
            os.remove(temporary)
        raise


def import_foreign_job(filepath: str, source: str, reference: dict, vehicle_class: str) -> dict:
    """Copy laps of another driver's folder that can be compared with reference lap (same circuit & class) to its
    foreign group (worker process job, laps already in group not copied again)

    Returns:
        paths: laps of group from source matching reference (copied now or before), present: laps copied before,
        skipped counts by reason ("circuit", "class", "file": not a lap), error text.
    """
    result: dict = {"paths": [], "present": 0, "circuit": 0, "class": 0, "file": 0, "error": ""}
    folder = import_folder(filepath)
    if inside(source, filepath):
        result["error"] = "own telemetry folder"
        return result
    track = str(reference.get("track", "")).lower()

    def current_track(name: str) -> bool:
        return bool(track) and name.lower().startswith(track)

    laps: list[str] = []
    for looked, path in enumerate(find_lap_files(source, skip=filepath, first=current_track)):
        if looked >= FOREIGN_MAX_FILES or len(laps) >= FOREIGN_MAX_LAPS:
            break
        info = read_lap_info(path)
        reason = compatible_lap(reference, info, vehicle_class, path) if is_recorded_lap(path, info) else "file"
        if reason:
            result[reason] += 1
        else:
            laps.append(path)
    if not laps:
        return result
    group = os.path.join(folder, foreign_group(filepath, source))
    try:
        os.makedirs(group, exist_ok=True)
        mark = os.path.join(group, FOREIGN_MARK)
        with open(f"{mark}.tmp", "w", encoding="utf-8") as file:
            json.dump({"source": os.path.normpath(source), "imported": round(time.time())}, file)
        os.replace(f"{mark}.tmp", mark)
        for path in laps:
            target = os.path.normpath(os.path.join(group, os.path.basename(path)))
            if target in result["paths"]:  # same file name in two track folders of source
                continue
            if os.path.exists(target):
                result["present"] += 1
            else:
                copy_file(path, target)
            result["paths"].append(target)
    except OSError as error:
        logger.error("LAP LIBRARY: unable to import laps from %s: %s", source, error)
        result["error"] = error.strerror or str(error)
    return result


class Deletion(NamedTuple):
    """Imported laps deleted"""

    deleted: list[str]  # lap paths gone from library
    trashed: list[tuple[str, str]]  # files moved to trash (path, path in trash), moved back by restore_laps
    failed: dict[str, str]  # lap paths not deleted: reason


def delete_laps(filepath: str, paths: list[str], trash: str) -> Deletion:
    """Move imported laps to trash batch folder (files outside library left untouched), groups without lap left
    removed (foreign mark kept in trash), lap caches removed

    A lap file still open (lap viewer loading it, antivirus) is tried again a moment later, then reported failed.
    """
    folder = import_folder(filepath)
    pending = [os.path.normpath(path) for path in paths]
    pending = [path for path in dict.fromkeys(pending) if os.path.dirname(os.path.dirname(path)) == folder]
    deletion = Deletion([], [], {})
    for attempt in range(RENAME_RETRIES):
        locked = []
        for path in pending:
            target = os.path.join(trash, IMPORT_FOLDER, os.path.basename(os.path.dirname(path)), os.path.basename(path))
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(path, target)
            except FileNotFoundError:  # removed meanwhile
                deletion.failed.pop(path, None)
                deletion.deleted.append(path)
                continue
            except PermissionError as error:  # Windows: file still open, tried again
                locked.append(path)
                deletion.failed[path] = error.strerror or str(error)
                continue
            except OSError as error:
                logger.error("LAP LIBRARY: unable to delete %s: %s", path, error)
                deletion.failed[path] = error.strerror or str(error)
                continue
            deletion.failed.pop(path, None)
            deletion.deleted.append(path)
            deletion.trashed.append((path, target))
            remove_cached_lap(filepath, path)
        pending = locked
        if not pending or attempt == RENAME_RETRIES - 1:
            break
        time.sleep(0.1)
    for path in pending:
        logger.error("LAP LIBRARY: unable to delete %s: %s", path, deletion.failed.get(path))
    for group in {os.path.dirname(path) for path in deletion.deleted}:
        if lap_files(group):
            continue
        mark = os.path.join(group, FOREIGN_MARK)
        target = os.path.join(trash, IMPORT_FOLDER, os.path.basename(group), FOREIGN_MARK)
        if os.path.isfile(mark):
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(mark, target)
                deletion.trashed.append((mark, target))
            except OSError as error:
                logger.error("LAP LIBRARY: unable to delete %s: %s", mark, error)
        shutil.rmtree(group, ignore_errors=True)  # left over temporary files
    return deletion


def restore_laps(trashed: list[tuple[str, str]]) -> list[str]:
    """Move files deleted by delete_laps back from trash (undo), returns lap paths restored

    A file whose place is taken meanwhile stays in trash. Trash folders left empty are removed.
    """
    restored = []
    for path, target in trashed:
        if os.path.exists(path):
            continue
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            os.replace(target, path)
        except OSError as error:
            logger.error("LAP LIBRARY: unable to restore %s: %s", path, error)
            continue
        if is_lap_file(path):
            restored.append(path)
        group = os.path.dirname(target)
        for empty in (group, os.path.dirname(group), os.path.dirname(os.path.dirname(group))):
            with suppress(OSError):  # group, imported & batch folders of trash removed once empty
                os.rmdir(empty)
    return restored
