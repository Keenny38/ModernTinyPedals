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
Race calculator inputs: saved inputs & their ranges, race clock texts, plan export

No Qt widget: used by the race calculator backend (race_backend.py) and its tests.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from math import isfinite
from typing import NamedTuple

from ... import calculation as calc
from ... import units
from ...api_control import api
from ...const_app import FORMAT_PREFIX, LEGACY_FORMAT_PREFIX
from ...fuel_strategy import MARGIN_UNITS, MAX_DRIVERS, driver_table_text, parse_driver_table
from ...i18n import tr
from ...template.setting_global import FUEL_CALCULATOR_INPUTS

RACE_SESSION = 4
RACE_PLAN_FORMAT = f"{FORMAT_PREFIX}-race-plan"
RACE_PLAN_FORMATS = (RACE_PLAN_FORMAT, f"{LEGACY_FORMAT_PREFIX}-race-plan")  # plans of versions until 0.23.0 too
RACE_PLAN_VERSION = 1
PLAN_FILE = "race_calculator_plan.json"  # plan input of race plan widget (config folder)

DRIVER_COLORS = ("#4C9AFF", "#F5A623", "#7ED321", "#BD10E0", "#50E3C2", "#E94B3C", "#B8E986", "#9013FE", "#F8E71C")
SAFETY_CAR_COLOR = "#F8E71C"
RAIN_COLOR = "#4FC3F7"
INVALID_COLOR = "#FF4400"  # invalid lap & values out of range (tank too small, tyres worn out)
TYRE_COLOR = "#F5B342"  # tyre change marks

# Saved inputs (config "fuel_calculator"): key, default
SAVED_INPUTS = FUEL_CALCULATOR_INPUTS
FUEL_INPUTS = ("input_fuel_per_lap", "input_tank_capacity", "input_fuel_start", "input_refuel_rate")  # fuel unit
INPUT_LIMIT = 1e6  # beyond every input range: huge numbers of a file clamped to it


class Spec(NamedTuple):
    """Range of a number input: decimals 0 = whole number, unit: suffix key (see unit_text)"""

    minimum: float
    maximum: float
    decimals: int
    step: float
    unit: str = ""


INPUT_SPECS = {
    "input_lap_time": Spec(0, 9999 * 60, 3, 0.1, "s"),
    "input_fuel_per_lap": Spec(0, 9999, 3, 0.1, "fuel"),
    "input_energy_per_lap": Spec(0, 100, 3, 0.1, "%"),
    "input_tank_capacity": Spec(0, 9999, 2, 1.0, "fuel"),
    "input_race_minutes": Spec(0, 9999, 0, 1, "min"),
    "input_race_laps": Spec(0, 9999, 0, 1, "lap"),
    "input_formation_laps": Spec(0, 9999, 2, 0.1, "lap"),
    "input_pit_seconds": Spec(0, 9999, 1, 1.0, "s"),
    "input_safety_margin": Spec(0, 99, 2, 0.1, "margin"),  # 9999 in fuel units, see input_spec
    "input_fuel_start": Spec(0, 9999, 2, 1.0, "fuel"),
    "input_energy_start": Spec(0, 100, 2, 1.0, "%"),
    "input_tread_start": Spec(0, 100, 3, 0.01, "%"),
    "input_wear_per_lap": Spec(0, 100, 3, 0.01, "%"),
    "input_minimum_tread": Spec(0, 100, 1, 1.0, "%"),
    "input_tyre_set_laps": Spec(0, 9999, 0, 1, "lap"),
    "input_refuel_rate": Spec(0, 999, 2, 0.1, "fuel/s"),
    "input_energy_rate": Spec(0, 100, 2, 0.1, "%/s"),
    "input_driver_change_seconds": Spec(0, 999, 1, 1.0, "s"),
    "input_pit_lap_consumption": Spec(0, 200, 0, 5.0, "%"),
    "input_minimum_stops": Spec(0, 99, 0, 1),
    "input_max_stint_minutes": Spec(0, 9999, 0, 1.0, "min"),
    "input_drivers": Spec(1, MAX_DRIVERS, 0, 1),
    "input_stints_per_driver": Spec(1, 9, 0, 1),
    "input_fuel_effect": Spec(0, 9, 3, 0.01, "s/10 fuel"),
    "input_track_evolution": Spec(-9, 9, 2, 0.05, "s/h"),
    "input_saving_cost": Spec(0, 9, 2, 0.05, "s"),
    "input_target_stint_laps": Spec(0, 999, 0, 1, "lap"),
    "input_race_start_minutes": Spec(-1, 24 * 60 - 1, 0, 1),
    "input_safety_margin_kind": Spec(0, len(MARGIN_UNITS) - 1, 0, 1),
    "input_sc_lap": Spec(1, 9999, 0, 1, "lap"),
    "input_sc_laps": Spec(1, 99, 0, 1, "lap"),
    "input_sc_consumption": Spec(0, 100, 0, 5.0, "%"),
    "input_sc_laptime": Spec(0, 500, 0, 10.0, "%"),
    "input_sc_wear": Spec(0, 100, 0, 5.0, "%"),
    "input_sc_pit_saving": Spec(0, 100, 0, 10.0, "%"),
    "input_rain_lap": Spec(1, 9999, 0, 1, "lap"),
    "input_rain_laps": Spec(0, 9999, 0, 1, "lap"),
    "input_rain_consumption": Spec(0, 200, 0, 5.0, "%"),
    "input_rain_laptime": Spec(0, 500, 0, 5.0, "%"),
}
# Driver table columns: lap time difference, total driving time at least & at most
DRIVER_SPECS = (Spec(-9, 9, 2, 0.1, "s"), Spec(0, 9999, 0, 10.0, "min"), Spec(0, 9999, 0, 10.0, "min"))


