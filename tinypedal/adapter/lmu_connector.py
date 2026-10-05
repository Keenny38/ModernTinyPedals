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
LMU API connector
"""

from __future__ import annotations

import ctypes
import logging
import threading
from collections.abc import Sequence
from time import monotonic
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # for type checker only
    from pyLMUSharedMemory import lmu_type as lmu_data
else:  # run time only
    from pyLMUSharedMemory import lmu_data

from pyLMUSharedMemory import lmu_data as lmu_struct  # ctypes structures (lmu_data is typed view)
from pyLMUSharedMemory import lmu_enum
from pyLMUSharedMemory.lmu_mmap import (
    INVALID_INDEX,
    LMUConstants,
    MMapControl,
)

from .. import app_signal
from ..replay import ReplayMMap, ReplayPlayer
from ..thread_guard import run_supervised

logger = logging.getLogger(__name__)

# Enum map
LMU_COMPOUND_TYPE = lmu_enum.enum_map(lmu_enum.LMUCompoundType)
STOP_TIMEOUT = 3.0  # seconds to wait for update thread to stop


def default_tele_indexes() -> dict[int, int]:
    """Telemetry index of slot id, before any match (same index)"""
    return {_index: _index for _index in range(128)}


def copy_struct(struct_data):
    """Allow to copy ctypes struct data with __slots__"""
    return type(struct_data).from_buffer_copy(
        ctypes.string_at(
            ctypes.byref(struct_data),
            ctypes.sizeof(struct_data),
        )
    )


def local_scoring_index(scor_veh: Sequence[lmu_data.LMUVehicleScoring]) -> int:
    """Find local player scoring index

    Args:
        scor_veh: scoring vehicle array.
    """
    for scor_idx, veh_info in enumerate(scor_veh):
        if veh_info.mIsPlayer:
            return scor_idx
    return INVALID_INDEX


def local_scoring_index_by_id(slot_id: int, scor_veh: Sequence[lmu_data.LMUVehicleScoring]) -> int:
    """Find local player scoring index by slot id

    Args:
        scor_veh: scoring array.
    """
    for scor_idx, veh_info in enumerate(scor_veh):
        if veh_info.mID == slot_id:
            return scor_idx
    return INVALID_INDEX


class LMUResults:
    """LMU results data (extracted from results stream)"""

    DEFAULT = MappingProxyType({
        "contact_vehicle": 0,
        "contact_immovable": 0,
        "track_cut": 0,
    })
    __slots__ = (
        "data",
        "timestamp",
        "_last_stream",
    )

    def __init__(self):
        self.data = {}
        self.timestamp = 0
        self._last_stream = b""

    def check_missing(self, driver: bytes):
        """Check & add missing driver"""
        if driver not in self.data:
            self.data[driver] = self.DEFAULT.copy()

    def update(self, stream: bytes):
        """Update results data"""
        # Check stream
        if self._last_stream == stream:
            return
        self._last_stream = stream
        if not stream:
            return
        # Parse stream
        results_data = self.data
        for line in stream.split(b"\n"):
            if not line:
                continue
            # Log incidents
            if line.startswith(b"<Incident"):
                pos_beg = line.find(b">")
                if pos_beg > 8:
                    pos_beg += 1
                    pos_end = line.find(b"(", pos_beg)
                    driver = line[pos_beg:pos_end]
                    self.check_missing(driver)
                    if b"with another vehicle" in line:
                        results_data[driver]["contact_vehicle"] += 1
                    else:
                        results_data[driver]["contact_immovable"] += 1
                continue
            # Log track cuts
            if line.startswith(b"<TrackLimits") and b"No Further Action" not in line:
                pos_beg = line.find(b"Driver=")
                if pos_beg > 11:
                    pos_beg += 8
                    pos_end = line.find(b'"', pos_beg)
                    driver = line[pos_beg:pos_end]
                    self.check_missing(driver)
                    results_data[driver]["track_cut"] += 1


class MMapDataSet:
    """Create mmap data set"""

    __slots__ = (
        "shmm",
    )

    def __init__(self) -> None:
        self.shmm = MMapControl(LMUConstants.LMU_SHARED_MEMORY_FILE, lmu_data.LMUObjectOut)

    def __del__(self):
        if logger is not None:  # module globals are cleared at interpreter exit
            logger.info("sharedmemory: GC: MMapDataSet")

    def create_mmap(self, access_mode: int) -> None:
        """Create mmap instance

        Args:
            access_mode: 0 = copy access, 1 = direct access.
        """
        self.shmm.create(access_mode)

    def close_mmap(self) -> None:
        """Close mmap instance"""
        self.shmm.close()

    def update_mmap(self) -> None:
        """Update mmap data"""
        self.shmm.update()

    def set_unavailable(self) -> None:
        """Zeroed data while shared memory cannot be opened (not connected state)"""
        self.shmm.data = lmu_struct.LMUObjectOut()

    def replay_paused(self) -> bool:
        """Whether replay player is paused: frame held on purpose, not a frozen game"""
        return bool(getattr(self.shmm, "paused", False))


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
        results: data from result stream.
        error: why shared memory could not be opened, empty if opened.
        last_update: monotonic time of last game data change, 0 if none.
    """

    __slots__ = (
        "_updating",
        "_update_thread",
        "_event",
        "_tele_indexes",
        "paused",
        "synced",
        "resets",
        "override_player_index",
        "player_slot_id",
        "player_scor_index",
        "player_scor",
        "player_tele",
        "dataset",
        "results",
        "error",
        "last_update",
    )

    def __init__(self) -> None:
        self._updating = False
        self._update_thread: threading.Thread | None = None
        self._event = threading.Event()
        self._tele_indexes = default_tele_indexes()

        self.paused = False
        self.synced = False
        self.resets = 0
        self.override_player_index = False
        self.player_slot_id = INVALID_INDEX
        self.player_scor_index = INVALID_INDEX
        self.player_scor: Any = None  # set by sync before use
        self.player_tele: Any = None
        self.dataset = MMapDataSet()
        self.results = LMUResults()
        self.error = ""
        self.last_update = 0.0

    def __del__(self):
        if logger is not None:  # module globals are cleared at interpreter exit
            logger.info("sharedmemory: GC: SyncData")

    def __sync_player_scor(self, scor_index: int = INVALID_INDEX) -> None:
        """Sync local player vehicle scoring data"""
        self.player_scor = self.dataset.shmm.data.scoring.vehScoringInfo[scor_index]

    def __sync_player_tele(self, tele_index: int = INVALID_INDEX) -> None:
        """Sync local player vehicle telemetry data"""
        self.player_tele = self.dataset.shmm.data.telemetry.telemInfo[tele_index]

    def __sync_player_data(self) -> bool:
        """Sync local player data

        Returns:
            False, if no valid player scoring index found.
            True, set player data.
        """
        # Update scoring index
        if self.override_player_index:
            scor_idx = local_scoring_index_by_id(self.player_slot_id, self.dataset.shmm.data.scoring.vehScoringInfo)
        else:
            scor_idx = local_scoring_index(self.dataset.shmm.data.scoring.vehScoringInfo)
        if scor_idx == INVALID_INDEX:
            return False  # index not found, not synced
        self.player_scor_index = scor_idx
        # Set player data
        self.__sync_player_scor(self.player_scor_index)
        self.__sync_player_tele(self.sync_tele_index(self.player_scor_index))
        return True  # found index, synced

    @staticmethod
    def __update_tele_indexes(tele_data: lmu_data.LMUTelemetryData, tele_indexes: dict) -> None:
        """Update telemetry player index dictionary for quick reference

        Telemetry index can be different from scoring index.
        Use mID matching to match telemetry index.
        Only active telemetry entries are matched (scoring vehicle count can differ while game updates).

        Args:
            tele_data: Telemetry data.
            tele_indexes: Telemetry mID:index reference dictionary.
        """
        for tele_idx, veh_info in zip(range(tele_data.activeVehicles), tele_data.telemInfo):
            tele_indexes[veh_info.mID] = tele_idx

    def sync_tele_index(self, scor_idx: int) -> int:
        """Sync telemetry index

        Use scoring index to find scoring mID,
        then match with telemetry mID in reference dictionary
        to find telemetry index.

        Args:
            scor_idx: Player scoring index.

        Returns:
            Player telemetry index.
        """
        return self._tele_indexes.get(
            self.dataset.shmm.data.scoring.vehScoringInfo[scor_idx].mID, INVALID_INDEX)

    def start(self, access_mode: int) -> None:
        """Update & sync mmap data copy in separate thread

        Args:
            access_mode: 0 = copy access, 1 = direct access.
        """
        if self._updating:
            logger.warning("sharedmemory: UPDATING: already started")
            return
        # Initialize mmap data
        try:
            self.dataset.create_mmap(access_mode)
        except (OSError, ValueError) as error:  # existing mapping of another size (other tool, older plugin)
            self.__set_unavailable(error)
            return
        self.error = ""
        self._updating = True
        self._tele_indexes = default_tele_indexes()
        self.__update_tele_indexes(self.dataset.shmm.data.telemetry, self._tele_indexes)
        if not self.__sync_player_data():
            self.__sync_player_scor()
            self.__sync_player_tele()
        # Setup updating thread
        self._event.clear()
        self._update_thread = threading.Thread(target=self.__update, daemon=True, name="LMU shared memory")
        self._update_thread.start()
        logger.info("sharedmemory: UPDATING: thread started")
        logger.info("sharedmemory: player index override: %s", self.override_player_index)

    def __set_unavailable(self, error: Exception) -> None:
        """Not connected state: zeroed data, paused, no updating thread"""
        self.error = str(error)
        logger.error(
            "sharedmemory: unable to open %s (%s bytes): %s. Shared memory may exist with another size "
            "(other telemetry tool or older plugin running), restart game & close other tools.",
            LMUConstants.LMU_SHARED_MEMORY_FILE, ctypes.sizeof(lmu_struct.LMUObjectOut), error,
        )
        app_signal.error.emit("Unable to open game shared memory, see log for details.")
        self.dataset.set_unavailable()
        self.player_scor_index = INVALID_INDEX
        self.__sync_player_scor()
        self.__sync_player_tele()
        self.paused = True
        self.synced = False

    def stop(self) -> None:
        """Join and stop updating thread, close mmap"""
        if self._updating:
            self._event.set()
            self._updating = False
            if self._update_thread is not None:
                self._update_thread.join(STOP_TIMEOUT)
            # Make final copy before close, otherwise mmap won't close if using direct access
            if self.player_scor is not None:
                self.player_scor = copy_struct(self.player_scor)
            if self.player_tele is not None:
                self.player_tele = copy_struct(self.player_tele)
            self.dataset.close_mmap()
        else:
            logger.warning("sharedmemory: UPDATING: already stopped")

    def __update(self) -> None:
        """Run update loop, restart after unexpected error"""
        if not run_supervised(self.__update_loop, "sharedmemory (LMU) update", self._event) and not self._event.is_set():
            # Stopped after repeated errors: hide overlays instead of showing frozen values
            self.paused = True
            self.synced = False

    def __update_loop(self) -> None:
        """Update synced player data"""
        self.paused = False  # make sure initial pause state is false
        self.synced = False
        self.resets = 0

        _event_wait = self._event.wait
        freezed_timestamp = 0  # store freezed timestamp
        last_session_timestamp = 0  # store last timestamp
        last_update_time = 0.0
        data_freezed = True  # whether data is freezed
        last_in_garage = False
        last_slot_id = INVALID_INDEX
        reset_counter = 0
        update_delay = 0.5  # longer delay while inactive

        while not _event_wait(update_delay):
            self.dataset.update_mmap()
            session_timestamp = self.dataset.shmm.data.scoring.scoringInfo.mCurrentET
            if session_timestamp < last_session_timestamp:  # session changed: forget slot ids of previous session
                self._tele_indexes = default_tele_indexes()
            self.__update_tele_indexes(self.dataset.shmm.data.telemetry, self._tele_indexes)

            # Update player data & index
            if not data_freezed:
                # Get player data
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
                if self.results.timestamp != session_timestamp:
                    if self.results.timestamp > session_timestamp:
                        self.results.data.clear()
                    self.results.timestamp = session_timestamp
                    self.results.update(self.dataset.shmm.data.scoring.scoringStream)

            if last_session_timestamp != session_timestamp:
                in_garage = self.player_scor.mInGarageStall
                slot_id = self.player_scor.mID
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
                freezed_timestamp = last_session_timestamp
                logger.info(
                    "sharedmemory: UPDATING: paused, data timestamp %s",
                    freezed_timestamp,
                )

        logger.info("sharedmemory: UPDATING: thread stopped")


