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

from abc import ABC, abstractmethod
from functools import partial
from typing import Any, ClassVar

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
from .replay import replay, rest_snapshot
from .validator import bytes_to_str


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

    def replay_header(self) -> dict:
        """Replay file header: source API & shared memory zone layout"""
        return {"source": self.NAME}

    def close(self):
        """Dereference all instances"""
        name: str
        for name in self.__slots__:
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
        self._replaying = replay.active
        # Recorded frames & Rest API data instead of game
        self._shmmapi.setReplay(replay.player, self._restapi_dataset)
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
        self._restapi = restapi_connector.RestAPIConnector(rf2_restapi.rf2_restapi_tasks(), self._restapi_dataset)

    def start(self):
        self._replaying = replay.active
        # Recorded frames & Rest API data instead of game
        self._shmmapi.setReplay(replay.player, self._restapi_dataset)
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

    def replay_header(self) -> dict:
        return {"source": self.NAME, "layout": rf2_connector.replay_layout()}

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

    __slots__ = (
        # Primary API
        "_shmmapi",
        # Secondary API
        "_restapi",
        "_restapi_dataset",
    )
    NAME = API_LMULEGACY_NAME
    LEGACY = True

    def __init__(self):
        self._shmmapi = rf2_connector.RF2Info()
        self._restapi_dataset = lmu_restapi.RestAPIData()
        self._restapi = restapi_connector.RestAPIConnector(lmu_restapi.lmu_restapi_tasks(), self._restapi_dataset)
