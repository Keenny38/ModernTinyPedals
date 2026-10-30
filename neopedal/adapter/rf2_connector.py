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
rF2 API connector
"""

from __future__ import annotations

import ctypes
import logging
from collections.abc import Sequence
from contextlib import suppress
from time import monotonic
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:  # for type checker only
    from pyRfactor2SharedMemory import rF2Type as rF2data
else:  # run time only
    from pyRfactor2SharedMemory import rF2data

from pyRfactor2SharedMemory import rF2data as rf2_struct  # ctypes structures (rF2data is typed view)
from pyRfactor2SharedMemory.rF2MMap import (
    INVALID_INDEX,
    MAX_VEHICLES,
    MMapControl,
    rFactor2Constants,
)

from ..replay import ReplayMMap, ReplayPlayer
from . import _sync
from ._sync import copy_struct as copy_struct  # re-exported
from ._sync import default_tele_indexes as default_tele_indexes  # re-exported

logger = logging.getLogger(__name__)
# Vehicle wrappers & scoring to telemetry index map of no data structure
NO_ROWS: tuple = (None, ())
NO_TELE_MAP: tuple = (None, None, ())
# Zeroed telemetry of vehicle without telemetry match (never another car's data)
EMPTY_TELE: Any = rf2_struct.rF2VehicleTelemetry()
# Zeroed scoring of player while not synced (never the last slot of the array, stale in a dense session)
EMPTY_SCOR: Any = rf2_struct.rF2VehicleScoring()

# Shared memory zones recorded in replay frame, in order: (name, structure)
REPLAY_ZONES: tuple[tuple[str, Any], ...] = (
    ("scor", rF2data.rF2Scoring),
    ("tele", rF2data.rF2Telemetry),
    ("ext", rF2data.rF2Extended),
    ("ffb", rF2data.rF2ForceFeedback),
    ("rule", rF2data.rF2Rules),
)


def replay_layout() -> list[list]:
    """Replay zone layout: [name, size], ..."""
    return [[name, ctypes.sizeof(data_struct)] for name, data_struct in REPLAY_ZONES]


def local_scoring_index(scor_veh: Sequence[rF2data.rF2VehicleScoring], veh_total: int = MAX_VEHICLES) -> int:
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
    slot_id: int, scor_veh: Sequence[rF2data.rF2VehicleScoring], veh_total: int = MAX_VEHICLES) -> int:
    """Find local player scoring index by slot id

    Args:
        scor_veh: scoring array.
        veh_total: number of vehicles in session (slots beyond may be stale).
    """
    for scor_idx, veh_info in zip(range(min(veh_total, MAX_VEHICLES)), scor_veh):
        if veh_info.mID == slot_id:
            return scor_idx
    return INVALID_INDEX


class MMapDataSet:
    """Create mmap data set"""

    __slots__ = (
        "scor",
        "tele",
        "ext",
        "ffb",
        "rule",
        "live",
        "replaying",
    )

    def __init__(self) -> None:
        self.scor = MMapControl(rFactor2Constants.MM_SCORING_FILE_NAME, rF2data.rF2Scoring)
        self.tele = MMapControl(rFactor2Constants.MM_TELEMETRY_FILE_NAME, rF2data.rF2Telemetry)
        self.ext = MMapControl(rFactor2Constants.MM_EXTENDED_FILE_NAME, rF2data.rF2Extended)
        self.ffb = MMapControl(rFactor2Constants.MM_FORCE_FEEDBACK_FILE_NAME, rF2data.rF2ForceFeedback)
        self.rule = MMapControl(rFactor2Constants.MM_RULES_FILE_NAME, rF2data.rF2Rules)
        self.live = (self.scor, self.tele, self.ext, self.ffb, self.rule)
        self.replaying = False

    def __del__(self) -> None:
        if logger is not None:  # module globals are cleared at interpreter exit
            logger.info("sharedmemory: GC: MMapDataSet")

    def create_mmap(self, access_mode: int, rf2_pid: str) -> None:
        """Create mmap instance

        Args:
            access_mode: 0 = copy access, 1 = direct access.
            rf2_pid: rF2 Process ID for accessing server data.
        """
        created = []
        try:
            for zone, mode in (
                (self.scor, access_mode),
                (self.tele, access_mode),
                (self.ext, 1),
                (self.ffb, 1),
                (self.rule, 1),
            ):
                zone.create(mode, rf2_pid)
                created.append(zone)
        except (OSError, ValueError):  # close zones already opened, nothing left half open
            for zone in created:
                with suppress(OSError, ValueError, TypeError):
                    zone.close()
            raise

    def set_unavailable(self) -> None:
        """Zeroed data while shared memory cannot be opened (not connected state)"""
        for zone, (_, data_struct) in zip(self.zones(), REPLAY_ZONES):
            zone.data = data_struct()

    def replay_paused(self) -> bool:
        """Whether replay player is paused: frame held on purpose, not a frozen game"""
        return self.replaying and bool(getattr(self.scor, "paused", False))

    def close_mmap(self) -> None:
        """Close mmap instance"""
        self.scor.close()
        self.tele.close()
        self.ext.close()
        self.ffb.close()
        self.rule.close()

    def update_mmap(self) -> bool | None:
        """Update mmap data

        Returns:
            True if scoring or telemetry copy updated, False if neither (copies unchanged),
            None if unknown (direct access, replay).
        """
        scor_copied = self.scor.update()
        tele_copied = self.tele.update()
        if self.replaying:  # live ext, ffb & rule use direct access, replay copies every zone
            self.ext.update()
            self.ffb.update()
            self.rule.update()
        if scor_copied is None or tele_copied is None:
            return None
        return scor_copied or tele_copied

    def zones(self) -> tuple:
        """Mmap instances in replay frame order"""
        return self.scor, self.tele, self.ext, self.ffb, self.rule

    def set_zones(self, zones: tuple, replaying: bool) -> None:
        """Replace mmap instances (replay or live)"""
        self.scor, self.tele, self.ext, self.ffb, self.rule = zones
        self.replaying = replaying


class SyncData(_sync.SyncData):
    """Synchronize data with player ID (rF2 shared memory, see _sync.SyncData)

    Attributes:
        tele_map: (scoring data, telemetry data, telemetry index per scoring index of vehicles in session),
            rebuilt on update tick with new data once index key changed.
    """

    THREAD_NAME = "rF2 shared memory"
    SUPERVISED_NAME = "sharedmemory (rF2) update"
    NO_TELE_MAP = NO_TELE_MAP
    __slots__ = (
        "_scor_rows",
        "_tele_rows",
    )

    def __init__(self) -> None:
        super().__init__(MMapDataSet())
        self._scor_rows = NO_ROWS
        self._tele_rows = NO_ROWS

    def __sync_player_scor(self, scor_index: int = INVALID_INDEX) -> None:
        """Sync local player vehicle scoring data, zeroed if no scoring index (cached wrapper otherwise)"""
        if scor_index < 0:
            self.player_scor = EMPTY_SCOR
        else:
            self.player_scor = self.scoring_rows(self.dataset.scor.data)[scor_index]

    def __sync_player_tele(self, tele_index: int = INVALID_INDEX) -> None:
        """Sync local player vehicle telemetry data, zeroed if no telemetry index (cached wrapper otherwise)"""
        if tele_index < 0:
            self.player_tele = EMPTY_TELE
        else:
            self.player_tele = self.telemetry_rows(self.dataset.tele.data)[tele_index]

    def _player_scoring_index(self) -> int:
        """Scoring index of local player (or player index override), from cached vehicle wrappers
        (same data as scoring array); last index checked first, it rarely changes between ticks"""
        scoring = self.dataset.scor.data
        veh_total = min(scoring.mScoringInfo.mNumVehicles, MAX_VEHICLES)
        scor_rows = self.scoring_rows(scoring)
        last_index = self.player_scor_index
        if 0 <= last_index < veh_total:
            last_row = scor_rows[last_index]
            if (last_row.mID == self.player_slot_id) if self.override_player_index else last_row.mIsPlayer:
                return last_index
        if self.override_player_index:
            return local_scoring_index_by_id(self.player_slot_id, scor_rows, veh_total)
        return local_scoring_index(scor_rows, veh_total)

    @staticmethod
    def __update_tele_indexes(
        veh_total: int, tele_data: rF2data.rF2Telemetry, tele_indexes: dict, tele_rows: Sequence | None = None,
    ) -> None:
        """Update telemetry player index dictionary for quick reference

        Telemetry index can be different from scoring index.
        Use mID matching to match telemetry index.
        Slot ids no longer in telemetry are dropped (a departed car's index may now be another car's).
        Updated in place, current slot ids never missing while other threads read it.

        Args:
            tele_data: Telemetry data.
            tele_indexes: Telemetry mID:index reference dictionary.
            tele_rows: cached telemetry vehicle wrappers of tele_data (telemetry_rows), telemetry array if None.
        """
        vehicles = tele_data.mVehicles if tele_rows is None else tele_rows
        current = {veh_info.mID: tele_idx for tele_idx, veh_info in zip(range(veh_total), vehicles)}
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
            self.scoring_rows(self.dataset.scor.data)[scor_idx].mID, INVALID_INDEX)

    def scoring_rows(self, data: Any) -> tuple:
        """Scoring vehicle wrappers of scoring data structure, created once per structure

        Mmap data copy (and replay frame) is updated in place, wrappers stay valid
        until data structure is replaced (start, close, replay, not connected).
        """
        rows = self._scor_rows
        if rows[0] is not data:
            rows = self._scor_rows = (data, tuple(data.mVehicles))
        return rows[1]

    def telemetry_rows(self, data: Any) -> tuple:
        """Telemetry vehicle wrappers of telemetry data structure, created once per structure"""
        rows = self._tele_rows
        if rows[0] is not data:
            rows = self._tele_rows = (data, tuple(data.mVehicles))
        return rows[1]

    def __update_tele_map(self) -> None:
        """Map telemetry index of every scoring index in session, on update tick once index key changed"""
        scor_data = self.dataset.scor.data
        get_index = self._tele_indexes.get
        veh_total = min(max(scor_data.mScoringInfo.mNumVehicles, 0), MAX_VEHICLES)
        self.tele_map = (scor_data, self.dataset.tele.data, tuple(
            get_index(veh_info.mID, INVALID_INDEX) for veh_info in self.scoring_rows(scor_data)[:veh_total]))

    def _index_key(self) -> tuple:
        """Scoring sample time & vehicle counts, see _sync.SyncData._index_key"""
        scor_info = self.dataset.scor.data.mScoringInfo
        return scor_info.mCurrentET, scor_info.mNumVehicles, self.dataset.tele.data.mNumVehicles

    def _update_indexes(self) -> None:
        """Update telemetry indexes of slot ids & telemetry map from current data"""
        tele_data = self.dataset.tele.data
        self.__update_tele_indexes(
            tele_data.mNumVehicles,
            tele_data,
            self._tele_indexes,
            self.telemetry_rows(tele_data),
        )
        self.__update_tele_map()

    def _read_data(self) -> tuple[Any, bool]:
        """(scoring info, scoring or telemetry data structure replaced since last call) of tick"""
        dataset = self.dataset
        scor_data = dataset.scor.data
        tele_data = dataset.tele.data
        last = self._last_data
        if last is not None and last[0] is scor_data and last[1] is tele_data:
            return scor_data.mScoringInfo, False
        self._last_data = (scor_data, tele_data)
        return scor_data.mScoringInfo, True

    def _release_rows(self) -> None:
        """Forget vehicle wrappers of mmap data (before close)"""
        self._scor_rows = self._tele_rows = NO_ROWS

    def _log_unavailable(self, error: Exception) -> None:
        """Log shared memory open error"""
        logger.error(
            "sharedmemory: unable to open rF2 shared memory (%s): %s. Shared memory may exist with another size "
            "(other telemetry tool or older plugin running), restart game & close other tools.",
            ", ".join(f"{name} {size} bytes" for name, size in replay_layout()), error,
        )

    def start(self, access_mode: int, rf2_pid: str) -> None:
        """Update & sync mmap data copy in separate thread

        Args:
            access_mode: 0 = copy access, 1 = direct access.
            rf2_pid: rF2 Process ID for accessing server data.
        """
        if self._updating:
            logger.warning("sharedmemory: UPDATING: already started")
            return
        # Initialize mmap data
        try:
            self.dataset.create_mmap(access_mode, rf2_pid)
        except (OSError, ValueError) as error:  # existing mapping of another size (other tool, older plugin)
            self._set_unavailable(error)
            return
        self._start_updating()
        logger.info("sharedmemory: server process ID: %s", rf2_pid if rf2_pid else "DISABLED")


class RF2Info:
    """RF2 shared memory data output"""

    __slots__ = (
        "_sync",
        "_access_mode",
        "_rf2_pid",
        "_state_override",
        "_active_state",
        "_scor",
        "_tele",
        "_ext",
        "_ffb",
        "_rule",
    )

    def __init__(self) -> None:
        self._sync = SyncData()
        self._access_mode = 0
        self._rf2_pid = ""
        self._state_override = False
        self._active_state = False
        # Assign mmap instance
        self._scor = self._sync.dataset.scor
        self._tele = self._sync.dataset.tele
        self._ext = self._sync.dataset.ext
        self._ffb = self._sync.dataset.ffb
        self._rule = self._sync.dataset.rule

    def __del__(self) -> None:
        if logger is not None:  # module globals are cleared at interpreter exit
            logger.info("sharedmemory: GC: RF2Info")

    def start(self) -> None:
        """Start data updating thread"""
        self._sync.start(self._access_mode, self._rf2_pid)

    def setReplay(self, player: ReplayPlayer | None = None, rest_target: Any = None) -> None:
        """Read frames from replay player, or live shared memory if None. Call before start()"""
        dataset = self._sync.dataset
        if player is None:
            dataset.set_zones(dataset.live, False)
        else:
            zones = []
            for name, data_struct in REPLAY_ZONES:
                zones.append(ReplayMMap(
                    data_struct, player, player.replay.zone_offset(name), rest_target if name == "scor" else None,
                    primary=name == "scor"))  # scoring updated first
            dataset.set_zones(tuple(zones), True)
        self._scor, self._tele, self._ext, self._ffb, self._rule = dataset.zones()

    @property
    def rawData(self) -> bytes | None:
        """Every shared memory zone back to back, for replay recording, None before shared memory opened"""
        zones = self._sync.dataset.zones()
        if any(zone.data is None for zone in zones):
            return None
        return b"".join(bytes(zone.data) for zone in zones)

    def stop(self) -> None:
        """Stop data updating thread"""
        self._sync.stop()

    def request_stop(self) -> None:
        """Signal data updating thread to stop, see SyncData.request_stop (threads of an API stop in parallel)"""
        self._sync.request_stop()

    def wait_stopped(self, timeout: float = _sync.STOP_TIMEOUT, deadline: float | None = None) -> bool:
        """Wait for signalled data updating thread & close mmap, see SyncData.wait_stopped"""
        return self._sync.wait_stopped(timeout, deadline)

    def setPID(self, pid: str = "") -> None:
        """Set rF2 process ID for connecting to server data"""
        self._rf2_pid = str(pid)

    def setMode(self, mode: int = 0) -> None:
        """Set rF2 mmap access mode

        Args:
            mode: 0 = copy access, 1 = direct access
        """
        self._access_mode = mode

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
    def rf2ScorInfo(self) -> rF2data.rF2ScoringInfo:
        """rF2 scoring info data"""
        return self._scor.data.mScoringInfo

    def rf2ScorVeh(self, index: int | None = None) -> rF2data.rF2VehicleScoring:
        """rF2 scoring vehicle data

        Specify index for specific player.

        Args:
            index: None for local player.
        """
        if index is None:
            return self._sync.player_scor
        return self._sync.scoring_rows(self._scor.data)[index]

    def rf2TeleVeh(self, index: int | None = None) -> rF2data.rF2VehicleTelemetry:
        """rF2 telemetry vehicle data

        Specify index for specific player.

        Args:
            index: None for local player.
        """
        if index is None:
            return self._sync.player_tele
        sync = self._sync
        tele_data = self._tele.data
        tele_rows = sync.telemetry_rows(tele_data)
        map_scor, map_tele, tele_map = sync.tele_map
        if map_tele is tele_data and map_scor is self._scor.data and 0 <= index < len(tele_map):
            tele_index = tele_map[index]
        else:
            tele_index = sync.sync_tele_index(index)  # not mapped: match now
        if tele_index < 0:  # no telemetry of vehicle (yet): zeroed, never another car's data
            return EMPTY_TELE
        return tele_rows[tele_index]

    @property
    def rf2Ext(self) -> rF2data.rF2Extended:
        """rF2 extended data"""
        return cast(rF2data.rF2Extended, self._ext.data)

    @property
    def rf2Ffb(self) -> rF2data.rF2ForceFeedback:
        """rF2 force feedback data"""
        return cast(rF2data.rF2ForceFeedback, self._ffb.data)

    @property
    def rf2Rule(self) -> rF2data.rF2Rules:
        """rF2 Rules info data"""
        return cast(rF2data.rF2Rules, self._rule.data)

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
            self.rf2ScorInfo.mInRealtime
            or self.rf2TeleVeh().mIgnitionStarter > 0
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
