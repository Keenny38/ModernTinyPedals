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
Presets page backend (qml/Presets.qml): presets with their tags & content, search, sort & actions

Each preset row tells its primary tags (car classes, tracks), lock, preset hotkeys, last change and
how many overlays & modules it turns on. Preset files are read only when they changed (size & time
cache), in background (rows show their last change only until read), and only while the page is shown:
a refresh while hidden is done when the page shows again.
Actions with dialogs (files) are run by the page hosting the backend. Compare, transfer, backups & recently
deleted presets are panels of the page, their state in parts (quick/preset_tools_backend.py: backend.compare...).
Short notices go to the toast of the page (toastShown), with Undo after a delete.
"""

from __future__ import annotations

import html
import json
import os
import threading
import time
from collections.abc import Callable, Iterable
from functools import partial
from typing import Any, NamedTuple, Protocol

from PySide6.QtCore import Property, QDateTime, QLocale, QObject, Signal, Slot

from ... import app_signal
from ...const_app import VERSION
from ...const_file import ConfigType, FileExt
from ...formatter import strip_filename_extension
from ...i18n import tr, trm
from ...i18n.options import module_label
from ...module_control import mctrl, wctrl
from ...setting import cfg
from ...template.setting_classes import CLASS_PRESET_KEYS, SESSION_PRESET_KEYS
from ...template.setting_shortcuts import SHORTCUTS_PRESET
from ...userfile.json_setting import create_backup_file, set_backup_timestamp
from ...userfile.preset_trash import count_trash
from ...validator import is_allowed_filename
from ..module_view import sort_key
from ..preset_management import after_saving, apply_preset_name, check_preset_name
from .formatting import date_locale, format_date
from .models import DictListModel
from .page_backend import PageBackend
from .preset_tools_backend import (
    PresetBackupsBackend,
    PresetCompareBackend,
    PresetTransferBackend,
    PresetTrashBackend,
    plain,
)

SORT_RECENT = 0
SORT_NAME = 1
MAX_SHOWN_NAMES = 40  # overlays & modules listed in details
ROLES = (
    "key", "name", "loaded", "locked", "lockVersion", "changedText", "classes", "tracks", "hotkeys",
    "overlays", "modules", "unreadable", "pending", "contentText",
)
MODE_NEW = ""
MODE_DUPLICATE = "duplicate"
MODE_RENAME = "rename"
MODE_RESTORE = "restore"  # backup restored as a new preset
# Held while the read job has a preset file open: moving or renaming it waits (Windows refuses to move an open file)
PRESET_FILES = threading.Lock()
# UI thread waits for a file being read at most this long (slow disk, antivirus), then asks to try again
PRESET_FILES_WAIT = 2.0
TRY_AGAIN = "Preset files are being read, please try again."


class PresetHost(Protocol):
    """Page hosting the backend: messages, files & other pages

    Optional: ask(title, message, on_result) confirmation over the page (answer by callback, else
    confirm_operation answers at once), page_toast(text, error, undo) toast of the page.
    """

    def confirm_operation(self, title: str = "Confirm", message: str = "") -> bool: ...
    def warn(self, text: str) -> None: ...
    def delete_preset(self, preset_filename: str) -> bool: ...
    def undo_delete(self, entry: Any = None) -> bool: ...
    def export_package(self, preset_filename: str) -> None: ...
    def import_package(self) -> None: ...
    def open_page(self, name: str) -> None: ...  # "folder": presets folder in file manager


class Summary(NamedTuple):
    """Content of preset file"""

    widgets: tuple[str, ...]  # turned on
    modules: tuple[str, ...]
    api: str


Stamp = tuple[int, int]  # file time (ns) & size


def summarize_preset(
    preset: dict, widget_names: Iterable[str], module_names: Iterable[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Enabled widgets & modules of preset"""
    widgets = set(widget_names)
    modules = set(module_names)
    enabled = [name for name, options in preset.items() if isinstance(options, dict) and options.get("enable")]
    return (
        tuple(sorted(name for name in enabled if name in widgets)),
        tuple(sorted(name for name in enabled if name in modules)),
    )


