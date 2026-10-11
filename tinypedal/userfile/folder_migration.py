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
User folder migration: legacy "TinyPedal" folders copied once to "NeoPedal" folders

Legacy folders are shared with the original TinyPedal app, so they are copied, never moved
nor modified. Copy goes to a temporary folder renamed when complete: an interrupted copy
never leaves a half new folder, and is retried on next start. Files that can not be read
(in use by a running TinyPedal) are left out, the rest is copied. Legacy folder is never
used by this app, even if copy fails: TinyPedal keeps its settings & running state (pid.log)
there, so both apps can run at the same time (failed copy: new folder starts with default
settings, "Import Again from TinyPedal" copies again).

Runs on first path request (setting import, before logging is set): messages are kept
and written to log by log_migration_report() once logging is ready.

User choice, saved in "migration.json" of new config folder (see ui/settings_import.py):
    pending   copied, user not asked yet (asked once window is up)
    kept      imported settings kept
    default   started with default settings (imported ones set aside)
    reset     default settings requested: applied on next start, before settings are loaded
    reimport  copy again from legacy folder requested: applied on next start
Requested changes never delete anything: current folder is renamed next to it
("NeoPedal.imported-<time>" or "NeoPedal.before-import-<time>").

Folders:
    Windows: %APPDATA%/<id> (global config)
    Linux:   $XDG_CONFIG_HOME/<id> (config, presets) & $XDG_DATA_HOME/<id> (data)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime

from ..const_app import CONFIG_ID, LEGACY_CONFIG_ID, PLATFORM
from ..version import SETTING_VERSION

logger = logging.getLogger(__name__)

CONFIG_FILE = "config.json"
TEMP_SUFFIX = ".migrating"
# Runtime files of a running app, not settings
SKIPPED_FILES = ("pid.log", "*.lock", "*.tmp")
STATE_FILE = "migration.json"

STATE_PENDING = "pending"
STATE_KEPT = "kept"
STATE_DEFAULT = "default"
STATE_RESET = "reset"
STATE_REIMPORT = "reimport"
REQUESTED_STATES = (STATE_RESET, STATE_REIMPORT)

_folder_ids: dict[str, str] = {}  # kind: folder id in use
_report: list[tuple[int, str]] = []  # (log level, message)


def _record(level: int, message: str) -> None:
    _report.append((level, message))


def log_migration_report(target: logging.Logger = logger) -> None:
    """Write migration messages to log (once logging is set)"""
    while _report:
        level, message = _report.pop(0)
        target.log(level, message)


def base_folder(kind: str) -> str:
    """Base folder of user folders: kind "config" or "data" (Linux only)"""
    if PLATFORM.WINDOWS:
        return os.getenv("APPDATA", ".")
    from xdg import BaseDirectory as BD
    return BD.xdg_data_home if kind == "data" else BD.xdg_config_home


def read_state(config_folder: str) -> dict:
    """Migration state of config folder, empty if none (folder not made by migration)"""
    try:
        with open(os.path.join(config_folder, STATE_FILE), encoding="utf-8") as jsonfile:
            state = json.load(jsonfile)
    except (OSError, ValueError):
        return {}
    if not isinstance(state, dict) or not isinstance(state.get("state"), str):
        return {}
    return state


def write_state(config_folder: str, state: str, source: str = "") -> bool:
    """Save migration state (atomic), False if failed"""
    data = read_state(config_folder)
    data.update({"state": state, "updated": datetime.now().isoformat(timespec="seconds")})
    if source:
        data["source"] = source
    filename = os.path.join(config_folder, STATE_FILE)
    temp_file = f"{filename}{TEMP_SUFFIX}"
    try:
        with open(temp_file, "w", encoding="utf-8") as jsonfile:
            json.dump(data, jsonfile, indent=4)
        os.replace(temp_file, filename)
    except OSError as error:
        logger.error("MIGRATION: state not saved in %s: %s", filename, error)
        return False
    return True


def legacy_config_folder() -> str:
    """Legacy config folder ("TinyPedal"), shared with original TinyPedal"""
    return os.path.join(base_folder("config"), LEGACY_CONFIG_ID)


def request_change(config_folder: str, state: str) -> bool:
    """Ask for default settings (STATE_RESET) or new copy (STATE_REIMPORT) on next start"""
    if state not in REQUESTED_STATES:
        raise ValueError(f"not a requested state: {state}")
    if state == STATE_REIMPORT and not os.path.isdir(legacy_config_folder()):
        return False
    return write_state(config_folder, state)


def version_tuple(text: str) -> tuple[int, ...]:
    """Version numbers ("2.50.5" -> (2, 50, 5)), empty if invalid"""
    try:
        return tuple(int(part) for part in text.split("."))
    except (AttributeError, ValueError):
        return ()


def check_setting_version(config_file: str) -> None:
    """Note settings saved by a newer TinyPedal: options unknown here are ignored by loader"""
    try:
        with open(config_file, encoding="utf-8") as jsonfile:
            config = json.load(jsonfile)
        version = str(config["preset"]["version"])
    except (OSError, ValueError, KeyError, TypeError):
        return
    if version_tuple(version) > version_tuple(SETTING_VERSION):
        _record(logging.INFO, f"MIGRATION: settings saved by a newer TinyPedal ({version}), "
                f"options unknown to this version ({SETTING_VERSION}) are ignored")


