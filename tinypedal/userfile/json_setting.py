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
Setting file function
"""

from __future__ import annotations

import filecmp
import json
import logging
import os
import shutil
import threading
from collections.abc import Callable
from contextlib import suppress
from time import localtime, monotonic, sleep, strftime, time

from ..const_file import FileExt
from ..setting_validator import PresetValidator
from . import atomic_write

logger = logging.getLogger(__name__)


_stamp_lock = threading.Lock()
_last_stamp_us = 0  # last backup timestamp (microseconds), see set_backup_timestamp

# Files that could not be read at load (locked by antivirus or cloud sync, not corrupted):
# defaults are used, and the file is never saved over this session (user data kept)
_unreadable_files: set[str] = set()
_notified_files: set[str] = set()  # unreadable files user was told about (once per file)


def _file_key(filename_source: str) -> str:
    """Normalized file path for unreadable file set"""
    return os.path.normcase(os.path.abspath(filename_source))


def _notify_save_skipped(filename: str, filepath: str) -> None:
    """Notify user once that changes of an unreadable file are not saved

    Notified at first skipped save, not at load: global config is loaded before main window
    exists (message would be lost).
    """
    key = _file_key(f"{filepath}{filename}")
    if key in _notified_files:
        return
    _notified_files.add(key)
    _show_notice(
        f"{filename} could not be read at load (locked by another program?): default settings are used "
        "and changes are not saved this session to keep your file. Restart the app to load it."
    )


_notice_lock = threading.Lock()
_notices_ready = False  # main window shows error messages
_pending_notices: list[str] = []  # messages sent before main window was ready


def _show_notice(message: str) -> None:
    """Show error message, kept until main window is ready (first save runs right after start)"""
    with _notice_lock:
        if not _notices_ready:
            _pending_notices.append(message)
            return
    from .. import app_signal  # lazy, userfile is imported early

    app_signal.error.emit(message)


def notices_ready() -> None:
    """Main window shows error messages: send messages kept until now"""
    global _notices_ready
    with _notice_lock:
        _notices_ready = True
        pending = tuple(_pending_notices)
        _pending_notices.clear()
    from .. import app_signal

    for message in pending:
        app_signal.error.emit(message)


def is_unreadable_file(filename: str, filepath: str) -> bool:
    """Check if file could not be read at load, so must not be saved over"""
    return _file_key(f"{filepath}{filename}") in _unreadable_files


def set_backup_timestamp(prefix: str = FileExt.BACKUP, timestamp: bool = True) -> str:
    """Set backup timestamp, unique in this process

    A coarse clock (15 ms with Python 3.11 on Windows) gives equal times in a row: a backup
    made just before saving (unreadable file) would get the same name as the temporary backup
    of the save, then be deleted with it. Equal times are moved 1 microsecond later.
    """
    if timestamp:
        global _last_stamp_us
        with _stamp_lock:
            stamp_us = max(int(time() * 1_000_000), _last_stamp_us + 1)
            _last_stamp_us = stamp_us
        seconds, microseconds = divmod(stamp_us, 1_000_000)
        time_stamp = f"-{strftime('%Y-%m-%d-%H-%M-%S', localtime(seconds))}-{microseconds:06d}"
    else:
        time_stamp = ""
    return f"{prefix}{time_stamp}"


def copy_setting(dict_user: dict) -> dict:
    """Copy setting"""
    for item in dict_user.values():
        if isinstance(item, dict):
            return {key: item.copy() for key, item in dict_user.items()}
        break
    return dict_user.copy()


def load_setting_json_file(
    filename: str, filepath: str, dict_def: dict, file_info: str = "user preset",
    validator: Callable[[dict, dict], dict] = PresetValidator.user_preset, max_attempts: int = 5,
    access_timeout: float = 2.0,
) -> dict:
    """Load setting json file & verify

    A file that cannot be accessed (locked, no permission) is retried up to access_timeout
    seconds, then defaults are used without saving them over the file this session.
    """
    filename_source = f"{filepath}{filename}"
    # Start loading attempts
    attempts = max_attempts
    access_deadline = monotonic() + access_timeout
    while attempts > 0:
        try:
            with open(filename_source, encoding="utf-8") as jsonfile:
                setting_user = json.load(jsonfile)
            # Verify & assign setting
            setting_user = validator(setting_user, dict_def)
            _unreadable_files.discard(_file_key(filename_source))
            _notified_files.discard(_file_key(filename_source))
            break
        except FileNotFoundError:
            logger.info("USERDATA: %s not found, fall back to default", filename)
            setting_user = copy_setting(dict_def)
            break
        except OSError:  # locked, not corrupted: retry longer, never overwrite
            if monotonic() < access_deadline:
                sleep(0.05)
                continue
            logger.error("USERDATA: %s not accessible, fall back to default (file kept, not saved)", filename, exc_info=True)
            _unreadable_files.add(_file_key(filename_source))
            setting_user = copy_setting(dict_def)
            break
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            logger.error("USERDATA: %s failed loading, %s attempt(s) left", filename, attempts - 1, exc_info=(attempts <= 1))
        attempts -= 1
        sleep(0.05)
    else:
        logger.error("USERDATA: %s failed loading, fall back to default", filename)
        create_backup_file(filename, filepath, set_backup_timestamp(), show_log=True)
        setting_user = copy_setting(dict_def)

    logger.info("USERDATA: %s loaded (%s)", filename, file_info)
    return setting_user


def load_style_json_file(
    filename: str, filepath: str, dict_def: dict, file_info: str = "style preset",
    validator: Callable[[dict], bool] | None = None, max_attempts: int = 5,
    access_timeout: float = 2.0,
) -> dict:
    """Load style json file & verify (optional), see load_setting_json_file for locked file"""
    filename_source = f"{filepath}{filename}"
    msg_text = "loaded"
    # Start loading attempts
    attempts = max_attempts
    access_deadline = monotonic() + access_timeout
    while attempts > 0:
        try:
            with open(filename_source, encoding="utf-8") as jsonfile:
                style_user = json.load(jsonfile)
            _unreadable_files.discard(_file_key(filename_source))
            _notified_files.discard(_file_key(filename_source))
            # Whether to validate style
            if validator is not None and validator(style_user):
                create_backup_file(filename, filepath, set_backup_timestamp(), show_log=True)
                msg_text = "updated"
            break
        except FileNotFoundError:
            logger.info("USERDATA: %s not found, fall back to default", filename)
            style_user = copy_setting(dict_def)
            msg_text = "updated"
            break
        except OSError:  # locked, not corrupted: retry longer, never overwrite
            if monotonic() < access_deadline:
                sleep(0.05)
                continue
            logger.error("USERDATA: %s not accessible, fall back to default (file kept, not saved)", filename, exc_info=True)
            _unreadable_files.add(_file_key(filename_source))
            style_user = copy_setting(dict_def)
            msg_text = "fall back to default"
            break
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            logger.error("USERDATA: %s failed loading, %s attempt(s) left", filename, attempts - 1, exc_info=(attempts <= 1))
        attempts -= 1
        sleep(0.05)
    else:
        logger.error("USERDATA: %s failed loading, fall back to default", filename)
        create_backup_file(filename, filepath, set_backup_timestamp(), show_log=True)
        style_user = copy_setting(dict_def)
        msg_text = "updated"

    if msg_text == "updated":
        save_json_file(style_user, filename, filepath)

    logger.info("USERDATA: %s %s (%s)", filename, msg_text, file_info)
    return style_user


def save_json_file(
    dict_user: dict, filename: str, filepath: str, extension: str = "", compact_json: bool = False
) -> None:
    """Save json file atomically (temporary file replaces target), error logged

    Existing file is never left half-written or empty (crash, power loss, full disk).
    """
    filename_source = f"{filepath}{filename}{extension}"
    with atomic_write(filename_source) as jsonfile:
        if compact_json:
            json.dump(dict_user, jsonfile, separators=(",", ":"))
        else:
            json.dump(dict_user, jsonfile, indent=4)


def verify_json_file(
    dict_user: dict | None, filename: str, filepath: str, extension: str = ""
) -> bool:
    """Verify saved json file"""
    filename_source = f"{filepath}{filename}{extension}"
    try:
        with open(filename_source, encoding="utf-8") as jsonfile:
            # Check load only
            if dict_user is None:
                json.load(jsonfile)
                return True
            # Compare saved data with loaded
            saved = json.dumps(json.load(jsonfile))
            loaded = json.dumps(dict_user)
            return saved == loaded
    except FileNotFoundError:
        logger.error("USERDATA: not found %s", filename_source)
    except (AttributeError, TypeError, ValueError, OSError):
        logger.error("USERDATA: unable to verify %s", filename_source)
    return False


def copy_and_verify_file(filename_source: str, filename_copied: str) -> bool:
    """Copy and verify (compare) json file"""
    shutil.copyfile(filename_source, filename_copied)
    return filecmp.cmp(filename_source, filename_copied)


def create_backup_file(
    filename: str, filepath: str, extension: str = FileExt.BACKUP, show_log: bool = False
) -> bool:
    """Create backup file before saving"""
    filename_source = f"{filepath}{filename}"
    filename_backup = f"{filepath}{filename}{extension}"
    backup_existed = os.path.exists(filename_backup)
    try:
        if not copy_and_verify_file(filename_source, filename_backup):
            raise FileNotFoundError
        if show_log:
            logger.info("USERDATA: backup saved %s", filename_backup)
        return True
    except FileNotFoundError:
        logger.error("USERDATA: not found %s", filename_source)
    except PermissionError:
        logger.error("USERDATA: no permission to access %s", filename_source)
    except (AttributeError, TypeError, ValueError, OSError):
        logger.error("USERDATA: unable to create backup %s", filename_source)
    # Never leave incomplete backup behind
    if not backup_existed:
        with suppress(OSError):
            os.remove(filename_backup)
    return False


def restore_backup_file(
    filename: str, filepath: str, extension: str = FileExt.BACKUP
) -> bool:
    """Restore backup file if saving failed"""
    filename_backup = f"{filepath}{filename}{extension}"
    filename_source = f"{filepath}{filename}"
    try:
        if not copy_and_verify_file(filename_backup, filename_source):
            raise FileNotFoundError
        logger.info("USERDATA: backup restored %s", filename_source)
        return True
    except FileNotFoundError:
        logger.error("USERDATA: backup not found %s", filename_backup)
    except PermissionError:
        logger.error("USERDATA: no permission to access backup %s", filename_backup)
    except (AttributeError, TypeError, ValueError, OSError):
        logger.error("USERDATA: unable to restore backup %s", filename_backup)
    return False


def copy_and_rename_backup_file(
    filename: str, filepath: str, extension: str = FileExt.BACKUP
) -> bool:
    """Copy and rename backup file if restoring backup failed"""
    filename_backup = f"{filepath}{filename}{extension}"
    filename_renamed = f"{filepath}{filename}{set_backup_timestamp()}"
    try:
        if not copy_and_verify_file(filename_backup, filename_renamed):
            raise FileNotFoundError
        logger.info("USERDATA: backup renamed %s", filename_renamed)
        return True
    except FileNotFoundError:
        logger.error("USERDATA: backup not found %s", filename_backup)
    except PermissionError:
        logger.error("USERDATA: no permission to access backup %s", filename_backup)
    except (AttributeError, TypeError, ValueError, OSError):
        logger.error("USERDATA: unable to copy and rename backup %s", filename_backup)
    return False


def delete_backup_file(
    filename: str, filepath: str, extension: str = FileExt.BACKUP
) -> bool:
    """Delete backup file"""
    filename_backup = f"{filepath}{filename}{extension}"
    try:
        if os.path.exists(filename_backup):
            os.remove(filename_backup)
        return True
    except FileNotFoundError:
        logger.error("USERDATA: backup not found %s", filename_backup)
    except PermissionError:
        logger.error("USERDATA: no permission to access backup %s", filename_backup)
    except OSError:
        logger.error("USERDATA: unable to delete backup %s", filename_backup)
    return False


def save_and_verify_json_file(
    dict_user: dict,
    filename: str,
    filepath: str,
    max_attempts: int = 10,
    compact_json: bool = False,
) -> None:
    """Save and verify json file, backup or restore if saving failed"""
    if is_unreadable_file(filename, filepath):
        # Never retry & save here: defaults (in memory since load) would overwrite user data
        # of a file readable again, only tell user that session changes are not saved
        logger.info("USERDATA: %s was not accessible at load, saving skipped (file kept)", filename)
        _notify_save_skipped(filename, filepath)
        return
    file_found = os.path.exists(f"{filepath}{filename}")
    backup_extension = set_backup_timestamp()
    # Create backup: abort saving if backup failed; skip backup and create new if not exist
    if not file_found:
        logger.info("USERDATA: %s not found, create new", filename)
    elif not create_backup_file(filename, filepath, backup_extension):
        logger.info("USERDATA: %s saving abort", filename)
        return
    # Start saving attempts
    attempts = max_attempts
    timer_start = monotonic()
    try:
        while attempts > 0:
            save_json_file(dict_user, filename, filepath, compact_json=compact_json)
            if verify_json_file(dict_user, filename, filepath):
                break
            attempts -= 1
            logger.error("USERDATA: %s failed saving, %s attempt(s) left", filename, attempts)
            sleep(0.05)
    except (TypeError, ValueError) as error:  # data not serializable, file untouched (atomic write)
        logger.error("USERDATA: %s failed saving, invalid data: %s", filename, error)
        attempts = 0
    timer_end = round((monotonic() - timer_start) * 1000)
    # Clean up
    if attempts > 0:
        state_text = "saved"
    else:
        if file_found and not restore_backup_file(filename, filepath, backup_extension):
            if not copy_and_rename_backup_file(filename, filepath, backup_extension):
                return  # abort without delete backup
        state_text = "failed saving"
    if file_found:
        delete_backup_file(filename, filepath, backup_extension)
    logger.info(
        "USERDATA: %s %s (took %sms, %s/%s attempts)",
        filename,
        state_text,
        timer_end,
        max_attempts - attempts,
        attempts,
    )


def create_versioned_backup(
    filename: str,
    filepath: str,
    max_count: int = 10,
    min_interval: float = 600,
) -> bool:
    """Create automatic versioned backup before saving preset

    Backup is named as "filename.backup-auto-timestamp" next to preset file,
    so it can be restored from "Restore Backup" dialog.

    Args:
        filename: preset file name (with extension).
        filepath: preset folder.
        max_count: max number of automatic backups to keep per file, 0 to disable.
        min_interval: minimum seconds between two backups of same file.

    Returns:
        True if new backup created.
    """
    source = f"{filepath}{filename}"
    if max_count <= 0 or not os.path.exists(source):
        return False
    prefix = f"{filename}{FileExt.BACKUP}-auto-"
    backup = f"{filepath}{filename}{set_backup_timestamp(f'{FileExt.BACKUP}-auto')}"
    copied = False
    try:
        existing = sorted(name for name in os.listdir(filepath) if name.startswith(prefix))
        # Backup modified time is its creation time (preset time not copied), for interval.
        # No interval: never throttled (file time can be ahead of time() by the clock resolution)
        if min_interval > 0 and existing and time() - os.path.getmtime(f"{filepath}{existing[-1]}") < min_interval:
            return False
        shutil.copyfile(source, backup)
        copied = True
        existing = sorted(name for name in os.listdir(filepath) if name.startswith(prefix))
        for old_backup in existing[:-max_count]:
            os.remove(f"{filepath}{old_backup}")
        return True
    except OSError as error:
        logger.error("USERDATA: unable to create automatic backup of %s: %s", filename, error)
        if not copied:  # never leave incomplete backup behind
            with suppress(OSError):
                os.remove(backup)
        return copied


def rename_preset_backups(filepath: str, old_filename: str, new_filename: str) -> int:
    """Rename backups (manual & automatic) of renamed preset, so they can still be restored

    Args:
        filepath: preset folder.
        old_filename: old preset file name (with extension).
        new_filename: new preset file name (with extension).

    Returns:
        Number of renamed backups.
    """
    prefix = f"{old_filename}{FileExt.BACKUP}"
    count = 0
    try:
        backups = [name for name in os.listdir(filepath) if name.startswith(prefix)]
    except OSError as error:
        logger.error("USERDATA: unable to list backups of %s: %s", old_filename, error)
        return 0
    for backup in backups:
        new_backup = f"{new_filename}{backup[len(old_filename):]}"
        # Case only rename (Windows): new name "exists" as the same file, rename anyway
        same_file = os.path.normcase(new_backup) == os.path.normcase(backup)
        try:
            if same_file or not os.path.exists(f"{filepath}{new_backup}"):
                os.rename(f"{filepath}{backup}", f"{filepath}{new_backup}")
                count += 1
        except OSError as error:
            logger.error("USERDATA: unable to rename backup %s: %s", backup, error)
    return count
