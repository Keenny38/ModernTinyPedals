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
List models for QML views
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Callable, Mapping, Sequence

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, QPersistentModelIndex, Qt

ROOT = QModelIndex()  # list rows have no parent
MIN_MOVES_RESET = 8  # sync: more moved rows than this (and than a quarter of the rows) resets the model


def longest_increasing(values: Sequence[int]) -> list[int]:
    """Positions of a longest strictly increasing subsequence of values (O(n log n))"""
    tails: list[int] = []  # smallest last value of an increasing run of each length
    tail_positions: list[int] = []
    previous = [-1] * len(values)
    for position, value in enumerate(values):
        length = bisect_left(tails, value)
        if length == len(tails):
            tails.append(value)
            tail_positions.append(position)
        else:
            tails[length] = value
            tail_positions[length] = position
        previous[position] = tail_positions[length - 1] if length else -1
    result = []
    position = tail_positions[-1] if tail_positions else -1
    while position >= 0:
        result.append(position)
        position = previous[position]
    result.reverse()
    return result


def too_many_moves(moves: int, rows: int) -> bool:
    """A reset is cheaper than this many row moves (one notification & relayout instead of one per row)"""
    return moves > max(MIN_MOVES_RESET, rows // 4)


class DictListModel(QAbstractListModel):
    """Rows of dicts, each key is a QML role (model.title, model.checked...)

    update_rows changes values in place: views keep scroll position & running animations
    (a reset rebuilds every delegate).
    """

    def __init__(self, roles: tuple[str, ...], parent=None):
        super().__init__(parent)
        self._names = roles
        self._roles = {Qt.ItemDataRole.UserRole + 1 + index: name for index, name in enumerate(roles)}
        self._role_of = {name: role for role, name in self._roles.items()}
        self.rows: list[dict] = []
        self._index_key = ""
        self._index: dict = {}  # row key value: row number (checked on use, rebuilt when wrong)

    def roleNames(self) -> dict[int, QByteArray]:
        return {role: QByteArray(name.encode()) for role, name in self._roles.items()}

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = ROOT) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        name = self._roles.get(role)
        return None if name is None else self.rows[index.row()].get(name)

    def reset(self, rows: list[dict]):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def index_of(self, value, key: str = "key") -> int:
        """Number of first row whose key is value, -1 if none (cached: no scan of every row per call)"""
        number = self._index.get(value, -1) if key == self._index_key else -1
        if 0 <= number < len(self.rows) and self.rows[number].get(key) == value:
            return number
        index: dict = {}
        for number, row in enumerate(self.rows):
            index.setdefault(row.get(key), number)
        self._index_key, self._index = key, index
        return index.get(value, -1)

    def update_row(self, number: int, values: Mapping) -> bool:
        """Values of one row changed in place (changed roles notified), True if anything changed"""
        if not 0 <= number < len(self.rows):
            return False
        row = self.rows[number]
        changed = {name: value for name, value in values.items() if row.get(name) != value}
        if not changed:
            return False
        row.update(changed)
        index = self.index(number, 0)
        self.dataChanged.emit(index, index, [self._role_of[name] for name in changed if name in self._role_of])
        return True

    def sync(self, rows: list[dict], key: str = "key", reset_if_mostly_new: bool = False) -> bool:
        """Rows become rows (same order), matched by key: removed, moved, inserted & changed rows notified
        (following removed or inserted rows together), True if anything changed

        Delegates of rows kept stay in place (a reset would create every delegate again), views keep scroll position.
        Reset instead when many rows moved (see too_many_moves), or with reset_if_mostly_new when less than half
        of the rows are kept (other overlay, search...).
        """
        old = self.rows
        wanted: dict = {}  # key: position in rows (first row of a key, a key listed again is a new row)
        for position, row in enumerate(rows):
            wanted.setdefault(row[key], position)
        kept: dict = {}  # key: number of old row kept (first row of a key, a key listed again is removed)
        for number, row in enumerate(old):
            value = row.get(key)
            if value in wanted and value not in kept:
                kept[value] = number
        kept_keys = list(kept)  # current order
        stay = {kept_keys[number] for number in longest_increasing([wanted[value] for value in kept_keys])}
        moves = len(kept_keys) - len(stay)
        if old and (too_many_moves(moves, len(rows))
                    or (reset_if_mostly_new and len(kept) * 2 < max(len(rows), len(old)))):
            self.reset([dict(row) for row in rows])
            return True
        changed = False
        # Removed rows, runs from last
        kept_numbers = set(kept.values())
        end = len(old)
        for number in range(len(old) - 1, -2, -1):
            if number >= 0 and number not in kept_numbers:
                continue
            if number + 1 < end:
                self.beginRemoveRows(ROOT, number + 1, end - 1)
                del self.rows[number + 1:end]
                self.endRemoveRows()
                changed = True
            end = number
        # Moved rows: rows out of the longest kept order, each placed right after the row before it in rows
        if moves:
            place = {value: number for number, value in enumerate(kept_keys)}
            previous = None
            for position, row in enumerate(rows):
                value = row[key]
                if value not in kept or wanted[value] != position:
                    continue
                if value not in stay:
                    source = place[value]
                    target = 0 if previous is None else place[previous] + 1
                    if target > source:
                        target -= 1  # row taken out first
                    if target != source:
                        self.beginMoveRows(ROOT, source, source, ROOT, target + 1 if target > source else target)
                        self.rows.insert(target, self.rows.pop(source))
                        kept_keys.insert(target, kept_keys.pop(source))
                        self.endMoveRows()
                        for number in range(min(source, target), max(source, target) + 1):
                            place[kept_keys[number]] = number
                        changed = True
                previous = value
        # Inserted rows (new keys, or a key listed again), runs together, then changed values of kept rows
        position = 0
        while position < len(rows):
            if not self._kept_at(rows, position, key, kept, wanted):
                last = position
                while last + 1 < len(rows) and not self._kept_at(rows, last + 1, key, kept, wanted):
                    last += 1
                self.beginInsertRows(ROOT, position, last)
                self.rows[position:position] = [dict(added) for added in rows[position:last + 1]]
                self.endInsertRows()
                changed = True
                position = last + 1
                continue
            changed = self.update_row(position, rows[position]) or changed
            position += 1
        return changed

    @staticmethod
    def _kept_at(rows: list[dict], position: int, key: str, kept: Mapping, wanted: Mapping) -> bool:
        value = rows[position][key]
        return value in kept and wanted[value] == position

    def update_rows(self, change: Callable[[dict], dict]) -> bool:
        """Apply change (row -> changed values) to every row, notify changed rows only, True if any changed"""
        changed = False
        for number, row in enumerate(self.rows):
            changed = self.update_row(number, change(row)) or changed
        return changed


class FoldedListModel(DictListModel):
    """DictListModel keeping every row (all_rows) but listing only shown ones (rows of collapsed groups left out:
    views make no delegate for them), update_rows changes hidden rows too (right when shown again)"""

    def __init__(self, roles: tuple[str, ...], key: str, parent=None):
        super().__init__(roles, parent)
        self.key = key  # row value telling rows apart
        self.all_rows: list[dict] = []

    def set_rows(self, rows: list[dict], shown: Callable[[dict], bool]) -> bool:
        """Every row, shown ones synced in place (rows kept stay: views keep scroll position)"""
        self.all_rows = rows
        return self.sync([row for row in rows if shown(row)], self.key)

    def update_rows(self, change: Callable[[dict], dict]) -> bool:
        """change computed once per row: copies of shown rows (model rows) get the values of their row"""
        values_of: dict = {}
        for row in self.all_rows:
            values = change(row)
            row.update(values)
            values_of.setdefault(row.get(self.key), values)
        changed = False
        for number, row in enumerate(self.rows):
            value = row.get(self.key)
            values = values_of[value] if value in values_of else change(row)
            changed = self.update_row(number, values) or changed
        return changed
