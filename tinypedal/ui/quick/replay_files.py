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
Replay files of the game (LMU UserData/Replays, "<replay name>.Vcr"): added or exported by copy, renamed,
deleted to the recycle bin, temporary files of the game (_vcr*.tmp) cleaned

The game lists every replay file of its folder (/rest/watch/replays), no game command is needed.
Files are copied under a temporary name first: the game never lists a half copied replay.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from typing import NamedTuple

from PySide6.QtCore import QFile, QUrl
from PySide6.QtGui import QDesktopServices

REPLAY_EXTENSION = ".Vcr"
PART_EXTENSION = ".part"  # file being copied
TEMP_PATTERN = ("_vcr", ".tmp")  # game temporary files: _vcr1222177728.tmp
TEMP_MIN_AGE = 600.0  # seconds: newer temporary files can be the replay being recorded
CHUNK_SIZE = 8 << 20  # bytes copied between progress reports
FREE_MARGIN = 200 << 20  # bytes left free on disk after copy
INVALID_NAME = '<>:"/\\|?*'


class CopyResult(NamedTuple):
    """Replays copied: names given, errors (file name: reason), copy cancelled"""

    added: list[str]
    errors: list[str]
    cancelled: bool = False


def is_replay_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() == REPLAY_EXTENSION.lower() and os.path.isfile(path)


def replay_path(folder: str, name: str) -> str:
    """File of replay named name (game replay name: file name without extension)"""
    return os.path.join(folder, f"{name}{REPLAY_EXTENSION}")


def free_name(folder: str, name: str) -> str:
    """Replay name not used in folder: name, else "name (2)", "name (3)"..."""
    candidate, number = name, 1
    while os.path.exists(replay_path(folder, candidate)):
        number += 1
        candidate = f"{name} ({number})"
    return candidate


def same_file(path_a: str, path_b: str) -> bool:
    return os.path.normcase(os.path.abspath(path_a)) == os.path.normcase(os.path.abspath(path_b))


def free_space(folder: str) -> int:
    """Free bytes on disk of folder, -1 if unknown"""
    try:
        return shutil.disk_usage(folder).free
    except OSError:
        return -1


def copy_replays(sources: Sequence[str], folder: str, progress: Callable[[float], None],
                 cancelled: threading.Event | None = None) -> CopyResult:
    """Copy replay files to folder (in background), names already used get a number, nothing copied
    if disk has not enough free space. Cancelled: file being copied removed, next ones left out."""
    sizes: dict[str, int] = {}
    for source in sources:
        if is_replay_file(source) and not same_file(os.path.dirname(source), folder):
            try:
                sizes[source] = os.stat(source).st_size
            except OSError:  # file gone meanwhile
                continue
    sources = list(sizes)
    total = sum(sizes.values())
    free = free_space(folder)
    if sources and 0 <= free < total + FREE_MARGIN:
        return CopyResult([], [f"{folder}: not enough free space ({free >> 20} MB free, {total >> 20} MB needed)"])
    copied = 0
    added: list[str] = []
    errors: list[str] = []
    for source in sources:
        name = free_name(folder, os.path.splitext(os.path.basename(source))[0])
        target = replay_path(folder, name)
        part = f"{target}{PART_EXTENSION}"
        try:
            with open(source, "rb") as reader, open(part, "wb") as writer:
                while chunk := reader.read(CHUNK_SIZE):
                    if cancelled is not None and cancelled.is_set():
                        break
                    writer.write(chunk)
                    copied += len(chunk)
                    progress(copied / max(total, 1))
            if cancelled is not None and cancelled.is_set():
                os.remove(part)
                return CopyResult(added, errors, True)
            shutil.copystat(source, part)  # replay keeps its date in game list
            os.replace(part, target)
            added.append(name)
        except OSError as error:
            errors.append(f"{os.path.basename(source)}: {error.strerror or error}")
            with suppress(OSError):
                os.remove(part)
    return CopyResult(added, errors)


def rename_replay(folder: str, name: str, new_name: str) -> str:
    """Rename replay file, error text ("" if renamed)"""
    new_name = new_name.strip()
    if not new_name or any(char in INVALID_NAME for char in new_name) or new_name.endswith("."):
        return "invalid name"
    if os.path.exists(replay_path(folder, new_name)) and not same_file(
            replay_path(folder, new_name), replay_path(folder, name)):
        return "name already used"
    try:
        os.replace(replay_path(folder, name), replay_path(folder, new_name))
    except OSError as error:
        return str(error.strerror or error)
    return ""


def temp_files(folder: str, now: float | None = None) -> list[str]:
    """Temporary files left by the game in replay folder (older than TEMP_MIN_AGE)"""
    now = time.time() if now is None else now
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return []
    paths = []
    for entry in entries:
        name = entry.name.lower()
        if not (name.startswith(TEMP_PATTERN[0]) and name.endswith(TEMP_PATTERN[1])):
            continue
        # File deleted by the game meanwhile (recording): stat of path, entry stat is cached by scandir on Windows
        try:
            if entry.is_file() and now - os.stat(entry.path).st_mtime > TEMP_MIN_AGE:
                paths.append(entry.path)
        except OSError:
            continue
    return paths


def trash_replays(paths: Sequence[str]) -> list[str]:
    """Move files to the recycle bin, names of files left in place"""
    return [os.path.basename(path) for path in paths if not QFile.moveToTrash(path)]


def show_in_folder(path: str):
    """File manager opened on folder of file, file selected (Windows)"""
    if sys.platform == "win32" and os.path.exists(path):
        subprocess.Popen(["explorer", f"/select,{os.path.normpath(path)}"])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
