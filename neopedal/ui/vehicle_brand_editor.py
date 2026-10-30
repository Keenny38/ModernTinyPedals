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
Vehicle brand editor: car maker of each car (table editor page, see quick/table_editor.py)

Import reads every car & its maker from the game while it runs (its REST API: Le Mans Ultimate, two lists, or
rFactor 2), or from a JSON file of the same format. Names already listed keep their brand.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from ..api_control import api
from ..async_request import get_response, resolve_hostname, set_header_get
from ..const_api import API_LMU_ALIAS, API_LMU_CONFIG, API_RF2_ALIAS, API_RF2_CONFIG
from ..const_file import ConfigType, FileFilter
from ..game_rest import GameRequest
from ..i18n import tr
from ..setting import cfg
from ..userfile.brands import extract_lmu_brand_name
from ._common import translate_filter
from .quick.table_editor import KIND_NAME, KIND_TEXT, Column, TableEditorBackend
from .quick.table_editor_host import TableEditorPage

logger = logging.getLogger(__name__)

# Import sources: game (API config, alias in messages, resource), None for a JSON file
GAME_SOURCES: tuple[tuple[str, str, str] | None, ...] = (
    (API_LMU_CONFIG, API_LMU_ALIAS, "/rest/race/car"),
    (API_LMU_CONFIG, API_LMU_ALIAS, "/rest/sessions/getAllVehicles"),
    (API_RF2_CONFIG, API_RF2_ALIAS, "/rest/race/car"),
    None,
)


class BrandBackend(TableEditorBackend):
    """Car brands: car name, brand name"""

    COLUMNS = (
        Column("", "Vehicle name", KIND_NAME, width=16),
        Column("", "Brand name", KIND_TEXT, width=10, replace=True),
    )
    CONFIG_TYPE = ConfigType.BRANDS
    NEW_NAME = "New Vehicle Name"
    RESET_TEXT = "Reset every car brand to default? Changes are saved only by Save."
    IMPORT_SOURCES = (
        ("Le Mans Ultimate (game running)", "Cars & makers read from the game while it runs (its REST API)"),
        ("Le Mans Ultimate, other list (game running)",
         "Second list of the game (its REST API), all installed cars: try it if the first one fails"),
        ("rFactor 2 (game running)", "Cars & makers read from rFactor 2 while it runs (its REST API)"),
        ("JSON File…", "File saved from the game REST API (list of cars with their maker)"),
    )

    def setup(self):
        # Game asked in background: takes seconds to answer when not running
        self.rest_request = GameRequest(self, (), self.restapi_imported, on_failed=self.restapi_failed)

    def load(self) -> list[list]:
        return [[name, brand] for name, brand in cfg.user.brands.items()]

    def default_rows(self) -> list[list]:
        return [[name, brand] for name, brand in cfg.default.brands.items()]

    def to_setting(self, rows: list[list]) -> dict:
        return {name: brand for name, brand in rows}

    def new_row(self, name: str) -> list:
        return [name, "Unknown"]

    def session_rows(self) -> list[list]:
        """Cars of the session, brand from car model"""
        return [
            [api.read.vehicle.vehicle_name(index),
             extract_lmu_brand_name(api.read.vehicle.vehicle_model(index), "Unknown")]
            for index in range(api.read.vehicle.total_vehicles())
        ]

    # Import
    def import_from(self, index: int):
        source = GAME_SOURCES[index]
        if source is None:
            self.import_from_file()
        else:
            setting_key, sim_name, resource = source
            setting_api = cfg.user.setting[setting_key]
            self.import_from_restapi(sim_name, setting_api["url_host"], setting_api["url_port"], resource)

    def import_from_restapi(self, sim_name: str, url_host: str, url_port: int, resource_name: str):
        """Game asked in background (Import disabled until answered)"""
        def requesting() -> tuple[str, Any]:
            try:
                return sim_name, request_vehicle_data(url_host, url_port, resource_name)
            except (TimeoutError, AttributeError, TypeError, IndexError, KeyError, ValueError, OSError, EOFError,
                    RecursionError):  # RecursionError: nested too deeply
                return sim_name, None

        if self.rest_request.start(requesting):
            self.set_busy(True)

    def restapi_imported(self, result: tuple[str, Any]):
        """Game answer received (in GUI thread), vehicle data None if request failed"""
        self.set_busy(False)
        sim_name, vehicles = result
        try:
            if vehicles is None:
                raise ValueError
            self.import_vehicles(vehicles)
        except (AttributeError, TypeError, IndexError, KeyError, ValueError):
            logger.error("Failed importing vehicle data from %s Rest API", sim_name)
            self._host.warn(
                f"Unable to import vehicle data from {sim_name} Rest API.<br><br>"
                "Make sure game is running and try again."
            )

    def restapi_failed(self):
        self.set_busy(False)

    def import_from_file(self):
        filename = self._host.open_file(translate_filter(FileFilter.JSON))
        if not filename:
            return
        try:
            if os.path.getsize(filename) > 5_120_000:  # 5 MB at most
                raise TypeError
            with open(filename, encoding="utf-8") as jsonfile:
                vehicles = json.load(jsonfile)
            self.import_vehicles(vehicles)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError, OSError,
                RecursionError):  # RecursionError: nested too deeply
            logger.error("Failed importing %s", filename)
            self._host.warn("Cannot import selected file.<br><br>Invalid vehicle data file.")

    def import_vehicles(self, vehicles: Any):
        """Brands of imported cars added, listed names keep their brand (one undo step)"""
        brands = parse_brand_data(vehicles)
        if not self.verify():  # duplicated names would be merged by import
            return
        brands.update(self.to_setting(self.rows))
        self.set_rows([[name, brand] for name, brand in brands.items()])
        self.changed()
        self.notify(tr("Car brands imported"), undo=True)


def parse_brand_data(vehicles: Any) -> dict[str, str]:
    """Car name: brand, from game data (LMU "desc" or rF2 "name" format), KeyError if neither"""
    if vehicles[0].get("desc"):  # LMU
        return {veh["desc"]: veh["manufacturer"] for veh in vehicles}
    if vehicles[0].get("name"):  # rF2 & LMU vehicle list
        return {parse_vehicle_name(veh): veh["manufacturer"] for veh in vehicles}
    raise KeyError


def request_vehicle_data(url_host: str, url_port: int, resource_name: str) -> Any:
    """Vehicle data from Rest API (blocking: up to seconds if game is not running)"""
    url_host = resolve_hostname(url_host, url_port)
    request_header = set_header_get(resource_name, url_host)
    time_out = 3
    raw_veh_data = asyncio.run(get_response(request_header, url_host, url_port, time_out))
    return json.loads(raw_veh_data)


def parse_vehicle_name(vehicle):
    """Parse vehicle name"""
    # Example path string: "D:\\RF2\\Installed\\Vehicles\\SOMECAR\\1.50\\CAR_24.VEH"
    path_split = vehicle["vehFile"].split("\\")
    if len(path_split) < 2:
        # If VEH path does not contain version number, split name by space directly
        # Example name: "#24 Some Car 1.50"
        version_length = len(vehicle["name"].split(" ")[-1]) + 1
    else:
        # Get version number from last second split of path_split
        version_length = len(path_split[-2]) + 1
    return vehicle["name"][:-version_length]


class VehicleBrandEditor(TableEditorPage):
    """Vehicle brand editor"""

    BACKEND = BrandBackend
    TITLE = "Vehicle Brand Editor"
