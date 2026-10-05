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
Tyre temperature trend Widget, modern design

One tile per tyre (front left, front right, rear left, rear right): current surface temperature
on heatmap colored pill, line chart of trend colored by heatmap, dashed optimal temperature.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen

from ...i18n import tr_overlay as tr
from ..tyre_temp_trend import DASH, WHEELS, TyreTrendMixin
from .base import CENTER, LEFT, ModernOverlay
from .draw import panel, readable_on, rounded


class Realtime(TyreTrendMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "display_width", "display_height", "trend_duration", "show_trend_by_lap", "number_of_laps",
        "show_optimal_temperature", "show_degree_sign", "enable_heatmap_auto_matching", "heatmap_name",
    )
    update_while_hidden = True  # trend kept while hidden

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        self.setup_trend()
        wcfg = self.wcfg
        unit = self.unit
        theme = self.theme
        pad = unit * 0.3
        inner = unit * 0.35
        gap = unit * 0.25
        self.labels = tuple(tr(label) for label in WHEELS)
        self.pill_w = self.text_width("small", f"888{self.sign}") + unit * 0.5
        label_w = max(self.text_width("label", label) for label in self.labels)
        chart_w = max(float(wcfg["display_width"]), label_w + unit * 0.4 + self.pill_w, unit * 3)
        chart_h = max(float(wcfg["display_height"]), unit * 1.2)
        header_h = unit * 1.25
        tile_w = chart_w + inner * 2
        tile_h = header_h + chart_h + inner
        self.tiles = []
        for wheel in range(4):
            left = pad + (tile_w + gap) * (wheel % 2)
            top = pad + (tile_h + gap) * (wheel // 2)
            tile = QRectF(left, top, tile_w, tile_h)
            label = QRectF(left + inner, top, label_w, header_h)
            pill_h = unit * 0.95
            pill = QRectF(tile.right() - inner - self.pill_w, top + (header_h - pill_h) / 2, self.pill_w, pill_h)
            chart = QRectF(left + inner, top + header_h, chart_w, chart_h)
            self.tiles.append((tile, label, pill, chart))
        self.chart_rects = tuple(chart.adjusted(0, unit * 0.1, 0, -unit * 0.1) for _, _, _, chart in self.tiles)
        self.line_width = max(unit * 0.11, 1.5)
        self.pen_optimal = QPen(theme.tint(theme.text, 110), max(unit * 0.06, 1.0), Qt.PenStyle.DashLine)
        self.set_size(pad * 2 + tile_w * 2 + gap, pad * 2 + tile_h * 2 + gap)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.refresh(self.read_trend(self.chart_rects))

    def paint_static(self, painter: QPainter):
        theme = self.theme
        panel(painter, QRectF(self.rect()), theme, self.radius(0.5), self.depth_effects)
        for wheel, (tile, label, _, chart) in enumerate(self.tiles):
            rounded(painter, tile, self.radius(0.3), theme.tint(theme.surface_alt, 200))
            rounded(painter, chart, self.radius(0.2), theme.tint(theme.surface, 160))
            self.draw_text(painter, label, self.labels[wheel], "label", theme.text_muted, LEFT)

    def paint(self, painter: QPainter):
        theme = self.theme
        _, texts, colors = self.state
        for wheel, (_, _, pill, _) in enumerate(self.tiles):
            fill = colors[wheel]
            text = texts[wheel]
            if fill is not None:
                rounded(painter, pill, self.radius(0.25), fill)
                self.draw_text(painter, pill, text, "small", readable_on(fill), CENTER, elide=False)
            else:
                self.draw_text(painter, pill, text if text else DASH, "small", theme.text_faint, CENTER, elide=False)
            chart = self.charts[wheel]
            rect = self.chart_rects[wheel]
            if chart.optimal >= 0:
                painter.setPen(self.pen_optimal)
                painter.drawLine(QPointF(rect.left(), chart.optimal), QPointF(rect.right(), chart.optimal))
            if chart.pen is not None:
                painter.setPen(chart.pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                for line in chart.lines:
                    painter.drawPolyline(line)
