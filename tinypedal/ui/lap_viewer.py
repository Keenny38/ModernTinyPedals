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

import json
import logging
import os
from typing import NamedTuple

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr, trm
from ..setting import cfg
from ..userfile.motec_import import import_ld_file
from ..userfile.motec_ld import export_lap
from ..userfile.telemetry_lap import (
    IMPORT_FOLDER,
    LapData,
    LapFile,
    best_laps,
    compute_delta,
    decimate_minmax,
    interpolate,
    is_valid_name,
    lap_stem,
    lap_time_of,
    list_laps,
    list_tracks,
    load_lap,
    monotonic_distance,
    read_lap_info,
    sector_bounds,
    theoretical_best,
)
from ..userfile.track_map import load_track_map_file
from ._common import BaseDialog, UIScaler, singleton_dialog

logger = logging.getLogger(__name__)

LAP_COLORS = tuple(QColor(color) for color in (
    "#38BDF8", "#F97316", "#A3E635", "#E879F9", "#FACC15", "#F43F5E", "#2DD4BF", "#A78BFA",
))
COLOR_A = LAP_COLORS[0]  # reference lap
COLOR_B = LAP_COLORS[1]  # first compared lap
COLOR_GRID = QColor(128, 128, 128, 70)
VIEWER_SETTING = ".lap_viewer.json"  # visible channels, in telemetry folder
LAP_CACHE_SIZE = 12  # loaded laps kept in memory


class Channel(NamedTuple):
    """Plotted channel"""

    column: str  # CSV column, "delta" for computed time delta
    title: str
    unit: str
    weight: float  # relative panel height
    fixed_range: tuple[float, float] | None = None
    group: str = ""  # menu group (per wheel channels)


def wheel_channels(prefix: str, title: str, unit: str) -> tuple[Channel, ...]:
    return tuple(
        Channel(f"{prefix}_{wheel}", f"{title} {wheel.upper()}", unit, 0.8, group=title)
        for wheel in ("fl", "fr", "rl", "rr")
    )


CHANNELS = (
    Channel("delta", "Delta", "s", 1.2),
    Channel("speed_kph", "Speed", "km/h", 2.0),
    Channel("throttle", "Throttle", "", 1.0, (0.0, 1.0)),
    Channel("brake", "Brake", "", 1.0, (0.0, 1.0)),
    Channel("gear", "Gear", "", 0.8),
    Channel("steering", "Steering", "", 1.0, (-1.0, 1.0)),
    Channel("rpm", "RPM", "rpm", 1.0),
    Channel("clutch", "Clutch", "", 0.6, (0.0, 1.0)),
    Channel("fuel", "Fuel", "l", 0.8),
    Channel("accel_lat", "Lateral G", "G", 1.0),
    Channel("accel_long", "Longitudinal G", "G", 1.0),
    Channel("tc_active", "TC Active", "", 0.5, (0.0, 1.0)),
    Channel("abs_active", "ABS Active", "", 0.5, (0.0, 1.0)),
    Channel("battery", "Battery", "%", 0.8),
    Channel("pos_z", "Elevation", "m", 0.8),
    *wheel_channels("tyre_temp", "Tyre Temp", "°C"),
    *wheel_channels("tyre_pres", "Tyre Pressure", "kPa"),
    *wheel_channels("tyre_wear", "Tyre Wear", "%"),
    *wheel_channels("brake_temp", "Brake Temp", "°C"),
    *wheel_channels("wheel_speed", "Wheel Speed", "km/h"),
    *wheel_channels("ride_height", "Ride Height", "mm"),
    *wheel_channels("susp_defl", "Suspension", "mm"),
)
CHANNEL_MAP = {channel.column: channel for channel in CHANNELS}
MAP_MAX_ZOOM = 40.0  # track map & G circle zoom limit
TRACK_WIDTH = 12.0  # meters, circuit drawn under driving lines
ROAD_COLOR = QColor(128, 128, 128, 80)
DEFAULT_CHANNELS = ("delta", "speed_kph", "throttle", "brake", "gear", "steering")


class PlotLap(NamedTuple):
    """Displayed lap"""

    key: str  # file path
    label: str
    data: LapData
    color: QColor


def lap_label(filename: str) -> str:
    """Short lap name from file name: "lap012 1m30.123s" """
    parts = lap_stem(filename).split(" ")
    return " ".join(parts[2:]) if len(parts) > 2 else filename


def channel_title(channel: Channel) -> str:
    """Translated channel title, wheel suffix kept (Tyre Temp FL)"""
    if channel.group:
        return tr(channel.group) + channel.title[len(channel.group):]
    return tr(channel.title)


def format_value(value: float) -> str:
    """Cursor value, 2 decimals, none for whole numbers (gear)"""
    text = f"{value:.2f}"
    return text[:-3] if text.endswith(".00") else text


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


