#  NeoPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of NeoPedal.
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
Last folder of file pickers: a file or folder chosen in a picker (open, save, folder) makes its folder the start of
the next picker of the same kind (key), kept between sessions in one small JSON file of the user config folder.

    path, _ = QFileDialog.getSaveFileName(parent, title, last_folder.start_path("lap_export", "lap.ld"), filter)
    if path:
        last_folder.remember("lap_export", path)

A folder removed since (USB drive, deleted) is skipped: the default folder of the picker opens instead.
"""

from __future__ import annotations

import os
from contextlib import suppress

from PySide6.QtCore import QCoreApplication
from shiboken6 import isValid

from .page_settings import PageSettings, load_settings, write_settings

FOLDERS_FILE = "file_picker_folders.json"
SAVE_DELAY_MS = 500
MAX_KEYS = 40  # kinds of pickers kept (keys of the app only: never grows much)

_writer: PageSettings | None = None  # delayed writes, lives with the app (never a disk write per picker)


def start_folder(key: str, default: str = "") -> str:
    """Folder of the last file or folder chosen in a picker of this kind, else default (home folder when empty)"""
    folder = load_settings(FOLDERS_FILE).get(key)
    if isinstance(folder, str) and folder and os.path.isdir(folder):
        return folder
    return default or os.path.expanduser("~")


def start_path(key: str, name: str, default: str = "") -> str:
    """Save picker start: file name in the last folder of this kind (default folder when none)"""
    return os.path.join(start_folder(key, default), name)


def remember(key: str, path: str):
    """File or folder chosen in a picker of this kind: its folder starts the next one (empty: cancelled, nothing)"""
    if not path:
        return
    folder = os.path.normpath(path if os.path.isdir(path) else os.path.dirname(path))
    folders = load_settings(FOLDERS_FILE)
    if folders.get(key) == folder:
        return
    folders.pop(key, None)
    folders[key] = folder  # last used last: oldest kinds dropped first
    folders = dict(list(folders.items())[-MAX_KEYS:])
    writer = _folder_writer()
    if writer is None:  # no app (scripts): written at once
        with suppress(OSError):
            write_settings(FOLDERS_FILE, folders)
        return
    writer.save(folders)


def _folder_writer() -> PageSettings | None:
    global _writer
    app = QCoreApplication.instance()
    if app is None:
        return None
    if _writer is None or not isValid(_writer) or _writer.parent() is not app:
        _writer = PageSettings(FOLDERS_FILE, SAVE_DELAY_MS, app)
    return _writer
