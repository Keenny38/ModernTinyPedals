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
Preset management: names (new, duplicate, rename, restore), references, trash, transfer & backups

Plain functions (no window): the Presets page (qml/Presets.qml, quick/preset_backend.py &
quick/preset_tools_backend.py) asks and shows, these do the work.
"""

from __future__ import annotations

import html
import logging
import os
import re
import shutil
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from math import ceil
from time import time
from typing import NamedTuple

from PySide6.QtCore import QDateTime, QLocale

from .. import app_signal
from .. import regex_pattern as rxp
from ..const_file import ConfigType, FileExt
from ..formatter import strip_filename_extension
from ..i18n import current_language, tr, trm
from ..setting import RELOAD_ACCESS_TIMEOUT, cfg, load_setting_json_file, save_and_verify_json_file
from ..template.setting_classes import CLASS_PRESET_KEYS, SESSION_PRESET_KEYS
from ..template.setting_shortcuts import SHORTCUTS_PRESET
from ..userfile.json_setting import rename_preset_backups
from ..userfile.layout_profile import profile_filename
from ..userfile.preset_trash import (
    DEFAULT_KEEP_DAYS,
    SECONDS_PER_DAY,
    TrashEntry,
    free_preset_name,
    move_to_trash,
    purge_trash,
    restore_from_trash,
)
from ..validator import is_allowed_filename

logger = logging.getLogger(__name__)

# Preset transfer: option types (key: shown name, English), in rule order of option_type
OPTION_TYPES = {
    "enable_state": "Enable State",
    "feature_toggle": "Feature Toggle",
    "update_interval": "Update Interval",
    "position": "Position",
    "opacity": "Opacity",
    "layout": "Layout",
    "color": "Color",
    "font": "Font",
    "prefix_and_suffix": "Prefix And Suffix",
    "caption_text": "Caption Text",
    "decimal_places": "Decimal Places",
    "display_order": "Display Order",
    "other_options": "Other Options",
}
INVALID_NAME_CHARACTERS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')  # not allowed in file names (control too)
# Transfer refused (English, see tr)
DESTINATION_GONE = "Preset not found, it may have been renamed or deleted."
DESTINATION_TAKEN = "Destination preset is now loaded or locked, choose another preset."


CLASS_SESSIONS = "class_sessions"  # trash references: primary class presets of a session ("preset_race:GT3")


def update_preset_references(old_name: str, new_name: str) -> list[str]:
    """Update preset name used by shortcuts, primary track & class presets

    Returns:
        Updated config types.
    """
    updated = []
    for option_name in SHORTCUTS_PRESET:
        if cfg.user.shortcuts[option_name]["preset"] == old_name:
            cfg.user.shortcuts[option_name]["preset"] = new_name
            if ConfigType.SHORTCUTS not in updated:
                updated.append(ConfigType.SHORTCUTS)
    for config_type in (ConfigType.TRACKS, ConfigType.CLASSES):
        keys = CLASS_PRESET_KEYS if config_type == ConfigType.CLASSES else ("preset",)
        for data in getattr(cfg.user, config_type).values():
            if not isinstance(data, dict):
                continue
            for key in keys:
                if data.get(key) == old_name:
                    data[key] = new_name
                    if config_type not in updated:
                        updated.append(config_type)
    for config_type in updated:
        cfg.save(config_type=config_type)
    return updated


def preset_references(name: str) -> dict[str, list[str]]:
    """Shortcuts, primary track & class presets using preset name, by config type

    Class presets of a session are listed under CLASS_SESSIONS as "preset_race:GT3" (key, class name).
    """
    references: dict[str, list[str]] = {}
    shortcuts = [option for option in SHORTCUTS_PRESET if cfg.user.shortcuts[option]["preset"] == name]
    if shortcuts:
        references[ConfigType.SHORTCUTS] = shortcuts
    for config_type in (ConfigType.TRACKS, ConfigType.CLASSES):
        entries = [
            entry for entry, data in getattr(cfg.user, config_type).items()
            if isinstance(data, dict) and data.get("preset") == name
        ]
        if entries:
            references[config_type] = entries
    sessions = [
        f"{key}:{entry}" for entry, data in cfg.user.classes.items() if isinstance(data, dict)
        for key in SESSION_PRESET_KEYS.values() if data.get(key) == name
    ]
    if sessions:
        references[CLASS_SESSIONS] = sessions
    return references


def restore_preset_references(name: str, references: dict[str, list[str]]) -> list[str]:
    """Set preset name again where it was cleared (preset restored from trash)

    Entries set to another preset meanwhile, or removed, are left as they are.

    Returns:
        Updated config types.
    """
    updated = []
    for config_type, entries in references.items():
        if config_type == ConfigType.SHORTCUTS:
            data = {option: cfg.user.shortcuts.get(option) for option in entries if option in SHORTCUTS_PRESET}
        elif config_type in (ConfigType.TRACKS, ConfigType.CLASSES):
            data = {entry: getattr(cfg.user, config_type).get(entry) for entry in entries}
        elif config_type == CLASS_SESSIONS:
            for entry in entries:
                key, _, class_name = entry.partition(":")
                value = cfg.user.classes.get(class_name)
                if key in SESSION_PRESET_KEYS.values() and isinstance(value, dict) and not value.get(key):
                    value[key] = name
                    if ConfigType.CLASSES not in updated:
                        updated.append(ConfigType.CLASSES)
            continue
        else:
            continue
        for value in data.values():
            if isinstance(value, dict) and not value.get("preset"):
                value["preset"] = name
                if config_type not in updated:
                    updated.append(config_type)
    for config_type in updated:
        cfg.save(config_type=config_type)
    return updated


def trash_keep_days() -> int:
    """Days deleted presets are kept in trash"""
    days = cfg.application.get("number_of_days_to_keep_deleted_presets", DEFAULT_KEEP_DAYS)
    return days if isinstance(days, int) and days > 0 else DEFAULT_KEEP_DAYS


def trash_preset(preset_filename: str) -> TrashEntry:
    """Move preset to trash, primary preset references cleared (kept in trash for undo)

    Raises:
        OSError: preset can not be moved (locked file), nothing changed.
    """
    name = preset_filename[:-len(FileExt.JSON)]
    entry = move_to_trash(cfg.path.settings, preset_filename, preset_references(name))
    update_preset_references(name, "")
    purge_trash(cfg.path.settings, trash_keep_days())
    return entry


def restore_trashed_preset(entry: TrashEntry) -> str:
    """Restore preset from trash (renamed if name is used meanwhile), references set again

    Returns:
        Restored preset file name.

    Raises:
        OSError: preset can not be moved back, kept in trash.
    """
    filename = free_preset_name(cfg.path.settings, entry.filename)
    restore_from_trash(cfg.path.settings, entry, filename)
    restore_preset_references(filename[:-len(FileExt.JSON)], entry.references)
    return filename


def format_deleted_time(deleted: float) -> str:
    """Deletion date & time in current language"""
    return QLocale(current_language()).toString(
        QDateTime.fromSecsSinceEpoch(int(deleted)), QLocale.FormatType.ShortFormat)


def days_left(deleted: float, keep_days: int, now: float | None = None) -> int:
    """Days (started) before preset is removed from trash, 0 once expired"""
    remaining = deleted + keep_days * SECONDS_PER_DAY - (time() if now is None else now)
    return max(ceil(remaining / SECONDS_PER_DAY), 0)


def check_preset_name(name: str, mode: str = "", source_filename: str = "") -> str:
    """Why name cannot be used by a new, duplicated, renamed or restored preset (translated), "" if it can

    Existing names are compared in any case, as Windows file names are case-insensitive: renaming
    "race" to "Race" is allowed (same file).
    """
    entered_filename = strip_filename_extension(name, FileExt.JSON)
    if not is_allowed_filename(entered_filename) or INVALID_NAME_CHARACTERS.search(entered_filename):
        return tr("Invalid preset name.")
    source_name = source_filename[:-len(FileExt.JSON)]
    rename_case = (  # renaming by case only ("race" to "Race"): same file
        mode == "rename" and entered_filename != source_name
        and entered_filename.lower() == source_name.lower()
    )
    for preset in cfg.preset_files():
        if entered_filename.lower() == preset.lower() and not (rename_case and preset == source_name):
            return tr("Preset already exists.")
    return ""


def apply_preset_name(name: str, mode: str = "", source_filename: str = "") -> str:
    """Create (mode ""), duplicate, rename or restore (backup) preset under name

    Renamed preset keeps its backups, layout profiles & primary preset references (hotkeys,
    tracks, classes), and is loaded again if it was loaded.

    Returns:
        "" if done, else why not (translated message).
    """
    error = check_preset_name(name, mode, source_filename)
    if error:
        return error
    entered_filename = strip_filename_extension(name, FileExt.JSON)
    source_name = source_filename[:-len(FileExt.JSON)]
    filepath = cfg.path.settings
    new_filename = f"{entered_filename}{FileExt.JSON}"
    source_loaded = mode in ("duplicate", "rename") and cfg.is_loaded(source_filename)
    if source_loaded:  # queued save of loaded preset written first: not resurrected, nor missed by copy
        cfg.flush()
    try:
        # Duplicate preset
        if mode == "duplicate":
            shutil.copy(f"{filepath}{source_filename}", f"{filepath}{new_filename}")
        # Restore or rename preset
        elif mode in ("restore", "rename"):
            os.rename(f"{filepath}{source_filename}", f"{filepath}{new_filename}")
    except OSError as error:  # locked file (cloud sync, antivirus), permission
        logger.error("USERDATA: unable to %s %s: %s", mode, source_filename, error)
        return trm(f"Unable to access preset file, it may be used by another program.<br><br>{html.escape(str(error))}")
    if mode == "rename":
        rename_preset_backups(filepath, source_filename, new_filename)
        with suppress(OSError):  # layout profiles of screen setups, if any
            os.replace(profile_filename(filepath, source_filename), profile_filename(filepath, new_filename))
        update_preset_references(source_name, entered_filename)
        # Reload if renamed file was loaded. Loaded name follows the file now: if reload is refused
        # (config page with unsaved changes), next saves go to renamed file, not a re-created old one
        if source_loaded:
            cfg.filename.setting = new_filename
            cfg.set_next_to_load(new_filename)
            app_signal.reload.emit(True)
            return ""
    # Create new preset
    elif not mode:
        cfg.create(new_filename)
    app_signal.refresh.emit(True)
    return ""


# Transfer: settings of the loaded preset copied into another preset
def option_type(option_name: str) -> str:
    """Transfer option type of an option (OPTION_TYPES key), first matching rule"""
    if option_name == "enable":
        return "enable_state"
    if re.search(rxp.CFG_BOOL, option_name):
        return "feature_toggle"
    if re.search("update_interval", option_name):
        return "update_interval"
    if re.search("^position_x$|^position_y$", option_name):
        return "position"
    if option_name == "opacity":
        return "opacity"
    if option_name == "layout":
        return "layout"
    if re.search(rxp.CFG_COLOR, option_name):
        return "color"
    if re.search("font_name|font_weight|font_size|font_offset", option_name):
        return "font"
    if re.search("prefix|suffix", option_name):
        return "prefix_and_suffix"
    if re.search("caption_text", option_name):
        return "caption_text"
    if re.search("display_order", option_name):
        return "display_order"
    if re.search("decimal_places", option_name):
        return "decimal_places"
    return "other_options"


def copy_preset_options(
    source: Mapping[str, Mapping], dest: dict, settings: Iterable[str], option_types: Iterable[str]
) -> int:
    """Copy options of settings (sections) whose option type is selected, from source into dest preset

    Returns:
        Number of options copied.
    """
    sections, types = set(settings), set(option_types)
    count = 0
    for setting_name, source_options in source.items():
        if setting_name not in sections or not isinstance(source_options, Mapping):
            continue
        dest_options = dest.get(setting_name)
        if not isinstance(dest_options, dict):
            continue
        for option_name, value in source_options.items():
            if option_type(option_name) in types:
                dest_options[option_name] = value
                count += 1
    return count


def transfer_destinations() -> list[str]:
    """Presets settings can be transferred to (names): neither loaded nor locked"""
    loaded = cfg.filename.setting[:-len(FileExt.JSON)]
    return [
        name for name in cfg.preset_files()
        if name != loaded and f"{name}{FileExt.JSON}" not in cfg.user.filelock
    ]


def destination_error(dest_filename: str) -> str:
    """Why settings cannot be written to preset now (English, see tr), "" if they can

    Writing to loaded preset would be overwritten by its next save, a locked preset must not change,
    a preset renamed or deleted since chosen would be made again from defaults.
    """
    if not os.path.isfile(f"{cfg.path.settings}{dest_filename}"):
        return DESTINATION_GONE
    if os.path.normcase(dest_filename) == os.path.normcase(cfg.filename.setting) or dest_filename in cfg.user.filelock:
        return DESTINATION_TAKEN
    return ""


def transfer_settings(dest_filename: str, settings: Iterable[str], option_types: Iterable[str]) -> str:
    """Copy selected settings & option types of loaded preset into dest preset file

    Returns:
        "" if saved, else why not (English message, see trm).
    """
    error = destination_error(dest_filename)
    if error:
        return error
    dest_dict = load_setting_json_file(filename=dest_filename, filepath=cfg.path.settings, dict_def=cfg.default.setting,
                                       access_timeout=RELOAD_ACCESS_TIMEOUT)  # GUI thread: short retry on a lock
    copy_preset_options(cfg.user.setting, dest_dict, settings, option_types)
    saved = save_and_verify_json_file(
        dict_user=dest_dict, filename=dest_filename, filepath=cfg.path.settings, max_attempts=cfg.max_saving_attempts,
    )
    if not saved:  # locked (cloud sync, antivirus) or not readable at load: never told transferred
        return f"Settings could not be saved to <b>{html.escape(dest_filename)}</b>."
    return ""


# Backups of presets & style presets
class BackupFile(NamedTuple):
    """Backup file of settings folder"""

    name: str  # file name
    style: bool  # backup of a style preset (brakes, classes...), not of a preset


def list_backups() -> list[BackupFile]:
    """Backup files of settings folder, newest first"""
    found = []
    for name in cfg.backup_files(cfg.path.settings):
        basename = name[:name.find(FileExt.JSON)]
        if basename:  # ignore empty file
            found.append(BackupFile(name, not is_allowed_filename(basename)))
    return found


def restore_style_backup(name: str):
    """Style preset backup put back in place of the style preset (overwritten), styles reloaded

    Raises:
        OSError: backup cannot be moved (locked file, permission), nothing changed.
    """
    basename = name[:name.find(FileExt.JSON)]
    filepath = cfg.path.settings
    # Saving paused & queued style saves (older styles) dropped meanwhile, styles reloaded:
    # a pending save or a refused reload would write old styles over the restored file
    with cfg.styles_replaced():
        shutil.move(f"{filepath}{name}", f"{filepath}{basename}{FileExt.JSON}")
    app_signal.reload.emit(True)


def delete_backup(name: str):
    """Backup file deleted for good

    Raises:
        OSError: file cannot be removed (locked file, permission).
    """
    path = f"{cfg.path.settings}{name}"
    if os.path.exists(path):
        os.remove(path)


# Saving waited off the UI thread
SAVING_WAIT = "Settings are being saved, please wait…"


def after_saving(page, then: Callable[[], object]) -> bool:
    """Run then() once no settings save is running: now if none (or without event loop: start & tests, where
    nothing would run meanwhile), else once the saving thread finished, waited by a job of page (its toast tells)

    File work on the loaded preset (duplicate, rename) or on style files (import, backup restored) waits
    for a queued save first (not resurrected, nor written over the imported styles): a file held by an
    antivirus or cloud sync kept the UI thread waiting for up to 10 s (audit PERF-018).

    Args:
        page: Presets page backend (jobs, show_toast).
        then: UI thread callback, dropped if the page is released meanwhile.

    Returns:
        True if then() ran now.
    """
    from ..module_control import event_loop_running

    if not cfg.is_saving or not event_loop_running():
        then()
        return True
    page.show_toast(tr(SAVING_WAIT))
    page.jobs.run("wait saving", cfg.flush, lambda _: then(), key="wait saving")
    return False
