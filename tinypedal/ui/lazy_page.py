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
Main window pages built when first shown, released while window stays hidden

Pages never visited cost no memory (widgets, their style sheet rules, page code) nor startup time.
While main window stays hidden in tray or minimized (racing), built pages are released and the
hidden window's graphics resources freed: everything is built again when shown.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Slot
from PySide6.QtWidgets import QVBoxLayout, QWidget

RELEASE_DELAY_MS = 60_000  # window hidden or minimized this long: pages released
DESTROY_DELAY_MS = 1_000  # released pages deleted meanwhile, then hidden window's graphics freed


class LazyPage(QWidget):
    """Placeholder of main window page, page built by factory when first shown or selected

    Args:
        factory: creates page with given parent (page module imported there).

    Attributes:
        page: page widget, None until built (or after released).
    """

    def __init__(self, parent: QWidget, factory: Callable[[QWidget], QWidget]):
        super().__init__(parent)
        self._factory = factory
        self._building = False
        self.page: QWidget | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def ensure_page(self) -> QWidget | None:
        """Page, built if needed and refreshed once (as pages built at startup were)

        Returns None while page is being built (page showing itself re-enters showEvent).
        """
        if self.page is None and not self._building:
            self._building = True  # page creating its Qt Quick view when shown re-enters showEvent
            try:
                page = self._factory(self)
                self.page = page
                self._layout.addWidget(page)
                page.show()  # child added to a shown page is not shown by itself
                self.setFocusProxy(page)
            finally:
                self._building = False
            self.refresh()
        return self.page

    def release(self) -> bool:
        """Delete built page (built again when shown or selected), True if released"""
        page = self.page
        if page is None:
            return False
        self.page = None
        self.setFocusProxy(None)  # type: ignore[arg-type]  # PySide6 stubs refuse None
        self._layout.removeWidget(page)
        page.hide()
        page.deleteLater()
        return True

    def showEvent(self, event):
        self.ensure_page()
        super().showEvent(event)

    @Slot(bool)  # type: ignore[operator]
    def refresh(self, *_):
        """Setting, preset or language changed: page refreshed if built"""
        refresh = getattr(self.page, "refresh", None)
        if callable(refresh):
            refresh()


class PageRelease(QObject):
    """Frees memory while main window stays hidden (tray) or minimized

    Built pages are released. Hidden window (not minimized one, kept in taskbar) also frees its
    native window & graphics resources (surface, Qt Quick swap chain, tens of MB), created
    again when shown, unless a Qt Quick page is still open in it (open tool page).

    Args:
        parent: main view, its window watched.
        pages: pages released.
    """

    def __init__(self, parent: QWidget, pages: Iterable[LazyPage], delay_ms: int = RELEASE_DELAY_MS):
        super().__init__(parent)
        self._pages = tuple(pages)
        self._window = parent.window()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self.release)
        self._destroy_timer = QTimer(self)
        self._destroy_timer.setSingleShot(True)
        self._destroy_timer.setInterval(DESTROY_DELAY_MS)
        self._destroy_timer.timeout.connect(self.destroy_window)
        self._window.installEventFilter(self)
        if self.window_away():  # started hidden in tray or minimized
            self._timer.start()

    def window_away(self) -> bool:
        """Window hidden or minimized"""
        return not self._window.isVisible() or self._window.isMinimized()

    def eventFilter(self, watched, event):
        if watched is self._window and event.type() in (
                QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.WindowStateChange):
            if self.window_away():
                if not self._timer.isActive():
                    self._timer.start()
            else:
                self._timer.stop()
        return False

    def release(self):
        """Release pages, then window graphics once pages are deleted"""
        if not self.window_away():
            return
        for page in self._pages:
            page.release()
        self._destroy_timer.start()

    def destroy_window(self):
        """Native window of hidden window destroyed (created again by Qt when shown)"""
        window = self._window
        if window.isVisible() or not window.testAttribute(Qt.WidgetAttribute.WA_WState_Created):
            return
        if any(child.inherits("QQuickWidget") for child in window.findChildren(QWidget)):
            return  # Qt Quick page left open (tool page): keeps its graphics
        window.destroy()
