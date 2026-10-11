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
Live game data of the race calculator: every race setup value the game gives

Two sources:
- car & session (shared memory, every game): race length, laps of the consumption history (lap
  time, fuel, energy, tyre wear per lap), tank capacity, compound on the car, fuel, energy & tread
  of now (race start amounts, on the grid), pit lane length & speed limit, time of day, forecast.
- LMU garage screens (REST, asked in background by the page, see GARAGE_RESOURCES): pit stop
  times of the series (refuel & energy rates, tyre & driver change, what is done at the same
  time), tyres offered by the pit menu (new compounds, used tyres with their tread), drivers of
  the team, tyre allocation, session settings (formation, start time of day).

Values come out in the units of the race calculator inputs (fuel unit of the page, energy & tread
in %), one LiveValue per input, with where it comes from. Pit menu texts are in the language of
the game: compounds are found by name in the main languages (unknown compound: left out).

Game values (seen in LMU 1.x garage screens): pitStopTimes FuelFillRate (liters / s),
virtualEnergyFillRate (fraction / s), TwoTireChange & FourTireChange, DriverChange (s),
FuelTimeConcurrent & TireTimeConcurrent (1: tyres changed while refuelling when both),
DriverConcurrent (1: driver change while refuelling); fuelInfo maxFuel (liters); teamInfo
driverNames; pit menu "FL TIRE:" ... "RR TIRE:" settings: no change, new compounds, used tyres
"<used> <compound> 84%"; tyre screen maxAvailableTires & newTiresRemaining; session settings
SESSSET_formation (text: "Fast Rolling", "Rolling", "Standing") & SESSSET_race_starting_time
(minutes after midnight).
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Callable, Sequence
from typing import Any, NamedTuple

from .api_control import api
from .fuel_strategy import MAX_DRIVERS, estimate_pace, history_laps, representative_laps
from .module_info import ConsumptionDataSet, minfo

RACE_SESSION = 4
GARAGE_RESOURCES = (
    "/rest/garage/UIScreen/RepairAndRefuel",
    "/rest/garage/UIScreen/TireManagement",
    "/rest/sessions",
)
WHEEL_ENTRIES = ("FL TIRE:", "FR TIRE:", "RL TIRE:", "RR TIRE:")
COMPOUND_WORDS = {  # tyre set key (userfile.tyre_strategy.DEFAULT_TYRE_SET): words of game texts (no accent)
    "Soft": ("soft", "tendre", "tendres", "weich", "blando", "blanda", "morbida", "morbido", "macio", "macia"),
    "Medium": ("medium", "moyen", "moyenne", "mittel", "medio", "media"),
    "Hard": ("hard", "dur", "dure", "hart", "duro", "dura"),
    "Intermediate": ("inter", "intermediate", "intermediaire", "intermedio", "intermedia"),
    "Wet": ("wet", "mouille", "pluie", "regen", "nass", "lluvia", "mojado", "bagnato", "pioggia", "chuva"),
}
FORMATION_LAPS = (("fast rolling", 0.5), ("rolling", 1.0), ("standing", 1.0))  # setting text: laps driven
RAIN_CHANCE = 0.5  # forecast node with this rain chance or more: wet
_PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_WORD = re.compile(r"[a-z]+")


class TyreOffer(NamedTuple):
    """Tyre the pit menu offers for a wheel"""

    compound: str  # tyre set key, "" unknown
    tread: float  # % left, 100 = new
    text: str  # as the game shows it


