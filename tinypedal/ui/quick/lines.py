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
import sys
import weakref
from array import array
from bisect import bisect_left, bisect_right
from collections.abc import Collection, Sequence
from itertools import chain
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
    """Vertices by key, filled by page backends (page thread), read by GpuShape items when drawn

    Items showing a key are told when its vertices change: only they are drawn again.
    """

    _data: dict[str, Vertices] = {}
    _serial = 0
    _watchers: dict[str, weakref.WeakSet] = {}  # key: items showing it

    @classmethod
    def set(cls, key: str, vertices: Vertices):
        cls._serial += 1
        cls._data[key] = vertices._replace(serial=cls._serial)
        cls.notify(key)

    @classmethod
    def watch(cls, key: str, item: QQuickItem):
        if key:
            cls._watchers.setdefault(key, weakref.WeakSet()).add(item)

    @classmethod
    def prune_watchers(cls, prefix: str = ""):
        """Forget keys of prefix no longer shown by any item (items destroyed without unwatching their key)"""
        for key in [key for key, items in cls._watchers.items() if key.startswith(prefix) and not items]:
            del cls._watchers[key]

    @classmethod
    def unwatch(cls, key: str, item: QQuickItem):
        items = cls._watchers.get(key)
        if items is not None:
            items.discard(item)
            if not items:
                del cls._watchers[key]

    @classmethod
    def notify(cls, key: str):
        """Items showing key drawn again"""
        items = cls._watchers.get(key)
        if items is None:
            return
        for item in list(items):
            try:
                item.update()
            except RuntimeError:  # item deleted by Qt
                items.discard(item)
        if not items:  # every item showing key destroyed
            del cls._watchers[key]

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
            cls.notify(key)
        cls.prune_watchers(prefix)

    @classmethod
    def retain(cls, prefix: str, keep: Collection[str]):
        """Forget vertices of a page not in keep (laps no longer shown, former settings)"""
        for key in [key for key in cls._data if key.startswith(prefix) and key not in keep]:
            del cls._data[key]
            cls.notify(key)
        cls.prune_watchers(prefix)


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
        # Hidden item is not drawn: data stored meanwhile is uploaded once shown again (else stale shape)
        self.visibleChanged.connect(self.update)

    def _get_key(self) -> str:
        return self._key

    def _set_key(self, key: str):
        if key != self._key:
            VertexStore.unwatch(self._key, self)
            self._key = key
            VertexStore.watch(key, self)  # drawn again when its vertices change
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
            if old is None:
                return None
            # Node kept empty, not deleted: a node deleted then created again while item is hidden
            # can be drawn with the deleted node's former vertices (stale shape)
            empty = cast(QSGGeometryNode, old)
            if empty.geometry().vertexCount():
                empty.geometry().allocate(0)
                empty.markDirty(QSGNode.DirtyStateBit.DirtyGeometry)
            return empty
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
    # Slice assignment (C loops) instead of one extend per point: same bytes
    data = array("f", bytes(count * 16))
    x_values, y_values = array("f", xs[:count]), array("f", ys[:count])
    data[0::4] = x_values
    data[2::4] = x_values
    data[3::4] = y_values
    data[1] = y_values[0]
    data[5::4] = y_values[:-1]  # value held from previous point
    return Vertices(data, count * 2, LINE_STRIP)


def segments(points: Sequence[tuple[float, float, float, float]]) -> Vertices:
    """Separate lines: (x0, y0, x1, y1) each"""
    return Vertices(array("f", chain.from_iterable(points)), len(points) * 2, LINES)


def normals(xs: Sequence[float], ys: Sequence[float]) -> list[tuple[float, float]]:
    """Unit normal at each point of a line (same for every thickness: computed once per line by callers)"""
    return _normals(xs, ys)


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


def band(xs: Sequence[float], ys: Sequence[float], half_width: float, closed: bool = False,
         line_normals: Sequence[tuple[float, float]] | None = None) -> Vertices:
    """Thick line as triangle strip, width in data units (uniform scale only: maps)

    line_normals: normal at each point if already known (same line drawn at several thicknesses).
    """
    count = min(len(xs), len(ys))
    if count < 2:
        return Vertices(array("f"), 0, TRIANGLE_STRIP)
    xs, ys = list(xs[:count]), list(ys[:count])
    if closed:
        xs.append(xs[0])
        ys.append(ys[0])
    if line_normals is None or closed or len(line_normals) < count:
        line_normals = _normals(xs, ys)
    flat: list[float] = []
    for x, y, (nx, ny) in zip(xs, ys, line_normals):
        across_x, across_y = nx * half_width, ny * half_width
        flat += (x + across_x, y + across_y, x - across_x, y - across_y)
    return Vertices(array("f", flat), len(xs) * 2, TRIANGLE_STRIP)


