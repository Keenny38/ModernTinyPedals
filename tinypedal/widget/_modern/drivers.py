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

Columns are chosen by "column_*" options, in design order (COLUMNS of each widget), or in
"display_order_*" options order once user changed one. A widget adds its own columns (time
gap, interval...) by overriding extra_column & extra_cell.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ...const_common import MAX_SECONDS, TEXT_NOLAPTIME
from ...i18n import tr_overlay as tr
from ...template.widget.drivers_ui import DISPLAY_ORDER_NAMES
from .base import ModernOverlay
from .draw import panel
from .rows import DASH, RowStyle, class_style, compound_cell, laptime_text, pit_cell
from .table import (
    BADGE,
    CENTER,
    CHANGE,
    CLASS,
    EMPTY_CELL,
    LOGO,
    RIGHT,
    TEXT,
    Cell,
    Column,
    Row,
    TableMixin,
    change_width,
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
    "column_brand_logo", "brand_logo_width", "column_average_laptime", "column_speed_trap",
    "column_lift_and_coast_time", "lift_and_coast_reset_threshold", "lift_and_coast_highlight_threshold",
    "show_compound_for_each_wheel", "show_class_style_for_position_in_class",
    "pit_status_text", "garage_status_text", "yellow_flag_status_text", "finish_status_text",
    "display_order_position", "display_order_class", "display_order_position_change", "display_order_driver",
    "display_order_vehicle", "display_order_brand_logo", "display_order_tyre_compound", "display_order_pit_status",
    "display_order_pitstop_count", "display_order_laptime", "display_order_best_laptime",
    "display_order_average_laptime", "display_order_energy_remaining", "display_order_vehicle_integrity",
    "display_order_incidents", "display_order_stint_laps", "display_order_speed_trap",
    "display_order_lift_and_coast_time",
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
        self.add_font("tiny", 0.5, "bold", caps=True)  # per wheel compound letters
        columns = []
        for key in self.COLUMNS:
            if self.wcfg.get(f"column_{key}", False):
                column = self.column_of(key)
                if column is not None:
                    columns.append(column)
        columns = self.display_ordered(columns, names=DISPLAY_ORDER_NAMES)
        self.table = self.build_table(columns, ROW_SCALE)

    def column_of(self, key: str) -> Column | None:
        """Column geometry"""
        unit = self.unit
        if key == "position":
            return Column(key, self.digit_width("strong") * 2 + unit * 0.7)
        if key == "class":
            return Column(key, self.row_style.class_width())
        if key == "position_change":
            return Column(key, change_width(unit, ROW_SCALE, self.digit_width("value")))
        if key == "driver_name":
            return Column(key, self.row_style.name_width(self.wcfg.get("driver_name_width", 10)))
        if key == "vehicle_name":
            return Column(key, self.row_style.name_width(self.wcfg.get("vehicle_name_width", 10), "dim"))
        if key == "brand_logo":  # 2.35 units at classic default (20): wordmark logos (AMG, McLaren) readable
            return Column(key, max(unit * float(self.wcfg.get("brand_logo_width", 20)) / 8.5, unit * 0.5), CENTER)
        if key == "tyre_compound":
            return Column(key, compounds_width(unit, ROW_SCALE, 2))
        if key == "pit_status":
            return Column(key, max(self.text_width("label", text) for text in self.row_style.pit_texts) + unit * 0.8)
        if key == "pitstop_count":
            return Column(key, self.text_width("label", tr("PEN")) + unit * 0.8)
        if key in ("laptime", "best_laptime", "average_laptime"):  # last lap column also shows time in pit lane
            pit_time = max(self.text_width("dim", pit_time_text(in_pit, 888.8)) for in_pit in (0, 1))
            return Column(key, max(self.text_width("dim", "*8:88.888"), pit_time), RIGHT)
        if key in ("energy_remaining", "vehicle_integrity"):
            return Column(key, self.text_width("dim", "100%"), RIGHT)
        if key == "incidents":
            return Column(key, self.text_width("dim", "x88"), RIGHT)
        if key == "stint_laps":
            return Column(key, self.text_width("dim", "88/88"), RIGHT)
        if key == "speed_trap":
            return Column(key, self.text_width("dim", "888.8"), RIGHT)
        if key == "lift_and_coast_time":
            return Column(key, self.text_width("dim", "8.8s"), RIGHT)
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

    def show_sample(self):
        """Rows of a sample race, without session (Overlay Options live preview)"""
        from .sample_field import sample_field

        field = sample_field()
        self.show_field(field, Context(in_race=True, player=field.vehicles[field.player_index],
                                       player_pit_request=False))

    def show_field(self, field, ctx: Context):
        """Rows of sample field (override)"""

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
                pos_fill = class_color.darker(150) if wcfg.get("show_class_style_for_position_in_class", False) else None
                cells.append(Cell(CLASS, alias, color=pos_fill, fill=class_color, extra=f"{veh.positionInClass}"))
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
            elif key == "brand_logo":
                cells.append(Cell(LOGO, veh.vehicleBrand, extra=veh.vehicleName))
            elif key == "tyre_compound":
                cells.append(compound_cell(veh.tireCompoundName, wcfg.get("show_compound_for_each_wheel", True)))
            elif key == "pit_status":
                cells.append(pit_cell(theme, veh.inPit, veh.isYellow, veh.isFinished, style.pit_texts))
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
            elif key == "average_laptime":
                cells.append(Cell(TEXT, laptime_text(veh.lapTimeHistory.average), "dim", theme.text_dim))
            elif key == "energy_remaining":
                cells.append(style.energy_cell(veh.energyRemaining))
            elif key == "vehicle_integrity":
                cells.append(style.integrity_cell(veh.vehicleIntegrity))
            elif key == "incidents":
                cells.append(style.incidents_cell(veh.incidents))
            elif key == "stint_laps":
                cells.append(style.stint_cell(veh.currentStintLaps, veh.estimatedStintLaps))
            elif key == "speed_trap":
                cells.append(style.speed_trap_cell(veh.speedTrap.speed))
            elif key == "lift_and_coast_time":
                cells.append(style.lift_and_coast_cell(veh.licoTimer.elapsed, veh.licoTimer.idling))
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
        return f"{tr('PIT') if in_pit else tr('OUT')} {pit_time:.1f}"
    return TEXT_NOLAPTIME


def gap_text(gap: float | int, decimals: int) -> str:
    """Time gap, or laps if int"""
    if isinstance(gap, int):
        return f"{gap}L" if gap else DASH
    return f"{gap:.{decimals}f}"
