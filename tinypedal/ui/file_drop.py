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
Files dropped on main window: preset (.json), preset package or plugin (.zip)
"""

from __future__ import annotations

import json
import logging
import os
import zipfile

from PySide6.QtCore import QMimeData

from .. import app_signal
from ..const_file import FileExt
from ..i18n import trm
from ..setting import cfg
from ..validator import is_allowed_filename

logger = logging.getLogger(__name__)

DROP_PRESET = "preset"
DROP_PACKAGE = "package"
DROP_PLUGIN = "plugin"
DROP_MOTEC = "motec"
MAX_PRESET_SIZE = 20 * 1024 * 1024


def dropped_files(mime: QMimeData) -> list[str]:
    """Local file paths of supported type"""
    if not mime.hasUrls():
        return []
    return [
        url.toLocalFile() for url in mime.urls()
        if url.isLocalFile() and url.toLocalFile().lower().endswith((FileExt.JSON, ".zip", ".ld"))
    ]


def classify(path: str) -> str:
    """Type of dropped file, empty if not supported"""
    lower = path.lower()
    if lower.endswith(FileExt.JSON):
        return DROP_PRESET
    if lower.endswith(".ld"):
        return DROP_MOTEC
    if lower.endswith(".zip"):
        try:
            with zipfile.ZipFile(path) as package:
                names = package.namelist()
        except (OSError, zipfile.BadZipFile):
            return ""
        if "manifest.json" in names:
            return DROP_PACKAGE
        if any(name.replace("\\", "/").endswith("/widget.py") for name in names):
            return DROP_PLUGIN
    return ""


def unique_preset_name(folder: str, filename: str) -> str:
    """File name not used in folder: name.json, name (2).json..."""
    base = os.path.splitext(filename)[0]
    candidate = f"{base}{FileExt.JSON}"
    index = 2
    while os.path.exists(os.path.join(folder, candidate)):
        candidate = f"{base} ({index}){FileExt.JSON}"
        index += 1
    return candidate


def import_preset_file(path: str, folder: str) -> str:
    """Copy preset json to settings folder (never overwrites), returns new file name

    Raises:
        ValueError: not a preset.
        OSError: file error.
    """
    if os.path.getsize(path) > MAX_PRESET_SIZE:
        raise ValueError("file too large")
    with open(path, encoding="utf-8") as file:
        try:
            data = json.load(file)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("invalid json file") from error
    if not isinstance(data, dict) or not all(isinstance(value, dict) for value in data.values()):
        raise ValueError("not a preset file")
    from ..template.setting_widget import WIDGET_FILENAME

    base = os.path.splitext(os.path.basename(path))[0]
    if not is_allowed_filename(base) or not any(name in data for name in WIDGET_FILENAME):
        raise ValueError("not a widget preset (global config & style presets are not imported)")
    filename = unique_preset_name(folder, os.path.basename(path))
    target = os.path.join(folder, filename)
    temp = f"{target}.tmp"
    with open(temp, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)
    os.replace(temp, target)
    logger.info("PRESET: imported %s", filename)
    return filename


def handle_drop(window, paths: list[str]) -> list[str]:
    """Import dropped files, returns messages (html)"""
    from .app import PAGE_INDEX

    messages = []
    for path in paths:
        kind = classify(path)
        name = os.path.basename(path)
        if kind == DROP_PRESET:
            try:
                filename = import_preset_file(path, cfg.path.settings)
            except (OSError, ValueError) as error:
                messages.append(trm(f"Unable to import <b>{name}</b>: {error}"))
                continue
            messages.append(trm(f"Preset imported: <b>{filename[:-5]}</b>"))
            window.centralWidget().set_current_index(PAGE_INDEX["preset"])
            app_signal.refresh.emit(True)
        elif kind == DROP_PACKAGE:
            window.centralWidget().set_current_index(PAGE_INDEX["preset"])
            window.centralWidget().preset_tab.import_package_file(path)
        elif kind == DROP_MOTEC:
            from .lap_viewer import import_motec_log

            messages.append(import_motec_log(window, path))
        elif kind == DROP_PLUGIN:
            from .plugin_manager import PluginManager

            manager = PluginManager(window)
            manager.show()
            if hasattr(manager, "install_file"):  # not already opened
                manager.install_file(path)
        else:
            messages.append(trm(f"Unsupported file: <b>{name}</b>"))
    return messages
