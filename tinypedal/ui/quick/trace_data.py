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

Same values as lap viewer charts (TracePlot): user units, delta against reference lap, time axis,
computed channels (wheel slip, steering rate...), smoothing of noisy channels.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from itertools import accumulate

from ...userfile.corner_analysis import resample_sorted
from ...userfile.telemetry_lap import (
    compute_delta,
    delta_rate,
    interpolate,
    monotonic_distance,
    sector_bounds,
)
from ..lap_viewer import (
    CHANNEL_MAP,
    DELTA_CHANNELS,
    WHEELS,
    Channel,
    PlotLap,
    delta_limit,
    display_units,
    format_channel_value,
)

ENVELOPE_POINTS = 1500  # grid points of min / max band over displayed laps
SLIP_MIN_SPEED = 30.0  # km/h, wheel slip not computed slower (division by small speed)


def moving_average(values: list[float], points: int) -> list[float]:
    """Centered moving average over points samples (cumulative sums: any width costs the same)"""
    count = len(values)
    if points <= 1 or count < 3:
        return values
    half = points // 2
    sums = [0.0, *accumulate(values)]
    return [
        (sums[min(index + half + 1, count)] - sums[max(index - half, 0)])
        / (min(index + half + 1, count) - max(index - half, 0))
        for index in range(count)
    ]


def channel_sources(channel: Channel) -> tuple[str, ...]:
    """Recorded columns needed to draw channel"""
    if channel.parts:
        return ()
    return channel.sources or (channel.column,)


