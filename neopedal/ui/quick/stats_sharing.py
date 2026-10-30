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
Driver stats viewer part (StatsSharing, mixin of DriverStatsBackend): Exports (table & session history), friend's stats compared
"""

from __future__ import annotations

import csv
import html
import logging
import os
from functools import partial

from PySide6.QtCore import Property, QLocale, QStandardPaths, QUrl, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog

from ... import calculation as calc
from ...const_app import VERSION
from ...formatter import strip_invalid_char
from ...i18n import tr, trm
from ...rank_info import ranks
from ...userfile import pb_code
from ...userfile.driver_history import SessionRecord, best_lap_date
from ...userfile.pb_code import SharedBest
from ..lap_viewer import number_text, signed
from . import dialogs
from .formatting import format_date
from .stats_card import CardData, draw_card
from .stats_common import (
    HISTORY_COLUMNS,
    RAW_UNITS,
    SESSION_NAMES,
    csv_number,
    csv_text,
    level_text,
    valid_laptime,
)
from .stats_core import StatsCore
from .stats_io import (
    StatsHost,
)
from .stint_analysis import (
    compare_friend,
    history_document,
    load_friend,
    write_history_csv,
    write_history_json,
)

logger = logging.getLogger(__name__)


class StatsSharing(StatsHost):
    """Exports (table & session history), friend's stats compared"""

    # Session history export (CSV, or JSON a friend can compare with)
    def history_records(self) -> list[SessionRecord]:
        """Session records of selected track, every track for All Tracks"""
        return [record for record in self.history if not self.selected_stats_key or record.track == self.selected_stats_key]

    @Slot(str)
    def exportHistory(self, kind: str):
        """Session history of selected track (every track for All Tracks) to CSV or JSON (friend's comparison)"""
        if not self.history_records():
            self.warning(tr("No session recorded yet: history starts with your next session."))
            return
        name = strip_invalid_char(self.selected_stats_key or tr("All Tracks"))
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        extension = "json" if kind == "json" else "csv"
        default = os.path.join(folder or os.path.expanduser("~"), f"{name} - {tr('Session History')}.{extension}")
        filename, _ = QFileDialog.getSaveFileName(self._window, tr("Export Session History…"), default,
                                                  "JSON (*.json)" if extension == "json" else "CSV (*.csv)")
        if filename and self.write_history(filename, extension):
            self.toast_exported(filename)

    def toast_exported(self, filename: str):
        """File exported: told, its folder opened from the toast"""
        from ..toast import show_toast
        from .replay_files import show_in_folder

        show_toast(self._window, trm(f"Exported: <b>{os.path.basename(filename)}</b>"),
                   action_text=tr("Show in Folder"), action=partial(show_in_folder, filename))

    def write_history(self, filename: str, kind: str, decimal_point: str = "") -> bool:
        """Write session history of selected track (every track for All Tracks), CSV in system number format"""
        from ...userfile import atomic_path

        records = self.history_records()
        try:
            if kind == "json":
                tracks = {self.selected_stats_key} if self.selected_stats_key else set(self.stats_temp)
                stats = {track: self.stats_temp[track] for track in tracks if track in self.stats_temp}
                write_history_json(filename, history_document(records, stats, self.classes))
            else:
                decimal = decimal_point or QLocale.system().decimalPoint() or "."
                header = [tr(name) for name in HISTORY_COLUMNS]
                with atomic_path(filename) as temp_filename:  # file open in a spreadsheet: left whole
                    write_history_csv(temp_filename, records, header, [tr(name) for name in SESSION_NAMES], decimal)
        except OSError as error:
            logger.error("DRIVER STATS: unable to export %s: %s", filename, error)
            self.warning(trm(f"Unable to export: {error}"))
            return False
        return True

    # Friend's stats: exported session history of another driver, personal bests compared track by track
    def load_friend(self, filename: str, quiet: bool = False) -> bool:
        """Friend's file read now (tests), see load_friend_file"""
        if not filename:
            return False
        try:
            self._friend = load_friend(filename)
        except ValueError as error:
            if not quiet:
                self.warning(trm(f"Unable to read friend's stats: {error}"))
            return False
        return True

    def load_friend_file(self, filename: str, chosen: bool = False):
        """Friend's file read in background, compared once read (chosen by user: saved for next time, warned if
        unreadable)"""
        if not filename or self._released:
            return
        self._friend_file = filename if chosen else ""
        self.jobs.run("friend", partial(load_friend, filename), self.friend_loaded,
                      self.friend_failed if chosen else self.friend_skipped, key="friend")

    def friend_loaded(self, friend: dict):
        if self._released:
            return
        self._friend = friend
        if self._friend_file:
            self.save_viewer_config(friend_file=self._friend_file)
            self._friend_file = ""
        self.refresh_friend()

    def friend_failed(self, error: BaseException):
        self._friend_file = ""
        if isinstance(error, ValueError) and not self._released:
            self.warning(trm(f"Unable to read friend's stats: {error}"))
        else:
            self.friend_skipped(error)

    @staticmethod
    def friend_skipped(error: BaseException):
        """Friend's file of last time unreadable (moved): nothing compared"""
        if not isinstance(error, ValueError):
            logger.warning("DRIVER STATS: friend's stats not read", exc_info=(type(error), error, error.__traceback__))

    @Slot()
    def importFriend(self):
        """Compare with a friend's exported session history (JSON)"""
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        filename, _ = QFileDialog.getOpenFileName(self._window, tr("Compare With a Friend's Stats…"),
                                                  folder or os.path.expanduser("~"), "JSON (*.json)")
        if filename:
            self.load_friend_file(filename, chosen=True)

    @Slot()
    def clearFriend(self):
        self._friend = None
        self._friend_file = ""
        self.jobs.cancel("friend")  # file being read dropped
        self.save_viewer_config(friend_file="")
        self.refresh_friend()

    @Property(dict, notify=StatsCore.friendChanged)
    def friend(self) -> dict:
        """Friend's personal bests against own: name, rows (track, class, lap times, gap), summary"""
        return self._friend_view

    def refresh_friend(self):
        self._friend_view = self.friend_data()
        self.publish("friend", self._friend_view, self.friendChanged)

    def friend_data(self) -> dict:
        """Friend's personal bests against own on selected track (every track both drove for All Tracks)"""
        if self._friend is None:
            return {"visible": False}
        tracks = [self.selected_stats_key] if self.selected_stats_key else None
        rows = compare_friend(self.stats_temp, self.class_of, self._friend, tracks)
        shown = []
        for row in rows:
            gap = row["gap"]
            shown.append({
                "track": row["track"], "vehicleClass": row["class"],
                "mine": calc.sec2laptime_full(row["mine"]) if row["mine"] else "-",
                "friend": calc.sec2laptime_full(row["friend"]) if row["friend"] else "-",
                "gap": ("" if not (row["mine"] and row["friend"]) else number_text(0.0, 3) if abs(gap) < 0.0005
                        else signed(gap, 3)),
                "gapColor": "" if abs(gap) < 0.0005 else "loss" if gap > 0 else "gain",
            })
        compared = [row for row in rows if row["mine"] and row["friend"]]
        faster = sum(1 for row in compared if row["gap"] < 0)
        return {"visible": True, "name": self._friend["name"], "rows": shown,
                "summary": trm(f"Faster on {faster} of {len(compared)}") if compared else
                tr("No track & class driven by both of you here.")}

    @Slot(bool)
    def exportCsv(self, raw: bool = False):
        """Table shown (visible columns) to CSV file"""
        if not self._table:
            return
        name = strip_invalid_char(self.selected_stats_key or tr("All Tracks"))
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        default = os.path.join(folder or os.path.expanduser("~"), f"{name} - {tr('Driver Stats')}.csv")
        filename, _ = QFileDialog.getSaveFileName(self._window, tr("Export CSV…"), default, "CSV (*.csv)")
        if filename and self.write_csv(filename, raw=raw):
            self.toast_exported(filename)

    def write_csv(self, filename: str, decimal_point: str = "", raw: bool = False) -> bool:
        """Visible columns of table, number format of system locale (decimal comma & semicolon in French)

        Args:
            raw: values in base units without formatting (lap times in seconds, distance in meters...).
        """
        from ...userfile import atomic_path

        decimal = decimal_point or QLocale.system().decimalPoint() or "."
        delimiter = ";" if decimal == "," else ","
        keys = self.visible_keys()
        header = []
        for key in keys:
            label = self._labels.get(key, key)
            unit = RAW_UNITS.get("pb" if key.startswith("class:") else key, "") if raw else ""
            header.append(f"{label} ({unit})" if unit else label)
        try:
            # BOM: Excel reads UTF-8; file open in a spreadsheet left whole
            with atomic_path(filename) as temp_filename, open(temp_filename, "w", newline="",
                                                                encoding="utf-8-sig") as file:
                writer = csv.writer(file, delimiter=delimiter)
                writer.writerow(header)
                for _, cells in self._table:
                    if raw:
                        writer.writerow([csv_number(cells[key].raw if key in cells else None, decimal) for key in keys])
                    else:
                        writer.writerow([csv_text(cells[key].text, decimal) if key in cells else "" for key in keys])
        except OSError as error:
            logger.error("DRIVER STATS: unable to export %s: %s", filename, error)
            self.warning(trm(f"Unable to export: {error}"))
            return False
        return True

    # Personal best of selected vehicle shared: share code (chat), picture card
    def selected_best(self) -> tuple[str, float]:
        """Selected vehicle & its personal best (0 if none)"""
        vehicle = self._selected["vehicles"] if self.selected_stats_key else ""
        data = self.selected_stats_dict.get(vehicle, {}) if vehicle else {}
        return vehicle, valid_laptime(data.get("pb", 0)) if isinstance(data, dict) else 0.0

    def driver_name(self) -> str:
        if self.profile is not None and self.profile.name:
            return self.profile.name
        player = ranks.player
        return player.name if player is not None else ""

    def shared_best(self) -> SharedBest | None:
        """Personal best of selected vehicle as shared, None if none"""
        vehicle, best = self.selected_best()
        if not best:
            return None
        records = self.history_index.get((self.selected_stats_key, vehicle), [])
        when = best_lap_date(records, best)
        record = next((record for record in records if record.time == when), None) if when else None
        version = self.record_version(record) if record is not None else ""
        return SharedBest(self.selected_stats_key, vehicle, self.class_of(vehicle), best, when, version,
                          self.driver_name())

    @Slot()
    def copyPbCode(self):
        """Share code of selected vehicle personal best copied (paste it in a chat)"""
        shared = self.shared_best()
        if shared is None:
            self.warning(tr("No personal best for this car yet."))
            return
        QGuiApplication.clipboard().setText(pb_code.encode(shared, VERSION))
        self.toast(tr("Personal best code copied: paste it in a chat"))

    @Slot()
    def pastePbCode(self):
        """Personal best of a share code (clipboard, else asked) compared with yours, offered as goal"""
        shared = pb_code.decode(QGuiApplication.clipboard().text())
        if shared is not None:
            self.compare_shared(shared)
            return
        self.ask_pb_code("")

    def ask_pb_code(self, text: str):
        """Personal best code asked (in the page); none found: told, then asked again with the text"""
        def accept(typed: str) -> bool:
            found = pb_code.decode(typed)
            if found is None:
                dialogs.alert(self._window, tr("Error"), tr("No personal best code found in this text."), "warning",
                              lambda: self.ask_pb_code(typed))
                return True
            self.compare_shared(found)
            return True

        dialogs.ask_text(self._window, tr("Compare a Personal Best Code…"), tr("Personal best code (NP1:pb:…):"),
                         accept, text)

    def own_vehicle(self, shared: SharedBest) -> tuple[str, str, float]:
        """Your track key, vehicle & personal best of the class of a shared one ("", "", 0 if never driven)"""
        track = next((key for key in self.stats_temp if key.casefold() == shared.track.casefold()), "")
        vehicles = self.stats_temp.get(track, {}) if track else {}
        found_vehicle, found_best = "", 0.0
        for vehicle, data in vehicles.items() if isinstance(vehicles, dict) else ():
            same = vehicle == shared.vehicle or bool(
                shared.vehicle_class and self.class_of(str(vehicle)) == shared.vehicle_class)
            best = valid_laptime(data.get("pb", 0)) if isinstance(data, dict) else 0.0
            if same and (not found_vehicle or (best and (not found_best or best < found_best))):
                found_vehicle, found_best = str(vehicle), best
        return (track, found_vehicle, found_best) if found_vehicle else ("", "", 0.0)

    def compare_shared(self, shared: SharedBest):
        """Shared personal best against yours: told, offered as goal of your vehicle when faster"""
        who = shared.driver or tr("Shared personal best")
        when = f" ({format_date(shared.time)})" if shared.time else ""
        version = f" · v{shared.game_version}" if shared.game_version else ""
        lines = [f"<b>{html.escape(who)}</b>: {calc.sec2laptime_full(shared.laptime)}{when}",
                 f"{html.escape(shared.track)} · {html.escape(shared.vehicle)}{version}"]
        track, vehicle, best = self.own_vehicle(shared)
        if not vehicle:
            lines.append(tr("You have no lap time on this track & class yet."))
            dialogs.alert(self._window, tr("Personal Best Code"), "<br>".join(lines), "info")
            return
        if best:
            gap = best - shared.laptime
            lines.append(trm(f"You: {calc.sec2laptime_full(best)} ({html.escape(vehicle)}), gap {signed(gap, 3)} s"))
        if best and best <= shared.laptime + 0.0005:
            lines.append(tr("You are faster."))
            dialogs.alert(self._window, tr("Personal Best Code"), "<br>".join(lines), "info")
            return
        lines.append("")
        lines.append(trm(f"Set {calc.sec2laptime_full(shared.laptime)} as your goal for {html.escape(vehicle)}?"))
        def set_goal():
            self.set_goal(f"{track}|{vehicle}", shared.laptime)
            if track in self.stats_temp and track != self.selected_stats_key:
                self.selectTrack(track)
            self.selectRow(vehicle)

        self.ask("<br>".join(lines), set_goal, tr("Set Goal"))

    def card_data(self) -> CardData | None:
        """Personal best card of selected vehicle, None if no personal best"""
        vehicle, best = self.selected_best()
        if not best:
            return None
        reference = self.reference_of(vehicle)
        level = reference.level(best) if reference else -1
        detail = ""
        if reference is not None and reference.reference > 0:
            detail = trm(f"{number_text(reference.percent(best), 2)} % of community reference "
                         f"{calc.sec2laptime_full(reference.reference)}")
        shared = self.shared_best()
        logo = self.logos.track(self.selected_stats_key)
        return CardData(
            track=self.selected_stats_key, vehicle=vehicle, laptime=calc.sec2laptime_full(best),
            driver=self.driver_name(), date=format_date(shared.time) if shared is not None and shared.time else "",
            level=level_text(level) if level >= 0 else "", level_color=self.level_color(level) if level >= 0 else "",
            detail=detail, logo=QUrl(logo).toLocalFile() if logo else "", title=tr("Personal Best").upper())

    @Slot()
    def exportPbCard(self):
        """Picture of selected vehicle personal best saved (PNG)"""
        data = self.card_data()
        if data is None:
            self.warning(tr("No personal best for this car yet."))
            return
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        name = strip_invalid_char(f"{data.track} - {data.vehicle} - {tr('Personal Best')}")
        default = os.path.join(folder or os.path.expanduser("~"), f"{name}.png")
        filename, _ = QFileDialog.getSaveFileName(self._window, tr("Save Personal Best Card…"), default,
                                                  "PNG (*.png)")
        if not filename:
            return
        if not draw_card(data).save(filename, b"PNG"):
            self.warning(trm(f"Unable to export: {filename}"))
            return
        self.toast_exported(filename)

    @Slot()
    def copyPbCard(self):
        """Picture of selected vehicle personal best copied (paste it in a chat)"""
        data = self.card_data()
        if data is None:
            self.warning(tr("No personal best for this car yet."))
            return
        QGuiApplication.clipboard().setImage(draw_card(data))
        self.toast(tr("Personal best card copied: paste it in a chat"))

    def toast(self, text: str):
        from ..toast import show_toast

        show_toast(self._window, text)
