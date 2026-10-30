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
Trailing Widget, modern design

Scrolling input history on a chart: throttle & brake lines with soft area under them, clutch,
force feedback, steering, speed & slip angle difference lines, TC / ABS activation, wheel lock
& wheel slip as dots; faint reference lines at quarters. Optional pedal bars (pedal widget design)
beside newest samples.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QTransform

from .._pedal_alert import ALERT_THEME_COLORS
from ..trailing import TrailingMixin
from .base import CENTER, ModernOverlay
from .draw import panel, rounded
from .pedal import PEDALS, PedalBarsMixin

if TYPE_CHECKING:
    from ...template.widget_config_types import TrailingConfig

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
    """Samples & style of one input; points: (sample number, value) newest first, mapped to the chart
    when painted"""

    __slots__ = ("name", "samples", "points", "pen", "dots", "fill")

    def __init__(self, name: str, size: int, color: QColor, width: float, dots: bool, fill: QColor | None):
        self.name = name
        self.samples: deque[float] = deque(maxlen=size)
        self.points = QPolygonF()
        self.pen = QPen(color, width)
        self.pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.dots = dots
        self.fill = fill

    def add(self, number: int, value: float):
        """Add newest sample, drop samples scrolled out (dots: negative value = no dot)"""
        self.samples.appendleft(value)
        points = self.points
        size = self.samples.maxlen or 0
        if self.dots:
            if value >= 0:
                points.prepend(QPointF(number, value))
            oldest = number - size
            while points.size() and points.last().x() <= oldest:
                points.removeLast()
        else:
            points.prepend(QPointF(number, min(max(value, 0.0), 1.0)))
            if points.size() > size:
                points.removeLast()


