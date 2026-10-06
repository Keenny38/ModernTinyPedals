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
Track map viewer: track map file with position along track, curve & slope at position, elevation profile

Qt Quick page (ui/qml/TrackMapViewer.qml), state in quick/track_map_backend.py.
"""

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QVBoxLayout

from ..i18n import tr
from ._common import BaseDialog, UIScaler


class TrackMapViewer(BaseDialog):
    """Track map viewer, optionally opened on a track map file"""

    def __init__(self, parent, filepath: str = "", filename: str = ""):
        from .quick import create_quick_view
        from .quick.track_map_backend import TrackMapBackend

        super().__init__(parent)
        self.set_utility_title(tr("Track Map Viewer"))
        self.backend = TrackMapBackend(self)
        self.view = create_quick_view(self, "TrackMapViewer.qml", {"backend": self.backend})
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.resize(UIScaler.size(70), UIScaler.size(46))
        if filepath and filename:  # opened on a track (driver stats)
            self.backend.load_map(filepath, filename)

    def closeEvent(self, event):
        # QML gone before the backend it binds to (deleted first: created first),
        # and GpuShapes gone before their vertex data is released
        self.view.setSource(QUrl())
        self.backend.release()
        super().closeEvent(event)