def read_summary(path: str, widget_names: Iterable[str], module_names: Iterable[str]) -> tuple[Stamp | None, Summary | None]:
    """Stamp & content of preset file (any thread): content None if unreadable, stamp None if file is gone"""
    try:
        stat = os.stat(path)
    except OSError:
        return None, None
    summary: Summary | None
    try:
        with PRESET_FILES, open(path, encoding="utf-8") as file:
            preset = json.load(file)
        if not isinstance(preset, dict):
            raise ValueError("not a preset")
        widgets, modules = summarize_preset(preset, widget_names, module_names)
        preset_info = preset.get("preset")
        api = str(preset_info.get("api_name", "")) if isinstance(preset_info, dict) else ""
        summary = Summary(widgets, modules, api)
    except (OSError, ValueError, RecursionError, UnicodeDecodeError):
        summary = None
    return (stat.st_mtime_ns, stat.st_size), summary


class SummaryCache:
    """Preset contents, read again only when file size or time changed"""

    def __init__(self):
        self._entries: dict[str, tuple[Stamp, Summary | None]] = {}

    def lookup(self, path: str, stamp: Stamp) -> tuple[bool, Summary | None]:
        """(cached, content) of preset file of stamp, cached False if not read or changed since"""
        cached = self._entries.get(path)
        if cached is not None and cached[0] == stamp:
            return True, cached[1]
        return False, None

    def store(self, path: str, stamp: Stamp, summary: Summary | None):
        self._entries[path] = (stamp, summary)

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
    return format_date(modified)  # date rule of every page (date_locale)


def full_date(modified: float) -> str:
    """Date & time of last change: "Sunday, October 4, 2026 · 21:07" (app language)"""
    locale = date_locale()
    moment = QDateTime.fromSecsSinceEpoch(int(modified))
    return (f"{locale.toString(moment.date(), QLocale.FormatType.LongFormat)}  ·  "
            f"{locale.toString(moment.time(), QLocale.FormatType.ShortFormat)}")


def size_text(size: int) -> str:
    if size < 1024:
        return trm(f"{size} bytes")
    return trm(f"{size / 1024:.0f} KB")


def trash_stamp(folder: str) -> int:
    """Change time (ns) of the trash of the presets folder: an entry (folder) added, restored or purged changes it,
    0 without trash"""
    from ...userfile.preset_trash import trash_path

    try:
        return os.stat(trash_path(folder)).st_mtime_ns
    except OSError:  # no trash yet
        return 0


def list_presets(folder: str) -> list[tuple[str, os.stat_result]]:
    """Preset file names (with extension) & their stat, newest first (order of cfg.preset_files), read by one
    directory scan: on Windows the listing carries each entry's stat (no call per file, audit PERF-048)"""
    found = []
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                filename = entry.name
                name = filename[:-len(FileExt.JSON)]
                if not filename.lower().endswith(FileExt.JSON) or not is_allowed_filename(name):
                    continue
                try:
                    if not entry.is_file():
                        continue
                    stat = entry.stat()
                except OSError:
                    continue
                found.append((stat.st_mtime, name, filename, stat))
    except OSError:
        return []
    found.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [(filename, stat) for _, _, filename, stat in found]


class References(NamedTuple):
    """Primary preset tags by preset name: car classes (name, color, session: "" every session, else "practice",
    "qualify", "race"), tracks (sorted), hotkey numbers"""

    classes: dict[str, list[dict]]
    tracks: dict[str, list[str]]
    hotkeys: dict[str, list[int]]


def preset_references() -> References:
    """Primary preset tags of every preset, classes, tracks & shortcuts read once"""
    def preset_of(data) -> str:
        preset = data.get("preset") if isinstance(data, dict) else None
        return preset if isinstance(preset, str) else ""

    classes: dict[str, list[dict]] = {}
    for class_name, data in cfg.user.classes.items():
        if not isinstance(data, dict):
            continue
        color = str(data.get("color", ""))
        if preset := preset_of(data):
            classes.setdefault(preset, []).append({"name": class_name, "color": color, "session": ""})
        for session, key in SESSION_PRESET_KEYS.items():
            if (session_preset := data.get(key)) and isinstance(session_preset, str):
                classes.setdefault(session_preset, []).append({"name": class_name, "color": color, "session": session})
    tracks: dict[str, list[str]] = {}
    for track, data in cfg.user.tracks.items():
        if preset := preset_of(data):
            tracks.setdefault(preset, []).append(track)
    for names in tracks.values():
        names.sort(key=sort_key)
    hotkeys: dict[str, list[int]] = {}
    for option in SHORTCUTS_PRESET:
        if preset := preset_of(cfg.user.shortcuts.get(option, {})):
            hotkeys.setdefault(preset, []).append(int(option.rsplit("_", 1)[1]))
    return References(classes, tracks, hotkeys)


