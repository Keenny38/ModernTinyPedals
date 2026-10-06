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
Race results viewer: sessions of game results files, classification, positions, laps & events

Qt Quick page (ui/qml/RaceResults.qml), state & actions in quick/results_backend.py.
"""

from PySide6.QtCore import QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QVBoxLayout

from ..i18n import tr
from ._common import BaseDialog, UIScaler


class RaceResultsViewer(BaseDialog):
    """Race results viewer"""

    def __init__(self, parent):
        from .quick import create_quick_view
        from .quick.results_backend import RaceResultsBackend

        super().__init__(parent)
        self.set_utility_title(tr("Race Results"))
        self.setMinimumSize(UIScaler.size(60), UIScaler.size(30))
        self.backend = RaceResultsBackend(self)
        self.view = create_quick_view(self, "RaceResults.qml", {"backend": self.backend})
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.resize(UIScaler.size(100), UIScaler.size(58))
        QShortcut(QKeySequence(QKeySequence.StandardKey.Refresh), self, self.backend.reload)  # F5, focus anywhere

    def showEvent(self, event):
        self.backend.page_shown()
        super().showEvent(event)

    def hideEvent(self, event):
        self.backend.page_hidden()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.backend.release()
        # QML bindings never read a deleted backend (see qml page pitfalls: view goes first)
        self.view.setSource(QUrl())
        super().closeEvent(event)
