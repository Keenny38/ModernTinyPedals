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
Driver stats viewer figures of All Tracks (no Qt, no page state): race record of results files (clean streak,
places gained), people met in online races, rank history chart, driving time by track & class of a period,
official races to come (RaceControl daily races) & tracks of driver stats they are on
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, NamedTuple

from ...process import driver_ranks as dr
from ...process import results_file as rf
from ...process import results_index as ri
from ...userfile.driver_history import SessionRecord

MIN_MEETINGS = 2  # races together before someone is a rival
MAX_RIVALS = 8
TOP_TRACKS = 6  # tracks of driving time distribution (others summed)
DAILY_TIERS = ("beginner", "intermediate", "advanced")  # RaceControl daily race levels (game menu order)
MAX_UPCOMING = 6
TRACK_VERSION = re.compile(r"\s+v?\d+(\.\d+)+$")  # "Algarve International Circuit 1.27" -> version at end


# Race record of results files
def clean_race(summary: ri.ResultSummary) -> bool:
    return summary.contacts == 0 and summary.penalties == 0


def clean_streak(summaries: Sequence[ri.ResultSummary]) -> int:
    """Latest races in a row without contact nor penalty (summaries oldest first)"""
    streak = 0
    for summary in reversed(summaries):
        if summary.kind != "Race":
            continue
        if not clean_race(summary):
            break
        streak += 1
    return streak


def class_places_gained(summary: ri.ResultSummary) -> int | None:
    """Class places gained in a finished race of a results file, None if start or finish unknown"""
    if summary.kind != "Race" or summary.status != rf.FINISHED or summary.class_grid <= 0 or summary.class_position <= 0:
        return None
    return summary.class_grid - summary.class_position


def average_gained(summaries: Iterable[ri.ResultSummary]) -> tuple[float, int]:
    """Average class places gained & races counted"""
    gains = [gained for gained in map(class_places_gained, summaries) if gained is not None]
    return (sum(gains) / len(gains), len(gains)) if gains else (0.0, 0)


# People met in online races
class Rival(NamedTuple):
    """Someone of your class in several online races: races together, finished ahead of them, behind them, best lap
    gap (s, yours minus theirs, mean of races both set one; None if none), last race together (Unix time)"""

    name: str
    races: int
    ahead: int
    behind: int
    gap: float | None
    last: float


def finish_order(position: int, status: str) -> int:
    """Classification for comparison: finishers by class position, others after every finisher"""
    if status == rf.FINISHED and position > 0:
        return position
    return 10000


def rivals(summaries: Iterable[ri.ResultSummary]) -> list[Rival]:
    """People met in MIN_MEETINGS online races or more (most races together first, then latest)"""
    found: dict[str, list] = {}  # name: races, ahead, behind, gaps, last
    for summary in summaries:
        if summary.kind != "Race" or summary.setting != "Multiplayer":
            continue
        mine = finish_order(summary.class_position, summary.status)
        for other in summary.rivals:
            entry = found.setdefault(other.name, [0, 0, 0, [], 0.0])
            entry[0] += 1
            theirs = finish_order(other.class_position, other.status)
            if mine < theirs:
                entry[1] += 1
            elif theirs < mine:
                entry[2] += 1
            if summary.best_lap > 0 and other.best_lap > 0:
                entry[3].append(summary.best_lap - other.best_lap)
            entry[4] = max(entry[4], summary.end)
    shown = [Rival(name, races, ahead, behind, sum(gaps) / len(gaps) if gaps else None, last)
             for name, (races, ahead, behind, gaps, last) in found.items() if races >= MIN_MEETINGS]
    shown.sort(key=lambda rival: (-rival.races, -rival.last, rival.name.casefold()))
    return shown[:MAX_RIVALS]


# Rank history
def rank_chart(history: Sequence[dr.HistoryEntry], field: str) -> list[dict]:
    """Points of a rank ("driver" or "safety") over time: x (0-1, time), y (0-1, Bronze 1 at bottom, top of
    Platinum 3 at top), rank text; empty under 2 points of different times"""
    values = [(entry.time, rank.level, rank.text) for entry in history
              if (rank := getattr(entry, field)) is not None and rank.level >= 0]
    if len(values) < 2 or values[0][0] == values[-1][0]:
        return []
    first, last = values[0][0], values[-1][0]
    top = len(dr.RANK_ORDER) * 3
    return [{"x": (when - first) / (last - first), "y": min(max(value / top, 0.0), 1.0), "text": text}
            for when, value, text in values]


# Driving time of a period by track & by class
def period_bounds(year: int, today: date) -> tuple[date, date]:
    """First & last day of a year (0: the last 12 months)"""
    if year > 0:
        return date(year, 1, 1), date(year, 12, 31)
    return today - timedelta(days=364), today


