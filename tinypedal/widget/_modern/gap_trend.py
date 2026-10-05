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
Gap trend Widget, modern design

Two rows (car ahead, car behind): gap, gap change per lap in gain or loss color (catching up,
being caught), gap of each lap as a small line chart in same color.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPen

from ...i18n import tr_overlay as tr
from ..gap_trend import BAD, GOOD, NEUTRAL, GapTrendMixin, TrendChart, trend_chart
from .base import ModernOverlay
from .draw import panel, rounded
from .table import CENTER, LEFT, RIGHT, TEXT, Cell, Column, Row, TableMixin


class Realtime(GapTrendMixin, TableMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "number_of_laps", "decimal_places", "show_gaps_in_class", "show_driver_name",
        "show_closing_rate", "show_trend_chart",
    )
    update_while_hidden = True  # gap history kept while hidden

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        self.setup_gaps()
        unit = self.unit
        theme = self.theme
        self.labels = (tr("Ahead"), tr("Behind"))
        decimals = f".{'8' * self.decimals}" if self.decimals else ""
        columns = [Column("label", max(self.text_width("label", label) for label in self.labels), LEFT)]
        if self.show_name:
            columns.append(Column("name", unit * 6.5, LEFT, "Driver"))
        columns.append(Column("gap", self.text_width("value", self.widest("value", (f"888{decimals}", "+88L"))),
                              RIGHT, "Gap"))
        if self.show_rate:
            columns.append(Column("rate", self.text_width("dim", "+88.88"), RIGHT, "Per lap"))
        if self.show_chart:
            columns.append(Column("chart", unit * 5.0, CENTER, "Trend"))
        self.table = self.build_table(columns, 1.45, header=True)
        self.set_size(self.table.width, self.table.height(2))
        self.column_x = {column.key: (left, column.width) for column, left in zip(self.table.columns, self.table.x)}
        self.name_width = self.column_x["name"][1] if self.show_name else 0.0

        line_width = max(unit * 0.09, 1.2)
        self.line_colors = {GOOD: theme.positive, BAD: theme.negative, NEUTRAL: theme.text_dim}
        self.pens = {meaning: QPen(color, line_width) for meaning, color in self.line_colors.items()}
        self.dot = max(unit * 0.17, 2.0)
        if self.show_chart:
            self.chart_rects = (self.chart_rect(0), self.chart_rect(1))
            self.chart_boxes = tuple(
                rect.adjusted(-self.dot, -self.dot * 0.6, self.dot, self.dot * 0.6) for rect in self.chart_rects)
        self.charts = (TrendChart(), TrendChart())
        self.chart_version = -1
        self.meanings = (NEUTRAL, NEUTRAL)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        rows = self.read_gaps()
        if self.show_chart and self.chart_version != self.version:
            self.chart_version = self.version
            self.charts = tuple(  # type: ignore[assignment]
                trend_chart(values, self.chart_rects[index], self.laps)
                for index, values in enumerate(self.trend_values())
            )
        table_rows = []
        for index, gap in enumerate(rows):
            cells = []
            rate_color = theme.positive if gap.meaning == GOOD else (theme.negative if gap.meaning == BAD else theme.text_dim)
            for column in self.table.columns:
                key = column.key
                if key == "label":
                    cells.append(Cell(TEXT, self.labels[index], "label", theme.text_muted))
                elif key == "name":
                    cells.append(Cell(TEXT, self.elided("dim", gap.name, self.name_width), "dim", theme.text_dim))
                elif key == "gap":
                    cells.append(Cell(TEXT, gap.gap, "value", theme.text))
                elif key == "rate":
                    cells.append(Cell(TEXT, gap.rate, "dim", rate_color))
                else:
                    cells.append(Cell())
            table_rows.append(Row(tuple(cells)))
        self.meanings = (rows[0].meaning, rows[1].meaning)
        self.refresh((self.version, tuple(table_rows), self.meanings))

    def chart_rect(self, row: int) -> QRectF:
        """Chart area of row"""
        left, width = self.column_x["chart"]
        rect = self.table.row_rect(row)
        inset = rect.height() * 0.2
        return QRectF(left, rect.top() + inset, width, rect.height() - inset * 2)

    def paint_static(self, painter: QPainter):
        panel(painter, QRectF(self.rect()), self.theme, self.radius(0.5), self.depth_effects)
        self.draw_header(painter)

    def paint(self, painter: QPainter):
        _, rows, meanings = self.state
        self.draw_rows(painter, rows)
        if not self.show_chart:
            return
        theme = self.theme
        for index, chart in enumerate(self.charts):
            rounded(painter, self.chart_boxes[index], self.radius(0.2), theme.tint(theme.surface, 150))
            painter.setPen(self.pens[meanings[index]])
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for line in chart.lines:
                painter.drawPolyline(line)
            if chart.end is not None:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self.line_colors[meanings[index]])
                painter.drawEllipse(chart.end, self.dot, self.dot)
