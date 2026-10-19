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
Imported laps library: import, search, add to lap viewer, rename & delete laps imported from MoTeC logs & other
drivers' folders (foreign laps)
"""

from __future__ import annotations

import html
import logging
import os
import weakref
from collections.abc import Callable
from typing import Any

import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ..i18n import tr, trm
from ..userfile.lap_cache import indexed_infos, info_index_path, read_infos, save_info_index
from ..userfile.lap_library import (
    Deletion,
    delete_laps,
    group_name_error,
    import_folder,
    is_foreign,
    list_imported,
    rename_group,
    restore_laps,
)
from ..userfile.motec_ld import import_ld_job
from ..userfile.telemetry_lap import IMPORT_FOLDER, LapFile
from ._common import BaseDialog, TextInputDialog, UIScaler
from .quick.background import BackgroundJobs, weak_callback
from .quick.formatting import file_stamp, iso_minutes
from .toast import show_toast

logger = logging.getLogger(__name__)

LibraryLap = tuple[LapFile, dict, float]  # lap file, lap info, time imported (file time, 0 if unknown)

_file_jobs: BackgroundJobs | None = None


def file_jobs() -> BackgroundJobs:
    """App-lifetime jobs moving library files (rename, delete, undo): not owned by a library, so a library closed
    meanwhile still has its lap viewer told of moved laps (created on the UI thread, first use)"""
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


class LapLibrary(BaseDialog):
    """Laps imported from MoTeC logs, grouped by log

    Args:
        filepath: telemetry folder.
        on_add: called with lap paths to show in lap viewer.
        on_changed: called with moved lap paths after rename or delete (old path: new path, "" if deleted).
        import_motec: imports logs as lap viewer page jobs, then calls done with (log, lap paths, error) of each
            (default: import_motec of on_add page). Page jobs finish when page closes, app exit waits for them.
    """

    EMBED_FROM_PAGE = True
    COL_NAME, COL_TIME, COL_TRACK, COL_VEHICLE, COL_DRIVER, COL_DATE = range(6)

    def __init__(
        self, parent, filepath: str,
        on_add: Callable[[list[str]], None], on_changed: Callable[[dict[str, str]], None],
        import_motec: Callable[..., None] | None = None,
    ):
        super().__init__(parent)
        self.set_utility_title(tr("Imported Laps"))
        self.filepath = filepath
        self._on_add = on_add
        self._on_changed = on_changed
        page = getattr(on_add, "__self__", None)  # lap viewer page, on_add is one of its methods
        self._import_motec = import_motec or getattr(page, "import_motec", None)
        self._importing = False
        self._writing = False  # files renamed, deleted or restored in background (buttons changing files disabled)
        self._undo: list[tuple[str, str]] = []  # deleted files: path, path in trash
        self._jobs = BackgroundJobs(self, "Lap library")
        self._expand: set[str] = set()  # groups shown expanded once listed (refresh asked meanwhile)

        self.edit_filter = QLineEdit(self)
        self.edit_filter.setPlaceholderText(tr("Search track, vehicle, driver or log..."))
        self.edit_filter.setClearButtonEnabled(True)
        self.edit_filter.textChanged.connect(self.apply_filter)
        self.button_import = QPushButton(tr("Import MoTeC..."))
        self.button_import.setToolTip(tr("Import complete laps of MoTeC logs (.ld), also by dropping them on the app"))
        self.button_import.clicked.connect(self.import_logs)
        layout_top = QHBoxLayout()
        layout_top.addWidget(self.edit_filter, stretch=1)
        layout_top.addWidget(self.button_import)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels([tr("Name"), tr("Time"), tr("Track"), tr("Vehicle"), tr("Driver"), tr("Imported")])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.itemDoubleClicked.connect(lambda item, _: self.add_to_viewer([item]))
        self.label_empty = QLabel(tr("No imported lap. Import a MoTeC log (.ld) with Import MoTeC..., or drop it on the app."), self)
        self.label_empty.setWordWrap(True)
        self.label_empty.setVisible(False)  # until imported laps are listed

        button_add = QPushButton(tr("Add to Viewer"))
        button_add.setToolTip(tr("Show selected laps in lap viewer (double-click also)"))
        button_add.clicked.connect(lambda: self.add_to_viewer(self.tree.selectedItems()))
        self.button_rename = QPushButton(tr("Rename..."))
        self.button_rename.setToolTip(tr("Rename selected imported log"))
        self.button_rename.clicked.connect(self.rename)
        self.button_delete = QPushButton(tr("Delete"))
        self.button_delete.setToolTip(tr("Move selected laps to trash"))
        self.button_delete.clicked.connect(self.delete)
        self.button_undo = QPushButton(tr("Undo Delete"))
        self.button_undo.clicked.connect(self.undo_delete)
        self.button_undo.setVisible(False)
        button_close = QPushButton(tr("Close"))
        button_close.clicked.connect(self.close)
        layout_button = QHBoxLayout()
        layout_button.addWidget(button_add)
        layout_button.addWidget(self.button_rename)
        layout_button.addWidget(self.button_delete)
        layout_button.addWidget(self.button_undo)
        layout_button.addStretch(1)
        layout_button.addWidget(button_close)

        layout_main = QVBoxLayout(self)
        layout_main.addLayout(layout_top)
        layout_main.addWidget(self.label_empty)
        layout_main.addWidget(self.tree, stretch=1)
        layout_main.addLayout(layout_button)
        layout_main.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        self.resize(UIScaler.size(46), UIScaler.size(30))
        self.refresh()

    def refresh(self, expand: set[str] | None = None):
        """List imported logs & their laps (read in background, tree filled once read), expanded state kept (and
        expand groups)"""
        self._expand |= expand or set()
        filepath = self.filepath
        self._jobs.run("refresh", lambda: read_library(filepath), self.fill_tree, key="refresh")

    def is_refreshing(self) -> bool:
        """Imported laps being listed, or their files moved, in background"""
        return self._writing or self._jobs.is_busy("refresh")

    def set_writing(self, writing: bool):
        """Files being moved in background: buttons changing files disabled meanwhile"""
        self._writing = writing
        for button in (self.button_rename, self.button_delete, self.button_undo):
            button.setEnabled(not writing)

    def run_write(self, name: str, work: Callable[[], Any], done: Callable[[LapLibrary | None, Any], None],
                  failed: Callable[[LapLibrary | None, BaseException], None]) -> bool:
        """Move files on a worker thread (a lap file still open is retried for up to a second), one write at a time

        done(library, result) or failed(library, error) called on the UI thread even once library closed (library
        None then: lap viewer still told of moved laps). Returns False if a write still runs (nothing started).
        """
        if self._writing:
            return False
        self.set_writing(True)
        library_ref = weakref.ref(self)

        def finished() -> LapLibrary | None:
            """Library (buttons enabled again), None if closed meanwhile"""
            library = library_ref()
            if library is None or not shiboken6.isValid(library):
                return None
            library.set_writing(False)
            return library

        file_jobs().run(name, work, lambda result: done(finished(), result), lambda error: failed(finished(), error))
        return True

    def fill_tree(self, groups: list[tuple[str, list[LibraryLap]]]):
        """Imported logs & their laps listed (lap infos read in background), expanded state kept"""
        from .lap_viewer import format_laptime, lap_label

        expanded = {self.group_of(item) for item in self.top_items() if item.isExpanded()} | self._expand
        self._expand = set()
        # Items selected meanwhile selected again (group name or lap path)
        selected = {item.data(self.COL_NAME, Qt.ItemDataRole.UserRole) for item in self.tree.selectedItems()}
        self.tree.clear()
        for name, laps in groups:
            group = QTreeWidgetItem(self.tree)
            group.setText(self.COL_NAME, name)
            group.setData(self.COL_NAME, Qt.ItemDataRole.UserRole, name)
            font = QFont(group.font(self.COL_NAME))
            font.setBold(True)
            group.setFont(self.COL_NAME, font)
            best = min((lap.lap_time for lap, _, _ in laps if lap.lap_time > 0), default=0.0)
            group.setText(self.COL_TIME, format_laptime(best))
            first_info: dict = {}
            newest = 0.0
            for lap, info, imported in laps:
                first_info = first_info or info
                newest = max(newest, imported)
                item = QTreeWidgetItem(group)
                item.setText(self.COL_DATE, iso_minutes(imported) if imported > 0 else "")
                item.setText(self.COL_NAME, lap_label(lap.filename))
                item.setData(self.COL_NAME, Qt.ItemDataRole.UserRole, lap.path)
                item.setText(self.COL_TIME, format_laptime(lap.lap_time))
                if lap.lap_time > 0 and lap.lap_time == best:
                    item.setFont(self.COL_TIME, font)
                item.setSelected(lap.path in selected)
                for column, key in ((self.COL_TRACK, "track"), (self.COL_VEHICLE, "vehicle"),
                                    (self.COL_DRIVER, "driver")):
                    item.setText(column, str(info.get(key, "")))
            for column, key in ((self.COL_TRACK, "track"), (self.COL_VEHICLE, "vehicle"), (self.COL_DRIVER, "driver")):
                group.setText(column, str(first_info.get(key, "")))
            if not first_info.get("driver") and is_foreign(laps[0][0].path):  # laps of another driver's folder
                group.setText(self.COL_DRIVER, tr("foreign laps"))
            group.setText(self.COL_DATE, iso_minutes(newest) if newest > 0 else "")
            group.setExpanded(name in expanded or len(groups) == 1)
            group.setSelected(name in selected)
        for column in range(self.tree.columnCount()):
            self.tree.resizeColumnToContents(column)
        self.label_empty.setVisible(not groups)
        self.apply_filter(self.edit_filter.text())

    def apply_filter(self, text: str):
        """Show logs & laps matching every searched word (name, time, track, vehicle, driver, date)"""
        words = text.lower().split()
        # Log described by its columns but best time (a searched time selects laps)
        group_columns = [column for column in range(self.tree.columnCount()) if column != self.COL_TIME]

        def matches(item: QTreeWidgetItem, extra: str = "") -> bool:
            content = " ".join(item.text(column) for column in range(self.tree.columnCount())).lower() + extra
            return all(word in content for word in words)

        for group in self.top_items():
            group_text = " ".join(group.text(column) for column in group_columns).lower()
            group_match = all(word in group_text for word in words)
            any_lap = False
            for index in range(group.childCount()):
                lap = group.child(index)
                if lap is None:
                    continue
                visible = group_match or matches(lap, " " + group_text)
                lap.setHidden(not visible)
                any_lap = any_lap or visible
            group.setHidden(not any_lap)
            if words and any_lap:
                group.setExpanded(True)

    def import_logs(self):
        """Import MoTeC logs into library in background (lap viewer page jobs), new logs shown expanded once done"""
        if self._importing:
            return
        filenames, _ = QFileDialog.getOpenFileNames(self, tr("Import MoTeC..."), "", "MoTeC i2 (*.ld)")
        if not filenames:
            return
        self._importing = True
        self.button_import.setEnabled(False)
        self.button_import.setText(tr("Importing..."))
        if self._import_motec is not None:
            self._import_motec(filenames, done=self.imported)
            return
        folder = import_folder(self.filepath)  # no lap viewer page: imported now
        self.imported([(filename, *import_ld_job(filename, folder)) for filename in filenames])

    def imported(self, results: list[tuple[str, list[str], str]]):
        """Every log imported (log, lap paths, error): imported logs shown expanded, problems told"""
        if not shiboken6.isValid(self):  # library closed meanwhile: laps are in library
            return
        groups: set[str] = set()
        problems: list[str] = []
        for filename, paths, error in results:
            name = html.escape(os.path.basename(filename))
            if error:
                problems.append(trm(f"Unable to import <b>{name}</b>: {html.escape(error)}"))
            elif not paths:
                problems.append(trm(f"No complete lap in: {name}"))
            groups.update(os.path.basename(os.path.dirname(path)) for path in paths)
        self._importing = False
        self.button_import.setEnabled(True)
        self.button_import.setText(tr("Import MoTeC..."))
        self.edit_filter.clear()
        self.refresh(groups)
        if problems:
            QMessageBox.warning(self, tr("Error"), "<br>".join(problems))

    def top_items(self) -> list[QTreeWidgetItem]:
        items = (self.tree.topLevelItem(index) for index in range(self.tree.topLevelItemCount()))
        return [item for item in items if item is not None]

    @staticmethod
    def group_of(item: QTreeWidgetItem) -> str:
        """Log group name of group or lap item"""
        group = item.parent() or item
        return group.data(0, Qt.ItemDataRole.UserRole)

    @staticmethod
    def lap_paths(items: list[QTreeWidgetItem]) -> list[str]:
        """Lap paths of selected laps, every lap of selected groups"""
        paths: list[str] = []
        for item in items:
            laps = [item] if item.parent() is not None else [item.child(index) for index in range(item.childCount())]
            for lap in filter(None, laps):
                path = lap.data(0, Qt.ItemDataRole.UserRole)
                if path not in paths:
                    paths.append(path)
        return paths

    def add_to_viewer(self, items: list[QTreeWidgetItem]):
        paths = self.lap_paths(items)
        if paths:
            self._on_add(paths)

    def rename(self):
        """Rename log of selected item (in background, see run_write), lap viewer told of moved laps"""
        items = self.tree.selectedItems()
        if not items or self._writing:
            return
        old = self.group_of(items[0])
        filepath = self.filepath
        changed = weak_callback(self._on_changed)  # never keeps lap viewer page alive

        def renamed(library: LapLibrary | None, moved: dict[str, str]):
            if library is not None:
                library.refresh()
            on_changed = changed()
            if on_changed is not None:
                on_changed(moved)

        def rename_failed(library: LapLibrary | None, error: BaseException):
            logger.error("LAP LIBRARY: unable to rename %s: %s", old, error,
                         exc_info=None if isinstance(error, OSError) else error)
            if library is not None:
                library.refresh()
                QMessageBox.warning(library, tr("Error"), trm(f"Unable to rename: {error}"))

        def renaming(new: str) -> bool:
            new = new.strip()
            if new == old:
                return True
            error = group_name_error(filepath, old, new)
            if error:
                message = (
                    "Name already used by another imported log." if error == "exists"
                    else 'Invalid name, characters \\ / : * ? " < > | not allowed.')
                QMessageBox.warning(self, tr("Error"), tr(message))
                return False
            # Input kept open while another write runs (buttons disabled meanwhile)
            return self.run_write("rename", lambda: rename_group(filepath, old, new), renamed, rename_failed)

        TextInputDialog(self, tr("Rename"), tr("Imported log name:"), renaming, old).show()

    def delete(self):
        """Move selected laps to trash (lap viewer trash, kept 30 days, in background, see run_write), undo offered,
        laps that can not be deleted (file open elsewhere) told"""
        from .quick.lap_backend import TRASH_FOLDER

        if self._writing:
            return
        paths = self.lap_paths(self.tree.selectedItems())
        if not paths:
            return
        if not self.confirm_operation("Delete", f"Move {len(paths)} laps to trash?"):
            return
        filepath = self.filepath
        trash = os.path.join(filepath, TRASH_FOLDER, file_stamp())
        changed = weak_callback(self._on_changed)  # never keeps lap viewer page alive

        def deleted(library: LapLibrary | None, deletion: Deletion):
            if library is not None:
                if deletion.trashed:
                    library._undo = deletion.trashed
                    library.button_undo.setVisible(True)
                library.refresh()
            on_changed = changed()
            if deletion.deleted and on_changed is not None:
                on_changed(dict.fromkeys(deletion.deleted, ""))
            if library is not None:
                library.tell_deleted(deletion)

        def delete_failed(library: LapLibrary | None, error: BaseException):
            logger.error("LAP LIBRARY: unable to delete laps: %s", error, exc_info=error)
            if library is not None:
                library.refresh()
                QMessageBox.warning(library, tr("Error"), trm(
                    f"Unable to delete lap: {html.escape(os.path.basename(paths[0]))} ({html.escape(str(error))})"))

        self.run_write("delete", lambda: delete_laps(filepath, paths, trash), deleted, delete_failed)

    def tell_deleted(self, deletion: Deletion):
        """Laps that could not be deleted told, else laps moved to trash (with undo)"""
        if deletion.failed:
            QMessageBox.warning(self, tr("Error"), "<br>".join(
                trm(f"Unable to delete lap: {html.escape(os.path.basename(path))} ({html.escape(reason)})")
                for path, reason in deletion.failed.items()))
        elif deletion.trashed:
            count = len({path for path, _ in deletion.trashed} & set(deletion.deleted))  # laps, not group marks
            show_toast(self, trm(f"{count} lap(s) moved to trash"), action_text=tr("Undo"), action=self.undo_delete)

    def undo_delete(self):
        """Restore laps deleted last from trash (in background, see run_write), restored groups shown expanded"""
        if not shiboken6.isValid(self) or not self._undo or self._writing:  # (undo kept while a write runs)
            return
        trashed = self._undo

        def restored(library: LapLibrary | None, paths: list[str]):
            if library is not None:
                library.refresh({os.path.basename(os.path.dirname(path)) for path in paths})

        def restore_failed(library: LapLibrary | None, error: BaseException):
            logger.error("LAP LIBRARY: unable to restore laps: %s", error, exc_info=error)
            if library is not None:
                library.refresh()

        if self.run_write("restore", lambda: restore_laps(trashed), restored, restore_failed):
            self._undo = []
            self.button_undo.setVisible(False)