class GarageData(NamedTuple):
    """LMU garage screens (REST): pit stop times, tyres offered, team, tyre allocation, session
    settings; -1 or empty: not given"""

    tank_capacity: float = 0.0  # liters
    fuel_rate: float = 0.0  # liters per second
    energy_rate: float = 0.0  # % per second
    two_tyres: float = -1.0  # tyre change seconds (1 or 2 tyres)
    four_tyres: float = -1.0  # (3 or 4 tyres)
    driver_change: float = -1.0
    tyres_during_refuel: bool | None = None
    driver_during_refuel: bool | None = None
    drivers: tuple[str, ...] = ()
    new_compounds: tuple[str, ...] = ()  # compounds of new tyres offered (tyre set keys)
    used_tyres: tuple[tuple[TyreOffer, ...], ...] = ()  # used tyres offered, per wheel (FL FR RL RR)
    rain: tuple[float, ...] = ()  # rain chance (0-1) of forecast nodes, over the race evenly
    tyres_allowed: int = 0  # tyre allocation of the race
    new_tyres_left: int = -1
    formation_laps: float = -1.0
    start_minutes: int = -1  # race start time of day (minutes after midnight)

    @property
    def available(self) -> bool:
        return bool(self.tank_capacity or self.fuel_rate or self.energy_rate or self.four_tyres >= 0
                    or self.drivers or self.new_compounds or self.tyres_allowed or self.formation_laps >= 0)


class LiveValue(NamedTuple):
    """Value of a race calculator input given by the game

    key: input key, or "race_length" (kind & length), "tyre_change_times" (1-2 & 3-4 tyres),
    "maximum_tyre" (tyre rule), "rain" (rain scenario: on, first lap, laps).
    value: in the unit of the input, None when the game gives none (text tells why).
    """

    key: str
    group: str  # race, pace, start, pit, tyres, weather
    title: str  # English, translated by the page
    value: Any
    text: str
    source: str  # English, translated by the page
    follow: bool = True  # applied by Load Live & Follow Live unless turned off (rough estimates: off)
    tip: str = ""