def band_part(xs: Sequence[float], ys: Sequence[float], line_normals: Sequence[tuple[float, float]],
              indexes: Sequence[int], half_width: float) -> Vertices:
    """Thick line through some points of a line (simplified for scale), normals of whole line reused"""
    return band([xs[index] for index in indexes], [ys[index] for index in indexes], half_width,
                line_normals=[line_normals[index] for index in indexes])


def range_indexes(distances: Sequence[float], start: float, end: float) -> range:
    """Indexes of line points between two distances"""
    return range(bisect_left(distances, start), bisect_right(distances, end))


def colored_band(xs: Sequence[float], ys: Sequence[float], colors: Sequence[QColor], half_width: float,
                 alphas: Sequence[float] | None = None) -> Vertices:
    """Thick line with a color at each point, opaque or with alpha at each point (0 to 1, fading trail)"""
    count = min(len(xs), len(ys), len(colors))
    if count < 2:
        return Vertices(bytearray(), 0, TRIANGLE_STRIP, True)
    data = bytearray(COLORED_VERTEX.size * count * 2)
    alphas = alphas if alphas is not None else [1.0] * count
    corners: list[float] = []  # 2 vertices per point: x, y each
    rgbas: list[int] = []  # 2 vertices per point: rgba each
    for x, y, (nx, ny), color, alpha in zip(xs, ys, _normals(xs[:count], ys[:count]), colors, alphas):
        opacity = min(max(alpha, 0.0), 1.0)  # premultiplied color
        rgba = (round(color.red() * opacity), round(color.green() * opacity), round(color.blue() * opacity),
                round(255 * opacity))
        corners += (x + nx * half_width, y + ny * half_width, x - nx * half_width, y - ny * half_width)
        rgbas += rgba * 2
    positions = array("f", corners)
    filled = len(corners) // 4  # points written (others left zero: alphas shorter than points)
    if sys.byteorder != "little":  # COLORED_VERTEX floats are little endian
        positions.byteswap()
    # Interleave x, y floats (8 bytes) & rgba (4 bytes) of each vertex record, byte column by column
    size = COLORED_VERTEX.size
    end = filled * 2 * size
    raw = positions.tobytes()
    for column in range(8):
        data[column:end:size] = raw[column::8]
    for column in range(4):
        data[8 + column:end:size] = bytes(rgbas[column::4])
    return Vertices(data, count * 2, TRIANGLE_STRIP, True)


