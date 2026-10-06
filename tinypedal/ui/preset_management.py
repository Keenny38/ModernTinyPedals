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
Preset management
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from contextlib import suppress
from math import ceil
from time import time
from types import MappingProxyType
from typing import cast

from PySide6.QtCore import QDateTime, QLocale, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
)

from .. import app_signal
from .. import regex_pattern as rxp
from ..const_file import ConfigType, FileExt
from ..formatter import strip_filename_extension
from ..i18n import current_language, tr, trm
from ..i18n.options import module_label
from ..setting import cfg, load_setting_json_file, save_and_verify_json_file
from ..template.setting_shortcuts import SHORTCUTS_PRESET
from ..userfile.json_setting import rename_preset_backups, verify_json_file
from ..userfile.layout_profile import profile_filename
from ..userfile.preset_trash import (
    DEFAULT_KEEP_DAYS,
    SECONDS_PER_DAY,
    TrashEntry,
    free_preset_name,
    list_trash,
    move_to_trash,
    purge_trash,
    remove_entry,
    restore_from_trash,
)
from ..validator import is_allowed_filename
from . import status_color
from ._common import QVAL_FILENAME, BaseDialog, BaseEditor, CompactButton, FocusRingButton, UIScaler
from .toast import show_toast

logger = logging.getLogger(__name__)

# Preset transfer: option types (key: shown name), list headers (title, select & deselect questions)
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
LIST_HEADER_SETTING = (
    "Select Setting", "Select all settings from list?", "Deselect all settings from list?")
INVALID_NAME_CHARACTERS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')  # not allowed in file names (control too)
LIST_HEADER_OPTION_TYPE = (
    "Select Option Type", "Select all option types from list?", "Deselect all option types from list?")


class BackupItem(QListWidgetItem):
    """Backup file list item"""

    def __init__(self):
        super().__init__()
        self.is_valid = False
        self.is_style = False


class KeyCheckBox(QCheckBox):
    """Check box of a setting key"""

    def __init__(self, parent):
        super().__init__(parent)
        self.key_name = ""


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
        for data in getattr(cfg.user, config_type).values():
            if isinstance(data, dict) and data.get("preset") == old_name:
                data["preset"] = new_name
                if config_type not in updated:
                    updated.append(config_type)
    for config_type in updated:
        cfg.save(config_type=config_type)
    return updated


def preset_references(name: str) -> dict[str, list[str]]:
    """Shortcuts, primary track & class presets using preset name, by config type"""
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
        return trm(f"Unable to access preset file, it may be used by another program.<br><br>{error}")
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


class CreatePreset(BaseDialog):
    """Create preset"""

    EMBED_FROM_PAGE = True  # page too when opened from a page (restore backup...)

    def __init__(self, parent, title: str = "", mode: str = "", source_filename: str = ""):
        """Initialize create preset dialog setting

        Args:
            title: Dialog title string (translated).
            mode: Edit mode, either "duplicate", "restore", "rename", or "" for new preset.
            source_filename: Source setting filename.
        """
        super().__init__(parent)
        self.edit_mode = mode
        self.source_filename = source_filename

        self.setWindowTitle(title)

        # Entry box
        self.preset_entry = QLineEdit()
        self.preset_entry.setMaxLength(40)
        self.preset_entry.setPlaceholderText(tr("Enter a new preset name"))
        self.preset_entry.setValidator(QVAL_FILENAME)

        # Button
        button_create = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        button_create.accepted.connect(self.create_preset)
        button_create.rejected.connect(self.reject)

        # Layout
        layout_main = QVBoxLayout()
        layout_main.addWidget(self.preset_entry)
        layout_main.addWidget(button_create)
        self.setLayout(layout_main)
        self.setMinimumWidth(UIScaler.size(21))
        self.setFixedHeight(self.sizeHint().height())

    def create_preset(self):
        """Create & save new preset"""
        error = apply_preset_name(self.preset_entry.text(), self.edit_mode, self.source_filename)
        if error:
            QMessageBox.warning(self, tr("Error"), error)
            return
        self.accept()