class Realtime(TrailingMixin, PedalBarsMixin, ModernOverlay):
    """Draw widget"""

    wcfg: TrailingConfig

    options = (
        "display_width", "display_height", "display_scale", "time_scale", "maximum_paused_frames",
        "show_inverted_trailing", "show_inverted_pedal", "show_tc_activation", "show_abs_activation",
        "show_throttle", "show_raw_throttle", "show_brake", "show_raw_brake", "show_clutch", "show_raw_clutch",
        "show_ffb", "show_absolute_ffb", "show_steering", "show_inverted_steering", "show_speed",
        "show_wheel_lock", "wheel_lock_threshold", "show_wheel_slip", "wheel_slip_threshold",
        "show_slip_angle_difference", "maximum_slip_angle_difference", "show_reference_line", "show_pedal_bars",
        "show_throttle_bar", "show_brake_bar", "show_clutch_bar", "show_ffb_bar", "pedal_bar_width_unfiltered",
        "pedal_bar_width_filtered", "pedal_bar_gap", "show_pedal_bar_brake_pressure",
        "pedal_bar_maximum_indicator_height", "pedal_bar_inner_gap", "show_pedal_bar_readings", "alert_flash_interval",
        "show_tc_activation_flash", "show_abs_activation_flash", "show_wheel_lock_flash", "show_wheel_slip_flash",
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
        self.step = float(self.display_scale)
        self.newest_right = bool(wcfg["show_inverted_trailing"])
        self.top_is_full = not wcfg["show_inverted_pedal"]
        # Pedal bars beside newest samples
        self.bar_colors = {key: getattr(theme, color) for key, _, color in PEDALS}
        self.alert_colors = {alert: getattr(theme, color) for alert, color in ALERT_THEME_COLORS.items()}
        self.gradients = {}
        self.fill_from_top = not self.top_is_full
        thickness = max(float(wcfg["pedal_bar_width_unfiltered"]) + float(wcfg["pedal_bar_width_filtered"]), 4.0)
        bar_gap = max(float(wcfg["pedal_bar_gap"]), 0.0)
        side_gap = unit * 0.45
        count = len(self.bar_keys)
        dot = max(unit * 0.42, 3.0)
        line = max(unit * 0.17, 1.5)
        inset = dot / 2 + 1
        # Maximum indicator beyond full input end of bars, readings beyond empty end: widget grows
        # when space around plot area too small
        max_h = max(float(wcfg["pedal_bar_maximum_indicator_height"]), 0.0) if count else 0.0
        max_gap = max(float(wcfg["pedal_bar_inner_gap"]), 0.0) if max_h else 0.0
        self.show_bar_readings = bool(count and wcfg["show_pedal_bar_readings"])
        reading_h = unit * 0.95 if self.show_bar_readings else 0.0
        column = max(thickness, self.text_width("small", "100") + unit * 0.1) if self.show_bar_readings else thickness
        full_end = max_h + max_gap + unit * 0.1 if max_h else 0.0
        empty_end = reading_h + unit * 0.05 if reading_h else 0.0
        top_end, bottom_end = (full_end, empty_end) if self.top_is_full else (empty_end, full_end)
        room = inset + pad
        extra_top = max(top_end - room, 0.0)
        extra_bottom = max(bottom_end - room, 0.0)
        side = count * column + (count - 1) * bar_gap + side_gap if count else 0.0
        self.set_size(width + side + pad * 2, height + pad * 2 + extra_top + extra_bottom)
        self.chart = QRectF(pad if self.newest_right else pad + side, pad + extra_top, width, height)
        self.plot_area = self.chart.adjusted(inset, inset, -inset, -inset)
        # Bars span plot area: full input level with plot full line
        bars_left = self.chart.right() + side_gap if self.newest_right else pad
        plot_area = self.plot_area
        columns = [bars_left + index * (column + bar_gap) for index in range(count)]
        self.bar_tracks = tuple(
            QRectF(left + (column - thickness) / 2, plot_area.top(), thickness, plot_area.height()) for left in columns)
        if self.top_is_full:
            max_top, reading_top = plot_area.top() - max_gap - max_h, plot_area.bottom() + unit * 0.05
        else:
            max_top, reading_top = plot_area.bottom() + max_gap, plot_area.top() - unit * 0.05 - reading_h
        self.max_rects = tuple(QRectF(track.left(), max_top, thickness, max_h) for track in self.bar_tracks) if max_h else ()
        self.reading_rects = tuple(QRectF(left, reading_top, column, reading_h) for left in columns)
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
        """Update when vehicle on track (pedal bars while plot paused too)"""
        paused = self.plot_paused()
        if not paused:
            values = dict(zip(self.plot_names, self.read_inputs()))
            number = self.samples_added + 1
            for plot in self.plots:
                plot.add(number, values[plot.name])
            self.samples_added = number
        if not self.bar_keys:
            if not paused:
                self.refresh(self.samples_added)
            return
        bars = self.read_bars()
        length = self.plot_area.height()
        self.refresh_keyed((self.samples_added, bars), (self.samples_added, tuple(
            (self.pixel_steps(min(max(filtered, 0.0), 1.0), length), self.pixel_steps(min(max(raw, 0.0), 1.0), length),
             filtered >= 1, raw >= 1, alert, f"{filtered * 100:.0f}" if self.show_bar_readings else "")
            for filtered, raw, alert in bars)))

    def paint_static(self, painter: QPainter):
        theme = self.theme
        panel(painter, QRectF(self.rect()), theme, self.panel_radius(), self.depth_effects)
        chart = self.chart
        rounded(painter, chart, self.radius(0.3), theme.tint(theme.surface_alt, 200))
        if self.wcfg["show_reference_line"]:
            area = self.plot_area
            for fraction in (0.25, 0.5, 0.75):
                y = round(area.bottom() - area.height() * fraction) - 0.5
                color = theme.tint(theme.text, 34 if fraction == 0.5 else 22)
                painter.fillRect(QRectF(chart.left() + 2, y, chart.width() - 4, 1), color)
        for track in (*self.bar_tracks, *self.max_rects):
            rounded(painter, track, min(track.width(), track.height()) / 2, theme.surface_raised)

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
        # Sample age (newest 0) from number, then x = start + age * step, y = base + value * scale
        newest = -self.samples_added
        to_chart = QTransform(-step, 0, 0, scale, start_x, base_y)
        painter.save()
        painter.setClipRect(self.chart)
        for plot in self.plots:
            if plot.dots:
                if plot.points.size():
                    painter.setPen(plot.pen)
                    painter.drawPoints(to_chart.map(plot.points.translated(newest, 0)))
                continue
            if plot.points.size() < 2:
                continue
            points = to_chart.map(plot.points.translated(newest, 0))
            if plot.fill is not None:
                area_points = QPolygonF(points)
                area_points.append(QPointF(points.last().x(), base_y))
                area_points.append(QPointF(points.first().x(), base_y))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(plot.fill)
                painter.drawPolygon(area_points)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(plot.pen)
            painter.drawPolyline(points)
        painter.restore()
        if self.bar_keys:
            self.paint_bars(painter)

    def paint_bars(self, painter: QPainter):
        """Pedal bars: filled to input as plotted, raw input tick, flashing alert color, force feedback
        orange while clipping, maximum indicator lit at full travel, readings"""
        theme = self.theme
        for index, (key, track, (filtered, raw, alert)) in enumerate(zip(self.bar_keys, self.bar_tracks, self.state[1])):
            color = self.alert_colors[alert] if alert else self.bar_colors[key]
            clipping = key == "ffb" and filtered >= 1
            if clipping:
                color = theme.warning
            self.draw_fill(painter, track, min(max(filtered, 0.0), 1.0), color)
            self.draw_tick(painter, track, min(max(raw, 0.0), 1.0))
            if self.max_rects and (raw >= 1 or clipping):  # full pedal travel (ffb: clipping)
                cap = self.max_rects[index]
                rounded(painter, cap, min(cap.width(), cap.height()) / 2, color)
            if self.show_bar_readings:
                self.draw_text(painter, self.reading_rects[index], f"{filtered * 100:.0f}", "small",
                               theme.text_dim, CENTER, elide=False)
