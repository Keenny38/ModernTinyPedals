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
Data module base
"""

from __future__ import annotations

import logging
import threading
from functools import partial
from time import monotonic
from typing import Any

from .. import realtime_state
from ..api_control import api
from ..setting import Setting
from ..thread_guard import run_supervised

logger = logging.getLogger(__name__)
# Function
round6 = partial(round, ndigits=6)
# Sent to data generator when module stops: save data not saved yet, without reloading
MODULE_STOP = object()
# Sent to data generator while player inactive (left track, garage) with a lap waiting for validation
PENDING_CHECK = object()
PENDING_WAIT = 10.0  # seconds to validate completed lap after leaving track just after start line


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
    """

    __slots__ = (
        "module_name",
        "closed",
        "discard",
        "cfg",
        "mcfg",
        "active_interval",
        "idle_interval",
        "_event",
        "_done",
    )

    def __init__(self, config: Setting, module_name: str):
        self.module_name = module_name
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
        self.active_interval = max(
            self.mcfg["update_interval"],
            self.cfg.application["minimum_update_interval"]) / 1000
        self.idle_interval = max(
            self.active_interval,
            self.mcfg["idle_update_interval"],
            self.cfg.application["minimum_update_interval"]) / 1000

    def start(self):
        """Start update thread"""
        if self.closed:
            self.closed = False
            self.discard = False
            self._event.clear()
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

    def update_data(self):
        """Update module data, rewrite in child class"""

    def __tasks(self):
        """Run tasks in separated thread"""
        try:
            run_supervised(self.update_data, self.module_name.replace("_", " "), self._event)
        finally:
            # Always mark closed, as module control waits for it before reload or quit
            self.closed = True
            self._done.set()
            logger.info("DISABLED: %s", self.module_name.replace("_", " "))
