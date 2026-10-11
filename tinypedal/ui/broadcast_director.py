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
Broadcast Director (LMU): camera desk, automatic director & commentator screen, live or in a replay

Qt Quick page (ui/qml/BroadcastDirector.qml), state & game requests in quick/director_backend.py,
race events & shots in process/director.py. Everything goes through the game Rest API (see game_rest).
"""

from PySide6.QtCore import QSize, QUrl
from PySide6.QtWidgets import QVBoxLayout

from ..i18n import tr
from ._common import BaseDialog, UIScaler


class BroadcastDirector(BaseDialog):
    """Broadcast director of the session or replay open in game (LMU)"""

    def __init__(self, parent):
        from .quick import create_quick_view
        from .quick.director_backend import DirectorBackend

        super().__init__(parent)
        self.set_utility_title(tr("Broadcast Director"))
        self.setMinimumSize(UIScaler.size(72), UIScaler.size(38))
        self.backend = DirectorBackend(self)
        self.view = create_quick_view(self, "BroadcastDirector.qml", {"backend": self.backend}, samples=0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.resize(UIScaler.size(100), UIScaler.size(56))

    @staticmethod
    def page_minimum_size() -> QSize:
        """Three columns & toolbar never cut (QML pages do not scroll)"""
        return QSize(UIScaler.size(72), UIScaler.size(38))

    def showEvent(self, event):
        """Game asked at once, then about every second until the page closes"""
        super().showEvent(event)
        self.backend.page_shown()

    def hideEvent(self, event):
        self.backend.page_hidden()
        super().hideEvent(event)

    def closeEvent(self, event):
        # QML bindings never read a released backend (see qml page pitfalls: view goes first)
        self.view.setSource(QUrl())
        self.backend.release()
        super().closeEvent(event)
