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
API connector
"""

from __future__ import annotations

import ctypes
import logging
import os
from abc import ABC, abstractmethod
from functools import partial
from typing import TYPE_CHECKING, Any, ClassVar, NamedTuple

from pyLMUSharedMemory import lmu_data

from . import app_signal

# Import APIs
from .adapter import (
    APIDataReader,
    lmu_connector,
    lmu_reader,
    lmu_restapi,
    restapi_connector,
    rf2_connector,
    rf2_reader,
    rf2_restapi,
)
from .const_api import API_LMU_NAME, API_LMULEGACY_NAME, API_RF2_NAME
from .process.garage import reset_rf2_setup_parts
from .replay import ReplayPlayer, replay, replay_mismatch, rest_snapshot
from .validator import bytes_to_str

if TYPE_CHECKING:
    from .adapter.restapi_connector import EndpointStatus

logger = logging.getLogger(__name__)


class ConnectorHealth(NamedTuple):
    """Game data connection state, for performance monitor

    Attributes:
        data_age: seconds since shared memory data last changed, -1 if never.
        paused: shared memory data stopped updating.
        replaying: frames from replay file instead of game.
        error: why shared memory could not be opened, empty if opened.
        rest: Rest API status of each resource.
    """

    data_age: float
    paused: bool
    replaying: bool
    error: str
    rest: tuple[EndpointStatus, ...]


class Connector(ABC):
    """API Connector"""

    __slots__ = ()
    NAME: ClassVar[str]
    LEGACY: ClassVar[bool]

    @abstractmethod
    def start(self):
        """Start API & load info access function"""

    @abstractmethod
    def stop(self):
        """Stop API"""

    @abstractmethod
    def reader(self) -> APIDataReader:
        """Data reader"""

    @abstractmethod
    def setup(self, config: dict):
        """Setup API parameters"""

    def raw_data(self) -> Any:
        """Raw shared memory structure for replay recording, None if unsupported"""
        return None

    def rest_data(self) -> dict | None:
        """Rest API data snapshot for replay recording, None if unsupported"""
        return None

    def replay_layout(self) -> list[list]:
        """Shared memory zones of replay frame: [name, structure size], ..., empty if unsupported"""
        return []

    def replay_header(self) -> dict:
        """Replay file header: source API & shared memory zone layout"""
        return {"source": self.NAME, "layout": self.replay_layout()}

    def replay_player(self) -> ReplayPlayer | None:
        """Loaded replay player if API can play it, None to read game

        A replay this API cannot read (other API, other structure size) is unloaded,
        so switching API (hotkey, preset) falls back to game data instead of failing to start.
        """
        player = replay.player
        if player is None:
            return None
        mismatch = replay_mismatch(player.replay, self.NAME, self.replay_layout())
        if mismatch is None:
            return player
        logger.warning(
            "replay: %s not played with %s API: %s", os.path.basename(player.replay.filename), self.NAME, mismatch)
        replay.unload()
        app_signal.error.emit(f"Replay not compatible with {self.NAME} API, reading game data.")
        return None

    def health(self) -> ConnectorHealth:
        """Game data connection state"""
        return ConnectorHealth(-1.0, False, False, "", ())

    def close(self):
        """Dereference all instances"""
        name: str
        for cls in type(self).__mro__:  # slots of every class, subclass may add none
            for name in getattr(cls, "__slots__", ()):
                setattr(self, name, None)


class SimLMU(Connector):
    """Le Mans Ultimate - LMU Native Sharedmemory API"""

    __slots__ = (
        # Primary API
        "_shmmapi",
        "_replaying",
        # Secondary API
        "_restapi",
        "_restapi_dataset",
    )
    NAME = API_LMU_NAME
    LEGACY = False

    def __init__(self):
        self._shmmapi = lmu_connector.LMUInfo()
        self._replaying = False
        self._restapi_dataset = lmu_restapi.RestAPIData()
        self._restapi = restapi_connector.RestAPIConnector(lmu_restapi.lmu_restapi_tasks(), self._restapi_dataset)

    def start(self):
        player = self.replay_player()
        self._replaying = player is not None
        # Recorded frames & Rest API data instead of game
        self._shmmapi.setReplay(player, self._restapi_dataset)
        self._shmmapi.start()  # 1 load first
        if not self._replaying:
            self._restapi.start()  # 2

    def stop(self):
        if not self._replaying:
            self._restapi.stop()  # 1 unload first
        self._shmmapi.stop()  # 2

    def raw_data(self) -> Any:
        if self._replaying or self._shmmapi.isPaused:
            return None
        return self._shmmapi.rawData

    def rest_data(self) -> dict | None:
        if self._replaying:
            return None
        return rest_snapshot(self._restapi_dataset)

    def replay_layout(self) -> list[list]:
        return [["shmm", ctypes.sizeof(lmu_data.LMUObjectOut)]]

    def health(self) -> ConnectorHealth:
        shmm = self._shmmapi
        return ConnectorHealth(
            shmm.dataAge, shmm.isPaused, self._replaying, shmm.openError,
            () if self._replaying else self._restapi.status())

    def reader(self) -> APIDataReader:
        shmm = self._shmmapi
        rest = self._restapi_dataset
        return APIDataReader(
            lmu_reader.State(shmm, rest),
            lmu_reader.Brake(shmm, rest),
            lmu_reader.ElectricMotor(shmm, rest),
            lmu_reader.Engine(shmm, rest),
            lmu_reader.Inputs(shmm, rest),
            lmu_reader.Lap(shmm, rest),
            lmu_reader.Session(shmm, rest),
            lmu_reader.Switch(shmm, rest),
            lmu_reader.Timing(shmm, rest),
            lmu_reader.Tyre(shmm, rest),
            lmu_reader.Vehicle(shmm, rest),
            lmu_reader.Wheel(shmm, rest),
        )

    def setup(self, config: dict):
        self._shmmapi.setMode(config["access_mode"])
        self._shmmapi.setStateOverride(config["enable_active_state_override"])
        self._shmmapi.setActiveState(config["active_state"])
        self._shmmapi.setPlayerOverride(config["enable_player_index_override"])
        self._shmmapi.setPlayerIndex(config["player_index"])
        self._restapi.setConnection(config.copy())
        lmu_reader.tostr = partial(bytes_to_str, char_encoding=config["character_encoding"].lower())


class SimRF2(Connector):
    """rFactor 2 - RF2 Sharedmemory Map Plugin API"""

    __slots__ = (
        # Primary API
        "_shmmapi",
        "_replaying",
        # Secondary API
        "_restapi",
        "_restapi_dataset",
    )
    NAME = API_RF2_NAME
    LEGACY = False

    def __init__(self):
        self._shmmapi = rf2_connector.RF2Info()
        self._replaying = False
        self._restapi_dataset = rf2_restapi.RestAPIData()
        self._restapi = restapi_connector.RestAPIConnector(
            self.restapi_tasks(), self._restapi_dataset, on_start=reset_rf2_setup_parts)

    @staticmethod
    def restapi_tasks() -> tuple:
        """Rest API task set"""
        return rf2_restapi.rf2_restapi_tasks()

    def start(self):
        player = self.replay_player()
        self._replaying = player is not None
        # Recorded frames & Rest API data instead of game
        self._shmmapi.setReplay(player, self._restapi_dataset)
        self._shmmapi.start()  # 1 load first
        if not self._replaying:
            self._restapi.start()  # 2

    def stop(self):
        if not self._replaying:
            self._restapi.stop()  # 1 unload first
        self._shmmapi.stop()  # 2

    def raw_data(self) -> Any:
        if self._replaying or self._shmmapi.isPaused:
            return None
        return self._shmmapi.rawData

    def rest_data(self) -> dict | None:
        if self._replaying:
            return None
        return rest_snapshot(self._restapi_dataset)

    def replay_layout(self) -> list[list]:
        return rf2_connector.replay_layout()

    def health(self) -> ConnectorHealth:
        shmm = self._shmmapi
        return ConnectorHealth(
            shmm.dataAge, shmm.isPaused, self._replaying, shmm.openError,
            () if self._replaying else self._restapi.status())

    def reader(self) -> APIDataReader:
        shmm = self._shmmapi
        rest = self._restapi_dataset
        return APIDataReader(
            rf2_reader.State(shmm, rest),
            rf2_reader.Brake(shmm, rest),
            rf2_reader.ElectricMotor(shmm, rest),
            rf2_reader.Engine(shmm, rest),
            rf2_reader.Inputs(shmm, rest),
            rf2_reader.Lap(shmm, rest),
            rf2_reader.Session(shmm, rest),
            rf2_reader.Switch(shmm, rest),
            rf2_reader.Timing(shmm, rest),
            rf2_reader.Tyre(shmm, rest),
            rf2_reader.Vehicle(shmm, rest),
            rf2_reader.Wheel(shmm, rest),
        )

    def setup(self, config: dict):
        if self.NAME == API_RF2_NAME:
            self._shmmapi.setPID(config["process_id"])
        self._shmmapi.setMode(config["access_mode"])
        self._shmmapi.setStateOverride(config["enable_active_state_override"])
        self._shmmapi.setActiveState(config["active_state"])
        self._shmmapi.setPlayerOverride(config["enable_player_index_override"])
        self._shmmapi.setPlayerIndex(config["player_index"])
        self._restapi.setConnection(config.copy())
        rf2_reader.tostr = partial(bytes_to_str, char_encoding=config["character_encoding"].lower())


class SimLMULegacy(SimRF2):
    """Le Mans Ultimate (legacy) - RF2 Sharedmemory Map Plugin API"""

    __slots__ = ()  # same instances as rF2, LMU Rest API tasks
    NAME = API_LMULEGACY_NAME
    LEGACY = True

    @staticmethod
    def restapi_tasks() -> tuple:
        """Rest API task set"""
        return lmu_restapi.lmu_restapi_tasks()
