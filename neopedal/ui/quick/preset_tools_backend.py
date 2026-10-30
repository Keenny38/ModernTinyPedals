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
Presets page tools (qml/Presets.qml panels): compare two presets, transfer settings, restore backups,
recently deleted presets

Parts of the Presets page backend (QML: backend.compare, backend.transfer, backend.backups,
backend.trash), child QObjects holding the page weakly. Files are read only while a panel is open,
in background (page jobs). The work itself is done by plain functions (ui/preset_management.py,
ui/preset_compare.py, userfile/preset_compare.py, userfile/preset_trash.py).
"""

from __future__ import annotations

import html
import os
import re
import threading
import weakref
from functools import partial
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from ... import app_signal
from ...const_file import FileExt
from ...i18n import tr, trm
from ...i18n.options import module_label, option_help_specific, option_label
from ...setting import cfg
from ...userfile.json_setting import copy_setting, verify_json_file
from ...userfile.preset_compare import copy_values, diff_presets
from ...userfile.preset_trash import TrashEntry, free_preset_name, list_trash, purge_trash, remove_entry
from ..module_view import sort_key
from ..preset_management import (
    DESTINATION_GONE,
    DESTINATION_TAKEN,
    OPTION_TYPES,
    BackupFile,
    after_saving,
    days_left,
    delete_backup,
    format_deleted_time,
    list_backups,
    restore_style_backup,
    restore_trashed_preset,
    transfer_destinations,
    transfer_settings,
    trash_keep_days,
)
from .models import DictListModel

if TYPE_CHECKING:
    from .preset_backend import PresetBackend

FILTER_DELAY = 150  # ms, comparison filter applied once typing pauses
_TAG = re.compile(r"<[^>]*>")


def plain(text: str) -> str:
    """Message without markup (QML texts are plain): line breaks as spaces, tags dropped, escapes undone"""
    return html.unescape(_TAG.sub("", text.replace("<br><br>", " ").replace("<br>", " "))).strip()


def preset_name(filename: str) -> str:
    return filename[:-len(FileExt.JSON)] if filename.endswith(FileExt.JSON) else filename


def value_text(value: Any) -> str:
    """Option value of a comparison row"""
    if isinstance(value, bool):
        return tr("On") if value else tr("Off")
    return "" if value is None else str(value)


class PresetPart(QObject):
    """Part of the Presets page backend: page read through a weak reference (no reference cycle)"""

    def __init__(self, page: PresetBackend):
        super().__init__(page)
        self._page = weakref.ref(page)

    @property
    def page(self) -> PresetBackend:
        page = self._page()
        if page is None:  # parts are children of the page: deleted with it
            raise RuntimeError("Presets page deleted")
        return page


# Compare
COMPARE_ROLES = ("key", "sectionLabel", "label", "help", "valueA", "valueB", "chosen")


class PresetCompareBackend(PresetPart):
    """Two presets side by side: different options, copy values A -> B or B -> A, save copied values

    Presets are read in background when chosen (loaded preset copied as it is now). Copied values stay
    pending until saved: only them are written, into a fresh copy of each preset.
    """

    choicesChanged = Signal()  # preset list, A & B
    rowsChanged = Signal()  # differences, selection & counts
    stateChanged = Signal()  # loading, pending copies
    filterChanged = Signal()

    def __init__(self, page: PresetBackend):
        super().__init__(page)
        self.model = DictListModel(COMPARE_ROLES, self)
        self._choices: list[str] = []
        self._a = ""
        self._b = ""
        self._ignore_positions = True
        self._filter = ""
        self._words: tuple[str, ...] = ()
        self._presets: dict[str, dict] = {}  # file name: read (possibly edited) preset
        self._edits: dict[str, dict[tuple[str, str], Any]] = {}  # file name: copied values by (section, key)
        self._copied = 0  # values copied, not saved yet (see edits_changed)
        self._rows: list[dict] = []  # every difference
        self._haystacks: dict[str, str] = {}  # row key: filter text
        self._selected: set[str] = set()
        self._labels: dict[tuple[str, str], tuple[str, str, str]] = {}
        self._loading = False
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(FILTER_DELAY)
        self._filter_timer.timeout.connect(self.update_rows)

    # Properties
    @Property(QObject, constant=True)
    def rows(self) -> QObject:
        return self.model

    @Property(list, notify=choicesChanged)
    def choices(self) -> list[str]:
        return self._choices

    @Property(str, notify=choicesChanged)
    def presetA(self) -> str:
        return self._a

    @Property(str, notify=choicesChanged)
    def presetB(self) -> str:
        return self._b

    @Property(bool, notify=choicesChanged)
    def ignorePositions(self) -> bool:
        return self._ignore_positions

    @Property(bool, notify=choicesChanged)
    def samePreset(self) -> bool:
        return bool(self._a) and self._a == self._b

    @Property(str, notify=filterChanged)
    def filterText(self) -> str:
        return self._filter

    @Property(int, notify=rowsChanged)
    def diffCount(self) -> int:
        return len(self._rows)

    @Property(int, notify=rowsChanged)
    def shownCount(self) -> int:
        return self.model.rowCount()

    @Property(int, notify=rowsChanged)
    def selectedCount(self) -> int:
        return len(self._selected)

    @Property(bool, notify=stateChanged)
    def loading(self) -> bool:
        return self._loading

    @Property(int, notify=stateChanged)
    def copiedCount(self) -> int:
        """Values copied, not saved yet"""
        return self._copied

    @Property(bool, notify=stateChanged)
    def modified(self) -> bool:
        return bool(self._edits)

    def edits_changed(self):
        """Pending copies changed: counted, stateChanged sent"""
        self._copied = sum(len(values) for values in self._edits.values())
        self.stateChanged.emit()

    # Presets
    @Slot(str)
    def start(self, filename: str):
        """Comparison of loaded preset (A) with preset (B, else another one), opened panel"""
        self._presets.clear()
        self._edits.clear()
        self._selected.clear()
        self._choices = [f"{name}{FileExt.JSON}" for name in cfg.preset_files()]
        self._a = cfg.filename.setting
        if filename in self._choices and filename != self._a:
            self._b = filename
        else:
            self._b = next((name for name in self._choices if name != self._a), "")
        self._filter, self._words = "", ()
        self.filterChanged.emit()
        self.choicesChanged.emit()
        self.edits_changed()
        self.refresh()

    @Slot()
    def stop(self):
        """Panel closed: presets & pending copies dropped"""
        self.page.jobs.cancel("compare")
        self._presets.clear()
        self._edits.clear()
        self._selected.clear()
        self._rows, self._haystacks = [], {}
        self._loading = False
        self.model.sync([])
        self.rowsChanged.emit()
        self.edits_changed()

    @Slot(str)
    def setPresetA(self, filename: str):
        if filename in self._choices and filename != self._a:
            self._a = filename
            self.choicesChanged.emit()
            self.refresh()

    @Slot(str)
    def setPresetB(self, filename: str):
        if filename in self._choices and filename != self._b:
            self._b = filename
            self.choicesChanged.emit()
            self.refresh()

    @Slot(bool)
    def setIgnorePositions(self, ignore: bool):
        if ignore != self._ignore_positions:
            self._ignore_positions = ignore
            self.choicesChanged.emit()
            self.refresh()

    def refresh(self):
        """Differences built again, presets not read yet read in background first"""
        missing = []
        for name in dict.fromkeys((self._a, self._b)):
            if not name or name in self._presets:
                continue
            if cfg.is_loaded(name):  # live setting, copied on UI thread
                self._presets[name] = copy_setting(cfg.user.setting)
            else:
                missing.append(name)
        if missing:
            from ..preset_compare import load_preset_file

            self._loading = True
            self.stateChanged.emit()
            self.page.jobs.run(
                "read compared presets", lambda: {name: load_preset_file(name) for name in missing},
                self._presets_read, self._read_failed, key="compare")
            return
        if self._loading:
            self._loading = False
            self.stateChanged.emit()
        self.build_rows()

    def _read_failed(self, error: BaseException):
        """Preset not readable (removed meanwhile, access denied): nothing compared, told"""
        self._loading = False
        self.stateChanged.emit()
        self.page.show_toast(trm(f"Unable to read preset:<br>{html.escape(str(error))}"), error=True)

    def _presets_read(self, presets: dict[str, dict]):
        for name, preset in presets.items():
            self._presets.setdefault(name, preset)
        self.refresh()  # loading state cleared once every preset is read

    def labels(self, section: str, key: str) -> tuple[str, str, str]:
        """Section label, option label & help (cached)"""
        labels = self._labels.get((section, key))
        if labels is None:
            labels = self._labels[section, key] = (
                module_label(section), option_label(key), option_help_specific(section, key))
        return labels

    def build_rows(self):
        rows: list[dict] = []
        haystacks: dict[str, str] = {}
        if self._a and self._b and self._a in self._presets and self._b in self._presets:
            for diff in diff_presets(self._presets[self._a], self._presets[self._b], self._ignore_positions):
                section_label, label, help_text = self.labels(diff.section, diff.key)
                key = f"{diff.section}/{diff.key}"
                rows.append({
                    "key": key, "sectionLabel": section_label, "label": label, "help": help_text,
                    "valueA": value_text(diff.value_a), "valueB": value_text(diff.value_b),
                })
                haystacks[key] = sort_key(f"{section_label} {label} {diff.section} {diff.key}")
        self._rows, self._haystacks = rows, haystacks
        self._selected &= set(haystacks)
        self.update_rows()

    @Slot(str)
    def setFilter(self, text: str):
        """Filter typed: applied once typing pauses"""
        if text != self._filter:
            self._filter = text
            self._words = tuple(sort_key(text).split())
            self.filterChanged.emit()
            self._filter_timer.start()

    def update_rows(self):
        self._filter_timer.stop()
        words = self._words
        shown = [
            {**row, "chosen": row["key"] in self._selected} for row in self._rows
            if all(word in self._haystacks[row["key"]] for word in words)
        ]
        self.model.sync(shown)
        self.rowsChanged.emit()

    # Selection
    @Slot(str)
    def toggleSelected(self, key: str):
        self.setSelected(key, key not in self._selected)

    @Slot(str, bool)
    def setSelected(self, key: str, selected: bool):
        if key not in self._haystacks or (key in self._selected) == selected:
            return
        if selected:
            self._selected.add(key)
        else:
            self._selected.discard(key)
        number = self.model.index_of(key)
        if number >= 0:
            self.model.update_row(number, {"chosen": selected})
        self.rowsChanged.emit()

    @Slot(bool)
    def selectShown(self, selected: bool):
        """Every shown row (filter) selected, or none"""
        if selected:
            self._selected |= {row["key"] for row in self.model.rows}
        else:
            self._selected.clear()
        self.update_rows()

    # Copy & save
    @Slot(bool, result=str)
    def copySelected(self, to_a: bool) -> str:
        """Selected values copied B -> A (to_a) or A -> B, pending until saved: "" if done, else why not"""
        if not self._selected or self._a == self._b:
            return ""
        target, source = (self._a, self._b) if to_a else (self._b, self._a)
        if target in cfg.user.filelock:
            return plain(trm("Changes to locked preset will not be saved."))
        if target not in self._presets or source not in self._presets:
            return ""
        items = [tuple(key.split("/", 1)) for key in self._selected]
        target_preset, source_preset = self._presets[target], self._presets[source]
        if copy_values(target_preset, source_preset, items):  # type: ignore[arg-type]
            edits = self._edits.setdefault(target, {})
            for section, key in items:
                if key in source_preset.get(section, {}):
                    edits[section, key] = source_preset[section][key]
            self._selected.clear()
            self.edits_changed()
            self.build_rows()
        return ""

    @Slot(result=str)
    def save(self) -> str:
        """Copied values written (loaded preset saved & reloaded): "" if saved, else why not"""
        from ..preset_compare import save_preset_edits

        if not self._edits:
            return ""
        failed = save_preset_edits(self._edits)
        self._edits.clear()
        self._presets.clear()  # read again, with changes made elsewhere
        self.edits_changed()
        self.refresh()
        self.page.refresh()
        if failed:
            return plain(trm(f"Settings could not be saved to <b>{html.escape(', '.join(failed))}</b>."))
        self.page.show_toast(tr("Presets saved"))
        return ""

    @Slot()
    def discard(self):
        """Pending copies dropped, presets read again"""
        if self._edits:
            self._edits.clear()
            self._presets.clear()
            self.edits_changed()
            self.refresh()


# Transfer
TRANSFER_ROLES = ("key", "label", "chosen")


class PresetTransferBackend(PresetPart):
    """Settings of the loaded preset (overlays, modules...) copied to another preset, by option type"""

    presetsChanged = Signal()  # source, destinations & destination
    selectionChanged = Signal()
    errorChanged = Signal()

    def __init__(self, page: PresetBackend):
        super().__init__(page)
        self.settings_model = DictListModel(TRANSFER_ROLES, self)
        self._source = ""
        self._destinations: list[str] = []
        self._destination = ""
        self.types_model = DictListModel(TRANSFER_ROLES, self)
        self.types_model.sync([{"key": key, "label": tr(label), "chosen": False} for key, label in OPTION_TYPES.items()])
        self._error = ""
        self._setting_count = 0  # settings checked (see selection_changed)
        self._type_count = 0  # option types checked

    @Property(QObject, constant=True)
    def settings(self) -> QObject:
        return self.settings_model

    @Property(str, notify=presetsChanged)
    def source(self) -> str:
        return self._source

    @Property(list, notify=presetsChanged)
    def destinations(self) -> list[str]:
        return self._destinations

    @Property(str, notify=presetsChanged)
    def destination(self) -> str:
        return self._destination

    @Property(QObject, constant=True)
    def optionTypes(self) -> QObject:
        return self.types_model

    @Property(int, notify=selectionChanged)
    def settingCount(self) -> int:
        return self._setting_count

    @Property(int, notify=selectionChanged)
    def settingTotal(self) -> int:
        return self.settings_model.rowCount()

    @Property(int, notify=selectionChanged)
    def typeCount(self) -> int:
        return self._type_count

    @Property(int, constant=True)
    def typeTotal(self) -> int:
        return len(OPTION_TYPES)

    @Property(str, notify=errorChanged)
    def error(self) -> str:
        return self._error

    @Property(str, notify=presetsChanged)
    def confirmText(self) -> str:
        if not self._destination:
            return ""
        return plain(trm(
            f"Transfer selected settings from <b>{html.escape(self._source)}{FileExt.JSON}</b>"
            f" to <b>{html.escape(self._destination)}{FileExt.JSON}</b>?<br><br>This cannot be undone!"))

    def selection_changed(self):
        """Settings or option types checked: counted, selectionChanged sent"""
        self._setting_count = sum(row["chosen"] for row in self.settings_model.rows)
        self._type_count = sum(row["chosen"] for row in self.types_model.rows)
        self.selectionChanged.emit()

    def _set_error(self, text: str):
        if text != self._error:
            self._error = text
            self.errorChanged.emit()

    @Slot()
    def start(self):
        """Panel opened: loaded preset & destinations read, selection kept if same settings"""
        self._set_error("")
        self.types_model.update_rows(lambda row: {"label": tr(OPTION_TYPES[row["key"]])})  # app language
        checked = {row["key"] for row in self.settings_model.rows if row["chosen"]}
        self.settings_model.sync([
            {"key": name, "label": module_label(name), "chosen": name in checked} for name in cfg.user.setting
        ])
        self.read_choices()
        self.selection_changed()

    def read_choices(self):
        self._source = preset_name(cfg.filename.setting)
        self._destinations = transfer_destinations()
        if self._destination not in self._destinations:
            self._destination = self._destinations[0] if self._destinations else ""
        self.presetsChanged.emit()

    @Slot(str)
    def setDestination(self, name: str):
        if name in self._destinations and name != self._destination:
            self._destination = name
            self._set_error("")
            self.presetsChanged.emit()

    @Slot(str)
    def toggleSetting(self, key: str):
        number = self.settings_model.index_of(key)
        if number >= 0:
            self.settings_model.update_row(number, {"chosen": not self.settings_model.rows[number]["chosen"]})
            self._set_error("")
            self.selection_changed()

    @Slot(bool)
    def setAllSettings(self, checked: bool):
        self.settings_model.update_rows(lambda row: {"chosen": checked})
        self._set_error("")
        self.selection_changed()

    @Slot(str)
    def toggleType(self, key: str):
        number = self.types_model.index_of(key)
        if number >= 0:
            self.types_model.update_row(number, {"chosen": not self.types_model.rows[number]["chosen"]})
            self._set_error("")
            self.selection_changed()

    @Slot(bool)
    def setAllTypes(self, checked: bool):
        self.types_model.update_rows(lambda row: {"chosen": checked})
        self._set_error("")
        self.selection_changed()

    @Slot(result=str)
    def missing(self) -> str:
        """What is left to choose before transfer (translated), "" if ready"""
        if not self._destination:
            return plain(trm("No destination preset selected or found."))
        if not self.settingCount:
            return plain(trm("No preset setting selected.<br><br>Select at least one setting and try again."))
        if not self.typeCount:
            return plain(trm("No option type selected.<br><br>Select at least one option type and try again."))
        return ""

    @Slot(result=bool)
    def transfer(self) -> bool:
        """Selected settings & option types written to destination (confirmed by page), True if done"""
        reason = self.missing()
        if reason:
            self._set_error(reason)
            return False
        destination = f"{self._destination}{FileExt.JSON}"
        settings = [row["key"] for row in self.settings_model.rows if row["chosen"]]
        types = [row["key"] for row in self.types_model.rows if row["chosen"]]
        error = transfer_settings(destination, settings, types)
        if error in (DESTINATION_GONE, DESTINATION_TAKEN):  # loaded, locked or renamed meanwhile: lists read again
            self.read_choices()
            self._set_error(tr(error))
            return False
        if error:
            self._set_error(plain(trm(error)))
            return False
        self._set_error("")
        self.page.show_toast(trm(
            f"Settings are transferred from <b>{html.escape(self._source)}{FileExt.JSON}</b>"
            f" to <b>{html.escape(destination)}</b>."))
        self.page.refresh()
        return True


# Backups
BACKUP_ROLES = ("key", "style", "status")
STATE_CHECKING = "checking"
STATE_VALID = "valid"
STATE_INVALID = "invalid"


class PresetBackupsBackend(PresetPart):
    """Backups of presets & style presets: listed at once, files checked in background; restore, delete"""

    rowsChanged = Signal()

    def __init__(self, page: PresetBackend):
        super().__init__(page)
        self.model = DictListModel(BACKUP_ROLES, self)
        self._files: dict[str, BackupFile] = {}

    @Property(QObject, constant=True)
    def rows(self) -> QObject:
        return self.model

    @Property(int, notify=rowsChanged)
    def count(self) -> int:
        return self.model.rowCount()

    @Property(bool, notify=rowsChanged)
    def checking(self) -> bool:
        return self.page.jobs.is_busy("backups")

    @Slot()
    def refresh(self):
        """Backup files listed, checked in background (invalid ones marked once checked)"""
        try:
            files = list_backups()
        except OSError:  # settings folder gone
            files = []
        known = {row["key"]: row["status"] for row in self.model.rows}
        self._files = {backup.name: backup for backup in files}
        self.model.sync([
            {"key": backup.name, "style": backup.style, "status": known.get(backup.name, STATE_CHECKING)}
            for backup in files
        ])
        names = tuple(name for name, state in known.items() if state == STATE_CHECKING and name in self._files)
        names += tuple(name for name in self._files if name not in known)
        if names:
            folder = cfg.path.settings
            self.page.jobs.run(
                "check backups", lambda: {name: verify_json_file(None, name, folder) for name in names},
                self._checked, key="backups")
        self.rowsChanged.emit()

    def _checked(self, valid: dict[str, bool]):
        for name, is_valid in valid.items():
            number = self.model.index_of(name)
            if number >= 0 and self.model.rows[number]["status"] == STATE_CHECKING:
                self.model.update_row(number, {"status": STATE_VALID if is_valid else STATE_INVALID})
        self.rowsChanged.emit()

    @Slot()
    def stop(self):
        self.page.jobs.cancel("backups")

    @Slot(str, result=str)
    def prepareRestore(self, name: str) -> str:
        """Kind of backup to restore: "style" (confirm first), "preset" (ask its name), "" if it cannot be
        (invalid file: told)"""
        backup = self._files.get(name)
        number = self.model.index_of(name)
        if backup is None or number < 0:
            return ""
        state = self.model.rows[number]["status"]
        if state == STATE_CHECKING:  # not checked yet in background
            state = STATE_VALID if verify_json_file(None, name, cfg.path.settings) else STATE_INVALID
            self.model.update_row(number, {"status": state})
        if state == STATE_INVALID:
            self.page.show_toast(trm("Selected backup file is invalid and cannot be restored."), error=True)
            return ""
        return "style" if backup.style else "preset"

    @Slot(str, result=str)
    def styleRestoreText(self, name: str) -> str:
        return plain(trm(
            f"<b>{html.escape(name)}</b> is a style preset.<br>"
            "Restoring this backup file will overwrite existing style preset.<br><br>"
            "Are you sure you want to restore and overwrite existing style preset?<br><br>"
            "This cannot be undone!"))

    @Slot(str)
    def restoreStyle(self, name: str):
        """Style preset backup put back (confirmed by page), styles reloaded; a running save is finished first,
        waited off the UI thread (audit PERF-018)"""
        if name not in self._files or not self._files[name].style:
            return
        after_saving(self.page, partial(self._restore_style, name))

    def _restore_style(self, name: str):
        try:
            restore_style_backup(name)
        except OSError as error:  # locked file (cloud sync, antivirus), permission
            self.page.show_toast(trm(f"Unable to restore backup file:<br>{html.escape(str(error))}"), error=True)
            return
        self.page.show_toast(trm(f"Preset restored: <b>{html.escape(name[:name.find(FileExt.JSON)])}</b>"))
        self.refresh()

    @Slot(str, result=str)
    def suggestName(self, name: str) -> str:
        """Free preset name for restored backup (its preset name, numbered if used)"""
        basename = name[:name.find(FileExt.JSON)] if FileExt.JSON in name else name
        return preset_name(free_preset_name(cfg.path.settings, f"{basename}{FileExt.JSON}"))

    @Slot(str, result=str)
    def deleteText(self, name: str) -> str:
        return plain(trm(f"Delete <b>{html.escape(name)}</b> preset permanently?<br><br>This cannot be undone!"))

    @Slot(str)
    def remove(self, name: str):
        """Backup file deleted for good (confirmed by page)"""
        if name not in self._files:
            return
        try:
            delete_backup(name)
        except OSError as error:  # locked file (cloud sync, antivirus), permission
            self.page.show_toast(trm(f"Unable to delete backup file:<br>{html.escape(str(error))}"), error=True)
        self.refresh()


# Recently deleted presets
TRASH_ROLES = ("key", "name", "deleted", "daysLeft")
# Trash folders changed by one thread at a time: the purge of the read job (old entries removed) never runs under a
# restore or delete of the page; the UI waits at most TRASH_WAIT seconds for it, then asks to try again
TRASH = threading.Lock()
TRASH_WAIT = 2.0
TRASH_BUSY = "Deleted presets are being read, please try again."
ENTRY_GONE = "This preset is no longer in the trash."


class PresetTrashBackend(PresetPart):
    """Recently deleted presets (trash): restore with their references, delete for good, empty"""

    trashChanged = Signal()  # presets in trash, reading, days kept

    def __init__(self, page: PresetBackend):
        super().__init__(page)
        self.model = DictListModel(TRASH_ROLES, self)
        self._entries: dict[str, TrashEntry] = {}
        self._keep_days = trash_keep_days()

    @Property(QObject, constant=True)
    def rows(self) -> QObject:
        return self.model

    @Property(int, notify=trashChanged)
    def count(self) -> int:
        return self.model.rowCount()

    @Property(bool, notify=trashChanged)
    def loading(self) -> bool:
        return self.page.jobs.is_busy("trash")

    @Property(int, notify=trashChanged)
    def keepDays(self) -> int:
        return self._keep_days

    @Slot()
    def refresh(self):
        """Old entries removed, presets in trash read in background (newest first)"""
        self._keep_days = keep_days = trash_keep_days()
        folder = cfg.path.settings

        def work() -> list[TrashEntry]:
            with TRASH:  # never under a restore or delete of the page
                purge_trash(folder, keep_days)
                return list_trash(folder)

        self.page.jobs.run("read deleted presets", work, self._read, key="trash")
        self.trashChanged.emit()

    def _hold_trash(self) -> bool:
        """Trash taken for a change by the page (released by release_trash), False if the read job keeps it too long
        (slow disk): told to try again"""
        if TRASH.acquire(timeout=TRASH_WAIT):
            return True
        self.page.show_toast(tr(TRASH_BUSY), error=True)
        return False

    def _read(self, entries: list[TrashEntry]):
        self._entries = {entry.folder: entry for entry in entries}
        self.model.sync([
            {
                "key": entry.folder, "name": entry.name, "deleted": format_deleted_time(entry.deleted),
                "daysLeft": days_left(entry.deleted, self._keep_days),
            }
            for entry in entries
        ])
        self.trashChanged.emit()
        self.page.update_trash_count(len(entries))

    @Slot(str)
    def restore(self, key: str):
        """Preset restored (renamed if a preset has its name), primary references set again"""
        entry = self._entries.get(key)
        if entry is None or not self._hold_trash():
            return
        try:
            if not os.path.isdir(entry.folder):  # purged (too old) or removed meanwhile: shown entry gone
                self.page.show_toast(tr(ENTRY_GONE), error=True)
                self.refresh()
                return
            filename = restore_trashed_preset(entry)
        except OSError as error:  # locked file (cloud sync, antivirus), permission
            self.page.show_toast(trm(f"Unable to restore preset:<br>{html.escape(str(error))}"), error=True)
            return
        finally:
            TRASH.release()
        self.page.refresh()
        app_signal.refresh.emit(True)
        self.page.show_toast(trm(f"Preset restored: <b>{html.escape(preset_name(filename))}</b>"))
        self.refresh()

    @Slot(str, result=str)
    def deleteText(self, key: str) -> str:
        entry = self._entries.get(key)
        if entry is None:
            return ""
        return plain(trm(f"Delete <b>{html.escape(entry.name)}</b> preset permanently?<br><br>This cannot be undone!"))

    @Slot(result=str)
    def emptyText(self) -> str:
        return plain(trm(
            f"Delete all <b>{len(self._entries)}</b> preset(s) in trash permanently?<br><br>This cannot be undone!"))

    @Slot(str)
    def remove(self, key: str):
        """Preset deleted for good (confirmed by page)"""
        entry = self._entries.get(key)
        if entry is None or not self._hold_trash():
            return
        try:
            removed = remove_entry(entry)
        finally:
            TRASH.release()
        if not removed:
            self.page.show_toast(trm(f"Unable to delete preset:<br>{html.escape(entry.folder)}"), error=True)
        self.refresh()

    @Slot()
    def empty(self):
        """Every preset in trash deleted for good (confirmed by page)"""
        if not self._hold_trash():
            return
        try:
            failed = [entry for entry in self._entries.values() if not remove_entry(entry)]
        finally:
            TRASH.release()
        if failed:
            self.page.show_toast(trm(f"Unable to delete preset:<br>{html.escape(failed[0].folder)}"), error=True)
        self.refresh()
