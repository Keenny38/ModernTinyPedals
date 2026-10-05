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
Stint history Widget, modern design

Current stint on top, highlighted, then previous stints: laps, time, fuel or energy used,
tyre compounds, tyre wear, lap time delta & consistency.
"""

from __future__ import annotations

from math import ceil

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ... import calculation as calc
from ... import units
from ...module_info import minfo
from .base import ModernOverlay
from .draw import panel
from .table import RIGHT, TEXT, Cell, Column, Row, TableMixin


class Realtime(TableMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "stint_history_count", "show_empty_history", "show_laps", "show_time",
        "show_fuel", "show_fuel_sign", "decimal_places_fuel", "show_virtual_energy_if_available",
        "show_tyre", "show_wear", "show_wear_sign", "decimal_places_wear",
        "show_delta", "decimal_places_delta", "show_consistency", "show_consistency_sign", "decimal_places_consistency",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.stint_slot = min(max(int(wcfg["stint_history_count"]), 1), 100)
        self.unit_fuel = units.set_unit_fuel(self.cfg.units["fuel_unit"])
        self.sign_fuel = units.set_symbol_fuel(self.cfg.units["fuel_unit"])[0].upper() if wcfg["show_fuel_sign"] else ""
        self.sign_wear = "%" if wcfg["show_wear_sign"] else ""
        self.sign_consist = "%" if wcfg["show_consistency_sign"] else ""
        self.dec_fuel = max(int(wcfg["decimal_places_fuel"]), 0)
        self.dec_wear = max(int(wcfg["decimal_places_wear"]), 0)
        self.dec_delta = max(int(wcfg["decimal_places_delta"]), 0)
        self.dec_consist = max(int(wcfg["decimal_places_consistency"]), 0)
        columns = []
        if wcfg["show_laps"]:
            columns.append(Column("laps", self.text_width("value", "888"), RIGHT, "Laps"))
        if wcfg["show_time"]:
            columns.append(Column("time", self.text_width("value", "88:88:88"), RIGHT, "Time"))
        if wcfg["show_fuel"]:
            columns.append(Column("fuel", self.text_width("dim", f"888.{'8' * self.dec_fuel}E"), RIGHT, "Used"))
        if wcfg["show_tyre"]:
            columns.append(Column("tyre", self.text_width("dim", "MMMM"), RIGHT, "Tyre"))
        if wcfg["show_wear"]:
            columns.append(Column("wear", self.text_width("dim", f"88.{'8' * self.dec_wear}%"), RIGHT, "Wear"))
        if wcfg["show_delta"]:
            columns.append(Column("delta", self.text_width("dim", f"+8.{'8' * self.dec_delta}"), RIGHT, "Delta"))
        if wcfg["show_consistency"]:
            columns.append(Column("consistency", self.text_width("dim", f"88.{'8' * self.dec_consist}%"), RIGHT, "Consist."))
        self.table = self.build_table(columns, 1.45, header=True)
        self.history_rows: tuple = ()
        self.last_data_version = -1
        self.resize_rows(1)

    def resize_rows(self, rows: int):
        """Widget height for number of rows"""
        height = self.table.height(rows)
        if ceil(height) != self.height():
            self.set_size(self.table.width, height)

    def paint_static(self, painter: QPainter):
        panel(painter, QRectF(self.rect()), self.theme, self.radius(0.5), self.depth_effects)
        self.draw_header(painter)

    def paint(self, painter: QPainter):
        self.draw_rows(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        energy_type = self.wcfg["show_virtual_energy_if_available"] and minfo.energy.available
        current = self.stint_row(minfo.history.stintDataCurrent, energy_type, current=True)
        if self.last_data_version != minfo.history.stintDataVersion:
            self.last_data_version = minfo.history.stintDataVersion
            rows: list[Row | None] = []
            dataset = minfo.history.stintDataSet
            for index in range(self.stint_slot):
                if index < len(dataset):
                    rows.append(self.stint_row(dataset[index], self.wcfg["show_virtual_energy_if_available"]))
                elif self.wcfg["show_empty_history"]:
                    rows.append(None)
            self.history_rows = tuple(rows)
            self.resize_rows(1 + len(rows))
        self.refresh((current, *self.history_rows))

    def stint_row(self, data, energy_type: bool, current: bool = False) -> Row:
        """Cells of one stint"""
        theme = self.theme
        cells = []
        for column in self.table.columns:
            key = column.key
            if key == "laps":
                cells.append(Cell(TEXT, f"{max(data.totalLaps, 0)}", "value", theme.text))
            elif key == "time":
                cells.append(Cell(TEXT, calc.sec2stinttime(max(data.totalTime, 0)), "value", theme.text))
            elif key == "fuel":
                if energy_type and data.totalEnergy:
                    text = f"{fit(data.totalEnergy, self.dec_fuel)}{'E' if self.sign_fuel else ''}"
                else:
                    text = f"{fit(self.unit_fuel(data.totalFuel), self.dec_fuel)}{self.sign_fuel}"
                cells.append(Cell(TEXT, text, "dim", theme.text_dim))
            elif key == "tyre":
                cells.append(Cell(TEXT, data.tyreCompound, "dim", theme.text_dim))
            elif key == "wear":
                cells.append(Cell(TEXT, f"{fit(data.totalTyreWear, self.dec_wear)}{self.sign_wear}", "dim", theme.text_dim))
            elif key == "delta":
                delta = data.lapTimeDelta
                color = theme.text_dim if not delta else (theme.negative if delta > 0 else theme.positive)
                cells.append(Cell(TEXT, f"{delta:+.{self.dec_delta}f}", "dim", color))
            elif key == "consistency":
                text = f"{data.lapTimeConsistency:.{self.dec_consist}f}{self.sign_consist}"
                cells.append(Cell(TEXT, text, "dim", theme.text_dim))
        return Row(tuple(cells), player=current)


def fit(value: float, size: int) -> str:
    """Number cut to 2 + size characters (size is decimal places for values under 10)"""
    size = max(size, 1)
    return f"{max(value, 0):.{size}f}"[:2 + size].strip(".")
