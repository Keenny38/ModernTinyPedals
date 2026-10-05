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
Race calculator: fuel & tyre strategy of a race in one page

Qt Quick page (qml/RaceCalculator.qml), state & actions in quick/race_backend.py: race setup &
key figures & strategy timeline on top, then tabs. Fuel tab: lap & consumption inputs (folding
sections), pit stop plan, details, scenarios, consumption history. Tyre tab: tyre wear & rules,
tyre plan with one row per stint, tyre stock. Team tab: stints of every driver of the car read
from the game. This page hosts the QML view: dialogs, toasts & undo history.

Replaces the former fuel calculator & tyre strategy planner tools (see tools_view.RENAMED_TOOLS).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QUrl
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QVBoxLayout

from ..i18n import tr
from ..userfile.tyre_strategy import DEFAULT_TYRE_SET
from ._common import BaseEditor, UIScaler
from .quick.race_backend import RaceBackend
from .toast import show_toast

MIN_PAGE = 46  # narrowest page width (in lines): race setup & key figures on two rows


class RaceCalculator(BaseEditor):
    """Race calculator (fuel & tyres)"""

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Race Calculator"))
        self.view: QQuickWidget | None = None  # see ensure_view
        self._creating = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.backend = RaceBackend(self, self)
        self.enable_undo(self.backend.capture_state, self.backend.restore_state)  # inputs & tyre plan edits
        self.setMinimumSize(UIScaler.size(MIN_PAGE), UIScaler.size(26))
        self.resize(UIScaler.size(80), UIScaler.size(50))
        self.reset_undo()  # history starts with the page shown

    def ensure_view(self) -> QQuickWidget | None:
        """QML page, created when first shown (backend works without it)"""
        if self.view is None and not self._creating:
            from .quick import create_quick_view

            self._creating = True  # page shown again while QML loads: one page only
            try:
                view = create_quick_view(self, "RaceCalculator.qml", {"backend": self.backend}, samples=0)
            finally:
                self._creating = False
            self._layout.addWidget(view)
            view.show()  # child added to a shown page is not shown by itself
            self.setFocusProxy(view)
            self.view = view
        return self.view

    def showEvent(self, event):
        self.ensure_view()
        self.backend.set_active(True)
        super().showEvent(event)

    def hideEvent(self, event):
        self.backend.set_active(False)
        super().hideEvent(event)

    def saving(self):
        """Save tyre plan to a file (Ctrl+S, asked before closing)"""
        self.backend.saveTyrePlan()

    def confirm_discard(self) -> bool:
        """Tyre plan kept automatically between sessions: nothing to lose"""
        return True

    def closeEvent(self, event):
        self.backend.release()
        super().closeEvent(event)
        if event.isAccepted() and self.view is not None:  # QML gone before the backend it binds to
            view, self.view = self.view, None
            view.setSource(QUrl())
            view.deleteLater()

    # Race host: dialogs & toasts of the backend
    def warn(self, text: str):
        QMessageBox.warning(self, tr("Error"), text)

    def toast(self, text: str):
        show_toast(self, text)

    def confirm(self, text: str) -> bool:
        return self.confirm_operation(message=text)

    def open_file(self, directory: str, file_filter: str) -> str:
        return QFileDialog.getOpenFileName(self, dir=directory, filter=file_filter)[0]

    def save_file(self, directory: str, file_filter: str) -> str:
        return QFileDialog.getSaveFileName(self, dir=directory, filter=file_filter)[0]

    def ask_text(self, title: str, label: str, text: str) -> tuple[str, bool]:
        return QInputDialog.getText(self, title, label, text=text)

    def open_compound_config(self, name: str, user_setting: dict, reload: Callable):
        """Starting tread & wear per stint of a compound"""
        from .config import UserConfig

        _dialog = UserConfig(
            self,
            key_name=name,
            preset_name="Tyre Compound",
            config_type="",
            user_setting=user_setting,
            default_setting=DEFAULT_TYRE_SET,
            reload_func=reload,
        )
        _dialog.open()

    def is_page_visible(self) -> bool:
        return self.isVisible()
