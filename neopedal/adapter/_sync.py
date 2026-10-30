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
Shared memory update thread of game API connectors (LMU, rF2): player sync, freeze & resume,
vehicle reset detection, slot id to telemetry index map

Each connector subclasses SyncData with the parts of its own data structures (see hooks).
"""

from __future__ import annotations

import ctypes
import logging
import threading
from time import monotonic
from typing import Any, ClassVar

from .. import app_signal, realtime_state
from ..thread_guard import run_supervised, wait_all_stopped
from .data_notify import notifier

logger = logging.getLogger(__name__)
INVALID_INDEX = -1  # same in LMU & rF2 shared memory libraries
STOP_TIMEOUT = 3.0  # seconds to wait for update thread to stop
RETRY_DELAYS = (1.0, 5.0, 30.0, 60.0)  # seconds before update loop restarts once its restart budget is spent


def default_tele_indexes() -> dict[int, int]:
    """Telemetry index of slot id, before any match (none: unknown slot id has no telemetry)"""
    return {}


def copy_struct(struct_data: Any) -> Any:
    """Allow to copy ctypes struct data with __slots__"""
    return type(struct_data).from_buffer_copy(
        ctypes.string_at(
            ctypes.byref(struct_data),
            ctypes.sizeof(struct_data),
        )
    )


class SyncData:
    """Synchronize data with player ID

    Attributes:
        dataset: mmap data set.
        paused: Is API data paused.
        synced: Is player data synced.
        resets: Number of player vehicle resets.
        override_player_index: is player index overidden.
        player_scor_index: Local player scoring index.
        player_scor: Local player scoring data.
        player_tele: Local player telemetry data.
        error: why shared memory could not be opened, empty if opened.
        last_update: monotonic time of last game data change, 0 if none.
        tele_map: telemetry index per scoring index of vehicles in session (with data structures
            it was made from), rebuilt on update tick with new data once index key changed.

    Hooks of connector (data structures): _read_data, _index_key, _update_indexes, _player_scoring_index,
    __sync_player_scor, __sync_player_tele, sync_tele_index, _release_rows, _log_unavailable,
    and _results_stream for a connector with results stream (results attribute).
    """

    THREAD_NAME: ClassVar[str] = ""  # update thread name
    SUPERVISED_NAME: ClassVar[str] = ""  # update task name in error log
    NO_TELE_MAP: ClassVar[tuple] = ()  # tele_map of no data structure
    __slots__ = (
        "_updating",
        "_update_thread",
        "_event",
        "_tele_indexes",
        "_last_data",
        "tele_map",
        "paused",
        "synced",
        "resets",
        "override_player_index",
        "player_slot_id",
        "player_scor_index",
        "player_scor",
        "player_tele",
        "dataset",
        "error",
        "last_update",
    )

    def __init__(self, dataset: Any) -> None:
        self._updating = False
        self._update_thread: threading.Thread | None = None
        self._event = threading.Event()
        self._tele_indexes = default_tele_indexes()
        self._last_data: Any = None  # data structures of last index update (update loop)
        self.tele_map = self.NO_TELE_MAP

        self.paused = False
        self.synced = False
        self.resets = 0
        self.override_player_index = False
        self.player_slot_id = INVALID_INDEX
        self.player_scor_index = INVALID_INDEX
        self.player_scor: Any = None  # set by sync before use
        self.player_tele: Any = None
        self.dataset = dataset
        self.error = ""
        self.last_update = 0.0

    def __del__(self) -> None:
        if logger is not None:  # module globals are cleared at interpreter exit
            logger.info("sharedmemory: GC: SyncData")

    # Hooks of connector
    def _read_data(self) -> tuple[Any, bool]:
        """(scoring info, data structures replaced since last call) of tick"""
        raise NotImplementedError

    def _index_key(self) -> tuple:
        """Key of current data, index maps rebuilt only once it changed (or data structure replaced):
        scoring sample time & vehicle counts of scoring & telemetry (slot ids only change with them,
        a reordered telemetry array waits for next scoring sample, at most a scoring period)"""
        raise NotImplementedError

    def _update_indexes(self) -> None:
        """Update telemetry indexes of slot ids & telemetry map from current data"""
        raise NotImplementedError

    def _player_scoring_index(self) -> int:
        """Scoring index of local player (or player index override), INVALID_INDEX if not found"""
        raise NotImplementedError

    def __sync_player_scor(self, scor_index: int = INVALID_INDEX) -> None:
        """Sync local player vehicle scoring data"""
        raise NotImplementedError

    def __sync_player_tele(self, tele_index: int = INVALID_INDEX) -> None:
        """Sync local player vehicle telemetry data, zeroed if no telemetry index"""
        raise NotImplementedError

    def sync_tele_index(self, scor_idx: int) -> int:
        """Telemetry index of scoring index (matched by slot id), INVALID_INDEX if none"""
        raise NotImplementedError

    def _release_rows(self) -> None:
        """Forget vehicle wrappers of mmap data (before close)"""
        raise NotImplementedError

    def _log_unavailable(self, error: Exception) -> None:
        """Log shared memory open error"""
        raise NotImplementedError

    def _results_stream(self) -> bytes:
        """Results stream of current data (connector with results attribute only)"""
        raise NotImplementedError

    # Player data
    def __sync_player_data(self) -> bool:
        """Sync local player data

        Returns:
            False, if no valid player scoring index found.
            True, set player data.
        """
        scor_idx = self._player_scoring_index()
        if scor_idx == INVALID_INDEX:
            return False  # index not found, not synced
        self.player_scor_index = scor_idx
        # Set player data
        self.__sync_player_scor(self.player_scor_index)
        self.__sync_player_tele(self.sync_tele_index(self.player_scor_index))
        return True  # found index, synced

    def _start_updating(self) -> None:
        """Update & sync mmap data copy in separate thread, once mmap created"""
        self.error = ""
        self._updating = True
        self._tele_indexes = default_tele_indexes()
        self._update_indexes()
        if not self.__sync_player_data():
            self.__sync_player_scor()
            self.__sync_player_tele()
        # Setup updating thread, own stop event for each thread (a previous thread still stopping never resumes)
        self._event = threading.Event()
        self._update_thread = threading.Thread(
            target=self.__update, args=(self._event,), daemon=True, name=self.THREAD_NAME)
        self._update_thread.start()
        logger.info("sharedmemory: UPDATING: thread started")
        logger.info("sharedmemory: player index override: %s", self.override_player_index)

    def _set_unavailable(self, error: Exception) -> None:
        """Not connected state: zeroed data, paused, no updating thread"""
        self.error = str(error)
        self._log_unavailable(error)
        app_signal.error.emit("Unable to open game shared memory, see log for details.")
        self.dataset.set_unavailable()
        self.player_scor_index = INVALID_INDEX
        self.__sync_player_scor()
        self.__sync_player_tele()
        self.paused = True
        self.synced = False

    def stop(self) -> None:
        """Join and stop updating thread, close mmap (request_stop then wait_stopped)"""
        if self._updating:
            self.request_stop()
            self.wait_stopped()
        else:
            logger.warning("sharedmemory: UPDATING: already stopped")

    def request_stop(self) -> None:
        """Signal updating thread to stop, returns at once: wait_stopped joins it & closes mmap

        Split so every API thread is signalled before any is waited (threads stop in parallel).
        """
        if self._updating:
            self._event.set()

    def wait_stopped(self, timeout: float = STOP_TIMEOUT, deadline: float | None = None) -> bool:
        """Wait (bounded) for signalled updating thread, then close mmap, returns True if thread stopped

        Args:
            timeout: maximum wait (seconds), see thread_guard.wait_all_stopped.
            deadline: monotonic time to give up at instead (shared with other threads stopping).
        """
        if not self._updating:
            return True
        stopped = True
        self._event.set()
        self._updating = False
        thread = self._update_thread
        if thread is not None:
            stopped = wait_all_stopped(
                ((self.THREAD_NAME, lambda: not thread.is_alive(), thread.join),), timeout, deadline)
            if not stopped:  # exits on its own event, close only makes its reads fail
                logger.warning("sharedmemory: UPDATING: thread still stopping in background")
        # Make final copy before close, otherwise mmap won't close if using direct access
        if self.player_scor is not None:
            self.player_scor = copy_struct(self.player_scor)
        if self.player_tele is not None:
            self.player_tele = copy_struct(self.player_tele)
        self._release_rows()  # release wrappers of mmap data
        self._last_data = None  # data structures of update loop (direct access: view of mmap)
        self.tele_map = self.NO_TELE_MAP
        self.dataset.close_mmap()
        return stopped

    def _hide_while_crashed(self) -> None:
        """Crashed update loop: hide overlays instead of showing frozen values until restarted"""
        self.paused = True
        self.synced = False
        realtime_state.notify_change()

    def __update(self, event: threading.Event) -> None:
        """Run update loop, restart after unexpected error

        Never gives up while not stopped (RETRY_DELAYS): a run of torn reads at session start must not leave
        the connector dead until the user reloads.
        """
        notifier.attach()  # data modules wait for notified new data while thread runs
        try:
            if (
                not run_supervised(  # positional: tests replace it with lambda *args
                    lambda: self.__update_loop(event), self.SUPERVISED_NAME, event, 3, 1.0,
                    RETRY_DELAYS, self._hide_while_crashed)
                and not event.is_set()
            ):
                # Stopped after repeated errors: hide overlays instead of showing frozen values
                self._hide_while_crashed()
        finally:
            notifier.detach()  # data modules woken, back to polling

    def __update_loop(self, event: threading.Event) -> None:
        """Update synced player data"""
        self.paused = False  # make sure initial pause state is false
        self.synced = False
        self.resets = 0
        realtime_state.notify_change()  # threads idle while frozen read state again

        _event_wait = event.wait
        _notify = notifier.notify
        _read_data = self._read_data
        results = getattr(self, "results", None)  # results stream data of connector, None if none
        freezed_timestamp = 0  # store freezed timestamp
        last_session_timestamp = 0  # store last timestamp
        last_update_time = 0.0
        data_freezed = True  # whether data is freezed
        last_in_garage = False
        last_slot_id = INVALID_INDEX
        reset_counter = 0
        update_delay = 0.5  # longer delay while inactive
        self._last_data = None  # data structures of last index update
        data_synced: bool | None = None  # result of last player sync, None: sync on next tick
        last_sync_key: tuple = ()  # player index override setting of last player sync
        last_signature: tuple = ()  # data read by modules, notified on change
        last_index_key: tuple | None = None  # index key of last index maps update
        last_session_key: tuple | None = None  # track, session type & start time of last tick with new data
        session_changed = False  # new session: results of previous one not forgotten yet (results stream below)

        while not _event_wait(update_delay):
            copied = self.dataset.update_mmap()
            scor_info, replaced = _read_data()
            session_timestamp = scor_info.mCurrentET
            # Data copies unchanged since last tick: index maps & player sync would give same result
            new_data = copied is not False or replaced
            if new_data:
                index_key = self._index_key()
                # Session changed: elapsed time went back, or another track, session type or start time (a
                # session joined with a larger elapsed time than the one left, multiplayer)
                session_key = (scor_info.mTrackName, scor_info.mSession, scor_info.mStartET)
                if session_timestamp < last_session_timestamp or (
                    last_session_key is not None and last_session_key != session_key
                ):
                    session_changed = True
                    self._tele_indexes = default_tele_indexes()  # forget slot ids of previous session
                    last_index_key = None
                last_session_key = session_key
                if replaced or last_index_key != index_key:
                    last_index_key = index_key
                    self._update_indexes()

            # Update player data & index
            if not data_freezed:
                # Get player data, again only after new data or player index override change
                sync_key = (self.override_player_index, self.player_slot_id)
                if new_data or data_synced is None or last_sync_key != sync_key:
                    last_sync_key = sync_key
                    data_synced = self.__sync_player_data()
                # Pause if local player index no longer exists, 5 tries
                if data_synced:
                    reset_counter = 0
                    self.synced = True
                elif reset_counter < 6:
                    reset_counter += 1
                    if reset_counter == 5:
                        self.player_scor_index = INVALID_INDEX
                        self.__sync_player_scor()
                        self.__sync_player_tele()
                        self.synced = False
                        logger.info("sharedmemory: UPDATING: player data paused")
                # Result stream
                if results is not None and (session_changed or results.timestamp != session_timestamp):
                    if session_changed or results.timestamp > session_timestamp:
                        results.clear()
                    session_changed = False
                    results.timestamp = session_timestamp
                    results.update(self._results_stream())

            if last_session_timestamp != session_timestamp:
                if self.synced:  # player data of a real slot (zeroed structure while not synced: no car)
                    in_garage = self.player_scor.mInGarageStall
                    slot_id = self.player_scor.mID
                else:
                    in_garage, slot_id = last_in_garage, last_slot_id
                if (
                    last_session_timestamp > session_timestamp  # session changed
                    or last_in_garage < in_garage  # returned to garage
                    or last_slot_id != slot_id  # changed slot id
                ):
                    self.resets += 1

                last_update_time = self.last_update = monotonic()
                last_session_timestamp = session_timestamp
                last_in_garage = in_garage
                last_slot_id = slot_id

            if data_freezed:
                # Check while IN freeze state
                if freezed_timestamp != last_session_timestamp:
                    update_delay = 0.01
                    self.paused = data_freezed = False
                    data_synced = None  # player synced again on resume
                    realtime_state.notify_change()
                    logger.info(
                        "sharedmemory: UPDATING: resumed, data timestamp %s",
                        last_session_timestamp,
                    )
            # Paused replay (frame by frame, opened at lap position) holds data on purpose
            elif self.dataset.replay_paused():
                last_update_time = monotonic()
            # Check while NOT IN freeze state
            # Set freeze state if data stopped updating after 2s
            elif monotonic() - last_update_time > 2:
                update_delay = 0.5
                self.paused = data_freezed = True
                self.synced = False
                data_synced = None
                freezed_timestamp = last_session_timestamp
                realtime_state.notify_change()
                logger.info(
                    "sharedmemory: UPDATING: paused, data timestamp %s",
                    freezed_timestamp,
                )

            # Notify data modules once data they read changed (data stamp, state)
            signature = (
                session_timestamp,
                self.player_tele.mElapsedTime,
                self.player_scor_index,
                scor_info.mNumVehicles,
                self.resets,
                self.paused,
                self.synced,
            )
            if last_signature != signature:
                last_signature = signature
                _notify()

        logger.info("sharedmemory: UPDATING: thread stopped")