def merge_strips(strips: Sequence[Vertices]) -> Vertices:
    """Triangle strips (2 floats per vertex) drawn as one buffer of separate triangles"""
    data = array("f")
    for strip in strips:
        source = cast(array, strip.data)  # float strips only
        triangles = strip.vertex_count - 2  # triangle: 3 consecutive vertices, 6 floats
        if triangles <= 0:
            continue
        if len(source) < strip.vertex_count * 2:  # short data: slices cut at its end
            for index in range(0, strip.vertex_count * 2 - 4, 2):
                data.extend(source[index:index + 6])
            continue
        # Triangle k = floats 2k to 2k + 6 of strip: column j of every triangle in one slice assignment
        part = array("f", bytes(triangles * 24))
        for column in range(6):
            part[column::6] = source[column:column + triangles * 2:2]
        data.extend(part)
    return Vertices(data, len(data) // 2, TRIANGLES)


def range_band(xs: Sequence[float], lows: Sequence[float], highs: Sequence[float]) -> Vertices:
    """Filled area between low & high lines (min / max band of laps)"""
    count = min(len(xs), len(lows), len(highs))
    data = array("f", bytes(count * 16))
    x_values = array("f", xs[:count])
    data[0::4] = x_values
    data[1::4] = array("f", lows[:count])
    data[2::4] = x_values
    data[3::4] = array("f", highs[:count])
    return Vertices(data, count * 2 if count > 1 else 0, TRIANGLE_STRIP)


def area(xs: Sequence[float], ys: Sequence[float], base: float) -> Vertices:
    """Filled area between line & base level (profile charts)"""
    count = min(len(xs), len(ys))
    data = array("f", bytes(count * 16))
    x_values = array("f", xs[:count])
    data[0::4] = x_values
    data[1::4] = array("f", (base,)) * count
    data[2::4] = x_values
    data[3::4] = array("f", ys[:count])
    return Vertices(data, count * 2 if count > 1 else 0, TRIANGLE_STRIP)


def circle(center_x: float, center_y: float, radius: float, segments_count: int = 96) -> tuple[list[float], list[float]]:
    """Closed circle points"""
    angles = [index / segments_count * math.tau for index in range(segments_count + 1)]
    return ([center_x + math.cos(angle) * radius for angle in angles],
            [center_y + math.sin(angle) * radius for angle in angles])


MARKER_SHAPES = ("diamond", "dot", "triangle", "square", "ring", "hollow_triangle", "cross", "hollow_diamond")


def _triangle_corners(x: float, y: float, angle: float, half: float) -> list[tuple[float, float]]:
    """Triangle pointing toward angle (radians), fitting a circle of radius half"""
    return [(x + math.cos(angle + turn) * half, y + math.sin(angle + turn) * half)
            for turn in (0.0, math.tau / 3, -math.tau / 3)]


def _outline(outer: list[tuple[float, float]], inner: list[tuple[float, float]], data: array):
    """Triangles between outer & inner polygons (same corner count): hollow shape"""
    count = len(outer)
    for index in range(count):
        following = (index + 1) % count
        data.extend((*outer[index], *outer[following], *inner[index]))
        data.extend((*inner[index], *outer[following], *inner[following]))


def markers(points: Sequence[tuple[float, float, float]], shape: str, size: float) -> Vertices:
    """Map markers as triangles, one per point (x, y, heading radians), size across in data units

    Sized for current map scale (rebuilt when zoom settles, like thick lines): hundreds of markers
    drawn by one item instead of one QML item each.
    """
    half = size / 2
    data = array("f")
    circle_steps = [index / 12 * math.tau for index in range(12)]
    for x, y, angle in points:
        if shape == "diamond":
            corners = [(x + half, y), (x, y + half), (x - half, y), (x, y - half)]
            data.extend((*corners[0], *corners[1], *corners[2], *corners[0], *corners[2], *corners[3]))
        elif shape == "square":
            side = half * 0.8
            corners = [(x - side, y - side), (x + side, y - side), (x + side, y + side), (x - side, y + side)]
            data.extend((*corners[0], *corners[1], *corners[2], *corners[0], *corners[2], *corners[3]))
        elif shape == "triangle":
            first, second, third = _triangle_corners(x, y, angle, half)
            data.extend((*first, *second, *third))
        elif shape == "cross":  # two bars, turned 45 degrees
            bar = half * 0.28
            for turn in (math.pi / 4, -math.pi / 4):
                cos, sin = math.cos(turn), math.sin(turn)
                corners = [(x + cos * along - sin * across, y + sin * along + cos * across)
                           for along, across in ((-half, -bar), (half, -bar), (half, bar), (-half, bar))]
                data.extend((*corners[0], *corners[1], *corners[2], *corners[0], *corners[2], *corners[3]))
        elif shape == "hollow_diamond":
            outer = [(x + half, y), (x, y + half), (x - half, y), (x, y - half)]
            inner = [(x + half * 0.5, y), (x, y + half * 0.5), (x - half * 0.5, y), (x, y - half * 0.5)]
            _outline(outer, inner, data)
        elif shape == "hollow_triangle":
            _outline(_triangle_corners(x, y, angle, half), _triangle_corners(x, y, angle, half * 0.45), data)
        elif shape == "ring":
            outer = [(x + math.cos(step) * half, y + math.sin(step) * half) for step in circle_steps]
            inner = [(x + math.cos(step) * half * 0.6, y + math.sin(step) * half * 0.6) for step in circle_steps]
            _outline(outer, inner, data)
        else:  # dot
            rim = [(x + math.cos(step) * half, y + math.sin(step) * half) for step in circle_steps]
            for index in range(len(rim)):
                data.extend((x, y, *rim[index], *rim[(index + 1) % len(rim)]))
    return Vertices(data, len(data) // 2, TRIANGLES)


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
