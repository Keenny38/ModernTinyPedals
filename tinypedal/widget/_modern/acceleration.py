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
Acceleration Widget, modern design

One column per speed range: last (or running) acceleration time, best time, difference.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ... import units
from ...api_control import api
from ...const_common import MAX_SECONDS
from ..acceleration import AccelTimer
from .base import CENTER, DASH, ModernOverlay
from .draw import panel, rounded


class Realtime(ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "bar_width", "speed_drop_threshold", "decimal_places_timer", "decimal_places_delta",
        *(f"speed_range_{index}_{end}" for index in range(1, 11) for end in ("start", "end")),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        self.char_width = max(int(wcfg["bar_width"]), 4)
        self.dec_timer = max(int(wcfg["decimal_places_timer"]), 0)
        self.dec_delta = max(int(wcfg["decimal_places_delta"]), 0)
        speed_drop = max(wcfg["speed_drop_threshold"], 0)
        self.timers = tuple(
            AccelTimer(wcfg[f"speed_range_{index}_start"], wcfg[f"speed_range_{index}_end"], speed_drop)
            for index in range(1, 11) if wcfg[f"speed_range_{index}_end"] > 0
        )
        unit_speed = units.set_unit_speed(self.cfg.units["speed_unit"])
        self.labels = tuple(f"{unit_speed(timer.speed_start):.0f}-{unit_speed(timer.speed_end):.0f}" for timer in self.timers)
        count = max(len(self.timers), 1)
        pad = unit * 0.3
        gap = unit * 0.14
        cell_w = max(self.text_width("value", "8" * self.char_width), max((self.text_width("small", label) for label in self.labels), default=0)) + unit * 0.6
        heights = (unit * 1.0, unit * 1.45, unit * 1.45, unit * 1.2)
        reversed_layout = wcfg["layout"] != 0
        self.cells = []
        top = pad
        for height in heights:
            row = []
            for slot in range(count):
                column = count - 1 - slot if reversed_layout else slot
                row.append(QRectF(pad + column * (cell_w + gap), top, cell_w, height))
            self.cells.append(row)
            top += height + gap
        self.set_size(pad * 2 + cell_w * count + gap * (count - 1), top - gap + pad)

    def paint_static(self, painter: QPainter):
        theme = self.theme
        panel(painter, QRectF(self.rect()), theme, self.radius(0.5), self.depth_effects)
        for slot, label in enumerate(self.labels):
            column = QRectF(self.cells[1][slot].topLeft(), self.cells[3][slot].bottomRight())
            rounded(painter, column, self.radius(0.3), theme.tint(theme.surface_alt, 170))
            self.draw_text(painter, self.cells[0][slot], label, "small", theme.text_muted, CENTER, elide=False)

    def paint(self, painter: QPainter):
        theme = self.theme
        for slot, (last, active, best, delta) in enumerate(self.state):
            if active:
                rounded(painter, self.cells[1][slot], self.radius(0.3), theme.highlight)
            self.draw_text(painter, self.cells[1][slot], last, "value", theme.accent if active else theme.text, CENTER)
            self.draw_text(painter, self.cells[2][slot], best, "value", theme.positive, CENTER)
            color = theme.text_faint if delta == DASH else (theme.negative if delta.startswith("+") else theme.positive)
            self.draw_text(painter, self.cells[3][slot], delta, "small", color, CENTER)

    def time_text(self, value: float) -> str:
        """Acceleration time"""
        if MAX_SECONDS > value > 0:
            return f"{value:.{self.dec_timer}f}"[:self.char_width]
        return DASH

    def timerEvent(self, event):
        """Update when vehicle on track"""
        reset = api.read.engine.gear() < 0
        speed = api.read.vehicle.speed()
        elapsed = api.read.timing.elapsed()
        values = []
        for timer in self.timers:
            if reset:
                timer.reset()
            timer.update(speed, elapsed)
            active = timer.start_time > 0
            delta = timer.delta
            delta_text = f"{delta:+.{self.dec_delta}f}"[:self.char_width] if delta else DASH
            values.append((self.time_text(timer.timer if active else timer.valid), active, self.time_text(timer.best), delta_text))
        self.refresh(tuple(values))
