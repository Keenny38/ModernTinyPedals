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
DRS Widget, modern design

DRS pill: dim when not available, outlined when available, green when allowed, bright when
activated.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter, QPen

from ...api_control import api
from .base import CENTER, ModernOverlay
from .draw import readable_on, rounded


class Realtime(ModernOverlay):
    """Draw widget"""

    options = ("font_size", "drs_text")

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        self.unit = self.unit * 0.5  # font size 30 by default
        self.add_font("drs", 1.6, "bold", spacing=104)
        self.text = self.wcfg["drs_text"]
        width = self.text_width("drs", self.text) + self.unit * 2.2
        height = self.metrics["drs"].capHeight() + self.unit * 1.8
        self.set_size(width, height)
        self.rect_pill = QRectF(self.unit * 0.2, self.unit * 0.2, width - self.unit * 0.4, height - self.unit * 0.4)

    def paint(self, painter: QPainter):
        theme = self.theme
        state = self.state
        pill = self.rect_pill
        radius = pill.height() / 2 * min(self.corner, 1.0)
        if state == 3:  # activated
            rounded(painter, pill, radius, theme.positive)
            color = readable_on(theme.positive)
        elif state == 2:  # allowed
            rounded(painter, pill, radius, theme.tint(theme.positive, 90))
            color = theme.positive
        else:
            rounded(painter, pill, radius, theme.surface)
            color = theme.text if state == 1 else theme.text_faint
            if state == 1:  # available: outlined
                pen = QPen(theme.positive, max(self.unit * 0.15, 1.5))
                painter.setPen(pen)
                painter.drawRoundedRect(pill.adjusted(1, 1, -1, -1), radius, radius)
        self.draw_text(painter, pill, self.text, "drs", color, CENTER, elide=False)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.refresh(api.read.switch.drs_status())