class PresetBackend(PageBackend):
    """Presets page state & actions

    Args:
        parent: page widget.
        host: messages, files & other pages, see PresetHost.
    """

    presetsChanged = Signal()  # counts, loaded preset, details
    filterChanged = Signal()
    selectionChanged = Signal()
    stateChanged = Signal()  # auto load, trash, undo
    toastShown = Signal(str, bool, bool)  # plain text, error, Undo (last delete) offered
    panelRequested = Signal(str, str)  # panel ("compare", "transfer", "restore", "trash") & preset file name

    def __init__(self, parent, host: PresetHost):
        super().__init__(parent, "Presets")
        self._host = host
        self.model = DictListModel(ROLES, self)
        self._cache = SummaryCache()
        self._summaries: dict[str, Summary | None] = {}  # filename: content of rows read
        self._rows: list[dict] = []  # every preset, file order
        self._times: dict[str, tuple[float, int]] = {}  # filename: (modified time, size)
        self._search = ""
        self._words: tuple[str, ...] = ()
        self._sort = SORT_RECENT
        self._selected = ""
        self._active = False
        self._stale = True
        # Trash change time the entries were counted at: a refresh while the trash did not change (overlay toggled,
        # option saved) never scans it again (the presets are stat'ed: a file edited in place keeps folder times)
        self._trash_stamp: int | None = None
        self._trash_count = 0
        self._can_undo = False
        self._compare = PresetCompareBackend(self)
        self._transfer = PresetTransferBackend(self)
        self._backups = PresetBackupsBackend(self)
        self._trash = PresetTrashBackend(self)

    # Reading
    def set_active(self, active: bool):
        """Page shown or hidden: presets read only while shown"""
        self._active = active
        if active:
            self._trash_stamp = None  # page shown: trash counted again
        if active and self._stale:
            self.refresh()

    def refresh(self):
        """Presets, tags & loaded preset read again (later if page is hidden); trash scanned only when it changed"""
        if not self._active:
            self._stale = True
            return
        self._stale = False
        folder = cfg.path.settings
        stamp = trash_stamp(folder)
        if stamp != self._trash_stamp:
            self._trash_count = count_trash(folder)  # entries read & checked by Trash page only
            self._trash_stamp = stamp
        references = preset_references()
        rows, times, summaries, missing = [], {}, {}, []
        for filename, stat in list_presets(folder):
            path = os.path.join(folder, filename)
            times[filename] = (stat.st_mtime, stat.st_size)
            found, summary = self._cache.lookup(path, (stat.st_mtime_ns, stat.st_size))
            if found:
                summaries[filename] = summary
            else:
                missing.append(path)  # read in background, row pending meanwhile
            rows.append(self.make_row(filename, stat.st_mtime, summary, pending=not found, references=references))
        self._cache.keep({os.path.join(folder, filename) for filename in times})
        self._rows, self._times, self._summaries = rows, times, summaries
        if missing:
            self._read_summaries(missing)
        if self._selected not in times:
            self._selected = cfg.filename.setting if cfg.filename.setting in times else ""
        self.update_rows()
        self.presetsChanged.emit()
        self.selectionChanged.emit()
        self.stateChanged.emit()

    def _read_summaries(self, paths: list[str]):
        """Contents of preset files read on a thread, rows updated when done (last refresh only)"""
        widget_names, module_names = tuple(wctrl.names), tuple(mctrl.names)

        def work() -> list[tuple[str, Stamp | None, Summary | None]]:
            return [(path, *read_summary(path, widget_names, module_names)) for path in paths]

        self.jobs.run("read presets", work, self._summaries_read, key="summaries")

    def _summaries_read(self, results: list[tuple[str, Stamp | None, Summary | None]]):
        """Preset contents read: pending rows updated (in place), loaded preset & details told"""
        read = {}
        for path, stamp, summary in results:
            if stamp is not None:
                self._cache.store(path, stamp, summary)
            read[os.path.normcase(path)] = summary
        folder = cfg.path.settings
        changed = False
        references = None
        for number, row in enumerate(self._rows):
            filename = row["key"]
            path = os.path.normcase(os.path.join(folder, filename))
            if not row["pending"] or path not in read:
                continue
            if references is None:
                references = preset_references()
            self._summaries[filename] = read[path]
            self._rows[number] = self.make_row(
                filename, row["modifiedTime"], read[path], pending=False, references=references)
            changed = True
        if changed:
            self.update_rows()
            self.presetsChanged.emit()
            self.selectionChanged.emit()

    @property
    def reading(self) -> bool:
        """Preset contents being read in background"""
        return self.jobs.is_busy("summaries")

    def make_row(
        self, filename: str, modified: float, summary: Summary | None = None, pending: bool = False,
        references: References | None = None,
    ) -> dict:
        """Row of preset, content read (pending: not read yet, shown without content)

        Args:
            references: primary tags of every preset (read once for all rows), read here if not set.
        """
        name = filename[:-len(FileExt.JSON)]
        if references is None:
            references = preset_references()
        lock = cfg.user.filelock.get(filename)
        changed = changed_text(modified)
        if pending:
            content = changed
        elif summary is None:
            content = f"{tr('Unreadable file')}  ·  {changed}"
        else:
            content = (f"{changed}  ·  {trm(f'{len(summary.widgets)} overlays')}"
                       f"  ·  {trm(f'{len(summary.modules)} modules')}")
        return {
            "key": filename,
            "name": name,
            "loaded": filename == cfg.filename.setting,
            "locked": lock is not None,
            "lockVersion": str(lock.get("version", "")) if isinstance(lock, dict) else "",
            "changedText": changed,
            "contentText": content,
            "modifiedTime": modified,
            "classes": [dict(entry) for entry in references.classes.get(name, ())],
            "tracks": list(references.tracks.get(name, ())),
            "hotkeys": list(references.hotkeys.get(name, ())),
            "overlays": len(summary.widgets) if summary else 0,
            "modules": len(summary.modules) if summary else 0,
            "unreadable": summary is None and not pending,
            "pending": pending,
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

    @Property(QObject, constant=True)
    def compare(self) -> QObject:
        return self._compare

    @Property(QObject, constant=True)
    def transfer(self) -> QObject:
        return self._transfer

    @Property(QObject, constant=True)
    def backups(self) -> QObject:
        return self._backups

    @Property(QObject, constant=True)
    def trash(self) -> QObject:
        return self._trash

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
        summary = self._summaries.get(row["key"])  # None while pending: shown once read
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
            # Classes this preset can be set for, by session ("" every session)
            "classChoices": {
                session: [name for name, data in cfg.user.classes.items()
                          if isinstance(data, dict) and data.get(key) != row["name"]]
                for session, key in (("", "preset"), *SESSION_PRESET_KEYS.items())
            },
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
        if mode == MODE_RESTORE:
            return self._backups.suggestName(filename)
        base = filename if mode == MODE_DUPLICATE and filename else f"{tr('New preset')}{FileExt.JSON}"
        return free_preset_name(cfg.path.settings, base)[:-len(FileExt.JSON)]

    @Slot(str, str, str, result=str)
    def applyName(self, mode: str, filename: str, name: str) -> str:
        """Create, duplicate, rename preset, or restore backup as preset: "" if done, else why not (translated)"""
        if mode not in (MODE_NEW, MODE_DUPLICATE, MODE_RENAME, MODE_RESTORE):
            return ""
        if mode == MODE_RESTORE:
            if not os.path.isfile(os.path.join(cfg.path.settings, filename)):
                return tr("Preset not found, it may have been renamed or deleted.")
        elif mode and not self._known(filename):
            return tr("Preset not found, it may have been renamed or deleted.")
        if mode == MODE_RENAME and filename in cfg.user.filelock:
            return tr("Unlock the preset to rename it.")
        entered_name = strip_filename_extension(name.strip(), FileExt.JSON)  # "Race.json" is "Race"
        if mode == MODE_RENAME and entered_name == filename[:-len(FileExt.JSON)]:
            return ""
        # Loaded preset being saved: its queued save is written first (waited off the UI thread), the name is
        # checked now (dialog told at once), file work & its errors (toast) follow (audit PERF-018)
        if mode in (MODE_DUPLICATE, MODE_RENAME) and cfg.is_loaded(filename) and cfg.is_saving:
            error = check_preset_name(name.strip(), mode, filename)
            if error:
                return error
            after_saving(self, partial(self._apply_name, mode, filename, name, entered_name, True))
            return ""
        return self._apply_name(mode, filename, name, entered_name, False)

    def _apply_name(self, mode: str, filename: str, name: str, entered_name: str, deferred: bool) -> str:
        """File work of applyName: "" if done, else why not (also shown in the toast when deferred)"""
        # File not being read meanwhile; the UI never waits long for a slow disk: asked to try again instead
        if not PRESET_FILES.acquire(timeout=PRESET_FILES_WAIT):
            error = tr(TRY_AGAIN)
        else:
            try:
                error = apply_preset_name(name.strip(), mode, filename)
            finally:
                PRESET_FILES.release()
        if error:
            if deferred:
                self.show_toast(error, error=True)
            return error
        self._selected = f"{entered_name}{FileExt.JSON}"
        self.refresh()
        if mode == MODE_RESTORE:
            self._backups.refresh()
        verb = {
            MODE_NEW: "Preset created", MODE_DUPLICATE: "Preset duplicated", MODE_RENAME: "Preset renamed",
            MODE_RESTORE: "Preset restored",
        }[mode]
        self.show_toast(trm(f"{verb}: <b>{entered_name}</b>"))
        return ""

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

    def ask(self, title: str, message: str, on_result: Callable[[bool], object]):
        """Confirmation (English message, translated by the host): over the page if the host can, answer by
        callback (the page keeps running meanwhile)"""
        ask = getattr(self._host, "ask", None)
        if callable(ask):
            ask(title, message, on_result)
        else:
            on_result(bool(self._host.confirm_operation(title, message)))

    @Slot(str)
    def toggleLock(self, filename: str):
        """Lock (changes never saved) or unlock preset, confirmed"""
        if not self._known(filename):
            return
        if filename in cfg.user.filelock:
            self.ask(tr("Unlock Preset"), f"Unlock <b>{html.escape(filename)}</b> preset?",
                     partial(self._set_lock, filename, False))
            return
        message = (f"Lock <b>{html.escape(filename)}</b> preset?<br><br>"
                   "Changes to locked preset will not be saved.")
        self.ask(tr("Lock Preset"), message, partial(self._set_lock, filename, True))

    def _set_lock(self, filename: str, lock: bool, confirmed: bool):
        """Lock or unlock once confirmed (state checked again: changed while asked)"""
        if not confirmed or (filename in cfg.user.filelock) == lock:
            return
        if lock:
            cfg.user.filelock[filename] = {"version": VERSION}
        else:
            cfg.user.filelock.pop(filename, None)
        cfg.save(config_type=ConfigType.FILELOCK)
        app_signal.refresh.emit(True)

    @Slot(str)
    def backup(self, filename: str):
        """Backup copy of preset, restored from Restore Backup page"""
        if not self._known(filename):
            return
        extension = set_backup_timestamp()
        if create_backup_file(filename, cfg.path.settings, extension, show_log=True):
            self.show_toast(trm(f"Backup saved as:<br><b>{filename}{extension}</b>"))
        else:
            self._host.warn(trm("Failed to create backup, please try again."))

    @Slot(str)
    def checkPreset(self, filename: str):
        """Unknown, invalid or out of range options of preset listed, then repaired if confirmed"""
        from ...userfile.preset_check import check_preset_file

        if not self._known(filename):
            return
        try:
            checked, changes = check_preset_file(filename, cfg.path.settings, cfg.default.setting)
        except (OSError, ValueError) as error:
            self._host.warn(trm(f"<b>{filename}</b> not checked: {error}"))
            return
        if not changes:
            self.show_toast(tr("No problem found"))
            return
        shown = "<br>".join(f"• {change}" for change in changes[:25])
        more = f"<br>… (+{len(changes) - 25})" if len(changes) > 25 else ""
        if filename in cfg.user.filelock:
            self._host.warn(trm(f"<b>{filename}</b>: {len(changes)} option(s) to repair (locked preset, not "
                                f"changed):<br><br>{shown}{more}"))
            return
        self.ask(tr("Check Preset"), trm(
            f"<b>{filename}</b>: {len(changes)} option(s) to repair (as loading it does):<br><br>{shown}{more}"
            "<br><br>Save repaired preset?"), partial(self._save_repaired, filename, checked))

    def _save_repaired(self, filename: str, checked: dict, confirmed: bool):
        """Repaired preset saved once confirmed"""
        from ...userfile.json_setting import save_and_verify_json_file

        if not confirmed:
            return
        if filename == cfg.filename.setting:  # loaded preset: repaired when loaded, saved as shown
            saved = cfg.save(0) is not False
        else:
            saved = save_and_verify_json_file(checked, filename, cfg.path.settings)
        if saved:
            self.show_toast(tr("Preset repaired"))
        else:
            self._host.warn(trm("Failed to save preset, please try again."))

    @Slot(str)
    def exportPackage(self, filename: str):
        if self._known(filename):
            self._host.export_package(filename)

    @Slot()
    def importPackage(self):
        self._host.import_package()

    @Slot(str)
    def compareWith(self, filename: str):
        """Compare panel: loaded preset with preset"""
        if self._known(filename):
            self.panelRequested.emit("compare", filename)

    @Slot(str)
    def openPage(self, name: str):
        """Transfer, restore backup or recently deleted panel, presets folder"""
        if name in ("compare", "transfer", "restore", "trash"):
            self.panelRequested.emit(name, "")
        else:
            self._host.open_page(name)

    # Notices
    def show_toast(self, text: str, error: bool = False, undo: bool = False):
        """Short notice in the toast of the page (host toast: TpDialogHost of the page), Undo offered for the
        last delete. toastShown tells it too (markup dropped)."""
        self.toastShown.emit(plain(text), error, undo)
        page_toast = getattr(self._host, "page_toast", None)
        if callable(page_toast):
            page_toast(text, error, undo)

    def update_trash_count(self, count: int):
        """Recently deleted presets read again by the trash panel"""
        if count != self._trash_count:
            self._trash_count = count
            self.stateChanged.emit()

    # Primary tags
    @Slot(str, str)
    def setPrimaryClass(self, filename: str, class_name: str):
        """Preset loaded automatically for car class (auto load)"""
        if self._known(filename) and class_name in cfg.user.classes:
            cfg.user.classes[class_name]["preset"] = filename[:-len(FileExt.JSON)]
            cfg.save(config_type=ConfigType.CLASSES)
            self.refresh()

    @Slot(str, str, str)
    def setPrimaryClassSession(self, filename: str, class_name: str, session: str):
        """Preset loaded automatically for car class in session ("practice", "qualify", "race"), before the
        track & class presets ("" session: class preset of every session)"""
        key = SESSION_PRESET_KEYS.get(session, "preset") if session else "preset"
        if (session and session not in SESSION_PRESET_KEYS) or not self._known(filename):
            return
        data = cfg.user.classes.get(class_name)
        if isinstance(data, dict):
            data[key] = filename[:-len(FileExt.JSON)]
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

    @Slot(str, str)
    def removePrimaryClassSession(self, class_name: str, session: str):
        """Class preset of session removed ("" session: class preset of every session)"""
        key = SESSION_PRESET_KEYS.get(session, "") if session else "preset"
        data = cfg.user.classes.get(class_name)
        if key and isinstance(data, dict) and data.get(key):
            data[key] = ""
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
            keys = CLASS_PRESET_KEYS if config_type == ConfigType.CLASSES else ("preset",)
            changed = False
            for data in entries.values():
                if not isinstance(data, dict):
                    continue
                for key in keys:
                    if data.get(key) == name:
                        data[key] = ""
                        changed = True
            if changed:
                cfg.save(config_type=config_type)
        self.refresh()
