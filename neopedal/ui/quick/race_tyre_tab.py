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
Race calculator tyre tab (mixin of RaceBackend): tyre plan edits, autosave, tyre plan files, tyre
allocation from game, undo & redo of inputs & tyre plan
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import Slot

from ...const_file import ConfigType, FileExt, FileFilter
from ...i18n import tr, trm
from ...process.team_usage import tyre_allocation as game_tyre_allocation
from ...setting import cfg
from ...userfile.tyre_strategy import (
    DEFAULT_TYRE_SET,
    export_tyre_strategy_file,
    load_tyre_strategy_file,
    save_tyre_strategy_file,
)
from ..file_drop import DROP_TYRE_PLAN
from .race_base import RaceBase
from .race_tyres import (
    AUTOSAVE_NAME,
    WHEELS,
    save_tyre_strategy_file_path,
    set_tyre_strategy_file_path,
)


class TyreTab(RaceBase):
    """Tyre plan & undo of race calculator page"""

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
        except OSError as error:  # logged by write_json
            self.save_failure("tyres", trm(f"Unable to save tyre plan automatically: {error}"))
            return
        self.save_success("tyres")
        config = cfg.user.config["tyre_strategy_planner"]
        if config.get("last_file_name") != self.tyres.name:
            config["last_file_name"] = self.tyres.name
            cfg.save(config_type=ConfigType.CONFIG)

    def tyres_kept(self) -> bool:
        """Page closing: change waiting or last autosave failed saved now, True if tyre plan is kept"""
        if self._autosave_timer.isActive() or "tyres" in self.save_failed:
            self.autosave_tyres()
        return "tyres" not in self.save_failed

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
        self.toast_undo(tr("Tyre taken off"))

    @Slot(int)
    def clearRow(self, row: int):
        self.tyres.clear_cells([(row, corner) for corner in range(WHEELS)])
        self.tyre_plan_changed()
        self.toast_undo(tr("Row cleared"))

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
            self.toast_undo(tr("Unused tyres removed"))
        else:
            self.host.toast(tr("No unused tyre in stock"))

    def toast_undo(self, text: str):
        """Change done without confirmation: toast with an Undo button (host without one: plain toast)"""
        toast_undo = getattr(self.host, "toast_undo", None)
        if callable(toast_undo):
            toast_undo(text)
        else:
            self.host.toast(text)

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
        if filename_full:
            self.open_tyre_plan_file(filename_full)

    def open_tyre_plan_file(self, filename_full: str) -> bool:
        """Tyre strategy file replacing tyre plan (first of Recent menu), True once opened"""
        filepath = os.path.dirname(filename_full) + "/"
        filename = os.path.basename(filename_full)
        user_data = load_tyre_strategy_file(filepath=filepath, filename=filename)
        if user_data is None:
            self.forget_recent(DROP_TYRE_PLAN, filename_full)
            self.host.warn(trm("Cannot open selected file.<br><br>Invalid tyre strategy file."))
            return False
        save_tyre_strategy_file_path(filepath)
        self.apply_tyre_strategy(user_data, os.path.splitext(filename)[0])
        self.remember_recent(DROP_TYRE_PLAN, filename_full)
        return True

    def apply_tyre_strategy(self, user_data: dict, name: str):
        """Tyre strategy (validated file) replacing tyre plan"""
        self.tyres.load(user_data, name)
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
        self.remember_recent(DROP_TYRE_PLAN, filename_full)
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
        if not self.game_data_refused() and self.tyre_request.start():
            self.tyresChanged.emit()

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
        self.undoChanged.emit()

    @Slot()
    def redo(self):
        self.host.redo()
        self.undoChanged.emit()
