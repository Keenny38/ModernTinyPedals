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
Lap viewer simple view (mixin of LapViewerBackend): channels at chart cursor drawn like overlays, in groups
(pedals & steering wheel, timing, engine, tyres, brakes, chassis, electronics, track, math channels)

One selection for both views: channels shown on charts (advanced view, Show menu) are the items of simple view (pedal
cards while a pedal, steering, gear or speed channel is shown, G circle while a G channel is, 4 wheel tiles while the
4 wheels channel or one wheel of it is). Show menu lists channels in the same groups.

Layout (groups & items shown) changes with laps & selection only, values are read at each cursor move, one entry per
item & lap in layout order: QML items are kept while cursor moves.
"""

from __future__ import annotations

import bisect
import math
from typing import NamedTuple

from PySide6.QtCore import Slot

from ...i18n import tr
from ..lap_viewer import (
    CHANNEL_MAP,
    CHANNELS,
    DELTA_CHANNELS,
    INTEGER_CHANNELS,
    MATH_PREFIX,
    PERCENT_RANGES,
    WHEELS,
    Channel,
    PlotLap,
    channel_title,
    format_channel_value,
    number_text,
)
from .lap_base import BackendBase

INPUTS_ITEM = "inputs"  # pedals & steering wheel cards of each lap
G_ITEM = "g"  # lateral & longitudinal G on a small circle
INPUTS_COLUMNS = ["throttle", "brake", "clutch", "steering", "speed_kph", "gear"]  # read by pedal cards
# Channels shown as pedal cards & G circle in simple view (in Show menu order)
CARD_CHANNELS = ("speed_kph", "throttle", "brake", "all:pedals", "clutch", "gear", "steering")
G_CHANNELS = ("accel_lat", "accel_long")


class Item(NamedTuple):
    """Simple view item: one channel (or 4 wheels, G) drawn like an overlay"""

    key: str  # channel column, combined wheel channel ("all:tyre_temp"), INPUTS_ITEM or G_ITEM
    kind: str  # bar (low to high), center (around 0), number (car setting), light (on / off), wheels (4 tiles),
    # g (circle), inputs
    heat: bool = False  # wheel tiles colored cold to hot (temperatures)
    scale: tuple[float, float] | None = None  # fixed bar range, else range of shown laps


GROUPS: tuple[tuple[str, str, tuple[Item, ...]], ...] = (
    ("driver", "Pedals & Steering Wheel", (Item(INPUTS_ITEM, "inputs"),)),
    ("timing", "Timing", (Item("delta", "center"), Item("delta_rate", "center"))),
    ("engine", "Engine", (
        Item("rpm", "bar"), Item("water_temp", "bar"), Item("oil_temp", "bar"), Item("fuel", "bar"),
        Item("fuel_used", "bar"), Item("battery", "bar", scale=(0.0, 100.0)), Item("engine_map", "number"),
    )),
    ("tyres", "Tyres", (
        Item("all:tyre_temp", "wheels", heat=True), Item("all:tyre_pres", "wheels"),
        Item("all:tyre_wear", "wheels", scale=(0.0, 100.0)), Item("all:tyre_temp_in", "wheels", True),
        Item("all:tyre_temp_mid", "wheels", True), Item("all:tyre_temp_out", "wheels", True),
        Item("all:camber_spread", "wheels"), Item("all:tyre_load", "wheels"), Item("tyre_temp_spread", "bar"),
    )),
    ("brakes", "Brakes", (Item("all:brake_temp", "wheels", heat=True), Item("brake_bias", "number"))),
    ("chassis", "Chassis", (
        Item(G_ITEM, "g"), Item("slip_angle", "center"), Item("all:slip", "wheels"), Item("all:wheel_speed", "wheels"),
        Item("all:susp_defl", "wheels"), Item("all:ride_height", "wheels"),
    )),
    ("electronics", "Electronics", (
        Item("tc_active", "light"), Item("abs_active", "light"), Item("tc_level", "number"), Item("abs_level", "number"),
    )),
    ("track", "Track", (
        Item("track_position", "center"), Item("path_lateral", "center"), Item("pos_z", "bar"),
        Item("steering_rate", "center"),
    )),
)
MISSING: dict = {"ok": False}


def wheel_columns(key: str) -> list[str]:
    """Channel of each wheel of a combined wheel item"""
    return [f"{key[4:]}_{wheel}" for wheel in WHEELS]


def item_columns(item: Item) -> list[str]:
    """Chart channels of item: item shown while one of them is shown on charts (one wheel: 4 wheels tiles)"""
    if item.kind == "inputs":
        return list(CARD_CHANNELS)
    if item.kind == "g":
        return list(G_CHANNELS)
    if item.kind == "wheels":
        return [item.key, *wheel_columns(item.key)]
    return [item.key]


def other_items() -> list[Item]:
    """Channels of no group (added later), shown as bars in Other group"""
    grouped = {column for _, _, items in GROUPS for item in items for column in item_columns(item)}
    return [Item(channel.column, "bar") for channel in CHANNELS
            if channel.column not in grouped and not channel.column.startswith(MATH_PREFIX)
            and not channel.parts]


def pedal_value(value: float | None) -> float:
    """Pedal input 0-1 for inputs tab, -1 if not recorded (or past end of lap)"""
    return -1.0 if value is None else min(max(value, 0.0), 1.0)


def value_text(channel: Channel, value: float) -> str:
    """Value of item: percent, signed delta or whole number like charts, else fewer decimals for larger values"""
    column = channel.column
    if channel.fixed_range in PERCENT_RANGES or column in DELTA_CHANNELS or column in INTEGER_CHANNELS:
        return format_channel_value(channel, value)
    size = abs(value)
    return number_text(value, 0 if size >= 100 else 1 if size >= 10 else 2)


def fraction(value: float, low: float, high: float) -> float:
    return min(max((value - low) / (high - low), 0.0), 1.0) if high > low else 0.0


class DashboardTab(BackendBase):
    """Simple view of lap viewer page (dashboardChanged, dashboardCatalog & dashboardLayout: see lap_backend)"""

    def load_dashboard(self, setting: dict):
        """Simple view state (items shown: channels shown on charts)"""
        self._dashboard_items: list[tuple[Item, Channel | None]] = []  # shown items in layout order
        self._clutch_used: dict[str, tuple] = {}  # lap key: lap data, clutch pressed in lap (pedal cards)
        self._dashboard_opened = False  # simple view shown once: its series built with charts

    def dashboard_groups(self) -> list[tuple[str, str, list[Item]]]:
        """Every group with its items: math channels & channels of no group in groups of their own"""
        groups = [(key, title, list(items)) for key, title, items in GROUPS]
        math_items = [Item(column, "bar") for column in CHANNEL_MAP if column.startswith(MATH_PREFIX)]
        if math_items:
            groups.append(("math", "Math Channels", math_items))
        extra = other_items()
        if extra:
            groups.append(("other", "Other", extra))
        return groups

    def dashboard_columns(self) -> list[str]:
        """Channels simple view reads at cursor (shown items, pedal cards) once it was opened, else none: their
        series & value ranges built with charts in background (see update_chart)"""
        if not self._dashboard_opened:
            return []
        columns: list[str] = []
        for _, _, items in self.dashboard_groups():
            for item in items:
                if not self.item_shown(item):
                    continue
                if item.kind == "inputs":
                    columns += INPUTS_COLUMNS
                elif item.kind == "g":
                    columns += ["accel_lat", "accel_long"]
                elif item.kind == "wheels":
                    columns += wheel_columns(item.key)
                else:
                    columns.append(item.key)
        return list(dict.fromkeys(columns))

    def item_shown(self, item: Item) -> bool:
        return any(column in self.visible for column in item_columns(item))

    def item_available(self, item: Item) -> bool:
        """Item recorded in at least one shown lap"""
        if item.kind == "inputs":
            return bool(self.data.laps)
        if item.kind == "g":
            return self.data.available(CHANNEL_MAP["accel_lat"]) and self.data.available(CHANNEL_MAP["accel_long"])
        channel = CHANNEL_MAP.get(item.key)
        return channel is not None and self.data.available(channel)

    @staticmethod
    def item_title(item: Item) -> str:
        if item.kind == "inputs":
            return tr("Pedals & Steering Wheel")
        if item.kind == "g":
            return tr("G Circle")
        channel = CHANNEL_MAP[item.key]
        return tr(channel.group) if item.kind == "wheels" and channel.group else channel_title(channel)

    def dashboard_catalog(self) -> list[dict]:
        """Show menu: every group & its chart channels, shown, recorded in shown laps; channel of one wheel as
        detail (listed while shown or searched)"""
        catalog = []
        for key, title, items in self.dashboard_groups():
            channels = []
            for item in items:
                for column in item_columns(item):
                    channel = CHANNEL_MAP.get(column)
                    if channel is None:
                        continue
                    channels.append({
                        "key": column, "title": channel_title(channel), "shown": column in self.visible,
                        "available": not self.data.laps or self.data.available(channel),
                        "detail": item.kind == "wheels" and column != item.key,
                        "search": f"{channel_title(channel)} {channel.title} {tr(title)}".lower(),
                    })
            catalog.append({"key": key, "title": tr(title), "items": channels})
        return catalog

    def dashboard_layout(self) -> list[dict]:
        """Groups & items shown (recorded & picked), index of each item in values read at cursor"""
        self._dashboard_items = []
        layout = []
        for key, title, items in self.dashboard_groups():
            shown = []
            for item in items:
                if not self.item_shown(item) or not self.item_available(item):
                    continue
                channel = CHANNEL_MAP.get(item.key)
                unit = self.data.unit_of(channel) if channel is not None else ""
                shown.append({"key": item.key, "kind": item.kind, "title": self.item_title(item), "unit": unit,
                              "heat": item.heat, "index": len(self._dashboard_items)})
                self._dashboard_items.append((item, channel))
            if shown:
                layout.append({"key": key, "title": tr(title), "items": shown})
        return layout

    @Slot(str, bool)
    def setDashboardGroup(self, group: str, shown: bool):
        """Every channel of group (one wheel ones aside) shown on charts, or none of it"""
        for key, _, items in self.dashboard_groups():
            if key != group:
                continue
            columns = [column for item in items for column in item_columns(item) if column in CHANNEL_MAP]
            if shown:
                details = {column for item in items if item.kind == "wheels" for column in wheel_columns(item.key)}
                self.visible += [column for column in columns if column not in self.visible and column not in details]
            else:
                self.visible = [column for column in self.visible if column not in columns]
            self.channels_updated()

    # Values at cursor
    def item_range(self, item: Item, channel: Channel) -> tuple[float, float]:
        """Value range of item: fixed, else over shown laps (wheels: of the 4 wheels together), symmetric around 0
        (center)"""
        if item.scale is not None:
            return item.scale
        low, high = self.data.value_range(channel)
        if item.kind == "center":
            limit = max(abs(low), abs(high)) or 1.0
            return -limit, limit
        return low, high

    @Slot(float, result=list)
    def dashboardCursor(self, x: float) -> list[dict]:
        """Value of each shown item (key: item shown, values of laps) for each shown lap at axis position, in layout
        order (key: values of former layout not read by QML once items shown change)

        bar: text & fraction of range (a), center: text & -1 to 1 (a), light: on, wheels: 4 texts & fractions,
        g: x & y as fraction of G limit. {"ok": False} past end of lap or not recorded in lap.
        """
        result: list[dict] = []
        laps = self.data.laps
        for item, channel in self._dashboard_items:
            if item.kind == "inputs":
                result.append({"key": item.key, "laps": []})
                continue
            if item.kind == "g":
                lateral, longitudinal = CHANNEL_MAP["accel_lat"], CHANNEL_MAP["accel_long"]
                limit = max(max(abs(value) for value in self.data.value_range(lateral)),
                            max(abs(value) for value in self.data.value_range(longitudinal)), 1.0)
                limit = float(math.ceil(limit))
                values = []
                for lap in laps:
                    across, along = self.data.value_at(lateral, lap, x), self.data.value_at(longitudinal, lap, x)
                    # Game: lateral positive to the left, longitudinal positive when braking (right & up drawn +)
                    values.append(MISSING if across is None or along is None else
                                  {"ok": True, "x": -across / limit, "y": -along / limit, "limit": limit})
                result.append({"key": item.key, "laps": values})
                continue
            assert channel is not None
            if item.kind == "wheels":
                low, high = self.item_range(item, channel)
                parts = [CHANNEL_MAP[column] for column in wheel_columns(item.key)]
                values = []
                for lap in laps:
                    readings = [self.data.value_at(part, lap, x) for part in parts]
                    if all(reading is None for reading in readings):
                        values.append(MISSING)
                        continue
                    values.append({
                        "ok": True,
                        "t": ["" if reading is None else value_text(part, reading)
                              for part, reading in zip(parts, readings)],
                        "a": [-1.0 if reading is None else fraction(reading, low, high) for reading in readings],
                    })
                result.append({"key": item.key, "laps": values})
                continue
            low, high = self.item_range(item, channel)
            values = []
            for lap in laps:
                value = self.data.value_at(channel, lap, x)
                if (value is None and item.key == "delta" and lap is self.data.reference and self.data.deltas
                        and self.data.value_at(CHANNEL_MAP["speed_kph"], lap, x) is not None):
                    value = 0.0  # reference lap (before its end): no gap to itself
                if value is None:
                    values.append(MISSING)
                elif item.kind == "light":
                    values.append({"ok": True, "on": value >= 0.5})
                elif item.kind == "center":
                    values.append({"ok": True, "t": value_text(channel, value),
                                   "a": min(max(value / high, -1.0), 1.0)})
                else:
                    values.append({"ok": True, "t": value_text(channel, value), "a": fraction(value, low, high)})
            result.append({"key": item.key, "laps": values})
        return result

    # Pedals & steering wheel cards: each lap at cursor, drawn like overlays
    @Slot(float, result=list)
    def inputsCursor(self, x: float) -> list[dict]:
        """Throttle, brake & clutch (0-1, -1 if not recorded), steering (-1 to 1), steering wheel angle (degrees,
        0 if wheel rotation not recorded), gear & speed of each shown lap at axis position"""
        if len(self._clutch_used) > len(self.data.laps):  # laps no longer shown forgotten
            shown = {lap.key for lap in self.data.laps}
            self._clutch_used = {key: value for key, value in self._clutch_used.items() if key in shown}
        laps = []
        for lap in self.data.laps:
            values = {column: self.data.value_at(CHANNEL_MAP[column], lap, x)
                      for column in ("throttle", "brake", "clutch", "steering", "speed_kph")}
            gear_xs, gear_ys = self.data.series(CHANNEL_MAP["gear"], lap)
            gear_index = bisect.bisect_right(gear_xs, x) - 1  # gear held until next sample (not interpolated)
            gear = round(gear_ys[gear_index]) if gear_xs and gear_xs[0] <= x <= gear_xs[-1] else None
            steering = values["steering"]
            rotation = lap.data.meta.get("steering_range")
            rotation = float(rotation) if isinstance(rotation, (int, float)) and rotation > 0 else 0.0
            speed = values["speed_kph"]
            laps.append({
                "lap": lap.key, "label": self.short_label(lap.key), "color": lap.color.name(),
                "ended": all(value is None for value in values.values()),  # past end of lap
                "throttle": pedal_value(values["throttle"]),
                "brake": pedal_value(values["brake"]),
                "clutch": pedal_value(values["clutch"]) if self.clutch_used(lap) else -1.0,
                "steering": 0.0 if steering is None else min(max(steering, -1.0), 1.0),
                "angle": (steering or 0.0) * rotation / 2,
                "rotation": rotation,
                "gear": "" if gear is None else ("R" if gear < 0 else "N" if gear == 0 else str(gear)),
                "speed": "" if speed is None else f"{speed:.0f}",
                "speedUnit": self.data.unit_of(CHANNEL_MAP["speed_kph"]),
            })
        return laps

    def clutch_used(self, lap: PlotLap) -> bool:
        """Clutch pressed somewhere in lap (else hidden in inputs tab: paddle shift cars), worked out once per lap"""
        cached = self._clutch_used.get(lap.key)
        if cached is None or cached[0] is not lap.data:
            cached = self._clutch_used[lap.key] = (lap.data, max(lap.data.columns.get("clutch") or [0.0]) > 0.05)
        return cached[1]
