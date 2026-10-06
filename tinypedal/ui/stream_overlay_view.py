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
Stream overlays: browser sources for OBS Studio, Streamlabs, XSplit, vMix... (see stream_overlay)

Qt Quick page (ui/qml/StreamOverlays.qml), state & actions in quick/stream_backend.py.
"""

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QVBoxLayout

from ..i18n import tr
from ._common import BaseDialog, UIScaler


class StreamOverlaysView(BaseDialog):
    """Stream overlays page"""

    def __init__(self, parent):
        from .quick import create_quick_view
        from .quick.stream_backend import StreamOverlaysBackend

        super().__init__(parent)
        self.set_utility_title(tr("Stream Overlays"))
        self.setMinimumSize(UIScaler.size(48), UIScaler.size(30))
        self.backend = StreamOverlaysBackend(self)
        self.view = create_quick_view(self, "StreamOverlays.qml", {"backend": self.backend}, samples=0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.resize(UIScaler.size(80), UIScaler.size(56))

    def showEvent(self, event):
        self.backend.page_shown()
        super().showEvent(event)

    def hideEvent(self, event):
        self.backend.page_hidden()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.backend.release()
        self.view.setSource(QUrl())  # QML bindings never read a deleted backend
        super().closeEvent(event)
