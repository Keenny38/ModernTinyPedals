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
Lap telemetry viewer: compare recorded laps along distance
"""

from __future__ import annotations

import csv
import html
import json
import logging
import math
import os
import threading
import time
from collections.abc import Callable
from typing import NamedTuple

from PySide6.QtCore import QLocale, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import units
from ..i18n import tr, trm
from ..setting import cfg
from ..userfile.corner_analysis import (
    SPEED_HYSTERESIS,
    CornerComparison,
    compare_corners,
    lap_time_delta,
    straights_delta,
)
from ..userfile.lap_marks import load_marks, remove_mark, set_mark
from ..userfile.motec_import import import_ld_file
from ..userfile.motec_ld import export_lap
from ..userfile.telemetry_lap import (
    IMPORT_FOLDER,
    LapData,
    LapFile,
    best_laps,
    compute_delta,
    decimate_minmax,
    delta_rate,
    group_sessions,
    interpolate,
    is_valid_name,
    lap_number_of,
    lap_stem,
    lap_time_of,
    lap_timestamp_of,
    list_laps,
    list_tracks,
    load_lap,
    monotonic_distance,
    read_lap_info,
    sector_bounds,
    theoretical_best,
)
from ..userfile.track_map import load_track_map_file
from ._common import BaseDialog, TextInputDialog, UIScaler, singleton_dialog

logger = logging.getLogger(__name__)

LAP_COLORS = tuple(QColor(color) for color in (
    "#38BDF8", "#F97316", "#A3E635", "#E879F9", "#FACC15", "#F43F5E", "#2DD4BF", "#A78BFA",
))
COLOR_A = LAP_COLORS[0]  # reference lap
COLOR_B = LAP_COLORS[1]  # first compared lap
COLOR_GRID = QColor(128, 128, 128, 70)
VIEWER_SETTING = ".lap_viewer.json"  # visible channels, in telemetry folder
LAP_CACHE_SIZE = 12  # loaded laps kept in memory
GAIN_WINDOW = 40.0  # meters, time gain/loss rate measured over this distance (smooths sampling noise)
GAIN_FULL_SCALE = 0.002  # seconds lost or gained per meter shown with full color
GAIN_COLOR = QColor("#22C55E")
LOSS_COLOR = QColor("#EF4444")
RELEASE_DELAY = 180_000  # ms hidden (page in background) before loaded laps are released
BACKGROUND_LOAD_COUNT = 3  # laps to read at once loaded in background (window stays responsive)


class Channel(NamedTuple):
    """Plotted channel"""

    column: str  # CSV column, "delta" for computed time delta
    title: str
    unit: str
    weight: float  # relative panel height
    fixed_range: tuple[float, float] | None = None
    group: str = ""  # menu group (per wheel channels)
    quantity: str = ""  # converted to user unit: speed, temperature, pressure, fuel (see display_units)


def wheel_channels(prefix: str, title: str, unit: str, quantity: str = "") -> tuple[Channel, ...]:
    return tuple(
        Channel(f"{prefix}_{wheel}", f"{title} {wheel.upper()}", unit, 0.8, group=title, quantity=quantity)
        for wheel in ("fl", "fr", "rl", "rr")
    )


CHANNELS = (
    Channel("delta", "Delta", "s", 1.2),
    Channel("delta_rate", "Time Gain/Loss", "s/100m", 1.0),
    Channel("speed_kph", "Speed", "km/h", 2.0, quantity="speed"),
    Channel("throttle", "Throttle", "", 1.0, (0.0, 1.0)),
    Channel("brake", "Brake", "", 1.0, (0.0, 1.0)),
    Channel("gear", "Gear", "", 0.8),
    Channel("steering", "Steering", "", 1.0, (-1.0, 1.0)),
    Channel("rpm", "RPM", "rpm", 1.0),
    Channel("clutch", "Clutch", "", 0.6, (0.0, 1.0)),
    Channel("fuel", "Fuel", "l", 0.8, quantity="fuel"),
    Channel("accel_lat", "Lateral G", "G", 1.0),
    Channel("accel_long", "Longitudinal G", "G", 1.0),
    Channel("tc_active", "TC Active", "", 0.5, (0.0, 1.0)),
    Channel("abs_active", "ABS Active", "", 0.5, (0.0, 1.0)),
    Channel("battery", "Battery", "%", 0.8),
    Channel("pos_z", "Elevation", "m", 0.8),
    *wheel_channels("tyre_temp", "Tyre Temp", "°C", "temperature"),
    *wheel_channels("tyre_pres", "Tyre Pressure", "kPa", "pressure"),
    *wheel_channels("tyre_wear", "Tyre Wear", "%"),
    *wheel_channels("brake_temp", "Brake Temp", "°C", "temperature"),
    *wheel_channels("wheel_speed", "Wheel Speed", "km/h", "speed"),
    *wheel_channels("ride_height", "Ride Height", "mm"),
    *wheel_channels("susp_defl", "Suspension", "mm"),
)
CHANNEL_MAP = {channel.column: channel for channel in CHANNELS}
MAP_MAX_ZOOM = 40.0  # track map & G circle zoom limit
TRACK_WIDTH = 12.0  # meters, circuit drawn under driving lines
ROAD_COLOR = QColor(128, 128, 128, 80)
DEFAULT_CHANNELS = ("delta", "speed_kph", "throttle", "brake", "gear", "steering")
PERCENT_RANGES = ((0.0, 1.0), (-1.0, 1.0))  # pedals & steering fractions shown in percent
DELTA_CHANNELS = ("delta", "delta_rate")  # computed against reference lap, symmetric range


def display_units() -> dict[str, tuple[Callable[[float], float] | None, str]]:
    """Conversion (None if same unit) & symbol of each quantity, from user units setting

    Lap files store km/h, °C, kPa & liters.
    """
    speed = cfg.units["speed_unit"]
    if speed == "MPH":
        speed_unit: tuple[Callable[[float], float] | None, str] = (lambda value: value / 1.609344, "mph")
    elif speed == "m/s":
        speed_unit = (lambda value: value / 3.6, "m/s")
    else:
        speed_unit = (None, "km/h")
    temperature = cfg.units["temperature_unit"]
    pressure = cfg.units["tyre_pressure_unit"]
    fuel = cfg.units["fuel_unit"]
    return {
        "speed": speed_unit,
        "temperature": (
            units.set_unit_temperature(temperature) if temperature == "Fahrenheit" else None,
            units.set_symbol_temperature(temperature)),
        "pressure": (
            units.set_unit_pressure(pressure) if pressure in ("psi", "bar") else None,
            units.set_symbol_pressure(pressure)),
        "fuel": (units.set_unit_fuel(fuel) if fuel == "Gallon" else None, units.set_symbol_fuel(fuel)),
    }


def nice_step(span: float, count: float) -> float:
    """Round axis step (1, 2 or 5 x 10^n) giving about count steps over span"""
    raw = max(span / max(count, 1.0), 1e-9)
    magnitude = 10 ** math.floor(math.log10(raw))
    for multiple in (1, 2, 5, 10):
        if raw <= multiple * magnitude:
            return multiple * magnitude
    return 10 * magnitude


def format_axis_time(seconds: float) -> str:
    """Time axis label: 45s, 1:05"""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, seconds = divmod(seconds, 60)
    return f"{int(minutes)}:{seconds:02.0f}"


def corner_label(number: int) -> str:
    """Short corner name: T1 (V1 in French)"""
    return trm(f"T{number}")


class PlotLap(NamedTuple):
    """Displayed lap"""

    key: str  # file path
    label: str
    data: LapData
    color: QColor


def lap_label(filename: str) -> str:
    """Short lap name from file name: "Lap 12 · 1:30.123" (file name if not a recorded lap name)"""
    number = lap_number_of(filename)
    if not number:
        return lap_stem(filename)
    text = trm(f"Lap {number}")
    lap_time = lap_time_of(filename)
    return f"{text} · {format_laptime(lap_time)}" if lap_time > 0 else text


def channel_title(channel: Channel) -> str:
    """Translated channel title, wheel suffix kept (Tyre Temp FL)"""
    if channel.group:
        return tr(channel.group) + channel.title[len(channel.group):]
    return tr(channel.title)


def format_value(value: float) -> str:
    """Cursor value, 2 decimals, none for whole numbers (gear)"""
    text = f"{value:.2f}"
    return text[:-3] if text.endswith(".00") else text


def format_channel_value(channel: Channel, value: float) -> str:
    """Value of channel for cursor & axis labels: pedals & steering in percent, signed deltas"""
    if channel.fixed_range in PERCENT_RANGES:
        return f"{value * 100:.0f}%"
    if channel.column == "delta":
        return f"{value:+.3f}"
    if channel.column == "delta_rate":
        return f"{value:+.2f}"
    if channel.column == "gear":
        return f"{value:.0f}"
    return format_value(value)


def format_axis_value(channel: Channel, value: float, span: float) -> str:
    """Value range label of channel panel"""
    if channel.fixed_range in PERCENT_RANGES or channel.column in DELTA_CHANNELS or channel.column == "gear":
        return format_channel_value(channel, value)
    if span >= 20:
        return f"{value:.0f}"
    if span >= 2:
        return f"{value:.1f}"
    return f"{value:.2f}"


def format_laptime(seconds: float) -> str:
    """Lap time text, "-" if unknown"""
    if seconds <= 0:
        return "-"
    minutes, seconds = divmod(seconds, 60)
    return f"{int(minutes)}:{seconds:06.3f}" if minutes else f"{seconds:.3f}"


def load_visible_channels(folder: str) -> list[str]:
    """Visible channels saved in telemetry folder"""
    try:
        with open(os.path.join(folder, VIEWER_SETTING), encoding="utf-8") as file:
            columns = json.load(file).get("channels", [])
        columns = [column for column in columns if column in CHANNEL_MAP]
        return columns or list(DEFAULT_CHANNELS)
    except (OSError, ValueError, AttributeError):
        return list(DEFAULT_CHANNELS)


def load_viewer_setting(folder: str) -> dict:
    """Lap viewer settings (visible channels, corner sensitivity) saved in telemetry folder"""
    try:
        with open(os.path.join(folder, VIEWER_SETTING), encoding="utf-8") as file:
            setting = json.load(file)
        return setting if isinstance(setting, dict) else {}
    except (OSError, ValueError):
        return {}


def save_viewer_setting(folder: str, **values):
    """Update lap viewer settings, other saved values kept"""
    setting = load_viewer_setting(folder)
    setting.update(values)
    try:
        with open(os.path.join(folder, VIEWER_SETTING), "w", encoding="utf-8") as file:
            json.dump(setting, file)
    except OSError as error:
        logger.warning("LAP VIEWER: unable to save setting: %s", error)


def save_visible_channels(folder: str, columns: list[str]):
    save_viewer_setting(folder, channels=columns)


class TracePlot(QWidget):
    """Stacked channel plots along lap distance

    Charts are drawn once into a cached pixmap (redrawn when laps, channels, zoom or size change),
    cursor & zoom selection are drawn over it.
    Mouse: wheel = zoom, drag = move, shift + drag = zoom to selection, double-click = reset,
    drag channel name (left margin) = move channel up or down.
    Keyboard: +/- zoom, left/right move, Home or 0 reset.

    Horizontal axis is lap distance, or lap time (time_axis): view & cursor are in axis units,
    track distance of reference lap is used for maps & corners (see distance_at_x).
    """

    cursor_changed = Signal()
    channels_reordered = Signal(list)  # channel columns in new order

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(UIScaler.size(40), UIScaler.size(26))
        self.laps: list[PlotLap] = []
        self.reference: PlotLap | None = None
        self.channels: list[Channel] = [CHANNEL_MAP[column] for column in DEFAULT_CHANNELS]
        self.deltas: dict[str, tuple[list[float], list[float]]] = {}
        self.sector_lines: list[float] = []
        self.view_start = 0.0
        self.view_end = 1.0
        self.cursor_distance: float | None = None  # cursor position in axis units (distance or time)
        self.margin_left = UIScaler.size(5)
        self.time_axis = False
        self.units = display_units()
        self.corner_marks: list[tuple[int, float]] = []  # corner number & apex distance of reference lap
        self._times: dict[str, tuple[list[float], list[float]]] = {}  # lap key: distances & lap times
        self._series: dict[tuple[str, str, bool], tuple[list[float], list[float]]] = {}
        self._ranges: dict[str, tuple[float, float]] = {}
        self._cache: QPixmap | None = None
        self._cache_key: tuple = ()
        self._version = 0
        self._drag: tuple[float, float, float] | None = None  # press x, view start, view end
        self._select: tuple[float, float] | None = None  # zoom selection x range
        self._move: tuple[int, int] | None = None  # moved channel: source & target panel index

    # Compatibility with 2 laps API
    @property
    def lap_a(self) -> LapData | None:
        return self.reference.data if self.reference else None

    @property
    def lap_b(self) -> LapData | None:
        compared = self.compared()
        return compared[0].data if compared else None

    @property
    def delta(self) -> list[tuple[float, float]]:
        compared = self.compared()
        if not compared or compared[0].key not in self.deltas:
            return []
        return list(zip(*self.deltas[compared[0].key]))

    def compared(self) -> list[PlotLap]:
        return [lap for lap in self.laps if lap is not self.reference]

    def set_laps(self, laps: list[PlotLap], reference_key: str = ""):
        self.laps = laps
        self.reference = next((lap for lap in laps if lap.key == reference_key), laps[0] if laps else None)
        self.deltas = {}
        if self.reference is not None:
            for lap in self.compared():
                points = compute_delta(self.reference.data, lap.data)
                if points:
                    self.deltas[lap.key] = ([point[0] for point in points], [point[1] for point in points])
        self.sector_lines = sector_bounds(self.reference.data) if self.reference else []
        self._series = {}
        self._times = {}
        self.units = display_units()
        self.invalidate()
        self.reset_view()

    def set_corner_marks(self, marks: list[tuple[int, float]]):
        """Corner numbers at apex distance, shown on charts"""
        if marks != self.corner_marks:
            self.corner_marks = marks
            self.invalidate()
            self.update()

    def set_time_axis(self, enabled: bool):
        """Lap time or distance horizontal axis, same part of lap kept in view"""
        if enabled == self.time_axis:
            return
        zoomed = self.zoomed()
        start, end = self.distance_at_x(self.view_start), self.distance_at_x(self.view_end)
        self.time_axis = enabled
        self._series = {}
        self.invalidate()
        self.cursor_distance = None
        if zoomed:
            self.set_view_distance(start, end)
        else:
            self.reset_view()

    # Axis conversion (time axis)
    def lap_times(self, lap: PlotLap) -> tuple[list[float], list[float]]:
        """Distances & lap times of lap, increasing distance"""
        cached = self._times.get(lap.key)
        if cached is None:
            if "lap_time" in lap.data.columns:
                cached = monotonic_distance(lap.data, "lap_time")
            else:  # no time recorded: distance used
                distances = monotonic_distance(lap.data, "distance")[0]
                cached = (distances, list(distances))
            self._times[lap.key] = cached
        return cached

    def x_at_distance(self, distance: float) -> float:
        """Axis position of reference lap distance"""
        if not self.time_axis or self.reference is None:
            return distance
        distances, times = self.lap_times(self.reference)
        return interpolate(distances, times, distance) if distances else distance

    def distance_at_x(self, x: float) -> float:
        """Reference lap distance at axis position"""
        if not self.time_axis or self.reference is None:
            return x
        distances, times = self.lap_times(self.reference)
        return interpolate(times, distances, x) if times else x

    def cursor_track_distance(self) -> float | None:
        """Reference lap distance at cursor, for maps"""
        return None if self.cursor_distance is None else self.distance_at_x(self.cursor_distance)

    def view_track_range(self) -> tuple[float, float]:
        """Reference lap distances of zoomed part, (0, 0) if not zoomed"""
        if not self.zoomed():
            return 0.0, 0.0
        return self.distance_at_x(self.view_start), self.distance_at_x(self.view_end)

    def set_view_distance(self, start: float, end: float):
        """Zoom on lap distances (corner)"""
        self.set_view(self.x_at_distance(start), self.x_at_distance(end))

    def show_distance(self, distance: float):
        """Cursor at reference lap distance (clicked on map), view moved to it if outside"""
        x = self.x_at_distance(distance)
        self.cursor_distance = x
        if not self.view_start <= x <= self.view_end:
            span = self.view_end - self.view_start
            self.set_view(x - span / 2, x + span / 2)
        self.update()
        self.cursor_changed.emit()

    def unit_of(self, channel: Channel) -> str:
        """Unit symbol of channel in user units"""
        if channel.quantity in self.units:
            return self.units[channel.quantity][1]
        return channel.unit

    def set_channels(self, columns: list[str]):
        self.channels = [CHANNEL_MAP[column] for column in columns if column in CHANNEL_MAP]
        widest = max((self.fontMetrics().horizontalAdvance(channel_title(channel)) for channel in self.channels),
                     default=0)
        self.margin_left = min(max(widest + UIScaler.pixel(12), UIScaler.size(5)), UIScaler.size(10))
        self.invalidate()
        self.update()

    def invalidate(self):
        """Recompute value ranges & redraw charts"""
        self._version += 1
        self._ranges = {}
        self._cache = None

    def max_distance(self) -> float:
        """End of horizontal axis: longest lap distance, or lap time"""
        if self.time_axis:
            return max((self.lap_times(lap)[1][-1] for lap in self.laps if self.lap_times(lap)[1]),
                       default=1.0) or 1.0
        return max((lap.data.distance[-1] for lap in self.laps if len(lap.data)), default=1.0) or 1.0

    def reset_view(self):
        self.set_view(0.0, self.max_distance())

    def set_view(self, start: float, end: float):
        max_distance = self.max_distance()
        if end - start >= max_distance:
            start, end = 0.0, max_distance
        elif start < 0:
            start, end = 0.0, end - start
        elif end > max_distance:
            start, end = start - (end - max_distance), max_distance
        self.view_start, self.view_end = max(start, 0.0), min(end, max_distance)
        self.update()
        self.cursor_changed.emit()

    def zoomed(self) -> bool:
        return self.view_end - self.view_start < self.max_distance() - 1

    # Coordinates
    def axis_height(self) -> float:
        """Room for horizontal axis labels below charts"""
        return self.fontMetrics().height() + 4

    def plot_rect(self) -> QRectF:
        return QRectF(self.margin_left, 4, max(self.width() - self.margin_left - 6, 1),
                      max(self.height() - 8 - self.axis_height(), 1))

    def x_of(self, distance: float, rect: QRectF) -> float:
        span = max(self.view_end - self.view_start, 1e-6)
        return rect.left() + (distance - self.view_start) / span * rect.width()

    def distance_of(self, x: float, rect: QRectF) -> float:
        span = self.view_end - self.view_start
        return self.view_start + (x - rect.left()) / max(rect.width(), 1) * span

    # Data
    def series(self, channel: Channel, lap: PlotLap, time_axis: bool | None = None,
               ) -> tuple[list[float], list[float]]:
        """Channel samples of lap by increasing axis position (distance or time), in user units, cached"""
        use_time = self.time_axis if time_axis is None else time_axis
        key = (lap.key, channel.column, use_time)
        cached = self._series.get(key)
        if cached is not None:
            return cached
        if channel.column == "delta":
            distances, values = self.deltas.get(lap.key, ([], []))
        elif channel.column == "delta_rate":
            distances, deltas = self.deltas.get(lap.key, ([], []))
            values = delta_rate(distances, deltas)
        elif channel.column in lap.data.columns:
            distances, values = monotonic_distance(lap.data, channel.column)
        else:
            distances, values = [], []
        convert = self.units.get(channel.quantity, (None, ""))[0] if channel.quantity else None
        if convert is not None:
            values = [convert(value) for value in values]
        xs = distances
        if use_time and distances:
            lap_distances, times = self.lap_times(lap)
            if len(lap_distances) == len(distances):  # same samples
                xs = times
            else:
                xs = [interpolate(lap_distances, times, distance) for distance in distances]
        cached = (xs, values)
        self._series[key] = cached
        return cached

    def value_range(self, channel: Channel) -> tuple[float, float]:
        if channel.fixed_range:
            return channel.fixed_range
        cached = self._ranges.get(channel.column)
        if cached is not None:
            return cached
        if channel.column in DELTA_CHANNELS:
            limit = delta_limit([self.series(channel, lap)[1] for lap in self.compared()])
            self._ranges[channel.column] = (-limit, limit)
            return -limit, limit
        low, high = float("inf"), float("-inf")
        for lap in self.laps:
            values = self.series(channel, lap)[1]
            if values:
                low, high = min(low, min(values)), max(high, max(values))
        if low > high:
            result = (0.0, 1.0)
        else:
            if high - low < 1e-6:
                high = low + 1
            padding = (high - low) * 0.05
            result = (low - padding, high + padding)
        self._ranges[channel.column] = result
        return result

    def panels(self, rect: QRectF) -> list[tuple[Channel, QRectF]]:
        total_weight = sum(channel.weight for channel in self.channels) or 1.0
        top = rect.top()
        result = []
        for channel in self.channels:
            height = rect.height() * channel.weight / total_weight
            result.append((channel, QRectF(rect.left(), top, rect.width(), max(height - 4, 1))))
            top += height
        return result

    # Paint
    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.plot_rect()
        text_color = self.palette().text().color()
        if not self.laps:
            painter.setPen(text_color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, tr("Select recorded laps to compare."))
            return
        ratio = self.devicePixelRatioF()
        key = (self.width(), self.height(), ratio, self.view_start, self.view_end, self._version, text_color.rgba())
        if self._cache is None or key != self._cache_key:
            self._cache = self.render_charts(rect, text_color, ratio)
            self._cache_key = key
        painter.drawPixmap(0, 0, self._cache)
        if self._move is not None:
            self.paint_move(painter, rect, text_color)
        if self._select is not None:
            left, right = sorted(self._select)
            painter.fillRect(QRectF(left, rect.top(), right - left, rect.height()), QColor(128, 128, 128, 60))
        if self.cursor_distance is not None and self._select is None:
            x = self.x_of(self.cursor_distance, rect)
            painter.setPen(QPen(text_color, 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            self.paint_cursor_values(painter, rect, x)

    def values_at(self, channel: Channel, x: float) -> list[tuple[PlotLap, str]]:
        """Value text of each lap at axis position (none past end of lap)"""
        values = []
        for lap in self.laps:
            xs, ys = self.series(channel, lap)
            if xs and xs[0] <= x <= xs[-1]:
                values.append((lap, format_channel_value(channel, interpolate(xs, ys, x))))
        return values

    def paint_cursor_values(self, painter: QPainter, rect: QRectF, x: float):
        """Value of each lap next to cursor, in each chart, colored like its lap"""
        if self.cursor_distance is None:
            return
        font = QFont(self.font())
        font.setPointSizeF(max(font.pointSizeF() * 0.85, 6))
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        line = metrics.height()
        background = QColor(self.palette().window().color())
        background.setAlphaF(0.85)
        for channel, panel in self.panels(rect):
            values = self.values_at(channel, self.cursor_distance)
            rows = min(len(values), int((panel.height() - 2) // line))
            if rows <= 0:
                continue
            width = max(metrics.horizontalAdvance(text) for _, text in values[:rows]) + 8
            left = x + 6 if x + 6 + width <= rect.right() else x - 6 - width
            box = QRectF(left, panel.top() + 2, width, rows * line + 2)
            painter.fillRect(box, background)
            for row, (lap, text) in enumerate(values[:rows]):
                painter.setPen(lap.color)
                painter.drawText(QPointF(left + 4, box.top() + 1 + row * line + metrics.ascent()), text)

    def render_charts(self, rect: QRectF, text_color: QColor, ratio: float) -> QPixmap:
        pixmap = QPixmap(round(self.width() * ratio), round(self.height() * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.paint_axis(painter, rect, text_color)
        for channel, panel in self.panels(rect):
            self.paint_channel(painter, channel, panel, text_color)
        self.paint_legend(painter, rect, text_color)
        ascent = painter.fontMetrics().ascent()
        # Sector lines of reference lap
        if self.sector_lines:
            painter.setPen(QPen(COLOR_GRID.lighter(160), 1, Qt.PenStyle.DotLine))
            for index, distance in enumerate(self.sector_lines):
                position = self.x_at_distance(distance)
                if self.view_start <= position <= self.view_end:
                    x = self.x_of(position, rect)
                    painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
                    painter.drawText(QPointF(x + 3, rect.top() + ascent), f"S{index + 2}")
        # Corner numbers at apex of reference lap
        if self.corner_marks:
            corner_pen = QPen(COLOR_GRID, 1, Qt.PenStyle.DotLine)
            label_color = QColor(text_color)
            label_color.setAlphaF(0.7)
            top = rect.top() + painter.fontMetrics().height() + ascent  # below sector labels
            for number, apex in self.corner_marks:
                position = self.x_at_distance(apex)
                if self.view_start <= position <= self.view_end:
                    x = self.x_of(position, rect)
                    painter.setPen(corner_pen)
                    painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
                    painter.setPen(label_color)
                    painter.drawText(QPointF(x + 3, top), corner_label(number))
        painter.end()
        return pixmap

    def paint_axis(self, painter: QPainter, rect: QRectF, text_color: QColor):
        """Distance (m) or lap time ticks below charts, faint grid lines across charts"""
        span = self.view_end - self.view_start
        if span <= 0:
            return
        metrics = painter.fontMetrics()
        sample = "0:00" if self.time_axis else "0000 m"
        step = nice_step(span, rect.width() / max(metrics.horizontalAdvance(sample) * 2.2, 1))
        grid = QColor(COLOR_GRID)
        grid.setAlphaF(grid.alphaF() * 0.5)
        label = QColor(text_color)
        label.setAlphaF(0.75)
        value = math.ceil(self.view_start / step) * step
        while value <= self.view_end + 1e-9:
            x = self.x_of(value, rect)
            painter.setPen(QPen(grid, 1))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            text = format_axis_time(value) if self.time_axis else f"{value:.0f} m"
            width = metrics.horizontalAdvance(text)
            left = min(max(x - width / 2, rect.left()), rect.right() - width)
            painter.setPen(label)
            painter.drawText(QPointF(left, rect.bottom() + 2 + metrics.ascent()), text)
            value += step

    def paint_move(self, painter: QPainter, rect: QRectF, text_color: QColor):
        """Moved channel highlighted, line where it will be placed"""
        source, target = self._move or (0, 0)
        panels = self.panels(rect)
        moved = panels[source][1]
        painter.fillRect(QRectF(0, moved.top(), rect.right(), moved.height()), QColor(56, 189, 248, 40))
        if target != source:
            target_panel = panels[target][1]
            y = target_panel.top() - 2 if target < source else target_panel.bottom() + 2
            painter.setPen(QPen(COLOR_A, 3))
            painter.drawLine(QPointF(0, y), QPointF(rect.right(), y))

    def panel_index_at(self, y: float) -> int:
        """Index of channel panel at height, nearest one if between panels"""
        panels = self.panels(self.plot_rect())
        for index, (_, panel) in enumerate(panels):
            if y < panel.bottom() + 2:
                return index
        return len(panels) - 1

    def paint_legend(self, painter: QPainter, rect: QRectF, text_color: QColor):
        """Color & name of each lap, top right of charts"""
        metrics = painter.fontMetrics()
        line_height = metrics.height()
        swatch = UIScaler.pixel(14)
        texts = [
            f"{lap.label} ({tr('Reference')})" if lap is self.reference else lap.label
            for lap in self.laps
        ]
        width = max(metrics.horizontalAdvance(text) for text in texts) + swatch + UIScaler.pixel(14)
        box = QRectF(rect.right() - width - 4, rect.top() + 4, width, line_height * len(texts) + 6)
        background = QColor(self.palette().window().color())
        background.setAlphaF(0.8)
        painter.fillRect(box, background)
        for index, (lap, text) in enumerate(zip(self.laps, texts)):
            y = box.top() + 3 + line_height * index
            painter.setPen(QPen(lap.color, 3))
            middle = y + line_height / 2
            painter.drawLine(QPointF(box.left() + 4, middle), QPointF(box.left() + 4 + swatch, middle))
            painter.setPen(text_color)
            painter.drawText(QPointF(box.left() + swatch + 10, y + metrics.ascent()), text)

    def paint_channel(self, painter: QPainter, channel: Channel, panel: QRectF, text_color: QColor):
        low, high = self.value_range(channel)
        span = high - low or 1.0

        def y_of(value: float) -> float:
            return panel.bottom() - (value - low) / span * panel.height()

        painter.setPen(QPen(COLOR_GRID, 1))
        painter.drawRect(panel)
        if low < 0 < high:
            painter.drawLine(QPointF(panel.left(), y_of(0)), QPointF(panel.right(), y_of(0)))
        painter.setPen(text_color)
        title = channel_title(channel)
        unit = self.unit_of(channel)
        painter.drawText(
            QRectF(0, panel.top(), self.margin_left - 4, panel.height()),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
            f"{title}\n{unit}" if unit else title,
        )
        self.paint_value_range(painter, channel, panel, low, high, text_color)
        painter.save()
        painter.setClipRect(panel)
        buckets = max(int(panel.width()), 1)
        steps = channel.column == "gear"  # gear changes at once: drawn as steps
        for lap in self.laps:
            xs, ys = self.series(channel, lap)
            if not xs:
                continue
            points = decimate_minmax(xs, ys, self.view_start, self.view_end, buckets)
            path = QPainterPath()
            last_y = 0.0
            for index, (distance, value) in enumerate(points):
                point = QPointF(self.x_of(distance, panel), y_of(value))
                if not index:
                    path.moveTo(point)
                elif steps:
                    path.lineTo(point.x(), last_y)
                    path.lineTo(point)
                else:
                    path.lineTo(point)
                last_y = point.y()
            painter.setPen(QPen(lap.color, 1.5))
            painter.drawPath(path)
        painter.restore()

    def paint_value_range(self, painter: QPainter, channel: Channel, panel: QRectF, low: float, high: float,
                          text_color: QColor):
        """Highest & lowest value of chart, small, inside its top & bottom left corners"""
        font = QFont(painter.font())
        font.setPointSizeF(max(font.pointSizeF() * 0.8, 6))
        metrics = QFontMetricsF(font)
        if panel.height() < metrics.height() * 2.2:
            return
        painter.save()
        painter.setFont(font)
        color = QColor(text_color)
        color.setAlphaF(0.55)
        painter.setPen(color)
        span = high - low
        painter.drawText(QPointF(panel.left() + 3, panel.top() + 1 + metrics.ascent()),
                         format_axis_value(channel, high, span))
        painter.drawText(QPointF(panel.left() + 3, panel.bottom() - 2 - metrics.descent()),
                         format_axis_value(channel, low, span))
        painter.restore()

    # Mouse & keyboard
    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        if x < self.plot_rect().left() and self.channels:  # channel name: move channel
            index = self.panel_index_at(event.position().y())
            self._move = (index, index)
            self.setCursor(Qt.CursorShape.SizeVerCursor)
            self.update()
        elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._select = (x, x)
        else:
            self._drag = (x, self.view_start, self.view_end)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, event):
        rect = self.plot_rect()
        if self._move is not None:
            source, target = self._move
            self._move = None
            if source != target:
                self.channels.insert(target, self.channels.pop(source))
                self.invalidate()
                self.channels_reordered.emit([channel.column for channel in self.channels])
            self.update()
        if self._select is not None:
            left, right = sorted(self._select)
            self._select = None
            if right - left > 4:
                self.set_view(self.distance_of(left, rect), self.distance_of(right, rect))
            self.update()
        self._drag = None
        self.unsetCursor()

    def mouseMoveEvent(self, event):
        rect = self.plot_rect()
        x = event.position().x()
        if self._move is not None:
            self._move = (self._move[0], self.panel_index_at(event.position().y()))
            self.update()
            return
        if self._drag is None and self._select is None:  # channel names can be dragged
            if x < rect.left():
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.unsetCursor()
        if self._select is not None:
            self._select = (self._select[0], min(max(x, rect.left()), rect.right()))
        elif self._drag is not None:
            press_x, start, end = self._drag
            shift = (press_x - x) / max(rect.width(), 1) * (end - start)
            self.set_view(start + shift, end + shift)
        if rect.contains(event.position()):
            self.cursor_distance = self.distance_of(x, rect)
        else:
            self.cursor_distance = None
        self.update()
        self.cursor_changed.emit()

    def leaveEvent(self, event):
        self.cursor_distance = None
        self.update()
        self.cursor_changed.emit()

    def wheelEvent(self, event):
        """Zoom around cursor"""
        center = self.distance_of(event.position().x(), self.plot_rect())
        self.zoom(0.8 if event.angleDelta().y() > 0 else 1.25, center)

    def zoom(self, factor: float, center: float | None = None):
        if center is None:
            center = (self.view_start + self.view_end) / 2
        start = center - (center - self.view_start) * factor
        end = center + (self.view_end - center) * factor
        if end - start < 5:
            return
        self.set_view(start, end)

    def keyPressEvent(self, event):
        key = event.key()
        span = self.view_end - self.view_start
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom(0.8, self.cursor_distance)
        elif key == Qt.Key.Key_Minus:
            self.zoom(1.25, self.cursor_distance)
        elif key == Qt.Key.Key_Left:
            self.set_view(self.view_start - span * 0.2, self.view_end - span * 0.2)
        elif key == Qt.Key.Key_Right:
            self.set_view(self.view_start + span * 0.2, self.view_end + span * 0.2)
        elif key in (Qt.Key.Key_Home, Qt.Key.Key_0):
            self.reset_view()
        else:
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.reset_view()

    def cursor_values(self) -> str:
        """Values of each channel at cursor, each value colored like its lap (rich text)"""
        position = self.cursor_distance
        if position is None:
            return ""
        distance = self.distance_at_x(position)
        where = f"{format_axis_time(position)} · {distance:.0f} m " if self.time_axis else f"{distance:.0f} m "
        texts = [where]
        for channel in self.channels:
            values = self.values_at(channel, position)
            if values:
                colored = " / ".join(
                    f"<span style='color:{lap.color.name()}'>{html.escape(text)}</span>" for lap, text in values)
                texts.append(f"<b>{html.escape(channel_title(channel))}</b> {colored}")
        return " &nbsp;&nbsp; ".join(texts)


def delta_limit(series: list[list[float]]) -> float:
    """Delta chart half range: 95th percentile of each lap's delta, lowest median of laps

    An aberrant lap (cut short, spin) would otherwise flatten every other lap's delta;
    its line is clipped instead.
    """
    limits = []
    for values in series:
        if values:
            ordered = sorted(abs(value) for value in values)
            limits.append(ordered[min(int(len(ordered) * 0.95), len(ordered) - 1)])
    if not limits:
        return 0.1
    limits.sort()
    return max(limits[(len(limits) - 1) // 2] * 1.15, 0.1)


class LapMapBase(QWidget):
    """Base of side views following trace plot cursor & zoom

    Laps are drawn once into a cached pixmap (redrawn when laps, zoom or size change),
    cursor markers are drawn over it, so moving mouse over charts stays cheap.
    """

    empty_text = ""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(UIScaler.size(16), UIScaler.size(16))
        self.laps: list[PlotLap] = []
        self.cursor_distance: float | None = None
        self.view: tuple[float, float] = (0.0, 0.0)  # zoomed range, (0, 0) if not zoomed
        self._cache: QPixmap | None = None
        self._cache_key: tuple = ()
        self._version = 0
        self.zoom = 1.0  # view zoom (mouse wheel), 1 = whole map
        self.pan = QPointF()  # view offset (drag)
        self._pan_drag: tuple[QPointF, QPointF] | None = None  # press position, pan at press
        self._press: QPointF | None = None  # left press position, a click if released near it

    def apply_zoom(self, point: QPointF) -> QPointF:
        """Screen position of unzoomed point"""
        return QPointF(point.x() * self.zoom + self.pan.x(), point.y() * self.zoom + self.pan.y())

    def reset_zoom(self):
        self.zoom, self.pan = 1.0, QPointF()
        self.update()

    def wheelEvent(self, event):
        """Zoom around mouse"""
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        zoom = min(max(self.zoom * factor, 1.0), MAP_MAX_ZOOM)
        if zoom == self.zoom:
            return
        mouse = event.position()
        ratio = zoom / self.zoom
        self.pan = QPointF(mouse.x() - (mouse.x() - self.pan.x()) * ratio,
                           mouse.y() - (mouse.y() - self.pan.y()) * ratio)
        self.zoom = zoom
        if zoom == 1.0:
            self.pan = QPointF()
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._press = event.position()
        if self.zoom > 1.0:
            self._pan_drag = (event.position(), QPointF(self.pan))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._pan_drag is not None:
            start, pan = self._pan_drag
            self.pan = pan + event.position() - start
            self.update()

    def mouseReleaseEvent(self, event):
        press, self._press = self._press, None
        self._pan_drag = None
        self.unsetCursor()
        if press is not None and (event.position() - press).manhattanLength() < 4 and self.has_data():
            self.map_clicked(event.position())

    def map_clicked(self, position: QPointF):
        """Clicked without moving"""

    def mouseDoubleClickEvent(self, event):
        self._press = None
        self.reset_zoom()

    def set_laps(self, laps: list[PlotLap]):
        self.laps = laps
        self.prepare()
        self._version += 1
        self.update()

    def prepare(self):
        """Compute cached data after laps change"""

    def has_data(self) -> bool:
        return False

    def set_cursor(self, distance: float | None, view: tuple[float, float]):
        if (distance, view) != (self.cursor_distance, self.view):
            self.cursor_distance, self.view = distance, view
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.has_data():
            painter.setPen(self.palette().color(self.foregroundRole()))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, tr(self.empty_text))
            return
        ratio = self.devicePixelRatioF()
        key = (self.width(), self.height(), ratio, self.view, self._version, self.zoom, self.pan.x(), self.pan.y())
        if self._cache is None or key != self._cache_key:
            pixmap = QPixmap(round(self.width() * ratio), round(self.height() * ratio))
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.GlobalColor.transparent)
            cache_painter = QPainter(pixmap)
            cache_painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self.draw_laps(cache_painter)
            cache_painter.end()
            self._cache, self._cache_key = pixmap, key
        painter.drawPixmap(0, 0, self._cache)
        if self.cursor_distance is not None:
            for point, color in self.cursor_points(self.cursor_distance):
                painter.setPen(QPen(QColor("#FFFFFF"), 1.5))
                painter.setBrush(color)
                painter.drawEllipse(point, 5, 5)

    def draw_laps(self, painter: QPainter):
        """Draw laps (cached)"""

    def cursor_points(self, distance: float) -> list[tuple[QPointF, QColor]]:
        """Screen position & color of each lap at cursor distance"""
        return []


class TrajectoryMap(LapMapBase):
    """Driving line of laps from recorded positions, with cursor position of each lap

    Zoomed part of trace plot is highlighted, so braking points & lines can be compared.
    """

    empty_text = "No position recorded"
    distance_clicked = Signal(float)  # reference lap distance nearest to clicked point

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setToolTip(tr("Click the driving line to show this point in charts"))
        self.corner_marks: list[tuple[int, float]] = []  # corner number & apex distance of reference lap
        self._lines: list[tuple[list[float], list[float], list[float], QColor]] = []
        self._bounds = (0.0, 0.0, 1.0, 1.0)
        self._outline: list[tuple[float, float]] = []  # circuit from track map file
        self.road: list[tuple[float, float]] = []  # drawn circuit: track map, or reference lap line
        self.show_gain = False  # first compared lap line colored by time gained / lost against reference
        self._gain: list[tuple[float, float, float, float]] = []  # distance, x, y, delta rate (s/m)

    def set_laps(self, laps: list[PlotLap], outline: list[tuple[float, float]] | None = None):
        """Set laps, and circuit outline from track map file (reference lap line if none)"""
        self._outline = list(outline or [])
        super().set_laps(laps)

    def prepare(self):
        self._lines = []
        for lap in self.laps:
            points = self.positions(lap.data)
            if points:
                distances, xs, ys = (list(values) for values in zip(*points))
                self._lines.append((distances, xs, ys, lap.color))
        if self._outline:
            self.road = self._outline
        elif self._lines:
            self.road = list(zip(self._lines[0][1], self._lines[0][2]))
        else:
            self.road = []
        self._gain = self.gain_points() if self.show_gain else []
        coords = self.road + [coord for line in self._lines for coord in zip(line[1], line[2])]
        if coords:
            self._bounds = (
                min(coord[0] for coord in coords), min(coord[1] for coord in coords),
                max(coord[0] for coord in coords), max(coord[1] for coord in coords),
            )

    def has_data(self) -> bool:
        return bool(self._lines)

    def set_corner_marks(self, marks: list[tuple[int, float]]):
        if marks != self.corner_marks:
            self.corner_marks = marks
            self._version += 1
            self.update()

    def map_clicked(self, position: QPointF):
        """Reference lap distance nearest to clicked point"""
        distances, xs, ys, _ = self._lines[0]
        nearest = min(
            range(len(distances)),
            key=lambda index: (self.to_screen(xs[index], ys[index]) - position).manhattanLength(),
            default=-1)
        if nearest >= 0:
            self.distance_clicked.emit(distances[nearest])

    def draw_corner_marks(self, painter: QPainter):
        """Corner numbers next to reference line at apex"""
        if not self.corner_marks or not self._lines:
            return
        distances, xs, ys, _ = self._lines[0]
        if len(distances) < 2:
            return
        font = QFont(painter.font())
        font.setPointSizeF(max(font.pointSizeF() * 0.8, 6))
        font.setBold(True)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        text_color = self.palette().color(self.foregroundRole())
        background = QColor(self.palette().window().color())
        background.setAlphaF(0.75)
        for number, apex in self.corner_marks:
            point = self.to_screen(interpolate(distances, xs, apex), interpolate(distances, ys, apex))
            text = corner_label(number)
            box = QRectF(point.x() + 4, point.y() - metrics.height() - 2,
                         metrics.horizontalAdvance(text) + 6, metrics.height())
            painter.fillRect(box, background)
            painter.setPen(text_color)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def set_show_gain(self, enabled: bool):
        self.show_gain = enabled
        self.set_laps(self.laps, self._outline)

    def gain_points(self) -> list[tuple[float, float, float, float]]:
        """Positions of first compared lap with rate of time lost (positive) or gained against reference"""
        if len(self.laps) < 2:
            return []
        reference, compared = self.laps[0].data, self.laps[1].data
        points = self.positions(compared)
        delta = compute_delta(reference, compared)
        if len(points) < 2 or len(delta) < 2:
            return []
        distances = [point[0] for point in delta]
        deltas = [point[1] for point in delta]
        half = GAIN_WINDOW / 2
        return [
            (distance, x, y,
             (interpolate(distances, deltas, distance + half) - interpolate(distances, deltas, distance - half))
             / GAIN_WINDOW)
            for distance, x, y in points
        ]

    @staticmethod
    def gain_color(rate: float) -> QColor:
        """Red when losing time, green when gaining, neutral grey when even"""
        amount = min(abs(rate) / GAIN_FULL_SCALE, 1.0)
        target = LOSS_COLOR if rate > 0 else GAIN_COLOR
        neutral = QColor("#9CA3AF")
        return QColor(
            round(neutral.red() + (target.red() - neutral.red()) * amount),
            round(neutral.green() + (target.green() - neutral.green()) * amount),
            round(neutral.blue() + (target.blue() - neutral.blue()) * amount),
        )

    def draw_gain(self, painter: QPainter):
        """Reference line thin, compared lap line colored by time gained / lost, legend"""
        view_start, view_end = self.view
        zoomed = view_end - view_start > 0
        _, xs, ys, color = self._lines[0]
        path = QPainterPath(self.to_screen(xs[0], ys[0]))
        for x, y in zip(xs[1:], ys[1:]):
            path.lineTo(self.to_screen(x, y))
        reference_color = QColor(color)
        reference_color.setAlphaF(0.5)
        painter.setPen(QPen(reference_color, 1.2))
        painter.drawPath(path)
        for (distance, x0, y0, rate), (_, x1, y1, _) in zip(self._gain, self._gain[1:]):
            line_color = self.gain_color(rate)
            if zoomed and not view_start <= distance <= view_end:
                line_color.setAlphaF(0.35)
            pen = QPen(line_color, 3.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(self.to_screen(x0, y0), self.to_screen(x1, y1))
        margin = UIScaler.pixel(6)
        line = self.fontMetrics().height()
        for row, (text, legend_color) in enumerate(((tr("Losing time"), LOSS_COLOR), (tr("Gaining time"), GAIN_COLOR))):
            top = self.height() - margin - line * (2 - row)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(legend_color)
            painter.drawEllipse(QRectF(margin, top + line * 0.3, line * 0.4, line * 0.4))
            painter.setPen(self.palette().color(self.foregroundRole()))
            painter.drawText(QPointF(margin + line * 0.6, top + line * 0.75), text)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    @staticmethod
    def positions(lap: LapData | None) -> list[tuple[float, float, float]]:
        """(distance, x, y) of lap, empty if positions not recorded"""
        if lap is None:
            return []
        xs, ys = lap.columns.get("pos_x"), lap.columns.get("pos_y")
        if not xs or not ys:
            return []
        return [(distance, x, y) for distance, x, y in zip(lap.distance, xs, ys) if x or y]

    def base_scale(self) -> float:
        """Pixels per meter of whole map (not zoomed)"""
        min_x, min_y, max_x, max_y = self._bounds
        margin = UIScaler.pixel(10)
        return min((self.width() - margin * 2) / max(max_x - min_x, 1e-6),
                   (self.height() - margin * 2) / max(max_y - min_y, 1e-6))

    def to_screen(self, x: float, y: float) -> QPointF:
        min_x, min_y, max_x, max_y = self._bounds
        scale = self.base_scale()
        offset_x = (self.width() - (max_x - min_x) * scale) / 2
        offset_y = (self.height() - (max_y - min_y) * scale) / 2
        # Game Y (forward) axis points up on screen
        return self.apply_zoom(
            QPointF(offset_x + (x - min_x) * scale, self.height() - offset_y - (y - min_y) * scale))

    def draw_road(self, painter: QPainter):
        """Circuit as a road band of track width, and start line"""
        road = self.road
        if len(road) < 2:
            return
        path = QPainterPath(self.to_screen(*road[0]))
        for point in road[1:]:
            path.lineTo(self.to_screen(*point))
        (x0, y0), (x1, y1) = road[0], road[-1]
        if (x1 - x0) ** 2 + (y1 - y0) ** 2 < 50 ** 2:  # closed circuit
            path.closeSubpath()
        width = max(TRACK_WIDTH * self.base_scale() * self.zoom, UIScaler.pixel(9))  # visible unzoomed
        pen = QPen(ROAD_COLOR, width)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)
        # Start line across road
        start = self.to_screen(*road[0])
        ahead = next((self.to_screen(*point) for point in road[1:]
                      if (self.to_screen(*point) - start).manhattanLength() > 2), None)
        if ahead is not None:
            dx, dy = ahead.x() - start.x(), ahead.y() - start.y()
            length = (dx * dx + dy * dy) ** 0.5
            nx, ny = -dy / length * width * 0.7, dx / length * width * 0.7
            painter.setPen(QPen(self.palette().color(self.foregroundRole()), 2))
            painter.drawLine(QPointF(start.x() - nx, start.y() - ny), QPointF(start.x() + nx, start.y() + ny))

    def draw_laps(self, painter: QPainter):
        view_start, view_end = self.view
        zoomed = view_end - view_start > 0
        painter.setBrush(Qt.BrushStyle.NoBrush)
        self.draw_road(painter)
        if self._gain:
            self.draw_gain(painter)
            self.draw_corner_marks(painter)
            return
        for distances, xs, ys, color in self._lines:
            if len(distances) < 2:
                continue
            for highlight in (False, True):
                if highlight and not zoomed:
                    continue
                path = QPainterPath()
                started = False
                for distance, x, y in zip(distances, xs, ys):
                    if highlight and not view_start <= distance <= view_end:
                        started = False
                        continue
                    point = self.to_screen(x, y)
                    if started:
                        path.lineTo(point)
                    else:
                        path.moveTo(point)
                        started = True
                faded = QColor(color)
                if zoomed and not highlight:
                    faded.setAlphaF(0.35)
                painter.setPen(QPen(faded, 3 if highlight else 1.5))
                painter.drawPath(path)
        self.draw_corner_marks(painter)

    def cursor_points(self, distance: float) -> list[tuple[QPointF, QColor]]:
        return [
            (self.to_screen(interpolate(distances, xs, distance), interpolate(distances, ys, distance)), color)
            for distances, xs, ys, color in self._lines
        ]


class GCircle(LapMapBase):
    """Lateral vs longitudinal acceleration of laps (zoomed part only when zoomed)"""

    empty_text = "No acceleration recorded"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list[tuple[list[float], list[float], list[float], QColor]] = []
        self._scale = 1.0

    def prepare(self):
        self._points = []
        for lap in self.laps:
            lat, lon = lap.data.columns.get("accel_lat"), lap.data.columns.get("accel_long")
            if lat and lon:
                self._points.append((list(lap.data.distance), list(lat), list(lon), lap.color))

    def has_data(self) -> bool:
        return bool(self._points)

    def center(self) -> QPointF:
        return self.apply_zoom(QPointF(self.width() / 2, self.height() / 2))

    def draw_laps(self, painter: QPainter):
        view_start, view_end = self.view
        zoomed = view_end - view_start > 0
        visible = [
            ([(lat, lon) for distance, lat, lon in zip(distances, lats, lons)
              if not zoomed or view_start <= distance <= view_end], color)
            for distances, lats, lons, color in self._points
        ]
        limit = max((max(abs(lat), abs(lon)) for points, _ in visible for lat, lon in points), default=1.0)
        limit = max(1.0, float(int(limit) + 1))
        radius = (min(self.width(), self.height()) / 2 - UIScaler.pixel(10)) * self.zoom
        center = self.center()
        scale = self._scale = radius / limit
        painter.setPen(QPen(COLOR_GRID, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for ring in range(1, int(limit) + 1):
            painter.drawEllipse(center, ring * scale, ring * scale)
        painter.drawLine(QPointF(center.x() - radius, center.y()), QPointF(center.x() + radius, center.y()))
        painter.drawLine(QPointF(center.x(), center.y() - radius), QPointF(center.x(), center.y() + radius))
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(QPointF(center.x() + 3, center.y() - scale + painter.fontMetrics().ascent()), "1G")
        painter.setPen(Qt.PenStyle.NoPen)
        for points, color in visible:
            faded = QColor(color)
            faded.setAlphaF(0.35)
            painter.setBrush(faded)
            step = max(len(points) // 3000, 1)
            for lat, lon in points[::step]:
                # Braking (negative longitudinal) at bottom
                painter.drawEllipse(QPointF(center.x() + lat * scale, center.y() - lon * scale), 1.5, 1.5)

    def cursor_points(self, distance: float) -> list[tuple[QPointF, QColor]]:
        center, scale = self.center(), self._scale
        return [
            (QPointF(center.x() + interpolate(distances, lats, distance) * scale,
                     center.y() - interpolate(distances, lons, distance) * scale), color)
            for distances, lats, lons, color in self._points
        ]


def signed(value: float, decimals: int = 0, unit: str = "") -> str:
    """Signed number text, minus sign as typeset"""
    return f"{value:+.{decimals}f}{unit}".replace("-", chr(0x2212))  # minus sign


class CornerTable(QWidget):
    """Corner by corner comparison of first compared lap with reference lap

    Time: positive = compared lap slower. Braking: positive = brakes later.
    Full throttle: negative = full throttle earlier. Click a corner to zoom charts on it.
    """

    corner_selected = Signal(float, float)  # corner start & end distance
    corners_changed = Signal(list)  # (corner number, apex distance) of reference lap

    COLUMNS = ("Corner", "Time", "Min Speed", "Braking", "Full Throttle", "Trail Braking", "Coasting", "Overlap")
    COLOR_GAIN = QColor("#22C55E")
    COLOR_LOSS = QColor("#EF4444")

    def __init__(self, parent=None, folder: str = ""):
        super().__init__(parent)
        self.rows: list[CornerComparison] = []
        self.folder = folder  # telemetry folder, sensitivity saved in viewer setting
        self.laps: tuple[LapData | None, LapData | None] = (None, None)
        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.spin_hysteresis = QSpinBox(self)
        self.spin_hysteresis.setRange(3, 40)
        self.spin_hysteresis.setSuffix(" km/h")
        saved = load_viewer_setting(folder).get("corner_hysteresis", SPEED_HYSTERESIS) if folder else SPEED_HYSTERESIS
        self.spin_hysteresis.setValue(int(saved) if isinstance(saved, (int, float)) else int(SPEED_HYSTERESIS))
        self.spin_hysteresis.setToolTip(tr("Speed drop & rise counted as a corner: lower finds more corners"))
        self.spin_hysteresis.valueChanged.connect(self.hysteresis_changed)
        layout_sensitivity = QHBoxLayout()
        layout_sensitivity.addWidget(QLabel(tr("Corner detection"), self))
        layout_sensitivity.addWidget(self.spin_hysteresis)
        layout_sensitivity.addStretch(1)
        self.table = QTreeWidget(self)
        self.table.setRootIsDecorated(False)
        self.table.setHeaderLabels([tr(text) for text in self.COLUMNS])
        self.speed_convert, self.speed_unit = display_units()["speed"]
        self.table.headerItem().setToolTip(2, trm(f"Minimum speed ({self.speed_unit}): reference lap, compared lap"))
        self.table.headerItem().setToolTip(3, tr("Braking point of compared lap: positive = brakes later"))
        self.table.headerItem().setToolTip(4, tr("Full throttle point of compared lap: negative = earlier"))
        self.table.headerItem().setToolTip(5, tr("Seconds braking while turning: reference lap, compared lap"))
        self.table.headerItem().setToolTip(
            6, tr("Seconds without throttle nor brake: reference lap, compared lap (red: more than reference)"))
        self.table.headerItem().setToolTip(
            7, tr("Seconds with throttle & brake together: reference lap, compared lap (red: more than reference)"))
        self.table.itemClicked.connect(self.select_row)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)
        layout.addLayout(layout_sensitivity)
        layout.addWidget(self.table, stretch=1)

    def hysteresis_changed(self, value: int):
        if self.folder:
            save_viewer_setting(self.folder, corner_hysteresis=value)
        self.set_laps(*self.laps)

    def set_laps(self, reference: LapData | None, compared: LapData | None):
        self.laps = (reference, compared)
        self.speed_convert, self.speed_unit = display_units()["speed"]  # follows units setting
        self.rows = (
            compare_corners(reference, compared, self.spin_hysteresis.value()) if reference is not None else [])
        self.table.clear()
        self.corners_changed.emit([(row.corner.number, row.corner.apex) for row in self.rows])
        if not self.rows:
            self.label.setText(tr("No corner found: speed not recorded."))
            return
        if compared is None:
            self.label.setText(tr("Check a second lap to compare it with reference lap, corner by corner."))
        else:
            self.label.setText(tr("Compared lap against reference lap. Click a corner to zoom on it."))
        for row in self.rows:
            self.table.addTopLevelItem(self.make_item(row))
        if reference is not None and compared is not None:  # corners + straights = lap delta
            for text, delta in ((tr("Straights"), straights_delta(self.rows, reference, compared)),
                                (tr("Total"), lap_time_delta(reference, compared))):
                item = QTreeWidgetItem()
                item.setText(0, text)
                item.setText(1, signed(delta, 2))
                item.setForeground(1, self.COLOR_LOSS if delta > 0.005 else self.COLOR_GAIN if delta < -0.005 else QColor())
                font = QFont(item.font(0))
                font.setBold(text == tr("Total"))
                item.setFont(0, font)
                item.setFont(1, font)
                self.table.addTopLevelItem(item)
        for column in range(self.table.columnCount()):
            self.table.resizeColumnToContents(column)

    def speed(self, value: float) -> float:
        return self.speed_convert(value) if self.speed_convert is not None else value

    def make_item(self, row: CornerComparison) -> QTreeWidgetItem:
        ref, other = row.reference, row.compared
        item = QTreeWidgetItem()
        item.setText(0, f"{corner_label(row.corner.number)}  ({row.corner.apex:.0f} m)")
        if other is None:  # reference lap values only
            item.setText(1, f"{ref.time:.2f}")
            item.setText(2, f"{self.speed(ref.min_speed):.0f}")
            item.setText(3, f"{ref.brake_point:.0f} m" if ref.brake_point >= 0 else "—")
            item.setText(4, f"{ref.throttle_point:.0f} m" if ref.throttle_point >= 0 else "—")
            for column, value in ((5, ref.trail_braking), (6, ref.coasting), (7, ref.overlap)):
                item.setText(column, f"{value:.1f} s")
            return item
        delta = other.time - ref.time
        item.setText(1, signed(delta, 2))
        item.setForeground(1, self.COLOR_LOSS if delta > 0.005 else self.COLOR_GAIN if delta < -0.005 else QColor())
        speed_delta = self.speed(other.min_speed) - self.speed(ref.min_speed)
        item.setText(2, f"{self.speed(ref.min_speed):.0f} / {self.speed(other.min_speed):.0f}  ({signed(speed_delta)})")
        if speed_delta <= -1 or speed_delta >= 1:
            item.setForeground(2, self.COLOR_GAIN if speed_delta > 0 else self.COLOR_LOSS)
        for column, ref_point, other_point in ((3, ref.brake_point, other.brake_point),
                                               (4, ref.throttle_point, other.throttle_point)):
            if ref_point >= 0 and other_point >= 0:
                item.setText(column, signed(other_point - ref_point, 0, " m"))
            else:
                item.setText(column, "—")
        # Driving: trail braking (no judgement), coasting & overlap (more = time lost)
        for column, ref_value, other_value, lower_better in (
                (5, ref.trail_braking, other.trail_braking, False),
                (6, ref.coasting, other.coasting, True),
                (7, ref.overlap, other.overlap, True)):
            item.setText(column, f"{ref_value:.1f} / {other_value:.1f} s")
            if lower_better and other_value - ref_value >= 0.1:
                item.setForeground(column, self.COLOR_LOSS)
            elif lower_better and ref_value - other_value >= 0.1:
                item.setForeground(column, self.COLOR_GAIN)
        return item

    def select_row(self, item: QTreeWidgetItem, *_):
        index = self.table.indexOfTopLevelItem(item)
        if 0 <= index < len(self.rows):
            corner = self.rows[index].corner
            self.corner_selected.emit(corner.start, corner.end)


class LapEntry(NamedTuple):
    """Lap list entry"""

    file: LapFile
    info: dict
    external: bool = False


def import_motec_log(window, filename: str) -> str:
    """Import MoTeC log (dropped on app) to imported laps, shown in lap viewer page, returns message"""
    from .tools_view import open_tool

    name = os.path.basename(filename)
    try:
        paths = import_ld_file(filename, os.path.join(cfg.path.telemetry, IMPORT_FOLDER))
    except (OSError, ValueError) as error:
        logger.error("LAP VIEWER: unable to import %s: %s", filename, error)
        return trm(f"Unable to import <b>{name}</b>: {error}")
    if not paths:
        return trm(f"No complete lap in: {name}")
    open_tool("lap_viewer.LapViewer", window)
    viewers = [  # LapViewer name is singleton wrapper, not class
        viewer for viewer in window.findChildren(BaseDialog)
        if type(viewer).__name__ == "LapViewer" and viewer.isVisibleTo(window)
    ]
    if viewers:
        viewers[-1].add_external(paths, paths)
    return trm(f"MoTeC log imported: <b>{name}</b> ({len(paths)} laps)")


@singleton_dialog("lap_viewer")
class LapViewer(BaseDialog):
    """Recorded lap telemetry viewer"""

    COL_LAP, COL_TIME, COL_S1, COL_S2, COL_S3, COL_INFO = range(6)

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Lap Telemetry Viewer"))
        self.filepath = cfg.path.telemetry
        self.entries: list[LapEntry] = []
        self.external: list[LapEntry] = []
        self.reference_key = ""
        self._lap_cache: dict[str, LapData | None] = {}  # recently loaded laps, see read_lap
        self._released = False  # loaded laps released while hidden, reloaded when shown
        self._released_view = (0.0, 0.0)  # chart zoom when released
        self._release_timer = QTimer(self)
        self._release_timer.setSingleShot(True)
        self._release_timer.setInterval(RELEASE_DELAY)
        self._release_timer.timeout.connect(self.release_laps)
        self._outline_cache: dict[str, list[tuple[float, float]]] = {}  # track name: circuit
        self._cache_mtime: dict[str, float] = {}  # loaded lap: file time, reloaded if file changed
        self._info_cache: dict[str, tuple[float, dict]] = {}  # lap info: file time & info
        self._marks: dict[str, dict[str, dict]] = {}  # folder: lap marks (kept, note)
        self._saved_selection: tuple = ()  # last saved checked laps & reference of track
        self._loader: threading.Thread | None = None  # background lap loading
        self._loaded: dict[str, LapData | None] = {}
        self._load_pending = False
        self._load_timer = QTimer(self)
        self._load_timer.setInterval(50)
        self._load_timer.timeout.connect(self.check_background_load)
        setting = load_viewer_setting(self.filepath)

        # Track selection
        self.combo_track = QComboBox(self)
        self.combo_track.currentTextChanged.connect(self.load_track)
        button_refresh = QPushButton(tr("Refresh"))
        button_refresh.clicked.connect(self.refresh_tracks)
        button_add = QPushButton(tr("Add File..."))
        button_add.setToolTip(tr("Add laps from another folder or track, or import a MoTeC log (.ld)"))
        button_add.clicked.connect(self.add_files)
        layout_track = QHBoxLayout()
        layout_track.addWidget(QLabel(tr("Track")))
        layout_track.addWidget(self.combo_track, stretch=1)
        layout_track.addWidget(button_refresh)
        layout_track.addWidget(button_add)
        button_library = QPushButton(tr("Imported Laps..."))
        button_library.setToolTip(tr("Laps imported from MoTeC logs: add to viewer, rename, delete"))
        button_library.clicked.connect(self.open_library)
        layout_track.addWidget(button_library)

        # Lap list
        self.lap_list = QTreeWidget(self)
        self.lap_list.setRootIsDecorated(True)  # laps grouped by session
        self.lap_list.setUniformRowHeights(True)
        self.lap_list.setHeaderLabels([tr("Lap"), tr("Time"), "S1", "S2", "S3", tr("Info")])
        self.lap_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lap_list.customContextMenuRequested.connect(self.lap_menu)
        self.lap_list.itemChanged.connect(self.lap_checked)
        self.lap_list.itemDoubleClicked.connect(self.set_reference_item)
        self.lap_list.setMinimumWidth(UIScaler.size(22))
        self.label_best = QLabel(self)
        self.label_best.setWordWrap(True)
        self.label_warning = QLabel(self)
        self.label_warning.setWordWrap(True)
        self.label_warning.setStyleSheet("color: #F97316;")
        panel_laps = QWidget(self)
        layout_laps = QVBoxLayout(panel_laps)
        layout_laps.setContentsMargins(0, 0, 0, 0)
        label_help = QLabel(tr("Check laps to compare, double-click to set reference lap."))
        label_help.setWordWrap(True)
        self.check_clean = QCheckBox(tr("Hide invalid, out & in laps").replace("&", "&&"), self)  # & is not a shortcut
        self.check_clean.setChecked(bool(setting.get("hide_unclean_laps", False)))
        self.check_clean.toggled.connect(self.toggle_clean_laps)
        layout_laps.addWidget(label_help)
        layout_laps.addWidget(self.check_clean)
        layout_laps.addWidget(self.lap_list, stretch=1)
        layout_laps.addWidget(self.label_best)
        layout_laps.addWidget(self.label_warning)

        # Charts
        self.label_cursor = QLabel(self)
        self.label_cursor.setMinimumHeight(UIScaler.size(1.6))
        self.label_cursor.setWordWrap(True)
        self.label_cursor.setTextFormat(Qt.TextFormat.RichText)
        self.plot = TracePlot(self)
        self.plot.cursor_changed.connect(self.update_cursor_info)
        self.plot.channels_reordered.connect(self.reorder_channels)
        self.trajectory = TrajectoryMap(self)
        self.trajectory.distance_clicked.connect(self.plot.show_distance)
        self.trajectory.show_gain = bool(setting.get("map_time_gain", False))
        self.check_gain = QCheckBox(tr("Color by time gained / lost"), self)
        self.check_gain.setToolTip(tr(
            "First compared lap line colored against reference lap: red where losing time, green where gaining"))
        self.check_gain.setChecked(self.trajectory.show_gain)
        self.check_gain.toggled.connect(self.toggle_time_gain)
        panel_map = QWidget(self)
        layout_map = QVBoxLayout(panel_map)
        layout_map.setContentsMargins(0, 0, 0, 0)
        layout_map.addWidget(self.check_gain)
        layout_map.addWidget(self.trajectory, stretch=1)
        self.gcircle = GCircle(self)
        self.side_tabs = QTabWidget(self)
        self.side_tabs.addTab(panel_map, tr("Track Map"))
        self.side_tabs.addTab(self.gcircle, tr("G Circle"))
        self.corners = CornerTable(self, self.filepath)
        self.corners.corner_selected.connect(lambda start, end: self.plot.set_view_distance(start, end))
        self.corners.corners_changed.connect(self.set_corner_marks)
        self.side_tabs.addTab(self.corners, tr("Corners"))

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(panel_laps)
        splitter.addWidget(self.plot)
        splitter.addWidget(self.side_tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([UIScaler.size(26), UIScaler.size(50), UIScaler.size(20)])

        # Buttons
        self.visible_channels = load_visible_channels(self.filepath)
        self.plot.set_channels(self.visible_channels)
        self.check_time_axis = QCheckBox(tr("Time axis"), self)
        self.check_time_axis.setToolTip(tr("Charts along lap time instead of lap distance"))
        self.check_time_axis.setChecked(bool(setting.get("time_axis", False)))
        self.plot.set_time_axis(self.check_time_axis.isChecked())
        self.check_time_axis.toggled.connect(self.toggle_time_axis)
        button_channels = QPushButton(tr("Channels"))
        button_channels.setMenu(self.channel_menu())
        button_export = QPushButton(tr("Export"))
        menu_export = QMenu(button_export)
        menu_motec = menu_export.addMenu("MoTeC i2 (.ld)")
        menu_motec.addAction(tr("Reference Lap...")).triggered.connect(self.export_motec)
        menu_motec.addAction(tr("Displayed Laps...")).triggered.connect(lambda: self.export_motec_many(False))
        menu_motec.addAction(tr("All Laps of Track...")).triggered.connect(lambda: self.export_motec_many(True))
        menu_export.addAction(tr("CSV, Displayed Laps...")).triggered.connect(self.export_csv)
        button_export.setMenu(menu_export)
        button_export.setToolTip(tr("Export laps to MoTeC i2 log files (.ld), or displayed charts to CSV (Excel)"))
        button_close = QPushButton(tr("Close"))
        button_close.clicked.connect(self.close)
        layout_button = QHBoxLayout()
        label_help = QLabel(tr(
            "Wheel: zoom, drag: move, Shift+drag: zoom area, double-click: reset (charts & map). "
            "Drag a channel name to reorder. Click the map to show a point."))
        label_help.setWordWrap(True)
        layout_button.addWidget(label_help, stretch=1)
        layout_button.addWidget(self.check_time_axis)
        layout_button.addWidget(button_channels)
        layout_button.addWidget(button_export)
        layout_button.addWidget(button_close)

        layout_main = QVBoxLayout()
        layout_main.addLayout(layout_track)
        layout_main.addWidget(self.label_cursor)
        layout_main.addWidget(splitter, stretch=1)
        layout_main.addLayout(layout_button)
        layout_main.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        self.setLayout(layout_main)
        self.resize(UIScaler.size(84), UIScaler.size(44))
        self.refresh_tracks()

    # Channels
    def channel_menu(self) -> QMenu:
        menu = QMenu(self)
        self.channel_actions: dict[str, QAction] = {}
        submenus: dict[str, QMenu] = {}
        for channel in CHANNELS:
            target = menu
            if channel.group:
                if channel.group not in submenus:
                    submenus[channel.group] = QMenu(tr(channel.group), menu)
                    menu.addMenu(submenus[channel.group])
                target = submenus[channel.group]
                text = channel.title[len(channel.group):].strip()
            else:
                text = tr(channel.title)
            action = QAction(text, target)
            action.setCheckable(True)
            action.setChecked(channel.column in self.visible_channels)
            action.toggled.connect(lambda checked, column=channel.column: self.toggle_channel(column, checked))
            target.addAction(action)
            self.channel_actions[channel.column] = action
        menu.addSeparator()
        menu.addAction(tr("Reset")).triggered.connect(self.reset_channels)
        return menu

    def toggle_channel(self, column: str, checked: bool):
        if checked and column not in self.visible_channels:
            self.visible_channels.append(column)  # added at bottom, can be moved by dragging its name
        elif not checked and column in self.visible_channels:
            self.visible_channels.remove(column)
        self.plot.set_channels(self.visible_channels)
        save_visible_channels(self.filepath, self.visible_channels)

    def reorder_channels(self, columns: list[str]):
        """Channels moved in charts, keep order"""
        self.visible_channels = list(columns)
        save_visible_channels(self.filepath, self.visible_channels)

    def reset_channels(self):
        self.visible_channels = list(DEFAULT_CHANNELS)
        self.plot.set_channels(self.visible_channels)
        save_visible_channels(self.filepath, self.visible_channels)
        for column, action in self.channel_actions.items():
            action.blockSignals(True)
            action.setChecked(column in self.visible_channels)
            action.blockSignals(False)

    # Laps
    def refresh_tracks(self):
        current = self.combo_track.currentText()
        self.combo_track.blockSignals(True)
        self.combo_track.clear()
        self.combo_track.addItems(list_tracks(self.filepath))
        self.combo_track.blockSignals(False)
        if current:
            self.combo_track.setCurrentText(current)
        self.drop_changed_laps()
        self._marks.clear()
        self.load_track(self.combo_track.currentText())
        if not self.combo_track.count() and not self.external:
            self.label_cursor.setText(tr("No recorded lap. Enable the Recorder module, then drive a few laps."))

    def load_track(self, track: str):
        laps = list_laps(self.filepath, track) if track else []
        self.entries = [LapEntry(lap, self.lap_info(lap.path)) for lap in laps]
        # Laps shown last time on this track, else fastest lap compared with newest other lap
        saved = load_viewer_setting(self.filepath).get("selections", {})
        saved = saved.get(track, {}) if isinstance(saved, dict) else {}
        paths = {lap.filename: lap.path for lap in laps}
        checked = {paths[name] for name in saved.get("checked", []) if name in paths}
        reference = paths.get(saved.get("reference", ""), "")
        if checked and reference in checked:
            self.reference_key = reference
        else:
            best = best_laps(laps, 1)
            self.reference_key = best[0].path if best else (laps[0].path if laps else "")
            checked = {self.reference_key}
            newest = next((lap.path for lap in laps if lap.valid and lap.path != self.reference_key), "")
            if newest:
                checked.add(newest)
        self._saved_selection = (track, tuple(sorted(os.path.basename(path) for path in checked)),
                                 os.path.basename(self.reference_key))
        self.fill_list(checked)

    def lap_info(self, path: str) -> dict:
        """Lap info (first line of file), read again only if file changed"""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0
        cached = self._info_cache.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        info = read_lap_info(path)
        self._info_cache[path] = (mtime, info)
        return info

    def drop_changed_laps(self):
        """Forget loaded laps whose file changed or was removed (refresh)"""
        for path in list(self._lap_cache):
            try:
                changed = os.path.getmtime(path) != self._cache_mtime.get(path)
            except OSError:
                changed = True
            if changed:
                self._lap_cache.pop(path, None)
                self._cache_mtime.pop(path, None)

    def lap_marks(self, path: str) -> dict:
        """Kept state & note of lap"""
        folder, name = os.path.split(path)
        if folder not in self._marks:
            self._marks[folder] = load_marks(folder)
        return self._marks[folder].get(name, {})

    def save_selection(self, paths: list[str]):
        """Remember checked laps & reference of current track"""
        track = self.combo_track.currentText()
        track_paths = {entry.file.path for entry in self.entries}
        names = tuple(sorted(os.path.basename(path) for path in paths if path in track_paths))
        reference = os.path.basename(self.reference_key) if self.reference_key in track_paths else ""
        selection = (track, names, reference)
        if not track or not names or selection == self._saved_selection:
            return
        self._saved_selection = selection
        selections = load_viewer_setting(self.filepath).get("selections", {})
        if not isinstance(selections, dict):
            selections = {}
        selections[track] = {"checked": list(names), "reference": reference}
        save_viewer_setting(self.filepath, selections=selections)

    def toggle_clean_laps(self, enabled: bool):
        save_viewer_setting(self.filepath, hide_unclean_laps=enabled)
        self.fill_list(set(self.checked_paths()))

    def toggle_time_axis(self, enabled: bool):
        save_viewer_setting(self.filepath, time_axis=enabled)
        self.plot.set_time_axis(enabled)

    def set_corner_marks(self, marks: list):
        self.plot.set_corner_marks(marks)
        self.trajectory.set_corner_marks(marks)

    def all_entries(self) -> list[LapEntry]:
        return self.entries + self.external

    def fill_list(self, checked: set[str]):
        """Laps grouped by session (newest first), added files on top, sessions with shown laps expanded"""
        expanded = {
            item.data(self.COL_LAP, Qt.ItemDataRole.UserRole + 1)
            for item in self.session_items() if item.isExpanded()
        }
        self.lap_list.blockSignals(True)
        self.lap_list.clear()
        # Added files may come from other tracks: theoretical best & best sectors of current track only
        sectors = [self.entry_sectors(entry) for entry in self.entries if entry.file.valid]
        best_total, best_sectors = theoretical_best(sectors)
        hide_unclean = self.check_clean.isChecked()
        entries = [
            entry for entry in self.entries
            if not hide_unclean or entry.file.path in checked or entry.file.path == self.reference_key
            or (entry.file.valid and entry.info.get("kind") not in ("out", "in"))
        ]
        groups: list[tuple[list[LapEntry], bool]] = [
            (group, False)
            for group in group_sessions(entries, lambda entry: entry.file.filename, lambda entry: entry.info)
        ]
        added: dict[str, list[LapEntry]] = {}  # added laps by folder (imported log, other track)
        for entry in self.external:
            added.setdefault(os.path.dirname(entry.file.path), []).append(entry)
        groups[:0] = [(group, True) for group in added.values()]
        for index, (group, is_added) in enumerate(groups):
            header = self.add_session_item(group, is_added)
            key = header.data(self.COL_LAP, Qt.ItemDataRole.UserRole + 1)
            vehicle = str(group[0].info.get("vehicle", ""))
            fastest = min((entry for entry in group if entry.file.valid and entry.file.lap_time > 0),
                          key=lambda entry: entry.file.lap_time, default=None)
            for entry in group:
                self.add_lap_item(header, entry, checked, best_sectors, vehicle, entry is fastest)
            has_checked = any(entry.file.path in checked for entry in group)
            header.setExpanded(has_checked or key in expanded or (index == 0 and not expanded))
        self.lap_list.blockSignals(False)
        if best_total > 0:
            self.label_best.setText(trm(f"Theoretical best: {format_laptime(best_total)}"))
        else:
            self.label_best.setText("")
        self.load_laps()

    def add_session_item(self, group: list[LapEntry], is_added: bool) -> QTreeWidgetItem:
        """Session header: session & date, best lap, number of laps & vehicle"""
        header = QTreeWidgetItem(self.lap_list)
        header.setFlags(Qt.ItemFlag.ItemIsEnabled)  # not checkable nor selectable
        first = group[0]
        if is_added:  # imported log or other folder
            folder = os.path.dirname(first.file.path)
            title = os.path.basename(folder)
            key = f"added {folder}"
        else:
            session = str(first.info.get("session", "")) or tr("Session")
            start = first.info.get("session_start")  # recorded, else when first lap started
            timestamp = start if isinstance(start, (int, float)) else (
                lap_timestamp_of(first.file.filename) - first.file.lap_time)
            date = time.strftime("%d/%m %H:%M", time.localtime(timestamp)) if timestamp > 0 else ""
            title = f"{tr(session)}  {date}".strip()
            key = f"{session} {first.file.filename[:19]}"
        header.setText(self.COL_LAP, title)
        header.setData(self.COL_LAP, Qt.ItemDataRole.UserRole + 1, key)
        best = min((entry.file.lap_time for entry in group if entry.file.valid and entry.file.lap_time > 0), default=0)
        header.setText(self.COL_TIME, format_laptime(best))
        details = [trm(f"{len(group)} laps") if len(group) > 1 else tr("1 lap")]
        vehicle = str(first.info.get("vehicle", ""))
        if is_added:
            details.append(tr("added"))
        if vehicle:
            details.append(vehicle)
        header.setText(self.COL_INFO, ", ".join(details))
        font = QFont(header.font(self.COL_LAP))
        font.setBold(True)
        for column in (self.COL_LAP, self.COL_TIME):
            header.setFont(column, font)
        header.setFirstColumnSpanned(False)
        return header

    def add_lap_item(self, header: QTreeWidgetItem, entry: LapEntry, checked: set[str], best_sectors,
                     vehicle: str, is_fastest: bool):
        """Lap row: number (star on fastest of session), time, sectors (best in purple), info; invalid laps dimmed"""
        item = QTreeWidgetItem(header)
        number = lap_number_of(entry.file.filename)
        label = trm(f"Lap {number}") if number else lap_stem(entry.file.filename)
        if is_fastest:
            label = f"★ {label}"
            item.setToolTip(self.COL_LAP, tr("Fastest valid lap of session"))
        item.setText(self.COL_LAP, label)
        item.setText(self.COL_TIME, format_laptime(entry.file.lap_time))
        item.setData(self.COL_LAP, Qt.ItemDataRole.UserRole, entry.file.path)
        item.setCheckState(
            self.COL_LAP, Qt.CheckState.Checked if entry.file.path in checked else Qt.CheckState.Unchecked)
        lap_sectors = self.entry_sectors(entry)
        for column, value, best in zip(
                (self.COL_S1, self.COL_S2, self.COL_S3), lap_sectors or (0, 0, 0), best_sectors or (0, 0, 0)):
            item.setText(column, format_laptime(value))
            if value > 0 and abs(value - best) < 0.0005 and entry.file.valid and not entry.external:
                item.setForeground(column, QColor("#A855F7"))  # best sector
        info = self.entry_text(entry, vehicle)
        if not entry.external:
            mark = self.lap_marks(entry.file.path)
            extra = [tr("kept")] if mark.get("kept") else []
            if mark.get("note"):
                extra.append(f"“{mark['note']}”")
                item.setToolTip(self.COL_INFO, str(mark["note"]))
            info = ", ".join(filter(None, [info, *extra]))
        item.setText(self.COL_INFO, info)
        if not entry.file.valid or entry.info.get("kind") in ("out", "in"):
            dimmed = self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
            for column in (self.COL_TIME, self.COL_INFO):
                item.setForeground(column, dimmed)

    def session_items(self) -> list[QTreeWidgetItem]:
        items = (self.lap_list.topLevelItem(index) for index in range(self.lap_list.topLevelItemCount()))
        return [item for item in items if item is not None]

    def lap_items(self) -> list[QTreeWidgetItem]:
        """Lap rows of every session"""
        laps = []
        for header in self.session_items():
            for index in range(header.childCount()):
                item = header.child(index)
                if item is not None:
                    laps.append(item)
        return laps

    @staticmethod
    def entry_sectors(entry: LapEntry) -> list[float]:
        sectors = entry.info.get("sectors")
        if isinstance(sectors, list) and len(sectors) == 3 and all(isinstance(v, (int, float)) for v in sectors):
            return [float(value) for value in sectors]
        return []

    @staticmethod
    def entry_text(entry: LapEntry, session_vehicle: str = "") -> str:
        """Lap details not shown by its session header"""
        texts = []
        if not entry.file.valid:
            texts.append(tr("invalid"))
        kind = entry.info.get("kind", "")
        if kind == "out":
            texts.append(tr("out lap"))
        elif kind == "in":
            texts.append(tr("in lap"))
        if entry.external and entry.info.get("session"):
            texts.append(tr(str(entry.info["session"])))
        vehicle = str(entry.info.get("vehicle", ""))
        if vehicle and vehicle != session_vehicle:
            texts.append(vehicle)
        return ", ".join(texts)

    def checked_paths(self) -> list[str]:
        return [
            item.data(self.COL_LAP, Qt.ItemDataRole.UserRole) for item in self.lap_items()
            if item.checkState(self.COL_LAP) == Qt.CheckState.Checked
        ]

    def lap_checked(self, item: QTreeWidgetItem, column: int):
        if column == self.COL_LAP:
            self.load_laps()

    def set_reference_item(self, item: QTreeWidgetItem, *_):
        path = item.data(self.COL_LAP, Qt.ItemDataRole.UserRole)
        if not path:  # session header
            return
        self.reference_key = path
        if item.checkState(self.COL_LAP) != Qt.CheckState.Checked:
            item.setCheckState(self.COL_LAP, Qt.CheckState.Checked)  # reloads laps
        else:
            self.load_laps()

    def lap_menu(self, position):
        item = self.lap_list.itemAt(position)
        if item is None or not item.data(self.COL_LAP, Qt.ItemDataRole.UserRole):  # no lap (session header)
            return
        path = item.data(self.COL_LAP, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction(tr("Set as Reference")).triggered.connect(lambda: self.set_reference_item(item))
        menu.addAction(tr("Export MoTeC...")).triggered.connect(lambda: self.export_motec(path))
        if path in {entry.file.path for entry in self.entries}:  # recorded lap of track
            menu.addSeparator()
            mark = self.lap_marks(path)
            action_keep = menu.addAction(tr("Keep Lap"))
            action_keep.setCheckable(True)
            action_keep.setChecked(bool(mark.get("kept")))
            action_keep.setToolTip(tr("Kept lap is never removed by the recorder"))
            action_keep.toggled.connect(lambda checked: self.keep_lap(path, checked))
            menu.addAction(tr("Note...")).triggered.connect(lambda: self.edit_note(path))
            menu.addSeparator()
            menu.addAction(tr("Delete Lap")).triggered.connect(lambda: self.delete_lap(path))
        menu.exec(self.lap_list.viewport().mapToGlobal(position))

    def keep_lap(self, path: str, keep: bool):
        """Kept lap is never removed by recorder (oldest laps over limit are)"""
        set_mark(path, kept=keep)
        self._marks.pop(os.path.dirname(path), None)
        self.fill_list(set(self.checked_paths()))

    def edit_note(self, path: str):
        """Free text note of lap, shown in lap list"""
        def saving(text: str) -> bool:
            set_mark(path, note=text)
            self._marks.pop(os.path.dirname(path), None)
            self.fill_list(set(self.checked_paths()))
            return True

        TextInputDialog(self, tr("Lap Note"), tr("Note for this lap (empty to remove):"), saving,
                        str(self.lap_marks(path).get("note", ""))).show()

    def delete_lap(self, path: str):
        """Delete recorded lap file after confirmation"""
        if not self.confirm_operation("Delete Lap", f"Delete <b>{os.path.basename(path)}</b> permanently?"):
            return
        try:
            os.remove(path)
        except OSError as error:
            logger.error("LAP VIEWER: unable to delete %s: %s", path, error)
            self.label_cursor.setText(trm(f"Unable to delete lap: {error}"))
            return
        remove_mark(path)
        self._marks.pop(os.path.dirname(path), None)
        self._lap_cache.pop(path, None)
        self.entries = [entry for entry in self.entries if entry.file.path != path]
        if self.reference_key == path:
            self.reference_key = ""
        self.fill_list(set(self.checked_paths()) - {path})

    def read_lap(self, path: str) -> LapData | None:
        if not path:
            return None
        if path in self._lap_cache:
            self._lap_cache[path] = self._lap_cache.pop(path)  # most recently used last
            return self._lap_cache[path]
        try:
            lap = load_lap(path)
        except (OSError, ValueError) as error:
            logger.error("LAP VIEWER: unable to load %s: %s", path, error)
            self.label_cursor.setText(trm(f"Unable to load lap: {error}"))
            lap = None
        self.store_lap(path, lap)
        return lap

    def store_lap(self, path: str, lap: LapData | None):
        """Keep loaded lap, oldest laps forgotten over cache size (a lap takes several MB in memory)"""
        self._lap_cache[path] = lap
        try:
            self._cache_mtime[path] = os.path.getmtime(path)
        except OSError:
            self._cache_mtime.pop(path, None)
        limit = max(LAP_CACHE_SIZE, len(self.checked_paths()))
        while len(self._lap_cache) > limit:
            oldest = next(iter(self._lap_cache))
            self._lap_cache.pop(oldest)
            self._cache_mtime.pop(oldest, None)

    def load_in_background(self, paths: list[str]):
        """Read laps in a thread, charts updated once all are loaded (window stays responsive)"""
        if self._loader is not None:
            self._load_pending = True  # selection changed meanwhile: shown when current loading ends
            return
        results: dict[str, LapData | None] = {}

        def loading():
            for path in paths:
                try:
                    results[path] = load_lap(path)
                except (OSError, ValueError) as error:
                    logger.error("LAP VIEWER: unable to load %s: %s", path, error)
                    results[path] = None

        self._loaded = results
        self._loader = threading.Thread(target=loading, daemon=True, name="Lap viewer loading")
        self._loader.start()
        self._load_timer.start()
        self.label_cursor.setText(trm(f"Loading {len(paths)} laps..."))

    def check_background_load(self):
        """Background loading finished: laps kept, charts updated"""
        if self._loader is None or self._loader.is_alive():
            return
        self._load_timer.stop()
        self._loader = None
        self._load_pending = False
        for path, lap in self._loaded.items():
            self.store_lap(path, lap)
        self._loaded = {}
        self.label_cursor.setText("")
        self.load_laps()

    def is_loading(self) -> bool:
        return self._loader is not None

    def hideEvent(self, event):
        """Page left in background: loaded laps (several MB each) released after a while"""
        self._release_timer.start()
        super().hideEvent(event)

    def showEvent(self, event):
        self._release_timer.stop()
        if self._released:  # same laps & zoom as before
            self._released = False
            self.load_laps()
            self.plot.set_view(*self._released_view)
        super().showEvent(event)

    def release_laps(self):
        """Free memory of loaded laps while hidden, see showEvent"""
        if self.isVisible() or self._released or self._loader is not None:
            return
        self._released_view = self.plot.view_start, self.plot.view_end
        self._lap_cache.clear()
        self._cache_mtime.clear()
        self.plot.set_laps([])
        self.trajectory.set_laps([])
        self.gcircle.set_laps([])
        self.corners.set_laps(None, None)
        self._released = True
        logger.info("LAP VIEWER: loaded laps released while hidden")

    def load_laps(self):
        paths = self.checked_paths()
        if paths and self.reference_key not in paths:
            self.reference_key = paths[0]
        ordered = sorted(paths, key=lambda path: path != self.reference_key)  # reference first
        missing = [path for path in ordered if path not in self._lap_cache]
        if self._loader is not None or len(missing) >= BACKGROUND_LOAD_COUNT:
            self.load_in_background(missing)
            return
        self.save_selection(paths)
        entries = {entry.file.path: entry for entry in self.all_entries()}
        laps: list[PlotLap] = []
        for path in ordered:
            data = self.read_lap(path)
            if data is not None:
                label = self.entry_label(entries.get(path), path)
                laps.append(PlotLap(path, label, data, LAP_COLORS[len(laps) % len(LAP_COLORS)]))
        self.plot.set_laps(laps, self.reference_key)
        self.trajectory.set_laps(laps, self.track_outline(laps))
        self.gcircle.set_laps(laps)
        self.corners.set_laps(self.plot.lap_a, self.plot.lap_b)
        self.update_list_colors(laps)
        vehicles = sorted({str(lap.data.meta.get("vehicle")) for lap in laps if lap.data.meta.get("vehicle")})
        if len(vehicles) > 1:
            self.label_warning.setText(trm(f"Laps from different vehicles: {', '.join(vehicles)}"))
        else:
            self.label_warning.setText("")

    @staticmethod
    def entry_label(entry: LapEntry | None, path: str) -> str:
        """Lap name in charts legend: "Lap 12 · 1:11.525 · Race 03/10", or "log: Lap 3 · 2:18.200" """
        label = lap_label(os.path.basename(path))
        if entry is None or entry.external:
            return f"{os.path.basename(os.path.dirname(path))}: {label}"
        session = str(entry.info.get("session", ""))
        timestamp = lap_timestamp_of(entry.file.filename)
        date = time.strftime("%d/%m", time.localtime(timestamp)) if timestamp > 0 else ""
        where = " ".join(filter(None, [tr(session) if session else "", date]))
        return f"{label} · {where}" if where else label

    def track_outline(self, laps: list[PlotLap]) -> list[tuple[float, float]]:
        """Circuit coordinates from track map file (recorded by Mapping module), empty if none"""
        if not laps:
            return []
        track = str(laps[0].data.meta.get("track", ""))
        if not track:  # older lap files: "<track> - <class>" folder
            track = os.path.basename(os.path.dirname(laps[0].key)).rsplit(" - ", 1)[0]
        if track not in self._outline_cache:
            coords, _, _ = load_track_map_file(cfg.path.track_map, track)
            self._outline_cache[track] = [(float(x), float(y)) for x, y in coords] if coords else []
        return self._outline_cache[track]

    def update_list_colors(self, laps: list[PlotLap]):
        colors = {lap.key: lap.color for lap in laps}
        self.lap_list.blockSignals(True)
        for item in self.lap_items():
            path = item.data(self.COL_LAP, Qt.ItemDataRole.UserRole)
            color = colors.get(path)
            item.setForeground(self.COL_LAP, color if color is not None else self.palette().text().color())
            font = QFont(item.font(self.COL_LAP))
            font.setBold(path == self.reference_key and color is not None)
            item.setFont(self.COL_LAP, font)
            item.setFont(self.COL_TIME, font)
        self.lap_list.blockSignals(False)
        for column in range(self.lap_list.columnCount()):
            self.lap_list.resizeColumnToContents(column)

    def add_files(self):
        filenames, _ = QFileDialog.getOpenFileNames(
            self, tr("Add File..."), self.filepath,
            f"{tr('Laps')} (*.csv *.csv.gz *.ld);;Modern Tiny Pedals Lap (*.csv *.csv.gz);;MoTeC i2 (*.ld)")
        paths: list[str] = []
        imported: list[str] = []
        for filename in filenames:
            if filename.lower().endswith(".ld"):  # MoTeC log: complete laps converted to lap files
                laps = [os.path.normpath(path) for path in self.import_motec(filename)]
                imported.extend(laps)
                paths.extend(laps)
            else:
                paths.append(filename)
        self.add_external(paths, imported)

    def add_external(self, lap_paths: list[str], reference_from: list[str] | None = None):
        """Show laps from other folders, fastest of reference_from laps set as reference"""
        known = {entry.file.path for entry in self.all_entries()}
        added = set()
        for lap_path in lap_paths:
            path = os.path.normpath(lap_path)
            if path in known or path in added:
                continue
            name = os.path.basename(path)
            self.external.append(LapEntry(
                LapFile(name, path, is_valid_name(name), lap_time_of(name)), self.lap_info(path), external=True))
            added.add(path)
        if reference_from:  # compare own laps with fastest imported lap
            self.reference_key = min(
                reference_from, key=lambda path: lap_time_of(os.path.basename(path)) or float("inf"))
        if added or reference_from:
            self.fill_list(set(self.checked_paths()) | added)

    def open_library(self):
        from .lap_library import LapLibrary

        LapLibrary(self, self.filepath, self.add_from_library, self.library_changed).show()

    def add_from_library(self, paths: list[str]):
        """Laps picked in library shown & checked, fastest one as reference"""
        self.add_external(paths, paths)

    def library_changed(self, moved: dict[str, str]):
        """Imported laps renamed (new path) or deleted (empty path) in library"""
        if not any(entry.file.path in moved for entry in self.external):
            return
        checked = set()
        for path in self.checked_paths():
            path = moved.get(path, path)
            if path:
                checked.add(path)
        external = []
        for entry in self.external:
            path = moved.get(entry.file.path, entry.file.path)
            if path:
                external.append(entry._replace(file=entry.file._replace(path=path)))
            self._lap_cache.pop(entry.file.path, None)
        self.external = external
        if self.reference_key in moved:
            self.reference_key = moved[self.reference_key]
        self.fill_list(checked)

    def import_motec(self, filename: str) -> list[str]:
        """Import complete laps of MoTeC .ld file, returns lap file paths"""
        try:
            paths = import_ld_file(filename, os.path.join(self.filepath, IMPORT_FOLDER))
        except (OSError, ValueError) as error:
            logger.error("LAP VIEWER: unable to import %s: %s", filename, error)
            self.label_cursor.setText(trm(f"Unable to import MoTeC file: {error}"))
            return []
        if not paths:
            self.label_cursor.setText(trm(f"No complete lap in: {os.path.basename(filename)}"))
        return paths

    # Export
    def export_motec(self, path: str = ""):
        """Export lap (reference lap by default) to MoTeC .ld file"""
        path = path or self.reference_key
        lap = self.read_lap(path)
        if lap is None:
            return
        default = lap_stem(path) + ".ld"
        filename, _ = QFileDialog.getSaveFileName(self, tr("Export MoTeC..."), default, "MoTeC i2 (*.ld)")
        if not filename:
            return
        if self.export_file(path, lap, filename):
            self.label_cursor.setText(trm(f"Exported: {os.path.basename(filename)}"))

    def export_motec_many(self, whole_track: bool):
        """Export displayed laps, or every lap of track, to folder"""
        paths = [entry.file.path for entry in self.entries] if whole_track else self.checked_paths()
        if not paths:
            return
        folder = QFileDialog.getExistingDirectory(self, tr("Export MoTeC..."), self.filepath)
        if not folder:
            return
        count = 0
        for path in paths:
            lap = self._lap_cache.get(path)
            if lap is None:  # not kept in cache: exporting every lap of track would fill memory
                try:
                    lap = load_lap(path)
                except (OSError, ValueError) as error:
                    logger.error("LAP VIEWER: unable to load %s: %s", path, error)
                    continue
            target = os.path.join(folder, os.path.basename(lap_stem(path)) + ".ld")
            if self.export_file(path, lap, target):
                count += 1
        self.label_cursor.setText(trm(f"Exported <b>{count}</b> file(s) to: {folder}"))

    def export_file(self, path: str, lap: LapData, filename: str) -> bool:
        track = os.path.basename(os.path.dirname(path)).split(" - ")[0]
        try:
            export_lap(lap, filename, venue=track, timestamp=os.path.getmtime(path))
        except (OSError, ValueError) as error:
            logger.error("LAP VIEWER: unable to export %s: %s", filename, error)
            self.label_cursor.setText(trm(f"Unable to export lap: {error}"))
            return False
        return True

    def toggle_time_gain(self, enabled: bool):
        self.trajectory.set_show_gain(enabled)
        save_viewer_setting(self.filepath, map_time_gain=enabled)

    def update_cursor_info(self):
        plot = self.plot
        if not self.is_loading():
            self.label_cursor.setText(plot.cursor_values())
        view = plot.view_track_range()
        distance = plot.cursor_track_distance()
        self.trajectory.set_cursor(distance, view)
        self.gcircle.set_cursor(distance, view)

    # CSV export
    def export_csv(self):
        """Displayed charts of displayed laps to CSV, every meter"""
        if not self.plot.laps:
            self.label_cursor.setText(tr("Check laps to export first."))
            return
        default = os.path.join(self.filepath, f"{self.combo_track.currentText() or 'laps'}.csv")
        filename, _ = QFileDialog.getSaveFileName(self, tr("Export CSV..."), default, "CSV (*.csv)")
        if filename and self.write_csv(filename):
            self.label_cursor.setText(trm(f"Exported: {html.escape(os.path.basename(filename))}"))

    def write_csv(self, filename: str, decimal_point: str = "") -> bool:
        """Distance, then each displayed channel of each displayed lap, resampled every meter

        Number format follows system locale (decimal comma & semicolon separator in French), for Excel.
        """
        plot = self.plot
        decimal = decimal_point or QLocale.system().decimalPoint() or "."
        delimiter = ";" if decimal == "," else ","
        length = max((lap.data.distance[-1] for lap in plot.laps if len(lap.data)), default=0.0)
        grid = [float(meter) for meter in range(int(length) + 1)]
        header = [f"{tr('Distance')} (m)"]
        columns: list[list[str]] = []
        for lap in plot.laps:
            for channel in plot.channels:
                unit = plot.unit_of(channel)
                header.append(f"{lap.label} - {channel_title(channel)}" + (f" ({unit})" if unit else ""))
                xs, ys = plot.series(channel, lap, time_axis=False)
                columns.append([
                    format_csv_number(interpolate(xs, ys, distance), decimal)
                    if xs and xs[0] <= distance <= xs[-1] else ""
                    for distance in grid
                ])
        try:
            with open(filename, "w", newline="", encoding="utf-8-sig") as file:  # BOM: Excel reads UTF-8
                writer = csv.writer(file, delimiter=delimiter)
                writer.writerow(header)
                for index, distance in enumerate(grid):
                    writer.writerow([format_csv_number(distance, decimal), *(column[index] for column in columns)])
        except OSError as error:
            logger.error("LAP VIEWER: unable to export %s: %s", filename, error)
            self.label_cursor.setText(trm(f"Unable to export lap: {error}"))
            return False
        return True


def format_csv_number(value: float, decimal: str) -> str:
    """Number with up to 4 decimals, locale decimal separator"""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    return text.replace(".", decimal) if decimal != "." else text
