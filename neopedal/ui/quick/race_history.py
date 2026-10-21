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
Race calculator consumption history & team stints (mixin of RaceBackend): history laps (sort, columns,
selection, laps added or deleted), team stints read from game strategy data
"""

from __future__ import annotations

import os
from collections import Counter, deque
from collections.abc import Sequence
from functools import partial

from PySide6.QtCore import Slot

from ... import calculation as calc
from ... import game_rest
from ...api_control import api
from ...const_file import FileExt
from ...fuel_strategy import (
    history_laps,
)
from ...i18n import tr, trm
from ...module_info import ConsumptionDataSet, minfo
from ...process.team_usage import StintUsage, combine_usage, driver_usage, parse_usage, stint_usage, tank_capacity
from ...setting import cfg
from ...userfile.consumption_history import save_consumption_history_file
from . import race_results as results
from .formatting import clock_seconds
from .race_base import TABS, RaceBase
from .race_model import (
    INVALID_COLOR,
)

USAGE_RESOURCES = ("/rest/strategy/usage", "/rest/garage/UIScreen/RepairAndRefuel")
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


def without_laps(history: Sequence[ConsumptionDataSet], removed: Sequence[ConsumptionDataSet],
                 ) -> deque[ConsumptionDataSet]:
    """Live history (newest lap first) less removed laps (each once) as a new data set: stint module & overlays
    may be iterating current one (copy on write, never changed in place), same length limit, placeholder if no
    lap left (stint module reads first entry: never empty)"""
    left = Counter(removed)
    kept = []
    for lap in history:
        if left[lap] > 0:
            left[lap] -= 1
        else:
            kept.append(lap)
    return deque(kept if history_laps(kept) else [ConsumptionDataSet()],
                 history.maxlen if isinstance(history, deque) else None)


def read_team_usage(resources: Sequence[str]) -> tuple[list[StintUsage] | None, float]:
    """Team request work (background thread): stints of strategy usage (None if no answer) & tank capacity
    (liters) of repair & refuel screen, parsed off the UI thread (whole race of every driver late in a 24 h race)"""
    usage, refuel = (game_rest.request_game(resource) for resource in resources)
    if usage is None:
        return None, 0.0
    return stint_usage(parse_usage(usage)), tank_capacity(refuel)


class HistoryTeam(RaceBase):
    """Consumption history & team stints of race calculator page"""

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
        self._history_cursor = serial
        self.set_history_selection(selection)

    @Slot(int, bool, result=int)
    def moveLapSelection(self, step: int, extend: bool) -> int:
        """Up / Down (Shift: range from the lap clicked first) in the history table: row index shown, -1 if none"""
        shown = self.shown_serials()
        if not shown:
            return -1
        cursor: int | None = self._history_cursor
        if cursor not in shown:
            cursor = self._history_anchor if self._history_anchor in shown else None
        if cursor is None:
            index = 0 if step > 0 else len(shown) - 1
        else:
            index = max(0, min(shown.index(cursor) + step, len(shown) - 1))
        anchor = self._history_anchor
        self.selectLap(shown[index], 2 if extend and anchor in shown else 0)
        if extend and anchor in shown:  # range kept from the anchor, never added to an older selection
            first, last = sorted((shown.index(anchor), index))
            self.set_history_selection(set(shown[first:last + 1]))
        return index

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
            filename, extension = api.read.session.combo_name(), FileExt.CONSUMPTION
            # Replaced in one step, never changed in place (stint module & overlays read it from other threads),
            # saved under the lock stint module adds laps & saves with: lap added meanwhile kept, none saved back
            with minfo.history.consumptionLock:
                history = without_laps(minfo.history.consumptionDataSet, removed)
                minfo.history.consumptionDataSet = history
                minfo.history.consumptionDataVersion += 1
                saved = not filename or write_history(cfg.path.fuel_delta, filename, extension, history_laps(history))
        else:
            filepath, filename, extension = self.history_file
            saved = not filename or write_history(filepath, filename, extension, kept)
        if not saved:
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

    # Team stints (game strategy data)
    def update_team_timer(self):
        """Game asked at once, then every few seconds while team tab is shown"""
        if self.active and self.game_data and self.tab == TABS.index("team"):
            if not self._team_timer.isActive():
                self._team_timer.start()
                self.refresh_team()
        else:
            self._team_timer.stop()

    @Slot()
    def refresh_team(self):
        if self.game_data and self.team_request.start(partial(read_team_usage, USAGE_RESOURCES)):
            self.team_status_changed()

    @Slot()
    def refreshTeam(self):
        if not self.game_data_refused():
            self.refresh_team()

    def team_status_changed(self):
        """Status line & busy state shown again (rows & drivers left as they are)"""
        self.teamStatusChanged.emit()
        self.teamChanged.emit()

    def received_team(self, answer: tuple[list[StintUsage] | None, float]):
        """Game answers read in background (read_team_usage): stints, tank capacity (liters)"""
        self.team_request.busy = False
        stints, capacity = answer
        if stints is None:
            self.team_status = tr("No data from game: LMU not running or not in a session")
            self.team_status_changed()
            return
        self.show_team_stints(stints, self.unit_fuel(capacity) if capacity else 0.0)
        self.team_status = trm("Updated from game at {}").replace("{}", clock_seconds(), 1)
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
