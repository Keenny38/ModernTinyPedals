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
Modern overlay design: driver list widgets base (relative, standings)

Columns are chosen by "column_*" options, in fixed order (COLUMNS of each widget). A widget
adds its own columns (time gap, interval...) by overriding extra_column & extra_cell.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ...const_common import MAX_SECONDS, TEXT_NOLAPTIME
from .base import ModernOverlay
from .draw import panel
from .rows import DASH, RowStyle, class_style, compound_cell, laptime_text, pit_cell
from .table import (
    BADGE,
    CHANGE,
    CLASS,
    EMPTY_CELL,
    RIGHT,
    TEXT,
    Cell,
    Column,
    Row,
    TableMixin,
    compounds_width,
)

ROW_SCALE = 1.62

# Options read by every driver list widget
DRIVER_OPTIONS = (
    "font_size", "show_player_highlighted", "show_lap_difference",
    "column_position", "column_class", "column_position_change", "show_position_change_in_class",
    "column_driver_name", "driver_name_shorten", "driver_name_uppercase", "driver_name_width",
    "column_vehicle_name", "show_vehicle_brand_as_name", "vehicle_name_width",
    "column_tyre_compound", "column_pit_status", "column_pitstop_count", "show_pit_request",
    "column_laptime", "show_highlighted_fastest_last_laptime", "show_pitstop_duration_while_requested_pitstop",
    "column_best_laptime", "show_best_laptime_from_recent_laps_in_race",
    "column_energy_remaining", "column_vehicle_integrity",
    "column_incidents", "incidents_high_threshold", "incidents_extreme_threshold",
    "column_stint_laps",
)


class Context(NamedTuple):
    """Data shared by all rows of one update"""

    in_race: bool
    player: Any  # player vehicle data
    player_pit_request: bool


