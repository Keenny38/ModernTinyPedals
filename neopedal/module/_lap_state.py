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
Reset, lap waiting for validation & save state of lap data generators
"""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic
from typing import Any

from .. import realtime_state
from . import _base
from ._base import MODULE_STOP, PENDING_CHECK, PendingLap

# Step of a data generator tick, returned by LapState.receive
SKIP = 0  # value handled, nothing else to do this tick
UPDATE = 1  # same stint: update data
LOAD = 2  # new stint (reset while driving): load data, then update


class LapState:
    """Reset, lap waiting for validation & save state of a lap data generator

    Generator receives the vehicle reset count every tick while active, PENDING_CHECK while player
    inactive with a lap waiting for validation, MODULE_STOP when module stops (last check, data
    not saved yet saved). Lap completed just before leaving track keeps being validated (see
    PendingLap.resolve) before data is saved & reset. Data is (re)loaded once driving.

    Attributes:
        pending: lap just completed waiting for validation, None if none.
        delayed_save: data recorded and not saved yet (save callback clears it once saved).
        next_checkpoint: monotonic time of next save while driving (checkpoint enabled).
    """

    __slots__ = (
        "pending",
        "delayed_save",
        "next_checkpoint",
        "_last_reset",
        "_sent_reset",
        "_on_resolved",
        "_save",
        "_checkpoint",
        "_reset_on_check",
    )

    def __init__(
        self,
        on_resolved: Callable[[PendingLap, bool], Any],
        save: Callable[[], Any] | None = None,
        checkpoint: bool = False,
        reset_on_check: bool = True,
    ) -> None:
        """
        Args:
            on_resolved: called with lap & whether validated by game, once lap waiting for
                validation after player left track is resolved (validated or not in time).
            save: saves data not saved yet (delayed_save) on reset & module stop, None if none.
            checkpoint: also save every CHECKPOINT_INTERVAL while driving (crash, power loss).
            reset_on_check: reset waiting for lap validation applied on PENDING_CHECK, else
                PENDING_CHECK only validates lap (data reset once driving again).
        """
        self.pending: PendingLap | None = None
        self.delayed_save = False
        self.next_checkpoint = 0.0
        self._last_reset: Any = None  # reset of data loaded
        self._sent_reset: Any = None  # last reset value sent
        self._on_resolved = on_resolved
        self._save = save
        self._checkpoint = checkpoint
        self._reset_on_check = reset_on_check

    def resolve(self, final: bool = False) -> None:
        """Validate lap waiting for validation after player left track (final: never waits)"""
        lap = self.pending
        if lap is None:
            return
        valid = lap.resolve(final)
        if valid is None:
            return
        self._on_resolved(lap, valid)
        self.pending = None

    def save(self) -> None:
        """Save data (next checkpoint from now)"""
        if self._checkpoint:
            self.next_checkpoint = monotonic() + _base.CHECKPOINT_INTERVAL
        if self._save is not None:
            self._save()

    def receive(self, reset: Any) -> int:
        """Step of tick for value sent to generator: SKIP, UPDATE or LOAD"""
        if reset is PENDING_CHECK:
            # Player inactive: only validate lap just completed (data of lap kept until reset)
            if not self._reset_on_check or self._last_reset == self._sent_reset:  # no reset waiting
                self.resolve()
                return SKIP
            reset = self._sent_reset  # reset waiting for lap validation
        elif reset is not MODULE_STOP:
            self._sent_reset = reset

        if self._last_reset == reset:
            # Checkpoint while driving (crash, power loss)
            if self._checkpoint and self.delayed_save and monotonic() >= self.next_checkpoint:
                self.save()
            return UPDATE

        # Reset: left track just after line, validate lap just completed before saving (bounded wait)
        if self.pending is not None:
            self.resolve(final=reset is MODULE_STOP)
            if self.pending is not None:
                return SKIP
        if self.delayed_save:
            self.save()
        # Delay reset until driving (module stopping: data saved only)
        if reset is MODULE_STOP or not realtime_state.active:
            return SKIP
        self._last_reset = reset
        if self._checkpoint:
            self.delayed_save = False
            self.next_checkpoint = monotonic() + _base.CHECKPOINT_INTERVAL
        return LOAD