class RestoreBackup(BaseEditor):
    """Restore backup"""

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Restore Backup"))
        self.setMinimumSize(UIScaler.size(40), UIScaler.size(20))

        # Backup list
        self.listbox_backup = QListWidget(self)
        self.listbox_backup.setAlternatingRowColors(True)

        # Button
        button_restore = CompactButton(tr("Restore"))
        button_restore.clicked.connect(self.restore)

        button_refresh = CompactButton(tr("Refresh"))
        button_refresh.clicked.connect(self.refresh)

        button_delete = CompactButton(tr("Delete"))
        button_delete.clicked.connect(self.delete)

        button_close = CompactButton(tr("Close"))
        button_close.clicked.connect(self.close)

        layout_button = QHBoxLayout()
        layout_button.addWidget(button_restore)
        layout_button.addWidget(button_refresh)
        layout_button.addWidget(button_delete)
        layout_button.addStretch(1)
        layout_button.addWidget(button_close)

        # Set layout
        layout_main = QGridLayout()
        layout_main.addWidget(self.listbox_backup, 2, 1)
        layout_main.addLayout(layout_button, 3, 1)
        layout_main.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        self.setLayout(layout_main)
        self.refresh()

    def refresh(self):
        """Load backup file list"""
        self.listbox_backup.clear()
        backup_list = cfg.backup_files(cfg.path.settings)
        palette = self.listbox_backup.palette()  # colors of window theme in use
        invalid_color = QColor(status_color("danger", palette))
        style_color = QColor(status_color("info", palette))

        for backup_name in backup_list:
            basename = backup_name[:backup_name.find(FileExt.JSON)]
            if not basename:  # ignore empty file
                continue
            item = BackupItem()
            item.setText(backup_name)
            item.is_valid = verify_json_file(None, backup_name, cfg.path.settings)
            item.is_style = not is_allowed_filename(basename)
            if not item.is_valid:
                item.setForeground(invalid_color)
            elif item.is_style:
                item.setForeground(style_color)
            self.listbox_backup.addItem(item)

    def is_selected(self) -> bool:
        """Is file selected"""
        if not self.listbox_backup.selectedIndexes():
            msg_text = "No backup file selected."
            QMessageBox.warning(self, tr("Error"), trm(msg_text))
            return False
        return True

    def delete(self):
        """Delete backup file"""
        if not self.is_selected():
            return

        selected_item = self.listbox_backup.currentItem()
        selected_filename = selected_item.text()
        msg_text = (
            f"Delete <b>{selected_filename}</b> preset permanently?<br><br>"
            "This cannot be undone!"
        )
        if self.confirm_operation(title=tr("Delete Preset"), message=msg_text):
            full_path = f"{cfg.path.settings}{selected_filename}"
            try:
                if os.path.exists(full_path):
                    os.remove(full_path)
            except OSError as error:  # locked file (cloud sync, antivirus), permission
                QMessageBox.warning(self, tr("Error"), trm(f"Unable to delete backup file:<br>{error}"))
            self.refresh()

    def restore(self):
        """Restore backup file"""
        if not self.is_selected():
            return

        selected_item = cast(BackupItem, self.listbox_backup.currentItem())
        if not selected_item.is_valid:
            msg_text = "Selected backup file is invalid and cannot be restored."
            QMessageBox.warning(self, tr("Error"), trm(msg_text))
            return

        selected_filename = selected_item.text()

        # Style preset
        if selected_item.is_style:
            msg_text = (
                f"<b>{selected_filename}</b> is a style preset.<br>"
                "Restoring this backup file will overwrite existing style preset.<br><br>"
                "Are you sure you want to restore and overwrite existing style preset?<br><br>"
                "This cannot be undone!"
            )
            if self.confirm_operation(title=tr("Restore Style Preset"), message=msg_text):
                basename = selected_filename[:selected_filename.find(FileExt.JSON)]
                filepath = cfg.path.settings
                try:
                    shutil.move(
                        f"{filepath}{selected_filename}",
                        f"{filepath}{basename}{FileExt.JSON}"
                    )
                except OSError as error:  # locked file (cloud sync, antivirus), permission
                    QMessageBox.warning(self, tr("Error"), trm(f"Unable to restore backup file:<br>{error}"))
                    return
                app_signal.reload.emit(True)
                self.refresh()
            return

        # User preset
        _dialog = CreatePreset(
            self,
            title=tr("Restore Backup"),
            mode="restore",
            source_filename=selected_filename
        )
        _dialog.accepted.connect(self.refresh)
        _dialog.open()


