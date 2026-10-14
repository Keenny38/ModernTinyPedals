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
Services imported once first used

Remote control, web dashboard & stream overlay servers, update checker: proxies importing their module (http.server,
ssl, urllib, zipfile...) at first attribute read, so features off never load them at start.
"""

import importlib
import sys
from typing import Any


class LazyService:
    """Server or update checker of a module imported once first used (any attribute read)

    Remote control, web dashboard & stream overlay servers, update checker: their modules (http.server, ssl, xml,
    asyncio...) never loaded at start with features off. See imported.
    """

    def __init__(self, module: str, name: str):
        self._module = f"{__package__}.{module}"
        self._name = name
        self._target: Any = None

    @property
    def imported(self) -> bool:
        """Whether module is imported (by this or any other user)"""
        return self._target is not None or self._module in sys.modules

    def __getattr__(self, attr: str) -> Any:
        target = self.__dict__.get("_target")
        if target is None:
            target = self._target = getattr(importlib.import_module(self._module), self._name)
        return getattr(target, attr)


def imported(service: Any) -> bool:
    """Whether server module is imported (replaced service of tests: always)"""
    return getattr(service, "imported", True)


cmdserver = LazyService("command_server", "cmdserver")
webdashboard = LazyService("web_dashboard", "webdashboard")
streamoverlay = LazyService("stream_overlay", "streamoverlay")
update_checker = LazyService("update", "update_checker")
