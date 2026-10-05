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
Tyre temperature trend Widget

Surface temperature of each tyre over the last seconds (or average of each of the last laps):
4 small line charts colored by tyre heatmap, optimal temperature line when game gives it.
"""

from __future__ import annotations

from collections import deque
from typing import Any, NamedTuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen, QPolygonF

from .. import units
from ..api_control import api
from ..i18n import tr_overlay as tr
from ._base import Overlay
from ._modern.quad import heat_color
from ._modern.wheels import TyreCompounds
from ._race_aids import LEFT, RIGHT, ClassicCells, finite, line_polygons, option_colors, scale_y, value_range

DASH = chr(0x2013)
WHEELS = ("FL", "FR", "RL", "RR")
TIME_SAMPLES = 60  # samples over trend duration (time mode)
MIN_SPAN = 20.0  # Celsius, chart range at least
RANGE_STEP = 5.0  # Celsius, chart range rounded out (stable scale)
INVALID = -100.0  # Celsius, temperature under this is not read
MAXIMUM = 1000.0  # Celsius, temperature over this is not read


def valid(temperature: float) -> bool:
    """Temperature read from game (not missing or out of range)"""
    return finite(temperature) and INVALID < temperature < MAXIMUM


class TemperatureTrend:
    """Surface temperature samples of each tyre, oldest first (Celsius)

    Time mode: one sample every trend duration / TIME_SAMPLES seconds.
    Lap mode: average of each completed lap.
    """

    def __init__(self, duration: float, by_lap: bool, laps: int):
        self.by_lap = by_lap
        self.interval = max(duration, 10.0) / TIME_SAMPLES
        size = max(laps, 2) if by_lap else TIME_SAMPLES
        self.samples: tuple[deque[float], ...] = tuple(deque(maxlen=size) for _ in range(4))
        self.size = size
        self.last_time = -1.0
        self.last_lap = -1
        self.sums = [0.0] * 4
        self.count = 0
        self.version = 0  # changed when samples change

    def clear(self):
        for samples in self.samples:
            samples.clear()
        self.sums = [0.0] * 4
        self.count = 0
        self.version += 1

    def update(self, elapsed: float, lap: int, temperatures: tuple[float, ...]):
        """Add sample (time mode), or add to lap average (lap mode)"""
        if not finite(elapsed) or len(temperatures) < 4:
            return
        if elapsed < self.last_time - 1:  # session restarted, time went back
            self.clear()
            self.last_time = -1.0
        if not all(valid(value) for value in temperatures[:4]):
            return
        if self.by_lap:
            if lap != self.last_lap:
                if self.count and lap == self.last_lap + 1:
                    for wheel, samples in enumerate(self.samples):
                        samples.append(round(self.sums[wheel] / self.count, 1))
                    self.version += 1
                elif lap < self.last_lap:
                    self.clear()
                self.sums = [0.0] * 4
                self.count = 0
                self.last_lap = lap
            if elapsed != self.last_time:  # one value per game update
                self.sums = [total + value for total, value in zip(self.sums, temperatures)]
                self.count += 1
                self.last_time = elapsed
            return
        if self.last_time < 0 or elapsed - self.last_time >= self.interval:
            for wheel, samples in enumerate(self.samples):
                samples.append(round(temperatures[wheel], 1))
            self.last_time = elapsed
            self.version += 1


class WheelChart(NamedTuple):
    """Chart geometry of one tyre"""

    lines: tuple[QPolygonF, ...] = ()
    pen: QPen | None = None  # heatmap colored
    optimal: float = -1.0  # y of optimal temperature line, -1 = none


class TyreTrendMixin:
    """Temperature samples & chart geometry, for classic & modern widget"""

    wcfg: Any
    cfg: Any

    def setup_trend(self):
        """Options, samples"""
        wcfg = self.wcfg
        self.trend = TemperatureTrend(
            float(wcfg["trend_duration"]), bool(wcfg["show_trend_by_lap"]),
            min(max(int(wcfg["number_of_laps"]), 2), 100))
        self.show_optimal = bool(wcfg["show_optimal_temperature"])
        self.unit_temp = units.set_unit_temperature(self.cfg.units["temperature_unit"])
        self.sign = "°" if wcfg["show_degree_sign"] else ""
        self.compounds = TyreCompounds(wcfg["enable_heatmap_auto_matching"], wcfg["heatmap_name"])
        self.chart_key: tuple = ()
        self.charts: tuple[WheelChart, ...] = (WheelChart(),) * 4
        self.line_width = 1.5

    def read_trend(self, chart_rects: tuple[QRectF, ...]) -> tuple:
        """Sample temperatures, charts if changed; state: (version, texts, heat colors)"""
        self.compounds.update()
        temperatures = api.read.tyre.surface_temperature_avg()
        self.trend.update(api.read.timing.elapsed(), api.read.lap.completed_laps(), temperatures)
        optimal: tuple[float, ...] = (0.0,) * 4
        if self.show_optimal:  # 0 = unknown
            optimal = tuple(round(value, 1) if finite(value) and 0 < value < 1000 else 0.0
                            for value in api.read.tyre.optimal_temperature()[:4])
        key = (self.trend.version, optimal, id(self.compounds.heat[0]), id(self.compounds.heat[2]))
        if key != self.chart_key:
            self.chart_key = key
            self.charts = self.build_charts(chart_rects, optimal)
        texts = []
        colors: list[QColor | None] = []
        for wheel in range(4):
            value = temperatures[wheel] if wheel < len(temperatures) else INVALID
            if valid(value):
                texts.append(f"{self.unit_temp(value):.0f}{self.sign}")
                colors.append(heat_color(self.compounds.heat[wheel], round(value)))
            else:
                texts.append(DASH)
                colors.append(None)
        return self.trend.version, tuple(texts), tuple(colors)

    def build_charts(self, rects: tuple[QRectF, ...], optimal: tuple[float, ...]) -> tuple[WheelChart, ...]:
        """Line of each tyre in its chart, all tyres on same scale"""
        samples = self.trend.samples
        known = [value for value in optimal[:4] if finite(value) and value > 0]
        low, high = value_range([*(value for wheel in samples for value in wheel), *known], MIN_SPAN, RANGE_STEP)
        charts = []
        for wheel, rect in enumerate(rects):
            lines = line_polygons(tuple(samples[wheel]), rect, low, high, self.trend.size)
            pen = QPen(QBrush(self.heat_gradient(self.compounds.heat[wheel], rect, low, high)), self.line_width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            value = optimal[wheel] if wheel < len(optimal) else 0.0
            line_y = scale_y(value, rect, low, high) if finite(value) and value > 0 else -1.0
            charts.append(WheelChart(lines, pen, line_y))
        return tuple(charts)

    @staticmethod
    def heat_gradient(steps: tuple, rect: QRectF, low: float, high: float) -> QLinearGradient:
        """Vertical gradient of heatmap colors over chart range (line colored by its value)"""
        gradient = QLinearGradient(QPointF(0, rect.bottom()), QPointF(0, rect.top()))
        span = high - low
        gradient.setColorAt(0.0, heat_color(steps, low))
        for value, color in steps:
            if low < value < high:
                gradient.setColorAt((value - low) / span, color)
        gradient.setColorAt(1.0, heat_color(steps, high))
        return gradient


class Realtime(TyreTrendMixin, ClassicCells, Overlay):
    """Draw widget"""

    update_while_hidden = True  # trend kept while hidden

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        font_m = self.setup_classic_font()
        self.setup_trend()

        # Config variable
        wcfg = self.wcfg
        gap = 2
        chart_w = max(int(wcfg["display_width"]), 20)
        chart_h = max(int(wcfg["display_height"]), 10)
        caption_h = round(font_m.height * 1.2)
        cell_w = max(chart_w, self.text_cell_width(9))
        self.cells = []
        for wheel in range(4):
            left = (cell_w + gap) * (wheel % 2)
            top = (caption_h + chart_h + gap) * (wheel // 2)
            self.cells.append((QRectF(left, top, cell_w, caption_h), QRectF(left, top + caption_h, cell_w, chart_h)))
        self.chart_rects = tuple(chart.adjusted(2, 3, -2, -3) for _, chart in self.cells)
        self.labels = tuple(tr(label) for label in WHEELS)
        self.colors = option_colors(wcfg, "font_color_caption", "background_color_caption", "background_color_chart",
                                    "optimal_line_color")
        self.pen_optimal = QPen(self.colors["optimal_line_color"], 1, Qt.PenStyle.DashLine)

        # Config canvas
        self.resize(round(cell_w * 2 + gap), (caption_h + chart_h) * 2 + gap)
        self.state: tuple | None = None

    def timerEvent(self, event):
        """Update when vehicle on track"""
        state = self.read_trend(self.chart_rects)
        if self.state != state:
            self.state = state
            self.update()

    # GUI update methods
    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        colors = self.colors
        texts = self.state[1] if self.state is not None else (DASH,) * 4
        heat = self.state[2] if self.state is not None else (None,) * 4
        for wheel, (caption, chart) in enumerate(self.cells):
            self.draw_cell(painter, caption, self.labels[wheel], colors["font_color_caption"],
                           colors["background_color_caption"], LEFT)
            self.draw_cell(painter, caption, texts[wheel], heat[wheel] or colors["font_color_caption"], None, RIGHT)
            painter.fillRect(chart, colors["background_color_chart"])
            wheel_chart = self.charts[wheel]
            if wheel_chart.optimal >= 0:
                painter.setPen(self.pen_optimal)
                rect = self.chart_rects[wheel]
                painter.drawLine(QPointF(rect.left(), wheel_chart.optimal), QPointF(rect.right(), wheel_chart.optimal))
            if wheel_chart.pen is not None:
                painter.setPen(wheel_chart.pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                for line in wheel_chart.lines:
                    painter.drawPolyline(line)
