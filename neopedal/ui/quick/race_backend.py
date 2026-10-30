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
race (plan of the rest of the race) & race plan files.

Every input change calculates at once (one calculation per change, see batch), scenarios
(saving target, strategy comparison, safety car & rain against none) once quick changes settle.
Dialogs, toasts & undo history belong to the page hosting the QML view (RaceHost).

Parts of the page are mixins of RaceBackend sharing its state (base: race_base.RaceBase): data source & files
(race_files), consumption history & team stints (race_history), line-up & driver of each stint
(race_team_plan), tyre tab & undo (race_tyre_tab), live tab (race_live_tab). This module keeps page state, properties, results, inputs & calculation.
"""

from __future__ import annotations

import os
import time
import weakref
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from functools import partial
from typing import Any, Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot

from ... import app_signal, units
from ... import calculation as calc
from ...api_control import api
from ...const_file import ConfigType
from ...fuel_strategy import (
    MAX_DRIVERS,
    RaceState,
    Strategy,
    StrategyInput,
    compare_compounds,
    compare_strategies,
    consumption,
    copy_strategy,
    driver_table_text,
    estimate_pace,
    history_laps,
    plan,
    remaining_input,
    representative_laps,
    reserves,
    safety_car_risk,
    saving_input,
    saving_target,
    strategy_input_from_values,
)
from ...game_rest import GameRequest
from ...i18n import tr, trm
from ...module_info import ConsumptionDataSet, minfo
from ...process.team_usage import StintUsage
from ...race_live import RivalTracker, StopCounter
from ...race_live_data import GARAGE_RESOURCES, GarageData, LiveValue
from ...setting import cfg
from ...userfile.tyre_strategy import (
    DEFAULT_TYRE_SET,
)
from . import race_results as results
from .game_pictures import LogoCache, notifier
from .models import DictListModel
from .page_backend import PageBackend
from .race_base import TABS
from .race_files import (  # noqa: F401  (re-exported)
    MAX_RECENT,
    RECENT_OPTIONS,
    RECENT_SEPARATOR,
    RaceFiles,
    missing_files_of,
    network_path,
    same_file,
)
from .race_history import (  # noqa: F401  (re-exported)
    COLUMN_OPTION_TITLES,
    HISTORY_COLUMNS,
    TEAM_COLUMNS,
    USAGE_RESOURCES,
    HistoryTeam,
    file_stamp,
    history_signature,
    read_team_usage,
    without_laps,
    write_history,
)
from .race_live_tab import FILLED_KEYS, LIVE_GROUPS, LIVE_PART_SIGNALS, LiveTab  # noqa: F401  (re-exported)
from .race_model import DRIVER_SPECS as DRIVER_INPUT_SPECS
from .race_model import (
    INPUT_SPECS,
    SAVED_INPUTS,
    clamp_input,
    clamp_number,
    clock_text,
    day_time_text,
    driver_rows,
    input_spec,
    laptime_text,
    parse_laptime,
    parse_start_time,
    ranged_inputs,
    start_time_text,
    unit_text,
)
from .race_team_plan import TeamPlan
from .race_tyre_tab import TyreTab
from .race_tyres import (
    MEASURED_DEFAULT,
    TyrePlan,
)

SCENARIO_DELAY_MS = 150  # quick input changes (arrow held): scenarios calculated once settled
SCENARIO_JOBS = True  # scenarios calculated on a worker thread (only the newest handed over), False: at once
LIVE_REFRESH_MS = 2000  # live history check, live race state, rivals
TEAM_REFRESH_MS = 15000  # game asked again while team tab shown
GARAGE_REFRESH_MS = 10000  # LMU garage screens asked again while live tab shown or inputs follow live
SAVE_DELAY_MS = 500  # tyre plan autosave & plan input of race plan widget, once changes settle
TYRE_SCREEN = ("/rest/garage/UIScreen/TireManagement",)
HISTORY_ROLES = ("serial", "valid", "cells", "selected")
TEAM_ROLES = ("key", "number", "enabled", "cells", "selected")  # number: of stint in team_stints
LIVE_ROLES = ("key", "header", "title", "game", "calc", "source", "tip", "known", "auto", "followed", "differs")


class RaceHost(Protocol):
    """Page hosting the race calculator: dialogs, toasts, undo history, modified marker"""

    def warn(self, text: str) -> None: ...
    def toast(self, text: str) -> None: ...
    def toast_file(self, text: str, path: str) -> None: ...  # toast of a file written: its folder opened on click
    def confirm(self, text: str) -> bool: ...
    def ask(self, text: str, on_yes: Callable[[], object], action_text: str = "", danger: bool = False) -> None: ...
    def open_file(self, directory: str, file_filter: str) -> str: ...
    def save_file(self, directory: str, file_filter: str) -> str: ...
    def open_compound_config(self, name: str, user_setting: dict, reload) -> None: ...
    def record_change(self) -> None: ...
    def set_modified(self) -> None: ...
    def set_unmodified(self) -> None: ...
    def undo(self) -> None: ...
    def redo(self) -> None: ...
    def is_page_visible(self) -> bool: ...


_active: weakref.ReferenceType | None = None  # backend of the open Race Calculator page (hotkey, palette, rail)


def scenario_results(strategy: Strategy, plan_setup: StrategyInput, setup: StrategyInput, laps_target: int,
                     safety_car: bool, rain: bool, symbol_fuel: str,
                     compounds: tuple[tuple[str, float, float, float], ...] = (), compound: str = "",
                     sc_risk: float = 0.0, sc_laps: int = 0) -> dict:
    """Saving target, strategies compared, safety car & rain against none, race on each compound,
    safety car risk (no Qt: worker thread)"""
    has_energy = setup.energy_per_lap > 0
    ready = strategy.ready
    target = saving_target(plan_setup, strategy)
    aimed = None
    if laps_target > 0 and ready:
        aimed_setup = saving_input(plan_setup, laps_target)
        aimed = (aimed_setup, plan(aimed_setup))
    scenarios = results.saving_texts(strategy, plan_setup, setup, target, aimed, symbol_fuel)
    variants = compare_strategies(plan_setup, strategy) if ready and strategy.feasible else []
    scenarios["comparison"] = results.comparison(variants, has_energy, symbol_fuel)
    for name, enabled, without_input in (
        ("safetyCar", safety_car, replace(plan_setup, sc_lap=0, sc_laps=0, sc_pit=False)),
        ("rain", rain, replace(plan_setup, rain_lap=0, rain_tyres=False)),
    ):
        without = plan(without_input) if enabled and ready else None
        scenarios[name] = results.scenario_text("rain" if name == "rain" else "sc", strategy, without) \
            if enabled else ""
    plans = compare_compounds(plan_setup, compounds) if ready and strategy.feasible else []
    scenarios["compounds"] = results.compound_comparison(plans, compound)
    risk = safety_car_risk(plan_setup, strategy, sc_risk, sc_laps) if sc_risk > 0 else None
    scenarios["risk"] = results.safety_car_risk_view(risk, sc_risk > 0)
    return scenarios


def race_page() -> RaceBackend | None:
    """Backend of the Race Calculator page if open"""
    return _active() if _active is not None else None


def race_status() -> str:
    """"on" (page open, calculator on), "off" (page open, calculator off), "" (page closed): rail dot"""
    backend = race_page()
    return "" if backend is None else "on" if backend.game_data else "off"


class RaceBackend(RaceFiles, HistoryTeam, TeamPlan, TyreTab, LiveTab, PageBackend):
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
    teamPlanChanged = Signal()
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
    raceProposalChanged = Signal()  # planning the rest of a race under way proposed or not
    rivalsChanged = Signal()
    liveDataChanged = Signal()  # anything of the live tab (Python callers: QML reads the parts below)
    liveRaceChanged = Signal()
    liveTyresChanged = Signal()
    liveDataStatusChanged = Signal()
    liveBusyChanged = Signal()
    liveDifferingChanged = Signal()
    recentChanged = Signal()
    undoChanged = Signal()  # undo / redo available (Undo & Redo buttons)

    def __init__(self, parent: QObject, host: RaceHost):
        global _active
        super().__init__(parent, "Race calculator")
        self.host = host
        self.logos = LogoCache()
        notifier().changed.connect(self.headerChanged)  # circuit logo fetched from game meanwhile
        config = cfg.user.config["fuel_calculator"]
        # Fuel unit of the page (frozen while open)
        self.is_gallon = cfg.units["fuel_unit"] == "Gallon"
        self.fuel_unit = "Gallon" if self.is_gallon else "Liter"  # of fuel inputs (race plan)
        self.unit_fuel = units.set_unit_fuel(cfg.units["fuel_unit"])
        self.symbol_fuel = units.set_symbol_fuel(cfg.units["fuel_unit"])

        self.values = ranged_inputs(config)
        if config.get("show_quick_setup", True) and self.values != ranged_inputs(SAVED_INPUTS):
            self.set_quick_setup(False)  # calculator used before (inputs kept): never asked
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
        self.pit_menu_available = False  # LMU session under way: refill of the next stop can be set in its pit menu
        self.race_tyre_changes: list[int] = []  # tyres changed at each stop of tyre plan (whole race)
        self.proposed_tyre_rows: list[int] = []  # tyre plan rows (stints) needing new tyres (minimum tread)
        self.sections: dict = {}  # results shown, by QML property name (see publish)
        self._last_calculation = 0.0
        self._plan_file_data: dict = {}
        self.save_failed: set[str] = set()  # automatic saves failing ("plan", "tyres"): told once per failure streak
        self._recent = self.read_recent()
        self._recent_serial = 0  # files remembered: network check started before one dropped (stale)
        self.check_network_recent()
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
        self._history_cursor = -1  # lap moved to with Up / Down
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
        self._apply_garage = False  # Game Session source chosen: garage values filled in once answered
        self.live_values: list[LiveValue] = []
        self._dry_plan: tuple[StrategyInput | None, int] = (None, 0)  # input of dry plan, its race laps
        # Live tab: rows synced in place (group titles as rows), each other part notified only when changed
        self.live_model = DictListModel(LIVE_ROLES, self)
        self._live_rows: list[dict] = []
        self._live_parts: dict = {"status": "", "busy": False, "differing": 0, "tyres": {}, "race": []}

        # Live race
        self.stop_counter = StopCounter()
        self.rival_tracker = RivalTracker()
        self._race_key: tuple | None = None
        self.live_status = ""
        self.live_tip = ""
        self._race_running = False  # race of the game under way (live race proposed while not planned from now)
        self._race_dismissed = False  # proposal turned down for the race under way
        self._race_proposal = False
        self._rivals: dict = results.class_rivals([], 0)
        self._combo_loaded = ""
        self._shown_combo = ""
        tab = config.get("race_tab", 0)
        self.tab = tab if isinstance(tab, int) and not isinstance(tab, bool) and 0 <= tab < len(TABS) else 0
        self.active = False  # page shown

        self._scenario_timer = self.page_timer(self.update_scenarios, single_shot=True)
        self._plan_file_timer = self.page_timer(self.write_plan_file, SAVE_DELAY_MS, single_shot=True)
        self._autosave_timer = self.page_timer(self.autosave_tyres, SAVE_DELAY_MS, single_shot=True)
        self._live_timer = self.page_timer(self.refresh_live, LIVE_REFRESH_MS)
        self._team_timer = self.page_timer(self.refresh_team, TEAM_REFRESH_MS)
        self._garage_timer = self.page_timer(self.refresh_garage, GARAGE_REFRESH_MS)

        # Inputs of a race plan opened last time kept: live laps shown, not filled in
        self._batch = 0
        with self.batch():
            if self.game_data:
                self.show_live_data(fill_inputs=not config.get("enable_plan_inputs"))
                self.auto_load_combo_plan()
        self.refresh_race_state()
        if self.game_data:
            self._live_timer.start()
        _active = weakref.ref(self)

    # Page shown or hidden, closed
    def set_active(self, active: bool):
        """Page shown: live history follows new laps, team asked to game while team tab shown"""
        self.active = active
        if active:
            self.refresh_live()
        self.update_team_timer()
        self.update_garage_timer()

    def release_resources(self):
        """Page closed: tyre plan & plan input written now, timers stopped"""
        global _active
        for timer in (self._live_timer, self._team_timer, self._garage_timer, self._scenario_timer):
            timer.stop()
        self.autosave_tyres()
        self.flush_plan_file()
        if _active is not None and _active() is self:
            _active = None

    # Calculator on or off (setting kept under its first name: game data)
    @property
    def game_data(self) -> bool:
        """Calculator on: game read (live laps, live race, rivals, team, garage, stops counted); off: page shows
        nothing and the game is not read"""
        return cfg.user.config["fuel_calculator"].get("enable_game_data", True) is not False

    @Slot(bool)
    def setGameData(self, enabled: bool):
        """Calculator on or off (kept for next time). Off: page empty, nothing read from the game, live race
        plan back to the whole race; inputs, tyre plan & plan file kept"""
        if enabled == self.game_data:
            return
        self.set_option("enable_game_data", enabled)
        app_signal.refresh.emit(True)  # navigation bar dot
        if enabled:
            self._live_timer.start()
            if self.active:
                self.refresh_live()
        else:
            for timer in (self._live_timer, self._team_timer, self._garage_timer):
                timer.stop()
            self.refresh_race_state()
            if self._rivals != results.class_rivals([], 0):
                self._rivals = results.class_rivals([], 0)
                self.rivalsChanged.emit()
        self.update_team_timer()
        self.update_garage_timer()
        self.update_race_proposal()

    def game_data_refused(self) -> bool:
        """Action asking the game while calculator is off: told, True"""
        if self.game_data:
            return False
        self.host.toast(tr("Race Calculator is off"))
        return True

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

    @Property(dict, notify=teamPlanChanged)
    def teamPlan(self) -> dict:
        return self.sections.get("teamPlan", {})

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
            "tab": self.tab, "combo": self.combo_name() if self.game_data else "", "gameData": self.game_data,
            "trackLogo": self.logos.track(self.source_name.split(" - ", 1)[0]) if self.source_name else "",
            "quickSetup": bool(config.get("show_quick_setup", True)),
        }

    @Property(bool, notify=raceProposalChanged)
    def raceProposal(self) -> bool:
        return self._race_proposal

    @Property(str, notify=liveChanged)
    def liveStatus(self) -> str:
        return self.live_status

    @Property(str, notify=liveChanged)
    def liveTip(self) -> str:
        return self.live_tip

    @Property(bool, notify=liveChanged)
    def pitMenuAvailable(self) -> bool:
        """Pit Menu button: game pit menu reachable (LMU, in a session)"""
        return self.pit_menu_available

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

    @Slot(str, result=bool)
    def lapTimeValid(self, text: str) -> bool:
        """Lap time text understood (field shown invalid while typing otherwise)"""
        return parse_laptime(text) is not None

    @Slot(str, result=bool)
    def startTimeValid(self, text: str) -> bool:
        return parse_start_time(text) is not None

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
        if (config.get("input_measured_compound", MEASURED_DEFAULT) == self.measured_index
                and all(config.get(key) == value for key, value in self.values.items())):
            return
        config.update(self.values)
        config["input_measured_compound"] = self.measured_index
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
        self.toast_undo(tr("Every input reset to zero"))

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
        # Measured compound shown with inputs (undo & plan file set it without set_measured_compound)
        shown = dict(self.values, input_measured_compound=self.measured_index)
        if shown != self._shown_values:
            self._shown_values = shown
            self.inputsChanged.emit()
        self.save_inputs()
        self.host.record_change()
        self.undoChanged.emit()

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

        def tyre_times() -> tuple[tuple[float, ...], tuple[float, ...]]:
            """(change time of each stop, compound pace of each stint): proposed changes cost 4 tyres
            until tyres are planned"""
            return (tuple(link.stop_change_times()) if link.has_tyres() else ()), link.stint_pace()

        extra, pace = tyre_times()
        strategy = plan(replace(setup, stop_extra_seconds=extra, stint_pace=pace))
        rows_changed = False
        if self.race_state is None:
            for _ in range(3):
                rows_changed |= link.set_stints(strategy)
                new_extra, new_pace = tyre_times()
                if (new_extra, new_pace) == (extra, pace):
                    break
                extra, pace = new_extra, new_pace
                strategy = plan(replace(setup, stop_extra_seconds=extra, stint_pace=pace))
            else:
                rows_changed |= link.set_stints(strategy)
        if rows_changed:
            self.tyresChanged.emit()
            self._autosave_timer.start()
        self.race_setup = self.plan_setup = replace(setup, stop_extra_seconds=extra, stint_pace=pace)
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
        self.publish("summary", results.summary(strategy, self.race_state, setup.pit_seconds))
        self.publish("timeline", results.timeline(strategy, drivers, self.symbol_fuel, self.time_text,
                                                       self.driver_label))
        self.publish("fuelLevels", results.fuel_levels(strategy, plan_setup, has_fuel))
        self.publish("plan", {
            "columns": [{"key": key, "title": title, "tip": tr(results.PLAN_TIPS[key]) if key in results.PLAN_TIPS else ""}
                        for key, title in zip(results.PLAN_COLUMNS, results.plan_header(self.symbol_fuel))],
            "rows": [list(row) for row in results.plan_rows(strategy, has_energy, self.time_text,
                                                             plan_setup.clock_offset, self.driver_short)],
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
        self.publish("driverTimes", results.driver_times(strategy, drivers, driver_limits, self.driver_short))
        self.publish("teamPlan", self.team_plan_view())
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
        against none: many plans (10 to 40 ms for a long race), on a worker thread"""
        wear = self.values["input_wear_per_lap"]
        compounds = tuple((name, pace, wear * factor, tread)
                          for name, pace, factor, tread in self.tyres.compound_options())
        work = partial(scenario_results, copy_strategy(self.strategy), self.plan_setup, self.strategy_input(),
                       self.values["input_target_stint_laps"], bool(self.values["enable_safety_car"]),
                       bool(self.values["enable_rain"]), self.symbol_fuel, compounds, self.tyres.compound,
                       self.values["input_sc_risk"] if self.values["enable_sc_risk"] else 0.0,
                       int(self.values["input_sc_laps"]))
        if SCENARIO_JOBS:
            self.jobs.run("race scenarios", work, self.scenarios_done, key="scenarios")
        else:
            self.scenarios_done(work())

    def scenarios_done(self, scenarios: dict):
        """Scenarios of the newest plan shown (UI thread)"""
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

    # Recent files (race_files) & page options
    @Property(dict, notify=recentChanged)
    def recentFiles(self) -> dict:
        """Recent files of each kind (history, race_plan, tyre_plan): list of path & name, newest first"""
        return {kind: [{"path": path, "name": os.path.basename(path)} for path in paths]
                for kind, paths in self._recent.items()}

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
        if checked and self.live_source and self.game_data:
            with self.batch():
                self.fill_in_data(history_laps(minfo.history.consumptionDataSet), skip=self.unfollowed_live())
                self.apply_live(followed=True)
        self.update_garage_timer()

    @Slot(bool)
    def setLiveRace(self, checked: bool):
        """During a race: plan of the rest of the race from now"""
        self.set_option("enable_live_race", checked)
        self.refresh_race_state()
        self.update_race_proposal()

    def update_race_proposal(self):
        """Race of the game under way, plan not made from now: planning the rest of the race proposed (until turned
        down for this race)"""
        proposal = (self.game_data and self._race_running and not self._race_dismissed
                    and not cfg.user.config["fuel_calculator"].get("enable_live_race"))
        if proposal != self._race_proposal:
            self._race_proposal = proposal
            self.raceProposalChanged.emit()

    @Slot()
    def dismissLiveRace(self):
        """Proposal to plan the rest of the race turned down: not proposed again during this race"""
        if self._race_running and not self._race_dismissed:
            self._race_dismissed = True
            self.update_race_proposal()

    # Quick setup: first use of the calculator asks race length, pit stop time & data source, then shows the page
    @staticmethod
    def set_quick_setup(shown: bool) -> bool:
        config = cfg.user.config["fuel_calculator"]
        if config.get("show_quick_setup", True) == shown:
            return False
        config["show_quick_setup"] = shown
        cfg.save(config_type=ConfigType.CONFIG)
        return True

    @Slot()
    def finishQuickSetup(self):
        """Quick setup answered or skipped: whole page shown, never asked again"""
        if self.set_quick_setup(False):
            self.headerChanged.emit()

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

    @Property(bool, notify=tyresChanged)
    def askingGame(self) -> bool:
        return self.tyre_request.busy

    @Property(bool, notify=undoChanged)
    def canUndo(self) -> bool:
        """Undo history has a step (host without history query: always offered)"""
        can_undo = getattr(self.host, "can_undo", None)
        return bool(can_undo()) if callable(can_undo) else True

    @Property(bool, notify=undoChanged)
    def canRedo(self) -> bool:
        can_redo = getattr(self.host, "can_redo", None)
        return bool(can_redo()) if callable(can_redo) else True

    # Live game data (live tab): every input value the game gives, see race_live_data
    @Property(dict, notify=liveDataChanged)
    def liveData(self) -> dict:
        """Whole live view (Python callers & tests: QML reads the parts below)"""
        return dict(self._live_parts, rows=self._live_rows,
                    groups=[{"key": key, "title": tr(title)} for key, title in LIVE_GROUPS])

    @Property(QObject, constant=True)
    def liveRows(self) -> DictListModel:
        return self.live_model

    @Property(list, notify=liveRaceChanged)
    def liveRace(self) -> list:
        return self._live_parts["race"]

    @Property(dict, notify=liveTyresChanged)
    def liveTyres(self) -> dict:
        return self._live_parts["tyres"]

    @Property(str, notify=liveDataStatusChanged)
    def liveDataStatus(self) -> str:
        return self._live_parts["status"]

    @Property(bool, notify=liveBusyChanged)
    def liveBusy(self) -> bool:
        return self._live_parts["busy"]

    @Property(int, notify=liveDifferingChanged)
    def liveDiffering(self) -> int:
        return self._live_parts["differing"]

