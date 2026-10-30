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
Init logger, state, signal
"""

import logging
import threading

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
        shown: whether overlays are shown & updated (active, or spectating while streamed, see overlay_control).
        hidden: whether overlay is hidden.
        screen_hidden: whether overlay is auto hidden on screen only (kept shown on stream while not driving,
            window fully transparent, see overlay_control).
        editing: whether overlay edit mode is on (toolbar & outlines shown, see widget._edit_mode).
        session_type: session type of player, for widget visibility context.
        in_pits: whether player is in pit lane or garage.
        overriding: whether is state override mode enabled.
        spectating: whether is spectate mode enabled.
        singleton: whether is single-instance mode enabled.
        overlays: names of overlays running (widget control), for data fetched only while an overlay reads it.
        version: activity change counter (active, paused, shown, resets, connector freeze & resume).

    Activity change: notify_change wakes threads idle until activity changes (wait_change, subscribed wake
    events), instead of polling state while game is closed or inactive.
    """

    __slots__ = (
        "active",
        "paused",
        "resets",
        "shown",
        "hidden",
        "screen_hidden",
        "editing",
        "session_type",
        "in_pits",
        "overriding",
        "spectating",
        "singleton",
        "overlays",
        "version",
        "_change",
        "_wakes",
    )

    def __init__(self):
        self.active: bool = False
        self.paused: bool = True
        self.resets: int = 0
        self.shown: bool = False
        self.hidden: bool = False
        self.screen_hidden: bool = False
        self.editing: bool = False
        self.session_type: int = -1  # 0 testday, 1 practice, 2 qualify, 3 warmup, 4 race, -1 unknown
        self.in_pits: bool = False  # player in pit lane or garage
        self.overriding: bool = False
        self.spectating: bool = False
        self.singleton: bool = False
        self.overlays: frozenset[str] = frozenset()
        self.version = 0
        self._change = threading.Condition()
        self._wakes: tuple[threading.Event, ...] = ()  # copy on write, set without lock

    def notify_change(self) -> None:
        """Activity changed: wake waiting threads & subscribed events

        Called from data threads (connector sync, overlay control), never emits a Qt signal: a plain function
        connected to it would run in the emitting thread (GUI readers poll realtime_state or wait_change).
        """
        with self._change:
            self.version += 1
            self._change.notify_all()
        for wake in self._wakes:
            wake.set()

    def subscribe(self, wake: threading.Event) -> None:
        """Set wake event on every activity change (thread waiting with its own stop wake)"""
        with self._change:
            if wake not in self._wakes:
                self._wakes += (wake,)

    def unsubscribe(self, wake: threading.Event) -> None:
        """Stop setting wake event"""
        with self._change:
            self._wakes = tuple(_wake for _wake in self._wakes if _wake is not wake)

    def wait_change(self, timeout: float, wake: threading.Event | None = None, since: int | None = None) -> bool:
        """Wait up to timeout seconds until activity changed, True if changed (or woken) before timeout

        Args:
            timeout: longest wait, seconds.
            wake: subscribed wake event (see subscribe), also set by owner to stop: waited, then cleared.
                Change notified while caller was busy is never missed (event kept set).
            since: without wake, version read before (change since then returns at once), current if None.
        """
        if wake is not None:
            if not wake.is_set():
                wake.wait(timeout)
            woken = wake.is_set()
            wake.clear()
            return woken
        with self._change:
            if since is None:
                since = self.version
            return self._change.wait_for(lambda: self.version != since, timeout)


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
        addresses: signal for LAN addresses of this computer changed (looked up in background).
        servers: signal for a server listening again (port unavailable before, tried again in background).
        spectate_changed: signal for spectated car changed (slot id), spectate mode still on (Broadcast Director
            cuts): Spectate page follows, without the whole GUI refreshed (refresh is still emitted when spectate
            mode is turned on or off: notification bar).
    """

    reload = Signal(bool)
    updates = Signal(bool)
    refresh = Signal(bool)
    quitapp = Signal(bool)
    hotkey = Signal(object)
    error = Signal(str)
    saving = Signal(bool)
    addresses = Signal()
    servers = Signal()
    spectate_changed = Signal(int)
    __slots__ = ()


realtime_state = RealtimeState()
overlay_signal = OverlaySignal()
app_signal = ApplicationSignal()
