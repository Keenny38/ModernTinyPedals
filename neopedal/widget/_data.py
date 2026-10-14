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
Overlay data shared by classic & modern renderers (pure functions, no Qt)

Values shown by widgets, read from module outputs (minfo) or game data passed in:
renderers only format & draw them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NamedTuple

from .. import calculation as calc


# Fuel & virtual energy
def run_laps(fuel: Any, energy: Any) -> float:
    """Laps left before pitting: fuel, or virtual energy if it runs out first

    Args:
        fuel: fuel module output (minfo.fuel).
        energy: virtual energy module output (minfo.energy).
    """
    if energy.available:
        return min(fuel.estimatedLaps, energy.estimatedLaps)
    return fuel.estimatedLaps


class ConsumptionData(NamedTuple):
    """Fuel or virtual energy values shown (amounts in display unit)"""

    remaining: float  # amount in tank
    needed: float  # refill needed: absolute amount, or relative to remaining
    laps: float  # estimated laps left
    minutes: float  # estimated minutes left
    used: float  # estimated consumption per lap
    save: float  # saving per lap for one less pit stop
    pits_end: float  # pit stops left, pitting at end of stint
    pits_early: float  # pit stops left, pitting at end of lap
    delta: float  # consumption delta of current lap
    end: float  # amount left at end of stint


def consumption_data(source: Any, convert: Callable[[float], float], absolute: bool) -> ConsumptionData:
    """Fuel or virtual energy values shown

    Args:
        source: fuel or energy module output (minfo.fuel, minfo.energy).
        convert: amount unit conversion.
        absolute: absolute refill amount (else relative to remaining).
    """
    if absolute:
        needed = calc.sym_max(convert(source.neededAbsolute), 9999)
    else:
        needed = calc.sym_max(convert(source.neededRelative), 9999)
    return ConsumptionData(
        convert(source.amountCurrent),
        needed,
        min(source.estimatedLaps, 9999),
        min(source.estimatedMinutes, 9999),
        convert(source.estimatedConsumption),
        calc.zero_max(convert(source.oneLessPitConsumption), 99.99),
        calc.zero_max(source.estimatedNumPitStopsEnd, 99.99),
        calc.zero_max(source.estimatedNumPitStopsEarly, 99.99),
        convert(source.deltaConsumption),
        convert(source.amountEndStint),
    )


def level_data(source: Any) -> tuple[float, float, float]:
    """Level bar amounts: current, stint start, after refill (in source unit)"""
    current = source.amountCurrent
    return current, source.amountStart, current + source.neededRelative


# Tyre & brake wear
class TyreWearData(NamedTuple):
    """Tyre tread values shown, of one tyre (percent)"""

    remaining: float  # tread left
    wear: float  # wear of last lap
    live: float  # wear of current lap
    flat_spot: float  # wear from locking
    laps: float  # lifespan in laps
    minutes: float  # lifespan in minutes
    end: float  # tread left at end of stint


def tyre_wear_data(wheels: Any, index: int, pace: float, laps_left: float) -> TyreWearData:
    """Tyre tread values of one tyre

    Args:
        wheels: wheels module output (minfo.wheels).
        index: tyre index (0 fl, 1 fr, 2 rl, 3 rr).
        pace: lap time pace (seconds).
        laps_left: laps left in stint (see run_laps).
    """
    tread = wheels.currentTreadDepth[index]
    valid_wear = wheels.estimatedValidTreadWear[index]
    return TyreWearData(
        tread,
        wheels.estimatedTreadWear[index],
        wheels.currentLapTreadWear[index],
        wheels.lockingTreadWear[index],
        calc.wear_lifespan_in_laps(tread, valid_wear),
        calc.wear_lifespan_in_mins(tread, valid_wear, pace),
        calc.end_stint_tread(tread, valid_wear, laps_left),
    )


class BrakeWearData(NamedTuple):
    """Brake values shown, of one brake (millimeters or percent of usable thickness)"""

    failed: bool  # worn out
    remaining: float  # thickness left above failure thickness
    remaining_percent: float
    wear: float  # wear of last lap
    wear_percent: float
    live: float  # wear of current lap
    live_percent: float
    laps: float  # lifespan in laps
    minutes: float  # lifespan in minutes
    usable: float  # usable thickness (millimeters, above failure thickness)


