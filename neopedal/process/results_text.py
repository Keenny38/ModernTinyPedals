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
Texts of session results in app language: times, gaps, game texts (retirement reasons, penalties)

Shared by race results page (ui/quick/results_backend.py) and race results stream overlay
(stream_overlay.py, served from a server thread: no Qt here).
"""

from __future__ import annotations

from .. import calculation as calc
from ..formatter import class_alias, class_color, class_style  # noqa: F401  # shared by results pages & stream graphics
from ..i18n import localized, tr
from .results_file import Entry, SessionResult, best_lap_gap, race_gap

MINUS = chr(0x2212)  # typeset minus sign
# Session filter of Results, Replays & Stats pages: labels in this order (index saved by each page)
SESSION_FILTER_LABELS = ("All", "Practice", "Qualifying", "Race")
MISSING = chr(0x2014)  # value unknown or not available, on every app page (in-game overlays keep their en dash)
PODIUM_TONES = ("gold", "silver", "bronze")  # race podium places of Results & Stats pages
RETIRED_TONE = "loss"  # DNF & DQ of Results & Stats pages
# Texts written by game (English): label shown, translated (unknown texts shown as written)
GAME_LABELS = {
    # Retirement reasons
    "Accident": "Accident",
    "Engine": "Engine failure",
    "Suspension": "Suspension failure",
    "Gearbox": "Gearbox failure",
    "Brakes": "Brake failure",
    "Electronics": "Electronics failure",
    "Overheating": "Overheating",
    "Damage": "Damage",
    # Track limits resolutions
    "Warning": "Track limits warning",
    "Invalid Lap Cut Track": "Lap invalidated (corner cut)",
    "Invalid Lap Off Track": "Lap invalidated (off track)",
    "Drive Through Penalty": "Drive-through penalty",
    "Stop/Go Penalty": "Stop & go penalty",
    # Penalties & reasons
    "Stop/Go": "Stop & go",
    "Drive Through": "Drive-through",
    "Speeding In Pitlane": "Pit lane speeding",
    "Exiting Pits Under Red": "Pit exit on red light",
}


def game_text(text: str) -> str:
    """Text written by game, in app language when known"""
    label = GAME_LABELS.get(text)
    return tr(label) if label else text


# Numbers & times of every app page: decimal separator of app language, typeset minus sign, " s" spaced
def number_text(value: float, decimals: int = 0) -> str:
    """Number with decimals: "2,5" in French, "-2,5" below zero (typeset minus) ("0" for a rounded "-0")"""
    decimals = max(decimals, 0)
    return localized(f"{round(value, decimals) + 0.0:.{decimals}f}").replace("-", MINUS)


def signed_text(value: float, decimals: int = 0, unit: str = "") -> str:
    """Signed number with optional unit: "+1,2 s", "-0,345" (typeset minus) (unit given with its leading space)"""
    decimals = max(decimals, 0)
    return f"{localized(f'{round(value, decimals) + 0.0:+.{decimals}f}')}{unit}".replace("-", MINUS)


def seconds_text(seconds: float, decimals: int = 1, sign: bool = False) -> str:
    """Duration in seconds: "12,3 s", signed if sign ("+1,2 s")"""
    if sign:
        return signed_text(seconds, decimals, " s")
    return f"{number_text(seconds, decimals)} s"


def laptime_text(seconds: float, missing: str = MISSING) -> str:
    """Lap time m:ss.sss of every app page (lap times keep their dot), missing text if none or aberrant"""
    return calc.sec2laptime_full(seconds) if 0 < seconds < 36000 else missing


def sector_text(seconds: float, missing: str = MISSING) -> str:
    """Sector time 32.456 (m:ss.sss from a minute), missing text if none"""
    if not 0 < seconds < 36000:
        return missing
    return calc.sec2laptime_full(seconds) if round(seconds, 3) >= 60 else f"{seconds:.3f}"


def position_text(position: int, total: int = 0) -> str:
    """Position "P3", "P3/12" out of a field, missing text if unknown"""
    if position <= 0:
        return MISSING
    return f"P{position}/{total}" if total > 0 else f"P{position}"


def place_tone(position: int, race: bool, retired: bool = False) -> str:
    """Finish place tone shared by Results & Stats: DNF / DQ "loss", race podium gold, silver & bronze (never in
    practice & qualifying), "" else"""
    if retired:
        return RETIRED_TONE
    return PODIUM_TONES[position - 1] if race and 1 <= position <= 3 else ""


def lap_text(seconds: float) -> str:
    """Lap time m:ss.sss, missing text if none"""
    return laptime_text(seconds)


def race_time_text(seconds: float) -> str:
    """Race time h:mm:ss.sss (m:ss.sss under an hour), "" if none"""
    if seconds <= 0:
        return ""
    minutes, rest = divmod(seconds, 60)
    hours, minutes = divmod(int(minutes), 60)
    if hours:
        return f"{hours}:{minutes:02d}:{rest:06.3f}"
    return f"{minutes}:{rest:06.3f}"


def gap_seconds_text(seconds: float, decimals: int = 3) -> str:
    """Gap "+2.345" (decimal separator of app language), "+1:02.345" over a minute: gaps of every page &
    stream graphic"""
    decimals = max(decimals, 0)
    seconds = round(seconds, decimals) + 0.0  # rounded first: 59.97 with 1 decimal is "+1:00.0", never "+60.0"
    if seconds >= 60:
        minutes, rest = divmod(seconds, 60)
        width = 3 + decimals if decimals else 2
        return f"+{minutes:.0f}:{rest:0{width}.{decimals}f}"
    return f"+{localized(f'{seconds:.{decimals}f}')}"


def laps_behind_text(laps: int) -> str:
    """Gap in whole laps: "+1 lap", "+2 laps" (in app language), for every page & stream graphic"""
    return f"+{laps_text(laps)}"


def count_text(count: int, one: str, many: str) -> str:
    """Count with word: "1 car", "3 cars" (in app language)"""
    return f"{count} {tr(one) if count == 1 else tr(many)}"


def laps_text(count: int) -> str:
    return count_text(count, "lap", "laps")


def kind_text(kind: str) -> str:
    """Session kind ("Race"...) in app language"""
    return tr(kind) if kind else ""


def finished(entry: Entry) -> bool:
    """Car not retired nor disqualified"""
    return entry.status not in ("DNF", "DQ")


def entry_gap(result: SessionResult, entry: Entry, leader: Entry, first: bool) -> tuple[str, str]:
    """Time or gap text & tone: race time of winner, "+2.345", "+1 lap", "DNF" ("loss" tone); best lap gap in
    practice & qualifying ("" for fastest car: its best lap is shown on its own)"""
    if result.kind == "Race":
        if not finished(entry):
            return game_text(entry.status), "loss"
        if first:
            return (race_time_text(entry.finish_time) or laps_text(entry.laps_completed)), ""
        gap = race_gap(entry, leader)
        if gap.laps:
            return laps_behind_text(gap.laps), "dim"
        return (gap_seconds_text(gap.time) if gap.time > 0 else ""), ""
    if first:
        return "", ""
    gap_time = best_lap_gap(entry, leader)
    return (gap_seconds_text(gap_time) if gap_time >= 0 else MISSING), "" if gap_time >= 0 else "dim"


def driver_names(entry: Entry) -> list[str]:
    """Drivers of car in order of first stint (driver changes), current driver if none"""
    names: list[str] = []
    for swap in entry.swaps:
        if swap.driver and swap.driver not in names:
            names.append(swap.driver)
    if entry.name and entry.name not in names:
        names.append(entry.name)
    return names