class TraceData:
    """Series, value ranges & axis conversion of displayed laps

    Axis position (x) is lap distance, or lap time of each lap (time_axis).
    Track distance of reference lap is used for maps & corners (see distance_at_x).
    Cached series of laps still shown are kept when laps change (only new laps are computed),
    those depending on reference lap (delta) only while reference stays the same.
    """

    def __init__(self):
        self.laps: list[PlotLap] = []
        self.reference: PlotLap | None = None
        self.deltas: dict[str, tuple[list[float], list[float]]] = {}
        self.sector_lines: list[float] = []
        self.time_axis = False
        self.smoothing = 0  # moving average samples of noisy channels, 0 = off
        self.delta_window = 40.0  # meters, time gain/loss measured over
        self.units = display_units()
        self._times: dict[str, tuple[list[float], list[float]]] = {}
        self._series: dict[tuple, tuple[list[float], list[float]]] = {}
        self._ranges: dict[tuple, tuple[float, float]] = {}

    def compared(self) -> list[PlotLap]:
        return [lap for lap in self.laps if lap is not self.reference]

    def set_laps(self, laps: list[PlotLap], reference_key: str = ""):
        previous = {lap.key: lap.data for lap in self.laps}
        previous_reference = self.reference.key if self.reference is not None else ""
        self.laps = laps
        self.reference = next((lap for lap in laps if lap.key == reference_key), laps[0] if laps else None)
        reference = self.reference.key if self.reference is not None else ""
        kept = {lap.key for lap in laps if previous.get(lap.key) is lap.data}  # same lap data loaded
        units = display_units()
        if units.keys() != self.units.keys() or any(
                self.units[name][1] != units[name][1] for name in units):  # unit setting changed
            kept = set()
        self.units = units
        same_reference = reference == previous_reference and reference in kept
        self.deltas = {key: value for key, value in self.deltas.items() if same_reference and key in kept}
        if self.reference is not None:
            for lap in self.compared():
                if lap.key not in self.deltas:
                    points = compute_delta(self.reference.data, lap.data)
                    if points:
                        self.deltas[lap.key] = ([point[0] for point in points], [point[1] for point in points])
        self.sector_lines = sector_bounds(self.reference.data) if self.reference else []
        self._series = {
            key: value for key, value in self._series.items()
            if key[0] in kept and (same_reference or key[1] not in DELTA_CHANNELS)
        }
        self._times = {key: value for key, value in self._times.items() if key in kept}
        self._ranges = {}

    def set_time_axis(self, enabled: bool):
        self.time_axis = enabled
        self._ranges = {}

    def set_smoothing(self, points: int):
        """Moving average of noisy channels (series recomputed)"""
        if points != self.smoothing:
            self.smoothing = points
            self._series = {key: value for key, value in self._series.items() if not CHANNEL_MAP[key[1]].noisy}
            self._ranges = {}

    def set_delta_window(self, meters: float):
        if meters != self.delta_window:
            self.delta_window = meters
            self._series = {key: value for key, value in self._series.items() if key[1] != "delta_rate"}
            self._ranges = {}

    def signature(self, channel: Channel) -> str:
        """Settings a series depends on, part of its vertex key (series redrawn when they change)"""
        parts = [str(int(self.time_axis))]
        if channel.noisy:
            parts.append(f"s{self.smoothing}")
        if channel.column in DELTA_CHANNELS and self.reference is not None:
            parts.append(f"r{self.reference.key}")
        if channel.column == "delta_rate":
            parts.append(f"w{self.delta_window:g}")
        return "|".join(parts)

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

    def lap_distance_at_x(self, lap: PlotLap, x: float) -> float:
        """Where lap is at axis position: same distance, or (time axis) its own distance at that lap time"""
        if not self.time_axis:
            return x
        distances, times = self.lap_times(lap)
        return interpolate(times, distances, x) if times else x

    def reference_time_at_x(self, x: float) -> float:
        """Reference lap time at axis position (playback)"""
        if self.time_axis or self.reference is None:
            return x
        distances, times = self.lap_times(self.reference)
        return interpolate(distances, times, x) if distances else x

    def x_at_reference_time(self, seconds: float) -> float:
        """Axis position reached by reference lap at lap time (playback)"""
        if self.time_axis or self.reference is None:
            return seconds
        distances, times = self.lap_times(self.reference)
        return interpolate(times, distances, seconds) if times else seconds

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

    def available(self, channel: Channel) -> bool:
        """Whether channel can be drawn for at least one displayed lap"""
        if channel.parts:
            return any(self.available(CHANNEL_MAP[part]) for part in channel.parts)
        if channel.column in DELTA_CHANNELS:
            return bool(self.deltas)
        sources = channel_sources(channel)
        return any(
            all(source in lap.data.columns for source in sources)
            # Wheel speeds read as 0 when not available from game
            and all(any(lap.data.columns[source]) for source in sources if source.startswith("wheel_speed"))
            for lap in self.laps
        )

    def computed(self, channel: Channel, lap: PlotLap) -> tuple[list[float], list[float]]:
        """Distances & values of channel (recorded or computed) by increasing distance, recorded unit"""
        column = channel.column
        columns = lap.data.columns
        if column == "delta":
            return self.deltas.get(lap.key, ([], []))
        if column == "delta_rate":
            distances, deltas = self.deltas.get(lap.key, ([], []))
            return distances, delta_rate(distances, deltas, self.delta_window)
        if not all(source in columns for source in channel_sources(channel)):
            return [], []
        if column == "steering_rate":
            distances, steering = monotonic_distance(lap.data, "steering")
            times = monotonic_distance(lap.data, "lap_time")[1]
            count = len(distances)
            values = [0.0] * count
            for index in range(1, count - 1):
                span = times[index + 1] - times[index - 1]
                if span > 0:
                    values[index] = (steering[index + 1] - steering[index - 1]) / span * 100
            return distances, values
        if column == "fuel_used":
            distances, fuel = monotonic_distance(lap.data, "fuel")
            return distances, [fuel[0] - value for value in fuel] if fuel else []
        if column == "tyre_temp_spread":
            distances = monotonic_distance(lap.data, "tyre_temp_fl")[0]
            temps = [monotonic_distance(lap.data, f"tyre_temp_{wheel}")[1] for wheel in WHEELS]
            return distances, [max(values) - min(values) for values in zip(*temps)]
        if column.startswith("slip_"):
            distances, wheel = monotonic_distance(lap.data, f"wheel_speed_{column[5:]}")
            speeds = monotonic_distance(lap.data, "speed_kph")[1]
            return distances, [
                max(min((wheel_speed - speed) / speed * 100, 100.0), -100.0) if speed >= SLIP_MIN_SPEED else 0.0
                for wheel_speed, speed in zip(wheel, speeds)
            ]
        return monotonic_distance(lap.data, column)

    def series(self, channel: Channel, lap: PlotLap, time_axis: bool | None = None,
               ) -> tuple[list[float], list[float]]:
        """Channel samples of lap by increasing axis position, in user units, cached"""
        use_time = self.time_axis if time_axis is None else time_axis
        key = (lap.key, channel.column, use_time)
        cached = self._series.get(key)
        if cached is not None:
            return cached
        distances, values = self.computed(channel, lap)
        convert = self.units.get(channel.quantity, (None, ""))[0] if channel.quantity else None
        if convert is not None:
            values = [convert(value) for value in values]
        if channel.noisy and self.smoothing > 1:
            values = moving_average(values, self.smoothing)
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
        for part in channel.parts or (channel.column,):
            for lap in self.laps:
                values = self.series(CHANNEL_MAP[part], lap)[1]
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

    def value_at(self, channel: Channel, lap: PlotLap, x: float) -> float | None:
        """Value of lap at axis position, None past end of lap"""
        xs, ys = self.series(channel, lap)
        if xs and xs[0] <= x <= xs[-1]:
            return interpolate(xs, ys, x)
        return None

    def values_at(self, channel: Channel, x: float) -> list[tuple[PlotLap, str]]:
        """Value text of each lap at axis position (none past end of lap)"""
        values = []
        for lap in self.laps:
            value = self.value_at(channel, lap, x)
            if value is not None:
                values.append((lap, format_channel_value(channel, value)))
        return values

    def envelope(self, channel: Channel) -> tuple[list[float], list[float], list[float]]:
        """Lowest & highest value of displayed laps along axis (consistency band), empty under 3 laps"""
        if len(self.laps) < 3 or channel.parts or channel.column in DELTA_CHANNELS:
            return [], [], []
        series = [self.series(channel, lap) for lap in self.laps]
        series = [(xs, ys) for xs, ys in series if len(xs) > 1]
        if len(series) < 3:
            return [], [], []
        end = min(xs[-1] for xs, _ in series)  # where every lap still has values
        start = max(xs[0] for xs, _ in series)
        if end <= start:
            return [], [], []
        step = (end - start) / ENVELOPE_POINTS
        grid = [start + index * step for index in range(ENVELOPE_POINTS + 1)]
        columns = [resample_sorted(xs, ys, grid) for xs, ys in series]
        return grid, [min(values) for values in zip(*columns)], [max(values) for values in zip(*columns)]

    def range_stats(self, start: float, end: float, channels: list[Channel]) -> list[dict]:
        """Each lap between axis positions: time taken, then min, max & mean of each channel"""
        if end < start:
            start, end = end, start
        result = []
        for lap in self.laps:
            begin, finish = self.lap_distance_at_x(lap, start), self.lap_distance_at_x(lap, end)
            distances, times = self.lap_times(lap)
            if not distances or finish <= begin:
                continue
            time_taken = interpolate(distances, times, finish) - interpolate(distances, times, begin)
            values = []
            for channel in channels:
                xs, ys = self.series(channel, lap)
                low, high = bisect_left(xs, start), bisect_right(xs, end)
                part = ys[low:high]
                values.append((min(part), max(part), sum(part) / len(part)) if part else None)
            result.append({"lap": lap, "time": time_taken, "distance": finish - begin, "values": values})
        return result
