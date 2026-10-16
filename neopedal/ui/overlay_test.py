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
Overlays on screen shown for a few seconds in a race situation of the simulated session (flags, pit, damage,
rain), to set their colors & thresholds without driving (Overlay Options, "Test on Screen")

While testing, widget modules read the simulated session (demo_data.demo_globals) and every running overlay is
updated from it; module threads keep writing game data, read again by overlays once the test ends.
"""

from __future__ import annotations

import logging
from contextlib import ExitStack

from PySide6.QtCore import QObject, QTimer, Signal

logger = logging.getLogger(__name__)

TEST_SECONDS = 10
UPDATE_MS = 100  # overlays updated from simulated session (their own timer may be stopped: no game)


class OverlayTest(QObject):
    """Running overlays updated from a simulated session for TEST_SECONDS"""

    changed = Signal()  # test started or ended

    def __init__(self):
        super().__init__()
        self._stack: ExitStack | None = None
        self._ticks = QTimer(self)
        self._ticks.setInterval(UPDATE_MS)
        self._ticks.timeout.connect(self._update)
        self._end = QTimer(self)
        self._end.setSingleShot(True)
        self._end.timeout.connect(self.stop)

    @property
    def running(self) -> bool:
        return self._stack is not None

    def start(self, scenario: str = "", seconds: float = TEST_SECONDS) -> int:
        """Test started (again), returns number of overlays seen on screen"""
        from ..demo_data import DemoSession, demo_globals
        from ..setting import cfg

        self.stop(refresh=False)
        session = DemoSession(cfg.user.setting["standings"], scenario)
        stack = ExitStack()
        stack.enter_context(demo_globals(session))
        self._stack = stack
        self._update()
        self._ticks.start()
        self._end.start(round(seconds * 1000))
        self.changed.emit()
        return sum(bool(widget.isVisible()) for widget in overlays())

    def stop(self, refresh: bool = True):
        """Game data read again by overlays (updated once now: no wait for a game update)"""
        if self._stack is None:
            return
        self._ticks.stop()
        self._end.stop()
        stack, self._stack = self._stack, None
        stack.close()
        if refresh:
            self._update()
        self.changed.emit()

    @staticmethod
    def _update():
        from ..demo_data import update_once

        for widget in overlays():
            try:
                update_once(widget)
            except Exception:  # one overlay never stops the test of others
                logger.debug("Overlay test: %s not updated", getattr(widget, "widget_name", widget), exc_info=True)


def overlays() -> list:
    """Running overlays (not stopped)"""
    from ..module_control import wctrl

    return [widget for widget in tuple(wctrl.active_modules.values()) if widget.__dict__]


_test: OverlayTest | None = None


def overlay_test() -> OverlayTest:
    """Test of the app (one at a time, kept running when the page closes)"""
    global _test
    if _test is None:
        _test = OverlayTest()
    return _test
