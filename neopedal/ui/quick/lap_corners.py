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
Lap viewer corners (part of LapViewerBackend, QML backend.cornerTable): corner by corner comparison with reference lap, ideal lap, coaching,
official corner names, corner card
"""

from __future__ import annotations

import bisect
import os
from typing import TYPE_CHECKING, Any, Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot

from ...i18n import tr, trm
from ...setting import cfg
from ...userfile.corner_analysis import (
    SPEED_HYSTERESIS,
    CornerComparison,
    CornerStats,
    IdealLap,
    ResampledLap,
    coaching_tips,
    compare_corners,
    corner_stats,
    ideal_lap,
    lap_time_delta,
    straights_delta,
    total_lap_time,
)
from ...userfile.corner_coach import corner_name, official_inside, official_text
from ...userfile.telemetry_lap import LapData
from ...userfile.track_corners import TrackCorner, track_corners
from ...userfile.track_map import load_track_map_file
from ..lap_viewer import (
    PlotLap,
    corner_label,
    distance_text,
    distance_unit,
    format_laptime,
    number_text,
    save_viewer_setting,
    signed,
)
from . import lap_map
from .lap_base import COLOR_GAIN, COLOR_LOSS, PagePart, keys_match, weak_host
from .models import DictListModel

if TYPE_CHECKING:
    from PySide6.QtCore import SignalInstance

    from .trace_data import TraceData

CORNER_ROLES = (
    "id", "index", "label", "apex", "kind", "best", "time", "timeColor", "bar", "speed", "speedColor", "brake",
    "throttle", "trail", "coast", "overlap", "coastColor", "overlapColor", "entry", "exit", "entryColor", "exitColor",
    "gear", "peakBrake",
)

CORNER_SORTS = ("track", "loss")
SUM_LENGTH_TOLERANCE = 0.1  # compared lap length difference (fraction) over which Straights & Total rows are left out


class CornerHost(Protocol):
    """What the corner table part uses of the lap viewer page"""

    data: TraceData
    folder: str

    @property
    def cornersChanged(self) -> SignalInstance: ...
    def short_label(self, key: str) -> str: ...
    def lap_line(self, lap: PlotLap) -> lap_map.MapLine | None: ...
    def lap_offsets(self, lap: PlotLap) -> tuple[lap_map.MapLine, list[float], list[int]] | None: ...
    def lap_placement(self, lap: PlotLap, distance: float) -> tuple[float, float, float] | None: ...
    def track_limits(self) -> lap_map.TrackLimits | None: ...
    def track_edges(self) -> tuple[list[float], list[float]]: ...
    def compared_changed(self): ...
    def corners_found(self): ...


class CornerTable(PagePart):
    """Corner table of lap viewer page (QML backend.cornerTable): corner by corner comparison with reference lap"""

    changed = Signal()  # corner rows, sort, sensitivity, compared lap (page cornersChanged)
    focusRequestChanged = Signal()
    summaryChanged = Signal()  # synthesis band under lap chips (sent only when its texts change)

    def __init__(self, page: CornerHost, setting: dict, parent: QObject | None = None):
        super().__init__(parent)
        self._page = weak_host(page)
        self._focus = -1  # corner row charts zoom on once the corner list shows (see request_focus), -1 if none
        self.row_model = DictListModel(CORNER_ROLES, self)  # corner table rows (kept while their corner stays)
        self._table: list[dict] = []  # corner table rows
        self._marks: list[dict] = []  # corner numbers on charts
        self.rows: list[CornerComparison] = []  # corners of reference lap compared
        self.key: tuple = ()  # laps & sensitivity of corner rows (computed again only if changed)
        self.ideal: IdealLap | None = None
        self._lap_corners: dict[str, tuple[tuple, ResampledLap, list[CornerStats | None]]] = {}  # stats of each lap
        self._trackouts: dict[str, tuple[tuple, dict[int, float]]] = {}  # lap key: (key, track-out point by corner)
        self._resampled: dict[str, ResampledLap] = {}  # lap key: columns on corner grid (same lap, same object)
        self._coaching: list[dict] = []  # corners where compared lap loses most time, causes
        self._summary: dict = {}  # synthesis band: compared & reference lap, total gap, worst corners (see summary)
        self.official: list[TrackCorner] = []  # official corner numbers (or names) of circuit
        self.official_numbered = True
        self._official_key: tuple | None = None  # reference & track of placed official corners
        self.compare_key = ""  # lap compared corner by corner & on gain map, first compared lap if not shown
        saved = setting.get("corner_hysteresis", SPEED_HYSTERESIS)
        self._hysteresis = int(saved) if isinstance(saved, (int, float)) else int(SPEED_HYSTERESIS)
        sort = setting.get("corner_sort", "track")
        self._sort = sort if sort in CORNER_SORTS else "track"
        page.cornersChanged.connect(self.changed)

    """Corner table of lap viewer page"""

    # Corners
    @Property(QObject, constant=True)
    def model(self) -> QObject:
        """Corner table rows (see items), rows kept while their corner stays: QML keeps their items"""
        return self.row_model

    @Property(int, notify=changed)
    def count(self) -> int:
        """Corners found on reference lap (ranges length, without building it)"""
        return len(self.rows)

    @Property(float, notify=changed)
    def maxDelta(self) -> float:
        """Largest corner time delta (bars of corner table scaled on it), at least 0.05 s"""
        return max((abs(row["bar"]) for row in self._table if row["kind"] == "corner"), default=0.0) or 0.05

    @Slot(int, result=int)
    def position(self, index: int) -> int:
        """Corner table row of corner (shown when selected on map), -1 if none"""
        return next((number for number, row in enumerate(self._table)
                     if row["kind"] == "corner" and row["index"] == index), -1)

    @Property(int, notify=focusRequestChanged)
    def focusRequest(self) -> int:
        """Corner row asked from elsewhere (Home page debrief), -1 if none: the corner list zooms charts on it"""
        return self._focus

    def request_focus(self, index: int):
        """Charts zoomed on corner row once the corner list shows (now if shown)"""
        self._focus = index
        self.focusRequestChanged.emit()

    @Slot(result=int)
    def takeFocus(self) -> int:
        """Corner row asked, then forgotten (zoomed on once), -1 if none"""
        index, self._focus = self._focus, -1
        if index >= 0:
            self.focusRequestChanged.emit()
        return index

    @Property(list, notify=changed)
    def marks(self) -> list[dict]:
        """Corner numbers on charts"""
        return self._marks

    @Property(list, notify=changed)
    def items(self) -> list[dict]:
        """Corner table rows"""
        return self._table

    @Property(int, notify=changed)
    def hysteresis(self) -> int:
        return self._hysteresis

    @Property(str, notify=changed)
    def compareKey(self) -> str:
        lap = self.compared_lap()
        return lap.key if lap is not None else ""

    @Property(str, notify=changed)
    def sort(self) -> str:
        return self._sort

    @Property(list, notify=changed)
    def coaching(self) -> list[dict]:
        """Corners where compared lap loses most time (up to 3): row index, name, time lost, causes"""
        return self._coaching

    @Property(dict, notify=summaryChanged)
    def summary(self) -> dict:
        """Synthesis band under lap chips, {} without compared lap: lap & reference names, total gap (tone: loss,
        gain or ""), worst corners (coaching rows: row index, name, time lost, causes)"""
        return self._summary

    @Property(str, notify=changed)
    def coachingLap(self) -> str:
        lap = self.compared_lap()
        return self._page.short_label(lap.key) if lap is not None else ""

    @Property(list, notify=changed)
    def ranges(self) -> list[list[float]]:
        """Axis range of every corner in lap order (previous / next corner keys)"""
        return [self.range(index) for index in range(len(self.rows))]

    def table(self) -> list[dict]:
        """Corner table rows (see items)"""
        return self._table

    def coaching_rows(self) -> list[dict]:
        """Coaching tips (see coaching)"""
        return self._coaching

    def sensitivity(self) -> int:
        """Speed hysteresis corners are found with (see hysteresis)"""
        return self._hysteresis

    def forget(self):
        """Results kept per loaded lap forgotten (they keep lap data in memory)"""
        for cache in (self._lap_corners, self._trackouts, self._resampled):
            cache.clear()
        self.key = ()
        self.rows = []
        self.ideal = None
        self._official_key = None

    def release(self):
        self.forget()
        self._table, self._marks, self._coaching = [], [], []
        self.set_summary({})

    def compared_lap(self) -> PlotLap | None:
        """Lap compared corner by corner & on gain map: chosen lap if shown, else first compared lap"""
        compared = self._page.data.compared()
        return next((lap for lap in compared if lap.key == self.compare_key), compared[0] if compared else None)

    @Slot(str)
    def setCompareKey(self, key: str):
        if key != self.compare_key:
            self.compare_key = key
            self.build_corners()
            self._page.compared_changed()
            self._page.cornersChanged.emit()

    @Slot(str)
    def setSort(self, sort: str):
        if sort in CORNER_SORTS and sort != self._sort:
            self._sort = sort
            save_viewer_setting(self._page.folder, corner_sort=sort)
            self.build_corners()
            self._page.cornersChanged.emit()

    def build_corners(self):
        """Corner by corner comparison of chosen compared lap with reference lap

        Time: positive = compared lap slower. Braking: positive = brakes later.
        Full throttle: negative = full throttle earlier.
        """
        reference = self._page.data.reference.data if self._page.data.reference else None
        compared_lap = self.compared_lap()
        other = compared_lap.data if compared_lap is not None else None
        scales = tuple(self._page.data.scale_of(lap) for lap in self._page.data.laps)
        key = (reference, other, self._hysteresis, tuple(lap.data for lap in self._page.data.laps), scales,
               tuple(lap.clean for lap in self._page.data.laps))
        if not keys_match(self.key, key):
            self.key = key
            self.rows = compare_corners(
                self.resampled(self._page.data.reference), self.resampled(compared_lap) if compared_lap is not None else None,
                self._hysteresis) if self._page.data.reference is not None else []
            self.ideal = self.clean_ideal_lap()
        convert = self._page.data.units["speed"][0]

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

        def faster_is_better(ref_value: float, other_value: float) -> str:
            if other_value - ref_value >= 1:
                return COLOR_GAIN
            if ref_value - other_value >= 1:
                return COLOR_LOSS
            return ""

        best_of = self.corner_best_laps()
        rows = []
        for index, row in enumerate(self.rows):
            ref, comp = row.reference, row.compared
            item: dict[str, Any] = {
                "index": index, "label": self.row_label(row), "apex": distance_text(row.corner.apex),
                "kind": "corner", "best": best_of.get(index, ""),
            }
            if comp is None:  # reference lap values only
                item.update({
                    "time": f"{number_text(ref.time, 2)} s", "timeColor": "", "bar": 0.0,
                    "speed": f"{speed(ref.min_speed):.0f}",
                    "speedColor": "", "brake": distance_text(ref.brake_point) if ref.brake_point >= 0 else "—",
                    "throttle": distance_text(ref.throttle_point) if ref.throttle_point >= 0 else "—",
                    "trail": f"{number_text(ref.trail_braking, 1)} s", "coast": f"{number_text(ref.coasting, 1)} s",
                    "overlap": f"{number_text(ref.overlap, 1)} s", "coastColor": "", "overlapColor": "",
                    "entry": f"{speed(ref.entry_speed):.0f}", "exit": f"{speed(ref.exit_speed):.0f}",
                    "entryColor": "", "exitColor": "",
                    "gear": str(ref.apex_gear) if ref.apex_gear else "—", "peakBrake": f"{ref.peak_brake * 100:.0f}%",
                })
            else:
                delta = comp.time - ref.time
                speed_delta = speed(comp.min_speed) - speed(ref.min_speed)
                item.update({
                    "time": signed(delta, 2), "timeColor": judged(delta), "bar": delta,
                    "speed": f"{speed(ref.min_speed):.0f} / {speed(comp.min_speed):.0f}",
                    "speedColor": COLOR_GAIN if speed_delta >= 1 else COLOR_LOSS if speed_delta <= -1 else "",
                    "brake": distance_text(comp.brake_point - ref.brake_point, sign=True)
                    if ref.brake_point >= 0 and comp.brake_point >= 0 else "—",
                    "throttle": distance_text(comp.throttle_point - ref.throttle_point, sign=True)
                    if ref.throttle_point >= 0 and comp.throttle_point >= 0 else "—",
                    # Driving: trail braking (no judgement), coasting & overlap (more = time lost)
                    "trail": f"{number_text(ref.trail_braking, 1)} / {number_text(comp.trail_braking, 1)} s",
                    "coast": f"{number_text(ref.coasting, 1)} / {number_text(comp.coasting, 1)} s",
                    "overlap": f"{number_text(ref.overlap, 1)} / {number_text(comp.overlap, 1)} s",
                    "coastColor": more_is_worse(ref.coasting, comp.coasting),
                    "overlapColor": more_is_worse(ref.overlap, comp.overlap),
                    "entry": f"{speed(ref.entry_speed):.0f} / {speed(comp.entry_speed):.0f}",
                    "exit": f"{speed(ref.exit_speed):.0f} / {speed(comp.exit_speed):.0f}",
                    "entryColor": faster_is_better(speed(ref.entry_speed), speed(comp.entry_speed)),
                    "exitColor": faster_is_better(speed(ref.exit_speed), speed(comp.exit_speed)),
                    "gear": f"{ref.apex_gear or '—'} / {comp.apex_gear or '—'}",
                    "peakBrake": f"{ref.peak_brake * 100:.0f} / {comp.peak_brake * 100:.0f}%",
                })
            rows.append(item)
        if self._sort == "loss":
            rows.sort(key=lambda item: -item["bar"])
        if reference is not None and other is not None and self.sums_comparable(reference, other):
            for text, kind, delta in ((tr("Straights"), "sum", straights_delta(self.rows, reference, other)),
                                      (tr("Total"), "total", lap_time_delta(reference, other))):
                rows.append({"index": -1, "label": text, "apex": "", "kind": kind, "time": signed(delta, 2),
                             "timeColor": judged(delta), "bar": delta})
        if self.ideal is not None and reference is not None:
            gap = self.ideal.time - total_lap_time(reference)  # same lap time as ideal lap parts & Total row
            rows.append({"index": -1, "label": tr("Ideal Lap"), "apex": "", "speed": format_laptime(self.ideal.time),
                         "speedColor": "", "kind": "ideal", "time": signed(gap, 2), "timeColor": judged(gap),
                         "bar": gap})
        self._table = rows
        self.row_model.sync([{**row, "id": f"{row['kind']}|{row['index']}"} for row in rows], "id")
        self.build_coaching()
        self.build_summary(reference, compared_lap)
        self.build_corner_marks()

    def build_summary(self, reference: LapData | None, compared: PlotLap | None):
        """Synthesis band: total gap of compared lap to reference lap & its worst corners (coaching rows), sent only
        when its texts change (charts rebuilt with the same laps: band items kept)"""
        summary: dict = {}
        if reference is not None and compared is not None and self._page.data.reference is not None:
            gap = lap_time_delta(reference, compared.data)
            summary = {
                "lap": self._page.short_label(compared.key), "lapKey": compared.key,
                "reference": self._page.short_label(self._page.data.reference.key),
                "gap": signed(gap, 3, " s"), "tone": "loss" if gap > 0.0005 else "gain" if gap < -0.0005 else "",
                "corners": self._coaching,
            }
        self.set_summary(summary)

    def set_summary(self, summary: dict):
        if summary != self._summary:
            self._summary = summary
            self.summaryChanged.emit()

    def lost_corners(self) -> list[int]:
        """Corner rows where compared lap loses most time, worst first (guided analysis)"""
        return [tip["index"] for tip in self._coaching]

    def sums_comparable(self, reference: LapData, other: LapData) -> bool:
        """Whether corners + straights = lap delta rows mean something: compared lap has stats in every corner & about
        the same length (else straights take time of missing corners, or of a stub lap)"""
        if not self.rows or any(row.compared is None for row in self.rows):
            return False
        length, other_length = max(reference.distance, default=0.0), max(other.distance, default=0.0)
        return length > 0 and abs(other_length / length - 1) <= SUM_LENGTH_TOLERANCE

    def clean_ideal_lap(self) -> IdealLap | None:
        """Ideal lap (fastest lap in each corner & straight) among clean shown laps: invalid, out & in laps
        (cut track) never count; best lap indexes are shown lap indexes"""
        clean = [index for index, lap in enumerate(self._page.data.laps) if lap.clean]
        found = ideal_lap([self.resampled(self._page.data.laps[index]) for index in clean],
                          [row.corner for row in self.rows])
        if found is None:
            return None
        return found._replace(best=[clean[position] for position in found.best])

    def build_coaching(self):
        """Corners where compared lap loses most time against reference lap & likely causes (corner table)"""
        convert, unit = self._page.data.units["speed"]

        def speed(value: float) -> float:
            return convert(value) if convert is not None else value

        texts = {
            "brake_early": lambda value: trm(f"Brakes {distance_text(value)} earlier"),
            "brake_late": lambda value: trm(f"Brakes {distance_text(value)} later, runs wide"),
            "min_speed": lambda value: trm(f"Minimum speed {speed(value):.0f} {unit} lower"),
            "throttle_late": lambda value: trm(f"Full throttle {distance_text(value)} later"),
            "coasting": lambda value: trm(f"Coasting {number_text(value, 1)} s longer"),
            "overlap": lambda value: trm(f"Throttle & brake together {number_text(value, 1)} s longer"),
            "exit_speed": lambda value: trm(f"Exit speed {speed(value):.0f} {unit} lower"),
        }
        self._coaching = [
            {"index": tip.row, "label": self.row_label(self.rows[tip.row]), "loss": signed(tip.loss, 2, " s"),
             "causes": [texts[kind](value) for kind, value in tip.causes[:3]]
             or [tr("No clear cause: compare traces of this corner")]}
            for tip in coaching_tips(self.rows)
        ]

    def corner_best_laps(self) -> dict[int, str]:
        """Fastest lap through each corner (ideal lap), corner row index: short lap name"""
        ideal = self.ideal
        if ideal is None:
            return {}
        result = {}
        for index, row in enumerate(self.rows):
            if row.corner.start in ideal.bounds:
                part = ideal.bounds.index(row.corner.start)
                if part < len(ideal.best):
                    result[index] = self._page.short_label(self._page.data.laps[ideal.best[part]].key)
        return result

    def build_corner_marks(self):
        """Corner numbers on charts: official corners of circuit, else corners found on reference lap"""
        if self.official:
            self._marks = [
                {"x": self._page.data.x_at_distance(corner.distance), "label": self.official_text(corner.label),
                 "distance": corner.distance}
                for corner in self.official
            ]
            return
        self._marks = [
            {"x": self._page.data.x_at_distance(row.corner.apex), "label": corner_label(row.corner.number),
             "distance": row.corner.apex}
            for row in self.rows
        ]

    # Official corners
    def track_name(self) -> str:
        """Track of displayed laps, from lap info or older lap files folder ("<track> - <class>")"""
        laps = self._page.data.laps
        if not laps:
            return ""
        track = str(laps[0].data.meta.get("track", ""))
        return track or os.path.basename(os.path.dirname(laps[0].key)).rsplit(" - ", 1)[0]

    def build_official(self):
        """Official corners of circuit placed on reference line (or track map file), once per reference lap"""
        reference = self._page.data.reference
        key = (reference.data if reference is not None else None, self.track_name())
        if self._official_key is not None and keys_match(self._official_key, key):
            return
        self._official_key = key
        self.official, self.official_numbered = [], True
        if reference is None:
            return
        line = self._page.lap_line(reference)
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
        self.official, self.official_numbered = track_corners(self.track_name(), distances, xs, ys)

    def official_text(self, label: str) -> str:
        """Official corner shown: "T5" ("V5" in French), or translated name"""
        return official_text(label, self.official_numbered)

    def official_in(self, row: CornerComparison) -> list[TrackCorner]:
        """Official corners inside corner found on reference lap"""
        return official_inside(self.official, row.corner.start, row.corner.end)

    def row_label(self, row: CornerComparison) -> str:
        """Corner found on reference lap named after official corners it covers: "T5", "T5-6" """
        if not self.official:
            return corner_label(row.corner.number)
        corner = row.corner
        return corner_name(self.official, self.official_numbered, corner.start, corner.apex, corner.end) or "—"

    @Slot(int, result=list)
    def range(self, index: int) -> list[float]:
        """Axis range of corner (zoom on it)"""
        if not 0 <= index < len(self.rows):
            return []
        corner = self.rows[index].corner
        return [self._page.data.x_at_distance(corner.start), self._page.data.x_at_distance(corner.end)]

    @Slot(int)
    def setHysteresis(self, value: int):
        if value != self._hysteresis:
            self._hysteresis = value
            save_viewer_setting(self._page.folder, corner_hysteresis=value)
            self.build_corners()
            self._page.corners_found()
            self._page.cornersChanged.emit()

    def lap_corner_stats(self, lap: PlotLap) -> tuple[ResampledLap, list[CornerStats | None]]:
        """Driving of lap in each corner found on reference lap, computed again only if laps or corners changed"""
        key = (lap.data, self.key, self._page.data.scale_of(lap))
        cached = self._lap_corners.get(lap.key)
        if cached is None or not keys_match(cached[0], key):
            sampled = self.resampled(lap)
            cached = (key, sampled, [corner_stats(sampled, row.corner) for row in self.rows])
            self._lap_corners = {name: value for name, value in self._lap_corners.items()
                                 if name in {shown.key for shown in self._page.data.laps}}
            self._lap_corners[lap.key] = cached
        return cached[1], cached[2]

    def resampled(self, lap: PlotLap) -> ResampledLap:
        """Lap columns on corner grid, resampled once per loaded lap (columns resampled at first use)"""
        scale = self._page.data.scale_of(lap)
        cached = self._resampled.get(lap.key)
        if cached is None or cached.lap is not lap.data or cached.scale != scale:
            cached = ResampledLap(lap.data, scale=scale)
            shown = {shown_lap.key for shown_lap in self._page.data.laps}
            self._resampled = {name: value for name, value in self._resampled.items() if name in shown}
            self._resampled[lap.key] = cached
        return cached

    def lap_trackouts(self, lap: PlotLap, stats: list[CornerStats | None], turns: dict[int, float],
                      reference_line: lap_map.MapLine) -> dict[int, float]:
        """Track-out point of lap in each corner (reference distance), computed once per lap, corners & edges"""
        scale = self._page.data.scale_of(lap)
        reference = self._page.data.reference
        key = (lap.data, reference.data if reference is not None else None, self._page.track_limits(), self.key, scale,
               self._page.track_edges())
        cached = self._trackouts.get(lap.key)
        if cached is not None and keys_match(cached[0], key):
            return cached[1]
        placed = self._page.lap_offsets(lap)  # offsets from base line, edges along it: no line search again
        found: dict[int, float] = {}
        if placed is not None and placed[1] and self._page.track_edges()[0]:
            line, sides, indexes = placed
            for index, row in enumerate(self.rows):
                stat = stats[index]
                if stat is None or index not in turns:
                    continue
                distance = lap_map.trackout_from_offsets(line.distances, sides, indexes, self._page.track_edges(),
                                                         stat.apex / scale, row.corner.end / scale,
                                                         turns[index])
                found[index] = distance * scale if distance >= 0 else -1.0
        shown = {shown_lap.key for shown_lap in self._page.data.laps}
        self._trackouts = {name: value for name, value in self._trackouts.items() if name in shown}
        self._trackouts[lap.key] = (key, found)
        return found

    @Slot(int, result=dict)
    def card(self, index: int) -> dict:
        """Every shown lap in corner (row of corner table): time, gap, speeds, braking & throttle points"""
        if not 0 <= index < len(self.rows) or self._page.data.reference is None:
            return {}
        row = self.rows[index]
        convert, unit = self._page.data.units["speed"]

        def speed(value: float) -> str:
            return f"{convert(value) if convert else value:.0f}"

        reference = self.lap_corner_stats(self._page.data.reference)[1][index]
        reference_line = self._page.lap_line(self._page.data.reference)
        turn = 0.0
        if reference_line is not None and len(reference_line.xs) > 2:
            turn = lap_map.turning(reference_line, min(bisect.bisect_left(reference_line.distances, row.corner.apex),
                                                       len(reference_line.xs) - 1))

        def room(lap: PlotLap, distance: float, inside: bool) -> str:
            """Room left to inside (apex) or outside edge (entry, exit), meters (distance: reference distance)"""
            found = self._page.lap_placement(lap, distance / self._page.data.scale_of(lap)) if distance >= 0 else None
            if found is None:
                return "—"
            left, right, _ = found
            value = (left if turn > 0 else right) if inside else (right if turn > 0 else left)
            return number_text(value * distance_unit()[0], 1)

        laps = []
        brakes = []
        for lap in self._page.data.laps:
            stats = self.lap_corner_stats(lap)[1][index]
            if stats is None:
                continue
            if stats.brake_point >= 0:
                brakes.append(stats.brake_point)
            gap = stats.time - reference.time if reference is not None and lap is not self._page.data.reference else None
            laps.append({
                "label": self._page.short_label(lap.key), "color": lap.color.name(),
                "time": f"{number_text(stats.time, 2)} s", "gap": signed(gap, 2) if gap is not None else "",
                "gapColor": COLOR_LOSS if gap is not None and gap > 0.005 else COLOR_GAIN if gap is not None
                and gap < -0.005 else "",
                "speeds": f"{speed(stats.entry_speed)} → {speed(stats.min_speed)} "
                          f"→ {speed(stats.exit_speed)} {unit}",  # entry, minimum, exit
                "brake": distance_text(stats.brake_point) if stats.brake_point >= 0 else "—",
                "throttle": distance_text(stats.throttle_point) if stats.throttle_point >= 0 else "—",
                # Room to edge: outside at braking point, inside at apex, outside at full throttle
                "width": (f"{room(lap, stats.brake_point, False)} → {room(lap, stats.apex, True)} → "
                          f"{room(lap, stats.throttle_point, False)} {distance_unit()[1]}") if self._page.track_edges()[0] else "",
            })
        spread = max(brakes) - min(brakes) if len(brakes) > 1 else -1.0
        return {"title": self.row_label(row), "apex": distance_text(row.corner.apex), "laps": laps,
                "spread": trm(f"Braking points spread: {distance_text(spread)}") if spread >= 0 else "",
                "widthTitle": tr("Room to edge: outside at braking, inside at apex, outside at exit")
                if self._page.track_edges()[0] else ""}