class DriverTable(TableMixin, ModernOverlay):
    """Driver list widget base"""

    # Column keys in display order (widget defines)
    COLUMNS: tuple[str, ...] = ()

    def setup_table(self):
        """Columns from options"""
        self.row_style = RowStyle(self, self.wcfg)
        columns = []
        for key in self.COLUMNS:
            if self.wcfg.get(f"column_{key}", False):
                column = self.column_of(key)
                if column is not None:
                    columns.append(column)
        self.table = self.build_table(columns, ROW_SCALE)

    def column_of(self, key: str) -> Column | None:
        """Column geometry"""
        unit = self.unit
        if key == "position":
            return Column(key, self.digit_width("strong") * 2 + unit * 0.7)
        if key == "class":
            return Column(key, self.row_style.class_width())
        if key == "position_change":
            return Column(key, unit * 0.62 + self.digit_width("value") * 2)
        if key == "driver_name":
            return Column(key, self.row_style.name_width(self.wcfg.get("driver_name_width", 10)))
        if key == "vehicle_name":
            return Column(key, self.row_style.name_width(self.wcfg.get("vehicle_name_width", 10), "dim"))
        if key == "tyre_compound":
            return Column(key, compounds_width(unit, ROW_SCALE, 2))
        if key == "pit_status":
            return Column(key, self.text_width("label", "SLOW") + unit * 0.8)
        if key == "pitstop_count":
            return Column(key, self.text_width("label", "PEN") + unit * 0.8)
        if key in ("laptime", "best_laptime"):
            return Column(key, self.text_width("dim", "*8:88.888"), RIGHT)
        if key in ("energy_remaining", "vehicle_integrity"):
            return Column(key, self.text_width("dim", "100%"), RIGHT)
        if key == "incidents":
            return Column(key, self.text_width("dim", "x88"), RIGHT)
        if key == "stint_laps":
            return Column(key, self.text_width("dim", "88/88"), RIGHT)
        return self.extra_column(key)

    def extra_column(self, key: str) -> Column | None:
        """Widget own column geometry (override)"""
        return None

    def context(self) -> Context:
        """Data shared by rows of this update"""
        from ...api_control import api
        from ...module_info import minfo

        data_set = minfo.vehicles.dataSet
        index = minfo.vehicles.playerIndex
        player = data_set[index] if 0 <= index < len(data_set) else None
        return Context(
            in_race=api.read.session.in_race(),
            player=player,
            player_pit_request=bool(player is not None and player.pitRequested),
        )

    def driver_row(self, veh, ctx: Context, **extra) -> Row:
        """Cells of one car"""
        wcfg = self.wcfg
        theme = self.theme
        style = self.row_style
        player = veh.isPlayer and wcfg.get("show_player_highlighted", True)
        alias, class_color = class_style(self.cfg, veh.vehicleClass, theme)
        cells = []
        for column in self.table.columns:
            key = column.key
            if key == "position":
                fill = theme.accent if player else theme.surface_raised
                color = style.on_accent if player else theme.text
                cells.append(Cell(BADGE, f"{veh.positionOverall}", "strong", color, fill))
            elif key == "class":
                cells.append(Cell(CLASS, alias, fill=class_color, extra=f"{veh.positionInClass}"))
            elif key == "position_change":
                if wcfg.get("show_position_change_in_class", True):
                    places = veh.qualifyInClass - veh.positionInClass
                else:
                    places = veh.qualifyOverall - veh.positionOverall
                cells.append(Cell(CHANGE, extra=places))
            elif key == "driver_name":
                color = style.lap_color(veh.isLapped, player)
                cells.append(Cell(TEXT, style.driver_name(veh.driverName), "strong" if player else "value", color))
            elif key == "vehicle_name":
                name = veh.vehicleBrand if wcfg.get("show_vehicle_brand_as_name", True) else veh.vehicleName
                cells.append(Cell(TEXT, name, "dim", theme.text_dim))
            elif key == "tyre_compound":
                cells.append(compound_cell(veh.tireCompoundName))
            elif key == "pit_status":
                cells.append(pit_cell(theme, veh.inPit, veh.isYellow, veh.isFinished))
            elif key == "pitstop_count":
                cells.append(style.pitstop_cell(veh.numPitStops, veh.pitRequested))
            elif key == "laptime":
                cells.append(self.laptime_cell(veh, ctx))
            elif key == "best_laptime":
                if ctx.in_race and wcfg.get("show_best_laptime_from_recent_laps_in_race", False):
                    laptime = veh.lapTimeHistory.best
                else:
                    laptime = veh.bestLapTime
                cells.append(Cell(TEXT, laptime_text(laptime), "dim", theme.text_dim))
            elif key == "energy_remaining":
                cells.append(style.energy_cell(veh.energyRemaining))
            elif key == "vehicle_integrity":
                cells.append(style.integrity_cell(veh.vehicleIntegrity))
            elif key == "incidents":
                cells.append(style.incidents_cell(veh.incidents))
            elif key == "stint_laps":
                cells.append(style.stint_cell(veh.currentStintLaps, veh.estimatedStintLaps))
            else:
                cells.append(self.extra_cell(key, veh, ctx, extra))
        faded = veh.inPit == 2 or veh.isFinished
        return Row(tuple(cells), player, class_color if wcfg["column_class"] else None, faded)

    def extra_cell(self, key: str, veh, ctx: Context, extra: dict) -> Cell:
        """Widget own column cell (override)"""
        return EMPTY_CELL

    def laptime_cell(self, veh, ctx: Context) -> Cell:
        """Last lap time, or time in pit lane"""
        theme = self.theme
        if (self.wcfg.get("show_pitstop_duration_while_requested_pitstop", True) and ctx.player_pit_request) or veh.pitTimer.pitting:
            return Cell(TEXT, pit_time_text(veh.inPit, veh.pitTimer.elapsed), "dim", theme.accent)
        best = self.wcfg.get("show_highlighted_fastest_last_laptime", True) and veh.isClassFastestLastLap
        return Cell(TEXT, laptime_text(veh.lastLapTime, veh.isValidLap), "dim", theme.best if best else theme.text_dim)

    def paint_static(self, painter: QPainter):
        panel(painter, QRectF(self.rect()), self.theme, self.radius(0.5), self.depth_effects)

    def paint(self, painter: QPainter):
        self.draw_rows(painter, self.state)


def pit_time_text(in_pit: int, pit_time: float) -> str:
    """Time spent in pit lane"""
    if 0 < pit_time < MAX_SECONDS:
        return f"{'PIT' if in_pit else 'OUT'} {pit_time:.1f}"
    return TEXT_NOLAPTIME


def gap_text(gap: float | int, decimals: int) -> str:
    """Time gap, or laps if int"""
    if isinstance(gap, int):
        return f"{gap}L" if gap else DASH
    return f"{gap:.{decimals}f}"
