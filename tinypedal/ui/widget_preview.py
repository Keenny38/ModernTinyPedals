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
Live widget preview for widget config dialog
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from importlib import import_module

from PySide6.QtCore import QBasicTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QCheckBox, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..i18n import tr, trm
from ..setting import Setting
from ._common import UIScaler

logger = logging.getLogger(__name__)


class _PreviewUser:
    """User presets, with edited (unsaved) widget setting"""

    def __init__(self, user, widget_name: str, widget_setting: dict):
        self._user = user
        self.setting = {**user.setting, widget_name: widget_setting}

    def __getattr__(self, name):
        return getattr(self._user, name)


class PreviewSetting:
    """Setting proxy for preview: reads edited values, never saves"""

    def __init__(self, config: Setting, widget_name: str, widget_setting: dict):
        self._cfg = config
        self.user = _PreviewUser(config.user, widget_name, widget_setting)

    def __getattr__(self, name):
        return getattr(self._cfg, name)

    def save(self, *args, **kwargs):
        """Never save preview setting"""


def render_widget(config: Setting, widget_name: str, widget_setting: dict) -> QPixmap:
    """Render widget with edited setting to pixmap"""
    module = import_module(f"tinypedal.widget.{widget_name}")
    widget = module.Realtime(PreviewSetting(config, widget_name, widget_setting), widget_name)
    try:
        widget.adjustSize()
        return widget.grab()
    finally:
        widget.deleteLater()


class WidgetPreview(QWidget):
    """Live preview panel, refresh when edited values change"""

    REFRESH_MS = 400

    def __init__(self, parent, config: Setting, widget_name: str, read_values: Callable[[], dict | None]):
        """
        Args:
            config: app setting.
            widget_name: widget name.
            read_values: return edited widget setting, or None if any value is invalid.
        """
        super().__init__(parent)
        self._config = config
        self._widget_name = widget_name
        self._read_values = read_values
        self._last_values: dict | None = None
        self._timer = QBasicTimer()

        self.checkbox = QCheckBox(tr("Live Preview"))
        self.checkbox.setChecked(True)
        self.checkbox.toggled.connect(self.toggle)

        self.label_preview = QLabel(self)
        self.label_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_preview.setObjectName("widgetPreview")

        self.scroll = QScrollArea(self)
        self.scroll.setWidget(self.label_preview)
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(UIScaler.size(6))
        self.scroll.setMaximumHeight(UIScaler.size(14))

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.checkbox)
        layout.addWidget(self.scroll)
        self.setLayout(layout)
        self.toggle(True)

    def toggle(self, enabled: bool):
        """Enable or disable preview"""
        self.scroll.setVisible(enabled)
        if enabled:
            self._last_values = None
            self.refresh()
            self._timer.start(self.REFRESH_MS, self)
        else:
            self._timer.stop()

    def timerEvent(self, event):
        """Refresh periodically"""
        self.refresh()

    def refresh(self):
        """Render preview if values changed"""
        values = self._read_values()
        if values is None:
            self.label_preview.setText(tr("Invalid value, preview not updated"))
            return
        if values == self._last_values:
            return
        self._last_values = values
        try:
            pixmap = render_widget(self._config, self._widget_name, values)
        except Exception as error:  # show error instead of breaking config dialog
            logger.debug("Preview error: %s", error, exc_info=True)
            self.label_preview.setText(trm(f"Preview not available: {error}"))
            return
        self.label_preview.setPixmap(pixmap)

    def closeEvent(self, event):
        """Stop refresh"""
        self._timer.stop()
        super().closeEvent(event)