def brake_wear_data(wheels: Any, index: int, thickness: bool, pace: float) -> BrakeWearData:
    """Brake values of one brake

    Args:
        wheels: wheels module output (minfo.wheels).
        index: brake index (0 fl, 1 fr, 2 rl, 3 rr).
        thickness: values in millimeters (else percent of usable thickness).
        pace: lap time pace (seconds).
    """
    current = wheels.currentBrakeThickness[index]
    failed = current <= 0
    failure = wheels.failureBrakeThickness[index]
    usable = wheels.maxBrakeThickness[index] - failure
    current = max(current - failure, 0.0)  # worn past failure thickness: no lifespan left
    live = wheels.currentlapBrakeWear[index]
    wear = wheels.estimatedBrakeWear[index]
    valid_wear = wheels.estimatedValidBrakeWear[index]
    if usable <= 0:  # bypass invalid value
        usable = 99999999
    live_percent = live * 100 / usable
    wear_percent = wear * 100 / usable
    remaining_percent = current * 100 / usable
    if not thickness:
        current = remaining_percent
        live = live_percent
        wear = wear_percent
        valid_wear = valid_wear * 100 / usable
    return BrakeWearData(
        failed,
        current,
        remaining_percent,
        wear,
        wear_percent,
        live,
        live_percent,
        calc.wear_lifespan_in_laps(current, valid_wear),
        calc.wear_lifespan_in_mins(current, valid_wear, pace),
        usable,
    )


def wear_text(value: float) -> str:
    """Wear value cut to 4 characters"""
    return f"{value:.2f}"[:4].strip(".")


# Tyre temperature
def temperature_text(value: float, unit_temp: Callable[[float], float], leading_zero: int, sign: str,
                     placeholder: str) -> str:
    """Temperature text (placeholder below -100 degrees: no reading)

    Args:
        value: temperature (Celsius, rounded).
        unit_temp: temperature unit conversion.
        leading_zero: digits padded with zeros.
        sign: degree sign, or empty.
        placeholder: text without reading.
    """
    if value < -100:
        return placeholder
    return f"{unit_temp(value):0{leading_zero}.0f}{sign}"


def rate_text(rate: float, scale: float) -> str:
    """Temperature rate of change text, unsigned (scale: temperature unit of a difference)"""
    change = abs(rate) * scale
    if change > 9.94:
        return f"{change:.0f}"
    return f"{change:.1f}"


class TemperatureRates:
    """Temperature rate of change of four tyres, smoothed, per interval (seconds)"""

    __slots__ = ("interval", "ema", "rates", "last_temps", "last_elapsed")

    def __init__(self, interval: float, samples: int):
        self.interval = interval
        self.ema = calc.ema_filter(samples)
        self.rates = [0.0] * 4
        self.last_temps: list[float] | None = None
        self.last_elapsed = 0.0

    def reset(self):
        """Rates cleared, next reading starts again (new session or paused timer)"""
        self.rates = [0.0] * 4
        self.last_temps = None

    def update(self, temps, elapsed: float) -> int:
        """Rates from temperatures read at session elapsed time

        Returns:
            0 unchanged, 1 rates updated, 2 rates reset (new session).
        """
        if self.last_elapsed > elapsed:  # new session
            self.last_elapsed = elapsed
            self.reset()
            return 2
        if elapsed - self.last_elapsed < 0.1:
            return 0
        interval = self.interval / (elapsed - self.last_elapsed)
        self.last_elapsed = elapsed
        last_temps = self.last_temps
        self.last_temps = list(temps)
        if last_temps is None:  # first reading: no rate yet (from 0 would be a fake spike)
            return 0
        rates = self.rates
        for index in range(4):
            rates[index] = self.ema(rates[index], (temps[index] - last_temps[index]) * interval)
        return 1


# Lap & stint history
def used_amount(use_energy: bool, energy: float, fuel: float, unit_fuel: Callable[[float], float],
                sign_fuel: str) -> tuple[float, str]:
    """Fuel or virtual energy used, with unit sign ("E" for energy if fuel has a sign)"""
    if use_energy:
        return energy, "E" if sign_fuel else ""
    return unit_fuel(fuel), sign_fuel


def lap_delta(laptime: float, previous: float) -> float | None:
    """Lap time delta to previous lap, None if either lap has no time"""
    if laptime > 0 and previous > 0:
        return laptime - previous
    return None


def cut_number(value: float, width: int, sign: str = "") -> str:
    """Number cut to width characters (decimals as many as fit, sign: "+" for signed number)"""
    return f"{value:{sign}.{width}f}"[:width].strip(".")
