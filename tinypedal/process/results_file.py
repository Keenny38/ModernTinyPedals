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
Session results files of the game (LMU & rFactor 2): "UserData/Log/Results/<date>-<n><P1|Q1|W1|R1>.xml"

Written by the game at the end of every session (practice, qualifying, warmup, race), online or offline:

    <rFactorXML><RaceResults>
        <Setting>Multiplayer | Race Weekend</Setting>, <ServerName>, <TrackVenue>, <TrackCourse>, <TrackEvent>,
        <TrackLength> (m), <GameVersion>, <RaceLaps>, <RaceTime> (minutes)...
        <Practice1 | Qualify | Warmup | Race>  (one session per file)
            <DateTime> (Unix time), <Laps> (2147483647: no lap limit), <Minutes>
            <Stream>  session events, "et" = session time (s)
                <Incident>Name(id) reported contact (strength) with another vehicle Other(id) | with Immovable
                <Penalty Driver= Penalty="Stop/Go" Time= Reason=>...
                <TrackLimits Driver= Lap= CurrentPoints= Resolution=>No Further Action | Warning | Invalid Lap...
                <ChatMessage>Name: text, <Score>, <Sector>, <Command>, <Sent>
            <MostLapsCompleted>
            <Driver>  one per car: Name, TeamName, VehName, CarType, CarClass, CarNumber, isPlayer (every human
                      online), GridPos, Position, ClassGridPos, ClassPosition, Laps, BestLapTime, FinishTime,
                      Pitstops, FinishStatus (Finished Normally, DNF, DQ, None), DNFReason, ControlAndAids,
                      <Swap startLap endLap>driver</Swap> (driver changes),
                      <Lap num p (position) et (session time at lap start) s1 s2 s3 topspeed (km/h) fcompound
                      pit="1" fuel fuelUsed ve veUsed (fractions, own car only) twfl...>lap time | --.----</Lap>

Files can end with a stray byte after the root element: anything after the closing root tag is ignored.
Player: "isPlayer" is set for every human online, so the player is found by name (game profile
UserData/player/Settings.JSON "Player Name"), else the only car marked as player (offline).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from typing import NamedTuple

logger = logging.getLogger(__name__)

RESULTS_EXTENSION = ".xml"
NO_LAP_LIMIT = 2147483647
MAX_FILE_SIZE = 64 << 20  # bytes, larger file is not a results file
SAME_CONTACT = 2.0  # seconds: contact reported by both cars (and repeated) counted once
SESSION_KINDS = (  # session element tag prefix, kind
    ("Practice", "Practice"),
    ("Qualify", "Qualifying"),
    ("Warmup", "Warmup"),
    ("Race", "Race"),
)
FINISHED = "Finished Normally"
IMMOVABLE = "Immovable"  # contact with track objects (walls, barriers)
GAME_FOLDERS = {  # game: Steam folder name
    "LMU": "Le Mans Ultimate",
    "rFactor 2": "rFactor 2",
}
RESULTS_SUBFOLDER = os.path.join("UserData", "Log", "Results")
PAGE_SETTINGS_FILE = "race_results.json"  # race results page settings (user config folder), folder chosen

DOCTYPE = re.compile(rb"<!DOCTYPE[^\[>]*(\[.*?\])?\s*>", re.S)
INVALID_CHARS = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")
ROOT_END = b"</rFactorXML>"
# "Name(12) reported contact (151.33) with another vehicle Other Name(11)", "... with Immovable"
CONTACT = re.compile(
    r"^(?P<driver>.+?)\(\d+\) reported contact \((?P<strength>[\d.]+)\) with "
    r"(?:another vehicle (?P<other>.+?)\(\d+\)|(?P<object>.+))$"
)


class Lap(NamedTuple):
    """Lap of a car"""

    number: int
    position: int  # overall position at end of lap
    time: float  # lap time (s), 0 if none (invalid, not completed)
    start: float  # session time at lap start (s), -1 if unknown
    sectors: tuple[float, float, float]  # sector times (s), 0 if none
    top_speed: float  # km/h
    compound: str  # front tyre compound name
    pit: bool  # car went through pit lane on this lap
    fuel: float  # fuel left (fraction) at end of lap, -1 if unknown (other cars)
    fuel_used: float
    energy: float  # virtual energy left (fraction), -1 if unknown
    energy_used: float
    wear: tuple[float, ...]  # tyre wear left (fraction) FL FR RL RR, empty if unknown


class Swap(NamedTuple):
    """Driver of a car between two laps (team races)"""

    driver: str
    start_lap: int
    end_lap: int


