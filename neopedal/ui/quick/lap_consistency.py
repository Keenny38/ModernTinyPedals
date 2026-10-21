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
Lap viewer map consistency mode (part of LapViewerBackend, QML backend.mapConsistency): spread of each mini-sector
time over clean laps of a stint, a session or shown laps, mini-sector times of laps not shown read in worker process
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot

from ...i18n import tr, trm
from ...userfile.lap_geometry import mini_sector_job, mini_sector_spread
from ..lap_viewer import number_text, save_viewer_setting
from . import lap_map
from .lap_base import PagePart, weak_host

if TYPE_CHECKING:
    from ..lap_viewer import LapEntry
    from .trace_data import TraceData

CONSISTENCY_SCOPES = ("stint", "session", "shown")  # laps compared in consistency mode (setting)


class ConsistencyHost(Protocol):
    """What the consistency part uses of the lap viewer page"""

    data: TraceData
    reference_key: str
    folder: str
    _list_revision: int  # grows when lap list is filled again (lap files may have changed)

    def track_sessions(self) -> list[list[LapEntry]]: ...
    def run_process_job(self, name: str, done: Callable[[Any], None], function: Callable, *args): ...
    def consistency_read(self): ...


class MapConsistency(PagePart):
    """Consistency mode of track map (QML backend.mapConsistency)"""

    scopeChanged = Signal()

    def __init__(self, page: ConsistencyHost, setting: dict, parent: QObject | None = None):
        super().__init__(parent)
        self._page = weak_host(page)
        scope = setting.get("consistency_scope", "session")
        self._scope = scope if scope in CONSISTENCY_SCOPES else "session"
        self.found: dict = {}  # spreads shown on map (see measure)
        self._mini_times: dict[str, tuple[float, tuple, list[float]]] = {}  # lap path: file time, bounds, times
        self._busy = False  # mini-sector times of laps not shown being read
        self._mtimes: tuple[int, dict[str, float | None]] = (-1, {})  # lap list revision, lap path: file time

    def release(self):
        self.found = {}
        self._mini_times = {}
        self._mtimes = (-1, {})

    @Property(str, notify=scopeChanged)
    def scope(self) -> str:
        """Laps compared: stint, session (of reference lap) or shown"""
        return self._scope

    @Slot(str)
    def setScope(self, scope: str):
        """Laps compared in consistency mode: stint or session of reference lap, or shown laps"""
        if scope in CONSISTENCY_SCOPES and scope != self._scope:
            self._scope = scope
            save_viewer_setting(self._page.folder, consistency_scope=scope)
            self.scopeChanged.emit()
            self._page.consistency_read()

    def paths(self) -> list[str]:
        """Clean laps compared: stint or session of reference lap (recorded laps of track), else shown laps"""
        page = self._page
        shown = [lap.key for lap in page.data.laps if lap.clean]
        if self._scope == "shown":
            return shown
        group = next((group for group in page.track_sessions()
                      if any(entry.file.path == page.reference_key for entry in group)), None)
        if group is None:  # reference lap added from another folder
            return shown
        if self._scope == "stint":  # laps between pit exit (out lap) & pit entry (in lap)
            index = next(index for index, entry in enumerate(group) if entry.file.path == page.reference_key)
            start = end = index
            while start > 0 and group[start].info.get("kind") != "out" and group[start - 1].info.get("kind") != "in":
                start -= 1
            while end + 1 < len(group) and group[end].info.get("kind") != "in" and group[end + 1].info.get("kind") != "out":
                end += 1
            group = group[start:end + 1]
        return [entry.file.path for entry in group
                if entry.file.valid and entry.file.lap_time > 0 and entry.info.get("kind", "lap") == "lap"]

    def measure(self) -> dict:
        """Spread (standard deviation) of each mini-sector time over laps of chosen scope: bounds, spreads (-1: under
        3 laps), laps counted, busy while laps are read (mini-sector times of laps not shown read in background),
        kept as found"""
        data = self._page.data
        mini = data.mini_sectors()
        reference = data.reference
        if not mini or reference is None:
            self.found = {}
            return self.found
        bounds = mini["bounds"]
        anchor = data.anchor_key  # imported laps aligned on reference lap (itself aligned on anchor lap)
        key = (reference.key, anchor, *(round(bound, 2) for bound in bounds))
        shown = {lap.key: times for lap, times in zip(data.laps, mini["times"]) if times}
        times: list[list[float]] = []
        missing: list[tuple[str, float]] = []
        for path in self.paths():
            if path in shown:
                times.append(shown[path])
                continue
            mtime = self.lap_mtime(path)
            if mtime is None:
                continue
            cached = self._mini_times.get(path)
            if cached is not None and cached[0] == mtime and cached[1] == key:
                if cached[2]:
                    times.append(cached[2])
            else:
                missing.append((path, mtime))
        if missing:
            self.start_job(missing, list(bounds), key, data.lap_end(reference), dict(reference.data.meta),
                           reference.key, anchor)
        self.found = {"bounds": bounds, "spreads": mini_sector_spread(times), "laps": len(times),
                      "busy": bool(missing) or self._busy}
        return self.found

    def lap_mtime(self, path: str) -> float | None:
        """File time of listed lap (None if gone), asked once while lap list stays the same (map zoom colors the
        consistency line again)"""
        revision, mtimes = self._mtimes
        if revision != self._page._list_revision:
            mtimes = {}
            self._mtimes = (self._page._list_revision, mtimes)
        if path not in mtimes:
            try:
                mtimes[path] = os.path.getmtime(path)
            except OSError:
                mtimes[path] = None
        return mtimes[path]

    def start_job(self, todo: list[tuple[str, float]], bounds: list[float], key: tuple, length: float,
                  reference_info: dict | None = None, reference_path: str = "", anchor_path: str = ""):
        """Mini-sector times of laps not shown read in worker process (cached by lap file time), map colored again

        length: reference lap end distance (see TraceData.lap_end), reference_info: reference lap info (laps of the
        same track length never scaled, see mini_sector_job), reference_path: reference lap file (imported laps aligned
        on it like shown laps), anchor_path: lap recorded by the app an imported reference lap is aligned on first.
        """
        if self._busy:
            return
        self._busy = True
        page = self._page

        def done(found):
            self._busy = False
            found = found if isinstance(found, dict) else {}
            for path, mtime in todo:  # unreadable laps not read again until their file changes
                self._mini_times[path] = (mtime, key, found.get(path, []))
            page.consistency_read()

        page.run_process_job("mini-sectors", done, mini_sector_job, page.folder, [path for path, _ in todo], bounds,
                             length, reference_info, reference_path, anchor_path)

    def legend(self) -> dict:
        """Map legend of consistency mode: lowest & highest spread (s), laps counted, scope"""
        found = self.found
        known = [spread for spread in found.get("spreads", []) if spread >= 0]
        laps = int(found.get("laps", 0))
        if found.get("busy"):
            text = tr("Reading laps...")
        elif not known:
            text = tr("3 clean laps or more needed")
        else:
            text = trm(f"Spread of mini-sector times over {laps} laps")
        legend: dict = {"consistency": True, "scope": self._scope, "text": text,
                        "colors": [color.name() for color in lap_map.CONSISTENCY_COLORS]}
        if known:
            legend.update({"low": number_text(min(known), 2), "high": number_text(max(known), 2), "unit": "s"})
        return legend
