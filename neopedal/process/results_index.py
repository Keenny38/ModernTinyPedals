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
Session results of the game linked to driver stats history & game replays (no Qt: read in background)

Results files (results_file.py) are summed up to what the player did in each session: classification,
gap, incidents, game version. A driver stats history record (stint) is linked to the session it was driven
in by time: the latest session of same kind & track started before the stint ended, still running or ended
a short while before (the game writes the results file when the session ends, the stint is saved when the
player leaves the session).

The game saves the replay of a session next to its results: "UserData/Replays/<track> <R1|Q1|P1|W1> <n>.Vcr",
written 0 to 4 minutes after the results file (measured on LMU sessions): replay linked to the results file
of same session code & track written just before it.

Results files are parsed once for both pages (race results list, driver stats links): what each page needs
of a file (SessionInfo, ResultSummary) is kept by path & file stamp (see scan_results), released once no page
holds it (hold_files, release_files).
"""

from __future__ import annotations

import heapq
import logging
import os
import re
import threading
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from typing import NamedTuple

from . import results_file as rf
from .results_file import Entry, SessionResult

logger = logging.getLogger(__name__)

REPLAY_EXTENSION = ".Vcr"
REPLAYS_SUBFOLDER = os.path.join("UserData", "Replays")
# Replay written after its results file (seconds): measured 0 to 230 s, file times of copies may differ a bit
REPLAY_BEFORE = 60.0
REPLAY_AFTER = 900.0
# Stint saved when player leaves session: some time after results written (results screen, replay watched)
STINT_AFTER_END = 3600.0
STINT_BEFORE_START = 60.0  # clock & file times
# Driver stats history session (0 test day, 1 practice, 2 qualify, 3 warmup, 4 race): results session kind
HISTORY_KINDS = ("Practice", "Practice", "Qualifying", "Warmup", "Race")
SESSION_CODE = re.compile(r"(?P<code>[PQWR])\d*$", re.I)  # "...-70R1" -> R
REPLAY_NAME = re.compile(r"^(?P<track>.+?)\s+(?P<code>[PQWR])\d*\s+\d+$", re.I)  # "<track> R1 3"
VERSION = re.compile(r"^\s*v?(?P<major>\d+)\.(?P<minor>\d+)\s*$", re.I)


class ResultSummary(NamedTuple):
    """What the player did in a session (results file), None values never: 0 / "" when unknown"""

    path: str
    game: str  # "LMU", "rFactor 2", ""
    start: float  # session start (Unix time)
    end: float  # results file written (Unix time): session end
    kind: str  # "Practice", "Qualifying", "Warmup", "Race"
    code: str  # session letter of file name: "P", "Q", "W", "R"
    track: str  # event name (driver stats track key)
    venue: str
    game_version: str  # "1.42"
    setting: str  # "Multiplayer", "Race Weekend"...
    server: str
    cars: int
    class_cars: int  # cars of player class
    driver: str  # player name in results
    vehicle: str  # entry name (livery)
    car: str  # car model
    car_class: str
    position: int  # 0 if none
    class_position: int
    status: str  # "Finished Normally", "DNF", "DQ", "None"
    best_lap: float  # valid best lap (s), 0 if none
    laps: int  # laps completed
    gap_laps: int  # laps behind class leader (race)
    gap_time: float  # s behind class leader (race: finish, else best lap), -1 if unknown, 0 if leader
    contacts: int  # with cars
    impacts: int  # with objects
    penalties: int
    track_limits: float  # points at end of session


class ReplayFile(NamedTuple):
    """Replay saved by game"""

    name: str  # game replay name (file name without extension)
    path: str
    modified: float


class BestLapFix(NamedTuple):
    """Stats lap time completed from a results file: track, vehicle key, stat ("pb", "qb", "rb")"""

    track: str
    vehicle: str
    stat: str
    laptime: float
    current: float  # stats lap time now, 0 if none
    path: str  # results file
    time: float  # session end


class FileStamp(NamedTuple):
    size: int
    modified: float


class SessionInfo(NamedTuple):
    """What the race results session list (rows, filters) needs of a results file: full results read again
    when picked"""

    path: str
    time: float
    kind: str
    track: str
    venue: str
    course: str
    server: str
    setting: str
    most_laps: int
    cars: int
    class_count: int
    first_class: str  # class of best placed car
    player: Entry | None  # without laps
    player_names: tuple[str, ...]  # player names the file was read with


def session_info(result: SessionResult, player_names: tuple[str, ...] = ()) -> SessionInfo:
    player = result.player_entry
    return SessionInfo(
        result.path, result.time, result.kind, result.track, result.venue, result.course, result.server,
        result.setting, result.most_laps, len(result.entries), len(result.classes),
        result.entries[0].car_class if result.entries else "",
        player._replace(laps=(), swaps=()) if player is not None else None, player_names)


class ParsedFile(NamedTuple):
    """Results file read: list info (None if not a results file) & player session (None if player not in it)"""

    stamp: FileStamp
    names: tuple[str, ...]  # player names the file was read with
    info: SessionInfo | None
    summary: ResultSummary | None


class ScanResult(NamedTuple):
    """Results files of folders (path: parsed, folder order, newest name first), full results of the newest
    files read by this scan (oldest first, see scan_results keep_full)"""

    files: dict[str, ParsedFile]
    full: dict[str, tuple[FileStamp, SessionResult]]


_files: dict[str, ParsedFile] = {}  # path: file parsed (shared by pages)
_files_lock = threading.Lock()  # _files & generation, held briefly (UI thread never waits for a parse)
_scan_lock = threading.Lock()  # one scan at a time (worker threads): a file read once for both pages
_generation = 0  # files dropped: scan running meanwhile keeps nothing
_holders = 0  # pages using the files kept


def game_version_text(version: str) -> str:
    """Game version as players know it: "1.4200" & "1.420" -> "1.42", "1.4150" -> "1.415", others as written

    Results files write 4 decimals, LMU shared memory an integer (read as "1.420"), "unknown" -> "".
    """
    version = version.strip() if isinstance(version, str) else ""
    match = VERSION.match(version)
    if match is None:
        return "" if version.casefold() in ("", "unknown", "0") else version
    minor = match["minor"].rstrip("0").ljust(2, "0")
    return f"{int(match['major'])}.{minor}"


def session_code(path: str) -> str:
    """Session letter of results file name ("...-70R1.xml" -> "R"), "" if none"""
    match = SESSION_CODE.search(os.path.splitext(os.path.basename(path))[0])
    return match["code"].upper() if match else ""


def class_leader(result: SessionResult, entry: Entry) -> Entry:
    """Best placed car of class of entry (entries are by position), fastest one outside races"""
    same_class = [other for other in result.entries if other.car_class == entry.car_class] or [entry]
    if result.kind == "Race":
        return same_class[0]
    timed = [other for other in same_class if other.best_lap > 0]
    return min(timed, key=lambda other: other.best_lap) if timed else same_class[0]


def own_drivers(entry: Entry, names: Iterable[str]) -> set[str]:
    """Names the player drove car of entry under: profile names among drivers (team race), else entry driver"""
    wanted = {name.strip().casefold() for name in names if name and name.strip()}
    drivers = {entry.name, *(swap.driver for swap in entry.swaps)}
    own = {driver for driver in drivers if driver.casefold() in wanted}
    return own or {entry.name}


def own_best_lap(entry: Entry, drivers: set[str]) -> float:
    """Best lap driven by player (laps of teammates left out in team races), 0 if none"""
    teammates = [swap for swap in entry.swaps if swap.driver not in drivers]
    if not teammates:
        return entry.best_lap
    own = [swap for swap in entry.swaps if swap.driver in drivers]
    times = [lap.time for lap in entry.laps if lap.time > 0 and any(
        swap.start_lap <= lap.number <= swap.end_lap for swap in own)]
    return min(times, default=0.0)


def summarize(result: SessionResult, end: float, names: Iterable[str] = ()) -> ResultSummary | None:
    """Player session of results, None if player not found (spectator, other driver's file)

    Args:
        names: player names of game profile (own laps & incidents in team races).
    """
    entry = result.player_entry
    if entry is None:
        return None
    leader = class_leader(result, entry)
    gap_laps, gap_time = 0, -1.0
    if leader is entry:
        gap_time = 0.0
    elif result.kind == "Race":
        gap = rf.race_gap(entry, leader)
        gap_laps, gap_time = gap.laps, gap.time if not gap.laps else -1.0
    else:
        gap_time = rf.best_lap_gap(entry, leader)
    names = own_drivers(entry, names)
    contacts = rf.contact_counts(result.events)
    penalties = rf.penalty_counts(result.events)
    limits = rf.track_limit_points(result.events)
    return ResultSummary(
        path=result.path, game=result.game, start=result.time, end=end, kind=result.kind,
        code=session_code(result.path) or result.kind[:1], track=result.track, venue=result.venue,
        game_version=game_version_text(result.game_version), setting=result.setting, server=result.server,
        cars=len(result.entries), class_cars=sum(other.car_class == entry.car_class for other in result.entries),
        driver=entry.name, vehicle=entry.vehicle, car=entry.car, car_class=entry.car_class,
        position=entry.position, class_position=entry.class_position, status=entry.status,
        best_lap=own_best_lap(entry, names), laps=entry.laps_completed, gap_laps=gap_laps, gap_time=gap_time,
        contacts=sum(contacts.get(name, (0, 0))[0] for name in names),
        impacts=sum(contacts.get(name, (0, 0))[1] for name in names),
        penalties=sum(penalties.get(name, 0) for name in names),
        track_limits=max((limits.get(name, 0.0) for name in names), default=0.0),
    )


def player_names(folders: Iterable[str]) -> dict[str, tuple[str, ...]]:
    """Player names of each results folder: its game profile, else profiles of every game found"""
    found: list[str] = []
    for game_folder in rf.find_results_folders().values():
        found.extend(rf.profile_player_names(game_folder))
    return {folder: tuple(rf.profile_player_names(folder) or found) for folder in folders}


def file_stamp(path: str) -> FileStamp | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return FileStamp(stat.st_size, stat.st_mtime)


def parse_file(path: str, stamp: FileStamp, names: tuple[str, ...]
               ) -> tuple[ParsedFile, SessionResult | None, bool]:
    """Results file read: parsed file, full results (None if unreadable), whether kept (not when unreadable
    now: locked or being written, read again next time)"""
    try:
        result = rf.read_results(path, names)
        parsed = ParsedFile(stamp, names, session_info(result, names), summarize(result, stamp.modified, names))
    except OSError as error:  # being written or locked
        logger.debug("RESULTS INDEX: %s not read: %s", path, error)
        return ParsedFile(stamp, names, None, None), None, False
    except ValueError as error:  # not a results file (read again once changed)
        logger.debug("RESULTS INDEX: %s not read: %s", path, error)
        return ParsedFile(stamp, names, None, None), None, True
    return parsed, result, True


def scan_results(folders: Sequence[str], keep_full: int = 0) -> ScanResult:
    """Results files of folders, only new or changed ones read (worker thread)

    Files read are kept by path & stamp for every page (a hundred files read in about half a second, then only
    new ones), dropped once removed from their folder or no page holds them.

    Args:
        keep_full: full results of the newest files read by this scan handed over (page shows them next).
    """
    with _files_lock:
        generation = _generation  # files dropped while waiting or reading: nothing kept
    names = player_names(folders)
    files: dict[str, ParsedFile] = {}
    newest: list[tuple[float, str, FileStamp, SessionResult]] = []  # heap, oldest first
    with _scan_lock:
        for folder in folders:
            folder_names = names[folder]
            for path in rf.results_files(folder):
                stamp = file_stamp(path)
                if stamp is None:
                    continue
                with _files_lock:
                    cached = _files.get(path)
                if cached is not None and cached.stamp == stamp and cached.names == folder_names:
                    files[path] = cached
                    continue
                parsed, result, keep = parse_file(path, stamp, folder_names)
                files[path] = parsed
                if keep:
                    with _files_lock:
                        if generation == _generation:
                            _files[path] = parsed
                if result is not None and keep_full > 0:
                    heapq.heappush(newest, (result.time, path, stamp, result))
                    if len(newest) > keep_full:
                        heapq.heappop(newest)
        scanned = {os.path.dirname(os.path.join(folder, "_")) for folder in folders}
        with _files_lock:
            for path in [path for path in _files if path not in files and os.path.dirname(path) in scanned]:
                del _files[path]  # removed from its folder
    full = {path: (stamp, result) for _, path, stamp, result in sorted(newest, key=lambda item: item[:2])}
    return ScanResult(files, full)


def read_summaries(folders: Sequence[str]) -> list[ResultSummary]:
    """Player sessions of results files of folders, oldest first (files read once, again when changed)"""
    summaries = [parsed.summary for parsed in scan_results(folders).files.values() if parsed.summary is not None]
    summaries.sort(key=lambda summary: (summary.start, summary.path))
    return summaries


def hold_files() -> None:
    """Page uses results files kept (see release_files)"""
    global _holders
    with _files_lock:
        _holders += 1


def release_files() -> None:
    """Page closed: results files kept dropped once no page holds them (memory freed)"""
    global _holders
    with _files_lock:
        _holders = max(_holders - 1, 0)
        if _holders:
            return
    forget_summaries()


def forget_summaries() -> None:
    """Results files kept dropped, a scan running meanwhile keeps nothing (never waits for it)"""
    global _generation
    with _files_lock:
        _files.clear()
        _generation += 1


def kept_files() -> int:
    """Results files kept (tests)"""
    with _files_lock:
        return len(_files)


def same_track(name: str, summary: ResultSummary) -> bool:
    folded = name.strip().casefold()
    return bool(folded) and folded in (summary.track.casefold(), summary.venue.casefold())


def same_vehicle(vehicle: str, vehicle_class: str, summary: ResultSummary) -> bool:
    """Driver stats vehicle key (& class) can be player car of session: class, class & brand or vehicle name"""
    if vehicle_class and vehicle_class != summary.car_class:
        return False
    if vehicle in (summary.vehicle, summary.car_class):
        return True
    prefix = f"{summary.car_class} - "
    if vehicle.startswith(prefix):  # brand in car model or entry name
        brand = vehicle[len(prefix):].casefold()
        return brand in f"{summary.car} {summary.vehicle}".casefold()
    return not vehicle_class and vehicle.casefold() in summary.vehicle.casefold()


def match_session(time: float, session: int, track: str, summaries: Sequence[ResultSummary],
                  vehicle: str = "", vehicle_class: str = "") -> ResultSummary | None:
    """Session a driver stats stint was driven in, None if not found (no results file, other game...)

    Args:
        time: end of stint (record time).
        session: history session (0 test day, 1 practice, 2 qualify, 3 warmup, 4 race).
        track: driver stats track key (game track name: results event name).
        summaries: player sessions, oldest first.
        vehicle: driver stats vehicle key ("" if unknown): a stint of another car is not that session.
        vehicle_class: game class of vehicle ("" if unknown).
    """
    kind = HISTORY_KINDS[session] if 0 <= session < len(HISTORY_KINDS) else ""
    found = None
    for summary in summaries:
        if summary.start - STINT_BEFORE_START > time:
            break
        if summary.kind == kind and same_track(track, summary):
            found = summary  # latest session started before stint ended
    if found is None or time > found.end + STINT_AFTER_END:
        return None
    if vehicle and not same_vehicle(vehicle, vehicle_class, found):
        return None
    return found


class SessionMatcher:
    """match_session over many stints: sessions grouped by kind & track name (event or venue, casefolded),
    each group by start time (a stint found in log time, same result as match_session)

    Args:
        summaries: player sessions, oldest first (by start).
    """

    def __init__(self, summaries: Sequence[ResultSummary]):
        groups: dict[tuple[str, str], tuple[list[float], list[ResultSummary]]] = {}
        for summary in summaries:
            for name in {summary.track.casefold(), summary.venue.casefold()}:
                if name:
                    limits, found = groups.setdefault((summary.kind, name), ([], []))
                    limits.append(summary.start - STINT_BEFORE_START)  # as match_session compares
                    found.append(summary)
        self._groups = groups

    def match(self, time: float, session: int, track: str, vehicle: str = "", vehicle_class: str = ""
              ) -> ResultSummary | None:
        """Session a stint was driven in, see match_session"""
        kind = HISTORY_KINDS[session] if 0 <= session < len(HISTORY_KINDS) else ""
        group = self._groups.get((kind, track.strip().casefold()))
        if group is None:
            return None
        index = bisect_right(group[0], time) - 1  # latest session started before stint ended
        if index < 0:
            return None
        found = group[1][index]
        if time > found.end + STINT_AFTER_END:
            return None
        if vehicle and not same_vehicle(vehicle, vehicle_class, found):
            return None
        return found


def link_records(records: Iterable, summaries: Sequence[ResultSummary]
                 ) -> tuple[SessionMatcher, dict, dict[str, str]]:
    """Session of each driver stats history record (record: summary or None) & vehicle key of linked sessions
    (results path: vehicle key of latest record), matcher for records added since (worker thread)"""
    matcher = SessionMatcher(summaries)
    links: dict = {}
    linked: dict[str, str] = {}
    for record in records:
        if record in links:
            found = links[record]
        else:
            found = links[record] = matcher.match(record.time, record.session, record.track, record.vehicle,
                                                  record.vehicle_class)
        if found is not None:
            linked[found.path] = record.vehicle
    return matcher, links, linked


def replay_folder(results_folder: str) -> str:
    """Replay folder of game of results folder ("" if none)"""
    folder = os.path.join(rf.game_root(results_folder), REPLAYS_SUBFOLDER)
    return folder if os.path.isdir(folder) else ""


def list_replay_files(folder: str) -> list[ReplayFile]:
    """Replays of folder, empty if none or unreadable"""
    replays: list[ReplayFile] = []
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return replays
    for entry in entries:
        name, extension = os.path.splitext(entry.name)
        if extension.casefold() != REPLAY_EXTENSION.casefold():
            continue
        try:
            if entry.is_file():
                replays.append(ReplayFile(name, entry.path, entry.stat().st_mtime))
        except OSError:
            continue
    return replays


def replay_key(name: str) -> tuple[str, str]:
    """Track (casefolded) & session letter of replay name, ("", "") if not a game replay name"""
    match = REPLAY_NAME.match(name.strip())
    if match is None:
        return "", ""
    return match["track"].casefold(), match["code"].upper()


class ReplaySession(NamedTuple):
    """What links a session to its replay: results file, track names, session letter, file written"""

    path: str
    track: str
    venue: str
    code: str
    end: float


def replay_session(summary: ResultSummary) -> ReplaySession:
    return ReplaySession(summary.path, summary.track, summary.venue, summary.code, summary.end)


def match_replays(sessions: Iterable[ReplaySession], replays: Iterable[ReplayFile]) -> dict[str, ReplayFile]:
    """Replay of each session (results path: replay), each replay given to one session only (closest)"""
    by_key: dict[tuple[str, str], list[ReplayFile]] = {}
    for replay in replays:
        key = replay_key(replay.name)
        if key[0]:
            by_key.setdefault(key, []).append(replay)
    pairs = []
    for session in sessions:
        for track in {session.track.casefold(), session.venue.casefold()}:
            for replay in by_key.get((track, session.code), ()):
                delay = replay.modified - session.end
                if -REPLAY_BEFORE <= delay <= REPLAY_AFTER:
                    pairs.append((abs(delay), session.path, replay))
    found: dict[str, ReplayFile] = {}
    used: set[str] = set()
    for _, path, replay in sorted(pairs, key=lambda pair: pair[0]):
        if path not in found and replay.path not in used:
            found[path] = replay
            used.add(replay.path)
    return found


def session_replays(sessions: Iterable[ReplaySession]) -> dict[str, ReplayFile]:
    """Replay of each session of results folders, from replay folder of each game"""
    folders: dict[str, list[ReplaySession]] = {}
    for session in sessions:
        folder = replay_folder(os.path.dirname(session.path))
        if folder:
            folders.setdefault(folder, []).append(session)
    found: dict[str, ReplayFile] = {}
    for folder, sessions in folders.items():
        found.update(match_replays(sessions, list_replay_files(folder)))
    return found


def best_lap_stat(kind: str) -> tuple[str, ...]:
    """Driver stats lap times a session best lap counts for"""
    if kind == "Qualifying":
        return ("pb", "qb")
    if kind == "Race":
        return ("pb", "rb")
    return ("pb",)


def vehicle_key(summary: ResultSummary, vehicles: Iterable[str], classification: str,
                brands: dict[str, str]) -> str:
    """Driver stats vehicle key of player car among vehicles of track, "" if none matches

    Keys are made by stats module from game data (see module_stats.stats_keys): class, class & brand, or
    vehicle name. Brand: brands preset of vehicle, else a vehicle of track whose brand is in car model name.
    """
    vehicles = list(vehicles)
    if classification == "Class":
        return summary.car_class if summary.car_class in vehicles else ""
    if classification != "Class - Brand":
        return summary.vehicle if summary.vehicle in vehicles else ""
    brand = brands.get(summary.vehicle, "")
    if brand:
        wanted = f"{summary.car_class} - {brand}"
        return wanted if wanted in vehicles else ""
    prefix = f"{summary.car_class} - "
    found = [key for key in vehicles if key.startswith(prefix) and same_vehicle(key, "", summary)]
    return found[0] if len(found) == 1 else ""  # several brands in names: unknown


def best_lap_fixes(summaries: Iterable[ResultSummary], stats: dict, linked: dict[str, str], classification: str,
                   brands: dict[str, str]) -> list[BestLapFix]:
    """Lap times of stats missing or slower than best lap of an LMU results session (laps invalidated by
    track limits have no time in LMU results), fastest session of each lap time only

    Args:
        stats: driver stats file content (track: vehicle: stats).
        linked: vehicle key of results sessions linked to history records (results path: vehicle key).
        classification: stats module vehicle classification (vehicle keys of sessions not linked).
        brands: brands preset (vehicle name: brand).
    """
    best: dict[tuple[str, str, str], BestLapFix] = {}
    for summary in summaries:
        if summary.game != "LMU" or summary.best_lap <= 0:
            continue
        vehicles = stats.get(summary.track)
        if not isinstance(vehicles, dict):
            continue
        vehicle = linked.get(summary.path) or vehicle_key(summary, vehicles, classification, brands)
        data = vehicles.get(vehicle)
        if not isinstance(data, dict):
            continue
        for stat in best_lap_stat(summary.kind):
            current = data.get(stat, 0)
            current = float(current) if isinstance(current, (int, float)) and 0 < current < 99999 else 0.0
            if current and summary.best_lap >= current - 0.0005:
                continue
            key = (summary.track, vehicle, stat)
            known = best.get(key)
            if known is None or summary.best_lap < known.laptime:
                best[key] = BestLapFix(summary.track, vehicle, stat, summary.best_lap, current, summary.path,
                                       summary.end)
    return sorted(best.values(), key=lambda fix: (fix.track, fix.vehicle, ("pb", "qb", "rb").index(fix.stat)))