class Entry(NamedTuple):
    """Car of a session, as classified by the game"""

    name: str  # driver at end of session
    team: str
    vehicle: str  # entry name (livery)
    car: str  # car model
    car_class: str
    number: str
    grid: int  # 0 if unknown (practice)
    position: int
    class_grid: int
    class_position: int
    laps_completed: int
    best_lap: float  # s, 0 if none
    finish_time: float  # session time at finish (s), 0 if not finished
    pitstops: int
    status: str  # FINISHED, "DNF", "DQ", "None"
    dnf_reason: str
    human: bool  # driven by a person ("isPlayer" of game)
    player: bool  # driven by user of this computer
    aids: str  # ControlAndAids of last stint
    laps: tuple[Lap, ...]
    swaps: tuple[Swap, ...]


class Event(NamedTuple):
    """Event of session stream"""

    time: float  # session time (s)
    kind: str  # "contact", "penalty", "track_limits", "chat"
    driver: str  # driver concerned, "" if none (chat: sender name as written)
    other: str  # other car of contact, object hit ("Immovable"), penalty kind, track limits resolution
    text: str
    value: float = 0.0  # contact strength, penalty time (s), track limits points


class SessionResult(NamedTuple):
    """Results file content"""

    path: str
    game: str  # "LMU", "rFactor 2" or "" if unknown
    setting: str  # "Multiplayer", "Race Weekend"...
    server: str
    time: float  # session start, Unix time
    tag: str  # session element: "Practice1", "Qualify", "Race"...
    kind: str  # "Practice", "Qualifying", "Warmup", "Race"
    track: str  # event name if any, else venue
    venue: str
    course: str
    track_length: float  # m
    game_version: str
    minutes: int  # session length, 0 if none
    lap_limit: int  # 0 if none
    most_laps: int
    entries: tuple[Entry, ...]  # by position
    events: tuple[Event, ...]  # by time

    @property
    def player_entry(self) -> Entry | None:
        return next((entry for entry in self.entries if entry.player), None)

    @property
    def classes(self) -> list[str]:
        """Car classes, in order of best placed car"""
        seen: dict[str, None] = {}
        for entry in self.entries:
            seen.setdefault(entry.car_class, None)
        return list(seen)


def session_kind(tag: str) -> str:
    """Session kind of session element tag, "" if not a session"""
    for prefix, kind in SESSION_KINDS:
        number = tag[len(prefix):]
        if tag.startswith(prefix) and (not number or number.isdigit()):
            return kind
    return ""


def _text(element: ET.Element | None, name: str, default: str = "") -> str:
    if element is None:
        return default
    found = element.findtext(name)
    return found.strip() if found is not None else default


def _int(text: str | None, default: int = 0) -> int:
    try:
        return int(float(text)) if text else default
    except (TypeError, ValueError, OverflowError):
        return default


def _float(text: str | None, default: float = 0.0) -> float:
    """Number of text, default if none ("--.----": no time)"""
    try:
        value = float(text) if text else default
    except (TypeError, ValueError):
        return default
    return value if value == value and abs(value) != float("inf") else default


def _time(text: str | None) -> float:
    """Lap or sector time, 0 if none or not positive"""
    value = _float(text)
    return value if value > 0 else 0.0


def _compound(text: str | None) -> str:
    """Compound name of "0,Medium" """
    if not text:
        return ""
    return text.split(",", 1)[-1].strip()


def parse_lap(element: ET.Element) -> Lap:
    get = element.get
    wear = tuple(_float(get(key), -1.0) for key in ("twfl", "twfr", "twrl", "twrr"))
    return Lap(
        number=_int(get("num")),
        position=_int(get("p")),
        time=_time(element.text),
        start=_float(get("et"), -1.0),
        sectors=(_time(get("s1")), _time(get("s2")), _time(get("s3"))),
        top_speed=_float(get("topspeed")),
        compound=_compound(get("fcompound")),
        pit=get("pit") == "1",
        fuel=_float(get("fuel"), -1.0),
        fuel_used=_float(get("fuelUsed"), -1.0),
        energy=_float(get("ve"), -1.0),
        energy_used=_float(get("veUsed"), -1.0),
        wear=wear if min(wear) >= 0 else (),
    )


