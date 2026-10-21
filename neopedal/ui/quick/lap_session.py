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
Lap viewer session tab (part of LapViewerBackend, QML backend.session): every lap of a session of current track, long run trend, tyre
wear, off tracks & track limits read from lap files in background
"""

from __future__ import annotations

import math
import os
from array import array
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtQml import QJSValue

from ...i18n import tr
from ...userfile.lap_geometry import session_values
from ...userfile.telemetry_lap import lap_number_of
from .. import lap_viewer
from ..lap_viewer import LapEntry, corner_label, distance_unit, format_laptime, number_text
from .lap_base import PagePart, weak_host
from .lines import TRIANGLES, VertexStore, Vertices

if TYPE_CHECKING:
    from PySide6.QtCore import SignalInstance

    from .trace_data import TraceData
from .stint_analysis import info_pair, trend_positions

SESSION_SHAPES = ("segments", "points", "bars")  # session chart vertex buffers
POINT_STEPS = 20  # lap point circle segments
STRIP_COLUMNS = ("fuel", "wear")  # bar strips under lap times, top to bottom
LAP_TIME = "time"  # session chart value: lap time, else sector time ("s1"...) or corner value ("min:3"...)
CORNER_VALUES = ("min", "brake", "corner")  # minimum speed, braking point, corner time: index in session_values


def premultiplied(color: QColor, opacity: float = 1.0) -> int:
    """Vertex color word: premultiplied r, g, b, a bytes"""
    alpha = color.alphaF() * opacity
    return (round(color.red() * alpha) | round(color.green() * alpha) << 8 | round(color.blue() * alpha) << 16
            | round(255 * alpha) << 24)


def colored_triangles(xs: Sequence[float], ys: Sequence[float], words: Sequence[int]) -> Vertices:
    """Triangles of colored vertices (x, y, color word each)"""
    count = len(xs)
    data = array("I", bytes(count * 12))
    data[0::3] = array("I", array("f", xs).tobytes())
    data[1::3] = array("I", array("f", ys).tobytes())
    data[2::3] = array("I", words)
    return Vertices(data, count, TRIANGLES, True)


def session_shapes(laps: Sequence[dict], view: dict) -> dict[str, Vertices]:
    """Session chart in chart pixels, same look as former items: lines joining valid laps (1.5 px, color of item),
    lap points (shown laps in their color, best gold, invalid hollow, outliers faded), fuel & tyre wear bars"""
    count = max(len(laps), 1)
    pad_left, plot_width = view["padLeft"], view["width"] - view["padLeft"] - view["padRight"]
    top, bottom, low, high = view["top"], view["bottom"], view["low"], view["high"]
    span = (high - low) or 1.0

    def x_at(index: float) -> float:
        return pad_left + (index + 0.5) / count * plot_width

    def y_at(time: float) -> float:
        return bottom - (min(time, high) - low) / span * (bottom - top)

    # Lines joining valid laps: rectangles 1.5 px high turned around their left middle (former items)
    segments = array("f")
    for index in range(1, len(laps)):
        lap, previous = laps[index], laps[index - 1]
        if not (lap["valid"] and previous["valid"] and lap["time"] > 0 and previous["time"] > 0):
            continue
        x0, y0, x1, y1 = x_at(index - 1), y_at(previous["time"]) + 0.75, x_at(index), y_at(lap["time"]) + 0.75
        length = math.hypot(x1 - x0, y1 - y0) or 1.0
        nx, ny = -(y1 - y0) / length * 0.75, (x1 - x0) / length * 0.75
        corners = ((x0 + nx, y0 + ny), (x0 - nx, y0 - ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny))
        segments.extend((*corners[0], *corners[1], *corners[2], *corners[1], *corners[3], *corners[2]))

    # Lap points: border ring & fill disc (fill none for invalid laps), in lap order (later laps on top)
    em, best, higher = view["em"], view["best"], bool(view.get("higherBetter"))
    window, text, gold = QColor(view["window"]), QColor(view["text"]), QColor(view["gold"])
    angles = [step / POINT_STEPS * math.tau for step in range(POINT_STEPS + 1)]
    cosines, sines = [math.cos(angle) for angle in angles], [math.sin(angle) for angle in angles]
    xs: list[float] = []
    ys: list[float] = []
    words: list[int] = []

    def ring(cx: float, cy: float, outer: float, inner: float, word: int):
        for step in range(POINT_STEPS):
            c0, s0, c1, s1 = cosines[step], sines[step], cosines[step + 1], sines[step + 1]
            if inner > 0:
                xs.extend((cx + c0 * outer, cx + c0 * inner, cx + c1 * outer,
                           cx + c0 * inner, cx + c1 * inner, cx + c1 * outer))
                ys.extend((cy + s0 * outer, cy + s0 * inner, cy + s1 * outer,
                           cy + s0 * inner, cy + s1 * inner, cy + s1 * outer))
                words.extend((word,) * 6)
            else:
                xs.extend((cx, cx + c0 * outer, cx + c1 * outer))
                ys.extend((cy, cy + s0 * outer, cy + s1 * outer))
                words.extend((word,) * 3)

    for index, lap in enumerate(laps):
        if not lap["time"] > 0:
            continue
        shown, valid = bool(lap["shown"]), bool(lap["valid"])
        tone = QColor(lap["color"]) if shown else gold if valid and is_best(lap["time"], best, higher) else text
        opacity = 0.4 if lap.get("outlier") else 1.0
        radius = em * (0.85 if shown else 0.6) / 2
        border = 1.5 if valid else 2.0
        cx, cy = x_at(index), y_at(lap["time"])
        ring(cx, cy, radius, max(radius - border, 0.0), premultiplied(window if valid else tone, opacity))
        if valid and radius > border:
            ring(cx, cy, radius - border, 0.0, premultiplied(tone, opacity))

    # Fuel & tyre wear used each lap: bar strips under lap times
    bar_xs: list[float] = []
    bar_ys: list[float] = []
    bar_words: list[int] = []
    bar_width = max(plot_width / count * 0.6, 2.0)
    for strip, (column, tone_name) in enumerate(zip(STRIP_COLUMNS, ("fuelColor", "wearColor"))):
        tallest = max((lap.get(column) or 0.0 for lap in laps), default=0.0)
        if tallest <= 0:
            continue
        tone = QColor(view[tone_name])
        strip_bottom = view["stripTops"][strip] + view["stripHeight"]
        valid_word, invalid_word = premultiplied(tone, 0.85), premultiplied(tone, 0.35)
        for index, lap in enumerate(laps):
            value = lap.get(column)
            if value is None or value < 0:
                continue
            height = value / tallest * (view["stripHeight"] - em * 0.2)
            if height <= 0:
                continue
            left, right, upper = x_at(index) - bar_width / 2, x_at(index) + bar_width / 2, strip_bottom - height
            bar_xs.extend((left, right, left, right, right, left))
            bar_ys.extend((upper, upper, strip_bottom, upper, strip_bottom, strip_bottom))
            bar_words.extend((valid_word if lap["valid"] else invalid_word,) * 6)
    return {"segments": Vertices(segments, len(segments) // 2, TRIANGLES),
            "points": colored_triangles(xs, ys, words), "bars": colored_triangles(bar_xs, bar_ys, bar_words)}


def is_best(value: float, best: float, higher_better: bool = False) -> bool:
    """Whether value is the best one of session chart (lowest time, highest speed)"""
    return value >= best - 1e-6 if higher_better else value <= best + 1e-6


def value_range(values: Sequence[float], low_span: float) -> list[float]:
    """Scale of session chart for values other than times [low, high]: all values, low_span at least, 8% margin"""
    if not values:
        return [0.0, 1.0]
    low, high = min(values), max(values)
    if high - low < low_span:
        low, high = (low + high - low_span) / 2, (low + high + low_span) / 2
    return [low - (high - low) * 0.08, high + (high - low) * 0.08]


def session_stats(rows: Sequence[dict]) -> dict:
    """Valid laps of session: count, mean lap time, consistency (sample standard deviation), fuel used by laps
    with a known fuel use (total & count)"""
    valid = [row["time"] for row in rows if row["valid"] and row["time"] > 0]
    count = len(valid)
    mean = sum(valid) / count if count else 0.0
    deviation = math.sqrt(sum((lap_time - mean) ** 2 for lap_time in valid) / (count - 1)) if count > 1 else 0.0
    fuels = [row["fuel"] for row in rows if row["fuel"] >= 0]
    return {"count": count, "mean": mean, "deviation": deviation, "fuel": float(sum(fuels)), "fuelCount": len(fuels)}


def session_time_range(rows: Sequence[dict]) -> list[float]:
    """Lap time scale of session chart [low, high]: slowest laps (spins, traffic) clipped, scale follows
    normal laps (90th percentile + 3%), half a second at least, 8% margin"""
    times = sorted(row["time"] for row in rows if row["time"] > 0 and row["kind"] == "lap")
    if not times:
        return [0.0, 1.0]
    low = times[0]
    high = min(times[-1], times[math.floor((len(times) - 1) * 0.9)] * 1.03)
    if high - low < 0.5:
        low -= 0.25
        high += 0.25
    return [low - (high - low) * 0.08, high + (high - low) * 0.08]


def least_squares(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Slope & intercept of line fitting points, (0, mean) if x does not vary"""
    count = len(points)
    if not count:
        return 0.0, 0.0
    mean_x = sum(x for x, _ in points) / count
    mean_y = sum(y for _, y in points) / count
    spread = sum((x - mean_x) ** 2 for x, _ in points)
    if spread <= 0:
        return 0.0, mean_y
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / spread
    return slope, mean_y - slope * mean_x


