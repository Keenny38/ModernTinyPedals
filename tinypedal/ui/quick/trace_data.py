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

import math
import zlib
from array import array
from bisect import bisect_left, bisect_right
from collections.abc import Collection, Mapping, Sequence
from itertools import accumulate

from ...userfile.corner_analysis import resample_sorted
from ...userfile.lap_offset import aligned_on, anchored, is_recorded
from ...userfile.telemetry_lap import (
    LapData,
    compute_delta,
    delta_rate,
    delta_to_curve,
    distance_scale,
    interpolate,
    lap_time_curve,
    monotonic_distance,
    sector_bounds,
)
from ..lap_viewer import (
    CHANNEL_MAP,
    DELTA_CHANNELS,
    MATH_PREFIX,
    SETTING_CHANNELS,
    WHEELS,
    Channel,
    PlotLap,
    delta_limit,
    display_units,
    format_channel_value,
)
from .math_channels import YAW_RATE, MathError, derivative, evaluate, input_names, parse_expression, unwrapped

ENVELOPE_POINTS = 1500  # grid points of min / max band over displayed laps
SLIP_MIN_SPEED = 30.0  # km/h, wheel slip not computed slower (division by small speed)
SLIP_ANGLE_MIN_SPEED = 5.0  # m/s, body slip angle not computed slower
PLACEMENT_COLUMNS = ("path_lateral", "track_position")  # measured on map when circuit & edges known
AUTOSCALE_MARGIN = 0.05  # share of visible value range added above & below (autoscaled panel)


def moving_average(values: Sequence[float], points: int) -> list[float]:
    """Centered moving average over points samples (cumulative sums: any width costs the same)"""
    count = len(values)
    if points <= 1 or count < 3:
        return list(values)
    half = points // 2
    sums = [0.0, *accumulate(values)]
    return [
        (sums[min(index + half + 1, count)] - sums[max(index - half, 0)])
        / (min(index + half + 1, count) - max(index - half, 0))
        for index in range(count)
    ]


def packed(values: Sequence[float]) -> Sequence[float]:
    """Values as packed array (4 bytes a value instead of a float object), arrays & empty lists as they are"""
    return array("f", values) if isinstance(values, list) and values else values


def channel_sources(channel: Channel) -> tuple[str, ...]:
    """Recorded columns needed to draw channel"""
    if channel.parts:
        return ()
    return channel.sources or (channel.column,)


AlignedLap = tuple[LapData, LapData, LapData, float]  # lap aligned on: reference lap data, lap data, aligned, offset


def align_laps(laps: Sequence[tuple[str, LapData]], reference_key: str, anchor: tuple[str, LapData] | None,
               cache: Mapping[str, AlignedLap], compute: bool = True) -> tuple[dict[str, AlignedLap], str, int]:
    """Laps (key, data) not recorded by the app aligned on reference lap (see lap_offset): aligned lap of each lap key,
    key of lap recorded by the app the reference lap was aligned on first (empty: none) & samples of laps whose
    offset was measured (or would be, not compute: aligned laps not in cache left out)

    An imported reference lap is aligned first on a lap recorded by the app (first shown one, else anchor: main lap
    of track), else laps recorded by the app would be shifted by its own distance offset. Results of cache kept
    while laps stay the same (same lap data).
    """
    reference = next(((key, data) for key, data in laps if key == reference_key), laps[0] if laps else None)
    aligned: dict[str, AlignedLap] = {}
    work = 0
    if reference is None:
        return aligned, "", work

    def align(key: str, base: LapData | None, data: LapData) -> LapData | None:
        nonlocal work
        cached = cache.get(key)
        if cached is None or cached[0] is not base or cached[1] is not data:
            if not is_recorded(data):  # offset measured (slow on a long track)
                work += len(data)
            if base is None or not compute:
                return None
            cached = (base, data, *aligned_on(base, data))
        aligned[key] = cached
        return cached[2]

    reference_data: LapData | None = reference[1]
    anchor = next(((key, data) for key, data in laps if key != reference[0] and is_recorded(data)), anchor)
    anchor_key = ""
    if anchor is not None and anchor[0] != reference[0] and anchored(reference[1], anchor[1]):
        anchor_key = anchor[0]
        reference_data = align(reference[0], anchor[1], reference[1])  # None: not measured yet (not compute)
    for key, data in laps:
        if key != reference[0]:
            align(key, reference_data, data)
    return aligned, anchor_key, work


