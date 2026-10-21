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
Screen view of Overlays page: screens & running overlays at their place on the desktop (plain geometry)

Rects are desktop coordinates (QRect). The page draws them scaled into its area; overlays overlapping
another one are marked, moved overlays are kept inside the screens bounding box.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from PySide6.QtCore import QPoint, QRect

DEFAULT_SCREEN = QRect(0, 0, 1920, 1080)  # no screen known (tests, offscreen)


def rect_value(rect: QRect) -> dict[str, int]:
    """Rect for QML (x, y, w, h)"""
    return {"x": rect.x(), "y": rect.y(), "w": rect.width(), "h": rect.height()}


def bounds_of(rects: Iterable[QRect]) -> QRect:
    """Bounding rect of rects (DEFAULT_SCREEN if none valid)"""
    bounds = QRect()
    for rect in rects:
        if rect.isValid():
            bounds = bounds.united(rect)
    return bounds if bounds.isValid() else QRect(DEFAULT_SCREEN)


def overlapping(rects: Mapping[str, QRect]) -> set[str]:
    """Names of rects overlapping at least one other (touching edges is no overlap)"""
    items = [(name, rect) for name, rect in rects.items() if rect.isValid()]
    found: set[str] = set()
    for index, (name, rect) in enumerate(items):
        for other, other_rect in items[index + 1:]:
            if rect.intersects(other_rect):
                found.add(name)
                found.add(other)
    return found


def clamped_position(rect: QRect, x: int, y: int, bounds: QRect) -> QPoint:
    """Top left of rect moved to x, y, kept inside bounds (rect bigger than bounds: at bounds top left)"""
    max_x = max(bounds.left(), bounds.left() + bounds.width() - rect.width())
    max_y = max(bounds.top(), bounds.top() + bounds.height() - rect.height())
    return QPoint(min(max(x, bounds.left()), max_x), min(max(y, bounds.top()), max_y))
