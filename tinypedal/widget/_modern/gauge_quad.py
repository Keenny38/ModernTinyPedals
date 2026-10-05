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
Modern overlay design: four wheel gauges base (tyre load, ride height, slip...)

One tile per wheel: value text over a gauge growing outward from car center, gauge color
by state (normal, warning). Subclass reads values & chooses gauge level and color.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPainter

from .base import ModernOverlay
from .draw import fraction
from .quad import QuadMixin, Section, Tile

GAUGE_ALPHA = 120
GAUGE_WIDTH = 4.0  # tile width, in unit


class GaugeQuad(QuadMixin, ModernOverlay):
    """Four wheel gauges"""

    label = ""  # section label (English)
    sample = "888"  # widest value text, whole part (decimal places added)
    common_options = ("font_size", "decimal_places")

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        self.decimals = max(int(self.wcfg.get("decimal_places", 0)), 0)
        self.setup()
        sample = f"{self.sample}.{'8' * self.decimals}" if self.decimals else self.sample
        section = Section(widget_name, self.label, sample, min_width=GAUGE_WIDTH)
        self.set_size(*self.build_quads([section], center_width=self.center_width(), show_labels=bool(self.label)))

    def setup(self):
        """Read options (override)"""

    def center_width(self) -> float:
        """Width of center column between left & right tiles, 0 = none (override)"""
        return 0.0

    def read(self) -> tuple:
        """4 wheel tiles (override)"""
        return ()

    def gauge(self, value: float, text_value: float, level: float, color: QColor, warning: bool = False,
              mark: float = -1.0) -> Tile:
        """Tile of gauge value: text, level 0-1, gauge color, mark 0-1 (-1 = none)"""
        theme = self.theme
        text = f"{text_value:.{self.decimals}f}"
        return Tile((text,), colors=(theme.negative if warning else theme.text,),
                    level=fraction(level), level_color=theme.tint(color, GAUGE_ALPHA),
                    mark=fraction(mark) if mark >= 0 else -1.0)

    def paint_static(self, painter: QPainter):
        self.paint_quads_static(painter)

    def paint(self, painter: QPainter):
        self.draw_quads(painter, (self.state,))

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.refresh(self.read())
