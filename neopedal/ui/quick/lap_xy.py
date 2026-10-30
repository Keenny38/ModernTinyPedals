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
Lap viewer XY tab, G circle & replay (mixin of LapViewerBackend): scatter of two channels, time spent in
value ranges (histogram), G circle & G-G envelope, replay file of a chart moment opened in game
"""

from __future__ import annotations

import bisect
import html
import math
import os
from collections.abc import Sequence
from contextlib import suppress
from typing import Any

from PySide6.QtCore import (
    Slot,
)
from PySide6.QtWidgets import QApplication

from ...i18n import tr, trm
from ...setting import cfg
from ...userfile.corner_analysis import resample_sorted
from ...userfile.lap_geometry import (
    coordinate_array,
)
from ...userfile.telemetry_lap import (
    interpolate,
    lap_time_of,
    lap_timestamp_of,
)
from ..lap_viewer import (
    CHANNEL_MAP,
    INTEGER_CHANNELS,
    Channel,
    PlotLap,
    channel_title,
    format_axis_time,
    format_axis_value,
    nice_step,
    save_viewer_setting,
)
from .lap_base import (
    BackendBase,
)
from .lines import (
    VertexStore,
    dots,
    line_strip,
)

G_PERCENTILE = 0.99  # G circle scale: share of samples inside (curb & contact spikes left out)
G_SECTORS = 36  # G-G envelope directions
G_ENVELOPE_QUANTILE = 0.98  # G-G envelope radius: share of samples inside, in each direction
XY_DOT = 0.007  # scatter dot size, share of plot
HISTOGRAM_BINS = 12  # about this many bins for continuous channels


def percentile(values: list[float], share: float) -> float:
    """Value under which share of values are, 0 if none"""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(int(len(ordered) * share), len(ordered) - 1)]


def g_envelope(xs: Sequence[float], ys: Sequence[float]) -> tuple[list[float], list[float]]:
    """Closed G-G envelope: grip used in every direction (high quantile radius per direction sector)"""
    radii: list[list[float]] = [[] for _ in range(G_SECTORS)]
    for x, y in zip(xs, ys):
        sector = int((math.atan2(y, x) + math.pi) / math.tau * G_SECTORS) % G_SECTORS
        radii[sector].append(math.hypot(x, y))
    points = []
    for sector, values in enumerate(radii):
        if len(values) >= 3:
            angle = (sector + 0.5) / G_SECTORS * math.tau - math.pi
            radius = percentile(values, G_ENVELOPE_QUANTILE)
            points.append((math.cos(angle) * radius, math.sin(angle) * radius))
    if len(points) < 3:
        return [], []
    points.append(points[0])
    return [x for x, _ in points], [y for _, y in points]


def find_replay(folder: str, moment: float, replayed: str) -> tuple[str, float] | None:
    """Replay file covering moment (real time) & position in it, None if none (background only: every replay file
    of folder is opened), replay of name replayed (lap recorded while replaying it) looked at first"""
    from ... import replay

    candidates = replay.list_replays(folder)
    if replayed:
        candidates.sort(key=lambda item: os.path.basename(item.filename) != replayed)
    for item in candidates:
        if item.duration >= 0:
            end = item.created + item.duration
        else:  # interrupted recording: written until file last changed
            try:
                end = os.path.getmtime(item.filename)
            except OSError:
                continue
        if item.created - 2 <= moment <= end + 2:
            return item.filename, min(max(moment - item.created, 0.0), max(end - item.created, 0.0))
    return None


def time_weights(times: Sequence[float]) -> list[float]:
    """Time each sample stands for (half of time to previous & next sample), histogram weights"""
    count = len(times)
    if count < 2:
        return [1.0] * count
    weights = []
    for index in range(count):
        before = times[index] - times[index - 1] if index > 0 else 0.0
        after = times[index + 1] - times[index] if index + 1 < count else 0.0
        weights.append(max((before + after) / 2, 0.0))
    return weights


class XyTabs(BackendBase):
    """XY tab, G circle & replay of lap viewer page"""

    # XY tab: scatter of two channels, time spent in value ranges (histogram)
    def xy_samples(self, column: str, lap: PlotLap) -> tuple[Sequence[float], Sequence[float]]:
        """Reference distances & values of channel (user unit), zoomed chart part only when charts are zoomed"""
        if column not in CHANNEL_MAP or CHANNEL_MAP[column].parts:
            return [], []
        xs, ys = self.data.series(CHANNEL_MAP[column], lap, time_axis=False, aligned=False)
        start, end = self.zoom_distances()
        if end > start and xs:
            low, high = bisect.bisect_left(xs, start), bisect.bisect_right(xs, end)
            return xs[low:high], ys[low:high]
        return xs, ys

    @Slot(str, str, str, str)
    def setXyState(self, mode: str, x_column: str, y_column: str, histogram: str):
        state = {"mode": mode if mode in ("scatter", "histogram") else "scatter", "x": x_column, "y": y_column,
                 "histogram": histogram}
        state.update({name: self._xy[name] for name in ("x", "y", "histogram") if state[name] not in CHANNEL_MAP})
        if state != self._xy:
            self._xy = state
            save_viewer_setting(self.folder, xy=state)

    @Slot(str, str, result=dict)
    def scatter(self, x_column: str, y_column: str) -> dict:
        """Dots of each shown lap: x channel value against y channel value (same place on track)

        Vertices in plot fractions (0 to 1, y up) & value range of each axis, zoomed chart part only if zoomed.
        """
        if x_column not in CHANNEL_MAP or y_column not in CHANNEL_MAP or not self.data.laps:
            return {}
        pairs: list[tuple[PlotLap, Sequence[float], Sequence[float]]] = []
        for lap in self.data.laps:
            x_distances, x_values = self.xy_samples(x_column, lap)
            y_distances, y_values = self.xy_samples(y_column, lap)
            if len(x_distances) < 2 or len(y_distances) < 2:
                continue
            ys = y_values if y_distances == x_distances else [interpolate(y_distances, y_values, distance)
                                                               for distance in x_distances]
            pairs.append((lap, x_values, ys))
        if not pairs:
            return {}
        ranges = []
        for series, column in (([pair[1] for pair in pairs], x_column), ([pair[2] for pair in pairs], y_column)):
            channel = CHANNEL_MAP[column]
            if channel.fixed_range:
                low, high = channel.fixed_range
            else:
                low = min(min(values) for values in series)
                high = max(max(values) for values in series)
                if high - low < 1e-6:
                    high = low + 1
                padding = (high - low) * 0.04
                low, high = low - padding, high + padding
            ranges.append((low, high, channel))
        (x_low, x_high, x_channel), (y_low, y_high, y_channel) = ranges
        laps = []
        keys = set()
        for lap, lap_xs, lap_ys in pairs:
            key = f"{self.prefix}xy|{lap.key}"
            VertexStore.set(key, dots([(x - x_low) / (x_high - x_low) for x in lap_xs],
                                      [(y - y_low) / (y_high - y_low) for y in lap_ys], XY_DOT, 6000))
            keys.add(key)
            laps.append({"key": key, "lap": lap.key, "color": lap.color.name()})
        self._xy_keys = keys
        self.bump_revision()

        def ticks(low: float, high: float, channel: Channel) -> list[dict]:
            step = nice_step(high - low, 4)
            first = math.ceil(low / step) * step
            return [{"at": (value - low) / (high - low), "text": format_axis_value(channel, value, high - low)}
                    for value in (first + index * step for index in range(10)) if value <= high]

        return {"laps": laps, "xTicks": ticks(x_low, x_high, x_channel), "yTicks": ticks(y_low, y_high, y_channel),
                "xTitle": channel_title(x_channel), "yTitle": channel_title(y_channel),
                "zero": [(0 - x_low) / (x_high - x_low), (0 - y_low) / (y_high - y_low)],
                "xRange": [x_low, x_high], "yRange": [y_low, y_high]}  # zoomed plot asks ticks of part shown

    def xy_weights(self, column: str, lap: PlotLap, distances: Sequence[float]) -> list[float]:
        """Lap time each sample of xy_samples stands for (histogram weights), lap times of the samples found in one
        pass (distances ascending), kept per lap, channel & zoomed part: the chart zoom asks the histogram again at
        each zoom end"""
        key = (lap.key, id(lap.data), column, self.data.version, len(distances), distances[0], distances[-1])
        weights = self._xy_weights.get(key)
        if weights is None:
            own, times = self.data.lap_times(lap)
            scale = self.data.scale_of(lap)
            if own:
                grid = [distance / scale for distance in distances] if scale != 1.0 else distances
                lap_times: Sequence[float] = resample_sorted(own, times, grid)
            else:
                lap_times = distances
            weights = time_weights(lap_times)
            if len(self._xy_weights) >= 64:  # laps or zoomed parts no longer shown
                self._xy_weights.clear()
            self._xy_weights[key] = weights
        return weights

    @Slot(str, result=dict)
    def histogram(self, column: str) -> dict:
        """Share of lap time spent in each value range of channel, each shown lap (zoomed chart part if zoomed)"""
        channel = CHANNEL_MAP.get(column)
        if channel is None or channel.parts or not self.data.laps:
            return {}
        samples = []
        for lap in self.data.laps:
            distances, values = self.xy_samples(column, lap)
            if len(distances) < 2:
                continue
            samples.append((lap, values, self.xy_weights(column, lap, distances)))
        if not samples:
            return {}
        if column in INTEGER_CHANNELS:  # one bar per whole value (gear 1, 2, 3...)
            levels = sorted({round(value) for _, values, _ in samples for value in values})
            edges = [level - 0.5 for level in levels] + [levels[-1] + 0.5]
            labels = [str(level) for level in levels]
        else:
            if channel.fixed_range:
                low, high = channel.fixed_range
                step = (high - low) / 10
            else:
                low = min(min(values) for _, values, _ in samples)
                high = max(max(values) for _, values, _ in samples)
                step = nice_step(max(high - low, 1e-6), HISTOGRAM_BINS)
                low = math.floor(low / step) * step
            count = max(min(math.ceil((high - low) / step - 1e-9), 40), 1)
            edges = [low + step * index for index in range(count + 1)]
            labels = [format_axis_value(channel, edges[index], step * count) for index in range(count)]
        laps = []
        top = 0.0
        for lap, values, weights in samples:
            shares = [0.0] * (len(edges) - 1)
            total = sum(weights) or 1.0
            for value, weight in zip(values, weights):
                position = min(max(bisect.bisect_right(edges, value) - 1, 0), len(shares) - 1)
                shares[position] += weight
            shares = [share / total * 100 for share in shares]
            top = max(top, max(shares, default=0.0))
            laps.append({"label": self.short_label(lap.key), "color": lap.color.name(), "values": shares, "lap": lap.key})
        return {"bins": labels, "laps": laps, "max": top, "unit": self.data.unit_of(channel),
                "title": channel_title(channel)}

    # G circle: right turn on the right, braking at bottom
    def build_gcircle(self, now: bool = False):
        """Dots & grip envelope of each shown lap, built only while G circle tab is shown or if now (laps changed
        while hidden: built once shown or read, see gCircle)"""
        self._g_points = []
        peaks = []
        shown = {lap.key for lap in self.data.laps}
        self._g_laps = {name: value for name, value in self._g_laps.items() if name in shown}
        self._g_drawn = {name: value for name, value in self._g_drawn.items() if name in shown}
        self._gcircle_stale = self._side_tab != 1 and not now
        if self._gcircle_stale:  # vertices of laps still shown kept (not built again), of other laps dropped
            kept = [item for item in self._gcircle.get("dots", []) if item["lap"] in shown]
            self._gcircle = {"dots": kept} if kept else {}
            return
        for lap in self.data.laps:
            cached = self._g_laps.get(lap.key)
            if cached is None or cached[0] is not lap.data:
                lat, lon = lap.data.columns.get("accel_lat"), lap.data.columns.get("accel_long")
                if not lat or not lon:
                    continue
                # Game: lateral positive to the left, longitudinal positive when braking
                lat_g, long_g = coordinate_array(lat), coordinate_array(lon)  # packed like lap columns (kept per lap)
                lat_g.extend([-value for value in lat])
                long_g.extend([-value for value in lon])
                peak = percentile([max(abs(x), abs(y)) for x, y in zip(lat_g, long_g)], G_PERCENTILE)
                cached = self._g_laps[lap.key] = (lap.data, lap.data.distance, lat_g, long_g, peak)
            self._g_points.append((cached[1], cached[2], cached[3], lap))
            peaks.append(cached[4])
        if not self._g_points:
            self._gcircle = {}
            return
        limit = max(peaks, default=1.0)
        limit = max(1.0, float(math.ceil(limit * 1.05)))  # some room around
        dots_list = []
        for _, xs, ys, lap in self._g_points:
            key = f"{self.prefix}g|{lap.key}"
            drawn = self._g_drawn.get(lap.key)
            if drawn is None or drawn[0] is not lap.data or drawn[1] != limit or not VertexStore.has(key):
                VertexStore.set(key, dots(xs, ys, limit / 110))
                VertexStore.set(key + "|envelope", line_strip(*g_envelope(xs, ys)))
                self._g_drawn[lap.key] = (lap.data, limit)
            dots_list.append({"key": key, "zoom": key + "|zoom", "envelope": key + "|envelope",
                              "color": lap.color.name(), "lap": lap.key})
        self._gcircle = {"limit": limit, "dots": dots_list}
        if self._side_tab == 1:  # else built when G circle tab is shown
            self.build_gcircle_zoom()

    def build_gcircle_zoom(self):
        start, end = self.zoom_distances()  # charts zoom (map view is not updated while map is hidden)
        limit = self._gcircle.get("limit", 1.0)
        for distances, xs, ys, lap in self._g_points:
            key = f"{self.prefix}g|{lap.key}|zoom"
            if end > start:
                scale = self.data.scale_of(lap)
                low, high = bisect.bisect_left(distances, start / scale), bisect.bisect_right(distances, end / scale)
                VertexStore.set(key, dots(xs[low:high], ys[low:high], limit / 70))
            else:
                VertexStore.set(key, dots([], [], 0))

    @Slot(float, result=list)
    def gCursor(self, x: float) -> list[dict]:
        if self._gcircle_stale:
            self.build_gcircle(True)
        points = []
        for distances, xs, ys, lap in self._g_points:
            distance = self.data.lap_distance_at_x(lap, x)
            points.append({"x": interpolate(distances, xs, distance), "y": interpolate(distances, ys, distance),
                           "color": lap.color.name(), "lap": lap.key})
        return points

    def g_positions(self, x: float) -> list[float]:
        """G circle position of each lap at cursor as one flat list (x, y of each lap, see gCursor)"""
        if self._gcircle_stale:
            self.build_gcircle(True)
        positions: list[float] = []
        for distances, xs, ys, lap in self._g_points:
            distance = self.data.lap_distance_at_x(lap, x)
            positions += (interpolate(distances, xs, distance), interpolate(distances, ys, distance))
        return positions

    # Replay
    def replay_moment(self, lap: PlotLap, x: float) -> tuple[float, str] | None:
        """Real time of lap at axis position & replay it was recorded while replaying ("" if none), None if unknown

        Lap end: exact time of lap info if recorded ("finished"), else file name date (whole seconds: middle of that
        second). Imported MoTeC laps without a log date (named at import time) are never linked.
        """
        meta = lap.data.meta
        finished = meta.get("finished")
        if isinstance(finished, (int, float)) and not isinstance(finished, bool) and finished > 0:
            timestamp = float(finished)
        elif meta.get("source") == "MoTeC":
            return None
        else:  # lap end: real time, or replay time if replayed
            timestamp = lap_timestamp_of(os.path.basename(lap.key)) + 0.5
        lap_time = lap.data.lap_time or lap_time_of(os.path.basename(lap.key))
        if timestamp <= 0.5 or lap_time <= 0:
            return None
        distances, times = self.data.lap_times(lap)
        at = interpolate(distances, times, self.data.lap_distance_at_x(lap, x)) if distances else 0.0
        return timestamp - lap_time + at, str(meta.get("replay", ""))

    @Slot(float, str)
    def openReplay(self, x: float, lap_key: str = ""):
        """Open replay recorded with lap at cursor position (replay page), once found in background"""
        lap = next((lap for lap in self.data.laps if lap.key == lap_key), self.data.reference)
        if lap is None or self._replay_lookup:
            return
        moment = self.replay_moment(lap, x)
        if moment is None:
            self.set_status(tr("No replay recorded with this lap."))
            return
        folder = cfg.path.telemetry or "."
        self._replay_lookup = True
        self.set_status(tr("Looking for the replay of this lap…"), transient=False)
        self.run_job("replay lookup", lambda: find_replay(folder, *moment), self.replay_found)

    def replay_found(self, target: tuple[str, float] | None):
        """Replay of lap found (or not) in background: opened at lap position"""
        self._replay_lookup = False
        if target is None:
            self.set_status(tr("No replay recorded with this lap."))
            return
        self.set_status("")  # lookup message left (replay page tells what it does)
        self.show_replay(*target)

    def show_replay(self, filename: str, position: float):
        """Replay page opened on replay file at position (loaded in background if not open)"""
        from ...replay import replay
        from .._common import BaseDialog
        from ..tools_view import open_tool

        open_tool("replay_view.ReplayView", self._window)
        top = self._window.window()
        views = [widget for widget in [top, *top.findChildren(BaseDialog), *QApplication.topLevelWidgets()]
                 if type(widget).__name__ == "ReplayView"]
        if not views:
            return
        view: Any = views[-1]  # ReplayView (imported only when replay page opens)

        def show_position():
            player = replay.player
            if player is None or os.path.normpath(player.replay.filename) != os.path.normpath(filename):
                return
            player.seek(position)
            player.set_paused(True)
            view.refresh()
            with suppress(RuntimeError):  # lap viewer closed while replay was loading
                self.set_status(
                    trm(f"Replay: {html.escape(os.path.basename(filename))} at {format_axis_time(position)}"))

        player = replay.player
        if player is None or os.path.normpath(player.replay.filename) != os.path.normpath(filename):
            view.open_file(filename, show_position)  # loaded in background, position shown once loaded
            if view.loader.busy:
                self.set_status(tr("Loading replay…"))
        else:
            show_position()
