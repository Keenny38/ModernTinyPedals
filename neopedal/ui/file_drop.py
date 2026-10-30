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
Files dropped on main window: preset (.json), preset package, overlay settings or plugin (.zip), MoTeC log (.ld),
consumption history, race plan or tyre plan (opened in Race Calculator, which takes them dropped on its page too)
"""

from __future__ import annotations

import logging
import os
import zipfile
from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import QMimeData

from .. import app_signal
from ..const_file import FileExt
from ..i18n import tr, trm
from ..setting import cfg
from ..userfile import write_json
from ..userfile.private_option import keep_receiver_options
from ..validator import is_allowed_filename, load_json_strict

logger = logging.getLogger(__name__)

DROP_PRESET = "preset"
DROP_PACKAGE = "package"
DROP_OVERLAYS = "overlays"  # overlay settings package
DROP_PLUGIN = "plugin"
DROP_MOTEC = "motec"
DROP_RACE = "race"  # one of the Race Calculator files below
DROP_HISTORY = "history"
DROP_RACE_PLAN = "race_plan"
DROP_TYRE_PLAN = "tyre_plan"
RACE_FILES = {FileExt.CONSUMPTION: DROP_HISTORY, FileExt.RACEPLAN: DROP_RACE_PLAN, FileExt.TYRESTRATEGY: DROP_TYRE_PLAN}
MAX_PRESET_SIZE = 20 * 1024 * 1024


def dropped_files(mime: QMimeData) -> list[str]:
    """Local file paths of supported type"""
    if not mime.hasUrls():
        return []
    return [
        url.toLocalFile() for url in mime.urls()
        if url.isLocalFile() and url.toLocalFile().lower().endswith((FileExt.JSON, ".zip", ".ld", *RACE_FILES))
    ]


def race_file_kind(path: str) -> str:
    """Race Calculator file: DROP_HISTORY, DROP_RACE_PLAN or DROP_TYRE_PLAN, empty if not one"""
    lower = path.lower()
    return next((kind for extension, kind in RACE_FILES.items() if lower.endswith(extension)), "")


def classify(path: str) -> str:
    """Type of dropped file, empty if not supported"""
    lower = path.lower()
    if race_file_kind(lower):
        return DROP_RACE
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
            from ..userfile.overlay_package import is_overlay_package

            return DROP_OVERLAYS if is_overlay_package(path) else DROP_PACKAGE
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


def import_preset_file(path: str, folder: str, receiver: Mapping[str, Mapping[str, Any]] | None = None) -> str:
    """Copy preset json to settings folder (never overwrites), returns new file name

    Local file & game connection options get the values of receiver (loaded preset), see private_option.

    Raises:
        ValueError: not a preset.
        OSError: file error.
    """
    if os.path.getsize(path) > MAX_PRESET_SIZE:
        raise ValueError("file too large")
    with open(path, encoding="utf-8") as file:
        try:
            data = load_json_strict(file.read())
        except (ValueError, UnicodeDecodeError) as error:  # also nested too deeply
            raise ValueError("invalid json file") from error
    if not isinstance(data, dict) or not all(isinstance(value, dict) for value in data.values()):
        raise ValueError("not a preset file")
    from ..template.setting_widget import WIDGET_FILENAME

    base = os.path.splitext(os.path.basename(path))[0]
    if not is_allowed_filename(base) or not any(name in data for name in WIDGET_FILENAME):
        raise ValueError("not a widget preset (global config & style presets are not imported)")
    kept = keep_receiver_options(data, receiver)
    filename = unique_preset_name(folder, os.path.basename(path))
    write_json(os.path.join(folder, filename), data, indent=4, raise_error=True)
    logger.info("PRESET: imported %s", filename)
    if kept:
        logger.info("PRESET: local file & game connection options kept as receiver's: %s", ", ".join(kept))
    return filename


def handle_drop(window, paths: list[str]) -> list[str]:
    """Import dropped files, returns messages (html)"""
    from .app import PAGE_INDEX

    messages = []
    imported = False  # presets imported not refreshed yet: pages & menus refreshed once, not once per file
    try:
        for path in paths:
            kind = classify(path)
            name = os.path.basename(path)
            if imported and kind != DROP_PRESET:  # other file next (may open a dialog): presets listed first
                imported = False
                app_signal.refresh.emit(True)
            if kind == DROP_PRESET:
                try:
                    filename = import_preset_file(path, cfg.path.settings, cfg.user.setting)
                except (OSError, ValueError) as error:
                    messages.append(trm(f"Unable to import <b>{name}</b>: {tr(str(error))}"))
                    continue
                messages.append(trm(f"Preset imported: <b>{filename[:-5]}</b>"))
                window.centralWidget().set_current_index(PAGE_INDEX["preset"])
                imported = True
            elif kind == DROP_PACKAGE:
                window.centralWidget().set_current_index(PAGE_INDEX["preset"])
                window.centralWidget().preset_tab.import_package_file(path)
            elif kind == DROP_OVERLAYS:
                from .overlay_share import import_overlay_file

                import_overlay_file(window, path)
            elif kind == DROP_MOTEC:
                from .lap_viewer import import_motec_log

                messages.append(import_motec_log(window, path))
            elif kind == DROP_RACE:
                from .tools_view import open_tool

                open_dropped = getattr(getattr(open_tool("race_calculator.RaceCalculator", window), "backend", None),
                                       "open_dropped", None)
                if callable(open_dropped):  # opened like its Open action, told by the page
                    open_dropped([path])
            elif kind == DROP_PLUGIN:
                from ._common import BaseDialog
                from .plugin_manager import PluginManager

                manager = PluginManager(window)
                manager.show()
                # Already open as page: installed from that page (new copy is deleted)
                shown = manager.shown_dialog() if isinstance(manager, BaseDialog) else manager
                install_file = getattr(shown, "install_file", None)
                if callable(install_file):  # not opened as separate window already
                    install_file(path)
            else:
                messages.append(trm(f"Unsupported file: <b>{name}</b>"))
    finally:
        if imported:
            app_signal.refresh.emit(True)
    return messages