class PresetTrash(BaseDialog):
    """Deleted presets: restore, or delete for good (removed by themselves after some days)"""

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Preset Trash"))
        self.setMinimumSize(UIScaler.size(34), UIScaler.size(20))
        self.entries: list[TrashEntry] = []

        self.label_info = QLabel(self)
        self.label_info.setWordWrap(True)

        self.listbox_trash = QListWidget(self)
        self.listbox_trash.setAlternatingRowColors(True)
        self.listbox_trash.itemDoubleClicked.connect(self.restore)
        self.listbox_trash.currentRowChanged.connect(self.refresh_buttons)

        self.button_restore = FocusRingButton(tr("Restore"), self)
        self.button_restore.setToolTip(tr("Restore selected preset (also by double click)"))
        self.button_restore.clicked.connect(self.restore)
        self.button_delete = FocusRingButton(tr("Delete Permanently"), self)
        self.button_delete.clicked.connect(self.delete)
        self.button_empty = FocusRingButton(tr("Empty Trash"), self)
        self.button_empty.clicked.connect(self.empty)
        button_close = FocusRingButton(tr("Close"), self)
        button_close.clicked.connect(self.close)

        layout_button = QHBoxLayout()
        layout_button.addWidget(self.button_restore)
        layout_button.addWidget(self.button_delete)
        layout_button.addWidget(self.button_empty)
        layout_button.addStretch(1)
        layout_button.addWidget(button_close)

        layout_main = QVBoxLayout()
        layout_main.addWidget(self.label_info)
        layout_main.addWidget(self.listbox_trash, stretch=1)
        layout_main.addLayout(layout_button)
        layout_main.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        self.setLayout(layout_main)
        self.refresh()

    def refresh(self):
        """Purge old entries, list presets in trash (newest first)"""
        keep_days = trash_keep_days()
        purge_trash(cfg.path.settings, keep_days)
        self.entries = list_trash(cfg.path.settings)
        self.listbox_trash.clear()
        for entry in self.entries:
            left = days_left(entry.deleted, keep_days)
            item = QListWidgetItem(trm(
                f"{entry.name} · deleted {format_deleted_time(entry.deleted)} · {left} day(s) left"))
            item.setData(Qt.ItemDataRole.UserRole, entry.folder)
            self.listbox_trash.addItem(item)
        if self.entries:
            self.listbox_trash.setCurrentRow(0)
            self.label_info.setText(trm(f"Deleted presets are kept for {keep_days} day(s), then removed."))
        else:
            self.label_info.setText(trm(f"Trash is empty. Deleted presets are kept for {keep_days} day(s)."))
        self.refresh_buttons()

    def refresh_buttons(self, *_):
        selected = self.selected_entry() is not None
        self.button_restore.setEnabled(selected)
        self.button_delete.setEnabled(selected)
        self.button_empty.setEnabled(bool(self.entries))

    def selected_entry(self) -> TrashEntry | None:
        row = self.listbox_trash.currentRow()
        return self.entries[row] if 0 <= row < len(self.entries) else None

    def restore(self, *_):
        """Restore selected preset (renamed if a preset has its name)"""
        entry = self.selected_entry()
        if entry is None:
            return
        try:
            filename = restore_trashed_preset(entry)
        except OSError as error:  # locked file (cloud sync, antivirus), permission
            QMessageBox.warning(self, tr("Error"), trm(f"Unable to restore preset:<br>{error}"))
            return
        app_signal.refresh.emit(True)
        self.refresh()
        show_toast(self, trm(f"Preset restored: <b>{filename[:-len(FileExt.JSON)]}</b>"))

    def delete(self):
        """Delete selected preset for good"""
        entry = self.selected_entry()
        if entry is None:
            return
        msg_text = (
            f"Delete <b>{entry.name}</b> preset permanently?<br><br>"
            "This cannot be undone!"
        )
        if not self.confirm_operation(title=tr("Delete Preset"), message=msg_text):
            return
        if not remove_entry(entry):
            QMessageBox.warning(self, tr("Error"), trm(f"Unable to delete preset:<br>{entry.folder}"))
        self.refresh()

    def empty(self):
        """Delete every preset in trash for good"""
        if not self.entries:
            return
        msg_text = (
            f"Delete all <b>{len(self.entries)}</b> preset(s) in trash permanently?<br><br>"
            "This cannot be undone!"
        )
        if not self.confirm_operation(title=tr("Empty Trash"), message=msg_text):
            return
        for entry in self.entries:
            remove_entry(entry)
        self.refresh()


