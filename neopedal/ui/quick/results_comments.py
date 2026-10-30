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
Race results page comments on the player's session, from the results file already read: pace against the
median of the class, places gained or lost on lap 1 (races), lap time trend of each stint (races)

Pure functions (no Qt): rows of plain texts the page lays out (glyph, title, value, detail, tone).
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from ...i18n import localized, tr
from ...process.results_file import Entry, Lap, SessionResult
from ...process.results_text import MINUS, count_text, lap_text

CLEAN_LIMIT = 1.07  # clean lap: within 107 % of the best lap of the car (or stint): yellow flags, traffic left out
MIN_PACE_LAPS = 3  # clean laps of a car for its race pace
MIN_CLASS_CARS = 3  # cars with a pace in the class for a class median
MIN_STINT_LAPS = 5  # clean laps of a stint for its lap time trend
MAX_STINTS = 4  # stints told (longest races: first ones)
SAME_PACE = 0.05  # s: pace this close to the median told as "on the median"

GLYPH_PACE = ""  # stopwatch
GLYPH_START = ""  # flag
GLYPH_TREND = ""  # chart


def signed(value: float, decimals: int = 3) -> str:
    return localized(f"{value:+.{decimals}f}").replace("-", MINUS)


def clean_times(laps: Sequence[Lap], race: bool) -> list[float]:
    """Lap times of laps at pace: timed, no pit lane, not the standing start (races), within CLEAN_LIMIT of the
    best of them"""
    times = [lap.time for lap in laps if lap.time > 0 and not lap.pit and not (race and lap.number <= 1)]
    if not times:
        return []
    limit = min(times) * CLEAN_LIMIT
    return [time for time in times if time <= limit]


def entry_pace(entry: Entry, race: bool) -> float:
    """Race: median of clean laps (MIN_PACE_LAPS at least), else best lap; 0 if none"""
    if not race:
        return entry.best_lap if entry.best_lap > 0 else 0.0
    times = clean_times(entry.laps, True)
    return statistics.median(times) if len(times) >= MIN_PACE_LAPS else 0.0


def pace_comment(result: SessionResult, entry: Entry) -> dict[str, str] | None:
    """Pace of entry against the median pace of its class (MIN_CLASS_CARS with a pace), None if unknown"""
    race = result.kind == "Race"
    paces = {id(other): entry_pace(other, race) for other in result.entries if other.car_class == entry.car_class}
    own = paces.get(id(entry), 0.0)
    known = sorted(pace for pace in paces.values() if pace > 0)
    if own <= 0 or len(known) < MIN_CLASS_CARS:
        return None
    median = statistics.median(known)
    delta = own - median
    rank = known.index(own) + 1
    if abs(delta) < SAME_PACE:
        compared = tr("on the class median")
    else:
        compared = f"{signed(delta)} s {tr('vs class median')}"
    return {
        "glyph": GLYPH_PACE,
        "title": tr("Race pace") if race else tr("Best Lap"),
        "value": lap_text(own),
        "detail": f"{compared} · {rank} / {len(known)} {tr('in class')}",
        "tone": "" if abs(delta) < SAME_PACE else "gain" if delta < 0 else "loss",
    }


def class_place(result: SessionResult, entry: Entry, lap_number: int) -> int:
    """Place of entry in its class at the end of a lap (overall places of its class cars that lap), 0 if unknown"""
    def place_of(car: Entry) -> int:
        return next((lap.position for lap in car.laps if lap.number == lap_number and lap.position > 0), 0)

    own = place_of(entry)
    if own <= 0:
        return 0
    return 1 + sum(1 for other in result.entries
                   if other is not entry and other.car_class == entry.car_class and 0 < place_of(other) < own)


def start_comment(result: SessionResult, entry: Entry) -> dict[str, str] | None:
    """Places gained or lost on lap 1 of a race (in class when several classes), None if grid or lap 1 unknown"""
    if result.kind != "Race":
        return None
    multiclass = len(result.classes) > 1
    grid = entry.class_grid if multiclass else entry.grid
    after = class_place(result, entry, 1) if multiclass else next(
        (lap.position for lap in entry.laps if lap.number == 1 and lap.position > 0), 0)
    if grid <= 0 or after <= 0:
        return None
    change = grid - after
    if change > 0:
        detail, tone = f"+{count_text(change, 'place gained', 'places gained')}", "gain"
    elif change < 0:
        detail, tone = f"{MINUS}{count_text(-change, 'place lost', 'places lost')}", "loss"
    else:
        detail, tone = tr("Same place as the start"), ""
    return {
        "glyph": GLYPH_START,
        "title": tr("Lap 1"),
        "value": f"P{grid} → P{after}",
        "detail": detail + (f" · {entry.car_class}" if multiclass else ""),
        "tone": tone,
    }


def stints_of(laps: Sequence[Lap]) -> list[list[Lap]]:
    """Laps of each stint: a new stint starts after a lap through the pit lane"""
    stints: list[list[Lap]] = [[]]
    for lap in laps:
        stints[-1].append(lap)
        if lap.pit:
            stints.append([])
    return [stint for stint in stints if stint]


def trend(points: Sequence[tuple[float, float]]) -> float:
    """Slope of the least squares line through points (x, y)"""
    count = len(points)
    mean_x = sum(x for x, _ in points) / count
    mean_y = sum(y for _, y in points) / count
    spread = sum((x - mean_x) ** 2 for x, _ in points)
    if spread <= 0:
        return 0.0
    return sum((x - mean_x) * (y - mean_y) for x, y in points) / spread


def stint_trends(laps: Sequence[Lap]) -> list[tuple[int, int, float]]:
    """Lap time trend (s per lap: tyres wearing, fuel burning) of each stint with MIN_STINT_LAPS clean laps:
    first & last lap of stint, slope"""
    found = []
    for stint in stints_of(laps):
        timed = [lap for lap in stint[1:] if lap.time > 0 and not lap.pit and lap.number > 1]  # out lap left out
        if not timed:
            continue
        limit = min(lap.time for lap in timed) * CLEAN_LIMIT
        points = [(float(lap.number), lap.time) for lap in timed if lap.time <= limit]
        if len(points) >= MIN_STINT_LAPS:
            found.append((stint[0].number, stint[-1].number, trend(points)))
    return found


def stint_comment(result: SessionResult, entry: Entry) -> dict[str, str] | None:
    """Lap time trend of each stint of a race, None if no stint is long enough"""
    if result.kind != "Race":
        return None
    trends = stint_trends(entry.laps)
    if not trends:
        return None
    parts = [f"{first}-{last}: {signed(slope, 2)} s" for first, last, slope in trends[:MAX_STINTS]]
    worst = max(slope for _, _, slope in trends)
    return {
        "glyph": GLYPH_TREND,
        "title": tr("Lap time trend"),
        "value": f"{signed(worst, 2)} s/{tr('lap')}",
        "detail": f"{tr('Laps')} " + " · ".join(parts) if len(trends) > 1 else f"{tr('Laps')} {parts[0]}",
        "tone": "",
    }


def session_comments(result: SessionResult | None) -> list[dict[str, str]]:
    """Comments on the player's session (none without player): pace in class, lap 1 (races), stint trends (races)"""
    if result is None:
        return []
    entry = result.player_entry
    if entry is None:
        return []
    comments = (pace_comment(result, entry), start_comment(result, entry), stint_comment(result, entry))
    return [comment for comment in comments if comment is not None]
