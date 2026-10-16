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
Modern overlay design: driver list widgets base (relative, standings)

Columns are chosen by "column_*" options, in design order (COLUMNS of each widget), or in
"display_order_*" options order once user changed one. A widget adds its own columns (time
gap, interval...) by overriding extra_column & extra_cell. With "show_column_headers", a row of
short column labels is drawn above the cars.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, NamedTuple

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter

from ...api_control import api
from ...const_common import MAX_SECONDS, TEXT_NOLAPTIME
from ...i18n import tr_overlay as tr
from ...module_info import minfo, sector_color
from ...template.setting_status_colors import SAME_TIME
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
    LAPTIME,
    LOGO,
    PAIR,
    RIGHT,
    TEXT,
    Cell,
    Column,
    LapTimeExtra,
    Row,
    TableMixin,
    change_width,
    compounds_width,
)

if TYPE_CHECKING:
    from ...template.widget_config_types import RelativeConfig, RivalsConfig, StandingsConfig

ROW_SCALE = 1.62
# Column labels of header row (English, translated when drawn): short, as a column is made as wide as its label
HEADER_LABELS = {
    "position": "Pos", "class": "Class", "position_change": "+/-", "driver_name": "Driver",
    "vehicle_name": "Car", "tyre_compound": "Tyres", "pit_status": "Pit", 
    "laptime": "Time", "best_laptime": "Best", "average_laptime": "Avg", "delta_laptime": "Delta",
    "energy_remaining": "Energy", "energy_per_lap": "E/Lap", "vehicle_integrity": "Health", "incidents": "Inc", "track_limits": "TL",
    "stint_laps": "Stint", "speed_trap": "Speed", "lift_and_coast_time": "L&C", "time_interval": "Int",
    "time_gap": "Gap", "gap_trend": "Trend",
}

# Options read by every driver list widget
DRIVER_OPTIONS = (
    "font_size", "show_player_highlighted", "show_lap_difference",
    "column_position", "column_class", "column_position_change", "show_position_change_in_class",
    "column_driver_name", "driver_name_shorten", "driver_name_uppercase", "driver_name_width",
    "column_vehicle_name", "show_vehicle_brand_as_name", "vehicle_name_width",
    "column_tyre_compound", "column_pit_status", "show_pit_request",  # pit status column shows pit stops too
    "column_laptime", "show_highlighted_fastest_last_laptime", "show_pitstop_duration_while_requested_pitstop",
    "show_lap_sectors", "show_lap_delta", "show_out_and_in_laps", "show_invalid_lap_in_red", "show_lap_trend",
    "show_running_lap_time",
    "column_best_laptime", "show_best_laptime_from_recent_laps_in_race",
    "column_energy_remaining", "decimal_places_energy_remaining", "column_vehicle_integrity",
    "column_incidents", "incidents_high_threshold", "incidents_extreme_threshold",
    "column_stint_laps",
    "column_brand_logo", "brand_logo_width", "column_average_laptime", "column_speed_trap",
    "column_lift_and_coast_time", "lift_and_coast_reset_threshold", "lift_and_coast_highlight_threshold",
    "show_compound_for_each_wheel", "show_class_style_for_position_in_class",
    "pit_status_text", "garage_status_text", "yellow_flag_status_text", "finish_status_text",
    "display_order_position", "display_order_class", "display_order_position_change", "display_order_driver",
    "display_order_vehicle", "display_order_brand_logo", "display_order_tyre_compound", "display_order_pit_status",
    "display_order_laptime", "display_order_best_laptime",
    "display_order_average_laptime", "display_order_energy_remaining", "display_order_vehicle_integrity",
    "display_order_incidents", "display_order_stint_laps", "display_order_speed_trap",
    "display_order_lift_and_coast_time",
)


class Context(NamedTuple):
    """Data shared by all rows of one update"""

    in_race: bool
    player: Any  # player vehicle data
    player_pit_request: bool
    now: float = 0.0  # session time of scoring (running lap times), 0 if unknown


CellBuilder = Callable[..., Cell]  # (car, context, player highlighted, class alias, class color, extra) -> cell


