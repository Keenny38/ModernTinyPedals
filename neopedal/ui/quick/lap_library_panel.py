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
Imported laps library of lap viewer page (QML backend.library, LapLibraryPanel.qml): laps imported from MoTeC
logs & other drivers' folders (foreign laps), grouped by log: search, add to viewer, import, rename & move to trash

Deleted laps go to the lap viewer trash: same undo (Ctrl+Z, page toast) & Recently Deleted list as recorded laps.
"""

from __future__ import annotations

import logging
import os
import weakref
from collections.abc import Callable
from typing import Any, Protocol

import shiboken6
from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtWidgets import QFileDialog, QWidget

from ...i18n import tr, trm
from ...userfile.lap_cache import indexed_infos, info_index_path, read_infos, save_info_index
from ...userfile.lap_library import (
    Deletion,
    delete_laps,
    group_name_error,
    import_folder,
    is_foreign,
    list_imported,
    rename_group,
)
from ...userfile.telemetry_lap import IMPORT_FOLDER, LapFile
from ..lap_viewer import format_laptime, lap_label
from .background import BackgroundJobs
from .formatting import date_text, file_stamp
from .lap_base import PagePart, weak_host
from .models import FoldedListModel

logger = logging.getLogger(__name__)

LibraryLap = tuple[LapFile, dict, float]  # lap file, lap info, time imported (file time, 0 if unknown)
LIBRARY_ROLES = ("key", "kind", "group", "path", "title", "time", "best", "track", "vehicle", "driver", "imported",
                 "count", "open", "selected")
GROUP_PREFIX = "group:"  # row id of a log group (lap rows: lap path)

_file_jobs: BackgroundJobs | None = None


def file_jobs() -> BackgroundJobs:
    """App-lifetime jobs moving library files (rename, delete): not owned by a page, so a write still running when
    the lap viewer closes ends cleanly (created on the UI thread, first use)"""
    global _file_jobs
    if _file_jobs is None or not shiboken6.isValid(_file_jobs):
        _file_jobs = BackgroundJobs(None, "Lap library")
    return _file_jobs


def imported_time(path: str) -> float:
    """Time lap was imported (file time), 0 if unknown"""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def read_library(filepath: str) -> list[tuple[str, list[LibraryLap]]]:
    """Imported log groups with infos & import time of their laps (thread job): infos from lap infos index of each
    group (like lap viewer track folders), new lap files read together, index saved again if changed"""
    groups = []
    for name, laps in list_imported(filepath):
        index_path = info_index_path(filepath, os.path.join(IMPORT_FOLDER, name))
        stamps, saved, known, missing = indexed_infos(os.path.join(import_folder(filepath), name), index_path, laps)
        for item in read_infos([lap.path for lap in missing]):
            if item is not None:
                known[os.path.basename(item[0])] = item[2]
        rows: list[LibraryLap] = []
        index = {}
        for lap in laps:
            stamp = stamps.get(lap.filename)
            info = known.get(lap.filename, {})
            if stamp is not None and lap.filename in known:
                index[lap.filename] = [stamp[0], stamp[1], info]
            rows.append((lap, info, stamp[2] if stamp is not None else imported_time(lap.path)))
        if missing or index.keys() != saved.keys():
            save_info_index(index_path, index)
        groups.append((name, rows))
    return groups


def group_rows(name: str, laps: list[LibraryLap]) -> tuple[dict, list[dict]]:
    """Group header row (best time, track, vehicle & driver of its first lap with info, newest import) & lap rows"""
    best = min((lap.lap_time for lap, _, _ in laps if lap.lap_time > 0), default=0.0)
    first_info = next((info for _, info, _ in laps if info), {})
    newest = max((imported for _, _, imported in laps), default=0.0)
    driver = str(first_info.get("driver", ""))
    if not driver and laps and is_foreign(laps[0][0].path):  # laps of another driver's folder
        driver = tr("foreign laps")
    header = {
        "key": GROUP_PREFIX + name, "kind": "group", "group": name, "path": "", "title": name,
        "time": format_laptime(best), "best": False, "track": str(first_info.get("track", "")),
        "vehicle": str(first_info.get("vehicle", "")), "driver": driver,
        "imported": date_text(newest), "count": len(laps), "open": False, "selected": False,
    }
    rows = [{
        "key": lap.path, "kind": "lap", "group": name, "path": lap.path, "title": lap_label(lap.filename),
        "time": format_laptime(lap.lap_time), "best": lap.lap_time > 0 and lap.lap_time == best,
        "track": str(info.get("track", "")), "vehicle": str(info.get("vehicle", "")),
        "driver": str(info.get("driver", "")), "imported": date_text(imported),
        "count": 0, "open": True, "selected": False,
    } for lap, info, imported in laps]
    return header, rows


def row_text(row: dict, with_time: bool = True) -> str:
    """Searched text of a row: name, time (laps), track, vehicle, driver, import date"""
    keys = ("title", "time", "track", "vehicle", "driver", "imported") if with_time else (
        "title", "track", "vehicle", "driver", "imported")
    return " ".join(str(row[key]) for key in keys).lower()


class LibraryHost(Protocol):
    """What the library part uses of the lap viewer page"""

    folder: str
    widget: QWidget

    def run_job(self, name: str, work: Callable[[], Any], done: Callable[[Any], None]): ...
    def add_from_library(self, paths: list[str]): ...
    def library_changed(self, moved: dict[str, str]): ...
    def trash_imported(self, deletion: Deletion): ...
    def import_motec(self, filenames: list[str], background: bool = True,
                     done: Callable[[list[tuple[str, list[str], str]]], None] | None = None): ...


class ImportedLaps(PagePart):
    """Imported laps library of lap viewer page (QML backend.library)

    Logs & laps listed in background when the panel opens (lap infos from each log's index), filtered by every
    searched word, selection & expanded logs kept when listed again. Rename & delete move files on a worker thread,
    one write at a time; the page is told of moved laps (shown imported laps follow them).
    """

    changed = Signal()  # loading, writing, importing, problem, empty & no match states
    selectionChanged = Signal()
    openRequested = Signal()  # Import menu "Imported Laps...", page openLibrary: panel opened
    searchReset = Signal()  # logs imported: search field cleared (new logs shown)

    def __init__(self, page: LibraryHost, parent: QObject | None = None):
        super().__init__(parent)
        self._page = weak_host(page)
        self._model = FoldedListModel(LIBRARY_ROLES, "key", self)
        self._groups: list[tuple[dict, list[dict]]] = []  # every log: header row, lap rows (search not applied)
        self._expanded: set[str] = set()  # logs shown expanded
        self._expand: set[str] = set()  # logs to show expanded once listed (imported, restored)
        self._selected: set[str] = set()  # row ids (log group or lap path)
        self._selected_count = 0  # laps selected (see selection_changed)
        self._rename_target = ""  # log renamed by Rename
        self._anchor = ""  # row of last plain or Ctrl click (Shift+click selects up to it)
        self._search = ""
        self._generation = 0  # latest listing asked (an older one finishing later is ignored)
        self._listing = False
        self._listed = False  # listed once (empty state shown only then)
        self._writing = False  # files renamed or deleted in background (actions changing files disabled)
        self._importing = False
        self._problem = ""  # last error (plain text), shown in the panel until dismissed
        self._shown = False  # panel open: listed again after a change of its files

    def release(self):
        self._groups = []
        self._model.set_rows([], lambda row: True)
        self._shown = False

    # State read by QML
    @Property(QObject, constant=True)
    def model(self) -> FoldedListModel:
        """Rows: log groups & laps of expanded groups matching search"""
        return self._model

    @Property(bool, notify=changed)
    def loading(self) -> bool:
        return self._listing

    @Property(bool, notify=changed)
    def writing(self) -> bool:
        return self._writing

    @Property(bool, notify=changed)
    def importing(self) -> bool:
        return self._importing

    @Property(bool, notify=changed)
    def empty(self) -> bool:
        """No imported lap (once listed)"""
        return self._listed and not self._groups

    @Property(bool, notify=changed)
    def noMatch(self) -> bool:
        """Imported laps listed but none matching search"""
        return bool(self._groups) and not self._model.all_rows

    @Property(str, notify=changed)
    def problem(self) -> str:
        return self._problem

    @Property(int, notify=selectionChanged)
    def selectedCount(self) -> int:
        """Laps selected (selected logs: every lap of them)"""
        return self._selected_count

    @Property(str, notify=selectionChanged)
    def renameTarget(self) -> str:
        """Log renamed by Rename: log of first selected row (list order), empty if none"""
        return self._rename_target

    def selection_changed(self):
        """Selection or listed logs changed: selected lap count & Rename target worked out, selectionChanged sent"""
        selected = self._selected
        self._selected_count = len(self.lap_paths(selected))
        self._rename_target = next((header["group"] for header, laps in self._groups
                                    if any(row["key"] in selected for row in (header, *laps))), "")
        self.selectionChanged.emit()

    def is_refreshing(self) -> bool:
        """Imported laps being listed, or their files moved, in background"""
        return self._listing or self._writing

    def set_state(self, **values):
        """Busy & problem states changed: one notification"""
        changed = False
        for name, value in values.items():
            if getattr(self, f"_{name}") != value:
                setattr(self, f"_{name}", value)
                changed = True
        if changed:
            self.changed.emit()

    # Listing
    @Slot()
    def open(self):
        """Panel opened: logs listed again (files may have changed since)"""
        self._shown = True
        self.refresh()

    @Slot()
    def closed(self):
        self._shown = False

    def refresh(self, expand: set[str] | None = None):
        """List imported logs & their laps in background (rows filled once read), expanded logs kept (and expand
        logs)"""
        self._expand |= expand or set()
        self._generation += 1
        generation = self._generation
        folder = self._page.folder
        self.set_state(listing=True)

        def done(groups):
            if generation != self._generation:
                return  # listed again meanwhile
            self.fill(groups if isinstance(groups, list) else [])

        self._page.run_job("lap library", lambda: read_library(folder), done)

    def fill(self, groups: list[tuple[str, list[LibraryLap]]]):
        """Imported logs listed (single log expanded), rows of selected logs & laps still listed kept selected"""
        self._groups = [group_rows(name, laps) for name, laps in groups]
        names = {header["group"] for header, _ in self._groups}
        self._expanded = (self._expanded | self._expand) & names
        if len(self._groups) == 1:
            self._expanded |= names
        self._expand = set()
        ids = {row["key"] for header, laps in self._groups for row in (header, *laps)}
        selected = self._selected & ids
        self._listed = True
        self._listing = False
        self.show_rows()
        if selected != self._selected:
            self._selected = selected
        self.selection_changed()
        self.changed.emit()

    def show_rows(self):
        """Rows matching every searched word: a log matching (name, track, vehicle, driver, date; not its best time)
        shows all its laps, else laps matching with the words of their log; logs with matches expanded while
        searching (a click collapses them again), lap rows of collapsed logs left out of the model"""
        words = self._search.lower().split()
        rows: list[dict] = []
        for header, laps in self._groups:
            group_text = row_text(header, with_time=False)
            group_match = all(word in group_text for word in words)
            shown = [lap for lap in laps if group_match or all(word in f"{row_text(lap)} {group_text}" for word in words)]
            if not shown:
                continue
            if words:
                self._expanded.add(header["group"])
            rows.append(dict(header, open=header["group"] in self._expanded, selected=header["key"] in self._selected))
            rows.extend(dict(lap, selected=lap["key"] in self._selected) for lap in shown)
        self.set_rows(rows)

    def set_rows(self, rows: list[dict]):
        """Every matching row, lap rows of collapsed logs left out of the model (rows kept in place)"""
        opened = self._expanded
        self._model.set_rows(rows, lambda row: row["kind"] == "group" or row["group"] in opened)

    @Slot(str)
    def setSearch(self, text: str):
        """Search text: every word in log or lap details"""
        text = text.strip()
        if text != self._search:
            self._search = text
            self.show_rows()
            self.changed.emit()  # no match state

    @Slot(str)
    def toggleGroup(self, name: str):
        """Log expanded or collapsed: its lap rows added to or removed from the model"""
        if name in self._expanded:
            self._expanded.discard(name)
        else:
            self._expanded.add(name)
        rows = self._model.all_rows
        for row in rows:
            if row["key"] == GROUP_PREFIX + name:
                row["open"] = name in self._expanded
        self.set_rows(rows)  # header row values synced too (chevron turned)

    # Selection
    @Slot(str, str)
    def select(self, row_id: str, mode: str = "set"):
        """Row selected: "set" (only it), "toggle" (Ctrl+click), "range" (Shift+click: rows listed from anchor)"""
        if mode == "toggle":
            self._selected ^= {row_id}
            self._anchor = row_id
        elif mode == "range" and self._anchor:
            listed = [row["key"] for row in self._model.rows]
            if self._anchor in listed and row_id in listed:
                low, high = sorted((listed.index(self._anchor), listed.index(row_id)))
                self._selected = set(listed[low:high + 1])
            else:
                self._selected = {row_id}
        else:
            self._selected = {row_id} if row_id else set()
            self._anchor = row_id
        self.selection_rows()

    @Slot()
    def selectAll(self):
        """Every listed row selected (logs: all their laps)"""
        self._selected = {row["key"] for row in self._model.all_rows}
        self.selection_rows()

    def selection_rows(self):
        selected = self._selected
        self._model.update_rows(lambda row: {"selected": row["key"] in selected})
        self.selection_changed()

    def lap_paths(self, ids: set[str] | list[str]) -> list[str]:
        """Lap paths of rows (list order): laps, every lap of logs"""
        paths: list[str] = []
        for header, laps in self._groups:
            whole = header["key"] in ids
            paths.extend(lap["path"] for lap in laps if whole or lap["key"] in ids)
        return list(dict.fromkeys(paths))

    # Actions
    @Slot()
    def addSelected(self):
        """Selected laps shown in viewer, fastest as reference"""
        self.add_rows(list(self._selected))

    @Slot(str)
    def addRow(self, row_id: str):
        """Lap or every lap of log shown in viewer (double-click)"""
        self.add_rows([row_id])

    def add_rows(self, ids: list[str]):
        paths = self.lap_paths(ids)
        if paths:
            self._page.add_from_library(paths)

    @Slot()
    def clearProblem(self):
        self.set_state(problem="")

    @Slot(str, str, result=str)
    def nameError(self, old: str, new: str) -> str:
        """Why log can not take new name (checked while typed), empty if it can"""
        new = new.strip()
        if new == old:
            return ""
        error = group_name_error(self._page.folder, old, new)
        if error == "exists":
            return tr("Name already used by another imported log.")
        if error:
            return tr('Invalid name, characters \\ / : * ? " < > | not allowed.')
        return ""

    def run_write(self, name: str, work: Callable[[], Any], done: Callable[[ImportedLaps | None, Any], None],
                  failed: Callable[[ImportedLaps | None, BaseException], None]) -> bool:
        """Move files on a worker thread (a lap file still open is retried for up to a second), one write at a time

        done(library, result) or failed(library, error) called on the UI thread (library None if the page closed
        meanwhile). Returns False if a write still runs (nothing started).
        """
        if self._writing:
            return False
        self.set_state(writing=True, problem="")
        library_ref = weakref.ref(self)

        def finished() -> ImportedLaps | None:
            library = library_ref()
            if library is None or not shiboken6.isValid(library):
                return None
            library.set_state(writing=False)
            return library

        file_jobs().run(name, work, lambda result: done(finished(), result), lambda error: failed(finished(), error))
        return True

    @Slot(str, str, result=bool)
    def rename(self, old: str, new: str) -> bool:
        """Rename log (in background, see run_write), page told of moved laps; False if refused (name, write running)"""
        new = new.strip()
        if not old or self.nameError(old, new):
            return False
        if new == old:
            return True
        folder = self._page.folder

        def renamed(library: ImportedLaps | None, moved: dict[str, str]):
            if library is None:
                return
            library._selected = {GROUP_PREFIX + new if row == GROUP_PREFIX + old else moved.get(row, row)
                                 for row in library._selected}
            library._expanded = {new if name == old else name for name in library._expanded}
            library.refresh()
            library._page.library_changed(moved)

        def rename_failed(library: ImportedLaps | None, error: BaseException):
            logger.error("LAP LIBRARY: unable to rename %s: %s", old, error,
                         exc_info=None if isinstance(error, OSError) else error)
            if library is not None:
                library.set_state(problem=trm(f"Unable to rename: {error}"))
                library.refresh()

        return self.run_write("rename", lambda: rename_group(folder, old, new), renamed, rename_failed)

    @Slot()
    def deleteSelected(self):
        """Move selected laps to lap viewer trash (in background, see run_write): page undo & toast, laps that can
        not be deleted (file open elsewhere) told"""
        from .lap_actions import TRASH_FOLDER

        paths = self.lap_paths(self._selected)
        if not paths or self._writing:
            return
        folder = self._page.folder
        trash = os.path.join(folder, TRASH_FOLDER, file_stamp())

        def deleted(library: ImportedLaps | None, deletion: Deletion):
            if library is None:
                return
            library._page.trash_imported(deletion)
            if deletion.failed:
                library.set_state(problem="\n".join(
                    trm(f"Unable to delete lap: {os.path.basename(path)} ({reason})")
                    for path, reason in deletion.failed.items()))
            library.refresh()

        def delete_failed(library: ImportedLaps | None, error: BaseException):
            logger.error("LAP LIBRARY: unable to delete laps: %s", error, exc_info=error)
            if library is not None:
                library.set_state(problem=trm(f"Unable to delete lap: {os.path.basename(paths[0])} ({error})"))
                library.refresh()

        self.run_write("delete", lambda: delete_laps(folder, paths, trash), deleted, delete_failed)

    def restored(self, paths: list[str]):
        """Imported laps restored from trash (page undo, Recently Deleted): listed again, their logs expanded"""
        root = os.path.normcase(os.path.abspath(import_folder(self._page.folder)))
        groups = {os.path.basename(os.path.dirname(path)) for path in paths
                  if os.path.normcase(os.path.dirname(os.path.dirname(os.path.abspath(path)))) == root}
        if groups and self._shown:
            self.refresh(groups)
        elif groups:
            self._expand |= groups

    @Slot()
    def importLogs(self):
        """Import MoTeC logs into library in background (lap viewer page jobs), new logs shown expanded once done"""
        if self._importing:
            return
        filenames, _ = QFileDialog.getOpenFileNames(self._page.widget, tr("Import MoTeC…"), "", "MoTeC i2 (*.ld)")
        if filenames:
            self.import_files(filenames)

    def import_files(self, filenames: list[str], background: bool = True):
        self.set_state(importing=True, problem="")
        self._page.import_motec(filenames, background, done=self.imported)

    def imported(self, results: list[tuple[str, list[str], str]]):
        """Every log imported (log, lap paths, error): imported logs shown expanded, problems told"""
        if not shiboken6.isValid(self):  # page closed meanwhile: laps are in library
            return
        groups: set[str] = set()
        problems: list[str] = []
        for filename, paths, error in results:
            name = os.path.basename(filename)
            if error:
                problems.append(trm(f"Unable to import <b>{name}</b>: {error}").replace("<b>", "").replace("</b>", ""))
            elif not paths:
                problems.append(trm(f"No complete lap in: {name}"))
            groups.update(os.path.basename(os.path.dirname(path)) for path in paths)
        self.set_state(importing=False, problem="\n".join(problems))
        self._search = ""
        self.searchReset.emit()
        self.refresh(groups)