class PresetTransfer(BaseEditor):
    """Preset Transfer"""

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Preset Transfer"))
        self.setMinimumSize(UIScaler.size(40), UIScaler.size(38))

        # Label
        self.loaded_preset = cfg.filename.setting[:-5]
        self.label_loaded = label_loaded = QLabel(trm(f"From: <b>{self.loaded_preset}</b>"))

        # Setting list
        self.listbox_setting = QListWidget(self)
        self.set_setting_list(self.listbox_setting, cfg.user.setting)

        # Preset selector
        self.dest_selector = QComboBox()
        self.dest_selector.addItems(self.set_selector_list())

        # Option type list
        self.listbox_options = QListWidget(self)
        self.set_setting_list(self.listbox_options, OPTION_TYPES, OPTION_TYPES)
        layout_dest = QHBoxLayout()
        layout_dest.addWidget(QLabel(tr("To:")))
        layout_dest.addWidget(self.dest_selector, stretch=1)

        # Button transfer
        button_apply = CompactButton(tr("Transfer"))
        button_apply.clicked.connect(self.transfer)

        button_close = CompactButton(tr("Close"))
        button_close.clicked.connect(self.close)

        layout_button = QHBoxLayout()
        layout_button.addStretch(1)
        layout_button.addWidget(button_apply)
        layout_button.addWidget(button_close)

        # List header
        header_setting = ListHeader(self, LIST_HEADER_SETTING, self.listbox_setting)
        header_options = ListHeader(self, LIST_HEADER_OPTION_TYPE, self.listbox_options)

        # Set layout
        layout_main = QGridLayout()
        layout_main.addWidget(label_loaded, 0, 0)
        layout_main.addWidget(header_setting, 1, 0)
        layout_main.addWidget(self.listbox_setting, 2, 0)
        layout_main.addLayout(layout_dest, 0, 1)
        layout_main.addWidget(header_options, 1, 1)
        layout_main.addWidget(self.listbox_options, 2, 1)
        layout_main.addLayout(layout_button, 3, 1)
        layout_main.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        self.setLayout(layout_main)

    def set_selector_list(self) -> list:
        """Set preset selector list"""
        preset_list = cfg.preset_files()
        # Remove loaded preset
        if self.loaded_preset in preset_list:
            preset_list.remove(self.loaded_preset)
        # Remove locked preset
        for name in reversed(preset_list):
            full_name = f"{name}.json"
            if full_name in cfg.user.filelock:
                preset_list.remove(name)
        return preset_list

    def set_setting_list(self, listbox: QListWidget, settings: tuple | dict, labels: dict[str, str] | None = None):
        """Set setting list, shown names from labels (English, translated) if set, else widget names"""
        for setting_name in settings:
            item = QListWidgetItem()
            listbox.addItem(item)
            checkbox_item = KeyCheckBox(self)
            checkbox_item.setText(tr(labels[setting_name]) if labels else module_label(setting_name))
            checkbox_item.key_name = setting_name
            listbox.setItemWidget(item, checkbox_item)

    def get_setting_selection(self, listbox: QListWidget):
        """Get setting selection"""
        for row_index in range(listbox.count()):
            item = listbox.item(row_index)
            checkbox = cast(KeyCheckBox, listbox.itemWidget(item))
            if checkbox.isChecked():
                yield checkbox.key_name

    def transfer(self):
        """Transfer setting"""
        if not self.dest_selector.currentText():
            msg_text = "No destination preset selected or found."
            QMessageBox.warning(self, tr("Error"), trm(msg_text))
            return
        self.refresh_loaded_preset()
        loaded_preset_name = f"{self.loaded_preset}.json"
        dest_preset_name = f"{self.dest_selector.currentText()}.json"
        setting_selection = tuple(self.get_setting_selection(self.listbox_setting))
        if not setting_selection:
            msg_text = "No preset setting selected.<br><br>Select at least one setting and try again."
            QMessageBox.warning(self, tr("Error"), trm(msg_text))
            return
        options_selection = tuple(self.get_setting_selection(self.listbox_options))
        if not options_selection:
            msg_text = "No option type selected.<br><br>Select at least one option type and try again."
            QMessageBox.warning(self, tr("Error"), trm(msg_text))
            return
        msg_text = (
            f"Transfer selected settings from <b>{loaded_preset_name}</b>"
            f" to <b>{dest_preset_name}</b>?<br><br>"
            "This cannot be undone!"
        )
        if not self.confirm_operation(message=msg_text):
            return
        if not self.is_destination_allowed(dest_preset_name):
            return
        # Load preset dict
        dest_dict = load_setting_json_file(
            filename=dest_preset_name,
            filepath=cfg.path.settings,
            dict_def=cfg.default.setting,
        )
        # Copy setting
        self.copy_setting(dest_dict, setting_selection, options_selection)
        # Save setting
        save_and_verify_json_file(
            dict_user=dest_dict,
            filename=dest_preset_name,
            filepath=cfg.path.settings,
            max_attempts=cfg.max_saving_attempts,
        )
        msg_text = (
            f"Settings are transferred from <b>{loaded_preset_name}</b>"
            f" to <b>{dest_preset_name}</b>."
        )
        show_toast(self, trm(msg_text))

    def refresh_loaded_preset(self):
        """Source (loaded) preset name, it may be another preset since page was opened (auto-load)"""
        self.loaded_preset = cfg.filename.setting[:-len(FileExt.JSON)]
        self.label_loaded.setText(trm(f"From: <b>{self.loaded_preset}</b>"))

    def is_destination_allowed(self, dest_preset_name: str) -> bool:
        """Destination still neither loaded nor locked (preset loaded or locked since list was made)

        Writing to loaded preset would be overwritten by its next save, a locked preset must not change.
        If refused, loaded preset & destination list are refreshed and why is shown.
        """
        if (os.path.normcase(dest_preset_name) != os.path.normcase(cfg.filename.setting)
                and dest_preset_name not in cfg.user.filelock):
            return True
        self.refresh_loaded_preset()
        self.dest_selector.clear()
        self.dest_selector.addItems(self.set_selector_list())
        QMessageBox.warning(self, tr("Error"), tr("Destination preset is now loaded or locked, choose another preset."))
        return False

    def copy_setting(self, dest_dict: dict, setting_selection: tuple[str, ...], options_selection: tuple[str, ...]):
        """Copy setting"""
        source_dict = MappingProxyType(cfg.user.setting)
        for setting_name, source_setting_dict in source_dict.items():
            if setting_name not in setting_selection:
                continue
            dest_setting_dict = dest_dict[setting_name]
            for option_name, option_value in source_setting_dict.items():
                if option_name == "enable":
                    if "enable_state" in options_selection:
                        dest_setting_dict[option_name] = option_value
                    continue
                if re.search(rxp.CFG_BOOL, option_name):
                    if "feature_toggle" in options_selection:
                        dest_setting_dict[option_name] = option_value
                    continue
                if re.search("update_interval", option_name):
                    if "update_interval" in options_selection:
                        dest_setting_dict[option_name] = option_value
                    continue
                if re.search("^position_x$|^position_y$", option_name):
                    if "position" in options_selection:
                        dest_setting_dict[option_name] = option_value
                    continue
                if option_name == "opacity":
                    if "opacity" in options_selection:
                        dest_setting_dict[option_name] = option_value
                    continue
                if option_name == "layout":
                    if "layout" in options_selection:
                        dest_setting_dict[option_name] = option_value
                    continue
                if re.search(rxp.CFG_COLOR, option_name):
                    if "color" in options_selection:
                        dest_setting_dict[option_name] = option_value
                    continue
                if re.search("font_name|font_weight|font_size|font_offset", option_name):
                    if "font" in options_selection:
                        dest_setting_dict[option_name] = option_value
                    continue
                if re.search("prefix|suffix", option_name):
                    if "prefix_and_suffix" in options_selection:
                        dest_setting_dict[option_name] = option_value
                    continue
                if re.search("caption_text", option_name):
                    if "caption_text" in options_selection:
                        dest_setting_dict[option_name] = option_value
                    continue
                if re.search("display_order", option_name):
                    if "display_order" in options_selection:
                        dest_setting_dict[option_name] = option_value
                    continue
                if re.search("decimal_places", option_name):
                    if "decimal_places" in options_selection:
                        dest_setting_dict[option_name] = option_value
                    continue
                if "other_options" in options_selection:
                    dest_setting_dict[option_name] = option_value
                    continue