class TraceData:
    """Series, value ranges & axis conversion of displayed laps

    Axis position (x) is lap distance, or lap time of each lap (time_axis).
    Track distance of reference lap is used for maps & corners (see distance_at_x): a lap measured on
    another length (imported log on driven distance) has its distances multiplied by its scale
    (see telemetry_lap.distance_scale), "lap distance" below is its own distance.
    Cached series of laps still shown are kept when laps change (only new laps are computed),
    those depending on reference lap (delta, lap scale) only while reference stays the same. Series values are
    packed arrays & laps share their distances between channels (a float object takes 32 bytes, an array 4 or 8).
    Delta is measured against reference lap, or against ideal lap (fastest clean shown lap in each mini-sector).
    Laps aligned on a braking point (offsets) are shifted along distance axis: same braking start on charts
    (deltas & time axis never shifted).
    A compared lap not recorded by the app (imported log) whose distance zero is not at the start line is aligned on
    reference lap first (see lap_offset): its lap data is replaced by the aligned lap (charts, delta, sectors,
    corners & map all use it), auto_offsets tells meters added (reference distance), user alignment adds to it.
    Math channels (user expressions) are computed from recorded & computed channels of each lap, again when a
    computed input changes (delta, map placement).
    """

    def __init__(self):
        self.laps: list[PlotLap] = []
        self.reference: PlotLap | None = None
        self.reference_deltas: dict[str, tuple[list[float], list[float]]] = {}  # against reference lap
        self.deltas: dict[str, tuple[list[float], list[float]]] = {}  # shown: against reference or ideal lap
        self.ideal_mode = False  # delta against ideal lap
        self.delta_version = 0  # ideal lap delta computed again
        self.scales: dict[str, float] = {}  # lap key: lap distances to reference lap distances
        self.sector_lines: list[float] = []
        self.time_axis = False
        self.smoothing = 0  # moving average samples of noisy channels, 0 = off
        self.delta_window = 40.0  # meters, time gain/loss measured over
        self.units = display_units()
        self._times: dict[str, tuple[Sequence[float], Sequence[float]]] = {}
        self._samples: dict[str, Sequence[float]] = {}  # lap time of each recorded sample (no lap start & end)
        self._series: dict[tuple, tuple[Sequence[float], Sequence[float]]] = {}
        self._xs: dict[tuple, tuple[Sequence[float], Sequence[float]]] = {}  # lap axis positions shared by channels
        self._ranges: dict[tuple, tuple[float, float]] = {}
        self._mini: dict | None = None
        self._ideal: tuple[list[float], list[float]] | None = None
        self._deltas_ideal = False  # shown deltas are against ideal lap
        # Lap placement across track measured on map (official circuit path & track edges), by lap key:
        # distances, distance to track middle (m, left positive), track position (%): every lap, even without game data
        self.placements: dict[str, tuple[list[float], list[float], list[float]]] = {}
        self.placement_version = 0
        self.offsets: dict[str, float] = {}  # lap key: meters added along distance axis (aligned on braking point)
        self.auto_offsets: dict[str, float] = {}  # lap key: meters lap distance zero was moved by (imported lap)
        self._aligned: dict[str, AlignedLap] = {}  # lap key: reference (or anchor), lap, aligned lap, offset
        self.anchor_key = ""  # lap recorded by the app imported reference lap is aligned on (empty: none)
        self.math: dict[str, str] = {}  # math channel column: expression
        self._math_names: dict[str, list[str] | None] = {}  # expression: channel names used (None: invalid)

    def set_math(self, expressions: dict[str, str]):
        """Math channel expressions by column: series of changed ones computed again"""
        changed = {column for column in set(self.math) | set(expressions)
                   if self.math.get(column) != expressions.get(column)}
        self.math = dict(expressions)
        if changed:
            self._series = {key: value for key, value in self._series.items() if key[1] not in changed}
            self._ranges = {}

    def set_offsets(self, offsets: dict[str, float]):
        """Distance added to each lap along distance axis (0: not shifted), shifted series computed again"""
        offsets = {key: value for key, value in offsets.items() if value}
        if offsets != self.offsets:
            self.offsets = offsets
            self._series = {key: value for key, value in self._series.items() if not key[3]}
            self._xs = {key: value for key, value in self._xs.items() if key[1] != "shift"}
            self._ranges = {}

    def shift_of(self, lap: PlotLap, time_axis: bool | None = None) -> float:
        """Meters lap is shifted by on distance axis (none on time axis)"""
        use_time = self.time_axis if time_axis is None else time_axis
        return 0.0 if use_time else self.offsets.get(lap.key, 0.0)

    def set_placements(self, placements: dict[str, tuple[list[float], list[float], list[float]]]):
        """Lap placements measured on map (track position & distance to center series drawn again)"""
        self.placements = placements
        self.placement_version += 1
        self.drop_series(PLACEMENT_COLUMNS)

    def with_math(self, columns: Collection[str]) -> set[str]:
        """Columns & math channels using one of them"""
        names = set(columns)
        return names | {column for column in self.math if names.intersection(self.math_names(column) or ())}

    def drop_series(self, columns: Collection[str]):
        """Series of columns & of math channels using them computed again (input changed)"""
        dropped = self.with_math(columns)
        self._series = {key: value for key, value in self._series.items() if key[1] not in dropped}
        self._ranges = {}

    def compared(self) -> list[PlotLap]:
        return [lap for lap in self.laps if lap is not self.reference]

    def delta_laps(self) -> list[PlotLap]:
        """Laps with a delta: compared laps, every lap against ideal lap"""
        return [lap for lap in self.laps if lap.key in self.deltas]

    def scale_of(self, lap: PlotLap) -> float:
        """Factor turning lap distances into reference lap distances (1 unless lap length differs a bit)"""
        return self.scales.get(lap.key, 1.0)

    def aligned_laps(self, laps: list[PlotLap], reference_key: str, anchor: tuple[str, LapData] | None = None
                     ) -> list[PlotLap]:
        """Laps with compared laps not recorded by the app aligned on reference lap (distance zero at the line),
        reference lap itself aligned first on a lap recorded by the app (shown, else anchor) when it is an imported
        one, aligned lap data kept while reference & lap stay the same (series, corners & map lines kept)"""
        aligned, self.anchor_key, _ = align_laps([(lap.key, lap.data) for lap in laps], reference_key, anchor,
                                                 self._aligned)
        self._aligned = aligned
        self.auto_offsets = {key: value[3] for key, value in aligned.items() if value[3]}
        return [lap if lap.key not in aligned or aligned[lap.key][2] is lap.data
                else lap._replace(data=aligned[lap.key][2]) for lap in laps]

    def alignment_work(self, laps: Sequence[tuple[str, LapData]], reference_key: str,
                       anchor: tuple[str, LapData] | None = None) -> int:
        """Samples of imported laps whose offset showing laps would measure (not aligned yet: slow on a long track)"""
        return align_laps(laps, reference_key, anchor, self._aligned, compute=False)[2]

    def aligned_snapshot(self) -> dict[str, AlignedLap]:
        """Aligned laps of shown laps (copy, read by background thread, see keep_aligned)"""
        return dict(self._aligned)

    def keep_aligned(self, aligned: Mapping[str, AlignedLap]):
        """Aligned laps measured beforehand (background thread, see align_laps): used by set_laps if laps match"""
        self._aligned.update(aligned)

    def set_laps(self, laps: list[PlotLap], reference_key: str = "", anchor: tuple[str, LapData] | None = None):
        """Laps shown (reference_key: reference lap, anchor: lap recorded by the app an imported reference lap is
        aligned on when no shown lap was recorded by the app, see aligned_laps)"""
        laps = self.aligned_laps(laps, reference_key, anchor)
        previous = {lap.key: lap.data for lap in self.laps}
        previous_reference = self.reference.key if self.reference is not None else ""
        self.laps = laps
        self.reference = next((lap for lap in laps if lap.key == reference_key), laps[0] if laps else None)
        reference = self.reference.key if self.reference is not None else ""
        kept = {lap.key for lap in laps if previous.get(lap.key) is lap.data}  # same lap data loaded
        if self.units_changed():
            kept = set()
        self.units = display_units()
        same_reference = reference == previous_reference and reference in kept
        previous_scales = self.scales
        if self.reference is not None:
            self.scales = {lap.key: 1.0 if lap is self.reference else distance_scale(self.reference.data, lap.data)
                           for lap in laps}
        else:
            self.scales = {}
        same_scale = {key for key in kept if self.scales.get(key, 1.0) == previous_scales.get(key, 1.0)}
        self.reference_deltas = {key: value for key, value in self.reference_deltas.items()
                                 if same_reference and key in kept}
        if self.reference is not None:
            for lap in self.compared():
                if lap.key not in self.reference_deltas:
                    points = compute_delta(self.reference.data, lap.data)
                    if points:
                        self.reference_deltas[lap.key] = ([point[0] for point in points],
                                                          [point[1] for point in points])
        self.sector_lines = sector_bounds(self.reference.data) if self.reference else []
        delta_columns = self.with_math(DELTA_CHANNELS)
        self._series = {  # lap scaled again (other reference): every series of lap along reference distance
            key: value for key, value in self._series.items()
            if key[0] in same_scale and (same_reference or key[1] not in delta_columns)
        }
        self._xs = {key: value for key, value in self._xs.items() if key[0] in same_scale}
        self._times = {key: value for key, value in self._times.items() if key in kept}
        self._samples = {key: value for key, value in self._samples.items() if key in kept}
        self._ranges = {}
        self._mini = None
        self._ideal = None
        self.update_deltas()

    def units_changed(self) -> bool:
        """Whether unit setting changed since series were computed"""
        units = display_units()
        return units.keys() != self.units.keys() or any(self.units[name][1] != units[name][1] for name in units)

    def refresh_units(self) -> bool:
        """Series in user units again if unit setting changed (settings dialog), returns True if changed"""
        if not self.units_changed():
            return False
        self.units = display_units()
        self._series = {key: value for key, value in self._series.items()  # removed math channels dropped too
                        if key[1] in CHANNEL_MAP and not CHANNEL_MAP[key[1]].quantity}
        self._ranges = {}
        return True

    def set_ideal_mode(self, enabled: bool):
        """Delta against ideal lap (enabled) or reference lap"""
        if enabled != self.ideal_mode:
            self.ideal_mode = enabled
            self.update_deltas()

    def update_deltas(self):
        """Shown deltas: against reference lap, or against ideal lap (every lap, reference lap too)"""
        was_ideal, self._deltas_ideal = self._deltas_ideal, self.ideal_mode
        if self.ideal_mode or was_ideal:  # ideal lap changes with every shown lap
            self.drop_series(DELTA_CHANNELS)
            self.delta_version += 1
        if not self.ideal_mode:
            self.deltas = self.reference_deltas
            return
        self.deltas = {}
        ideal_distances, ideal_times = self.ideal_curve()
        if len(ideal_distances) < 2:
            return
        for lap in self.laps:
            points = delta_to_curve(ideal_distances, ideal_times, lap.data, self.scale_of(lap))
            if points:
                self.deltas[lap.key] = ([point[0] for point in points], [point[1] for point in points])

    # Mini-sectors & ideal lap: lap split in equal parts, fastest clean shown lap in each part
    def mini_sectors(self) -> dict:
        """Mini-sector bounds (reference distances, lap start to lap end), winner lap index & time of each lap in
        each part, ideal time

        Invalid, out & in laps never win a part (cut track) unless no clean lap is shown. Laps without lap time
        never do.
        """
        reference = self.reference
        if reference is None or len(reference.data) < 2:
            return {}
        if self._mini is not None:
            return self._mini
        from .lap_map import mini_sector_bounds, mini_sector_times, mini_sector_winners

        bounds = mini_sector_bounds(self.lap_end(reference))
        timed = ["lap_time" in lap.data.columns for lap in self.laps]
        usable = [lap.clean and use for lap, use in zip(self.laps, timed)]
        if not any(usable):
            usable = timed
        times: list[list[float]] = []
        for lap, use in zip(self.laps, usable):
            if not use:
                times.append([])
                continue
            distances, lap_times = self.lap_times(lap)
            scale = self.scale_of(lap)
            times.append(mini_sector_times(bounds, [distance * scale for distance in distances]
                                           if scale != 1.0 else distances, lap_times))
        winners = mini_sector_winners(times)
        ideal = sum(min(lap_times[index] for lap_times in times if index < len(lap_times) and lap_times[index] > 0)
                    for index, winner in enumerate(winners) if winner >= 0)
        self._mini = {"bounds": bounds, "winners": winners, "times": times, "ideal": ideal,
                      "complete": bool(winners) and all(winner >= 0 for winner in winners)}
        return self._mini

    def ideal_curve(self) -> tuple[list[float], list[float]]:
        """Ideal lap: lap time along reference distance, each mini-sector driven by its fastest lap, empty if
        a mini-sector has no lap time or under 2 laps shown"""
        if self._ideal is not None:
            return self._ideal
        self._ideal = ([], [])
        mini = self.mini_sectors()
        if len(self.laps) < 2 or not mini or not mini["complete"]:
            return self._ideal
        bounds, winners, times = mini["bounds"], mini["winners"], mini["times"]
        distances: list[float] = []
        curve: list[float] = []
        elapsed = 0.0
        for index, winner in enumerate(winners):
            lap = self.laps[winner]
            own_distances, own_times = self.lap_times(lap)
            scale = self.scale_of(lap)
            lap_distances = [distance * scale for distance in own_distances] if scale != 1.0 else own_distances
            start, end = bounds[index], bounds[index + 1]
            start_time = interpolate(lap_distances, own_times, start)
            if not distances or start > distances[-1]:
                distances.append(start)
                curve.append(elapsed)
            for position in range(bisect_right(lap_distances, start), bisect_left(lap_distances, end)):
                if lap_distances[position] > distances[-1]:
                    distances.append(lap_distances[position])
                    curve.append(elapsed + own_times[position] - start_time)
            elapsed += times[winner][index]
        if bounds[-1] > distances[-1]:
            distances.append(bounds[-1])
            curve.append(elapsed)
        self._ideal = (distances, curve)
        return self._ideal

    def ideal_time(self) -> float:
        """Ideal lap time of shown laps, 0 if unknown"""
        curve = self.ideal_curve()
        return curve[1][-1] if curve[1] else 0.0

    def set_time_axis(self, enabled: bool):
        self.time_axis = enabled
        self._ranges = {}

    def set_smoothing(self, points: int):
        """Moving average of noisy channels (series recomputed)"""
        if points != self.smoothing:
            self.smoothing = points
            self._series = {key: value for key, value in self._series.items()  # removed math channels dropped too
                            if key[1] in CHANNEL_MAP and not CHANNEL_MAP[key[1]].noisy}
            self._ranges = {}

    def set_delta_window(self, meters: float):
        if meters != self.delta_window:
            self.delta_window = meters
            self.drop_series(("delta_rate",))

    def signature(self, channel: Channel, lap: PlotLap | None = None) -> str:
        """Settings a series depends on, part of its vertex key (series redrawn when they change): series of lap,
        or of every shown lap (lap None)

        Math channels depend on their computed inputs too (delta, map placement).
        """
        column = channel.column
        uses = {column, *(self.math_names(column) or ())} if column in self.math else {column}
        parts = [str(int(self.time_axis))]
        if channel.noisy:
            parts.append(f"s{self.smoothing}")
        if channel.quantity in self.units:
            parts.append(f"u{self.units[channel.quantity][1]}")
        if uses.intersection(DELTA_CHANNELS) and self.ideal_mode:
            parts.append(f"i{self.delta_version}")
        elif uses.intersection(DELTA_CHANNELS) and self.reference is not None:
            parts.append(f"r{self.reference.key}")
        if "delta_rate" in uses:
            parts.append(f"w{self.delta_window:g}")
        if uses.intersection(PLACEMENT_COLUMNS):
            parts.append(f"p{self.placement_version}")
        if column in self.math:  # expression edited: drawn again
            parts.append(f"x{zlib.crc32(self.math[column].encode('utf-8')):x}")
        if lap is not None and self.scale_of(lap) != 1.0:  # lap distances scaled to reference lap length
            parts.append(f"k{self.scale_of(lap):.6g}")
        elif lap is None and any(value != 1.0 for value in self.scales.values()):  # every lap (envelope)
            scaled = "|".join(f"{key}:{value:.6g}" for key, value in sorted(self.scales.items()) if value != 1.0)
            parts.append(f"k{zlib.crc32(scaled.encode('utf-8')):x}")
        return "|".join(parts)

    # Axis conversion
    def lap_times(self, lap: PlotLap) -> tuple[Sequence[float], Sequence[float]]:
        """Distances & lap times of lap, increasing distance, from lap start to lap end (see lap_time_curve)"""
        cached = self._times.get(lap.key)
        if cached is None:
            if "lap_time" in lap.data.columns:
                cached = lap_time_curve(lap.data)
            else:  # no time recorded: distance used
                distances = monotonic_distance(lap.data, "distance")[0]
                cached = (distances, list(distances))
            self._times[lap.key] = cached
        return cached

    def sample_times(self, lap: PlotLap) -> Sequence[float]:
        """Lap time of each recorded sample by increasing distance (same samples as recorded channels)"""
        cached = self._samples.get(lap.key)
        if cached is None:
            cached = (monotonic_distance(lap.data, "lap_time")[1] if "lap_time" in lap.data.columns
                      else self.lap_times(lap)[1])
            self._samples[lap.key] = cached
        return cached

    def lap_end(self, lap: PlotLap) -> float:
        """Lap distance at lap end: track length if lap reaches the line (see lap_time_curve), else last sample"""
        distances = self.lap_times(lap)[0]
        return distances[-1] if distances else (lap.data.distance[-1] if len(lap.data) else 0.0)

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
        """Where lap is at axis position (its own distance): same place on track, or (time axis) where it is
        at that lap time"""
        if not self.time_axis:
            scale = self.scale_of(lap)
            x -= self.shift_of(lap)
            return x / scale if scale != 1.0 else x
        distances, times = self.lap_times(lap)
        return interpolate(times, distances, x) if times else x

    def x_at_lap_distance(self, lap: PlotLap, distance: float) -> float:
        """Axis position of lap at its own distance"""
        if not self.time_axis:
            return distance * self.scale_of(lap) + self.shift_of(lap)
        distances, times = self.lap_times(lap)
        return interpolate(distances, times, distance) if distances else distance

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
        return max((self.lap_end(lap) * self.scale_of(lap) for lap in self.laps if len(lap.data)),
                   default=1.0) or 1.0

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
        if channel.column in PLACEMENT_COLUMNS and any(lap.key in self.placements for lap in self.laps):
            return True
        if channel.column.startswith(MATH_PREFIX):
            return any(self.math_available(channel.column, lap) for lap in self.laps)
        sources = channel_sources(channel)
        return any(
            all(source in lap.data.columns for source in sources)
            # Wheel speeds read as 0 when not available from game, car settings as -1
            and all(any(lap.data.columns[source]) for source in sources if source.startswith("wheel_speed"))
            and all(max(lap.data.columns[source], default=-1) >= 0 for source in sources if source in SETTING_CHANNELS)
            for lap in self.laps
        )

    # Math channels: expression over recorded & computed channels of each lap, on its recorded samples
    def math_names(self, column: str) -> list[str] | None:
        """Channel names used by math channel expression, None if not a valid expression"""
        expression = self.math.get(column, "")
        if expression not in self._math_names:
            try:
                self._math_names[expression] = input_names(parse_expression(expression))
            except MathError:
                self._math_names[expression] = None
        return self._math_names[expression]

    def math_available(self, column: str, lap: PlotLap) -> bool:
        """Whether every input of math channel is recorded (or can be computed) in lap"""
        names = self.math_names(column)
        if names is None:
            return False
        columns = lap.data.columns
        for name in names:
            if name == YAW_RATE:
                found = "yaw" in columns and "lap_time" in columns
            elif name in columns:
                found = True
            else:
                channel = CHANNEL_MAP.get(name)
                if channel is None or channel.parts or name.startswith(MATH_PREFIX):
                    found = False
                elif name in DELTA_CHANNELS:
                    found = lap.key in self.deltas
                else:
                    found = all(source in columns for source in channel_sources(channel))
            if not found:
                return False
        return True

    def math_input(self, lap: PlotLap, name: str) -> tuple[Sequence[float], Sequence[float]] | None:
        """Distances & values of a math channel input: recorded column, computed channel or yaw rate (radians
        per second), None if missing"""
        columns = lap.data.columns
        if name == YAW_RATE:
            if "yaw" not in columns or "lap_time" not in columns:
                return None
            distances, yaws = monotonic_distance(lap.data, "yaw")
            return distances, derivative(unwrapped(yaws), monotonic_distance(lap.data, "lap_time")[1])
        if name in columns:
            return monotonic_distance(lap.data, name)
        channel = CHANNEL_MAP.get(name)
        if channel is None or channel.parts or name.startswith(MATH_PREFIX):
            return None
        found = self.computed(channel, lap)
        return found if len(found[0]) > 1 else None

    def math_series(self, column: str, lap: PlotLap) -> tuple[Sequence[float], Sequence[float]]:
        """Distances & values of math channel along recorded samples of lap, empty if an input is missing"""
        names = self.math_names(column)
        grid = monotonic_distance(lap.data, "distance")[0] if len(lap.data) else []
        if names is None or len(grid) < 2:
            return [], []
        inputs: dict[str, Sequence[float]] = {}
        for name in names:
            found = self.math_input(lap, name)
            if found is None:
                return [], []
            distances, values = found
            scale = self.scale_of(lap)
            if name in DELTA_CHANNELS and scale != 1.0:  # delta along reference distances: lap distances scaled
                distances = [distance / scale for distance in distances]
            same = len(distances) == len(grid) and distances[0] == grid[0] and distances[-1] == grid[-1]
            inputs[name] = values if same else resample_sorted(distances, values, grid)
        times = monotonic_distance(lap.data, "lap_time")[1] if "lap_time" in lap.data.columns else grid
        try:
            return grid, evaluate(self.math.get(column, ""), inputs, times, len(grid))
        except (MathError, ArithmeticError):
            return [], []

    def computed(self, channel: Channel, lap: PlotLap) -> tuple[Sequence[float], Sequence[float]]:
        """Distances & values of channel (recorded or computed) by increasing distance, recorded unit"""
        column = channel.column
        columns = lap.data.columns
        distances: Sequence[float]
        if column.startswith(MATH_PREFIX):
            return self.math_series(column, lap)
        if column == "delta":
            return self.deltas.get(lap.key, ([], []))
        if column == "delta_rate":
            distances, deltas = self.deltas.get(lap.key, ([], []))
            return distances, delta_rate(distances, deltas, self.delta_window)
        placement = self.placements.get(lap.key) if column in PLACEMENT_COLUMNS else None
        if placement is not None and (column == "track_position" or not any(columns.get(column, ()))):  # no game value
            return placement[0], placement[1] if column == "path_lateral" else placement[2]
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
        if column == "track_position":  # game: lateral position over track edge (0 center, 100 edge)
            distances, laterals = monotonic_distance(lap.data, "path_lateral")
            edges = monotonic_distance(lap.data, "track_edge")[1]
            return distances, [
                max(min(lateral / abs(edge) * 100, 150.0), -150.0) if abs(edge) > 0.5 else 0.0
                for lateral, edge in zip(laterals, edges)
            ]
        if column.startswith("camber_spread_"):  # inner minus outer tread temperature
            wheel = column[-2:]
            distances, inner = monotonic_distance(lap.data, f"tyre_temp_in_{wheel}")
            outer = monotonic_distance(lap.data, f"tyre_temp_out_{wheel}")[1]
            return distances, [first - last for first, last in zip(inner, outer)]
        if column == "slip_angle":  # angle between car heading & travel direction (degrees)
            distances, lateral = monotonic_distance(lap.data, "vel_lat")
            longitudinal = monotonic_distance(lap.data, "vel_long")[1]
            return distances, [
                math.degrees(math.atan2(across, abs(along))) if abs(along) >= SLIP_ANGLE_MIN_SPEED else 0.0
                for across, along in zip(lateral, longitudinal)
            ]
        if column in SETTING_CHANNELS:  # -1: car has no such setting (not drawn)
            distances, settings = monotonic_distance(lap.data, column)
            kept = [index for index, value in enumerate(settings) if value >= 0]
            if len(kept) == len(settings):
                return distances, settings
            return [distances[index] for index in kept], [settings[index] for index in kept]
        if column == "fuel_used":
            distances, fuel = monotonic_distance(lap.data, "fuel")
            return distances, [fuel[0] - value for value in fuel] if fuel else []
        if column == "tyre_temp_spread":
            distances = monotonic_distance(lap.data, "tyre_temp_fl")[0]
            temps = [monotonic_distance(lap.data, f"tyre_temp_{wheel}")[1] for wheel in WHEELS]
            return distances, [max(values) - min(values) for values in zip(*temps)]
        if column.startswith("slip_"):
            distances, wheel_speeds = monotonic_distance(lap.data, f"wheel_speed_{column[5:]}")
            speeds = monotonic_distance(lap.data, "speed_kph")[1]
            return distances, [
                max(min((wheel_speed - speed) / speed * 100, 100.0), -100.0) if speed >= SLIP_MIN_SPEED else 0.0
                for wheel_speed, speed in zip(wheel_speeds, speeds)
            ]
        return monotonic_distance(lap.data, column)

    def series(self, channel: Channel, lap: PlotLap, time_axis: bool | None = None, aligned: bool = True,
               ) -> tuple[Sequence[float], Sequence[float]]:
        """Channel samples of lap by increasing axis position, in user units, cached

        Args:
            aligned: lap shifted like on charts (aligned on a braking point), else at its place on track.
        """
        use_time = self.time_axis if time_axis is None else time_axis
        along_reference = channel.column in DELTA_CHANNELS  # delta distances are reference distances already
        shift = self.shift_of(lap, use_time) if aligned and not along_reference else 0.0
        key = (lap.key, channel.column, use_time, shift)
        cached = self._series.get(key)
        if cached is not None:
            return cached
        if shift:  # same values as on track, shifted
            xs, ys = self.series(channel, lap, use_time, aligned=False)
            cached = (self.shared_xs(lap, xs, "shift", shift), ys)
            self._series[key] = cached
            return cached
        distances, values = self.computed(channel, lap)
        convert = self.units.get(channel.quantity, (None, ""))[0] if channel.quantity else None
        if convert is not None:
            values = [convert(value) for value in values]
        if channel.noisy and self.smoothing > 1:
            values = moving_average(values, self.smoothing)
        xs = distances
        scale = self.scale_of(lap)
        if use_time and distances:
            lap_distances, times = self.lap_times(lap)
            # Same samples: delta has one point per lap time curve point, recorded channels one per sample
            same = times if along_reference else self.sample_times(lap)
            if len(same) == len(distances):
                xs = same
            else:
                factor = 1 / scale if along_reference else 1.0
                xs = array("d", [interpolate(lap_distances, times, distance * factor) for distance in distances])
        elif scale != 1.0 and not along_reference:
            xs = self.shared_xs(lap, distances, "scale", scale)
        cached = (xs, values if channel.column == "delta" else packed(values))  # delta: list of deltas itself
        self._series[key] = cached
        return cached

    def shared_xs(self, lap: PlotLap, xs: Sequence[float], kind: str, value: float) -> Sequence[float]:
        """Axis positions of lap multiplied by its scale (kind "scale") or shifted (kind "shift") by value: one copy
        shared by every channel of lap on the same samples"""
        key = (lap.key, kind, value)
        cached = self._xs.get(key)
        if cached is not None and cached[0] is xs:
            return cached[1]
        result = array("d", [x * value for x in xs] if kind == "scale" else [x + value for x in xs])
        self._xs[key] = (xs, result)
        return result

    def value_range(self, channel: Channel) -> tuple[float, float]:
        """Plotted range of channel over every lap (5% margin), symmetric for deltas"""
        if channel.fixed_range:
            return channel.fixed_range
        key = (channel.column, self.time_axis)
        cached = self._ranges.get(key)
        if cached is not None:
            return cached
        if channel.column in DELTA_CHANNELS:
            limit = delta_limit([self.series(channel, lap)[1] for lap in self.delta_laps()])
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

    def visible_range(self, channel: Channel, start: float, end: float) -> tuple[float, float]:
        """Value range of shown laps between axis positions (margin added), whole lap range if no value there

        Samples just outside are counted too: lines reaching panel edges stay inside panel.
        """
        low, high = math.inf, -math.inf
        for part in channel.parts or (channel.column,):
            for lap in self.laps:
                xs, ys = self.series(CHANNEL_MAP[part], lap)
                first, last = max(bisect_left(xs, start) - 1, 0), min(bisect_right(xs, end) + 1, len(xs))
                if first < last:
                    shown = ys[first:last]
                    low, high = min(low, min(shown)), max(high, max(shown))
        if low > high:
            return self.value_range(channel)
        if high - low < 1e-6:  # flat line: kept in panel middle
            half = max(abs(high) * AUTOSCALE_MARGIN, 0.01)
            return low - half, high + half
        padding = (high - low) * AUTOSCALE_MARGIN
        return low - padding, high + padding

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
        """Each lap over the same part of track between axis positions: time taken, then min, max & mean of
        each channel

        Axis positions are turned into reference lap distances first: on time axis, the same time is
        another place on track for each lap.
        """
        low_distance, high_distance = sorted((self.distance_at_x(start), self.distance_at_x(end)))
        result = []
        for lap in self.laps:
            scale = self.scale_of(lap)
            begin, finish = low_distance / scale, high_distance / scale  # lap distances
            distances, times = self.lap_times(lap)
            if not distances or finish <= begin:
                continue
            time_taken = interpolate(distances, times, finish) - interpolate(distances, times, begin)
            values = []
            for channel in channels:
                xs, ys = self.series(channel, lap, time_axis=False, aligned=False)  # reference distances
                low, high = bisect_left(xs, low_distance), bisect_right(xs, high_distance)
                part = ys[low:high]
                values.append((min(part), max(part), sum(part) / len(part)) if part else None)
            result.append({"lap": lap, "time": time_taken, "distance": finish - begin, "values": values})
        return result