def save_visible_channels(folder: str, columns: list[str]):
    try:
        with open(os.path.join(folder, VIEWER_SETTING), "w", encoding="utf-8") as file:
            json.dump({"channels": columns}, file)
    except OSError as error:
        logger.warning("LAP VIEWER: unable to save channels: %s", error)


class TracePlot(QWidget):
    """Stacked channel plots along lap distance

    Charts are drawn once into a cached pixmap (redrawn when laps, channels, zoom or size change),
    cursor & zoom selection are drawn over it.
    Mouse: wheel = zoom, drag = move, shift + drag = zoom to selection, double-click = reset,
    drag channel name (left margin) = move channel up or down.
    Keyboard: +/- zoom, left/right move, Home or 0 reset.
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
        self.cursor_distance: float | None = None
        self.margin_left = UIScaler.size(5)
        self._series: dict[tuple[str, str], tuple[list[float], list[float]]] = {}
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
        self.invalidate()
        self.reset_view()

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
    def plot_rect(self) -> QRectF:
        return QRectF(self.margin_left, 4, max(self.width() - self.margin_left - 6, 1), max(self.height() - 8, 1))

    def x_of(self, distance: float, rect: QRectF) -> float:
        span = max(self.view_end - self.view_start, 1e-6)
        return rect.left() + (distance - self.view_start) / span * rect.width()

    def distance_of(self, x: float, rect: QRectF) -> float:
        span = self.view_end - self.view_start
        return self.view_start + (x - rect.left()) / max(rect.width(), 1) * span

    # Data
    def series(self, channel: Channel, lap: PlotLap) -> tuple[list[float], list[float]]:
        """Channel samples of lap by increasing distance, cached"""
        if channel.column == "delta":
            return self.deltas.get(lap.key, ([], []))
        key = (lap.key, channel.column)
        cached = self._series.get(key)
        if cached is None:
            if channel.column in lap.data.columns:
                cached = monotonic_distance(lap.data, channel.column)
            else:
                cached = ([], [])
            self._series[key] = cached
        return cached

    def value_range(self, channel: Channel) -> tuple[float, float]:
        if channel.fixed_range:
            return channel.fixed_range
        cached = self._ranges.get(channel.column)
        if cached is not None:
            return cached
        if channel.column == "delta":
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

    def render_charts(self, rect: QRectF, text_color: QColor, ratio: float) -> QPixmap:
        pixmap = QPixmap(round(self.width() * ratio), round(self.height() * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for channel, panel in self.panels(rect):
            self.paint_channel(painter, channel, panel, text_color)
        self.paint_legend(painter, rect, text_color)
        # Sector lines of reference lap
        if self.sector_lines:
            painter.setPen(QPen(COLOR_GRID.lighter(160), 1, Qt.PenStyle.DotLine))
            for index, distance in enumerate(self.sector_lines):
                if self.view_start <= distance <= self.view_end:
                    x = self.x_of(distance, rect)
                    painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
                    painter.drawText(QPointF(x + 3, rect.top() + painter.fontMetrics().ascent()), f"S{index + 2}")
        painter.end()
        return pixmap

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
        painter.drawText(
            QRectF(0, panel.top(), self.margin_left - 4, panel.height()),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
            f"{title}\n{channel.unit}" if channel.unit else title,
        )
        painter.save()
        painter.setClipRect(panel)
        buckets = max(int(panel.width()), 1)
        for lap in self.laps:
            xs, ys = self.series(channel, lap)
            if not xs:
                continue
            points = decimate_minmax(xs, ys, self.view_start, self.view_end, buckets)
            path = QPainterPath()
            for index, (distance, value) in enumerate(points):
                point = QPointF(self.x_of(distance, panel), y_of(value))
                if index:
                    path.lineTo(point)
                else:
                    path.moveTo(point)
            painter.setPen(QPen(lap.color, 1.5))
            painter.drawPath(path)
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
        """Values of each channel at cursor distance"""
        distance = self.cursor_distance
        if distance is None:
            return ""
        texts = [f"{distance:.0f} m"]
        for channel in self.channels:
            values = []
            for lap in self.laps:
                xs, ys = self.series(channel, lap)
                if xs and xs[0] <= distance <= xs[-1]:  # no value past end of lap
                    values.append(format_value(interpolate(xs, ys, distance)))
            if values:
                title = channel_title(channel)
                texts.append(f"{title}: {' / '.join(values)}")
        return "   ".join(texts)


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
        if event.button() == Qt.MouseButton.LeftButton and self.zoom > 1.0:
            self._pan_drag = (event.position(), QPointF(self.pan))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._pan_drag is not None:
            start, pan = self._pan_drag
            self.pan = pan + event.position() - start
            self.update()

    def mouseReleaseEvent(self, event):
        self._pan_drag = None
        self.unsetCursor()

    def mouseDoubleClickEvent(self, event):
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lines: list[tuple[list[float], list[float], list[float], QColor]] = []
        self._bounds = (0.0, 0.0, 1.0, 1.0)
        self._outline: list[tuple[float, float]] = []  # circuit from track map file
        self.road: list[tuple[float, float]] = []  # drawn circuit: track map, or reference lap line

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
        coords = self.road + [coord for line in self._lines for coord in zip(line[1], line[2])]
        if coords:
            self._bounds = (
                min(coord[0] for coord in coords), min(coord[1] for coord in coords),
                max(coord[0] for coord in coords), max(coord[1] for coord in coords),
            )

    def has_data(self) -> bool:
        return bool(self._lines)

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


class LapEntry(NamedTuple):
    """Lap list entry"""

    file: LapFile
    info: dict
    external: bool = False


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
        self._outline_cache: dict[str, list[tuple[float, float]]] = {}  # track name: circuit

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

        # Lap list
        self.lap_list = QTreeWidget(self)
        self.lap_list.setRootIsDecorated(False)
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
        layout_laps.addWidget(label_help)
        layout_laps.addWidget(self.lap_list, stretch=1)
        layout_laps.addWidget(self.label_best)
        layout_laps.addWidget(self.label_warning)

        # Charts
        self.label_cursor = QLabel(self)
        self.label_cursor.setMinimumHeight(UIScaler.size(1.6))
        self.label_cursor.setWordWrap(True)
        self.plot = TracePlot(self)
        self.plot.cursor_changed.connect(self.update_cursor_info)
        self.plot.channels_reordered.connect(self.reorder_channels)
        self.trajectory = TrajectoryMap(self)
        self.gcircle = GCircle(self)
        self.side_tabs = QTabWidget(self)
        self.side_tabs.addTab(self.trajectory, tr("Track Map"))
        self.side_tabs.addTab(self.gcircle, tr("G Circle"))

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
        button_channels = QPushButton(tr("Channels"))
        button_channels.setMenu(self.channel_menu())
        button_export = QPushButton(tr("Export MoTeC..."))
        menu_export = QMenu(button_export)
        menu_export.addAction(tr("Reference Lap...")).triggered.connect(self.export_motec)
        menu_export.addAction(tr("Displayed Laps...")).triggered.connect(lambda: self.export_motec_many(False))
        menu_export.addAction(tr("All Laps of Track...")).triggered.connect(lambda: self.export_motec_many(True))
        button_export.setMenu(menu_export)
        button_export.setToolTip(tr("Export laps to MoTeC i2 log files (.ld)"))
        button_close = QPushButton(tr("Close"))
        button_close.clicked.connect(self.close)
        layout_button = QHBoxLayout()
        label_help = QLabel(tr(
            "Wheel: zoom, drag: move, Shift+drag: zoom area, double-click: reset (charts & map). "
            "Drag a channel name to reorder."))
        label_help.setWordWrap(True)
        layout_button.addWidget(label_help, stretch=1)
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
        self._lap_cache.clear()
        self.load_track(self.combo_track.currentText())
        if not self.combo_track.count() and not self.external:
            self.label_cursor.setText(tr("No recorded lap. Enable the Recorder module, then drive a few laps."))

    def load_track(self, track: str):
        laps = list_laps(self.filepath, track) if track else []
        self.entries = [LapEntry(lap, read_lap_info(lap.path)) for lap in laps]
        best = best_laps(laps, 1)
        self.reference_key = best[0].path if best else (laps[0].path if laps else "")
        # Compare reference with newest other lap by default
        checked = {self.reference_key}
        newest = next((lap.path for lap in laps if lap.valid and lap.path != self.reference_key), "")
        if newest:
            checked.add(newest)
        self.fill_list(checked)

    def all_entries(self) -> list[LapEntry]:
        return self.entries + self.external

    def fill_list(self, checked: set[str]):
        self.lap_list.blockSignals(True)
        self.lap_list.clear()
        # Added files may come from other tracks: theoretical best & best sectors of current track only
        sectors = [self.entry_sectors(entry) for entry in self.entries if entry.file.valid]
        best_total, best_sectors = theoretical_best(sectors)
        for entry in self.all_entries():
            item = QTreeWidgetItem(self.lap_list)
            label = lap_label(entry.file.filename)
            if entry.external:
                label = f"{os.path.basename(os.path.dirname(entry.file.path))}: {label}"
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
            item.setText(self.COL_INFO, self.entry_text(entry))
        self.lap_list.blockSignals(False)
        if best_total > 0:
            self.label_best.setText(trm(f"Theoretical best: {format_laptime(best_total)}"))
        else:
            self.label_best.setText("")
        self.load_laps()

    @staticmethod
    def entry_sectors(entry: LapEntry) -> list[float]:
        sectors = entry.info.get("sectors")
        if isinstance(sectors, list) and len(sectors) == 3 and all(isinstance(v, (int, float)) for v in sectors):
            return [float(value) for value in sectors]
        return []

    @staticmethod
    def entry_text(entry: LapEntry) -> str:
        texts = []
        if not entry.file.valid:
            texts.append(tr("invalid"))
        kind = entry.info.get("kind", "")
        if kind == "out":
            texts.append(tr("out lap"))
        elif kind == "in":
            texts.append(tr("in lap"))
        if entry.info.get("session"):
            texts.append(tr(str(entry.info["session"])))
        if entry.info.get("vehicle"):
            texts.append(str(entry.info["vehicle"]))
        return ", ".join(texts)

    def checked_paths(self) -> list[str]:
        paths = []
        for index in range(self.lap_list.topLevelItemCount()):
            item = self.lap_list.topLevelItem(index)
            if item is not None and item.checkState(self.COL_LAP) == Qt.CheckState.Checked:
                paths.append(item.data(self.COL_LAP, Qt.ItemDataRole.UserRole))
        return paths

    def lap_checked(self, item: QTreeWidgetItem, column: int):
        if column == self.COL_LAP:
            self.load_laps()

    def set_reference_item(self, item: QTreeWidgetItem, *_):
        path = item.data(self.COL_LAP, Qt.ItemDataRole.UserRole)
        self.reference_key = path
        if item.checkState(self.COL_LAP) != Qt.CheckState.Checked:
            item.setCheckState(self.COL_LAP, Qt.CheckState.Checked)  # reloads laps
        else:
            self.load_laps()

    def lap_menu(self, position):
        item = self.lap_list.itemAt(position)
        if item is None:
            return
        menu = QMenu(self)
        menu.addAction(tr("Set as Reference")).triggered.connect(lambda: self.set_reference_item(item))
        menu.addAction(tr("Export MoTeC...")).triggered.connect(
            lambda: self.export_motec(item.data(self.COL_LAP, Qt.ItemDataRole.UserRole)))
        menu.exec(self.lap_list.viewport().mapToGlobal(position))

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
        self._lap_cache[path] = lap
        while len(self._lap_cache) > LAP_CACHE_SIZE:  # a lap takes several MB in memory
            self._lap_cache.pop(next(iter(self._lap_cache)))
        return lap

    def load_laps(self):
        paths = self.checked_paths()
        if paths and self.reference_key not in paths:
            self.reference_key = paths[0]
        ordered = sorted(paths, key=lambda path: path != self.reference_key)  # reference first
        laps: list[PlotLap] = []
        for path in ordered:
            data = self.read_lap(path)
            if data is not None:
                label = lap_label(os.path.basename(path))
                laps.append(PlotLap(path, label, data, LAP_COLORS[len(laps) % len(LAP_COLORS)]))
        self.plot.set_laps(laps, self.reference_key)
        self.trajectory.set_laps(laps, self.track_outline(laps))
        self.gcircle.set_laps(laps)
        self.update_list_colors(laps)
        vehicles = sorted({str(lap.data.meta.get("vehicle")) for lap in laps if lap.data.meta.get("vehicle")})
        if len(vehicles) > 1:
            self.label_warning.setText(trm(f"Laps from different vehicles: {', '.join(vehicles)}"))
        else:
            self.label_warning.setText("")

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
        for index in range(self.lap_list.topLevelItemCount()):
            item = self.lap_list.topLevelItem(index)
            if item is None:
                continue
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
        known = {entry.file.path for entry in self.all_entries()}
        added = set()
        imported: list[str] = []
        for filename in filenames:
            paths = [filename]
            if filename.lower().endswith(".ld"):  # MoTeC log: complete laps converted to lap files
                paths = self.import_motec(filename)
                imported.extend(os.path.normpath(path) for path in paths)
            for lap_path in paths:
                path = os.path.normpath(lap_path)
                if path in known:
                    continue
                name = os.path.basename(path)
                self.external.append(LapEntry(
                    LapFile(name, path, is_valid_name(name), lap_time_of(name)), read_lap_info(path), external=True))
                added.add(path)
        if imported:  # compare own laps with fastest imported lap
            self.reference_key = min(imported, key=lambda path: lap_time_of(os.path.basename(path)) or float("inf"))
        if added:
            self.fill_list(set(self.checked_paths()) | added)

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

    def update_cursor_info(self):
        plot = self.plot
        self.label_cursor.setText(plot.cursor_values())
        view = (plot.view_start, plot.view_end) if plot.zoomed() else (0.0, 0.0)
        self.trajectory.set_cursor(plot.cursor_distance, view)
        self.gcircle.set_cursor(plot.cursor_distance, view)
