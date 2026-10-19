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

Hidden pages never recompute on app signals (setting applied, preset loaded...): the slot defers its work with
defer_while_hidden / when_shown, run once when the page is shown again (several signals meanwhile: once).
"""

from __future__ import annotations

import functools
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from ...context import AppContext, app_context
from .background import BackgroundJobs


class PageBackend(QObject):
    """Backend of a Qt Quick page

    Subclasses override page_shown & page_hidden, or set_active(active): hosts may call either form.
    page_visible: page shown, kept by the base class whatever form a subclass overrides (see __init_subclass__).
    when_shown / defer_while_hidden: work of a hidden page deferred until shown, then run once (after the page_shown
    or set_active(True) of the subclass); drop_when_shown forgets it (page shown made everything again anyway).
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
        self._page_visible = False
        # Work deferred while hidden, run once shown (in order): key, then callable & whether called with the page.
        # Methods of the page kept as functions, never as bound methods (no reference cycle page -> page)
        self._page_deferred: dict[object, tuple[Callable[..., object], bool]] = {}

    def __init_subclass__(cls, **kwargs):
        """page_shown, page_hidden & set_active of subclass wrapped: page visibility kept & deferred work run
        whichever form hosts call and subclasses override (an override never has to call the base class)"""
        super().__init_subclass__(**kwargs)
        for name in ("page_shown", "page_hidden", "set_active"):
            method = cls.__dict__.get(name)
            if callable(method) and not getattr(method, "_page_state", False):
                setattr(cls, name, _tracked(name, method))

    @property
    def page_released(self) -> bool:
        """release() called (page closed)"""
        return self._page_released

    @property
    def page_visible(self) -> bool:
        """Page shown (page_shown or set_active(True) last) and not released"""
        return self._page_visible and not self._page_released

    def defer_while_hidden(self, callback: Callable[[], object]) -> bool:
        """True if page hidden: callback run once page shown again (once, whatever the number of calls meanwhile),
        the caller returns. Guard at the top of a slot: `if self.defer_while_hidden(self.refresh): return`

        callback: method of this page, or a function holding no reference to the page (else a reference cycle).
        """
        if self.page_visible:
            return False
        if not self._page_released:
            func = getattr(callback, "__func__", None)
            if func is not None and getattr(callback, "__self__", None) is self:
                self._page_deferred[func] = (func, True)
            else:
                self._page_deferred[callback] = (callback, False)
        return True

    def when_shown(self, callback: Callable[[], object]) -> bool:
        """Run callback now if page shown, else once shown again (see defer_while_hidden), True if run now"""
        if self.defer_while_hidden(callback):
            return False
        callback()
        return True

    def drop_when_shown(self, callback: Callable[[], object] | None = None):
        """Forget deferred callback (every one if None): page shown made it again already"""
        if callback is None:
            self._page_deferred.clear()
        else:
            self._page_deferred.pop(getattr(callback, "__func__", callback), None)

    def run_deferred(self):
        """Page shown: work deferred while hidden run once, in order (rest kept if page hidden again meanwhile).
        Run after the page_shown / set_active of the subclass, which may run it first (state read before polling)"""
        while self._page_deferred and self.page_visible:
            func, with_page = self._page_deferred.pop(next(iter(self._page_deferred)))
            if with_page:
                func(self)
            else:
                func()

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
        self._page_visible = True
        if type(self).set_active is not PageBackend.set_active:
            self.set_active(True)
        self.run_deferred()

    def page_hidden(self):
        """Page hidden (another page shown, window hidden while racing)"""
        self._page_visible = False
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
        self._page_deferred.clear()
        if self.CANCEL_JOBS_ON_RELEASE:
            self.jobs.cancel_all()
        self.release_resources()
        for timer in self._page_timers:
            timer.stop()

    def release_resources(self):
        """Page closed (called once by release): subclass writes pending files, stops its timers & watchers"""


def _tracked(name: str, method: Callable[..., object]) -> Callable[..., object]:
    """page_shown, page_hidden or set_active of a subclass: page visibility set first, deferred work run after a
    page shown (see PageBackend.__init_subclass__)"""

    @functools.wraps(method)
    def tracked(self: PageBackend, *args, **kwargs):
        if name == "set_active":
            shown = bool(args[0] if args else kwargs.get("active"))
        else:
            shown = name == "page_shown"
        self._page_visible = shown
        result = method(self, *args, **kwargs)
        if shown:
            self.run_deferred()
        return result

    tracked._page_state = True  # type: ignore[attr-defined]  # wrapped once (subclass of a subclass)
    return tracked
