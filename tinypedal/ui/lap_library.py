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
Imported laps library: import, search, add to lap viewer, rename & delete laps imported from MoTeC logs & other
drivers' folders (foreign laps)
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
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
from ..userfile.lap_library import (
    delete_laps,
    group_name_error,
    import_folder,
    is_foreign,
    list_imported,
    rename_group,
)
from ..userfile.motec_ld import import_ld_job
from ..userfile.telemetry_lap import read_lap_info
from ._common import BaseDialog, TextInputDialog, UIScaler

logger = logging.getLogger(__name__)


def imported_time(path: str) -> float:
    """Time lap was imported (file time), 0 if unknown"""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def format_date(timestamp: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp)) if timestamp > 0 else ""


class LapLibrary(BaseDialog):
    """Laps imported from MoTeC logs, grouped by log

    Args:
        filepath: telemetry folder.
        on_add: called with lap paths to show in lap viewer.
        on_changed: called with moved lap paths after rename or delete (old path: new path, "" if deleted).
    """

    EMBED_FROM_PAGE = True
    COL_NAME, COL_TIME, COL_TRACK, COL_VEHICLE, COL_DRIVER, COL_DATE = range(6)

    def __init__(
        self, parent, filepath: str,
        on_add: Callable[[list[str]], None], on_changed: Callable[[dict[str, str]], None],
    ):
        super().__init__(parent)
        self.set_utility_title(tr("Imported Laps"))
        self.filepath = filepath
        self._on_add = on_add
        self._on_changed = on_changed

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
        # Imports run in lap viewer worker process (a long log takes seconds to read): (log name, job)
        self._imports: list = []
        self._import_timer = QTimer(self)
        self._import_timer.setInterval(100)
        self._import_timer.timeout.connect(self.check_imports)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels([tr("Name"), tr("Time"), tr("Track"), tr("Vehicle"), tr("Driver"), tr("Imported")])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.itemDoubleClicked.connect(lambda item, _: self.add_to_viewer([item]))
        self.label_empty = QLabel(tr("No imported lap. Import a MoTeC log (.ld) with Import MoTeC..., or drop it on the app."), self)
        self.label_empty.setWordWrap(True)

        button_add = QPushButton(tr("Add to Viewer"))
        button_add.setToolTip(tr("Show selected laps in lap viewer (double-click also)"))
        button_add.clicked.connect(lambda: self.add_to_viewer(self.tree.selectedItems()))
        button_rename = QPushButton(tr("Rename..."))
        button_rename.setToolTip(tr("Rename selected imported log"))
        button_rename.clicked.connect(self.rename)
        button_delete = QPushButton(tr("Delete"))
        button_delete.clicked.connect(self.delete)
        button_close = QPushButton(tr("Close"))
        button_close.clicked.connect(self.close)
        layout_button = QHBoxLayout()
        layout_button.addWidget(button_add)
        layout_button.addWidget(button_rename)
        layout_button.addWidget(button_delete)
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
        """List imported logs & their laps, expanded state kept (and expand groups)"""
        from .lap_viewer import format_laptime, lap_label

        expanded = {self.group_of(item) for item in self.top_items() if item.isExpanded()} | (expand or set())
        self.tree.clear()
        groups = list_imported(self.filepath)
        for name, laps in groups:
            group = QTreeWidgetItem(self.tree)
            group.setText(self.COL_NAME, name)
            group.setData(self.COL_NAME, Qt.ItemDataRole.UserRole, name)
            font = QFont(group.font(self.COL_NAME))
            font.setBold(True)
            group.setFont(self.COL_NAME, font)
            best = min((lap.lap_time for lap in laps if lap.lap_time > 0), default=0.0)
            group.setText(self.COL_TIME, format_laptime(best))
            first_info: dict = {}
            newest = 0.0
            for lap in laps:
                info = read_lap_info(lap.path)
                first_info = first_info or info
                imported = imported_time(lap.path)
                newest = max(newest, imported)
                item = QTreeWidgetItem(group)
                item.setText(self.COL_DATE, format_date(imported))
                item.setText(self.COL_NAME, lap_label(lap.filename))
                item.setData(self.COL_NAME, Qt.ItemDataRole.UserRole, lap.path)
                item.setText(self.COL_TIME, format_laptime(lap.lap_time))
                if lap.lap_time > 0 and lap.lap_time == best:
                    item.setFont(self.COL_TIME, font)
                for column, key in ((self.COL_TRACK, "track"), (self.COL_VEHICLE, "vehicle"),
                                    (self.COL_DRIVER, "driver")):
                    item.setText(column, str(info.get(key, "")))
            for column, key in ((self.COL_TRACK, "track"), (self.COL_VEHICLE, "vehicle"), (self.COL_DRIVER, "driver")):
                group.setText(column, str(first_info.get(key, "")))
            if not first_info.get("driver") and is_foreign(laps[0].path):  # laps of another driver's folder
                group.setText(self.COL_DRIVER, tr("foreign laps"))
            group.setText(self.COL_DATE, format_date(newest))
            group.setExpanded(name in expanded or len(groups) == 1)
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
        """Import MoTeC logs into library in background, new logs shown expanded once done"""
        if self._imports:
            return
        filenames, _ = QFileDialog.getOpenFileNames(self, tr("Import MoTeC..."), "", "MoTeC i2 (*.ld)")
        if not filenames:
            return
        from .quick.lap_backend import start_job

        folder = import_folder(self.filepath)
        self._imports = [(os.path.basename(filename), start_job("motec import", import_ld_job, filename, folder))
                         for filename in filenames]
        self.button_import.setEnabled(False)
        self.button_import.setText(tr("Importing..."))
        self._import_timer.start()

    def check_imports(self, wait: bool = False):
        """Show imported logs once every import is done (wait: block until done, for tests)"""
        if wait:
            for _, job in self._imports:
                job.join()
        if not self._imports or any(job.is_alive() for _, job in self._imports):
            return
        from .quick.lap_backend import JobHandle

        self._import_timer.stop()
        groups: set[str] = set()
        problems: list[str] = []
        for name, job in self._imports:
            result = job.result()
            if result is None or result is JobHandle.BROKEN:
                paths, error = [], tr("Unexpected error")
            else:
                paths, error = result
            if error:
                problems.append(trm(f"Unable to import <b>{name}</b>: {error}"))
            elif not paths:
                problems.append(trm(f"No complete lap in: {name}"))
            groups.update(os.path.basename(os.path.dirname(path)) for path in paths)
        self._imports = []
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
        items = self.tree.selectedItems()
        if not items:
            return
        old = self.group_of(items[0])

        def renaming(new: str) -> bool:
            new = new.strip()
            if new == old:
                return True
            error = group_name_error(self.filepath, old, new)
            if error:
                message = (
                    "Name already used by another imported log." if error == "exists"
                    else 'Invalid name, characters \\ / : * ? " < > | not allowed.')
                QMessageBox.warning(self, tr("Error"), tr(message))
                return False
            try:
                moved = rename_group(self.filepath, old, new)
            except OSError as error:
                logger.error("LAP LIBRARY: unable to rename %s: %s", old, error)
                QMessageBox.warning(self, tr("Error"), trm(f"Unable to rename: {error}"))
                return False
            self.refresh()
            self._on_changed(moved)
            return True

        TextInputDialog(self, tr("Rename"), tr("Imported log name:"), renaming, old).show()

    def delete(self):
        paths = self.lap_paths(self.tree.selectedItems())
        if not paths:
            return
        if not self.confirm_operation("Delete", f"Delete {len(paths)} imported lap(s)?"):
            return
        deleted = delete_laps(self.filepath, paths)
        self.refresh()
        self._on_changed(deleted)
