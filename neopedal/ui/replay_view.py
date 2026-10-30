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
Session recorder: telemetry recording & replay control

Qt Quick page (ui/qml/telemetry/SessionRecorder.qml), state in quick/session_recorder_backend.py.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtWidgets import QVBoxLayout

from ..i18n import tr
from ._common import BaseDialog, UIScaler, singleton_dialog


@singleton_dialog("replay", show_error=False)
class ReplayView(BaseDialog):
    """Record shared memory, and replay it through all widgets without the game"""

    def __init__(self, parent):
        from .quick import create_quick_view
        from .quick.session_recorder_backend import SessionRecorderBackend

        super().__init__(parent)
        self.set_utility_title(tr("Session Recorder"))
        self.backend = SessionRecorderBackend(self)
        self.view = create_quick_view(self, "SessionRecorder.qml", {"backend": self.backend})
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.resize(UIScaler.size(50), UIScaler.size(42))

    # Replay loading & section export (lap viewer opens a replay at a lap position, tests)
    @property
    def loader(self):
        return self.backend.loader

    @property
    def export(self):
        return self.backend.export

    def open_file(self, filename: str, on_loaded: Callable[[], None] | None = None):
        """Load replay file in background, then play it (see SessionRecorderBackend.open_file)"""
        self.backend.open_file(filename, on_loaded)

    def refresh(self):
        """Read recording & playback state again"""
        self.backend.refresh()

    def page_minimum_size(self) -> QSize:
        """Page area minimum while shown in app window: transport bar & section row at full width"""
        root = self.view.rootObject()
        width = UIScaler.size(40)
        if root is not None:
            width = max(width, int(root.property("minimumWidth") or 0))
        return QSize(width, 0)

    def focus_page(self):
        """Keys (Space, arrows) to page: dialog shown as window gives them to its first control"""
        if not self.isVisible():
            return
        self.view.setFocus(Qt.FocusReason.OtherFocusReason)
        root = self.view.rootObject()
        if root is not None:
            root.forceActiveFocus()

    def hideEvent(self, event):
        self.backend.page_hidden()
        super().hideEvent(event)

    def showEvent(self, event):
        self.backend.page_shown()
        super().showEvent(event)
        if not event.spontaneous():  # page shown (not app window restored): after focus given by dialog show
            QTimer.singleShot(0, self, self.focus_page)

    def free_page(self):
        """Replay loading stopped, QML gone before the backend it binds to; replay & recording keep running"""
        self.view.setSource(QUrl())
        self.backend.release()

    def closeEvent(self, event):
        self.release_page()
        super().closeEvent(event)
