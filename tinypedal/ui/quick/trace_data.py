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
Channel series of compared laps along lap distance or lap time (no drawing)

Same values as lap viewer charts (TracePlot): user units, delta against reference lap, time axis.
"""

from __future__ import annotations

from ...userfile.telemetry_lap import (
    compute_delta,
    delta_rate,
    interpolate,
    monotonic_distance,
    sector_bounds,
)
from ..lap_viewer import (
    DELTA_CHANNELS,
    Channel,
    PlotLap,
    delta_limit,
    display_units,
    format_channel_value,
)


class TraceData:
    """Series, value ranges & axis conversion of displayed laps

    Axis position (x) is lap distance, or lap time of each lap (time_axis).
    Track distance of reference lap is used for maps & corners (see distance_at_x).
    """

    def __init__(self):
        self.laps: list[PlotLap] = []
        self.reference: PlotLap | None = None
        self.deltas: dict[str, tuple[list[float], list[float]]] = {}
        self.sector_lines: list[float] = []
        self.time_axis = False
        self.units = display_units()
        self._times: dict[str, tuple[list[float], list[float]]] = {}
        self._series: dict[tuple[str, str, bool], tuple[list[float], list[float]]] = {}
        self._ranges: dict[tuple[str, bool], tuple[float, float]] = {}

    def compared(self) -> list[PlotLap]:
        return [lap for lap in self.laps if lap is not self.reference]

    def set_laps(self, laps: list[PlotLap], reference_key: str = ""):
        self.laps = laps
        self.reference = next((lap for lap in laps if lap.key == reference_key), laps[0] if laps else None)
        self.deltas = {}
        if self.reference is not None:
            for lap in self.compared():
                points = compute_delta(self.reference.data, lap.data)
                if points:
                    self.deltas[lap.key] = ([point[0] for point in points], [point[1] for point in points])
        self.sector_lines = sector_bounds(self.reference.data) if self.reference else []
        self.units = display_units()
        self._series = {}
        self._times = {}
        self._ranges = {}

    def set_time_axis(self, enabled: bool):
        self.time_axis = enabled

    # Axis conversion
    def lap_times(self, lap: PlotLap) -> tuple[list[float], list[float]]:
        """Distances & lap times of lap, increasing distance"""
        cached = self._times.get(lap.key)
        if cached is None:
            if "lap_time" in lap.data.columns:
                cached = monotonic_distance(lap.data, "lap_time")
            else:  # no time recorded: distance used
                distances = monotonic_distance(lap.data, "distance")[0]
                cached = (distances, list(distances))
            self._times[lap.key] = cached
        return cached

    def x_at_distance(self, distance: float) -> float:
        """Axis position of reference lap distance"""
        if not self.time_axis or self.reference is None:
            return distance
        distances, times = self.lap_times(self.reference)
        return interpolate(distances, times, distance) if distances else distance

    def distance_at_x(self, x: float) -> float:
        """Reference lap distance at axis position"""
        if not self.time_axis or self.reference is None:
            return x
        distances, times = self.lap_times(self.reference)
        return interpolate(times, distances, x) if times else x

    def max_x(self) -> float:
        """End of horizontal axis: longest lap distance, or lap time"""
        if self.time_axis:
            return max((self.lap_times(lap)[1][-1] for lap in self.laps if self.lap_times(lap)[1]),
                       default=1.0) or 1.0
        return max((lap.data.distance[-1] for lap in self.laps if len(lap.data)), default=1.0) or 1.0

    # Values
    def unit_of(self, channel: Channel) -> str:
        if channel.quantity in self.units:
            return self.units[channel.quantity][1]
        return channel.unit

    def series(self, channel: Channel, lap: PlotLap, time_axis: bool | None = None,
               ) -> tuple[list[float], list[float]]:
        """Channel samples of lap by increasing axis position, in user units, cached"""
        use_time = self.time_axis if time_axis is None else time_axis
        key = (lap.key, channel.column, use_time)
        cached = self._series.get(key)
        if cached is not None:
            return cached
        if channel.column == "delta":
            distances, values = self.deltas.get(lap.key, ([], []))
        elif channel.column == "delta_rate":
            distances, deltas = self.deltas.get(lap.key, ([], []))
            values = delta_rate(distances, deltas)
        elif channel.column in lap.data.columns:
            distances, values = monotonic_distance(lap.data, channel.column)
        else:
            distances, values = [], []
        convert = self.units.get(channel.quantity, (None, ""))[0] if channel.quantity else None
        if convert is not None:
            values = [convert(value) for value in values]
        xs = distances
        if use_time and distances:
            lap_distances, times = self.lap_times(lap)
            if len(lap_distances) == len(distances):  # same samples
                xs = times
            else:
                xs = [interpolate(lap_distances, times, distance) for distance in distances]
        cached = (xs, values)
        self._series[key] = cached
        return cached

    def value_range(self, channel: Channel) -> tuple[float, float]:
        """Plotted range of channel over every lap (5% margin), symmetric for deltas"""
        if channel.fixed_range:
            return channel.fixed_range
        key = (channel.column, self.time_axis)
        cached = self._ranges.get(key)
        if cached is not None:
            return cached
        if channel.column in DELTA_CHANNELS:
            limit = delta_limit([self.series(channel, lap)[1] for lap in self.compared()])
            self._ranges[key] = (-limit, limit)
            return -limit, limit
        low, high = float("inf"), float("-inf")
        for lap in self.laps:
            values = self.series(channel, lap)[1]
            if values:
                low, high = min(low, min(values)), max(high, max(values))
        if low > high:
            result = (0.0, 1.0)
        else:
            if high - low < 1e-6:
                high = low + 1
            padding = (high - low) * 0.05
            result = (low - padding, high + padding)
        self._ranges[key] = result
        return result

    def values_at(self, channel: Channel, x: float) -> list[tuple[PlotLap, str]]:
        """Value text of each lap at axis position (none past end of lap)"""
        values = []
        for lap in self.laps:
            xs, ys = self.series(channel, lap)
            if xs and xs[0] <= x <= xs[-1]:
                values.append((lap, format_channel_value(channel, interpolate(xs, ys, x))))
        return values
