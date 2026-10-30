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
Table editor backend: one page (qml/editors/TableEditor.qml) for every table of style data

Rows of a style preset (brakes, tyre compounds, car classes & brands, track info, heatmap steps) edited in a table:
columns described by Column (text, number shown in the user's units & stored in base units, color, choice, clock,
one letter symbol, preset name chosen among existing presets). Search filters rows, header click sorts them, Delete
removes selected rows (toast with Undo), Enter / F2 edits a cell, Esc cancels the edit. Save checks the table
(names listed once, valid colors) then writes and applies it: one save, no separate Apply.

Editors subclass TableEditorBackend: COLUMNS, CONFIG_TYPE, load (setting -> rows), to_setting (rows -> setting),
session_rows (rows of the running session for Add), new_row. The page hosting the QML view (table_editor_host.
TableEditorPage) keeps undo history (snapshots of rows), unsaved changes marker and dialogs.
"""

from __future__ import annotations

import html
import math
import re
import weakref
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot

from ... import units
from ...const_common import EMPTY_DICT
from ...i18n import tr
from ...setting import cfg, copy_setting
from ...validator import is_hex_color
from .models import DictListModel
from .page_backend import PageBackend

# Column kinds
KIND_NAME = "name"  # row name, listed once (key of setting)
KIND_TEXT = "text"
KIND_NUMBER = "number"
KIND_COLOR = "color"
KIND_CHOICE = "choice"  # one of choice_values()
KIND_CLOCK = "clock"  # hours:minutes
KIND_SYMBOL = "symbol"  # one letter, "?" if empty
KIND_PRESET = "preset"  # name of an existing preset, "" for none

# Cell marks: error (refused by Save: duplicated name, invalid color), missing (preset or heatmap not found)
MARK_ERROR = "error"
MARK_MISSING = "missing"

# User unit of number columns: units setting key, value converter, unit symbol
UNIT_SETTINGS: dict[str, tuple[str, str, Callable[[str], Callable], Callable[[str], str]]] = {
    "distance": ("distance_unit", "Meter", units.set_unit_distance, units.set_symbol_distance),
    "speed": ("speed_unit", "KPH", units.set_unit_speed, units.set_symbol_speed),
    "temperature": ("temperature_unit", "Celsius", units.set_unit_temperature, units.set_symbol_temperature),
}

ROLES = ("key", "cells", "colors", "marks", "selected", "current")
SELECT_ONE, SELECT_TOGGLE, SELECT_RANGE = 0, 1, 2  # click alone, with Ctrl, with Shift


@dataclass(frozen=True)
class Column:
    """Column of a table editor

    Args:
        key: setting key of the value ("" for the row name).
        header: English header (translated when shown).
        kind: KIND_* value kind.
        width: least width of values (em), header text widens it (French headers are never cut).
        unit: "distance", "speed" or "temperature": shown & typed in the user's unit, stored in base unit.
        symbol: fixed unit symbol of header ("mm", "°"), when no user unit.
        decimals: most decimals shown (numbers).
        replace: offered by Replace.
        action: cell menu action of column ("telemetry": speed trap set from car position).
    """

    key: str
    header: str
    kind: str = KIND_TEXT
    width: float = 6.0
    unit: str = ""
    symbol: str = ""
    decimals: int = 4
    replace: bool = False
    action: str = ""


class EditorHost(Protocol):
    """Page hosting the table editor (table_editor_host.TableEditorPage): undo history, unsaved marker, dialogs"""

    def set_modified(self) -> None: ...
    def set_unmodified(self) -> None: ...
    def record_change(self) -> None: ...
    def reset_undo(self) -> None: ...
    def undo(self) -> None: ...
    def redo(self) -> None: ...
    def warn(self, text: str) -> None: ...
    def ask(self, title: str, text: str, action_text: str, on_result: Callable[[bool], object]) -> None: ...
    def toast(self, text: str, error: bool = False, undo: bool = False) -> None: ...
    def pick_color(self, color: str) -> str: ...
    def open_file(self, file_filter: str) -> str: ...
    def reloading(self) -> None: ...


def parse_number(text: str) -> float | None:
    """Typed number (comma decimal point & spaces accepted), None if not a finite number"""
    try:
        value = float(str(text).strip().replace(",", ".").replace(" ", ""))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def format_number(value: float, decimals: int) -> str:
    """Number rounded to decimals, without trailing zeros ("6800", "16.67")"""
    text = f"{value:.{max(decimals, 0)}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def parse_clock(text: str) -> str:
    """Clock time (hours:minutes) as "HH:MM", clamped to the day (24:00 at most), "" if invalid"""
    try:
        data = str(text).strip().split(":")
        if len(data) != 2:
            raise ValueError
        hours = min(max(int(data[0]), 0), 24)
        minutes = min(max(int(data[1]), 0), 60)
    except (AttributeError, IndexError, ValueError, TypeError):
        return ""
    if minutes >= 60:
        hours += 1
        minutes = 0
    if hours >= 24:
        hours, minutes = 24, 0
    return f"{hours:02d}:{minutes:02d}"


def unit_converters(unit: str) -> tuple[Callable[[float], float], Callable[[float], float], str]:
    """Base -> user unit, user unit -> base, unit symbol, from the user's Units settings (affine conversions)"""
    setting_key, default, set_unit, set_symbol = UNIT_SETTINGS[unit]
    name = cfg.units.get(setting_key, default) if isinstance(cfg.units, dict) else default
    convert = set_unit(name)
    offset = convert(0.0)
    scale = convert(1.0) - offset or 1.0
    return convert, lambda value: (value - offset) / scale, set_symbol(name)


