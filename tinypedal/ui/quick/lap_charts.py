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
Lap viewer chart tools (mixin of LapViewerBackend): math channels, value axis of each panel (zoom & autoscale to
visible part), laps aligned on a braking point
"""

from __future__ import annotations

import math

from PySide6.QtCore import Slot

from ...i18n import tr, trm
from ...userfile.corner_analysis import BRAKE_ON, braking_start
from ..lap_viewer import (
    CHANNEL_MAP,
    DEFAULT_CHANNELS,
    DELTA_CHANNELS,
    MATH_PREFIX,
    PERCENT_RANGES,
    Channel,
    PlotLap,
    distance_text,
    format_axis_value,
    math_channel,
    nice_step,
    save_viewer_setting,
    set_math_channels,
)
from .lap_base import BackendBase
from .math_channels import (
    MAX_CHANNELS,
    PRESETS,
    YAW_RATE,
    MathChannel,
    expression_error,
    name_error,
    parse_channels,
    saved_channels,
)

ALIGN_MAX_OFFSET = 250.0  # meters, a lap braking farther from reference lap braking point is not shifted
ALIGN_SEARCH = 200.0  # meters before corner start (reference lap braking) braking of other laps is looked for


class ChartTools(BackendBase):
    """Chart tools of lap viewer page"""

    # Math channels: user expressions over channels, saved with viewer settings
    def load_math_channels(self, setting: dict):
        self._math = parse_channels(setting.get("math_channels"))
        self.apply_math_channels()

    def apply_math_channels(self):
        """Math channels known to charts (CHANNEL_MAP) & computed by trace data"""
        set_math_channels([math_channel(channel.name, channel.unit) for channel in self._math])
        self.data.set_math({channel.column: channel.expression for channel in self._math})

    def math_menu(self) -> list[dict]:
        """Math channels in channel menu: column, title, group, visible, available in shown laps"""
        group = tr("Math Channels")
        return [{
            "column": channel.column, "group": group, "title": channel.name,
            "search": f"{channel.name} {channel.expression} {group}".lower(),
            "visible": channel.column in self.visible,
            "available": not self.data.laps or self.data.available(CHANNEL_MAP[channel.column]),
        } for channel in self._math]

    def math_known(self, name: str) -> bool:
        """Whether a math channel can use name: recorded in shown laps, computed channel, yaw rate"""
        if name == YAW_RATE:
            return True
        channel = CHANNEL_MAP.get(name)
        if channel is not None and not channel.parts and not name.startswith(MATH_PREFIX):
            return True
        return any(name in lap.data.columns for lap in self.data.laps)

    def math_inputs(self) -> list[str]:
        """Names math channels can use: recorded columns of shown laps, computed channels, yaw rate"""
        names = {name for lap in self.data.laps for name in lap.data.columns}
        names.update(column for column, channel in CHANNEL_MAP.items()
                     if not channel.parts and not column.startswith(MATH_PREFIX))
        names.add(YAW_RATE)
        return sorted(names)

    def math_error(self, old_name: str, name: str, expression: str) -> str:
        """Why math channel is refused (translated), "" if fine"""
        taken = [channel.name for channel in self._math if channel.name != old_name]
        error = name_error(name, taken)
        if not error and not old_name and len(self._math) >= MAX_CHANNELS:
            error = "Too many math channels"
        if not error:
            error = expression_error(expression, self.math_known)
        return trm(tr(error)) if error else ""

    @Slot(str, str, str, result=str)
    def checkMathChannel(self, old_name: str, name: str, expression: str) -> str:
        """Editor check while typing: why math channel is refused, "" if fine"""
        return self.math_error(old_name, name, expression)

    @Slot(str, str, str, str, result=str)
    def saveMathChannel(self, old_name: str, name: str, expression: str, unit: str) -> str:
        """Add math channel (old_name empty) or change one, shown on charts, returns why refused ("" if saved)"""
        error = self.math_error(old_name, name, expression)
        if error:
            return error
        channel = MathChannel(name, expression.strip(), unit.strip()[:12])
        old = next((item for item in self._math if item.name == old_name), None) if old_name else None
        if old is not None:
            self._math = [channel if item is old else item for item in self._math]
            self.visible = [channel.column if column == old.column else column for column in self.visible]
        else:
            self._math.append(channel)
        if channel.column not in self.visible:
            self.visible.append(channel.column)
        self.apply_math_channels()
        save_viewer_setting(self.folder, math_channels=saved_channels(self._math), channels=self.visible)
        self.channels_updated(save=False)
        self.mathChanged.emit()
        return ""

    @Slot(str)
    def removeMathChannel(self, name: str):
        old = next((item for item in self._math if item.name == name), None)
        if old is None:
            return
        self._math = [item for item in self._math if item is not old]
        self.visible = [column for column in self.visible if column != old.column] or list(DEFAULT_CHANNELS)
        self._weights.pop(old.column, None)
        self.apply_math_channels()
        save_viewer_setting(self.folder, math_channels=saved_channels(self._math), channels=self.visible,
                            panel_weights=self._weights)
        self.channels_updated(save=False)
        self.mathChanged.emit()

    @Slot(int, result=str)
    def addMathPreset(self, index: int) -> str:
        """Add built-in math channel (understeer angle, pedal rates), returns why refused ("" if added)"""
        if not 0 <= index < len(PRESETS):
            return ""
        name, expression, unit = PRESETS[index]
        return self.saveMathChannel("", tr(name), expression, unit)

    # Value axis of each panel: whole range or autoscaled to visible part of lap
    def axis_ticks(self, channel: Channel, low: float, high: float) -> list[dict]:
        """Value grid of panel range: round values (quarters for pedals & steering)"""
        span = high - low
        if channel.fixed_range in PERCENT_RANGES:
            return [{"value": low + span * quarter / 4, "text": format_axis_value(channel, low + span * quarter / 4, span)}
                    for quarter in (1, 2, 3)]
        step = nice_step(span, 5)
        return [
            {"value": value, "text": format_axis_value(channel, value, span)}
            for value in (math.ceil(low / step) * step + index * step for index in range(10))
            if low < value < high and value - low > step * 0.25 and high - value > step * 0.25
        ]

    @Slot(str, float, float, result=dict)
    def valueAxis(self, column: str, low: float, high: float) -> dict:
        """Panel value range, its labels & grid (zoomed panel)"""
        channel = CHANNEL_MAP.get(column)
        if channel is None or not high > low:
            return {}
        span = high - low
        return {"low": low, "high": high, "ticks": self.axis_ticks(channel, low, high),
                "lowText": format_axis_value(channel, low, span), "highText": format_axis_value(channel, high, span)}

    @Slot(str, float, float, result=list)
    def axisTicks(self, column: str, low: float, high: float) -> list[dict]:
        """Round values between low & high (zoomed XY axis): value, text"""
        channel = CHANNEL_MAP.get(column)
        if channel is None or not high > low:
            return []
        step = nice_step(high - low, 4)
        first = math.ceil(low / step) * step
        return [{"value": value, "text": format_axis_value(channel, value, high - low)}
                for value in (first + index * step for index in range(10)) if value <= high]

    @Slot(str, float, float, result=dict)
    def autoscaleAxis(self, column: str, start: float, end: float) -> dict:
        """Panel value range fitting shown laps between axis positions (autoscaled panel)"""
        channel = CHANNEL_MAP.get(column)
        if channel is None:
            return {}
        return self.valueAxis(column, *self.data.visible_range(channel, min(start, end), max(start, end)))

    @Slot(str, bool)
    def setPanelAutoscale(self, column: str, enabled: bool):
        """Panel values fitted to visible part of lap while zooming (saved for this channel)"""
        if column not in CHANNEL_MAP or (column in self._autoscale) == enabled:
            return
        if enabled:
            self._autoscale.add(column)
        else:
            self._autoscale.discard(column)
        save_viewer_setting(self.folder, panel_autoscale=sorted(self._autoscale))
        self._panels = [dict(panel, autoscale=panel["column"] in self._autoscale) for panel in self._panels]
        self.panelsChanged.emit()

    # Laps aligned on braking point of a corner: shifted along distance axis
    def align_row(self) -> int:
        """Corner row laps are aligned on (row covering chosen apex), -1 if none"""
        if self._align_apex < 0:
            return -1
        return next((index for index, row in enumerate(self._corner_rows)
                     if row.corner.start <= self._align_apex <= row.corner.end), -1)

    def braking_point(self, lap: PlotLap, index: int) -> float:
        """Reference distance where lap starts braking for corner (corner row): looked for from ALIGN_SEARCH before
        corner start (a lap may brake before reference lap) to lap apex, -1 if none"""
        row = self._corner_rows[index]
        stats = self.lap_corner_stats(lap)[1][index]
        sampled = self.resampled(lap)
        brake = sampled.column("brake")
        grid = sampled.grid
        if stats is None or not brake or len(grid) < 2:
            return -1.0
        first, last = sampled.indexes(row.corner.start - ALIGN_SEARCH, stats.apex)
        step = grid[1] - grid[0]
        found = braking_start(brake[first:last], last - first - 1, step) if last - first > 1 else -1
        if found < 0:
            return -1.0
        distance = grid[first + found]
        point = sampled.crossing("brake", distance - step, distance, BRAKE_ON)
        return point if point >= 0 else distance

    def alignment_offsets(self) -> dict[str, float]:
        """Meters each compared lap is shifted by: its braking start on reference lap braking start"""
        index = self.align_row()
        reference = self.data.reference
        if index < 0 or reference is None:
            return {}
        start = self.braking_point(reference, index)
        if start < 0:
            return {}
        offsets = {}
        for lap in self.data.compared():
            point = self.braking_point(lap, index)
            if point >= 0 and abs(start - point) <= ALIGN_MAX_OFFSET:
                offsets[lap.key] = round(start - point, 1)
        return offsets

    def update_alignment(self) -> bool:
        """Lap offsets of chosen corner applied to trace data, True if changed"""
        offsets = self.alignment_offsets()
        changed = offsets != self.data.offsets
        self.data.set_offsets(offsets)
        return changed

    @Slot(int)
    def alignBraking(self, index: int):
        """Align laps on braking start of corner (corner row), -1: laps back at their place"""
        apex = self._corner_rows[index].corner.apex if 0 <= index < len(self._corner_rows) else -1.0
        moved = apex != self._align_apex
        self._align_apex = apex
        if self.update_alignment():
            self._legend = [dict(row, offset=self.legend_offset(row["key"])) for row in self._legend]
            self.legend_model.sync(self._legend)
            self.build_panels()
            self.drop_unused_vertices()
            self.bump_revision()
            self.chartChanged.emit()
        elif moved:  # laps already there (or none to shift): alignment chip only
            self.cornersChanged.emit()

    @Slot(float)
    def alignBrakingAt(self, x: float):
        """Align laps on braking start of corner at axis position (chart menu), nearest corner if between two"""
        distance = self.data.distance_at_x(x)
        rows = self._corner_rows
        if not rows:
            return
        inside = next((index for index, row in enumerate(rows) if row.corner.start <= distance <= row.corner.end), -1)
        if inside < 0:
            inside = min(range(len(rows)), key=lambda index: abs(rows[index].corner.apex - distance))
        self.alignBraking(inside)

    def alignment_info(self) -> dict:
        """Corner laps are aligned on & offset of each lap, empty if not aligned"""
        index = self.align_row()
        if index < 0:
            return {}
        offsets = self.data.offsets
        return {
            "label": self.row_label(self._corner_rows[index]), "index": index, "timeAxis": self.data.time_axis,
            "laps": [{"label": self.short_label(lap.key), "color": lap.color.name(),
                      "offset": distance_text(offsets[lap.key], 1, sign=True)}
                     for lap in self.data.compared() if lap.key in offsets],
        }

    def legend_offset(self, key: str) -> str:
        """Offset of aligned lap (legend chip, shown on distance axis), empty if not shifted"""
        offset = self.data.offsets.get(key, 0.0)
        return distance_text(offset, 1, sign=True) if offset else ""

    def shift_key(self, lap_key: str, channel: Channel) -> str:
        """Part of series vertex key telling lap offset (aligned laps drawn again)"""
        offset = self.data.offsets.get(lap_key, 0.0)
        if not offset or self.data.time_axis or channel.column in DELTA_CHANNELS:
            return ""
        return f"|o{offset:g}"
