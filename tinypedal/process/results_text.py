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
Texts of session results in app language: times, gaps, game texts (retirement reasons, penalties)

Shared by race results page (ui/quick/results_backend.py) and race results stream overlay
(stream_overlay.py, served from a server thread: no Qt here).
"""

from __future__ import annotations

from .. import calculation as calc
from ..formatter import random_color_class
from ..i18n import tr
from .results_file import Entry, SessionResult, best_lap_gap, race_gap

MINUS = chr(0x2212)  # typeset minus sign
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


def lap_text(seconds: float) -> str:
    """Lap time m:ss.sss, "-" if none"""
    return calc.sec2laptime_full(seconds) if seconds > 0 else "-"


def race_time_text(seconds: float) -> str:
    """Race time h:mm:ss.sss (m:ss.sss under an hour), "" if none"""
    if seconds <= 0:
        return ""
    minutes, rest = divmod(seconds, 60)
    hours, minutes = divmod(int(minutes), 60)
    if hours:
        return f"{hours}:{minutes:02d}:{rest:06.3f}"
    return f"{minutes}:{rest:06.3f}"


def gap_seconds_text(seconds: float) -> str:
    """Gap "+2.345", "+1:02.345" over a minute"""
    if seconds >= 60:
        return f"+{calc.sec2laptime_full(seconds)}"
    return f"+{seconds:.3f}"


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
            return f"+{laps_text(gap.laps)}", "dim"
        return (gap_seconds_text(gap.time) if gap.time > 0 else ""), ""
    if first:
        return "", ""
    gap_time = best_lap_gap(entry, leader)
    return (gap_seconds_text(gap_time) if gap_time >= 0 else "-"), "" if gap_time >= 0 else "dim"


def driver_names(entry: Entry) -> list[str]:
    """Drivers of car in order of first stint (driver changes), current driver if none"""
    names: list[str] = []
    for swap in entry.swaps:
        if swap.driver and swap.driver not in names:
            names.append(swap.driver)
    if entry.name and entry.name not in names:
        names.append(entry.name)
    return names


def class_color(car_class: str, classes: dict | None = None) -> str:
    """Color of vehicle class (vehicle class editor), made from name if not set"""
    if classes is None:
        from ..setting import cfg

        classes = cfg.user.classes
    style = classes.get(car_class) if isinstance(classes, dict) else None
    if isinstance(style, dict) and style.get("color"):
        return str(style["color"])
    return random_color_class(car_class)