class DriverTable(TableMixin, ModernOverlay):
    """Driver list widget base"""

    wcfg: RelativeConfig | StandingsConfig | RivalsConfig
    # Column keys in display order (widget defines)
    COLUMNS: tuple[str, ...] = ()
    # Class shown by a header above each class group (widget sets): no class column, position in class
    class_headers = False
    class_column_hidden = False  # class column left out (class name in class headers)

    def setup_table(self):
        """Columns from options"""
        self.row_style = RowStyle(self, self.wcfg)
        self.add_font("tiny", 0.5, "bold", caps=True)  # per wheel compound letters
        columns = []
        # Every column ordered (shown or not), as the column list of Overlay Options: design order while no
        # display order of any column was changed, same order there & here
        for key in self.display_ordered(list(self.COLUMNS), key=str, names=DISPLAY_ORDER_NAMES):
            if key == "class" and self.class_column_hidden:
                continue
            if self.wcfg.get(f"column_{key}", False):
                column = self.column_of(key)
                if column is not None:
                    columns.append(column)
        header = bool(self.wcfg.get("show_column_headers", False))
        if header:
            columns = [column._replace(label=HEADER_LABELS.get(column.key, "")) for column in columns]
        self.table = self.build_table(columns, ROW_SCALE, header=header)
        # Cell builders of columns (options read once), kept colors & cells: same objects compare fast
        self.highlight_player = self.wcfg.get("show_player_highlighted", True)
        self.class_stripe = bool(self.wcfg["column_class"])
        self.class_shades: dict[int, QColor] = {}
        self.compound_cells: dict[tuple, Cell] = {}
        self.driver_names: dict[str, str] = {}
        self.builders = tuple(self.builder_of(column.key) for column in self.table.columns)

    def builder_of(self, key: str) -> CellBuilder:
        """Cell builder of column: (car, context, player highlighted, class alias, class color, extra) -> cell"""
        wcfg = self.wcfg
        theme = self.theme
        style = self.row_style
        if key == "position":
            in_class = self.class_headers
            on_accent = style.on_accent

            def position(veh, ctx, player, alias, class_color, extra):
                text = f"{veh.positionInClass if in_class else veh.positionOverall}"
                if player:
                    return Cell(BADGE, text, "strong", on_accent, theme.accent)
                return Cell(BADGE, text, "strong", theme.text, theme.surface_raised)
            return position
        if key == "class":
            shaded = wcfg.get("show_class_style_for_position_in_class", False)
            shade = self.class_shade

            def class_cell(veh, ctx, player, alias, class_color, extra):
                return Cell(CLASS, alias, color=shade(class_color) if shaded else None, fill=class_color,
                            extra=f"{veh.positionInClass}")
            return class_cell
        if key == "position_change":
            change_in_class = wcfg.get("show_position_change_in_class", True)

            def position_change(veh, ctx, player, alias, class_color, extra):
                if change_in_class:
                    return Cell(CHANGE, extra=veh.qualifyInClass - veh.positionInClass)
                return Cell(CHANGE, extra=veh.qualifyOverall - veh.positionOverall)
            return position_change
        if key == "driver_name":
            lap_color = style.lap_color
            name_of = self.driver_name

            def driver_name(veh, ctx, player, alias, class_color, extra):
                return Cell(TEXT, name_of(veh.driverName), "strong" if player else "value",
                            lap_color(veh.isLapped, player))
            return driver_name
        if key == "vehicle_name":
            brand = wcfg.get("show_vehicle_brand_as_name", True)
            return lambda veh, *_: Cell(TEXT, veh.vehicleBrand if brand else veh.vehicleName, "dim", theme.text_dim)
        if key == "brand_logo":
            return lambda veh, *_: Cell(LOGO, veh.vehicleBrand, extra=veh.vehicleName)
        if key == "tyre_compound":
            per_wheel = wcfg.get("show_compound_for_each_wheel", True)
            cells = self.compound_cells

            def tyre_compound(veh, ctx, player, alias, class_color, extra):
                names = veh.tireCompoundName
                cell = cells.get(names)
                if cell is None:
                    if len(cells) >= 256:
                        cells.clear()
                    cell = cells[names] = compound_cell(names, per_wheel)
                return cell
            return tyre_compound
        if key == "pit_status":  # pit lane, garage, slow, finished; then pit stops or penalty
            pit_texts = style.pit_texts
            pitstop_cell = style.pitstop_cell
            pit_width = self.pit_part_width

            def pit_and_stops(veh, ctx, player, alias, class_color, extra):
                return Cell(PAIR, extra=(pit_cell(theme, veh.inPit, veh.isYellow, veh.isFinished, pit_texts),
                                         pitstop_cell(veh.numPitStops, veh.pitRequested, veh.penalty), pit_width))
            return pit_and_stops
        if key == "laptime":
            laptime_cell = self.laptime_cell
            return lambda veh, ctx, *_: laptime_cell(veh, ctx)
        if key == "best_laptime":
            recent = wcfg.get("show_best_laptime_from_recent_laps_in_race", False)

            def best_laptime(veh, ctx, player, alias, class_color, extra):
                laptime = veh.lapTimeHistory.best if recent and ctx.in_race else veh.bestLapTime
                return Cell(TEXT, laptime_text(laptime), "dim", theme.text_dim)
            return best_laptime
        if key == "average_laptime":
            return lambda veh, *_: Cell(TEXT, laptime_text(veh.lapTimeHistory.average), "dim", theme.text_dim)
        if key == "energy_remaining":
            energy_cell = style.energy_cell
            return lambda veh, *_: energy_cell(veh.energyRemaining)
        if key == "vehicle_integrity":
            integrity_cell = style.integrity_cell
            return lambda veh, *_: integrity_cell(veh.vehicleIntegrity)
        if key == "incidents":
            incidents_cell = style.incidents_cell
            return lambda veh, *_: incidents_cell(veh.incidents)
        if key == "stint_laps":
            stint_cell = style.stint_cell
            return lambda veh, *_: stint_cell(veh.currentStintLaps, veh.estimatedStintLaps)
        if key == "speed_trap":
            speed_trap_cell = style.speed_trap_cell
            return lambda veh, *_: speed_trap_cell(veh.speedTrap.speed)
        if key == "lift_and_coast_time":
            lift_and_coast_cell = style.lift_and_coast_cell
            return lambda veh, *_: lift_and_coast_cell(veh.licoTimer.elapsed, veh.licoTimer.idling)
        extra_cell = self.extra_cell
        return lambda veh, ctx, player, alias, class_color, extra: extra_cell(key, veh, ctx, extra)

    def class_shade(self, color: QColor) -> QColor:
        """Darker class color (position in class part of class pill), one color object per class color"""
        rgba = color.rgba()
        shade = self.class_shades.get(rgba)
        if shade is None:
            shade = self.class_shades[rgba] = color.darker(150)
        return shade

    def driver_name(self, name: str) -> str:
        """Driver name as shown (shortened, upper case by options), made once per name"""
        shown = self.driver_names.get(name)
        if shown is None:
            if len(self.driver_names) >= 512:
                self.driver_names.clear()
            shown = self.driver_names[name] = self.row_style.driver_name(name)
        return shown

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
        if key == "pit_status":  # pit status pill, then pit stops or penalty (SG100, DT x2, +35s, DQ)
            self.pit_part_width = max(self.text_width("label", text) for text in self.row_style.pit_texts) + unit * 0.8
            stops = max(self.text_width("label", text) for text in (tr("PEN"), "SG100", "+100s")) + unit * 0.8
            return Column(key, self.pit_part_width + unit * 0.3 + stops)
        if key in ("laptime", "best_laptime", "average_laptime"):  # last lap column also shows time in pit lane
            pit_time = max(self.text_width("dim", pit_time_text(in_pit, 888.8)) for in_pit in (0, 1))
            if key != "laptime":
                return Column(key, max(self.text_width("dim", "*8:88.888"), pit_time), RIGHT)
            wcfg = self.wcfg
            # One time slot: lap time, delta & running time shown one after another (invalid lap in red: no "*")
            sample = "8:88.888" if wcfg.get("show_invalid_lap_in_red", True) else "*8:88.888"
            self.bars_width = self.text_width("dim", "8:88.888")
            width = self.time_width = max(self.text_width("dim", sample), pit_time, self.text_width("dim", "+8.888"))
            self.side_width = (ROW_SCALE * unit * 0.42 * 0.8 + unit * ARROW_GAP
                               if wcfg.get("show_lap_trend", True) else 0.0)  # trend arrow
            return Column(key, width + self.side_width, RIGHT)
        if key == "energy_remaining":  # decimals as set (decimal_places_energy_remaining)
            return Column(key, self.text_width("dim", self.row_style.energy_text(1.0)), RIGHT)
        if key == "vehicle_integrity":
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
        data_set = minfo.vehicles.dataSet
        index = minfo.vehicles.playerIndex
        player = data_set[index] if 0 <= index < len(data_set) else None
        return Context(
            in_race=api.read.session.in_race(),
            player=player,
            player_pit_request=bool(player is not None and player.pitRequested),
            now=api.read.timing.elapsed(),  # player telemetry time: running lap times move smoothly
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
        player = veh.isPlayer and self.highlight_player
        alias, class_color = class_style(self.cfg, veh.vehicleClass, self.theme)
        cells = tuple([build(veh, ctx, player, alias, class_color, extra) for build in self.builders])
        faded = veh.inPit == 2 or veh.isFinished
        return Row(cells, player, class_color if self.class_stripe else None, faded)

    def extra_cell(self, key: str, veh, ctx: Context, extra: dict) -> Cell:
        """Widget own column cell (override)"""
        return EMPTY_CELL

    def laptime_cell(self, veh, ctx: Context) -> Cell:
        """Running time of lap being driven (if set), completed lap for RESULT_SECONDS after the line; sector bars
        as game live timing; time in pit lane while pitting"""
        theme = self.theme
        wcfg = self.wcfg
        if (wcfg.get("show_pitstop_duration_while_requested_pitstop", True) and ctx.player_pit_request) or veh.pitTimer.pitting:
            return Cell(TEXT, pit_time_text(veh.inPit, veh.pitTimer.elapsed), "dim", theme.accent)
        running = self.running_time(veh, ctx)
        sectors = self.sector_parts(veh, ctx, running) if wcfg.get("show_lap_sectors", True) else ()
        if wcfg.get("show_running_lap_time", True) and 0 <= running < MAX_SECONDS and not veh.isFinished:
            if running >= RESULT_SECONDS:  # lap being driven
                return Cell(LAPTIME, running_text(running), "dim", theme.text, extra=self.laptime_extra(sectors))
            show_delta = running >= LAP_SECONDS  # after the line: lap time, then delta
        else:  # lap time & delta in turn
            show_delta = ctx.now > 0 and int(ctx.now / LAP_SECONDS) % 2 == 1
        return self.lap_result_cell(veh, sectors, show_delta)

    def laptime_extra(self, sectors: tuple, trend: int = 0) -> LapTimeExtra:
        return LapTimeExtra(sectors, trend, self.time_width, self.side_width, self.bars_width)

    def lap_result_cell(self, veh, sectors: tuple, show_delta: bool = False) -> Cell:
        """Completed lap: purple fastest last lap of class, green personal best, red invalid; OUT / IN for out & in
        laps; delta to personal best in place of time if show_delta (& any); trend against lap before"""
        theme = self.theme
        wcfg = self.wcfg
        kind = veh.sectors.last_kind if wcfg.get("show_out_and_in_laps", True) else ""
        trend = 0
        if kind:
            text, role, color = tr(kind), "label", theme.text_faint
        else:
            last, best = veh.lastLapTime, veh.bestLapTime
            if wcfg.get("show_lap_trend", True) and not veh.sectors.previous_kind:
                trend = lap_trend(veh.lapTimeHistory[3], veh.lapTimeHistory[4])
            if (show_delta and wcfg.get("show_lap_delta", True) and veh.isValidLap
                    and 0 < best < last - SAME_TIME and last < MAX_SECONDS):
                return Cell(LAPTIME, delta_text(last - best), "dim", theme.warning,
                            extra=self.laptime_extra(sectors, trend))
            text, role, color = laptime_text(last, veh.isValidLap), "dim", theme.text_dim
            if not veh.isValidLap and wcfg.get("show_invalid_lap_in_red", True):
                text, color = laptime_text(last), theme.negative
            elif wcfg.get("show_highlighted_fastest_last_laptime", True) and veh.isValidLap and 0 < last < MAX_SECONDS:
                if veh.classBestLap and abs(last - veh.classBestLap) < SAME_TIME:
                    color = theme.best  # best lap of class in session
                elif 0 < best < MAX_SECONDS and abs(last - best) < SAME_TIME:
                    color = theme.positive  # personal best
        return Cell(LAPTIME, text, role, color, extra=self.laptime_extra(sectors, trend))

    @staticmethod
    def running_time(veh, ctx: Context) -> float:
        """Time into lap being driven (seconds), -1 if unknown"""
        if ctx.now > 0 and veh.lapStartTime > 0:
            return ctx.now - veh.lapStartTime
        return -1.0

    def sector_parts(self, veh, ctx: Context, running: float = -1.0) -> tuple:
        """(color, fill) of S1, S2, S3 bars as game live timing: sectors of lap being driven (last lap while S1 is
        driven), purple if best of class in session, green if personal best of completed laps, orange if slower;
        sector being driven filled as driven (time into it against personal best of sector); (None, 0) if not
        driven yet"""
        theme = self.theme
        sectors = veh.sectors
        values, driving = sectors.shown(ctx.in_race, veh.pitTimer.pitting)
        parts: list[tuple[QColor | None, float]] = []
        for number, value in enumerate(values):
            if number == driving:
                parts.append((theme.text_dim, self.sector_fill(sectors, number, running)))
                continue
            color = sector_color(value, number, sectors, veh.classBestSectors)
            parts.append((getattr(theme, color), 1.0) if color else (None, 0.0))
        return tuple(parts)

    @staticmethod
    def sector_fill(sectors, number: int, running: float) -> float:
        """Share of sector being driven already driven: time into sector against personal best of sector (else
        last lap's), 0 if unknown; in FILL_STEPS steps (bar a few dozen pixels wide): row unchanged between steps,
        lap time cell not repainted every update"""
        expected = sectors.best[number] or sectors.last[number] or sectors.best_lap[number]
        if running < 0 or not expected:
            return 0.0
        into = running - sum(sectors.current[:number])
        return min(round(min(max(into / expected, 0.0), 0.97) * FILL_STEPS) / FILL_STEPS, 0.97)

    def refresh(self, state: Any) -> bool:
        """Repaint rows that changed, True if anything repainted"""
        return self.refresh_rows(state)

    def paint_static(self, painter: QPainter):
        panel(painter, QRectF(self.rect()), self.theme, self.radius(0.5), self.depth_effects)
        self.draw_header(painter)

    def paint(self, painter: QPainter):
        self.draw_rows(painter, self.state)


FILL_STEPS = 64  # drawn steps of sector bar being driven (see sector_fill)
RESULT_SECONDS = 8.0  # seconds after the line the completed lap is shown (lap time, then delta), then running time
LAP_SECONDS = 4.0  # seconds lap time is shown before delta (in turn without running time)
ARROW_GAP = 0.15  # space between time slot & trend arrow (font size units, see table.draw_laptime)


def running_text(seconds: float) -> str:
    """Running lap time, tenths: 1:23.4"""
    minutes, rest = divmod(round(max(seconds, 0.0), 1), 60)  # rounded first: 59.96 is 1:00.0, never 0:60.0
    return f"{int(minutes)}:{rest:04.1f}"


def delta_text(seconds: float) -> str:
    """Time behind reference, as wide as +8.888: +0.345, +12.3"""
    return f"+{seconds:.3f}" if seconds < 9.9995 else f"+{min(seconds, 99.9):.1f}"


def lap_trend(previous: float, last: float) -> int:
    """1 if last lap faster than lap before, -1 if slower, 0 if same or unknown"""
    if not (0 < previous < MAX_SECONDS and 0 < last < MAX_SECONDS) or abs(last - previous) < SAME_TIME:
        return 0
    return 1 if last < previous else -1


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
