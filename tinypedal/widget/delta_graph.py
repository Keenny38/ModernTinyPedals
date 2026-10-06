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
Delta graph Widget

Delta to reference lap (best, session best, stint best or last lap) along current lap distance:
time loss above zero line, time gain below, previous lap faded behind, current position mark.
"""

from __future__ import annotations

from array import array
from math import nan
from typing import Any, NamedTuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF

from .. import calculation as calc
from ..api_control import api
from ..i18n import tr_overlay as tr
from ..module_info import minfo
from ._base import Overlay
from ._common import delta_shown
from ._race_aids import LEFT, RIGHT, ClassicCells, finite, line_polygons, option_colors, sample_runs, scale_y

SAMPLE_SPACING = 2  # chart pixels per sample along lap
MAX_SAMPLES = 1000
FILL_GAP = 8  # missing samples filled between two samples at most this far apart (lag, low rate)


class DeltaTrace:
    """Delta samples along lap distance, of current & previous lap (nan = no sample)

    One sample per lap distance slot, taken when car enters slot: trace changes a few times
    per second at most, chart geometry is built again only then.
    """

    def __init__(self, samples: int):
        self.samples = min(max(samples, 2), MAX_SAMPLES)
        self.empty = array("d", [nan]) * self.samples
        self.current = array("d", self.empty)
        self.previous = array("d", self.empty)
        self.last_lap = -1
        self.last_slot = -1
        self.wrapped = False  # lap distance went past finish line before lap counter
        self.version = 0  # changed when samples change

    def slot(self, progress: float) -> int:
        """Sample slot of lap progress (0 to 1)"""
        return min(max(int(progress * self.samples), 0), self.samples - 1)

    def next_lap(self):
        """Lap completed: current lap becomes previous lap"""
        self.previous[:] = self.current
        self.current[:] = self.empty

    def update(self, lap: int, progress: float, delta: float) -> bool:
        """Sample delta at lap progress (lap: completed laps), True if trace changed"""
        if not (finite(progress) and finite(delta)):
            return False
        changed = False
        if lap != self.last_lap:
            if lap != self.last_lap + 1:  # new session, or lap counter went back
                self.previous[:] = self.empty
                self.current[:] = self.empty
                self.last_slot = -1
            elif not self.wrapped:
                self.next_lap()
                self.last_slot = -1
            self.wrapped = False
            self.last_lap = lap
            changed = True
            self.version += 1
        slot = self.slot(progress)
        if slot == self.last_slot:
            return changed
        if 0 <= slot < self.last_slot - 1:  # moved back along lap
            if not self.wrapped and slot < self.samples * 0.1 and self.last_slot >= self.samples * 0.9:
                self.next_lap()  # crossed finish line, lap counter not updated yet
                self.wrapped = True
            else:  # garage, reset: lap restarted
                self.current[:] = self.empty
        elif 0 <= self.last_slot < slot <= self.last_slot + FILL_GAP:  # skipped slots: linear fill
            start = self.current[self.last_slot]
            if finite(start):
                steps = slot - self.last_slot
                for index in range(1, steps):
                    self.current[self.last_slot + index] = start + (delta - start) * index / steps
        self.current[slot] = delta
        self.last_slot = slot
        self.version += 1
        return True


class GraphShapes(NamedTuple):
    """Chart shapes of trace"""

    gain: tuple[QPolygonF, ...] = ()  # areas below zero line
    loss: tuple[QPolygonF, ...] = ()  # areas above zero line
    line: tuple[QPolygonF, ...] = ()  # current lap
    previous: tuple[QPolygonF, ...] = ()  # previous lap


def area_polygons(values, rect: QRectF, span: float, sign: int) -> tuple[QPolygonF, ...]:
    """Areas between zero line and samples of one sign (+1 loss, -1 gain), one per run"""
    step = rect.width() / max(len(values) - 1, 1)
    base = rect.center().y()
    areas = []
    for first, last in sample_runs(values):
        points = [QPointF(rect.left() + first * step, base)]
        for index in range(first, last + 1):
            value = values[index]
            clipped = max(value, 0.0) if sign > 0 else min(value, 0.0)
            points.append(QPointF(rect.left() + index * step, scale_y(clipped, rect, -span, span)))
        points.append(QPointF(rect.left() + last * step, base))
        areas.append(QPolygonF(points))
    return tuple(areas)


class DeltaGraphMixin:
    """Delta trace & chart geometry, for classic & modern widget"""

    wcfg: Any
    chart: QRectF

    def setup_graph(self, chart: QRectF):
        """Chart area, options"""
        wcfg = self.wcfg
        self.chart = chart
        self.source = wcfg["deltabest_source"]
        self.delta_source = f"delta{wcfg['deltabest_source']}"
        self.delta_range = max(float(wcfg["delta_display_range"]), 0.05)
        self.decimals = min(max(int(wcfg["decimal_places"]), 0), 3)
        self.show_previous = bool(wcfg["show_previous_lap"])
        self.show_mark = bool(wcfg["show_position_mark"])
        self.trace = DeltaTrace(int(chart.width() / SAMPLE_SPACING) + 1)
        self.shapes = GraphShapes()
        self.shapes_version = -1

    def read_graph(self) -> tuple:
        """Sample delta, chart geometry if trace changed; state: (trace version, mark x, mark y, delta)"""
        delta = getattr(minfo.delta, self.delta_source) if delta_shown(self.source) else nan
        progress = api.read.lap.progress()
        trace = self.trace
        trace.update(api.read.lap.completed_laps(), progress, delta)
        if self.shapes_version != trace.version:
            self.shapes_version = trace.version
            self.shapes = self.build_shapes()
        chart = self.chart
        reading: float | None = None  # None, not nan: unchanged state compares equal (no repaint)
        mark_y = chart.center().y()
        if finite(delta):
            reading = round(calc.sym_max(delta, 99.99), self.decimals)
            mark_y = round(scale_y(reading, chart, -self.delta_range, self.delta_range), 1)
        mark_x = round(chart.left() + min(max(progress, 0.0), 1.0) * chart.width(), 1) if finite(progress) else chart.left()
        return trace.version, mark_x, mark_y, reading

    def build_shapes(self) -> GraphShapes:
        """Chart shapes of current trace"""
        trace = self.trace
        chart = self.chart
        span = self.delta_range
        current = trace.current
        return GraphShapes(
            gain=area_polygons(current, chart, span, -1),
            loss=area_polygons(current, chart, span, 1),
            line=line_polygons(current, chart, -span, span),
            previous=line_polygons(trace.previous, chart, -span, span) if self.show_previous else (),
        )

    def delta_text(self, delta: float | None) -> str:
        """Delta reading"""
        if not finite(delta):
            return "-.--"
        return f"{delta:+.{self.decimals}f}"


class Realtime(DeltaGraphMixin, ClassicCells, Overlay):
    """Draw widget"""

    update_while_hidden = True  # lap trace kept while hidden

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        font_m = self.setup_classic_font()

        # Config variable
        wcfg = self.wcfg
        width = max(int(wcfg["display_width"]), 40)
        height = max(int(wcfg["display_height"]), 20)
        self.show_reading = bool(wcfg["show_delta_reading"])
        header = font_m.height if self.show_reading else 0
        self.rect_reading = QRectF(0, 0, width, header)
        self.setup_graph(QRectF(0, header, width, height))
        self.colors = option_colors(
            wcfg, "font_color_reading", "background_color", "fill_color_time_gain", "fill_color_time_loss",
            "line_color_current_lap", "line_color_previous_lap", "zero_line_color", "position_mark_color",
        )
        self.pen_line = QPen(self.colors["line_color_current_lap"], 1.5)
        self.pen_previous = QPen(self.colors["line_color_previous_lap"], 1.5)
        self.pen_zero = QPen(self.colors["zero_line_color"], 1)
        self.pen_mark = QPen(self.colors["position_mark_color"], 2)
        self.color_gain = QColor(self.colors["fill_color_time_gain"])
        self.color_gain.setAlpha(255)
        self.color_loss = QColor(self.colors["fill_color_time_loss"])
        self.color_loss.setAlpha(255)
        self.label = f"{tr('Delta')} {tr(wcfg['deltabest_source'])}"

        # Config canvas
        self.resize(width, header + height)
        self.state: tuple | None = None

    def timerEvent(self, event):
        """Update when vehicle on track"""
        state = self.read_graph()
        if self.state != state:
            self.state = state
            self.update()

    # GUI update methods
    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        colors = self.colors
        painter.fillRect(self.rect(), colors["background_color"])
        chart = self.chart
        painter.setPen(self.pen_zero)
        painter.drawLine(QPointF(chart.left(), chart.center().y()), QPointF(chart.right(), chart.center().y()))
        shapes = self.shapes
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self.pen_previous)
        for line in shapes.previous:
            painter.drawPolyline(line)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colors["fill_color_time_gain"])
        for area in shapes.gain:
            painter.drawPolygon(area)
        painter.setBrush(colors["fill_color_time_loss"])
        for area in shapes.loss:
            painter.drawPolygon(area)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self.pen_line)
        for line in shapes.line:
            painter.drawPolyline(line)
        if self.show_reading:
            self.draw_cell(painter, self.rect_reading, self.label, colors["font_color_reading"], None, LEFT)
        if self.state is None:
            return
        _, mark_x, mark_y, delta = self.state
        if self.show_mark:
            painter.setPen(self.pen_mark)
            painter.drawLine(QPointF(mark_x, chart.top()), QPointF(mark_x, chart.bottom()))
            painter.setBrush(colors["position_mark_color"])
            painter.drawEllipse(QPointF(mark_x, mark_y), 3, 3)
        if self.show_reading:
            reading = self.rect_reading
            if finite(delta) and delta:
                color = self.color_loss if delta > 0 else self.color_gain
            else:
                color = colors["font_color_reading"]
            self.draw_cell(painter, reading, self.delta_text(delta), color, None, RIGHT)
