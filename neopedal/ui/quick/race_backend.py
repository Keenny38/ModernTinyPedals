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
Race calculator page state & actions for QML (qml/RaceCalculator.qml)

Inputs (saved in config "fuel_calculator"), fuel strategy & tyre plan linked (tyre change time of
each stop added to that stop, one tyre plan row per stint), results, consumption history, team
stints read from the game, live game data (every input the game gives, see race_live_data), live
race (plan of the rest of the race), race plan files & share code.

Every input change calculates at once (one calculation per change, see batch), scenarios
(saving target, strategy comparison, safety car & rain against none) once quick changes settle.
Dialogs, toasts & undo history belong to the page hosting the QML view (RaceHost).
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, replace
from typing import Any, Protocol

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication

from ... import calculation as calc
from ... import units
from ...api_control import api
from ...const_file import ConfigType, FileExt, FileFilter
from ...fuel_strategy import (
    MAX_DRIVERS,
    RaceState,
    Strategy,
    StrategyInput,
    compare_strategies,
    consumption,
    driver_table_text,
    estimate_pace,
    full_tank_laps,
    history_laps,
    plan,
    remaining_input,
    representative_laps,
    reserves,
    saving_input,
    saving_target,
    strategy_input_from_values,
)
from ...i18n import tr, trm
from ...module_info import ConsumptionDataSet, minfo
from ...process.team_usage import StintUsage, combine_usage, driver_usage, parse_usage, stint_usage, tank_capacity
from ...process.team_usage import tyre_allocation as game_tyre_allocation
from ...race_live import RivalTracker, StopCounter
from ...race_live import clock as race_clock
from ...race_live import read_race_state as read_live
from ...race_live_data import GARAGE_RESOURCES, GarageData, LiveValue, parse_garage
from ...race_live_data import collect as collect_live
from ...setting import cfg
from ...userfile import atomic_write, write_text_file
from ...userfile.consumption_history import load_consumption_history_file, save_consumption_history_file
from ...userfile.tyre_strategy import (
    DEFAULT_TYRE_SET,
    HEADER_TYREPLAN,
    export_tyre_strategy_file,
    load_tyre_strategy_file,
    save_tyre_strategy_file,
    validate_tyre_strategy,
)
from ..game_rest import GameRequest
from . import race_results as results
from .game_pictures import LogoCache, notifier
from .models import DictListModel
from .race_model import DRIVER_SPECS as DRIVER_INPUT_SPECS
from .race_model import (
    INPUT_SPECS,
    INVALID_COLOR,
    PLAN_FILE,
    RACE_PLAN_FORMAT,
    RACE_PLAN_VERSION,
    RACE_SESSION,
    SAVED_INPUTS,
    checked_inputs,
    clamp_input,
    clamp_number,
    clock_text,
    convert_fuel_inputs,
    day_time_text,
    decode_share_code,
    driver_rows,
    encode_share_code,
    input_spec,
    laptime_text,
    live_race_length,
    parse_laptime,
    parse_start_time,
    plan_markdown,
    ranged_inputs,
    start_time_text,
    unit_text,
    write_plan_csv,
)
from .race_tyres import (
    AUTOSAVE_NAME,
    MEASURED_DEFAULT,
    WHEELS,
    TyrePlan,
    save_tyre_strategy_file_path,
    set_tyre_strategy_file_path,
    tread_color,
)

logger = logging.getLogger(__name__)

SCENARIO_DELAY_MS = 150  # quick input changes (arrow held): scenarios calculated once settled
LIVE_REFRESH_MS = 2000  # live history check, live race state, rivals
TEAM_REFRESH_MS = 15000  # game asked again while team tab shown
GARAGE_REFRESH_MS = 10000  # LMU garage screens asked again while live tab shown or inputs follow live
SAVE_DELAY_MS = 500  # tyre plan autosave & plan input of race plan widget, once changes settle
USAGE_RESOURCES = ("/rest/strategy/usage", "/rest/garage/UIScreen/RepairAndRefuel")
TYRE_SCREEN = ("/rest/garage/UIScreen/TireManagement",)
TABS = ("fuel", "tyres", "team", "live")
LIVE_GROUPS = (  # live tab groups: key, title
    ("race", "Race"), ("pace", "Pace & Consumption"), ("start", "Race Start"), ("pit", "Pit Stop"),
    ("tyres", "Tyres"), ("weather", "Weather"),
)
FILLED_KEYS = frozenset((  # live values Load Live & Follow Live fill in from laps (fill_in_data)
    "race_length", "input_lap_time", "input_fuel_per_lap", "input_energy_per_lap", "input_wear_per_lap",
    "input_tank_capacity",
))
HISTORY_COLUMNS = (  # key, title, option of config "fuel_calculator" (always shown if none), selectable
    ("lap", "Lap", ""),
    ("time", "Time", ""),
    ("fuel", "Fuel", ""),
    ("energy", "Energy", ""),
    ("ratio", "F/E Ratio", "show_column_fuel_ratio"),
    ("drain", "Drain", "show_column_battery_drain"),
    ("regen", "Regen", "show_column_battery_regen"),
    ("net", "Net", "show_column_battery_net_change"),
    ("tyre", "Tyre", "show_column_tyre_wear"),
    ("tank", "Tank", "show_column_tank_capacity"),
)
COLUMN_OPTION_TITLES = {  # history column menu (option name made readable, as before)
    "show_column_fuel_ratio": "Fuel Ratio",
    "show_column_battery_drain": "Battery Drain",
    "show_column_battery_regen": "Battery Regen",
    "show_column_battery_net_change": "Battery Net Change",
    "show_column_tyre_wear": "Tyre Wear",
    "show_column_tank_capacity": "Tank Capacity",
}
TEAM_COLUMNS = ("Driver", "Stint", "Laps", "Laps counted", "Fuel", "Energy", "Tyre")
HISTORY_ROLES = ("serial", "valid", "cells", "selected")
TEAM_ROLES = ("key", "number", "enabled", "cells", "selected")  # number: of stint in team_stints


class RaceHost(Protocol):
    """Page hosting the race calculator: dialogs, toasts, undo history, modified marker"""

    def warn(self, text: str) -> None: ...
    def toast(self, text: str) -> None: ...
    def confirm(self, text: str) -> bool: ...
    def open_file(self, directory: str, file_filter: str) -> str: ...
    def save_file(self, directory: str, file_filter: str) -> str: ...
    def ask_text(self, title: str, label: str, text: str) -> tuple[str, bool]: ...
    def open_compound_config(self, name: str, user_setting: dict, reload) -> None: ...
    def record_change(self) -> None: ...
    def set_modified(self) -> None: ...
    def set_unmodified(self) -> None: ...
    def undo(self) -> None: ...
    def redo(self) -> None: ...
    def is_page_visible(self) -> bool: ...


def file_stamp(full_path: str) -> tuple[int, int] | None:
    """Modified time & size of a file, None if missing"""
    try:
        stat = os.stat(full_path)
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def write_history(filepath: str, filename: str, extension: str, laps: Sequence[ConsumptionDataSet]) -> bool:
    """Consumption history file rewritten with laps kept, removed when none left,
    False if file left as it was (locked by another program, read-only)"""
    full_path = f"{filepath}{filename}{extension}"
    if not laps:
        try:
            if os.path.exists(full_path):
                os.remove(full_path)
        except OSError:
            return False
        return True
    dataset = list(laps) if len(laps) > 1 else [*laps, ConsumptionDataSet()]  # placeholder: skipped on load
    stamp = file_stamp(full_path)
    save_consumption_history_file(dataset=dataset, filepath=filepath, filename=filename, extension=extension)
    return file_stamp(full_path) != stamp  # failed save only logged: file not replaced


def history_signature(dataset: Sequence[ConsumptionDataSet]) -> tuple:
    return (len(dataset), dataset[0] if dataset else None)


