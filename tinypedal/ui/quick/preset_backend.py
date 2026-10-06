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
Presets page backend (qml/Presets.qml): presets with their tags & content, search, sort & actions

Each preset row tells its primary tags (car classes, tracks), lock, preset hotkeys, last change and
how many overlays & modules it turns on. Preset files are read only when they changed (size & time
cache), and only while the page is shown: a refresh while hidden is done when the page shows again.
Actions with dialogs (files, share codes, other pages) are run by the page hosting the backend.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, NamedTuple, Protocol

from PySide6.QtCore import Property, QDateTime, QLocale, QObject, Signal, Slot

from ... import app_signal
from ...const_app import VERSION
from ...const_file import ConfigType, FileExt
from ...formatter import strip_filename_extension
from ...i18n import current_language, tr, trm
from ...i18n.options import module_label
from ...module_control import mctrl, wctrl
from ...setting import cfg
from ...template.setting_shortcuts import SHORTCUTS_PRESET
from ...userfile.json_setting import create_backup_file, set_backup_timestamp
from ...userfile.preset_share import summarize_preset
from ...userfile.preset_trash import list_trash
from ..module_view import sort_key
from ..preset_management import apply_preset_name, check_preset_name
from .models import DictListModel

SORT_RECENT = 0
SORT_NAME = 1
MAX_SHOWN_NAMES = 40  # overlays & modules listed in details
ROLES = (
    "key", "name", "loaded", "locked", "lockVersion", "changedText", "classes", "tracks", "hotkeys",
    "overlays", "modules", "unreadable",
)
MODE_NEW = ""
MODE_DUPLICATE = "duplicate"
MODE_RENAME = "rename"


class PresetHost(Protocol):
    """Page hosting the backend: messages, files & other pages"""

    def confirm_operation(self, title: str = "Confirm", message: str = "") -> bool: ...
    def warn(self, text: str) -> None: ...
    def toast(self, text: str) -> None: ...
    def delete_preset(self, preset_filename: str) -> bool: ...
    def undo_delete(self, entry: Any = None) -> bool: ...
    def export_package(self, preset_filename: str) -> None: ...
    def copy_share_code(self, preset_filename: str) -> None: ...
    def import_package(self) -> None: ...
    def import_share_code(self) -> None: ...
    def open_page(self, name: str, preset_filename: str = "") -> None: ...


class Summary(NamedTuple):
    """Content of preset file"""

    widgets: tuple[str, ...]  # turned on
    modules: tuple[str, ...]
    api: str


class SummaryCache:
    """Preset contents, read again only when file size or time changed"""

    def __init__(self):
        self._entries: dict[str, tuple[tuple[int, int], Summary | None]] = {}

    def get(self, path: str) -> Summary | None:
        """Content of preset file, None if unreadable"""
        try:
            stat = os.stat(path)
        except OSError:
            return None
        stamp = (stat.st_mtime_ns, stat.st_size)
        cached = self._entries.get(path)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        summary: Summary | None
        try:
            with open(path, encoding="utf-8") as file:
                preset = json.load(file)
            if not isinstance(preset, dict):
                raise ValueError("not a preset")
            content = summarize_preset(preset, wctrl.names, mctrl.names)
            preset_info = preset.get("preset")
            api = str(preset_info.get("api_name", "")) if isinstance(preset_info, dict) else ""
            summary = Summary(content.widgets, content.modules, api)
        except (OSError, ValueError, RecursionError, UnicodeDecodeError):
            summary = None
        self._entries[path] = (stamp, summary)
        return summary

    def keep(self, paths: set[str]):
        """Forget presets gone"""
        for path in list(self._entries):
            if path not in paths:
                del self._entries[path]


