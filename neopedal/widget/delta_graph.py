#  NeoPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of NeoPedal.
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
from typing import TYPE_CHECKING, Any, NamedTuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF

from .. import calculation as calc
from ..api_control import api
from ..i18n import tr_overlay as tr
from ..module_info import minfo
from ._base import Overlay
from ._common import delta_shown
from ._race_aids import LEFT, RIGHT, ClassicCells, finite, line_polygons, option_colors, sample_runs, scale_y

if TYPE_CHECKING:
    from ..template.widget_config_types import DeltaGraphConfig

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
        self.changed_from = 0  # first current lap slot changed since shapes were built (samples: none)
        self.previous_version = 0  # changed when previous lap samples change

    def take_changed(self) -> int:
        """First current lap slot changed since last call (samples if none)"""
        changed = self.changed_from
        self.changed_from = self.samples
        return changed

    def slot(self, progress: float) -> int:
        """Sample slot of lap progress (0 to 1)"""
        return min(max(int(progress * self.samples), 0), self.samples - 1)

    def next_lap(self):
        """Lap completed: current lap becomes previous lap"""
        self.previous[:] = self.current
        self.current[:] = self.empty
        self.changed_from = 0
        self.previous_version += 1

    def update(self, lap: int, progress: float, delta: float) -> bool:
        """Sample delta at lap progress (lap: completed laps), True if trace changed

        Delta nan (out lap, back to garage: no delta) leaves its slots empty, laps still followed.
        """
        if not finite(progress):
            return False
        if not finite(delta):
            delta = nan
        changed = False
        if lap != self.last_lap:
            if lap != self.last_lap + 1:  # new session, or lap counter went back
                self.previous[:] = self.empty
                self.current[:] = self.empty
                self.changed_from = 0
                self.previous_version += 1
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
                self.changed_from = 0
        elif 0 <= self.last_slot < slot <= self.last_slot + FILL_GAP:  # skipped slots: linear fill
            start = self.current[self.last_slot]
            if finite(start) and finite(delta):
                steps = slot - self.last_slot
                for index in range(1, steps):
                    self.current[self.last_slot + index] = start + (delta - start) * index / steps
                self.changed_from = min(self.changed_from, self.last_slot + 1)
        self.current[slot] = delta
        self.changed_from = min(self.changed_from, slot)
        self.last_slot = slot
        self.version += 1
        return True


class GraphShapes(NamedTuple):
    """Chart shapes of trace"""

    gain: tuple[QPolygonF, ...] = ()  # areas below zero line
    loss: tuple[QPolygonF, ...] = ()  # areas above zero line
    line: tuple[QPolygonF, ...] = ()  # current lap
    previous: tuple[QPolygonF, ...] = ()  # previous lap


