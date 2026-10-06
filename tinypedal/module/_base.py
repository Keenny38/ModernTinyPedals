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

import logging
import threading
from functools import partial

from .. import realtime_state
from ..api_control import api
from ..setting import Setting
from ..thread_guard import run_supervised

logger = logging.getLogger(__name__)
# Function
round6 = partial(round, ndigits=6)
# Sent to data generator when module stops: save data not saved yet, without reloading
MODULE_STOP = object()


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
        """Save data not saved yet of data generators (run after update loop ended), unless discarded"""
        if self.discard:
            return
        for generator in generators:
            if generator is not None:
                generator.send(MODULE_STOP)

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
