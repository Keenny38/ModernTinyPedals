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
Setting file function
"""

from __future__ import annotations

import errno
import filecmp
import io
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
from . import REPLACE_ATTEMPTS, REPLACE_RETRY_DELAY, atomic_write, encode_text

logger = logging.getLogger(__name__)

# Seconds a file locked for a moment (antivirus, cloud sync) is retried at load: at start nothing is shown
# yet, at reload the GUI thread waits (every overlay frozen), see is_transient_access_error
ACCESS_TIMEOUT = 2.0
RELOAD_ACCESS_TIMEOUT = 0.3
TRANSIENT_WINERRORS = (5, 32, 33)  # access denied, sharing violation, lock violation
TRANSIENT_ERRNOS = (errno.EACCES, errno.EBUSY, errno.ETXTBSY)

_stamp_lock = threading.Lock()
_last_stamp_us = 0  # last backup timestamp (microseconds), see set_backup_timestamp

# Files that could not be read at load (locked by antivirus or cloud sync, not corrupted):
# defaults are used, and the file is never saved over this session (user data kept)
_unreadable_files: set[str] = set()
_notified_files: set[str] = set()  # unreadable files user was told about (once per file)


def _file_key(filename_source: str) -> str:
    """Normalized file path for unreadable file set"""
    return os.path.normcase(os.path.abspath(filename_source))


def is_saving_backup(filename: str) -> bool:
    """File (with path) is the temporary backup of a save in progress (removed once saved)"""
    with _saving_lock:
        return bool(_saving_backups) and _file_key(filename) in _saving_backups


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
_saving_backups: set[str] = set()  # temporary backups of saves in progress, see is_saving_backup
_saving_lock = threading.Lock()
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


def notify_save_failed(filename: str) -> None:
    """Tell user a file could not be saved (every attempt failed): changes are only in memory"""
    _show_notice(
        f"{filename} could not be saved (file locked by another program, or disk error?): "
        "your changes are kept in memory and saved again with the next change."
    )


def is_unreadable_file(filename: str, filepath: str) -> bool:
    """Check if file could not be read at load, so must not be saved over"""
    return _file_key(f"{filepath}{filename}") in _unreadable_files


def is_transient_access_error(error: OSError) -> bool:
    """File held by another program for a moment (antivirus scan, cloud sync, lock): worth a retry,
    unlike a permanent error (a folder in place of the file, invalid path, I/O error)"""
    winerror = getattr(error, "winerror", None)
    if winerror:  # None or 0 when not raised by Windows itself
        return winerror in TRANSIENT_WINERRORS
    return error.errno in TRANSIENT_ERRNOS


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


def _retry_access(error: OSError, access_deadline: float) -> bool:
    """Whether a failed read is tried again (file held for a moment, deadline not passed), after a short wait"""
    if not is_transient_access_error(error) or monotonic() >= access_deadline:
        return False
    sleep(0.05)
    return True


def read_setting_json_file(
    filename: str, filepath: str, dict_def: dict, file_info: str = "user preset",
    validator: Callable[[dict, dict], dict] = PresetValidator.user_preset, access_timeout: float = ACCESS_TIMEOUT,
) -> tuple[dict, bool]:
    """Load setting json file & verify

    A file held by another program (antivirus, cloud sync) is retried up to access_timeout seconds; then,
    as for any other access error, defaults are used without saving them over the file this session.
    A corrupted file (invalid JSON or values) is never read again: kept as backup, defaults used at once.

    Returns:
        Setting, and whether saving it would change the file: missing, corrupted, repaired or migrated
        by the validator (a file saved as it is not rewritten at start).
    """
    filename_source = f"{filepath}{filename}"
    access_deadline = monotonic() + access_timeout
    while True:
        try:
            with open(filename_source, encoding="utf-8-sig") as jsonfile:  # BOM of Notepad, PowerShell
                text = jsonfile.read()  # kept: compared with the setting as it would be saved
            setting_user = json.load(io.StringIO(text))
            # Verify & assign setting
            setting_user = validator(setting_user, dict_def)
            _unreadable_files.discard(_file_key(filename_source))
            _notified_files.discard(_file_key(filename_source))
            changed = setting_json_text(setting_user) != text  # as saved (indent, key order, values)
            break
        except FileNotFoundError:
            logger.info("USERDATA: %s not found, fall back to default", filename)
            setting_user = copy_setting(dict_def)
            changed = True
            break
        except OSError as error:  # locked, not corrupted: retry for a while, never overwrite
            if _retry_access(error, access_deadline):
                continue
            logger.error("USERDATA: %s not accessible, fall back to default (file kept, not saved)", filename, exc_info=True)
            _unreadable_files.add(_file_key(filename_source))
            setting_user = copy_setting(dict_def)
            changed = False
            break
        # corrupted (RecursionError: nested too deep, never a crash at start): same result if read again
        except (AttributeError, IndexError, KeyError, RecursionError, TypeError, ValueError):
            logger.error("USERDATA: %s failed loading, fall back to default", filename, exc_info=True)
            create_backup_file(filename, filepath, set_backup_timestamp(), show_log=True)
            setting_user = copy_setting(dict_def)
            changed = True
            break

    logger.info("USERDATA: %s loaded (%s)", filename, file_info)
    return setting_user, changed


def load_setting_json_file(
    filename: str, filepath: str, dict_def: dict, file_info: str = "user preset",
    validator: Callable[[dict, dict], dict] = PresetValidator.user_preset, access_timeout: float = ACCESS_TIMEOUT,
) -> dict:
    """Load setting json file & verify, see read_setting_json_file"""
    return read_setting_json_file(filename, filepath, dict_def, file_info, validator, access_timeout)[0]


def read_style_json_file(
    filename: str, filepath: str, dict_def: dict, file_info: str = "style preset",
    validator: Callable[[dict], bool] | None = None, access_timeout: float = ACCESS_TIMEOUT,
) -> tuple[dict, bool]:
    """Load style json file & verify (optional), see read_setting_json_file for locked & corrupted file

    Returns:
        Style, and whether it must be saved (file missing, corrupted or updated by validator): caller
        saves it (queued save with backup & verification, or save_json_file at once).
    """
    filename_source = f"{filepath}{filename}"
    msg_text = "loaded"
    access_deadline = monotonic() + access_timeout
    while True:
        try:
            with open(filename_source, encoding="utf-8-sig") as jsonfile:  # BOM of Notepad, PowerShell
                style_user = json.load(jsonfile)
            _unreadable_files.discard(_file_key(filename_source))
            _notified_files.discard(_file_key(filename_source))
            if not isinstance(style_user, dict):  # list or value at top: invalid like corrupted file
                raise TypeError(f"{filename} is not a JSON object")
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
        except OSError as error:  # locked, not corrupted: retry for a while, never overwrite
            if _retry_access(error, access_deadline):
                continue
            logger.error("USERDATA: %s not accessible, fall back to default (file kept, not saved)", filename, exc_info=True)
            _unreadable_files.add(_file_key(filename_source))
            style_user = copy_setting(dict_def)
            msg_text = "fall back to default"
            break
        # corrupted (RecursionError: nested too deep, never a crash at start): same result if read again
        except (AttributeError, IndexError, KeyError, RecursionError, TypeError, ValueError):
            logger.error("USERDATA: %s failed loading, fall back to default", filename, exc_info=True)
            create_backup_file(filename, filepath, set_backup_timestamp(), show_log=True)
            style_user = copy_setting(dict_def)
            msg_text = "updated"
            break

    logger.info("USERDATA: %s %s (%s)", filename, msg_text, file_info)
    return style_user, msg_text == "updated"


def load_style_json_file(
    filename: str, filepath: str, dict_def: dict, file_info: str = "style preset",
    validator: Callable[[dict], bool] | None = None, access_timeout: float = ACCESS_TIMEOUT,
) -> dict:
    """Load style json file & verify (optional), saved at once if missing or updated (start, no GUI yet)

    Setting.load_styles reads with read_style_json_file and queues the save instead (reload on GUI thread).
    """
    style_user, changed = read_style_json_file(filename, filepath, dict_def, file_info, validator, access_timeout)
    if changed:
        save_json_file(style_user, filename, filepath)
    return style_user


def setting_json_text(dict_user: dict, compact_json: bool = False, max_attempts: int = 20) -> str:
    """Serialize setting in one shot, retry if dict is modified by other thread meanwhile

    Raises:
        TypeError, ValueError: data not serializable.
    """
    options: dict = {"separators": (",", ":")} if compact_json else {"indent": 4}
    for _ in range(max_attempts - 1):
        try:
            return json.dumps(dict_user, **options)
        except RuntimeError:  # dictionary changed size during iteration
            sleep(0.005)
    return json.dumps(dict_user, **options)


def save_json_file(
    dict_user: dict, filename: str, filepath: str, extension: str = "", compact_json: bool = False,
    text: str | None = None,
) -> None:
    """Save json file atomically (temporary file replaces target), error logged

    Existing file is never left half-written or empty (crash, power loss, full disk).
    Text (serialized dict_user, see setting_json_text) is written as is if given.
    """
    if text is None:
        text = setting_json_text(dict_user, compact_json)
    filename_source = f"{filepath}{filename}{extension}"
    with atomic_write(filename_source) as jsonfile:
        jsonfile.write(text)


def verify_json_file(
    dict_user: dict | None, filename: str, filepath: str, extension: str = "", text: str | None = None
) -> bool:
    """Verify saved json file, by byte compare with written text if given (see save_json_file)"""
    filename_source = f"{filepath}{filename}{extension}"
    try:
        if text is not None:
            with open(filename_source, "rb") as file:
                return file.read() == encode_text(text)
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
    except (AttributeError, RecursionError, TypeError, ValueError, OSError):
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
        # Source held by antivirus or cloud sync for a moment: retried as replace_retry does, a failed
        # backup aborts the save (data stays queued, see Setting.__saving)
        copied = False
        for attempt in range(1, REPLACE_ATTEMPTS + 1):
            try:
                copied = copy_and_verify_file(filename_source, filename_backup)
                break
            except PermissionError:
                if attempt >= REPLACE_ATTEMPTS:
                    raise
                sleep(REPLACE_RETRY_DELAY * attempt)
        if not copied:
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
) -> bool:
    """Save and verify json file, backup or restore if saving failed, True if saved & verified"""
    if is_unreadable_file(filename, filepath):
        # Never retry & save here: defaults (in memory since load) would overwrite user data
        # of a file readable again, only tell user that session changes are not saved
        logger.info("USERDATA: %s was not accessible at load, saving skipped (file kept)", filename)
        _notify_save_skipped(filename, filepath)
        return False
    # Serialize once (snapshot of dict_user), byte compared after each write
    try:
        text = setting_json_text(dict_user, compact_json)
    except (TypeError, ValueError) as error:  # data not serializable, file untouched
        logger.error("USERDATA: %s failed saving, invalid data: %s", filename, error)
        return False
    backup_extension = set_backup_timestamp()
    backup_key = _file_key(f"{filepath}{filename}{backup_extension}")
    with _saving_lock:
        _saving_backups.add(backup_key)
    try:
        return _save_with_backup(dict_user, filename, filepath, max_attempts, compact_json, text, backup_extension)
    finally:
        with _saving_lock:
            _saving_backups.discard(backup_key)


def _save_with_backup(
    dict_user: dict, filename: str, filepath: str, max_attempts: int, compact_json: bool, text: str,
    backup_extension: str,
) -> bool:
    """Save & verify json file, file backed up first (backup_extension) if exists, see save_and_verify_json_file"""
    filename_source = f"{filepath}{filename}"
    file_found = os.path.exists(filename_source)
    # Create backup: abort saving if backup failed; skip backup and create new if not exist
    if not file_found:
        logger.info("USERDATA: %s not found, create new", filename)
    elif _file_holds(filename_source, encode_text(text)):
        # Same bytes already on disk (start, preset loaded again): one read instead of backup, write with
        # fsync & read back. Modified time still set: the preset loaded last is the most recent one (start)
        with suppress(OSError):
            os.utime(filename_source)
        logger.info("USERDATA: %s unchanged, not written", filename)
        return True
    elif not create_backup_file(filename, filepath, backup_extension):
        logger.info("USERDATA: %s saving abort", filename)
        return False
    # Start saving attempts
    attempts = max_attempts
    timer_start = monotonic()
    while attempts > 0:
        save_json_file(dict_user, filename, filepath, compact_json=compact_json, text=text)
        if verify_json_file(dict_user, filename, filepath, text=text):
            break
        attempts -= 1
        logger.error("USERDATA: %s failed saving, %s attempt(s) left", filename, attempts)
        sleep(0.05)
    timer_end = round((monotonic() - timer_start) * 1000)
    # Clean up
    if attempts > 0:
        state_text = "saved"
    else:
        if file_found and not restore_backup_file(filename, filepath, backup_extension):
            if not copy_and_rename_backup_file(filename, filepath, backup_extension):
                return False  # abort without delete backup
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
    return attempts > 0


def _file_holds(filename_source: str, data: bytes) -> bool:
    """Whether file holds exactly data (False if it cannot be read: saved as usual)"""
    try:
        with open(filename_source, "rb") as file:
            return file.read() == data
    except OSError:
        return False


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