class SessionHost(Protocol):
    """What the session tab part uses of the lap viewer page"""

    data: TraceData
    folder: str
    prefix: str  # vertex store keys of page
    reference_key: str

    @property
    def chartChanged(self) -> SignalInstance: ...
    @property
    def cornersChanged(self) -> SignalInstance: ...
    def track_sessions(self) -> list: ...
    def session_row(self, group: list[LapEntry], is_added: bool) -> dict: ...
    def session_shown(self) -> bool: ...
    def run_process_job(self, name: str, done: Callable[[Any], None], function: Callable, *args): ...
    def session_corners(self) -> list[tuple[int, float, float, float]]: ...
    @staticmethod
    def entry_sectors(entry: LapEntry) -> list[float]: ...


class SessionTab(PagePart):
    """Session tab of lap viewer page (QML backend.session): every lap of a session of current track"""

    changed = Signal()  # session tab laps (sessions, shown session, its laps & values read from lap files)

    def __init__(self, page: SessionHost, parent: QObject | None = None):
        super().__init__(parent)
        self._page = weak_host(page)
        self._key = ""  # session shown in session tab
        self._extra: dict[str, tuple[float, dict]] = {}  # lap path: file time, values read from lap
        self._extra_corners: tuple = ()  # corners of reference lap values of _extra were read for
        self._metric = LAP_TIME  # value of session chart
        self._busy = False  # values of session laps being read
        self._state: dict | None = None  # session tab state, built once until changed (see session_state)
        self._corner_numbers: tuple = ()  # corners of reference lap (session chart values to choose)
        self.changed.connect(self.drop_state)  # connected first: dropped before QML reads
        page.chartChanged.connect(self.drop_state)  # laps shown (colors) read again on next read
        page.cornersChanged.connect(self.corners_changed)

    @Property(dict, notify=changed)
    def state(self) -> dict:
        """Sessions of track (key, title), session shown (key) & its laps (data, see values): one read"""
        return self.session_state()

    @Property(list, notify=changed)
    def sessions(self) -> list[dict]:
        return self.session_state()["sessions"]

    @Property(str, notify=changed)
    def key(self) -> str:
        return self.session_state()["key"]

    @Property(dict, notify=changed)
    def values(self) -> dict:
        """Laps of shown session: number, time, valid, fuel & tyre wear used, off tracks, track limits, shown"""
        return self.session_state()["data"]

    def corners_changed(self):
        """Corners of reference lap found again: values to choose & corner values of session laps"""
        corners = tuple(self._page.session_corners())
        if corners == self._corner_numbers:
            return
        self._corner_numbers = corners
        self.changed.emit()
        if ":" in self._metric and self._page.session_shown():
            self.start_job()

    @Property(list, notify=changed)
    def metrics(self) -> list[dict]:
        return self.metric_list()

    def metric_list(self) -> list[dict]:
        """Values the session chart can show: key, title"""
        items = [{"key": LAP_TIME, "title": tr("Lap Time")}]
        items += [{"key": f"s{index}", "title": f"{tr('Sector Time')} S{index}"} for index in (1, 2, 3)]
        titles = (tr("Minimum Speed"), tr("Braking Point"), tr("Corner Time"))
        for number, *_ in self._page.session_corners():
            items += [{"key": f"{kind}:{number}", "title": f"{corner_label(number)} · {title}"}
                      for kind, title in zip(CORNER_VALUES, titles)]
        return items

    @Property(str, notify=changed)
    def metric(self) -> str:
        return self.current_metric()

    def current_metric(self) -> str:
        """Value shown on session chart, lap time if chosen one is gone (corners of another reference lap)"""
        return self._metric if any(item["key"] == self._metric for item in self.metric_list()) else LAP_TIME

    @Slot(str)
    def setMetric(self, key: str):
        """Value shown on session chart (lap time, sector time, corner value)"""
        self._metric = key
        self.changed.emit()
        self.start_job()

    @staticmethod
    def metric_info(key: str) -> dict:
        """How values of session chart read: time (lap time text), unit, decimals, higher value better"""
        if key == LAP_TIME or key[:1] == "s" or key.startswith("corner:"):
            return {"key": key, "time": True, "unit": "s", "decimals": 3, "higherBetter": False}
        if key.startswith("min:"):
            return {"key": key, "time": False, "unit": lap_viewer.display_units()["speed"][1], "decimals": 1,
                    "higherBetter": True}
        return {"key": key, "time": False, "unit": distance_unit()[1], "decimals": 0, "higherBetter": True}

    def metric_value(self, key: str, entry: LapEntry, extra: dict) -> float:
        """Value of lap shown on session chart, 0 if unknown"""
        if key == LAP_TIME:
            return entry.file.lap_time
        if key[:1] == "s":
            sectors = self._page.entry_sectors(entry)
            return sectors[int(key[1]) - 1] if len(sectors) == 3 else 0.0
        kind, _, number = key.partition(":")
        values = (extra.get("corners") or {}).get(number)
        if not isinstance(values, list) or len(values) != len(CORNER_VALUES) or kind not in CORNER_VALUES:
            return 0.0
        value = float(values[CORNER_VALUES.index(kind)])
        if value <= 0:
            return 0.0
        if kind == "min":
            convert = lap_viewer.display_units()["speed"][0]
            return convert(value) if convert is not None else value
        if kind == "brake":
            return value * distance_unit()[0]
        return value

    def reset(self):
        """Circuit changed: session of reference lap shown"""
        self._key = ""

    def release(self):
        self._state = None
        self._extra = {}

    def session_groups(self) -> list[tuple[str, str, list[LapEntry]]]:
        """Sessions of current track, newest first: key, title, laps in driving order"""
        groups = []
        page = self._page
        for group in page.track_sessions():
            header = page.session_row(group, False)
            groups.append((header["session"], f"{header['title']} · {len(group)}", group))
        return groups

    def session_key(self, groups: list[tuple[str, str, list[LapEntry]]] | None = None) -> str:
        """Session shown: chosen one, else session of reference lap, else newest"""
        groups = self.session_groups() if groups is None else groups
        keys = [key for key, _, _ in groups]
        if self._key in keys:
            return self._key
        reference_key = self._page.reference_key
        for key, _, group in groups:  # session of reference lap, else newest
            if any(entry.file.path == reference_key for entry in group):
                return key
        return keys[0] if keys else ""

    @Slot(str)
    def choose(self, key: str):
        """Session shown"""
        self._key = key
        self.changed.emit()
        self.start_job()

    def session_state(self) -> dict:
        """Sessions of track, session shown & its laps (see session_data), built once until changed"""
        state = self._state
        if state is None:
            groups = self.session_groups()
            key = self.session_key(groups)
            state = self._state = {
                "sessions": [{"key": name, "title": title} for name, title, _ in groups], "key": key,
                "data": self.session_data(groups, key)}
        return state

    @Slot()
    def drop_state(self):
        self._state = None

    def shape_keys(self) -> dict[str, str]:
        """Vertex store keys of session chart shapes"""
        return {name: f"{self._page.prefix}session|{name}" for name in SESSION_SHAPES}

    @Slot("QVariant", result="QVariantMap")
    def setChart(self, view) -> dict:
        """Session chart lines, lap points & fuel / tyre wear bars built in chart pixels (view: laps shown by tab,
        chart layout, time range & colors, sent once chart size settles or laps change), their vertex keys"""
        if isinstance(view, QJSValue):
            view = view.toVariant()
        keys = self.shape_keys()
        if not isinstance(view, dict):
            return keys
        shapes = session_shapes(view.get("laps") or [], view)
        for name, key in keys.items():
            VertexStore.set(key, shapes[name])
        return keys

    def session_data(self, groups: list[tuple[str, str, list[LapEntry]]] | None = None, key: str | None = None) -> dict:
        """Laps of shown session: number, time, valid, fuel & tyre wear used, off tracks, track limits, shown"""
        groups = self.session_groups() if groups is None else groups
        key = self.session_key(groups) if key is None else key
        group = next((laps for name, _, laps in groups if name == key), [])
        colors = {lap.key: lap.color.name() for lap in self._page.data.laps}
        reference_key = self._page.reference_key
        units = lap_viewer.display_units()
        to_temperature = units["temperature"][0]
        rows = []
        for entry in group:
            info = entry.info
            extra = self._extra.get(entry.file.path, (0.0, {}))[1]
            fuel = -1.0
            start, end = info.get("fuel_start"), info.get("fuel_end")
            if isinstance(start, (int, float)) and isinstance(end, (int, float)) and start >= end:
                fuel = float(start - end)
            wear = extra.get("wear", -1.0)
            wears = info_pair(info, "wear_start", "wear_end", 4)
            if wears is not None:  # tread left at lap start & end, more at end: tyres changed during lap (unknown)
                wear = (sum(first - last for first, last in zip(*wears)) / 4
                        if all(first >= last for first, last in zip(*wears)) else -1.0)
            temperature = info.get("track_temperature")
            rows.append({
                "path": entry.file.path, "number": lap_number_of(entry.file.filename),
                "time": entry.file.lap_time, "text": format_laptime(entry.file.lap_time),
                "valid": entry.file.valid and info.get("kind", "lap") == "lap", "kind": str(info.get("kind", "lap")),
                "fuel": fuel, "wear": wear,
                "temp": (to_temperature(float(temperature)) if to_temperature else float(temperature))
                if isinstance(temperature, (int, float)) and not isinstance(temperature, bool) else None,
                "offtrack": extra.get("offtrack", -1), "limits": extra.get("limits", -1),
                "shown": entry.file.path in colors, "color": colors.get(entry.file.path, ""),
                "reference": entry.file.path == reference_key,
            })
        metric = self.current_metric()
        info = self.metric_info(metric)
        if metric != LAP_TIME:  # lap value shown instead of lap time (lap time kept for lap details)
            for row, entry in zip(rows, group):
                value = self.metric_value(metric, entry, self._extra.get(entry.file.path, (0.0, {}))[1])
                row["lapText"] = row["text"]
                row["time"] = value
                if value <= 0:
                    row["text"] = "\u2014"
                elif info["time"]:
                    row["text"] = format_laptime(value)
                else:
                    row["text"] = f"{number_text(value, info['decimals'])} {info['unit']}"
        valid = [row["time"] for row in rows if row["valid"] and row["time"] > 0]
        higher = info["higherBetter"]
        fuel_unit = units["fuel"]
        return {
            "laps": rows, "best": (max if higher else min)(valid, default=0.0),
            "worst": (min if higher else max)(valid, default=0.0), "metric": info,
            "busy": self._busy, "fuelUnit": fuel_unit[1], "temperatureUnit": units["temperature"][1],
            "fuelScale": fuel_unit[0](1.0) if fuel_unit[0] else 1.0,
            "trend": self.session_trend(rows, group) if metric == LAP_TIME else self.value_trend(rows),
            "stats": session_stats(rows),
            "range": session_time_range(rows) if info["time"] else value_range(valid, 2.0 if higher else 0.1),
            "stripMax": {name: max([0.0, *(row[name] or 0.0 for row in rows)]) for name in STRIP_COLUMNS},
        }

    @staticmethod
    def session_trend(rows: list[dict], group: list[LapEntry]) -> dict:
        """Long run of session: clean laps without outliers (traffic, mistakes), pace, lap time trend per lap
        (along lap numbers: laps not recorded keep their place), per % of tyre wear; outlier laps flagged in rows

        Trend line ends (x0, x1) are row positions (chart of rows).
        """
        clean = [(index, row["time"]) for index, row in enumerate(rows) if row["valid"] and row["time"] > 0]
        for row in rows:
            row["outlier"] = False
        if len(clean) < 3:
            return {}
        times = sorted(lap_time for _, lap_time in clean)
        quarter, three_quarters = times[len(times) // 4], times[(len(times) * 3) // 4]
        limit = min(three_quarters + 1.5 * (three_quarters - quarter), times[0] * 1.07)
        paced = [(index, lap_time) for index, lap_time in clean if lap_time <= limit + 1e-6]
        for index, lap_time in clean:
            if lap_time > limit + 1e-6:
                rows[index]["outlier"] = True
        result: dict = {"pace": sum(lap_time for _, lap_time in paced) / len(paced), "used": len(paced),
                        "left": len(clean) - len(paced)}
        if len(paced) >= 4:
            positions = trend_positions([row.get("number", 0) for row in rows], [index for index, _ in paced])
            slope, intercept = least_squares([(position, lap_time) for position, (_, lap_time) in zip(positions, paced)])
            result.update({"slope": slope, "x0": paced[0][0], "y0": intercept + slope * positions[0],
                           "x1": paced[-1][0], "y1": intercept + slope * positions[-1]})
            worn = []  # tread worn at lap start (%), lap time
            for index, lap_time in paced:
                start = group[index].info.get("wear_start") if index < len(group) else None
                if isinstance(start, list) and len(start) == 4 and all(isinstance(value, (int, float)) for value in start):
                    worn.append((100 - sum(start) / 4, lap_time))
            if len(worn) >= 4 and max(value for value, _ in worn) - min(value for value, _ in worn) >= 1:
                result["wearSlope"] = least_squares(worn)[0]
        return result

    @staticmethod
    def value_trend(rows: list[dict]) -> dict:
        """Change per lap of session chart value other than lap time (every valid lap, no outlier left out)"""
        for row in rows:
            row["outlier"] = False
        kept = [index for index, row in enumerate(rows) if row["valid"] and row["time"] > 0]
        if len(kept) < 4:
            return {}
        positions = trend_positions([row.get("number", 0) for row in rows], kept)
        slope, intercept = least_squares([(position, rows[index]["time"]) for position, index in zip(positions, kept)])
        return {"slope": slope, "x0": kept[0], "y0": intercept + slope * positions[0],
                "x1": kept[-1], "y1": intercept + slope * positions[-1]}

    def start_job(self):
        """Tyre wear, off tracks & track limits of session laps read from lap files in background (cached)

        Session chosen while a job runs: its laps read once the job is done (see done).
        """
        if self._busy:
            return
        groups = self.session_groups()
        key = self.session_key(groups)
        group = next((laps for name, _, laps in groups if name == key), [])
        corners = tuple(self._page.session_corners()) if ":" in self.current_metric() else ()
        if corners and corners != self._extra_corners:  # corner values asked for other corners: read again
            self._extra = {}
            self._extra_corners = corners
        todo = []
        for entry in group:
            try:
                mtime = os.path.getmtime(entry.file.path)
            except OSError:
                continue
            cached = self._extra.get(entry.file.path)
            if cached is None or cached[0] != mtime or (corners and "corners" not in cached[1]):
                todo.append((entry.file.path, mtime))
        if not todo:
            return
        self._busy = True
        self.changed.emit()  # busy indicator
        page = self._page

        def done(found):
            self._busy = False
            found = found if isinstance(found, dict) else {}
            for path, mtime in todo:  # unreadable laps (or job failed) not read again until their file changes
                self._extra[path] = found.get(path, (mtime, {}))
            self.changed.emit()
            if page.session_shown():  # session or track changed meanwhile
                self.start_job()

        page.run_process_job("session", done, session_values, page.folder, todo, corners)