def unit_text(unit: str, symbol_fuel: str, margin_kind: int = 0) -> str:
    """Suffix of a number input: unit key of Spec, fuel symbol of display unit"""
    if unit == "margin":
        kind = MARGIN_UNITS[margin_kind] if 0 <= margin_kind < len(MARGIN_UNITS) else MARGIN_UNITS[0]
        return {"laps": tr("lap"), "fuel": symbol_fuel, "percent": "%"}[kind]
    return {
        "fuel": symbol_fuel, "fuel/s": f"{symbol_fuel}/s", "lap": tr("lap"), "s/10 fuel": f"s/10 {symbol_fuel}",
    }.get(unit, unit)


def input_spec(key: str, margin_kind: int = 0) -> Spec:
    """Range of a number input (safety margin: range of its unit)"""
    spec = INPUT_SPECS[key]
    if key == "input_safety_margin" and 0 <= margin_kind < len(MARGIN_UNITS) and MARGIN_UNITS[margin_kind] == "fuel":
        return spec._replace(maximum=9999)
    return spec


def clamp_number(value: float, spec: Spec) -> float | int:
    """Number kept inside its range, rounded as shown (nan & infinity: minimum, above 0 if allowed)"""
    if not isfinite(value):
        value = max(spec.minimum, 0)
    value = min(max(value, spec.minimum), spec.maximum)
    if spec.decimals <= 0:
        return round(value)
    return round(value, spec.decimals)


def clamp_input(key: str, value, margin_kind: int = 0):
    """Input value of the type & range of its key (as a saved input), None if key is unknown"""
    default = SAVED_INPUTS.get(key)
    if default is None:
        return None
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, str):
        return value if isinstance(value, str) else default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return default
    spec = input_spec(key, margin_kind) if key in INPUT_SPECS else None
    if spec is None:
        return value
    return clamp_number(float(value), spec)


def checked_inputs(values: dict) -> dict:
    """Saved inputs with type checked (file or config), default for missing or wrong values
    (nan & infinity of a hand edited file too), huge numbers clamped (integer boxes overflow)"""
    inputs = {}
    for key, default in SAVED_INPUTS.items():
        value = values.get(key, default)
        if isinstance(default, bool):
            value = value if isinstance(value, bool) else default
        elif isinstance(default, str):
            value = value if isinstance(value, str) else default
        elif (not isinstance(value, (int, float)) or isinstance(value, bool)
              or (isinstance(value, float) and not isfinite(value))):
            value = default
        else:
            value = min(max(value, -INPUT_LIMIT), INPUT_LIMIT)
        inputs[key] = value
    return inputs


def ranged_inputs(values: dict) -> dict:
    """Checked inputs kept inside the range of each input (as typed in the page)"""
    inputs = checked_inputs(values)
    kind = inputs["input_safety_margin_kind"]
    kind = int(kind) if 0 <= kind < len(MARGIN_UNITS) else 0  # unknown unit: laps
    inputs["input_safety_margin_kind"] = kind
    for key, value in inputs.items():
        if key in INPUT_SPECS:
            inputs[key] = clamp_input(key, value, kind)
    inputs["input_driver_table"] = driver_table_text(driver_rows(inputs["input_driver_table"]))
    start = inputs["input_race_start_minutes"]
    inputs["input_race_start_minutes"] = start if 0 <= start < 24 * 60 else -1
    if inputs["input_tank_capacity"] > 0:
        inputs["input_fuel_start"] = min(inputs["input_fuel_start"], inputs["input_tank_capacity"])
    return inputs


