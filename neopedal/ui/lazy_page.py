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
Main window pages built when first shown, released while window stays hidden

Pages never visited cost no memory (widgets, their style sheet rules, page code) nor startup time.
While main window stays hidden in tray or minimized (racing), built pages are released and the
hidden window's graphics resources freed: everything is built again when shown.
Qt Quick pages left hidden a while, window shown or not, are released too (see IdlePageRelease).
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterable

import shiboken6
from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Slot
from PySide6.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget

from ..jobs import weak_callback

RELEASE_DELAY_MS = 60_000  # window hidden or minimized this long: pages released
DESTROY_DELAY_MS = 1_000  # released pages deleted meanwhile, then hidden window's graphics freed
IDLE_RELEASE_MS = 10 * 60_000  # page left hidden this long (window shown or not): its Qt Quick page released
IDLE_CHECK_MS = 60_000  # hidden pages checked this often while any is hidden


def request_idle_collect():
    """Garbage of released pages collected at next idle moment (frozen with the app, see loader), app
    started only (loader never imported here)"""
    loader = sys.modules.get(f"{__package__.rpartition('.')[0]}.loader")
    request = getattr(loader, "request_idle_collect", None)
    if callable(request):
        request()


def release_quick_views(widget: QWidget):
    """Unload Qt Quick views of widget & its children before they are deleted

    Qt Quick views go first: backend (created before view) is deleted first by Qt,
    QML bindings still active would then read a null backend.
    """
    from PySide6.QtCore import QUrl
    from PySide6.QtQuickWidgets import QQuickWidget

    for view in widget.findChildren(QQuickWidget):
        view.setSource(QUrl())


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
        release_quick_views(page)
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
        release_others: called before pages are released (tool pages closed, reopened by shown).
        shown: called once window is shown again (after show event).
    """

    def __init__(
        self, parent: QWidget, pages: Iterable[LazyPage], delay_ms: int = RELEASE_DELAY_MS,
        release_others: Callable[[], object] | None = None, shown: Callable[[], object] | None = None,
    ):
        super().__init__(parent)
        self._pages = tuple(pages)
        # Bound methods held weakly (no reference cycle with the view owning this object)
        self._release_others = weak_callback(release_others)
        self._shown = weak_callback(shown)
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
                if self._shown() is not None:  # shown or restored from minimized
                    QTimer.singleShot(0, self, self.window_shown)  # once show is done
        return False

    def window_shown(self):
        """Window shown again: shown callback (pages released or deferred reopened)"""
        callback = self._shown()
        if callback is not None and not self.window_away():
            callback()

    @staticmethod
    def dialog_running() -> bool:
        """Modal dialog or popup running (its nested event loop runs this timer): page or window it was
        opened from (its QML handler still on the call stack) never deleted under it"""
        return QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None

    def release(self):
        """Release pages, then window graphics once pages are deleted"""
        if not self.window_away():
            return
        if self.dialog_running():
            self._timer.start()  # tried again later
            return
        release_others = self._release_others()
        if release_others is not None:
            release_others()
        released = [page.release() for page in self._pages]
        if any(released):
            request_idle_collect()
        self._destroy_timer.start()

    def destroy_window(self):
        """Native window of hidden window destroyed (created again by Qt when shown)"""
        window = self._window
        if window.isVisible() or not window.testAttribute(Qt.WidgetAttribute.WA_WState_Created):
            return
        if self.dialog_running():
            self._destroy_timer.start()
            return
        if any(child.inherits("QQuickWidget") for child in window.findChildren(QWidget)):
            return  # Qt Quick page left open (tool page): keeps its graphics
        window.destroy()


class IdlePageRelease(QObject):
    """Frees Qt Quick pages left hidden a while, window shown or not (pages visited once, tools of navigation
    rail kept open): least recently shown first, built again when shown

    Each Qt Quick page holds its engine, scene graph & render target (tens of MB) while hidden. Page
    stack is watched: page left is timed, page shown is not. Which page is released, and how, is
    decided by release callback (live pages, unsaved changes... are kept).

    Args:
        stack: page stack watched.
        release: called with page hidden for delay_ms: True if released, False if kept for now (tried
            again later), None if kept until shown again.
        delay_ms: hidden this long: page released.
        check_ms: hidden pages checked this often (while any).
        clock: seconds clock (tests).
    """

    def __init__(
        self, stack: QStackedWidget, release: Callable[[QWidget], bool | None], delay_ms: int = IDLE_RELEASE_MS,
        check_ms: int = IDLE_CHECK_MS, clock: Callable[[], float] = time.monotonic,
    ):
        super().__init__(stack)
        self._stack = stack
        self._release = weak_callback(release)  # bound method of view owning this object: no reference cycle
        self._delay = delay_ms / 1000
        self._clock = clock
        self._hidden_since: dict[QWidget, float] = {}  # page left: time left
        self._current: QWidget | None = stack.currentWidget()
        self._timer = QTimer(self)
        self._timer.setInterval(check_ms)
        self._timer.timeout.connect(self.check)
        stack.currentChanged.connect(self.page_changed)

    def page_changed(self, index: int):
        """Page left timed, page shown no longer"""
        shown = self._stack.widget(index)
        left = self._current
        if left is not None and left is not shown and shiboken6.isValid(left):
            self._hidden_since[left] = self._clock()
        if shown is not None:
            self._hidden_since.pop(shown, None)
        self._current = shown
        if self._hidden_since and not self._timer.isActive():
            self._timer.start()

    def hidden_pages(self) -> list[QWidget]:
        """Pages hidden (still in stack), least recently shown first"""
        stack = self._stack
        for page in list(self._hidden_since):
            if not shiboken6.isValid(page) or stack.indexOf(page) < 0:
                del self._hidden_since[page]  # closed page
        return sorted(self._hidden_since, key=self._hidden_since.__getitem__)

    def check(self):
        """Pages hidden for delay released, garbage collected once idle"""
        pages = self.hidden_pages()
        if not pages:
            self._timer.stop()
            return
        release = self._release()
        if release is None or PageRelease.dialog_running():  # page opening a message box never deleted under it
            return
        now = self._clock()
        released = False
        for page in pages:
            if now - self._hidden_since[page] < self._delay or page is self._stack.currentWidget():
                continue
            result = release(page)
            if result is not False:  # released, or kept until shown again
                self._hidden_since.pop(page, None)
            released = released or bool(result)
        if released:
            request_idle_collect()
        if not self._hidden_since:
            self._timer.stop()
