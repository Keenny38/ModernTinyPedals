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

Request saved in config folder ("import_request.json"), applied on next start once no other instance
runs, before settings are loaded (a running app would save its settings over imported ones), see
apply_pending_import & main.apply_settings_import.
Source folder is copied, never moved nor modified. Current folder is never deleted: it is
renamed next to it ("<folder>.before-import-<time>") before the copy, and put back if the copy
fails; every folder set aside is kept (backups the user may import again, as told before
importing). Runtime files of a running app (pid.log, lock & temporary files) and lap cache
(rebuilt from laps) are not copied. A copy failing on disk errors (full, I/O) is not used.

Linux: data folder of same name next to source (XDG data home) is imported too, and
"user_path" values of copied config.json pointing inside source folders are updated.

Runs before logging is set: messages are kept and written to log by log_import_report().
"""

from __future__ import annotations

import errno
import json
import logging
import os
import shutil
from datetime import datetime

from . import atomic_replace, encode_text, read_json

logger = logging.getLogger(__name__)

REQUEST_FILE = "import_request.json"
CONFIG_FILE = "config.json"
SETTINGS_FILES = (CONFIG_FILE, "shortcuts.json")  # one of them: a global settings folder
SKIPPED_FILES = ("pid.log", "*.lock", "*.tmp", "startup.marker", REQUEST_FILE, ".lap_cache")
TEMP_SUFFIX = ".importing"
# Copy errors of a failing disk (full, quota, I/O, CRC): copy not used (files cut short), unlike files in use
FATAL_COPY_ERRORS = ("[Errno 28]", "[Errno 122]", "[Errno 5]", "[WinError 112]", "[WinError 39]", "[WinError 23]",
                     "No space left")
ASIDE_SUFFIX = ".before-import-"  # + time stamp: previous folder set aside
# Starts an import is tried while it fails for a temporary cause (files in use by an instance closing, antivirus,
# sync tool), request kept for next start; never retried in a loop within a start
MAX_IMPORT_ATTEMPTS = 3
TEMPORARY_ERRNOS = (errno.EACCES, errno.EBUSY, errno.ETXTBSY, errno.EPERM)
TEMPORARY_WINERRORS = (5, 32, 33)  # access denied, sharing violation, lock violation

_report: list[tuple[int, str]] = []  # (log level, message)


def _record(level: int, message: str) -> None:
    _report.append((level, message))


def record_message(level: int, message: str) -> None:
    """Import message written to log once logging is set (see log_import_report)"""
    _record(level, message)


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
    data = {"source": os.path.abspath(source), "requested": datetime.now().isoformat(timespec="seconds")}
    try:
        atomic_replace(filename, encode_text(json.dumps(data, indent=4)))
    except OSError as error:
        logger.error("IMPORT: request not saved in %s: %s", filename, error)
        return False
    logger.info("IMPORT: settings of %s imported on next start", source)
    return True


def read_request(config_folder: str) -> str:
    """Source folder of pending import request, empty if none"""
    source = _request_data(config_folder).get("source")
    return source if isinstance(source, str) else ""


def _request_data(config_folder: str) -> dict:
    return read_json(os.path.join(config_folder, REQUEST_FILE), strict=False, default={}, dict_only=True)


def is_temporary_error(error: BaseException) -> bool:
    """Import failed on files in use (may work on next start), not on a failing disk or a bad source"""
    if isinstance(error, shutil.Error) or not isinstance(error, OSError):
        return False
    return (getattr(error, "winerror", None) in TEMPORARY_WINERRORS or isinstance(error, PermissionError)
            or error.errno in TEMPORARY_ERRNOS)


def keep_request(config_folder: str, source: str, attempts: int) -> bool:
    """Request saved again for next start (temporary failure), False once tried MAX_IMPORT_ATTEMPTS times"""
    if attempts >= MAX_IMPORT_ATTEMPTS:
        return False
    data = {"source": source, "requested": datetime.now().isoformat(timespec="seconds"), "attempts": attempts}
    try:
        atomic_replace(os.path.join(config_folder, REQUEST_FILE), encode_text(json.dumps(data, indent=4)))
    except OSError as error:
        _record(logging.ERROR, f"IMPORT: request not kept for next start: {error}")
        return False
    return True


def clear_request(config_folder: str) -> None:
    try:
        os.remove(os.path.join(config_folder, REQUEST_FILE))
    except FileNotFoundError:
        pass
    except OSError as error:
        _record(logging.ERROR, f"IMPORT: request not removed: {error}")


def rewrite_config_paths(config_file: str, path_map: dict[str, str]) -> int:
    """Point "user_path" values inside source folders to new folders, return changed count"""
    with open(config_file, encoding="utf-8-sig") as jsonfile:
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
        atomic_replace(config_file, encode_text(json.dumps(config, indent=4)))
    return changed


def is_fatal_copy_error(error: shutil.Error) -> bool:
    """Copy error of a failing disk (copied files may be cut short), not files left out (in use, locked)"""
    entries = error.args[0] if error.args and isinstance(error.args[0], list) else [error.args]
    return any(marker in str(entry) for entry in entries for marker in FATAL_COPY_ERRORS)


def restore_folder(target: str, aside: str) -> None:
    """Folder imported to target removed, folder set aside (if any) put back"""
    shutil.rmtree(target, ignore_errors=True)
    if aside:
        os.rename(aside, target)


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
        if is_fatal_copy_error(error):
            shutil.rmtree(temp_folder, ignore_errors=True)
            raise OSError(f"copy failed: {error}") from error
        _record(logging.WARNING, f"IMPORT: some files not copied: {error}")
        os.makedirs(temp_folder, exist_ok=True)
    except OSError:
        shutil.rmtree(temp_folder, ignore_errors=True)
        raise
    aside = ""
    try:
        if os.path.exists(target):
            aside = f"{target}{ASIDE_SUFFIX}{stamp}"
            os.rename(target, aside)  # fails if files are in use (another app running): nothing changed
            try:
                os.rename(temp_folder, target)
            except OSError:
                os.rename(aside, target)
                raise
        else:
            os.rename(temp_folder, target)
    except OSError:
        shutil.rmtree(temp_folder, ignore_errors=True)
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
    request = _request_data(config_folder)
    source = read_request(config_folder)
    if not source:
        return False
    attempts = request.get("attempts", 0)
    attempts = (attempts if isinstance(attempts, int) and not isinstance(attempts, bool) else 0) + 1
    clear_request(config_folder)  # never retried in a loop: kept for next start only if failed on files in use
    if not is_settings_folder(source, config_folder):
        _record(logging.WARNING, f"IMPORT: {source} is not a settings folder, nothing imported")
        return False
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path_map = {source: config_folder}
    data_imported: tuple[str, str] | None = None  # data folder & its previous folder set aside
    if data_folder:
        data_folder = data_folder.rstrip("/\\")
        source_data = os.path.join(os.path.dirname(data_folder), os.path.basename(source.rstrip("/\\")))
        if os.path.isdir(source_data) and not same_folder(source_data, data_folder):
            try:
                aside = replace_folder(source_data, data_folder, stamp)
                data_imported = data_folder, aside
                path_map[source_data] = data_folder
                _record(logging.INFO, f"IMPORT: data copied from {source_data}"
                        + (f", previous data set aside as {aside}" if aside else ""))
            except (OSError, shutil.Error) as error:
                _record(logging.ERROR, f"IMPORT: data of {source_data} not imported: {error}")
    try:
        aside = replace_folder(source, config_folder, stamp)
    except (OSError, shutil.Error) as error:
        _record(logging.ERROR, f"IMPORT: settings of {source} not imported, current settings kept: {error}")
        if is_temporary_error(error) and keep_request(config_folder, source, attempts):
            _record(logging.WARNING, f"IMPORT: files in use, tried again on next start "
                                     f"(attempt {attempts} of {MAX_IMPORT_ATTEMPTS})")
        if data_imported is not None:  # data of source never used with current settings: put back
            try:
                restore_folder(*data_imported)
            except OSError as restore_error:
                _record(logging.ERROR, f"IMPORT: previous data not put back from {data_imported[1]}: {restore_error}")
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
