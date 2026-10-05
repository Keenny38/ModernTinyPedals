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
Race aid widgets (delta graph, gap trend, pit lane helper, stint timer, spotter, notifications,
tyre temperature trend): parts shared by classic & modern design

    ClassicCells   classic layout drawing: text cells on background colors, widget font
    HiddenPreview  widget drawn only while it has something to show, or while overlay is
                   unlocked (to place it)
    line_polygons  sparkline & chart geometry from samples (nan = no sample, line broken)
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from math import isfinite
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPolygonF

from .. import overlay_signal
from ._common import FontMetrics

CENTER = Qt.AlignmentFlag.AlignCenter
LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def option_colors(wcfg: dict, *keys: str) -> dict[str, QColor]:
    """Color options as QColor, created once (classic layout)"""
    return {key: QColor(wcfg[key]) for key in keys}


def finite(value: Any) -> bool:
    """Number that can be drawn (not nan, inf or missing)"""
    return isinstance(value, (int, float)) and isfinite(value)


def sample_runs(values: Sequence[float]) -> list[tuple[int, int]]:
    """(first, last) index of each run of consecutive drawable samples"""
    runs = []
    start = -1
    for index, value in enumerate(values):
        if finite(value):
            if start < 0:
                start = index
        elif start >= 0:
            runs.append((start, index - 1))
            start = -1
    if start >= 0:
        runs.append((start, len(values) - 1))
    return runs


def scale_y(value: float, rect: QRectF, low: float, high: float) -> float:
    """Chart y of value (low at bottom, high at top), clamped to rect"""
    span = high - low
    if not span > 0:
        return rect.center().y()
    fraction = min(max((value - low) / span, 0.0), 1.0)
    return rect.bottom() - fraction * rect.height()


def line_polygons(values: Sequence[float], rect: QRectF, low: float, high: float,
                  slots: int = 0) -> tuple[QPolygonF, ...]:
    """Chart line of samples, one polygon per run (missing sample breaks line)

    Args:
        values: samples, oldest first.
        rect: chart area.
        low, high: value at bottom & top of chart.
        slots: samples across chart width, newest sample at right edge (0 = number of samples).
    """
    count = len(values)
    slots = max(slots, count, 2)
    step = rect.width() / (slots - 1)
    left = rect.left() + (slots - count) * step  # newest sample at right edge
    lines = []
    for first, last in sample_runs(values):
        if first == last:  # single sample: short flat line, still visible
            y = scale_y(values[first], rect, low, high)
            x = left + first * step
            lines.append(QPolygonF((QPointF(max(x - step * 0.3, rect.left()), y), QPointF(x, y))))
            continue
        lines.append(QPolygonF([
            QPointF(left + index * step, scale_y(values[index], rect, low, high))
            for index in range(first, last + 1)
        ]))
    return tuple(lines)


def value_range(values: Sequence[float], min_span: float, step: float = 0.0) -> tuple[float, float]:
    """Chart range around samples: at least min_span wide, rounded out to step (stable scale:
    range, and so chart geometry, changes only when samples cross a step)"""
    drawn = [value for value in values if finite(value)]
    if not drawn:
        return 0.0, max(min_span, 1e-6)
    low = min(drawn)
    high = max(drawn)
    if high - low < min_span:
        middle = (high + low) / 2
        low = middle - min_span / 2
        high = middle + min_span / 2
    if step > 0:
        low = (low // step) * step
        high = -((-high) // step) * step
    return low, high


class ClassicCells:
    """Classic layout drawing: text cells on background colors, widget font, for Overlay widgets"""

    wcfg: Any
    font_m: FontMetrics

    def setup_classic_font(self: Any) -> FontMetrics:
        """Widget font from font options, metrics kept for cell sizes"""
        font = self.config_font(self.wcfg["font_name"], self.wcfg["font_size"], self.wcfg["font_weight"])
        self.setFont(font)
        self.font_m = self.get_font_metrics(font)
        return self.font_m

    def cell_padding(self) -> float:
        """Horizontal text padding of cells (bar_padding option, in character widths)"""
        return self.font_m.width * max(float(self.wcfg.get("bar_padding", 0.2)), 0.0)

    def text_cell_width(self, characters: int) -> float:
        """Width of cell for number of characters, with padding"""
        return self.font_m.width * characters + self.cell_padding() * 2

    def draw_cell(self, painter: QPainter, rect: QRectF, text: str, color: QColor,
                  background: QColor | None = None, align: Qt.AlignmentFlag = CENTER):
        """Fill cell, then text inside (padded when aligned to a side)"""
        if background is not None:
            painter.fillRect(rect, background)
        if not text:
            return
        pad = 0.0 if align == CENTER else self.cell_padding()
        painter.setPen(color)
        painter.drawText(rect.adjusted(pad, self.font_m.voffset, -pad, 0), align, text)


class HiddenPreview:
    """Widget hidden while it has nothing to show (nothing drawn), always drawn while overlay is
    unlocked, so it can be placed. Mixin before widget class."""

    cfg: Any

    def start(self: Any):
        super().start()  # type: ignore[misc]
        overlay_signal.locked.connect(self.preview_toggled)

    def stop(self: Any):
        with suppress(RuntimeError, TypeError):  # not connected (widget never started)
            overlay_signal.locked.disconnect(self.preview_toggled)
        super().stop()  # type: ignore[misc]

    def preview_toggled(self: Any, _locked: bool):
        """Overlay locked or unlocked: drawn again (shown or hidden)"""
        self.update()

    def previewing(self) -> bool:
        """Overlay unlocked: widget always drawn"""
        return not self.cfg.overlay["fixed_position"]
