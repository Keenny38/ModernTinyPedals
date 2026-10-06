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
Init logger, state, signal
"""

import logging

from PySide6.QtCore import QObject, Signal

# Create logger
logger = logging.getLogger(__package__)


class RealtimeState:
    """Realtime state

    Check realtime data update state without calling methods.
    State control: APIControl, OverlayControl.

    Attributes:
        active: whether is active (driving or overriding) state.
        paused: whether data stopped updating.
        resets: number of player vehicle resets.
        hidden: whether overlay is hidden.
        editing: whether overlay edit mode is on (toolbar & outlines shown, see widget._edit_mode).
        session_type: session type of player, for widget visibility context.
        in_pits: whether player is in pit lane or garage.
        overriding: whether is state override mode enabled.
        spectating: whether is spectate mode enabled.
        singleton: whether is single-instance mode enabled.
    """

    __slots__ = (
        "active",
        "paused",
        "resets",
        "hidden",
        "editing",
        "session_type",
        "in_pits",
        "overriding",
        "spectating",
        "singleton",
    )

    def __init__(self):
        self.active: bool = False
        self.paused: bool = True
        self.resets: int = 0
        self.hidden: bool = False
        self.editing: bool = False
        self.session_type: int = -1  # 0 testday, 1 practice, 2 qualify, 3 warmup, 4 race, -1 unknown
        self.in_pits: bool = False  # player in pit lane or garage
        self.overriding: bool = False
        self.spectating: bool = False
        self.singleton: bool = False


class OverlaySignal(QObject):
    """Overlay signal

    Attributes:
        hidden: signal for toggling auto hide state.
        locked: signal for toggling lock state.
        paused: signal for pausing and resuming overlay timer.
        iconify: signal for toggling taskbar icon visibility state (for VR compatibility).
        context: signal for session type or pit state changed (widget visibility context).
        editing: signal for overlay edit mode started or ended.
    """

    hidden = Signal(bool)
    context = Signal()
    locked = Signal(bool)
    paused = Signal(bool)
    iconify = Signal(bool)
    editing = Signal(bool)
    __slots__ = ()


class ApplicationSignal(QObject):
    """Application signal

    Attributes:
        reload: signal for reloading preset, should only be emitted after app fully loaded.
        updates: signal for checking version updates.
        refresh: signal for refreshing main GUI.
        quitapp: signal for closing APP.
        hotkey: signal for run hotkey command from main thread.
        error: signal for notifying background error message (thread crash, save failure).
        saving: signal for saving state changes (True = started, False = finished).
    """

    reload = Signal(bool)
    updates = Signal(bool)
    refresh = Signal(bool)
    quitapp = Signal(bool)
    hotkey = Signal(object)
    error = Signal(str)
    saving = Signal(bool)
    __slots__ = ()


realtime_state = RealtimeState()
overlay_signal = OverlaySignal()
app_signal = ApplicationSignal()
