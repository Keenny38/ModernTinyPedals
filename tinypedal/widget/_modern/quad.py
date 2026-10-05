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
Modern overlay design: four wheel panels (tyres, brakes, suspension...)

A widget shows one or more sections; each section is a 2x2 grid of wheel tiles (front left,
front right, rear left, rear right) under a small label. A tile shows one value, or several
parts side by side (tyre inner / center / outer). Tiles are filled with heatmap color (like
black box tyres) or stay neutral with colored text. An optional center column between left
and right tiles holds tyre compound badges.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, NamedTuple

from PySide6.QtCore import QRectF
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter

from ... import calculation as calc
from ...i18n import tr_overlay as tr
from ...userfile.heatmap import load_heatmap_color
from .base import CENTER, LEFT, RIGHT
from .draw import panel, readable_on, rounded

WHEELS = 4


class Section(NamedTuple):
    """Section definition"""

    key: str
    label: str  # English, translated when drawn ("" = no label)
    sample: str  # widest value text (one part)
    parts: int = 1  # values per tile
    role: str = "strong"  # value font role (single part)
    sub: bool = False  # small secondary value under main value
    min_width: float = 0.0  # minimum tile width, in unit (gauges)


class Tile(NamedTuple):
    """Wheel tile value of one update"""

    texts: tuple[str, ...]  # one text per part
    fills: tuple[QColor | None, ...] = ()  # fill per part (None = neutral)
    colors: tuple[QColor | None, ...] = ()  # text color per part (None = readable on fill / theme text)
    sub: str = ""  # secondary value (section with sub)
    sub_color: QColor | None = None
    level: float = -1.0  # 0-1 gauge filling neutral tile from left, -1 = none
    level_color: QColor | None = None
    mark: float = -1.0  # 0-1 mark on gauge (reference: input, third spring...), -1 = none


class SectionSlot(NamedTuple):
    """Section geometry"""

    section: Section
    label: QRectF
    tiles: tuple[QRectF, ...]  # fl, fr, rl, rr
    center: tuple[QRectF, QRectF]  # front & rear center column cells


@lru_cache(maxsize=64)
def heatmap(name: str, default: str) -> tuple:
    """Heatmap steps: ((value, QColor), ...)"""
    return tuple((value, QColor(color)) for value, (color, _) in load_heatmap_color(name, default))


def reload_heatmaps():
    """Heatmaps read again from preset by widgets created from now on (heatmap edited, preset
    switched: widgets are created again on reload)"""
    heatmap.cache_clear()


def heat_color(steps: tuple, value: float) -> QColor:
    """Heatmap color of value"""
    return calc.select_grade(steps, value)


_shades: dict[int, tuple[QColor, QColor]] = {}


def tile_shades(fill: QColor) -> tuple[QColor, QColor]:
    """Top & bottom color of heat colored tile gradient (few heatmap colors: cached)"""
    key = fill.rgba()
    shades = _shades.get(key)
    if shades is None:
        if len(_shades) > 512:
            _shades.clear()
        shades = _shades[key] = (fill.lighter(112), fill.darker(112))
    return shades


