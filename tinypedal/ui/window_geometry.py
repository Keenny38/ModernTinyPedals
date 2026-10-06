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
Main window geometry: default size, window kept inside screens

Positions are frame positions (title bar included, as QWidget.pos & move), sizes are content
sizes (as QWidget.size & resize): frame rects below convert between both.
"""

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QGuiApplication, QScreen
from PySide6.QtWidgets import QWidget

from ._common import UIScaler

# Default window content size in base font size units (1008 x 672 pixels at 100% scale):
# most pages & tools fit without growing window
DEFAULT_SIZE = (84, 56)
# Part of screen available area default window size never goes over
DEFAULT_SCREEN_RATIO = 0.85
# Minimum page area in base font size units (648 x 444 pixels at 100% scale): smaller, pages
# overlap or get cut (checked on every page), never over this part of screen available area
PAGE_MINIMUM = (54, 37)
PAGE_MINIMUM_SCREEN_RATIO = 0.6


def screen_for(rect: QRect) -> QScreen | None:
    """Screen showing most of rect, else nearest one (rect on no screen: screen unplugged...)"""
    screens = QGuiApplication.screens()
    if not screens:
        return None

    def shown_area(screen: QScreen) -> int:
        shown = screen.geometry().intersected(rect)
        return 0 if shown.isEmpty() else shown.width() * shown.height()

    best = max(screens, key=shown_area)
    if shown_area(best) > 0:
        return best
    center = rect.center()

    def distance(screen: QScreen) -> int:
        geometry = screen.geometry()
        dx = max(geometry.left() - center.x(), 0, center.x() - geometry.right())
        dy = max(geometry.top() - center.y(), 0, center.y() - geometry.bottom())
        return dx * dx + dy * dy

    return min(screens, key=distance)


def fit_rect(rect: QRect, area: QRect) -> QRect:
    """Rect moved inside area, shrunk first if larger"""
    width = min(rect.width(), area.width())
    height = min(rect.height(), area.height())
    x = min(max(rect.x(), area.x()), area.x() + area.width() - width)
    y = min(max(rect.y(), area.y()), area.y() + area.height() - height)
    return QRect(x, y, width, height)


def frame_extra(window: QWidget) -> QSize:
    """Size of window frame (title bar & borders) around window content, known once window is created"""
    return window.frameGeometry().size() - window.size()


def available_area(window: QWidget) -> QRect:
    """Available area (taskbar excluded) of screen showing most of window"""
    screen = screen_for(window.frameGeometry()) or window.screen()
    return screen.availableGeometry()


def max_content_size(window: QWidget) -> QSize:
    """Largest window content size whose frame fits in screen showing most of window"""
    return available_area(window).size() - frame_extra(window)


def set_frame_rect(window: QWidget, frame: QRect):
    """Move & resize window so its frame (title bar included) covers frame rect"""
    content = frame.size() - frame_extra(window)
    if content != window.size():
        window.resize(content)
    if frame.topLeft() != window.pos():
        window.move(frame.topLeft())


def default_frame_rect(window: QWidget, screen: QScreen | None = None) -> QRect:
    """Window frame rect at first launch: comfortable size (most pages & tools fit without growing
    window, within screen), centered on screen (primary screen if not set)"""
    screen = screen or QGuiApplication.primaryScreen() or window.screen()
    area = screen.availableGeometry()
    extra = frame_extra(window)
    size = QSize(UIScaler.size(DEFAULT_SIZE[0]), UIScaler.size(DEFAULT_SIZE[1]))
    limit = QSize(round(area.width() * DEFAULT_SCREEN_RATIO), round(area.height() * DEFAULT_SCREEN_RATIO)) - extra
    size = size.boundedTo(limit).expandedTo(window.minimumSizeHint()).expandedTo(window.minimumSize())
    frame = QRect(QPoint(0, 0), size + extra)
    frame.moveCenter(area.center())
    return fit_rect(frame, area)


def page_minimum_size() -> QSize:
    """Minimum size of page area of main window, so pages never show broken (overlapped or cut)"""
    size = QSize(UIScaler.size(PAGE_MINIMUM[0]), UIScaler.size(PAGE_MINIMUM[1]))
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        area = screen.availableGeometry()
        limit = QSize(round(area.width() * PAGE_MINIMUM_SCREEN_RATIO), round(area.height() * PAGE_MINIMUM_SCREEN_RATIO))
        size = size.boundedTo(limit)
    return size


def keep_on_screen(window: QWidget) -> bool:
    """Window moved inside available area of screen showing most of it (nearest screen if on
    none), shrunk first if larger, so title bar & content are never off screen

    Returns:
        True if window was moved or resized.
    """
    if window.isMaximized() or window.isFullScreen():
        return False
    frame = window.frameGeometry()
    target = fit_rect(frame, available_area(window))
    if target == frame:
        return False
    set_frame_rect(window, target)
    return True
