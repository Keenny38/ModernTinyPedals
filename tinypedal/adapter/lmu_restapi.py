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
LMU Rest API task
"""

from __future__ import annotations

import logging

from ..const_common import WHEELS_NA
from ..process.game_info import parse_chat, parse_contacts, parse_distance, parse_setup_name
from ..process.garage import export_lmu_car_setup
from ..process.vehicle import absolute_refilling, export_wheels, steerlock_to_number
from ..process.weather import FORECAST_DEFAULT, WeatherNode, forecast_rf2
from .restapi_connector import ResOutput, RestAPITask, valid_json_value

logger = logging.getLogger(__name__)


class RestAPIData:
    """Rest API data"""

    __slots__ = (
        # LMU, RF2
        "timeScale",
        "privateQualifying",
        "forecastPractice",
        "forecastQualify",
        "forecastRace",
        "lastCarSetup",
        # LMU only
        "steeringWheelRange",
        "aeroDamage",
        "repairTime",
        "pitStopTime",
        "absoluteRefill",
        "maxVirtualEnergy",
        "brakeWear",
        "suspensionDamage",
        "expectedFuelConsumption",
        "expectedEnergyConsumption",
        "chatMessages",
        "contacts",
        "pitEntryDistance",
        "setupName",
        "setupModified",
    )

    def __init__(self):
        # LMU, RF2
        self.timeScale: int = 1
        self.privateQualifying: int = 0
        self.forecastPractice: tuple[WeatherNode, ...] = FORECAST_DEFAULT
        self.forecastQualify: tuple[WeatherNode, ...] = FORECAST_DEFAULT
        self.forecastRace: tuple[WeatherNode, ...] = FORECAST_DEFAULT
        self.lastCarSetup: tuple[str, ...] = ()
        # LMU only
        self.steeringWheelRange: float = 0.0
        self.aeroDamage: float = -1.0
        self.repairTime: float = 0.0
        self.pitStopTime: float = 0.0
        self.absoluteRefill: float = 0.0
        self.maxVirtualEnergy: float = 0.0
        self.brakeWear: tuple[float, float, float, float] = WHEELS_NA
        self.suspensionDamage: tuple[float, float, float, float] = WHEELS_NA
        self.expectedFuelConsumption: float = 0.0
        self.expectedEnergyConsumption: float = 0.0
        self.chatMessages: tuple[tuple[float, str], ...] = ()
        self.contacts: tuple[tuple[float, str, str], ...] = ()
        self.pitEntryDistance: float = -1.0
        self.setupName: str = ""
        self.setupModified: bool = False

    def __del__(self):
        if logger is not None:  # module globals are cleared at interpreter exit
            logger.info("RestAPI: GC: RestAPIData")


def lmu_restapi_tasks() -> tuple[RestAPITask, ...]:
    """Define RestAPI task set - LMU"""
    # Define resources output set
    res_weatherforecast = (
        ResOutput("forecastPractice", FORECAST_DEFAULT, forecast_rf2, ("PRACTICE",)),
        ResOutput("forecastQualify", FORECAST_DEFAULT, forecast_rf2, ("QUALIFY",)),
        ResOutput("forecastRace", FORECAST_DEFAULT, forecast_rf2, ("RACE",)),
    )
    res_currentstint = (
        ResOutput("aeroDamage", -1.0, valid_json_value, ("wearables", "body", "aero")),
        ResOutput("brakeWear", WHEELS_NA, export_wheels, ("wearables", "brakes")),
        ResOutput("suspensionDamage", WHEELS_NA, export_wheels, ("wearables", "suspension")),
        ResOutput("absoluteRefill", 0.0, absolute_refilling, ("pitMenu", "pitMenu")),
        ResOutput("maxVirtualEnergy", 0.0, valid_json_value, ("fuelInfo", "maxVirtualEnergy")),
    )
    res_garagesetup = (
        ResOutput("steeringWheelRange", 0.0, steerlock_to_number, ("VM_STEER_LOCK", "stringValue")),
        ResOutput("lastCarSetup", (), export_lmu_car_setup),
    )
    res_sessionsinfo = (
        ResOutput("timeScale", 1, valid_json_value, ("SESSSET_race_timescale", "currentValue")),
        ResOutput("privateQualifying", 0, valid_json_value, ("SESSSET_private_qual", "currentValue")),
    )
    res_expectedusage = (
        ResOutput("expectedFuelConsumption", 0.0, valid_json_value, ("expectedUsage", "fuelConsumption")),
        ResOutput("expectedEnergyConsumption", 0.0, valid_json_value, ("expectedUsage", "virtualEnergyFractionPerLap")),
    )
    res_chat = (
        ResOutput("chatMessages", (), parse_chat),
    )
    res_contacts = (
        ResOutput("contacts", (), parse_contacts),
    )
    res_gamestate = (
        ResOutput("pitEntryDistance", -1.0, parse_distance, ("PitEntryDist",)),
    )
    res_setupsummary = (
        ResOutput("setupName", "", parse_setup_name, ("activeSetup",)),
        ResOutput("setupModified", False, valid_json_value, ("unsavedChanges",)),
    )
    res_pitstoptime = (
        ResOutput("pitStopTime", 0.0, valid_json_value, ("total",)),
        ResOutput("repairTime", 0.0, valid_json_value, ("damage",)),
    )
    # Define task set (repeated tasks: minimum interval, maximum interval while data unchanged)
    return (
        RestAPITask("/rest/sessions/weather", res_weatherforecast, "enable_weather_info", False, 0.1),
        RestAPITask("/rest/sessions", res_sessionsinfo, "enable_session_info", False, 0.1),
        RestAPITask("/rest/garage/getPlayerGarageData", res_garagesetup, "enable_garage_setup_info", False, 0.1),
        RestAPITask("/rest/garage/summary", res_setupsummary, "enable_garage_setup_info", False, 0.1),
        RestAPITask("/rest/garage/UIScreen/RepairAndRefuel", res_currentstint, "enable_vehicle_info", True, 0.2, 1.0),
        RestAPITask("/rest/strategy/pitstop-estimate", res_pitstoptime, "enable_vehicle_info", True, 1.0, 2.0),
        RestAPITask("/rest/garage/UIScreen/TireManagement", res_expectedusage, "enable_vehicle_info", True, 1.0),
        RestAPITask("/rest/chat/", res_chat, "enable_race_info", True, 0.5, 1.0),
        RestAPITask("/rest/watch/getIncidentsList/1", res_contacts, "enable_race_info", True, 1.0, 1.0),
        RestAPITask("/rest/sessions/GetGameState", res_gamestate, "enable_race_info", True, 1.0),
    )