# Parsing of game answers
def _number(value: Any, default: float = -1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _plain(text: str) -> str:
    """Lower case text without accents"""
    return "".join(char for char in unicodedata.normalize("NFKD", str(text).lower())
                   if not unicodedata.combining(char))


def compound_key(text: str) -> str:
    """Tyre set key of a compound name of the game (any main language), "" unknown"""
    words = set(_WORD.findall(_plain(text)))
    for key, names in COMPOUND_WORDS.items():
        if words.intersection(names):
            return key
    return ""


def tyre_offer(text: str) -> TyreOffer | None:
    """Tyre of a pit menu setting: new ("New Soft") or used ("Used Soft 84%"), None for no change
    or an invalid entry"""
    text = str(text).strip()
    if not text or text.upper() == "INVALID":
        return None
    compound = compound_key(text)
    if not compound:
        return None
    matched = _PERCENT.search(text)
    tread = min(max(float(matched.group(1).replace(",", ".")), 0.0), 100.0) if matched else 100.0
    return TyreOffer(compound, tread, " ".join(text.split()))


def _pit_menu(data: dict) -> list[dict]:
    menu = data.get("pitMenu")
    menu = menu.get("pitMenu") if isinstance(menu, dict) else None
    return [entry for entry in menu if isinstance(entry, dict)] if isinstance(menu, list) else []


def _settings(entry: dict) -> list[str]:
    settings = entry.get("settings")
    if not isinstance(settings, list):
        return []
    return [str(item.get("text", "")) if isinstance(item, dict) else "" for item in settings]


def _flag(value: Any) -> bool | None:
    number = _number(value)
    return None if number < 0 else number >= 1


def parse_garage(refuel: Any, tyres: Any = None, session: Any = None) -> GarageData:
    """Garage data of LMU answers: repair & refuel screen, tyre screen, session settings (None or
    anything unexpected: left out)"""
    values: dict[str, Any] = {}
    if isinstance(refuel, dict):
        fuel_info = refuel.get("fuelInfo")
        if isinstance(fuel_info, dict):
            values["tank_capacity"] = max(_number(fuel_info.get("maxFuel"), 0.0), 0.0)
        times = refuel.get("pitStopTimes")
        times = times.get("times") if isinstance(times, dict) else None
        if isinstance(times, dict):
            values["fuel_rate"] = max(_number(times.get("FuelFillRate"), 0.0), 0.0)
            values["energy_rate"] = max(_number(times.get("virtualEnergyFillRate"), 0.0), 0.0) * 100
            values["two_tyres"] = _number(times.get("TwoTireChange"))
            values["four_tyres"] = _number(times.get("FourTireChange"))
            values["driver_change"] = _number(times.get("DriverChange"))
            fuel_concurrent = _flag(times.get("FuelTimeConcurrent"))
            tyre_concurrent = _flag(times.get("TireTimeConcurrent"))
            if fuel_concurrent is not None and tyre_concurrent is not None:
                values["tyres_during_refuel"] = fuel_concurrent and tyre_concurrent
            values["driver_during_refuel"] = _flag(times.get("DriverConcurrent"))
        team = refuel.get("teamInfo")
        names = team.get("driverNames") if isinstance(team, dict) else None
        if isinstance(names, list):
            values["drivers"] = tuple(str(name) for name in names if str(name).strip())[:MAX_DRIVERS]
        new: dict[str, None] = {}
        used: list[tuple[TyreOffer, ...]] = []
        entries = {str(entry.get("name", "")).strip().upper(): entry for entry in _pit_menu(refuel)}
        for wheel in WHEEL_ENTRIES:
            offers = [tyre_offer(text) for text in _settings(entries.get(wheel, {}))[1:]]  # first: no change
            used.append(tuple(offer for offer in offers if offer is not None and offer.tread < 100))
            new.update((offer.compound, None) for offer in offers if offer is not None and offer.tread >= 100)
        if any(used) or new:
            values["used_tyres"] = tuple(used)
            values["new_compounds"] = tuple(new)
        forecast = refuel.get("weatherForecast")
        nodes = forecast.get("nodes") if isinstance(forecast, dict) else None
        chances = nodes.get("RainChance") if isinstance(nodes, dict) else None
        if isinstance(chances, list) and chances:
            values["rain"] = tuple(min(max(_number(chance, 0.0) / 100, 0.0), 1.0) for chance in chances)
    if isinstance(tyres, dict):
        try:
            maximum = int(tyres["tireInventory"]["maxAvailableTires"])
            left = int(tyres["tireInvGarageOptions"]["newTiresRemaining"])
        except (KeyError, TypeError, ValueError, OverflowError):
            maximum, left = 0, -1
        if maximum > 0:
            values["tyres_allowed"] = maximum
            values["new_tyres_left"] = min(max(left, 0), maximum)
    if isinstance(session, dict):
        formation = session.get("SESSSET_formation")
        text = _plain(formation.get("stringValue", "")) if isinstance(formation, dict) else ""
        laps = next((laps for name, laps in FORMATION_LAPS if name in text), -1.0)
        if laps >= 0:
            values["formation_laps"] = laps
        start = session.get("SESSSET_race_starting_time")
        minutes = _number(start.get("currentValue")) if isinstance(start, dict) else -1.0
        if 0 <= minutes < 24 * 60:
            values["start_minutes"] = round(minutes)
    return GarageData(**values)


def rain_period(chances: Sequence[float], race_laps: int) -> tuple[int, int] | None:
    """Wet part of the race from forecast nodes (race split evenly between nodes, wet from the
    first node with a rain chance of RAIN_CHANCE or more to the last one in a row): first plan
    lap & laps, (0, 0) when dry, None if no forecast or race length"""
    if not chances or race_laps <= 0:
        return None
    wet = [chance >= RAIN_CHANCE for chance in chances]
    if True not in wet:
        return 0, 0
    start = wet.index(True)
    end = start
    while end + 1 < len(wet) and wet[end + 1]:
        end += 1
    share = race_laps / len(wet)
    first = math.floor(start * share) + 1
    last = race_laps if end == len(wet) - 1 else max(math.floor((end + 1) * share), first)
    return first, last - first + 1


# Texts
def clock_minutes(minutes: float) -> str:
    minutes = round(minutes) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def laptime_text(seconds: float) -> str:
    milliseconds = round(max(seconds, 0) * 1000)
    return f"{milliseconds // 60000}:{milliseconds // 1000 % 60:02d}.{milliseconds % 1000:03d}"


def _amount(value: float, decimals: int, unit: str) -> str:
    return f"{value:.{decimals}f} {unit}".strip()


# Values of now
def race_length() -> tuple[str, int] | None:
    """Race length of the live race session: ("minutes" | "laps", value), None if not in a race"""
    session = api.read.session
    if session.session_type() != RACE_SESSION:
        return None
    if session.finish_type() == 1:  # laps only
        laps = api.read.lap.maximum()
        return ("laps", laps) if 0 < laps < 100000 else None
    minutes = round((session.end() - max(session.start(), 0)) / 60)
    return ("minutes", minutes) if minutes > 0 else None


def before_start() -> bool:
    """Race session, no race lap completed yet: car amounts of now are the race start amounts"""
    return api.read.session.session_type() == RACE_SESSION and api.read.lap.completed_laps() <= 0


def start_minutes_now() -> int:
    """Race start time of day from the track clock of a race under way (minutes), -1 unknown"""
    session = api.read.session
    if session.session_type() != RACE_SESSION or not session.in_race():
        return -1
    track_time = session.track_time()
    if track_time < 0:
        return -1
    elapsed = max(session.elapsed() - max(session.start(), 0.0), 0.0)
    return round((track_time - elapsed * max(session.time_scale(), 1)) / 60) % (24 * 60)


def compound_now() -> str:
    """Compound of the car (front left tyre, tyre set key), "" unknown"""
    names = api.read.tyre.compound_name()
    return compound_key(names[0]) if names else ""


def collect(history: Sequence[ConsumptionDataSet], garage: GarageData, unit_fuel: Callable[[float], float],
            symbol_fuel: str, plan_laps: int = 0, compounds: Sequence[str] = ()) -> list[LiveValue]:
    """Every input value given by the game now (see module docstring)

    Args:
        history: consumption history of the live session (newest first).
        garage: LMU garage screens (GarageData() when not asked or not LMU).
        unit_fuel: liters to fuel unit of the page.
        plan_laps: laps of the race plan (rain period in laps), 0 unknown.
        compounds: tyre set keys, in the order of the measured compound input.
    """
    read = api.read
    laps = history_laps(history)
    race = representative_laps(laps)
    count = len(race)
    average = f"Average of {count} valid lap(s) at race pace"
    values: list[LiveValue] = []

    def add(key: str, group: str, title: str, value: Any, text: str, source: str, follow: bool = True,
            tip: str = ""):
        values.append(LiveValue(key, group, title, value, text if value is not None else (text or "-"),
                                source, follow, tip))

    # Race
    length = race_length()
    add("race_length", "race", "Race Length", length,
        (f"{length[1]} min" if length[0] == "minutes" else f"{length[1]} laps") if length else "",
        "Race session" if length else "Race session only")
    formation = garage.formation_laps
    add("input_formation_laps", "race", "Formation Laps", formation if formation >= 0 else None,
        f"{formation:g} lap(s)" if formation >= 0 else "", "Session settings (LMU)")
    start = start_minutes_now()
    start_source = "Track clock"
    if start < 0 and garage.start_minutes >= 0:
        start, start_source = garage.start_minutes, "Session settings (LMU)"
    add("input_race_start_minutes", "race", "Start Time", start if start >= 0 else None,
        clock_minutes(start) if start >= 0 else "", start_source if start >= 0 else "Race session only")
    drivers = garage.drivers
    add("input_drivers", "race", "Drivers", len(drivers) if drivers else None, str(len(drivers)) if drivers else "",
        "Team (LMU)", tip=", ".join(drivers))

    # Pace & consumption
    if count:
        laptime = sum(lap.lapTimeLast for lap in race) / count
        add("input_lap_time", "pace", "Lap Time", laptime, laptime_text(laptime), average)
    else:
        pace = minfo.delta.lapTimePace
        laptime = pace if 0 < pace < 3600 else 0.0
        add("input_lap_time", "pace", "Lap Time", laptime or None, laptime_text(laptime) if laptime else "",
            "Race pace of the session" if laptime else "No valid lap yet")
    fuel_lap = sum(lap.lastLapUsedFuel for lap in race) / count if count else 0.0
    energy_lap = sum(lap.lastLapUsedEnergy for lap in race) / count if count else 0.0
    if fuel_lap > 0:
        add("input_fuel_per_lap", "pace", "Fuel per Lap", unit_fuel(fuel_lap),
            _amount(unit_fuel(fuel_lap), 3, symbol_fuel), average)
    else:
        estimate = read.engine.expected_fuel_consumption()
        add("input_fuel_per_lap", "pace", "Fuel per Lap", unit_fuel(estimate) if estimate > 0 else None,
            _amount(unit_fuel(estimate), 3, symbol_fuel) if estimate > 0 else "",
            "Game estimate (LMU)" if estimate > 0 else "No valid lap yet")
    if energy_lap > 0:
        add("input_energy_per_lap", "pace", "Energy per Lap", energy_lap, _amount(energy_lap, 3, "%"), average)
    else:
        estimate = read.engine.expected_energy_consumption()
        add("input_energy_per_lap", "pace", "Energy per Lap", estimate if estimate > 0 else None,
            _amount(estimate, 3, "%") if estimate > 0 else "",
            "Game estimate (LMU)" if estimate > 0 else "Car without virtual energy or no valid lap yet")
    wear = sum(lap.tyreAvgWearLast for lap in race) / count if count else 0.0
    if wear > 0:
        add("input_wear_per_lap", "pace", "Wear per Lap", wear, _amount(wear, 3, "%"), average)
    else:
        estimate = sum(minfo.wheels.estimatedValidTreadWear) / 4
        add("input_wear_per_lap", "pace", "Wear per Lap", estimate if estimate > 0 else None,
            _amount(estimate, 3, "%") if estimate > 0 else "",
            "Tyre wear of the lap in progress" if estimate > 0 else "No valid lap yet", follow=False)
    capacity = max(read.engine.tank_capacity(), garage.tank_capacity, laps[0].capacityFuel if laps else 0.0)
    add("input_tank_capacity", "pace", "Tank Capacity", unit_fuel(capacity) if capacity > 0 else None,
        _amount(unit_fuel(capacity), 1, symbol_fuel) if capacity > 0 else "", "Car")
    compound = compound_now()
    index = list(compounds).index(compound) if compound in compounds else -1
    add("input_measured_compound", "pace", "Measured Compound", index if index >= 0 else None, compound,
        "Tyres on the car")

    # Race start amounts: the car on the grid
    if before_start():
        fuel = unit_fuel(read.engine.fuel())
        energy = read.engine.virtual_energy() * 100
        tread = sum(read.tyre.wear()) * 25
        add("input_fuel_start", "start", "Starting Fuel", fuel if fuel > 0 else None,
            _amount(fuel, 1, symbol_fuel) if fuel > 0 else "", "Car on the grid")
        add("input_energy_start", "start", "Starting Energy", energy if energy > 0 else None,
            _amount(energy, 1, "%") if energy > 0 else "", "Car on the grid")
        add("input_tread_start", "start", "Starting Tread", tread if tread > 0 else None,
            _amount(tread, 1, "%") if tread > 0 else "", "Car on the grid")
    else:
        for key, title in (("input_fuel_start", "Starting Fuel"), ("input_energy_start", "Starting Energy"),
                           ("input_tread_start", "Starting Tread")):
            add(key, "start", title, None, "", "Race session before the start only")

    # Pit stops
    estimate_stops = estimate_pace(laps, unit_fuel)
    if estimate_stops.pit_stops:
        add("input_pit_seconds", "pit", "Pit Stop Time", round(estimate_stops.pit_seconds, 1),
            f"{estimate_stops.pit_seconds:.1f} s", f"Stops of the session ({estimate_stops.pit_stops})")
    else:
        lane = minfo.mapping.pitPassTime
        lane_length = minfo.mapping.pitLaneLength
        track_length = read.lap.track_length()
        loss = lane - lane_length / track_length * laptime if lane > 0 and track_length > 0 and laptime else 0.0
        add("input_pit_seconds", "pit", "Pit Stop Time", round(loss, 1) if loss > 0 else None,
            f"{loss:.1f} s" if loss > 0 else "", "Pit lane at speed limit (braking & pulling away not counted)"
            if loss > 0 else "No stop in the session yet", follow=False)
    if garage.fuel_rate > 0:
        add("input_refuel_rate", "pit", "Refuel Rate", unit_fuel(garage.fuel_rate),
            _amount(unit_fuel(garage.fuel_rate), 2, f"{symbol_fuel}/s"), "Pit stop times (LMU)")
    else:
        add("input_refuel_rate", "pit", "Refuel Rate", None, "", "Pit stop times (LMU)")
    add("input_energy_rate", "pit", "Energy Rate", garage.energy_rate if garage.energy_rate > 0 else None,
        _amount(garage.energy_rate, 2, "%/s") if garage.energy_rate > 0 else "", "Pit stop times (LMU)")
    change = garage.driver_change
    add("input_driver_change_seconds", "pit", "Driver Change Time", change if change >= 0 else None,
        f"{change:.1f} s" if change >= 0 else "", "Pit stop times (LMU)")
    add("enable_driver_change_during_refuel", "pit", "Driver Change While Refuelling", garage.driver_during_refuel,
        ("On" if garage.driver_during_refuel else "Off") if garage.driver_during_refuel is not None else "",
        "Pit stop times (LMU)")
    add("enable_tyres_during_refuel", "pit", "Tyres Changed While Refuelling", garage.tyres_during_refuel,
        ("On" if garage.tyres_during_refuel else "Off") if garage.tyres_during_refuel is not None else "",
        "Pit stop times (LMU)")
    known = garage.two_tyres >= 0 and garage.four_tyres >= 0
    add("tyre_change_times", "pit", "Tyre Change Time", (garage.two_tyres, garage.four_tyres) if known else None,
        f"{garage.two_tyres:.1f} s / {garage.four_tyres:.1f} s" if known else "", "Pit stop times (LMU)",
        tip="1-2 tyres / 3-4 tyres")

    # Tyres & weather
    allowed = garage.tyres_allowed
    add("maximum_tyre", "tyres", "Maximum Tyres", allowed if allowed > 0 else None,
        (f"{allowed}" + (f" ({garage.new_tyres_left} new left)" if garage.new_tyres_left >= 0 else ""))
        if allowed > 0 else "", "Tyre allocation (LMU)" if allowed > 0 else "Tyre allocation (LMU, while driving)")
    chances = garage.rain or tuple(node.rain_chance for node in read.session.weather_forecast() if node.sky_type >= 0)
    period = rain_period(chances, plan_laps)
    if period is None:
        add("rain", "weather", "Rain Forecast", None, "", "Weather Forecast" if chances else "No forecast")
    else:
        first, count_wet = period
        text = "No Rain" if not count_wet else f"Laps {first}-{first + count_wet - 1}"
        add("rain", "weather", "Rain Forecast", (count_wet > 0, first, count_wet), text, "Weather Forecast",
            tip=" · ".join(f"{chance:.0%}" for chance in chances))
    return values