def driver_rows(text: str) -> list[tuple[float, float, float]]:
    """Pace, minimum & maximum driving time of each driver (MAX_DRIVERS rows, in range)"""
    rows = parse_driver_table(text if isinstance(text, str) else "")
    result = []
    for index in range(MAX_DRIVERS):
        values = rows[index] if index < len(rows) else (0.0, 0.0, 0.0)
        result.append(tuple(float(clamp_number(value, spec)) for value, spec in zip(values, DRIVER_SPECS)))
    return result  # type: ignore[return-value]


def convert_fuel_inputs(values: dict, from_unit: str, to_unit: str) -> dict:
    """Checked inputs (see checked_inputs) of a race plan made in another fuel unit ("Liter",
    "Gallon"), converted to to_unit: amounts, refuel rate, safety margin in fuel, fuel effect"""
    from_gallon, to_gallon = from_unit == "Gallon", to_unit == "Gallon"
    if from_gallon == to_gallon:
        return values
    factor = units.liter_to_gallon(1.0) if to_gallon else 1 / units.liter_to_gallon(1.0)
    values = dict(values)
    for key in FUEL_INPUTS:
        values[key] = values[key] * factor
    kind = int(values["input_safety_margin_kind"])
    if 0 <= kind < len(MARGIN_UNITS) and MARGIN_UNITS[kind] == "fuel":
        values["input_safety_margin"] = values["input_safety_margin"] * factor
    values["input_fuel_effect"] = values["input_fuel_effect"] / factor  # per 10 fuel units
    return values


def live_race_length() -> tuple[str, int] | None:
    """Race length of live race session: ("minutes" | "laps", value), None if not in a race"""
    session = api.read.session
    if session.session_type() != RACE_SESSION:
        return None
    if session.finish_type() == 1:  # laps only
        laps = api.read.lap.maximum()
        return ("laps", laps) if 0 < laps < 100000 else None
    minutes = round((session.end() - max(session.start(), 0)) / 60)
    return ("minutes", minutes) if minutes > 0 else None


# Lap time & time of day typed as text
def laptime_text(seconds: float) -> str:
    """Lap time as m:ss.mmm (same format as every lap time)"""
    return calc.sec2laptime_full(max(seconds, 0.0))


def parse_laptime(text: str) -> float | None:
    """Seconds of a typed lap time: m:ss.mmm, ss.mmm, m:ss or plain seconds (comma decimal too),
    None if not a lap time"""
    text = str(text).strip().replace(",", ".")
    if not text:
        return 0.0
    parts = text.split(":")
    if len(parts) > 3:
        return None
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return None
    if any(not isfinite(number) or number < 0 for number in numbers):
        return None
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    return min(round(seconds, 3), INPUT_SPECS["input_lap_time"].maximum)


def start_time_text(minutes: int) -> str:
    """Time of day of race start as hh:mm, "" if not set"""
    return f"{minutes // 60:02d}:{minutes % 60:02d}" if 0 <= minutes < 24 * 60 else ""


def parse_start_time(text: str) -> int | None:
    """Minutes after midnight of a typed time of day (hh:mm, hhmm, hh), None if not a time"""
    text = str(text).strip().replace(".", ":").replace("h", ":")
    if ":" in text:
        hours, _, minutes = text.partition(":")
    elif text.isdigit() and len(text) > 2:
        hours, minutes = text[:-2], text[-2:]
    else:
        hours, minutes = text, "0"
    try:
        hour, minute = int(hours), int(minutes or 0)
    except ValueError:
        return None
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return hour * 60 + minute


def clock_text(seconds: float) -> str:
    """Race time as h:mm"""
    minutes = int(max(seconds, 0) // 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def day_time_text(start_minutes: int, seconds: float) -> str:
    """Time of day (hh:mm) of race clock seconds, race started at start_minutes after midnight"""
    minutes = int((start_minutes * 60 + max(seconds, 0)) // 60) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def duration_text(seconds: float) -> str:
    """Race duration as h:mm:ss"""
    seconds = round(max(seconds, 0))
    return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def laps_text(laps: int) -> str:
    return f"{laps} {tr('lap') if laps < 2 else tr('laps')}"


# Plan export
def plan_markdown(title: str, header: Sequence[str], rows: Sequence[Sequence[str]], footer: str = "") -> str:
    """Pit stop plan for Discord: title in bold, table in a code block (columns aligned)"""
    widths = [max(len(str(row[column])) for row in (header, *rows)) for column in range(len(header))]
    lines = [" | ".join(str(text).ljust(width) for text, width in zip(row, widths)).rstrip()
             for row in (header, *rows)]
    lines.insert(1, "-+-".join("-" * width for width in widths))
    text = f"**{title}**\n```\n" + "\n".join(lines) + "\n```"
    return text + (f"\n{footer}" if footer else "")


def write_plan_csv(filename: str, header: Sequence[str], rows: Sequence[Sequence[str]]):
    """Pit stop plan as spreadsheet (CSV)"""
    with open(filename, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        writer.writerows(rows)