def sort_key(kind: str, value: Any) -> tuple:
    """Sort key of a cell value: numbers by value, texts case & accent blind"""
    if kind == KIND_NUMBER:
        return (0, float(value) if isinstance(value, (int, float)) else 0.0, "")
    return (1, 0.0, str(value).casefold())


class TableEditorBackend(PageBackend):
    """Table editor page state (QML context property "backend")

    Rows are lists of values (one per column, base units), told apart by a key (int) that stays the same while the
    row lives (selection, QML delegates). Changes are recorded by the host (snapshot of rows, see capture_state).
    """

    COLUMNS: tuple[Column, ...] = ()
    CONFIG_TYPE = ""  # cfg.user attribute & config type saved
    NEW_NAME = "New Name"  # name of added row when session has nothing new (numbered)
    RESET_TEXT = "Reset every row to default?"
    FEATURES: tuple[str, ...] = ()  # parts of page shown for this editor only ("heatmap")
    IMPORT_SOURCES: tuple[tuple[str, str], ...] = ()  # Import menu entries: English label & tooltip

    tableChanged = Signal()  # columns (units, presets list)
    rowsChanged = Signal()  # counts
    selectionChanged = Signal()
    historyChanged = Signal()  # modified, undo, redo
    sortChanged = Signal()
    filterChanged = Signal()
    busyChanged = Signal()
    longestChanged = Signal()  # longest text of each column (columns as wide as their values)
    rowAdded = Signal(int, bool)  # row key, name to type (page starts editing it)
    commitEdits = Signal()  # cell being typed kept now (save by Ctrl+S or Save while a field is edited)

    def __init__(self, host: EditorHost, parent: QObject | None = None):
        super().__init__(parent, type(self).__name__)
        self._host = host
        self.rows: list[list] = []
        self.keys: list[int] = []
        self._next_key = 1
        self._selected: set[int] = set()
        self._current_key = 0  # row of keyboard cursor (0: none)
        self._current_column = 0
        self._anchor = 0  # row Shift selection starts from
        self._filter_words: tuple[str, ...] = ()
        self._filter_text = ""
        self._sort_column = -1
        self._sort_descending = False
        self._modified = False
        self._can_undo = False
        self._can_redo = False
        self._busy = False
        self.last_notice = ("", False, False)  # toast: text, error, undo
        self._longest: list[str] = []
        self._converters: dict[int, tuple[Callable[[float], float], Callable[[float], float], str]] = {}
        self._presets: tuple[str, ...] = ()
        self._units_key: tuple = ()
        self.model = DictListModel(ROLES, self)
        self.setup()
        self.read_units()
        self.read_presets()
        self._columns: list[dict] = []  # see update_columns
        self._replace_columns: list[dict] = []
        self.update_columns()
        self._import_sources = [{"label": tr(label), "tip": tr(tip)} for label, tip in self.IMPORT_SOURCES]
        self.set_rows(self.load())

    # Editor hooks
    def setup(self):
        """State of a subclass needed by load (before rows are read)"""

    def load(self) -> list[list]:
        """Rows of saved setting"""
        return []

    def default_rows(self) -> list[list]:
        """Rows of default setting (Reset)"""
        return []

    def to_setting(self, rows: list[list]) -> dict:
        """Setting saved from rows"""
        return {}

    def session_rows(self) -> list[list]:
        """Rows of the running session (Add): already listed names are skipped"""
        return []

    def new_row(self, name: str) -> list:
        """Row added with a new name"""
        return [name]

    def choice_values(self, column: int) -> Sequence[str]:
        """Values of a choice column"""
        return ()

    def store(self, setting: dict):
        """Saved setting written & applied"""
        setattr(cfg.user, self.CONFIG_TYPE, copy_setting(setting))
        cfg.save(0, config_type=self.CONFIG_TYPE)

    def duplicate_message(self, row: list) -> str:
        """Save refused: name listed twice"""
        return (
            f"<b>{html.escape(str(row[0]))}</b> is listed more than once.<br><br>"
            "Each name can only be listed once, rename or delete duplicate rows."
        )

    def unique_text(self, value: Any) -> str:
        """Text telling rows apart (first column)"""
        return str(value).strip()

    def name_required_message(self) -> str:
        return "A row has no name.<br><br>Type a name in its first column or delete the row."

    def can_reset(self) -> bool:
        return True

    def import_from(self, index: int):
        """Import menu entry chosen (IMPORT_SOURCES)"""

    def cell_action(self, key: int, column: int):
        """Cell menu action of column (Column.action)"""

    # Page
    def page_shown(self):
        """Units, presets or values set elsewhere changed while hidden: values shown again"""
        table = self.read_units() | self.read_presets()
        if table:
            self.update_columns()
            self.tableChanged.emit()
        if self.read_saved() or table:
            self.refresh()

    def read_saved(self) -> bool:
        """Values set elsewhere meanwhile (and left as is here) taken, True if any"""
        return False

    def read_units(self) -> bool:
        """Converters of number columns from Units settings, True if changed"""
        key = tuple(cfg.units.get(UNIT_SETTINGS[column.unit][0]) if isinstance(cfg.units, dict) else None
                    for column in self.COLUMNS if column.unit)
        if key == self._units_key and self._converters:
            return False
        self._units_key = key
        self._converters = {index: unit_converters(column.unit) for index, column in enumerate(self.COLUMNS)
                            if column.unit}
        return True

    def read_presets(self) -> bool:
        """Preset names (primary preset choices), True if changed"""
        if not any(column.kind == KIND_PRESET for column in self.COLUMNS):
            return False
        try:
            presets = tuple(sorted(cfg.preset_files(by_date=False, reverse=False), key=str.casefold))
        except OSError:
            presets = ()
        if presets == self._presets:
            return False
        self._presets = presets
        return True

    # Values
    def display(self, column: int, value: Any) -> str:
        """Cell text: numbers in user unit"""
        spec = self.COLUMNS[column]
        if spec.kind == KIND_NUMBER:
            number = float(value) if isinstance(value, (int, float)) else 0.0
            converter = self._converters.get(column)
            if converter is not None:
                number = converter[0](number)
            return format_number(number, spec.decimals)
        return str(value)

    def parse(self, column: int, text: str) -> tuple[bool, Any]:
        """Typed text as cell value (valid, value): numbers back to base unit"""
        spec = self.COLUMNS[column]
        kind = spec.kind
        if kind == KIND_NUMBER:
            number = parse_number(text)
            if number is None:
                return False, None
            converter = self._converters.get(column)
            return True, converter[1](number) if converter is not None else number
        if kind == KIND_CLOCK:
            clock = parse_clock(text)
            return clock != "", clock
        if kind == KIND_SYMBOL:
            return True, text.strip()[:1] or "?"
        if kind == KIND_COLOR:
            color = text.strip()
            return is_hex_color(color), color
        if kind == KIND_PRESET:
            name = text.strip()
            return name == "" or name in self._presets, name
        if kind == KIND_CHOICE:
            return text in self.choice_values(column), text
        if kind == KIND_NAME:  # key of the setting: never empty nor padded (game names never are)
            name = text.strip()
            return bool(name), name
        return True, text

    def marks(self, row: list, duplicated: bool) -> list[str]:
        """Marks of row cells"""
        found = []
        for column, spec in enumerate(self.COLUMNS):
            value = row[column]
            if column == 0 and duplicated:
                found.append(MARK_ERROR)
            elif spec.kind == KIND_COLOR and not is_hex_color(value):
                found.append(MARK_ERROR)
            elif spec.kind == KIND_PRESET and value and value not in self._presets:
                found.append(MARK_MISSING)
            elif spec.kind == KIND_CHOICE and value not in self.choice_values(column):
                found.append(MARK_MISSING)
            else:
                found.append("")
        return found

    # Rows
    def set_rows(self, rows: list[list], keys: Sequence[int] | None = None):
        """Rows shown (keys kept from a snapshot, else new ones)"""
        self.rows = [list(row) for row in rows]
        if keys is None:
            keys = range(self._next_key, self._next_key + len(rows))
        self.keys = list(keys)
        self._next_key = max(self.keys, default=self._next_key - 1) + 1
        kept = set(self.keys)
        self._selected &= kept
        if self._current_key not in kept:
            self._current_key = 0
        self.refresh()

    def index_of(self, key: int) -> int:
        """Row number of key, -1 if gone"""
        try:
            return self.keys.index(key)
        except ValueError:
            return -1

    def duplicated_rows(self) -> set[int]:
        """Row numbers whose name is listed more than once"""
        seen: dict[str, int] = {}
        found: set[int] = set()
        for number, row in enumerate(self.rows):
            text = self.unique_text(row[0])
            first = seen.setdefault(text, number)
            if first != number:
                found.update((first, number))
        return found

    def shown(self, cells: Sequence[str]) -> bool:
        """Row matches search words"""
        if not self._filter_words:
            return True
        text = " ".join(cells).casefold()
        return all(word in text for word in self._filter_words)

    def refresh(self):
        """Rows of view: shown by search, texts, marks, selection"""
        duplicated = self.duplicated_rows()
        shown = []
        longest = [""] * len(self.COLUMNS)
        for number, (key, row) in enumerate(zip(self.keys, self.rows)):
            cells = [self.display(column, value) for column, value in enumerate(row)]
            for column, text in enumerate(cells):
                if len(text) > len(longest[column]):
                    longest[column] = text
            if not self.shown(cells):
                continue
            shown.append({
                "key": key,
                "cells": cells,
                "colors": [str(value) if spec.kind == KIND_COLOR and is_hex_color(value) else ""
                           for spec, value in zip(self.COLUMNS, row)],
                "marks": self.marks(row, number in duplicated),
                "selected": key in self._selected,
                "current": self._current_column if key == self._current_key else -1,
            })
        self.model.sync(shown, reset_if_mostly_new=True)  # search changed: no ghost rows left in view
        if longest != self._longest:
            self._longest = longest
            self.longestChanged.emit()
        self.rowsChanged.emit()
        self.selectionChanged.emit()

    def changed(self, keep_sort: bool = False):
        """Rows changed by the user: view & undo history"""
        if not keep_sort and self._sort_column >= 0:
            self._sort_column = -1
            self.sortChanged.emit()
        self.refresh()
        self._host.set_modified()

    # Undo history (host)
    def capture_state(self) -> tuple:
        return tuple(self.keys), tuple(tuple(row) for row in self.rows)

    def restore_state(self, state: tuple):
        keys, rows = state
        self.set_rows([list(row) for row in rows], keys)

    def set_history(self, modified: bool, can_undo: bool, can_redo: bool):
        """Host history state (unsaved changes, undo & redo available)"""
        if (modified, can_undo, can_redo) != (self._modified, self._can_undo, self._can_redo):
            self._modified, self._can_undo, self._can_redo = modified, can_undo, can_redo
            self.historyChanged.emit()

    # Notices
    def notify(self, text: str, error: bool = False, undo: bool = False):
        """Toast of page (Undo button with undo)"""
        self.last_notice = (text, error, undo)
        self._host.toast(text, error, undo)

    def ask(self, title: str, text: str, accept_text: str, method: str, *args):
        """Confirmation asked by the page (dialog bridge), method of backend called with args once confirmed
        (backend held weakly by its name: no reference cycle, nothing run once the page is closed)"""
        self._host.ask(title, text, accept_text, partial(run_confirmed, weakref.ref(self), method, args))

    def update_columns(self):
        """Columns & Replace columns (headers with unit symbol) made again: units or presets changed"""
        found = []
        for index, spec in enumerate(self.COLUMNS):
            header = tr(spec.header)
            symbol = self._converters[index][2] if index in self._converters else spec.symbol
            if symbol:
                header = f"{header} ({symbol})"
            found.append({
                "header": header,
                "kind": spec.kind,
                "width": spec.width,
                "right": spec.kind in (KIND_NUMBER, KIND_CLOCK),
                "action": spec.action,
                "actionText": tr("Set from Telemetry") if spec.action == "telemetry" else "",
                "symbol": symbol,
            })
        self._columns = found
        self._replace_columns = [
            {"index": index, "header": tr(spec.header)} for index, spec in enumerate(self.COLUMNS) if spec.replace]

    # Properties
    @Property(list, notify=tableChanged)
    def columns(self) -> list[dict]:
        """Columns of page: header (with unit), kind, least width (em), right aligned, cell menu action"""
        return self._columns

    @Property(QObject, constant=True)
    def rowsModel(self) -> QObject:
        return self.model

    @Property(int, notify=rowsChanged)
    def rowCount(self) -> int:
        return len(self.rows)

    @Property(int, notify=rowsChanged)
    def shownCount(self) -> int:
        return self.model.rowCount()

    @Property(int, notify=selectionChanged)
    def selectedCount(self) -> int:
        return len(self._selected)

    @Property(int, notify=selectionChanged)
    def currentIndex(self) -> int:
        """Shown row of keyboard cursor, -1 if none"""
        return self.model.index_of(self._current_key) if self._current_key else -1

    @Property(int, notify=selectionChanged)
    def currentKey(self) -> int:
        return self._current_key

    @Property(int, notify=selectionChanged)
    def currentColumn(self) -> int:
        return self._current_column

    @Property(bool, notify=historyChanged)
    def modified(self) -> bool:
        return self._modified

    @Property(bool, notify=historyChanged)
    def canUndo(self) -> bool:
        return self._can_undo

    @Property(bool, notify=historyChanged)
    def canRedo(self) -> bool:
        return self._can_redo

    @Property(bool, notify=historyChanged)
    def canReset(self) -> bool:
        return self.can_reset()

    @Property(int, notify=sortChanged)
    def sortColumn(self) -> int:
        return self._sort_column

    @Property(bool, notify=sortChanged)
    def sortDescending(self) -> bool:
        return self._sort_descending

    @Property(str, notify=filterChanged)
    def filterText(self) -> str:
        return self._filter_text

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(list, notify=longestChanged)
    def longest(self) -> list[str]:
        """Longest shown text of each column (page sizes columns to fit it)"""
        return self._longest

    @Property(list, notify=tableChanged)
    def replaceColumns(self) -> list[dict]:
        """Columns offered by Replace: index & header"""
        return self._replace_columns

    @Property(list, constant=True)
    def features(self) -> list[str]:
        return list(self.FEATURES)

    @Property(list, constant=True)
    def importSources(self) -> list[dict]:
        return self._import_sources

    @Slot(int)
    def importFrom(self, index: int):
        if 0 <= index < len(self.IMPORT_SOURCES) and not self._busy:
            self.import_from(index)

    @Slot(int, int)
    def cellAction(self, key: int, column: int):
        if self.index_of(key) >= 0 and 0 <= column < len(self.COLUMNS) and self.COLUMNS[column].action:
            self.cell_action(key, column)

    def set_busy(self, busy: bool):
        if busy != self._busy:
            self._busy = busy
            self.busyChanged.emit()

    # Search & sort
    @Slot(str)
    def setFilter(self, text: str):
        words = tuple(text.casefold().split())
        if words == self._filter_words:
            return
        self._filter_words = words
        self._filter_text = text
        self.filterChanged.emit()
        self.refresh()
        # Rows hidden by search leave the selection: Delete never removes rows not shown
        shown = {row["key"] for row in self.model.rows}
        if self._selected - shown:
            self._selected &= shown
            self.refresh()

    @Slot(int)
    def sortBy(self, column: int):
        """Rows sorted by column (ascending, then descending when sorted by it already), one undo step"""
        if not 0 <= column < len(self.COLUMNS):
            return
        descending = column == self._sort_column and not self._sort_descending
        kind = self.COLUMNS[column].kind
        order = sorted(range(len(self.rows)), key=lambda number: sort_key(kind, self.rows[number][column]),
                       reverse=descending)
        self.rows = [self.rows[number] for number in order]
        self.keys = [self.keys[number] for number in order]
        self._sort_column = column
        self._sort_descending = descending
        self.sortChanged.emit()
        self.changed(keep_sort=True)

    # Selection & keyboard cursor
    def shown_keys(self) -> list[int]:
        return [row["key"] for row in self.model.rows]

    @Slot(int, int, int)
    def select(self, key: int, column: int, mode: int = SELECT_ONE):
        """Row clicked: alone, toggled (Ctrl) or range from last clicked row (Shift)"""
        if self.index_of(key) < 0:
            return
        if mode == SELECT_TOGGLE:
            self._selected ^= {key}
            self._anchor = key
        elif mode == SELECT_RANGE and self._anchor:
            shown = self.shown_keys()
            if self._anchor in shown:
                first, last = sorted((shown.index(self._anchor), shown.index(key)))
                self._selected = set(shown[first:last + 1])
            else:
                self._selected = {key}
                self._anchor = key
        else:
            self._selected = {key}
            self._anchor = key
        self._current_key = key
        self._current_column = max(0, min(column, len(self.COLUMNS) - 1))
        self.refresh_selection()

    @Slot(int, int, bool)
    def moveCurrent(self, rows: int, columns: int, extend: bool):
        """Keyboard cursor moved (arrows, Page Up / Down, Home / End): row selected, range with Shift"""
        shown = self.shown_keys()
        if not shown:
            return
        index = shown.index(self._current_key) if self._current_key in shown else -1
        index = max(0, min(len(shown) - 1, index + rows if index >= 0 else 0))
        column = max(0, min(len(self.COLUMNS) - 1, self._current_column + columns))
        self.select(shown[index], column, SELECT_RANGE if extend else SELECT_ONE)

    @Slot()
    def selectAll(self):
        self._selected = set(self.shown_keys())
        self.refresh_selection()

    @Slot(int, int)
    def setCurrent(self, key: int, column: int):
        """Keyboard cursor on a cell, selection kept (right click in a selection)"""
        if self.index_of(key) >= 0 and 0 <= column < len(self.COLUMNS):
            self._current_key = key
            self._current_column = column
            self.refresh_selection()

    @Slot(result=bool)
    def clearSelection(self) -> bool:
        """Selection cleared (Esc), False if nothing was selected"""
        if not self._selected:
            return False
        self._selected = set()
        self.refresh_selection()
        return True

    def refresh_selection(self):
        """Selected & current flags of shown rows"""
        selected, current_key, current_column = self._selected, self._current_key, self._current_column
        self.model.update_rows(lambda row: {
            "selected": row["key"] in selected,
            "current": current_column if row["key"] == current_key else -1,
        })
        self.selectionChanged.emit()

    # Cells
    @Slot(int, int, result=str)
    def editText(self, key: int, column: int) -> str:
        """Text of cell editor"""
        number = self.index_of(key)
        if number < 0 or not 0 <= column < len(self.COLUMNS):
            return ""
        return self.display(column, self.rows[number][column])

    @Slot(int, str, result=bool)
    def checkCell(self, column: int, text: str) -> bool:
        """Typed text valid for column (field marked invalid while typing)"""
        return 0 <= column < len(self.COLUMNS) and self.parse(column, text)[0]

    @Slot(int, int, str, result=bool)
    def setCell(self, key: int, column: int, text: str) -> bool:
        """Cell edited, False if text is invalid (cell kept)"""
        number = self.index_of(key)
        if number < 0 or not 0 <= column < len(self.COLUMNS):
            return False
        row = self.rows[number]
        if text == self.display(column, row[column]):
            return True  # unchanged text: stored value kept (no unit round trip)
        valid, value = self.parse(column, text)
        if not valid:
            return False
        if value != row[column]:
            row[column] = value
            self.changed()
        return True

    @Slot(int, int, result="QVariantList")
    def choices(self, key: int, column: int) -> list[dict]:
        """Values of a choice or preset cell: label & value, value of cell kept first if not found"""
        if not 0 <= column < len(self.COLUMNS):
            return []
        kind = self.COLUMNS[column].kind
        if kind == KIND_PRESET:
            values: list[tuple[str, str]] = [(tr("None"), "")] + [(name, name) for name in self._presets]
        elif kind == KIND_CHOICE:
            values = [(name, name) for name in self.choice_values(column)]
        else:
            return []
        number = self.index_of(key)
        if number >= 0:
            current = self.rows[number][column]
            if all(value != current for _, value in values):
                values.insert(0, (f"{current} ({tr('not found')})", current))
        return [{"label": label, "value": value} for label, value in values]

    @Slot(int, int)
    def pickColor(self, key: int, column: int):
        """Color dialog for a color cell"""
        number = self.index_of(key)
        if number < 0 or self.COLUMNS[column].kind != KIND_COLOR:
            return
        color = self._host.pick_color(str(self.rows[number][column]))
        if color:
            self.setCell(key, column, color)

    # Rows actions
    def new_name(self) -> str:
        """NEW_NAME with first number not listed"""
        listed = {str(row[0]) for row in self.rows}
        index = 1
        while f"{self.NEW_NAME} {index}" in listed:
            index += 1
        return f"{self.NEW_NAME} {index}"

    @Slot()
    def addRow(self):
        """Rows of running session not listed yet, else a new name to type: one undo step"""
        added, typed = self.rows_to_add()
        if added:
            self.append_rows(added, typed)

    def rows_to_add(self) -> tuple[list[list], bool]:
        """Rows added (Add), True if the first cell of the last one is to type"""
        listed = {str(row[0]) for row in self.rows}
        added = []
        for row in self.session_rows():
            if row[0] and str(row[0]) not in listed:
                listed.add(str(row[0]))
                added.append(list(row))
        if added:
            return added, False
        return [self.new_row(self.new_name())], True

    def append_rows(self, added: list[list], typed: bool = False):
        """Rows added at the end, last one selected (search cleared: added rows shown)"""
        keys = list(range(self._next_key, self._next_key + len(added)))
        self._next_key += len(added)
        self.rows.extend(added)
        self.keys.extend(keys)
        if self._filter_words:
            self._filter_words = ()
            self._filter_text = ""
            self.filterChanged.emit()
        self._selected = {keys[-1]}
        self._current_key = self._anchor = keys[-1]
        self._current_column = 0
        self.changed()
        self.rowAdded.emit(keys[-1], typed)

    @Slot()
    def deleteSelected(self):
        """Selected rows removed (toast with Undo)"""
        if not self._selected:
            return
        count = sum(key in self._selected for key in self.keys)
        kept = [(key, row) for key, row in zip(self.keys, self.rows) if key not in self._selected]
        # Cursor moves to the row after the last removed one
        shown = self.shown_keys()
        after = [key for key in shown[shown.index(self._current_key):] if key not in self._selected] \
            if self._current_key in shown else []
        self.keys = [key for key, _ in kept]
        self.rows = [row for _, row in kept]
        self._selected = set()
        self._current_key = after[0] if after else (self.keys[-1] if self.keys else 0)
        if self._current_key:
            self._selected = {self._current_key}
            self._anchor = self._current_key
        self.changed()
        self.notify(f"{tr('Rows deleted:')} {count}" if count > 1 else tr("Row deleted"), undo=True)

    @Slot()
    def askReset(self):
        if self.can_reset():
            self.ask(tr("Reset to Default?"), tr(self.RESET_TEXT), tr("Reset"), "resetToDefault")

    @Slot()
    def resetToDefault(self):
        """Default rows (one undo step)"""
        if not self.can_reset():
            return
        self.set_rows(self.default_rows())
        self.changed()

    @Slot(int, result="QVariantList")
    def replaceValues(self, column: int) -> list[str]:
        """Values of column (Replace: find field suggestions)"""
        if not 0 <= column < len(self.COLUMNS):
            return []
        return sorted({self.display(column, row[column]) for row in self.rows}, key=str.casefold)

    @Slot(int, str, str, bool, bool, result=int)
    def replace(self, column: int, find: str, replacement: str, whole: bool, match_case: bool) -> int:
        """Found text replaced in every cell of column (one undo step), number of cells changed"""
        if not find or not 0 <= column < len(self.COLUMNS) or not self.COLUMNS[column].replace:
            return 0
        pattern = re.escape(find)
        if whole:
            pattern = f"^{pattern}$"
        flags = 0 if match_case else re.IGNORECASE
        count = 0
        for row in self.rows:
            # Replacement is plain text, never a template ("\1", "\" are not group references)
            text = re.sub(pattern, lambda _: replacement, self.display(column, row[column]), flags=flags)
            valid, value = self.parse(column, text)
            if valid and value != row[column]:
                row[column] = value
                count += 1
        if count:
            self.changed()
            self.notify(f"{tr('Cells replaced:')} {count}", undo=True)
        else:
            self.notify(tr("Nothing replaced"))
        return count

    # Saving
    def verify(self) -> bool:
        """Table can be saved: names listed once, valid colors (else warned, row selected)"""
        duplicated = self.duplicated_rows()
        seen: set[str] = set()
        for number, row in enumerate(self.rows):
            text = ""
            if self.COLUMNS and self.COLUMNS[0].kind == KIND_NAME and not self.unique_text(row[0]):
                text = self.name_required_message()
            elif number in duplicated:
                unique = self.unique_text(row[0])
                if unique in seen:
                    text = self.duplicate_message(row)
                seen.add(unique)
            if not text:
                for column, spec in enumerate(self.COLUMNS):
                    if spec.kind == KIND_COLOR and not is_hex_color(row[column]):
                        text = (
                            f"Invalid color <b>{html.escape(str(row[column]))}</b> for "
                            f"<b>{html.escape(self.row_label(row))}</b>.<br><br>"
                            "Use #RGB, #RRGGBB or #AARRGGBB format."
                        )
                        break
            if text:
                self.show_row(self.keys[number])
                self._host.warn(text)
                return False
        return True

    def row_label(self, row: list) -> str:
        """Row name in messages"""
        return str(row[0])

    def show_row(self, key: int):
        """Row selected & shown (search cleared if it hides it)"""
        if self._filter_words and key not in self.shown_keys():
            self.setFilter("")
        self.select(key, 0, SELECT_ONE)

    @Slot(result=bool)
    def save(self) -> bool:
        """Table checked, saved & applied, False if refused (warned)"""
        self.commitEdits.emit()  # value being typed (valid) kept first
        if not self.verify():
            return False
        self.store(self.to_setting(self.rows))
        self._host.set_unmodified()
        from .._common import run_after_saving

        run_after_saving(self._host.reloading)
        self.notify(tr("Changes saved"))
        return True

    @Slot()
    def discard(self):
        """Unsaved changes dropped (unsaved changes bar): saved rows shown again, Undo (Ctrl+Z) brings them back"""
        if not self._modified:
            return
        self.set_rows(self.load())
        self._host.set_modified()  # rows put back recorded: one undo step
        self._host.set_unmodified()

    @Slot()
    def undo(self):
        self._host.undo()

    @Slot()
    def redo(self):
        self._host.redo()


def run_confirmed(backend_ref: Callable[[], TableEditorBackend | None], method: str, args: tuple, chosen: bool):
    """Answer of a confirmation: backend method run if chosen and the page still open"""
    backend = backend_ref()
    if chosen and backend is not None and not backend.page_released:
        getattr(backend, method)(*args)


def dict_rows(setting: dict, keys: Sequence[str], defaults: dict | Any = EMPTY_DICT) -> list[list]:
    """Rows of a setting of dicts (name, then values of keys, default of a missing key)"""
    rows = []
    for name, data in setting.items():
        if not isinstance(data, dict):
            continue
        rows.append([name, *(data.get(key, defaults.get(key, "")) for key in keys)])
    return rows
