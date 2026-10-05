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
Lap viewer corners (mixin of LapViewerBackend): corner by corner comparison with reference lap, ideal lap, coaching,
official corner names, corner card
"""

from __future__ import annotations

import bisect
import math
import os
from collections import OrderedDict
from typing import Any

from PySide6.QtCore import Slot

from ...i18n import tr, trm
from ...setting import cfg
from ...userfile.corner_analysis import (
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
)
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
from .lap_base import COLOR_GAIN, COLOR_LOSS, BackendBase, keys_match

CORNER_SORTS = ("track", "loss")


class CornerTable(BackendBase):
    """Corner table of lap viewer page"""

    # Corners
    def compared_lap(self) -> PlotLap | None:
        """Lap compared corner by corner & on gain map: chosen lap if shown, else first compared lap"""
        compared = self.data.compared()
        return next((lap for lap in compared if lap.key == self._compare_key), compared[0] if compared else None)

    @Slot(str)
    def setCompareKey(self, key: str):
        if key != self._compare_key:
            self._compare_key = key
            self.build_corners()
            if self._map:
                self._map["corners"] = self.map_corner_points()
                self._map["sectors"] = self.map_sector_labels()
                if self._map_mode in ("gain", "line"):
                    self.build_colored_line(self._map_view[2])
                    self.bump_revision()
            self.chartChanged.emit()

    @Slot(str)
    def setCornerSort(self, sort: str):
        if sort in CORNER_SORTS and sort != self._corner_sort:
            self._corner_sort = sort
            save_viewer_setting(self.folder, corner_sort=sort)
            self.build_corners()
            self.chartChanged.emit()

    def build_corners(self):
        """Corner by corner comparison of chosen compared lap with reference lap

        Time: positive = compared lap slower. Braking: positive = brakes later.
        Full throttle: negative = full throttle earlier.
        """
        reference = self.data.reference.data if self.data.reference else None
        compared_lap = self.compared_lap()
        other = compared_lap.data if compared_lap is not None else None
        scales = tuple(self.data.scale_of(lap) for lap in self.data.laps)
        key = (reference, other, self._hysteresis, tuple(lap.data for lap in self.data.laps), scales,
               tuple(lap.clean and lap.comparable for lap in self.data.laps))
        if not keys_match(self._corner_key, key):
            self._corner_key = key
            self._corner_rows = compare_corners(
                self.resampled(self.data.reference), self.resampled(compared_lap) if compared_lap is not None else None,
                self._hysteresis) if self.data.reference is not None else []
            self._ideal = self.clean_ideal_lap()
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

        def faster_is_better(ref_value: float, other_value: float) -> str:
            if other_value - ref_value >= 1:
                return COLOR_GAIN
            if ref_value - other_value >= 1:
                return COLOR_LOSS
            return ""

        best_of = self.corner_best_laps()
        rows = []
        for index, row in enumerate(self._corner_rows):
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
        if self._corner_sort == "loss":
            rows.sort(key=lambda item: -item["bar"])
        if reference is not None and other is not None and self._corner_rows:  # corners + straights = lap delta
            for text, kind, delta in ((tr("Straights"), "sum", straights_delta(self._corner_rows, reference, other)),
                                      (tr("Total"), "total", lap_time_delta(reference, other))):
                rows.append({"index": -1, "label": text, "apex": "", "kind": kind, "time": signed(delta, 2),
                             "timeColor": judged(delta), "bar": delta})
        if self._ideal is not None and reference is not None:
            gap = self._ideal.time - reference.lap_time
            rows.append({"index": -1, "label": tr("Ideal Lap"), "apex": "", "speed": format_laptime(self._ideal.time),
                         "speedColor": "", "kind": "ideal", "time": signed(gap, 2), "timeColor": judged(gap),
                         "bar": gap})
        self._corners = rows
        self.build_coaching()
        self.build_corner_marks()

    def clean_ideal_lap(self) -> IdealLap | None:
        """Ideal lap (fastest lap in each corner & straight) among clean shown laps: invalid, out & in laps
        (cut track) & laps of another circuit never count; best lap indexes are shown lap indexes"""
        clean = [index for index, lap in enumerate(self.data.laps) if lap.clean and lap.comparable]
        found = ideal_lap([self.resampled(self.data.laps[index]) for index in clean],
                          [row.corner for row in self._corner_rows])
        if found is None:
            return None
        return found._replace(best=[clean[position] for position in found.best])

    def build_coaching(self):
        """Corners where compared lap loses most time against reference lap & likely causes (corner table)"""
        convert, unit = self.data.units["speed"]

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
            {"index": tip.row, "label": self.row_label(self._corner_rows[tip.row]), "loss": signed(tip.loss, 2, " s"),
             "causes": [texts[kind](value) for kind, value in tip.causes[:3]]
             or [tr("No clear cause: compare traces of this corner")]}
            for tip in coaching_tips(self._corner_rows)
        ]

    def corner_best_laps(self) -> dict[int, str]:
        """Fastest lap through each corner (ideal lap), corner row index: short lap name"""
        ideal = self._ideal
        if ideal is None:
            return {}
        result = {}
        for index, row in enumerate(self._corner_rows):
            if row.corner.start in ideal.bounds:
                part = ideal.bounds.index(row.corner.start)
                if part < len(ideal.best):
                    result[index] = self.short_label(self.data.laps[ideal.best[part]].key)
        return result

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
        """Official corners of circuit placed on reference line (or track map file), once per reference lap"""
        reference = self.data.reference
        key = (reference.data if reference is not None else None, self.track_name())
        if self._official_key is not None and keys_match(self._official_key, key):
            return
        self._official_key = key
        self._official, self._official_numbered = [], True
        if reference is None:
            return
        line = self.lap_line(reference)
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
            if self._map:
                self._map["corners"] = self.map_corner_points()
                self._map["points"] = self.map_driving_points()
                self._band_cache = OrderedDict()
                self._band_generation += 1
                self._preview_step = math.nan
                self._band_cache_applied = False
                self.build_map_bands()
                self.bump_revision()
            self.chartChanged.emit()

    def lap_corner_stats(self, lap: PlotLap) -> tuple[ResampledLap, list[CornerStats | None]]:
        """Driving of lap in each corner found on reference lap, computed again only if laps or corners changed"""
        key = (lap.data, self._corner_key, self.data.scale_of(lap))
        cached = self._lap_corners.get(lap.key)
        if cached is None or not keys_match(cached[0], key):
            sampled = self.resampled(lap)
            cached = (key, sampled, [corner_stats(sampled, row.corner) for row in self._corner_rows])
            self._lap_corners = {name: value for name, value in self._lap_corners.items()
                                 if name in {shown.key for shown in self.data.laps}}
            self._lap_corners[lap.key] = cached
        return cached[1], cached[2]

    def resampled(self, lap: PlotLap) -> ResampledLap:
        """Lap columns on corner grid, resampled once per loaded lap (columns resampled at first use)"""
        scale = self.data.scale_of(lap)
        cached = self._resampled.get(lap.key)
        if cached is None or cached.lap is not lap.data or cached.scale != scale:
            cached = ResampledLap(lap.data, scale=scale)
            shown = {shown_lap.key for shown_lap in self.data.laps}
            self._resampled = {name: value for name, value in self._resampled.items() if name in shown}
            self._resampled[lap.key] = cached
        return cached

    def lap_trackouts(self, lap: PlotLap, stats: list[CornerStats | None], turns: dict[int, float],
                      reference_line: lap_map.MapLine) -> dict[int, float]:
        """Track-out point of lap in each corner (reference distance), computed once per lap, corners & edges"""
        scale = self.data.scale_of(lap)
        reference = self.data.reference
        key = (lap.data, reference.data if reference is not None else None, self._limits, self._corner_key, scale,
               self._edges)
        cached = self._trackouts.get(lap.key)
        if cached is not None and keys_match(cached[0], key):
            return cached[1]
        placed = self.lap_offsets(lap)  # offsets from base line, edges along it: no line search again
        found: dict[int, float] = {}
        if placed is not None and placed[1] and self._edges[0]:
            line, sides, indexes = placed
            for index, row in enumerate(self._corner_rows):
                stat = stats[index]
                if stat is None or index not in turns:
                    continue
                distance = lap_map.trackout_from_offsets(line.distances, sides, indexes, self._edges,
                                                         stat.apex / scale, row.corner.end / scale,
                                                         turns[index])
                found[index] = distance * scale if distance >= 0 else -1.0
        shown = {shown_lap.key for shown_lap in self.data.laps}
        self._trackouts = {name: value for name, value in self._trackouts.items() if name in shown}
        self._trackouts[lap.key] = (key, found)
        return found

    @Slot(int, result=dict)
    def cornerCard(self, index: int) -> dict:
        """Every shown lap in corner (row of corner table): time, gap, speeds, braking & throttle points"""
        if not 0 <= index < len(self._corner_rows) or self.data.reference is None:
            return {}
        row = self._corner_rows[index]
        convert, unit = self.data.units["speed"]

        def speed(value: float) -> str:
            return f"{convert(value) if convert else value:.0f}"

        reference = self.lap_corner_stats(self.data.reference)[1][index]
        reference_line = self.lap_line(self.data.reference)
        turn = 0.0
        if reference_line is not None and len(reference_line.xs) > 2:
            turn = lap_map.turning(reference_line, min(bisect.bisect_left(reference_line.distances, row.corner.apex),
                                                       len(reference_line.xs) - 1))

        def room(lap: PlotLap, distance: float, inside: bool) -> str:
            """Room left to inside (apex) or outside edge (entry, exit), meters (distance: reference distance)"""
            found = self.lap_placement(lap, distance / self.data.scale_of(lap)) if distance >= 0 else None
            if found is None:
                return "—"
            left, right, _ = found
            value = (left if turn > 0 else right) if inside else (right if turn > 0 else left)
            return number_text(value * distance_unit()[0], 1)

        laps = []
        brakes = []
        for lap in self.data.laps:
            stats = self.lap_corner_stats(lap)[1][index]
            if stats is None:
                continue
            if stats.brake_point >= 0:
                brakes.append(stats.brake_point)
            gap = stats.time - reference.time if reference is not None and lap is not self.data.reference else None
            laps.append({
                "label": self.short_label(lap.key), "color": lap.color.name(),
                "time": f"{number_text(stats.time, 2)} s", "gap": signed(gap, 2) if gap is not None else "",
                "gapColor": COLOR_LOSS if gap is not None and gap > 0.005 else COLOR_GAIN if gap is not None
                and gap < -0.005 else "",
                "speeds": f"{speed(stats.entry_speed)} → {speed(stats.min_speed)} "
                          f"→ {speed(stats.exit_speed)} {unit}",  # entry, minimum, exit
                "brake": distance_text(stats.brake_point) if stats.brake_point >= 0 else "—",
                "throttle": distance_text(stats.throttle_point) if stats.throttle_point >= 0 else "—",
                # Room to edge: outside at braking point, inside at apex, outside at full throttle
                "width": (f"{room(lap, stats.brake_point, False)} → {room(lap, stats.apex, True)} → "
                          f"{room(lap, stats.throttle_point, False)} {distance_unit()[1]}") if self._edges[0] else "",
            })
        spread = max(brakes) - min(brakes) if len(brakes) > 1 else -1.0
        return {"title": self.row_label(row), "apex": distance_text(row.corner.apex), "laps": laps,
                "spread": trm(f"Braking points spread: {distance_text(spread)}") if spread >= 0 else "",
                "widthTitle": tr("Room to edge: outside at braking, inside at apex, outside at exit")
                if self._edges[0] else ""}
