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
Widget drawn with edited (unsaved) options, for pictures of Overlays & Overlay Options pages
"""

from __future__ import annotations

import logging
from importlib import import_module

from PySide6.QtGui import QPixmap

from ..setting import Setting

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
    from ..widget._modern import modern_module, uses_modern_design

    preview_config = PreviewSetting(config, widget_name, widget_setting)
    if uses_modern_design(preview_config, widget_name):
        module = modern_module(widget_name)  # classic widget code not loaded
    else:
        module = import_module(f"tinypedal.widget.{widget_name}")
    widget = module.Realtime(preview_config, widget_name)
    try:
        widget.adjustSize()
        return widget.grab()
    finally:
        widget.deleteLater()
