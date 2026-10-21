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
Race calculator data source & files (mixin of RaceBackend): live session or consumption history file,
Recent menus & dropped files, live session refresh, plan of car & track, race plan files, pit stop plan
export, race plan widget input file
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from dataclasses import asdict
from functools import partial

from PySide6.QtCore import QUrl, Slot
from PySide6.QtGui import QGuiApplication

from ...api_control import api
from ...const_file import ConfigType, FileExt, FileFilter
from ...fuel_strategy import (
    RaceState,
    full_tank_laps,
    history_laps,
)
from ...i18n import tr, trm
from ...module_info import minfo
from ...race_live import pit_exit
from ...race_live import read_race_state as read_live
from ...setting import cfg
from ...userfile import atomic_path, atomic_write, write_text_file
from ...userfile.consumption_history import load_consumption_history_file
from ...userfile.tyre_strategy import (
    DEFAULT_TYRE_SET,
    validate_tyre_strategy,
)
from ..file_drop import DROP_HISTORY, DROP_RACE_PLAN, DROP_TYRE_PLAN, race_file_kind
from . import race_results as results
from .race_base import TABS, RaceBase
from .race_history import history_signature
from .race_model import (
    PLAN_FILE,
    RACE_PLAN_FORMAT,
    RACE_PLAN_FORMATS,
    RACE_PLAN_VERSION,
    RACE_SESSION,
    checked_inputs,
    convert_fuel_inputs,
    live_race_length,
    plan_markdown,
    ranged_inputs,
    write_plan_csv,
)
from .race_tyres import (
    MEASURED_DEFAULT,
    save_tyre_strategy_file_path,
    set_tyre_strategy_file_path,
)

logger = logging.getLogger(__name__)

RECENT_OPTIONS = {  # files opened or saved last (newest first), option of config "fuel_calculator" by kind
    DROP_HISTORY: "recent_history_file_names",
    DROP_RACE_PLAN: "recent_race_plan_file_names",
    DROP_TYRE_PLAN: "recent_tyre_plan_file_names",
}
MAX_RECENT = 8
RECENT_SEPARATOR = "|"  # never in a Windows file name


def same_file(path: str, other: str) -> bool:
    return os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(other))


def network_path(path: str) -> bool:
    """UNC path (network share): checking it may wait seconds for a server gone (never on the UI thread)"""
    return path.startswith(("\\\\", "//"))


def missing_files_of(serial: int, paths: Sequence[str]) -> tuple[int, set[str]]:
    """Paths that are not files, with the serial given (worker thread: network shares)"""
    return serial, {path for path in paths if not os.path.isfile(path)}


