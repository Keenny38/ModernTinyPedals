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
Track & pace notes editor page state (QML backend of TrackNotesEditor.qml)

Notes rows (distance, pace or track note, comment, tags) edited in place, undo & redo history, notes file opened,
saved to the same file (Save, Ctrl+S) or another one (Save As), track map of the track (TrackMapBackend, as Track Map
Viewer) with the place of every note.

Notes files are shared: the lap viewer writes the track notes file of a track (quick/lap_track_notes.py), other
programs may too. File time is kept when the file is read or written: a file changed meanwhile is read again if
nothing was edited here, else saving asks before replacing it (no silent overwrite in either place).
"""

from __future__ import annotations

import html
import logging
import math
import os
import re
import weakref

from PySide6.QtCore import Property, QFileSystemWatcher, QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from ...const_file import ConfigType, FileExt, FileFilter
from ...context import AppContext
from ...i18n import tr, trm
from ...setting import cfg
from ...userfile.track_notes import (
    COLUMN_COMMENT,
    COLUMN_DISTANCE,
    COLUMN_PACENOTE,
    COLUMN_TAGS,
    COLUMN_TRACKNOTE,
    NOTESTYPE_PACE,
    NOTESTYPE_TRACK,
    TAG_PITNOTES,
    create_notes_metadata,
    load_notes_file,
    save_notes_file,
    set_notes_filter,
    set_notes_header,
    set_notes_header_by_filter,
    set_notes_parser,
    set_notes_writer,
)
from .._common import original_filter, translate_filter
from ..track_map_geometry import node_at
from . import dialogs
from .models import DictListModel
from .page_backend import PageBackend
from .track_map_backend import TrackMapBackend, map_path

logger = logging.getLogger(__name__)

DECIMALS = 2  # distance decimals kept
MAX_UNDO = 100
NOTE_ROLES = ("key", "distance", "note", "comment", "tags", "pit", "selected", "current")
TEXT_COLUMNS = ("note", "comment")  # columns of rows edited as text (tags: tag actions only)
# Shown names (translated) of notes columns & metadata fields, which are file keys
COLUMN_LABELS = {
    COLUMN_DISTANCE: "Distance",
    COLUMN_PACENOTE: "Pace Note",
    COLUMN_TRACKNOTE: "Track Note",
    COLUMN_COMMENT: "Comment",
    COLUMN_TAGS: "Tags",
}
METADATA_LABELS = {
    "TITLE": "Title:",
    "AUTHOR": "Author:",
    "DATE": "Date:",
    "DESCRIPTION": "Description:",
}
NOTES_NAME_HINTS = {NOTESTYPE_PACE: "Pace Notes Name", NOTESTYPE_TRACK: "Track Notes Name"}
EXTENSION_FILTERS = {FileExt.TPPN: FileFilter.TPPN, FileExt.TPTN: FileFilter.TPTN}
MARKED_KEY = "show_marked_coordinates"  # notes places on map (Show menu), track_map_viewer config


def column_label(fieldname: str) -> str:
    """Translated name of notes column"""
    return tr(COLUMN_LABELS.get(fieldname, fieldname))


def notes_folder(notes_type: str) -> str:
    return cfg.path.pace_notes if notes_type == NOTESTYPE_PACE else cfg.path.track_notes


def file_time(path: str) -> float:
    """Modified time of file, 0 if missing"""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def parse_distance(value) -> float | None:
    """Distance typed or read (comma accepted), rounded, None if not a finite number"""
    try:
        number = float(str(value).replace(",", ".").strip()) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        return None
    return round(number, DECIMALS) if math.isfinite(number) else None


def replaced(text: str, find: str, replace: str, match_case: bool, whole_word: bool) -> str:
    """Text with find replaced (plain text both, never a pattern or a template), whole text only if whole_word"""
    pattern = re.escape(find)
    if whole_word:
        pattern = f"^{pattern}$"
    return re.sub(pattern, lambda _: replace, text, flags=0 if match_case else re.IGNORECASE)


class TrackNotesBackend(PageBackend):
    """Track & pace notes editor page state (QML context property "backend")

    Rows: notes model (roles NOTE_ROLES), kept in step with rows (key: row id, stable through edits & undo:
    delegates kept). Selection: row keys (several), current row (insert & set position place).
    """

    typeChanged = Signal()  # notes type: pace or track notes, column names
    fileChanged = Signal()  # file name, open file
    modifiedChanged = Signal()
    historyChanged = Signal()
    selectionChanged = Signal()
    marksChanged = Signal()
    metadataChanged = Signal()
    diskChanged = Signal()  # open file changed by another editor while notes edited here
    mapShownChanged = Signal()
    message = Signal(str, bool, bool)  # toast: text, error, Undo offered

    def __init__(self, parent: QWidget, ctx: AppContext | None = None):
        super().__init__(parent, "Track notes editor", ctx)
        self._window = parent
        self._map = TrackMapBackend(parent)  # map of the track, as Track Map Viewer
        self._map.mapChanged.connect(self.update_marks)
        self._map.configChanged.connect(self.update_marks)
        self._notes_model = DictListModel(NOTE_ROLES, self)
        self.notes_type = NOTESTYPE_PACE
        self.header: tuple[str, ...] = ()
        self._column_labels: list[str] = []  # shown column names (see set_header)
        self._text_columns: list[dict] = []
        self.set_header(set_notes_header(NOTESTYPE_PACE))
        self.metadata: dict = {}
        self._metadata_fields: list[dict] = []  # see set_metadata
        self.set_metadata(create_notes_metadata())
        self.rows: list[dict] = []
        self._next_key = 1
        self._selected: set[int] = set()
        self._current = 0  # key of current row, 0: none
        self._anchor = 0  # key a Shift click selects from
        self._name = ""  # file name field
        self._path = ""  # file notes were read from or saved to, "" for new notes
        self._filter = ""  # file filter of that file (format written by Save)
        self._time = 0.0  # its modified time when read or written
        self._disk_changed = False
        self._modified = False
        self._map_shown = True
        self._marks: list[dict] = []
        self._undo: list[tuple] = []
        self._redo: list[tuple] = []
        self._state: tuple = ()
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self.file_touched)
        self.message.connect(self.toast)
        self.create(NOTESTYPE_PACE)

    def toast(self, text: str, error: bool, undoable: bool):
        """Message in the page toast (TpDialogHost; page hidden: none), Undo of the change it tells"""
        bridge = dialogs.page_bridge(self._window)
        if bridge is None:
            return
        page = weakref.ref(self)
        bridge.show_toast(html.escape(text), "error" if error else "success", action_text=tr("Undo") if undoable else "",
                          action=lambda: (backend := page()) is not None and backend.undo())

    def release_resources(self):
        self._map.release()
        files = self.watcher.files()
        if files:
            self.watcher.removePaths(files)

    def page_shown(self):
        self._map.page_shown()
        self.check_disk()  # file changed by the lap viewer while another page was shown

    def page_hidden(self):
        self._map.page_hidden()

    # Properties
    @Property(QObject, constant=True)
    def trackMap(self) -> TrackMapBackend:
        """Track map (TrackMapBackend: map file, position, curve & slope, Show menu)"""
        return self._map

    @Property(QObject, constant=True)
    def notes(self) -> DictListModel:
        return self._notes_model

    @Property(str, notify=typeChanged)
    def notesType(self) -> str:
        return self.notes_type

    @Property(bool, notify=typeChanged)
    def paceNotes(self) -> bool:
        return self.notes_type == NOTESTYPE_PACE

    @Property(str, notify=typeChanged)
    def typeLabel(self) -> str:
        return tr(self.notes_type)

    @Property(list, notify=typeChanged)
    def columnLabels(self) -> list[str]:
        """Shown names of the 4 columns: distance, pace or track note, comment, tags"""
        return self._column_labels

    @Property(list, notify=typeChanged)
    def textColumns(self) -> list[dict]:
        """Columns batch replace works on: key & shown name"""
        return self._text_columns

    def set_header(self, header: tuple[str, ...]):
        """Columns of notes type (typeChanged sent by caller with the type)"""
        self.header = header
        self._column_labels = [column_label(name) for name in header]
        self._text_columns = [{"key": key, "label": column_label(name)} for key, name in zip(TEXT_COLUMNS, header[1:3])]

    @Property(str, notify=fileChanged)
    def fileName(self) -> str:
        return self._name

    @Property(str, notify=typeChanged)
    def namePlaceholder(self) -> str:
        return tr(NOTES_NAME_HINTS.get(self.notes_type, self.notes_type))

    @Property(str, notify=fileChanged)
    def filePath(self) -> str:
        """File notes were read from or saved to, "" for new notes"""
        return self._path

    @Property(str, notify=fileChanged)
    def statusText(self) -> str:
        mode = trm(f"Edit Mode: {tr(self.notes_type)}")
        return f"{mode} · {os.path.normpath(self._path)}" if self._path else mode

    @Property(bool, notify=modifiedChanged)
    def modified(self) -> bool:
        return self._modified

    @Property(bool, notify=historyChanged)
    def canUndo(self) -> bool:
        return bool(self._undo)

    @Property(bool, notify=historyChanged)
    def canRedo(self) -> bool:
        return bool(self._redo)

    @Property(bool, notify=diskChanged)
    def diskChangedWarning(self) -> bool:
        """Open file changed by another editor since read, while notes are edited here"""
        return self._disk_changed

    @Property(int, notify=selectionChanged)
    def selectedCount(self) -> int:
        return len(self._selected)

    @Property(int, notify=selectionChanged)
    def currentIndex(self) -> int:
        """Row number of current row, -1 if none"""
        return self.row_index(self._current)

    @Property(int, notify=selectionChanged)
    def rowCount(self) -> int:
        return len(self.rows)

    @Property(list, notify=metadataChanged)
    def metadataFields(self) -> list[dict]:
        """Metadata of notes file: key, translated label, value"""
        return self._metadata_fields

    def set_metadata(self, metadata: dict):
        """Metadata of notes & its fields, metadataChanged sent"""
        self.metadata = metadata
        self._metadata_fields = [
            {"key": key, "label": tr(METADATA_LABELS.get(key, f"{key.capitalize()}:")), "value": str(value)}
            for key, value in metadata.items()]
        self.metadataChanged.emit()

    @Property(list, notify=marksChanged)
    def marks(self) -> list[dict]:
        """Notes on track map: map point, row key, text (none if map not loaded or marks hidden)"""
        return self._marks

    @Property(bool, notify=marksChanged)
    def marksShown(self) -> bool:
        return bool(self._map.ecfg.get(MARKED_KEY, True))

    @Property(str, notify=marksChanged)
    def marksColor(self) -> str:
        return str(self._map.ecfg.get("marked_coordinates_color", ""))

    @Property(bool, notify=mapShownChanged)
    def mapShown(self) -> bool:
        return self._map_shown

    @Slot()
    def toggleMap(self):
        self._map_shown = not self._map_shown
        self.mapShownChanged.emit()

    # Rows
    def new_row(self, distance: float = 0.0, note: str = "", comment: str = "", tags: str = "") -> dict:
        row = {"key": self._next_key, "distance": distance, "note": note, "comment": comment, "tags": tags}
        self._next_key += 1
        return row

    def row_index(self, key: int) -> int:
        return next((index for index, row in enumerate(self.rows) if row["key"] == key), -1)

    def selected_rows(self) -> list[dict]:
        """Selected rows in table order"""
        return [row for row in self.rows if row["key"] in self._selected]

    def snapshot(self) -> tuple:
        """Rows & metadata (undo history)"""
        return (tuple((row["key"], row["distance"], row["note"], row["comment"], row["tags"]) for row in self.rows),
                tuple(self.metadata.items()))

    def refresh_rows(self):
        """Model rows from rows (changed rows only told to view), selection kept to rows left"""
        keys = {row["key"] for row in self.rows}
        self._selected &= keys
        if self._current not in keys:
            self._current = 0
        selected, current = self._selected, self._current
        self._notes_model.sync([
            {**row, "pit": TAG_PITNOTES in row["tags"], "selected": row["key"] in selected,
             "current": row["key"] == current}
            for row in self.rows
        ], reset_if_mostly_new=True)  # other file: rows made again (no ghost delegates)
        self.selectionChanged.emit()
        self.update_marks()

    def changed(self):
        """Rows or metadata edited: recorded in undo history, notes marked modified"""
        state = self.snapshot()
        if state != self._state:
            self._undo.append(self._state)
            del self._undo[:-MAX_UNDO]
            self._state = state
            self._redo.clear()
            self.set_modified(True)
            self.historyChanged.emit()
        self.refresh_rows()

    def restore(self, state: tuple):
        rows, metadata = state
        self.rows = [{"key": key, "distance": distance, "note": note, "comment": comment, "tags": tags}
                     for key, distance, note, comment, tags in rows]
        if dict(metadata) != self.metadata:
            self.set_metadata(dict(metadata))
        self._state = state
        self.set_modified(True)
        self.historyChanged.emit()
        self.refresh_rows()

    def reset_history(self):
        self._undo.clear()
        self._redo.clear()
        self._state = self.snapshot()
        self.historyChanged.emit()

    @Slot()
    def undo(self):
        if self._undo:
            self._redo.append(self._state)
            self.restore(self._undo.pop())

    @Slot()
    def redo(self):
        if self._redo:
            self._undo.append(self._state)
            self.restore(self._redo.pop())

    def is_modified(self) -> bool:
        return self._modified

    def set_modified(self, modified: bool):
        if modified != self._modified:
            self._modified = modified
            self.modifiedChanged.emit()

    @Slot(int, str, str, result=bool)
    def setValue(self, key: int, column: str, text: str) -> bool:
        """Cell typed: distance (number, False if not one: value kept), note or comment"""
        index = self.row_index(key)
        if index < 0:
            return False
        row = self.rows[index]
        if column == "distance":
            distance = parse_distance(text)
            if distance is None:
                return False
            value: float | str = distance
        elif column in TEXT_COLUMNS:
            value = text
        else:
            return False
        if row[column] != value:
            row[column] = value
            self.changed()
        return True

    @Slot(str)
    def setFileName(self, name: str):
        name = name.strip()
        if name != self._name:
            self._name = name
            self.fileChanged.emit()

    # Selection
    @Slot(int, int)
    def select(self, key: int, modifiers: int):
        """Row clicked: only this row, Ctrl: added or removed, Shift: rows from last clicked one"""
        index = self.row_index(key)
        if index < 0:
            return
        if modifiers & Qt.KeyboardModifier.ControlModifier.value:
            self._selected ^= {key}
            self._anchor = key
        elif modifiers & Qt.KeyboardModifier.ShiftModifier.value and self.row_index(self._anchor) >= 0:
            first, last = sorted((self.row_index(self._anchor), index))
            self._selected = {row["key"] for row in self.rows[first:last + 1]}
        else:
            self._selected = {key}
            self._anchor = key
        self._current = key
        self.refresh_rows()

    @Slot(int)
    def focusRow(self, key: int):
        """Cell of row focused: current row, selected alone unless already among selected rows"""
        if self.row_index(key) < 0:
            return
        if key == self._current and key in self._selected:
            return
        if key not in self._selected:
            self._selected = {key}
            self._anchor = key
        self._current = key
        self.refresh_rows()

    @Slot()
    def selectAll(self):
        self._selected = {row["key"] for row in self.rows}
        self.refresh_rows()

    @Slot()
    def clearSelection(self):
        self._selected.clear()
        self._current = 0
        self.refresh_rows()

    # Row actions
    @Slot()
    def addRow(self):
        """New note at end, current"""
        row = self.new_row()
        self.rows.append(row)
        self._selected, self._current, self._anchor = {row["key"]}, row["key"], row["key"]
        self.changed()

    @Slot(int)
    def insertRow(self, offset: int = 0):
        """New note above current row (offset 1: below), at top if none"""
        index = self.row_index(self._current)
        position = max(index + offset, 0) if index >= 0 else 0
        row = self.new_row()
        self.rows.insert(position, row)
        self._selected, self._current, self._anchor = {row["key"]}, row["key"], row["key"]
        self.changed()

    @Slot()
    def sortRows(self):
        """Notes by increasing distance"""
        self.rows.sort(key=lambda row: row["distance"])
        self.changed()

    @Slot(result=int)
    def deleteSelected(self) -> int:
        """Selected notes removed (Undo puts them back), count removed"""
        count = len(self._selected)
        if not count:
            return 0
        self.rows = [row for row in self.rows if row["key"] not in self._selected]
        self._selected.clear()
        self.changed()
        self.message.emit(trm(f"{count} notes deleted") if count > 1 else tr("Note deleted"), False, True)
        return count

    @Slot(str)
    def addTag(self, tag: str):
        """Tag added to selected notes (once)"""
        for row in self.selected_rows():
            if tag not in row["tags"]:
                row["tags"] += tag
        self.changed()

    @Slot()
    def clearTags(self):
        for row in self.selected_rows():
            row["tags"] = ""
        self.changed()

    @Slot(float, bool, result=int)
    def applyOffset(self, value: float, scale: bool) -> int:
        """Distance of selected notes moved by value (scale: multiplied), count changed"""
        rows = self.selected_rows()
        for row in rows:
            distance = row["distance"] * value if scale else row["distance"] + value
            row["distance"] = round(distance, DECIMALS) if math.isfinite(distance) else row["distance"]
        self.changed()
        return len(rows)

    @Slot(str, result=list)
    def columnValues(self, column: str) -> list[str]:
        """Distinct texts of a text column (batch replace suggestions)"""
        if column not in TEXT_COLUMNS:
            return []
        return sorted({row[column] for row in self.rows if row[column]})

    @Slot(str, str, str, bool, bool, result=int)
    def replaceText(self, column: str, find: str, replace: str, match_case: bool, whole_word: bool) -> int:
        """Text found in column of every note replaced (one undo step), count of notes changed"""
        if column not in TEXT_COLUMNS or not find:
            return 0
        count = 0
        for row in self.rows:
            text = replaced(row[column], find, replace, match_case, whole_word)
            if text != row[column]:
                row[column] = text
                count += 1
        self.changed()
        return count

    @Slot("QVariantMap")
    def setMetadata(self, values: dict):
        """Metadata edited: notes modified only if a value changed"""
        edited = {key: str(values.get(key, value)) for key, value in self.metadata.items()}
        if edited != self.metadata:
            self.set_metadata(edited)
            self.changed()

    # Positions
    def set_current_distance(self, distance: float) -> bool:
        """Distance of current note (one note selected), shown on map"""
        rows = self.selected_rows()
        if len(rows) != 1:
            self.message.emit(tr("Select one note to set its position."), True, False)
            return False
        rows[0]["distance"] = round(distance, DECIMALS)
        self.changed()
        self._map.setPosition(rows[0]["distance"])
        return True

    @Slot(result=bool)
    def setPositionFromMap(self) -> bool:
        if not self._map.raw_coords:  # no map shown
            return False
        return self.set_current_distance(self._map._position)

    @Slot(result=bool)
    def setPositionFromTelemetry(self) -> bool:
        return self.set_current_distance(float(self.ctx.api.read.lap.distance()))

    @Slot()
    def showOnMap(self):
        """Map position moved to current note"""
        index = self.row_index(self._current)
        if index >= 0:
            self._map.setPosition(self.rows[index]["distance"])

    @Slot(bool)
    def setMarksShown(self, shown: bool):
        """Notes places on map shown or hidden (Show menu, saved like the other map overlays)"""
        if shown != self.marksShown:
            self._map.ecfg[MARKED_KEY] = shown
            cfg.save(config_type=ConfigType.CONFIG)
            self.update_marks(force=True)

    def update_marks(self, force: bool = False):
        """Places of notes on map (marks shown & map loaded), told only if changed"""
        dists, coords, length = self._map.raw_dists, self._map.raw_coords, self._map.map_length
        marks = []
        if coords and self._map.ecfg.get(MARKED_KEY, True):
            for row in self.rows:
                if 0 <= row["distance"] <= length:
                    x, y = coords[node_at(dists, row["distance"])]
                    marks.append({"x": x, "y": y, "key": row["key"], "text": row["note"] or row["comment"],
                                  "current": row["key"] == self._current})
        if force or marks != self._marks:
            self._marks = marks
            self.marksChanged.emit()

    # Files
    def track_name(self) -> str:
        """Game track name, else name of map shown"""
        name = self.ctx.api.read.session.track_name()
        return name if name else self._map.map_name

    def load_map_named(self, name: str):
        """Track map of the same name as notes shown (if recorded and no map shown yet)"""
        name = os.path.splitext(name)[0]
        folder = cfg.path.track_map
        if name and not self._map.raw_coords and not self._map._loading and os.path.isfile(map_path(folder, name)):
            self._map.load_map(folder, name)

    def confirm_discard(self) -> bool:
        """Changes saved, discarded or kept (Cancel, or saving failed): True to go on"""
        if not self._modified:
            return True
        answer = QMessageBox.question(
            self._window, tr("Confirm"), tr("<b>Save changes before continuing?</b>"),
            buttons=QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    @Slot(str)
    def newNotes(self, notes_type: str):
        """New pace or track notes (one empty note), unsaved changes asked first"""
        if self.confirm_discard():
            self.create(notes_type)

    def create(self, notes_type: str):
        self.notes_type = NOTESTYPE_TRACK if notes_type == NOTESTYPE_TRACK else NOTESTYPE_PACE
        self.set_header(set_notes_header(self.notes_type))
        self._name = self.track_name()
        self.set_file("", "")
        self.set_metadata(create_notes_metadata())
        self.rows = []
        self._selected.clear()
        self.addRow()
        self.reset_history()
        self.set_modified(False)
        self.typeChanged.emit()
        self.fileChanged.emit()
        self.load_map_named(self._name)

    @Slot(str)
    def openNotes(self, notes_type: str):
        """Notes file picked (unsaved changes asked first)"""
        if not self.confirm_discard():
            return
        notes_filter = set_notes_filter(notes_type)
        path, shown_filter = QFileDialog.getOpenFileName(
            self._window, dir=notes_folder(notes_type), filter=translate_filter(notes_filter))
        if path:
            self.load_file(path, notes_type, original_filter(notes_filter, shown_filter))

    def load_file(self, path: str, notes_type: str, file_filter: str = "") -> bool:
        """Notes file read (warned if invalid), True if loaded"""
        if not file_filter:
            file_filter = EXTENSION_FILTERS.get(os.path.splitext(path)[1].lower(), "")
        header = set_notes_header(notes_type)
        parsed = load_notes_file(os.path.dirname(path) + "/", os.path.basename(path), header,
                                 set_notes_parser(file_filter))
        if parsed is None:
            dialogs.alert(self._window, tr("Error"), trm("Cannot open selected file.<br><br>Invalid notes file."))
            return False
        notes, metadata = parsed
        self.notes_type = NOTESTYPE_TRACK if notes_type == NOTESTYPE_TRACK else NOTESTYPE_PACE
        self.set_header(header)
        other = COLUMN_TRACKNOTE if header[1] == COLUMN_PACENOTE else COLUMN_PACENOTE  # file of other type
        self.rows = [
            self.new_row(round(float(note[COLUMN_DISTANCE]), DECIMALS), str(note.get(header[1], note.get(other, ""))),
                         str(note.get(COLUMN_COMMENT, "")), str(note.get(COLUMN_TAGS, "")))
            for note in notes if isinstance(note, dict)
        ]
        self.set_metadata({**create_notes_metadata(), **metadata})
        self._name = os.path.basename(path)
        self.set_file(path, file_filter)
        self._selected.clear()
        self._current = 0
        self.reset_history()
        self.set_modified(False)
        self.typeChanged.emit()
        self.fileChanged.emit()
        self.refresh_rows()
        self.load_map_named(self._name)
        return True

    def set_file(self, path: str, file_filter: str):
        """Open file (read or written now): watched for changes by other editors"""
        files = self.watcher.files()
        if files:
            self.watcher.removePaths(files)
        self._path = os.path.normpath(path) if path else ""
        self._filter = file_filter
        self._time = file_time(self._path) if path else 0.0
        if self._path and os.path.isfile(self._path):
            self.watcher.addPath(self._path)
        self.set_disk_changed(False)

    def set_disk_changed(self, changed: bool):
        if changed != self._disk_changed:
            self._disk_changed = changed
            self.diskChanged.emit()

    def file_touched(self, _path: str = ""):
        """Open file written by another editor (lap viewer track notes, other program): checked once shown"""
        if self._path and self._path not in self.watcher.files() and os.path.isfile(self._path):
            self.watcher.addPath(self._path)  # replaced file (atomic write): watched again
        if self.defer_while_hidden(self.check_disk):
            return
        self.check_disk()

    def check_disk(self):
        """Open file changed since read: read again if nothing edited here, else warned (Save asks first)"""
        if not self._path:
            return
        changed = file_time(self._path)
        if not changed or changed == self._time:
            return
        if not self._modified:
            if self.load_file(self._path, self.notes_type, self._filter):
                self.message.emit(tr("Notes read again: file changed by another editor"), False, False)
            return
        self.set_disk_changed(True)

    @Slot(result=bool)
    def save(self) -> bool:
        """Save to open file (Ctrl+S), file name asked for new notes or a name changed to another file"""
        if not self._path:
            return self.saveAs()
        folder = os.path.dirname(self._path)
        target = os.path.normpath(os.path.join(folder, self.target_name(self._name or os.path.basename(self._path))))
        if target == self._path:
            changed = file_time(target)
            if changed and changed != self._time:
                return self.confirm_replace(target, trm(
                    "Notes file changed by another editor since it was read.<br><br>"
                    f"<b>{html.escape(target)}</b><br><br>Replace it with these notes?"))
        elif os.path.exists(target):
            return self.confirm_replace(target, trm(
                f"<b>{html.escape(target)}</b> already exists.<br><br>Replace it with these notes?"))
        return self.write(target, self._filter)

    def target_name(self, name: str) -> str:
        """File name of name field: extension of open file format added if missing"""
        name = os.path.basename(name)
        extension = os.path.splitext(self._path)[1]
        return name if os.path.splitext(name)[1] or not extension else name + extension

    def confirm_replace(self, target: str, text: str) -> bool:
        """Notes written to target once replacing it is confirmed (dialog in the page): True if written at once
        (widget dialog answered meanwhile), False while asked in the page or refused"""
        written: list[bool] = []
        page = weakref.ref(self)
        file_filter = self._filter

        def answered(chosen: bool):
            backend = page()
            written.append(bool(chosen and backend is not None and backend.write(target, file_filter)))

        dialogs.confirm(self._window, tr("Confirm"), text, tr("Replace"), answered)
        return bool(written and written[0])

    @Slot(result=bool)
    def saveAs(self) -> bool:
        """Save to a file picked (default: name field in notes folder, or folder of open file)"""
        name = self._name or self.track_name()
        folder = os.path.dirname(self._path) + "/" if self._path else notes_folder(self.notes_type)
        notes_filter = set_notes_filter(self.notes_type)
        path, shown_filter = QFileDialog.getSaveFileName(
            self._window, dir=f"{folder}{name}", filter=translate_filter(notes_filter))
        if not path:
            return False
        return self.write(os.path.normpath(path), original_filter(notes_filter, shown_filter))

    @Slot()
    def discard(self):
        """Unsaved changes dropped (unsaved changes bar): open file read again, new notes back to one empty note.
        Undo (Ctrl+Z) brings the changes back."""
        if not self._modified:
            return
        undo = [*self._undo, self._state]
        if self._path:
            if not self.load_file(self._path, self.notes_type, self._filter):
                return
        else:
            self.create(self.notes_type)
        self._undo = undo[-MAX_UNDO:]
        self._redo.clear()
        self.historyChanged.emit()

    def write(self, path: str, file_filter: str) -> bool:
        """Notes sorted by distance & written in format of file filter, True if saved"""
        self.sortRows()
        header = set_notes_header_by_filter(file_filter) or self.header
        notes = [dict(zip(header, (row["distance"], row["note"], row["comment"], row["tags"]))) for row in self.rows]
        if not notes:
            self.message.emit(tr("Nothing to save."), True, False)
            return False
        folder, filename = os.path.dirname(path) + "/", os.path.basename(path)
        try:
            save_notes_file(filepath=folder, filename=filename, table_header=header, dataset=notes,
                            metadata=self.metadata, writer=set_notes_writer(file_filter))
        except OSError as error:  # read-only folder, file used by another program
            logger.error("Failed saving notes %s: %s", path, error)
            dialogs.alert(self._window, tr("Error"), trm(
                f"Unable to save notes at:<br><b>{html.escape(path)}</b><br><br>"
                "Make sure the folder is writable, or save notes to another folder."))
            return False
        self._name = filename
        self.set_file(path, file_filter)
        self.set_modified(False)
        self.fileChanged.emit()
        self.message.emit(trm(f"Notes saved at: {path}"), False, False)  # toast: plain text
        return True
