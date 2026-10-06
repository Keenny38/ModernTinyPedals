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
Friction circle Widget, modern design

G-G diagram on a round dial: ring at every whole G (labelled), crosshair, ring of maximum
average lateral G, trace of last samples fading with age, glowing dot at current G.
Lateral & longitudinal G under it, with recent peak.
"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen, QPolygonF

from ...i18n import tr_overlay as tr
from ...module_info import minfo
from ...validator import infnan_to_zero as rmnan
from .base import ModernOverlay
from .draw import disc, panel
from .stats import Stat, StatsMixin, Value

TRACE_PARTS = 6  # trace drawn in parts, older parts fainter


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "display_size", "display_radius_g", "show_inverted_orientation", "show_readings",
        "show_trace", "trace_maximum_samples", "show_trace_fade_out", "show_maximum_average_lateral_g_circle",
        "show_reference_circle", "show_center_mark", "show_dot",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        theme = self.theme
        self.add_font("ring", 0.55, "semibold")
        pad = unit * 0.35
        size = max(float(wcfg["display_size"]), unit * 4)
        self.radius_g = max(float(wcfg["display_radius_g"]), 1.0)
        self.scale = size * 0.5 / self.radius_g  # pixels per G
        self.inverted = bool(wcfg["show_inverted_orientation"])
        self.show_trace = bool(wcfg["show_trace"])
        self.trace_fade = bool(wcfg["show_trace_fade_out"])
        self.show_max_circle = bool(wcfg["show_maximum_average_lateral_g_circle"])
        self.show_dot = bool(wcfg["show_dot"])
        self.show_readings = bool(wcfg["show_readings"])
        self.trace: deque[QPointF] = deque(maxlen=max(int(wcfg["trace_maximum_samples"]), 5))

        width = size + pad * 2
        height = size + pad * 2
        if self.show_readings:
            peak = f"{tr('Max')} 8.88"
            stats = [Stat("lat", "Lat. G", "8.88", sub_sample=peak), Stat("long", "Long. G", "8.88", sub_sample=peak)]
            width, height = self.build_stats(stats, show_sub=True, top=size + pad * 1.4, min_width=width - unit * 0.6)
        else:
            self.build_stats([])
        self.plot = QRectF((width - size) / 2, pad, size, size)
        self.center = self.plot.center()
        self.set_size(width, height)

        self.pen_trace = QPen(theme.accent, max(unit * 0.16, 1.5))
        self.pen_trace.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.pen_trace.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.trace_colors = tuple(
            theme.tint(theme.accent, round(255 * (index + 1) / TRACE_PARTS) if self.trace_fade else 220)
            for index in range(TRACE_PARTS)
        )
        self.pen_max = QPen(theme.tint(theme.warning, 190), max(unit * 0.09, 1.2))
        self.pen_max.setDashPattern((4.0, 3.0))
        self.dot = max(unit * 0.3, 3.0)
        self.post_update()

    def post_update(self):
        """Trace starts again"""
        self.trace.clear()
        self.last_g = (0.0, 0.0)

    def to_screen(self, gforce: float, center: float) -> float:
        """G reading as plot coordinate, clamped near plot (non-finite or absurd values never
        reach Qt drawing)"""
        size = self.plot.width()
        return min(max(rmnan(gforce) * self.scale + center, center - size), center + size)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        force = minfo.force
        if self.inverted:  # accel top, brake bottom
            lgt, lat = round(force.lgtGForceRaw, 3), round(-force.latGForceRaw, 3)
        else:  # brake top, accel bottom
            lgt, lat = round(-force.lgtGForceRaw, 3), round(force.latGForceRaw, 3)
        if (lgt, lat) != self.last_g:
            self.last_g = (lgt, lat)
            if self.show_trace:
                self.trace.append(QPointF(self.to_screen(lat, self.center.x()), self.to_screen(lgt, self.center.y())))
        readings = None
        if self.show_readings:
            peak = tr("Max")
            readings = (
                Value(f"{abs(rmnan(lat)):.2f}", sub=f"{peak} {min(abs(rmnan(force.maxLatGForce)), 9.99):.2f}",
                      sub_color=self.theme.warning),
                Value(f"{abs(rmnan(lgt)):.2f}", sub=f"{peak} {min(abs(rmnan(force.maxLgtGForce)), 9.99):.2f}",
                      sub_color=self.theme.warning),
            )
        max_avg = round(rmnan(force.maxAvgLatGForce), 2) if self.show_max_circle else 0.0
        self.refresh((self.last_g, len(self.trace), max_avg, readings))

    def paint_static(self, painter: QPainter):
        theme = self.theme
        wcfg = self.wcfg
        panel(painter, QRectF(self.rect()), theme, self.radius(0.5), self.depth_effects)
        plot = self.plot
        center = self.center
        disc(painter, plot, theme, False, theme.tint(theme.surface_alt, 220))
        line = theme.tint(theme.text, 34)
        if wcfg["show_center_mark"]:
            painter.fillRect(QRectF(plot.left() + 1, center.y() - 0.5, plot.width() - 2, 1), line)
            painter.fillRect(QRectF(center.x() - 0.5, plot.top() + 1, 1, plot.height() - 2), line)
        if wcfg["show_reference_circle"]:
            pen = QPen(theme.tint(theme.text, 30), 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            whole = int(self.radius_g)
            label_h = self.metrics["ring"].height()
            for g in range(1, whole + 1):
                radius = g * self.scale
                if g < self.radius_g:
                    painter.drawEllipse(center, radius, radius)
                # Label inside ring, on top right diagonal (away from axis lines)
                text = f"{g}G"
                text_w = self.text_width("ring", text) + 1
                offset = radius * 0.7071
                label = QRectF(center.x() + offset - text_w - label_h * 0.15, center.y() - offset, text_w, label_h)
                if label.left() > center.x() + 1:
                    self.draw_text(painter, label, text, "ring", theme.text_faint, Qt.AlignmentFlag.AlignRight, elide=False)
        self.paint_stats_static(painter, show_panel=False)

    def paint(self, painter: QPainter):
        theme = self.theme
        (lgt, lat), _, max_avg, readings = self.state
        center = self.center
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.show_max_circle and 0 < max_avg <= self.radius_g:
            painter.setPen(self.pen_max)
            radius = max_avg * self.scale
            painter.drawEllipse(center, radius, radius)
        if self.show_trace and len(self.trace) > 1:
            self.draw_trace(painter)
        if self.show_dot:
            dot = QPointF(self.to_screen(lat, center.x()), self.to_screen(lgt, center.y()))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.tint(theme.accent, 60))
            painter.drawEllipse(dot, self.dot * 1.9, self.dot * 1.9)
            painter.setPen(QPen(theme.surface, max(self.unit * 0.08, 1.0)))
            painter.setBrush(theme.text)
            painter.drawEllipse(dot, self.dot, self.dot)
        if readings is not None:
            self.draw_stats(painter, readings)

    def draw_trace(self, painter: QPainter):
        """Trace in parts, older parts fainter"""
        points = list(self.trace)
        count = len(points)
        step = max(count // TRACE_PARTS, 1)
        pen = self.pen_trace
        part = TRACE_PARTS - 1
        end = count
        while end > 1 and part >= 0:
            start = max(end - step, 0) if part else 0
            pen.setColor(self.trace_colors[part])
            painter.setPen(pen)
            painter.drawPolyline(QPolygonF(points[start:end]))
            end = start + 1  # parts share a point: line stays continuous
            part -= 1
