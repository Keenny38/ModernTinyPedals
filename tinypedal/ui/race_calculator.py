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
Race calculator: fuel & tyre strategy of a race in one page

Top: data source & actions, race setup and key figures (shared by all tabs).
Fuel tab: lap & consumption inputs, strategy timeline, pit stop plan, details, consumption
history (fuel_calculator). Tyre tab: tyre wear, tyre rules, tyre plan with one row per stint,
tyre stock (tyre_strategy_planner). The tyre change time of each stop is added to that stop,
tyre changes of the tyre plan show on the strategy. Team tab: stints of every driver of the car
read from the game, usage per lap filled in (team_stints).

Replaces the former fuel calculator & tyre strategy planner tools (see tools_view.RENAMED_TOOLS).
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..api_control import api
from ..const_file import ConfigType, FileExt, FileFilter
from ..fuel_strategy import RaceState, full_tank_laps, history_laps
from ..i18n import tr, trm, untr
from ..module_info import ConsumptionDataSet, minfo
from ..race_live import RivalTracker, StopCounter
from ..race_live import read_race_state as read_live
from ..setting import cfg
from ..userfile import atomic_write
from ..userfile.consumption_history import load_consumption_history_file, save_consumption_history_file
from ..userfile.tyre_strategy import validate_tyre_strategy
from ._common import BaseEditor, CompactButton, UIScaler
from .fuel_calculator import RACE_SESSION, CalculatorPanel, HistoryPanel, checked_inputs, live_race_length
from .race_scenarios import decode_share_code, encode_share_code
from .team_stints import TeamStintsPanel
from .toast import show_toast
from .tyre_strategy_planner import (
    MEASURED_DEFAULT,
    TyrePlannerPanel,
    save_tyre_strategy_file_path,
    set_tyre_strategy_file_path,
)

WIDE_PAGE = 80  # page width (in lines) from which history sits beside calculator
MIN_PAGE = 46  # narrowest page width (in lines): race setup & key figures on two rows
RACE_PLAN_FORMAT = "modern-tiny-pedals-race-plan"
RACE_PLAN_VERSION = 1
LIVE_REFRESH_MS = 2000  # live history check while page shown


def write_history(filepath: str, filename: str, extension: str, laps: Sequence[ConsumptionDataSet]):
    """Consumption history file rewritten with laps kept, removed when none left"""
    full_path = f"{filepath}{filename}{extension}"
    if not laps:
        if os.path.exists(full_path):
            os.remove(full_path)
        return
    dataset = list(laps) if len(laps) > 1 else [*laps, ConsumptionDataSet()]  # placeholder: skipped on load
    save_consumption_history_file(dataset=dataset, filepath=filepath, filename=filename, extension=extension)


def scroll_page(widget: QWidget) -> QScrollArea:
    """Tab content scrolled when window is small"""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidget(widget)
    return scroll


