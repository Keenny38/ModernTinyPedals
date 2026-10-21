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
Driver stats viewer part (StatsTable, mixin of DriverStatsBackend): Table of vehicles (tracks for All Tracks): rows, columns, sort, key figures, header line, level distribution
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable
from contextlib import suppress
from statistics import median_low
from typing import Any

from PySide6.QtCore import Property, QObject, Slot
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPalette
from PySide6.QtWidgets import QApplication

from ... import calculation as calc
from ...const_common import MAX_SECONDS, TEXT_NOLAPTIME
from ...i18n import tr, trm
from ...setting import cfg
from ...userfile.driver_history import SessionRecord, is_reset_best
from ...userfile.driver_stats import DriverStats
from ...userfile.lap_reference import LEVELS
from ...userfile.sector_best import load_theoretical_best
from .. import UIScaler
from ..lap_viewer import number_text, signed
from .formatting import format_date, iso_day
from .stats_common import (
    DERIVED_COLUMNS,
    FIXED_COLUMNS,
    HEADER_TOOLTIPS,
    LOGO_EM,
    LOWER_IS_BETTER,
    REFERENCE_KEYS,
    RUST_COLOR,
    RUST_DAYS,
    TRACK_TOTAL_COLUMNS,
    VEHICLE_COLUMNS,
    Cell,
    class_prefix,
    combo_name,
    derived_value,
    format_derived,
    format_duration,
    format_header_key,
    header_label,
    level_letter,
    level_text,
    parse_display_value,
    places_gained,
    plural,
    stat_number,
    valid_laptime,
    vehicle_logo,
)
from .stats_core import StatsCore
from .stats_io import (
    StatsHost,
)


