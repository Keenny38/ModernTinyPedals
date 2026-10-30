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
Driver table columns shared by classic Relative, Standings & Rivals widgets

Column table (options, width & colors of each column), layout builder and cell update methods.
Widget differences are parameters: player styles, lap difference colors, rows hidden (Standings,
Rivals) or blanked (Relative), and widget own columns (time gap, interval, delta laptime).
"""

from typing import Any, NamedTuple

from .. import calculation as calc
from .. import units
from ..const_common import MAX_SECONDS, TEXT_NOLAPTIME, TEXT_PLACEHOLDER
from ..formatter import random_color_class, shorten_driver_name
from ..penalty_info import count_text
from ..userfile.custom_image import BrandLogos
from ..userfile.heatmap import select_compound_color, select_compound_symbol
from ._base import Overlay
from ._painter import MultiCompounds, RawImage, RawText


class Column(NamedTuple):
    """Text column: bars_<name>, bar_style_<name>, update_<name>"""

    show: str  # show option
    order: str  # display order option
    width: int | str  # characters, or widget attribute of characters
    styles: tuple[tuple[str, str], ...]  # font & background color options of each style index


def styles(*names: str | tuple[str, str]) -> tuple[tuple[str, str], ...]:
    """Color options of style names: font_color_<name> & background_color_<name>,
    or (font name, background name)"""
    return tuple(
        (f"font_color_{name}", f"background_color_{name}") if isinstance(name, str)
        else (f"font_color_{name[0]}", f"background_color_{name[1]}")
        for name in names
    )


# Text columns, by name; player styles have "player" in names
COLUMNS = {
    "pos": Column("show_position", "display_order_position", 2, styles("position", "player_position")),
    "pgl": Column("show_position_change", "display_order_position_change", 3, styles(
        "position_same", "position_gain", "position_loss", "player_position_change")),
    "drv": Column("show_driver_name", "display_order_driver", "drv_width", styles(
        "driver_name", "player_driver_name")),
    "veh": Column("show_vehicle_name", "display_order_vehicle", "veh_width", styles(
        "vehicle_name", "player_vehicle_name")),
    "gap": Column("show_time_gap", "display_order_time_gap", "gap_width", styles("time_gap", "player_time_gap")),
    "int": Column("show_time_interval", "display_order_time_interval", "int_width", styles(
        "time_interval", "player_time_interval")),
    "lpt": Column("show_laptime", "display_order_laptime", 8, styles(
        "laptime", "player_laptime", "fastest_last_laptime", "player_fastest_last_laptime")),
    "blp": Column("show_best_laptime", "display_order_best_laptime", 8, styles(
        "best_laptime", "player_best_laptime")),
    "alp": Column("show_average_laptime", "display_order_average_laptime", 8, styles(
        "average_laptime", "player_average_laptime")),
    "pic": Column("show_position_in_class", "display_order_position_in_class", 2, styles(
        "position_in_class", "player_position_in_class")),
    "cls": Column("show_class", "display_order_class", "cls_width", styles("class")),
    "psc": Column("show_pitstop_count", "display_order_pitstop_count", 2, styles(
        "pitstop_count", "player_pitstop_count", "pit_request", "penalty_count")),
    "nrg": Column("show_energy_remaining", "display_order_energy_remaining", "nrg_width", styles(
        ("energy_remaining_unavailable", "energy_remaining"), ("energy_remaining_high", "energy_remaining"),
        ("energy_remaining_low", "energy_remaining"), ("energy_remaining_critical", "energy_remaining"),
        "player_energy_remaining")),
    "dmg": Column("show_vehicle_integrity", "display_order_vehicle_integrity", 1, styles(
        ("vehicle_integrity_full", "vehicle_integrity"), ("vehicle_integrity_high", "vehicle_integrity"),
        ("vehicle_integrity_low", "vehicle_integrity"), "player_vehicle_integrity")),
    "icd": Column("show_incidents", "display_order_incidents", 3, styles(
        "incidents_low", "incidents_high", "incidents_extreme", "player_incidents")),
    "stl": Column("show_stint_laps", "display_order_stint_laps", 5, styles("stint_laps", "player_stint_laps")),
    "spd": Column("show_speed_trap", "display_order_speed_trap", 5, styles("speed_trap", "player_speed_trap")),
    "lic": Column("show_lift_and_coast_time", "display_order_lift_and_coast_time", 4, styles(
        "lift_and_coast_time", "lift_and_coast_highlight", "player_lift_and_coast_time")),
}
LAP_DIFFERENCE_COLUMNS = ("pos", "drv", "veh")  # colored by lap difference (Relative)


class DriverTable(Overlay):
    """Driver table widget: columns of driver rows

    Row state (last value of cell data) is widget own: Standings 0 shown, 1 class gap, 2 hidden;
    Rivals 1 shown, 0 hidden; Relative 1 shown, 0 blank (cells kept, text cleared: blank_state).
    """

    wcfg: Any  # Relative, Standings or Rivals options
    blank_state: int | None = None  # row state of blank cells (text cleared), None if rows hidden instead
    shown_state: int = 1  # row state of a row showing a car (Standings: 0)
    veh_range: int
    count_tcp: int
    drv_width: int
    veh_width: int
    brd_width: int
    brd_height: int
    cls_width: int
    nrg_width: int
    nrg_decimals: int
    unit_speed: Any
    pit_status_text: tuple[str, ...]
    # Cells (bars_<name>) & colors (bar_style_<name>) of enabled columns
    bars_pos: tuple[RawText, ...]
    bars_pgl: tuple[RawText, ...]
    bars_drv: tuple[RawText, ...]
    bars_veh: tuple[RawText, ...]
    bars_brd: tuple[RawImage, ...]
    bars_gap: tuple[RawText, ...]
    bars_int: tuple[RawText, ...]
    bars_lpt: tuple[RawText, ...]
    bars_blp: tuple[RawText, ...]
    bars_alp: tuple[RawText, ...]
    bars_pic: tuple[RawText, ...]
    bars_cls: tuple[RawText, ...]
    bars_pit: tuple[RawText, ...]
    bars_tcp: tuple[MultiCompounds, ...]
    bars_psc: tuple[RawText, ...]
    bars_nrg: tuple[RawText, ...]
    bars_dmg: tuple[RawText, ...]
    bars_icd: tuple[RawText, ...]
    bars_stl: tuple[RawText, ...]
    bars_spd: tuple[RawText, ...]
    bars_lic: tuple[RawText, ...]
    bar_style_pos: tuple[tuple[str, str], ...]
    bar_style_pgl: tuple[tuple[str, str], ...]
    bar_style_drv: tuple[tuple[str, str], ...]
    bar_style_veh: tuple[tuple[str, str], ...]
    bar_style_brd: tuple[str, str]
    bar_style_gap: tuple[tuple[str, str], ...]
    bar_style_int: tuple[tuple[str, str], ...]
    bar_style_lpt: tuple[tuple[str, str], ...]
    bar_style_blp: tuple[tuple[str, str], ...]
    bar_style_alp: tuple[tuple[str, str], ...]
    bar_style_pic: tuple[tuple[str, str], ...]
    bar_style_pit: tuple[tuple[str, str], ...]
    bar_style_tcp: tuple[tuple[str, str], ...]
    bar_style_psc: tuple[tuple[str, str], ...]
    bar_style_nrg: tuple[tuple[str, str], ...]
    bar_style_dmg: tuple[tuple[str, str], ...]
    bar_style_icd: tuple[tuple[str, str], ...]
    bar_style_stl: tuple[tuple[str, str], ...]
    bar_style_spd: tuple[tuple[str, str], ...]
    bar_style_lic: tuple[tuple[str, str], ...]

    def set_driver_columns(
        self,
        layout,
        font_m,
        bar_padx: int,
        names: tuple[str, ...],
        hide_start: int = 99999,
        player_styles: bool = True,
        lap_difference: bool = False,
        own_styles: dict[str, tuple[tuple[str, str], ...]] | None = None,
        own_columns: dict[str, Any] | None = None,
    ):
        """Set enabled columns of names, in names order

        Args:
            layout: grid layout of table.
            font_m: font metrics.
            bar_padx: horizontal padding of cells.
            names: column names.
            hide_start: rows hidden from start (from this row).
            player_styles: widget has player colors (else player style is default style).
            lap_difference: name columns have lap difference colors.
            own_styles: column styles of widget (instead of COLUMNS styles).
            own_columns: column builders of widget, called with (layout, font_m, bar_padx) if enabled.
        """
        wcfg = self.wcfg
        own_styles = own_styles or {}
        own_columns = own_columns or {}
        self.brand_logos = BrandLogos(self, self.cfg.path.brand_logo, self.brd_width, self.brd_height,
                                      self.brand_logo_arrived)
        for name in names:
            if name in own_columns:
                own_columns[name](layout, font_m, bar_padx)
                continue
            if name == "brd":
                if wcfg["show_brand_logo"]:
                    self.set_brand_column(layout, font_m, hide_start, player_styles)
                continue
            if name == "pit":
                if wcfg["show_pit_status"]:
                    self.set_pit_column(layout, font_m, bar_padx, hide_start)
                continue
            if name == "tcp":
                if wcfg["show_tyre_compound"]:
                    self.set_compound_column(layout, font_m, bar_padx, hide_start, player_styles)
                continue
            column = COLUMNS[name]
            if not wcfg[column.show]:
                continue
            pairs = own_styles.get(name, column.styles)
            bar_style = tuple(
                (wcfg[pairs[0][0]], wcfg[pairs[0][1]]) if not player_styles and "player" in font
                else (wcfg[font], wcfg[bg])
                for font, bg in pairs
            )
            if lap_difference and name in LAP_DIFFERENCE_COLUMNS:
                bg_color = bar_style[0][1]
                bar_style += (
                    (wcfg["font_color_same_lap"], bg_color),
                    (wcfg["font_color_laps_behind"], bg_color),
                    (wcfg["font_color_laps_ahead"], bg_color),
                )
            if name == "spd":
                self.unit_speed = units.set_unit_speed(self.cfg.units["speed_unit"])
            chars = column.width if isinstance(column.width, int) else getattr(self, column.width)
            setattr(self, f"bar_style_{name}", bar_style)
            bars = self.set_rawtext(
                width=chars * font_m.width + bar_padx,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=bar_style[0][0],
                bg_color=bar_style[0][1],
                count=self.veh_range,
            )
            setattr(self, f"bars_{name}", bars)
            self.set_grid_layout_table_column(
                layout=layout,
                targets=bars,
                column=wcfg[column.order],
                hide_start=hide_start,
            )

    def set_brand_column(self, layout, font_m, hide_start: int, player_styles: bool):
        """Brand logo column"""
        background = self.wcfg["background_color_brand_logo"]
        self.bar_style_brd = (
            background,
            self.wcfg["background_color_player_brand_logo"] if player_styles else background,
        )
        self.bars_brd = self.set_rawimage(
            width=self.brd_width,
            fixed_height=font_m.height,
            bg_color=self.bar_style_brd[0],
            count=self.veh_range,
        )
        self.set_grid_layout_table_column(
            layout=layout,
            targets=self.bars_brd,
            column=self.wcfg["display_order_brand_logo"],
            hide_start=hide_start,
        )

    def set_pit_column(self, layout, font_m, bar_padx: int, hide_start: int):
        """Pit status column"""
        wcfg = self.wcfg
        self.pit_status_text = (
            "",
            wcfg["pit_status_text"],
            wcfg["garage_status_text"],
            wcfg["yellow_flag_status_text"],
            wcfg["finish_status_text"],
        )
        self.bar_style_pit = (
            ("#00000000", "#00000000"),
            (wcfg["font_color_pit"], wcfg["background_color_pit"]),
            (wcfg["font_color_garage"], wcfg["background_color_garage"]),
            (wcfg["font_color_yellow_flag"], wcfg["background_color_yellow_flag"]),
            (wcfg["font_color_finish"], wcfg["background_color_finish"]),
        )
        self.bars_pit = self.set_rawtext(
            width=max(map(len, self.pit_status_text)) * font_m.width + bar_padx,
            fixed_height=font_m.height,
            offset_y=font_m.voffset,
            fg_color=self.bar_style_pit[0][0],
            bg_color=self.bar_style_pit[0][1],
            count=self.veh_range,
        )
        self.set_grid_layout_table_column(
            layout=layout,
            targets=self.bars_pit,
            column=wcfg["display_order_pit_status"],
            hide_start=hide_start,
        )

    def set_compound_column(self, layout, font_m, bar_padx: int, hide_start: int, player_styles: bool):
        """Tyre compound column"""
        wcfg = self.wcfg
        self.count_tcp = 4 if wcfg["show_compound_for_each_wheel"] else 1
        default = (wcfg["font_color_tyre_compound"], wcfg["background_color_tyre_compound"])
        self.bar_style_tcp = (
            default,
            (wcfg["font_color_player_tyre_compound"], wcfg["background_color_player_tyre_compound"])
            if player_styles else default,
        )
        self.bars_tcp = tuple(
            MultiCompounds(
                parent=self,
                count=self.count_tcp,
                spacing=max(wcfg["tyre_compound_spacing"], 0),
                padding=bar_padx,
                width=font_m.width,
                height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=default[0],
                bg_color=default[1],
            )
            for _ in range(self.veh_range)
        )
        self.set_grid_layout_table_column(
            layout=layout,
            targets=self.bars_tcp,
            column=wcfg["display_order_tyre_compound"],
            hide_start=hide_start,
        )

    def update_columns(self, idx: int, veh_info, hi_player: bool, name_style: int, in_race: bool, state: int):
        """Update shared columns of row (time gap, interval, laptime & delta laptime: widget own)

        Args:
            idx: row index.
            veh_info: vehicle data of row.
            hi_player: highlighted player row.
            name_style: style index of position, driver & vehicle name.
            in_race: race session.
            state: row state.
        """
        wcfg = self.wcfg
        # Driver position
        if wcfg["show_position"]:
            self.update_pos(self.bars_pos[idx], veh_info.positionOverall, name_style, state)
        # Driver position change
        if wcfg["show_position_change"]:
            if wcfg["show_position_change_in_class"]:
                pos_diff = veh_info.qualifyInClass - veh_info.positionInClass
            else:
                pos_diff = veh_info.qualifyOverall - veh_info.positionOverall
            self.update_pgl(self.bars_pgl[idx], pos_diff, hi_player, state)
        # Driver name
        if wcfg["show_driver_name"]:
            self.update_drv(self.bars_drv[idx], veh_info.driverName, name_style, state)
        # Vehicle name
        if wcfg["show_vehicle_name"]:
            if wcfg["show_vehicle_brand_as_name"]:
                vehicle_name = veh_info.vehicleBrand
            else:
                vehicle_name = veh_info.vehicleName
            self.update_veh(self.bars_veh[idx], vehicle_name, name_style, state)
        # Brand logo
        if wcfg["show_brand_logo"]:
            self.update_brd(self.bars_brd[idx], veh_info.vehicleBrand, hi_player, state)
        # Vehicle best laptime
        if wcfg["show_best_laptime"]:
            if in_race and wcfg["show_best_laptime_from_recent_laps_in_race"]:
                laptime = veh_info.lapTimeHistory.best
            else:
                laptime = veh_info.bestLapTime
            self.update_blp(self.bars_blp[idx], laptime, hi_player, state)
        # Vehicle average laptime
        if wcfg["show_average_laptime"]:
            self.update_alp(self.bars_alp[idx], veh_info.lapTimeHistory.average, hi_player, state)
        # Position in class
        if wcfg["show_position_in_class"]:
            self.update_pic(self.bars_pic[idx], veh_info.positionInClass, veh_info.vehicleClass, hi_player, state)
        # Vehicle class
        if wcfg["show_class"]:
            self.update_cls(self.bars_cls[idx], veh_info.vehicleClass, state)
        # Vehicle in pit
        if wcfg["show_pit_status"]:
            self.update_pit(self.bars_pit[idx], veh_info.inPit, veh_info.isYellow, veh_info.isFinished, state)
        # Tyre compound
        if wcfg["show_tyre_compound"]:
            self.update_tcp(self.bars_tcp[idx], veh_info.tireCompoundName, hi_player, state)
        # Pitstop count
        if wcfg["show_pitstop_count"]:
            self.update_psc(self.bars_psc[idx], veh_info.numPitStops, veh_info.pitRequested, hi_player,
                            veh_info.penalty, state)
        # Remaining energy
        if wcfg["show_energy_remaining"]:
            self.update_nrg(self.bars_nrg[idx], veh_info.energyRemaining, hi_player, state)
        # Vehicle integrity
        if wcfg["show_vehicle_integrity"]:
            self.update_dmg(self.bars_dmg[idx], veh_info.vehicleIntegrity, hi_player, state)
        # Incidents
        if wcfg["show_incidents"]:
            self.update_icd(self.bars_icd[idx], veh_info.incidents, hi_player, state)
        # Stint laps
        if wcfg["show_stint_laps"]:
            self.update_stl(self.bars_stl[idx], veh_info.currentStintLaps, veh_info.estimatedStintLaps, hi_player,
                            state)
        # Speed trap
        if wcfg["show_speed_trap"]:
            self.update_spd(self.bars_spd[idx], veh_info.speedTrap.speed, hi_player, state)
        # Lift and coast time
        if wcfg["show_lift_and_coast_time"]:
            self.update_lic(self.bars_lic[idx], veh_info.licoTimer.elapsed, veh_info.licoTimer.idling, hi_player,
                            state)

    # GUI update methods: data (values..., style index or highlighted player, row state)
    def toggle_visibility(self, target, state):
        """Cell shown, hidden or drawn again by row state"""
        raise NotImplementedError

    def update_pos(self, target, *data):
        """Driver position"""
        if target.last != data:
            target.last = data
            target.text = "" if data[-1] == self.blank_state else f"{data[0]:02d}"
            target.fg, target.bg = self.bar_style_pos[data[1]]
            self.toggle_visibility(target, data[-1])

    def update_pgl(self, target, *data):
        """Driver position change (gain/loss)"""
        if target.last != data:
            target.last = data
            pos_diff = data[0]
            if pos_diff > 0:
                text = f"▲{pos_diff:>2}"
                color_index = 1
            elif pos_diff < 0:
                text = f"▼{-pos_diff:>2}"
                color_index = 2
            else:
                text = "- 0"
                color_index = 0
            if data[1]:
                color_index = 3
            if data[-1] == self.blank_state:
                text = ""
                color_index = 0
            target.text = text
            target.fg, target.bg = self.bar_style_pgl[color_index]
            self.toggle_visibility(target, data[-1])

    def update_drv(self, target, *data):
        """Driver name"""
        if target.last != data:
            target.last = data
            if data[-1] == self.blank_state:
                text = ""
            else:
                if self.wcfg["driver_name_shorten"]:
                    text = shorten_driver_name(data[0])
                else:
                    text = data[0]
                if self.wcfg["driver_name_uppercase"]:
                    text = text.upper()
                if self.wcfg["driver_name_align_center"]:
                    text = f"{text:.{self.drv_width}}"
                else:
                    text = f"{text:<{self.drv_width}.{self.drv_width}}"
            target.text = text
            target.fg, target.bg = self.bar_style_drv[data[1]]
            self.toggle_visibility(target, data[-1])

    def update_veh(self, target, *data):
        """Vehicle name"""
        if target.last != data:
            target.last = data
            if data[-1] == self.blank_state:
                text = ""
            else:
                text = data[0]
                if self.wcfg["vehicle_name_uppercase"]:
                    text = text.upper()
                if self.wcfg["vehicle_name_align_center"]:
                    text = f"{text:.{self.veh_width}}"
                else:
                    text = f"{text:<{self.veh_width}.{self.veh_width}}"
            target.text = text
            target.fg, target.bg = self.bar_style_veh[data[1]]
            self.toggle_visibility(target, data[-1])

    def update_brd(self, target, *data):
        """Brand logo"""
        if target.last != data:
            target.last = data
            if data[-1] == self.blank_state:
                target.image = None
            else:
                target.image = self.brand_logos.get(data[0])
            target.bg = self.bar_style_brd[data[1]]
            self.toggle_visibility(target, data[-1])

    def update_lpt(self, target, *data):
        """Vehicle laptime: data (pitting, in pit or valid lap, seconds), fastest last lap of class"""
        if target.last != data:
            target.last = data
            if data[1] and self.wcfg["show_highlighted_fastest_last_laptime"]:
                color_index = 2 + data[2]
            else:
                color_index = data[2]
            if data[-1] == self.blank_state:
                text = ""
            else:
                pitting, flag, seconds = data[0]
                if pitting:
                    text = self.set_pittime(flag, seconds)[:8]
                else:
                    text = self.set_laptime(seconds, flag)[:8]
            target.text = text
            target.fg, target.bg = self.bar_style_lpt[color_index]
            self.toggle_visibility(target, data[-1])

    def update_blp(self, target, *data):
        """Vehicle best laptime"""
        if target.last != data:
            target.last = data
            target.text = "" if data[-1] == self.blank_state else self.set_laptime(data[0])[:8]
            target.fg, target.bg = self.bar_style_blp[data[1]]
            self.toggle_visibility(target, data[-1])

    def update_alp(self, target, *data):
        """Vehicle average laptime"""
        if target.last != data:
            target.last = data
            target.text = "" if data[-1] == self.blank_state else self.set_laptime(data[0])[:8]
            target.fg, target.bg = self.bar_style_alp[data[1]]
            self.toggle_visibility(target, data[-1])

    def update_pic(self, target, *data):
        """Position in class"""
        if target.last != data:
            target.last = data
            if data[2]:  # player
                style = self.bar_style_pic[1]
            elif data[-1] == self.blank_state:  # no class color of car of empty row
                style = self.bar_style_pic[0]
            elif self.wcfg["show_class_style_for_position_in_class"]:
                style = (self.wcfg["font_color_position_in_class"], self.set_class_style(data[1])[1])
            else:
                style = self.bar_style_pic[0]
            target.text = "" if data[-1] == self.blank_state else f"{data[0]:02d}"
            target.fg, target.bg = style
            self.toggle_visibility(target, data[-1])

    def update_cls(self, target, *data):
        """Vehicle class"""
        if target.last != data:
            target.last = data
            # Empty row: no class of car of row (vehicle data of index -1)
            text, bg_color = self.set_class_style("" if data[-1] == self.blank_state else data[0])
            target.text = text[:self.cls_width]
            target.fg, target.bg = (self.wcfg["font_color_class"], bg_color)
            self.toggle_visibility(target, data[-1])

    def update_pit(self, target, *data):
        """Vehicle in pit"""
        if target.last != data:
            target.last = data
            if data[-1] == self.blank_state:  # empty row: no status of car of row (vehicle data of index -1)
                index = 0
            elif data[2]:  # finish flag
                index = 4
            else:
                index = data[0]
                if data[1] and index == 0:  # show yellow flag outside pits
                    index = 3
            target.text = self.pit_status_text[index]
            target.fg, target.bg = self.bar_style_pit[index]
            self.toggle_visibility(target, data[-1])

    def update_tcp(self, target, *data):
        """Tyre compound"""
        if target.last != data:
            target.last = data
            color = self.bar_style_tcp[data[1]]
            target.bg = color[1]
            show_color_by_type = (not data[1] and self.wcfg["show_compound_color_by_type"])
            if data[-1] == self.blank_state:
                target.compounds = ("",) * self.count_tcp
            # Single compound
            elif self.count_tcp == 1:
                compound = data[0][0]
                for name in data[0]:
                    if name != compound:
                        target.compounds = (self.wcfg["mixed_compound_symbol"][:1],)
                        if show_color_by_type:
                            target.colors = (self.wcfg["font_color_mixed_compound"],)
                        else:
                            target.colors = (color[0],)
                        break
                else:
                    target.compounds = (select_compound_symbol(compound),)
                    if show_color_by_type:
                        target.colors = (select_compound_color(compound),)
                    else:
                        target.colors = (color[0],)
            # All compounds
            else:
                target.compounds = tuple(select_compound_symbol(name) for name in data[0])
                if show_color_by_type:
                    target.colors = tuple(select_compound_color(name) for name in data[0])
                else:
                    target.colors = (color[0],) * self.count_tcp
            self.toggle_visibility(target, data[-1])

    def update_psc(self, target, *data):
        """Pitstop count"""
        if target.last != data:
            target.last = data
            if data[0] < 0 or data[-2].disqualified:  # penalty
                color_index = 3
            elif self.wcfg["show_pit_request"] and data[1]:
                color_index = 2
            elif data[2]:  # highlighted player
                color_index = 1
            else:
                color_index = 0
            if data[-1] == self.blank_state:
                text = ""
            elif data[0] == 0 and not data[-2].disqualified:
                text = TEXT_PLACEHOLDER
            else:
                text = count_text(data[0], data[-2])  # pit stops, or penalty (DT, SG, DQ)
            target.text = text
            target.fg, target.bg = self.bar_style_psc[color_index]
            self.toggle_visibility(target, data[-1])

    def update_nrg(self, target, *data):
        """Remaining energy, drawn again once its text or color changes (continuous value)"""
        ve = data[0]
        if data[1]:  # highlighted player
            color_index = 4
        elif ve <= -1:  # unavailable
            color_index = 0
        elif ve <= 0.1:  # 10% remaining
            color_index = 3
        elif ve <= 0.3:  # 30% remaining
            color_index = 2
        else:
            color_index = 1
        if data[-1] == self.blank_state:
            text = ""
        elif ve <= -1:
            text = "-" * self.nrg_width
        else:
            text = f"{ve:0{self.nrg_width}.{self.nrg_decimals}%}"[:self.nrg_width]
        shown = (text, color_index, data[-1])
        if target.last != shown:
            target.last = shown
            target.text = text
            target.fg, target.bg = self.bar_style_nrg[color_index]
            self.toggle_visibility(target, data[-1])

    def update_dmg(self, target, *data):
        """Vehicle integrity, drawn again once its shown tenth changes"""
        data = (int(data[0] * 10), *data[1:])
        if target.last != data:
            target.last = data
            hp = data[0]
            if data[1]:  # highlighted player
                color_index = 3
            elif hp >= 10:  # full integrity
                color_index = 0
            elif hp > 5:  # high
                color_index = 1
            else:  # low
                color_index = 2
            if data[-1] == self.blank_state:
                text = ""
            elif hp >= 10:
                text = TEXT_PLACEHOLDER
            else:
                if hp < 0:
                    hp = 0
                text = f"{hp:d}"
            target.text = text
            target.fg, target.bg = self.bar_style_dmg[color_index]
            self.toggle_visibility(target, data[-1])

    def update_icd(self, target, *data):
        """Incidents"""
        if target.last != data:
            target.last = data
            score = data[0]
            if data[1]:  # highlighted player
                color_index = 3
            elif score >= self.wcfg["incidents_extreme_threshold"]:
                color_index = 2
            elif score >= self.wcfg["incidents_high_threshold"]:
                color_index = 1
            else:
                color_index = 0
            if data[-1] == self.blank_state:
                text = ""
            elif score <= 0:
                text = "--"
            else:
                text = f"x{score:d}"
            target.text = text
            target.fg, target.bg = self.bar_style_icd[color_index]
            self.toggle_visibility(target, data[-1])

    def update_stl(self, target, *data):
        """Stint laps, drawn again once its text changes (estimated laps: continuous value)"""
        if data[-1] == self.blank_state:
            text = ""
        else:
            stint_laps_done = data[0]
            stint_laps_est = data[1]
            if stint_laps_done <= 0:
                text_done = "--"
            else:
                text_done = f"{stint_laps_done:02.0f}"
            if stint_laps_est <= 0:
                text_est = "--"
            else:
                text_est = f"{stint_laps_est // 1:02.0f}"
            text = f"{text_done}/{text_est}"
        shown = (text, data[2], data[-1])
        if target.last != shown:
            target.last = shown
            target.text = text
            target.fg, target.bg = self.bar_style_stl[data[2]]
            self.toggle_visibility(target, data[-1])

    def update_spd(self, target, *data):
        """Speed trap"""
        if target.last != data:
            target.last = data
            target.text = "" if data[-1] == self.blank_state else f"{self.unit_speed(data[0]):.3f}"[:5]
            target.fg, target.bg = self.bar_style_spd[data[1]]
            self.toggle_visibility(target, data[-1])

    def update_lic(self, target, *data):
        """Lift and coast time, drawn again once its text or color changes (continuous timer)"""
        if data[1] > self.wcfg["lift_and_coast_reset_threshold"]:
            lico_time = 0
        else:
            lico_time = data[0]
            if lico_time > 99:
                lico_time = 99
        if data[2]:  # highlighted player
            color_index = 2
        elif lico_time > self.wcfg["lift_and_coast_highlight_threshold"]:
            color_index = 1
        else:
            color_index = 0
        if data[-1] == self.blank_state:
            text = ""
        elif lico_time < 9.94:
            text = f"{lico_time:.1f}s"
        else:
            text = f"{lico_time:.0f}s"
        shown = (text, color_index, data[-1])
        if target.last != shown:
            target.last = shown
            target.text = text
            target.fg, target.bg = self.bar_style_lic[color_index]
            self.toggle_visibility(target, data[-1])

    # Additional methods
    def set_brand_logo(self, brand_name: str):
        """Set brand logo"""
        return self.brand_logos.get(brand_name)

    def brand_logo_arrived(self, brand_name: str, pixmap):
        """Brand logo read in background: drawn in cells showing brand (rows shown only: not blank, hidden or
        class separator rows, whose data is that of a car too)"""
        for target in self.bars_brd:
            if target.last is not None and target.last[0] == brand_name and target.last[-1] == self.shown_state:
                target.image = pixmap
                target.update()

    def set_class_style(self, class_name: str):
        """Compare vehicle class name with user defined dictionary"""
        style = self.cfg.user.classes.get(class_name)
        if style is not None:
            return style["alias"], style["color"]
        if class_name:
            return class_name, random_color_class(class_name)
        return class_name, self.wcfg["background_color_class"]

    @staticmethod
    def set_laptime(laptime, valid: bool = True):
        """Set lap time"""
        if 0 < laptime < MAX_SECONDS:
            if valid:
                return calc.sec2laptime_full(laptime)
            return f"*{calc.sec2laptime_full(laptime)}"
        return TEXT_NOLAPTIME

    @staticmethod
    def set_pittime(inpit, pit_time):
        """Set pit lane time (pit_time rounded to 0.1 s, negative if unknown)"""
        if pit_time >= 0:
            return f"{'PIT' if inpit else 'OUT'}{pit_time:>5.1f}"
        return TEXT_NOLAPTIME


def pit_time_shown(veh_info) -> bool:
    """Lap time column shows the pit lane time: in pit lane or on the out lap of a pit visit; a car in the garage
    (pit time 0) or finished shows its last lap instead"""
    return veh_info.pitTimer.pitting and veh_info.inPit != 2 and not veh_info.isFinished


def pit_time_key(in_pit: int, pit_time: float) -> tuple:
    """Pit lane time cell as displayed: seconds rounded to 0.1, negative if unknown"""
    return True, in_pit, round(pit_time, 1) if 0 < pit_time < MAX_SECONDS else -1.0


def lap_time_key(laptime: float, valid: bool = True) -> tuple:
    """Lap time cell: seconds, negative if unknown"""
    return False, valid, laptime if 0 < laptime < MAX_SECONDS else -1.0
