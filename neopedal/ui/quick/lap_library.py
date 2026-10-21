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
Lap viewer tracks & lap list (mixin of LapViewerBackend): track folders & lap infos read (indexed, in
background when many), track picker rows & game logos, folders watched for new laps, lap list rows (sessions,
search, labels), lap selection & compared laps
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import (
    Slot,
)

from ...i18n import tr, trm
from ...userfile.lap_cache import (
    IndexedInfos,
    indexed_infos,
    info_index_path,
    prune_cache,
    read_infos,
    save_info_index,
    save_pending_index,
)
from ...userfile.lap_marks import load_marks
from ...userfile.telemetry_lap import (
    LapData,
    LapFile,
    best_laps,
    group_sessions,
    lap_number_of,
    lap_stem,
    lap_timestamp_of,
    list_laps,
    list_tracks,
    read_lap_info,
    same_circuit,
    theoretical_best,
)
from .. import lap_viewer
from ..lap_viewer import (
    LapEntry,
    PlotLap,
    format_laptime,
    lap_label,
    load_viewer_setting,
    number_text,
    save_viewer_setting,
    signed,
)
from .formatting import day_month_minutes
from .game_pictures import brand_logo_url, track_logo_url
from .lap_actions import path_key, purge_trash
from .lap_base import (
    BackendBase,
)
from .models import DictListModel

TRACK_ROLES = ("key", "label", "logo", "date", "current")  # track picker rows (same roles as TrackPicker.qml)
INFO_BACKGROUND = 0  # more lap infos to read from files than this: read in background (track shown once read)


def setup_text(info: dict) -> str:
    """Setup of a lap: name loaded in game (* if changed in garage), with fingerprint of its values"""
    name = str(info.get("setup_name", ""))
    fingerprint = str(info.get("setup", ""))
    if name:
        name += "*" if info.get("setup_modified") else ""
        return f"{name} ({fingerprint})" if fingerprint else name
    return fingerprint


class TrackListModel(DictListModel):
    """Track picker rows (TrackPicker.qml trackModel): tracks whose name holds the search text (any case), filtered
    here and synced: typing only removes or inserts the rows that change, delegates of kept rows stay (no list
    reset, no list of every track sent to QML per key)"""

    def __init__(self, parent=None):
        super().__init__(TRACK_ROLES, parent)
        self._entries: list[dict] = []
        self._search = ""

    def set_entries(self, entries: list[dict]):
        """Every track row (search applied)"""
        self._entries = entries
        self.apply_search()

    @Slot(str)
    def setSearch(self, text: str):
        words = text.lower().strip()
        if words != self._search:
            self._search = words
            self.apply_search()

    def apply_search(self):
        words = self._search
        self.sync([entry for entry in self._entries if not words or words in entry["label"].lower()])

    @Slot(str, result=int)
    def indexOf(self, key: str) -> int:
        """Row of track key, -1 if not shown"""
        return self.index_of(key)

    @Slot(int, result="QVariant")
    def keyAt(self, number: int) -> str | None:
        """Track key of row, None (QML undefined) if no such row"""
        return self.rows[number]["key"] if 0 <= number < len(self.rows) else None


