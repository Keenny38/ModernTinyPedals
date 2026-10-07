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
Telemetry comparison Widget

Live telemetry against reference lap of lap telemetry viewer (recorded laps of current track & class):
speed, pedals, steering & gear along a distance window around car. Reference is drawn over whole
window, so next braking point shows ahead of car, current lap behind car; time delta & speed
difference to reference at car position.

Reference lap is drawn once in tiles along lap, then tiles move with car: on each update, only the
current lap line is built and drawn.
"""

from __future__ import annotations

import math
import time
from array import array
from collections import OrderedDict, deque
from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap, QPolygonF

from .. import calculation as calc
from .. import units
from ..api_control import api
from ..i18n import tr_overlay as tr
from ..module_info import minfo
from ..userfile.reference_trace import CHANNELS, ReferenceLoader, ReferenceTrace, held_gear, stop_loading
from ..userfile.telemetry_lap import lap_folder_name
from ._base import Overlay
from ._race_aids import LEFT, RIGHT, ClassicCells, finite, option_colors, scale_y

SAMPLE_SPACING = 2  # chart pixels between samples along distance
TILE_WIDTH = 256  # chart pixels of a reference lap tile
TILE_SPARE = 3  # tiles kept besides tiles over chart width (car going back & forth near a tile edge)
JUMP_AHEAD = 150.0  # meters, car moving farther in one update moved elsewhere (garage, reset): trail cleared
JUMP_BACK = 30.0  # meters, same backward (smaller moves back are position corrections, ignored)
TRACK_CHECK = 1.0  # seconds between reads of track & class name
DELTA_LIMIT = 0.25  # share of reference lap time, larger delta: lap line crossed by one lap only, or long stop
SPEED_STEP = 20.0  # km/h, speed chart range rounded to it
DEFAULT_RANGES = {  # chart range of channels without reference lap
    "speed_kph": (0.0, 300.0), "throttle": (0.0, 1.0), "brake": (0.0, 1.0), "steering": (-1.0, 1.0), "gear": (0.5, 7.5),
}
PANELS = (  # panel, chart height (share of display height), channels
    ("speed", 1.0, ("speed_kph",)),
    ("pedals", 0.7, ("throttle", "brake")),
    ("steering", 0.55, ("steering",)),
    ("gear", 0.45, ("gear",)),
)
PANEL_LABELS = {"speed": "Speed", "pedals": "Pedals", "steering": "Steering", "gear": "Gear"}
CHANNEL_OPTIONS = {
    "speed_kph": "show_speed", "throttle": "show_throttle", "brake": "show_brake",
    "steering": "show_steering", "gear": "show_gear",
}
CENTERED_CHANNELS = frozenset(("steering",))  # zero line at middle of chart


def delta_limit(decimals: int) -> float:
    """Largest delta shown with decimals, still 2 digits once rounded (99.99 rounds to 100 with 0-1 decimals)"""
    return min(99.99, 100 - 10 ** -decimals)


def shown_panels(wcfg) -> list[tuple[str, float, tuple[str, ...]]]:
    """Panels with at least one shown channel (speed panel if none): panel, height share, channels"""
    panels = []
    for key, height, channels in PANELS:
        shown = tuple(channel for channel in channels if wcfg[CHANNEL_OPTIONS[channel]])
        if shown:
            panels.append((key, height, shown))
    return panels or [PANELS[0]]


def finite_values(values) -> list[float]:
    return [value for value in values if finite(value)]


def channel_ranges(trace: ReferenceTrace | None) -> dict[str, tuple[float, float]]:
    """Chart range of each channel, from reference lap values (fixed while reference lap is shown)"""
    ranges = dict(DEFAULT_RANGES)
    if trace is None:
        return ranges
    speeds = finite_values(trace.channels.get("speed_kph", ()))
    if speeds:
        low = max(math.floor(min(speeds) * 0.9 / SPEED_STEP) * SPEED_STEP, 0.0)
        high = max(math.ceil(max(speeds) * 1.05 / SPEED_STEP) * SPEED_STEP, low + SPEED_STEP)
        ranges["speed_kph"] = (low, high)
    steering = finite_values(trace.channels.get("steering", ()))
    if steering:
        span = max(abs(min(steering)), abs(max(steering)))
        span = min(max(math.ceil(span * 1.15 * 20) / 20, 0.1), 1.0)
        ranges["steering"] = (-span, span)
    gears = finite_values(trace.channels.get("gear", ()))
    if gears:
        ranges["gear"] = (0.5, max(max(gears), 1.0) + 0.5)
    return ranges


class LiveTrail:
    """Samples of current car along driven distance, kept over distance behind car

    Driven distance goes on over lap line (where lap distance goes back to 0): trail stays continuous.
    Sample: driven distance, then values of CHANNELS.
    """

    def __init__(self, behind: float, step: float):
        self.behind = behind
        self.step = step
        self.samples: deque[tuple[float, ...]] = deque()
        self.driven = 0.0  # meters driven since trail started
        self.last_distance = math.nan
        self.version = 0  # changed when samples change
        self.added = 0  # samples added & removed since trail started (lines built from samples follow them)
        self.removed = 0

    def clear(self):
        if self.samples:
            self.removed += len(self.samples)
            self.samples.clear()
            self.version += 1

    def update(self, distance: float, length: float, values: tuple[float, ...]) -> bool:
        """Add sample at lap distance (length: lap length, 0 if unknown), True if samples changed"""
        if not finite(distance):
            return False
        last = self.last_distance
        self.last_distance = distance
        if finite(last):
            moved = distance - last
            if length > 0:
                if moved < -length / 2:  # crossed lap line
                    moved += length
                elif moved > length / 2:  # back over lap line
                    moved -= length
            if -JUMP_BACK < moved < 0:  # position correction: wait until car is past last position again
                self.last_distance = last
                return False
            if not 0 <= moved < JUMP_AHEAD:  # car moved elsewhere
                self.clear()
                moved = 0.0
            self.driven += moved
        samples = self.samples
        if samples and self.driven - samples[-1][0] < self.step:
            return False
        samples.append((self.driven, *values))
        self.added += 1
        oldest = self.driven - self.behind
        while len(samples) > 2 and samples[1][0] < oldest:  # one sample kept before window: line reaches edge
            samples.popleft()
            self.removed += 1
        self.version += 1
        return True


def reference_line(chart_y: Sequence[float], first: int, last: int, spacing: float) -> QPolygonF:
    """Reference lap line from value index first to last, x = index * spacing (chart pixels along lap),
    indexes outside lap wrap around it (previous & next lap)"""
    count = len(chart_y)
    return QPolygonF([QPointF(index * spacing, chart_y[index % count]) for index in range(first, last + 1)])


class TelemetryCompareMixin:
    """Live trail, reference lap tiles & chart geometry, for classic & modern widget

    Design sets pens_reference (channel: pen) & fills (channel: area brush under reference line, optional).
    """

    wcfg: Any
    cfg: Any
    pens_reference: dict[str, QPen]
    fills: dict[str, QColor | QBrush]

    def setup_compare(self, left: float, width: float, panels: list[tuple[str, QRectF, tuple[str, ...]]]):
        """Chart x span (same for every panel) & chart area of each panel: panel, rect, channels"""
        wcfg = self.wcfg
        self.behind = max(float(wcfg["distance_behind"]), 10.0)
        self.ahead = max(float(wcfg["distance_ahead"]), 0.0)
        window = self.behind + self.ahead
        width = max(width, 1.0)
        self.chart_left = left
        self.chart_right = left + width
        self.meter_px = width / window
        self.car_x = left + self.behind * self.meter_px
        step = window / max(width / SAMPLE_SPACING, 2.0)
        self.loader = ReferenceLoader(self.cfg.path.telemetry, wcfg["reference_lap_source"], step)
        self.trail = LiveTrail(self.behind, step)
        self.panel_rects = {key: rect for key, rect, _ in panels}
        self.channel_rects = {channel: rect for _, rect, channels in panels for channel in channels}
        self.trail_channels = tuple(  # value index in trail sample, channel
            (index, channel) for index, channel in enumerate(CHANNELS, 1) if channel in self.channel_rects)
        self.trail_lines: dict[str, QPolygonF] = {}  # trail samples, x: chart pixels along driven distance
        self.trail_synced: tuple[int, int] | None = None  # trail samples added & removed in trail lines
        self.charts_top = min(rect.top() for _, rect, _ in panels)
        self.charts_bottom = max(rect.bottom() for _, rect, _ in panels)
        self.tiles: OrderedDict[int, QPixmap] = OrderedDict()  # tile index: reference lap drawing
        self.tile_ratio = 0.0  # screen pixel ratio of tiles
        self.tile_cache = math.ceil(width / TILE_WIDTH) + 1 + TILE_SPARE
        self.ranges = channel_ranges(None)
        self.reference_y: dict[str, array] = {}  # chart y of reference values, one per resampled value
        self.reference_version = 0  # loader version reference_y belongs to
        self.decimals = min(max(int(wcfg["decimal_places"]), 0), 3)
        self.speed_unit = units.set_unit_speed(self.cfg.units["speed_unit"])
        self.speed_symbol = units.set_symbol_speed(self.cfg.units["speed_unit"])
        self.window_left: float | None = None  # chart pixels along lap at chart left edge, None if no position
        self.lines: tuple[tuple[str, QPolygonF], ...] = ()  # current lap behind car: channel, line
        self.lines_key: tuple | None = None
        self.track = ""
        self.track_time = -TRACK_CHECK
        self.gear = 0.0  # last gear shown (kept while shifting)

    def stop(self):
        stop_loading()
        super().stop()  # type: ignore[misc]

    @property
    def reference(self) -> ReferenceTrace | None:
        return self.loader.trace

    def read_compare(self) -> tuple:
        """Sample car, find reference lap, current lap lines if changed; state: (lines key, delta, speed difference)"""
        now = time.monotonic()
        if now - self.track_time >= TRACK_CHECK:
            self.track_time = now
            self.track = lap_folder_name(api.read.session.combo_name())
        loader = self.loader
        loader.poll(self.track, now, api.read.lap.track_length())
        if loader.version != self.reference_version:
            self.reference_version = loader.version
            self.reference_changed(loader.trace)
        trace = loader.trace
        read = api.read
        length = trace.length if trace is not None else read.lap.track_length()
        if not (finite(length) and length > 0):
            length = 0.0
        distance = self.lap_distance()
        if finite(distance) and length:
            distance %= length  # estimated distance goes a bit past lap line before game resets it
        speed = read.vehicle.speed() * 3.6
        values = tuple(value if finite(value) else 0.0 for value in (
            speed, read.inputs.throttle_raw(), read.inputs.brake_raw(), read.inputs.steering(), read.engine.gear(),
        ))
        self.gear = held_gear(values[4], self.gear, values[0])
        values = (*values[:4], self.gear)
        self.trail.update(distance, length, values)
        self.sync_trail_lines()
        delta = speed_difference = None
        if trace is not None and finite(distance):
            delta = self.delta_at(trace, distance)
            reference_speed = trace.value("speed_kph", distance)
            if finite(reference_speed) and finite(speed):
                speed_difference = round(self.speed_unit((speed - reference_speed) / 3.6))
        key = (
            loader.version, self.trail.version, round(distance, 1) if finite(distance) else None,
            round(values[0]), round(values[1], 2), round(values[2], 2), round(values[3], 3), values[4],
        )
        if key != self.lines_key:
            self.lines_key = key
            self.window_left = (distance - self.behind) * self.meter_px if finite(distance) else None
            self.lines = self.build_lines(values) if finite(distance) else ()
        return key, delta, speed_difference

    def lap_distance(self) -> float:
        """Car lap distance: estimated between game updates (delta module), smooth at any speed"""
        if self.cfg.user.setting["module_delta"]["enable"]:
            return minfo.delta.lapDistance
        return api.read.lap.distance()

    def delta_at(self, trace: ReferenceTrace, distance: float) -> float | None:
        """Current lap time against reference lap time at distance, None if unknown"""
        reference_time = trace.time_at(distance)
        laptime = api.read.timing.current_laptime()
        if not (finite(reference_time) and finite(laptime)):
            return None
        delta = laptime - reference_time
        if abs(delta) > max(trace.lap_time * DELTA_LIMIT, 10.0):
            return None
        return round(calc.sym_max(delta, delta_limit(self.decimals)), self.decimals)

    def reference_changed(self, trace: ReferenceTrace | None):
        """New reference lap: chart ranges, chart y of every reference value"""
        self.ranges = channel_ranges(trace)
        self.reference_y = {}
        self.tiles.clear()
        self.trail_synced = None  # chart y of trail samples changed with ranges
        if trace is None:
            return
        for channel, rect in self.channel_rects.items():
            values = trace.channels.get(channel)
            if values:
                low, high = self.ranges[channel]
                self.reference_y[channel] = array(
                    "f", [scale_y(value if finite(value) else low, rect, low, high) for value in values])

    def sync_trail_lines(self):
        """Trail lines follow trail samples: new samples added, old samples removed (all built again only
        when trail restarted or chart ranges changed), so each update only moves lines along"""
        trail = self.trail
        samples = trail.samples
        synced = self.trail_synced
        self.trail_synced = (trail.added, trail.removed)
        new = trail.added - synced[0] if synced is not None else len(samples)
        gone = trail.removed - synced[1] if synced is not None else 0
        lines = self.trail_lines
        rebuild = synced is None or any(
            lines[channel].size() - gone + new != len(samples) for _, channel in self.trail_channels)
        if rebuild:
            gone, new = 0, len(samples)
            self.trail_lines = lines = {channel: QPolygonF() for _, channel in self.trail_channels}
        if not (gone or new):
            return
        meter_px = self.meter_px
        added = [samples[index] for index in range(len(samples) - new, len(samples))]
        for index, channel in self.trail_channels:
            line = lines[channel]
            if gone:
                line.remove(0, gone)
            rect = self.channel_rects[channel]
            low, high = self.ranges[channel]
            for sample in added:
                line.append(QPointF(sample[0] * meter_px, scale_y(sample[index], rect, low, high)))

    def build_lines(self, values: tuple[float, ...]) -> tuple[tuple[str, QPolygonF], ...]:
        """Current lap lines behind car, up to car values"""
        lines = []
        offset = self.car_x - self.trail.driven * self.meter_px
        car_x = self.car_x
        for index, channel in self.trail_channels:
            line = self.trail_lines[channel].translated(offset, 0.0)
            low, high = self.ranges[channel]
            line.append(QPointF(car_x, scale_y(values[index - 1], self.channel_rects[channel], low, high)))
            if line.size() > 1:
                lines.append((channel, line))
        return tuple(lines)

    def draw_reference(self, painter: QPainter):
        """Reference lap tiles over chart width (painter clipped to chart width)"""
        left = self.window_left
        if left is None or not self.reference_y:
            return
        ratio = self.devicePixelRatioF()  # type: ignore[attr-defined]
        if ratio != self.tile_ratio:
            self.tile_ratio = ratio
            self.tiles.clear()
        tiles = self.tiles
        last = math.floor((left + self.chart_right - self.chart_left) / TILE_WIDTH)
        for index in range(math.floor(left / TILE_WIDTH), last + 1):
            tile = tiles.get(index)
            if tile is None:
                tile = tiles[index] = self.render_tile(index, ratio)
                while len(tiles) > self.tile_cache:
                    tiles.popitem(last=False)
            else:
                tiles.move_to_end(index)
            painter.drawPixmap(QPointF(self.chart_left + index * TILE_WIDTH - left, self.charts_top), tile)

    def render_tile(self, index: int, ratio: float) -> QPixmap:
        """Reference lap from index * TILE_WIDTH to next tile (chart pixels along lap, previous & next lap
        outside lap), every chart"""
        tile = QPixmap(max(math.ceil(TILE_WIDTH * ratio), 1),
                       max(math.ceil((self.charts_bottom - self.charts_top) * ratio), 1))
        tile.setDevicePixelRatio(ratio)
        tile.fill(Qt.GlobalColor.transparent)
        trace = self.loader.trace
        if trace is None:
            return tile
        spacing = trace.step * self.meter_px
        first = math.floor(index * TILE_WIDTH / spacing) - 1  # one value beyond each edge: line reaches it
        last = math.ceil((index + 1) * TILE_WIDTH / spacing) + 1
        painter = QPainter(tile)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.translate(-index * TILE_WIDTH, -self.charts_top)
        for channel, chart_y in self.reference_y.items():
            line = reference_line(chart_y, first, last, spacing)
            fill = self.fills.get(channel)
            if fill is not None:
                bottom = self.channel_rects[channel].bottom()
                area = QPolygonF(line)
                area.append(QPointF(line.last().x(), bottom))
                area.append(QPointF(line.first().x(), bottom))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill)
                painter.drawPolygon(area)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(self.pens_reference[channel])
            painter.drawPolyline(line)
        painter.end()
        return tile

    def reference_laptime(self) -> str:
        trace = self.loader.trace
        if trace is None or not trace.lap_time > 0:
            return "-:--.---"
        return calc.sec2laptime_full(trace.lap_time)

    def reference_text(self) -> str:
        """Reference lap time, or why there is none"""
        if self.loader.trace is None:
            return tr("No reference lap")
        return f"{tr('Ref')} {self.reference_laptime()}"

    def delta_text(self, delta: float | None) -> str:
        if delta is None:
            return "-.--"
        return f"{delta:+.{self.decimals}f}"

    def speed_text(self, difference: int | None) -> str:
        if difference is None:
            return f"-- {self.speed_symbol}"
        return f"{difference:+d} {self.speed_symbol}" if difference else f"0 {self.speed_symbol}"


class Realtime(TelemetryCompareMixin, ClassicCells, Overlay):
    """Draw widget"""

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        font_m = self.setup_classic_font()

        # Config variable
        wcfg = self.wcfg
        width = max(int(wcfg["display_width"]), 80)
        height = max(int(wcfg["display_height"]), 20)
        gap = max(int(wcfg["bar_gap"]), 0)
        self.show_reference_info = bool(wcfg["show_reference_lap_time"])
        self.show_delta = bool(wcfg["show_delta"])
        self.show_speed_difference = bool(wcfg["show_speed_difference"])
        header = font_m.height if self.show_reference_info or self.show_delta or self.show_speed_difference else 0
        self.rect_header = QRectF(0, 0, width, header)
        panels = []
        top: float = header + (gap if header else 0)
        for key, share, channels in shown_panels(wcfg):
            rect = QRectF(0, top, width, max(round(height * share), 10))
            panels.append((key, rect, channels))
            top = rect.bottom() + gap
        self.setup_compare(0, width, panels)
        self.colors = option_colors(
            wcfg, "font_color_reading", "font_color_time_gain", "font_color_time_loss", "background_color",
            "background_color_chart", "zero_line_color", "position_mark_color",
            "line_color_speed", "line_color_throttle", "line_color_brake", "line_color_steering", "line_color_gear",
        )
        opacity = min(max(float(wcfg["reference_line_opacity"]), 0.0), 1.0)
        self.pens_current: dict[str, QPen] = {}
        self.pens_reference = {}
        self.fills = {}
        for channel in CHANNELS:
            color = self.colors[f"line_color_{channel.removesuffix('_kph')}"]
            self.pens_current[channel] = QPen(color, 1.5)
            faded = QColor(color)
            faded.setAlphaF(faded.alphaF() * opacity)
            self.pens_reference[channel] = QPen(faded, 2.5)
        self.pen_zero = QPen(self.colors["zero_line_color"], 1)
        self.pen_mark = QPen(self.colors["position_mark_color"], 1.5)

        # Config canvas
        self.resize(width, max(round(top - gap), header + 10))
        self.state: tuple = (None, None, None)  # lines key, delta, speed difference

    def timerEvent(self, event):
        """Update when vehicle on track"""
        state = self.read_compare()
        if self.state != state:
            self.state = state
            self.update()

    # GUI update methods
    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        colors = self.colors
        painter.fillRect(self.rect(), colors["background_color"])
        for rect in self.panel_rects.values():
            painter.fillRect(rect, colors["background_color_chart"])
        painter.setPen(self.pen_zero)
        for channel in CENTERED_CHANNELS:
            chart = self.channel_rects.get(channel)
            if chart is not None:
                painter.drawLine(QPointF(chart.left(), chart.center().y()), QPointF(chart.right(), chart.center().y()))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setClipRect(QRectF(self.chart_left, 0, self.chart_right - self.chart_left, self.height()))
        self.draw_reference(painter)
        for channel, line in self.lines:
            painter.setPen(self.pens_current[channel])
            painter.drawPolyline(line)
        painter.setClipping(False)
        painter.setPen(self.pen_mark)
        for rect in self.panel_rects.values():
            painter.drawLine(QPointF(self.car_x, rect.top()), QPointF(self.car_x, rect.bottom()))
        header = self.rect_header
        if self.show_reference_info:
            self.draw_cell(painter, header, self.reference_text(), colors["font_color_reading"], None, LEFT)
        _, delta, speed_difference = self.state
        texts = []
        if self.show_speed_difference:
            color = colors["font_color_reading"]
            if speed_difference:
                color = colors["font_color_time_gain"] if speed_difference > 0 else colors["font_color_time_loss"]
            texts.append((self.speed_text(speed_difference), color))
        if self.show_delta:
            color = colors["font_color_reading"]
            if delta:
                color = colors["font_color_time_loss"] if delta > 0 else colors["font_color_time_gain"]
            texts.append((self.delta_text(delta), color))
        right = header.right()
        for text, color in reversed(texts):
            width = self.font_m.width * (len(text) + 1)
            self.draw_cell(painter, QRectF(right - width, header.top(), width, header.height()), text, color, None, RIGHT)
            right -= width
