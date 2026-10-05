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
Delta graph Widget, modern design

Delta to reference lap along lap distance: loss area above zero line in loss color, gain
area below in gain color, previous lap as faint line, current position mark & reading.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen

from ...i18n import tr_overlay as tr
from .._race_aids import finite
from ..delta_graph import DeltaGraphMixin
from .base import LEFT, RIGHT, ModernOverlay
from .draw import panel, rounded


class Realtime(DeltaGraphMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "display_width", "display_height", "deltabest_source", "delta_display_range",
        "decimal_places", "show_delta_reading", "show_previous_lap", "show_position_mark",
    )
    update_while_hidden = True  # lap trace kept while hidden

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        theme = self.theme
        pad = unit * 0.35
        self.show_reading = bool(wcfg["show_delta_reading"])
        self.label = f"{tr('Delta')} {tr(wcfg['deltabest_source'])}"
        decimals = min(max(int(wcfg["decimal_places"]), 0), 3)
        sample = "+88." + "8" * decimals if decimals else "+88"
        header_w = self.text_width("label", self.label) + unit * 0.8 + self.text_width("value", sample)
        chart_w = max(float(wcfg["display_width"]), header_w, unit * 4)
        chart_h = max(float(wcfg["display_height"]), unit * 1.5)
        header_h = unit * 1.3 if self.show_reading else 0.0
        self.rect_header = QRectF(pad + unit * 0.2, pad, chart_w - unit * 0.4, header_h)
        top = pad + header_h + (unit * 0.15 if header_h else 0.0)
        self.rect_chart_box = QRectF(pad, top, chart_w, chart_h)
        inset = unit * 0.2
        self.setup_graph(self.rect_chart_box.adjusted(0, inset, 0, -inset))
        self.set_size(chart_w + pad * 2, top + chart_h + pad)

        self.pen_line = QPen(theme.text_dim, max(unit * 0.09, 1.2))
        self.pen_previous = QPen(theme.tint(theme.text_faint, 170), max(unit * 0.08, 1.0))
        self.pen_mark = QPen(theme.accent, max(unit * 0.1, 1.5))
        self.fill_gain = theme.tint(theme.positive, 120)
        self.fill_loss = theme.tint(theme.negative, 120)
        self.dot = max(unit * 0.2, 2.5)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.refresh(self.read_graph())

    def paint_static(self, painter: QPainter):
        theme = self.theme
        panel(painter, QRectF(self.rect()), theme, self.radius(0.5), self.depth_effects)
        rounded(painter, self.rect_chart_box, self.radius(0.3), theme.tint(theme.surface_alt, 200))
        chart = self.chart
        zero = chart.center().y()
        painter.fillRect(QRectF(chart.left(), zero - 0.5, chart.width(), 1), theme.tint(theme.text, 60))
        if self.show_reading:
            self.draw_text(painter, self.rect_header, self.label, "label", theme.text_muted, LEFT)

    def paint(self, painter: QPainter):
        theme = self.theme
        shapes = self.shapes
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self.pen_previous)
        for line in shapes.previous:
            painter.drawPolyline(line)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.fill_gain)
        for area in shapes.gain:
            painter.drawPolygon(area)
        painter.setBrush(self.fill_loss)
        for area in shapes.loss:
            painter.drawPolygon(area)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self.pen_line)
        for line in shapes.line:
            painter.drawPolyline(line)
        _, mark_x, mark_y, delta = self.state
        if self.show_mark:
            chart = self.rect_chart_box
            painter.setPen(self.pen_mark)
            painter.drawLine(QPointF(mark_x, chart.top()), QPointF(mark_x, chart.bottom()))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.accent)
            painter.drawEllipse(QPointF(mark_x, mark_y), self.dot, self.dot)
        if self.show_reading:
            if finite(delta) and delta:
                color = theme.negative if delta > 0 else theme.positive
            else:
                color = theme.text
            self.draw_text(painter, self.rect_header, self.delta_text(delta), "value", color, RIGHT, elide=False)
