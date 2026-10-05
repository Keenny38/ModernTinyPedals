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
Spotter Widget, modern design

Classic side bars in theme colors (warning, then loss color when critical), rounded ends that
follow global corner roundness (see restyle module).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ..spotter import Realtime as Classic
from .base import DEFAULT_CORNER_SCALE
from .draw import rounded
from .restyle import Restyled, restyled_options


class Realtime(Restyled, Classic):
    """Draw widget"""

    options = restyled_options("spotter")
    color_tokens = {
        "bar_color_nearby": "warning",
        "bar_color_critical": "negative",
        "bar_background_color": "surface_raised",
    }

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        style = self.cfg.user.config["overlay_style"]
        corner = min(max(float(style.get("corner_radius_scale", DEFAULT_CORNER_SCALE)), 0.0), 0.5)
        self.bar_radius = self.bar_width / 2 * min(corner / DEFAULT_CORNER_SCALE, 1.0)

    def fill_bar(self, painter: QPainter, rect: QRectF, color: Any):
        """Bar part, rounded ends"""
        rounded(painter, rect, self.bar_radius, color)
