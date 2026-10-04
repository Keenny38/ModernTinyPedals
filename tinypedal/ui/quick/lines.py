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
GPU drawn lines for QML pages

Vertices are uploaded once in data coordinates (lap distance, channel value...) into the scene graph,
QML moves & scales them with a transform matrix: zoom & pan never run Python code nor re-upload data.

Scene graph notes (PySide6):
- QSGGeometry keeps a reference to its attribute set: attribute sets are module constants,
  a temporary one is freed by Python while the geometry still uses it (random crash).
- Only the returned root node is handed over to Qt, appended child nodes stay owned by Python:
  each item draws one geometry node, items are composed in QML instead.
"""

from __future__ import annotations

import ctypes
import math
import struct
from array import array
from collections.abc import Sequence
from typing import NamedTuple, cast

from PySide6.QtCore import Property, Signal
from PySide6.QtGui import QColor
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuick import (
    QQuickItem,
    QSGFlatColorMaterial,
    QSGGeometry,
    QSGGeometryNode,
    QSGNode,
    QSGVertexColorMaterial,
)

POINT2D = QSGGeometry.defaultAttributes_Point2D()
COLORED_POINT2D = QSGGeometry.defaultAttributes_ColoredPoint2D()
COLORED_VERTEX = struct.Struct("<ff4B")  # x, y, premultiplied rgba

LINE_STRIP = QSGGeometry.DrawingMode.DrawLineStrip
LINES = QSGGeometry.DrawingMode.DrawLines
TRIANGLE_STRIP = QSGGeometry.DrawingMode.DrawTriangleStrip
TRIANGLES = QSGGeometry.DrawingMode.DrawTriangles


class Vertices(NamedTuple):
    """Packed vertex data: 2 floats per vertex, or COLORED_VERTEX records if colored"""

    data: array | bytearray
    vertex_count: int
    mode: QSGGeometry.DrawingMode = LINE_STRIP
    colored: bool = False
    serial: int = 0  # set by VertexStore, changes with every stored data


class VertexStore:
    """Vertices by key, filled by page backends, read by GpuShape items when drawn"""

    _data: dict[str, Vertices] = {}
    _serial = 0

    @classmethod
    def set(cls, key: str, vertices: Vertices):
        cls._serial += 1
        cls._data[key] = vertices._replace(serial=cls._serial)

    @classmethod
    def get(cls, key: str) -> Vertices | None:
        return cls._data.get(key)

    @classmethod
    def has(cls, key: str) -> bool:
        return key in cls._data

    @classmethod
    def remove_prefix(cls, prefix: str):
        """Forget vertices of a page (keys start with page prefix)"""
        for key in [key for key in cls._data if key.startswith(prefix)]:
            del cls._data[key]


class GpuShape(QQuickItem):
    """One vertex buffer of VertexStore drawn in item coordinates (QML transform maps data to screen)

    QML: GpuShape { key: "..."; color: "red"; revision: backend.revision }
    revision change redraws after store update with same key.
    """

    keyChanged = Signal()
    colorChanged = Signal()
    revisionChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFlag(QQuickItem.Flag.ItemHasContents, True)
        self._key = ""
        self._color = QColor("white")
        self._revision = 0
        self._uploaded: tuple = ()  # vertices & color in scene graph
        self._colored = False  # node material

    def _get_key(self) -> str:
        return self._key

    def _set_key(self, key: str):
        if key != self._key:
            self._key = key
            self.keyChanged.emit()
            self.update()

    def _get_color(self) -> QColor:
        return self._color

    def _set_color(self, color: QColor):
        color = QColor(color)
        if color != self._color:
            self._color = color
            self.colorChanged.emit()
            self.update()

    def _get_revision(self) -> int:
        return self._revision

    def _set_revision(self, revision: int):
        if revision != self._revision:
            self._revision = revision
            self.revisionChanged.emit()
            self.update()

    key = Property(str, _get_key, _set_key, notify=keyChanged)
    color = Property(QColor, _get_color, _set_color, notify=colorChanged)
    revision = Property(int, _get_revision, _set_revision, notify=revisionChanged)

    def updatePaintNode(self, old: QSGNode | None, _data) -> QSGNode | None:  # type: ignore[override]
        vertices = VertexStore.get(self._key) if self._key else None
        if vertices is None or vertices.vertex_count < 2:
            self._uploaded = ()
            return None  # old node deleted by scene graph
        node = cast(QSGGeometryNode, old)
        if old is None or self._colored != vertices.colored:
            node = self.new_node(vertices)
            self._uploaded = ()
        state = (vertices.serial, self._color.rgba())
        if state == self._uploaded:
            return node
        geometry = node.geometry()
        if geometry.vertexCount() != vertices.vertex_count:
            geometry.allocate(vertices.vertex_count)
        geometry.setDrawingMode(vertices.mode)
        size = vertices.vertex_count * (COLORED_VERTEX.size if vertices.colored else 8)
        ctypes.memmove(int(geometry.vertexData()), _address(vertices.data), size)
        node.markDirty(QSGNode.DirtyStateBit.DirtyGeometry)
        if not vertices.colored:
            material = cast(QSGFlatColorMaterial, node.material())
            material.setColor(self._color)
            node.markDirty(QSGNode.DirtyStateBit.DirtyMaterial)
        self._uploaded = state
        return node

    def new_node(self, vertices: Vertices) -> QSGGeometryNode:
        node = QSGGeometryNode()
        geometry = QSGGeometry(COLORED_POINT2D if vertices.colored else POINT2D, vertices.vertex_count)
        geometry.setDrawingMode(vertices.mode)
        node.setGeometry(geometry)
        node.setFlag(QSGNode.Flag.OwnsGeometry, True)
        material = QSGVertexColorMaterial() if vertices.colored else QSGFlatColorMaterial()
        node.setMaterial(material)
        node.setFlag(QSGNode.Flag.OwnsMaterial, True)
        self._colored = vertices.colored
        return node


def _address(data: array | bytearray) -> int:
    """Memory address of packed data (kept alive by VertexStore while drawn)"""
    if isinstance(data, array):
        return data.buffer_info()[0]
    return ctypes.addressof((ctypes.c_char * len(data)).from_buffer(data))


def register_line_types():
    qmlRegisterType(GpuShape, "TinyPedal", 1, 0, "GpuShape")  # type: ignore[call-overload]  # stub wants bytes, str required


# Vertex builders
def line_strip(xs: Sequence[float], ys: Sequence[float]) -> Vertices:
    """Polyline through points"""
    count = min(len(xs), len(ys))
    data = array("f", bytes(count * 8))
    data[0::2] = array("f", xs[:count])
    data[1::2] = array("f", ys[:count])
    return Vertices(data, count, LINE_STRIP)


def step_strip(xs: Sequence[float], ys: Sequence[float]) -> Vertices:
    """Polyline holding each value until next point (gear)"""
    count = min(len(xs), len(ys))
    if count < 2:
        return line_strip(xs, ys)
    data = array("f")
    previous = ys[0]
    for x, y in zip(xs[:count], ys[:count]):
        data.extend((x, previous, x, y))
        previous = y
    return Vertices(data, count * 2, LINE_STRIP)


def segments(points: Sequence[tuple[float, float, float, float]]) -> Vertices:
    """Separate lines: (x0, y0, x1, y1) each"""
    data = array("f")
    for line in points:
        data.extend(line)
    return Vertices(data, len(points) * 2, LINES)


def _normals(xs: Sequence[float], ys: Sequence[float]) -> list[tuple[float, float]]:
    """Unit normal at each point (average of neighbor segments)"""
    count = len(xs)
    normals = []
    for index in range(count):
        before, after = max(index - 1, 0), min(index + 1, count - 1)
        dx, dy = xs[after] - xs[before], ys[after] - ys[before]
        length = math.hypot(dx, dy) or 1.0
        normals.append((-dy / length, dx / length))
    return normals


def band(xs: Sequence[float], ys: Sequence[float], half_width: float, closed: bool = False) -> Vertices:
    """Thick line as triangle strip, width in data units (uniform scale only: maps)"""
    count = min(len(xs), len(ys))
    if count < 2:
        return Vertices(array("f"), 0, TRIANGLE_STRIP)
    xs, ys = list(xs[:count]), list(ys[:count])
    if closed:
        xs.append(xs[0])
        ys.append(ys[0])
    data = array("f")
    for x, y, (nx, ny) in zip(xs, ys, _normals(xs, ys)):
        data.extend((x + nx * half_width, y + ny * half_width, x - nx * half_width, y - ny * half_width))
    return Vertices(data, len(xs) * 2, TRIANGLE_STRIP)


def colored_band(xs: Sequence[float], ys: Sequence[float], colors: Sequence[QColor], half_width: float,
                 ) -> Vertices:
    """Thick line with a color at each point (opaque colors)"""
    count = min(len(xs), len(ys), len(colors))
    if count < 2:
        return Vertices(bytearray(), 0, TRIANGLE_STRIP, True)
    data = bytearray(COLORED_VERTEX.size * count * 2)
    offset = 0
    for x, y, (nx, ny), color in zip(xs, ys, _normals(xs[:count], ys[:count]), colors):
        rgba = (color.red(), color.green(), color.blue(), 255)
        COLORED_VERTEX.pack_into(data, offset, x + nx * half_width, y + ny * half_width, *rgba)
        COLORED_VERTEX.pack_into(data, offset + COLORED_VERTEX.size, x - nx * half_width, y - ny * half_width, *rgba)
        offset += COLORED_VERTEX.size * 2
    return Vertices(data, count * 2, TRIANGLE_STRIP, True)


def merge_strips(strips: Sequence[Vertices]) -> Vertices:
    """Triangle strips (2 floats per vertex) drawn as one buffer of separate triangles"""
    data = array("f")
    for strip in strips:
        points = [(strip.data[index], strip.data[index + 1]) for index in range(0, strip.vertex_count * 2, 2)]
        for first, second, third in zip(points, points[1:], points[2:]):
            data.extend((*first, *second, *third))
    return Vertices(data, len(data) // 2, TRIANGLES)


def area(xs: Sequence[float], ys: Sequence[float], base: float) -> Vertices:
    """Filled area between line & base level (profile charts)"""
    count = min(len(xs), len(ys))
    data = array("f")
    for x, y in zip(xs[:count], ys[:count]):
        data.extend((x, base, x, y))
    return Vertices(data, count * 2 if count > 1 else 0, TRIANGLE_STRIP)


def circle(center_x: float, center_y: float, radius: float, segments_count: int = 96) -> tuple[list[float], list[float]]:
    """Closed circle points"""
    angles = [index / segments_count * math.tau for index in range(segments_count + 1)]
    return ([center_x + math.cos(angle) * radius for angle in angles],
            [center_y + math.sin(angle) * radius for angle in angles])


def dots(xs: Sequence[float], ys: Sequence[float], size: float, limit: int = 4000) -> Vertices:
    """Small squares (2 triangles each), at most limit points evenly picked"""
    count = min(len(xs), len(ys))
    step = max(count // limit, 1)
    half = size / 2
    data = array("f")
    for index in range(0, count, step):
        x, y = xs[index], ys[index]
        left, right, top, bottom = x - half, x + half, y - half, y + half
        data.extend((left, top, right, top, left, bottom, right, top, right, bottom, left, bottom))
    return Vertices(data, len(data) // 2, TRIANGLES)
