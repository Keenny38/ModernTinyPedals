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
Lap telemetry viewer state for QML page: laps, chart series, track map, G circle, corners, cursor values

Charts, map & G circle vertices go to VertexStore (drawn by GpuShape items),
everything else is exposed as properties of plain values (lists of dicts) & a lap list model.
"""

from __future__ import annotations

import bisect
import csv
import html
import logging
import os
import threading
import time
from typing import Any

from PySide6.QtCore import Property, QLocale, QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from ...i18n import tr, trm
from ...setting import cfg
from ...userfile.corner_analysis import (
    SPEED_HYSTERESIS,
    CornerComparison,
    compare_corners,
    lap_time_delta,
    straights_delta,
)
from ...userfile.lap_marks import load_marks, remove_mark, set_mark
from ...userfile.motec_import import import_ld_file
from ...userfile.motec_ld import export_lap
from ...userfile.telemetry_lap import (
    IMPORT_FOLDER,
    LapData,
    LapFile,
    best_laps,
    group_sessions,
    interpolate,
    is_valid_name,
    lap_number_of,
    lap_stem,
    lap_time_of,
    lap_timestamp_of,
    list_laps,
    list_tracks,
    load_lap,
    read_lap_info,
    theoretical_best,
)
from ...userfile.track_corners import TrackCorner, track_corners
from ...userfile.track_map import load_track_map_file
from .. import lap_viewer
from .._common import TextInputDialog
from ..lap_viewer import (
    CHANNEL_MAP,
    CHANNELS,
    DEFAULT_CHANNELS,
    LAP_COLORS,
    PERCENT_RANGES,
    TRACK_WIDTH,
    LapEntry,
    PlotLap,
    channel_title,
    corner_label,
    format_axis_time,
    format_axis_value,
    format_csv_number,
    format_laptime,
    lap_label,
    load_viewer_setting,
    save_viewer_setting,
    signed,
)
from . import lap_map
from .lines import VertexStore, band, dots, line_strip, segments, step_strip
from .models import DictListModel
from .trace_data import TraceData

logger = logging.getLogger(__name__)

COLOR_GAIN = "#22C55E"
COLOR_LOSS = "#EF4444"
LAP_ROLES = (
    "kind", "session", "path", "title", "time", "s1", "s2", "s3", "best1", "best2", "best3", "info", "note",
    "checked", "reference", "color", "dim", "fastest", "count",
)
LINE_WIDTH = 1.2  # half width of driving lines on map, pixels
ZOOMED_WIDTH = 2.2  # half width of zoomed part & colored line, pixels


class LapViewerBackend(QObject):
    """Lap telemetry viewer page state (QML context property "backend")"""

    tracksChanged = Signal()
    listChanged = Signal()  # best lap text, expanded sessions, hide unclean
    chartChanged = Signal()  # laps shown: panels, legend, maps, corners
    channelsChanged = Signal()
    statusChanged = Signal()
    revisionChanged = Signal()  # vertex store updated
    mapChanged = Signal()  # map color mode, options
    viewRestored = Signal(float, float)  # chart zoom to show again (laps reloaded after release)

    def __init__(self, parent: QWidget, folder: str):
        super().__init__(parent)
        self._window = parent
        self.folder = folder
        self.prefix = f"lap_viewer_{id(self)}|"  # vertex store keys of this page
        self.data = TraceData()
        self.entries: list[LapEntry] = []
        self.external: list[LapEntry] = []
        self.checked: set[str] = set()
        self.reference_key = ""
        self.lap_model = DictListModel(LAP_ROLES, self)
        self._tracks: list[str] = []
        self._track = ""
        self._expanded: list[str] = []
        self._best_text = ""
        self._status = ""
        self._warning = ""
        self._revision = 0
        self._panels: list[dict] = []
        self._overview: dict = {}
        self._legend: list[dict] = []
        self._map: dict = {}
        self._gcircle: dict = {}
        self._corners: list[dict] = []
        self._corner_marks: list[dict] = []
        self._corner_rows: list[CornerComparison] = []
        self._official: list[TrackCorner] = []  # official corner numbers (or names) of circuit
        self._official_numbered = True
        self._map_lines: list[tuple[lap_map.MapLine, PlotLap]] = []
        self._road = lap_map.MapLine([], [], [])  # circuit: track map file, else reference line
        self._g_points: list[tuple[list[float], list[float], list[float], PlotLap]] = []  # distance, lat, long
        self._map_view = (0.0, 0.0, 1.0)  # highlighted reference distances & map meters per pixel
        self._chart_view = (0.0, 0.0)  # chart axis range shown, kept while laps are released
        self._restore_view: tuple[float, float] | None = None
        self._released_view = (0.0, 0.0)
        self._speed_range = (0.0, 0.0)
        self._info_cache: dict[str, tuple[float, dict]] = {}
        self._lap_cache: dict[str, LapData | None] = {}
        self._cache_mtime: dict[str, float] = {}
        self._outline_cache: dict[str, list[tuple[float, float]]] = {}
        self._marks: dict[str, dict[str, dict]] = {}
        self._loader: threading.Thread | None = None
        self._loaded: dict[str, LapData | None] = {}
        self._load_timer = QTimer(self)
        self._load_timer.setInterval(30)
        self._load_timer.timeout.connect(self.check_background_load)
        self._released = False
        self._release_timer = QTimer(self)
        self._release_timer.setSingleShot(True)
        self._release_timer.setInterval(lap_viewer.RELEASE_DELAY)
        self._release_timer.timeout.connect(self.release_laps)
        setting = load_viewer_setting(folder)
        self._hide_unclean = bool(setting.get("hide_unclean_laps", False))
        self.data.set_time_axis(bool(setting.get("time_axis", False)))
        mode = setting.get("map_color_mode", "gain" if setting.get("map_time_gain") else "laps")
        self._map_mode = mode if mode in lap_map.MAP_MODES else "laps"
        self._map_follow = bool(setting.get("map_follow_zoom", True))
        self._map_braking = bool(setting.get("map_braking_points", True))
        saved = setting.get("corner_hysteresis", SPEED_HYSTERESIS)
        self._hysteresis = int(saved) if isinstance(saved, (int, float)) else int(SPEED_HYSTERESIS)
        columns = setting.get("channels", [])
        self.visible = [column for column in columns if column in CHANNEL_MAP] if isinstance(columns, list) else []
        self.visible = self.visible or list(DEFAULT_CHANNELS)

    def release(self):
        """Forget page vertices (page closed)"""
        VertexStore.remove_prefix(self.prefix)

    # Properties
    def _tracks_get(self) -> list[str]:
        return self._tracks

    def _track_get(self) -> str:
        return self._track

    def _track_set(self, track: str):
        if track != self._track:
            self.load_track(track)

    tracks = Property(list, _tracks_get, notify=tracksChanged)
    currentTrack = Property(str, _track_get, _track_set, notify=tracksChanged)

    @Property(QObject, constant=True)
    def laps(self) -> QObject:
        return self.lap_model

    @Property(list, notify=listChanged)
    def expanded(self) -> list[str]:
        return self._expanded

    @Property(str, notify=listChanged)
    def bestText(self) -> str:
        return self._best_text

    @Property(bool, notify=listChanged)
    def hideUnclean(self) -> bool:
        return self._hide_unclean

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(bool, notify=statusChanged)
    def loading(self) -> bool:
        return self._loader is not None

    @Property(int, notify=revisionChanged)
    def revision(self) -> int:
        return self._revision

    @Property(list, notify=chartChanged)
    def panels(self) -> list[dict]:
        return self._panels

    @Property(dict, notify=chartChanged)
    def overview(self) -> dict:
        """Speed of reference lap over whole lap, for zoom navigator"""
        return self._overview

    @Property(list, notify=chartChanged)
    def legend(self) -> list[dict]:
        return self._legend

    @Property(str, notify=chartChanged)
    def warning(self) -> str:
        return self._warning

    @Property(float, notify=chartChanged)
    def maxX(self) -> float:
        return self.data.max_x()

    @Property(bool, notify=chartChanged)
    def timeAxis(self) -> bool:
        return self.data.time_axis

    @Property(list, notify=chartChanged)
    def sectorLines(self) -> list[dict]:
        return [
            {"x": self.data.x_at_distance(distance), "label": f"S{index + 2}"}
            for index, distance in enumerate(self.data.sector_lines)
        ]

    @Property(list, notify=chartChanged)
    def cornerMarks(self) -> list[dict]:
        return self._corner_marks

    @Property(dict, notify=chartChanged)
    def trackMap(self) -> dict:
        return self._map

    @Property(dict, notify=chartChanged)
    def gCircle(self) -> dict:
        return self._gcircle

    @Property(list, notify=chartChanged)
    def corners(self) -> list[dict]:
        return self._corners

    @Property(int, notify=chartChanged)
    def hysteresis(self) -> int:
        return self._hysteresis

    @Property(str, notify=mapChanged)
    def mapMode(self) -> str:
        return self._map_mode

    @Property(bool, notify=mapChanged)
    def mapFollow(self) -> bool:
        return self._map_follow

    @Property(bool, notify=mapChanged)
    def mapBraking(self) -> bool:
        return self._map_braking

    @Property(dict, notify=mapChanged)
    def mapLegend(self) -> dict:
        """Color scale of current map mode: speed range in user unit"""
        if self._map_mode != "speed" or self._speed_range[1] <= self._speed_range[0]:
            return {}
        convert, unit = self.data.units["speed"]
        low, high = (convert(value) if convert else value for value in self._speed_range)
        return {"low": f"{low:.0f}", "high": f"{high:.0f}", "unit": unit,
                "colors": [color.name() for color in lap_map.SPEED_COLORS]}

    @Property(list, notify=channelsChanged)
    def channelMenu(self) -> list[dict]:
        """Every channel: column, title, group (per wheel channels), visible"""
        return [
            {"column": channel.column, "group": tr(channel.group) if channel.group else "",
             "title": channel.title[len(channel.group):].strip() if channel.group else tr(channel.title),
             "visible": channel.column in self.visible}
            for channel in CHANNELS
        ]

    def set_status(self, text: str):
        self._status = text
        self.statusChanged.emit()

    def bump_revision(self):
        self._revision += 1
        self.revisionChanged.emit()

    # Tracks & lap list
    @Slot()
    def refresh(self):
        self._tracks = list_tracks(self.folder)
        track = self._track if self._track in self._tracks else (self._tracks[0] if self._tracks else "")
        self.drop_changed_laps()
        self._marks.clear()
        self.load_track(track)
        if not self._tracks and not self.external:
            self.set_status(tr("No recorded lap. Enable the Recorder module, then drive a few laps."))

    def drop_changed_laps(self):
        """Forget loaded laps whose file changed or was removed (refresh)"""
        for path in list(self._lap_cache):
            try:
                changed = os.path.getmtime(path) != self._cache_mtime.get(path)
            except OSError:
                changed = True
            if changed:
                self._lap_cache.pop(path, None)
                self._cache_mtime.pop(path, None)

    def load_track(self, track: str):
        self._track = track
        self.tracksChanged.emit()
        laps = list_laps(self.folder, track) if track else []
        self.entries = [LapEntry(lap, self.lap_info(lap.path)) for lap in laps]
        # Laps shown last time on this track, else fastest lap compared with newest other lap
        saved = load_viewer_setting(self.folder).get("selections", {})
        saved = saved.get(track, {}) if isinstance(saved, dict) else {}
        paths = {lap.filename: lap.path for lap in laps}
        checked = {paths[name] for name in saved.get("checked", []) if name in paths}
        reference = paths.get(saved.get("reference", ""), "")
        if checked and reference in checked:
            self.reference_key = reference
        else:
            best = best_laps(laps, 1)
            self.reference_key = best[0].path if best else (laps[0].path if laps else "")
            checked = {self.reference_key} if self.reference_key else set()
            newest = next((lap.path for lap in laps if lap.valid and lap.path != self.reference_key), "")
            if newest:
                checked.add(newest)
        added = {entry.file.path for entry in self.external}
        self.checked = checked | (self.checked & added)
        self._expanded = []
        self.fill_list()
        self.load_laps()

    def lap_info(self, path: str) -> dict:
        """Lap info (first line of file), read again only if file changed"""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0
        cached = self._info_cache.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        info = read_lap_info(path)
        self._info_cache[path] = (mtime, info)
        return info

    def lap_marks(self, path: str) -> dict:
        """Kept state & note of lap"""
        folder, name = os.path.split(path)
        if folder not in self._marks:
            self._marks[folder] = load_marks(folder)
        return self._marks[folder].get(name, {})

    @staticmethod
    def entry_sectors(entry: LapEntry) -> list[float]:
        sectors = entry.info.get("sectors")
        if isinstance(sectors, list) and len(sectors) == 3 and all(isinstance(v, (int, float)) for v in sectors):
            return [float(value) for value in sectors]
        return []

    @staticmethod
    def entry_text(entry: LapEntry, session_vehicle: str = "") -> str:
        """Lap details not shown by its session header"""
        texts = []
        if not entry.file.valid:
            texts.append(tr("invalid"))
        kind = entry.info.get("kind", "")
        if kind == "out":
            texts.append(tr("out lap"))
        elif kind == "in":
            texts.append(tr("in lap"))
        if entry.external and entry.info.get("session"):
            texts.append(tr(str(entry.info["session"])))
        vehicle = str(entry.info.get("vehicle", ""))
        if vehicle and vehicle != session_vehicle:
            texts.append(vehicle)
        return ", ".join(texts)

    def all_entries(self) -> list[LapEntry]:
        return self.entries + self.external

    def fill_list(self):
        """Laps grouped by session (newest first), added files on top, sessions with shown laps expanded"""
        # Added files may come from other tracks: theoretical best & best sectors of current track only
        sectors = [self.entry_sectors(entry) for entry in self.entries if entry.file.valid]
        best_total, best_sectors = theoretical_best(sectors)
        entries = [
            entry for entry in self.entries
            if not self._hide_unclean or entry.file.path in self.checked or entry.file.path == self.reference_key
            or (entry.file.valid and entry.info.get("kind") not in ("out", "in"))
        ]
        groups: list[tuple[list[LapEntry], bool]] = [
            (group, False)
            for group in group_sessions(entries, lambda entry: entry.file.filename, lambda entry: entry.info)
        ]
        added: dict[str, list[LapEntry]] = {}  # added laps by folder (imported log, other track)
        for entry in self.external:
            added.setdefault(os.path.dirname(entry.file.path), []).append(entry)
        groups[:0] = [(group, True) for group in added.values()]
        rows: list[dict] = []
        expanded = []
        for index, (group, is_added) in enumerate(groups):
            header = self.session_row(group, is_added)
            rows.append(header)
            vehicle = str(group[0].info.get("vehicle", ""))
            fastest = min((entry for entry in group if entry.file.valid and entry.file.lap_time > 0),
                          key=lambda entry: entry.file.lap_time, default=None)
            for entry in group:
                rows.append(self.lap_row(header["session"], entry, best_sectors, vehicle, entry is fastest))
            if (index == 0 or header["session"] in self._expanded
                    or any(entry.file.path in self.checked or entry.file.path == self.reference_key
                           for entry in group)):
                expanded.append(header["session"])
        self.lap_model.reset(rows)
        self._expanded = expanded
        self._best_text = trm(f"Theoretical best: {format_laptime(best_total)}") if best_total > 0 else ""
        self.listChanged.emit()

    def session_row(self, group: list[LapEntry], is_added: bool) -> dict:
        """Session header: session & date, best lap, number of laps & vehicle"""
        first = group[0]
        if is_added:  # imported log or other folder
            folder = os.path.dirname(first.file.path)
            title = os.path.basename(folder)
            key = f"added {folder}"
        else:
            session = str(first.info.get("session", "")) or tr("Session")
            start = first.info.get("session_start")  # recorded, else when first lap started
            timestamp = start if isinstance(start, (int, float)) else (
                lap_timestamp_of(first.file.filename) - first.file.lap_time)
            date = time.strftime("%d/%m %H:%M", time.localtime(timestamp)) if timestamp > 0 else ""
            title = f"{tr(session)}  {date}".strip()
            key = f"{session} {first.file.filename[:19]}"
        best = min((entry.file.lap_time for entry in group if entry.file.valid and entry.file.lap_time > 0), default=0)
        details = []
        vehicle = str(first.info.get("vehicle", ""))
        if is_added:
            details.append(tr("added"))
        if vehicle:
            details.append(vehicle)
        return {
            "kind": "session", "session": key, "path": "", "title": title, "time": format_laptime(best),
            "s1": "", "s2": "", "s3": "", "best1": False, "best2": False, "best3": False,
            "info": ", ".join(details), "note": "", "count": len(group), "checked": False, "reference": False,
            "color": "", "dim": False, "fastest": False,
        }

    def lap_row(self, session: str, entry: LapEntry, best_sectors: list[float], vehicle: str,
                is_fastest: bool) -> dict:
        """Lap row: number, time, sectors (best ones flagged), info; invalid & out/in laps dimmed"""
        number = lap_number_of(entry.file.filename)
        sectors = self.entry_sectors(entry) or [0.0, 0.0, 0.0]
        bests = [
            value > 0 and bool(best_sectors) and abs(value - best) < 0.0005 and entry.file.valid and not entry.external
            for value, best in zip(sectors, best_sectors or [0.0, 0.0, 0.0])
        ]
        info = self.entry_text(entry, vehicle)
        note = ""
        if not entry.external:
            mark = self.lap_marks(entry.file.path)
            note = str(mark.get("note", ""))
            if mark.get("kept"):
                info = ", ".join(filter(None, [info, tr("kept")]))
        return {
            "kind": "lap", "session": session, "path": entry.file.path,
            "title": trm(f"Lap {number}") if number else lap_stem(entry.file.filename),
            "time": format_laptime(entry.file.lap_time),
            "s1": format_laptime(sectors[0]), "s2": format_laptime(sectors[1]), "s3": format_laptime(sectors[2]),
            "best1": bests[0], "best2": bests[1], "best3": bests[2], "info": info, "note": note,
            "checked": entry.file.path in self.checked, "reference": entry.file.path == self.reference_key,
            "color": "", "dim": not entry.file.valid or entry.info.get("kind") in ("out", "in"),
            "fastest": is_fastest, "count": 0,
        }

    def lap_rows(self) -> list[dict]:
        return [row for row in self.lap_model.rows if row["kind"] == "lap"]

    def ordered_checked(self) -> list[str]:
        """Checked laps in list order"""
        return [row["path"] for row in self.lap_rows() if row["path"] in self.checked]

    @Slot(str)
    def toggleSession(self, key: str):
        if key in self._expanded:
            self._expanded = [session for session in self._expanded if session != key]
        else:
            self._expanded = [*self._expanded, key]
        self.listChanged.emit()

    @Slot(str)
    def toggleLap(self, path: str):
        self.setLapChecked(path, path not in self.checked)

    @Slot(str, bool)
    def setLapChecked(self, path: str, checked: bool):
        if checked:
            self.checked.add(path)
        else:
            self.checked.discard(path)
        self.load_laps()

    @Slot(str)
    def setReference(self, path: str):
        if not path:  # session header
            return
        self.reference_key = path
        self.checked.add(path)
        self.load_laps()

    @Slot(bool)
    def setHideUnclean(self, enabled: bool):
        self._hide_unclean = enabled
        save_viewer_setting(self.folder, hide_unclean_laps=enabled)
        self.fill_list()
        self.update_list_state(self.data.laps)

    def save_selection(self, paths: list[str]):
        """Remember checked laps & reference of current track"""
        track_paths = {entry.file.path for entry in self.entries}
        names = sorted(os.path.basename(path) for path in paths if path in track_paths)
        if not self._track or not names:
            return
        selections = load_viewer_setting(self.folder).get("selections", {})
        if not isinstance(selections, dict):
            selections = {}
        reference = os.path.basename(self.reference_key) if self.reference_key in track_paths else ""
        selection = {"checked": names, "reference": reference}
        if selections.get(self._track) != selection:
            selections[self._track] = selection
            save_viewer_setting(self.folder, selections=selections)

    # Lap actions (lap list context menu)
    @Slot(str, result=dict)
    def lapActions(self, path: str) -> dict:
        """Actions available for lap: recorded laps of track can be kept, noted & deleted"""
        recorded = path in {entry.file.path for entry in self.entries}
        return {"recorded": recorded, "kept": bool(self.lap_marks(path).get("kept")) if recorded else False}

    @Slot(str, bool)
    def keepLap(self, path: str, keep: bool):
        """Kept lap is never removed by recorder (oldest laps over limit are)"""
        set_mark(path, kept=keep)
        self.marks_changed(path)

    def marks_changed(self, path: str):
        self._marks.pop(os.path.dirname(path), None)
        self.fill_list()
        self.update_list_state(self.data.laps)

    @Slot(str)
    def editNote(self, path: str):
        """Free text note of lap, shown in lap list"""
        def saving(text: str) -> bool:
            set_mark(path, note=text)
            self.marks_changed(path)
            return True

        TextInputDialog(self._window, tr("Lap Note"), tr("Note for this lap (empty to remove):"), saving,
                        str(self.lap_marks(path).get("note", ""))).show()

    @Slot(str)
    def deleteLap(self, path: str):
        """Delete recorded lap file after confirmation"""
        message = trm(f"Delete <b>{html.escape(os.path.basename(path))}</b> permanently?")
        confirm = QMessageBox.question(
            self._window, tr("Delete Lap"), message,
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            defaultButton=QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            os.remove(path)
        except OSError as error:
            logger.error("LAP VIEWER: unable to delete %s: %s", path, error)
            self.set_status(trm(f"Unable to delete lap: {error}"))
            return
        remove_mark(path)
        self._marks.pop(os.path.dirname(path), None)
        self._lap_cache.pop(path, None)
        self.entries = [entry for entry in self.entries if entry.file.path != path]
        self.checked.discard(path)
        if self.reference_key == path:
            self.reference_key = ""
        self.fill_list()
        self.load_laps()

    # Added laps: other folders, MoTeC logs, imported laps library
    @Slot()
    def addFiles(self):
        filenames, _ = QFileDialog.getOpenFileNames(
            self._window, tr("Add File..."), self.folder,
            f"{tr('Laps')} (*.csv *.csv.gz *.ld);;Modern Tiny Pedals Lap (*.csv *.csv.gz);;MoTeC i2 (*.ld)")
        paths: list[str] = []
        imported: list[str] = []
        for filename in filenames:
            if filename.lower().endswith(".ld"):  # MoTeC log: complete laps converted to lap files
                laps = [os.path.normpath(path) for path in self.import_motec(filename)]
                imported.extend(laps)
                paths.extend(laps)
            else:
                paths.append(filename)
        self.add_external(paths, imported)

    def import_motec(self, filename: str) -> list[str]:
        """Import complete laps of MoTeC .ld file, returns lap file paths"""
        try:
            paths = import_ld_file(filename, os.path.join(self.folder, IMPORT_FOLDER))
        except (OSError, ValueError) as error:
            logger.error("LAP VIEWER: unable to import %s: %s", filename, error)
            self.set_status(trm(f"Unable to import MoTeC file: {error}"))
            return []
        if not paths:
            self.set_status(trm(f"No complete lap in: {os.path.basename(filename)}"))
        return paths

    def add_external(self, lap_paths: list[str], reference_from: list[str] | None = None):
        """Show laps from other folders, fastest of reference_from laps set as reference"""
        known = {entry.file.path for entry in self.all_entries()}
        added = []
        for lap_path in lap_paths:
            path = os.path.normpath(lap_path)
            if path in known or path in added:
                continue
            name = os.path.basename(path)
            self.external.append(LapEntry(
                LapFile(name, path, is_valid_name(name), lap_time_of(name)), self.lap_info(path), external=True))
            added.append(path)
        self.checked.update(added)
        if reference_from:  # compare own laps with fastest imported lap
            self.reference_key = os.path.normpath(min(
                reference_from, key=lambda path: lap_time_of(os.path.basename(path)) or float("inf")))
        if added or reference_from:
            self.fill_list()
            self.load_laps()

    @Slot()
    def openLibrary(self):
        from ..lap_library import LapLibrary

        LapLibrary(self._window, self.folder, self.add_from_library, self.library_changed).show()

    def add_from_library(self, paths: list[str]):
        """Laps picked in library shown & checked, fastest one as reference"""
        self.add_external(paths, paths)

    def library_changed(self, moved: dict[str, str]):
        """Imported laps renamed (new path) or deleted (empty path) in library"""
        moved = {os.path.normpath(old): os.path.normpath(new) if new else "" for old, new in moved.items()}
        if not any(entry.file.path in moved for entry in self.external):
            return
        self.checked = {moved.get(path, path) for path in self.checked} - {""}
        external = []
        for entry in self.external:
            path = moved.get(entry.file.path, entry.file.path)
            if path:
                external.append(entry._replace(file=entry.file._replace(path=path)))
            self._lap_cache.pop(entry.file.path, None)
        self.external = external
        if self.reference_key in moved:
            self.reference_key = moved[self.reference_key]
        self.fill_list()
        self.load_laps()

    # Export
    @Slot(str)
    def exportMotec(self, path: str = ""):
        """Export lap (reference lap by default) to MoTeC .ld file"""
        path = path or self.reference_key
        lap = self.read_lap(path) if path else None
        if lap is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self._window, tr("Export MoTeC..."), lap_stem(path) + ".ld", "MoTeC i2 (*.ld)")
        if filename and self.export_file(path, lap, filename):
            self.set_status(trm(f"Exported: {os.path.basename(filename)}"))

    @Slot(bool)
    def exportMotecMany(self, whole_track: bool):
        """Export displayed laps, or every lap of track, to folder"""
        paths = [entry.file.path for entry in self.entries] if whole_track else self.ordered_checked()
        if not paths:
            return
        folder = QFileDialog.getExistingDirectory(self._window, tr("Export MoTeC..."), self.folder)
        if folder:
            self.export_many(paths, folder)

    def export_many(self, paths: list[str], folder: str) -> int:
        count = 0
        for path in paths:
            lap = self._lap_cache.get(path)
            if lap is None:  # not kept in cache: exporting every lap of track would fill memory
                try:
                    lap = load_lap(path)
                except (OSError, ValueError) as error:
                    logger.error("LAP VIEWER: unable to load %s: %s", path, error)
                    continue
            target = os.path.join(folder, os.path.basename(lap_stem(path)) + ".ld")
            if self.export_file(path, lap, target):
                count += 1
        self.set_status(trm(f"Exported <b>{count}</b> file(s) to: {folder}"))
        return count

    def export_file(self, path: str, lap: LapData, filename: str) -> bool:
        track = os.path.basename(os.path.dirname(path)).split(" - ")[0]
        try:
            export_lap(lap, filename, venue=track, timestamp=os.path.getmtime(path))
        except (OSError, ValueError) as error:
            logger.error("LAP VIEWER: unable to export %s: %s", filename, error)
            self.set_status(trm(f"Unable to export lap: {error}"))
            return False
        return True

    @Slot()
    def exportCsv(self):
        """Displayed charts of displayed laps to CSV, every meter"""
        if not self.data.laps:
            self.set_status(tr("Check laps to export first."))
            return
        default = os.path.join(self.folder, f"{self._track or 'laps'}.csv")
        filename, _ = QFileDialog.getSaveFileName(self._window, tr("Export CSV..."), default, "CSV (*.csv)")
        if filename and self.write_csv(filename):
            self.set_status(trm(f"Exported: {html.escape(os.path.basename(filename))}"))

    def write_csv(self, filename: str, decimal_point: str = "") -> bool:
        """Distance, then each displayed channel of each displayed lap, resampled every meter

        Number format follows system locale (decimal comma & semicolon separator in French), for Excel.
        """
        decimal = decimal_point or QLocale.system().decimalPoint() or "."
        delimiter = ";" if decimal == "," else ","
        length = max((lap.data.distance[-1] for lap in self.data.laps if len(lap.data)), default=0.0)
        grid = [float(meter) for meter in range(int(length) + 1)]
        header = [f"{tr('Distance')} (m)"]
        columns: list[list[str]] = []
        for lap in self.data.laps:
            for column in self.visible:
                channel = CHANNEL_MAP[column]
                unit = self.data.unit_of(channel)
                header.append(f"{lap.label} - {channel_title(channel)}" + (f" ({unit})" if unit else ""))
                xs, ys = self.data.series(channel, lap, time_axis=False)
                columns.append([
                    format_csv_number(interpolate(xs, ys, distance), decimal)
                    if xs and xs[0] <= distance <= xs[-1] else ""
                    for distance in grid
                ])
        try:
            with open(filename, "w", newline="", encoding="utf-8-sig") as file:  # BOM: Excel reads UTF-8
                writer = csv.writer(file, delimiter=delimiter)
                writer.writerow(header)
                for index, distance in enumerate(grid):
                    writer.writerow([format_csv_number(distance, decimal), *(column[index] for column in columns)])
        except OSError as error:
            logger.error("LAP VIEWER: unable to export %s: %s", filename, error)
            self.set_status(trm(f"Unable to export lap: {error}"))
            return False
        return True

    # Lap loading
    def read_lap(self, path: str) -> LapData | None:
        if not path:
            return None
        if path in self._lap_cache:
            self._lap_cache[path] = self._lap_cache.pop(path)  # most recently used last
            return self._lap_cache[path]
        try:
            lap = load_lap(path)
        except (OSError, ValueError) as error:
            logger.error("LAP VIEWER: unable to load %s: %s", path, error)
            self.set_status(trm(f"Unable to load lap: {error}"))
            lap = None
        self.store_lap(path, lap)
        return lap

    def store_lap(self, path: str, lap: LapData | None):
        """Keep loaded lap, oldest laps forgotten over cache size (a lap takes several MB in memory)"""
        self._lap_cache[path] = lap
        try:
            self._cache_mtime[path] = os.path.getmtime(path)
        except OSError:
            self._cache_mtime.pop(path, None)
        limit = max(lap_viewer.LAP_CACHE_SIZE, len(self.checked))
        while len(self._lap_cache) > limit:
            oldest = next(iter(self._lap_cache))
            self._lap_cache.pop(oldest)
            self._cache_mtime.pop(oldest, None)

    def load_in_background(self, paths: list[str]):
        """Read laps in a thread, charts updated once all are loaded (page stays responsive)"""
        if self._loader is not None:
            return  # current selection shown once loaded (check_background_load)
        results: dict[str, LapData | None] = {}

        def loading():
            for path in paths:
                try:
                    results[path] = load_lap(path)
                except (OSError, ValueError) as error:
                    logger.error("LAP VIEWER: unable to load %s: %s", path, error)
                    results[path] = None

        self._loaded = results
        self._loader = threading.Thread(target=loading, daemon=True, name="Lap viewer loading")
        self._loader.start()
        self._load_timer.start()
        self.set_status(trm(f"Loading {len(paths)} laps..."))

    @Slot()
    def check_background_load(self):
        """Background loading finished: laps kept, charts updated"""
        if self._loader is None or self._loader.is_alive():
            return
        self._load_timer.stop()
        self._loader = None
        for path, lap in self._loaded.items():
            self.store_lap(path, lap)
        self._loaded = {}
        self.set_status("")
        self.load_laps()

    def is_loading(self) -> bool:
        return self._loader is not None

    def load_laps(self):
        paths = self.ordered_checked()
        if paths and self.reference_key not in paths:
            self.reference_key = paths[0]
        ordered = sorted(paths, key=lambda path: path != self.reference_key)  # reference first
        missing = [path for path in ordered if path not in self._lap_cache]
        if self._loader is not None or len(missing) >= lap_viewer.BACKGROUND_LOAD_COUNT:
            self.update_list_state([])
            self.load_in_background(missing)
            return
        self.save_selection(paths)
        entries = {entry.file.path: entry for entry in self.all_entries()}
        laps: list[PlotLap] = []
        for path in ordered:
            lap_data = self.read_lap(path)
            if lap_data is not None:
                laps.append(PlotLap(path, self.entry_label(entries.get(path), path), lap_data,
                                    LAP_COLORS[len(laps) % len(LAP_COLORS)]))
        self.data.set_laps(laps, self.reference_key)
        self.update_list_state(laps)
        vehicles = sorted({str(lap.data.meta.get("vehicle")) for lap in laps if lap.data.meta.get("vehicle")})
        self._warning = trm(f"Laps from different vehicles: {', '.join(vehicles)}") if len(vehicles) > 1 else ""
        self.rebuild_chart()
        if self._restore_view is not None:
            self.viewRestored.emit(*self._restore_view)
            self._restore_view = None

    @staticmethod
    def entry_label(entry: LapEntry | None, path: str) -> str:
        """Lap name in legend: "Lap 12 · 1:11.525 · Race 03/10", or "log: Lap 3 · 2:18.200" """
        label = lap_label(os.path.basename(path))
        if entry is None or entry.external:
            return f"{os.path.basename(os.path.dirname(path))}: {label}"
        session = str(entry.info.get("session", ""))
        timestamp = lap_timestamp_of(entry.file.filename)
        date = time.strftime("%d/%m", time.localtime(timestamp)) if timestamp > 0 else ""
        where = " ".join(filter(None, [tr(session) if session else "", date]))
        return f"{label} · {where}" if where else label

    def update_list_state(self, laps: list[PlotLap]):
        """Check marks, lap colors & reference in lap list (in place: list keeps scroll position)"""
        colors = {lap.key: lap.color.name() for lap in laps}
        self.lap_model.update_rows(lambda row: {
            "checked": row["path"] in self.checked,
            "reference": bool(row["path"]) and row["path"] == self.reference_key,
            "color": colors.get(row["path"], ""),
        })

    # Memory release while page is in background
    def page_hidden(self):
        self._release_timer.start()

    def page_shown(self):
        self._release_timer.stop()
        if self._released:  # same laps & zoom as before
            self._released = False
            view = self._released_view
            self._restore_view = view if view[1] > view[0] else None
            self.load_laps()

    @Slot()
    def release_laps(self):
        """Free memory of loaded laps (several MB each) while page is hidden, see page_shown"""
        if self._window.isVisible() or self._released or self._loader is not None:
            return
        self._released_view = self._chart_view
        self._lap_cache.clear()
        self._cache_mtime.clear()
        self.data.set_laps([])
        self.rebuild_chart()
        self._released = True
        logger.info("LAP VIEWER: loaded laps released while hidden")

    @Slot(float, float)
    def setChartView(self, start: float, end: float):
        """Chart zoom (kept to show same part after laps are reloaded)"""
        self._chart_view = (start, end)

    # Charts
    def series_key(self, lap: PlotLap, column: str) -> str:
        return f"{self.prefix}{lap.key}|{column}|{int(self.data.time_axis)}"

    def rebuild_chart(self):
        """Vertices & properties of every view from displayed laps"""
        VertexStore.remove_prefix(self.prefix)
        self._legend = [
            {"label": lap_label(os.path.basename(lap.key)), "full": lap.label, "color": lap.color.name(),
             "reference": lap is self.data.reference}
            for lap in self.data.laps
        ]
        self.build_panels()
        self.build_overview()
        self.build_official()
        self.build_corners()
        self.build_map()
        self.build_gcircle()
        self.bump_revision()
        self.chartChanged.emit()
        self.mapChanged.emit()

    def build_panels(self):
        panels = []
        for column in self.visible:
            channel = CHANNEL_MAP[column]
            low, high = self.data.value_range(channel)
            series = []
            for lap in self.data.laps:
                key = self.series_key(lap, column)
                if not VertexStore.has(key):
                    xs, ys = self.data.series(channel, lap)
                    VertexStore.set(key, step_strip(xs, ys) if column == "gear" else line_strip(xs, ys))
                series.append({"key": key, "color": lap.color.name()})
            span = high - low
            panels.append({
                "column": column, "title": channel_title(channel), "unit": self.data.unit_of(channel),
                "weight": channel.weight, "low": low, "high": high,
                "lowText": format_axis_value(channel, low, span), "highText": format_axis_value(channel, high, span),
                "zero": low < 0 < high, "percent": channel.fixed_range in PERCENT_RANGES, "series": series,
            })
        self._panels = panels

    def build_overview(self):
        reference = self.data.reference
        if reference is None or "speed_kph" not in reference.data.columns:
            self._overview = {}
            return
        key = self.series_key(reference, "speed_kph") + "|overview"
        xs, ys = self.data.series(CHANNEL_MAP["speed_kph"], reference)
        VertexStore.set(key, line_strip(xs, ys))
        low, high = min(ys, default=0.0), max(ys, default=1.0)
        self._overview = {"key": key, "low": low, "high": high if high > low else low + 1}

    @Slot(str, bool)
    def setChannelVisible(self, column: str, visible: bool):
        if visible and column not in self.visible:
            self.visible.append(column)  # added at bottom, can be moved by dragging its name
        elif not visible and column in self.visible:
            self.visible.remove(column)
        self.channels_updated()

    @Slot(int, int)
    def moveChannel(self, source: int, target: int):
        if source != target and 0 <= source < len(self.visible) and 0 <= target < len(self.visible):
            self.visible.insert(target, self.visible.pop(source))
            self.channels_updated()

    @Slot()
    def resetChannels(self):
        self.visible = list(DEFAULT_CHANNELS)
        self.channels_updated()

    def channels_updated(self):
        save_viewer_setting(self.folder, channels=self.visible)
        self.build_panels()
        self.bump_revision()
        self.channelsChanged.emit()
        self.chartChanged.emit()

    @Slot(bool)
    def setTimeAxis(self, enabled: bool):
        """Lap time or distance horizontal axis, same part of lap kept in view"""
        if enabled == self.data.time_axis:
            return
        start, end = self._chart_view
        zoomed = end > start and end - start < self.data.max_x() - 1
        if zoomed:
            start, end = self.data.distance_at_x(start), self.data.distance_at_x(end)
        self.data.set_time_axis(enabled)
        save_viewer_setting(self.folder, time_axis=enabled)
        self.build_panels()
        self.build_overview()
        self.build_corner_marks()
        self.bump_revision()
        self.chartChanged.emit()
        if zoomed:
            self.viewRestored.emit(self.data.x_at_distance(start), self.data.x_at_distance(end))

    @Slot(float, result=float)
    def distanceAt(self, x: float) -> float:
        """Reference lap distance at axis position"""
        return self.data.distance_at_x(x)

    @Slot(float, result=float)
    def xAtDistance(self, distance: float) -> float:
        return self.data.x_at_distance(distance)

    @Slot(float, result=str)
    def cursorTitle(self, x: float) -> str:
        distance = self.data.distance_at_x(x)
        return f"{format_axis_time(x)} · {distance:.0f} m" if self.data.time_axis else f"{distance:.0f} m"

    @Slot(float, result=list)
    def cursorValues(self, x: float) -> list[list[dict]]:
        """Value of each lap at axis position, for each panel"""
        return [
            [{"text": text, "color": lap.color.name()} for lap, text in self.data.values_at(CHANNEL_MAP[column], x)]
            for column in self.visible
        ]

    # Corners
    def build_corners(self):
        """Corner by corner comparison of first compared lap with reference lap

        Time: positive = compared lap slower. Braking: positive = brakes later.
        Full throttle: negative = full throttle earlier.
        """
        reference = self.data.reference.data if self.data.reference else None
        compared = self.data.compared()
        other = compared[0].data if compared else None
        self._corner_rows = compare_corners(reference, other, self._hysteresis) if reference is not None else []
        convert = self.data.units["speed"][0]

        def speed(value: float) -> float:
            return convert(value) if convert is not None else value

        def judged(delta: float) -> str:
            return COLOR_LOSS if delta > 0.005 else COLOR_GAIN if delta < -0.005 else ""

        def more_is_worse(ref_value: float, other_value: float) -> str:
            if other_value - ref_value >= 0.1:
                return COLOR_LOSS
            if ref_value - other_value >= 0.1:
                return COLOR_GAIN
            return ""

        rows = []
        for index, row in enumerate(self._corner_rows):
            ref, comp = row.reference, row.compared
            item: dict[str, Any] = {
                "index": index, "label": self.row_label(row), "apex": f"{row.corner.apex:.0f} m",
                "kind": "corner",
            }
            if comp is None:  # reference lap values only
                item.update({
                    "time": f"{ref.time:.2f} s", "timeColor": "", "bar": 0.0, "speed": f"{speed(ref.min_speed):.0f}",
                    "speedColor": "", "brake": f"{ref.brake_point:.0f} m" if ref.brake_point >= 0 else "—",
                    "throttle": f"{ref.throttle_point:.0f} m" if ref.throttle_point >= 0 else "—",
                    "trail": f"{ref.trail_braking:.1f} s", "coast": f"{ref.coasting:.1f} s",
                    "overlap": f"{ref.overlap:.1f} s", "coastColor": "", "overlapColor": "",
                })
            else:
                delta = comp.time - ref.time
                speed_delta = speed(comp.min_speed) - speed(ref.min_speed)
                item.update({
                    "time": signed(delta, 2), "timeColor": judged(delta), "bar": delta,
                    "speed": f"{speed(ref.min_speed):.0f} / {speed(comp.min_speed):.0f}",
                    "speedColor": COLOR_GAIN if speed_delta >= 1 else COLOR_LOSS if speed_delta <= -1 else "",
                    "brake": signed(comp.brake_point - ref.brake_point, 0, " m")
                    if ref.brake_point >= 0 and comp.brake_point >= 0 else "—",
                    "throttle": signed(comp.throttle_point - ref.throttle_point, 0, " m")
                    if ref.throttle_point >= 0 and comp.throttle_point >= 0 else "—",
                    # Driving: trail braking (no judgement), coasting & overlap (more = time lost)
                    "trail": f"{ref.trail_braking:.1f} / {comp.trail_braking:.1f} s",
                    "coast": f"{ref.coasting:.1f} / {comp.coasting:.1f} s",
                    "overlap": f"{ref.overlap:.1f} / {comp.overlap:.1f} s",
                    "coastColor": more_is_worse(ref.coasting, comp.coasting),
                    "overlapColor": more_is_worse(ref.overlap, comp.overlap),
                })
            rows.append(item)
        if reference is not None and other is not None and self._corner_rows:  # corners + straights = lap delta
            for text, kind, delta in ((tr("Straights"), "sum", straights_delta(self._corner_rows, reference, other)),
                                      (tr("Total"), "total", lap_time_delta(reference, other))):
                rows.append({"index": -1, "label": text, "apex": "", "kind": kind, "time": signed(delta, 2),
                             "timeColor": judged(delta), "bar": delta})
        self._corners = rows
        self.build_corner_marks()

    def build_corner_marks(self):
        """Corner numbers on charts: official corners of circuit, else corners found on reference lap"""
        if self._official:
            self._corner_marks = [
                {"x": self.data.x_at_distance(corner.distance), "label": self.official_text(corner.label),
                 "distance": corner.distance}
                for corner in self._official
            ]
            return
        self._corner_marks = [
            {"x": self.data.x_at_distance(row.corner.apex), "label": corner_label(row.corner.number),
             "distance": row.corner.apex}
            for row in self._corner_rows
        ]

    # Official corners
    def track_name(self) -> str:
        """Track of displayed laps, from lap info or older lap files folder ("<track> - <class>")"""
        laps = self.data.laps
        if not laps:
            return ""
        track = str(laps[0].data.meta.get("track", ""))
        return track or os.path.basename(os.path.dirname(laps[0].key)).rsplit(" - ", 1)[0]

    def build_official(self):
        """Official corners of circuit placed on reference line (or track map file)"""
        self._official, self._official_numbered = [], True
        reference = self.data.reference
        if reference is None:
            return
        line = lap_map.map_line(reference.data)
        if line is not None:
            distances, xs, ys = line.distances, line.xs, line.ys
        else:  # positions not recorded (imported log): track map file
            coords, dists, _ = load_track_map_file(cfg.path.track_map, self.track_name())
            if not coords or not dists:
                return
            nodes = sorted(zip((float(distance) for distance, _ in dists), coords))
            distances = [distance for distance, _ in nodes]
            xs = [float(coord[0]) for _, coord in nodes]
            ys = [float(coord[1]) for _, coord in nodes]
        self._official, self._official_numbered = track_corners(self.track_name(), distances, xs, ys)

    def official_text(self, label: str) -> str:
        """Official corner shown: "T5" ("V5" in French), or translated name"""
        return trm(f"T{label}") if self._official_numbered else tr(label)

    def official_in(self, row: CornerComparison) -> list[TrackCorner]:
        """Official corners inside corner found on reference lap"""
        return [corner for corner in self._official if row.corner.start <= corner.distance <= row.corner.end]

    def row_label(self, row: CornerComparison) -> str:
        """Corner found on reference lap named after official corners it covers: "T5", "T5-6" """
        if not self._official:
            return corner_label(row.corner.number)
        inside = self.official_in(row)
        if not inside:
            nearest = min(self._official, key=lambda corner: abs(corner.distance - row.corner.apex))
            if abs(nearest.distance - row.corner.apex) > 200:
                return "—"
            inside = [nearest]
        if len(inside) == 1:
            return self.official_text(inside[0].label)
        if self._official_numbered:
            return trm(f"T{inside[0].label}-{inside[-1].label}")
        return " / ".join(tr(corner.label) for corner in inside)

    @Slot(int, result=list)
    def cornerRange(self, index: int) -> list[float]:
        """Axis range of corner (zoom on it)"""
        if not 0 <= index < len(self._corner_rows):
            return []
        corner = self._corner_rows[index].corner
        return [self.data.x_at_distance(corner.start), self.data.x_at_distance(corner.end)]

    @Slot(int)
    def setHysteresis(self, value: int):
        if value != self._hysteresis:
            self._hysteresis = value
            save_viewer_setting(self.folder, corner_hysteresis=value)
            self.build_corners()
            self._map["corners"] = self.map_corner_points()
            self.chartChanged.emit()

    # Track map
    def track_outline(self) -> list[tuple[float, float]]:
        """Circuit coordinates from track map file (recorded by Mapping module), empty if none"""
        laps = self.data.laps
        if not laps:
            return []
        track = str(laps[0].data.meta.get("track", ""))
        if not track:  # older lap files: "<track> - <class>" folder
            track = os.path.basename(os.path.dirname(laps[0].key)).rsplit(" - ", 1)[0]
        if track not in self._outline_cache:
            coords, _, _ = load_track_map_file(cfg.path.track_map, track)
            self._outline_cache[track] = [(float(x), float(y)) for x, y in coords] if coords else []
        return self._outline_cache[track]

    def build_map(self):
        """Circuit, driving lines, start & sector marks, corners, braking points of displayed laps"""
        self._map_lines = []
        for lap in self.data.laps:
            line = lap_map.map_line(lap.data)
            if line is not None:
                self._map_lines.append((line, lap))
        outline = self.track_outline()
        if outline:
            road = lap_map.MapLine(list(range(len(outline))), [x for x, _ in outline], [y for _, y in outline])
        elif self._map_lines:
            road = self._map_lines[0][0]
        else:
            self._map = {}
            return
        xs = road.xs + [x for line, _ in self._map_lines for x in line.xs]
        ys = road.ys + [y for line, _ in self._map_lines for y in line.ys]
        self._road = road
        self._map = {
            "road": self.prefix + "map|road", "edge": self.prefix + "map|edge", "colored": self.prefix + "map|colored",
            "marks": self.prefix + "map|marks",
            "lines": [
                {"key": f"{self.prefix}map|{lap.key}", "highlight": f"{self.prefix}map|{lap.key}|zoom",
                 "color": lap.color.name(), "reference": lap is self.data.reference}
                for _, lap in self._map_lines
            ],
            "minX": min(xs), "minY": min(ys), "maxX": max(xs), "maxY": max(ys),
            "corners": self.map_corner_points(),
            "braking": self.map_braking_points(),
            "start": self.start_mark(),
        }
        self.build_map_bands()

    def start_mark(self) -> list[float]:
        """Start line across circuit (reference line start), x0 y0 x1 y1"""
        if not self._map_lines:
            road = self._road
            if len(road.xs) < 2:
                return []
            dx, dy = road.xs[1] - road.xs[0], road.ys[1] - road.ys[0]
            length = max((dx * dx + dy * dy) ** 0.5, 1e-6)
            nx, ny = -dy / length * TRACK_WIDTH, dx / length * TRACK_WIDTH
            return [road.xs[0] - nx, road.ys[0] - ny, road.xs[0] + nx, road.ys[0] + ny]
        line = self._map_lines[0][0]
        return list(lap_map.cross_mark(line, line.distances[0] + 1, TRACK_WIDTH))

    def map_corner_points(self) -> list[dict]:
        """Corner labels at apex of reference line, with time lost or gained by first compared lap

        Official corners of circuit when known (every corner, even flat out ones), else corners found
        on reference lap. Each label zooms charts on its corner (start & end distances).
        """
        if self._official:
            return self.official_points()
        if not self._map_lines or not self._corner_rows:
            return []
        line = self._map_lines[0][0]
        points = []
        for index, row in enumerate(self._corner_rows):
            x, y = lap_map.point_at(line, row.corner.apex)
            delta = row.time_delta
            points.append({
                "x": x, "y": y, "label": corner_label(row.corner.number), "index": index,
                "start": row.corner.start, "end": row.corner.end,
                "delta": signed(delta, 2) if delta is not None else "",
                "deltaColor": COLOR_LOSS if delta is not None and delta > 0.005
                else COLOR_GAIN if delta is not None and delta < -0.005 else "",
            })
        return points

    def official_points(self) -> list[dict]:
        """Official corners on map, time lost / gained shown on the official corner nearest to apex"""
        delta_on: dict[int, CornerComparison] = {}  # official corner index: corner found on reference lap
        for row in self._corner_rows:
            nearest = min(self.official_in(row) or self._official,
                          key=lambda corner: abs(corner.distance - row.corner.apex))
            if abs(nearest.distance - row.corner.apex) <= 200:
                delta_on[self._official.index(nearest)] = row
        points = []
        for index, corner in enumerate(self._official):
            found = delta_on.get(index) or next(
                (row for row in self._corner_rows if corner in self.official_in(row)), None)
            delta = found.time_delta if found is not None and index in delta_on else None
            start, end = (found.corner.start, found.corner.end) if found is not None else (
                corner.distance - 120, corner.distance + 120)
            points.append({
                "x": corner.x, "y": corner.y, "label": self.official_text(corner.label), "index": index,
                "start": start, "end": end,
                "delta": signed(delta, 2) if delta is not None else "",
                "deltaColor": COLOR_LOSS if delta is not None and delta > 0.005
                else COLOR_GAIN if delta is not None and delta < -0.005 else "",
            })
        return points

    def map_braking_points(self) -> list[dict]:
        """Where each lap starts braking, colored like its lap"""
        points = []
        for line, lap in self._map_lines:
            for distance in lap_map.braking_points(lap.data):
                x, y = lap_map.point_at(line, distance)
                points.append({"x": x, "y": y, "color": lap.color.name(), "distance": distance})
        return points

    def build_map_bands(self):
        """Thick lines sized for current map zoom: road, driving lines, zoomed part, colored line"""
        if not self._map:
            return
        start, end, meters_per_pixel = self._map_view
        road = self._road
        closed = len(road.xs) > 2 and (road.xs[0] - road.xs[-1]) ** 2 + (road.ys[0] - road.ys[-1]) ** 2 < 50 ** 2
        road_half = max(TRACK_WIDTH / 2, meters_per_pixel * 4)  # visible when zoomed out
        simple_road = lap_map.simplify(road, meters_per_pixel * 0.75)
        VertexStore.set(self._map["road"], band(simple_road.xs, simple_road.ys, road_half, closed))
        VertexStore.set(self._map["edge"], band(simple_road.xs, simple_road.ys, road_half + meters_per_pixel * 1.5,
                                                closed))
        zoomed = end > start
        for (line, _), keys in zip(self._map_lines, self._map["lines"]):
            simple = lap_map.simplify(line, meters_per_pixel * 0.75)
            VertexStore.set(keys["key"], lap_map.line_band(simple, meters_per_pixel * LINE_WIDTH))
            highlight = lap_map.part(line, start, end) if zoomed else lap_map.MapLine([], [], [])
            VertexStore.set(keys["highlight"], lap_map.line_band(highlight, meters_per_pixel * ZOOMED_WIDTH))
        marks = []
        if self._map_lines:
            reference = self._map_lines[0][0]
            for distance in self.data.sector_lines:  # sector boundaries across road
                marks.append(lap_map.cross_mark(reference, distance, road_half * 1.6))
        VertexStore.set(self._map["marks"], segments(marks))
        self.build_colored_line(meters_per_pixel)

    def build_colored_line(self, meters_per_pixel: float):
        """Line of current color mode: compared lap by time gain, reference lap by speed or pedals"""
        key = self._map["colored"]
        self._speed_range = (0.0, 0.0)
        mode = self._map_mode
        lines = self._map_lines
        if mode == "laps" or not lines:
            VertexStore.set(key, lap_map.colored_line(lap_map.MapLine([], [], []), [], 0))
            return
        if mode == "gain":
            if len(lines) < 2 or self.data.reference is None:
                VertexStore.set(key, lap_map.colored_line(lap_map.MapLine([], [], []), [], 0))
                return
            line, lap = lines[1]
            colors = lap_map.gain_colors(lines[0][1].data, lap.data, line)
        else:
            line, lap = lines[0]
            if mode == "speed":
                colors, low, high = lap_map.speed_colors(lap.data, line)
                self._speed_range = (low, high)
            else:
                colors = lap_map.pedal_colors(lap.data, line)
        simple = lap_map.simplify(line, meters_per_pixel * 0.5)
        if simple is not line and colors:  # colors of kept points
            index = {distance: number for number, distance in enumerate(line.distances)}
            colors = [colors[index[distance]] for distance in simple.distances]
        VertexStore.set(key, lap_map.colored_line(simple, colors, meters_per_pixel * ZOOMED_WIDTH))

    @Slot(float, float, float)
    def setMapView(self, start_x: float, end_x: float, meters_per_pixel: float):
        """Charts zoom (axis range, equal if not zoomed) & map scale: map lines rebuilt"""
        start, end = (self.data.distance_at_x(start_x), self.data.distance_at_x(end_x)) if end_x > start_x else (0, 0)
        view = (start, end, max(meters_per_pixel, 1e-3))
        if view != self._map_view:
            self._map_view = view
            self.build_map_bands()
            self.build_gcircle_zoom()
            self.bump_revision()

    @Slot(str)
    def setMapMode(self, mode: str):
        if mode in lap_map.MAP_MODES and mode != self._map_mode:
            self._map_mode = mode
            save_viewer_setting(self.folder, map_color_mode=mode)
            if self._map:
                self.build_colored_line(self._map_view[2])
                self.bump_revision()
            self.mapChanged.emit()

    @Slot(bool)
    def setMapFollow(self, enabled: bool):
        self._map_follow = enabled
        save_viewer_setting(self.folder, map_follow_zoom=enabled)
        self.mapChanged.emit()

    @Slot(bool)
    def setMapBraking(self, enabled: bool):
        self._map_braking = enabled
        save_viewer_setting(self.folder, map_braking_points=enabled)
        self.mapChanged.emit()

    @Slot(float, float, result=list)
    def mapBounds(self, start_x: float, end_x: float) -> list[float]:
        """Map area of reference line between axis positions (map follows chart zoom), empty if none"""
        if not self._map_lines:
            return []
        line = lap_map.part(self._map_lines[0][0], self.data.distance_at_x(start_x), self.data.distance_at_x(end_x))
        if len(line.xs) < 2:
            return []
        return [min(line.xs), min(line.ys), max(line.xs), max(line.ys)]

    @Slot(float, result=list)
    def mapCursor(self, x: float) -> list[dict]:
        """Position of each lap at axis position, map coordinates"""
        distance = self.data.distance_at_x(x)
        return [
            {"x": interpolate(line.distances, line.xs, distance), "y": interpolate(line.distances, line.ys, distance),
             "color": lap.color.name()}
            for line, lap in self._map_lines
        ]

    @Slot(float, float, float, result=float)
    def mapPick(self, map_x: float, map_y: float, radius: float) -> float:
        """Axis position of reference line point nearest to map point, -1 if farther than radius"""
        if not self._map_lines:
            return -1.0
        line = self._map_lines[0][0]
        best, nearest = radius * radius, -1
        for index, (x, y) in enumerate(zip(line.xs, line.ys)):
            gap = (x - map_x) ** 2 + (y - map_y) ** 2
            if gap < best:
                best, nearest = gap, index
        return self.data.x_at_distance(line.distances[nearest]) if nearest >= 0 else -1.0

    # G circle
    def build_gcircle(self):
        self._g_points = []
        for lap in self.data.laps:
            lat, lon = lap.data.columns.get("accel_lat"), lap.data.columns.get("accel_long")
            if lat and lon:
                self._g_points.append((list(lap.data.distance), list(lat), list(lon), lap))
        if not self._g_points:
            self._gcircle = {}
            return
        limit = max((max(max(map(abs, lats)), max(map(abs, lons))) for _, lats, lons, _ in self._g_points),
                    default=1.0)
        limit = max(1.0, float(int(limit) + 1))
        dots_list = []
        for _, lats, lons, lap in self._g_points:
            key = f"{self.prefix}g|{lap.key}"
            VertexStore.set(key, dots(lats, lons, limit / 110))
            dots_list.append({"key": key, "zoom": key + "|zoom", "color": lap.color.name()})
        self._gcircle = {"limit": limit, "dots": dots_list}
        self.build_gcircle_zoom()

    def build_gcircle_zoom(self):
        start, end, _ = self._map_view
        limit = self._gcircle.get("limit", 1.0)
        for distances, lats, lons, lap in self._g_points:
            key = f"{self.prefix}g|{lap.key}|zoom"
            if end > start:
                low, high = bisect.bisect_left(distances, start), bisect.bisect_right(distances, end)
                VertexStore.set(key, dots(lats[low:high], lons[low:high], limit / 70))
            else:
                VertexStore.set(key, dots([], [], 0))

    @Slot(float, result=list)
    def gCursor(self, x: float) -> list[dict]:
        distance = self.data.distance_at_x(x)
        return [
            {"x": interpolate(distances, lats, distance), "y": interpolate(distances, lons, distance),
             "color": lap.color.name()}
            for distances, lats, lons, lap in self._g_points
        ]
