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
Data module base
"""

from __future__ import annotations

import logging
import threading
from functools import partial
from time import monotonic
from typing import Any

from .. import realtime_state
from ..adapter.data_notify import notifier
from ..api_control import api
from ..context import AppContext, app_context
from ..setting import Setting
from ..thread_guard import STOP_TIMEOUT, run_supervised

logger = logging.getLogger(__name__)
# Function
round6 = partial(round, ndigits=6)
# Sent to data generator when module stops: save data not saved yet, without reloading
MODULE_STOP = object()
# Sent to data generator while player inactive (left track, garage) with a lap waiting for validation
PENDING_CHECK = object()
PENDING_WAIT = 10.0  # seconds to validate completed lap after leaving track just after start line
# Data recorded while driving also saved this often (seconds), not only on reset: kept after a crash or power loss
CHECKPOINT_INTERVAL = 300.0
# Longest wait for new game data while active (seconds), as state changes made by other threads
# (realtime state, other modules output) are not notified
DATA_MAX_WAIT = 0.1
# Update interval of an idle module (not driving, nothing pending): wait for activity state change
# (realtime_state.notify_change: active, paused, shown, resets), at most IDLE_WAIT seconds, see wait_update
WAIT_STATE_CHANGE = -1.0
IDLE_WAIT = 5.0


class DerivedUpdates:
    """Delta module position updates followed by modules with WAKE_ON_DERIVED (fuel, notes)

    While delta module updates (active), these modules wake once per delta update only (after delta position
    is set for the new sample), not also on the game data notification just before it (computed twice).

    Attributes:
        active: delta module updating every new sample (else derived modules follow game data).
        sequence: number of delta updates, changes only on new delta update.
    """

    __slots__ = ("active", "sequence", "_lock", "_events")

    def __init__(self) -> None:
        self.active = False
        self.sequence = 0
        self._lock = threading.Lock()
        self._events: tuple[threading.Event, ...] = ()  # copy on write

    def subscribe(self, event: threading.Event) -> None:
        """Set event on each delta update"""
        with self._lock:
            if event not in self._events:
                self._events += (event,)

    def unsubscribe(self, event: threading.Event) -> None:
        """Stop setting event"""
        with self._lock:
            self._events = tuple(_event for _event in self._events if _event is not event)

    def publish(self) -> None:
        """Delta module updated for a new sample"""
        self.sequence += 1
        for event in self._events:
            event.set()

    def set_active(self, active: bool) -> None:
        """Delta module started or stopped updating every sample, derived modules woken to follow"""
        if self.active != active:
            self.active = active
            for event in self._events:
                event.set()


derived_updates = DerivedUpdates()


def data_stamp() -> tuple:
    """Stamp of game data, changes on new telemetry or scoring sample, player change or vehicle reset

    Modules compare it every tick to skip work while game data did not update
    (update interval is shorter than game telemetry rate).
    """
    read = api.read
    return (
        read.timing.elapsed(),
        read.session.elapsed(),
        read.vehicle.player_index(),
        realtime_state.resets,
    )



def derived_stamp(delta: Any) -> tuple:
    """Stamp of modules following delta module position (WAKE_ON_DERIVED), delta: delta module output

    While delta module updates every sample: its update number (it updates once per new data stamp,
    after setting delta position), else game data stamp & delta position.
    """
    if derived_updates.active:
        return (derived_updates.sequence, realtime_state.resets)
    return (data_stamp(), delta.lapDistance)

class PendingLap:
    """Lap just completed, waiting for validation by game lap time (scoring updates slower than telemetry)

    Lap data is captured at the line, so a new lap started meanwhile (back to garage starts a new lap)
    never replaces it. Player leaving track (reset, inactive) before validation: lap kept & checked
    for up to PENDING_WAIT seconds (see resolve), saved if validated.

    Attributes:
        laptime: lap time from lap start times.
        finish: game elapsed time at the line.
        data: lap data of module.
        deadline: clock time limit of validation once player left track, 0 while driving.
    """

    __slots__ = ("laptime", "finish", "data", "deadline")

    def __init__(self, laptime: float, finish: float, data: Any = None):
        self.laptime = laptime
        self.finish = finish
        self.data = data
        self.deadline = 0.0

    def matched(self, laptime_valid: float) -> bool:
        """Whether game last lap time (laptime_valid) is the lap time of this lap"""
        return laptime_valid > 0 and abs(laptime_valid - self.laptime) < 0.001

    def confirmed(self) -> bool:
        """Whether game last lap time is the lap time of this lap"""
        try:
            return self.matched(api.read.timing.last_laptime())
        except (AttributeError, TypeError):
            return False

    def resolve(self, final: bool = False) -> bool | None:
        """Validate lap after player left track (game data may not update while driving stopped)

        Args:
            final: last check (module stopping, new stint starting), never waits.

        Returns:
            True if validated by game lap time, False if not validated in time, None if still waiting.
        """
        if not self.deadline:
            self.deadline = monotonic() + PENDING_WAIT
        if self.confirmed():
            return True
        if final or monotonic() >= self.deadline:
            return False
        return None


class DataModule:
    """Data module base

    Attributes:
        discard: data not saved yet is discarded when module stops (data reset), else saved.
        WAKE_ON_DERIVED: also woken by delta module position update (module stamp includes it).
        STOP_TIMEOUT: longest wait for update thread to finish its stop work (saving), seconds.
    """

    WAKE_ON_DERIVED = False
    STOP_TIMEOUT = STOP_TIMEOUT
    __slots__ = (
        "module_name",
        "ctx",
        "closed",
        "discard",
        "cfg",
        "mcfg",
        "active_interval",
        "idle_interval",
        "_event",
        "_done",
        "_wake",
        "_wake_derived",
        "_wake_state",
        "_max_wait",
        "_next_update",
    )

    def __init__(self, config: Setting, module_name: str, ctx: AppContext | None = None):
        self.module_name = module_name
        # App objects (see neopedal.context): new code reads them here, the update loop keeps its globals
        self.ctx = ctx if ctx is not None else app_context()
        self.closed = True
        self.discard = False

        # Base config
        self.cfg = config

        # Module config
        self.mcfg: dict = self.cfg.user.setting[module_name]

        # Module update interval
        self._event = threading.Event()
        self._done = threading.Event()  # set once update thread finished
        self._done.set()
        self._wake = threading.Event()  # set on new game data (connector notification) or stop
        self._wake_derived = threading.Event()  # set on delta module update or stop (WAKE_ON_DERIVED)
        self._wake_state = threading.Event()  # set on activity state change or stop (idle module)
        self._next_update = 0.0  # monotonic time of earliest next update (update interval kept)
        self.active_interval = max(
            self.mcfg["update_interval"],
            self.cfg.application["minimum_update_interval"]) / 1000
        self.idle_interval = max(
            self.active_interval,
            self.mcfg["idle_update_interval"],
            self.cfg.application["minimum_update_interval"]) / 1000
        self._max_wait = max(self.active_interval, min(self.idle_interval, DATA_MAX_WAIT))

    def start(self):
        """Start update thread"""
        if self.closed:
            self.closed = False
            self.discard = False
            self._event.clear()
            self._wake.clear()
            self._wake_derived.clear()
            self._wake_state.set()  # idle wait at start returns at once (state read on first update)
            self._next_update = 0.0
            self._done.clear()
            threading.Thread(target=self.__tasks, daemon=True, name=f"module:{self.module_name}").start()
            logger.info("ENABLED: %s", self.module_name.replace("_", " "))

    def stop(self, discard: bool = False):
        """Stop update thread

        Args:
            discard: discard data not saved yet (data reset), else saved before stopping.
        """
        self.discard = discard
        self._event.set()
        self._wake.set()  # wake thread waiting for game data
        self._wake_derived.set()  # or for delta module update
        self._wake_state.set()  # or for activity state change

    def wait_closed(self, timeout: float) -> bool:
        """Wait (up to timeout seconds) until update thread finished, True if finished"""
        return self._done.wait(timeout)

    def save_on_stop(self, *generators) -> None:
        """Save data not saved yet of data generators (run after update loop ended), unless discarded

        Also run when update loop ended by error, before module restarts and reloads data from file.
        """
        if self.discard:
            return
        for generator in generators:
            if generator is None:
                continue
            try:
                generator.send(MODULE_STOP)
            except StopIteration:  # generator ended by error, already logged
                pass
            except Exception:  # save other generators data
                logger.exception("%s: saving data on stop failed", self.module_name)

    def wait_update(self, interval: float) -> bool:
        """Wait before next update, returns True once module stopping

        While active (interval shorter than longest data wait) and a connector notifies new game data,
        waits for new data first (up to longest data wait, DATA_MAX_WAIT), then only for the rest of
        update interval if data came early: woken once per sample, never more often than update interval.
        Modules following delta module position (WAKE_ON_DERIVED) wait for delta module update instead,
        while it updates every sample (see DerivedUpdates). Else same as fixed interval polling.
        Interval WAIT_STATE_CHANGE (idle module, nothing pending): waits for activity state change instead,
        at most IDLE_WAIT seconds (state changes made without notification, such as replay state).
        """
        if interval == WAIT_STATE_CHANGE:
            realtime_state.wait_change(IDLE_WAIT, self._wake_state)
            return self._event.is_set()
        if self.WAKE_ON_DERIVED and derived_updates.active and interval < self._max_wait:
            wake = self._wake_derived
        elif interval >= self._max_wait or not notifier.available:
            return self._event.wait(interval)
        else:
            wake = self._wake
        wake.wait(self._max_wait)
        if self._event.is_set():
            return True
        early = self._next_update - monotonic()
        if early > 0 and self._event.wait(early):
            return True
        wake.clear()  # before reading data: data notified from now on wakes next wait
        self._next_update = monotonic() + interval
        return False

    def wait_fixed(self, interval: float) -> bool:
        """Wait fixed interval (no wake on new game data), returns True once module stopping

        Interval WAIT_STATE_CHANGE: waits for activity state change instead, see wait_update.
        """
        if interval == WAIT_STATE_CHANGE:
            realtime_state.wait_change(IDLE_WAIT, self._wake_state)
            return self._event.is_set()
        return self._event.wait(interval)

    def update_data(self):
        """Update module data, rewrite in child class"""

    def __tasks(self):
        """Run tasks in separated thread"""
        notifier.subscribe(self._wake, self.WAKE_ON_DERIVED)
        if self.WAKE_ON_DERIVED:
            derived_updates.subscribe(self._wake_derived)
        realtime_state.subscribe(self._wake_state)
        try:
            run_supervised(self.update_data, self.module_name.replace("_", " "), self._event)
        finally:
            notifier.unsubscribe(self._wake)
            derived_updates.unsubscribe(self._wake_derived)
            realtime_state.unsubscribe(self._wake_state)
            # Always mark closed, as module control waits for it before reload or quit
            self.closed = True
            self._done.set()
            logger.info("DISABLED: %s", self.module_name.replace("_", " "))
