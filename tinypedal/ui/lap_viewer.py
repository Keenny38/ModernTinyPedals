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
Lap telemetry viewer: compare two recorded laps along distance
"""

from __future__ import annotations

import logging
import os
from typing import NamedTuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr, trm
from ..setting import cfg
from ..userfile.motec_ld import export_lap
from ..userfile.telemetry_lap import LapData, compute_delta, interpolate, list_laps, list_tracks, load_lap
from ._common import BaseDialog, CompactButton, UIScaler, singleton_dialog

logger = logging.getLogger(__name__)

COLOR_A = QColor("#38BDF8")  # reference lap
COLOR_B = QColor("#F97316")  # compared lap
COLOR_GRID = QColor(128, 128, 128, 70)


class Channel(NamedTuple):
    """Plotted channel"""

    column: str  # CSV column, "delta" for computed time delta
    title: str
    unit: str
    weight: float  # relative panel height
    fixed_range: tuple[float, float] | None = None


CHANNELS = (
    Channel("delta", "Delta", "s", 1.2),
    Channel("speed_kph", "Speed", "km/h", 2.0),
    Channel("throttle", "Throttle", "", 1.0, (0.0, 1.0)),
    Channel("brake", "Brake", "", 1.0, (0.0, 1.0)),
    Channel("gear", "Gear", "", 0.8),
    Channel("steering", "Steering", "", 1.0, (-1.0, 1.0)),
)


def lap_label(filename: str) -> str:
    """Short lap name from file name: "lap012 1m30.123s" """
    parts = filename.removesuffix(".csv").split(" ")
    return " ".join(parts[2:]) if len(parts) > 2 else filename


class TracePlot(QWidget):
    """Stacked channel plots along lap distance"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(UIScaler.size(40), UIScaler.size(26))
        self.lap_a: LapData | None = None
        self.lap_b: LapData | None = None
        self.delta: list[tuple[float, float]] = []
        self.view_start = 0.0
        self.view_end = 1.0
        self.cursor_distance: float | None = None
        self.margin_left = UIScaler.size(5)

    def set_laps(self, lap_a: LapData | None, lap_b: LapData | None):
        self.lap_a, self.lap_b = lap_a, lap_b
        self.delta = compute_delta(lap_a, lap_b) if lap_a and lap_b else []
        self.reset_view()

    def max_distance(self) -> float:
        return max((lap.distance[-1] for lap in (self.lap_a, self.lap_b) if lap), default=1.0) or 1.0

    def reset_view(self):
        self.view_start, self.view_end = 0.0, self.max_distance()
        self.update()

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
    def series(self, channel: Channel, lap: LapData | None, is_b: bool) -> tuple[list[float], list[float]]:
        if channel.column == "delta":
            if not is_b or not self.delta:
                return [], []
            return [point[0] for point in self.delta], [point[1] for point in self.delta]
        if lap is None or channel.column not in lap.columns:
            return [], []
        return lap.distance, lap.columns[channel.column]

    def value_range(self, channel: Channel) -> tuple[float, float]:
        if channel.fixed_range:
            return channel.fixed_range
        values = [
            value
            for lap, is_b in ((self.lap_a, False), (self.lap_b, True))
            for value in self.series(channel, lap, is_b)[1]
        ]
        if not values:
            return 0.0, 1.0
        low, high = min(values), max(values)
        if channel.column == "delta":
            limit = max(abs(low), abs(high), 0.1)
            return -limit, limit
        if high - low < 1e-6:
            high = low + 1
        padding = (high - low) * 0.05
        return low - padding, high + padding

    # Paint
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.plot_rect()
        text_color = self.palette().text().color()
        if not self.lap_a and not self.lap_b:
            painter.setPen(text_color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, tr("Select recorded laps to compare."))
            return
        total_weight = sum(channel.weight for channel in CHANNELS)
        top = rect.top()
        for channel in CHANNELS:
            height = rect.height() * channel.weight / total_weight
            panel = QRectF(rect.left(), top, rect.width(), height - 4)
            self.paint_channel(painter, channel, panel, text_color)
            top += height
        if self.cursor_distance is not None:
            x = self.x_of(self.cursor_distance, rect)
            painter.setPen(QPen(text_color, 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))

    def paint_channel(self, painter: QPainter, channel: Channel, panel: QRectF, text_color: QColor):
        low, high = self.value_range(channel)
        span = high - low or 1.0

        def y_of(value: float) -> float:
            return panel.bottom() - (value - low) / span * panel.height()

        painter.setPen(QPen(COLOR_GRID, 1))
        painter.drawRect(panel)
        if channel.column == "delta":
            painter.drawLine(QPointF(panel.left(), y_of(0)), QPointF(panel.right(), y_of(0)))
        painter.setPen(text_color)
        painter.drawText(
            QRectF(0, panel.top(), self.margin_left - 4, panel.height()),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"{tr(channel.title)}\n{channel.unit}" if channel.unit else tr(channel.title),
        )
        painter.save()
        painter.setClipRect(panel)
        for lap, is_b, color in ((self.lap_a, False, COLOR_A), (self.lap_b, True, COLOR_B)):
            xs, ys = self.series(channel, lap, is_b)
            if not xs:
                continue
            path = QPainterPath()
            step = max(len(xs) // max(int(panel.width() * 2), 1), 1)  # limit points to plot width
            first = True
            for index in range(0, len(xs), step):
                point = QPointF(self.x_of(xs[index], panel), y_of(ys[index]))
                if first:
                    path.moveTo(point)
                    first = False
                else:
                    path.lineTo(point)
            painter.setPen(QPen(color if channel.column != "delta" else text_color, 1.5))
            painter.drawPath(path)
        painter.restore()

    # Mouse
    def mouseMoveEvent(self, event):
        rect = self.plot_rect()
        if rect.contains(event.position()):
            self.cursor_distance = self.distance_of(event.position().x(), rect)
        else:
            self.cursor_distance = None
        self.update()
        update_cursor_info = getattr(self.parent(), "update_cursor_info", None)
        if update_cursor_info is not None:
            update_cursor_info(self.cursor_values())

    def wheelEvent(self, event):
        """Zoom around cursor"""
        rect = self.plot_rect()
        center = self.distance_of(event.position().x(), rect)
        factor = 0.8 if event.angleDelta().y() > 0 else 1.25
        start = center - (center - self.view_start) * factor
        end = center + (self.view_end - center) * factor
        max_distance = self.max_distance()
        if end - start >= max_distance:
            start, end = 0.0, max_distance
        self.view_start, self.view_end = max(start, 0.0), min(end, max_distance)
        self.update()

    def mouseDoubleClickEvent(self, event):
        self.reset_view()

    def cursor_values(self) -> str:
        """Values of each channel at cursor distance"""
        distance = self.cursor_distance
        if distance is None:
            return ""
        texts = [f"{distance:.0f} m"]
        for channel in CHANNELS:
            values = []
            for lap, is_b in ((self.lap_a, False), (self.lap_b, True)):
                xs, ys = self.series(channel, lap, is_b)
                if xs:
                    values.append(f"{interpolate(xs, ys, distance):.2f}")
            if values:
                texts.append(f"{tr(channel.title)}: {' / '.join(values)}")
        return "   ".join(texts)


@singleton_dialog("lap_viewer")
class LapViewer(BaseDialog):
    """Recorded lap telemetry viewer"""

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Lap Telemetry Viewer"))
        self.filepath = cfg.path.telemetry

        self.combo_track = QComboBox(self)
        self.combo_track.currentTextChanged.connect(self.load_track)
        self.combo_a = QComboBox(self)
        self.combo_b = QComboBox(self)
        self.combo_a.currentIndexChanged.connect(self.load_laps)
        self.combo_b.currentIndexChanged.connect(self.load_laps)
        button_refresh = CompactButton(tr("Refresh"))
        button_refresh.clicked.connect(self.refresh_tracks)

        self.label_a = QLabel(self)
        self.label_b = QLabel(self)
        self.label_cursor = QLabel(self)
        self.label_cursor.setMinimumHeight(UIScaler.size(1.6))
        self.plot = TracePlot(self)

        layout_select = QGridLayout()
        layout_select.addWidget(QLabel(tr("Track")), 0, 0)
        layout_select.addWidget(self.combo_track, 0, 1)
        layout_select.addWidget(button_refresh, 0, 2)
        layout_select.addWidget(self.legend(COLOR_A, tr("Reference")), 1, 0)
        layout_select.addWidget(self.combo_a, 1, 1)
        layout_select.addWidget(self.label_a, 1, 2)
        layout_select.addWidget(self.legend(COLOR_B, tr("Compare")), 2, 0)
        layout_select.addWidget(self.combo_b, 2, 1)
        layout_select.addWidget(self.label_b, 2, 2)
        layout_select.setColumnStretch(1, 1)

        button_export = CompactButton(tr("Export MoTeC..."))
        button_export.setToolTip(tr("Export reference lap to MoTeC i2 log file (.ld)"))
        button_export.clicked.connect(self.export_motec)
        button_close = CompactButton(tr("Close"))
        button_close.clicked.connect(self.close)
        layout_button = QHBoxLayout()
        layout_button.addWidget(QLabel(tr("Mouse wheel: zoom, double-click: reset.")))
        layout_button.addStretch(1)
        layout_button.addWidget(button_export)
        layout_button.addWidget(button_close)

        layout_main = QVBoxLayout()
        layout_main.addLayout(layout_select)
        layout_main.addWidget(self.label_cursor)
        layout_main.addWidget(self.plot, stretch=1)
        layout_main.addLayout(layout_button)
        layout_main.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        self.setLayout(layout_main)
        self.resize(UIScaler.size(60), UIScaler.size(40))
        self.refresh_tracks()

    @staticmethod
    def legend(color: QColor, text: str) -> QLabel:
        label = QLabel(f"<span style='color:{color.name()}'>■</span> {text}")
        return label

    def refresh_tracks(self):
        current = self.combo_track.currentText()
        self.combo_track.blockSignals(True)
        self.combo_track.clear()
        self.combo_track.addItems(list_tracks(self.filepath))
        self.combo_track.blockSignals(False)
        if current:
            self.combo_track.setCurrentText(current)
        self.load_track(self.combo_track.currentText())
        if not self.combo_track.count():
            self.label_cursor.setText(tr("No recorded lap. Enable the Recorder module, then drive a few laps."))

    def load_track(self, track: str):
        laps = list_laps(self.filepath, track) if track else []
        for combo in (self.combo_a, self.combo_b):
            combo.blockSignals(True)
            combo.clear()
        self.combo_b.addItem(tr("None"), "")
        for lap in laps:
            text = lap_label(lap.filename) + ("" if lap.valid else f" ({tr('invalid')})")
            self.combo_a.addItem(text, lap.path)
            self.combo_b.addItem(text, lap.path)
        self.combo_a.setCurrentIndex(0)
        # Compare with previous lap by default
        self.combo_b.setCurrentIndex(2 if len(laps) > 1 else 0)
        for combo in (self.combo_a, self.combo_b):
            combo.blockSignals(False)
        self.load_laps()

    def read_lap(self, path: str) -> LapData | None:
        if not path:
            return None
        try:
            return load_lap(path)
        except (OSError, ValueError) as error:
            logger.error("LAP VIEWER: unable to load %s: %s", path, error)
            self.label_cursor.setText(trm(f"Unable to load lap: {error}"))
            return None

    def load_laps(self):
        lap_a = self.read_lap(self.combo_a.currentData() or "")
        lap_b = self.read_lap(self.combo_b.currentData() or "")
        self.label_a.setText(self.lap_info(lap_a))
        self.label_b.setText(self.lap_info(lap_b))
        self.plot.set_laps(lap_a, lap_b)

    def export_motec(self):
        """Export reference lap to MoTeC .ld file"""
        path = self.combo_a.currentData() or ""
        lap = self.read_lap(path)
        if lap is None:
            return
        default = os.path.splitext(path)[0] + ".ld"
        filename, _ = QFileDialog.getSaveFileName(self, tr("Export MoTeC..."), default, "MoTeC i2 (*.ld)")
        if not filename:
            return
        track = self.combo_track.currentText().split(" - ")[0]
        try:
            export_lap(lap, filename, venue=track, timestamp=os.path.getmtime(path))
        except (OSError, ValueError) as error:
            logger.error("LAP VIEWER: unable to export %s: %s", filename, error)
            self.label_cursor.setText(trm(f"Unable to export lap: {error}"))
            return
        self.label_cursor.setText(trm(f"Exported: {os.path.basename(filename)}"))

    @staticmethod
    def lap_info(lap: LapData | None) -> str:
        if lap is None:
            return ""
        minutes, seconds = divmod(lap.lap_time, 60)
        top_speed = max(lap.columns.get("speed_kph", [0.0]))
        return f"{int(minutes)}:{seconds:06.3f}  ·  {top_speed:.0f} km/h"

    def update_cursor_info(self, text: str):
        self.label_cursor.setText(text)
