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
Lap time history Widget, modern design

Current lap (estimated) on top, highlighted, then recent laps: lap time (invalid in red),
delta to previous lap, fuel or virtual energy used, fuel ratio, tyre wear.
"""

from __future__ import annotations

from math import ceil

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ... import calculation as calc
from ... import units
from ...api_control import api
from ...module_info import ConsumptionDataSet, minfo
from .base import DASH, ModernOverlay, display_order_options
from .draw import panel
from .table import RIGHT, TEXT, Cell, Column, Row, TableMixin


class Realtime(TableMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "lap_time_history_count", "show_empty_history", "show_laps", "show_time",
        "show_delta", "decimal_places_delta", "show_fuel", "show_fuel_sign", "decimal_places_fuel",
        "show_virtual_energy_if_available", "show_fuel_ratio", "decimal_places_fuel_ratio",
        "show_wear", "show_wear_sign", "decimal_places_wear", *display_order_options("lap_time_history"),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.history_slot = min(max(int(wcfg["lap_time_history_count"]), 1), 100)
        self.unit_fuel = units.set_unit_fuel(self.cfg.units["fuel_unit"])
        self.sign_fuel = units.set_symbol_fuel(self.cfg.units["fuel_unit"])[0].upper() if wcfg["show_fuel_sign"] else ""
        self.sign_wear = "%" if wcfg["show_wear_sign"] else ""
        self.dec_delta = max(int(wcfg["decimal_places_delta"]), 0)
        self.dec_fuel = max(int(wcfg["decimal_places_fuel"]), 0)
        self.dec_ratio = max(int(wcfg["decimal_places_fuel_ratio"]), 0)
        self.dec_wear = max(int(wcfg["decimal_places_wear"]), 0)
        columns = []
        if wcfg["show_laps"]:
            columns.append(Column("laps", self.text_width("dim", "888"), label="Lap"))
        if wcfg["show_time"]:
            columns.append(Column("time", self.text_width("value", "8:88.888"), RIGHT, "Time"))
        if wcfg["show_delta"]:
            columns.append(Column("delta", self.text_width("dim", f"+88.{'8' * self.dec_delta}"), RIGHT, "Delta"))
        if wcfg["show_fuel"]:
            columns.append(Column("fuel", self.text_width("dim", f"88.{'8' * self.dec_fuel}{self.sign_fuel or ''}E"), RIGHT, "Used"))
        if wcfg["show_fuel_ratio"]:
            columns.append(Column("ratio", self.text_width("dim", f"8.{'8' * self.dec_ratio}"), RIGHT, "Ratio"))
        if wcfg["show_wear"]:
            columns.append(Column("wear", self.text_width("dim", f"8.{'8' * self.dec_wear}%"), RIGHT, "Wear"))
        columns = self.display_ordered(columns, names={"ratio": "fuel_ratio"})
        self.table = self.build_table(columns, 1.45, header=True)
        self.empty_data = ConsumptionDataSet()
        self.history_rows: tuple = ()
        self.history_version = 0  # changed with history rows: drawn in static layer
        self.last_data_version = -1
        self.last_energy_type = None
        self.resize_rows(1)

    def resize_rows(self, rows: int):
        """Widget height for number of rows"""
        height = self.table.height(rows)
        if ceil(height) != self.height():
            self.set_size(self.table.width, height)

    def paint_static(self, painter: QPainter):
        """Panel, header & recent laps (they only change when a lap is completed)"""
        panel(painter, QRectF(self.rect()), self.theme, self.radius(0.5), self.depth_effects)
        self.draw_header(painter)
        self.draw_rows(painter, self.history_rows, start=1)

    def paint(self, painter: QPainter):
        self.draw_rows(painter, self.state[:1])  # current lap

    def timerEvent(self, event):
        """Update when vehicle on track"""
        energy_type = self.wcfg["show_virtual_energy_if_available"] and minfo.energy.available
        if energy_type:
            fuel, sign = minfo.energy.estimatedConsumption, "E" if self.sign_fuel else ""
        else:
            fuel, sign = self.unit_fuel(minfo.fuel.estimatedConsumption), self.sign_fuel
        current = self.lap_row(
            api.read.lap.number() + 1, minfo.delta.lapTimeEstimated, True, minfo.delta.deltaLast,
            fuel, sign, minfo.hybrid.fuelEnergyRatio, calc.mean(minfo.wheels.estimatedTreadWear), current=True,
        )
        if self.last_data_version != minfo.history.consumptionDataVersion or self.last_energy_type != energy_type:
            self.last_data_version = minfo.history.consumptionDataVersion
            self.last_energy_type = energy_type
            history_rows = self.history(minfo.history.consumptionDataSet, energy_type)
            if history_rows != self.history_rows:
                self.history_rows = history_rows
                self.history_version += 1
                self.resize_rows(1 + len(history_rows))
                self.redraw_static()
        self.refresh((current, self.history_version))

    def history(self, dataset, energy_type: bool) -> tuple:
        """Rows of recent laps"""
        rows: list[Row | None] = []
        for index in range(self.history_slot):
            if index < len(dataset):
                data = dataset[index]
            elif self.wcfg["show_empty_history"]:
                rows.append(None)
                continue
            else:
                break
            previous = dataset[index + 1] if index + 1 < len(dataset) else self.empty_data
            if energy_type and data.lastLapUsedEnergy:
                fuel, sign = data.lastLapUsedEnergy, "E" if self.sign_fuel else ""
            else:
                fuel, sign = self.unit_fuel(data.lastLapUsedFuel), self.sign_fuel
            # Oldest lap: no previous lap time (empty placeholder lap) to compare with
            delta = data.lapTimeLast - previous.lapTimeLast if previous.lapTimeLast > 0 else None
            rows.append(self.lap_row(
                data.lapNumber, data.lapTimeLast, data.isValidLap, delta,
                fuel, sign, calc.fuel_to_energy_ratio(data.lastLapUsedFuel, data.lastLapUsedEnergy), data.tyreAvgWearLast,
            ))
        return tuple(rows)

    def lap_row(self, lap: int, laptime: float, valid: bool, delta: float | None, fuel: float, sign: str,
                ratio: float, wear: float, current: bool = False) -> Row:
        """Cells of one lap (delta None: no previous lap)"""
        theme = self.theme
        cells = []
        for column in self.table.columns:
            key = column.key
            if key == "laps":
                cells.append(Cell(TEXT, f"{lap}", "dim", theme.text_muted))
            elif key == "time":
                if laptime <= 0:
                    color = theme.text_faint
                elif not valid and not current:
                    color = theme.negative
                else:
                    color = theme.text
                cells.append(Cell(TEXT, calc.sec2laptime_full(laptime)[:8], "value", color))
            elif key == "delta":
                if delta is None or (not current and (laptime <= 0 or abs(delta) > 99)):
                    cells.append(Cell(TEXT, DASH, "dim", theme.text_faint))
                else:
                    text = f"{calc.sym_max(delta, 99.9):+.{self.dec_delta}f}"
                    cells.append(Cell(TEXT, text, "dim", theme.negative if delta > 0 else theme.positive))
            elif key == "fuel":
                cells.append(Cell(TEXT, f"{fuel:.{self.dec_fuel}f}{sign}", "dim", theme.text_dim))
            elif key == "ratio":
                cells.append(Cell(TEXT, f"{ratio:.{self.dec_ratio}f}", "dim", theme.text_dim))
            elif key == "wear":
                cells.append(Cell(TEXT, f"{wear:.{self.dec_wear}f}{self.sign_wear}", "dim", theme.text_dim))
        return Row(tuple(cells), player=current)