def distribution(records: Iterable[SessionRecord], first: date, last: date, class_of) -> tuple[list, list]:
    """Driving time (seconds) of each track (TOP_TRACKS, then others as "") & of each class, most first"""
    tracks: dict[str, float] = {}
    classes: dict[str, float] = {}
    for record in records:
        day = date.fromtimestamp(record.time)
        if day < first or day > last or record.seconds <= 0:
            continue
        tracks[record.track] = tracks.get(record.track, 0.0) + record.seconds
        name = record.vehicle_class or class_of(record.vehicle)
        classes[name] = classes.get(name, 0.0) + record.seconds
    ordered = sorted(tracks.items(), key=lambda item: -item[1])
    top = ordered[:TOP_TRACKS]
    others = sum(seconds for _, seconds in ordered[TOP_TRACKS:])
    if others > 0:
        top.append(("", others))
    return top, sorted(classes.items(), key=lambda item: -item[1])


def history_years(records: Iterable[SessionRecord]) -> list[int]:
    """Years with sessions, newest first"""
    return sorted({date.fromtimestamp(record.time).year for record in records}, reverse=True)


# Official races to come (RaceControl daily races, as the game menu lists them)
class Upcoming(NamedTuple):
    """Daily race to come: tier (beginner...), title, start (Unix time), track name & scene (game track key),
    classes registered so far"""

    tier: str
    title: str
    start: float
    track: str
    scene: str
    classes: tuple[str, ...]


def parse_start(value: Any) -> float:
    """ISO time of RaceControl (UTC when no zone) to Unix time, 0 if unreadable"""
    if not isinstance(value, str) or not value:
        return 0.0
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp()


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def parse_events(tier: str, data: Any) -> list[Upcoming]:
    """Daily races of a tier answer (list of events, see game web UI Event class), unreadable entries skipped"""
    events = []
    for event in data if isinstance(data, list) else ():
        if not isinstance(event, dict):
            continue
        config = event.get("configuration")
        config = config if isinstance(config, dict) else {}
        content = config.get("content")
        content = content if isinstance(content, dict) else {}
        track = content.get("track")
        track = track if isinstance(track, dict) else {}
        layouts = track.get("subItems")
        layout = layouts[0] if isinstance(layouts, list) and layouts and isinstance(layouts[0], dict) else {}
        registered = event.get("registered")
        classes = registered.get("class") if isinstance(registered, dict) else None
        start = parse_start(config.get("starts")) or parse_start(event.get("raceStartsAt"))
        name = _text(track.get("friendly")) or _text(layout.get("name")) or _text(track.get("name"))
        if not start or not name:
            continue
        events.append(Upcoming(
            tier=tier, title=_text(config.get("title")) or _text(event.get("title")), start=start,
            track=name.replace("_", " "), scene=_text(layout.get("scn")) or _text(layout.get("sceneDesc")),
            classes=tuple(sorted(str(key) for key in classes)) if isinstance(classes, dict) else (),
        ))
    return events


def read_upcoming(get) -> list[Upcoming]:
    """Next races of every tier (get: RaceControl GET path -> JSON, None if not read), soonest first (worker
    thread)"""
    events: list[Upcoming] = []
    for tier in DAILY_TIERS:
        events.extend(parse_events(tier, get(f"api/v1/daily/list/{tier}?take=2")))
    events.sort(key=lambda event: event.start)
    return events[:MAX_UPCOMING]


def track_names(game_tracks: Any) -> dict[str, tuple[str, ...]]:
    """Names of each game track scene (game Rest API /rest/race/track): name, short names without version"""
    names: dict[str, tuple[str, ...]] = {}
    for track in game_tracks if isinstance(game_tracks, list) else ():
        if not isinstance(track, dict):
            continue
        scene = _text(track.get("sceneDesc"))
        display = track.get("displayProperties")
        display = display if isinstance(display, dict) else {}
        found = [_text(track.get("name")), TRACK_VERSION.sub("", _text(track.get("shortName"))),
                 _text(display.get("name")), _text(display.get("shortName"))]
        if scene:
            names[scene.casefold()] = tuple(dict.fromkeys(name for name in found if name))
    return names


def stats_track(event: Upcoming, keys: Iterable[str], names: dict[str, tuple[str, ...]]) -> str:
    """Driver stats track of an event ("" if never driven there): game names of its scene, else its own name"""
    wanted = {name.casefold() for name in names.get(event.scene.casefold(), ())} | {event.track.casefold()}
    return next((key for key in keys if key.casefold() in wanted), "")
