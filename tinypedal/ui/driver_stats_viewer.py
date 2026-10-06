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
Driver stats viewer: stats of each track & vehicle, community lap time levels, progression & sessions

Qt Quick page (ui/qml/DriverStats.qml), state & actions in quick/stats_backend.py.
"""

from PySide6.QtCore import QSize, QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QVBoxLayout

from ..i18n import tr
from ._common import BaseDialog, UIScaler


class DriverStatsViewer(BaseDialog):
    """Driver stats viewer"""

    def __init__(self, parent):
        from .quick import create_quick_view
        from .quick.stats_backend import DriverStatsBackend

        super().__init__(parent)
        self.set_utility_title(tr("Driver Stats Viewer"))
        self.setMinimumSize(UIScaler.size(60), UIScaler.size(30))
        self.backend = DriverStatsBackend(self)
        self.view = create_quick_view(
            self, "DriverStats.qml", {"backend": self.backend}, samples=0)  # no GpuShape: no MSAA
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.resize(UIScaler.size(96), UIScaler.size(56))
        # Text fields keep their own undo (shortcut override)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self, self.backend.undo)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Redo), self, self.backend.redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, self.backend.redo)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Refresh), self, self.backend.reload)  # F5, focus anywhere

    @staticmethod
    def page_minimum_size() -> QSize:
        """Page area minimum while shown in app window (see app.DialogPage): tiles & cards text whole,
        French included (narrower, empty tracks card note is cut, shorter, levels card note)"""
        return QSize(UIScaler.size(64), UIScaler.size(40))

    def showEvent(self, event):
        self.backend.page_shown()
        super().showEvent(event)

    def hideEvent(self, event):
        self.backend.page_hidden()
        super().hideEvent(event)

    def closeEvent(self, event):
        # QML bindings never read a released backend (see qml page pitfalls: view goes first)
        self.view.setSource(QUrl())
        self.backend.release()
        super().closeEvent(event)
