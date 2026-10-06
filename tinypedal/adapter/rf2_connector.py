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
rF2 API connector
"""

from __future__ import annotations

import ctypes
import logging
import threading
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

from .. import app_signal
from ..replay import ReplayMMap, ReplayPlayer
from ..thread_guard import run_supervised

logger = logging.getLogger(__name__)
STOP_TIMEOUT = 3.0  # seconds to wait for update thread to stop
# Vehicle wrappers & scoring to telemetry index map of no data structure
NO_ROWS: tuple = (None, ())
NO_TELE_MAP: tuple = (None, None, ())
# Zeroed telemetry of vehicle without telemetry match (never another car's data)
EMPTY_TELE: Any = rf2_struct.rF2VehicleTelemetry()

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


def default_tele_indexes() -> dict[int, int]:
    """Telemetry index of slot id, before any match (none: unknown slot id has no telemetry)"""
    return {}


def copy_struct(struct_data):
    """Allow to copy ctypes struct data with __slots__"""
    return type(struct_data).from_buffer_copy(
        ctypes.string_at(
            ctypes.byref(struct_data),
            ctypes.sizeof(struct_data),
        )
    )


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

    def __del__(self):
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

    def update_mmap(self) -> None:
        """Update mmap data"""
        self.scor.update()
        self.tele.update()
        if self.replaying:  # live ext, ffb & rule use direct access, replay copies every zone
            self.ext.update()
            self.ffb.update()
            self.rule.update()

    def zones(self) -> tuple:
        """Mmap instances in replay frame order"""
        return self.scor, self.tele, self.ext, self.ffb, self.rule

    def set_zones(self, zones: tuple, replaying: bool) -> None:
        """Replace mmap instances (replay or live)"""
        self.scor, self.tele, self.ext, self.ffb, self.rule = zones
        self.replaying = replaying


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
        tele_map: (scoring data, telemetry data, telemetry index per scoring index of vehicles in session),
            rebuilt every update tick.
    """

    __slots__ = (
        "_updating",
        "_update_thread",
        "_event",
        "_tele_indexes",
        "_scor_rows",
        "_tele_rows",
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

    def __init__(self) -> None:
        self._updating = False
        self._update_thread: threading.Thread | None = None
        self._event = threading.Event()
        self._tele_indexes = default_tele_indexes()
        self._scor_rows = NO_ROWS
        self._tele_rows = NO_ROWS
        self.tele_map = NO_TELE_MAP

        self.paused = False
        self.synced = False
        self.resets = 0
        self.override_player_index = False
        self.player_slot_id = INVALID_INDEX
        self.player_scor_index = INVALID_INDEX
        self.player_scor: Any = None  # set by sync before use
        self.player_tele: Any = None
        self.dataset = MMapDataSet()
        self.error = ""
        self.last_update = 0.0

    def __del__(self):
        if logger is not None:  # module globals are cleared at interpreter exit
            logger.info("sharedmemory: GC: SyncData")

    def __sync_player_scor(self, scor_index: int = INVALID_INDEX) -> None:
        """Sync local player vehicle scoring data"""
        self.player_scor = self.dataset.scor.data.mVehicles[scor_index]

    def __sync_player_tele(self, tele_index: int = INVALID_INDEX) -> None:
        """Sync local player vehicle telemetry data, zeroed if no telemetry index"""
        if tele_index < 0:
            self.player_tele = EMPTY_TELE
        else:
            self.player_tele = self.dataset.tele.data.mVehicles[tele_index]

    def __sync_player_data(self) -> bool:
        """Sync local player data

        Returns:
            False, if no valid player scoring index found.
            True, set player data.
        """
        # Update scoring index
        scoring = self.dataset.scor.data
        if self.override_player_index:
            scor_idx = local_scoring_index_by_id(
                self.player_slot_id, scoring.mVehicles, scoring.mScoringInfo.mNumVehicles)
        else:
            scor_idx = local_scoring_index(scoring.mVehicles, scoring.mScoringInfo.mNumVehicles)
        if scor_idx == INVALID_INDEX:
            return False  # index not found, not synced
        self.player_scor_index = scor_idx
        # Set player data
        self.__sync_player_scor(self.player_scor_index)
        self.__sync_player_tele(self.sync_tele_index(self.player_scor_index))
        return True  # found index, synced

    @staticmethod
    def __update_tele_indexes(veh_total: int, tele_data: rF2data.rF2Telemetry, tele_indexes: dict) -> None:
        """Update telemetry player index dictionary for quick reference

        Telemetry index can be different from scoring index.
        Use mID matching to match telemetry index.

        Args:
            tele_data: Telemetry data.
            tele_indexes: Telemetry mID:index reference dictionary.
        """
        for tele_idx, veh_info in zip(range(veh_total), tele_data.mVehicles):
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
        """Map telemetry index of every scoring index in session, once per update tick"""
        scor_data = self.dataset.scor.data
        get_index = self._tele_indexes.get
        veh_total = min(max(scor_data.mScoringInfo.mNumVehicles, 0), MAX_VEHICLES)
        self.tele_map = (scor_data, self.dataset.tele.data, tuple(
            get_index(veh_info.mID, INVALID_INDEX) for veh_info in self.scoring_rows(scor_data)[:veh_total]))

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
            self.__set_unavailable(error)
            return
        self.error = ""
        self._updating = True
        self._tele_indexes = default_tele_indexes()
        self.__update_tele_indexes(
            self.dataset.tele.data.mNumVehicles,
            self.dataset.tele.data,
            self._tele_indexes,
        )
        self.__update_tele_map()
        if not self.__sync_player_data():
            self.__sync_player_scor()
            self.__sync_player_tele()
        # Setup updating thread, own stop event for each thread (a previous thread still stopping never resumes)
        self._event = threading.Event()
        self._update_thread = threading.Thread(
            target=self.__update, args=(self._event,), daemon=True, name="rF2 shared memory")
        self._update_thread.start()
        logger.info("sharedmemory: UPDATING: thread started")
        logger.info("sharedmemory: player index override: %s", self.override_player_index)
        logger.info("sharedmemory: server process ID: %s", rf2_pid if rf2_pid else "DISABLED")

    def __set_unavailable(self, error: Exception) -> None:
        """Not connected state: zeroed data, paused, no updating thread"""
        self.error = str(error)
        logger.error(
            "sharedmemory: unable to open rF2 shared memory (%s): %s. Shared memory may exist with another size "
            "(other telemetry tool or older plugin running), restart game & close other tools.",
            ", ".join(f"{name} {size} bytes" for name, size in replay_layout()), error,
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
                if self._update_thread.is_alive():  # exits on its own event, close only makes its reads fail
                    logger.warning("sharedmemory: UPDATING: thread still stopping in background")
            # Make final copy before close, otherwise mmap won't close if using direct access
            if self.player_scor is not None:
                self.player_scor = copy_struct(self.player_scor)
            if self.player_tele is not None:
                self.player_tele = copy_struct(self.player_tele)
            self._scor_rows = self._tele_rows = NO_ROWS  # release wrappers of mmap data
            self.tele_map = NO_TELE_MAP
            self.dataset.close_mmap()
        else:
            logger.warning("sharedmemory: UPDATING: already stopped")

    def __update(self, event: threading.Event) -> None:
        """Run update loop, restart after unexpected error"""
        if not run_supervised(lambda: self.__update_loop(event), "sharedmemory (rF2) update", event) and not event.is_set():
            # Stopped after repeated errors: hide overlays instead of showing frozen values
            self.paused = True
            self.synced = False

    def __update_loop(self, event: threading.Event) -> None:
        """Update synced player data"""
        self.paused = False  # make sure initial pause state is false
        self.synced = False
        self.resets = 0

        _event_wait = event.wait
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
            session_timestamp = self.dataset.scor.data.mScoringInfo.mCurrentET
            if session_timestamp < last_session_timestamp:  # session changed: forget slot ids of previous session
                self._tele_indexes = default_tele_indexes()
            self.__update_tele_indexes(
                self.dataset.tele.data.mNumVehicles,
                self.dataset.tele.data,
                self._tele_indexes,
            )
            self.__update_tele_map()

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

    def __del__(self):
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