def parse_entry(element: ET.Element) -> Entry:
    laps = tuple(sorted((parse_lap(lap) for lap in element.iter("Lap")), key=lambda lap: lap.number))
    swaps = tuple(
        Swap((swap.text or "").strip(), _int(swap.get("startLap")), _int(swap.get("endLap")))
        for swap in element.iter("Swap")
    )
    aids = element.findall("ControlAndAids")
    return Entry(
        name=_text(element, "Name"),
        team=_text(element, "TeamName"),
        vehicle=_text(element, "VehName"),
        car=_text(element, "CarType"),
        car_class=_text(element, "CarClass"),
        number=_text(element, "CarNumber"),
        grid=_int(_text(element, "GridPos")),
        position=_int(_text(element, "Position")),
        class_grid=_int(_text(element, "ClassGridPos")),
        class_position=_int(_text(element, "ClassPosition")),
        laps_completed=_int(_text(element, "Laps")),
        best_lap=_time(_text(element, "BestLapTime")),
        finish_time=_time(_text(element, "FinishTime")),
        pitstops=_int(_text(element, "Pitstops")),
        status=_text(element, "FinishStatus", "None"),
        dnf_reason=_text(element, "DNFReason"),
        human=_text(element, "isPlayer") == "1",
        player=False,  # set once every car is known, see mark_player
        aids=(aids[-1].text or "").strip() if aids else "",
        laps=laps,
        swaps=swaps,
    )


def parse_events(stream: ET.Element | None) -> tuple[Event, ...]:
    """Contacts, penalties, track limits (other than no further action) & chat of session stream"""
    if stream is None:
        return ()
    events: list[Event] = []
    for element in stream:
        tag = element.tag
        text = (element.text or "").strip()
        time = _float(element.get("et"))
        if tag == "Incident":
            match = CONTACT.match(text)
            if match is None:
                continue
            other = match.group("other") or match.group("object") or ""
            events.append(Event(time, "contact", match.group("driver"), other.strip(), text,
                                _float(match.group("strength"))))
        elif tag == "Penalty":
            events.append(Event(time, "penalty", element.get("Driver", ""), element.get("Penalty", ""), text,
                                _float(element.get("Time"))))
        elif tag == "TrackLimits":
            if element.get("Resolution") == "7":  # no further action
                continue
            events.append(Event(time, "track_limits", element.get("Driver", ""), text, text,
                                _float(element.get("CurrentPoints"))))
        elif tag == "ChatMessage":
            sender, _, _ = text.partition(": ")
            events.append(Event(time, "chat", sender, "", text))
    events.sort(key=lambda event: event.time)
    return tuple(_drop_repeats(events))


def _drop_repeats(events: Iterable[Event]) -> Iterable[Event]:
    """Track limits are written twice in a row by the game"""
    last: Event | None = None
    for event in events:
        if event != last:
            yield event
        last = event


def mark_player(entries: list[Entry], player_names: Iterable[str]) -> list[Entry]:
    """Entry of user marked as player: driver name (or driver swap) of game profile, else the only human car"""
    names = {name.strip().casefold() for name in player_names if name and name.strip()}
    found = -1
    if names:
        for index, entry in enumerate(entries):
            drivers = {entry.name.casefold(), *(swap.driver.casefold() for swap in entry.swaps)}
            if drivers & names:
                found = index
                break
    if found < 0:
        humans = [index for index, entry in enumerate(entries) if entry.human]
        if len(humans) == 1:
            found = humans[0]
    if found >= 0:
        entries[found] = entries[found]._replace(player=True)
    return entries


def entry_order(entry: Entry) -> tuple[int, int]:
    """Classification order: position, unclassified (0) last"""
    return (entry.position if entry.position > 0 else 1 << 30, entry.class_position)


def parse_results(data: bytes, path: str = "", player_names: Iterable[str] = ()) -> SessionResult:
    """Results file content

    Raises:
        ValueError: not a results file (or not complete yet: game still writing it).
    """
    data = DOCTYPE.sub(b"", data, count=1)
    end = data.rfind(ROOT_END)
    if end < 0:
        raise ValueError("no results root element")
    data = INVALID_CHARS.sub(b"", data[:end + len(ROOT_END)])
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError(f"invalid results file: {error}") from error
    results = root.find("RaceResults")
    if results is None:
        raise ValueError("no RaceResults element")
    session = next((child for child in results if session_kind(child.tag)), None)
    if session is None:
        raise ValueError("no session element")
    entries = mark_player([parse_entry(driver) for driver in session.findall("Driver")], player_names)
    entries.sort(key=entry_order)
    venue = _text(results, "TrackVenue")
    event_name = _text(results, "TrackEvent")
    lap_limit = _int(_text(session, "Laps"))
    return SessionResult(
        path=path,
        game=game_of_path(path),
        setting=_text(results, "Setting"),
        server=_text(results, "ServerName"),
        time=_float(_text(session, "DateTime")) or _float(_text(results, "DateTime")),
        tag=session.tag,
        kind=session_kind(session.tag),
        track=event_name or venue,
        venue=venue,
        course=_text(results, "TrackCourse"),
        track_length=_float(_text(results, "TrackLength")),
        game_version=_text(results, "GameVersion"),
        minutes=_int(_text(session, "Minutes")),
        lap_limit=lap_limit if 0 < lap_limit < NO_LAP_LIMIT else 0,
        most_laps=_int(_text(session, "MostLapsCompleted")),
        entries=tuple(entries),
        events=parse_events(session.find("Stream")),
    )