class QuadMixin:
    """Draw four wheel sections, for ModernOverlay widgets"""

    quad_slots: tuple[SectionSlot, ...]

    def build_quads(self: Any, sections: list[Section], horizontal: bool = False,
                    center_width: float = 0.0, show_labels: bool = True) -> tuple[float, float]:
        """Section geometry, returns widget size"""
        unit = self.unit
        pad = unit * 0.35
        gap = unit * 0.16
        section_gap = unit * 0.45
        label_h = unit * 0.95 if show_labels and any(s.label for s in sections) else 0.0
        slots = []
        left = top = pad
        right = bottom = pad
        center_gap = gap * 2 + center_width if center_width else gap
        widths = []
        for section in sections:
            part_w = self.text_width("value" if section.parts > 1 else section.role, section.sample)
            if section.parts > 1:
                tile_w = (part_w + unit * 0.35) * section.parts
            else:
                tile_w = max(part_w + unit * 0.9, unit * section.min_width)
            if label_h and section.label:  # section at least as wide as its label
                tile_w = max(tile_w, (self.text_width("label", tr(section.label)) + unit * 0.4 - center_gap) / 2)
            widths.append(tile_w)
        if not horizontal and widths:  # stacked sections aligned
            widths = [max(widths)] * len(widths)
        for section, tile_w in zip(sections, widths):
            tile_h = unit * (2.25 if section.sub else 1.55)
            width = tile_w * 2 + gap * 2 + center_width if center_width else tile_w * 2 + gap
            label = QRectF(left, top, width, label_h)
            row_top = top + label_h
            col_right = left + tile_w + (gap * 2 + center_width if center_width else gap)
            tiles = (
                QRectF(left, row_top, tile_w, tile_h),
                QRectF(col_right, row_top, tile_w, tile_h),
                QRectF(left, row_top + tile_h + gap, tile_w, tile_h),
                QRectF(col_right, row_top + tile_h + gap, tile_w, tile_h),
            )
            center_left = left + tile_w + gap
            center = (
                QRectF(center_left, row_top, center_width, tile_h),
                QRectF(center_left, row_top + tile_h + gap, center_width, tile_h),
            )
            slots.append(SectionSlot(section, label, tiles, center))
            section_h = label_h + tile_h * 2 + gap
            right = max(right, left + width)
            bottom = max(bottom, top + section_h)
            if horizontal:
                left += width + section_gap
            else:
                top += section_h + section_gap
        self.quad_slots = tuple(slots)
        return right + pad, bottom + pad

    def paint_quads_static(self: Any, painter: QPainter, show_panel: bool = True):
        """Panel, section labels"""
        theme = self.theme
        if show_panel:
            panel(painter, QRectF(self.rect()), theme, self.radius(0.5), self.depth_effects)
        for slot in self.quad_slots:
            if slot.label.height() and slot.section.label:
                self.draw_text(painter, slot.label, tr(slot.section.label), "label", theme.text_muted, CENTER)

    def draw_quads(self: Any, painter: QPainter, values: tuple[tuple[Tile, ...], ...]):
        """Tiles of every section"""
        for slot, tiles in zip(self.quad_slots, values):
            for wheel, (rect, tile) in enumerate(zip(slot.tiles, tiles)):
                self.draw_tile(painter, rect, tile, slot.section, wheel)

    def draw_tile(self: Any, painter: QPainter, rect: QRectF, tile: Tile, section: Section, wheel: int = 0):
        """One wheel tile"""
        theme = self.theme
        radius = self.radius(0.32)
        parts = max(len(tile.texts), 1)
        if parts == 1:
            fill = tile.fills[0] if tile.fills else None
            self.fill_tile(painter, rect, fill, radius)
            align = CENTER
            text_rect = rect
            if tile.level >= 0:  # gauge grows outward from car center, value on outer side
                width = rect.width() * min(tile.level, 1.0)
                left = rect.left() if wheel % 2 else rect.right() - width
                if width >= 1:
                    rounded(painter, QRectF(left, rect.top(), width, rect.height()), min(radius, width / 2),
                            tile.level_color or theme.tint(theme.accent, 110))
                if tile.mark >= 0:  # thin line across tile, same direction as gauge
                    mark_w = max(self.unit * 0.12, 2.0)
                    offset = (rect.width() - mark_w) * min(tile.mark, 1.0)
                    mark_left = rect.left() + offset if wheel % 2 else rect.right() - mark_w - offset
                    painter.fillRect(QRectF(mark_left, rect.top() + rect.height() * 0.12, mark_w,
                                            rect.height() * 0.76), theme.text_dim)
                inset = self.unit * 0.4
                text_rect = rect.adjusted(inset, 0, -inset, 0)
                align = RIGHT if wheel % 2 else LEFT
            color = tile.colors[0] if tile.colors and tile.colors[0] is not None else (
                readable_on(fill) if fill is not None else theme.text)
            if section.sub:
                text_rect = QRectF(rect.left(), rect.top(), rect.width(), rect.height() * 0.62)
                sub_rect = QRectF(rect.left(), rect.top() + rect.height() * 0.56, rect.width(), rect.height() * 0.4)
                if tile.sub and tile.sub_color is not None and fill is not None:  # colored text on dark chip
                    chip_w = min(self.text_width("small", tile.sub) + self.unit * 0.5, rect.width())
                    chip = QRectF(sub_rect.center().x() - chip_w / 2, sub_rect.top() + sub_rect.height() * 0.06,
                                  chip_w, sub_rect.height() * 0.88)
                    rounded(painter, chip, chip.height() / 2 * min(self.corner, 1.0), theme.tint(theme.surface, 210))
                sub_color = tile.sub_color or (readable_on(fill) if fill is not None else theme.text_dim)
                self.draw_text(painter, sub_rect, tile.sub, "small", sub_color, CENTER, elide=False)
            self.draw_text(painter, text_rect, tile.texts[0] if tile.texts else "", section.role, color, align, elide=False)
            return
        rounded(painter, rect, radius, theme.surface_alt)
        part_w = rect.width() / parts
        inset = self.unit * 0.08
        for index, text in enumerate(tile.texts):
            part = QRectF(rect.left() + part_w * index, rect.top(), part_w, rect.height())
            fill = tile.fills[index] if index < len(tile.fills) else None
            if fill is not None:
                self.fill_tile(painter, part.adjusted(inset, inset, -inset, -inset), fill, radius * 0.7)
            color = tile.colors[index] if index < len(tile.colors) and tile.colors[index] is not None else (
                readable_on(fill) if fill is not None else theme.text)
            self.draw_text(painter, part, text, "value", color, CENTER, elide=False)

    def fill_tile(self: Any, painter: QPainter, rect: QRectF, fill: QColor | None, radius: float):
        """Neutral tile, or heat colored tile with soft vertical gradient"""
        if fill is None:
            rounded(painter, rect, radius, self.theme.surface_alt)
            return
        if self.depth_effects:
            top, bottom = tile_shades(fill)
            gradient = QLinearGradient(0, rect.top(), 0, rect.bottom())
            gradient.setColorAt(0.0, top)
            gradient.setColorAt(1.0, bottom)
            rounded(painter, rect, radius, QBrush(gradient))
        else:
            rounded(painter, rect, radius, fill)

    def draw_center_texts(self: Any, painter: QPainter, slot: SectionSlot, texts: tuple,
                          colors: tuple = (None, None)):
        """Axle values in center column: (front, rear)"""
        for cell, text, color in zip(slot.center, texts, colors):
            self.draw_text(painter, cell, text, "small", color or self.theme.text_dim, CENTER, elide=False)

    def draw_center_badges(self: Any, painter: QPainter, slot: SectionSlot, badges: tuple):
        """Compound badges in center column: (front, rear) of axle badges, each ((symbol, QColor),)
        or left & right badges side by side when wheels of axle differ"""
        size = min(slot.center[0].width(), slot.center[0].height() * 0.7)
        for cell, axle in zip(slot.center, badges):
            if not axle:
                continue
            box = QRectF(cell.center().x() - size / 2, cell.center().y() - size / 2, size, size)
            if len(axle) == 1:
                symbol, color = axle[0]
                rounded(painter, box, self.radius(0.25), color)
                self.draw_text(painter, box, symbol, "label", readable_on(color), CENTER, elide=False)
                continue
            gap = size * 0.08
            half = (size - gap) / 2
            role = "tiny" if "tiny" in self.fonts else "label"
            for index, (symbol, color) in enumerate(axle[:2]):
                part = QRectF(box.left() + index * (half + gap), box.top(), half, size)
                rounded(painter, part, self.radius(0.2), color)
                self.draw_text(painter, part, symbol, role, readable_on(color), CENTER, elide=False)


def wheel_values(values, fmt) -> tuple:
    """Format 4 wheel values"""
    return tuple(fmt(value) for value in values)