class RaceBackend(QObject):
    """Race calculator state for QML, see module docstring"""

    inputsChanged = Signal()
    calcChanged = Signal()
    tilesChanged = Signal()
    summaryChanged = Signal()
    timelineChanged = Signal()
    fuelLevelsChanged = Signal()
    planChanged = Signal()
    detailsChanged = Signal()
    tyreLifeChanged = Signal()
    driverTimesChanged = Signal()
    planVsRaceChanged = Signal()
    scenariosChanged = Signal()
    notesChanged = Signal()
    historyChanged = Signal()  # anything of the history (Python callers: QML reads the parts below)
    historyViewChanged = Signal()
    historySelectionChanged = Signal()
    tyresChanged = Signal()
    teamChanged = Signal()  # anything of the team (Python callers: QML reads the parts below)
    teamInfoChanged = Signal()
    teamStatusChanged = Signal()
    teamSelectionChanged = Signal()
    headerChanged = Signal()
    liveChanged = Signal()  # live race status & tip (apart from header: tip changes at each live refresh)
    rivalsChanged = Signal()
    liveDataChanged = Signal()

    def __init__(self, parent: QObject, host: RaceHost):
        super().__init__(parent)
        self.host = host
        self.logos = LogoCache()
        notifier().changed.connect(self.headerChanged)  # circuit logo fetched from game meanwhile
        config = cfg.user.config["fuel_calculator"]
        # Fuel unit of the page (frozen while open)
        self.is_gallon = cfg.units["fuel_unit"] == "Gallon"
        self.fuel_unit = "Gallon" if self.is_gallon else "Liter"  # of fuel inputs (race plan, share code)
        self.unit_fuel = units.set_unit_fuel(cfg.units["fuel_unit"])
        self.symbol_fuel = units.set_symbol_fuel(cfg.units["fuel_unit"])

        self.values = ranged_inputs(config)
        measured = config.get("input_measured_compound", MEASURED_DEFAULT)
        compounds = tuple(DEFAULT_TYRE_SET)
        self.measured_index = measured if isinstance(measured, int) and not isinstance(measured, bool) \
            and 0 <= measured < len(compounds) else MEASURED_DEFAULT
        self._batch = 1  # no calculation while page is built
        self._updating = False
        self._shown_values: dict = {}
        self.strategy = Strategy()
        self.plan_setup = StrategyInput()  # input of strategy, tyre plan included
        self.race_setup = StrategyInput()  # input of whole race (before live race state), kept for widget
        self.race_strategy = Strategy()  # plan of whole race (before live race state)
        self.race_state: RaceState | None = None  # live race under way: plan of the rest of the race
        self.race_tyre_changes: list[int] = []  # tyres changed at each stop of tyre plan (whole race)
        self.proposed_tyre_rows: list[int] = []  # tyre plan rows (stints) needing new tyres (minimum tread)
        self.sections: dict = {}  # results shown, by QML property name (see publish)
        self._last_calculation = 0.0
        self._plan_file_data: dict = {}
        self.calculations = 0  # calculations made (tests)

        # Notes of actions: fill in source, estimate, history
        self.fill_source = ""
        self.estimate_text = ""
        self.history_added = ""

        # Tyre plan of last time
        self.tyres = TyrePlan()
        self.tyres.measured = compounds[self.measured_index]
        self.load_tyre_autosave()

        # Consumption history: newest lap first, serial of each lap (newest highest, kept as laps come)
        self.live_source = True
        self.source_name = ""
        self.history_file = ("", "", "")  # file source: path, name, extension
        self.history_data: list[ConsumptionDataSet] = []
        self.history_serials: list[int] = []
        self.history_selection: set[int] = set()  # serials
        self._history_anchor = -1
        self.sort_column = -1  # newest first until a column is clicked
        self.sort_ascending = True
        self._live_signature: tuple = ()
        # Rows shown kept in place (new lap: one row inserted, selection: one role changed), view without rows
        self.history_model = DictListModel(HISTORY_ROLES, self)
        self._history_view: dict = {}
        self._history_cache: dict[int, tuple[ConsumptionDataSet, dict]] = {}  # serial: lap, row formatted

        # Team stints (game strategy usage)
        self.team_stints: list[StintUsage] = []
        self.team_capacity = 0.0  # tank capacity of car (fuel unit), 0 if unknown
        self.team_selection: set[int] = set()
        self.team_status = ""
        self.team_model = DictListModel(TEAM_ROLES, self)  # stints synced in place: list keeps scroll position
        self._team_info: dict = {}
        # Bound methods (held weakly): busy state left on failure too
        self.team_request = GameRequest(self, USAGE_RESOURCES, self.received_team, self.team_request_failed)
        self.tyre_request = GameRequest(self, TYRE_SCREEN, self.received_allocation, self.allocation_request_failed)
        self.publish_team()

        # Live game data: LMU garage screens asked in background, values of every input
        self.garage = GarageData()
        self.garage_time = ""  # time of last garage answer
        self.garage_request = GameRequest(self, GARAGE_RESOURCES, self.received_garage, self.garage_request_failed)
        self._apply_garage = False  # Load Live asked: garage values filled in once answered
        self.live_values: list[LiveValue] = []
        self._live_view: dict = {}

        # Live race
        self.stop_counter = StopCounter()
        self.rival_tracker = RivalTracker()
        self._race_key: tuple | None = None
        self.live_status = ""
        self.live_tip = ""
        self._rivals: dict = results.class_rivals([], 0)
        self._combo_loaded = ""
        self._shown_combo = ""
        tab = config.get("race_tab", 0)
        self.tab = tab if isinstance(tab, int) and not isinstance(tab, bool) and 0 <= tab < len(TABS) else 0
        self.active = False  # page shown

        self._scenario_timer = self._timer(self.update_scenarios, single=True)
        self._plan_file_timer = self._timer(self.write_plan_file, SAVE_DELAY_MS, single=True)
        self._autosave_timer = self._timer(self.autosave_tyres, SAVE_DELAY_MS, single=True)
        self._live_timer = self._timer(self.refresh_live, LIVE_REFRESH_MS)
        self._team_timer = self._timer(self.refresh_team, TEAM_REFRESH_MS)
        self._garage_timer = self._timer(self.refresh_garage, GARAGE_REFRESH_MS)

        # Inputs of a race plan opened last time kept: live laps shown, not filled in
        self._batch = 0
        with self.batch():
            self.show_live_data(fill_inputs=not config.get("enable_plan_inputs"))
            self.auto_load_combo_plan()
        self.refresh_race_state()
        self._live_timer.start()

    def _timer(self, slot, interval: int = 0, single: bool = False) -> QTimer:
        timer = QTimer(self)
        timer.setSingleShot(single)
        timer.setInterval(interval)
        timer.timeout.connect(slot)
        return timer

    # Page shown or hidden, closed
    def set_active(self, active: bool):
        """Page shown: live history follows new laps, team asked to game while team tab shown"""
        self.active = active
        if active:
            self.refresh_live()
        self.update_team_timer()
        self.update_garage_timer()

    def release(self):
        """Page closed: tyre plan & plan input written now, timers stopped"""
        for timer in (self._live_timer, self._team_timer, self._garage_timer, self._scenario_timer):
            timer.stop()
        self.autosave_tyres()
        self.flush_plan_file()

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Several inputs changed together: one calculation at the end, not one per input"""
        self._batch += 1
        try:
            yield
        finally:
            self._batch -= 1
            if not self._batch:
                self.update_input()

    # QML properties
    @Property(dict, notify=inputsChanged)
    def inputs(self) -> dict:
        values = dict(self.values)
        values["input_measured_compound"] = self.measured_index
        values["lap_time_text"] = laptime_text(values["input_lap_time"])
        values["start_time_text"] = start_time_text(values["input_race_start_minutes"])
        values["drivers_table"] = [list(row) for row in driver_rows(values["input_driver_table"])]
        return values

    @Property(dict, constant=True)
    def specs(self) -> dict:
        """Range, decimals, step & unit of each number input (margin: see marginSpec)"""
        specs = {key: {"min": spec.minimum, "max": spec.maximum, "decimals": spec.decimals, "step": spec.step,
                       "suffix": unit_text(spec.unit, self.symbol_fuel)} for key, spec in INPUT_SPECS.items()}
        for index, spec in enumerate(DRIVER_INPUT_SPECS):
            specs[f"driver_{index}"] = {"min": spec.minimum, "max": spec.maximum, "decimals": spec.decimals,
                                        "step": spec.step, "suffix": unit_text(spec.unit, self.symbol_fuel)}
        return specs

    @Property(dict, notify=inputsChanged)
    def marginSpec(self) -> dict:
        kind = self.values["input_safety_margin_kind"]
        spec = input_spec("input_safety_margin", kind)
        return {"min": spec.minimum, "max": spec.maximum, "decimals": spec.decimals, "step": spec.step,
                "suffix": unit_text("margin", self.symbol_fuel, kind)}

    @Property(str, constant=True)
    def fuelSymbol(self) -> str:
        return self.symbol_fuel

    @Property(list, constant=True)
    def marginUnits(self) -> list:
        return [tr("lap"), self.symbol_fuel, "%"]

    @Property(list, constant=True)
    def measuredCompounds(self) -> list:
        return list(DEFAULT_TYRE_SET)

    @Property(int, constant=True)
    def maxDrivers(self) -> int:
        return MAX_DRIVERS

    # Results, one property per part of the page: only parts that changed are shown again
    @Property(dict, notify=calcChanged)
    def calc(self) -> dict:
        return self.sections.get("calc", {})

    @Property(list, notify=tilesChanged)
    def tiles(self) -> list:
        return self.sections.get("tiles", [])

    @Property(dict, notify=summaryChanged)
    def summary(self) -> dict:
        return self.sections.get("summary", {})

    @Property(dict, notify=timelineChanged)
    def timeline(self) -> dict:
        return self.sections.get("timeline", {})

    @Property(list, notify=fuelLevelsChanged)
    def fuelLevels(self) -> list:
        return self.sections.get("fuelLevels", [])

    @Property(dict, notify=planChanged)
    def plan(self) -> dict:
        return self.sections.get("plan", {})

    @Property(dict, notify=detailsChanged)
    def details(self) -> dict:
        return self.sections.get("details", {})

    @Property(dict, notify=tyreLifeChanged)
    def tyreLife(self) -> dict:
        return self.sections.get("tyreLife", {})

    @Property(dict, notify=driverTimesChanged)
    def driverTimes(self) -> dict:
        return self.sections.get("driverTimes", {})

    @Property(dict, notify=planVsRaceChanged)
    def planVsRace(self) -> dict:
        return self.sections.get("planVsRace", {})

    @Property(dict, notify=scenariosChanged)
    def scenarios(self) -> dict:
        return self.sections.get("scenarios", {})

    def publish(self, name: str, value):
        """Part of the results shown again if it changed"""
        if self.sections.get(name) != value:
            self.sections[name] = value
            getattr(self, f"{name}Changed").emit()

    @Property(dict, notify=notesChanged)
    def notes(self) -> dict:
        return {"fillSource": self.fill_source, "estimate": self.estimate_text, "historyAdded": self.history_added}

    @Property(dict, notify=headerChanged)
    def header(self) -> dict:
        config = cfg.user.config["fuel_calculator"]
        return {
            "live": self.live_source, "source": self.source_name or "-",
            "followLive": bool(config.get("enable_follow_live")), "liveRace": bool(config.get("enable_live_race")),
            "autoCombo": bool(config.get("enable_auto_load_combo_plan", True)),
            "showHistory": bool(config.get("show_consumption_history", True)),
            "collapsed": self.collapsed_sections(),
            "tab": self.tab, "combo": self.combo_name(),
            "trackLogo": self.logos.track(self.source_name.split(" - ", 1)[0]) if self.source_name else "",
        }

    @Property(str, notify=liveChanged)
    def liveStatus(self) -> str:
        return self.live_status

    @Property(str, notify=liveChanged)
    def liveTip(self) -> str:
        return self.live_tip

    @Property(dict, notify=historyChanged)
    def history(self) -> dict:
        """Whole history view with its rows (Python callers): QML reads historyView & historyRows"""
        return dict(self.history_view(), rows=[dict(row) for row in self.history_model.rows])

    @Property(dict, notify=historyViewChanged)
    def historyView(self) -> dict:
        return self._history_view

    @Property(QObject, constant=True)
    def historyRows(self) -> QObject:
        return self.history_model

    @Property(list, notify=historySelectionChanged)
    def historySelection(self) -> list:
        return sorted(self.history_selection)

    @Property(dict, notify=tyresChanged)
    def tyrePlan(self) -> dict:
        return self.tyres.view()

    @Property(dict, notify=teamChanged)
    def team(self) -> dict:
        """Whole team view (Python callers): QML reads teamInfo, teamRows & teamStatus"""
        return dict(self.team_view(), status=self.team_status, busy=self.team_request.busy)

    @Property(dict, notify=teamInfoChanged)
    def teamInfo(self) -> dict:
        return self._team_info

    @Property(QObject, constant=True)
    def teamRows(self) -> QObject:
        return self.team_model

    @Property(str, notify=teamStatusChanged)
    def teamStatus(self) -> str:
        return self.team_status

    @Property(bool, notify=teamStatusChanged)
    def teamBusy(self) -> bool:
        return self.team_request.busy

    @Property(list, notify=teamSelectionChanged)
    def teamSelection(self) -> list:
        return sorted(self.team_selection)

    @Property(dict, notify=rivalsChanged)
    def rivals(self) -> dict:
        return self._rivals

    # Inputs
    @Slot(str, "QVariant", result="QVariant")
    def setInput(self, key: str, value: Any) -> Any:
        """Input changed in the page: kept in range, strategy calculated again, value kept returned"""
        if key == "input_measured_compound":
            self.set_measured_compound(int(value))
            return self.measured_index
        value = clamp_input(key, value, self.values["input_safety_margin_kind"])
        if value is None:
            return None
        if self.values.get(key) != value:
            self.values[key] = value
            if key == "input_safety_margin_kind":  # range of the new unit
                self.values["input_safety_margin"] = clamp_input(
                    "input_safety_margin", self.values["input_safety_margin"], value)
            if key in ("input_tank_capacity", "input_fuel_start"):
                self.limit_starting_fuel()
            self.update_input()
        return self.values[key]

    def set_values(self, values: dict):
        """Several inputs (checked) at once, one calculation"""
        with self.batch():
            for key, value in values.items():
                self.setInput(key, value)

    @Slot(str, result=str)
    def setLapTime(self, text: str) -> str:
        """Lap time typed (m:ss.mmm), lap time kept returned as text"""
        seconds = parse_laptime(text)
        if seconds is not None:
            self.setInput("input_lap_time", seconds)
        return laptime_text(self.values["input_lap_time"])

    @Slot(float, result=str)
    def stepLapTime(self, seconds: float) -> str:
        """Lap time up or down (never below zero)"""
        self.setInput("input_lap_time", max(self.values["input_lap_time"] + seconds, 0.0))
        return laptime_text(self.values["input_lap_time"])

    @Slot(bool, str, result=str)
    def setStartTime(self, enabled: bool, text: str) -> str:
        """Time of day of race start (hh:mm), unchecked: race time shown"""
        minutes = parse_start_time(text) if enabled else -1
        if minutes is None:  # not a time: last one kept
            minutes = self.values["input_race_start_minutes"]
            if enabled and minutes < 0:
                minutes = 14 * 60
        self.setInput("input_race_start_minutes", minutes)
        return start_time_text(self.values["input_race_start_minutes"])

    @Slot(int, int, float, result=float)
    def setDriverValue(self, driver: int, column: int, value: float) -> float:
        """Pace, minimum or maximum driving time of a driver"""
        rows = [list(row) for row in driver_rows(self.values["input_driver_table"])]
        if not (0 <= driver < len(rows) and 0 <= column < 3):
            return 0.0
        rows[driver][column] = float(clamp_number(float(value), DRIVER_INPUT_SPECS[column]))
        self.setInput("input_driver_table", driver_table_text(rows))
        return rows[driver][column]

    def limit_starting_fuel(self):
        """Starting fuel never above tank capacity"""
        capacity = self.values["input_tank_capacity"]
        if capacity > 0 and self.values["input_fuel_start"] > capacity:
            self.values["input_fuel_start"] = capacity

    def set_measured_compound(self, index: int):
        """Compound of measured wear per lap: wear of other compounds scaled by their wear per stint"""
        compounds = tuple(DEFAULT_TYRE_SET)
        if not 0 <= index < len(compounds) or index == self.measured_index:
            return
        self.measured_index = index
        config = cfg.user.config["fuel_calculator"]
        if config.get("input_measured_compound") != index:
            config["input_measured_compound"] = index
            cfg.save(config_type=ConfigType.CONFIG)
        self.tyres.measured = compounds[index]
        self.tyres.forget_stints()
        self.tyres.refresh()
        self.tyre_plan_changed(user_edit=False)

    def save_inputs(self):
        """Inputs kept for next time (saved once changed)"""
        config = cfg.user.config["fuel_calculator"]
        if all(config.get(key) == value for key, value in self.values.items()):
            return
        config.update(self.values)
        cfg.save(config_type=ConfigType.CONFIG)

    def input_values(self) -> dict:
        return dict(self.values)

    @Slot()
    def resetValues(self):
        """Every input back to zero (tyre tread to new tyres), tyre plan kept"""
        with self.batch():
            self.values = ranged_inputs(SAVED_INPUTS)
        self.fill_source = ""
        self.history_added = ""
        self.notesChanged.emit()

    # Calculation
    def strategy_input(self) -> StrategyInput:
        """Input of the whole race (tyre plan & live race state applied by plan_with_tyres)"""
        return strategy_input_from_values(self.values)

    def update_input(self):
        """Calculate and output results"""
        if self._batch or self._updating:
            return
        self._updating = True
        try:
            self.calculate()
        finally:
            self._updating = False
        if self.values != self._shown_values or not self._shown_values:
            self._shown_values = dict(self.values)
            self.inputsChanged.emit()
        self.save_inputs()
        self.host.record_change()

    def set_race_state(self, state: RaceState | None):
        """Live race under way: plan of the rest of the race from now (None: whole race)"""
        if state != self.race_state:
            self.race_state = state
            self.update_input()

    def plan_with_tyres(self, setup: StrategyInput) -> Strategy:
        """Pit stop plan, tyre change time of the tyre plan added to each stop

        Tyre plan rows follow stints and stints follow tyre time (time race): settled in a few
        rounds. Tyre plan with tyres: its changes replace the proposed ones (minimum tread).
        Live race state: plan of the rest of the race, tyre plan rows kept as planned before.
        """
        link = self.tyres
        link.wear_per_lap = self.values["input_wear_per_lap"]
        link.minimum_tread = self.values["input_minimum_tread"]
        setup = replace(
            setup,
            tyre_change_seconds=link.full_change_seconds(),
            tread_start=link.start_tread(setup.tread_start),
            fresh_tread=link.fresh_tread(),
            wear_per_lap=setup.wear_per_lap * link.wear_factor(),
        )

        def tyre_times() -> tuple[float, ...]:  # proposed changes cost 4 tyres until tyres are planned
            return tuple(link.stop_change_times()) if link.has_tyres() else ()

        extra = tyre_times()
        strategy = plan(replace(setup, stop_extra_seconds=extra))
        rows_changed = False
        if self.race_state is None:
            for _ in range(3):
                rows_changed |= link.set_stints(strategy)
                new_extra = tyre_times()
                if new_extra == extra:
                    break
                extra = new_extra
                strategy = plan(replace(setup, stop_extra_seconds=extra))
            else:
                rows_changed |= link.set_stints(strategy)
        if rows_changed:
            self.tyresChanged.emit()
            self._autosave_timer.start()
        self.race_setup = self.plan_setup = replace(setup, stop_extra_seconds=extra)
        self.race_strategy = strategy
        self.proposed_tyre_rows = [index for index, stop in enumerate(strategy.stops, 1) if stop.tyres]
        changes = link.stop_tyre_changes()
        self.race_tyre_changes = list(changes)
        if self.race_state is not None and strategy.ready:
            self.plan_setup = remaining_input(self.race_setup, strategy, self.race_state)
            strategy = plan(self.plan_setup)
            changes = changes[self.race_state.stops_done:]
        if changes:
            strategy.tyre_changes = changes[:len(strategy.stops)]
            strategy.stops = [
                replace(stop, tyres=index < len(changes) and changes[index] > 0)
                for index, stop in enumerate(strategy.stops)
            ]
        return strategy

    def time_text(self, seconds: float) -> str:
        """Race clock of a stop: time of day when start time is set, else race time"""
        start = self.values["input_race_start_minutes"]
        return day_time_text(start, seconds) if start >= 0 else clock_text(seconds)

    def calculate(self):
        self.calculations += 1
        setup = self.strategy_input()
        strategy = self.strategy = self.plan_with_tyres(setup)
        plan_setup = self.plan_setup
        has_energy = setup.energy_per_lap > 0
        has_fuel = setup.fuel_per_lap > 0 and setup.tank_capacity > 0
        drivers = self.values["input_drivers"]
        ready = strategy.ready
        stops = len(strategy.stops)

        fuel_used = setup.fuel_per_lap * 3.785411784 if self.is_gallon else setup.fuel_per_lap
        fuel_ratio = calc.fuel_to_energy_ratio(fuel_used, setup.energy_per_lap)

        # Details of fuel & energy, same race length (pit stops shared)
        usage = consumption(plan_setup)
        reserve = reserves(plan_setup, usage)
        fuel, fuel_stint = results.consumption_details(
            "fuel", setup.tank_capacity, usage.get("fuel", setup.fuel_per_lap),
            plan_setup.fuel_start or setup.tank_capacity, strategy.fuel_needed, reserve["fuel"], setup.laptime,
            self.is_gallon)
        energy, _ = results.consumption_details(
            "energy", 100, usage.get("energy", setup.energy_per_lap), plan_setup.energy_start or 100,
            strategy.energy_needed, reserve["energy"], setup.laptime, False)
        fuel["average_refill"] = f"{strategy.average_fuel:.2f}" if stops else results.DASH
        energy["average_refill"] = f"{strategy.average_energy:.2f}" if stops else results.DASH
        if not ready or not has_fuel:  # energy only car: no fuel figure
            fuel = {}
        if not ready or not has_energy:
            energy = {}
        previous = self.sections.get("scenarios", {})
        fuel["one_less_stint"] = previous.get("oneLessFuel", results.DASH) if fuel else results.DASH
        energy["one_less_stint"] = previous.get("oneLessEnergy", results.DASH) if energy else results.DASH

        stint_laps = results.stint_laps_of(strategy, fuel_stint)
        tyre_status = self.tyres.status()
        driver_limits = driver_rows(self.values["input_driver_table"])
        stints_done = list(reversed(self.race_stints()))
        self.publish("calc", {
            "ready": ready, "feasible": strategy.feasible, "impossible": strategy.impossible,
            "hasEnergy": has_energy, "hasFuel": has_fuel, "drivers": drivers,
            "fuelRatio": f"{fuel_ratio:.3f}" if has_energy else results.DASH,
        })
        self.publish("tiles", results.key_figures(strategy, setup, self.symbol_fuel, self.is_gallon, tyre_status))
        self.publish("summary", results.summary(strategy, self.race_state))
        self.publish("timeline", results.timeline(strategy, drivers, self.symbol_fuel, self.time_text))
        self.publish("fuelLevels", results.fuel_levels(strategy, plan_setup, has_fuel))
        self.publish("plan", {
            "columns": [{"key": key, "title": title, "tip": tr(results.PLAN_TIPS[key]) if key in results.PLAN_TIPS else ""}
                        for key, title in zip(results.PLAN_COLUMNS, results.plan_header(self.symbol_fuel))],
            "rows": [list(row) for row in results.plan_rows(strategy, has_energy, self.time_text,
                                                             plan_setup.clock_offset)],
            "hidden": results.plan_hidden(strategy, has_energy, drivers),
            "title": results.plan_title(strategy) if ready else tr("Pit Stop Plan"),
            "ready": ready,
        })
        self.publish("details", {
            "rows": results.detail_rows(fuel, energy), "fuelEnabled": has_fuel or not has_energy,
            "energyEnabled": has_energy,
            "fuelTitle": f"{tr('Fuel')} ({self.symbol_fuel})", "energyTitle": f"{tr('Energy')} (%)",
        })
        self.publish("tyreLife", results.tyre_life(
            self.values["input_tread_start"], self.values["input_wear_per_lap"], self.values["input_minimum_tread"],
            stint_laps, setup.laptime))
        self.publish("driverTimes", results.driver_times(strategy, drivers, driver_limits))
        self.publish("planVsRace", results.plan_against_race(
            stints_done, self.race_strategy, setup.fuel_per_lap, setup.energy_per_lap, setup.laptime,
            self.unit_fuel, has_energy, self.symbol_fuel, self.race_stint_drivers()))
        self.schedule_plan_file()

        # Scenarios: at once, or once quick changes (arrow held) settle
        now = time.monotonic()
        quick = now - self._last_calculation < SCENARIO_DELAY_MS / 1000
        self._last_calculation = now
        if quick and SCENARIO_DELAY_MS > 0:
            self._scenario_timer.start(SCENARIO_DELAY_MS)
        else:
            self._scenario_timer.stop()
            self.update_scenarios()

    def update_scenarios(self):
        """Saving target (and one stop less of details), strategies compared, safety car & rain
        against none"""
        strategy, plan_setup = self.strategy, self.plan_setup
        setup = self.strategy_input()
        has_energy = setup.energy_per_lap > 0
        ready = strategy.ready
        target = saving_target(plan_setup, strategy)
        laps_target = self.values["input_target_stint_laps"]
        aimed = None
        if laps_target > 0 and ready:
            aimed_setup = saving_input(plan_setup, laps_target)
            aimed = (aimed_setup, plan(aimed_setup))
        scenarios = results.saving_texts(strategy, plan_setup, setup, target, aimed, self.symbol_fuel)
        variants = compare_strategies(plan_setup, strategy) if ready and strategy.feasible else []
        scenarios["comparison"] = results.comparison(variants, has_energy, self.symbol_fuel)
        for name, enabled, without_input in (
            ("safetyCar", self.values["enable_safety_car"], replace(plan_setup, sc_lap=0, sc_laps=0, sc_pit=False)),
            ("rain", self.values["enable_rain"], replace(plan_setup, rain_lap=0, rain_tyres=False)),
        ):
            without = plan(without_input) if enabled and ready else None
            scenarios[name] = results.scenario_text("rain" if name == "rain" else "sc", strategy, without) \
                if enabled else ""
        self.publish("scenarios", scenarios)
        details = self.sections.get("details")
        if details:  # one stop less in details
            calc_view = self.sections.get("calc", {})
            rows = []
            for row in details["rows"]:
                if row["key"] == "one_less_stint":
                    row = dict(row, fuel=scenarios["oneLessFuel"] if calc_view.get("ready") and calc_view.get("hasFuel")
                               else results.DASH, energy=scenarios["oneLessEnergy"])
                rows.append(row)
            self.publish("details", dict(details, rows=rows))

    # Fill in
    def fill_in_data(self, dataset: Sequence[ConsumptionDataSet], race_length: tuple[str, int] | None = None,
                     live: bool = True, skip: frozenset[str] | set[str] = frozenset()):
        """Fill in history data: average of latest laps at race pace, race length of a live race,
        tank capacity of live car (live data) or of the laps (file, maybe another car)

        Args:
            skip: live values not followed (live tab): inputs left as they are.
        """
        def put(key: str, value):
            if key not in skip:
                self.setInput(key, value)

        with self.batch():
            if race_length is not None and "race_length" not in skip:
                kind, value = race_length
                self.setInput("input_race_laps" if kind == "laps" else "input_race_minutes", value)
                self.setInput("enable_lap_race", kind == "laps")
            if not dataset:
                if live:
                    self.fill_in_game_estimate(skip)
                return
            capacity = dataset[0].capacityFuel
            if live:
                capacity = max(api.read.engine.tank_capacity(), capacity)
            if capacity:
                put("input_tank_capacity", self.unit_fuel(capacity))
            laps = representative_laps(dataset)
            if not laps:
                if not (live and self.fill_in_game_estimate(skip)):
                    self.set_fill_source(tr("No valid lap at race pace to fill in"))
                return
            put("input_lap_time", calc.dataset_mean([lap.lapTimeLast for lap in laps]))
            put("input_fuel_per_lap", self.unit_fuel(calc.dataset_mean([lap.lastLapUsedFuel for lap in laps])))
            put("input_energy_per_lap", calc.dataset_mean([lap.lastLapUsedEnergy for lap in laps]))
            put("input_wear_per_lap", calc.dataset_mean([lap.tyreAvgWearLast for lap in laps]))
            self.set_fill_source(trm(f"Average of {len(laps)} valid lap(s) at race pace"))

    def fill_in_game_estimate(self, skip: frozenset[str] | set[str] = frozenset()) -> bool:
        """Fuel & energy per lap estimated by game (LMU, while driving) until a valid lap at race pace,
        False if game gives none"""
        fuel = api.read.engine.expected_fuel_consumption()
        energy = api.read.engine.expected_energy_consumption()
        if fuel <= 0 and energy <= 0:
            return False
        with self.batch():
            capacity = api.read.engine.tank_capacity()
            if capacity > 0 and "input_tank_capacity" not in skip:
                self.setInput("input_tank_capacity", self.unit_fuel(capacity))
            if fuel > 0 and "input_fuel_per_lap" not in skip:
                self.setInput("input_fuel_per_lap", self.unit_fuel(fuel))
            if energy > 0 and "input_energy_per_lap" not in skip:
                self.setInput("input_energy_per_lap", energy)
        self.set_fill_source(tr("Game estimate per lap: no valid lap at race pace yet"))
        return True

    def set_fill_source(self, text: str):
        self.fill_source = text
        self.notesChanged.emit()

    @Slot()
    def estimateFromHistory(self):
        """Pit stop time, fuel effect & track evolution estimated from consumption history"""
        estimate = estimate_pace(self.history_data, self.unit_fuel)
        found = []
        with self.batch():
            if estimate.pit_stops:
                self.setInput("input_pit_seconds", round(estimate.pit_seconds, 1))
                found.append(f"{tr('Pit Stop Time')}: {estimate.pit_seconds:.1f} s ({estimate.pit_stops} {tr('stop(s)')})")
            if estimate.fuel_laps:
                self.setInput("input_fuel_effect", estimate.fuel_effect)
                found.append(f"{tr('Fuel Effect')}: {estimate.fuel_effect:.3f} ({estimate.fuel_laps} {tr('laps')})")
            if estimate.track_laps:
                self.setInput("input_track_evolution", estimate.track_evolution)
                found.append(f"{tr('Track Evolution')}: {estimate.track_evolution:+.2f} s/h")
        self.estimate_text = "<br>".join(found) if found else tr(
            "Not enough laps: stints of 3 laps or more at race pace needed")
        self.notesChanged.emit()

    # Data source: live session or file
    def set_source(self, live: bool, name: str):
        self.live_source = live
        self.source_name = name
        self.headerChanged.emit()

    @Slot()
    def loadLive(self):
        """Laps of live session, race length of a live race and every live value followed (live tab)
        filled in, LMU garage screens asked (filled in once answered)"""
        with self.batch():
            self.show_live_data(fill_inputs=True)
            self.apply_live(followed=True)
        self.set_plan_inputs(False)
        self.refresh_garage(apply=True)

    def show_live_data(self, fill_inputs: bool):
        """History of live session in table, inputs filled in from it (and race length) or kept"""
        history_data = history_laps(minfo.history.consumptionDataSet)
        self._live_signature = history_signature(history_data)
        if fill_inputs:
            self.fill_in_data(history_data, live_race_length(), skip=self.unfollowed_live())
        self.refresh_history(history_data)
        self.set_source(True, api.read.session.combo_name())

    @Slot()
    def loadFile(self):
        """Laps of a consumption history file (or CSV file)"""
        filename_full = self.host.open_file(cfg.path.fuel_delta, ";;".join((FileFilter.CONSUMPTION, FileFilter.CSV)))
        if not filename_full:
            return
        filepath = os.path.dirname(filename_full) + "/"
        filename, extension = os.path.splitext(os.path.basename(filename_full))
        history_data = history_laps(load_consumption_history_file(
            filepath=filepath, filename=filename, extension=extension))
        if not history_data:
            self.host.warn(trm(f"Unable to read consumption history: {filename}{extension}"))
            return
        self.fill_in_data(history_data, live=False)
        self.refresh_history(history_data)
        self.history_file = (filepath, filename, extension)
        self.set_source(False, filename)
        self.set_plan_inputs(False)

    @staticmethod
    def set_plan_inputs(from_plan: bool):
        """Inputs of a race plan (kept when page opens) or of laps (filled in from live laps)"""
        config = cfg.user.config["fuel_calculator"]
        if config.get("enable_plan_inputs") != from_plan:
            config["enable_plan_inputs"] = from_plan
            cfg.save(config_type=ConfigType.CONFIG)

    def set_option(self, name: str, value) -> bool:
        """Option of config "fuel_calculator" kept for next time, True if changed"""
        config = cfg.user.config["fuel_calculator"]
        if config.get(name) == value:
            return False
        config[name] = value
        cfg.save(config_type=ConfigType.CONFIG)
        self.headerChanged.emit()
        return True

    @Slot(bool)
    def setFollowLive(self, checked: bool):
        """Inputs follow new live laps (kept for next time)"""
        self.set_option("enable_follow_live", checked)
        if checked and self.live_source:
            with self.batch():
                self.fill_in_data(history_laps(minfo.history.consumptionDataSet), skip=self.unfollowed_live())
                self.apply_live(followed=True)
        self.update_garage_timer()

    @Slot(bool)
    def setLiveRace(self, checked: bool):
        """During a race: plan of the rest of the race from now"""
        self.set_option("enable_live_race", checked)
        self.refresh_race_state()

    @Slot(bool)
    def setShowHistory(self, checked: bool):
        self.set_option("show_consumption_history", checked)

    @Slot(int)
    def setTab(self, index: int):
        if 0 <= index < len(TABS) and index != self.tab:
            self.tab = index
            self.set_option("race_tab", index)
            self.update_team_timer()
            self.update_garage_timer()
            if index == TABS.index("live"):
                self.publish_live_data()

    @staticmethod
    def collapsed_sections() -> list[str]:
        collapsed = cfg.user.config["fuel_calculator"].get("collapsed_sections", "")
        return [name for name in collapsed.split(",") if name] if isinstance(collapsed, str) else []

    @Slot(str, bool)
    def setSectionCollapsed(self, name: str, collapsed: bool):
        """Input section folded (kept for next time)"""
        names = [item for item in self.collapsed_sections() if item != name] + ([name] if collapsed else [])
        self.set_option("collapsed_sections", ",".join(names))

    # Live session
    def refresh_live(self):
        """Every few seconds: stops counted, and while page shown: new laps, live race state,
        plan of car & track, class rivals"""
        live = read_live(self.unit_fuel, self.stop_counter, self.symbol_fuel)
        if not self.active:
            return
        self.refresh_live_history()
        self.refresh_race_state(live)
        self.auto_load_combo_plan()
        self.refresh_rivals()
        if self.tab == TABS.index("live"):
            self.publish_live_data()
        combo = self.combo_name()
        if combo != self._shown_combo:
            self._shown_combo = combo
            self.headerChanged.emit()

    def refresh_live_history(self):
        """New live laps added to history (inputs left as they are, or followed)"""
        if not self.live_source:
            return
        history_data = history_laps(minfo.history.consumptionDataSet)
        signature = history_signature(history_data)
        if signature != self._live_signature:
            self._live_signature = signature
            self.refresh_history(history_data)
            if cfg.user.config["fuel_calculator"].get("enable_follow_live"):
                with self.batch():
                    self.fill_in_data(history_data, skip=self.unfollowed_live())
                    self.apply_live(followed=True)

    def refresh_race_state(self, live=None):
        """Rest of race planned again at each lap & stop (not while in the pits), status shown
        next to Live Race (values read from the game in its tooltip, to check them)"""
        if live is None:
            live = read_live(self.unit_fuel, self.stop_counter, self.symbol_fuel)
        checked = bool(cfg.user.config["fuel_calculator"].get("enable_live_race"))
        state: RaceState | None = live.state if checked else None
        if not checked:
            status = ""
        elif state is not None:
            status = f"{tr('from lap')} {state.laps_done + 1}" + (f" · {tr('in the pits')}" if live.in_pits else "")
            if api.read.lap.safety_car_active():
                status += f" · {tr('Safety Car')}"
            elif api.read.session.yellow_flag_state() > 0:
                status += f" · {tr('Full Course Yellow')}"
        else:
            status = tr("waiting for the race") if not live.text else tr("waiting for lap 1")
        tip = (f"{tr('Lap')} (+{tr('progress')}) · {tr('race time')} / {tr('time left')} · {tr('fuel')} · "
               f"{tr('energy')} · {tr('tread')} · {tr('stops')} ({tr('game')})<br>{live.text}" if live.text else "")
        if (status, tip) != (self.live_status, self.live_tip):
            self.live_status, self.live_tip = status, tip
            self.liveChanged.emit()
        if state is not None and live.in_pits:
            return
        key = (state.laps_done, state.stops_done) if state is not None else None
        if key != self._race_key:
            self._race_key = key
            self.set_race_state(state)

    @staticmethod
    def race_stints() -> list:
        """Stints of the race in progress (stint history of live session), newest first"""
        if api.read.session.session_type() != RACE_SESSION:
            return []
        return [stint for stint in minfo.history.stintDataSet if stint.totalLaps > 0]

    def race_stint_drivers(self) -> tuple[str, ...]:
        """Driver of each stint of the race in progress (stops counted), oldest first"""
        if api.read.session.session_type() != RACE_SESSION:
            return ()
        return self.stop_counter.stint_drivers()

    def refresh_rivals(self):
        """Cars of the player class in a live race"""
        if api.read.session.session_type() != RACE_SESSION or not api.read.state.active():
            rivals = results.class_rivals([], 0)
        else:
            rivals = results.class_rivals(self.rival_tracker.update(), full_tank_laps(self.plan_setup))
        if rivals != self._rivals:
            self._rivals = rivals
            self.rivalsChanged.emit()

    # Plan of car & track
    @staticmethod
    def combo_name() -> str:
        return api.read.session.combo_name() if api.read.state.active() else ""

    @staticmethod
    def combo_plan_path(combo: str) -> str:
        return f"{cfg.path.fuel_delta}{combo}{FileExt.RACEPLAN}"

    @Slot()
    def saveComboPlan(self):
        """Race plan opened again when this car & track are driven"""
        combo = self.combo_name()
        if combo:
            self.save_race_plan(self.combo_plan_path(combo))
            self._combo_loaded = combo

    @Slot(bool)
    def setAutoComboPlan(self, checked: bool):
        self.set_option("enable_auto_load_combo_plan", checked)
        if checked:
            self.auto_load_combo_plan()

    def auto_load_combo_plan(self):
        """Race plan of car & track driven opened once per car & track"""
        if not cfg.user.config["fuel_calculator"].get("enable_auto_load_combo_plan", True):
            return
        combo = self.combo_name()
        if not combo or combo == self._combo_loaded:
            return
        self._combo_loaded = combo
        filename = self.combo_plan_path(combo)
        if os.path.exists(filename) and self.load_race_plan(filename, quiet=True):
            self.host.toast(trm(f"Race plan of {combo} opened"))

    # Race plan file: race setup, fuel & tyre plan
    def race_plan_data(self) -> dict:
        inputs = self.input_values()
        inputs["input_measured_compound"] = self.measured_index
        return {
            "format": RACE_PLAN_FORMAT,
            "version": RACE_PLAN_VERSION,
            "plan_name": self.tyres.name,
            "fuel_unit": self.fuel_unit,  # of fuel inputs, converted when opened in another unit
            "inputs": inputs,
            "tyre_strategy": self.tyres.capture_data(),
        }

    @Slot()
    def saveRacePlan(self):
        self.save_race_plan()

    def save_race_plan(self, filename_full: str = ""):
        """Save race plan file (asked when no file name given)"""
        if not filename_full:
            name = self.tyres.name or tr("Untitled plan")
            filename_full = self.host.save_file(set_tyre_strategy_file_path(f"{name}{FileExt.RACEPLAN}"),
                                                FileFilter.RACEPLAN)
            if not filename_full:
                return
            save_tyre_strategy_file_path(os.path.dirname(filename_full) + "/")
        if not write_text_file(filename_full, json.dumps(self.race_plan_data(), indent=4)):
            self.host.warn(trm(f"Unable to save race plan:<br><b>{filename_full}</b>"))
            return
        self.host.toast(trm(f"Race plan saved at:<br><b>{filename_full}</b>"))

    @Slot()
    def openRacePlan(self):
        self.load_race_plan()

    def load_race_plan(self, filename_full: str = "", quiet: bool = False) -> bool:
        """Open race plan file (asked when no file name given): race setup, fuel & tyre plan
        replaced (undoable), True once opened"""
        if not filename_full:
            filename_full = self.host.open_file(set_tyre_strategy_file_path(), FileFilter.RACEPLAN)
            if not filename_full:
                return False
            save_tyre_strategy_file_path(os.path.dirname(filename_full) + "/")
        try:
            with open(filename_full, encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError):
            data = None
        if not self.apply_race_plan(data, os.path.splitext(os.path.basename(filename_full))[0]):
            if not quiet:
                self.host.warn(trm(f"Invalid race plan file: {os.path.basename(filename_full)}"))
            return False
        return True

    def apply_race_plan(self, data, name: str, unitless_fuel: str = "") -> bool:
        """Race setup, fuel & tyre plan of race plan data replaced, False if not a race plan

        Args:
            unitless_fuel: fuel unit of plan saved without one (older version): share codes are
                litres, own plan files were saved in fuel unit of page (default).
        """
        try:
            if not isinstance(data, dict) or data.get("format") != RACE_PLAN_FORMAT:
                raise ValueError
            inputs: dict = data["inputs"] if isinstance(data.get("inputs"), dict) else {}
            tyre_data = validate_tyre_strategy(data.get("tyre_strategy") or {})
        except (ValueError, TypeError, AttributeError):
            return False
        # Inputs checked & in the fuel unit of the page (plan without unit: see unitless_fuel)
        # before anything is applied: never half applied
        plan_unit = data.get("fuel_unit") or unitless_fuel or self.fuel_unit
        values = ranged_inputs(convert_fuel_inputs(checked_inputs(inputs), plan_unit, self.fuel_unit))
        # One calculation with the whole plan loaded: rows of the new tyre plan follow the new
        # stints, not the ones of the plan replaced (whose rows kept aside are dropped)
        with self.batch():
            index = inputs.get("input_measured_compound", MEASURED_DEFAULT)
            if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(DEFAULT_TYRE_SET):
                self.measured_index = index
                self.tyres.measured = tuple(DEFAULT_TYRE_SET)[index]
            self.tyres.load(tyre_data, str(data.get("plan_name") or name))
            self.values = values
            self.tyresChanged.emit()
        self.autosave_tyres()
        self.set_plan_inputs(True)
        return True

    # Share code: race plan in one line of text
    @Slot()
    def copyShareCode(self):
        QGuiApplication.clipboard().setText(encode_share_code(self.race_plan_data()))
        self.host.toast(tr("Share code of race plan copied"))

    @Slot()
    def pasteShareCode(self):
        """Race plan of a share code (clipboard proposed)"""
        text, accepted = self.host.ask_text(tr("Paste Share Code..."), tr("Race plan share code:"),
                                            QGuiApplication.clipboard().text().strip())
        if not accepted or not text.strip():
            return
        try:
            data = decode_share_code(text)
        except ValueError:
            data = None
        if not self.apply_race_plan(data, tr("Shared plan"), unitless_fuel="Liter"):
            self.host.warn(tr("Invalid race plan share code."))
            return
        self.host.toast(tr("Race plan of share code opened"))

    # Pit stop plan export
    def plan_columns(self) -> list[int]:
        """Columns of the plan shown in the page (indexes of PLAN_COLUMNS)"""
        hidden = results.plan_hidden(self.strategy, self.values["input_energy_per_lap"] > 0,
                                     self.values["input_drivers"])
        return [index for index, key in enumerate(results.PLAN_COLUMNS) if key not in hidden]

    def visible_plan(self) -> tuple[list[str], list[tuple[str, ...]]]:
        """Header & rows of the plan, columns hidden in the page left out"""
        columns = self.plan_columns()
        header = results.plan_header(self.symbol_fuel)
        rows = results.plan_rows(self.strategy, self.values["input_energy_per_lap"] > 0, self.time_text,
                                 self.plan_setup.clock_offset)
        return [header[column] for column in columns], [tuple(row[column] for column in columns) for row in rows]

    def plan_text(self) -> str:
        return results.plan_text(self.strategy, self.symbol_fuel, self.values["input_energy_per_lap"] > 0,
                                 self.values["input_drivers"], self.time_text)

    @Slot()
    def copyPlanText(self):
        QGuiApplication.clipboard().setText(self.plan_text())
        self.host.toast(tr("Pit stop plan copied"))

    @Slot()
    def copyPlanMarkdown(self):
        """Pit stop plan for Discord (table in a code block)"""
        header, rows = self.visible_plan()
        QGuiApplication.clipboard().setText(plan_markdown(
            results.plan_title(self.strategy), header, rows, results.plan_footer(self.strategy)))
        self.host.toast(tr("Pit stop plan copied"))

    @staticmethod
    def export_folder() -> str:
        """Folder of last export (CSV, image), config folder at first"""
        folder = cfg.user.config["fuel_calculator"].get("export_path", "")
        return folder if isinstance(folder, str) and folder and os.path.isdir(folder) else cfg.path.config

    @staticmethod
    def keep_export_folder(filename: str):
        folder = os.path.dirname(filename) + "/"
        config = cfg.user.config["fuel_calculator"]
        if config.get("export_path") != folder:
            config["export_path"] = folder
            cfg.save(config_type=ConfigType.CONFIG)

    @Slot()
    def exportPlanCsv(self):
        """Pit stop plan as spreadsheet"""
        filename = self.host.save_file(os.path.join(self.export_folder(), f"{tr('Pit Stop Plan')}.csv"),
                                       FileFilter.CSV)
        if not filename:
            return
        header, rows = self.visible_plan()
        try:
            write_plan_csv(filename, header, rows)
        except OSError as error:  # file open in a spreadsheet, read-only folder
            self.host.warn(trm(f"Unable to export: {error}"))
            return
        self.keep_export_folder(filename)

    def plan_image(self):
        """Strategy timeline & pit stop plan as a picture"""
        from .race_picture import plan_picture

        header, rows = self.visible_plan()
        columns = self.plan_columns()
        tyres = results.PLAN_COLUMNS.index("tyres")
        return plan_picture(results.plan_title(self.strategy), self.symbol_fuel, self.sections.get("timeline", {}),
                            header, rows, results.plan_footer(self.strategy),
                            tyres_column=columns.index(tyres) if tyres in columns else -1)

    @Slot()
    def savePlanImage(self):
        """Strategy & pit stop plan as image (to share)"""
        filename = self.host.save_file(os.path.join(self.export_folder(), f"{tr('Pit Stop Plan')}.png"),
                                       FileFilter.PNG)
        if not filename:
            return
        if not self.plan_image().save(filename, "PNG"):
            self.host.warn(trm(f"Unable to save picture: {filename}"))
            return
        self.keep_export_folder(filename)

    @Slot()
    def copyPlanImage(self):
        """Strategy & pit stop plan as image in the clipboard (to paste in Discord)"""
        QGuiApplication.clipboard().setImage(self.plan_image())
        self.host.toast(tr("Plan image copied"))

    # Race plan widget input (plan made again with race calculator closed)
    def plan_file_data(self) -> dict:
        return {"version": 1, "setup": asdict(self.race_setup), "tyre_changes": list(self.race_tyre_changes)}

    def schedule_plan_file(self):
        """Plan input written for the race plan widget once changed (not at every key)"""
        data = self.plan_file_data()
        if data != self._plan_file_data:
            self._plan_file_data = data
            self._plan_file_timer.start()

    def flush_plan_file(self):
        """Plan input change not written yet: written now (page closed)"""
        if self._plan_file_timer.isActive():
            self._plan_file_timer.stop()
            self.write_plan_file()

    def write_plan_file(self):
        try:
            with atomic_write(f"{cfg.path.config}{PLAN_FILE}") as file:
                json.dump(self._plan_file_data, file)
        except OSError:
            pass

    # Consumption history
    def refresh_history(self, dataset: Sequence[ConsumptionDataSet]):
        """Laps of history (newest first): new laps of a live session get new serials, laps kept
        keep theirs (selection kept), oldest dropped when history is full"""
        dataset = list(dataset)
        old = self.history_data
        added = next((count for count in range(1, min(len(dataset), 5) + 1)
                      if old and dataset[count:] == old[:len(dataset) - count]), 0)
        selection = self.history_selection
        if added:
            newest = self.history_serials[0] if self.history_serials else -1
            kept = self.history_serials[:len(dataset) - added]
            self.history_serials = [newest + added - offset for offset in range(added)] + kept
        elif dataset != old:
            self.history_serials = list(range(len(dataset) - 1, -1, -1))
            self._history_cache.clear()  # same serials, other laps
            selection = set()
        self.history_data = dataset
        self.set_history_selection(selection & set(self.history_serials), notify_rows=False)
        self.publish_history()

    def publish_history(self, rows: bool = True):
        """History shown again: rows synced in place by serial (rows=False: view only, rows unchanged),
        view (columns, sort...) notified only when changed"""
        if rows:
            serials = set(self.history_serials)
            self._history_cache = {serial: item for serial, item in self._history_cache.items() if serial in serials}
            selection = self.history_selection
            self.history_model.sync([
                {"serial": row["serial"], "valid": row["valid"], "cells": row["cells"],
                 "selected": row["serial"] in selection}
                for row in self.history_rows()], key="serial")
        view = self.history_view()
        if view != self._history_view:
            self._history_view = view
            self.historyViewChanged.emit()
        self.historyChanged.emit()

    def set_history_selection(self, selection: set[int], notify_rows: bool = True):
        """Selected laps (serials): selected role of rows changed in place, notified only when changed"""
        if selection == self.history_selection:
            return
        self.history_selection = selection
        if notify_rows:
            self.history_model.update_rows(lambda row: {"selected": row["serial"] in selection})
        self.historySelectionChanged.emit()

    def shown_serials(self) -> list[int]:
        """Serials of the laps shown, in their order (last rows published)"""
        return [row["serial"] for row in self.history_model.rows]

    def history_columns(self) -> list[dict]:
        config = cfg.user.config["fuel_calculator"]
        symbol = self.symbol_fuel
        units_of = {"fuel": f" ({symbol})", "energy": " (%)", "drain": " (%)", "regen": " (%)", "net": " (%)",
                    "tyre": " (%)", "tank": f" ({symbol})"}
        return [{"key": key, "title": tr(title) + units_of.get(key, ""), "option": option,
                 "visible": not option or bool(config.get(option, True))} for key, title, option in HISTORY_COLUMNS]

    def history_row(self, lap: ConsumptionDataSet, serial: int) -> dict:
        """Row of a lap, formatted once per lap (kept while its serial is the same lap): never changed"""
        cached = self._history_cache.get(serial)
        if cached is not None and (cached[0] is lap or cached[0] == lap):
            return cached[1]
        row = self.format_history_row(lap, serial)
        self._history_cache[serial] = (lap, row)
        return row

    def format_history_row(self, lap: ConsumptionDataSet, serial: int) -> dict:
        fuel = self.unit_fuel(lap.lastLapUsedFuel)
        ratio = calc.fuel_to_energy_ratio(lap.lastLapUsedFuel, lap.lastLapUsedEnergy)
        net = lap.batteryRegenLast - lap.batteryDrainLast
        tank = self.unit_fuel(lap.capacityFuel)
        values = (lap.lapNumber, lap.lapTimeLast, fuel, lap.lastLapUsedEnergy, ratio, lap.batteryDrainLast,
                  lap.batteryRegenLast, net, lap.tyreAvgWearLast, tank)
        cells = [f"{lap.lapNumber}", calc.sec2laptime_full(lap.lapTimeLast), f"{fuel:.3f}",
                 f"{lap.lastLapUsedEnergy:.3f}", f"{ratio:.3f}", f"{lap.batteryDrainLast:.3f}",
                 f"{lap.batteryRegenLast:.3f}", f"{net:+.3f}", f"{lap.tyreAvgWearLast:.3f}", f"{tank:.3f}"]
        return {"serial": serial, "valid": bool(lap.isValidLap), "cells": cells, "values": values}

    def history_rows(self) -> list[dict]:
        """Rows shown: invalid laps left out (valid only), sorted by column clicked"""
        valid_only = bool(cfg.user.config["fuel_calculator"].get("enable_valid_laps_only"))
        rows = [self.history_row(lap, serial) for lap, serial in zip(self.history_data, self.history_serials)
                if lap.isValidLap or not valid_only]
        if 0 <= self.sort_column < len(HISTORY_COLUMNS):
            rows.sort(key=lambda row: row["values"][self.sort_column], reverse=not self.sort_ascending)
        return rows

    def history_view(self) -> dict:
        """History table without its rows (see historyRows)"""
        return {
            "columns": self.history_columns(), "empty": not self.history_data,
            "sortColumn": self.sort_column, "sortAscending": self.sort_ascending,
            "validOnly": bool(cfg.user.config["fuel_calculator"].get("enable_valid_laps_only")),
            "invalidColor": INVALID_COLOR,
            "menu": [{"option": option, "title": tr(COLUMN_OPTION_TITLES[option]),
                      "checked": bool(cfg.user.config["fuel_calculator"].get(option, True))}
                     for _, _, option in HISTORY_COLUMNS if option],
        }

    @Slot(int)
    def sortHistory(self, column: int):
        """Laps sorted by a column (numbers by value), clicked again: other way"""
        if column == self.sort_column:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_column, self.sort_ascending = column, True
        self.publish_history()

    @Slot(bool)
    def setValidOnly(self, checked: bool):
        """Invalid laps hidden (kept for next time)"""
        self.set_option("enable_valid_laps_only", checked)
        if checked:
            valid = {serial for lap, serial in zip(self.history_data, self.history_serials) if lap.isValidLap}
            self.set_history_selection(self.history_selection & valid)
        self.publish_history()

    @Slot(str)
    def toggleHistoryColumn(self, option: str):
        if option in COLUMN_OPTION_TITLES:
            config = cfg.user.config["fuel_calculator"]
            self.set_option(option, not config.get(option, True))
            self.publish_history(rows=False)  # rows hold every column

    @Slot(int, int)
    def selectLap(self, serial: int, mode: int):
        """Lap clicked: mode 0 alone, 1 added or removed (Ctrl), 2 range from last clicked (Shift)"""
        shown = self.shown_serials()
        if serial not in shown:
            return
        if mode == 1:
            selection = self.history_selection ^ {serial}
            self._history_anchor = serial
        elif mode == 2 and self._history_anchor in shown:
            first, last = sorted((shown.index(self._history_anchor), shown.index(serial)))
            selection = self.history_selection | set(shown[first:last + 1])
        else:
            selection = {serial}
            self._history_anchor = serial
        self.set_history_selection(selection)

    @Slot()
    def selectAllLaps(self):
        self.set_history_selection(set(self.shown_serials()))

    @Slot()
    def clearLapSelection(self):
        self.set_history_selection(set())

    def selected_indexes(self) -> set[int]:
        """Indexes in history data of selected laps"""
        return {index for index, serial in enumerate(self.history_serials) if serial in self.history_selection}

    @Slot()
    def addSelectedLaps(self):
        """Average of selected valid laps filled in"""
        selected = [self.history_data[index] for index in sorted(self.selected_indexes())]
        if not selected:
            self.host.warn(tr("No data selected."))
            return
        used = [lap for lap in selected if lap.isValidLap]
        skipped = len(selected) - len(used)
        if not used:
            self.host.warn(tr("Selected laps are all invalid."))
            return
        with self.batch():
            self.setInput("input_lap_time", calc.dataset_mean([lap.lapTimeLast for lap in used]))
            self.setInput("input_fuel_per_lap", calc.dataset_mean([self.unit_fuel(lap.lastLapUsedFuel) for lap in used]))
            self.setInput("input_energy_per_lap", calc.dataset_mean([lap.lastLapUsedEnergy for lap in used]))
            self.setInput("input_wear_per_lap", calc.dataset_mean([lap.tyreAvgWearLast for lap in used]))
            capacity = max(self.unit_fuel(lap.capacityFuel) for lap in used)
            if capacity:
                self.setInput("input_tank_capacity", capacity)
        self.fill_source = trm(f"Average of {len(used)} selected lap(s)")
        text = trm(f"Average of {len(used)} lap(s) added")
        if skipped:
            text += " · " + trm(f"{skipped} invalid lap(s) left out")
        self.history_added = text
        self.notesChanged.emit()

    @Slot()
    def deleteSelectedLaps(self):
        self.delete_laps(self.selected_indexes())

    @Slot()
    def deleteAllLaps(self):
        self.delete_laps(None)

    def delete_laps(self, indexes: set[int] | None):
        """Delete laps (indexes in history data), or whole history (None), after confirmation"""
        dataset = self.history_data
        if indexes is not None and not indexes:
            self.host.warn(tr("No data selected."))
            return
        removed = [lap for index, lap in enumerate(dataset) if indexes is None or index in indexes]
        kept_index = [index for index in range(len(dataset)) if indexes is not None and index not in indexes]
        kept = [dataset[index] for index in kept_index]
        if not removed:
            return
        message = (trm(f"Delete <b>{len(removed)}</b> lap(s) from consumption history?")
                   if indexes is not None else tr("<b>Delete whole consumption history?</b>"))
        if not self.host.confirm(message + "<br><br>" + trm("This cannot be undone!")):
            return
        if self.live_source:
            history = minfo.history.consumptionDataSet
            history.append(ConsumptionDataSet())  # never empty while module reads it
            for lap in removed:
                if lap in history:
                    history.remove(lap)
            while len(history) > 1 and not history_laps([history[-1]]):
                history.pop()  # placeholder no longer needed
            minfo.history.consumptionDataVersion += 1
            filepath, filename, extension = cfg.path.fuel_delta, api.read.session.combo_name(), FileExt.CONSUMPTION
        else:
            filepath, filename, extension = self.history_file
        if filename and not write_history(filepath, filename, extension, kept):
            self.host.warn(trm(f"Unable to save consumption history: {filename}{extension}"))
            if not self.live_source:
                return  # file unchanged: laps still listed
        serials = [self.history_serials[index] for index in kept_index]
        self.history_data, self.history_serials = kept, serials
        self.set_history_selection(self.history_selection & set(serials), notify_rows=False)
        self._live_signature = history_signature(kept)
        self.history_added = trm(f"{len(removed)} lap(s) deleted")
        self.publish_history()
        self.notesChanged.emit()

    # Tyre plan
    def tyre_plan_changed(self, user_edit: bool = True):
        """Tyre plan edited: page marked modified (user edit), kept, strategy calculated again
        (tyre change time)"""
        if user_edit:
            self.host.set_modified()
        self.tyresChanged.emit()
        self._autosave_timer.start()
        self.update_input()

    def autosave_path(self) -> tuple[str, str]:
        return cfg.path.config, f"{AUTOSAVE_NAME}{FileExt.TYRESTRATEGY}"

    def autosave_tyres(self):
        """Tyre plan saved to config folder, reopened next time"""
        self._autosave_timer.stop()
        filepath, filename = self.autosave_path()
        try:
            save_tyre_strategy_file(dict_user=self.tyres.capture_data(), filename=filename, filepath=filepath)
        except OSError:
            return
        config = cfg.user.config["tyre_strategy_planner"]
        if config.get("last_file_name") != self.tyres.name:
            config["last_file_name"] = self.tyres.name
            cfg.save(config_type=ConfigType.CONFIG)

    def load_tyre_autosave(self):
        """Tyre plan of last time, new plan if none"""
        filepath, filename = self.autosave_path()
        user_data = load_tyre_strategy_file(filepath=filepath, filename=filename) \
            if os.path.exists(f"{filepath}{filename}") else None
        if user_data is None:
            self.tyres.new_plan()
            return
        self.tyres.load(user_data, cfg.user.config["tyre_strategy_planner"].get("last_file_name") or tr("Untitled plan"))

    @Slot(str, "QVariant")
    def setTyreRule(self, key: str, value: Any):
        if self.tyres.set_rule(key, value):
            self.tyre_plan_changed()

    @Slot(bool)
    def setHighlightNew(self, checked: bool):
        self.tyres.highlight_new = checked
        self.tyresChanged.emit()

    @Slot(str)
    def setStockCompound(self, name: str):
        """Compound added to stock, and of proposed tyre changes (strategy wear follows)"""
        if name in self.tyres.compounds and name != self.tyres.compound:
            self.tyres.compound = name
            self.tyres.forget_stints()
            self.tyres.refresh()
            self.tyre_plan_changed(user_edit=False)

    @Slot(str)
    def setPlanName(self, name: str):
        name = "".join(char for char in name if char not in '\\/:*?"<>|').strip()
        if name and name != self.tyres.name:
            self.tyres.name = name
            self.tyresChanged.emit()
            self._autosave_timer.start()

    @Slot(int, int, str)
    def assignTyre(self, row: int, corner: int, name: str):
        """Tyre of stock dropped (or picked) on a wheel of a stint"""
        error = self.tyres.assign(row, corner, name)
        if error:
            self.host.toast(error)
            return
        self.tyre_plan_changed()

    @Slot(int, int)
    def clearTyre(self, row: int, corner: int):
        self.tyres.clear_cells([(row, corner)])
        self.tyre_plan_changed()

    @Slot(int)
    def clearRow(self, row: int):
        self.tyres.clear_cells([(row, corner) for corner in range(WHEELS)])
        self.tyre_plan_changed()

    @Slot(int, bool)
    def insertRow(self, row: int, above: bool):
        """New empty row above or below a row (manual plan)"""
        self.tyres.insert_row(row if above else row + 1)
        self.tyre_plan_changed()

    @Slot()
    def addRow(self):
        self.tyres.insert_row(-1)
        self.tyre_plan_changed()

    @Slot(int)
    def duplicateRow(self, row: int):
        self.tyres.insert_row(row + 1, copy_from=row)
        self.tyre_plan_changed()

    @Slot(int)
    def deleteRow(self, row: int):
        if self.host.confirm(tr("<b>Delete selected row?</b>")):
            self.tyres.delete_rows([row])
            self.tyre_plan_changed()

    @Slot()
    def proposeChanges(self):
        """New tyres where the strategy proposes them (minimum tread), within tyres allowed"""
        if self.tyres.has_tyres() and not self.host.confirm(tr("<b>Replace tyre plan with proposed changes?</b>")):
            return
        self.tyres.propose()
        self.tyre_plan_changed()

    @Slot()
    def addTyre(self):
        self.tyres.add_tyre()
        self.tyre_plan_changed()

    @Slot(str)
    def removeTyre(self, name: str):
        """Tyre taken out of stock (and off the plan) after confirmation"""
        if self.host.confirm("<b>Remove selected tyre from list?</b><br><br>"  # translated by message rules
                             "Corresponding tyre will be removed from table."):
            self.tyres.remove_tyres([name])
            self.tyre_plan_changed()

    @Slot()
    def clearTyres(self):
        if self.tyres.stock and self.host.confirm("<b>Remove all tyres from list?</b><br><br>"  # message rules
                                                  "All allocated tyres will be removed from table."):
            self.tyres.remove_tyres(list(self.tyres.stock))
            self.tyre_plan_changed()

    @Slot()
    def removeUnusedTyres(self):
        unused = self.tyres.unused_tyres()
        if unused:
            self.tyres.remove_tyres(unused)
            self.tyre_plan_changed()

    @Slot(bool)
    def sortStock(self, by_stints: bool):
        self.tyres.sort_stock(by_stints)
        self.tyre_plan_changed()

    @Slot()
    def newTyrePlan(self):
        if self.tyres.has_tyres() and not self.host.confirm(tr("<b>Start a new tyre plan?</b>")):
            return
        self.tyres.new_plan()
        self.tyre_plan_changed(user_edit=False)

    @Slot()
    def openTyrePlan(self):
        """Tyre strategy file opened"""
        filename_full = self.host.open_file(set_tyre_strategy_file_path(), FileFilter.TYRESTRATEGY)
        if not filename_full:
            return
        filepath = os.path.dirname(filename_full) + "/"
        filename = os.path.basename(filename_full)
        user_data = load_tyre_strategy_file(filepath=filepath, filename=filename)
        if user_data is None:
            self.host.warn(trm("Cannot open selected file.<br><br>Invalid tyre strategy file."))
            return
        save_tyre_strategy_file_path(filepath)
        self.tyres.load(user_data, os.path.splitext(filename)[0])
        self.tyre_plan_changed(user_edit=False)

    @Slot()
    def saveTyrePlan(self):
        """Tyre strategy file saved"""
        filename_full = self.host.save_file(set_tyre_strategy_file_path(self.tyres.name or tr("Untitled plan")),
                                            FileFilter.TYRESTRATEGY)
        if not filename_full:
            return
        filepath = os.path.dirname(filename_full) + "/"
        filename = os.path.basename(filename_full)
        try:
            save_tyre_strategy_file(dict_user=self.tyres.file_data(), filename=filename, filepath=filepath)
        except OSError as error:  # file locked by another program, read-only folder
            self.host.warn(trm(f"Unable to save tyre strategy file:<br><br>{error}"))
            return
        save_tyre_strategy_file_path(filepath)
        self.tyres.name = os.path.splitext(filename)[0]
        self.tyresChanged.emit()
        self.host.set_unmodified()
        self.host.toast(trm(f"Tyre strategy file saved at:<br><b>{filename_full}</b>"))

    @Slot()
    def exportTyrePlanCsv(self):
        """Tyre strategy as spreadsheet (CSV): rules, stock, plan with tread of each wheel"""
        filename_full = self.host.save_file(set_tyre_strategy_file_path(self.tyres.name or tr("Untitled plan")),
                                            FileFilter.CSV)
        if not filename_full:
            return
        from ...formatter import format_option_name
        from ...userfile.tyre_strategy import HEADER_TYREPLAN

        rule = self.tyres.rule
        rule_data = [[format_option_name(name) for name in rule], list(rule.values())]
        stock_data: list[list] = [["Tyre Stock", "Stints"]]
        stock_data += [[name, self.tyres.uses[name]] for name in self.tyres.stock]
        header = ["Stint"]
        for index, name in enumerate(HEADER_TYREPLAN):
            header.append(name)
            if index < WHEELS:
                header.append("Tread (%)")
        plan_data: list[list] = [header]
        for row_index, row in enumerate(self.tyres.rows):
            line: list = [row_index + 1]
            for corner, name in enumerate(row):
                line.append(name)
                info = self.tyres.cells[row_index][corner] if row_index < len(self.tyres.cells) else {}
                line.append(f"{info['remaining'] * 100:.2f} - {max(info['end'], 0.0) * 100:.2f}" if info else "0.0")
            seconds = self.tyres.change_times[row_index] if row_index < len(self.tyres.change_times) else 0.0
            line.append(f"{seconds:+.1f}s" if seconds > 0 else tr("N/A"))
            plan_data.append(line)
        filepath = os.path.dirname(filename_full) + "/"
        try:
            export_tyre_strategy_file(rule_data=rule_data, stock_data=stock_data, plan_data=plan_data,
                                      filename=os.path.basename(filename_full), filepath=filepath)
        except OSError as error:  # file open in a spreadsheet, read-only folder
            self.host.warn(trm(f"Unable to export: {error}"))
            return
        save_tyre_strategy_file_path(filepath)
        self.host.toast(trm(f"Tyre strategy file exported at:<br><b>{filename_full}</b>"))

    @Slot()
    def configureCompound(self):
        """Starting tread & wear per stint of compound selected in stock"""
        self.host.open_compound_config(self.tyres.compound, self.tyres.user_data["tyre_set"], self.compound_changed)

    def compound_changed(self, *_):
        self.tyres.forget_stints()
        self.tyres.refresh()
        self.tyre_plan_changed()

    @Slot()
    def tyreAllocationFromGame(self):
        """Tyres allowed by the session asked to game (LMU)"""
        if self.tyre_request.start():
            self.tyresChanged.emit()

    @Property(bool, notify=tyresChanged)
    def askingGame(self) -> bool:
        return self.tyre_request.busy

    def received_allocation(self, answers: list):
        allocation = game_tyre_allocation(answers[0])
        self.tyre_request.busy = False
        if allocation is None:
            self.tyresChanged.emit()
            self.host.toast(tr("No tyre allocation from game: LMU not running or not in a session"))
            return
        self.setTyreRule("maximum_tyre", allocation.maximum)
        self.tyresChanged.emit()
        self.host.toast(trm(f"Tyre allocation from game: {allocation.maximum} tyre(s), {allocation.new_left} new left"))

    def allocation_request_failed(self):
        """Game request raised an error: busy indicator cleared"""
        self.tyre_request.busy = False
        self.tyresChanged.emit()
        self.host.toast(tr("No tyre allocation from game: LMU not running or not in a session"))

    # Undo & redo: inputs & tyre plan
    def capture_state(self) -> dict:
        return {"tyres": self.tyres.capture_state(), "inputs": self.input_values(), "measured": self.measured_index}

    def restore_state(self, state: dict):
        with self.batch():
            self.tyres.restore_state(state["tyres"])
            self.values = dict(state["inputs"])
            index = state.get("measured", self.measured_index)
            self.measured_index = index
            self.tyres.measured = tuple(DEFAULT_TYRE_SET)[index]
        self.tyresChanged.emit()
        self._autosave_timer.start()

    @Slot()
    def undo(self):
        self.host.undo()

    @Slot()
    def redo(self):
        self.host.redo()

    # Live game data (live tab): every input value the game gives, see race_live_data
    @Property(dict, notify=liveDataChanged)
    def liveData(self) -> dict:
        return self._live_view

    @staticmethod
    def unfollowed_live() -> set[str]:
        """Live values the user turned off: left out of Load Live, Follow Live & Fill In All"""
        text = cfg.user.config["fuel_calculator"].get("live_unfollowed", "")
        return {key for key in text.split(",") if key} if isinstance(text, str) else set()

    def update_garage_timer(self):
        """LMU garage screens asked at once, then every few seconds while the live tab is shown or
        inputs follow live"""
        follow = bool(cfg.user.config["fuel_calculator"].get("enable_follow_live"))
        if self.active and (self.tab == TABS.index("live") or follow):
            if not self._garage_timer.isActive():
                self._garage_timer.start()
                self.refresh_garage()
        else:
            self._garage_timer.stop()

    @Slot()
    def refreshGarage(self):
        self.refresh_garage()
        self.publish_live_data()

    def refresh_garage(self, apply: bool = False):
        """LMU garage screens asked (game in a session only), apply: followed values filled in once
        answered"""
        if not api.read.state.active():
            self._apply_garage = False
            if self.garage != GarageData():  # values of a session left behind
                self.garage = GarageData()
                self.garage_time = ""
            return
        if apply:
            self._apply_garage = True
        self.garage_request.start()

    def received_garage(self, answers: list):
        """Game answers: repair & refuel screen, tyre screen, session settings"""
        self.garage_request.busy = False
        refuel, tyres, session = (list(answers) + [None] * 3)[:3]
        self.garage = parse_garage(refuel, tyres, session)
        self.garage_time = time.strftime("%H:%M:%S") if self.garage.available else ""
        apply = self._apply_garage or bool(cfg.user.config["fuel_calculator"].get("enable_follow_live"))
        self._apply_garage = False
        if apply and self.garage.available and self.live_source:
            self.apply_live(followed=True)
        self.publish_live_data()

    def garage_request_failed(self):
        """Game request raised an error: asked again by the garage timer"""
        self.garage_request.busy = False
        self._apply_garage = False
        self.publish_live_data()

    def dry_plan_laps(self) -> int:
        """Laps of the whole race plan without rain scenario (wet laps of the forecast), from the
        inputs of now (not the last calculation: values filled in together agree)"""
        setup = replace(self.strategy_input(), rain_lap=0, rain_laps=0, rain_tyres=False,
                        tyre_change_seconds=self.tyres.full_change_seconds())
        strategy = plan(setup)
        return strategy.race_laps if strategy.ready else 0

    def collect_live_values(self) -> list[LiveValue]:
        return collect_live(history_laps(minfo.history.consumptionDataSet), self.garage, self.unit_fuel,
                            self.symbol_fuel, self.dry_plan_laps(), tuple(DEFAULT_TYRE_SET))

    def apply_live(self, keys: set[str] | None = None, followed: bool = False, filled: bool = False) -> int:
        """Live values filled in: those of keys, or every value followed (filled: values Load Live
        fills in from laps too), count filled in"""
        unfollowed = self.unfollowed_live()

        def wanted(item: LiveValue) -> bool:
            if item.value is None:
                return False
            if keys is not None:
                return item.key in keys
            return (followed and item.follow and item.key not in unfollowed
                    and (filled or item.key not in FILLED_KEYS))

        count = 0
        with self.batch():
            for item in self.collect_live_values():
                if item.key != "rain" and wanted(item) and not self.live_matches(item):
                    self.apply_live_value(item)
                    count += 1
            # Rain laps last: race laps follow the values just filled in
            rain = next((item for item in self.collect_live_values() if item.key == "rain"), None)
            if rain is not None and wanted(rain) and not self.live_matches(rain):
                self.apply_live_value(rain)
                count += 1
        return count

    def apply_live_value(self, item: LiveValue):
        """One live value filled in (inputs, tyre rules or rain scenario)"""
        key, value = item.key, item.value
        if key == "race_length":
            kind, length = value
            self.setInput("input_race_laps" if kind == "laps" else "input_race_minutes", length)
            self.setInput("enable_lap_race", kind == "laps")
        elif key == "input_measured_compound":
            self.set_measured_compound(int(value))
        elif key in ("tyre_change_times", "maximum_tyre"):
            rules: tuple[tuple[str, Any], ...]
            if key == "maximum_tyre":
                rules = (("maximum_tyre", value),)
            else:
                two, four = value
                rules = (("tyre_change_time_1", two), ("tyre_change_time_2", two),
                         ("tyre_change_time_3", four), ("tyre_change_time_4", four))
            changed = False
            for rule, number in rules:
                changed |= self.tyres.set_rule(rule, number)
            if changed:
                self.tyre_plan_changed(user_edit=False)
        elif key == "rain":
            wet, first, laps = value
            self.setInput("enable_rain", bool(wet))
            if wet:
                self.setInput("input_rain_lap", first)
                self.setInput("input_rain_laps", laps)
        else:
            self.setInput(key, value)

    def live_matches(self, item: LiveValue) -> bool:
        """Calculator already holds the live value (to the decimals of the input)"""
        key, value, values = item.key, item.value, self.values
        if value is None:
            return True
        if key == "race_length":
            kind, length = value
            laps = kind == "laps"
            return values["enable_lap_race"] == laps and values["input_race_laps" if laps else "input_race_minutes"] == length
        if key == "input_measured_compound":
            return self.measured_index == value
        rule = self.tyres.rule
        if key == "tyre_change_times":
            two, four = value
            return all(abs(float(rule[f"tyre_change_time_{count}"]) - seconds) < 0.05
                       for count, seconds in ((1, two), (2, two), (3, four), (4, four)))
        if key == "maximum_tyre":
            return int(rule["maximum_tyre"]) == value
        if key == "rain":
            wet, first, laps = value
            if not wet:
                return not values["enable_rain"]
            return bool(values["enable_rain"]) and values["input_rain_lap"] == first and values["input_rain_laps"] == laps
        current = values.get(key)
        if isinstance(value, bool) or isinstance(current, bool):
            return bool(current) == bool(value)
        spec = INPUT_SPECS.get(key)
        decimals = spec.decimals if spec is not None else 3
        if not isinstance(current, (int, float)):
            return False
        return abs(float(current) - float(value)) < 0.5 * 10 ** -decimals + 1e-9

    def live_current(self, key: str) -> str:
        """Value of the calculator a live value would replace, as text"""
        values, symbol = self.values, self.symbol_fuel
        rule = self.tyres.rule
        if key == "race_length":
            if values["enable_lap_race"]:
                return trm(f"{values['input_race_laps']} laps")
            return f"{values['input_race_minutes']} min"
        if key == "input_formation_laps":
            return trm(f"{values[key]:g} lap(s)")
        if key == "input_race_start_minutes":
            return start_time_text(values[key]) if values[key] >= 0 else results.DASH
        if key == "input_drivers":
            return f"{values[key]}"
        if key == "input_lap_time":
            return laptime_text(values[key])
        if key == "input_measured_compound":
            return tuple(DEFAULT_TYRE_SET)[self.measured_index]
        if key in ("input_fuel_start", "input_energy_start") and values[key] <= 0:
            return tr("Full Tank")
        if key == "tyre_change_times":
            return f"{float(rule['tyre_change_time_2']):.1f} s / {float(rule['tyre_change_time_4']):.1f} s"
        if key == "maximum_tyre":
            return f"{int(rule['maximum_tyre'])}"
        if key == "rain":
            if not values["enable_rain"]:
                return tr("Off")
            first, laps = values["input_rain_lap"], values["input_rain_laps"]
            return trm(f"Laps {first}-{first + laps - 1}") if laps > 0 else trm(f"From lap {first}")
        value = values.get(key)
        if isinstance(value, bool):
            return tr("On") if value else tr("Off")
        spec = INPUT_SPECS.get(key)
        if spec is None or not isinstance(value, (int, float)):
            return f"{value}"
        decimals = {"input_tank_capacity": 1, "input_fuel_start": 1, "input_energy_start": 1, "input_tread_start": 1,
                    "input_pit_seconds": 1, "input_driver_change_seconds": 1}.get(key, spec.decimals)
        unit = unit_text(spec.unit, symbol)
        return f"{value:.{decimals}f} {unit}".strip()

    def live_race_items(self) -> list[dict]:
        """Race under way read from the game: lap, race time, amounts, stops, track state, penalties,
        repair, class position (empty out of a race)"""
        read = api.read
        session = read.session
        if session.session_type() != RACE_SESSION or not read.state.active() or not session.in_race():
            return []
        elapsed = max(session.elapsed() - max(session.start(), 0.0), 0.0)
        left = session.remaining()
        lap_race = session.finish_type() == 1
        laps_done = read.lap.completed_laps()
        maximum = read.lap.maximum()
        if read.lap.safety_car_active():
            track, warning = tr("Safety Car"), True
        elif session.yellow_flag_state() > 0:
            track, warning = tr("Full Course Yellow"), True
        else:
            track, warning = tr("Green Flag"), False
        penalties = read.vehicle.number_penalties()
        repair = read.vehicle.repair_time()
        pit_time = read.vehicle.pit_stop_time()
        player = read.vehicle.player_index()
        place, cars = 0, 0
        for index in range(read.vehicle.total_vehicles()):
            if index == player or read.vehicle.same_class(index):
                cars += 1
                if index != player and read.vehicle.place(index) < read.vehicle.place():
                    place += 1
        items = [
            {"title": tr("Lap"), "value": f"{laps_done + 1}" + (f" / {maximum}" if lap_race and 0 < maximum < 100000 else ""),
             "warning": False},
            {"title": tr("Race Time"), "value": race_clock(elapsed), "warning": False},
            {"title": tr("Time left"), "value": race_clock(max(left, 0.0)) if not lap_race else results.DASH,
             "warning": False},
            {"title": tr("Fuel"), "value": f"{self.unit_fuel(read.engine.fuel()):.1f} {self.symbol_fuel}",
             "warning": False},
            {"title": tr("Energy"), "value": f"{read.engine.virtual_energy() * 100:.0f} %", "warning": False},
            {"title": tr("Tread"), "value": f"{sum(read.tyre.wear()) * 25:.0f} %", "warning": False},
            {"title": tr("Pit Stops"), "value": f"{read.vehicle.number_pitstops()}", "warning": False},
            {"title": tr("Track"), "value": track, "warning": warning},
            {"title": tr("Penalties"), "value": f"{penalties}", "warning": penalties > 0},
        ]
        if cars:
            items.append({"title": tr("Class Position"), "value": f"P{place + 1} / {cars}", "warning": False})
        if repair > 0:
            items.append({"title": tr("Pending Repair"), "value": f"{repair:.0f} s", "warning": True})
        if pit_time > 0:
            items.append({"title": tr("Next Stop (Game)"), "value": f"{pit_time:.1f} s", "warning": False})
        return items

    def garage_tyres(self) -> dict:
        """Tyres the pit menu offers (LMU): allocation, new compounds, used tyres of each wheel"""
        garage = self.garage
        wheels = []
        for wheel, offers in zip(HEADER_TYREPLAN, garage.used_tyres):
            wheels.append({"wheel": tr(wheel), "tyres": [
                {"text": f"{offer.compound} {offer.tread:.0f}%", "color": tread_color(offer.tread / 100),
                 "tip": offer.text} for offer in offers]})
        return {
            "known": bool(garage.new_compounds or garage.used_tyres or garage.tyres_allowed),
            "allowed": garage.tyres_allowed, "newLeft": garage.new_tyres_left,
            "newCompounds": list(garage.new_compounds), "wheels": wheels,
            "used": sum(len(offers) for offers in garage.used_tyres),
        }

    def live_data_status(self) -> str:
        if not api.read.state.active():
            return tr("Game not running or not in a session: values of the car & session needed")
        if self.garage_request.busy and not self.garage_time:
            return tr("Asking game...")
        if self.garage_time:
            return trm("LMU garage data at {}").replace("{}", self.garage_time, 1)
        return tr("No LMU garage data: pit stop times, tyres & team come from LMU in a session")

    def publish_live_data(self):
        """Live tab shown again when anything changed: values of the game against the calculator"""
        values = self.live_values = self.collect_live_values()
        unfollowed = self.unfollowed_live()
        rows = []
        for item in values:
            known = item.value is not None
            rows.append({
                "key": item.key, "group": item.group, "title": tr(item.title),
                "game": trm(tr(item.text)), "calc": self.live_current(item.key),
                "source": trm(tr(item.source)), "tip": trm(tr(item.tip)), "known": known, "auto": item.follow,
                "followed": item.follow and item.key not in unfollowed,
                "differs": known and not self.live_matches(item),
            })
        view = {
            "rows": rows, "groups": [{"key": key, "title": tr(title)} for key, title in LIVE_GROUPS],
            "status": self.live_data_status(), "busy": self.garage_request.busy,
            "differing": sum(1 for row in rows if row["differs"] and row["followed"]),
            "tyres": self.garage_tyres(), "race": self.live_race_items(),
        }
        if view != self._live_view:
            self._live_view = view
            self.liveDataChanged.emit()

    @Slot()
    def addGameTyres(self):
        """Used tyres the pit menu offers added to the tyre stock with their tread (fitted by hand),
        tyre allocation of the game set"""
        tyres = [(offer.compound, offer.tread) for offers in self.garage.used_tyres for offer in offers]
        if not tyres:
            return
        added = self.tyres.add_used_tyres(tyres)
        if self.garage.tyres_allowed > 0:
            self.tyres.set_rule("maximum_tyre", self.garage.tyres_allowed)
        self.tyre_plan_changed()
        self.host.toast(trm(f"{len(added)} used tyre(s) added to stock"))

    @Slot(str)
    def applyLiveValue(self, key: str):
        """Live value of a row filled in (followed or not)"""
        if self.apply_live(keys={key}):
            self.publish_live_data()

    @Slot()
    def applyAllLive(self):
        """Every live value followed filled in"""
        count = self.apply_live(followed=True, filled=True)
        self.host.toast(trm(f"{count} live value(s) filled in") if count else tr("Calculator already holds the live values"))
        self.publish_live_data()

    @Slot(str, bool)
    def setLiveFollowed(self, key: str, followed: bool):
        """Live value filled in by Load Live, Follow Live & Fill In All, or left out (kept for next time)"""
        names = self.unfollowed_live() - {key}
        if not followed:
            names.add(key)
        self.set_option("live_unfollowed", ",".join(sorted(names)))
        self.publish_live_data()

    # Team stints (game strategy data)
    def update_team_timer(self):
        """Game asked at once, then every few seconds while team tab is shown"""
        if self.active and self.tab == TABS.index("team"):
            if not self._team_timer.isActive():
                self._team_timer.start()
                self.refresh_team()
        else:
            self._team_timer.stop()

    @Slot()
    def refresh_team(self):
        if self.team_request.start():
            self.team_status_changed()

    @Slot()
    def refreshTeam(self):
        self.refresh_team()

    def team_status_changed(self):
        """Status line & busy state shown again (rows & drivers left as they are)"""
        self.teamStatusChanged.emit()
        self.teamChanged.emit()

    def received_team(self, answers: list):
        """Game answers: strategy usage, repair & refuel screen (tank capacity)"""
        self.team_request.busy = False
        usage, refuel = answers
        if usage is None:
            self.team_status = tr("No data from game: LMU not running or not in a session")
            self.team_status_changed()
            return
        capacity = tank_capacity(refuel)
        self.show_team_stints(stint_usage(parse_usage(usage)), self.unit_fuel(capacity) if capacity else 0.0)
        self.team_status = trm("Updated from game at {}").replace("{}", time.strftime("%H:%M:%S"), 1)
        self.team_status_changed()

    def team_request_failed(self):
        """Game request raised an error: busy indicator cleared (asked again by team timer)"""
        self.team_request.busy = False
        self.team_status = tr("No data from game: LMU not running or not in a session")
        self.team_status_changed()

    def car_capacity(self) -> float:
        """Tank capacity (fuel unit): of the car from game, else of calculator, else of live car"""
        return (self.team_capacity or self.values["input_tank_capacity"]
                or self.unit_fuel(api.read.engine.tank_capacity()))

    def show_team_stints(self, stints: Sequence[StintUsage], capacity: float):
        """Stints of the team (selection kept when same stints)"""
        selected = {(usage.driver, usage.stint) for usage in self.selected_stints()}
        self.team_stints = list(stints)
        self.team_capacity = capacity
        selection = {index for index, usage in enumerate(self.team_stints)
                     if (usage.driver, usage.stint) in selected and usage.laps}
        selection_changed = selection != self.team_selection
        self.team_selection = selection
        self.publish_team()
        if selection_changed:
            self.teamSelectionChanged.emit()

    def publish_team(self):
        """Team view built once: stints synced in place (by driver & stint), columns, drivers & fill in
        notified only when changed"""
        view = self.team_view()
        self.team_model.sync(view.pop("rows"))
        if view != self._team_info:
            self._team_info = view
            self.teamInfoChanged.emit()
        self.teamChanged.emit()

    def team_view(self) -> dict:
        capacity = self.car_capacity()
        rows = []
        for index, usage in enumerate(self.team_stints):
            fuel = usage.fuel * capacity
            cells = [usage.driver, f"{usage.stint}", f"{usage.first_lap}-{usage.last_lap}", f"{usage.laps}",
                     f"{fuel:.3f}" if usage.laps and capacity else results.DASH,
                     f"{usage.energy * 100:.3f}" if usage.laps else results.DASH,
                     f"{usage.wear:.3f}" if usage.laps else results.DASH]
            rows.append({"key": f"{usage.driver}|{usage.stint}", "number": index, "enabled": usage.laps > 0,
                         "selected": index in self.team_selection, "cells": cells})
        drivers = []
        for usage in driver_usage(self.team_stints):
            if not usage.laps:
                drivers.append({"name": usage.driver, "text": tr("No lap counted")})
                continue
            parts = [f"{usage.laps} {tr('laps')}"]
            if capacity:
                parts.append(f"{usage.fuel * capacity:.2f} {self.symbol_fuel}")
            if usage.energy:
                parts.append(f"{usage.energy * 100:.2f} % {tr('Energy').lower()}")
            parts.append(f"{usage.wear:.2f} % {tr('Tyre').lower()}")
            drivers.append({"name": usage.driver, "text": " · ".join(parts)})
        columns = [tr(name) for name in TEAM_COLUMNS]
        columns[4] += f" ({self.symbol_fuel})"
        columns[5] += " (%)"
        columns[6] += " (%)"
        return {"columns": columns, "rows": rows, "drivers": drivers, "count": len(rows),
                "canFill": any(usage.laps for usage in self.team_stints)}

    @Slot(int, int)
    def selectStint(self, index: int, mode: int):
        """Team stint clicked: mode 0 alone, 1 added or removed (Ctrl), 2 range (Shift)"""
        if not 0 <= index < len(self.team_stints) or not self.team_stints[index].laps:
            return
        if mode == 1:
            selection = self.team_selection ^ {index}
        elif mode == 2 and self.team_selection:
            first, last = sorted((min(self.team_selection), index))
            selection = self.team_selection | {row for row in range(first, last + 1) if self.team_stints[row].laps}
        else:
            selection = {index}
        if selection == self.team_selection:
            return
        self.team_selection = selection
        self.team_model.update_rows(lambda row: {"selected": row["number"] in selection})
        self.teamSelectionChanged.emit()

    def selected_stints(self) -> list[StintUsage]:
        return [self.team_stints[index] for index in sorted(self.team_selection) if 0 <= index < len(self.team_stints)]

    @Slot()
    def fillInTeam(self):
        """Average per lap of selected stints (all if none selected) filled in"""
        usage = combine_usage(self.selected_stints() or self.team_stints)
        capacity = self.car_capacity()
        if usage.laps <= 0:
            return
        with self.batch():
            if capacity > 0:
                self.setInput("input_tank_capacity", capacity)
                self.setInput("input_fuel_per_lap", usage.fuel * capacity)
            self.setInput("input_energy_per_lap", usage.energy * 100)
            self.setInput("input_wear_per_lap", usage.wear)
        self.set_fill_source(trm(f"Average of {usage.laps} team lap(s) from game"))