def read_results(path: str, player_names: Iterable[str] = ()) -> SessionResult:
    """Results file content

    Raises:
        OSError: file not readable.
        ValueError: not a results file.
    """
    if os.path.getsize(path) > MAX_FILE_SIZE:
        raise ValueError("file too large")
    with open(path, "rb") as file:
        data = file.read()
    return parse_results(data, path, player_names)


def is_results_file(name: str) -> bool:
    """Results file name: "2026_10_05_22_34_33-70R1.xml" (game templates & other files excluded)"""
    stem, extension = os.path.splitext(os.path.basename(name))
    return extension.lower() == RESULTS_EXTENSION and stem[:4].isdigit()


def results_files(folder: str) -> list[str]:
    """Results files of folder, newest name first, empty if folder not readable"""
    try:
        names = [entry.name for entry in os.scandir(folder) if entry.is_file() and is_results_file(entry.name)]
    except OSError:
        return []
    return [os.path.join(folder, name) for name in sorted(names, reverse=True)]


# Game folders
def game_of_path(path: str) -> str:
    """Game of results file path (game install folder name), "" if unknown"""
    parts = {part.casefold() for part in re.split(r"[\\/]", os.path.abspath(path))} if path else set()
    for game, folder in GAME_FOLDERS.items():
        if folder.casefold() in parts:
            return game
    return ""


