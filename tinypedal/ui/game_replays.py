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
Game replays (LMU): replays saved by the game opened in game, playback of the replay open in game,
incidents between cars of the session with a jump to each one in the game replay, camera on a car

Qt Quick page (ui/qml/GameReplays.qml), state & game requests in quick/replays_backend.py.
Everything goes through the game Rest API (see game_rest), the game must be running.
"""

from PySide6.QtWidgets import QVBoxLayout

from ..i18n import tr
from ._common import BaseDialog, UIScaler


class GameReplays(BaseDialog):
    """Game replays & incidents of session (LMU)"""

    def __init__(self, parent):
        from .quick import create_quick_view
        from .quick.replays_backend import GameReplaysBackend

        super().__init__(parent)
        self.set_utility_title(tr("Game Replays"))
        self.setMinimumSize(UIScaler.size(46), UIScaler.size(30))
        self.backend = GameReplaysBackend(self)
        self.view = create_quick_view(self, "GameReplays.qml", {"backend": self.backend})
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.resize(UIScaler.size(84), UIScaler.size(50))

    def showEvent(self, event):
        """Game asked at once, then again every few seconds while shown"""
        super().showEvent(event)
        self.backend.page_shown()

    def hideEvent(self, event):
        self.backend.page_hidden()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.backend.release()
        super().closeEvent(event)
