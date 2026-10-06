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
Overlay placement geometry: magnetic snapping, grid, axis lock, screen fit

Pure functions on QRect & QPoint (no widget), used to drag overlays (widget._common.MousePosition),
move them with arrow keys & context menu actions (widget._base).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from PySide6.QtCore import QPoint, QRect

VISIBLE_MARGIN = 24  # pixels of overlay that must stay on a screen to be reachable with the mouse


def _span_x(rect: QRect) -> tuple[int, int]:
    return rect.x(), rect.x() + rect.width()


def _span_y(rect: QRect) -> tuple[int, int]:
    return rect.y(), rect.y() + rect.height()


def axis_candidates(
    size: int, others: Iterable[tuple[int, int]], screens: Iterable[tuple[int, int]], gap: int = 0,
) -> list[float]:
    """Start positions (left or top) of a span of size that line up with references on one axis

    Args:
        size: span size (overlay width or height).
        others: (start, end) spans of other overlays: aligned starts, ends, centers, or placed
            next to them with gap.
        screens: (start, end) spans of screen: edges (gap as margin) & center.
        gap: space between overlays placed side by side.
    """
    candidates: list[float] = []
    for start, end in screens:
        candidates += (start + gap, end - size - gap, (start + end - size) / 2)
    for start, end in others:
        candidates += (
            start,  # starts aligned
            end - size,  # ends aligned
            end + gap,  # placed after
            start - size - gap,  # placed before
            (start + end - size) / 2,  # centers aligned
        )
    return candidates


def snap_axis(value: int, candidates: Iterable[float], distance: int) -> int | None:
    """Closest candidate within distance, None if none"""
    best = None
    best_gap = distance + 0.5
    for candidate in candidates:
        gap = abs(candidate - value)
        if gap < best_gap:
            best_gap = gap
            best = candidate
    return None if best is None else round(best)


def snap_position(
    target: QRect, others: Sequence[QRect], screens: Sequence[QRect], distance: int, gap: int = 0,
) -> tuple[QPoint, bool, bool]:
    """Magnetic snapping: top-left of target moved so its edges or center line up with others

    Each axis snaps to the closest reference within distance, else keeps its position.

    Returns:
        New top-left, whether x snapped, whether y snapped.
    """
    if distance <= 0:
        return target.topLeft(), False, False
    new_x = snap_axis(target.x(), axis_candidates(
        target.width(), map(_span_x, others), map(_span_x, screens), gap), distance)
    new_y = snap_axis(target.y(), axis_candidates(
        target.height(), map(_span_y, others), map(_span_y, screens), gap), distance)
    return (
        QPoint(target.x() if new_x is None else new_x, target.y() if new_y is None else new_y),
        new_x is not None,
        new_y is not None,
    )


def grid_value(value: int, grid: int) -> int:
    """Value rounded to grid"""
    if grid <= 1:
        return value
    return round(value / grid) * grid


def step_on_grid(value: int, direction: int, grid: int, count: int = 1) -> int:
    """Value moved by count steps in direction (-1 or 1): pixels, or to next grid lines"""
    if grid <= 1:
        return value + direction * count
    if direction > 0:
        return (value // grid + count) * grid
    return (-(-value // grid) - count) * grid  # from grid line at or above value


def constrain_axis(start: QPoint, pos: QPoint) -> QPoint:
    """Move restricted to the axis of largest movement since start (Shift held)"""
    if abs(pos.x() - start.x()) >= abs(pos.y() - start.y()):
        return QPoint(pos.x(), start.y())
    return QPoint(start.x(), pos.y())


def visible_area(rect: QRect, screens: Iterable[QRect]) -> int:
    """Largest part of rect shown on one screen, in pixels"""
    best = 0
    for screen in screens:
        shown = rect.intersected(screen)
        if not shown.isEmpty():
            best = max(best, shown.width() * shown.height())
    return best


def clamp_into(rect: QRect, screen: QRect) -> QPoint:
    """Top-left of rect moved inside screen (top-left corner kept on screen if larger)"""
    x = min(max(rect.x(), screen.x()), screen.x() + screen.width() - rect.width())
    y = min(max(rect.y(), screen.y()), screen.y() + screen.height() - rect.height())
    return QPoint(max(x, screen.x()), max(y, screen.y()))


def nearest_screen(rect: QRect, screens: Sequence[QRect]) -> QRect | None:
    """Screen closest to rect center (screen holding most of rect first)"""
    if not screens:
        return None
    center = rect.center()

    def distance(screen: QRect) -> tuple[int, int]:
        shown = rect.intersected(screen)
        dx = max(screen.left() - center.x(), 0, center.x() - screen.right())
        dy = max(screen.top() - center.y(), 0, center.y() - screen.bottom())
        return -(shown.width() * shown.height() if not shown.isEmpty() else 0), dx * dx + dy * dy

    return min(screens, key=distance)


def fit_on_screens(rect: QRect, screens: Sequence[QRect], margin: int = VISIBLE_MARGIN) -> QPoint | None:
    """Top-left bringing an overlay back on the nearest screen, None if enough of it is shown

    An overlay left on a monitor that is gone (or placed by a preset made on another computer)
    is moved inside the nearest screen, so it can be seen and grabbed again.
    """
    needed = min(margin, rect.width()) * min(margin, rect.height())
    if not screens or visible_area(rect, screens) >= max(needed, 1):
        return None
    screen = nearest_screen(rect, screens)
    if screen is None:
        return None
    return clamp_into(rect, screen)


def move_to_screen(rect: QRect, source: QRect, target: QRect) -> QPoint:
    """Top-left of rect at the same relative place on target screen

    Free space left & right (above & below) is shared the same way, so an overlay stuck
    to the right edge (or centered) stays stuck to the right edge (centered) on the other screen.
    """
    def place(start: int, size: int, src_start: int, src_size: int, dst_start: int, dst_size: int) -> int:
        room = src_size - size
        ratio = (start - src_start) / room if room > 0 else 0.0
        ratio = min(max(ratio, 0.0), 1.0)
        return dst_start + round(ratio * max(dst_size - size, 0))

    return QPoint(
        place(rect.x(), rect.width(), source.x(), source.width(), target.x(), target.width()),
        place(rect.y(), rect.height(), source.y(), source.height(), target.y(), target.height()),
    )


def centered(area: QRect, screen: QRect, horizontal: bool, pos: QPoint) -> QPoint:
    """Overlay position centering area (widget coordinates) on screen, other axis kept

    Args:
        area: part of overlay to center, in overlay coordinates.
        screen: screen geometry, in desktop coordinates (secondary screens are not at 0, 0).
        horizontal: center horizontally, else vertically.
        pos: current overlay position.
    """
    if horizontal:
        return QPoint(screen.x() + (screen.width() - area.width()) // 2 - area.x(), pos.y())
    return QPoint(pos.x(), screen.y() + (screen.height() - area.height()) // 2 - area.y())
