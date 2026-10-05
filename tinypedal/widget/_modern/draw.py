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
Modern overlay design: shapes

Plain painter functions, sizes in pixels. Text is drawn by ModernOverlay (cached layouts).
"""

from __future__ import annotations

from collections import OrderedDict
from math import isfinite

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QTransform,
)

from .theme import Theme

_DEPTH_TOP = QColor(255, 255, 255, 14)
_MAX_SIZE = 100_000  # pixels, larger shape is invalid
_DEPTH_BOTTOM = QColor(0, 0, 0, 26)


def rounded(painter: QPainter, rect: QRectF, radius: float, color: QColor | QBrush) -> None:
    """Fill rounded rect (square if radius < 0.5)

    Plain color fills of a size seen before are drawn from a cached pixmap: list widgets repaint
    the same row, badge & pill shapes every update, antialiased path fills cost far more.
    """
    if not drawable(rect):
        return
    radius = min(radius, rect.width() / 2, rect.height() / 2)
    if radius < 0.5:
        painter.fillRect(rect, color)
        return
    if isinstance(color, QColor) and painter.transform().type() in _PLAIN_TRANSFORMS:
        pixmap = _cached_shape(rect.width(), rect.height(), radius, color, painter.device().devicePixelRatioF())
        if pixmap is not None:
            painter.drawPixmap(rect.topLeft(), pixmap)
            return
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.fillPath(path, color)


_PLAIN_TRANSFORMS = (QTransform.TransformationType.TxNone, QTransform.TransformationType.TxTranslate)
_SHAPE_CACHE_SIZE = 1024
_SHAPE_SEEN_SIZE = 4096
_SHAPE_MAX_PIXELS = 256 * 256
_shape_cache: OrderedDict[tuple, QPixmap] = OrderedDict()
_shape_seen: OrderedDict[tuple, None] = OrderedDict()


def _cached_shape(width: float, height: float, radius: float, color: QColor, ratio: float) -> QPixmap | None:
    """Rounded rect pixmap, cached once a shape is drawn a second time (animated bars change
    size every update, caching them would only churn the cache)"""
    if width * height * ratio * ratio > _SHAPE_MAX_PIXELS:
        return None
    key = (round(width * ratio), round(height * ratio), round(radius * ratio, 1), color.rgba(), ratio)
    pixmap = _shape_cache.get(key)
    if pixmap is not None:
        _shape_cache.move_to_end(key)
        return pixmap
    if key not in _shape_seen:
        _shape_seen[key] = None
        if len(_shape_seen) > _SHAPE_SEEN_SIZE:
            _shape_seen.popitem(last=False)
        return None
    pixmap = QPixmap(max(key[0], 1), max(key[1], 1))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    shape = QPainter(pixmap)
    shape.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, key[0] / ratio, key[1] / ratio), radius, radius)
    shape.fillPath(path, color)
    shape.end()
    _shape_cache[key] = pixmap
    if len(_shape_cache) > _SHAPE_CACHE_SIZE:
        _shape_cache.popitem(last=False)
    return pixmap


def drawable(rect: QRectF) -> bool:
    """Rect of finite position & positive finite size (nan or inf values from data never reach Qt)"""
    width = rect.width()
    height = rect.height()
    return 0 < width < _MAX_SIZE and 0 < height < _MAX_SIZE and isfinite(rect.left()) and isfinite(rect.top())


def panel(painter: QPainter, rect: QRectF, theme: Theme, radius: float, depth: bool = True) -> None:
    """Card background: surface fill, soft vertical shading, hairline border"""
    if not drawable(rect):
        return
    radius = min(radius, rect.width() / 2, rect.height() / 2)
    path = QPainterPath()
    if radius < 0.5:
        path.addRect(rect)
    else:
        path.addRoundedRect(rect, radius, radius)
    painter.fillPath(path, theme.surface)
    if depth:
        shade = QLinearGradient(0, rect.top(), 0, rect.bottom())
        shade.setColorAt(0.0, _DEPTH_TOP)
        shade.setColorAt(1.0, _DEPTH_BOTTOM)
        painter.fillPath(path, QBrush(shade))
    pen = QPen(theme.border, 1)
    pen.setCosmetic(True)
    painter.save()
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    half = 0.5
    inner = rect.adjusted(half, half, -half, -half)
    if radius < 0.5:
        painter.drawRect(inner)
    else:
        painter.drawRoundedRect(inner, max(radius - half, 0), max(radius - half, 0))
    painter.restore()


def accent_edge(painter: QPainter, rect: QRectF, color: QColor, width: float, radius: float) -> None:
    """Vertical colored bar on left side of rect (row marker, class color)"""
    edge = QRectF(rect.left(), rect.top(), width, rect.height())
    rounded(painter, edge, min(radius, width / 2), color)


def triangle(painter: QPainter, rect: QRectF, up: bool, color: QColor) -> None:
    """Filled triangle centered in rect, pointing up or down"""
    side = min(rect.width(), rect.height())
    half_w = side * 0.5
    height = side * 0.8
    cx = rect.center().x()
    cy = rect.center().y()
    top = cy - height / 2
    bottom = cy + height / 2
    if up:
        points = (QPointF(cx, top), QPointF(cx + half_w, bottom), QPointF(cx - half_w, bottom))
    else:
        points = (QPointF(cx - half_w, top), QPointF(cx + half_w, top), QPointF(cx, bottom))
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPolygon(QPolygonF(points))
    painter.restore()


def arrow(painter: QPainter, rect: QRectF, angle: float, color: QColor) -> None:
    """Arrow centered in rect, pointing up at angle 0, turned clockwise by angle (degrees)"""
    side = min(rect.width(), rect.height())
    if not side > 0 or not isfinite(angle):
        return
    half = side / 2
    head = side * 0.42
    shaft = side * 0.09
    points = (
        QPointF(0, -half), QPointF(head, -half + head), QPointF(shaft, -half + head),
        QPointF(shaft, half), QPointF(-shaft, half), QPointF(-shaft, -half + head), QPointF(-head, -half + head),
    )
    painter.save()
    painter.translate(rect.center())
    painter.rotate(angle)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPolygon(QPolygonF(points))
    painter.restore()


def bar(painter: QPainter, rect: QRectF, fraction: float, color: QColor, track: QColor | None,
        radius: float, vertical: bool = False) -> None:
    """Progress bar: track, then filled part (left to right, or bottom to top)"""
    if track is not None:
        rounded(painter, rect, radius, track)
    if not fraction > 0:  # also nan
        return
    fraction = min(fraction, 1.0)
    if vertical:
        fill_h = rect.height() * fraction
        fill = QRectF(rect.left(), rect.bottom() - fill_h, rect.width(), fill_h)
    else:
        fill = QRectF(rect.left(), rect.top(), rect.width() * fraction, rect.height())
    rounded(painter, fill, radius, color)


def center_bar(painter: QPainter, rect: QRectF, value: float, max_range: float,
               positive: QColor, negative: QColor, track: QColor | None, radius: float) -> None:
    """Bar growing from center: right for positive value, left for negative"""
    if track is not None:
        rounded(painter, rect, radius, track)
    if not (max_range > 0 and isfinite(value)) or not value:
        return
    fraction = min(abs(value) / max_range, 1.0)
    half = rect.width() / 2
    width = half * fraction
    if value > 0:
        fill = QRectF(rect.center().x(), rect.top(), width, rect.height())
        color = positive
    else:
        fill = QRectF(rect.center().x() - width, rect.top(), width, rect.height())
        color = negative
    rounded(painter, fill, radius, color)


def ring(painter: QPainter, rect: QRectF, fraction: float, color: QColor, track: QColor, width: float) -> None:
    """Circular gauge, clockwise from top"""
    inner = rect.adjusted(width / 2, width / 2, -width / 2, -width / 2)
    painter.save()
    pen = QPen(track, width)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(inner)
    fraction = min(fraction, 1.0) if fraction > 0 else 0.0  # also nan
    if fraction > 0:
        pen.setColor(color)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(inner, 90 * 16, -round(360 * 16 * fraction))
    painter.restore()


_DARK_TEXT = QColor(14, 17, 22)
_LIGHT_TEXT = QColor(244, 246, 249)
_readable: dict[int, QColor] = {}


def readable_on(color: QColor) -> QColor:
    """Dark or light text color readable on a colored background (shared color, never modified)

    Rows, badges & tiles ask for it on every paint: answer cached per background color.
    """
    key = color.rgba()
    text = _readable.get(key)
    if text is None:
        luminance = 0.2126 * color.redF() + 0.7152 * color.greenF() + 0.0722 * color.blueF()
        text = _DARK_TEXT if luminance > 0.55 else _LIGHT_TEXT
        if len(_readable) > 1024:
            _readable.clear()
        _readable[key] = text
    return text


def fraction(value: float) -> float:
    """Bar or gauge fill: 0 to 1, rounded to 0.1% (sub-pixel changes do not repaint widget)"""
    if not value > 0:  # also nan
        return 0.0
    return round(min(value, 1.0), 3)
