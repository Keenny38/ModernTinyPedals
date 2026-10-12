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
Global settings imported from a folder chosen by user (settings folder of an older version,
or of another computer)

Request saved in config folder ("import_request.json"), applied on next start before settings
are loaded (a running app would save its settings over imported ones), see apply_pending_import.
Source folder is copied, never moved nor modified. Current folder is never deleted: it is
renamed next to it ("<folder>.before-import-<time>") before the copy, and put back if the copy
fails. Runtime files of a running app (pid.log, lock & temporary files) are not copied.

Linux: data folder of same name next to source (XDG data home) is imported too, and
"user_path" values of copied config.json pointing inside source folders are updated.

Runs before logging is set: messages are kept and written to log by log_import_report().
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime

logger = logging.getLogger(__name__)

REQUEST_FILE = "import_request.json"
CONFIG_FILE = "config.json"
SETTINGS_FILES = (CONFIG_FILE, "shortcuts.json")  # one of them: a global settings folder
SKIPPED_FILES = ("pid.log", "*.lock", "*.tmp", "startup.marker", REQUEST_FILE)
TEMP_SUFFIX = ".importing"

_report: list[tuple[int, str]] = []  # (log level, message)


def _record(level: int, message: str) -> None:
    _report.append((level, message))


def log_import_report(target: logging.Logger = logger) -> None:
    """Write import messages to log (once logging is set)"""
    while _report:
        level, message = _report.pop(0)
        target.log(level, message)


def same_folder(path_a: str, path_b: str) -> bool:
    return os.path.normcase(os.path.abspath(path_a)) == os.path.normcase(os.path.abspath(path_b))


def is_settings_folder(path: str, config_folder: str) -> bool:
    """Folder holds global settings, and is not current config folder (nor inside it)"""
    if not os.path.isdir(path) or same_folder(path, config_folder):
        return False
    inside = os.path.normcase(os.path.abspath(path)).startswith(
        os.path.normcase(os.path.join(os.path.abspath(config_folder), "")))
    return not inside and any(os.path.isfile(os.path.join(path, name)) for name in SETTINGS_FILES)


def request_import(config_folder: str, source: str) -> bool:
    """Save import request, applied on next start; False if not saved"""
    filename = os.path.join(config_folder, REQUEST_FILE)
    temp_file = f"{filename}{TEMP_SUFFIX}"
    data = {"source": os.path.abspath(source), "requested": datetime.now().isoformat(timespec="seconds")}
    try:
        with open(temp_file, "w", encoding="utf-8") as jsonfile:
            json.dump(data, jsonfile, indent=4)
        os.replace(temp_file, filename)
    except OSError as error:
        logger.error("IMPORT: request not saved in %s: %s", filename, error)
        return False
    logger.info("IMPORT: settings of %s imported on next start", source)
    return True


def read_request(config_folder: str) -> str:
    """Source folder of pending import request, empty if none"""
    try:
        with open(os.path.join(config_folder, REQUEST_FILE), encoding="utf-8") as jsonfile:
            data = json.load(jsonfile)
    except (OSError, ValueError):
        return ""
    source = data.get("source") if isinstance(data, dict) else None
    return source if isinstance(source, str) else ""


def clear_request(config_folder: str) -> None:
    try:
        os.remove(os.path.join(config_folder, REQUEST_FILE))
    except FileNotFoundError:
        pass
    except OSError as error:
        _record(logging.ERROR, f"IMPORT: request not removed: {error}")


