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
Backend of a Qt Quick page: one lifecycle for every page

Host (dialog or page widget) calls page_shown() / page_hidden() from its show & hide events (set_active(bool) is
the same, older name), and release() once the page closes (BaseDialog.free_page: QML view unloaded first).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from ...context import AppContext, app_context
from .background import BackgroundJobs


class PageBackend(QObject):
    """Backend of a Qt Quick page

    Subclasses override page_shown & page_hidden, or set_active(active): hosts may call either form.
    release(): page closed, once (later calls do nothing): jobs cancelled (results dropped), release_resources()
    of subclass called (files written, connections & watchers dropped), then timers made by page_timer stopped.
    jobs: background jobs of the page (work off the UI thread, results on it).
    ctx: app objects (game data API, settings, module & overlay controls), default the app ones.
    """

    # Jobs cancelled on release: a job still waiting for a worker thread is then never run. Pages whose jobs save
    # files (edits must still be written after close) keep them running: their done callbacks check release.
    CANCEL_JOBS_ON_RELEASE = True

    def __init__(self, parent: QObject | None = None, label: str = "Page", ctx: AppContext | None = None):
        super().__init__(parent)
        self.ctx = ctx if ctx is not None else app_context()  # app objects (neopedal.context): tests hand fakes
        self.jobs = BackgroundJobs(self, label)
        self._page_timers: list[QTimer] = []
        self._page_released = False

    @property
    def page_released(self) -> bool:
        """release() called (page closed)"""
        return self._page_released

    def page_timer(self, slot: Callable[[], object], interval: int = 0, single_shot: bool = False) -> QTimer:
        """Timer of the page (deleted with it), stopped once released"""
        timer = QTimer(self)
        timer.setSingleShot(single_shot)
        timer.setInterval(interval)
        timer.timeout.connect(slot)
        self._page_timers.append(timer)
        return timer

    def page_shown(self):
        """Page shown"""
        if type(self).set_active is not PageBackend.set_active:
            self.set_active(True)

    def page_hidden(self):
        """Page hidden (another page shown, window hidden while racing)"""
        if type(self).set_active is not PageBackend.set_active:
            self.set_active(False)

    def set_active(self, active: bool):
        """Page shown (True) or hidden (False)"""
        if active:
            self.page_shown()
        else:
            self.page_hidden()

    def release(self):
        """Page closed: resources freed once"""
        if self._page_released:
            return
        self._page_released = True
        if self.CANCEL_JOBS_ON_RELEASE:
            self.jobs.cancel_all()
        self.release_resources()
        for timer in self._page_timers:
            timer.stop()

    def release_resources(self):
        """Page closed (called once by release): subclass writes pending files, stops its timers & watchers"""