def changed_text(modified: float, now: float | None = None) -> str:
    """When preset was last changed: "Just now", "5 min ago", "3 h ago", "Yesterday", "4 days ago", date"""
    seconds = max((time.time() if now is None else now) - modified, 0)
    if seconds < 60:
        return tr("Just now")
    if seconds < 3600:
        return trm(f"{int(seconds // 60)} min ago")
    if seconds < 86400:
        return trm(f"{int(seconds // 3600)} h ago")
    days = int(seconds // 86400)
    if days == 1:
        return tr("Yesterday")
    if days < 7:
        return trm(f"{days} days ago")
    return QLocale(current_language()).toString(
        QDateTime.fromSecsSinceEpoch(int(modified)).date(), QLocale.FormatType.ShortFormat)


def full_date(modified: float) -> str:
    """Date & time of last change: "Sunday, October 4, 2026 · 21:07" (app language)"""
    locale = QLocale(current_language())
    moment = QDateTime.fromSecsSinceEpoch(int(modified))
    return (f"{locale.toString(moment.date(), QLocale.FormatType.LongFormat)}  ·  "
            f"{locale.toString(moment.time(), QLocale.FormatType.ShortFormat)}")


def size_text(size: int) -> str:
    if size < 1024:
        return trm(f"{size} bytes")
    return trm(f"{size / 1024:.0f} KB")


class PresetBackend(QObject):
    """Presets page state & actions

    Args:
        parent: page widget.
        host: messages, files & other pages, see PresetHost.
    """

    presetsChanged = Signal()  # counts, loaded preset, details
    filterChanged = Signal()
    selectionChanged = Signal()
    stateChanged = Signal()  # auto load, trash, undo

    def __init__(self, parent, host: PresetHost):
        super().__init__(parent)
        self._host = host
        self.model = DictListModel(ROLES, self)
        self._cache = SummaryCache()
        self._rows: list[dict] = []  # every preset, file order
        self._times: dict[str, tuple[float, int]] = {}  # filename: (modified time, size)
        self._search = ""
        self._words: tuple[str, ...] = ()
        self._sort = SORT_RECENT
        self._selected = ""
        self._active = False
        self._stale = True
        self._trash_count = 0
        self._can_undo = False

    # Reading
    def set_active(self, active: bool):
        """Page shown or hidden: presets read only while shown"""
        self._active = active
        if active and self._stale:
            self.refresh()

    def refresh(self):
        """Presets, tags & loaded preset read again (later if page is hidden)"""
        if not self._active:
            self._stale = True
            return
        self._stale = False
        folder = cfg.path.settings
        names = cfg.preset_files() if os.path.isdir(folder) else []
        rows, times = [], {}
        for name in names:
            filename = f"{name}{FileExt.JSON}"
            path = os.path.join(folder, filename)
            try:
                stat = os.stat(path)
            except OSError:
                continue  # "default" listed while folder has no preset
            times[filename] = (stat.st_mtime, stat.st_size)
            rows.append(self.make_row(filename, path, stat.st_mtime))
        self._cache.keep({os.path.join(folder, filename) for filename in times})
        self._rows, self._times = rows, times
        if self._selected not in times:
            self._selected = cfg.filename.setting if cfg.filename.setting in times else ""
        self._trash_count = len(list_trash(folder)) if os.path.isdir(folder) else 0
        self.update_rows()
        self.presetsChanged.emit()
        self.selectionChanged.emit()
        self.stateChanged.emit()

    def make_row(self, filename: str, path: str, modified: float) -> dict:
        name = filename[:-len(FileExt.JSON)]
        summary = self._cache.get(path)
        lock = cfg.user.filelock.get(filename)
        return {
            "key": filename,
            "name": name,
            "loaded": filename == cfg.filename.setting,
            "locked": lock is not None,
            "lockVersion": str(lock.get("version", "")) if isinstance(lock, dict) else "",
            "changedText": changed_text(modified),
            "modifiedTime": modified,
            "classes": [
                {"name": class_name, "color": str(data.get("color", ""))}
                for class_name, data in cfg.user.classes.items()
                if isinstance(data, dict) and data.get("preset") == name
            ],
            "tracks": sorted(
                (track for track, data in cfg.user.tracks.items() if isinstance(data, dict) and data.get("preset") == name),
                key=sort_key),
            "hotkeys": [
                int(option.rsplit("_", 1)[1]) for option in SHORTCUTS_PRESET
                if cfg.user.shortcuts.get(option, {}).get("preset") == name
            ],
            "overlays": len(summary.widgets) if summary else 0,
            "modules": len(summary.modules) if summary else 0,
            "unreadable": summary is None,
        }

    def update_rows(self):
        """Shown rows (search & sort), synced in place"""
        rows = [row for row in self._rows if self._accepts(row)]
        if self._sort == SORT_NAME:
            rows.sort(key=lambda row: sort_key(row["name"]))
        else:
            rows.sort(key=lambda row: -row["modifiedTime"])
        self.model.sync([{name: row[name] for name in ROLES} for row in rows])

    def _accepts(self, row: dict) -> bool:
        if not self._words:
            return True
        text = sort_key(" ".join((
            row["name"], *(entry["name"] for entry in row["classes"]), *row["tracks"],
        )))
        return all(word in text for word in self._words)

    # Properties
    @Property(QObject, constant=True)
    def presets(self) -> QObject:
        return self.model

    @Property(int, notify=presetsChanged)
    def presetCount(self) -> int:
        return len(self._rows)

    @Property(int, notify=presetsChanged)
    def shownCount(self) -> int:
        return self.model.rowCount()

    @Property(dict, notify=presetsChanged)
    def loaded(self) -> dict:
        """Loaded preset card"""
        filename = cfg.filename.setting
        row = next((row for row in self._rows if row["key"] == filename), None)
        name = filename[:-len(FileExt.JSON)] if filename.endswith(FileExt.JSON) else filename
        if row is None:
            return {"key": filename, "name": name, "found": False, "locked": filename in cfg.user.filelock}
        return {**row, "found": True}

    @Property(str, notify=selectionChanged)
    def selectedKey(self) -> str:
        return self._selected

    @Property(dict, notify=selectionChanged)
    def selected(self) -> dict:
        """Details of selected preset: content, tags, file"""
        row = next((row for row in self._rows if row["key"] == self._selected), None)
        if row is None:
            return {"found": False}
        path = os.path.join(cfg.path.settings, row["key"])
        summary = self._cache.get(path)
        modified, size = self._times.get(row["key"], (0.0, 0))
        overlays = sorted((module_label(name) for name in summary.widgets), key=sort_key) if summary else []
        modules = sorted((module_label(name) for name in summary.modules), key=sort_key) if summary else []
        return {
            **row,
            "found": True,
            "overlayNames": overlays[:MAX_SHOWN_NAMES],
            "overlayMore": max(len(overlays) - MAX_SHOWN_NAMES, 0),
            "moduleNames": modules[:MAX_SHOWN_NAMES],
            "moduleMore": max(len(modules) - MAX_SHOWN_NAMES, 0),
            "api": summary.api if summary else "",
            "date": full_date(modified),
            "size": size_text(size),
            "classChoices": [name for name in cfg.user.classes if cfg.user.classes[name].get("preset") != row["name"]],
            "trackChoices": sorted(
                (track for track, data in cfg.user.tracks.items()
                 if isinstance(data, dict) and data.get("preset") != row["name"]),
                key=sort_key),
        }

    @Property(bool, notify=stateChanged)
    def autoLoad(self) -> bool:
        return bool(cfg.application["enable_auto_load_preset"])

    @Property(int, notify=stateChanged)
    def trashCount(self) -> int:
        return self._trash_count

    @Property(bool, notify=stateChanged)
    def canUndoDelete(self) -> bool:
        return self._can_undo

    @Property(str, notify=filterChanged)
    def searchText(self) -> str:
        return self._search

    @Property(int, notify=filterChanged)
    def sortMode(self) -> int:
        return self._sort

    @Property(bool, notify=filterChanged)
    def filtered(self) -> bool:
        return bool(self._words)

    # Filters & selection
    @Slot(str)
    def setSearch(self, text: str):
        self._search = text
        words = tuple(sort_key(text).split())
        if words != self._words:
            self._words = words
            self.update_rows()
            self.presetsChanged.emit()
        self.filterChanged.emit()

    @Slot(int)
    def setSortMode(self, mode: int):
        if mode in (SORT_RECENT, SORT_NAME) and mode != self._sort:
            self._sort = mode
            self.update_rows()
            self.filterChanged.emit()

    @Slot(str)
    def select(self, filename: str):
        if filename != self._selected and filename in self._times:
            self._selected = filename
            self.selectionChanged.emit()

    # Actions
    def _known(self, filename: str) -> bool:
        return filename in self._times

    @Slot(str)
    def load(self, filename: str):
        """Load preset (whole app reloaded)"""
        if self._known(filename):
            cfg.set_next_to_load(filename)
            app_signal.reload.emit(True)

    @Slot(bool)
    def setAutoLoad(self, enabled: bool):
        cfg.application["enable_auto_load_preset"] = enabled
        cfg.save(config_type=ConfigType.CONFIG)
        self.stateChanged.emit()

    @Slot(str, str, str, result=str)
    def nameError(self, mode: str, filename: str, name: str) -> str:
        """Why name cannot be used (translated), "" if it can (or rename keeps same name)"""
        if mode == MODE_RENAME and strip_filename_extension(name.strip(), FileExt.JSON) == filename[:-len(FileExt.JSON)]:
            return ""
        return check_preset_name(name, mode, filename) if name.strip() else ""

    @Slot(str, str, result=str)
    def suggestName(self, mode: str, filename: str) -> str:
        """Name proposed in name box: free copy name, current name, or free "New preset" """
        from ...userfile.preset_trash import free_preset_name

        if mode == MODE_RENAME:
            return filename[:-len(FileExt.JSON)]
        base = filename if mode == MODE_DUPLICATE and filename else f"{tr('New preset')}{FileExt.JSON}"
        return free_preset_name(cfg.path.settings, base)[:-len(FileExt.JSON)]

    @Slot(str, str, str, result=str)
    def applyName(self, mode: str, filename: str, name: str) -> str:
        """Create, duplicate or rename preset: "" if done, else why not (translated)"""
        if mode not in (MODE_NEW, MODE_DUPLICATE, MODE_RENAME):
            return ""
        if mode and not self._known(filename):
            return tr("Preset not found, it may have been renamed or deleted.")
        if mode == MODE_RENAME and filename in cfg.user.filelock:
            return tr("Unlock the preset to rename it.")
        entered_name = strip_filename_extension(name.strip(), FileExt.JSON)  # "Race.json" is "Race"
        if mode == MODE_RENAME and entered_name == filename[:-len(FileExt.JSON)]:
            return ""
        error = apply_preset_name(name.strip(), mode, filename)
        if not error:
            self._selected = f"{entered_name}{FileExt.JSON}"
            self.refresh()
            verb = {MODE_NEW: "Preset created", MODE_DUPLICATE: "Preset duplicated", MODE_RENAME: "Preset renamed"}[mode]
            self._host.toast(trm(f"{verb}: <b>{entered_name}</b>"))
        return error

    @Slot(str)
    def remove(self, filename: str):
        """Delete preset: moved to trash, undo offered"""
        if not self._known(filename):
            return
        if os.path.normcase(filename) == os.path.normcase(cfg.filename.setting):
            self._host.warn(tr("The loaded preset cannot be deleted, load another preset first."))
            return
        if filename in cfg.user.filelock:
            self._host.warn(tr("Unlock the preset to delete it."))
            return
        if self._host.delete_preset(filename):
            app_signal.refresh.emit(True)

    def deleted(self, can_undo: bool):
        """Host deleted or restored a preset: undo state"""
        self._can_undo = can_undo
        self.stateChanged.emit()

    @Slot()
    def undoDelete(self):
        self._host.undo_delete()

    @Slot(str)
    def toggleLock(self, filename: str):
        """Lock (changes never saved) or unlock preset, confirmed"""
        if not self._known(filename):
            return
        if filename in cfg.user.filelock:
            if self._host.confirm_operation(tr("Unlock Preset"), f"Unlock <b>{filename}</b> preset?"):
                cfg.user.filelock.pop(filename, None)
                cfg.save(config_type=ConfigType.FILELOCK)
                app_signal.refresh.emit(True)
            return
        message = f"Lock <b>{filename}</b> preset?<br><br>Changes to locked preset will not be saved."
        if self._host.confirm_operation(tr("Lock Preset"), message):
            cfg.user.filelock[filename] = {"version": VERSION}
            cfg.save(config_type=ConfigType.FILELOCK)
            app_signal.refresh.emit(True)

    @Slot(str)
    def backup(self, filename: str):
        """Backup copy of preset, restored from Restore Backup page"""
        if not self._known(filename):
            return
        extension = set_backup_timestamp()
        if create_backup_file(filename, cfg.path.settings, extension, show_log=True):
            self._host.toast(trm(f"Backup saved as:<br><b>{filename}{extension}</b>"))
        else:
            self._host.warn(trm("Failed to create backup, please try again."))

    @Slot(str)
    def exportPackage(self, filename: str):
        if self._known(filename):
            self._host.export_package(filename)

    @Slot(str)
    def copyShareCode(self, filename: str):
        if self._known(filename):
            self._host.copy_share_code(filename)

    @Slot()
    def importPackage(self):
        self._host.import_package()

    @Slot()
    def importShareCode(self):
        self._host.import_share_code()

    @Slot(str)
    def compare(self, filename: str):
        """Compare with loaded preset"""
        if self._known(filename):
            self._host.open_page("compare", filename)

    @Slot(str)
    def openPage(self, name: str):
        """Transfer, restore backup or trash page"""
        self._host.open_page(name)

    # Primary tags
    @Slot(str, str)
    def setPrimaryClass(self, filename: str, class_name: str):
        """Preset loaded automatically for car class (auto load)"""
        if self._known(filename) and class_name in cfg.user.classes:
            cfg.user.classes[class_name]["preset"] = filename[:-len(FileExt.JSON)]
            cfg.save(config_type=ConfigType.CLASSES)
            self.refresh()

    @Slot(str, str)
    def setPrimaryTrack(self, filename: str, track: str):
        """Preset loaded automatically for track (auto load, before class preset)"""
        if self._known(filename) and track in cfg.user.tracks:
            cfg.user.tracks[track]["preset"] = filename[:-len(FileExt.JSON)]
            cfg.save(config_type=ConfigType.TRACKS)
            self.refresh()

    @Slot(str)
    def removePrimaryClass(self, class_name: str):
        data = cfg.user.classes.get(class_name)
        if isinstance(data, dict) and data.get("preset"):
            data["preset"] = ""
            cfg.save(config_type=ConfigType.CLASSES)
            self.refresh()

    @Slot(str)
    def removePrimaryTrack(self, track: str):
        data = cfg.user.tracks.get(track)
        if isinstance(data, dict) and data.get("preset"):
            data["preset"] = ""
            cfg.save(config_type=ConfigType.TRACKS)
            self.refresh()

    @Slot(str)
    def clearPrimary(self, filename: str):
        """Every primary tag of preset removed"""
        name = filename[:-len(FileExt.JSON)]
        for config_type in (ConfigType.CLASSES, ConfigType.TRACKS):
            entries = getattr(cfg.user, config_type)
            changed = False
            for data in entries.values():
                if isinstance(data, dict) and data.get("preset") == name:
                    data["preset"] = ""
                    changed = True
            if changed:
                cfg.save(config_type=config_type)
        self.refresh()
