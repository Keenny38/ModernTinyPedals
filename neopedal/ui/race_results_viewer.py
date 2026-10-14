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
Results & replays: sessions of game results files (classification, positions, laps, events) and replays saved
by the game (LMU: watched in game, playback, incidents, standings & map of the replay or live session)

Qt Quick page (ui/qml/RaceResults.qml): results state in quick/results_backend.py ("backend"), game replays &
requests in quick/replays_backend.py ("replays"). Each session is linked to its replay (results files &
replay files on disk): an event or a lap of the results opens the replay there. The game is asked only while
the replay tab or the replays list shows.
"""

from PySide6.QtCore import QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QVBoxLayout

from ..i18n import tr
from ._common import BaseDialog, UIScaler


class RaceResultsViewer(BaseDialog):
    """Results of game sessions & game replays"""

    def __init__(self, parent):
        from .quick import create_quick_view
        from .quick.replays_backend import GameReplaysBackend
        from .quick.results_backend import RaceResultsBackend

        super().__init__(parent)
        self.set_utility_title(tr("Results & Replays"))
        self.setMinimumSize(UIScaler.size(60), UIScaler.size(30))
        self.backend = RaceResultsBackend(self)
        self.replays = GameReplaysBackend(self)
        self._replays_active = False  # game asked (replay tab or replays list shown)
        self.backend.replaysLinked.connect(self.replays.set_results_links)
        self.backend.watchWanted.connect(self.watch)
        self.backend.tabChanged.connect(self.update_replays_active)
        self.backend.listModeChanged.connect(self.update_replays_active)
        self.backend.selectionChanged.connect(self.session_selected)
        self.replays.selectionChanged.connect(self.replay_selected)
        self.view = create_quick_view(  # chart lines: multisampled layer
            self, "RaceResults.qml", {"backend": self.backend, "replays": self.replays}, samples=0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.resize(UIScaler.size(100), UIScaler.size(58))
        QShortcut(QKeySequence(QKeySequence.StandardKey.Refresh), self, self.refresh)  # F5, focus anywhere

    def refresh(self):
        """Results files read again, game asked again while replays show"""
        self.backend.reload()
        if self._replays_active:
            self.replays.refresh()

    def replays_wanted(self) -> bool:
        from .quick.results_backend import REPLAY_TAB

        return self.isVisible() and (self.backend.tab == REPLAY_TAB or self.backend.list_mode == 1)

    def update_replays_active(self):
        """Game asked while replay tab or replays list shows on a shown page, not otherwise"""
        wanted = self.replays_wanted()
        if wanted == self._replays_active:
            return
        self._replays_active = wanted
        if wanted:
            self.replays.page_shown()
        else:
            self.replays.page_hidden()

    def watch(self, action):
        """Replay of session opened in game (event or lap of results: replay goes there)"""
        self.replays.watch_named(action.replay, action)

    def show_replays(self):
        """Replays list shown (opened from former Game Replays page path)"""
        self.backend.setListMode(1)

    def session_selected(self):
        """Session picked in sessions list: its replay picked in replays list too"""
        name = self.backend.header.get("replay", "")
        if self.backend.list_mode == 0 and name and self.replays.replay_of(name) is not None:
            self.replays.selectReplay(name)

    def replay_selected(self):
        """Replay picked in replays list: results of its session shown"""
        if self.backend.list_mode != 1:
            return
        path = self.replays.results_links.get(self.replays.selected_replay, "")
        if path and path != self.backend.selected_key:
            self.backend.open_path(path)

    def showEvent(self, event):
        self.backend.page_shown()
        super().showEvent(event)
        self.update_replays_active()

    def hideEvent(self, event):
        self.backend.page_hidden()
        super().hideEvent(event)
        self.update_replays_active()

    def free_page(self):
        """QML gone before both backends it binds to"""
        self.view.setSource(QUrl())
        self.replays.release()
        self.backend.release()

    def closeEvent(self, event):
        self.release_page()
        super().closeEvent(event)
