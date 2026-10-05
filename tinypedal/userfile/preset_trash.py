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
Preset trash: deleted presets kept for some days, restored (undo, trash list) or purged

Trash is a "trash" folder inside settings folder (not listed as preset nor backup),
one folder per deleted preset, named by deletion time:
    trash/<YYYYmmdd-HHMMSS-micro>/<preset>.json      preset file
    trash/<YYYYmmdd-HHMMSS-micro>/<preset>.layouts   layout profiles, if any
    trash/<YYYYmmdd-HHMMSS-micro>/trash.json         preset name, deletion time, references
References are primary preset entries (shortcuts, tracks, classes) cleared when deleted,
set again when restored.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from contextlib import suppress
from time import localtime, strftime, time
from typing import NamedTuple

from ..const_file import FileExt
from .layout_profile import FILE_EXTENSION as LAYOUT_EXTENSION

logger = logging.getLogger(__name__)

TRASH_FOLDER = "trash"
INFO_FILENAME = "trash.json"
DEFAULT_KEEP_DAYS = 30
SECONDS_PER_DAY = 86400


class TrashEntry(NamedTuple):
    """Deleted preset in trash"""

    folder: str  # entry folder (full path)
    filename: str  # preset file name, with extension
    deleted: float  # deletion time (seconds since epoch)
    references: dict[str, list[str]]  # cleared primary preset references, by config type

    @property
    def name(self) -> str:
        """Preset name, without extension"""
        return self.filename[:-len(FileExt.JSON)]


def trash_path(settings_path: str) -> str:
    """Trash folder of settings folder"""
    return os.path.join(settings_path, TRASH_FOLDER)


def new_entry_folder(settings_path: str) -> str:
    """Create new (unique) entry folder named by current time"""
    now = time()
    stamp = f"{strftime('%Y%m%d-%H%M%S', localtime(now))}-{int(now % 1 * 1_000_000):06d}"
    folder = os.path.join(trash_path(settings_path), stamp)
    index = 1
    while True:
        try:
            os.makedirs(folder)
            return folder
        except FileExistsError:
            index += 1
            folder = os.path.join(trash_path(settings_path), f"{stamp}-{index}")


def move_to_trash(
    settings_path: str, filename: str, references: dict[str, list[str]] | None = None
) -> TrashEntry:
    """Move preset file & its layout profiles to a new trash entry

    Raises:
        OSError: preset file can not be moved (locked, permission), preset kept as is.
    """
    source = os.path.join(settings_path, filename)
    if not os.path.isfile(source):
        raise FileNotFoundError(f"preset not found: {filename}")
    entry = TrashEntry(new_entry_folder(settings_path), filename, time(), dict(references or {}))
    try:
        with open(os.path.join(entry.folder, INFO_FILENAME), "w", encoding="utf-8") as file:
            json.dump({"filename": filename, "deleted": entry.deleted, "references": entry.references}, file)
        os.replace(source, os.path.join(entry.folder, filename))
    except OSError:
        shutil.rmtree(entry.folder, ignore_errors=True)  # never leave an entry without preset
        raise
    layouts = f"{os.path.splitext(filename)[0]}{LAYOUT_EXTENSION}"
    with suppress(OSError):  # layout profiles, if any
        os.replace(os.path.join(settings_path, layouts), os.path.join(entry.folder, layouts))
    logger.info("USERDATA: preset %s moved to trash", filename)
    return entry


def read_entry(folder: str) -> TrashEntry | None:
    """Trash entry of folder, None if invalid (no info or no preset file)"""
    try:
        with open(os.path.join(folder, INFO_FILENAME), encoding="utf-8") as file:
            info = json.load(file)
        filename = str(info["filename"])
        deleted = float(info["deleted"])
        references = info.get("references", {})
    except (OSError, ValueError, TypeError, KeyError):
        return None
    if (os.path.basename(filename) != filename or not filename.lower().endswith(FileExt.JSON)
            or not os.path.isfile(os.path.join(folder, filename))):
        return None
    if not isinstance(references, dict):
        references = {}
    references = {
        str(key): [str(name) for name in names]
        for key, names in references.items() if isinstance(names, list)
    }
    return TrashEntry(folder, filename, deleted, references)


def list_trash(settings_path: str) -> list[TrashEntry]:
    """Presets in trash, newest first"""
    folder = trash_path(settings_path)
    try:
        names = os.listdir(folder)
    except OSError:  # no trash yet
        return []
    entries = []
    for name in names:
        path = os.path.join(folder, name)
        if os.path.isdir(path):
            entry = read_entry(path)
            if entry is not None:
                entries.append(entry)
    return sorted(entries, key=lambda entry: entry.deleted, reverse=True)


def preset_exists(settings_path: str, filename: str) -> bool:
    """Preset file exists, any case (file names are case-insensitive on Windows)"""
    try:
        names = os.listdir(settings_path)
    except OSError:
        return False
    return filename.lower() in (name.lower() for name in names)


def free_preset_name(settings_path: str, filename: str) -> str:
    """File name not used by another preset (any case): name.json, name (2).json..."""
    base = os.path.splitext(filename)[0]
    candidate = f"{base}{FileExt.JSON}"
    index = 2
    while preset_exists(settings_path, candidate):
        candidate = f"{base} ({index}){FileExt.JSON}"
        index += 1
    return candidate


def restore_from_trash(settings_path: str, entry: TrashEntry, filename: str = "") -> str:
    """Move preset of trash entry back to settings folder, entry removed

    Args:
        filename: restored file name, entry file name if not set.

    Returns:
        Restored preset file name.

    Raises:
        FileExistsError: a preset with same name exists.
        OSError: preset can not be moved back (entry kept).
    """
    filename = filename or entry.filename
    if preset_exists(settings_path, filename):
        raise FileExistsError(f"preset already exists: {filename}")
    os.replace(os.path.join(entry.folder, entry.filename), os.path.join(settings_path, filename))
    layouts = f"{os.path.splitext(entry.filename)[0]}{LAYOUT_EXTENSION}"
    target_layouts = os.path.join(settings_path, f"{os.path.splitext(filename)[0]}{LAYOUT_EXTENSION}")
    source_layouts = os.path.join(entry.folder, layouts)
    if os.path.isfile(source_layouts) and not os.path.exists(target_layouts):
        with suppress(OSError):
            os.replace(source_layouts, target_layouts)
    shutil.rmtree(entry.folder, ignore_errors=True)
    logger.info("USERDATA: preset %s restored from trash", filename)
    return filename


def remove_entry(entry: TrashEntry) -> bool:
    """Delete trash entry for good, False if not removed"""
    shutil.rmtree(entry.folder, ignore_errors=True)
    return not os.path.exists(entry.folder)


def purge_trash(settings_path: str, keep_days: float, now: float | None = None) -> int:
    """Delete trash entries older than keep_days (invalid entries too), returns removed count"""
    folder = trash_path(settings_path)
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    limit = (time() if now is None else now) - max(keep_days, 0) * SECONDS_PER_DAY
    removed = 0
    for name in names:
        path = os.path.join(folder, name)
        if not os.path.isdir(path):
            continue
        entry = read_entry(path)
        deleted = entry.deleted if entry is not None else _modified_time(path)
        if deleted < limit:
            shutil.rmtree(path, ignore_errors=True)
            if not os.path.exists(path):
                removed += 1
    if removed:
        logger.info("USERDATA: %s preset(s) removed from trash", removed)
    return removed


def _modified_time(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return time()