def game_root(results_folder: str) -> str:
    """Game folder of results folder (".../UserData/Log/Results" -> "...")"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.normpath(results_folder))))


def profile_player_names(results_folder: str) -> list[str]:
    """Driver name & nickname of game profile (UserData/player/Settings.JSON), empty if not found"""
    path = os.path.join(game_root(results_folder), "UserData", "player", "Settings.JSON")
    try:
        with open(path, encoding="utf-8", errors="replace") as file:
            profile = json.load(file)
    except (OSError, ValueError):
        return []
    driver = profile.get("DRIVER") if isinstance(profile, dict) else None
    if not isinstance(driver, dict):
        return []
    names = [driver.get("Player Name"), driver.get("Player Nick")]
    return [name.strip() for name in names if isinstance(name, str) and name.strip()]


def steam_folder() -> str:
    """Steam install folder, "" if unknown"""
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                return os.path.normpath(str(winreg.QueryValueEx(key, "SteamPath")[0]))
        except OSError:
            return os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"), "Steam")
    candidates = ("~/.steam/steam", "~/.local/share/Steam", "~/.var/app/com.valvesoftware.Steam/.local/share/Steam")
    for candidate in candidates:
        path = os.path.expanduser(candidate)
        if os.path.isdir(path):
            return path
    return ""


LIBRARY_PATH = re.compile(r'^\s*"path"\s+"(?P<path>(?:[^"\\]|\\.)*)"', re.M)


def steam_libraries(steam: str) -> list[str]:
    """Steam library folders (libraryfolders.vdf), Steam folder first"""
    libraries = [steam] if steam else []
    try:
        with open(os.path.join(steam, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="replace") as file:
            content = file.read()
    except OSError:
        return libraries
    for match in LIBRARY_PATH.finditer(content):
        path = os.path.normpath(match.group("path").replace("\\\\", "\\"))
        if path not in libraries:
            libraries.append(path)
    return libraries


def find_results_folders(libraries: Iterable[str] | None = None) -> dict[str, str]:
    """Results folder of each game found in Steam libraries: {game: folder}"""
    if libraries is None:
        libraries = steam_libraries(steam_folder())
    found: dict[str, str] = {}
    for library in libraries:
        for game, folder in GAME_FOLDERS.items():
            path = os.path.join(library, "steamapps", "common", folder, RESULTS_SUBFOLDER)
            if game not in found and os.path.isdir(path):
                found[game] = path
    return found


def chosen_results_folder(config_path: str) -> str:
    """Results folder chosen by user on race results page ("" if none: game folders found are read)"""
    try:
        with open(os.path.join(config_path, PAGE_SETTINGS_FILE), encoding="utf-8") as file:
            settings = json.load(file)
    except (OSError, ValueError):
        return ""
    folder = settings.get("folder", "") if isinstance(settings, dict) else ""
    return folder if isinstance(folder, str) else ""


def results_folders(chosen: str) -> tuple[str, ...]:
    """Folders read: folder chosen by user if any, else results folder of every game found"""
    if chosen:
        return (chosen,) if os.path.isdir(chosen) else ()
    return tuple(find_results_folders().values())


# Classification
class Gap(NamedTuple):
    """Gap to leader: laps down, or time (s) on same lap"""

    laps: int
    time: float


def lap_end_time(entry: Entry, number: int) -> float:
    """Session time at end of lap (start of next lap, else lap start + lap time), 0 if unknown"""
    for index, lap in enumerate(entry.laps):
        if lap.number != number:
            continue
        following = entry.laps[index + 1] if index + 1 < len(entry.laps) else None
        if following is not None and following.number == number + 1 and following.start > 0:
            return following.start
        if lap.start > 0 and lap.time > 0:
            return lap.start + lap.time
        return 0.0
    return 0.0


def race_gap(entry: Entry, leader: Entry) -> Gap:
    """Race gap of finished or running car to leader

    Time gap of cars on same lap: finish times, else times at end of last lap both completed (race left
    before its end: game writes classification of that moment, without finish times).
    """
    laps = max(leader.laps_completed - entry.laps_completed, 0)
    if laps:
        return Gap(laps, 0.0)
    if entry.finish_time > 0 and leader.finish_time > 0:
        return Gap(0, max(entry.finish_time - leader.finish_time, 0.0))
    entry_end = lap_end_time(entry, entry.laps_completed)
    leader_end = lap_end_time(leader, entry.laps_completed)
    if entry_end > 0 and leader_end > 0:
        return Gap(0, max(entry_end - leader_end, 0.0))
    return Gap(0, 0.0)


def race_unfinished(result: SessionResult) -> bool:
    """Race left before its end: no car has finished (classification of that moment)"""
    return result.kind == "Race" and bool(result.entries) and not any(
        entry.status == FINISHED for entry in result.entries)


def best_lap_gap(entry: Entry, leader: Entry) -> float:
    """Best lap gap to fastest car (practice, qualifying), -1 if none"""
    if entry.best_lap <= 0 or leader.best_lap <= 0:
        return -1.0
    return max(entry.best_lap - leader.best_lap, 0.0)


def contact_counts(events: Iterable[Event]) -> dict[str, tuple[int, int]]:
    """Contacts of each driver: (with cars, with objects), contacts of same pair close in time counted once"""
    counts: dict[str, list[int]] = {}
    last: dict[tuple[str, str], float] = {}
    for event in events:
        if event.kind != "contact":
            continue
        with_car = bool(event.other) and event.other != IMMOVABLE
        pair = (min(event.driver, event.other), max(event.driver, event.other)) if with_car else (event.driver, "")
        repeated = event.time - last.get(pair, -SAME_CONTACT * 2) <= SAME_CONTACT
        last[pair] = event.time
        if repeated:
            continue
        for driver in (pair if with_car else pair[:1]):
            count = counts.setdefault(driver, [0, 0])
            count[0 if with_car else 1] += 1
    return {driver: (count[0], count[1]) for driver, count in counts.items()}


def penalty_counts(events: Iterable[Event]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        if event.kind == "penalty":
            counts[event.driver] = counts.get(event.driver, 0) + 1
    return counts


def track_limit_points(events: Iterable[Event]) -> dict[str, float]:
    """Track limits points of each driver at end of session (highest reached)"""
    points: dict[str, float] = {}
    for event in events:
        if event.kind == "track_limits":
            points[event.driver] = max(points.get(event.driver, 0.0), event.value)
    return points


def best_sectors(entries: Iterable[Entry]) -> tuple[float, float, float]:
    """Best time of each sector among every lap, 0 if none"""
    best = [0.0, 0.0, 0.0]
    for entry in entries:
        for lap in entry.laps:
            for index, sector in enumerate(lap.sectors):
                if sector > 0 and (best[index] <= 0 or sector < best[index]):
                    best[index] = sector
    return best[0], best[1], best[2]
