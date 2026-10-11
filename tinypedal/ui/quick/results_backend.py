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
Race results page (ui/qml/RaceResults.qml): sessions of the game results files (LMU, rFactor 2), with
classification, positions lap by lap, laps of a driver and session events (contacts, penalties, track
limits, chat)

Results files are read in background (about half a second for a hundred files), only new or changed
files again when the folder changes (session ended while page is open). Only what the session list needs is
kept of each file: the session picked is read again in background (last few kept), results are released a
while after the page is hidden. Row texts are built here (app language, user units), QML only lays them out.
"""

from __future__ import annotations

import json
import logging
import os
import statistics
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from typing import Any, NamedTuple

from PySide6.QtCore import Property, QDate, QFileSystemWatcher, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QWidget

from ... import calculation as calc
from ... import units
from ...i18n import tr
from ...process import results_file as rf
from ...process import results_index as ri
from ...process.results_file import Entry, Event, SessionResult
from ...process.results_index import FileStamp, SessionInfo, session_info
from ...process.results_text import (
    MINUS,
    class_color,
    count_text,
    driver_names,
    entry_gap,
    finished,
    game_text,
    kind_text,
    lap_text,
    laps_text,
)
from ...setting import cfg
from ...userfile import atomic_write
from ..game_rest import GameRequest
from ..lap_viewer import localized
from .background import BackgroundJobs
from .game_pictures import (
    LogoCache,
    brand_logo_url,
    car_picture_url,
    light_theme,
    notifier,
    track_logo_url,
    track_picture_url,
)
from .lines import VertexStore, Vertices, band, normals
from .models import DictListModel
from .replays_backend import clock_minutes, day_text

logger = logging.getLogger(__name__)

SETTINGS_FILE = rf.PAGE_SETTINGS_FILE  # page settings, user config folder
KIND_FILTERS = ("", "Race", "Qualifying", "Practice")  # "" = every session
KIND_CODES = {"Race": "R", "Qualifying": "Q", "Practice": "P", "Warmup": "W"}
TABS = ("classification", "positions", "laps", "events")
EVENT_FILTERS = ("", "contact", "penalty", "track_limits", "chat")
RELOAD_DELAY_MS = 1500  # folder changed: read again once game has written whole file
KEPT_RESULTS = 5  # full results of sessions picked lately (each one: up to a few MB)
RELEASE_DELAY_MS = 60_000  # page hidden that long: full results released (read again when shown)
READ_DELAY_MS = 120  # session picked: read once selection settles (Up / Down held: one read)
SYNC_CHART_POINTS = 3000  # positions chart built at once up to this many laps, longer races in background

SESSION_ROLES = (
    "key", "title", "course", "code", "kindText", "day", "clock", "cars", "online", "resultText",
    "resultTone", "detailText", "newest", "trackLogo", "replay",
)
CLASSIFICATION_ROLES = (
    "key", "posText", "gridDelta", "classText", "classPosText", "classColor", "number", "driver", "team",
    "drivers", "car", "laps", "gapText", "gapTone", "reasonText", "bestText", "bestTone", "pits", "contacts",
    "penalties", "player", "selected", "brandLogo",
)
LAP_ROLES = (
    "key", "lap", "posText", "timeText", "timeTone", "deltaText", "s1", "s2", "s3", "s1Tone", "s2Tone",
    "s3Tone", "speedText", "compound", "pit", "usageText", "wearText",
)
EVENT_ROLES = ("key", "clock", "kind", "glyph", "title", "detail", "mine")
EVENT_GLYPHS = {  # Segoe Fluent Icons / MDL2 Assets
    "contact": "",  # lightning
    "penalty": "",  # warning
    "track_limits": "",  # flag
    "chat": "",  # message
}
# Page settings (user config folder), kept between sessions
def settings_path() -> str:
    return os.path.join(cfg.path.config, SETTINGS_FILE)


def load_page_settings() -> dict[str, Any]:
    try:
        with open(settings_path(), encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_page_settings(data: dict[str, Any]):
    with atomic_write(settings_path()) as file:
        json.dump(data, file, indent=1, ensure_ascii=False)


# Reading (background): files read once for driver stats page too (results_index)
def as_info(result: SessionResult | SessionInfo) -> SessionInfo:
    return result if isinstance(result, SessionInfo) else session_info(result)


class Loaded(NamedTuple):
    """Results read in background"""

    folders: tuple[str, ...]
    files: dict[str, tuple[FileStamp, SessionInfo | None]]  # None: not a results file (yet)
    full: dict[str, tuple[FileStamp, SessionResult]]  # newest sessions new to page (oldest first)
    replays: dict[str, ri.ReplayFile]  # replay of sessions (results path: replay saved by game)


def load_results(folders: Sequence[str], known: dict[str, tuple[FileStamp, SessionInfo | None]]) -> Loaded:
    """Session list of folders, files unchanged since read (by this page or driver stats) not read again

    Only the list part of each file is kept, with full results of the newest sessions new to the page (shown
    next): taken from the files read now, else read again (read before by driver stats).
    """
    scan = ri.scan_results(folders, keep_full=KEPT_RESULTS)
    files = {path: (parsed.stamp, parsed.info) for path, parsed in scan.files.items()}
    fresh = []
    for path, (stamp, info) in files.items():
        previous = known.get(path)
        if info is not None and not (previous is not None and previous[0] == stamp and previous[1] is not None):
            fresh.append((info.time, path))
    full: dict[str, tuple[FileStamp, SessionResult]] = {}
    for _, path in sorted(fresh)[-KEPT_RESULTS:]:
        stamp, info = files[path]
        read = scan.full.get(path)
        if read is not None and read[0] == stamp:
            full[path] = read
            continue
        try:
            full[path] = (stamp, rf.read_results(path, info.player_names if info is not None else ()))
        except (OSError, ValueError) as error:  # changed meanwhile: read once picked
            logger.debug("RACE RESULTS: %s not read: %s", path, error)
    sessions = [ri.ReplaySession(path, info.track, info.venue, ri.session_code(path) or KIND_CODES.get(info.kind, ""),
                                 stamp.modified) for path, (stamp, info) in files.items() if info is not None]
    return Loaded(tuple(folders), files, full, ri.session_replays(sessions))


def read_session(path: str, stamp: FileStamp, player_names: tuple[str, ...]
                 ) -> tuple[str, FileStamp, SessionResult]:
    """Full results of session picked (background)"""
    return path, stamp, rf.read_results(path, player_names)


# Texts
def percent_text(fraction: float, decimals: int = 1) -> str:
    return f"{localized(f'{fraction * 100:.{decimals}f}')} %"


def signed_seconds(value: float) -> str:
    return f"{value:+.3f}".replace("-", MINUS)


def speed_converter() -> tuple[Any, str]:
    """Speed (km/h) in user unit, symbol"""
    unit = str(cfg.units.get("speed_unit", "KPH")) if isinstance(cfg.units, dict) else "KPH"
    to_unit = units.set_unit_speed(unit)
    return (lambda kph: to_unit(kph / 3.6)), units.set_symbol_speed(unit)


def length_text(result: SessionResult) -> str:
    """Session length: "60 min", "20 laps" """
    if result.lap_limit:
        return laps_text(result.lap_limit)
    if result.minutes:
        return f"{result.minutes} {tr('min')}"
    return ""


def track_subtitle(result: SessionResult | SessionInfo) -> str:
    """Layout name, or venue when event name is shown"""
    for name in (result.course, result.venue):
        if name and name != result.track:
            return name
    return ""


def player_result_text(result: SessionResult | SessionInfo, entry: Entry | None) -> tuple[str, str]:
    """Result of player for session list: ("P3", tone), ("DNF", "loss"), ("", "") if not in session"""
    if entry is None:
        return "", ""
    if result.kind == "Race" and not finished(entry):
        return game_text(entry.status), "loss"
    if entry.position <= 0 or (result.kind != "Race" and entry.best_lap <= 0):
        return "", ""
    multiclass = as_info(result).class_count > 1
    shown = entry.class_position if multiclass and entry.class_position > 0 else entry.position
    tone = "gold" if shown == 1 else "gain" if shown <= 3 else ""
    return f"P{shown}", tone


def session_row(result: SessionResult | SessionInfo, today: QDate, newest: bool = False, replay: bool = False,
                logo: str | None = None) -> dict[str, Any]:
    """Row of session list (logo: circuit logo URL if known already)"""
    info = as_info(result)
    player = info.player
    result_text, tone = player_result_text(info, player)
    if player is None:
        detail = laps_text(info.most_laps) if info.most_laps else ""
    elif info.class_count > 1:
        detail = player.car_class
    else:
        detail = player.car
    return {
        "key": info.path,
        "title": info.track,
        "course": track_subtitle(info),
        "code": KIND_CODES.get(info.kind, "?"),
        "kindText": kind_text(info.kind),
        "day": day_text(info.time, today),
        "clock": clock_minutes(info.time) if info.time > 0 else "",
        "cars": info.cars,
        "online": info.setting == "Multiplayer",
        "resultText": result_text,
        "resultTone": tone,
        "detailText": detail,
        "newest": newest,
        "trackLogo": track_logo_url(info.track, info.venue, info.course) if logo is None else logo,
        "replay": replay,
    }


def session_text(info: SessionInfo) -> str:
    """Searched text of a session (casefolded)"""
    player = info.player
    return " ".join((
        info.track, info.venue, info.course, info.server, info.kind, kind_text(info.kind),
        info.first_class, player.car if player else "", player.car_class if player else "",
    )).casefold()


def session_matches(result: SessionResult | SessionInfo, kind: str, words: Sequence[str], hide_empty: bool,
                    text: str | None = None) -> bool:
    """Session shown by filters (text: session_text if known already)"""
    info = as_info(result)
    if kind and info.kind != kind:
        return False
    if hide_empty and info.most_laps <= 0:
        return False
    if words:
        haystack = session_text(info) if text is None else text
        return all(word in haystack for word in words)
    return True


# Classification
def filtered_entries(result: SessionResult, class_filter: str) -> list[tuple[int, Entry]]:
    return [(index, entry) for index, entry in enumerate(result.entries)
            if not class_filter or entry.car_class == class_filter]


def classification_rows(result: SessionResult, class_filter: str, selected: str, logos: LogoCache | None = None
                        ) -> list[dict[str, Any]]:
    entries = filtered_entries(result, class_filter)
    brand_logo = logos.brand if logos is not None else brand_logo_url
    if not entries:
        return []
    race = result.kind == "Race"
    leader = entries[0][1]
    times = [entry.best_lap for _, entry in entries if entry.best_lap > 0]
    fastest = min(times) if times else 0.0
    contacts = rf.contact_counts(result.events)
    penalties = rf.penalty_counts(result.events)
    multiclass = len(result.classes) > 1
    rows = []
    for rank, (index, entry) in enumerate(entries, 1):
        position = (entry.class_position if class_filter else entry.position) or rank
        grid = entry.class_grid if class_filter else entry.grid
        gap, tone = entry_gap(result, entry, leader, rank == 1)
        names = driver_names(entry)
        cars, objects = contacts.get(entry.name, (0, 0))
        for name in names:
            if name != entry.name:
                extra = contacts.get(name, (0, 0))
                cars, objects = cars + extra[0], objects + extra[1]
        rows.append({
            "key": str(index),
            "posText": str(position),
            "gridDelta": grid - position if race and grid > 0 and finished(entry) else 0,
            "classText": entry.car_class if multiclass else "",
            "classPosText": str(entry.class_position) if multiclass and entry.class_position > 0 else "",
            "classColor": class_color(entry.car_class),
            "number": entry.number,
            "driver": entry.name,
            "team": entry.team or entry.vehicle,
            "drivers": ", ".join(names) if len(names) > 1 else "",
            "car": entry.car,
            "laps": entry.laps_completed,
            "gapText": gap,
            "gapTone": tone,
            "reasonText": game_text(entry.dnf_reason) if race and entry.status == "DNF" and entry.dnf_reason != "DNF"
            else "",
            "bestText": lap_text(entry.best_lap) if entry.best_lap > 0 else "-",
            "bestTone": "purple" if entry.best_lap > 0 and entry.best_lap == fastest else "",
            "pits": entry.pitstops,
            "contacts": cars + objects,
            "penalties": sum(penalties.get(name, 0) for name in names),
            "player": entry.player,
            "selected": str(index) == selected,
            "brandLogo": brand_logo(entry.vehicle, entry.car),
        })
    return rows


def class_chips(result: SessionResult) -> list[dict[str, Any]]:
    """Car classes with color & car count, only when several"""
    classes = result.classes
    if len(classes) < 2:
        return []
    return [{
        "name": name,
        "color": class_color(name),
        "count": sum(1 for entry in result.entries if entry.car_class == name),
    } for name in classes]


# Player summary
def tile(label: str, value: str, detail: str = "", tone: str = "") -> dict[str, str]:
    return {"label": label, "value": value, "detail": detail, "tone": tone}


def summary_tiles(result: SessionResult) -> list[dict[str, str]]:
    """Key figures of player (winner & fastest lap if player not in session)"""
    entries = result.entries
    if not entries:
        return []
    times = [entry for entry in entries if entry.best_lap > 0]
    fastest = min(times, key=lambda entry: entry.best_lap) if times else None
    player = result.player_entry
    tiles = []
    if player is None:
        winner = entries[0]
        label = tr("Winner") if result.kind == "Race" else tr("Fastest")
        tiles.append(tile(label, winner.name, winner.car))
    else:
        multiclass = len(result.classes) > 1
        if result.kind == "Race" and not finished(player):
            value, tone = game_text(player.status), "loss"
            detail = game_text(player.dnf_reason) if player.dnf_reason not in ("", "DNF") else ""
        else:
            value = f"P{player.position}" if player.position > 0 else "-"
            tone = "gold" if player.position == 1 else ""
            class_cars = sum(1 for entry in entries if entry.car_class == player.car_class)
            detail = (f"{player.car_class} P{player.class_position} / {class_cars}" if multiclass
                      else f"/ {len(entries)}")
        tiles.append(tile(tr("Position"), value, detail, tone))
        if result.kind == "Race" and player.grid > 0 and player.position > 0 and finished(player):
            grid = player.class_grid if multiclass and player.class_grid > 0 else player.grid
            finish = player.class_position if multiclass and player.class_position > 0 else player.position
            change = grid - finish
            tiles.append(tile(tr("Grid"), f"P{grid}", (f"+{change}" if change > 0 else
                                                        f"{change}".replace("-", MINUS) if change else "="),
                              "gain" if change > 0 else "loss" if change < 0 else ""))
        rank = sorted(entry.best_lap for entry in entries
                      if entry.best_lap > 0 and (not multiclass or entry.car_class == player.car_class))
        best_detail = ""
        if player.best_lap > 0 and rank:
            place = rank.index(player.best_lap) + 1
            best_detail = f"#{place}" if place > 1 else tr("Fastest")
        tiles.append(tile(tr("Best Lap"), lap_text(player.best_lap), best_detail,
                          "purple" if fastest is not None and fastest is player else ""))
        tiles.append(tile(tr("Laps"), str(player.laps_completed),
                          f"{player.pitstops} {tr('Pit Stops').lower()}" if result.kind == "Race" else ""))
        cars, objects = rf.contact_counts(result.events).get(player.name, (0, 0))
        points = rf.track_limit_points(result.events).get(player.name, 0.0)
        penalties = rf.penalty_counts(result.events).get(player.name, 0)
        tiles.append(tile(tr("Contacts"), str(cars + objects),
                          f"{count_text(cars, 'car', 'cars')} · {count_text(objects, 'wall', 'walls')}"
                          if cars + objects else "",
                          "loss" if cars + objects else ""))
        if points or penalties:
            tiles.append(tile(tr("Track limits"), localized(f"{points:g}"),
                              f"{penalties} {tr('Penalties').lower()}" if penalties else "",
                              "loss" if penalties else "warning"))
    if fastest is not None and (player is None or fastest is not player):
        tiles.append(tile(tr("Fastest Lap"), lap_text(fastest.best_lap), fastest.name, "purple"))
    return tiles


def session_header(result: SessionResult) -> dict[str, Any]:
    online = result.setting == "Multiplayer"
    parts = [
        tr("Online Session") if online else tr("Single Player Session"),
        result.server if online else "",
        length_text(result),
        count_text(len(result.entries), "car", "cars"),
        f"{localized(f'{result.track_length / 1000:.2f}')} km" if result.track_length > 0 else "",
    ]
    return {
        "title": result.track,
        "subtitle": track_subtitle(result),
        "code": KIND_CODES.get(result.kind, "?"),
        "kindText": kind_text(result.kind),
        "when": f"{day_text(result.time, QDate.currentDate())} · {clock_minutes(result.time)}" if result.time > 0
        else "",
        "details": " · ".join(part for part in parts if part),
        "race": result.kind == "Race",
        "partial": rf.race_unfinished(result),
        "file": os.path.basename(result.path),
        "game": result.game,
        "trackLogo": track_logo_url(result.track, result.venue, result.course),
        "trackPicture": track_picture_url(result.track, result.venue, result.course, large=True),
    }


# Laps of a driver
def lap_rows(result: SessionResult, entry: Entry) -> list[dict[str, Any]]:
    to_speed, _ = speed_converter()
    session_best = min((other.best_lap for other in result.entries if other.best_lap > 0), default=0.0)
    overall_sectors = rf.best_sectors(result.entries)
    own_sectors = rf.best_sectors((entry,))
    valid = [lap.time for lap in entry.laps if lap.time > 0]
    best = entry.best_lap if entry.best_lap > 0 else min(valid, default=0.0)
    rows = []
    for lap in entry.laps:
        row: dict[str, Any] = {
            "key": str(lap.number),
            "lap": lap.number,
            "posText": f"P{lap.position}" if lap.position > 0 else "",
            "timeText": lap_text(lap.time),
            "timeTone": ("purple" if lap.time > 0 and abs(lap.time - session_best) < 1e-4 else
                         "gain" if lap.time > 0 and abs(lap.time - best) < 1e-4 else "dim" if lap.time <= 0 else ""),
            "deltaText": signed_seconds(lap.time - best) if lap.time > 0 and best > 0 and lap.time - best > 1e-4
            else "",
            "speedText": f"{to_speed(lap.top_speed):.0f}" if lap.top_speed > 0 else "",
            "compound": lap.compound,
            "pit": lap.pit,
            "usageText": usage_text(lap),
            "wearText": percent_text(min(lap.wear), 0) if lap.wear else "",
        }
        for number, sector in enumerate(lap.sectors):
            key = f"s{number + 1}"
            row[key] = f"{sector:.3f}" if sector > 0 else ""
            row[f"{key}Tone"] = ("purple" if sector > 0 and abs(sector - overall_sectors[number]) < 1e-4 else
                                 "gain" if sector > 0 and abs(sector - own_sectors[number]) < 1e-4 else "")
        rows.append(row)
    return rows


def usage_text(lap: rf.Lap) -> str:
    """Virtual energy (else fuel) used on lap, share of full tank: "3.1 %" (own car only)"""
    if lap.energy_used > 0:
        return percent_text(lap.energy_used)
    if lap.fuel_used > 0:
        return percent_text(lap.fuel_used)
    return ""


def lap_stats(result: SessionResult, entry: Entry) -> list[dict[str, str]]:
    """Best, average & spread of clean laps (no pit lane, not first lap), theoretical best, top speed"""
    to_speed, symbol = speed_converter()
    clean = [lap.time for lap in entry.laps if lap.time > 0 and not lap.pit and lap.number > 1]
    stats = [tile(tr("Best Lap"), lap_text(entry.best_lap))]
    if len(clean) >= 2:
        stats.append(tile(tr("Average"), lap_text(statistics.fmean(clean))))
        stats.append(tile(tr("Consistency"), f"± {localized(f'{statistics.pstdev(clean):.3f}')} s"))
    sectors = rf.best_sectors((entry,))
    if all(sector > 0 for sector in sectors):
        stats.append(tile(tr("Theoretical Best"), lap_text(sum(sectors))))
    speeds = [lap.top_speed for lap in entry.laps if lap.top_speed > 0]
    if speeds:
        stats.append(tile(tr("Top Speed"), f"{to_speed(max(speeds)):.0f} {symbol}"))
    pits = sum(1 for lap in entry.laps if lap.pit)
    if pits:
        stats.append(tile(tr("Pit lane"), laps_text(pits)))
    return stats


def driver_options(result: SessionResult, class_filter: str) -> list[dict[str, str]]:
    """Cars to pick for laps: "P3  #7 Name" """
    return [{"key": str(index), "text": f"P{entry.position}  #{entry.number}  {entry.name}" if entry.number
             else f"P{entry.position}  {entry.name}"}
            for index, entry in filtered_entries(result, class_filter)]


# Positions chart
class ChartView(NamedTuple):
    """Plot size (px) & line widths the chart lines are built for"""

    width: float
    height: float
    thin: float
    thick: float
    wide: float


def positions_chart(result: SessionResult, class_filter: str) -> dict[str, Any]:
    """Position of each car at end of each lap (class position when a class is picked), grid at lap 0

    Series in classification order: {"key", "name", "number", "color", "player", "points": [[lap, place]],
    "places": place at each lap from grid (last one known, 0 if none yet)}.
    """
    entries = filtered_entries(result, class_filter)
    laps = max((lap.number for _, entry in entries for lap in entry.laps), default=0)
    if not entries or laps < 1:
        return {"laps": 0, "places": 0, "series": []}
    by_lap: dict[int, list[tuple[int, int]]] = {}  # lap: [(overall position, entry index)]
    for index, entry in entries:
        for lap in entry.laps:
            if lap.position > 0:
                by_lap.setdefault(lap.number, []).append((lap.position, index))
    places: dict[tuple[int, int], int] = {}  # (entry index, lap): shown place
    for number, cars in by_lap.items():
        for place, (_, index) in enumerate(sorted(cars), 1):
            places[(index, number)] = place
    series = []
    for index, entry in entries:
        grid = entry.class_grid if class_filter else entry.grid
        points = [[0, grid]] if grid > 0 else []
        points.extend([lap.number, places[(index, lap.number)]] for lap in entry.laps
                      if (index, lap.number) in places)
        series.append({
            "key": str(index),
            "name": entry.name,
            "number": entry.number,
            "color": class_color(entry.car_class),
            "player": entry.player,
            "points": points,
            "places": place_table(points, laps),
        })
    return {"laps": laps, "places": len(entries), "series": series}


def place_table(points: Sequence[Sequence[int]], laps: int) -> list[int]:
    """Place at each lap (0 to laps): last one known, 0 before first point (hovered car found without a scan)"""
    table = [0] * (laps + 1)
    place = following = 0
    for lap in range(laps + 1):
        while following < len(points) and points[following][0] <= lap:
            place = points[following][1]
            following += 1
        table[lap] = place
    return table


def chart_lines(chart: dict[str, Any], view: ChartView) -> list[dict[str, Vertices]]:
    """Line of each series as bands in plot pixels: "thin" (other cars), "thick" (picked or hovered), "wide"
    (player only), drawn at plot size of view (other sizes: scaled by QML until built again)"""
    laps, places = chart["laps"], chart["places"]
    lines = []
    for series in chart["series"]:
        points = series["points"]
        xs = [lap / laps * view.width for lap, _ in points] if laps > 0 else []
        ys = [(place - 1) / (places - 1) * view.height if places > 1 else view.height / 2 for _, place in points]
        across = normals(xs, ys)  # pixel space: same width along the line
        bands = {"thin": band(xs, ys, view.thin / 2, line_normals=across),
                 "thick": band(xs, ys, view.thick / 2, line_normals=across)}
        if series["player"]:
            bands["wide"] = band(xs, ys, view.wide / 2, line_normals=across)
        lines.append(bands)
    return lines


def lap_count(result: SessionResult) -> int:
    """Laps of every car: chart points of a race"""
    return sum(len(entry.laps) for entry in result.entries)


def series_points(chart: dict[str, Any]) -> int:
    return sum(len(series["points"]) for series in chart["series"])


class BuiltChart(NamedTuple):
    """Positions chart built in background: serial asked, series with points, lines for view (None if no view)"""

    serial: int
    series: dict[str, Any]
    view: ChartView | None
    lines: list[dict[str, Vertices]] | None


def build_chart(serial: int, result: SessionResult, class_filter: str, view: ChartView | None) -> BuiltChart:
    """Positions chart & its lines (background: long races)"""
    chart = positions_chart(result, class_filter)
    lines = chart_lines(chart, view) if view is not None and chart["series"] else None
    return BuiltChart(serial, chart, view, lines)


# Events
def event_mine(event: Event, names: set[str]) -> bool:
    return event.driver in names or event.other in names


def contact_title(event: Event) -> str:
    other = tr("Wall") if event.other == rf.IMMOVABLE or not event.other else event.other
    return f"{event.driver}  ↔  {other}"


def merged_contacts(events: Iterable[Event]) -> list[Event]:
    """Events with contacts reported by both cars (and repeated) shown once"""
    merged: list[Event] = []
    last: dict[tuple[str, str], int] = {}  # pair: index in merged
    for event in events:
        if event.kind != "contact":
            merged.append(event)
            continue
        other = event.other if event.other and event.other != rf.IMMOVABLE else ""
        pair = (min(event.driver, other), max(event.driver, other)) if other else (event.driver, "")
        index = last.get(pair)
        if index is not None and event.time - merged[index].time <= rf.SAME_CONTACT:
            if event.value > merged[index].value:
                merged[index] = merged[index]._replace(value=event.value)
            continue
        last[pair] = len(merged)
        merged.append(event)
    return merged


def event_rows(result: SessionResult, kind: str, only: set[str], highlight: set[str],
               merged: Sequence[Event] | None = None) -> list[dict[str, Any]]:
    """Session events, filtered by kind ("" every kind) and drivers (empty: everyone), events of highlight
    drivers (player) marked (merged: merged_contacts of session if known already)"""
    rows = []
    for number, event in enumerate(merged_contacts(result.events) if merged is None else merged):
        if kind and event.kind != kind:
            continue
        if only and not event_mine(event, only):
            continue
        mine = event_mine(event, highlight)
        if event.kind == "contact":
            title = contact_title(event)
            detail = f"{tr('Impact')} {event.value:.0f}"
        elif event.kind == "penalty":
            title = event.driver or tr("Penalty")
            reason = event.text.partition(" for ")[2].partition(".")[0].strip()
            seconds = f" {event.value:g} s" if event.value > 0 else ""
            detail = " · ".join(part for part in (f"{game_text(event.other)}{seconds}", game_text(reason)) if part)
        elif event.kind == "track_limits":
            title = event.driver
            detail = f"{game_text(event.other)} · {localized(f'{event.value:g}')} {tr('pts')}"
        else:
            sender, _, message = event.text.partition(": ")
            title, detail = sender, message
        rows.append({
            "key": str(number),
            "clock": calc.sec2sessiontime(event.time),
            "kind": event.kind,
            "glyph": EVENT_GLYPHS.get(event.kind, ""),
            "title": title,
            "detail": detail,
            "mine": mine,
        })
    return rows


def event_counts(result: SessionResult, merged: Sequence[Event] | None = None) -> list[int]:
    """Event count of each filter (all, contacts...)"""
    events = merged_contacts(result.events) if merged is None else merged
    counts = [len(events)]
    counts.extend(sum(1 for event in events if event.kind == kind) for kind in EVENT_FILTERS[1:])
    return counts


class RaceResultsBackend(QObject):
    """Race results page state & actions"""

    loadingChanged = Signal()
    sessionsChanged = Signal()  # list rows, counts, folders
    filterChanged = Signal()
    selectionChanged = Signal()  # session picked: header, tiles, classes
    classificationChanged = Signal()
    driverChanged = Signal()  # car picked for laps (and highlighted)
    lapsChanged = Signal()
    chartChanged = Signal()
    eventsChanged = Signal()
    tabChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        settings = load_page_settings()
        self.custom_folder = str(settings.get("folder", ""))
        self.kind_filter = self._index(settings.get("kind"), len(KIND_FILTERS))
        self.hide_empty = bool(settings.get("hide_empty", True))
        self.tab = self._index(settings.get("tab"), len(TABS))
        self.event_filter = self._index(settings.get("event_filter"), len(EVENT_FILTERS))
        self.event_mine = bool(settings.get("event_mine", False))
        self.search = ""
        self.folders: tuple[str, ...] = ()
        self.files: dict[str, tuple[FileStamp, SessionInfo | None]] = {}
        self.replays: dict[str, ri.ReplayFile] = {}  # replay of sessions (results path: replay)
        self.pending_path = ""  # session to show once files read (driver stats page)
        self.sessions: list[SessionInfo] = []
        self._infos: dict[str, SessionInfo] = {}  # session of path
        self.loading = False
        self.loaded_once = False
        self.selected_key = ""  # session picked in list
        self.shown_key = ""  # session shown (picked one being read meanwhile)
        self.reading = ""  # session picked being read in background
        self.result: SessionResult | None = None  # released while page hidden a while (shown again when read)
        self.kept: OrderedDict[str, tuple[FileStamp, SessionResult]] = OrderedDict()  # last sessions shown
        self.is_race = False
        self.class_filter = ""
        self.selected_entry = ""
        self.header: dict[str, Any] = {}
        self.tiles: list[dict[str, str]] = []
        self.classes: list[dict[str, Any]] = []
        self.lap_summary: list[dict[str, str]] = []
        self.lap_columns: dict[str, bool] = {"usage": False, "wear": False}
        self.drivers: list[dict[str, str]] = []
        self.driver_pictures: tuple[str, str] = ("", "")  # brand logo & car picture of car picked
        self.chart: dict[str, Any] = {"laps": 0, "places": 0, "series": []}
        self.chart_series: dict[str, Any] = self.chart  # with line points (chart has places & line keys)
        self.chart_view: ChartView | None = None
        self.counts: list[int] = [0] * len(EVENT_FILTERS)
        self.prefix = f"race_results_{id(self)}|"
        self._shown = False
        self._released = False
        self._pictures_stale = False  # logos fetched while hidden: rows built again once shown
        self.logos = LogoCache()  # car brand logos looked for once per name
        self._rows: dict[str, tuple[tuple, dict[str, Any]]] = {}  # session list row of path: built for, row
        self._texts: dict[str, tuple[SessionInfo, str]] = {}  # searched text of path: info, text
        self._events: tuple[SessionResult | None, list[Event], list[int]] = (None, [], [])  # merged & counts
        self._read_path = ""  # session read running (one at a time), "" if none
        self._chart_serial = 0  # chart asked last (charts built in background for long races)
        self._lines_serial = 0
        ri.hold_files()  # results files read once for driver stats page too
        self._session_model = DictListModel(SESSION_ROLES, self)
        self._classification_model = DictListModel(CLASSIFICATION_ROLES, self)
        self._lap_model = DictListModel(LAP_ROLES, self)
        self._event_model = DictListModel(EVENT_ROLES, self)
        self.request = GameRequest(self, (), self.received, self.load_failed)
        self._jobs = BackgroundJobs(self, "Race results")
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self.folder_changed)
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(RELOAD_DELAY_MS)
        self._reload_timer.timeout.connect(self.reload)
        self._release_timer = QTimer(self)
        self._release_timer.setSingleShot(True)
        self._release_timer.setInterval(RELEASE_DELAY_MS)
        self._release_timer.timeout.connect(self.release_results)
        self._read_timer = QTimer(self)
        self._read_timer.setSingleShot(True)
        self._read_timer.setInterval(READ_DELAY_MS)
        self._read_timer.timeout.connect(self.start_read)
        notifier().changed.connect(self.pictures_changed)

    @staticmethod
    def _index(value: Any, count: int) -> int:
        return value if isinstance(value, int) and 0 <= value < count else 0

    # Page
    def page_shown(self):
        """Results read at once, again when folder changes while shown"""
        self._shown = True
        self._release_timer.stop()
        self.reload()

    def page_hidden(self):
        self._shown = False
        self._reload_timer.stop()
        self.watch(())
        self._release_timer.start()

    def release(self):
        self.page_hidden()
        self._release_timer.stop()
        self.release_results()
        if not self._released:
            self._released = True
            ri.release_files()

    @Slot()
    def release_results(self):
        """Full results released (page hidden a while): rows kept as they are, session read again once shown"""
        self.kept.clear()
        self.result = None
        self.reading = ""
        self._read_timer.stop()
        self._events = (None, [], [])
        self._chart_serial += 1  # chart being built dropped
        self._lines_serial += 1
        VertexStore.remove_prefix(self.prefix)

    def save_settings(self):
        save_page_settings({
            "folder": self.custom_folder, "kind": self.kind_filter, "hide_empty": self.hide_empty,
            "tab": self.tab, "event_filter": self.event_filter, "event_mine": self.event_mine,
        })

    def watch(self, folders: Iterable[str]):
        watched = set(self._watcher.directories())
        wanted = {folder for folder in folders if os.path.isdir(folder)}
        if watched - wanted:
            self._watcher.removePaths(sorted(watched - wanted))
        if wanted - watched:
            self._watcher.addPaths(sorted(wanted - watched))

    @Slot()
    def pictures_changed(self):
        """Logos & pictures fetched from game meanwhile: rows built again, views told only what changed
        (page hidden: once shown)"""
        if not self._shown:
            self._pictures_stale = True
            return
        self._pictures_stale = False
        if self.sessions:
            self._rows = {}  # logos fetched or made meanwhile: rows built again
            self.refresh_list(always=False)
        if self.result is not None:
            header = self.session_header(self.result)
            if header != self.header:
                self.header = header
                self.selectionChanged.emit()
            self.refresh_classification(keep_rows=True)
            entry = self.entry()
            pictures = (self.logos.brand(entry.vehicle, entry.car), car_picture_url(entry.vehicle)) if entry else ("", "")
            if pictures != self.driver_pictures:
                self.driver_pictures = pictures
                self.driverChanged.emit()

    # Reading
    @Slot()
    def reload(self):
        """Read results files again (changed ones only)"""
        folders = rf.results_folders(self.custom_folder)
        known = dict(self.files) if folders == self.folders else {}
        if self.request.start(lambda: load_results(folders, known)):
            self.loading = True
            self.loadingChanged.emit()
        else:  # still reading: read again after
            self._reload_timer.start()

    def folder_changed(self, _path: str):
        if self._shown:
            self._reload_timer.start()  # game writes file in several steps

    def load_failed(self):
        """Reading ended by an unexpected error (logged): page stops waiting"""
        self.loading = False
        self.loadingChanged.emit()
        if self._pictures_stale:
            self.pictures_changed()

    def received(self, loaded: Loaded):
        newest_selected = bool(self.sessions) and self.selected_key == self.sessions[0].path
        self.loading = False
        self.loaded_once = True
        self._pictures_stale = False  # rows & session built again below
        self.folders = loaded.folders
        self.files = loaded.files
        self.replays = loaded.replays
        self.sessions = sorted((info for _, info in loaded.files.values() if info is not None),
                               key=lambda info: (info.time, info.path), reverse=True)
        for path, (stamp, result) in loaded.full.items():  # newest last: kept longest
            self.keep(path, stamp, result)
        for path in [path for path, (stamp, _) in self.kept.items() if self.stamp_of(path) != stamp]:
            del self.kept[path]  # file changed or gone
        self._rows = {path: row for path, row in self._rows.items() if path in self.files}
        self._texts = {path: text for path, text in self._texts.items() if path in self.files}
        self._infos = {info.path: info for info in self.sessions}
        if self._shown:
            self.watch(self.folders)
        self.loadingChanged.emit()
        self.refresh_list()
        if self.pending_path:
            path, self.pending_path = self.pending_path, ""
            if self.show_path(path):
                return
        shown = self.shown_sessions()
        keys = {info.path for info in shown}
        if newest_selected and shown:  # new session ended while newest one was shown: show new one
            self.select(shown[0].path)
        elif self.selected_key in keys:
            self.select(self.selected_key, force=True)  # file may have changed
        elif shown:
            self.select(shown[0].path)
        else:
            self.select("")

    def stamp_of(self, path: str) -> FileStamp | None:
        known = self.files.get(path)
        return known[0] if known is not None else None

    def keep(self, path: str, stamp: FileStamp, result: SessionResult):
        """Full results of a session kept (last ones shown only)"""
        self.kept[path] = (stamp, result)
        self.kept.move_to_end(path)
        while len(self.kept) > KEPT_RESULTS:
            self.kept.popitem(last=False)

    def kept_result(self, path: str) -> SessionResult | None:
        """Full results kept of a session, None if not kept or file changed since"""
        kept = self.kept.get(path)
        if kept is None or kept[0] != self.stamp_of(path):
            return None
        self.kept.move_to_end(path)
        return kept[1]

    def session_text(self, info: SessionInfo) -> str:
        """Searched text of session, made once per file read"""
        known = self._texts.get(info.path)
        if known is None or known[0] is not info:
            known = self._texts[info.path] = (info, session_text(info))
        return known[1]

    def shown_sessions(self) -> list[SessionInfo]:
        kind = KIND_FILTERS[self.kind_filter]
        words = [word for word in self.search.casefold().split() if word]
        return [info for info in self.sessions
                if session_matches(info, kind, words, self.hide_empty, self.session_text(info) if words else "")]

    def refresh_list(self, always: bool = True):
        """List rows, sessionsChanged told always (counts, folders) or only when rows changed

        Rows built once per file read, day & logos (typing a search only filters them).
        """
        today = QDate.currentDate()
        light = light_theme()
        newest = self.sessions[0].path if self.sessions else ""
        rows = []
        for info in self.shown_sessions():
            built_for = (info, today.toJulianDay(), light, info.path == newest, info.path in self.replays)
            known = self._rows.get(info.path)
            if known is None or known[0] != built_for:
                logo = self.logos.track(info.track, info.venue) or (self.logos.track(info.course) if info.course else "")
                known = self._rows[info.path] = (built_for, session_row(info, today, built_for[3], built_for[4], logo))
            rows.append(known[1])
        changed = self._session_model.sync(rows)
        if changed or always:
            self.sessionsChanged.emit()

    # Session list
    @Property(QObject, constant=True)
    def sessionModel(self) -> QObject:
        return self._session_model

    @Property(bool, notify=loadingChanged)
    def busy(self) -> bool:
        return self.loading

    @Property(bool, notify=loadingChanged)
    def loaded(self) -> bool:
        return self.loaded_once

    @Property(int, notify=sessionsChanged)
    def sessionCount(self) -> int:
        return len(self.sessions)

    @Property(int, notify=sessionsChanged)
    def shownCount(self) -> int:
        return len(self._session_model.rows)

    @Property(str, notify=sessionsChanged)
    def folderText(self) -> str:
        """Folders read, one per line, "" if none found"""
        return "\n".join(self.folders)

    @Property(bool, notify=sessionsChanged)
    def customFolder(self) -> bool:
        return bool(self.custom_folder)

    @Property(int, notify=filterChanged)
    def kindFilter(self) -> int:
        return self.kind_filter

    @Property(bool, notify=filterChanged)
    def hideEmpty(self) -> bool:
        return self.hide_empty

    @Property(str, notify=filterChanged)
    def searchText(self) -> str:
        return self.search

    @Slot(int)
    def setKindFilter(self, index: int):
        if 0 <= index < len(KIND_FILTERS) and index != self.kind_filter:
            self.kind_filter = index
            self.filter_changed()

    @Slot(bool)
    def setHideEmpty(self, hide: bool):
        if hide != self.hide_empty:
            self.hide_empty = hide
            self.filter_changed()

    @Slot(str)
    def setSearch(self, text: str):
        if text != self.search:
            self.search = text
            self.filter_changed(save=False)

    def filter_changed(self, save: bool = True):
        if save:
            self.save_settings()
        self.filterChanged.emit()
        self.refresh_list()
        shown = self._session_model.rows
        if shown and self._session_model.index_of(self.selected_key) < 0:
            self.select(shown[0]["key"])

    @Slot(int, result=int)
    def moveSelection(self, step: int) -> int:
        """Session before / after selected one in list (Up / Down keys), its row index"""
        rows = self._session_model.rows
        if not rows:
            return -1
        current = self._session_model.index_of(self.selected_key) if self.selected_key else -1
        target = min(max(current + step, 0), len(rows) - 1) if current >= 0 else 0
        self.select(rows[target]["key"])
        return target

    @Slot()
    def openFolder(self):
        if self.folders:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.folders[0]))

    @Slot()
    def chooseFolder(self):
        start = self.folders[0] if self.folders else os.path.expanduser("~")
        parent = self.parent()
        folder = QFileDialog.getExistingDirectory(parent if isinstance(parent, QWidget) else None,
                                                  tr("Results Folder"), start)
        if folder:
            self.custom_folder = os.path.normpath(folder)
            self.save_settings()
            self.reload()

    @Slot()
    def resetFolder(self):
        """Back to game results folders found automatically"""
        if self.custom_folder:
            self.custom_folder = ""
            self.save_settings()
            self.reload()

    def open_path(self, path: str):
        """Session of results file shown (driver stats page): at once if read, else once files are read"""
        if self.loaded_once and not self.loading and self.show_path(path):
            return
        self.pending_path = path
        if not self.loading:
            self.reload()

    def show_path(self, path: str) -> bool:
        """Session of results file shown, filters that hide it cleared, False if not a session of the list"""
        wanted = os.path.normcase(os.path.normpath(path))
        info = next((info for info in self.sessions if os.path.normcase(os.path.normpath(info.path)) == wanted), None)
        if info is None:
            return False
        if info not in self.shown_sessions():
            self.kind_filter, self.search, self.hide_empty = 0, "", False
            self.filter_changed(save=False)  # filters of user kept for next time
        self.select(info.path)
        return True

    def session_header(self, result: SessionResult) -> dict[str, Any]:
        """Header of session, with its replay (LMU: watched from game replays page)"""
        replay = self.replays.get(result.path)
        return {**session_header(result), "replay": replay.name if replay is not None and result.game == "LMU" else ""}

    @Slot()
    def watchReplay(self):
        """Replay of session shown opened in game, from game replays page (game state, confirmation, controls)"""
        name = self.header.get("replay", "")
        if not name:
            return
        from ..tools_view import open_tool

        page = open_tool("game_replays.GameReplays", self.parent())
        backend = getattr(page, "backend", None)
        if backend is not None:
            backend.watch_named(name)

    # Selected session
    @Property(str, notify=selectionChanged)
    def selectedKey(self) -> str:
        return self.selected_key

    @Property(bool, notify=selectionChanged)
    def hasSession(self) -> bool:
        return bool(self.shown_key)

    @Property(dict, notify=selectionChanged)
    def sessionHeader(self) -> dict:
        return self.header

    @Property(list, notify=selectionChanged)
    def summaryTiles(self) -> list:
        return self.tiles

    @Property(list, notify=selectionChanged)
    def classChips(self) -> list:
        return self.classes

    @Property(str, notify=classificationChanged)
    def classFilter(self) -> str:
        return self.class_filter

    @Property(bool, notify=selectionChanged)
    def isRace(self) -> bool:
        return self.is_race

    @Slot(str)
    def select(self, key: str, force: bool = False):
        """Session shown: at once if kept, else once read in background (session shown before stays meanwhile)"""
        if key == self.selected_key and not force and (self.result is not None or not key or self.reading == key):
            return
        info = self._infos.get(key)
        stamp = self.stamp_of(key)
        if info is None or stamp is None:
            self.show_session("", None)
            return
        result = self.kept_result(key)
        if result is not None:
            self.show_session(key, result)
            return
        self.reading = key
        if key != self.selected_key:
            self.selected_key = key
            self.selectionChanged.emit()
        self._read_timer.start()  # selection moving (keys held): read once it settles

    @Slot()
    def start_read(self):
        """Session picked read in background, once the running read (if any) is over: one read at a time"""
        key = self.reading
        if not key or self._read_path or self._released:
            return
        info, stamp = self._infos.get(key), self.stamp_of(key)
        if info is None or stamp is None:
            return
        self._read_path = key
        names = info.player_names
        self._jobs.run("read session", lambda: read_session(key, stamp, names), self.session_read,
                       self.session_failed)

    def session_read(self, answer: tuple[str, FileStamp, SessionResult]):
        path, stamp, result = answer
        self._read_path = ""
        if self.stamp_of(path) == stamp and (self._shown or path == self.reading):
            self.keep(path, stamp, result)  # session passed by kept too: shown at once if picked again
        if path != self.reading:  # other session picked meanwhile
            if self.reading and not self._read_timer.isActive():
                self.start_read()
            return
        self.reading = ""
        self.show_session(path, result)

    def session_failed(self, error: BaseException):
        """File gone or being written (read again once folder changes), not a results file, or bug"""
        path, self._read_path = self._read_path or self.reading, ""
        if isinstance(error, OSError):
            logger.debug("RACE RESULTS: %s not read: %s", path, error)
        elif isinstance(error, ValueError):  # not a results file (or written meanwhile)
            logger.info("RACE RESULTS: %s not read: %s", path, error)
        else:
            logger.warning("RACE RESULTS: %s not read", path, exc_info=(type(error), error, error.__traceback__))
        if not self.reading:
            return
        if path == self.reading:
            self.reading = ""
            self.show_session("", None)
        elif not self._read_timer.isActive():
            self.start_read()  # other session picked meanwhile

    def show_session(self, key: str, result: SessionResult | None):
        self.reading = ""
        changed_session = key != self.shown_key
        self.selected_key = self.shown_key = key if result is not None else ""
        self.result = result
        self.is_race = result is not None and result.kind == "Race"
        if changed_session or result is None:
            self.class_filter = ""
            player = result.player_entry if result is not None else None
            if result is None:
                self.selected_entry = ""
            elif player is not None:
                self.selected_entry = str(result.entries.index(player))
            else:
                self.selected_entry = "0" if result.entries else ""
        elif result is not None and self.class_filter not in result.classes:
            self.class_filter = ""
        if result is None:
            self.header, self.tiles, self.classes = {}, [], []
            self._events = (None, [], [])
        else:
            self.header = self.session_header(result)
            self.tiles = summary_tiles(result)
            self.classes = class_chips(result)
            if not self.selected_entry or int(self.selected_entry) >= len(result.entries):
                self.selected_entry = "0" if result.entries else ""
        self.selectionChanged.emit()
        self.refresh_session()

    def refresh_session(self):
        self.refresh_classification()
        self.refresh_driver()
        self.refresh_chart()
        self.refresh_events()

    @Slot(str)
    def setClassFilter(self, name: str):
        if name == self.class_filter or (name and (self.result is None or name not in self.result.classes)):
            return
        self.class_filter = name
        if self.result is not None and self.selected_entry:
            entry = self.result.entries[int(self.selected_entry)]
            if name and entry.car_class != name:  # car picked not in class: first car of class
                first = filtered_entries(self.result, name)
                self.selected_entry = str(first[0][0]) if first else ""
        self.refresh_session()

    def refresh_classification(self, keep_rows: bool = False):
        """Rows made again (reset: other session or filter), or rows changed in place (logos fetched)"""
        rows = classification_rows(self.result, self.class_filter, self.selected_entry, self.logos) if self.result else []
        if not keep_rows:
            self._classification_model.reset(rows)
            self.classificationChanged.emit()
        elif self._classification_model.sync(rows):
            self.classificationChanged.emit()

    @Property(QObject, constant=True)
    def classificationModel(self) -> QObject:
        return self._classification_model

    # Car picked: laps
    @Property(str, notify=driverChanged)
    def selectedEntry(self) -> str:
        return self.selected_entry

    @Property(dict, notify=driverChanged)
    def driverInfo(self) -> dict:
        entry = self.entry()
        if entry is None:
            return {}
        names = driver_names(entry)
        return {
            "name": entry.name,
            "number": entry.number,
            "team": entry.team or entry.vehicle,
            "car": entry.car,
            "carClass": entry.car_class,
            "color": class_color(entry.car_class),
            "drivers": ", ".join(names) if len(names) > 1 else "",
            "player": entry.player,
            "aids": entry.aids,
            "brandLogo": self.logos.brand(entry.vehicle, entry.car),
            "carPicture": car_picture_url(entry.vehicle),
        }

    @Property(list, notify=driverChanged)
    def driverOptions(self) -> list:
        return self.drivers

    @Property(int, notify=driverChanged)
    def driverIndex(self) -> int:
        return next((number for number, option in enumerate(self.drivers) if option["key"] == self.selected_entry), -1)

    @Property(list, notify=driverChanged)
    def lapSummary(self) -> list:
        return self.lap_summary

    @Property(QObject, constant=True)
    def lapModel(self) -> QObject:
        return self._lap_model

    @Property(dict, notify=lapsChanged)
    def lapColumns(self) -> dict:
        """Columns shown only when a lap has a value (own car): {"usage": bool, "wear": bool}"""
        return self.lap_columns

    @Property(str, notify=driverChanged)
    def speedUnit(self) -> str:
        return speed_converter()[1]

    def entry(self) -> Entry | None:
        if self.result is None or not self.selected_entry:
            return None
        index = int(self.selected_entry)
        return self.result.entries[index] if 0 <= index < len(self.result.entries) else None

    @Slot(str)
    def selectEntry(self, key: str):
        if key == self.selected_entry or self.result is None:
            return
        if not key.isdigit() or int(key) >= len(self.result.entries):
            return
        self.selected_entry = key
        self._classification_model.update_rows(lambda row: {"selected": row["key"] == key})
        self.refresh_driver()
        if self.event_mine:
            self.refresh_events()

    def refresh_driver(self):
        entry = self.entry()
        result = self.result
        self.drivers = driver_options(result, self.class_filter) if result is not None else []
        rows = lap_rows(result, entry) if entry is not None and result is not None else []
        self.lap_summary = lap_stats(result, entry) if entry is not None and result is not None else []
        self.lap_columns = {"usage": any(row["usageText"] for row in rows), "wear": any(row["wearText"] for row in rows)}
        self.driver_pictures = ((self.logos.brand(entry.vehicle, entry.car), car_picture_url(entry.vehicle))
                                if entry is not None else ("", ""))
        self._lap_model.reset(rows)
        self.driverChanged.emit()
        self.lapsChanged.emit()

    # Positions chart
    @Property(dict, notify=chartChanged)
    def positions(self) -> dict:
        return self.chart

    def refresh_chart(self):
        """Chart of session (QML: places table & line keys of each series), lines built for plot size

        Long races (endurance: thousands of laps) built in background, chart empty meanwhile.
        """
        result = self.result
        self._chart_serial += 1
        if result is None or result.kind != "Race" or lap_count(result) <= SYNC_CHART_POINTS:
            self.set_chart(positions_chart(result, self.class_filter) if result is not None and result.kind == "Race"
                           else {"laps": 0, "places": 0, "series": []})
            return
        serial, class_filter, view = self._chart_serial, self.class_filter, self.chart_view
        self.set_chart({"laps": 0, "places": 0, "series": []})
        self._jobs.run("positions chart", lambda: build_chart(serial, result, class_filter, view), self.chart_built,
                       key="chart")

    def chart_built(self, built: BuiltChart):
        if built.serial != self._chart_serial:
            return  # other session or class picked meanwhile
        self.set_chart(built.series, built.lines if built.view == self.chart_view else None)

    def set_chart(self, chart_series: dict[str, Any], lines: list[dict[str, Vertices]] | None = None):
        """Chart shown: series with points, lines built for chart view already (else built here)"""
        self.chart_series = chart_series
        chart = dict(self.chart_series)
        chart["series"] = [{
            "key": series["key"], "name": series["name"], "number": series["number"], "color": series["color"],
            "player": series["player"], "places": series["places"],
            "last": series["points"][-1] if series["points"] else [],
            "thin": f"{self.prefix}thin{number}", "thick": f"{self.prefix}thick{number}",
            "wide": f"{self.prefix}wide{number}" if series["player"] else "",
        } for number, series in enumerate(self.chart_series["series"])]
        self.chart = chart
        self.build_chart_lines(lines)
        self.chartChanged.emit()

    @Slot(float, float, float, float, float)
    def setChartView(self, width: float, height: float, thin: float, thick: float, wide: float):
        """Plot size & line widths of positions chart settled (resize, zoom): lines built again for them"""
        view = ChartView(width, height, thin, thick, wide)
        if view != self.chart_view and width >= 1 and height >= 1:
            self.chart_view = view
            self.build_chart_lines()

    def build_chart_lines(self, lines: list[dict[str, Vertices]] | None = None):
        """Lines of chart for chart view: at once, in background for long races (lines kept meanwhile:
        scaled by QML)"""
        view = self.chart_view
        self._lines_serial += 1
        if view is None or not self.chart_series["series"]:
            VertexStore.remove_prefix(self.prefix)
            return
        if lines is None:
            if series_points(self.chart_series) > SYNC_CHART_POINTS:
                serial, chart_series = self._lines_serial, self.chart_series
                self._jobs.run("chart lines", lambda: (serial, view, chart_lines(chart_series, view)),
                               self.lines_built, key="chart lines")
                return
            lines = chart_lines(self.chart_series, view)
        self.store_lines(lines)

    def lines_built(self, built: tuple[int, ChartView, list[dict[str, Vertices]]]):
        serial, view, lines = built
        if serial == self._lines_serial and view == self.chart_view:
            self.store_lines(lines)

    def store_lines(self, lines: list[dict[str, Vertices]]):
        keys = []
        for series, bands in zip(self.chart["series"], lines):
            for kind, vertices in bands.items():
                VertexStore.set(series[kind], vertices)
                keys.append(series[kind])
        VertexStore.retain(self.prefix, keys)

    # Events
    @Property(QObject, constant=True)
    def eventModel(self) -> QObject:
        return self._event_model

    @Property(int, notify=eventsChanged)
    def eventKind(self) -> int:
        """Event filter: index of EVENT_FILTERS"""
        return self.event_filter

    @Property(bool, notify=eventsChanged)
    def eventMine(self) -> bool:
        return self.event_mine

    @Property(list, notify=eventsChanged)
    def eventCounts(self) -> list:
        return self.counts

    @Slot(int)
    def setEventKind(self, index: int):
        if 0 <= index < len(EVENT_FILTERS) and index != self.event_filter:
            self.event_filter = index
            self.save_settings()
            self.refresh_events()

    @Slot(bool)
    def setEventMine(self, mine: bool):
        if mine != self.event_mine:
            self.event_mine = mine
            self.save_settings()
            self.refresh_events()

    def refresh_events(self):
        result = self.result
        if result is None:
            self.counts = [0] * len(EVENT_FILTERS)
            self._event_model.reset([])
        else:
            entry = self.entry()
            only = set(driver_names(entry)) if self.event_mine and entry is not None else set()
            player = result.player_entry
            highlight = set(driver_names(player)) if player is not None else set()
            merged, self.counts = self.session_events(result)
            self._event_model.reset(event_rows(result, EVENT_FILTERS[self.event_filter], only, highlight, merged))
        self.eventsChanged.emit()

    def session_events(self, result: SessionResult) -> tuple[list[Event], list[int]]:
        """Events of session with contacts merged & count of each filter, made once per session shown"""
        if self._events[0] is not result:
            merged = merged_contacts(result.events)
            self._events = (result, merged, event_counts(result, merged))
        return self._events[1], self._events[2]

    # Tabs
    @Property(int, notify=tabChanged)
    def tabIndex(self) -> int:
        return self.tab

    @Slot(int)
    def setTab(self, index: int):
        if 0 <= index < len(TABS) and index != self.tab:
            self.tab = index
            self.save_settings()
            self.tabChanged.emit()