def rewrite_config_paths(config_file: str, path_map: dict[str, str]) -> int:
    """Point "user_path" values inside source folders to new folders, return changed count"""
    with open(config_file, encoding="utf-8") as jsonfile:
        config = json.load(jsonfile)
    user_path = config.get("user_path") if isinstance(config, dict) else None
    if not isinstance(user_path, dict):
        return 0
    changed = 0
    for key, value in user_path.items():
        if not isinstance(value, str):
            continue
        normalized = value.replace("\\", "/")
        for old_root, new_root in path_map.items():
            old = old_root.replace("\\", "/").rstrip("/")
            if normalized == old or normalized.startswith(f"{old}/"):
                user_path[key] = new_root.replace("\\", "/").rstrip("/") + normalized[len(old):]
                changed += 1
                break
    if changed:
        temp_file = f"{config_file}{TEMP_SUFFIX}"
        with open(temp_file, "w", encoding="utf-8") as jsonfile:
            json.dump(config, jsonfile, indent=4)
        os.replace(temp_file, config_file)
    return changed


def replace_folder(source: str, target: str, stamp: str) -> str:
    """Copy source to target, current target set aside first; returns folder set aside (empty if none)

    Raises:
        OSError, shutil.Error: copy failed, target put back as it was.
    """
    temp_folder = f"{target}{TEMP_SUFFIX}"
    if os.path.exists(temp_folder):  # left by an interrupted import
        shutil.rmtree(temp_folder)
    try:
        shutil.copytree(source, temp_folder, ignore=shutil.ignore_patterns(*SKIPPED_FILES))
    except shutil.Error as error:  # other files copied: unreadable ones (in use) left out
        _record(logging.WARNING, f"IMPORT: some files not copied: {error}")
        os.makedirs(temp_folder, exist_ok=True)
    except OSError:
        shutil.rmtree(temp_folder, ignore_errors=True)
        raise
    aside = ""
    if os.path.exists(target):
        aside = f"{target}.before-import-{stamp}"
        os.rename(target, aside)
    try:
        os.rename(temp_folder, target)
    except OSError:
        if aside:
            os.rename(aside, target)
        raise
    return aside


def apply_pending_import(config_folder: str, data_folder: str = "") -> bool:
    """Import settings asked last run (before settings are loaded), True if imported

    Args:
        config_folder: global config folder of this app.
        data_folder: Linux data folder of this app (empty on Windows): data folder of same
            name next to source folder imported too, if any.
    """
    config_folder = config_folder.rstrip("/\\")
    source = read_request(config_folder)
    if not source:
        return False
    clear_request(config_folder)  # never retried in a loop: asked again from menu if failed
    if not is_settings_folder(source, config_folder):
        _record(logging.WARNING, f"IMPORT: {source} is not a settings folder, nothing imported")
        return False
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path_map = {source: config_folder}
    if data_folder:
        data_folder = data_folder.rstrip("/\\")
        source_data = os.path.join(os.path.dirname(data_folder), os.path.basename(source.rstrip("/\\")))
        if os.path.isdir(source_data) and not same_folder(source_data, data_folder):
            try:
                aside = replace_folder(source_data, data_folder, stamp)
                path_map[source_data] = data_folder
                _record(logging.INFO, f"IMPORT: data copied from {source_data}"
                        + (f", previous data set aside as {aside}" if aside else ""))
            except (OSError, shutil.Error) as error:
                _record(logging.ERROR, f"IMPORT: data of {source_data} not imported: {error}")
    try:
        aside = replace_folder(source, config_folder, stamp)
    except (OSError, shutil.Error) as error:
        _record(logging.ERROR, f"IMPORT: settings of {source} not imported, current settings kept: {error}")
        return False
    _record(logging.INFO, f"IMPORT: settings copied from {source}"
            + (f", previous settings set aside as {aside}" if aside else ""))
    config_file = os.path.join(config_folder, CONFIG_FILE)
    if os.path.isfile(config_file):
        try:
            changed = rewrite_config_paths(config_file, path_map)
            if changed:
                _record(logging.INFO, f"IMPORT: {changed} user path(s) updated in {CONFIG_FILE}")
        except (OSError, ValueError) as error:  # invalid json: loader resets it as usual
            _record(logging.WARNING, f"IMPORT: user paths not updated in {CONFIG_FILE}: {error}")
    return True
