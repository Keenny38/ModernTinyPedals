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
Stint timer Widget, modern design

Stat tiles (stint time, laps, countdown to maximum stint in warning colors, fair share), then
one row per driver of the car: driving time, time left to target, thin progress line.
"""

from __future__ import annotations

from math import ceil

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ..stint_timer import MET, OVER, WARNING, StintReading, StintTimerMixin
from .base import ModernOverlay
from .draw import bar, panel
from .stats import Stat, StatsMixin, Value
from .table import LEFT, RIGHT, TEXT, Cell, Column, Row, TableMixin


class Realtime(StintTimerMixin, StatsMixin, TableMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "maximum_stint_minutes", "stint_warning_minutes", "show_stint_laps", "show_stint_countdown",
        "show_driver_times", "number_of_drivers", "minimum_driving_minutes",
    )
    update_while_hidden = True  # driving time counted while hidden

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        self.setup_stint()
        unit = self.unit
        stats = [Stat("stint", "Stint", "88:88:88", "strong")]
        if self.show_laps:
            stats.append(Stat("laps", "Laps", "888"))
        if self.show_countdown:
            stats.append(Stat("countdown", "Max stint", "-88:88:88"))
        if self.show_drivers:
            stats.append(Stat("fair_share", "Fair share", "88:88:88"))
        self.keys = tuple(stat.key for stat in stats)
        time_w = self.text_width("value", "88:88:88")
        name_w = unit * 7.0
        columns = [
            Column("name", name_w, LEFT, "Driver"),
            Column("driven", time_w, RIGHT, "Time"),
            Column("remaining", time_w, RIGHT, "Remaining"),
        ]
        self.table = self.build_table(columns, 1.45, header=True)
        stats_w, stats_h = self.build_stats(stats, min_width=self.table.width - unit * 0.6)
        if stats_w > self.table.width:  # driver names take extra width
            columns[0] = columns[0]._replace(width=name_w + stats_w - self.table.width)
            self.table = self.build_table(columns, 1.45, header=True)
        self.name_width = self.table.columns[0].width
        self.content_width = max(stats_w, self.table.width)
        self.table_top = stats_h - unit * 0.3
        self.line_h = max(unit * 0.1, 1.5)
        self.rows = -1
        self.resize_rows(self.driver_rows())
        self.state = (self.values(StintReading()), ())

    def resize_rows(self, rows: int):
        """Widget height for number of driver rows"""
        if rows == self.rows:
            return
        self.rows = rows
        height = self.table_top + self.table.height(rows) if rows else self.table_top + self.unit * 0.3
        if ceil(height) != self.height() or ceil(self.content_width) != self.width():
            self.set_size(self.content_width, height)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        reading = self.read_stint()
        self.resize_rows(self.driver_rows())
        self.refresh((self.values(reading), self.driver_cells(reading)))

    def values(self, reading: StintReading) -> tuple[Value, ...]:
        """Stat values"""
        theme = self.theme
        values = []
        for key in self.keys:
            if key == "countdown" and reading.countdown_state == OVER:
                values.append(Value(reading.countdown, theme.negative, theme.tint(theme.negative, 70)))
            elif key == "countdown" and reading.countdown_state == WARNING:
                values.append(Value(reading.countdown, theme.warning))
            else:
                text = getattr(reading, key)
                values.append(Value(text, theme.text if key == "stint" else theme.text_dim))
        return tuple(values)

    def driver_cells(self, reading: StintReading) -> tuple:
        """Driver rows: (table row, progress fraction, target met)"""
        if not self.show_drivers:
            return ()
        theme = self.theme
        rows = []
        for driver in reading.drivers[:self.rows]:
            met = driver.state == MET
            cells = (
                Cell(TEXT, self.elided("dim", driver.name, self.name_width), "dim",
                     theme.text if driver.current else theme.text_dim),
                Cell(TEXT, driver.driven, "value", theme.text),
                Cell(TEXT, driver.remaining, "dim", theme.positive if met else theme.text_dim),
            )
            rows.append((Row(cells, player=driver.current), driver.fraction, met))
        return tuple(rows)

    def paint_static(self, painter: QPainter):
        panel(painter, QRectF(self.rect()), self.theme, self.radius(0.5), self.depth_effects)
        self.paint_stats_static(painter, show_panel=False)
        if self.rows:
            painter.translate(0, self.table_top)
            self.draw_header(painter)
            painter.translate(0, -self.table_top)

    def paint(self, painter: QPainter):
        values, drivers = self.state
        self.draw_stats(painter, values)
        if not self.rows:
            return
        theme = self.theme
        painter.translate(0, self.table_top)
        rows = tuple(row for row, _, _ in drivers)
        self.draw_rows(painter, rows + (None,) * (self.rows - len(rows)))
        table = self.table
        for index, (_, fraction, met) in enumerate(drivers):
            if fraction < 0:
                continue
            rect = table.row_rect(index)
            line = QRectF(rect.left() + table.stripe + table.col_gap * 0.5, rect.bottom() - self.line_h * 1.6,
                          rect.width() - table.stripe - table.col_gap, self.line_h)
            bar(painter, line, fraction, theme.positive if met else theme.accent, theme.surface_raised, self.line_h / 2)
        painter.translate(0, -self.table_top)