class LMUInfo:
    """LMU shared memory data output"""

    __slots__ = (
        "_sync",
        "_access_mode",
        "_state_override",
        "_active_state",
        "_shmm",
        "_live_shmm",
    )

    def __init__(self) -> None:
        self._sync = SyncData()
        self._live_shmm = self._sync.dataset.shmm
        self._access_mode = 0
        self._state_override = False
        self._active_state = False
        # Assign mmap instance
        self._shmm = self._sync.dataset.shmm

    def __del__(self):
        if logger is not None:  # module globals are cleared at interpreter exit
            logger.info("sharedmemory: GC: LMUInfo")

    def start(self) -> None:
        """Start data updating thread"""
        self._sync.start(self._access_mode)

    def stop(self) -> None:
        """Stop data updating thread"""
        self._sync.stop()

    def setMode(self, mode: int = 0) -> None:
        """Set LMU mmap access mode

        Args:
            mode: 0 = copy access, 1 = direct access
        """
        self._access_mode = mode

    def setReplay(self, player: ReplayPlayer | None = None, rest_target: Any = None) -> None:
        """Read frames from replay player, or live shared memory if None. Call before start()"""
        if player is None:
            shmm: Any = self._live_shmm
        else:
            shmm = ReplayMMap(lmu_data.LMUObjectOut, player, player.replay.zone_offset("shmm"), rest_target)
        self._sync.dataset.shmm = shmm
        self._shmm = shmm

    @property
    def rawData(self) -> Any:
        """Raw shared memory structure"""
        return self._shmm.data

    def setStateOverride(self, state: bool = False) -> None:
        """Enable state override"""
        self._state_override = state

    def setActiveState(self, state: bool = False) -> None:
        """Set state override"""
        self._active_state = state

    def setPlayerOverride(self, state: bool = False) -> None:
        """Enable player index override state"""
        self._sync.override_player_index = state

    def setPlayerIndex(self, index: int = INVALID_INDEX) -> None:
        """Manual override player index"""
        self._sync.player_slot_id = max(index, INVALID_INDEX)

    @property
    def lmuScorInfo(self) -> lmu_data.LMUScoringInfo:
        """LMU scoring info data"""
        return self._shmm.data.scoring.scoringInfo

    def lmuResults(self, index: int | None = INVALID_INDEX) -> dict[str, float]:
        """LMU results data"""
        if index is None:
            data = self._sync.player_scor
        else:
            data = self._shmm.data.scoring.vehScoringInfo[index]
        return self._sync.results.data.get(data.mDriverName, LMUResults.DEFAULT)

    def lmuScorVeh(self, index: int | None = None) -> lmu_data.LMUVehicleScoring:
        """LMU scoring vehicle data

        Specify index for specific player.

        Args:
            index: None for local player.
        """
        if index is None:
            return self._sync.player_scor
        return self._shmm.data.scoring.vehScoringInfo[index]

    def lmuTeleVeh(self, index: int | None = None) -> lmu_data.LMUVehicleTelemetry:
        """LMU telemetry vehicle data

        Specify index for specific player.

        Args:
            index: None for local player.
        """
        if index is None:
            return self._sync.player_tele
        return self._shmm.data.telemetry.telemInfo[self._sync.sync_tele_index(index)]

    @property
    def lmuGeneric(self) -> lmu_data.LMUGeneric:
        """LMU generic data"""
        return self._shmm.data.generic

    @property
    def playerIndex(self) -> int:
        """Local player's scoring index"""
        return self._sync.player_scor_index

    @property
    def isPaused(self) -> bool:
        """Check whether data stopped updating"""
        return self._sync.paused #or self._sync.player_scor_index < 0

    @property
    def isActive(self) -> bool:
        """Check whether in active (driving or overriding) state"""
        if self._state_override:
            return self._active_state
        return self._sync.synced and self._sync.player_scor_index >= 0 and (
            self.lmuScorInfo.mInRealtime
            or self.lmuTeleVeh().mIgnitionStarter > 0
        )

    @property
    def vehicleResets(self) -> int:
        """Number of player vehicle resets"""
        return self._sync.resets

    @property
    def dataAge(self) -> float:
        """Seconds since game data last changed, -1 if never"""
        if self._sync.last_update <= 0:
            return -1.0
        return monotonic() - self._sync.last_update

    @property
    def openError(self) -> str:
        """Why shared memory could not be opened, empty if opened"""
        return self._sync.error
