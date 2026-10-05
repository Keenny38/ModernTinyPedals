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
Race calculator, team tab: stints of every driver of the team car (teammates included), read from
game strategy data (LMU), usage per lap of each stint & driver, filled in calculator

Asked to game while tab is shown, also from the monitor while a teammate drives.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .. import units
from ..api_control import api
from ..i18n import tr, trm
from ..process.team_usage import StintUsage, combine_usage, driver_usage, parse_usage, stint_usage, tank_capacity
from ..setting import cfg
from ._common import NumericTableItem, UIScaler
from .game_rest import GameRequest
from .race_widgets import muted_label

USAGE_RESOURCES = ("/rest/strategy/usage", "/rest/garage/UIScreen/RepairAndRefuel")
REFRESH_MS = 15000  # game asked again while tab shown
STINT_ROLE = Qt.ItemDataRole.UserRole + 1  # stint item: index in stints


class TeamStintsPanel(QFrame):
    """Team stints: table of stints (driver, laps, usage per lap), usage of each driver, fill in"""

    def __init__(self, parent, calculator):
        super().__init__(parent)
        self.setObjectName("fuelCard")
        self.calculator = calculator
        self.unit_fuel = units.set_unit_fuel(cfg.units["fuel_unit"])
        self.symbol_fuel = units.set_symbol_fuel(cfg.units["fuel_unit"])
        self.stints: list[StintUsage] = []
        self.capacity = 0.0  # tank capacity of car (fuel unit), 0 if unknown
        self.request = GameRequest(self, USAGE_RESOURCES, self.received)

        title = QLabel(tr("Team Stints"))
        title.setObjectName("fuelCardTitle")
        self.button_refresh = QPushButton(tr("Refresh"))
        self.button_refresh.setToolTip(tr("Ask game again"))
        self.button_refresh.clicked.connect(self.refresh)
        layout_title = QHBoxLayout()
        layout_title.addWidget(title, stretch=1)
        layout_title.addWidget(self.button_refresh)
        hint = muted_label(tr("Stints of every driver of the car read from the game (LMU), teammates included: "
                              "usage per lap, out laps & pit laps left out. Select stints, then fill in: "
                              "their average goes to the calculator."))
        hint.setWordWrap(True)

        self.table = QTableWidget(self)
        headers = (tr("Driver"), tr("Stint"), tr("Laps"), tr("Laps counted"),
                   f"{tr('Fuel')} ({self.symbol_fuel})", f"{tr('Energy')} (%)", f"{tr('Tyre')} (%)")
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)  # stints in driven order until a column is clicked
        self.table.setMinimumHeight(UIScaler.size(10))

        self.label_empty = muted_label(tr("No team stint from game yet: LMU running with the car on track needed."))
        self.label_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_empty.setWordWrap(True)
        self.label_drivers = QLabel("")
        self.label_drivers.setWordWrap(True)
        self.label_status = muted_label("")

        self.button_fill = QPushButton(tr("Fill In Calculator"))
        self.button_fill.setToolTip(tr("Average per lap of selected stints (all stints if none selected): "
                                       "fuel, energy & tyre wear"))
        self.button_fill.clicked.connect(self.fill_in)
        layout_buttons = QHBoxLayout()
        layout_buttons.addWidget(self.label_status, stretch=1)
        layout_buttons.addWidget(self.button_fill)
        for button in (self.button_refresh, self.button_fill):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        layout = QVBoxLayout(self)
        margin = UIScaler.pixel(10)
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(UIScaler.pixel(6))
        layout.addLayout(layout_title)
        layout.addWidget(hint)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(self.label_empty, stretch=1)
        layout.addWidget(self.label_drivers)
        layout.addLayout(layout_buttons)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self.show_stints([], 0.0)

    def showEvent(self, event):
        """Asked to game at once, then every few seconds while shown"""
        super().showEvent(event)
        self.refresh()
        self._timer.start(REFRESH_MS)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    def refresh(self):
        if self.request.start():
            self.button_refresh.setEnabled(False)

    def received(self, answers: list):
        """Game answers: strategy usage, repair & refuel screen (tank capacity)"""
        self.button_refresh.setEnabled(True)
        usage, refuel = answers
        if usage is None:
            self.label_status.setText(tr("No data from game: LMU not running or not in a session"))
            return
        capacity = tank_capacity(refuel)
        self.show_stints(stint_usage(parse_usage(usage)), self.unit_fuel(capacity) if capacity else 0.0)
        self.label_status.setText(trm(f"Updated from game at {time.strftime('%H:%M:%S')}"))

    def car_capacity(self) -> float:
        """Tank capacity (fuel unit): of the car from game, else of calculator, else of live car"""
        return (self.capacity or self.calculator.input_fuel.capacity.value()
                or self.unit_fuel(api.read.engine.tank_capacity()))

    def show_stints(self, stints: Sequence[StintUsage], capacity: float):
        """Stints in table (selection kept when same stints), usage of each driver below"""
        selected = {(usage.driver, usage.stint) for usage in self.selected_stints()}
        self.stints = list(stints)
        self.capacity = capacity
        capacity = self.car_capacity()
        table = self.table
        table.setSortingEnabled(False)
        table.clearContents()
        table.setRowCount(len(self.stints))
        for row_index, usage in enumerate(self.stints):
            fuel = usage.fuel * capacity
            row_items = (
                (usage.stint, f"{usage.stint}"),
                (usage.first_lap, f"{usage.first_lap}-{usage.last_lap}"),
                (usage.laps, f"{usage.laps}"),
                (fuel, f"{fuel:.3f}" if usage.laps and capacity else "-"),
                (usage.energy, f"{usage.energy * 100:.3f}" if usage.laps else "-"),
                (usage.wear, f"{usage.wear:.3f}" if usage.laps else "-"),
            )
            items = [QTableWidgetItem(usage.driver), *(NumericTableItem(value, text) for value, text in row_items)]
            for column_index, item in enumerate(items):
                item.setData(STINT_ROLE, row_index)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if not usage.laps:
                    item.setFlags(Qt.ItemFlag.NoItemFlags)  # nothing measured: not selectable
                table.setItem(row_index, column_index, item)
            if (usage.driver, usage.stint) in selected:
                table.selectionModel().select(
                    table.model().index(row_index, 0),
                    QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        table.setSortingEnabled(True)
        has_rows = bool(self.stints)
        table.setHidden(not has_rows)
        self.label_empty.setHidden(has_rows)
        self.button_fill.setEnabled(any(usage.laps for usage in self.stints))
        self.label_drivers.setText("<br>".join(self.driver_text(usage, capacity) for usage in driver_usage(self.stints)))

    def driver_text(self, usage: StintUsage, capacity: float) -> str:
        """Usage per lap of a driver, all stints"""
        if not usage.laps:
            return f"<b>{usage.driver}</b> · {tr('No lap counted')}"
        parts = [f"<b>{usage.driver}</b>", f"{usage.laps} {tr('laps')}"]
        if capacity:
            parts.append(f"{usage.fuel * capacity:.2f} {self.symbol_fuel}")
        if usage.energy:
            parts.append(f"{usage.energy * 100:.2f} % {tr('Energy').lower()}")
        parts.append(f"{usage.wear:.2f} % {tr('Tyre').lower()}")
        return " · ".join(parts)

    def selected_stints(self) -> list[StintUsage]:
        rows = {item.data(STINT_ROLE) for item in self.table.selectedItems()}
        return [self.stints[row] for row in sorted(rows) if 0 <= row < len(self.stints)]

    def fill_in(self):
        """Average per lap of selected stints (all if none selected) to calculator"""
        stints = self.selected_stints() or self.stints
        self.calculator.fill_in_usage(combine_usage(stints), self.car_capacity())