class StatsTable(StatsHost):
    """Table of vehicles (tracks for All Tracks): rows, columns, sort, key figures, header line, level distribution"""

    # Table
    @Slot()
    def pictures_changed(self):
        """Logos fetched from game meanwhile (or theme changed): track list & table shown again if their
        logos changed (once shown again if hidden: hidden pages never rebuild, see page_backend)"""
        if not self._loaded or self.defer_while_hidden(self.pictures_changed):
            return
        tracks = [dict(entry, logo=self.logos.track(entry["key"])) if entry["key"] else entry
                  for entry in self._tracks]
        if tracks != self._tracks:
            self._tracks = tracks
            self.tracksChanged.emit()
        if self.table_logos_changed():
            self.refresh_table()

    def table_logos_changed(self) -> bool:
        """Logo of a table row or recent session (All Tracks) not the one shown"""
        if self.selected_stats_key:
            classes = self.classes.values()
            return any(cells["vehicle"].logo != vehicle_logo(key, classes, self.logos)
                       for key, cells in self._table if "vehicle" in cells)
        return (any(row["trackLogo"] != self.logos.track(row["track"]) for row in self._recent)
                or any(cells["track"].logo != self.logos.track(key) for key, cells in self._table if "track" in cells))

    def publish(self, name: str, value: Any, signal) -> bool:
        """Part of page told (signal) only if it changed since last told, True if told"""
        if name in self._published and self._published[name] == value:
            return False
        self._published[name] = value
        signal.emit()
        return True

    def refresh_table(self):
        """Table of vehicles (or tracks), sort, selection & tiles kept; parts of page told only when changed
        (every lap while driving: stats saved)"""
        columns = self._columns
        if self.selected_stats_key:
            rows = self.vehicle_rows()
        else:
            rows = self.track_rows()
        self._unfiltered_rows = len(rows)
        self._table_classes = self.row_classes()
        self._table = self.sorted_rows([row for row in rows if self.row_shown(row)])
        self.publish_table()
        self.refresh_tiles()
        self._track_info = self.track_info()
        self._fixes = self.lap_time_fixes()
        if not self.selected_stats_key:
            self._activity = self.activity_data()
            self._recent = self.recent_sessions()
            self._driver = self.driver_card()
            self._rivals = self.rivals_card()
        selected = self._selected[self.mode]
        keys = [key for key, _ in self._table]
        if selected not in keys:
            self._selected[self.mode] = keys[0] if keys else ""
        if self._columns != columns:
            self.columnsChanged.emit()
        self.publish_sort()
        self.publish_stats()
        self.publish("tiles", self._tiles, self.tilesChanged)
        self.publish("trackInfo", self._track_info, self.trackInfoChanged)
        self.publish("levels", (self.levels_data(), self.levels_info()), self.levelsChanged)
        if not self.selected_stats_key:
            self.publish("activity", self._activity, self.activityChanged)
            self.publish("recent", self._recent, self.recentChanged)
            self.publish("driver", self._driver, self.driverChanged)
            self.publish("rivals", self._rivals, self.rivalsChanged)
            self.publish_upcoming()  # best laps on their tracks changed
            if self._visible:
                self.load_upcoming()
        self.publish_edits()
        self.publish_table_filter()
        self.update_selection()
        self.refresh_friend()  # rows of selected track

    def publish_sort(self):
        self.publish("sort", (self.mode, *self._sort[self.mode]), self.sortChanged)

    def publish_stats(self):
        self.publish("stats", (bool(self._table), self.mode, self._reading, self.filtered_out()), self.statsChanged)

    # Table search & class filter (not saved), rows grouped by class (saved)
    def filtered_out(self) -> bool:
        """Every row hidden by the search or class filter"""
        return bool(self._unfiltered_rows) and not self._table

    def row_classes(self) -> list[str]:
        """Classes of the rows made (vehicle classes, class columns of All Tracks)"""
        if self.selected_stats_key:
            return sorted({self.class_of(str(vehicle)) for vehicle in self.selected_stats_dict}, key=str.lower)
        return [key[6:] for key in self.table_header_key if key.startswith("class:")]

    def row_shown(self, row: tuple[str, dict[str, Cell]]) -> bool:
        """Row kept by the search (name) & class filter (vehicle of class, track with a lap time of class)"""
        key, cells = row
        if self._search and self._search.casefold() not in key.casefold():
            return False
        wanted = self._class_filter
        if not wanted:
            return True
        if self.selected_stats_key:
            return self.class_of(key) == wanted
        cell = cells.get(f"class:{wanted}")
        return cell is not None and cell.value is not None

    @property
    def group_by_class(self) -> bool:
        return bool(self.viewer_config().get("enable_group_by_class", False)) and bool(self.selected_stats_key)

    def publish_table_filter(self):
        self.publish("tableFilter", (self._search, self._class_filter, tuple(self._table_classes),
                                     bool(self.viewer_config().get("enable_group_by_class", False))),
                     self.tableFilterChanged)

    @Property(str, notify=StatsCore.tableFilterChanged)
    def searchText(self) -> str:
        return self._search

    @Property(str, notify=StatsCore.tableFilterChanged)
    def classFilter(self) -> str:
        return self._class_filter

    @Property(list, notify=StatsCore.tableFilterChanged)
    def tableClasses(self) -> list[str]:
        """Classes of the table rows (class filter entries)"""
        return list(self._published.get("tableFilter", ("", "", ()))[2])

    @Property(bool, notify=StatsCore.tableFilterChanged)
    def groupByClass(self) -> bool:
        return self._published.get("tableFilter", ("", "", (), False))[3]

    @Slot(str)
    def setSearch(self, text: str):
        """Rows whose name has text (vehicles, tracks for All Tracks)"""
        text = text.strip()
        if text != self._search:
            self._search = text
            self.refresh_table()

    @Slot(str)
    def setClassFilter(self, name: str):
        """Rows of a class only (empty: every class)"""
        if name != self._class_filter:
            self._class_filter = name
            self.refresh_table()  # All Tracks: lap time columns of other classes hidden too

    @Slot(bool)
    def setGroupByClass(self, enabled: bool):
        """Vehicles grouped by class (each class sorted by the sort column), saved"""
        self.save_viewer_config(enable_group_by_class=enabled)
        self.refresh_table()

    def publish_edits(self):
        self.publish("edits", (self.editing, bool(self._edits_undo), bool(self._edits_redo), self._backups is None),
                     self.editsChanged)

    def set_header(self, keys: list[str], labels: list[str]):
        self.table_header_key = keys
        self._labels = dict(zip(keys, labels))

    def vehicle_rows(self) -> list[tuple[str, dict[str, Cell]]]:
        """Vehicles of selected track: stats, reference, derived figures"""
        latest = self.latest_version()
        self.set_header(list(VEHICLE_COLUMNS), [
            f"{tr('PB')} v{latest}" if key == "version_pb" and latest else header_label(key) for key in VEHICLE_COLUMNS])
        track = self.selected_stats_key
        rows = [(str(vehicle), self.vehicle_cells(track, str(vehicle), data))
                for vehicle, data in self.selected_stats_dict.items() if isinstance(data, dict)]
        # Best personal best of each class with several vehicles: told in its tooltip
        bests: dict[str, tuple[float, str]] = {}
        counts: dict[str, int] = {}
        for vehicle, cells in rows:
            name = self.class_of(vehicle)
            counts[name] = counts.get(name, 0) + 1
            value = cells["pb"].value
            if value and (name not in bests or value < bests[name][0]):
                bests[name] = (value, vehicle)
        for name, (_, vehicle) in bests.items():
            if counts[name] > 1:
                cells = dict(rows)[vehicle]
                cells["pb"] = cells["pb"]._replace(tip=trm(f"Fastest of class {name}"))
        return rows

    def vehicle_cells(self, track: str, vehicle: str, data: dict) -> dict[str, Cell]:
        reference = self.reference_for(track, vehicle)
        best = valid_laptime(data.get("pb", 0))
        theory = self.theory_of(track, vehicle)
        cells: dict[str, Cell] = {"vehicle": Cell(vehicle, vehicle.lower(), vehicle,
                                                  logo=vehicle_logo(vehicle, self.classes.values(), self.logos))}
        percent = reference.percent(best) if reference else 0.0
        cells["gap"] = Cell(f"{number_text(percent, 2)} %" if percent else "-", percent or None, round(percent, 3) if percent else None)
        level = reference.level(best) if reference else -1
        cells["level"] = Cell(level_text(level), level if level >= 0 else None, level_text(level) if level >= 0 else None,
                              self.level_color(level), level >= 0, pill=level >= 0)
        cells["theory"] = Cell(str(parse_display_value("theory", theory)), theory or None, round(theory, 3) if theory else None)
        potential = best - theory if best and theory and best >= theory - 0.0005 else None
        cells["potential"] = Cell(number_text(max(potential, 0.0), 3) if potential is not None else "-",
                                  potential, round(max(potential, 0.0), 3) if potential is not None else None)
        for key in DERIVED_COLUMNS:
            value = derived_value(key, data)
            cells[key] = Cell(format_derived(key, value), value, round(value, 3) if value is not None else None)
        cells["last"] = self.last_cell(self.vehicle_last_driven.get((track, vehicle), 0.0))
        cells.update(self.history_cells(track, vehicle, best))
        for key in ("pb", "qb", "rb", "meters", "seconds", "liters", "valid", "invalid", "penalties",
                    "starts", "races", "wins", "podiums", "dnf"):
            value = stat_number(data, key)
            if DriverStats.is_lap_time(key):
                laptime = valid_laptime(value)
                cells[key] = Cell(str(parse_display_value(key, laptime or MAX_SECONDS)), laptime or None,
                                  round(laptime, 3) if laptime else None, bold=key == "pb" and laptime > 0)
            else:
                cells[key] = Cell(str(parse_display_value(key, value)), value, value)
        return cells

    def last_cell(self, driven: float) -> Cell:
        """Last driven date, colored when not driven for RUST_DAYS (driving again needs a warm up)"""
        if not driven:
            return Cell(format_date(driven), None, None)
        days = int((time.time() - driven) // 86400)
        if days < RUST_DAYS:
            return Cell(format_date(driven), driven, iso_day(driven))
        return Cell(format_date(driven), driven, iso_day(driven), self.rust_color(),
                    tip=trm(f"Not driven for {plural(days, 'day', 'days')}"))

    def rust_color(self) -> str:
        """Color of combos not driven for a while, darker on light theme for contrast"""
        color = QColor(RUST_COLOR)
        if QApplication.palette().color(QPalette.ColorRole.Window).lightness() >= 128:
            color = color.darker(135)
        return color.name()

    def history_cells(self, track: str, vehicle: str, best: float) -> dict[str, Cell]:
        """Columns from session history & results files: wet & latest version bests, places gained, clean races"""
        records = self.history_index.get((track, vehicle), [])

        def best_of(kept: Iterable[SessionRecord]) -> float:
            return min((record.best for record in kept if record.best > 0 and not is_reset_best(record, best)),
                       default=0.0)

        def laptime_cell(laptime: float) -> Cell:
            return Cell(calc.sec2laptime_full(laptime) if laptime else TEXT_NOLAPTIME, laptime or None,
                        round(laptime, 3) if laptime else None)

        latest = self.latest_version()
        cells = {
            "wet_pb": laptime_cell(best_of(record for record in records if record.conditions_known and record.wet)),
            "version_pb": laptime_cell(best_of(
                record for record in records if latest and self.record_version(record) == latest)),
        }
        gains = []
        linked = []
        for record in records:
            if record.session != 4:
                continue
            summary = self.record_result(record)
            gained = places_gained(record, summary if record.start_position <= 0 else None)
            if gained is not None:
                gains.append(gained)
            if summary is not None and summary.kind == "Race":
                linked.append(summary)
        gained_value = sum(gains) / len(gains) if gains else None
        cells["gained"] = Cell(signed(gained_value, 1) if gained_value is not None else "-", gained_value,
                               round(gained_value, 2) if gained_value is not None else None,
                               tip=plural(len(gains), "race", "races") if gains else "")
        clean = sum(summary.contacts == 0 and summary.penalties == 0 for summary in linked)
        rate = clean / len(linked) * 100 if linked else None
        cells["clean_rate"] = Cell(f"{number_text(rate, 0)} %" if rate is not None else "-", rate,
                                   round(rate, 1) if rate is not None else None,
                                   tip=trm(f"{clean} of {len(linked)} races without contact nor penalty")
                                   if linked else "")
        return cells

    def track_rows(self) -> list[tuple[str, dict[str, Cell]]]:
        """All Tracks: best lap of each class (level color & letter), totals; level distribution"""
        tracks = {key: vehicles for key, vehicles in self.stats_temp.items() if key and isinstance(vehicles, dict)}
        classes = sorted({self.class_of(str(vehicle)) for vehicles in tracks.values() for vehicle in vehicles},
                         key=str.lower)
        keys = ["track", *(f"class:{name}" for name in classes), *TRACK_TOTAL_COLUMNS]
        self.set_header(keys, [tr("Track"), *classes, *(header_label(key) for key in TRACK_TOTAL_COLUMNS)])
        counts = [0] * len(LEVELS)
        unrated = 0
        rows = []
        for track, vehicles in tracks.items():
            cells: dict[str, Cell] = {"track": Cell(track, track.lower(), track, logo=self.logos.track(track))}
            bests: dict[str, tuple[float, str]] = {}
            for vehicle, data in vehicles.items():
                best = valid_laptime(data.get("pb", 0)) if isinstance(data, dict) else 0.0
                name = self.class_of(str(vehicle))
                if best and (name not in bests or best < bests[name][0]):
                    bests[name] = (best, str(vehicle))
            for name in classes:
                best, vehicle = bests.get(name, (0.0, ""))
                if not best:
                    cells[f"class:{name}"] = Cell("-")
                    continue
                reference = self.reference_for(track, vehicle)
                level = reference.level(best) if reference else -1
                if reference is not None and level >= 0:
                    counts[level] += 1
                    tip = f"{vehicle} · {level_text(level)} · {number_text(reference.percent(best), 2)} %"
                else:
                    unrated += 1
                    tip = vehicle
                cells[f"class:{name}"] = Cell(calc.sec2laptime_full(best), best, round(best, 3),
                                              self.level_color(level), level >= 0, tip, level_letter(level))
            data_list = [data for data in vehicles.values() if isinstance(data, dict)]
            for key in TRACK_TOTAL_COLUMNS:
                if key == "last":
                    cells[key] = self.last_cell(self.track_last_driven.get(track, 0.0))
                else:
                    value = sum(stat_number(data, key) for data in data_list)
                    cells[key] = Cell(str(parse_display_value(key, value)), value, value)
            rows.append((track, cells))
        self.level_counts = counts
        self.unrated = unrated
        return rows

    def class_of(self, vehicle: str) -> str:
        """Game class of vehicle key: recorded in history, else class part of key"""
        return self.classes.get(vehicle) or class_prefix(vehicle)

    def theory_of(self, track: str, vehicle: str) -> float:
        """Theoretical best of track & vehicle class (sector best file, read again once changed), 0 if unknown"""
        name = combo_name(track, self.class_of(vehicle))
        path = f"{cfg.path.sector_best}{name}.sector"
        try:
            modified = os.path.getmtime(path)
        except OSError:
            return 0.0
        cached = self._theory_cache.get(name)
        if cached is None or cached[0] != modified:
            cached = self._theory_cache[name] = (modified, load_theoretical_best(cfg.path.sector_best, name))
        return cached[1]

    def sorted_rows(self, rows: list[tuple[str, dict[str, Cell]]]) -> list[tuple[str, dict[str, Cell]]]:
        """Rows by sort column (unknown values last, whatever the order)"""
        key, descending = self._sort[self.mode]
        if key not in self.table_header_key:
            key, descending = (self.table_header_key[1] if self.selected_stats_key else "track"), False
            self._sort[self.mode] = (key, descending)
        known = [row for row in rows if row[1].get(key, Cell("")).value is not None]
        unknown = [row for row in rows if row[1].get(key, Cell("")).value is None]
        known.sort(key=lambda row: row[1][key].value, reverse=descending)
        unknown.sort(key=lambda row: row[0].lower())
        ordered = known + unknown
        if self.group_by_class:  # classes in name order, each sorted as above
            ordered.sort(key=lambda row: self.class_of(row[0]).lower())
        return ordered

    @Slot(str)
    def sortBy(self, key: str):
        """Sort by column, again for reverse order"""
        current, descending = self._sort[self.mode]
        if key == current:
            descending = not descending
        else:
            descending = key in ("last",) or (key not in LOWER_IS_BETTER and key not in FIXED_COLUMNS
                                             and not key.startswith("class:"))
        self._sort[self.mode] = (key, descending)
        self._table = self.sorted_rows(self._table)
        self.publish_rows()  # rows moved: columns & widths unchanged
        self.publish_sort()
        self.publish("rowIndex", self.selected_index(), self.rowIndexChanged)  # same row: reference & charts kept

    @Property(str, notify=StatsCore.sortChanged)
    def sortKey(self) -> str:
        return self._sort[self.mode][0]

    @Property(bool, notify=StatsCore.sortChanged)
    def sortDescending(self) -> bool:
        return self._sort[self.mode][1]

    def hidden_columns(self) -> set[str]:
        text = self.viewer_config().get("hidden_columns", "")
        return {key.strip() for key in str(text).split(",") if key.strip()}

    def column_widths(self) -> dict[str, float]:
        """Column widths set by user (font size units)"""
        widths = {}
        for entry in str(self.viewer_config().get("column_widths", "")).split(","):
            key, _, width = entry.rpartition(":")
            with suppress(ValueError):
                widths[key] = float(width)
        return widths

    def visible_keys(self) -> list[str]:
        """Columns shown: fixed ones, others unless hidden by user (reference ones only while compared)"""
        hidden = self.hidden_columns()
        if not self.compare:
            hidden |= set(REFERENCE_KEYS)
        if self._class_filter and not self.selected_stats_key:  # lap times of the class filtered only
            hidden |= {key for key in self.table_header_key
                       if key.startswith("class:") and key != f"class:{self._class_filter}"}
        return [key for key in self.table_header_key if key in FIXED_COLUMNS or key not in hidden]

    def publish_table(self):
        """Visible columns (widths from contents) & rows to page"""
        self.publish_columns()
        self.publish_rows()

    def publish_columns(self):
        """Visible columns: widths from contents (each text measured once, kept while font unchanged), or set
        by user"""
        keys = self.visible_keys()
        font = QFont(QApplication.font())
        font_key = (font.key(), UIScaler.FONT_PIXEL_SCALED)
        measured = self._text_widths  # many cells share a text ("-", dates...), most unchanged after a lap
        if font_key != self._width_font or len(measured) > 20000:
            measured.clear()
            self._width_font = font_key
        metrics = QFontMetricsF(font)
        font.setBold(True)
        bold = QFontMetricsF(font)

        def text_width(text: str, is_bold: bool) -> float:
            width = measured.get((text, is_bold))
            if width is None:
                width = measured[(text, is_bold)] = (bold if is_bold else metrics).horizontalAdvance(text)
            return width

        em = float(UIScaler.FONT_PIXEL_SCALED)  # theme.em of page
        user_widths = self.column_widths()
        columns = []
        for key in keys:
            label = self._labels.get(key, key)
            width = text_width(label, True) * 1.05 + em * 2.0  # margins & sort arrow (StatsTable.qml)
            extras = False  # logo, pill or letter badge in any cell: decorations made in this column only
            for _, cells in self._table:
                cell = cells.get(key)
                if cell is not None:
                    margins = 3.3 if cell.badge else 2.4 if cell.pill else 1.6  # badge, pill & cell margins
                    if cell.logo:
                        margins += LOGO_EM  # logo before text (StatsTable.qml)
                    extras = extras or bool(cell.badge or cell.pill or cell.logo)
                    width = max(width, text_width(cell.text, cell.bold) * 1.05 + em * margins)
            if key in user_widths:
                width = max(user_widths[key] * em, em * 2)
            tip = HEADER_TOOLTIPS.get(key, "")
            columns.append({"key": key, "label": label, "tip": tr(tip) if tip else "", "width": round(width),
                            # names at left, numbers at right (tabular digits line up)
                            "align": "left" if key in FIXED_COLUMNS else "right", "extras": extras})
        self._columns = columns

    def publish_rows(self):
        """Rows to page: moved & changed in place (scroll & delegates kept); other track with mostly the same
        vehicles changed in place too (page told: back to top), else rows made again (All Tracks, few shared)"""
        keys = self.visible_keys()
        grouped = self.group_by_class
        rows = []
        previous = None
        for row_key, cells in self._table:
            group = ""
            if grouped:
                name = self.class_of(row_key)
                group = name if name != previous and previous is not None else ""
                previous = name
            rows.append({"key": row_key, "cells": [self.cell_data(cells.get(key)) for key in keys], "group": group})
        if self._published_track == self.selected_stats_key:
            self.row_model.sync(rows)
            return
        switched_from = self._published_track
        self._published_track = self.selected_stats_key
        old_keys = {row.get("key") for row in self.row_model.rows}
        shared = sum(row["key"] in old_keys for row in rows)
        if not switched_from or not self.selected_stats_key or shared * 2 < max(len(rows), len(old_keys)):
            self.row_model.reset(rows)  # All Tracks, or few vehicles in common: rows fade in
            return
        self.row_model.sync(rows)  # a reset if too many rows move (then rows fade in too)
        self.rowsSwitched.emit()

    @staticmethod
    def cell_data(cell: Cell | None) -> dict:
        """Cell of page: text, look, tooltip; unknown value dimmed"""
        if cell is None:
            return {"text": "", "color": "", "bold": False, "tip": "", "badge": "", "pill": False, "dim": False,
                    "logo": ""}
        return {"text": cell.text, "color": cell.color, "bold": cell.bold, "tip": cell.tip, "badge": cell.badge,
                "pill": cell.pill, "dim": cell.value is None and not cell.color, "logo": cell.logo}

    @Property(QObject, constant=True)
    def rows(self) -> QObject:
        return self.row_model

    @Property(list, notify=StatsCore.columnsChanged)
    def columns(self) -> list[dict]:
        return self._columns

    @Property(list, notify=StatsCore.columnsChanged)
    def columnMenu(self) -> list[dict]:
        """Columns of vehicle table that can be hidden (shared ones in All Tracks too)"""
        hidden = self.hidden_columns()
        compare = self.compare
        return [{"key": key, "label": header_label(key), "visible": key not in hidden}
                for key in VEHICLE_COLUMNS if key not in FIXED_COLUMNS and (compare or key not in REFERENCE_KEYS)]

    @Slot(str, bool)
    def setColumnVisible(self, key: str, visible: bool):
        hidden = self.hidden_columns()
        if visible:
            hidden.discard(key)
        else:
            hidden.add(key)
        self.save_viewer_config(hidden_columns=",".join(key for key in VEHICLE_COLUMNS if key in hidden))
        self.publish_table()
        self.columnsChanged.emit()

    @Slot(str, float)
    def setColumnWidth(self, key: str, width: float):
        """Column resized by user (pixels), saved in font size units"""
        em = float(UIScaler.FONT_PIXEL_SCALED)
        widths = self.column_widths()
        widths[key] = round(max(width, em * 2) / em, 2)
        self.save_viewer_config(column_widths=",".join(f"{name}:{value:g}" for name, value in widths.items()))
        self.publish_columns()  # rows unchanged
        self.columnsChanged.emit()

    @Slot()
    def resetColumnWidths(self):
        self.save_viewer_config(column_widths="")
        self.publish_columns()
        self.columnsChanged.emit()

    @Property(bool, notify=StatsCore.statsChanged)
    def hasRows(self) -> bool:
        return bool(self._table)

    @Property(str, notify=StatsCore.statsChanged)
    def tableTitle(self) -> str:
        return tr("Vehicles") if self.selected_stats_key else tr("Tracks")

    @Property(str, notify=StatsCore.statsChanged)
    def hint(self) -> str:
        if self.selected_stats_key:
            return tr("Right click a vehicle or lap time to remove or reset it, Ctrl+Z to undo.")
        return tr("Double click a track to show its vehicles.")

    @Property(str, notify=StatsCore.statsChanged)
    def emptyText(self) -> str:
        if self.filtered_out():
            return tr("No row matches the search or class filter.")
        if self.selected_stats_key:
            return tr("No stats for this track yet: drive a few laps.")
        return tr("No stats yet: drive a few laps.")

    def cell(self, key: str, column: str) -> Cell | None:
        """Cell of row key & column key (tests, actions)"""
        for row_key, cells in self._table:
            if row_key == key:
                return cells.get(column)
        return None

    def row_keys(self) -> list[str]:
        return [key for key, _ in self._table]

    # Key figures
    def refresh_tiles(self):
        """Key figures of selected track, all vehicles (All Tracks: career)"""
        if self.selected_stats_key:
            data = [value for value in self.selected_stats_dict.values() if isinstance(value, dict)]
            tiles = self.track_tiles()
        else:
            data = [value for vehicles in self.stats_temp.values() if isinstance(vehicles, dict)
                    for value in vehicles.values() if isinstance(value, dict)]
            tiles = self.career_tiles()

        def total(key: str) -> float:
            return sum(stat_number(value, key) for value in data)

        meters = total("meters")
        valid, invalid = total("valid"), total("invalid")
        laps = valid + invalid
        laps_detail = ""
        if laps:
            laps_detail = trm(f"{valid / laps * 100:.0f} % of {laps:.0f} {'lap' if laps == 1 else 'laps'}")
        races_detail = f"{plural(total('wins'), 'win', 'wins')} · {plural(total('podiums'), 'podium', 'podiums')}"
        tiles += [
            self.tile(tr("Distance"), f"{parse_display_value('meters', meters)} {tr(format_header_key('meters')).lower()}"
                      if data else "-", glyph=""),  # car
            self.tile(tr("Driving Time"), format_duration(total("seconds")) if data else "-", glyph=""),  # clock
            self.tile(tr("Valid Laps"), f"{valid:.0f}" if data else "-", laps_detail, glyph="",  # check
                      ratio=valid / laps if laps else -1.0),
            self.tile(tr("Races"), f"{total('races'):.0f}" if data else "-", races_detail if data else "",
                      glyph=""),  # flag
        ]
        self._tiles = tiles

    @staticmethod
    def tile(title: str, value: str, detail: str = "", color: str = "", tip: str = "", glyph: str = "",
             letter: str = "", ratio: float = -1.0) -> dict:
        """Key figure: icon, title, value (color: level), detail line, level letter, ratio bar (-1: none)"""
        return {"title": title, "value": value, "detail": detail, "color": color, "tip": tip, "glyph": glyph,
                "letter": letter, "ratio": ratio}

    def track_tiles(self) -> list[dict]:
        """Best lap of track & its level"""
        bests = [(valid_laptime(value.get("pb", 0)), name) for name, value in self.selected_stats_dict.items()
                 if isinstance(value, dict)]
        bests = [entry for entry in bests if entry[0] > 0]
        tip_best = tr("Best personal best of the track, any vehicle")
        tip_level = tr("Level of best lap on community lap times")
        if not bests:
            return [self.tile(tr("Best Lap"), "-", tip=tip_best, glyph=""),  # stopwatch
                    self.tile(tr("Level"), "-", tip=tip_level, glyph="")]  # star
        best, vehicle = min(bests)
        reference = self.reference_of(vehicle)
        level = reference.level(best) if reference else -1
        if reference is not None:
            detail = f"{number_text(reference.percent(best), 2)} %"
        else:
            detail = tr("No reference for this track or class") if self.references.entries else ""
        return [self.tile(tr("Best Lap"), calc.sec2laptime_full(best), vehicle, tip=tip_best, glyph=""),
                self.tile(tr("Level"), level_text(level), detail, self.level_color(level), tip_level, glyph="",
                          letter=level_letter(level))]

    def career_tiles(self) -> list[dict]:
        """Tracks driven & most driven one, median level of best laps"""
        tracks = {key: vehicles for key, vehicles in self.stats_temp.items() if key and isinstance(vehicles, dict)}
        seconds = {key: sum(stat_number(data, "seconds") for data in vehicles.values() if isinstance(data, dict))
                   for key, vehicles in tracks.items()}
        most = max(seconds, key=lambda key: seconds[key], default="")
        detail = trm(f"Most driven: {most}") if most and seconds[most] > 0 else ""
        levels = [level for level, count in enumerate(self.level_counts) for _ in range(count)]
        level = median_low(levels) if levels else -1
        level_detail = f"{tr('Median of')} {plural(len(levels), 'best lap', 'best laps')}" if levels else ""
        return [
            self.tile(tr("Tracks"), str(len(tracks)) if tracks else "-", detail, tip=f"{tr('Tracks with stats')}\n{detail}",
                      glyph=""),  # map pin
            self.tile(tr("Level"), level_text(level), level_detail, self.level_color(level),
                      tr("Median level of your best laps, all tracks & classes"), glyph="",
                      letter=level_letter(level)),
        ]

    # Header line: vehicles, sessions & last driven date of track (All Tracks: tracks, sessions, first date)
    def track_info(self) -> dict:
        track = self.selected_stats_key
        if track:
            sessions, first = self.track_sessions.get(track, (0, 0.0))
            parts = [plural(len(self.selected_stats_dict), "vehicle", "vehicles")]
            driven = self.track_last_driven.get(track, 0.0)
        else:
            found = [self.track_sessions[key] for key in self.stats_temp if key in self.track_sessions]
            sessions, first = sum(count for count, _ in found), min((when for _, when in found), default=0.0)
            count = len([key for key in self.stats_temp if key])
            parts = [plural(count, "track", "tracks")] if count else []  # no stats: empty page says it
            driven = 0.0
        if sessions:
            parts.append(plural(sessions, "session", "sessions"))
            if track:
                parts.append(f"{tr('last driven')} {format_date(driven)}")
            else:
                parts.append(f"{tr('since')} {format_date(first)}")
        return {"subtitle": " · ".join(parts), "live": bool(track) and track == self.game_track()}

    @Property(dict, notify=StatsCore.trackInfoChanged)
    def trackInfo(self) -> dict:
        """Line under track name (subtitle), live: track of game session"""
        return self._track_info

    @Property(list, notify=StatsCore.tilesChanged)
    def tiles(self) -> list[dict]:
        return self._tiles

    # Level distribution (All Tracks)
    def levels_data(self) -> list[dict]:
        top = max(self.level_counts, default=0)
        return [{"name": tr(name), "color": self.level_color(level), "count": self.level_counts[level],
                 "ratio": self.level_counts[level] / top if top else 0.0, "letter": level_letter(level)}
                for level, name in enumerate(LEVELS)]

    @Property(list, notify=StatsCore.levelsChanged)
    def levels(self) -> list[dict]:
        return self._published.get("levels", ([], ""))[0]

    @Property(str, notify=StatsCore.levelsChanged)
    def levelsInfo(self) -> str:
        return self._published.get("levels", ([], ""))[1]

    def levels_info(self) -> str:
        if not any(self.level_counts):
            return tr("No level yet: community lap times needed, vehicle classification by class.")
        if self.unrated:
            return plural(self.unrated, "track & class combo without reference", "track & class combos without reference")
        return ""
