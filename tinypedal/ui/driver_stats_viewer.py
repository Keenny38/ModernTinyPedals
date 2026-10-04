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
Driver stats viewer

Track selector & actions, key figures of the track (best lap and its level, distance, driving
time, valid laps, races), stats table of each vehicle, and the lap time reference of the
selected vehicle: community LMU lap times (userfile.lap_reference), level ladder from Alien to
Offline with personal & race best placed on it.
"""

from __future__ import annotations

import threading
import time
from contextlib import suppress

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import calculation as calc
from .. import units
from ..api_control import api
from ..const_common import MAX_SECONDS, TEXT_NOLAPTIME
from ..const_file import ConfigType
from ..formatter import strip_invalid_char
from ..i18n import tr, trm, untr
from ..setting import cfg
from ..userfile import lap_reference
from ..userfile.driver_stats import (
    DriverStats,
    load_stats_json_file,
    save_stats_json_file,
    validate_stats_file,
)
from ..userfile.lap_reference import LEVEL_COLORS, LEVELS, LapReference, LapReferenceTable
from ._common import (
    BaseEditor,
    NumericTableItem,
    TextInputDialog,
    UIScaler,
    table_item,
)
from .race_widgets import Card, KpiTile, muted_label
from .track_map_viewer import TrackMapViewer

REFERENCE_MAX_AGE = 24 * 3600  # seconds before cached lap time reference is downloaded again
REFERENCE_KEYS = ("gap", "level")  # table columns from lap time reference, after personal best


def parse_display_value(key: str, value: float) -> str | float:
    """Parse stats display value"""
    if DriverStats.is_lap_time(key):
        if 0 < value < MAX_SECONDS:
            return calc.sec2laptime_full(value)
        return TEXT_NOLAPTIME
    if key == "meters":
        if cfg.units["odometer_unit"] == "Kilometer":
            return round(units.meter_to_kilometer(value), 1)
        if cfg.units["odometer_unit"] == "Mile":
            return round(units.meter_to_mile(value), 1)
        return int(value)
    if key == "seconds":
        return round(value / 60 / 60, 2)
    if key == "liters":
        if cfg.units["fuel_unit"] == "Gallon":
            value = units.liter_to_gallon(value)
        return round(value, 2)
    return value


def format_header_key(key: str):
    """Format header key"""
    if key == "pb":
        return "PB"
    if key == "qb":
        return "Qualifying"
    if key == "rb":
        return "Race"
    if key == "meters":
        if cfg.units["odometer_unit"] == "Kilometer":
            return "Km"
        if cfg.units["odometer_unit"] == "Mile":
            return "Miles"
        return "Meters"
    if key == "seconds":
        return "Hours"
    if key == "liters":
        if cfg.units["fuel_unit"] == "Gallon":
            return "Gallons"
        return "Liters"
    if key == "races":
        return "Finishes"
    if key == "gap":
        return "Ref."
    return key.title()


def valid_laptime(value) -> float:
    """Lap time in seconds, 0 if none"""
    return value if isinstance(value, (int, float)) and 0 < value < MAX_SECONDS else 0.0


def level_text(level: int) -> str:
    return tr(LEVELS[level]) if level >= 0 else "-"


class LevelLadder(QWidget):
    """Reference levels from Alien to Offline: lap time limit of each, personal & race best placed"""

    def __init__(self, parent):
        super().__init__(parent)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(UIScaler.pixel(10))
        self.grid.setVerticalSpacing(UIScaler.pixel(3))
        self.rows: list[tuple[QLabel, QLabel, QLabel]] = []
        for level, name in enumerate(LEVELS):
            label_name = QLabel(f"<span style='color:{LEVEL_COLORS[level]}'>●</span> {tr(name)}")
            label_name.setTextFormat(Qt.TextFormat.RichText)
            label_limit = muted_label("")
            label_limit.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            label_mark = QLabel("")
            label_mark.setObjectName("statsMark")
            self.grid.addWidget(label_name, level, 0)
            self.grid.addWidget(label_limit, level, 1)
            self.grid.addWidget(label_mark, level, 2)
            self.rows.append((label_name, label_limit, label_mark))
        self.grid.setColumnStretch(2, 1)

    def set_reference(self, reference: LapReference | None, best: float, race_best: float):
        # Limits: last ladder step of each level (Midpack 104%, Tail-ender 106%), Offline slower
        limits = {}
        if reference is not None:
            for step, level in enumerate(lap_reference.LADDER_LEVEL):
                limits[level] = reference.ladder[step]
        marks: dict[int, list[str]] = {}
        for text, laptime in ((tr("PB"), best), (tr("Race"), race_best)):
            if reference is not None and laptime > 0:
                marks.setdefault(reference.level(laptime), []).append(text)
        for level, (label_name, label_limit, label_mark) in enumerate(self.rows):
            limit = limits.get(level, 0.0)
            if level == len(LEVELS) - 1 and level - 1 in limits:
                label_limit.setText(f"> {calc.sec2laptime_full(limits[level - 1])}")
            else:
                label_limit.setText(f"≤ {calc.sec2laptime_full(limit)}" if limit else "-")
            mark = marks.get(level, [])
            label_mark.setText("  ".join(f"← {text}" for text in mark))
            font = label_name.font()
            font.setBold(bool(mark))
            label_name.setFont(font)


class ReferenceCard(Card):
    """Lap time reference of selected vehicle: level ladder, gap to reference & fastest car"""

    def __init__(self, parent):
        super().__init__(parent, tr("Lap Time Reference"))
        self.label_subject = QLabel("")
        self.label_subject.setWordWrap(True)
        self.ladder = LevelLadder(self)
        self.label_gap = QLabel("")
        self.label_gap.setWordWrap(True)
        self.label_fastest = muted_label("")
        self.label_fastest.setWordWrap(True)
        self.label_empty = muted_label("")
        self.label_empty.setWordWrap(True)
        self.grid.addWidget(self.label_subject, 0, 0)
        self.grid.addWidget(self.ladder, 1, 0)
        self.grid.addWidget(self.label_gap, 2, 0)
        self.grid.addWidget(self.label_fastest, 3, 0)
        self.grid.addWidget(self.label_empty, 4, 0)
        self.layout_card.addStretch(1)

    def show_reference(self, vehicle: str, reference: LapReference | None, best: float, race_best: float,
                       reason: str = ""):
        has_reference = reference is not None
        for widget in (self.label_subject, self.ladder, self.label_gap, self.label_fastest):
            widget.setVisible(has_reference)
        self.label_empty.setVisible(not has_reference)
        if reference is None:
            self.label_empty.setText(reason)
            return
        patch = f" · {tr('patch')} {reference.patch}" if reference.patch else ""
        self.label_subject.setText(f"<b>{vehicle}</b><br>{reference.track} · {reference.vehicle_class}{patch}")
        self.ladder.set_reference(reference, best, race_best)
        if best > 0:
            gap = best - reference.reference
            self.label_gap.setText(trm(
                f"Personal best {calc.sec2laptime_full(best)}: {gap:+.2f} s ({reference.percent(best):.2f} %) "
                f"to reference {calc.sec2laptime_full(reference.reference)}"))
        else:
            self.label_gap.setText(trm(f"Reference {calc.sec2laptime_full(reference.reference)}, no personal best yet"))
        if reference.fastest_car and reference.fastest_time:
            self.label_fastest.setText(trm(
                f"Fastest car: {reference.fastest_car} · {calc.sec2laptime_full(reference.fastest_time)}"))
        else:
            self.label_fastest.setText("")


class DriverStatsViewer(BaseEditor):
    """Driver stats viewer"""

    reference_loaded = Signal(str, str)  # sheet CSV text (empty if failed), error

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Driver Stats Viewer"))
        self.setMinimumSize(UIScaler.size(60), UIScaler.size(30))
        self.resize(UIScaler.size(90), UIScaler.size(52))

        self.stats_temp: dict = {}
        self.selected_stats_key = ""  # get active session key
        self.selected_stats_dict: dict = {}
        self.references = LapReferenceTable()
        self.reference_error = ""
        self._downloading = False
        self.reference_loaded.connect(self.reference_downloaded)

        # Header: track selector & actions, lap time reference source
        self.stats_list = QComboBox()
        self.stats_list.setObjectName("statsTrack")
        self.stats_list.currentIndexChanged.connect(self.select_stats)
        button_viewmap = QPushButton(tr("View Map"))
        button_viewmap.clicked.connect(self.open_trackmap)
        button_delete = QPushButton(tr("Delete"))
        button_delete.setToolTip(tr("Delete all stats of this track"))
        button_delete.clicked.connect(self.delete_stats_key)
        button_reload = QPushButton(tr("Reload"))
        button_reload.clicked.connect(self.reload_stats)
        self.label_reference = muted_label("")
        self.label_reference.setTextFormat(Qt.TextFormat.RichText)
        self.label_reference.setOpenExternalLinks(True)
        self.button_reference = QPushButton(tr("Reference"))
        self.button_reference.setToolTip(tr("Community lap times compared with your lap times"))
        menu_reference = QMenu(self)
        self.action_update = menu_reference.addAction(tr("Update Reference"))
        self.action_update.triggered.connect(lambda: self.download_reference(force=True))
        menu_reference.addAction(tr("Change Sheet Address...")).triggered.connect(self.change_sheet_url)
        self.action_enable = menu_reference.addAction(tr("Compare With Community Lap Times"))
        self.action_enable.setCheckable(True)
        self.action_enable.setChecked(bool(self.reference_config().get("enable_lap_reference", True)))
        self.action_enable.toggled.connect(self.toggle_reference)
        self.button_reference.setMenu(menu_reference)
        layout_header = QHBoxLayout()
        layout_header.addWidget(self.stats_list, stretch=2)
        for button in (button_viewmap, button_reload, button_delete):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            layout_header.addWidget(button)
        layout_header.addStretch(1)
        layout_header.addWidget(self.label_reference)
        layout_header.addWidget(self.button_reference)

        # Key figures of selected track
        self.tile_best = KpiTile(self, tr("Best Lap"), tr("Best personal best of the track, any vehicle"))
        self.tile_level = KpiTile(self, tr("Level"), tr("Level of best lap on community lap times"))
        self.tile_distance = KpiTile(self, tr("Distance"))
        self.tile_time = KpiTile(self, tr("Driving Time"))
        self.tile_laps = KpiTile(self, tr("Valid Laps"))
        self.tile_races = KpiTile(self, tr("Races"))
        layout_tiles = QGridLayout()
        layout_tiles.setSpacing(UIScaler.pixel(10))
        for index, tile in enumerate((self.tile_best, self.tile_level, self.tile_distance,
                                      self.tile_time, self.tile_laps, self.tile_races)):
            layout_tiles.addWidget(tile, 0, index)

        # Stats table of each vehicle
        self.table_header_key = ["vehicle", "pb", *REFERENCE_KEYS,
                                 *(key for key in DriverStats.__annotations__ if key != "pb")]
        self.table_stats = QTableWidget(self)
        self.table_stats.setColumnCount(len(self.table_header_key))
        self.table_stats.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_stats.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_stats.setHorizontalHeaderLabels([tr(format_header_key(key)) for key in self.table_header_key])
        self.table_stats.verticalHeader().setVisible(False)
        self.table_stats.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table_stats.setShowGrid(False)
        self.table_stats.setAlternatingRowColors(True)
        self.table_stats.setFrameShape(QFrame.Shape.NoFrame)
        self.table_stats.setWordWrap(False)
        header = self.table_stats.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setMinimumSectionSize(UIScaler.size(3.5))
        self.table_stats.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_stats.customContextMenuRequested.connect(self.open_context_menu)
        self.table_stats.itemSelectionChanged.connect(self.show_selected_reference)
        self.label_empty = muted_label(tr("No stats for this track yet: drive a few laps."))
        self.label_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_table = Card(self, tr("Vehicles"))
        hint = muted_label(tr("Right click a vehicle or lap time to remove or reset it."))
        card_table.layout_card.addWidget(hint)
        card_table.layout_card.addWidget(self.table_stats, stretch=1)
        card_table.layout_card.addWidget(self.label_empty, stretch=1)

        self.card_reference = ReferenceCard(self)
        self.card_reference.setMinimumWidth(UIScaler.size(20))
        self.card_reference.setMaximumWidth(UIScaler.size(24))  # table keeps the room

        layout_body = QHBoxLayout()
        layout_body.setSpacing(UIScaler.pixel(10))
        layout_body.addWidget(card_table, stretch=3)
        layout_body.addWidget(self.card_reference, stretch=1)

        layout_main = QVBoxLayout(self)
        layout_main.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        layout_main.setSpacing(UIScaler.pixel(10))
        layout_main.addLayout(layout_header)
        layout_main.addLayout(layout_tiles)
        layout_main.addLayout(layout_body, stretch=1)

        self.load_reference()
        self.reload_stats()
        self.refresh_table()
        self.download_reference()

    # Lap time reference
    def reference_config(self) -> dict:
        return cfg.user.config.get("driver_stats_viewer", {})

    def load_reference(self):
        """Lap time reference kept from last download (works offline)"""
        text, _ = lap_reference.load_cache(cfg.path.config)
        self.references = lap_reference.parse_lap_references(text) if text else LapReferenceTable()
        self.update_reference_label()

    def download_reference(self, force: bool = False):
        """Download lap time reference in background, when older than a day (or asked)"""
        config = self.reference_config()
        if not config.get("enable_lap_reference", True) or self._downloading:
            return
        _, cached_time = lap_reference.load_cache(cfg.path.config)
        if not force and cached_time and time.time() - cached_time < REFERENCE_MAX_AGE:
            return
        url = config.get("lap_reference_sheet_url") or lap_reference.DEFAULT_SHEET_URL
        self._downloading = True
        self.update_reference_label()

        def download():
            try:
                text, error = lap_reference.fetch_sheet(url), ""
            except (OSError, ValueError) as exc:
                text, error = "", str(exc)
            with suppress(RuntimeError):  # page closed meanwhile
                self.reference_loaded.emit(text, error)

        threading.Thread(target=download, daemon=True, name="Lap reference download").start()

    def reference_downloaded(self, text: str, error: str):
        self._downloading = False
        self.reference_error = error
        if text:
            lap_reference.save_cache(cfg.path.config, text)
            self.references = lap_reference.parse_lap_references(text)
        self.update_reference_label()
        self.refresh_table()

    def update_reference_label(self):
        source = f"<a href='{lap_reference.SHEET_SOURCE_URL}'>{lap_reference.SHEET_SOURCE}</a>"
        if not self.reference_config().get("enable_lap_reference", True):
            text = tr("Community lap times off")
        elif self._downloading:
            text = tr("Downloading community lap times...")
        elif self.references.entries:
            updated = f" · {tr('updated')} {self.references.updated}" if self.references.updated else ""
            text = f"{tr('Community lap times')} ({source}){updated}"
        elif self.reference_error:
            text = tr("Community lap times unavailable (offline?)")
        else:
            text = ""
        self.label_reference.setText(text)
        self.action_update.setEnabled(not self._downloading)

    def reference_of(self, vehicle: str) -> LapReference | None:
        if not self.references.entries or not self.reference_config().get("enable_lap_reference", True):
            return None
        return self.references.find(self.selected_stats_key, vehicle)

    def save_reference_config(self, **values):
        config = cfg.user.config.setdefault("driver_stats_viewer", {})
        if any(config.get(key) != value for key, value in values.items()):
            config.update(values)
            cfg.save(config_type=ConfigType.CONFIG)

    def toggle_reference(self, enabled: bool):
        """Compare with community lap times or not (saved)"""
        self.save_reference_config(enable_lap_reference=enabled)
        self.update_reference_label()
        self.refresh_table()
        if enabled:
            self.download_reference()

    def change_sheet_url(self):
        """Published Google Sheet of lap times (same layout), downloaded at once"""
        def accept(url: str) -> bool:
            url = url.strip() or lap_reference.DEFAULT_SHEET_URL
            if not url.startswith("https://docs.google.com/spreadsheets/"):
                QMessageBox.warning(self, tr("Error"), tr("Not a Google Sheets address."))
                return False
            self.save_reference_config(lap_reference_sheet_url=url)
            self.download_reference(force=True)
            return True

        TextInputDialog(
            self, tr("Change Sheet Address..."),
            tr("Address of the published Google Sheet of community lap times (empty for default):"),
            accept, self.reference_config().get("lap_reference_sheet_url") or lap_reference.DEFAULT_SHEET_URL,
        ).open()

    # Stats
    def reload_stats(self):
        """Reload stats data"""
        stats_user = load_stats_json_file(
            filepath=cfg.path.config,
        )
        if stats_user is None:
            self.refresh_tiles()
            return

        self.stats_temp = validate_stats_file(stats_user)

        if self.selected_stats_key:
            last_selected_stats_key = self.selected_stats_key
        else:  # initial load current track name
            last_selected_stats_key = api.read.session.track_name()

        self.stats_list.clear()
        if self.stats_temp:
            self.stats_list.addItems(sorted(self.stats_temp, key=sort_stats_key))
        self.stats_list.setCurrentText(last_selected_stats_key)

    def refresh_table(self):
        """Refresh stats table"""
        self.table_stats.setSortingEnabled(False)  # must disable before refresh
        self.table_stats.setRowCount(0)

        row_index = 0
        for veh_name, veh_data in self.selected_stats_dict.items():
            self.add_stats_vehicle(row_index, veh_name, veh_data)
            row_index += 1

        self.table_stats.setSortingEnabled(True)
        self.table_stats.sortByColumn(1, Qt.SortOrder.AscendingOrder)  # sort by laptime
        has_rows = self.table_stats.rowCount() > 0
        self.table_stats.setHidden(not has_rows)
        self.label_empty.setHidden(has_rows)
        if has_rows and not self.table_stats.selectedItems():
            self.table_stats.selectRow(0)  # best vehicle: its reference shown
        self.refresh_tiles()
        self.show_selected_reference()

    def add_stats_vehicle(self, row_index: int, veh_name: str, veh_data: dict):
        """Add stats vehicle to table"""
        self.table_stats.insertRow(row_index)
        flag_selectable = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        reference = self.reference_of(str(veh_name))
        best = valid_laptime(veh_data.get("pb", 0))

        for column_index, header_key in enumerate(self.table_header_key):
            # Vehicle name
            if column_index == 0:
                item = QTableWidgetItem(str(veh_name))
                item.setFlags(flag_selectable)
                self.table_stats.setItem(row_index, column_index, item)
                continue
            # Lap time reference: gap in percent, level
            if header_key == "gap":
                percent = reference.percent(best) if reference else 0.0
                item = NumericTableItem(percent or 999.0, f"{percent:.2f} %" if percent else "-")
            elif header_key == "level":
                level = reference.level(best) if reference else -1
                item = NumericTableItem(level if level >= 0 else 99, level_text(level))
                if level >= 0:
                    item.setForeground(QColor(LEVEL_COLORS[level]))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
            else:  # Vehicle stats
                value_raw = veh_data.get(header_key, 0)
                if DriverStats.is_lap_time(header_key) and value_raw <= 0:
                    value_raw = MAX_SECONDS  # correct invalid lap time
                item = NumericTableItem(value_raw, str(parse_display_value(header_key, value_raw)))
            item.setFlags(flag_selectable)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_stats.setItem(row_index, column_index, item)

    def refresh_tiles(self):
        """Key figures of selected track, all vehicles"""
        data = list(self.selected_stats_dict.values())

        def total(key: str) -> float:
            return sum(value.get(key, 0) for value in data if isinstance(value.get(key, 0), (int, float)))

        bests = [(valid_laptime(value.get("pb", 0)), name) for name, value in self.selected_stats_dict.items()]
        bests = [entry for entry in bests if entry[0] > 0]
        if bests:
            best, vehicle = min(bests)
            self.tile_best.set_text(calc.sec2laptime_full(best), vehicle)
            reference = self.reference_of(vehicle)
            level = reference.level(best) if reference else -1
            self.tile_level.set_text(level_text(level), f"{reference.percent(best):.2f} %" if reference else (
                tr("No reference for this track or class") if self.references.entries else ""))
            color = LEVEL_COLORS[level] if level >= 0 else ""
            self.tile_level.label_value.setStyleSheet(f"color:{color}" if color else "")
        else:
            self.tile_best.set_text("-")
            self.tile_level.set_text("-")
            self.tile_level.label_value.setStyleSheet("")
        meters = total("meters")
        self.tile_distance.set_text(
            f"{parse_display_value('meters', meters)} {tr(format_header_key('meters')).lower()}" if data else "-")
        self.tile_time.set_text(f"{parse_display_value('seconds', total('seconds'))} h" if data else "-")
        valid, invalid = total("valid"), total("invalid")
        laps = valid + invalid
        self.tile_laps.set_text(f"{valid:.0f}" if data else "-",
                                trm(f"{valid / laps * 100:.0f} % of {laps:.0f} laps") if laps else "")
        self.tile_races.set_text(f"{total('races'):.0f}" if data else "-",
                                 trm(f"{total('wins'):.0f} wins · {total('podiums'):.0f} podiums") if data else "")

    def show_selected_reference(self):
        """Reference card follows selected vehicle"""
        rows = {item.row() for item in self.table_stats.selectedItems()}
        if not rows:
            self.card_reference.show_reference("", None, 0, 0, tr("Select a vehicle to compare its lap times."))
            return
        vehicle = table_item(self.table_stats, min(rows), 0).text()
        data = self.selected_stats_dict.get(vehicle, {})
        reference = self.reference_of(vehicle)
        if reference is not None:
            reason = ""
        elif not self.references.entries:
            reason = tr("Community lap times not downloaded yet.")
        elif not lap_reference.vehicle_class_of(vehicle):
            reason = tr("Vehicle class unknown: set vehicle classification to class (Class - Brand) to compare.")
        else:
            reason = trm(f"No community lap time for {self.selected_stats_key} in this class.")
        self.card_reference.show_reference(
            vehicle, reference, valid_laptime(data.get("pb", 0)), valid_laptime(data.get("rb", 0)), reason)

    def select_stats(self):
        """Select stats key"""
        self.selected_stats_key = self.stats_list.currentText()
        if self.selected_stats_key:
            self.selected_stats_dict = self.stats_temp[self.selected_stats_key]
        else:
            self.selected_stats_dict = {}
        self.refresh_table()

    def delete_stats_key(self):
        """Delete stats key"""
        if not self.selected_stats_key:
            QMessageBox.warning(self, tr("Error"), tr("No data found."))
            return

        msg_text = (
            "Delete all stats from<br>"
            f"<b>{self.selected_stats_key}</b> ?<br><br>"
            "This cannot be undone!"
        )
        if self.confirm_operation(message=msg_text):
            self.stats_temp.pop(self.selected_stats_key, None)  # remove from dict
            save_stats_json_file(
                stats_user=self.stats_temp,
                filepath=cfg.path.config,
            )
            self.selected_stats_key = ""
            self.reload_stats()

    def remove_vehicle(self):
        """Remove vehicle and stats"""
        selected_rows = [data.row() for data in self.table_stats.selectedIndexes()]
        if not selected_rows:
            QMessageBox.warning(self, tr("Error"), tr("No data selected."))
            return

        track_stats = self.stats_temp.get(self.selected_stats_key, None)
        if not isinstance(track_stats, dict):
            QMessageBox.warning(self, tr("Error"), tr("No data found."))
            return

        selected_vehicle = table_item(self.table_stats, selected_rows[0], 0).text()
        msg_text = (
            f"Remove all stats from <b>{selected_vehicle}</b>?<br><br>"
            "This cannot be undone!"
        )
        if self.confirm_operation(message=msg_text):
            track_stats.pop(selected_vehicle, None)  # remove from dict
            save_stats_json_file(
                stats_user=self.stats_temp,
                filepath=cfg.path.config,
            )
            self.reload_stats()

    def reset_stat(self, row: int, column: int):
        """Reset stat"""
        selected_vehicle = table_item(self.table_stats, row, 0).text()
        selected_column = self.table_header_key[column]
        best_laptime = table_item(self.table_stats, row, column).text()
        if best_laptime == TEXT_NOLAPTIME:
            QMessageBox.warning(self, tr("Error"), tr("No lap time found."))
            return
        msg_text = (
            f"Reset <b>{best_laptime}</b> lap time for <b>{selected_vehicle}</b>?<br><br>"
            "This cannot be undone!"
        )
        if self.confirm_operation(message=msg_text):
            default_value = DriverStats.__dict__[selected_column]
            self.stats_temp[self.selected_stats_key][selected_vehicle][selected_column] = default_value
            save_stats_json_file(
                stats_user=self.stats_temp,
                filepath=cfg.path.config,
            )
            self.reload_stats()

    def open_context_menu(self, position: QPoint):
        """Open context menu"""
        item = self.table_stats.itemAt(position)
        if not item:
            return

        item_row = item.row()
        item_column = item.column()

        menu = QMenu()  # no parent for temp menu
        if item_column == 0:
            menu.addAction(tr("Remove Vehicle"))
        elif DriverStats.is_lap_time(self.table_header_key[item_column]):
            menu.addAction(tr("Reset Lap Time"))
        else:
            return

        position += QPoint(  # position correction from header
            self.table_stats.verticalHeader().width(),
            self.table_stats.horizontalHeader().height(),
        )
        selected_action = menu.exec(self.table_stats.mapToGlobal(position))
        if not selected_action:
            return

        action = untr(selected_action.text())
        if action == "Remove Vehicle":
            self.remove_vehicle()
        elif action == "Reset Lap Time":
            self.reset_stat(item_row, item_column)

    def open_trackmap(self):
        """Open trackmap, make sure to strip off invalid char from key name"""
        _dialog = TrackMapViewer(
            self,
            filepath=cfg.path.track_map,
            filename=strip_invalid_char(self.selected_stats_key),
        )
        _dialog.show()


def sort_stats_key(key: str):
    """Sort stats key in lower case"""
    return key.lower()
