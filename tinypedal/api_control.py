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
API control
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from . import api_connector, realtime_state
from .const_api import API_MAP_ALIAS
from .setting import cfg

if TYPE_CHECKING:
    from .adapter import APIDataReader

logger = logging.getLogger(__name__)


def _set_available_api(enable_legacy: bool):
    """Set available API (same on every platform)"""
    available_api = (
        api_connector.SimLMU,
        api_connector.SimLMULegacy,
        api_connector.SimRF2,
    )
    # Sort API by name
    api_gen = (_api for _api in available_api if not _api.LEGACY or enable_legacy)
    return tuple(sorted(api_gen, key=lambda _api:_api.NAME))


class APIControl:
    """API Control"""

    __slots__ = (
        "_api",
        "_available_api",
        "_enable_legacy",
        "_same_api_loaded",
        "read",
    )

    def __init__(self):
        self._api: api_connector.Connector | None = None
        self._available_api: tuple[type[api_connector.Connector], ...] = ()
        self._enable_legacy = False
        self._same_api_loaded = False
        # Data reader, always available after start() (widgets & modules only run after start)
        self.read: APIDataReader = None  # type: ignore[assignment]

    def connect(self, name: str = ""):
        """Connect to API

        Args:
            name: API full name
        """
        if not name:
            name = cfg.api_name

        enable_legacy = cfg.telemetry["enable_legacy_api_selection"]
        if not self._available_api or self._enable_legacy != enable_legacy:
            self._enable_legacy = enable_legacy
            self._available_api = _set_available_api(enable_legacy)
            self._same_api_loaded = False
        else:
            # Do not create new instance if same API already loaded
            self._same_api_loaded = bool(self._api is not None and name == self._api.NAME)

        if self._same_api_loaded:
            logger.info("CONNECTING: same API detected, fast restarting")
            return

        for _api in self._available_api:
            if name == _api.NAME:
                self._api = _api()
                return

        logger.warning("CONNECTING: Invalid API name, fall back to default")
        self._api = self._available_api[0]()
        cfg.api_name = self._api.NAME

    def start(self):
        """Start API"""
        logger.info("CONNECTING: %s API", self._connected.NAME)
        self.setup()
        self._connected.start()

        # Reload dataset if API changed
        if self.read is None or not self._same_api_loaded:
            init_read = self._connected.reader()
            self.read = init_read
            self._same_api_loaded = True

        logger.info("ENCODING: %s", cfg.api["character_encoding"])
        logger.info("CONNECTED: %s API (%s)", self._connected.NAME, self.read.state.version())

    def stop(self):
        """Stop API"""
        logger.info("DISCONNECTING: %s API (%s)", self._connected.NAME, self.read.state.version())
        self._connected.stop()
        logger.info("DISCONNECTED: %s API", self._connected.NAME)

    def close(self):
        """Close & dereference API"""
        if self._api:
            self._api.close()
        for var in self.__slots__:
            setattr(self, var, None)

    def restart(self):
        """Restart API"""
        self.stop()
        self.connect()
        self.start()

    def setup(self):
        """Setup & apply API changes"""
        setting_api = cfg.api
        realtime_state.overriding = setting_api["enable_active_state_override"]
        realtime_state.spectating = setting_api["enable_player_index_override"]
        self._connected.setup(setting_api)

    @property
    def _connected(self) -> api_connector.Connector:
        """Connected API, raise RuntimeError if connect() was not called"""
        if self._api is None:
            raise RuntimeError("API not connected, call connect() first")
        return self._api

    def raw_data(self) -> Any:
        """Raw shared memory of connected API for replay recording, None if unavailable"""
        if self._api is None:
            return None
        return self._api.raw_data()

    def rest_data(self) -> dict | None:
        """Rest API data snapshot of connected API for replay recording, None if unavailable"""
        if self._api is None:
            return None
        return self._api.rest_data()

    def replay_header(self) -> dict:
        """Replay file header of connected API (source name, zone layout)"""
        return self._connected.replay_header()

    def replay_layout(self) -> list[list]:
        """Shared memory zones of connected API replay frame: [name, size], ..."""
        return self._connected.replay_layout()

    def health(self) -> api_connector.ConnectorHealth | None:
        """Game data connection state of connected API, None if not connected"""
        if self._api is None:
            return None
        return self._api.health()

    @property
    def available(self):
        """Available API"""
        return self._available_api

    @property
    def name(self) -> str:
        """API full name"""
        return self._connected.NAME

    @property
    def alias(self) -> str:
        """API alias name"""
        return API_MAP_ALIAS[self._connected.NAME]


api = APIControl()