class RaceFiles(RaceBase):
    """Data source, live session & files of race calculator page"""

    # Data source: live session or file
    def set_source(self, live: bool, name: str):
        self.live_source = live
        self.source_name = name
        self.headerChanged.emit()

    @Slot()
    def loadLive(self):
        """Laps of live session, race length of a live race and every live value followed (live tab)
        filled in, LMU garage screens asked (filled in once answered)"""
        if self.game_data_refused():
            return
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
        if filename_full:
            self.load_history_file(filename_full)

    def load_history_file(self, filename_full: str) -> bool:
        """Laps of a consumption history file (or CSV file) in table & filled in, True once loaded"""
        filepath = os.path.dirname(filename_full) + "/"
        filename, extension = os.path.splitext(os.path.basename(filename_full))
        history_data = history_laps(load_consumption_history_file(
            filepath=filepath, filename=filename, extension=extension))
        if not history_data:
            self.forget_recent(DROP_HISTORY, filename_full)
            self.host.warn(trm(f"Unable to read consumption history: {filename}{extension}"))
            return False
        self.fill_in_data(history_data, live=False)
        self.refresh_history(history_data)
        self.history_file = (filepath, filename, extension)
        self.set_source(False, filename)
        self.set_plan_inputs(False)
        self.remember_recent(DROP_HISTORY, filename_full)
        return True

    # Files opened or saved last (Recent menus), files dropped on page
    @staticmethod
    def read_recent() -> dict[str, list[str]]:
        """Recent files of each kind kept in config (newest first), missing files left out (network shares kept:
        checked in background, see check_network_recent)"""
        config = cfg.user.config["fuel_calculator"]
        recent = {}
        for kind, option in RECENT_OPTIONS.items():
            value = config.get(option, "")
            paths = value.split(RECENT_SEPARATOR) if isinstance(value, str) else []
            recent[kind] = [path for path in paths
                            if path and (network_path(path) or os.path.isfile(path))][:MAX_RECENT]
        return recent

    def check_network_recent(self):
        """Files of Recent menus on network shares checked on a worker thread, missing ones then left out"""
        paths = tuple({path for paths in self._recent.values() for path in paths if network_path(path)})
        if paths:
            # Serial in the result: done callback a bound method (held weakly, never keeps the page alive)
            self.jobs.run("recent files", partial(missing_files_of, self._recent_serial, paths),
                          self.network_recent_checked, key="recent")

    def network_recent_checked(self, result: tuple[int, set[str]]):
        """Network check over: missing files out of their menu (unless a file was opened or saved meanwhile:
        checked again at next menu opening)"""
        serial, missing = result
        if not missing or serial != self._recent_serial:
            return
        for kind, paths in list(self._recent.items()):
            kept = [path for path in paths if path not in missing]
            if kept != paths:
                self.keep_recent(kind, kept)

    def keep_recent(self, kind: str, paths: list[str]):
        """Recent files of a kind kept for next time, Recent menus told if changed"""
        paths = paths[:MAX_RECENT]
        changed = paths != self._recent.get(kind)
        self._recent[kind] = paths
        config = cfg.user.config["fuel_calculator"]
        value = RECENT_SEPARATOR.join(paths)
        if config.get(RECENT_OPTIONS[kind]) != value:
            config[RECENT_OPTIONS[kind]] = value
            cfg.save(config_type=ConfigType.CONFIG)
        if changed:
            self.recentChanged.emit()

    def remember_recent(self, kind: str, filename_full: str):
        """File opened or saved: first of its Recent menu"""
        path = os.path.abspath(filename_full).replace("\\", "/")
        self._recent_serial += 1  # network check running: may have missed this file (saved meanwhile)
        self.keep_recent(kind, [path, *(item for item in self._recent.get(kind, []) if not same_file(item, path))])

    def forget_recent(self, kind: str, filename_full: str):
        """File missing or unreadable: out of its Recent menu"""
        paths = self._recent.get(kind, [])
        if any(same_file(item, filename_full) for item in paths):
            self.keep_recent(kind, [item for item in paths if not same_file(item, filename_full)])

    @Slot()
    def refreshRecent(self):
        """Recent menu about to open: files deleted or moved meanwhile left out (network shares: once checked)"""
        recent = self.read_recent()
        for kind, paths in recent.items():
            if paths != self._recent.get(kind):
                self.keep_recent(kind, paths)
        self.check_network_recent()

    @Slot(str, str)
    def openRecent(self, kind: str, path: str):
        """File of a Recent menu opened (removed from menu if missing or unreadable)"""
        if not os.path.isfile(path):
            self.forget_recent(kind, path)
            self.host.warn(trm(f"File not found: {path}"))
            return
        self.open_file_of_kind(kind, path)

    def open_file_of_kind(self, kind: str, path: str) -> bool:
        if kind == DROP_HISTORY:
            return self.load_history_file(path)
        if kind == DROP_RACE_PLAN:
            return self.load_race_plan(path)
        if kind == DROP_TYRE_PLAN:
            return self.open_tyre_plan_file(path)
        return False

    @Slot(list, result=bool)
    def canDrop(self, urls: list) -> bool:
        """Files dragged over page: True if any can be opened (consumption history, race plan, tyre plan)"""
        return any(race_file_kind(path) for path in self.local_paths(urls))

    @Slot(list)
    def dropFiles(self, urls: list):
        """Files dropped on page opened like their Open action"""
        self.open_dropped(self.local_paths(urls))

    def open_dropped(self, paths: Sequence[str]) -> int:
        """Consumption history, race plan & tyre plan files opened, other files told; files opened returned"""
        if self.game_data_refused():
            return 0
        opened = 0
        unsupported = []
        for path in paths:
            kind = race_file_kind(path)
            if not kind:
                unsupported.append(os.path.basename(path))
            elif self.open_file_of_kind(kind, path):
                opened += 1
        if unsupported:
            self.host.toast(trm(f"Unsupported file: <b>{', '.join(unsupported)}</b>"))
        return opened

    @staticmethod
    def local_paths(urls: Sequence) -> list[str]:
        """Local file paths of file urls (QML drop urls)"""
        paths = []
        for item in urls:
            url = item if isinstance(item, QUrl) else QUrl(str(item))
            if url.isLocalFile():
                paths.append(url.toLocalFile())
        return paths

    @staticmethod
    def set_plan_inputs(from_plan: bool):
        """Inputs of a race plan (kept when page opens) or of laps (filled in from live laps)"""
        config = cfg.user.config["fuel_calculator"]
        if config.get("enable_plan_inputs") != from_plan:
            config["enable_plan_inputs"] = from_plan
            cfg.save(config_type=ConfigType.CONFIG)

    # Live session
    def refresh_live(self):
        """Every few seconds: stops counted, and while page shown: new laps, live race state,
        plan of car & track, class rivals"""
        if not self.game_data:
            return
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
        if not self.game_data:  # whole race planned, nothing read
            if (self.live_status, self.live_tip) != ("", ""):
                self.live_status, self.live_tip = "", ""
                self.liveChanged.emit()
            if self._race_key is not None:
                self._race_key = None
                self.set_race_state(None)
            return
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
        key = state.replan_key() if state is not None else None
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
            cars = self.rival_tracker.update()
            # Time lost stopping now: next stop of the plan (pit lane & service), else pit lane time
            strategy = self.strategy
            loss = strategy.stops[0].seconds if strategy.ready and strategy.stops else self.plan_setup.pit_seconds
            rivals = results.class_rivals(cars, full_tank_laps(self.plan_setup),
                                          pit_exit(cars, loss, self.plan_setup.laptime))
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
        """Save race plan file (asked when no file name given, then first of Recent menu)"""
        chosen = not filename_full
        if chosen:
            name = self.tyres.name or tr("Untitled plan")
            filename_full = self.host.save_file(set_tyre_strategy_file_path(f"{name}{FileExt.RACEPLAN}"),
                                                FileFilter.RACEPLAN)
            if not filename_full:
                return
            save_tyre_strategy_file_path(os.path.dirname(filename_full) + "/")
        if not write_text_file(filename_full, json.dumps(self.race_plan_data(), indent=4)):
            self.host.warn(trm(f"Unable to save race plan:<br><b>{filename_full}</b>"))
            return
        if chosen:
            self.remember_recent(DROP_RACE_PLAN, filename_full)
        self.host.toast(trm(f"Race plan saved at:<br><b>{filename_full}</b>"))

    @Slot()
    def openRacePlan(self):
        self.load_race_plan()

    def load_race_plan(self, filename_full: str = "", quiet: bool = False) -> bool:
        """Open race plan file (asked when no file name given): race setup, fuel & tyre plan
        replaced (undoable), True once opened. Opened by user (not quiet): first of Recent menu"""
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
                self.forget_recent(DROP_RACE_PLAN, filename_full)
                self.host.warn(trm(f"Invalid race plan file: {os.path.basename(filename_full)}"))
            return False
        if not quiet:
            self.remember_recent(DROP_RACE_PLAN, filename_full)
        return True

    def apply_race_plan(self, data, name: str) -> bool:
        """Race setup, fuel & tyre plan of race plan data replaced, False if not a race plan
        (plan saved without fuel unit by an older version: fuel unit of page)"""
        try:
            if not isinstance(data, dict) or data.get("format") not in RACE_PLAN_FORMATS:
                raise ValueError
            inputs: dict = data["inputs"] if isinstance(data.get("inputs"), dict) else {}
            tyre_data = validate_tyre_strategy(data.get("tyre_strategy") or {})
        except (ValueError, TypeError, AttributeError):
            return False
        # Inputs checked & in the fuel unit of the page before anything is applied: never half applied
        plan_unit = data.get("fuel_unit") or self.fuel_unit
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
            with atomic_path(filename) as temp_filename:  # file open in a spreadsheet: left whole
                write_plan_csv(temp_filename, header, rows)
        except OSError as error:  # file open in a spreadsheet, read-only folder
            self.host.warn(trm(f"Unable to export: {error}"))
            return
        self.keep_export_folder(filename)
        self.host.toast_file(trm(f"Exported: <b>{os.path.basename(filename)}</b>"), filename)

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
        image = self.plan_image()
        try:
            with atomic_path(filename) as temp_filename:
                if not image.save(temp_filename, "PNG"):
                    raise OSError(f"unable to write {temp_filename}")
        except OSError:
            self.host.warn(trm(f"Unable to save picture: {filename}"))
            return
        self.keep_export_folder(filename)
        self.host.toast_file(trm(f"Exported: <b>{os.path.basename(filename)}</b>"), filename)

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
            with atomic_write(f"{cfg.path.config}{PLAN_FILE}", raise_error=True) as file:  # error logged
                file.write(json.dumps(self._plan_file_data))
        except OSError as error:
            self.save_failure("plan", trm(f"Unable to update the Race Plan overlay: {error}"))
            return
        self.save_success("plan")

    def save_failure(self, kind: str, text: str):
        """Automatic save failed: told once per failure streak (saves retried at each change)"""
        if kind not in self.save_failed:
            self.save_failed.add(kind)
            self.host.toast(text)

    def save_success(self, kind: str):
        if kind in self.save_failed:
            self.save_failed.discard(kind)
            logger.info("RACE CALCULATOR: %s saved again", kind)
