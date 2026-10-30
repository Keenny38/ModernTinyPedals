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
Track & pace notes editor

Qt Quick page (ui/qml/telemetry/TrackNotesEditor.qml), state in quick/track_notes_backend.py: notes table, track map
with the place of each note (as Track Map Viewer), notes file opened, saved (Ctrl+S: same file) or saved as.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QVBoxLayout

from ..i18n import tr
from ._common import BaseDialog, UIScaler


class TrackNotesEditor(BaseDialog):
    """Track & pace notes editor page: unsaved changes marked on page title & asked on close"""

    def __init__(self, parent):
        from .quick import create_quick_view
        from .quick.track_notes_backend import TrackNotesBackend

        super().__init__(parent)
        self.set_utility_title(tr("Track Notes Editor"))
        self.backend = TrackNotesBackend(self)
        self.backend.modifiedChanged.connect(self.refresh_modified)
        self.view = create_quick_view(self, "TrackNotesEditor.qml", {"backend": self.backend})
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        # Undo & redo of this page only (a QML shortcut also matched while another page of app window was shown),
        # text fields keep their own undo (shortcut override)
        for keys, slot in ((QKeySequence.StandardKey.Undo, self.backend.undo),
                           (QKeySequence.StandardKey.Redo, self.backend.redo),
                           (QKeySequence("Ctrl+Shift+Z"), self.backend.redo)):
            QShortcut(QKeySequence(keys), self, slot)
        self.resize(UIScaler.size(84), UIScaler.size(48))

    def is_modified(self) -> bool:
        return self.backend.is_modified()

    def set_unmodified(self):
        """Changes dropped (tests, page closed without asking)"""
        self.backend.set_modified(False)

    def confirm_discard(self) -> bool:
        """Changes saved, discarded or kept (Cancel, saving failed): True to close"""
        return self.backend.confirm_discard()

    def save_action(self) -> Callable[[], object] | None:
        """Ctrl+S: saved to the open file (file name asked for new notes only), page kept open"""
        return self.backend.save

    def showEvent(self, event):
        self.backend.page_shown()
        super().showEvent(event)

    def hideEvent(self, event):
        self.backend.page_hidden()
        super().hideEvent(event)

    def reject(self):
        """Esc: closed like Close (unsaved changes asked)"""
        self.close()

    def closeEvent(self, event):
        """Unsaved changes asked first (Cancel or saving failed: page kept open). QDialog.closeEvent not called:
        it would call reject(), closing again (ignored as nested: page left open)"""
        if not self._page_released and not self.confirm_discard():
            event.ignore()
            return
        self.release_page()
        event.accept()

    def free_page(self):
        self.view.setSource(QUrl())  # QML gone before the backend it binds to, GPU shapes before vertex data
        self.backend.release()
