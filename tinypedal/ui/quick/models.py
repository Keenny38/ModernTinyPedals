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

from collections.abc import Callable

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, QPersistentModelIndex, Qt

ROOT = QModelIndex()  # list rows have no parent


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

    def sync(self, rows: list[dict], key: str = "key"):
        """Rows become rows (same order), matched by key: removed, moved, inserted & changed rows notified one by one

        Delegates of rows kept stay in place (a reset would create every delegate again).
        """
        wanted = {row[key] for row in rows}
        for number in range(len(self.rows) - 1, -1, -1):
            if self.rows[number].get(key) not in wanted:
                self.beginRemoveRows(ROOT, number, number)
                del self.rows[number]
                self.endRemoveRows()
        for position, row in enumerate(rows):
            current = next((number for number in range(position, len(self.rows)) if self.rows[number].get(key) == row[key]),
                           -1)
            if current < 0:
                self.beginInsertRows(ROOT, position, position)
                self.rows.insert(position, dict(row))
                self.endInsertRows()
                continue
            if current != position:
                self.beginMoveRows(ROOT, current, current, ROOT, position)
                self.rows.insert(position, self.rows.pop(current))
                self.endMoveRows()
            existing = self.rows[position]
            values = {name: value for name, value in row.items() if existing.get(name) != value}
            if values:
                existing.update(values)
                index = self.index(position, 0)
                self.dataChanged.emit(index, index, [self._role_of[name] for name in values if name in self._role_of])

    def update_rows(self, change: Callable[[dict], dict]):
        """Apply change (row -> changed values) to every row, notify changed rows only"""
        for number, row in enumerate(self.rows):
            values = {name: value for name, value in change(row).items() if row.get(name) != value}
            if values:
                row.update(values)
                index = self.index(number, 0)
                self.dataChanged.emit(index, index, [self._role_of[name] for name in values])