class RaceCalculator(BaseEditor):
    """Race calculator (fuel & tyres)"""

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Race Calculator"))
        self.status_bar = QStatusBar(self)  # holds source message, source chip in header shows it
        self.status_bar.hide()
        self.live_source = True
        self._live_signature: tuple = ()
        self.history_file = ("", "", "")  # file source: path, name, extension

        # Header: data source & actions
        self.label_source = QLabel("")
        self.label_source.setObjectName("fuelSource")
        button_loadlive = QPushButton(tr("Load Live"))
        button_loadlive.setToolTip(tr("Laps of current session, race length of a live race"))
        button_loadlive.clicked.connect(self.load_live_data)
        button_loadfile = QPushButton(tr("Load File"))
        button_loadfile.setToolTip(tr("Consumption history file"))
        button_loadfile.clicked.connect(self.load_file_data)
        button_reset = QPushButton(tr("Reset to Zero"))
        button_reset.setToolTip(tr("Clear every input"))
        button_reset.clicked.connect(self.reset_values)
        self.button_toggle = QPushButton(tr("Hide History"))
        self.button_toggle.setCheckable(True)
        self.button_toggle.setChecked(True)
        self.button_toggle.toggled.connect(self.toggle_history_panel)
        self.check_follow = QCheckBox(tr("Follow Live"))
        self.check_follow.setToolTip(tr("Inputs follow each new lap of the live session"))
        self.check_follow.setChecked(bool(cfg.user.config["fuel_calculator"].get("enable_follow_live")))
        self.check_follow.toggled.connect(self.toggle_follow_live)
        config = cfg.user.config["fuel_calculator"]
        self.check_live_race = QCheckBox(tr("Live Race"))
        self.check_live_race.setToolTip(tr("During a race: plan of the rest of the race from now "
                                           "(laps & time done, fuel, energy & tyres of the car, stops done)"))
        self.check_live_race.setChecked(bool(config.get("enable_live_race")))
        self.check_live_race.toggled.connect(self.toggle_live_race)
        self._race_key: tuple | None = None
        self.label_live = QLabel("")
        self.label_live.setEnabled(False)  # muted
        self.stop_counter = StopCounter()
        self.rival_tracker = RivalTracker()
        plan_menu = QMenu(self)
        plan_menu.addAction(tr("Open Race Plan...")).triggered.connect(lambda: self.load_race_plan())
        plan_menu.addAction(tr("Save Race Plan As...")).triggered.connect(lambda: self.save_race_plan())
        plan_menu.addAction(tr("Copy Share Code")).triggered.connect(self.copy_share_code)
        plan_menu.addAction(tr("Paste Share Code...")).triggered.connect(self.paste_share_code)
        plan_menu.addSeparator()
        self.action_save_combo = plan_menu.addAction(tr("Save for Current Car & Track"))
        self.action_save_combo.setToolTip(tr("Opened again when this car & track are driven"))
        self.action_save_combo.triggered.connect(self.save_combo_plan)
        self.action_auto_combo = plan_menu.addAction(tr("Open Plan of Car & Track Automatically"))
        self.action_auto_combo.setCheckable(True)
        self.action_auto_combo.setChecked(bool(config.get("enable_auto_load_combo_plan", True)))
        self.action_auto_combo.toggled.connect(self.toggle_auto_combo_plan)
        plan_menu.aboutToShow.connect(lambda: self.action_save_combo.setEnabled(bool(self.combo_name())))
        self._combo_loaded = ""
        button_plan = CompactButton(tr("Race Plan"), has_menu=True)
        button_plan.setToolTip(tr("Race setup, fuel & tyre plan in one file, to keep or share"))
        button_plan.setMenu(plan_menu)
        layout_header = QHBoxLayout()
        layout_header.addWidget(self.label_source)
        layout_header.addWidget(self.check_follow)
        layout_header.addWidget(self.check_live_race)
        layout_header.addWidget(self.label_live)
        layout_header.addStretch(1)
        for button in (button_plan, button_loadlive, button_loadfile, button_reset, self.button_toggle):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            layout_header.addWidget(button)

        # Fuel & tyre sides, linked
        self.panel_calculator = calc = CalculatorPanel(self)
        self.panel_history = HistoryPanel(self)
        self.button_adddata = self.panel_history.button_adddata
        self.button_adddata.clicked.connect(self.add_selected_data)
        self.tyre_planner = planner = TyrePlannerPanel(self, host=self)
        planner.add_left_card(calc.card_tyre_input, 0)
        planner.add_left_card(calc.card_tyre_life)
        planner.proposed_rows = lambda: calc.proposed_tyre_rows
        planner.wear_per_lap = calc.input_tyre.wear_lap.value
        planner.minimum_tread = calc.input_tyre.minimum_tread.value
        calc.card_tyre_input.add_row(tr("Measured Compound"), planner.combo_measured, 3)
        planner.status_listener = calc.set_tyre_status
        planner.changed.connect(calc.update_input)
        calc.tyre_link = planner
        calc.history_source = lambda: self.panel_history.dataset
        calc.stint_source = self.race_stints
        self.enable_undo(self.capture_state, self.restore_state)  # inputs & tyre plan edits
        calc.inputs_changed = self.record_change
        self.add_undo_buttons(planner.tyre_plan_panel.layout_top)

        # Fuel tab: calculator & history (history below on narrow page)
        fuel_body = QWidget()
        fuel_body.setObjectName("pageStack")
        self.layout_body = layout_body = QBoxLayout(QBoxLayout.Direction.LeftToRight, fuel_body)
        layout_body.setContentsMargins(0, 0, 0, 0)
        layout_body.setSpacing(UIScaler.pixel(10))
        layout_body.addWidget(calc, stretch=3)
        layout_body.addWidget(self.panel_history, stretch=2)
        planner.setObjectName("pageStack")
        planner.setMinimumHeight(UIScaler.size(30))

        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(scroll_page(fuel_body), tr("Fuel"))
        self.tabs.addTab(scroll_page(planner), tr("Tyres"))
        self.panel_team = TeamStintsPanel(self, calc)
        self.tabs.addTab(self.panel_team, tr("Team"))

        layout_main = QVBoxLayout(self)
        layout_main.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        layout_main.setSpacing(UIScaler.pixel(8))
        layout_main.addLayout(layout_header)
        layout_main.addWidget(calc.card_race)
        layout_main.addWidget(calc.tiles)
        layout_main.addWidget(self.tabs, stretch=1)
        self.resize(UIScaler.size(76), UIScaler.size(48))
        # Own minimum (narrow layout), else wide layout minimum keeps page from narrowing
        self.setMinimumWidth(UIScaler.size(MIN_PAGE))
        self._wide = True

        self.button_toggle.setChecked(config["show_consumption_history"])
        # Inputs of a race plan opened last time kept: live laps shown, not filled in
        self.show_live_data(fill_inputs=not config.get("enable_plan_inputs"))
        self.auto_load_combo_plan()
        calc.update_input()  # tyre plan linked: rows & tyre tile
        self.refresh_race_state()
        self.reset_undo()  # history starts with the page shown

        # Live history follows new laps while page is shown, live race state, plan of car & track
        self._live_timer = QTimer(self)
        self._live_timer.timeout.connect(self.refresh_live)
        self._live_timer.start(LIVE_REFRESH_MS)

    def saving(self):
        """Save tyre plan to a file"""
        self.tyre_planner.saving()

    def confirm_discard(self) -> bool:
        """Tyre plan kept automatically between sessions: nothing to lose"""
        return True

    def closeEvent(self, event):
        self.tyre_planner.autosave()
        self.panel_calculator.flush_plan_file()
        super().closeEvent(event)

    def resizeEvent(self, event):
        """Narrow page: history below calculator, race setup & key figures on two rows"""
        super().resizeEvent(event)
        calc = self.panel_calculator
        wide = self.width() >= max(UIScaler.size(WIDE_PAGE), calc.wide_top_width() + self.MARGIN * 2)
        if wide != self._wide:
            self._wide = wide
            self.layout_body.setDirection(
                QBoxLayout.Direction.LeftToRight if wide else QBoxLayout.Direction.TopToBottom)
            calc.arrange_top(wide)
            self.tyre_planner.set_wide(wide)

    def set_source(self, live: bool, name: str):
        """Source chip & status bar message"""
        self.live_source = live
        dot = "#3DDC84" if live else "#5AAEFF"
        kind = tr("Live") if live else tr("File")
        self.label_source.setText(f"<span style='color:{dot}'>●</span> <b>{kind}</b> · {name or '-'}")
        self.status_bar.showMessage(trm(f"Live Source: {name}") if live else trm(f"File Source: {name}"))

    def load_file_data(self):
        """Load history data from file (consumption or CSV file)"""
        filename_full = QFileDialog.getOpenFileName(
            self,
            dir=cfg.path.fuel_delta,
            filter=";;".join((FileFilter.CONSUMPTION, FileFilter.CSV))
        )[0]
        if not filename_full:
            return

        filepath = os.path.dirname(filename_full) + "/"
        filename, extension = os.path.splitext(os.path.basename(filename_full))
        history_data = history_laps(load_consumption_history_file(
            filepath=filepath,
            filename=filename,
            extension=extension,
        ))
        if not history_data:
            QMessageBox.warning(self, tr("Error"), trm(f"Unable to read consumption history: {filename}{extension}"))
            return
        self.panel_calculator.fill_in_data(history_data, live=False)
        self.panel_history.refresh(history_data)
        self.history_file = (filepath, filename, extension)
        self.set_source(False, filename)
        self.set_plan_inputs(False)

    def load_live_data(self):
        """Load history data from live session, race length of a live race (inputs filled in)"""
        self.show_live_data(fill_inputs=True)
        self.set_plan_inputs(False)

    def show_live_data(self, fill_inputs: bool):
        """History of live session in table, inputs filled in from it (and race length) or kept"""
        history_data = history_laps(minfo.history.consumptionDataSet)
        self._live_signature = self.history_signature(history_data)
        if fill_inputs:
            self.panel_calculator.fill_in_data(history_data, live_race_length())
        self.panel_history.refresh(history_data)
        self.set_source(True, api.read.session.combo_name())

    @staticmethod
    def set_plan_inputs(from_plan: bool):
        """Inputs of a race plan (kept when page opens) or of laps (filled in from live laps)"""
        config = cfg.user.config["fuel_calculator"]
        if config.get("enable_plan_inputs") != from_plan:
            config["enable_plan_inputs"] = from_plan
            cfg.save(config_type=ConfigType.CONFIG)

    @staticmethod
    def history_signature(dataset: Sequence[ConsumptionDataSet]) -> tuple:
        latest = dataset[0] if dataset else None
        return (len(dataset), latest)

    def refresh_live(self):
        """Every few seconds: stops counted, and while page shown: new laps, live race state,
        plan of car & track, class rivals"""
        live = read_live(self.panel_calculator.unit_fuel, self.stop_counter, self.panel_calculator.symbol_fuel)
        if not self.isVisible():
            return
        self.refresh_live_history()
        self.refresh_race_state(live)
        self.auto_load_combo_plan()
        self.refresh_rivals()

    # Undo & redo: inputs & tyre plan
    def capture_state(self) -> dict:
        return {"tyres": self.tyre_planner.capture_state(), "inputs": self.panel_calculator.input_values()}

    def restore_state(self, state: dict):
        with self.panel_calculator.batch():
            self.tyre_planner.restore_state(state["tyres"])
            self.panel_calculator.set_input_values(checked_inputs(state["inputs"]))

    @staticmethod
    def race_stints() -> list:
        """Stints of the race in progress (stint history of live session), newest first"""
        if api.read.session.session_type() != RACE_SESSION:
            return []
        return [stint for stint in minfo.history.stintDataSet if stint.totalLaps > 0]

    def refresh_rivals(self):
        """Cars of the player class in a live race"""
        calc = self.panel_calculator
        if api.read.session.session_type() != RACE_SESSION or not api.read.state.active():
            calc.card_rivals.set_rivals([], 0)
            return
        calc.card_rivals.set_rivals(self.rival_tracker.update(), full_tank_laps(calc.plan_setup))

    # Live race: plan of the rest of the race
    def toggle_live_race(self, checked: bool):
        config = cfg.user.config["fuel_calculator"]
        if config.get("enable_live_race") != checked:
            config["enable_live_race"] = checked
            cfg.save(config_type=ConfigType.CONFIG)
        self.refresh_race_state()

    # Share code: race plan in one line of text
    def copy_share_code(self):
        QGuiApplication.clipboard().setText(encode_share_code(self.race_plan_data()))
        show_toast(self, tr("Share code of race plan copied"))

    def paste_share_code(self):
        """Race plan of a share code (clipboard proposed)"""
        text, accepted = QInputDialog.getText(
            self, tr("Paste Share Code..."), tr("Race plan share code:"),
            text=QGuiApplication.clipboard().text().strip())
        if not accepted or not text.strip():
            return
        try:
            data = decode_share_code(text)
        except ValueError:
            QMessageBox.warning(self, tr("Error"), tr("Invalid race plan share code."))
            return
        if self.apply_race_plan(data, tr("Shared plan")):
            show_toast(self, tr("Race plan of share code opened"))

    def refresh_race_state(self, live=None):
        """Rest of race planned again at each lap & stop (not while in the pits), status shown
        next to Live Race (values read from the game in its tooltip, to check them)"""
        calc = self.panel_calculator
        if live is None:
            live = read_live(calc.unit_fuel, self.stop_counter, calc.symbol_fuel)
        checked = self.check_live_race.isChecked()
        state: RaceState | None = live.state if checked else None
        if not checked:
            status = ""
        elif state is not None:
            status = f"{tr('from lap')} {state.laps_done + 1}" + (f" · {tr('in the pits')}" if live.in_pits else "")
        else:
            status = tr("waiting for the race") if not live.text else tr("waiting for lap 1")
        self.label_live.setText(status)
        self.label_live.setToolTip(
            f"{tr('Lap')} (+{tr('progress')}) · {tr('race time')} / {tr('time left')} · {tr('fuel')} · "
            f"{tr('energy')} · {tr('tread')} · {tr('stops')} ({tr('game')})<br>{live.text}" if live.text else "")
        if state is not None and live.in_pits:
            return
        key = (state.laps_done, state.stops_done) if state is not None else None
        if key != self._race_key:
            self._race_key = key
            calc.set_race_state(state)

    # Plan of car & track
    @staticmethod
    def combo_name() -> str:
        return api.read.session.combo_name() if api.read.state.active() else ""

    def combo_plan_path(self, combo: str) -> str:
        return f"{cfg.path.fuel_delta}{combo}{FileExt.RACEPLAN}"

    def save_combo_plan(self):
        """Race plan opened again when this car & track are driven"""
        combo = self.combo_name()
        if combo:
            self.save_race_plan(self.combo_plan_path(combo))
            self._combo_loaded = combo

    def toggle_auto_combo_plan(self, checked: bool):
        config = cfg.user.config["fuel_calculator"]
        if config.get("enable_auto_load_combo_plan") != checked:
            config["enable_auto_load_combo_plan"] = checked
            cfg.save(config_type=ConfigType.CONFIG)
        if checked:
            self.auto_load_combo_plan()

    def auto_load_combo_plan(self):
        """Race plan of car & track driven opened once per car & track"""
        if not self.action_auto_combo.isChecked():
            return
        combo = self.combo_name()
        if not combo or combo == self._combo_loaded:
            return
        self._combo_loaded = combo
        filename = self.combo_plan_path(combo)
        if os.path.exists(filename) and self.load_race_plan(filename, quiet=True):
            show_toast(self, trm(f"Race plan of {combo} opened"))

    def refresh_live_history(self):
        """New live laps added to history table (inputs left as they are)"""
        if not self.live_source or not self.isVisible():
            return
        history_data = history_laps(minfo.history.consumptionDataSet)
        signature = self.history_signature(history_data)
        if signature != self._live_signature:
            self._live_signature = signature
            self.panel_history.refresh(history_data)
            if self.check_follow.isChecked():
                self.panel_calculator.fill_in_data(history_data)

    def add_selected_data(self):
        """Add selected data to calculator"""
        selected_data = self.panel_history.table_history.selectedItems()
        if not selected_data:
            QMessageBox.warning(self, tr("Error"), tr("No data selected."))
            return
        used, skipped = self.panel_calculator.add_table_data(selected_data)
        if not used:
            QMessageBox.warning(self, tr("Error"), tr("Selected laps are all invalid."))
            return
        text = trm(f"Average of {used} lap(s) added")
        if skipped:
            text += " · " + trm(f"{skipped} invalid lap(s) left out")
        self.panel_history.label_added.setText(text)

    def reset_values(self):
        """Every input back to zero (tyre tread to new tyres), tyre plan kept"""
        self.panel_calculator.reset_inputs()
        self.panel_history.label_added.setText("")

    def toggle_history_panel(self, checked: bool):
        """Toggle history data panel"""
        self.panel_history.setHidden(not checked)
        self.button_toggle.setText(tr("Hide History") if checked else tr("Show History"))
        config = cfg.user.config["fuel_calculator"]
        if checked != config["show_consumption_history"]:
            config["show_consumption_history"] = checked
            cfg.save(config_type=ConfigType.CONFIG)

    def table_header_menu(self, position: QPoint):
        """Open table header context menu"""
        table = self.panel_history.table_history
        self.column_menu(table.mapToGlobal(position))

    def column_menu(self, global_position: QPoint):
        """Menu of optional history columns, checked ones shown"""
        config = cfg.user.config["fuel_calculator"]
        menu = QMenu()  # no parent for temp menu

        for option_name in config:
            if option_name.startswith("show_column"):
                action_name = option_name.replace("show_column_", "").replace("_", " ").title()
                action = menu.addAction(tr(action_name))
                action.setCheckable(True)
                action.setChecked(config[option_name])

        selected_action = menu.exec(global_position)
        if not selected_action:
            return

        selected_name = "show_column_" + untr(selected_action.text()).replace(" ", "_").lower()
        for option_name in config:
            if selected_name == option_name:
                config[option_name] = not config[option_name]
                self.panel_history.toggle_column()
                cfg.save(config_type=ConfigType.CONFIG)
                break

    def toggle_follow_live(self, checked: bool):
        """Inputs follow new live laps (kept for next time)"""
        config = cfg.user.config["fuel_calculator"]
        if config.get("enable_follow_live") != checked:
            config["enable_follow_live"] = checked
            cfg.save(config_type=ConfigType.CONFIG)
        if checked and self.live_source:
            self.panel_calculator.fill_in_data(history_laps(minfo.history.consumptionDataSet))

    # Consumption history deletion
    def delete_laps(self, indexes: set[int] | None):
        """Delete selected laps (indexes in history data), or whole history (None), after confirmation"""
        dataset = self.panel_history.dataset
        if indexes is not None and not indexes:
            QMessageBox.warning(self, tr("Error"), tr("No data selected."))
            return
        removed = [lap for index, lap in enumerate(dataset) if indexes is None or index in indexes]
        kept = [lap for index, lap in enumerate(dataset) if indexes is not None and index not in indexes]
        if not removed:
            return
        message = (trm(f"Delete <b>{len(removed)}</b> lap(s) from consumption history?")
                   if indexes is not None else tr("<b>Delete whole consumption history?</b>"))
        if not self.confirm_operation(message=message + "<br><br>" + trm("This cannot be undone!")):
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
        if filename:
            write_history(filepath, filename, extension, kept)
        self._live_signature = self.history_signature(kept)
        self.panel_history.refresh(kept)
        self.panel_history.label_added.setText(trm(f"{len(removed)} lap(s) deleted"))

    # Race plan file: race setup, fuel & tyre plan
    def race_plan_data(self) -> dict:
        inputs = self.panel_calculator.input_values()
        inputs["input_measured_compound"] = self.tyre_planner.combo_measured.currentIndex()
        return {
            "format": RACE_PLAN_FORMAT,
            "version": RACE_PLAN_VERSION,
            "plan_name": self.tyre_planner.tyre_plan_panel.filename(),
            "inputs": inputs,
            "tyre_strategy": self.tyre_planner.capture_data(),
        }

    def save_race_plan(self, filename_full: str = ""):
        """Save race plan file (asked when no file name given)"""
        if not filename_full:
            name = self.tyre_planner.tyre_plan_panel.filename() or tr("Untitled plan")
            filename_full, _ = QFileDialog.getSaveFileName(
                self, dir=set_tyre_strategy_file_path(f"{name}{FileExt.RACEPLAN}"), filter=FileFilter.RACEPLAN)
            if not filename_full:
                return
            save_tyre_strategy_file_path(os.path.dirname(filename_full) + "/")
        with atomic_write(filename_full) as file:
            json.dump(self.race_plan_data(), file, indent=4)
        show_toast(self, trm(f"Race plan saved at:<br><b>{filename_full}</b>"))

    def load_race_plan(self, filename_full: str = "", quiet: bool = False) -> bool:
        """Open race plan file (asked when no file name given): race setup, fuel & tyre plan
        replaced (tyre plan undoable), True once opened"""
        if not filename_full:
            filename_full, _ = QFileDialog.getOpenFileName(
                self, dir=set_tyre_strategy_file_path(), filter=FileFilter.RACEPLAN)
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
                QMessageBox.warning(self, tr("Error"), trm(f"Invalid race plan file: {os.path.basename(filename_full)}"))
            return False
        return True

    def apply_race_plan(self, data, name: str) -> bool:
        """Race setup, fuel & tyre plan of race plan data replaced, False if not a race plan"""
        try:
            if not isinstance(data, dict) or data.get("format") != RACE_PLAN_FORMAT:
                raise ValueError
            inputs: dict = data["inputs"] if isinstance(data.get("inputs"), dict) else {}
            tyre_data = validate_tyre_strategy(data.get("tyre_strategy") or {})
        except (ValueError, TypeError, AttributeError):
            return False
        planner = self.tyre_planner
        # One calculation with the whole plan loaded: rows of the new tyre plan follow the new
        # stints, not the ones of the plan replaced (whose rows kept aside are dropped)
        with self.panel_calculator.batch():
            index = inputs.get("input_measured_compound", MEASURED_DEFAULT)
            if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < planner.combo_measured.count():
                planner.combo_measured.setCurrentIndex(index)
            planner.user_data = tyre_data
            planner.clear_kept_rows()
            planner.tyre_plan_panel.set_filename(str(data.get("plan_name") or name))
            planner.refresh_table()
            self.panel_calculator.set_input_values(checked_inputs(inputs))
        planner.autosave()
        self.set_plan_inputs(True)
        return True
