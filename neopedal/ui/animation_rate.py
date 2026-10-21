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
Animation step follows the refresh rate of the main window screen

Qt animations (QML transitions, list scrolling, overlay fades) advance on a 16 ms timer whatever the
screen: Qt Quick pages of the app are widgets (QQuickWidget), they get no vsync driven animation driver
and render at most 62 frames per second, on a 144 Hz or 240 Hz screen too. The step of that timer
(QUnifiedTimer timing interval, GUI thread) is set from the screen refresh rate instead.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import sys
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QScreen, QWindow
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL = 16  # ms: Qt animation step (60 Hz)
MIN_INTERVAL = 4  # ms: a Qt Quick widget renders 5 ms after a change at best, shorter steps only cost CPU

# Qt Core exports (MSVC x64): static QUnifiedTimer *QUnifiedTimer::instance(), void setTimingInterval(int)
_INSTANCE = "?instance@QUnifiedTimer@@SAPEAV1@XZ"
_SET_INTERVAL = "?setTimingInterval@QUnifiedTimer@@QEAAXH@Z"


def interval_for(refresh_rate: float) -> int:
    """Animation step (ms) for a screen refresh rate (Hz): one step per refresh, 4 to 16 ms"""
    if not refresh_rate > 0:  # unknown (0, nan)
        return DEFAULT_INTERVAL
    return max(MIN_INTERVAL, min(DEFAULT_INTERVAL, round(1000 / refresh_rate)))


def _load_setter() -> Callable[[int], None] | None:
    """Setter of the animation step of the calling thread, None if unavailable (other platform, Qt build)"""
    if sys.platform != "win32" or sys.maxsize <= 2**32:  # mangled names of 64-bit MSVC builds only
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetModuleHandleW.argtypes = (ctypes.c_wchar_p,)
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        handle = kernel32.GetModuleHandleW("Qt6Core.dll")  # library loaded by PySide6, never loaded again
        if not handle:
            return None
        core = ctypes.WinDLL("Qt6Core.dll", handle=handle)
        instance = ctypes.CFUNCTYPE(ctypes.c_void_p)((_INSTANCE, core))
        set_interval = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int)((_SET_INTERVAL, core))
    except (OSError, AttributeError):  # symbol not exported by this Qt build
        return None

    def setter(interval: int):
        timer = instance()  # per thread instance, created if needed
        if timer:
            set_interval(timer, interval)

    return setter


class AnimationRate(QObject):
    """Animation step of the GUI thread set from the refresh rate of the screen showing the window, followed
    when the window moves to another screen or the refresh rate changes"""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        self._setter = _load_setter()
        self._handle: QWindow | None = None  # window handle whose screen is followed (exists once window is shown)
        self._screen: QScreen | None = None
        self.interval = DEFAULT_INTERVAL
        if self._setter is None:
            logger.info("ANIMATION: step stays %s ms (not available on this platform)", DEFAULT_INTERVAL)
            return
        window.installEventFilter(self)
        self.follow_handle()
        self.follow_screen(window.screen())

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show and watched is self._window:
            self.follow_handle()
        return False

    def follow_handle(self):
        handle = self._window.windowHandle()
        if handle is None or handle is self._handle:
            return
        self._handle = handle
        handle.screenChanged.connect(self.follow_screen)
        self.follow_screen(handle.screen())

    def follow_screen(self, screen: QScreen | None):
        if screen is self._screen:
            return
        if self._screen is not None:
            with contextlib.suppress(RuntimeError, TypeError):  # screen removed meanwhile
                self._screen.refreshRateChanged.disconnect(self.apply)
        self._screen = screen
        if screen is not None:
            screen.refreshRateChanged.connect(self.apply)
        self.apply()

    def apply(self, *_):
        if self._setter is None:
            return
        interval = interval_for(self._screen.refreshRate() if self._screen is not None else 0.0)
        if interval == self.interval:
            return
        self.interval = interval
        self._setter(interval)
        logger.info("ANIMATION: step %s ms (screen %.0f Hz)", interval,
                    self._screen.refreshRate() if self._screen is not None else 0.0)
