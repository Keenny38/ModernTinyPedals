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
Lap viewer charts (mixin of LapViewerBackend): chart zoom, page layout & options, chart panels & series vertices
built in background, channels shown, distance / time axis, cursor values, playback & range stats
"""

from __future__ import annotations

import base64
import bisect
import threading
from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtCore import (
    QByteArray,
    Slot,
)
from PySide6.QtWidgets import QApplication

from ...i18n import tr
from ...userfile.lap_geometry import (
    Yielder,
)
from ...userfile.telemetry_lap import (
    LapFile,
    decimate_minmax,
)
from .. import lap_viewer
from ..lap_viewer import (
    CHANNEL_MAP,
    CHANNEL_PRESETS,
    DEFAULT_CHANNELS,
    DELTA_CHANNELS,
    DELTA_RATE_WINDOWS,
    INTEGER_CHANNELS,
    PERCENT_RANGES,
    SMOOTHING_LEVELS,
    Channel,
    LapEntry,
    PlotLap,
    channel_title,
    distance_text,
    format_axis_time,
    format_axis_value,
    format_channel_value,
    number_text,
    part_color,
    part_label,
    save_viewer_setting,
    shade,
    signed,
)
from .lap_base import (
    BackendBase,
    format_diff,
)
from .lap_charts import axis_ticks, legend_offset, shift_key
from .lines import (
    VertexStore,
    Vertices,
    line_strip,
    range_band,
    step_strip,
)
from .models import DictListModel
from .trace_data import TraceData

SERIES_ROLES = ("key", "lods", "color", "lap")
CHART_RETRIES = 3  # charts jobs in a row refused (trace data changed meanwhile) before built on page thread
# Chart series reduced copies (min & max of each bucket, same peaks): drawn when a bucket is at most a pixel wide
LOD_LEVELS = (1500, 4500)  # buckets over whole lap
LOD_MIN_RATIO = 2.5  # copy made only for series with this many samples per bucket or more


class ChartPanels(BackendBase):
    """Page options & chart panels of lap viewer page"""

    # Chart zoom
    @Slot(float, float)
    def setChartView(self, start: float, end: float):
        """Chart zoom (kept to show same part after laps are reloaded), G circle zoomed part follows it"""
        self._chart_view = (start, end)
        if self._gcircle and self._side_tab == 1:  # G circle shown: zoomed part follows charts
            self._zoom_timer.start()

    def zoom_distances(self) -> tuple[float, float]:
        """Reference distances of charts zoomed part, (0, 0) if whole lap shown"""
        start, end = self._chart_view
        if end <= start or end - start >= self.data.max_x() - 1:
            return 0.0, 0.0
        return self.data.distance_at_x(start), self.data.distance_at_x(end)

    @Slot()
    def update_gcircle_zoom(self):
        if self._gcircle:
            self.build_gcircle_zoom()
            self.bump_revision()

    # Page layout & options
    @Slot(int)
    def setSideTab(self, index: int):
        index = min(max(index, 0), 5)
        if index != self._side_tab:
            self._side_tab = index
            save_viewer_setting(self.folder, side_tab=index)
            self.optionsChanged.emit()
        if index == 1 and self._gcircle_stale:  # laps changed while G circle was hidden: built now
            self.build_gcircle()
            self.bump_revision()
            self.gCircleChanged.emit()
        elif index == 1:  # G circle: zoomed part of charts (not followed while hidden)
            self.update_gcircle_zoom()
        if index == 4:  # session tab: values read from lap files
            self._session.start_job()

    @Slot(bool)
    def setSimpleView(self, enabled: bool):
        """Simple view (pedals, steering wheel & values at cursor) shown over charts, or advanced view (charts)"""
        enabled = bool(enabled)
        if enabled != self._simple_view:
            self._simple_view = enabled
            save_viewer_setting(self.folder, simple_view=enabled)
            self.optionsChanged.emit()
        if enabled and not self._dashboard.opened:  # simple view: its series built in background from now on
            self._dashboard.opened = True
            self.update_chart(self.dashboard_warmed)

    def dashboard_warmed(self):
        """Simple view series & ranges built (see DashboardTab.columns): read at cursor without computing"""

    @Slot("QVariant")
    def setLayoutState(self, state):
        """Split view sizes (SplitView.saveState), restored next time"""
        data = bytes(state.data()) if isinstance(state, QByteArray) else bytes(state or b"")
        text = base64.b64encode(data).decode("ascii") if data else ""
        if text != self._layout:
            self._layout = text
            save_viewer_setting(self.folder, layout=text)

    @Slot(int)
    def setSmoothing(self, level: int):
        level = min(max(level, 0), len(SMOOTHING_LEVELS) - 1)
        if level != self._smoothing:
            self._smoothing = level
            save_viewer_setting(self.folder, smoothing=level)
            self.optionsChanged.emit()
            points = SMOOTHING_LEVELS[level]
            self.update_chart(self.panels_updated, lambda data: data.set_smoothing(points))

    @Slot(int)
    def setDeltaWindow(self, meters: int):
        if meters in DELTA_RATE_WINDOWS and meters != self._delta_window:
            self._delta_window = meters
            save_viewer_setting(self.folder, delta_window=meters)
            self.optionsChanged.emit()
            self.update_chart(self.delta_window_updated, lambda data: data.set_delta_window(float(meters)))

    def delta_window_updated(self):
        """Charts & map line colored by time gain drawn again (delta window changed)"""
        self.panels_updated()
        if self._map and self._map_mode == "gain":
            self.build_colored_line(self._map_view[2])
            self.bump_revision()

    @Slot(bool)
    def setEnvelope(self, enabled: bool):
        if enabled != self._envelope:
            self._envelope = enabled
            save_viewer_setting(self.folder, envelope=enabled)
            self.optionsChanged.emit()
            self.channels_updated(save=False)

    @Slot(bool)
    def setIdealDelta(self, enabled: bool):
        if enabled != self._ideal_delta:
            self._ideal_delta = enabled
            save_viewer_setting(self.folder, ideal_delta=enabled)
            self.optionsChanged.emit()
            self.update_chart(self.panels_updated, lambda data: data.set_ideal_mode(enabled))

    @Slot(bool)
    def setGEnvelope(self, enabled: bool):
        if enabled != self._g_envelope:
            self._g_envelope = enabled
            save_viewer_setting(self.folder, g_envelope=enabled)
            self.optionsChanged.emit()

    @Slot(str, float)
    def setPanelWeight(self, column: str, weight: float):
        """Panel height set by dragging its lower edge"""
        if column in CHANNEL_MAP:
            self._weights[column] = round(min(max(weight, 0.2), 6.0), 2)
            save_viewer_setting(self.folder, panel_weights=self._weights)
            for panel in self._panels:
                if panel["column"] == column:
                    panel["weight"] = self._weights[column]
            self._panels = [dict(panel) for panel in self._panels]
            self.panelsChanged.emit()

    @Slot()
    def resetPanelWeights(self):
        self._weights = {}
        save_viewer_setting(self.folder, panel_weights={})
        self.channels_updated(save=False)

    # Charts
    def series_key(self, lap: PlotLap, channel: Channel, data: TraceData | None = None) -> str:
        """Vertex key of lap series (trace data of page by default)"""
        data = data or self.data
        signature = data.signature(channel, lap)  # only rescaled laps drawn again (reference lap changed)
        return f"{self.prefix}{lap.key}|{channel.column}|{signature}{shift_key(data or self.data, lap.key, channel)}"

    def envelope_key(self, column: str, data: TraceData | None = None) -> str:
        """Vertex key of channel envelope over shown laps (trace data of page by default)"""
        data = data or self.data
        shown = hash((tuple(lap.key for lap in data.laps), tuple(sorted(data.offsets.items()))))  # laps, offsets
        return f"{self.prefix}envelope|{column}|{data.signature(CHANNEL_MAP[column])}|{len(data.laps)}|{shown:x}"

    def overview_key(self, reference: PlotLap, data: TraceData | None = None) -> str:
        return self.series_key(reference, CHANNEL_MAP["speed_kph"], data) + "|overview"

    @staticmethod
    def lod_keys(key: str, count: int, stepped: bool) -> list[list]:
        """Reduced copies of a series of count samples: buckets over whole lap & vertex key of each"""
        lods: list[list] = []
        for buckets in LOD_LEVELS:
            if stepped or count < buckets * LOD_MIN_RATIO:
                break
            lods.append([buckets, f"{key}|lod{buckets}"])
        return lods

    def chart_vertices(self, data: TraceData, visible: Sequence[str], envelope: bool,
                       have: Callable[[str], bool] = VertexStore.has,
                       pause: Callable[[], None] | None = None) -> dict[str, Vertices]:
        """Vertices of chart series (& their reduced copies), envelopes & overview of trace data not in vertex store
        yet (have): series & value ranges computed on the way (cached by trace data)

        Trace data of page, or a snapshot of it in a background thread: never touches page state. pause: called now &
        then (thread: Yielder, which may stop a stale job).
        """
        shapes: dict[str, Vertices] = {}
        laps = data.laps
        if pause is None:
            pause = Yielder() if threading.current_thread() is not threading.main_thread() else (lambda: None)
        for column in visible:
            channel = CHANNEL_MAP.get(column)
            if channel is None:  # math channel removed meanwhile (background thread)
                continue
            data.value_range(channel)
            for lap in laps:
                for part in channel.parts or (column,):
                    pause()  # background thread: page thread gets the interpreter lock now & then
                    part_channel = CHANNEL_MAP[part]
                    key = self.series_key(lap, part_channel, data)
                    xs, ys = data.series(part_channel, lap)
                    stepped = part in INTEGER_CHANNELS
                    if not have(key) and key not in shapes:
                        shapes[key] = step_strip(xs, ys) if stepped else line_strip(xs, ys)
                    for buckets, lod in self.lod_keys(key, len(xs), stepped):
                        if not have(lod) and lod not in shapes:
                            points = decimate_minmax(xs, ys, xs[0], xs[-1], buckets)
                            shapes[lod] = line_strip([p[0] for p in points], [p[1] for p in points])
            if envelope and not channel.parts:
                key = self.envelope_key(column, data)
                if not have(key):
                    shapes[key] = range_band(*data.envelope(channel))
        reference = data.reference
        if reference is not None and "speed_kph" in reference.data.columns:
            key = self.overview_key(reference, data)
            if not have(key):
                shapes[key] = line_strip(*data.series(CHANNEL_MAP["speed_kph"], reference))
        return shapes

    def chart_work(self) -> int:
        """Samples of chart series to compute for shown laps (estimate): every series if a setting changed, else
        series whose vertices are missing"""
        laps = self.data.laps
        if self._chart_changes:
            return sum(len(lap.data) for lap in laps) * self.series_count()
        work = 0
        for column in self.visible:
            channel = CHANNEL_MAP.get(column)
            if channel is None:
                continue
            for part in channel.parts or (column,):
                part_channel = CHANNEL_MAP[part]
                work += sum(len(lap.data) for lap in laps if not VertexStore.has(self.series_key(lap, part_channel)))
            if self._envelope and not channel.parts and len(laps) >= 3 and column not in DELTA_CHANNELS:
                work += 0 if VertexStore.has(self.envelope_key(column)) else sum(len(lap.data) for lap in laps)
        for column in self._dashboard.columns():  # simple view values (tab opened)
            channel = CHANNEL_MAP.get(column)
            if channel is not None and not channel.parts and self.data.available(channel):
                work += sum(len(lap.data) for lap in laps if not self.data.series_cached(channel, lap))
        return work

    def update_chart(self, after: Callable[[], None], change: Callable[[TraceData], Any] | None = None):
        """Charts updated by after() once their series are ready: built in background when long (page stays
        responsive, charts shown keep former settings meanwhile), else at once

        Args:
            after: page update using chart series (panels, whole charts...), once per update even if asked twice.
            change: trace data setting changed, applied with series ready (charts never drawn half way).
        Updates asked meanwhile wait for the same series: one charts job at a time, a running one built for older
        settings stops at its next pause and is started again with every change asked so far.
        """
        if change is not None:
            self._chart_changes.append(change)
        if after not in self._chart_afters:
            self._chart_afters.append(after)
        self._chart_generation += 1  # running job stale: stops early, built again once it ends
        self._chart_rejected = 0
        if not self._chart_running:
            self.start_chart_job()

    def start_chart_job(self):
        """Pending chart updates: done at once if little work, else series built on a snapshot in background"""
        if not self._chart_afters and not self._chart_changes:
            return
        if self.chart_work() < lap_viewer.BACKGROUND_CHART_SAMPLES or self._chart_rejected >= CHART_RETRIES:
            self._chart_rejected = 0
            self.finish_chart()
            return
        generation = self._chart_generation
        snapshot = self.data.snapshot()
        changes, visible, envelope = list(self._chart_changes), list(self.visible), self._envelope
        dashboard = self._dashboard.columns()

        def building() -> dict[str, Vertices]:
            pause = Yielder(cancelled=lambda: generation != self._chart_generation)
            for setting in changes:
                setting(snapshot)
            vertices = self.chart_vertices(snapshot, visible, envelope, pause=pause)
            snapshot.warm(dashboard, pause)  # simple view values read at cursor
            return vertices

        def built(vertices: dict[str, Vertices] | None):
            self._chart_running = False
            if generation != self._chart_generation:  # newer update: built again with every change asked
                self.start_chart_job()
                return
            if vertices is None:  # job failed: done on page thread
                self.finish_chart()
                return
            if not self.data.adopt(snapshot):  # trace data changed meanwhile (laps shown...): built again
                self._chart_rejected += 1
                self.start_chart_job()
                return
            self._chart_rejected = 0
            self._chart_changes = []  # applied on snapshot
            for key, item in vertices.items():
                if not VertexStore.has(key):
                    VertexStore.set(key, item)
            self.finish_chart()

        self._chart_running = True
        self.run_job("charts", building, built)

    def finish_chart(self):
        """Settings changed applied (if not adopted with background series) & chart updates done"""
        changes, self._chart_changes = self._chart_changes, []
        afters, self._chart_afters = self._chart_afters, []
        for change in changes:
            change(self.data)
        for after in afters:
            after()

    def rebuild_chart(self):
        """Vertices & properties of every view from displayed laps (series built in background if long)"""
        self.update_chart(self.rebuild_chart_now)

    def rebuild_chart_now(self):
        """Vertices & properties of every view from displayed laps"""
        self.update_base()
        self._corner_table.build_official()
        self._corner_table.build_corners()
        self._charts.update_alignment()  # laps aligned on a braking point: shifted before charts are built
        entries = {entry.file.path: entry for entry in self.all_entries()}
        self._legend = [
            {"key": lap.key, "label": self.short_label(lap.key), "full": lap.label,
             "color": lap.color.name(), "reference": lap is self.data.reference, "clean": lap.clean,
             "tip": self.entry_conditions(entries[lap.key]) if lap.key in entries
             else self.entry_conditions(LapEntry(LapFile("", lap.key, True), lap.data.meta)),
             "excluded": self.excluded_text(lap), "offset": legend_offset(self.data, lap.key)}
            for lap in self.data.laps
        ]
        self.legend_model.sync(self._legend)
        self.build_panels()
        self.build_overview()
        self.build_map()
        self.build_gcircle()  # only if its tab is shown, else once shown
        self.drop_unused_vertices()
        self.bump_revision()
        self.chartChanged.emit()
        self.mapChanged.emit()
        self.channelsChanged.emit()  # channels available in shown laps
        self.pinChanged.emit()
        if not self._gcircle_stale:
            self.gCircleChanged.emit()
        if self._restore_view is not None:  # laps reloaded (released while page was hidden): same zoom
            self.viewRestored.emit(*self._restore_view)
            self._restore_view = None

    @staticmethod
    def excluded_text(lap: PlotLap) -> str:
        """Why lap never counts in ideal lap & mini-sectors (legend tooltip), empty if it may"""
        if not lap.clean:
            return tr("Not counted in ideal lap & mini-sectors (invalid, out or in lap)")
        return ""

    def drop_unused_vertices(self):
        """Forget vertices of laps no longer shown & of former settings (others kept: not built again)"""
        keep = {series["key"] for panel in self._panels for series in panel["series"]}
        keep.update(key for panel in self._panels for series in panel["series"] for _, key in series["lods"])
        keep.update(self._xy_keys)
        keep.update(self._dashboard.vertex_keys())  # simple view summary band delta lines
        keep.update(self._session.shape_keys().values())
        keep.update(panel["envelope"] for panel in self._panels if panel["envelope"])
        if self._overview:
            keep.add(self._overview["key"])
        if self._map:
            keep.update((self._map["road"], self._map["edge"], self._map["colored"], self._map["marks"],
                         self._map["arrowsKey"], self._map["rangeKey"], self._map["selectedKey"], self._map["pit"],
                         self._map["mini"], self._map["spread"]))
            for line in self._map["lines"]:
                keep.update((line["key"], line["highlight"], line["trail"]))
            for item in self._map["markers"]:
                keep.update((item["brakeZones"], item["throttleZones"]))
                for shape in item["shapes"]:
                    keep.update((shape["fill"], shape["outline"]))
        for item in self._gcircle.get("dots", []):
            keep.update((item["key"], item["zoom"], item["envelope"]))
        VertexStore.retain(self.prefix, keep)

    def build_panels(self):
        for key, vertices in self.chart_vertices(self.data, self.visible, self._envelope).items():
            VertexStore.set(key, vertices)  # missing ones (built in background before if long, see update_chart)
        self._panels_axis = self.data.time_axis
        panels = []
        laps = self.data.laps
        for column in self.visible:
            channel = CHANNEL_MAP[column]
            low, high = self.data.value_range(channel)
            parts = channel.parts or (column,)
            single = len(laps) == 1
            series = []
            for lap in laps:
                for index, part in enumerate(parts):
                    part_channel = CHANNEL_MAP[part]
                    key = self.series_key(lap, part_channel)
                    # Reduced copies (buckets over whole lap, key): same peaks, far fewer vertices
                    lods = self.lod_keys(key, len(self.data.series(part_channel, lap)[0]), part in INTEGER_CHANNELS)
                    if not channel.parts:
                        color = lap.color.name()
                    elif single:
                        color = part_color(part)
                    else:
                        color = shade(lap.color, index, len(parts)).name()
                    series.append({"key": key, "lods": lods, "color": color, "lap": lap.key})
            envelope = ""
            if self._envelope and not channel.parts:
                envelope = self.envelope_key(column)
                band_vertices = VertexStore.get(envelope)
                if band_vertices is None or band_vertices.vertex_count == 0:
                    envelope = ""
            span = high - low
            reference = self.data.reference
            available = self.data.available(channel) if laps else True
            note = ""
            if not available:
                if column not in DELTA_CHANNELS:
                    note = tr("Not recorded in shown laps")
                elif self.data.ideal_mode:
                    note = tr("Ideal lap needs 2 laps or more with lap times")
                else:
                    note = tr("Check a second lap to compare")
            panels.append({
                "ticks": axis_ticks(channel, low, high),  # value grid between range limits
                "column": column, "title": channel_title(channel), "unit": self.data.unit_of(channel),
                "weight": self._weights.get(column, channel.weight), "low": low, "high": high,
                "lowText": format_axis_value(channel, low, span), "highText": format_axis_value(channel, high, span),
                "zero": low < 0 < high, "percent": channel.fixed_range in PERCENT_RANGES, "series": series,
                "available": available, "note": note, "envelope": envelope, "autoscale": column in self._charts.autoscale,
                "parts": [
                    {"label": part_label(part),
                     "color": part_color(part) if single or reference is None
                     else shade(reference.color, index, len(parts)).name()}
                    for index, part in enumerate(channel.parts)
                ],
            })
        self._panels = panels
        self.sync_panel_models()

    def sync_panel_models(self):
        """Panel & series models follow panels list (changed rows only)"""
        rows = []
        shown = set()
        for panel in self._panels:
            column = panel["column"]
            shown.add(column)
            series = self.series_models.get(column)
            if series is None:
                series = self.series_models[column] = DictListModel(SERIES_ROLES, self)
            series.sync([{"key": item["key"], "lods": item["lods"], "color": item["color"], "lap": item["lap"]}
                         for item in panel["series"]])
            rows.append({"column": column, "low": panel["low"], "high": panel["high"], "ticks": panel["ticks"],
                         "envelope": panel["envelope"], "note": panel["note"], "available": panel["available"],
                         "seriesModel": series})
        self.panel_model.sync(rows, "column")
        for column in [column for column in self.series_models if column not in shown]:
            self.series_models.pop(column).deleteLater()

    def build_overview(self):
        reference = self.data.reference
        if reference is None or "speed_kph" not in reference.data.columns:
            self._overview = {}
            return
        key = self.overview_key(reference)
        xs, ys = self.data.series(CHANNEL_MAP["speed_kph"], reference)
        if not VertexStore.has(key):
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

    @Slot(str)
    def applyPreset(self, name: str):
        """Channel menu preset: Pedals, Tyres, Brakes, Suspension..."""
        if name in CHANNEL_PRESETS:
            self.visible = list(CHANNEL_PRESETS[name])
            self.channels_updated()

    def channels_updated(self, save: bool = True):
        """Visible channels or chart settings changed: panels built again (series built in background if long)"""
        if save:
            save_viewer_setting(self.folder, channels=self.visible)
        self._dashboard.changed.emit()  # Show menu & simple view items follow at once (charts once built)
        self.update_chart(self.panels_updated)

    def panels_updated(self):
        self.build_panels()
        self.build_overview()
        self.drop_unused_vertices()  # series of former settings (smoothing, delta window...) forgotten
        self.bump_revision()
        self.channelsChanged.emit()
        self.chartChanged.emit()

    @Slot(bool)
    def setTimeAxis(self, enabled: bool):
        """Lap time or distance horizontal axis, same part of lap kept in view (charts switched once built)"""
        if enabled == self._time_axis:
            return
        self._time_axis = enabled
        save_viewer_setting(self.folder, time_axis=enabled)
        self.update_chart(self.time_axis_switched, lambda data: data.set_time_axis(enabled))

    def time_axis_switched(self):
        """Charts along axis picked last (one update however many times axis was toggled meanwhile)"""
        self.axis_switched(self._time_axis)

    def axis_switched(self, enabled: bool):
        """Charts along other axis (time axis setting applied to trace data), same part of lap kept in view"""
        if enabled != self.data.time_axis:
            return  # switched back meanwhile: charts built by last switch
        shown = self._panels_axis  # axis of charts shown until now
        start, end = self._chart_view
        zoomed = shown != enabled and end > start and end - start < self.data.max_x(shown) - 1
        if zoomed:
            start, end = self.data.distance_at_x(start, shown), self.data.distance_at_x(end, shown)
        self.build_panels()
        self.build_overview()
        self._corner_table.build_corner_marks()
        self.drop_unused_vertices()  # series along former axis forgotten
        self.bump_revision()
        self.chartChanged.emit()
        self.pinChanged.emit()  # same place, other axis position
        if zoomed:
            self.viewRestored.emit(self.data.x_at_distance(start), self.data.x_at_distance(end))

    @Slot(float, result=float)
    def distanceAt(self, x: float) -> float:
        """Reference lap distance at axis position"""
        return self.data.distance_at_x(x)

    @Slot(float, result=float)
    def xAtDistance(self, distance: float) -> float:
        return self.data.x_at_distance(distance)

    @Slot(float, result=float)
    def referenceTimeAt(self, x: float) -> float:
        """Reference lap time at axis position (playback)"""
        return self.data.reference_time_at_x(x)

    @Slot(float, result=float)
    def xAtReferenceTime(self, seconds: float) -> float:
        return self.data.x_at_reference_time(seconds)

    @Slot(float, result=str)
    def cursorTitle(self, x: float) -> str:
        distance = self.data.distance_at_x(x)
        return f"{format_axis_time(x)} · {distance_text(distance)}" if self.data.time_axis else distance_text(distance)

    def panel_columns(self) -> list[str]:
        """Channels of panels shown (visible channels, a channel just shown once its series are built)"""
        return [panel["column"] for panel in self._panels]

    @Slot(float, result=list)
    def cursorValues(self, x: float) -> list[list[dict]]:
        """Value of each lap (each series of combined panels) at axis position, for each panel

        One entry per drawn series (empty text past end of lap), so QML keeps its items.
        Difference with reference lap value added for single channel panels.
        """
        return self.cursor_values(x)

    def cursor_values(self, x: float, colors: bool = True) -> list[list[dict]]:
        """Values at cursor (see cursorValues), without series color unless colors (cursorState: QML takes them from
        panel series)"""
        result = []
        reference = self.data.reference
        for column in self.panel_columns():
            channel = CHANNEL_MAP[column]
            values = []
            if channel.parts:
                for lap in self.data.laps:
                    for index, part in enumerate(channel.parts):
                        part_channel = CHANNEL_MAP[part]
                        value = self.data.value_at(part_channel, lap, x)
                        entry = {"text": "" if value is None else f"{part_label(part)} "
                                 f"{format_channel_value(part_channel, value)}", "diff": ""}
                        if colors:
                            entry["color"] = (part_color(part) if len(self.data.laps) == 1
                                              else shade(lap.color, index, len(channel.parts)).name())
                        values.append(entry)
            else:
                reference_value = self.data.value_at(channel, reference, x) if reference is not None else None
                for lap in self.data.laps:
                    value = self.data.value_at(channel, lap, x)
                    diff = ""
                    if (value is not None and reference_value is not None and lap is not reference
                            and column not in DELTA_CHANNELS):
                        diff = format_diff(channel, value - reference_value)
                    entry = {"text": "" if value is None else format_channel_value(channel, value), "diff": diff}
                    if colors:
                        entry["color"] = lap.color.name()
                    values.append(entry)
            result.append(values)
        return result

    @Slot(float, result=dict)
    def cursorState(self, x: float) -> dict:
        """Everything shown at cursor in one call: title, chart values, map & G circle positions, simple view

        Map, G circle & simple view only while shown (empty otherwise, asked again once shown: optionsChanged,
        setMapShown): a hidden side tab costs nothing per cursor move. Colors & lap keys of chart values & map
        positions left out (QML takes them from panel series & map laps). Same position & page state as last call:
        same state, nothing worked out.
        """
        key = (x, self._revision, self.data.version, id(self._panels), id(self._map), self._map_shown, self._side_tab,
               self._simple_view, id(self._dashboard.items), self._map_view, self._map_options.get("trail"))
        cached = self._cursor_state
        if cached is not None and cached[0] == key:
            return cached[1]
        self.build_trails(x)
        state = {"title": self.cursorTitle(x), "values": self.cursor_values(x, False),
                 "map": self._map_pointer.map_cursor(x, False) if self._map_shown else [],
                 "g": self.gCursor(x) if self._side_tab == 1 else [],
                 "inputs": self._dashboard.inputs_at(x) if self._simple_view else [],
                 "dashboard": self._dashboard.cursor_values(x) if self._simple_view else []}
        self._cursor_state = (key, state)
        return state

    @Slot(float, bool, result=dict)
    def playbackStep(self, seconds: float, full: bool) -> dict:
        """Playback frame in one call: axis position at reference lap time, cursor state if full (values & texts,
        a few times a second), else only map & G circle positions as flat lists (cars move every frame, see
        map_positions) while shown"""
        x = self.data.x_at_reference_time(seconds)
        if full:
            return {"x": x, "state": self.cursorState(x)}
        self.build_trails(x)
        return {"x": x, "mapXY": self._map_pointer.map_positions(x)[0] if self._map_shown else [],
                "gXY": self.g_positions(x) if self._side_tab == 1 else []}

    @Slot(float)
    def copyValues(self, x: float):
        """Values at cursor to clipboard as text (one line per channel)"""
        lines = [self.cursorTitle(x)]
        for column, values in zip(self.panel_columns(), self.cursorValues(x)):
            channel = CHANNEL_MAP[column]
            unit = self.data.unit_of(channel)
            texts = [
                f"{lap.label}: {value['text']}" for lap, value in zip(
                    [lap for lap in self.data.laps for _ in (channel.parts or (column,))], values) if value["text"]
            ]
            lines.append(f"{channel_title(channel)}{f' ({unit})' if unit else ''}: " + " | ".join(texts))
        QApplication.clipboard().setText("\n".join(lines))
        self.set_status(tr("Values copied"))

    @Slot(int, result=list)
    def sectorRange(self, sector: int) -> list[float]:
        """Axis range of sector 1, 2 or 3 of reference lap (zoom on it), empty if sectors unknown"""
        bounds = self.data.sector_lines
        if len(bounds) != 2 or not 1 <= sector <= 3:
            return []
        limits = [0.0, *bounds, self.data.distance_at_x(self.data.max_x())]
        return [self.data.x_at_distance(limits[sector - 1]), self.data.x_at_distance(limits[sector])]

    @Slot(float, int, result=float)
    def stepFrame(self, x: float, frames: int) -> float:
        """Axis position of recorded sample frames before (negative) or after cursor, on reference lap"""
        reference = self.data.reference
        if reference is None or not frames:
            return x
        times = self.data.lap_times(reference)[1]
        if len(times) < 2:
            return x
        current = self.data.reference_time_at_x(x)
        if frames > 0:
            index = min(bisect.bisect_right(times, current + 1e-6) + frames - 1, len(times) - 1)
        else:
            index = max(bisect.bisect_left(times, current - 1e-6) + frames, 0)
        return self.data.x_at_reference_time(times[index])

    @Slot(float, float, result=list)
    def passageTimes(self, start: float, end: float) -> list[dict]:
        """Time of each shown lap between markers A & B, gap to fastest of them (fastest flagged)"""
        rows = self.data.range_stats(start, end, [])
        if not rows:
            return []
        best = min(row["time"] for row in rows)
        return [{"label": self.short_label(row["lap"].key), "color": row["lap"].color.name(),
                 "time": number_text(row["time"], 3), "gap": signed(row["time"] - best, 3) if row["time"] > best else "",
                 "best": row["time"] <= best} for row in rows]

    @Slot(float, float, result=dict)
    def rangeStats(self, start: float, end: float) -> dict:
        """Between markers A & B: each lap time taken (and gap to reference), min / max / mean of channels"""
        channels = [channel for channel in self._exports.csv_channels() if channel.column not in DELTA_CHANNELS]
        stats = self.data.range_stats(start, end, channels)
        if not stats:
            return {}
        low, high = sorted((start, end))
        reference_time = next((row["time"] for row in stats if row["lap"] is self.data.reference), None)
        laps = []
        for row in stats:
            gap = ""
            if reference_time is not None and row["lap"] is not self.data.reference:
                gap = signed(row["time"] - reference_time, 3)
            laps.append({"label": self.short_label(row["lap"].key), "color": row["lap"].color.name(),
                         "time": f"{number_text(row['time'], 3)} s", "gap": gap, "distance": distance_text(row["distance"])})
        channel_rows = []
        for index, channel in enumerate(channels):
            unit = self.data.unit_of(channel)
            cells = []
            for row in stats:
                values = row["values"][index]
                if values is None:
                    cells.append({"text": "—", "color": row["lap"].color.name()})
                    continue
                low_value, high_value, mean = (format_channel_value(channel, value) for value in values)
                cells.append({"text": f"{low_value} / {high_value} / {mean}", "color": row["lap"].color.name()})
            channel_rows.append({"title": channel_title(channel) + (f" ({unit})" if unit else ""), "cells": cells})
        return {
            "title": f"{self.cursorTitle(low)} → {self.cursorTitle(high)}", "laps": laps, "channels": channel_rows,
        }