class LapShapes:
    """Chart shapes of current lap (as area_polygons & line_polygons): polygons of each run of samples kept,
    runs from first changed sample built again, last run extended sample by sample"""

    def __init__(self, rect: QRectF, span: float, samples: int):
        self.rect = rect
        self.span = span
        self.step = rect.width() / max(samples - 1, 1)
        self.base = rect.center().y()
        self.runs: list[list] = []  # first, last, line, gain area, loss area

    def update(self, values, changed_from: int) -> tuple[tuple[QPolygonF, ...], ...]:
        """Shapes after samples changed from changed_from: gain areas, loss areas, lines"""
        runs = self.runs
        while runs and runs[-1][0] >= changed_from:
            runs.pop()
        index = changed_from
        extended = None
        if runs and runs[-1][1] >= changed_from - 1:  # last run reaches first changed sample: cut there
            run = runs[-1]
            kept = changed_from - run[0]
            if kept < 2:  # single sample line drawn differently: built again
                runs.pop()
                index = run[0]
            else:
                run[1] = changed_from - 1
                run[2].resize(kept)
                run[3].resize(kept + 1)  # bottom point at end removed
                run[4].resize(kept + 1)
                extended = run
        count = len(values)
        if extended is not None:
            while index < count and finite(values[index]):
                self.add_point(extended, index, values[index])
                index += 1
            extended[1] = index - 1
            base_x = self.rect.left() + extended[1] * self.step
            extended[3].append(QPointF(base_x, self.base))
            extended[4].append(QPointF(base_x, self.base))
        while index < count:
            if not finite(values[index]):
                index += 1
                continue
            first = index
            while index < count and finite(values[index]):
                index += 1
            runs.append(self.new_run(values, first, index - 1))
        return (tuple(run[3] for run in runs), tuple(run[4] for run in runs), tuple(run[2] for run in runs))

    def add_point(self, run: list, index: int, value: float):
        """Sample at end of run"""
        rect, span = self.rect, self.span
        x = rect.left() + index * self.step
        run[2].append(QPointF(x, scale_y(value, rect, -span, span)))
        run[3].append(QPointF(x, scale_y(min(value, 0.0), rect, -span, span)))
        run[4].append(QPointF(x, scale_y(max(value, 0.0), rect, -span, span)))

    def new_run(self, values, first: int, last: int) -> list:
        """Shapes of samples first to last"""
        rect, step, base = self.rect, self.step, self.base
        start = QPointF(rect.left() + first * step, base)
        run: list = [first, first, QPolygonF(), QPolygonF([start]), QPolygonF([start])]
        for index in range(first, last + 1):
            self.add_point(run, index, values[index])
        run[1] = last
        end = QPointF(rect.left() + last * step, base)
        run[3].append(end)
        run[4].append(end)
        if first == last:  # single sample: short flat line, still visible
            x = rect.left() + first * step
            y = run[2].first().y()
            run[2] = QPolygonF((QPointF(max(x - step * 0.3, rect.left()), y), QPointF(x, y)))
        return run


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

    wcfg: DeltaGraphConfig
    chart: QRectF
    devicePixelRatioF: Any

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
        self.lap_shapes = LapShapes(chart, self.delta_range, self.trace.samples)
        self.previous_shapes: tuple[QPolygonF, ...] = ()
        self.previous_version = -1  # previous lap shapes built from this trace previous_version

    def read_graph(self) -> tuple:
        """Sample delta, chart geometry if trace changed; state: (trace version, mark x, mark y, delta)"""
        delta = getattr(minfo.delta, self.delta_source) if delta_shown(self.source) else nan
        # Lap counter may go up while progress still reads end of lap: start of lap then, else lap
        # completed twice (counter, then progress going back) and previous lap trace lost
        progress = calc.lap_progress_correction(api.read.lap.progress(), api.read.timing.current_laptime())
        trace = self.trace
        trace.update(api.read.lap.completed_laps(), progress, delta)
        if self.shapes_version != trace.version:
            self.shapes_version = trace.version
            self.shapes = self.build_shapes()
        chart = self.chart
        # Mark position in device pixels: unchanged until it moves visibly (no repaint every update)
        dpr = self.devicePixelRatioF()
        reading: float | None = None  # None, not nan: unchanged state compares equal (no repaint)
        mark_y = chart.center().y()
        if finite(delta):
            reading = round(calc.sym_max(delta, 99.99), self.decimals)
            mark_y = round(scale_y(reading, chart, -self.delta_range, self.delta_range) * dpr) / dpr
        mark_x = chart.left()
        if finite(progress):
            mark_x = round((chart.left() + min(max(progress, 0.0), 1.0) * chart.width()) * dpr) / dpr
        return trace.version, mark_x, mark_y, reading

    def build_shapes(self) -> GraphShapes:
        """Chart shapes of current trace: current lap from first changed sample on, previous lap once per lap"""
        trace = self.trace
        gain, loss, line = self.lap_shapes.update(trace.current, trace.take_changed())
        if self.show_previous and self.previous_version != trace.previous_version:
            self.previous_version = trace.previous_version
            self.previous_shapes = line_polygons(trace.previous, self.chart, -self.delta_range, self.delta_range)
        return GraphShapes(gain=gain, loss=loss, line=line, previous=self.previous_shapes)

    def delta_text(self, delta: float | None) -> str:
        """Delta reading"""
        if not finite(delta):
            return "-.--"
        return f"{delta:+z.{self.decimals}f}"


class Realtime(DeltaGraphMixin, ClassicCells, Overlay):
    """Draw widget"""

    wcfg: DeltaGraphConfig

    update_while_hidden = True  # lap trace kept while hidden

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        font_m = self.setup_classic_font()

        # Config variable
        wcfg = self.wcfg
        self.label = f"{tr('Delta')} {tr(wcfg['deltabest_source'])}"
        self.show_reading = bool(wcfg["show_delta_reading"])
        width = max(int(wcfg["display_width"]), 40)
        if self.show_reading:  # label & widest reading side by side (+99.99), never overlapping
            decimals = min(max(int(wcfg["decimal_places"]), 0), 3)
            width = max(width, round(self.text_cell_width(len(self.label) + 5 + decimals + bool(decimals))))
        height = max(int(wcfg["display_height"]), 20)
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
