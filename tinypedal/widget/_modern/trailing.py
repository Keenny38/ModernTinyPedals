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
Trailing Widget, modern design

Scrolling input history on a chart: throttle & brake lines with soft area under them, clutch,
force feedback, steering, speed & slip angle difference lines, TC / ABS activation, wheel lock
& wheel slip as dots; faint reference lines at quarters.
"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF

from ..trailing import TrailingMixin
from .base import ModernOverlay
from .draw import panel, rounded

PLOTS = {  # plot: theme color, drawn as dots, area under line
    "tc_activation": ("warning", True, False),
    "abs_activation": ("blue", True, False),
    "throttle": ("positive", False, True),
    "brake": ("negative", False, True),
    "clutch": ("accent", False, False),
    "ffb": ("text_muted", False, False),
    "steering": ("text", False, False),
    "speed": ("caution", False, False),
    "wheel_lock": ("caution", True, False),
    "wheel_slip": ("best", True, False),
    "slip_angle_difference": ("orange", False, False),
}


class Plot:
    """Samples & style of one input"""

    __slots__ = ("name", "samples", "pen", "dots", "fill")

    def __init__(self, name: str, size: int, color: QColor, width: float, dots: bool, fill: QColor | None):
        self.name = name
        self.samples: deque[float] = deque(maxlen=size)
        self.pen = QPen(color, width)
        self.pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.dots = dots
        self.fill = fill


class Realtime(TrailingMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "display_width", "display_height", "display_scale", "time_scale", "maximum_paused_frames",
        "show_inverted_trailing", "show_inverted_pedal", "show_tc_activation", "show_abs_activation",
        "show_throttle", "show_raw_throttle", "show_brake", "show_raw_brake", "show_clutch", "show_raw_clutch",
        "show_ffb", "show_absolute_ffb", "show_steering", "show_inverted_steering", "show_speed",
        "show_wheel_lock", "wheel_lock_threshold", "show_wheel_slip", "wheel_slip_threshold",
        "show_slip_angle_difference", "maximum_slip_angle_difference", "show_reference_line",
        *(f"display_order_{name}" for name in PLOTS),
    )
    update_while_hidden = True  # input history keeps recording

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        theme = self.theme
        self.setup_trailing()
        pad = unit * 0.35
        width = max(float(wcfg["display_width"]), unit * 4)
        height = max(float(wcfg["display_height"]), unit * 2)
        self.set_size(width + pad * 2, height + pad * 2)
        self.chart = QRectF(pad, pad, width, height)
        dot = max(unit * 0.42, 3.0)
        line = max(unit * 0.17, 1.5)
        inset = dot / 2 + 1
        self.plot_area = self.chart.adjusted(inset, inset, -inset, -inset)
        self.step = float(self.display_scale)
        self.newest_right = bool(wcfg["show_inverted_trailing"])
        self.top_is_full = not wcfg["show_inverted_pedal"]
        size = int(self.plot_area.width() / self.step) + 2
        plots = []
        for name in self.plot_names:
            token, dots, area = PLOTS[name]
            color = getattr(theme, token)
            plots.append((wcfg[f"display_order_{name}"], name, Plot(
                name, size, color, dot if dots else line, dots, theme.tint(color, 46) if area else None)))
        # Highest display order drawn first, display order 1 on top
        self.plots = tuple(plot for _, _, plot in sorted(plots, key=lambda item: (item[0], item[1]), reverse=True))
        self.samples_added = 0

    def design_unit(self) -> float:
        """Chart height sets size"""
        return max(float(self.wcfg["display_height"]), 10.0) / 5

    def timerEvent(self, event):
        """Update when vehicle on track"""
        if self.plot_paused():
            return
        values = dict(zip(self.plot_names, self.read_inputs()))
        for plot in self.plots:
            plot.samples.appendleft(values[plot.name])
        self.samples_added += 1
        self.refresh(self.samples_added)

    def paint_static(self, painter: QPainter):
        theme = self.theme
        panel(painter, QRectF(self.rect()), theme, self.radius(0.5), self.depth_effects)
        chart = self.chart
        rounded(painter, chart, self.radius(0.3), theme.tint(theme.surface_alt, 200))
        if self.wcfg["show_reference_line"]:
            area = self.plot_area
            for fraction in (0.25, 0.5, 0.75):
                y = round(area.bottom() - area.height() * fraction) - 0.5
                color = theme.tint(theme.text, 34 if fraction == 0.5 else 22)
                painter.fillRect(QRectF(chart.left() + 2, y, chart.width() - 4, 1), color)

    def paint(self, painter: QPainter):
        area = self.plot_area
        height = area.height()
        if self.newest_right:
            start_x, step = area.right(), -self.step
        else:
            start_x, step = area.left(), self.step
        if self.top_is_full:
            base_y, scale = area.bottom(), -height
        else:
            base_y, scale = area.top(), height
        painter.save()
        painter.setClipRect(self.chart)
        for plot in self.plots:
            if plot.dots:
                points = [QPointF(start_x + index * step, base_y + value * scale)
                          for index, value in enumerate(plot.samples) if value >= 0]
                if points:
                    painter.setPen(plot.pen)
                    painter.drawPoints(QPolygonF(points))
                continue
            points = [QPointF(start_x + index * step, base_y + min(max(value, 0.0), 1.0) * scale)
                      for index, value in enumerate(plot.samples)]
            if len(points) < 2:
                continue
            if plot.fill is not None:
                area_points = [*points, QPointF(points[-1].x(), base_y), QPointF(points[0].x(), base_y)]
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(plot.fill)
                painter.drawPolygon(QPolygonF(area_points))
                painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(plot.pen)
            painter.drawPolyline(QPolygonF(points))
        painter.restore()
