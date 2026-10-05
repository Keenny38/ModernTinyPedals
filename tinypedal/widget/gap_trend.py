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
Gap trend Widget

Gap to car ahead & car behind (overall or in class): current gap, gap change per lap over
the last laps (catching up or being caught) and gap of each lap as a small chart.
"""

from __future__ import annotations

from collections import deque
from math import nan
from typing import Any, NamedTuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen, QPolygonF

from ..api_control import api
from ..i18n import tr_overlay as tr
from ..module_info import minfo
from ._base import Overlay
from ._race_aids import LEFT, ClassicCells, finite, line_polygons, option_colors, scale_y, value_range

DASH = chr(0x2013)
GAP_LIMIT = 999.9  # gap shown at most (seconds)
STEADY_RATE = 0.05  # gap change per lap (seconds) under which gap is steady
GOOD = 1
BAD = -1
NEUTRAL = 0


class GapSeries:
    """Gap at end of each lap to one car slot (ahead or behind): gap & car identity"""

    def __init__(self, laps: int):
        self.samples: deque[tuple[float, int]] = deque(maxlen=max(laps, 2))

    def add(self, gap: float, car: int):
        """Gap at end of lap (nan if not a time gap), car slot id (-1 if no car)"""
        self.samples.append((gap if finite(gap) else nan, car))

    def clear(self):
        self.samples.clear()

    def trend(self) -> list[float]:
        """Gaps of each lap to current car, nan for laps against another car (line broken)"""
        if not self.samples:
            return []
        car = self.samples[-1][1]
        trend = [nan] * len(self.samples)
        for index in range(len(self.samples) - 1, -1, -1):
            gap, sample_car = self.samples[index]
            if sample_car != car or car < 0 or not finite(gap):
                break
            trend[index] = gap
        return trend

    def rate(self) -> float:
        """Gap change per lap to current car (negative = gap shrinking), nan if under 2 laps"""
        gaps = [gap for gap in self.trend() if finite(gap)]
        if len(gaps) < 2:
            return nan
        return (gaps[-1] - gaps[0]) / (len(gaps) - 1)


class GapRow(NamedTuple):
    """Gap to one car, for drawing"""

    label: str
    name: str
    gap: str
    rate: str
    meaning: int  # GOOD, BAD or NEUTRAL: player catching up, being caught...


class GapTrendMixin:
    """Gap readings & per lap history, for classic & modern widget"""

    wcfg: Any

    def setup_gaps(self):
        """Options, history"""
        wcfg = self.wcfg
        self.laps = min(max(int(wcfg["number_of_laps"]), 2), 50)
        self.decimals = min(max(int(wcfg["decimal_places"]), 0), 3)
        self.in_class = bool(wcfg["show_gaps_in_class"])
        self.show_name = bool(wcfg["show_driver_name"])
        self.show_rate = bool(wcfg["show_closing_rate"])
        self.show_chart = bool(wcfg["show_trend_chart"])
        self.series = (GapSeries(self.laps), GapSeries(self.laps))
        self.last_lap = -1
        self.version = 0  # changed when history changes

    def nearby_cars(self) -> tuple[tuple[Any, int], tuple[Any, int]]:
        """(gap, vehicle index) of car ahead & car behind, index -1 if none

        Gap is time (float) or laps (int) as given by vehicles module.
        """
        vehicles = minfo.vehicles
        cars = vehicles.dataSet
        total = min(vehicles.totalVehicles, len(cars))
        index = vehicles.playerIndex
        if not 0 <= index < total:
            return (0.0, -1), (0.0, -1)
        player = cars[index]
        if self.in_class:
            ahead = player.classAheadIndex
            behind = player.classBehindIndex
            gap_ahead = player.gapBehindNextInClass
            gap_behind = cars[behind].gapBehindNextInClass if 0 <= behind < total else 0.0
        else:
            ahead = behind = -1
            place = player.positionOverall
            for other in range(total):
                position = cars[other].positionOverall
                if position == place - 1:
                    ahead = other
                elif position == place + 1:
                    behind = other
            gap_ahead = player.gapBehindNext
            gap_behind = cars[behind].gapBehindNext if behind >= 0 else 0.0
        if not 0 <= ahead < total:
            ahead = -1
        if not 0 <= behind < total:
            behind = -1
        return (gap_ahead, ahead), (gap_behind, behind)

    def read_gaps(self) -> tuple[GapRow, GapRow]:
        """Current gaps, history updated at end of each lap"""
        nearby = self.nearby_cars()
        lap = api.read.lap.completed_laps()
        if lap != self.last_lap:
            if lap == self.last_lap + 1:
                for series, (gap, index) in zip(self.series, nearby):
                    series.add(time_gap(gap) if index >= 0 else nan, car_id(index))
            elif lap < self.last_lap:  # new session
                for series in self.series:
                    series.clear()
            self.last_lap = lap
            self.version += 1
        rows = []
        for slot, (series, (gap, index)) in enumerate(zip(self.series, nearby)):
            ahead = slot == 0
            rate = series.rate() if index >= 0 else nan
            rows.append(GapRow(
                label="Ahead" if ahead else "Behind",
                name=minfo.vehicles.dataSet[index].driverName if index >= 0 and self.show_name else "",
                gap=self.gap_text(gap) if index >= 0 else DASH,
                rate=f"{max(min(rate, 99.99), -99.99):+.2f}" if finite(rate) else DASH,
                meaning=rate_meaning(rate, ahead),
            ))
        return rows[0], rows[1]

    def gap_text(self, gap: Any) -> str:
        """Gap in seconds, or laps"""
        if isinstance(gap, int) and gap > 0:
            return f"+{gap}L"
        if not finite(gap):
            return DASH
        return f"{min(abs(gap), GAP_LIMIT):.{self.decimals}f}"

    def trend_values(self) -> tuple[list[float], list[float]]:
        """Gaps per lap of car ahead & behind"""
        return self.series[0].trend(), self.series[1].trend()


def time_gap(gap: Any) -> float:
    """Time gap (seconds), nan if gap is laps"""
    if isinstance(gap, int):
        return nan if gap > 0 else float(gap)
    return min(abs(gap), GAP_LIMIT) if finite(gap) else nan


def car_id(index: int) -> int:
    """Vehicle identity (slot id), -1 if no car"""
    if index < 0:
        return -1
    return api.read.vehicle.slot_id(index)


def rate_meaning(rate: float, ahead: bool) -> int:
    """Whether gap change is good for player: gap to car ahead shrinking, to car behind growing"""
    if not finite(rate) or abs(rate) < STEADY_RATE:
        return NEUTRAL
    shrinking = rate < 0
    return GOOD if shrinking == ahead else BAD


class TrendChart(NamedTuple):
    """Gap per lap chart geometry"""

    lines: tuple[QPolygonF, ...] = ()
    end: QPointF | None = None  # last lap (dot)


def trend_chart(values: list[float], rect: QRectF, laps: int) -> TrendChart:
    """Gap per lap line in chart rect (scale follows gaps, at least 1 second)"""
    low, high = value_range(values, 1.0, 0.5)
    lines = line_polygons(values, rect, low, high, laps)
    if not lines or not values or not finite(values[-1]):
        return TrendChart(lines)
    return TrendChart(lines, QPointF(rect.right(), scale_y(values[-1], rect, low, high)))


class Realtime(GapTrendMixin, ClassicCells, Overlay):
    """Draw widget"""

    update_while_hidden = True  # gap history kept while hidden

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        font_m = self.setup_classic_font()
        self.setup_gaps()

        # Config variable
        wcfg = self.wcfg
        gap = 2
        row_h = round(font_m.height * 1.2)
        columns = [("label", self.text_cell_width(8), "")]
        if self.show_name:
            columns.append(("name", self.text_cell_width(12), ""))
        columns.append(("gap", self.text_cell_width(6), "Gap"))
        if self.show_rate:
            columns.append(("rate", self.text_cell_width(6), "Per lap"))
        if self.show_chart:
            columns.append(("chart", self.text_cell_width(10), "Trend"))
        left = 0.0
        self.cells: dict[str, tuple[QRectF, ...]] = {}  # key: header, ahead row, behind row
        for key, width, _ in columns:
            self.cells[key] = tuple(QRectF(left, (row_h + gap) * row, width, row_h) for row in range(3))
            left += width + gap
        self.headers = tuple((self.cells[key][0], tr(label)) for key, _, label in columns if label)
        self.labels = (tr("Ahead"), tr("Behind"))
        self.colors = option_colors(
            wcfg, "font_color_caption", "background_color_caption", "font_color_gap", "background_color_gap",
            "font_color_gaining", "font_color_losing", "background_color_chart", "chart_line_color",
        )
        self.pen_chart = QPen(self.colors["chart_line_color"], 1.5)
        self.charts = (TrendChart(), TrendChart())
        self.chart_version = -1
        self.name_width = round(self.cells["name"][1].width() - self.cell_padding() * 2) if self.show_name else 0

        # Config canvas
        self.resize(max(round(left - gap), 1), row_h * 3 + gap * 2)
        self.state: tuple | None = None

    def timerEvent(self, event):
        """Update when vehicle on track"""
        rows: tuple[GapRow, ...] = self.read_gaps()
        if self.show_name:  # long names cut to cell
            metrics = self.fontMetrics()
            rows = tuple(
                row._replace(name=metrics.elidedText(row.name, Qt.TextElideMode.ElideRight, self.name_width))
                for row in rows
            )
        if self.show_chart and self.chart_version != self.version:
            self.chart_version = self.version
            self.charts = tuple(  # type: ignore[assignment]
                trend_chart(values, self.cells["chart"][row + 1].adjusted(3, 3, -3, -3), self.laps)
                for row, values in enumerate(self.trend_values())
            )
        state = (self.version, rows)
        if self.state != state:
            self.state = state
            self.update()

    # GUI update methods
    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        colors = self.colors
        caption = colors["font_color_caption"]
        caption_bg = colors["background_color_caption"]
        for rect, label in self.headers:
            self.draw_cell(painter, rect, label, caption, caption_bg)
        rows = self.state[1] if self.state is not None else (None, None)
        for row_index, row in enumerate(rows):
            line = row_index + 1
            for key, rects in self.cells.items():
                rect = rects[line]
                if key == "label":
                    self.draw_cell(painter, rect, self.labels[row_index], caption, caption_bg, LEFT)
                elif key == "chart":
                    self.draw_chart(painter, rect, self.charts[row_index])
                elif row is None:
                    self.draw_cell(painter, rect, DASH if key == "gap" else "", colors["font_color_gap"],
                                   colors["background_color_gap"])
                else:
                    color = colors["font_color_gap"]
                    if key == "rate" and row.meaning:
                        color = colors["font_color_gaining"] if row.meaning == GOOD else colors["font_color_losing"]
                    self.draw_cell(painter, rect, getattr(row, key), color, colors["background_color_gap"],
                                   LEFT if key == "name" else Qt.AlignmentFlag.AlignCenter)

    def draw_chart(self, painter: QPainter, rect: QRectF, chart: TrendChart):
        """Gap per lap line, dot on last lap"""
        painter.fillRect(rect, self.colors["background_color_chart"])
        painter.setPen(self.pen_chart)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for line in chart.lines:
            painter.drawPolyline(line)
        if chart.end is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.colors["chart_line_color"])
            painter.drawEllipse(chart.end, 2.5, 2.5)
