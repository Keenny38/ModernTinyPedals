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
LMU API connector
"""

from __future__ import annotations

import ctypes
import html
import logging
import re
from collections.abc import Mapping, Sequence
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
    MAX_VEHICLES,
    LMUConstants,
    MMapControl,
)

from ..penalty_info import NO_PENALTY, Penalty
from ..penalty_info import apply_line as apply_penalty_line
from ..penalty_info import parse_line as parse_penalty_line
from ..replay import ReplayMMap, ReplayPlayer
from . import _sync
from ._sync import default_tele_indexes as default_tele_indexes  # re-exported

logger = logging.getLogger(__name__)

# Enum map
LMU_COMPOUND_TYPE = lmu_enum.enum_map(lmu_enum.LMUCompoundType)
# Vehicle wrappers & scoring to telemetry index map of no data structure
NO_ROWS: tuple = (None, (), ())
NO_TELE_MAP: tuple = (None, ())
# Zeroed telemetry of vehicle without telemetry match (never another car's data)
EMPTY_TELE: Any = lmu_struct.LMUVehicleTelemetry()


def local_scoring_index(scor_veh: Sequence[lmu_data.LMUVehicleScoring], veh_total: int = MAX_VEHICLES) -> int:
    """Find local player scoring index

    Args:
        scor_veh: scoring vehicle array.
        veh_total: number of vehicles in session (slots beyond may be stale).
    """
    for scor_idx, veh_info in zip(range(min(veh_total, MAX_VEHICLES)), scor_veh):
        if veh_info.mIsPlayer:
            return scor_idx
    return INVALID_INDEX


def local_scoring_index_by_id(
    slot_id: int, scor_veh: Sequence[lmu_data.LMUVehicleScoring], veh_total: int = MAX_VEHICLES) -> int:
    """Find local player scoring index by slot id

    Args:
        scor_veh: scoring array.
        veh_total: number of vehicles in session (slots beyond may be stale).
    """
    for scor_idx, veh_info in zip(range(min(veh_total, MAX_VEHICLES)), scor_veh):
        if veh_info.mID == slot_id:
            return scor_idx
    return INVALID_INDEX


# "<Incident et="120.0">Name (FR)(12) reported contact ..." (name may contain parenthesis)
INCIDENT_DRIVER = re.compile(rb">(.+?)\(\d+\) reported contact")
DRIVER_NAME_SIZE = lmu_struct.LMUVehicleScoring.mDriverName.size  # bytes of shared memory name, with NUL


def unescape_name(name: bytes) -> bytes:
    """Decode XML entities (&amp;, &apos;...) in driver name, keep other bytes unchanged"""
    if b"&" not in name:
        return name
    return html.unescape(name.decode("utf-8", "surrogateescape")).encode("utf-8", "surrogateescape")


class LMUResults:
    """LMU results data (extracted from results stream)"""

    DEFAULT = MappingProxyType({
        "contact_vehicle": 0,
        "contact_immovable": 0,
        "track_cut": 0,
    })
    __slots__ = (
        "data",
        "penalties",
        "timestamp",
        "_last_stream",
        "_full_names",
    )

    def __init__(self) -> None:
        self.data: dict[bytes, dict[str, int]] = {}
        self.penalties: dict[bytes, Penalty] = {}  # driver name: penalties to serve, added, disqualified
        self.timestamp = 0
        self._last_stream = b""
        # (table is penalties, cut name): full name matched by start, None if no or several matches.
        # Replaced (never mutated) after driver names change, so a lookup of old names is never kept
        self._full_names: dict[tuple[bool, bytes], bytes | None] = {}

    def find(self, table: dict, driver: bytes, default: Any) -> Any:
        """Value of driver, shared memory name cut to field size: matched by start of full name

        Cut name shared by several full names: default (never another driver's value).
        """
        data = table.get(driver)
        if data is not None:
            return data
        if driver and len(driver) >= DRIVER_NAME_SIZE - 1:  # bytes compared: cut may split a character
            full_names = self._full_names  # lookup stored in the cache of the names it was made from
            key = (table is self.penalties, driver)
            if key in full_names:
                full_name = full_names[key]
            else:
                full_name = None
                for name in tuple(table):  # copy: stream thread may add drivers
                    if name.startswith(driver):
                        if full_name is not None:  # ambiguous: several drivers share the cut name
                            full_name = None
                            break
                        full_name = name
                full_names[key] = full_name
            if full_name is not None:
                return table.get(full_name, default)
        return default

    def get(self, driver: bytes) -> Mapping[str, float]:
        """Results of driver"""
        return self.find(self.data, driver, self.DEFAULT)

    def penalty(self, driver: bytes) -> Penalty:
        """Penalties of driver (to serve, added time, disqualified)"""
        return self.find(self.penalties, driver, NO_PENALTY)

    def clear(self) -> None:
        """Forget drivers of previous session"""
        self.data.clear()
        self.penalties.clear()
        self._full_names = {}

    def check_missing(self, driver: bytes) -> None:
        """Check & add missing driver"""
        if driver not in self.data:
            self.data[driver] = self.DEFAULT.copy()

    def update(self, stream: bytes) -> None:
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
                matched = INCIDENT_DRIVER.search(line)
                if matched:
                    driver = unescape_name(matched.group(1))
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
                    driver = unescape_name(line[pos_beg:pos_end])
                    self.check_missing(driver)
                    results_data[driver]["track_cut"] += 1
                continue
            # Log penalties: received, served, added at finish, disqualified
            if line.startswith(b"<Penalty"):
                parsed = parse_penalty_line(line)
                if parsed is not None:
                    driver, state, added, disqualified = parsed
                    self.penalties[driver] = apply_penalty_line(
                        self.penalties.get(driver, NO_PENALTY), state, added, disqualified)
        self._full_names = {}  # driver names may have changed


class MMapDataSet:
    """Create mmap data set"""

    __slots__ = (
        "shmm",
    )

    def __init__(self) -> None:
        self.shmm = MMapControl(LMUConstants.LMU_SHARED_MEMORY_FILE, lmu_data.LMUObjectOut)

    def __del__(self) -> None:
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

    def update_mmap(self) -> bool | None:
        """Update mmap data

        Returns:
            True if data copy updated, False if no new data (copy unchanged), None if unknown (direct access, replay).
        """
        return self.shmm.update()

    def set_unavailable(self) -> None:
        """Zeroed data while shared memory cannot be opened (not connected state)"""
        self.shmm.data = lmu_struct.LMUObjectOut()

    def replay_paused(self) -> bool:
        """Whether replay player is paused: frame held on purpose, not a frozen game"""
        return bool(getattr(self.shmm, "paused", False))


class SyncData(_sync.SyncData):
    """Synchronize data with player ID (LMU shared memory, see _sync.SyncData)

    Attributes:
        results: data from result stream.
        tele_map: (data structure, telemetry index per scoring index of vehicles in session),
            rebuilt on update tick with new data once index key changed.
    """

    THREAD_NAME = "LMU shared memory"
    SUPERVISED_NAME = "sharedmemory (LMU) update"
    NO_TELE_MAP = NO_TELE_MAP
    __slots__ = (
        "_rows",
        "results",
    )

    def __init__(self) -> None:
        super().__init__(MMapDataSet())
        self._rows = NO_ROWS
        self.results = LMUResults()

    def __sync_player_scor(self, scor_index: int = INVALID_INDEX) -> None:
        """Sync local player vehicle scoring data"""
        self.player_scor = self.dataset.shmm.data.scoring.vehScoringInfo[scor_index]

    def __sync_player_tele(self, tele_index: int = INVALID_INDEX) -> None:
        """Sync local player vehicle telemetry data, zeroed if no telemetry index"""
        if tele_index < 0:
            self.player_tele = EMPTY_TELE
        else:
            self.player_tele = self.dataset.shmm.data.telemetry.telemInfo[tele_index]

    def _player_scoring_index(self) -> int:
        """Scoring index of local player (or player index override), from cached vehicle wrappers
        (same data as scoring array)"""
        data = self.dataset.shmm.data
        veh_total = data.scoring.scoringInfo.mNumVehicles
        scor_rows = self.vehicle_rows(data)[1]
        if self.override_player_index:
            return local_scoring_index_by_id(self.player_slot_id, scor_rows, veh_total)
        return local_scoring_index(scor_rows, veh_total)

    @staticmethod
    def __update_tele_indexes(
        tele_data: lmu_data.LMUTelemetryData, tele_indexes: dict, tele_rows: Sequence | None = None) -> None:
        """Update telemetry player index dictionary for quick reference

        Telemetry index can be different from scoring index.
        Use mID matching to match telemetry index.
        Only active telemetry entries are matched (scoring vehicle count can differ while game updates).
        Slot ids no longer in telemetry are dropped (a departed car's index may now be another car's).
        Updated in place, current slot ids never missing while other threads read it.

        Args:
            tele_data: Telemetry data.
            tele_indexes: Telemetry mID:index reference dictionary.
            tele_rows: cached telemetry vehicle wrappers of tele_data (vehicle_rows), telemetry array if None.
        """
        vehicles = tele_data.telemInfo if tele_rows is None else tele_rows
        current = {veh_info.mID: tele_idx for tele_idx, veh_info in zip(range(tele_data.activeVehicles), vehicles)}
        for slot_id in tele_indexes.keys() - current.keys():
            tele_indexes.pop(slot_id, None)
        tele_indexes.update(current)

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
            self.vehicle_rows(self.dataset.shmm.data)[1][scor_idx].mID, INVALID_INDEX)

    def vehicle_rows(self, data: Any) -> tuple:
        """Scoring & telemetry vehicle wrappers of data structure, created once per structure

        Mmap data copy (and replay frame) is updated in place, wrappers stay valid
        until data structure is replaced (start, close, replay, not connected).

        Returns:
            (data structure, scoring vehicles, telemetry vehicles).
        """
        rows = self._rows
        if rows[0] is not data:
            rows = self._rows = (data, tuple(data.scoring.vehScoringInfo), tuple(data.telemetry.telemInfo))
        return rows

    def __update_tele_map(self) -> None:
        """Map telemetry index of every scoring index in session, on update tick once index key changed"""
        data = self.dataset.shmm.data
        get_index = self._tele_indexes.get
        veh_total = min(max(data.scoring.scoringInfo.mNumVehicles, 0), MAX_VEHICLES)
        self.tele_map = (data, tuple(
            get_index(veh_info.mID, INVALID_INDEX) for veh_info in self.vehicle_rows(data)[1][:veh_total]))

    def _index_key(self) -> tuple:
        """Scoring sample time & vehicle counts, see _sync.SyncData._index_key"""
        data = self.dataset.shmm.data
        scor_info = data.scoring.scoringInfo
        return scor_info.mCurrentET, scor_info.mNumVehicles, data.telemetry.activeVehicles

    def _update_indexes(self) -> None:
        """Update telemetry indexes of slot ids & telemetry map from current data"""
        data = self.dataset.shmm.data
        self.__update_tele_indexes(data.telemetry, self._tele_indexes, self.vehicle_rows(data)[2])
        self.__update_tele_map()

    def _read_data(self) -> tuple[Any, bool]:
        """(scoring info, data structure replaced since last call) of tick"""
        data = self.dataset.shmm.data
        if data is self._last_data:
            return data.scoring.scoringInfo, False
        self._last_data = data
        return data.scoring.scoringInfo, True

    def _results_stream(self) -> bytes:
        """Results stream of current data"""
        return self.dataset.shmm.data.scoring.scoringStream

    def _release_rows(self) -> None:
        """Forget vehicle wrappers of mmap data (before close)"""
        self._rows = NO_ROWS

    def _log_unavailable(self, error: Exception) -> None:
        """Log shared memory open error"""
        logger.error(
            "sharedmemory: unable to open %s (%s bytes): %s. Shared memory may exist with another size "
            "(other telemetry tool or older plugin running), restart game & close other tools.",
            LMUConstants.LMU_SHARED_MEMORY_FILE, ctypes.sizeof(lmu_struct.LMUObjectOut), error,
        )

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
            self._set_unavailable(error)
            return
        self._start_updating()


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

    def __del__(self) -> None:
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

    def lmuPenalty(self, index: int | None = INVALID_INDEX) -> Penalty:
        """LMU penalties of vehicle from results stream"""
        if index is None:
            data = self._sync.player_scor
        else:
            data = self._shmm.data.scoring.vehScoringInfo[index]
        return self._sync.results.penalty(data.mDriverName)

    def lmuResults(self, index: int | None = INVALID_INDEX) -> Mapping[str, float]:
        """LMU results data"""
        if index is None:
            data = self._sync.player_scor
        else:
            data = self._shmm.data.scoring.vehScoringInfo[index]
        return self._sync.results.get(data.mDriverName)

    def lmuScorVeh(self, index: int | None = None) -> lmu_data.LMUVehicleScoring:
        """LMU scoring vehicle data

        Specify index for specific player.

        Args:
            index: None for local player.
        """
        if index is None:
            return self._sync.player_scor
        return self._sync.vehicle_rows(self._shmm.data)[1][index]

    def lmuTeleVeh(self, index: int | None = None) -> lmu_data.LMUVehicleTelemetry:
        """LMU telemetry vehicle data

        Specify index for specific player.

        Args:
            index: None for local player.
        """
        if index is None:
            return self._sync.player_tele
        data = self._shmm.data
        tele_rows = self._sync.vehicle_rows(data)[2]
        map_data, tele_map = self._sync.tele_map
        if map_data is data and 0 <= index < len(tele_map):
            tele_index = tele_map[index]
        else:
            tele_index = self._sync.sync_tele_index(index)  # not mapped: match now
        if tele_index < 0:  # no telemetry of vehicle (yet): zeroed, never another car's data
            return EMPTY_TELE
        return tele_rows[tele_index]

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
