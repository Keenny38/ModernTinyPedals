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
Lap viewer track map marks (part of LapViewerBackend, used by its track map): corner labels, driving points (braking,
apex, exit, track-out), off tracks & track limits, wheel lockups, wheelspin & bottoming, sector times

Built from the map lines of shown laps & corners of reference lap the page keeps (see MarksHost), placed in the
map data of the page (trackMap, mapCorners).
"""

from __future__ import annotations

import bisect
import math
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import QObject

from ...i18n import tr
from ...process.results_text import sector_text
from ...userfile.corner_analysis import CornerComparison, CornerStats, ResampledLap
from ...userfile.telemetry_lap import LapData, sector_times
from ..lap_viewer import CHANNEL_MAP, PlotLap, corner_label, distance_text, signed
from . import lap_map
from .lap_base import COLOR_GAIN, COLOR_LOSS, PagePart, format_diff, weak_host

if TYPE_CHECKING:
    from .lap_corners import CornerTable
    from .trace_data import TraceData

EVENT_TITLES = {"offtrack": "Off track", "limit": "Track limits exceeded"}


class MarksHost(Protocol):
    """What the map marks part uses of the lap viewer page"""

    data: TraceData
    _corner_table: CornerTable
    _map: dict
    _map_lines: list[tuple[lap_map.MapLine, PlotLap]]
    _edges: tuple[list[float], list[float]]

    def compared_lap(self) -> PlotLap | None: ...
    def corner_rows(self) -> list[CornerComparison]: ...
    def lap_corner_stats(self, lap: PlotLap) -> tuple[ResampledLap, list[CornerStats | None]]: ...
    def lap_events(self, lap: PlotLap) -> list[tuple[float, str]]: ...
    def lap_line(self, lap: PlotLap) -> lap_map.MapLine | None: ...
    def reference_map_line(self) -> lap_map.MapLine | None: ...
    def rotate_point(self, x: float, y: float) -> tuple[float, float]: ...
    def row_label(self, row: CornerComparison) -> str: ...
    def short_label(self, key: str) -> str: ...


class MapMarks(PagePart):
    """Corner labels & points of track map, built for the page map (not read by QML itself)"""

    def __init__(self, page: MarksHost, parent: QObject | None = None):
        super().__init__(parent)
        self._page = weak_host(page)
        self._slips: dict[str, tuple[LapData, list]] = {}  # lap key: lap data, wheel slip & bottoming events

    def release(self):
        self._slips = {}

    def forget(self):
        """Loaded laps released: events kept per lap forgotten (they keep lap data)"""
        self._slips.clear()

    def corner_points(self) -> list[dict]:
        """Corner labels at apex of reference line, with time lost or gained by compared lap

        Official corners of circuit when known (every corner, even flat out ones), else corners found
        on reference lap. Each label zooms charts on its corner (start & end distances).
        Labels with a time delta are drawn first when labels overlap (priority).
        """
        page = self._page
        if page._corner_table.official:
            return self.official_points()
        line = page.reference_map_line()
        if line is None or not page.corner_rows():
            return []
        return [self.corner_point(*lap_map.point_at(line, row.corner.apex), corner_label(row.corner.number), index, row,
                                  row.corner.start, row.corner.end, row.time_delta)
                for index, row in enumerate(page.corner_rows())]

    def official_points(self) -> list[dict]:
        """Official corners on map, time lost / gained of each corner found on reference lap shown on the official
        corner nearest to its apex

        A corner found that covers the official corner wins it over one only near it. A corner found without
        official corner left for it (none within 200 m, or taken) gets its own label at its apex.
        """
        page = self._page
        delta_on: dict[int, tuple[bool, CornerComparison]] = {}  # official corner index: covered, corner found
        loose: list[CornerComparison] = []  # corners found shown at their own apex
        for row in page.corner_rows():
            inside = page._corner_table.official_in(row)
            nearest = min(inside or page._corner_table.official, key=lambda corner: abs(corner.distance - row.corner.apex))
            index = page._corner_table.official.index(nearest)
            held = delta_on.get(index)
            if (inside or abs(nearest.distance - row.corner.apex) <= 200) and (held is None or (inside and not held[0])):
                if held is not None:  # corner only near the official corner: own label
                    loose.append(held[1])
                delta_on[index] = (bool(inside), row)
            else:
                loose.append(row)
        points = []
        for index, corner in enumerate(page._corner_table.official):
            held = delta_on.get(index)
            found = held[1] if held is not None else next(
                (row for row in page.corner_rows() if corner in page._corner_table.official_in(row)), None)
            start, end = (found.corner.start, found.corner.end) if found is not None else (
                corner.distance - 120, corner.distance + 120)
            points.append(self.corner_point(*page.rotate_point(corner.x, corner.y), page._corner_table.official_text(corner.label),
                                            index, found, start, end, held[1].time_delta if held is not None else None))
        line = page.reference_map_line()
        if line is not None:
            for row in loose:  # named like in corner table
                points.append(self.corner_point(*lap_map.point_at(line, row.corner.apex), page.row_label(row),
                                                len(points), row, row.corner.start, row.corner.end, row.time_delta))
        return points

    def corner_point(self, x: float, y: float, label: str, index: int, row: CornerComparison | None, start: float,
                     end: float, delta: float | None) -> dict:
        """Corner label on map: position, name, corner row (-1 if none), range zoomed on click, time delta"""
        page = self._page
        return {
            "x": x, "y": y, "label": label, "index": index,
            "row": page.corner_rows().index(row) if row is not None else -1,
            "start": start, "end": end,
            "delta": signed(delta, 2) if delta is not None else "",
            "deltaColor": COLOR_LOSS if delta is not None and delta > 0.005
            else COLOR_GAIN if delta is not None and delta < -0.005 else "",
            "priority": abs(delta) if delta is not None else 0.0,
        }

    def driving_points(self) -> list[dict]:
        """Braking, apex (minimum speed) & exit (full throttle) points of each lap in each corner

        Each point tells its corner, speed & distance, and differences with reference lap.
        """
        page = self._page
        if not page._map_lines or not page.corner_rows() or page.data.reference is None:
            return []
        convert, unit = page.data.units["speed"]
        speed_channel = CHANNEL_MAP["speed_kph"]
        reference_sampled, reference_stats = page.lap_corner_stats(page.data.reference)
        titles = {"brake": tr("Braking"), "apex": tr("Apex"), "exit": tr("Exit (full throttle)"),
                  "trackout": tr("Track-out (outside edge)")}
        lefts = page._edges[0]  # track edges known
        reference_line = page.lap_line(page.data.reference)
        turns: dict[int, float] = {}  # turning direction at each corner apex (reference line)
        reference_trackouts: dict[int, float] = {}  # track-out point of reference lap in each corner
        if lefts and reference_line is not None:
            for index, row in enumerate(page.corner_rows()):
                turns[index] = lap_map.turning(reference_line, min(bisect.bisect_left(
                    reference_line.distances, row.corner.apex), len(reference_line.xs) - 1))
            reference_trackouts = page._corner_table.lap_trackouts(page.data.reference, reference_stats, turns, reference_line)
        points = []
        for order, (line, lap) in enumerate(page._map_lines):
            sampled, lap_stats = page.lap_corner_stats(lap)
            is_reference = lap is page.data.reference
            name = page.short_label(lap.key)
            scale = page.data.scale_of(lap)  # corner stats in reference distances, map line in lap distances
            trackouts = page._corner_table.lap_trackouts(lap, lap_stats, turns, reference_line) \
                if turns and reference_line is not None else {}
            for index, row in enumerate(page.corner_rows()):
                stats, reference = lap_stats[index], reference_stats[index]
                if stats is None:
                    continue
                corner = page.row_label(row)
                trackout = trackouts.get(index, -1.0)
                reference_trackout = reference_trackouts.get(index, -1.0)
                for kind, distance, reference_distance in (
                    ("brake", stats.brake_point, reference.brake_point if reference else -1.0),
                    ("apex", stats.apex, reference.apex if reference else -1.0),
                    ("exit", stats.throttle_point, reference.throttle_point if reference else -1.0),
                    ("trackout", trackout, reference_trackout),
                ):
                    if distance < 0:
                        continue
                    speed = sampled.value_at("speed_kph", distance) or 0.0
                    shown_speed = convert(speed) if convert else speed
                    lines = [f"{shown_speed:.0f} {unit}", distance_text(distance)]
                    if not is_reference and reference_distance >= 0:
                        reference_speed = reference_sampled.value_at("speed_kph", reference_distance) or 0.0
                        reference_shown = convert(reference_speed) if convert else reference_speed
                        lines[0] += f" ({format_diff(speed_channel, shown_speed - reference_shown)})"
                        lines[1] += f" ({distance_text(distance - reference_distance, sign=True)})"
                    x, y = lap_map.point_at(line, distance / scale)
                    points.append({
                        "x": x, "y": y, "kind": kind, "color": lap.color.name(), "lap": lap.key, "corner": index,
                        "distance": distance,
                        "order": order,  # lap position (speed labels of laps stacked)
                        "angle": math.degrees(lap_map.heading_at(line, distance / scale)), "value": f"{shown_speed:.0f}",
                        "tip": f"{name} · {corner} · {titles[kind]}\n" + " · ".join(lines),
                    })
        return points

    def event_points(self) -> list[dict]:
        """Off track & track limits points of each shown lap on map"""
        page = self._page
        points = []
        for line, lap in page._map_lines:
            name = page.short_label(lap.key)
            for distance, kind in page.lap_events(lap):
                x, y = lap_map.point_at(line, distance)
                points.append({"x": x, "y": y, "kind": kind, "color": lap.color.name(), "lap": lap.key,
                               "distance": distance, "corner": -1, "angle": 0.0,
                               "tip": f"{name} · {tr(EVENT_TITLES[kind])} · {distance_text(distance)}"})
        return points

    def violation_counts(self, events: list[dict]) -> list[dict]:
        """Track limits exceeded & off track count of each shown lap (map legend)"""
        page = self._page
        rows = []
        for _, lap in page._map_lines:
            limits = sum(1 for point in events if point["lap"] == lap.key and point["kind"] == "limit")
            offs = sum(1 for point in events if point["lap"] == lap.key and point["kind"] == "offtrack")
            if limits or offs:
                rows.append({"lap": lap.key, "label": page.short_label(lap.key), "color": lap.color.name(),
                             "limits": limits, "offtrack": offs})
        return rows

    def sector_labels(self) -> list[dict]:
        """Sector names at mid sector on reference line: reference sector time, gap of compared lap"""
        page = self._page
        reference = page.data.reference
        bounds = page.data.sector_lines
        line = page.reference_map_line()
        if reference is None or len(bounds) != 2 or line is None:
            return []
        reference_times = sector_times(reference.data)
        compared = page.compared_lap()
        compared_times = sector_times(compared.data) if compared is not None else []
        limits = [line.distances[0], *bounds, line.distances[-1]]
        labels = []
        for index in range(3):
            x, y = lap_map.point_at(line, (limits[index] + limits[index + 1]) / 2)
            gap = compared_times[index] - reference_times[index] if reference_times and compared_times else None
            labels.append({
                "x": x, "y": y, "label": f"S{index + 1}",
                "time": sector_text(reference_times[index], "") if reference_times else "",
                "delta": signed(gap, 3) if gap is not None else "",
                "deltaColor": COLOR_LOSS if gap is not None and gap > 0.0005
                else COLOR_GAIN if gap is not None and gap < -0.0005 else "",
            })
        return labels

    def slip_points(self) -> list[dict]:
        """Front wheel lockups, rear wheelspin & bottoming of each lap, colored like its lap"""
        page = self._page
        points = []
        shown = {lap.key for _, lap in page._map_lines}
        self._slips = {name: value for name, value in self._slips.items() if name in shown}
        for line, lap in page._map_lines:
            cached = self._slips.get(lap.key)
            if cached is None or cached[0] is not lap.data:
                cached = self._slips[lap.key] = (lap.data, lap_map.slip_events(lap.data))
            for distance, kind in cached[1]:
                x, y = lap_map.point_at(line, distance)
                points.append({"x": x, "y": y, "color": lap.color.name(), "kind": kind, "distance": distance,
                               "lap": lap.key})
        return points

    def brake_spreads(self) -> dict[int, tuple[float, float]]:
        """First & last braking point of shown laps in each corner (reference distances)"""
        page = self._page
        spreads: dict[int, list[float]] = {}
        for point in page._map.get("points", []) if page._map else []:
            if point["kind"] == "brake" and point.get("distance") is not None:
                spreads.setdefault(point["corner"], []).append(point["distance"])
        return {corner: (min(values), max(values)) for corner, values in spreads.items() if len(values) > 1}
