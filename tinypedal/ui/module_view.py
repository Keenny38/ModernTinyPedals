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
Modules page: data modules as cards (what each computes, state, overlays depending on it), search & filter

Qt Quick page (qml/Modules.qml), state & actions in quick/module_backend.py. The QML page is created
when first shown. sort_key lives here (imported by many pages): this module imports nothing heavy.
"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QVBoxLayout, QWidget

if TYPE_CHECKING:
    from PySide6.QtQuickWidgets import QQuickWidget

    from ..module_control import ModuleControl


def sort_key(text: str) -> str:
    """Alphabetical sort key in any language: ignore case & accents (é = e)"""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


class ModuleList(QWidget):
    """Modules page

    Args:
        module_control: module control.
        widget_control: widget control (overlays depending on each module), wctrl if not set.
    """

    def __init__(self, parent, module_control: ModuleControl, widget_control: ModuleControl | None = None):
        from ..module_control import wctrl
        from .quick.module_backend import ModuleBackend

        super().__init__(parent)
        self.module_control = module_control
        self.backend = ModuleBackend(
            self, module_control, widget_control or wctrl, self.open_config, self.confirm, self.show_log,
            self.reset_data,
        )
        self.view: QQuickWidget | None = None  # see ensure_view
        self._creating = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def ensure_view(self) -> QQuickWidget | None:
        """QML page, created on first use"""
        if self.view is None and not self._creating:
            from .quick import create_quick_view

            self._creating = True  # page shown again while QML loads: one page only
            try:
                view = create_quick_view(self, "Modules.qml", {"backend": self.backend}, samples=0)
            finally:
                self._creating = False
            view.setAcceptDrops(False)  # preset & plugin files dropped go to main window
            self._layout.addWidget(view)
            view.show()  # child added to a shown page is not shown by itself
            self.setFocusProxy(view)
            self.view = view
        return self.view

    def showEvent(self, event):
        self.ensure_view()
        self.backend.refresh()  # overlays switched on other pages: who depends on what
        self.backend.loadDependenciesLater()
        super().showEvent(event)

    @Slot(bool)  # type: ignore[operator]
    def refresh(self, *_):
        """Setting, preset or module state changed elsewhere (hotkey, tray, other page)"""
        self.backend.refresh()

    def open_config(self, name: str):
        from functools import partial

        from ..const_file import ConfigType
        from ..setting import cfg
        from .config import UserConfig

        _dialog = UserConfig(
            parent=self,
            key_name=name,
            preset_name=cfg.filename.setting,
            config_type=ConfigType.MODULE,
            user_setting=cfg.user.setting,
            default_setting=cfg.default.setting,
            reload_func=partial(self.reload_module, name),
        )
        _dialog.open()

    def reload_module(self, name: str):
        """Config saved: module restarted, its card updated (page may be gone after language change)"""
        import shiboken6

        self.module_control.reload(name)
        if shiboken6.isValid(self):
            self.backend.refresh()

    def confirm(self, text: str) -> bool:
        from PySide6.QtWidgets import QMessageBox

        from ..i18n import tr

        answer = QMessageBox.question(
            self, tr("Confirm"), text,
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            defaultButton=QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def show_log(self):
        from .log_info import LogInfo

        LogInfo(self.window()).show()

    def reset_data(self, method: str):
        """Reset saved data (delta best, fuel delta...): asked first, see menu.ResetDataMenu"""
        from ..i18n import tr
        from .menu import ResetDataMenu

        menu = ResetDataMenu(tr("Reset Data"), self.window())
        try:
            getattr(menu, method)()
        finally:
            menu.deleteLater()