class ListHeader(QFrame):
    """List header

    Args:
        texts: title, select all & deselect all questions (English, translated here).
    """

    def __init__(self, parent, texts: tuple[str, str, str], listbox: QListWidget):
        super().__init__(parent)
        self._parent = parent
        self._listbox = listbox
        self._title, self._select_text, self._deselect_text = texts

        button_selectall = CompactButton(tr(" All "))
        button_selectall.clicked.connect(self.button_select_all)

        button_deselectall = CompactButton(tr("None"))
        button_deselectall.clicked.connect(self.button_deselect_all)

        layout = QHBoxLayout()
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(tr(self._title)))
        layout.addWidget(button_selectall)
        layout.addWidget(button_deselectall)
        self.setLayout(layout)
        self.setFrameShape(QFrame.Shape.StyledPanel)

    def button_select_all(self):
        """Select all check box"""
        if self._parent.confirm_operation(message=tr(self._select_text)):
            self.set_selection(self._listbox, True)

    def button_deselect_all(self):
        """Deselect all check box"""
        if self._parent.confirm_operation(message=tr(self._deselect_text)):
            self.set_selection(self._listbox, False)

    def set_selection(self, listbox: QListWidget, checked: bool):
        """Set check box"""
        for row_index in range(listbox.count()):
            item = listbox.item(row_index)
            cast(QCheckBox, listbox.itemWidget(item)).setChecked(checked)
