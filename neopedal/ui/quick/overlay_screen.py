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
another one are marked, moved overlays are kept inside the screens bounding box. A dragged overlay snaps to
the edges & centers of other overlays and screens (snap_position, formerly of the Layout Editor tool), a
screenshot shown under the overlays is placed on the screen it was taken on (screen_for_image).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from PySide6.QtCore import QPoint, QRect, QSize

DEFAULT_SCREEN = QRect(0, 0, 1920, 1080)  # no screen known (tests, offscreen)
SNAP_DISTANCE = 8  # desktop pixels


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


def snap_position(
    target: QRect, others: Iterable[QRect], screen: QRect | Sequence[QRect], distance: int = SNAP_DISTANCE
) -> QPoint:
    """Snap target top-left so its edges or center line up with other rects or screen edges & center

    Each axis snaps to the closest reference within distance, else keeps its position.
    Screen can be a single rect or the geometry of each screen (multi-monitor).
    """
    def best_offset(points: tuple[float, ...], refs: set[float]) -> float:
        best = 0.0
        best_gap = distance + 1.0
        for point in points:
            for ref in refs:
                gap = abs(ref - point)
                if gap < best_gap:
                    best_gap = gap
                    best = ref - point
        return best if best_gap <= distance else 0.0

    ref_x: set[float] = set()
    ref_y: set[float] = set()
    for rect in [screen] if isinstance(screen, QRect) else screen:
        ref_x.update((rect.left(), rect.left() + rect.width(), rect.center().x() + 0.5))
        ref_y.update((rect.top(), rect.top() + rect.height(), rect.center().y() + 0.5))
    for rect in others:
        ref_x.update((rect.left(), rect.left() + rect.width(), rect.left() + rect.width() / 2))
        ref_y.update((rect.top(), rect.top() + rect.height(), rect.top() + rect.height() / 2))
    left, top, width, height = target.left(), target.top(), target.width(), target.height()
    offset_x = best_offset((left, left + width, left + width / 2), ref_x)
    offset_y = best_offset((top, top + height, top + height / 2), ref_y)
    return QPoint(round(left + offset_x), round(top + offset_y))


def screen_for_image(size: QSize, screens: Sequence[tuple[QRect, float]], fallback: QRect) -> QRect:
    """Geometry of the screen a screenshot of this pixel size was taken on, else fallback

    Args:
        size: screenshot size in pixels.
        screens: (geometry, device pixel ratio) of each screen.
        fallback: geometry used when no screen has the screenshot size.
    """
    for geometry, ratio in screens:
        if size in (geometry.size(), (geometry.size().toSizeF() * ratio).toSize()):
            return QRect(geometry)
    return QRect(fallback)
