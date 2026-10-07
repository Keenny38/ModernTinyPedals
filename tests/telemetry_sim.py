"""Simple driving simulator and fake API reader for module replay tests

A car laps a track at constant speed per lap, with known lap times and fuel usage,
so module outputs (delta, consumption) can be checked against expected values.
"""

from __future__ import annotations

import math
from types import SimpleNamespace


class LapSim:
    """Simulated car state

    Args:
        lap_times: lap time (seconds) of each lap, car stops after last lap.
        track_length: lap distance (meters).
        fuel_per_lap: fuel used per lap (liters), used evenly along lap.
        fuel_start: initial fuel (liters).
        step: simulation time step (seconds).
    """

    def __init__(
        self,
        lap_times: list[float],
        track_length: float = 3000.0,
        fuel_per_lap: float | list[float] = 2.5,
        fuel_start: float = 50.0,
        step: float = 0.02,
    ):
        self.lap_times = lap_times
        self.track_length = track_length
        self.fuel_per_lap = (
            fuel_per_lap if isinstance(fuel_per_lap, list) else [fuel_per_lap] * len(lap_times)
        )
        self.fuel_start = fuel_start
        self.step = step
        self.elapsed = 0.0
        self.lap_index = 0  # current lap (0 = first lap)
        self.lap_start = 0.0  # current lap start time
        self.last_laptime = -1.0  # last completed lap time (-1 = invalid)
        self.fuel_used_total = 0.0
        self.fuel_used_completed = 0.0  # fuel used by completed laps

    @property
    def finished(self) -> bool:
        return self.lap_index >= len(self.lap_times)

    @property
    def lap_progress(self) -> float:
        if self.finished:
            return 0.0
        return min((self.elapsed - self.lap_start) / self.lap_times[self.lap_index], 1.0)

    @property
    def distance(self) -> float:
        return self.lap_progress * self.track_length

    @property
    def speed(self) -> float:
        if self.finished:
            return 0.0
        return self.track_length / self.lap_times[self.lap_index]

    @property
    def fuel(self) -> float:
        return self.fuel_start - self.fuel_used_total

    def tick(self):
        """Advance simulation by one step"""
        if self.finished:
            self.elapsed += self.step
            return
        self.elapsed += self.step
        lap_time = self.lap_times[self.lap_index]
        lap_end = self.lap_start + lap_time
        if self.elapsed >= lap_end:  # cross finish line
            self.fuel_used_completed += self.fuel_per_lap[self.lap_index]
            self.fuel_used_total = self.fuel_used_completed
            self.last_laptime = lap_time
            self.lap_start = lap_end
            self.lap_index += 1
        else:
            self.fuel_used_total = (
                self.fuel_used_completed
                + self.fuel_per_lap[self.lap_index] * self.lap_progress
            )


class _Group(SimpleNamespace):
    """API reader group, unknown methods return 0"""

    def __getattr__(self, name):
        return lambda *args, **kwargs: 0


def fake_reader(sim: LapSim) -> SimpleNamespace:
    """Fake api.read, backed by simulator"""
    return SimpleNamespace(
        timing=_Group(
            start=lambda index=None: sim.lap_start,
            elapsed=lambda index=None: sim.elapsed,
            current_laptime=lambda index=None: sim.elapsed - sim.lap_start,
            last_laptime=lambda index=None: sim.last_laptime,
            reference_laptime=lambda laptime=0.0, **kwargs: laptime,
        ),
        lap=_Group(
            distance=lambda index=None: sim.distance,
            progress=lambda index=None: sim.lap_progress,
            completed_laps=lambda index=None: sim.lap_index,
            maximum=lambda: 99,
            track_length=lambda: sim.track_length,
        ),
        vehicle=_Group(
            speed=lambda index=None: sim.speed,
            in_pits=lambda index=None: False,
            in_garage=lambda index=None: False,
        ),
        session=_Group(
            combo_name=lambda: "SimTrack - SimCar",
            identifier=lambda: (1, 0, 0),
            remaining=lambda: 3600.0,
            finish_type=lambda *args: False,
        ),
        engine=_Group(
            fuel=lambda: sim.fuel,
            tank_capacity=lambda: 100.0,
        ),
        emotor=_Group(),
        inputs=_Group(
            throttle=lambda index=None: 1.0, brake=lambda index=None: 0.0,
            throttle_raw=lambda index=None: 0.8, brake_raw=lambda index=None: 0.1,
        ),
        tyre=_Group(
            surface_temperature_avg=lambda index=None: (80.0, 81.0, 78.0, 79.0),
            pressure=lambda index=None: (170.0, 171.0, 165.0, 166.0),
        ),
        state=_Group(active=lambda: True, paused=lambda: False),
        brake=_Group(temperature=lambda index=None: (400.0, 410.0, 300.0, 310.0)),
        wheel=_Group(),
        switch=_Group(),
    )


CIRCUIT_CORNERS = ((0.12, 0.03, 45.0), (0.35, 0.02, 35.0), (0.6, 0.05, 50.0), (0.85, 0.025, 30.0))  # share, width, m/s


def circuit_speed(distance: float, track_length: float) -> float:
    """Speed (m/s) along a circuit with braking zones: same at the same place of every lap"""
    share = (distance % track_length) / track_length
    speed = 75.0
    for center, width, depth in CIRCUIT_CORNERS:
        gap = min(abs(share - center), 1 - abs(share - center))
        speed -= depth * math.exp(-(gap / width) ** 2)
    return speed


def circuit_lap(track_length: float = 3000.0, start: float = 0.0, pace: float = 1.0, step: float = 0.05,
                positions: bool = True) -> tuple[dict[str, list[float]], float]:
    """Lap columns of a car driven from track distance start to one lap later (lap distance & lap time from 0
    there) & its lap time, pace: lap time factor (1.02 = 2% slower everywhere)

    A lap starting away from the line (start not 0) is an imported lap whose distance zero is meters away from
    the start line. Positions on a circle (track distance turns once around it).
    """
    distances, times, speeds = [], [], []
    distance, elapsed = start, 0.0
    end = start + track_length - 0.05  # last sample just before the line (lap end rounded like an import)
    while distance < end:
        speed = circuit_speed(distance, track_length) / pace
        distances.append(distance)
        times.append(elapsed)
        speeds.append(speed * 3.6)
        distance += speed * step
        elapsed += step
    speed = circuit_speed(end, track_length) / pace
    lap_time = times[-1] + (end - distances[-1]) / speed
    distances.append(end)
    times.append(lap_time)
    speeds.append(speed * 3.6)
    lap_time += (start + track_length - end) / speed
    columns = {"distance": [value - start for value in distances], "lap_time": times, "speed_kph": speeds}
    if positions:
        radius = track_length / (2 * math.pi)
        columns["pos_x"] = [radius * math.cos(value / radius) for value in distances]
        columns["pos_z"] = [radius * math.sin(value / radius) for value in distances]
    return columns, lap_time