def apply_requested_change(new_folder: str, old_folder: str) -> None:
    """Default settings or new copy asked last run: set current folder aside first"""
    state = read_state(new_folder).get("state") if os.path.isdir(new_folder) else None
    if state not in REQUESTED_STATES:
        return
    if state == STATE_REIMPORT and not os.path.isdir(old_folder):
        _record(logging.WARNING, f"MIGRATION: new copy skipped, {old_folder} not found")
        write_state(new_folder, STATE_KEPT)
        return
    label = "imported" if state == STATE_RESET else "before-import"
    aside = f"{new_folder}.{label}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    try:
        os.rename(new_folder, aside)
    except OSError as error:  # folder in use: request kept, applied on next start
        _record(logging.ERROR, f"MIGRATION: {new_folder} not set aside, retried next start: {error}")
        return
    _record(logging.INFO, f"MIGRATION: {new_folder} set aside as {aside}")
    if state == STATE_RESET:
        try:
            os.makedirs(new_folder)
        except OSError as error:
            _record(logging.ERROR, f"MIGRATION: {new_folder} not created: {error}")
            return
        write_state(new_folder, STATE_DEFAULT, old_folder)
        _record(logging.INFO, "MIGRATION: started with default settings")


def rewrite_config_paths(config_file: str, path_map: dict[str, str]) -> int:
    """Point "user_path" values inside legacy folders to new folders, return changed count"""
    with open(config_file, encoding="utf-8") as jsonfile:
        config = json.load(jsonfile)
    user_path = config.get("user_path") if isinstance(config, dict) else None
    if not isinstance(user_path, dict):
        return 0
    changed = 0
    for key, value in user_path.items():
        if not isinstance(value, str):
            continue
        for old_root, new_root in path_map.items():
            # Same root or sub folder (both separators: paths are saved with "/")
            normalized = value.replace("\\", "/")
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


def migrate_folder(
    old_folder: str, new_folder: str, path_map: dict[str, str] | None = None, state: str = ""
) -> bool:
    """Copy legacy folder to new folder if new one does not exist, return False if copy failed

    path_map: legacy roots to new roots, rewritten in copied config.json "user_path".
    state: migration state saved in copy (config folder only).
    """
    if os.path.exists(new_folder) or not os.path.isdir(old_folder):
        return True
    temp_folder = f"{new_folder}{TEMP_SUFFIX}"
    _record(logging.INFO, f"MIGRATION: copying {old_folder} to {new_folder}")
    try:
        if os.path.exists(temp_folder):  # left by an interrupted copy
            shutil.rmtree(temp_folder)
        try:
            shutil.copytree(old_folder, temp_folder, ignore=shutil.ignore_patterns(*SKIPPED_FILES))
        except shutil.Error as error:  # other files copied: unreadable ones left out
            _record(logging.WARNING, f"MIGRATION: some files not copied: {error}")
            os.makedirs(temp_folder, exist_ok=True)
        config_file = os.path.join(temp_folder, CONFIG_FILE)
        if os.path.isfile(config_file):
            check_setting_version(config_file)
        if path_map and os.path.isfile(config_file):
            try:
                changed = rewrite_config_paths(config_file, path_map)
                if changed:
                    _record(logging.INFO, f"MIGRATION: {changed} user path(s) updated in {CONFIG_FILE}")
            except (OSError, ValueError) as error:  # invalid json: loader resets it as before
                _record(logging.WARNING, f"MIGRATION: user paths not updated in {CONFIG_FILE}: {error}")
        if state and not write_state(temp_folder, state, old_folder):
            raise OSError(f"{STATE_FILE} not saved")
        os.rename(temp_folder, new_folder)
    except (OSError, shutil.Error) as error:
        _record(logging.ERROR, f"MIGRATION: failed, {old_folder} not used (kept for TinyPedal), "
                f"starting with default settings: {error}")
        shutil.rmtree(temp_folder, ignore_errors=True)
        return False
    _record(logging.INFO, f"MIGRATION: done, {old_folder} kept unchanged")
    return True


def user_folder_id(kind: str = "config") -> str:
    """Folder name of user folders (kind "config" or "data"), migrate legacy folder first

    Migration runs once per kind & run. Linux data folder is migrated before config folder,
    copied config.json points to new data folder. Legacy folder is never used (shared with
    a running TinyPedal), even if copy failed: see module doc.
    """
    folder_id = _folder_ids.get(kind)
    if folder_id is not None:
        return folder_id
    path_map = {}
    if kind == "config" and not PLATFORM.WINDOWS:
        user_folder_id("data")
        data_base = base_folder("data")
        path_map[os.path.join(data_base, LEGACY_CONFIG_ID)] = os.path.join(data_base, CONFIG_ID)
    base = base_folder(kind)
    old_folder = os.path.join(base, LEGACY_CONFIG_ID)
    new_folder = os.path.join(base, CONFIG_ID)
    path_map[old_folder] = new_folder
    state = ""
    if kind == "config":
        reimport = read_state(new_folder).get("state") == STATE_REIMPORT
        apply_requested_change(new_folder, old_folder)
        state = STATE_KEPT if reimport else STATE_PENDING  # asked for new copy: not asked again
    migrate_folder(old_folder, new_folder, path_map, state)
    _folder_ids[kind] = CONFIG_ID
    return CONFIG_ID