class LapLibrary(BackendBase):
    """Tracks & lap list of lap viewer page"""

    # Tracks & lap list
    @Slot()
    def refresh(self):
        if self._geometry is None:  # game started since: official circuit asked again
            self._geometry_tried.discard(self._track)
            self._geometry_track = ""
        if not self._tracks:  # first refresh: oldest cached laps removed over size limit, old deleted laps
            folder = self.folder
            self.run_job("lap cache", lambda: (prune_cache(folder), purge_trash(folder)), lambda _: None)
        self._tracks = list_tracks(self.folder)
        self._switch_to = None
        # Laps of another circuit shown without track folder (see switch_circuit): kept
        kept = self._track in self._tracks or (not self._track and bool(self.external))
        track = self._track if kept else (self._tracks[0] if self._tracks else "")
        self.drop_changed_laps()
        self._marks.clear()
        self.load_track(track)
        if not self._tracks and not self.external:
            self.set_status(tr("No recorded lap. Enable the Recorder module, then drive a few laps."), False)

    def drop_changed_laps(self):
        """Forget loaded laps whose file changed or was removed, and laps that could not be read (refresh: read
        again, file may be readable now)"""
        for path in list(self._lap_cache):
            try:
                changed = self._lap_cache[path] is None or os.path.getmtime(path) != self._cache_mtime.get(path)
            except OSError:
                changed = True
            if changed:
                self._lap_cache.pop(path, None)
                self._cache_mtime.pop(path, None)

    def load_track(self, track: str, new_lap: LapFile | None = None, background: bool = True):
        """Laps of track listed, laps shown last time on it shown (new_lap: lap just recorded compared, live mode),
        many new lap files: their infos read in background first (unless not background)"""
        laps = list_laps(self.folder, track) if track else []
        self._infos_generation += 1  # infos read for a former load ignored
        if self._infos_track:
            self._infos_track = ""
            self.notify_status()  # busy indicator of former read dropped
        indexed = self.indexed_infos(track, laps)
        if background and len(indexed[3]) > INFO_BACKGROUND:  # hundreds of new lap files (seconds): page not frozen
            self.read_track_infos(track, new_lap, [lap.path for lap in indexed[3]])
            return
        switch = self._switch_to if self._switch_to is not None and self._switch_to[0] == track else None
        self._switch_to = None
        changed = track != self._track
        self._track = track
        self.entries = [LapEntry(lap, info) for lap, info in zip(laps, self.track_infos(track, laps, indexed))]
        if switch is not None:  # laps opened (kept while track laps infos were read in background)
            self.checked, self.reference_key = set(switch[1]), switch[2]
        elif self._switched and changed:  # circuit of laps opened left: reference picked there not carried over
            self._chosen_reference = ""
        self._switched = switch is not None or (self._switched and not changed)
        adopted = self.adopt_external()
        self.tracksChanged.emit()
        if changed or switch is not None:  # analysis of former circuit laps not carried over (distances)
            self.reset_circuit_state()
        if new_lap is not None:
            self.compare_new_lap(laps, new_lap)
        elif switch is not None:  # laps of another circuit opened: only them shown (track laps listed)
            self.checked &= {entry.file.path for entry in self.all_entries()}  # adopted laps: track lap paths
        else:
            self.checked, self.reference_key = self.track_selection(track, laps, adopted)
        self._expanded = []
        self.watch_folders()
        self.start_geometry(track)
        self.start_limits(track)
        self.fill_list()
        self.load_laps()
        if self._side_tab == 4:  # session tab shown (page opened on it, track changed): its laps read
            self._session.start_job()

    def reset_circuit_state(self):
        """Analysis of former circuit laps not carried over: corner alignment, compared lap, session tab, chart
        markers, selected corner (track or circuit changed)"""
        self._charts.align_apex = -1.0  # laps aligned on a corner
        self._corner_table.compare_key = ""
        self._session.reset()
        self._map_range = (-1.0, -1.0)  # chart markers A & B
        if self._selected_corner != -1:
            self._selected_corner = -1
            self.selectionChanged.emit()

    def read_track_infos(self, track: str, new_lap: LapFile | None, paths: list[str]):
        """Lap infos of track read in background, track shown once read (shown track kept meanwhile), unless another
        track was loaded since"""
        generation = self._infos_generation
        self._infos_track = track
        before = self._status if self._status != tr("Reading laps...") else ""  # shown again once read
        self.set_status(tr("Reading laps..."), False)

        def done(result):
            self.keep_infos(result)  # kept even if another track is shown: read once
            if generation != self._infos_generation:
                return  # another track loaded meanwhile
            self._infos_track = ""
            if self._status == tr("Reading laps..."):
                self.set_status(before, bool(before))
            else:
                self.notify_status()  # busy indicator
            self.load_track(track, new_lap, False)  # infos known now (laps failed or added meanwhile: read here)

        self.run_job("lap infos", lambda: read_infos(paths), done)

    def keep_infos(self, result: Any):
        """Lap infos read in background (see read_infos) kept with their file time"""
        for item in result if isinstance(result, list) else []:
            if item is not None:
                self._info_cache[item[0]] = (item[1], item[2])

    def track_selection(self, track: str, laps: list[LapFile], adopted: set[str]) -> tuple[set[str], str]:
        """Laps shown on track & reference: laps shown last time (saved reference, else fastest of them), else fastest
        lap compared with newest other lap; added laps stay checked, an added reference stays if on this circuit"""
        saved = load_viewer_setting(self.folder).get("selections", {})
        saved = saved.get(track, {}) if isinstance(saved, dict) else {}
        saved = saved if isinstance(saved, dict) else {}
        paths = {lap.filename: lap.path for lap in laps}
        names = saved.get("checked", [])
        checked = {paths[name] for name in names if name in paths} if isinstance(names, list) else set()
        reference = paths.get(str(saved.get("reference", "")), "")
        if checked and reference not in checked:  # reference was an added lap (not saved): fastest checked lap
            best = best_laps([lap for lap in laps if lap.path in checked], 1)
            reference = best[0].path if best else next(lap.path for lap in laps if lap.path in checked)
        elif not checked:
            best = best_laps(laps, 1)
            reference = best[0].path if best else (laps[0].path if laps else "")
            checked = {reference} if reference else set()
            newest = next((lap.path for lap in laps if lap.valid and lap.path != reference), "")
            if newest:
                checked.add(newest)
        kept = self.checked & ({entry.file.path for entry in self.external} | adopted)
        if self.reference_key in kept and (not laps or self.same_circuit_paths(laps[0].path, self.reference_key)):
            reference = self.reference_key  # added lap chosen as reference, still shown & driven on this circuit
        return checked | kept, reference

    def adopt_external(self) -> set[str]:
        """Added laps that are laps of shown track listed once, as track laps (check & reference kept), their paths"""
        if not self.external:
            return set()
        listed = {path_key(entry.file.path): entry.file.path for entry in self.entries}
        moved = {entry.file.path: listed[path_key(entry.file.path)] for entry in self.external
                 if path_key(entry.file.path) in listed}
        if not moved:
            return set()
        self.external = [entry for entry in self.external if entry.file.path not in moved]
        self.checked = {moved.get(path, path) for path in self.checked}
        self.reference_key = moved.get(self.reference_key, self.reference_key)
        self._chosen_reference = moved.get(self._chosen_reference, self._chosen_reference)
        return set(moved.values())

    def same_circuit_paths(self, reference: str, path: str) -> bool:
        """Whether listed lap was driven on circuit of reference lap (lap info: game track name & length)"""
        infos = {entry.file.path: entry.info for entry in self.all_entries()}
        return same_circuit(LapData("", {}, infos.get(reference, {})), LapData("", {}, infos.get(path, {})))

    # Track picker rows & game logos
    @Slot()
    def update_track_rows(self):
        """Track picker rows made again only when tracks or circuit logos changed (tracksChanged is sent by every
        track load)"""
        key = (tuple(self._tracks), self._picture_version)
        if key == self._track_rows:
            return
        self._track_rows = key
        self.track_model.set_entries([
            {"key": track, "label": track, "logo": self.trackLogo(track), "date": "", "current": False}
            for track in self._tracks
        ])

    @Slot(str, result=str)
    def trackLogo(self, folder: str) -> str:
        """Circuit logo of game for a track folder ("Track - Class")"""
        return track_logo_url(folder.rsplit(" - ", 1)[0], folder) if folder else ""

    @Slot()
    def pictures_changed(self):
        self._picture_version += 1
        self.picturesChanged.emit()
        self.lap_model.update_rows(  # car brand logos of session headers, list kept in place
            lambda row: {"logo": brand_logo_url(row["brand"])} if row["kind"] == "session" and row.get("brand") else {})

    def watch_folders(self):
        """Watch telemetry & current track folders (every track folder in live mode: lap driven on another track
        shown): new laps listed without refresh

        Folders already watched keep their listing (kept up to date by folder_changed: a change waiting to be told
        is never hidden by a listing made again). Folders watched from now on are listed once watched (a lap written
        meanwhile is told by the watcher): telemetry & shown track folders at once, other track folders of live mode
        in background (hundreds of folders never listed on page thread, see folder_changed while being listed).
        """
        current = {os.path.normpath(path): path for path in self._watcher.directories()}
        shown = [folder for folder in (self.folder, os.path.join(self.folder, self._track) if self._track else "")
                 if folder and os.path.isdir(folder)]
        # Other track folders: listed as folders by refresh or auto_refresh (one removed since: not watched by Qt)
        others = [os.path.join(self.folder, track) for track in self._tracks if track != self._track] if self._live else []
        wanted = {os.path.normpath(folder): folder for folder in (*others, *shown)}
        gone = [path for key, path in current.items() if key not in wanted]
        if gone:
            self._watcher.removePaths(gone)
        added = [folder for key, folder in wanted.items() if key not in current]
        if added:
            self._watcher.addPaths(added)
        # Listings of folders no longer watched, or watched again (changes missed meanwhile) forgotten
        self._watched = {key: entries for key, entries in self._watched.items() if key in wanted and key in current}
        self._listing &= wanted.keys()
        listed = {os.path.normpath(folder) for folder in shown}
        later: list[tuple[str, str]] = []
        for key, folder in wanted.items():
            if key in self._watched or key in self._listing:
                continue
            if key in listed:
                self._watched[key] = self.folder_entries(folder)
            else:
                later.append((key, folder))
        if later:
            self.list_watched(later)

    def list_watched(self, folders: list[tuple[str, str]]):
        """Listings of watched track folders made in background (live mode): kept unless folder_changed listed one
        meanwhile (newer), or it is no longer watched"""
        self._listing.update(key for key, _ in folders)

        def done(result):
            for key, entries in (result or {}).items():
                if key in self._listing:
                    self._watched.setdefault(key, entries)
            self._listing.difference_update(key for key, _ in folders)

        self.run_job("lap folders", lambda: {key: self.folder_entries(folder) for key, folder in folders}, done)

    @staticmethod
    def folder_entries(folder: str) -> tuple:
        """Lap files & track folders of watched folder (hidden settings, caches, trash & files being written left out)"""
        try:
            names = os.listdir(folder)
        except OSError:
            return ()
        return tuple(sorted(name for name in names if not name.startswith(".") and not name.endswith(".tmp")))

    @Slot(str)
    def folder_changed(self, folder: str):
        """Watched folder changed: list refreshed a moment later only if laps or tracks changed (viewer settings,
        lap caches & trash are written in telemetry folder too)"""
        entries = self.folder_entries(folder)
        key = os.path.normpath(folder)
        seen = self._watched.get(key)
        if seen == entries:
            return
        self._watched[key] = entries  # newer than a background listing still running (kept, see list_watched)
        if seen is None and key in self._listing:  # changed while first listed: what it held before is unknown
            seen = ()
        track = os.path.basename(key)
        if (seen is not None and key != os.path.normpath(self.folder) and track != self._track
                and set(entries) - set(seen)):  # other track folder watched in live mode: new lap there
            self._new_lap_tracks.add(track)  # (newer than shown laps only, see other_track_lap)
        self._watch_timer.start()

    @Slot()
    def auto_refresh(self):
        """Lap files added or removed: list updated, newest lap compared with best lap in live mode (lap driven on
        another track: that track shown); page hidden: done once shown again (no list update nor lap read while
        driving, laps released stay released)"""
        if self._hidden:
            self._refresh_pending = True
            return
        if self._loader is not None or self._infos_reading or self._infos_track:
            self._watch_timer.start()  # after current loading
            return
        tracks = list_tracks(self.folder)
        added_tracks = [track for track in tracks if track not in self._tracks]
        if tracks != self._tracks:
            self._tracks = tracks
            self.tracksChanged.emit()
        changed, self._new_lap_tracks = self._new_lap_tracks, set()
        if not self._track and tracks and not self.external:  # first lap ever recorded (laps of another circuit
            # shown without track folder kept, see switch_circuit: live mode shows track of a new lap below)
            self.load_track(tracks[0])
            return
        if self._live:
            found = self.other_track_lap(added_tracks + sorted(changed - set(added_tracks)))
            if found is not None:
                self.load_track(*found)
                return
            if added_tracks:  # new track folders watched
                self.watch_folders()
        known = {entry.file.path for entry in self.entries}
        laps = list_laps(self.folder, self._track) if self._track else []
        listed = {lap.path for lap in laps}
        if listed == known:
            return
        indexed = self.indexed_infos(self._track, laps)
        if indexed[3]:  # infos of new lap files read in background first, list updated once read
            self.read_new_infos([lap.path for lap in indexed[3]])
            return
        new = [lap for lap in laps if lap.path not in known]
        self.entries = [LapEntry(lap, info) for lap, info in zip(laps, self.track_infos(self._track, laps, indexed))]
        self.checked = {path for path in self.checked if path in listed or path not in known}
        if self.reference_key not in self.checked:
            self.reference_key = ""
        if self._live and new:
            self.compare_new_lap(laps, new[0])  # lap files newest first
        self.fill_list()
        self.load_laps()

    def read_new_infos(self, paths: list[str]):
        """Infos of lap files added to shown track read in background, then list updated again (see auto_refresh)"""
        self._infos_reading = True
        self.notify_status()  # busy indicator
        generation = self._infos_generation

        def done(result):
            self._infos_reading = False
            self.notify_status()
            self.keep_infos(result)
            if generation == self._infos_generation:  # same track shown
                self.auto_refresh()

        self.run_job("lap infos", lambda: read_infos(paths), done)

    def other_track_lap(self, tracks: list[str]) -> tuple[str, LapFile] | None:
        """Track & newest lap recorded on other tracks than shown one (live mode), None if none newer than laps of
        shown track (laps copied there)"""
        found = None
        newest = max((lap_timestamp_of(entry.file.filename) for entry in self.entries), default=0.0)
        for track in tracks:
            laps = list_laps(self.folder, track) if track != self._track else []
            timestamp = lap_timestamp_of(laps[0].filename) if laps else 0.0
            if timestamp > newest:
                found, newest = (track, laps[0]), timestamp
        return found

    def compare_new_lap(self, laps: list[LapFile], new_lap: LapFile):
        """Live mode: lap just recorded compared with reference lap picked by user if driven on same circuit, else with
        best lap of track (former best lap if new lap is best lap)"""
        reference = self.reference_key
        infos = {entry.file.path: entry.info for entry in self.all_entries()}
        if not (reference and reference == self._chosen_reference and reference != new_lap.path and reference in infos
                and not self.other_circuit((infos.get(new_lap.path, {}), new_lap.path), infos[reference], reference)
                and not self.other_circuit(self.main_circuit(), infos[reference], reference)):
            best = [lap.path for lap in best_laps(laps, 2)]
            reference = next((path for path in best if path != new_lap.path), new_lap.path)
        self.checked = {new_lap.path, reference}
        self.reference_key = reference
        self.set_status(trm(f"New lap: {lap_label(new_lap.filename)}"))

    @Slot(bool)
    def setLiveMode(self, enabled: bool):
        self._live = enabled
        save_viewer_setting(self.folder, live_mode=enabled)
        self.watch_folders()  # every track folder in live mode
        self.optionsChanged.emit()

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

    def info_index_path(self, track: str) -> str:
        return info_index_path(self.folder, track)

    def indexed_infos(self, track: str, laps: list[LapFile]) -> IndexedInfos:
        """Lap file stamps, saved track index, infos known (memory or index) & laps whose info must be read from file"""
        return indexed_infos(os.path.join(self.folder, track), self.info_index_path(track), laps, self._info_cache)

    def track_infos(self, track: str, laps: list[LapFile], indexed: IndexedInfos | None = None) -> list[dict]:
        """Infos of track laps: from memory, else from track index (lap file size & time unchanged), else read from
        lap files (index saved again in background): opening hundreds of new files takes seconds (antivirus scan,
        read in background first, see read_track_infos)"""
        if not laps:
            return []
        stamps, saved, known, missing = indexed if indexed is not None else self.indexed_infos(track, laps)
        read = read_infos([lap.path for lap in missing])  # files added since infos were read in background
        known.update((lap.filename, item[2] if item is not None else {}) for lap, item in zip(missing, read))
        infos, index = [], {}
        for lap in laps:
            stamp = stamps.get(lap.filename)
            if stamp is None:
                infos.append(self.lap_info(lap.path))
                continue
            info = known[lap.filename]
            self._info_cache[lap.path] = (stamp[2], info)
            index[lap.filename] = [stamp[0], stamp[1], info]
            infos.append(info)
        if missing or index.keys() != saved.keys():
            self.save_index_later(self.info_index_path(track), index)
        return infos

    @staticmethod
    def save_info_index(path: str, index: dict):
        """Lap infos of a track saved atomically (temporary file renamed): never read half written"""
        save_info_index(path, index)

    def save_index_later(self, path: str, index: dict):
        """Lap infos index saved in background (newest index of path written last, see save_info_index): a job per
        call, one finding the index already saved by an earlier job does nothing"""
        pending = self._index_saves
        pending[path] = index
        self.run_job("lap infos index", lambda: save_pending_index(path, pending), lambda _: None)

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
        if entry.foreign:
            texts.append(tr("foreign"))
        shared_by = entry.info.get("shared_by")
        if shared_by and isinstance(shared_by, str):  # lap shared by another driver (Share Lap)
            texts.append(trm(f"shared by {shared_by}"))
        if entry.external and entry.info.get("session"):
            texts.append(tr(str(entry.info["session"])))
        vehicle = str(entry.info.get("vehicle", ""))
        if vehicle and vehicle != session_vehicle:
            texts.append(vehicle)
        return ", ".join(texts)

    @staticmethod
    def entry_conditions(entry: LapEntry) -> str:
        """Lap conditions tooltip: vehicle, temperatures, wetness, fuel used"""
        info = entry.info
        lines = []
        for key, label in (("vehicle", "Vehicle"), ("class", "Class"), ("combo", "Layout")):
            if info.get(key):
                lines.append(f"{tr(label)}: {info[key]}")

        def number(key: str) -> float | None:
            value = info.get(key)
            return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

        convert, symbol = lap_viewer.display_units()["temperature"]
        for key, label in (("track_temperature", "Track Temp"), ("ambient_temperature", "Air Temp")):
            value = number(key)
            if value is not None:
                lines.append(f"{tr(label)}: {number_text(convert(value) if convert else value, 1)}{symbol}")
        wetness = number("wetness")
        if wetness is not None:
            lines.append(f"{tr('Wetness')}: {wetness * 100:.0f}%")
        start, end = number("fuel_start"), number("fuel_end")
        if start is not None:
            convert, symbol = lap_viewer.display_units()["fuel"]
            lines.append(f"{tr('Starting Fuel')}: {number_text(convert(start) if convert else start, 1)} {symbol}")
            if end is not None and start >= end:
                used = start - end
                lines.append(f"{tr('Fuel Used')}: {number_text(convert(used) if convert else used, 2)} {symbol}")
        setup = setup_text(info)
        if setup:
            lines.append(f"{tr('Setup')}: {setup}")
        return "\n".join(lines)

    def all_entries(self) -> list[LapEntry]:
        return self.entries + self.external

    def track_sessions(self) -> list:
        """Laps of current track grouped by session (cached while track laps stay the same)"""
        if self._groups is None or self._groups[0] is not self.entries:
            self._groups = (self.entries, group_sessions(self.entries, lambda entry: entry.file.filename,
                                                         lambda entry: entry.info))
        return self._groups[1]

    def entry_search_text(self, entry: LapEntry) -> str:
        """Everything a lap can be searched by: name, time, session, vehicle, conditions, note, setup"""
        info = entry.info
        number = lap_number_of(entry.file.filename)
        parts = [lap_label(entry.file.filename), trm(f"Lap {number}") if number else "", format_laptime(entry.file.lap_time),
                 str(info.get("session", "")), tr(str(info.get("session", ""))), str(info.get("vehicle", "")),
                 str(info.get("class", "")), str(info.get("combo", "")), str(info.get("setup", "")),
                 str(info.get("setup_name", "")),
                 self.entry_text(entry), self.entry_conditions(entry), entry.file.filename]
        if not entry.external:
            parts.append(str(self.lap_marks(entry.file.path).get("note", "")))
            if self.lap_marks(entry.file.path).get("kept"):
                parts.append(tr("kept"))
        return " ".join(parts).lower()

    def matches_filter(self, entry: LapEntry) -> bool:
        """Lap list search: every word of search text found in lap details"""
        words = self._filter.lower().split()
        if not words:
            return True
        text = self.entry_search_text(entry)
        return all(word in text for word in words)

    @Slot(str)
    def setFilter(self, text: str):
        """Lap list search text: vehicle, session, conditions, note, setup..."""
        text = text.strip()
        if text != self._filter:
            self._filter = text
            self.fill_list()
            self.update_list_state(self.data.laps)

    def build_labels(self, laps: list[PlotLap]):
        """Short names of shown laps, told apart when two are the same (folder of added laps, else session date)"""
        entries = {entry.file.path: entry for entry in self.all_entries()}
        labels = {lap.key: lap_label(os.path.basename(lap.key)) for lap in laps}
        counts = Counter(labels.values())
        for key, label in list(labels.items()):
            if counts[label] < 2:
                continue
            entry = entries.get(key)
            if entry is None or entry.external:
                extra = os.path.basename(os.path.dirname(key))
            else:
                timestamp = lap_timestamp_of(entry.file.filename)
                extra = day_month_minutes(timestamp)
            labels[key] = f"{label} ({extra})" if extra else label
        counts = Counter(labels.values())
        seen: Counter = Counter()
        for key, label in list(labels.items()):
            if counts[label] > 1:
                seen[label] += 1
                labels[key] = f"{label} #{seen[label]}"
        self._labels = labels

    def short_label(self, key: str) -> str:
        """Short name of shown lap (legend chips, map, corners)"""
        return self._labels.get(key) or lap_label(os.path.basename(key))

    def fill_list(self):
        """Laps grouped by session (newest first), added files on top, sessions with shown laps expanded

        Rows kept in place (list keeps scroll position), lap rows of collapsed sessions left out of list model.
        """
        self._list_revision += 1  # lap file times asked again (see MapConsistency.lap_mtime)
        # Added files may come from other tracks: theoretical best & best sectors of current track only
        sectors = [self.entry_sectors(entry) for entry in self.entries if entry.file.valid]
        best_total, best_sectors = theoretical_best(sectors)
        best_lap = min((entry.file.lap_time for entry in self.entries if entry.file.valid and entry.file.lap_time > 0),
                       default=0.0)
        shown = self.checked | {self.reference_key}  # listed even if search or clean only filter leaves them out
        matched = False
        entries = []
        for entry in self.entries:
            match = ((not self._hide_unclean or (entry.file.valid and entry.info.get("kind") not in ("out", "in")))
                     and self.matches_filter(entry))
            matched = matched or match
            if match or entry.file.path in shown:
                entries.append(entry)
        groups: list[tuple[list[LapEntry], bool]] = [
            (group, False)
            for group in group_sessions(entries, lambda entry: entry.file.filename, lambda entry: entry.info)
        ]
        added: dict[str, list[LapEntry]] = {}  # added laps by folder (imported log, other track)
        for entry in self.external:
            match = self.matches_filter(entry)
            matched = matched or match
            if match or entry.file.path in shown:
                added.setdefault(os.path.dirname(entry.file.path), []).append(entry)
        groups[:0] = [(group, True) for group in added.values()]
        colors = {lap.key: lap.color.name() for lap in self.data.laps}
        hint = self.circuit_hints()
        rows: list[dict] = []
        expanded = []
        for index, (group, is_added) in enumerate(groups):
            header = self.session_row(group, is_added)
            rows.append(header)
            vehicle = str(group[0].info.get("vehicle", ""))
            fastest = min((entry for entry in group if entry.file.valid and entry.file.lap_time > 0),
                          key=lambda entry: entry.file.lap_time, default=None)
            for entry in group:
                row = self.lap_row(header["session"], entry, best_sectors, vehicle, entry is fastest, best_lap,
                                   colors.get(entry.file.path, ""))
                row.update(hint(row))
                rows.append(row)
            if (index == 0 or header["session"] in self._expanded
                    or any(entry.file.path in shown for entry in group)):
                expanded.append(header["session"])
        self._expanded = expanded
        self.show_rows(rows)
        self._no_match = not matched and bool(self.entries or self.external)
        self._session.changed.emit()
        self._best_text = trm(f"Theoretical best: {format_laptime(best_total)}") if best_total > 0 else ""
        self.listChanged.emit()

    def show_rows(self, rows: list[dict]):
        """List rows: lap rows of collapsed sessions left out of list model (no delegate made for them)"""
        opened = set(self._expanded)
        for row in rows:
            if row["kind"] == "session":
                row["open"] = row["session"] in opened
        self.lap_model.set_rows(rows, lambda row: row["kind"] == "session" or row["session"] in opened)

    def circuit_hints(self) -> Callable[[dict], dict]:
        """Lap row change: lap driven on another circuit than reference lap dimmed with a hint (unchecked & never
        compared with it, see drop_other_circuits)"""
        infos = {entry.file.path: entry.info for entry in self.all_entries()}
        main = self.main_circuit() if self.entries or self.reference_key in infos else None
        text = tr("Another circuit than reference lap: not compared")

        def hint(row: dict) -> dict:
            if row["kind"] != "lap":
                return {}
            other = main is not None and self.other_circuit(main, infos.get(row["path"], {}), row["path"])
            return {"hint": text if other else ""}

        return hint

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
            date = day_month_minutes(timestamp)
            title = f"{tr(session)}  {date}".strip()
            key = f"{session} {first.file.filename[:19]}"
        best = min((entry.file.lap_time for entry in group if entry.file.valid and entry.file.lap_time > 0), default=0)
        details = []
        vehicle = str(first.info.get("vehicle", ""))
        if is_added:
            details.append(tr("foreign laps") if first.foreign else tr("added"))
        if vehicle:
            details.append(vehicle)
        return {
            "id": f"session:{key}", "kind": "session", "session": key, "path": "", "title": title,
            "time": format_laptime(best), "s1": "", "s2": "", "s3": "", "best1": False, "best2": False, "best3": False,
            "info": ", ".join(details), "note": "", "count": len(group), "checked": False, "reference": False,
            "color": "", "dim": False, "fastest": False, "error": False, "gap": "", "tip": "", "open": False,
            "hint": "", "logo": brand_logo_url(vehicle) if vehicle and not is_added else "",
            "brand": vehicle if not is_added else "",  # logo asked again once game logos arrive
        }

    def lap_row(self, session: str, entry: LapEntry, best_sectors: list[float], vehicle: str,
                is_fastest: bool, best_lap: float = 0.0, color: str = "") -> dict:
        """Lap row: number, time, gap to best lap, sectors (best ones flagged), info; invalid & out/in laps dimmed"""
        number = lap_number_of(entry.file.filename)
        sectors = self.entry_sectors(entry) or [0.0, 0.0, 0.0]
        bests = [
            value > 0 and bool(best_sectors) and abs(value - best) < 0.0005 and entry.file.valid and not entry.external
            for value, best in zip(sectors, best_sectors or [0.0, 0.0, 0.0])
        ]
        gap = ""
        if best_lap > 0 and entry.file.lap_time > 0 and not entry.external:
            difference = entry.file.lap_time - best_lap
            gap = signed(difference, 3) if difference >= 0.0005 else ""
        path = entry.file.path
        return {
            "id": path, "kind": "lap", "session": session, "path": path, "vehicle": vehicle,
            "title": trm(f"Lap {number}") if number else lap_stem(entry.file.filename),
            "time": format_laptime(entry.file.lap_time),
            "s1": format_laptime(sectors[0]), "s2": format_laptime(sectors[1]), "s3": format_laptime(sectors[2]),
            "best1": bests[0], "best2": bests[1], "best3": bests[2], **self.mark_values(entry, vehicle),
            "checked": path in self.checked, "reference": path == self.reference_key,
            "color": color, "dim": not entry.file.valid or entry.info.get("kind") in ("out", "in"),
            "fastest": is_fastest, "count": 0, "error": path in self._failed and path in self.checked, "gap": gap,
            "tip": self.entry_conditions(entry), "open": True, "hint": "", "logo": "",
        }

    def mark_values(self, entry: LapEntry, vehicle: str) -> dict:
        """Lap row info & note: details not shown by session header (vehicle), kept state & note of recorded lap"""
        info = self.entry_text(entry, vehicle)
        note = ""
        if not entry.external:
            mark = self.lap_marks(entry.file.path)
            note = str(mark.get("note", ""))
            if mark.get("kept"):
                info = ", ".join(filter(None, [info, tr("kept")]))
        return {"info": info, "note": note}

    def lap_rows(self) -> list[dict]:
        """Lap rows, also of collapsed sessions (their checked laps are shown in charts)"""
        return [row for row in self.lap_model.all_rows if row["kind"] == "lap"]

    def ordered_checked(self) -> list[str]:
        """Checked laps in list order"""
        return [row["path"] for row in self.lap_rows() if row["path"] in self.checked]

    @Slot(str)
    def toggleSession(self, key: str):
        """Session expanded or collapsed: its lap rows added to or removed from list model"""
        if key in self._expanded:
            self._expanded = [session for session in self._expanded if session != key]
        else:
            self._expanded = [*self._expanded, key]
        self.show_rows(self.lap_model.all_rows)
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

    @Slot(str, str, bool)
    def selectRange(self, first: str, last: str, checked: bool):
        """Shift+click: every lap seen between two laps checked (or unchecked, reference lap kept): laps of collapsed
        sessions left as they are"""
        paths = [row["path"] for row in self.lap_rows()]
        if first not in paths or last not in paths:
            self.setLapChecked(last, checked)
            return
        listed = {row["path"] for row in self.lap_model.rows} | {first, last}
        low, high = sorted((paths.index(first), paths.index(last)))
        for path in paths[low:high + 1]:
            if path not in listed:
                continue
            if checked:
                self.checked.add(path)
            elif path != self.reference_key:
                self.checked.discard(path)
        self.load_laps()

    @Slot()
    def clearSelection(self):
        """Uncheck every lap except reference lap"""
        self.checked = {self.reference_key} if self.reference_key else set()
        self.load_laps()

    @Slot()
    def compareBestLast(self):
        """Fastest valid lap of track as reference, compared with newest lap"""
        laps = [entry.file for entry in self.entries]
        best = best_laps(laps, 1)
        if not laps:
            return
        newest = laps[0]
        self.reference_key = best[0].path if best else newest.path
        self._chosen_reference = ""  # best lap: follows new laps in live mode
        self.checked = {self.reference_key, newest.path}
        self.fill_list()
        self.load_laps()

    @Slot(int)
    def compareBest(self, count: int):
        """Fastest valid laps of track, fastest as reference"""
        best = best_laps([entry.file for entry in self.entries], count)
        if not best:
            return
        self.reference_key = best[0].path
        self._chosen_reference = ""
        self.checked = {lap.path for lap in best}
        self.fill_list()
        self.load_laps()

    @Slot(str)
    def setReference(self, path: str):
        if not path:  # session header
            return
        infos = {entry.file.path: entry.info for entry in self.all_entries()}
        if self.entries and self.other_circuit(self.main_circuit(), infos.get(path, {}), path):
            self.set_status(trm(f"Lap from another circuit, not usable as reference lap: "
                                f"{', '.join(self.circuit_names([path], infos))}"))
            return
        self.reference_key = self._chosen_reference = path
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
