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
Overlays page: every overlay as a card with its preview (or a compact row), search & filters

Qt Quick page (qml/Overlays.qml), state & actions in quick/overlay_backend.py. The QML page is
created when first shown: no QML engine started at launch while another page is shown.
"""

from __future__ import annotations

from functools import partial

import shiboken6
from PySide6.QtCore import Slot
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QMessageBox, QVBoxLayout, QWidget

from ..const_file import ConfigType
from ..i18n import tr
from ..module_control import ModuleControl, wctrl
from ..setting import cfg
from .config import UserConfig
from .quick.overlay_backend import OverlayBackend


class OverlayView(QWidget):
    """Overlays page"""

    def __init__(self, parent, module_control: ModuleControl = wctrl):
        super().__init__(parent)
        self.module_control = module_control
        self.backend = OverlayBackend(self, module_control, self.open_config, self.confirm, self.show_log)
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
                view = create_quick_view(self, "Overlays.qml", {"backend": self.backend}, samples=0)
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
        self.backend.set_active(True)
        super().showEvent(event)

    def hideEvent(self, event):
        self.backend.set_active(False)  # no preview rendered while racing with window hidden
        super().hideEvent(event)

    @Slot(bool)  # type: ignore[operator]
    def refresh(self, *_):
        """Setting, preset or overlay state changed elsewhere (hotkey, tray, other page)"""
        self.backend.refresh()

    def open_config(self, name: str):
        _dialog = UserConfig(
            parent=self,
            key_name=name,
            preset_name=cfg.filename.setting,
            config_type=ConfigType.WIDGET,
            user_setting=cfg.user.setting,
            default_setting=cfg.default.setting,
            reload_func=partial(self.reload_overlay, name),
        )
        _dialog.open()

    def reload_overlay(self, name: str):
        """Config saved: overlay restarted, its card updated (page may be gone after language change)"""
        self.module_control.reload(name)
        if shiboken6.isValid(self):
            self.backend.update_overlay(name)
            self.backend.invalidate_preview(name)

    def confirm(self, text: str) -> bool:
        answer = QMessageBox.question(
            self, tr("Confirm"), text,
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            defaultButton=QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def show_log(self):
        from .log_info import LogInfo

        LogInfo(self.window()).show()
