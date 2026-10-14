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
Game info of LMU Rest API: chat, contacts between cars, pit entry, setup name, replays

    /rest/chat/                         [{"message": "Name: text", "timestamp": 100 ns since 1970}]
    /rest/watch/getIncidentsList/{s}    [{"et": session time, "player": name, "contactWith": name or "Immovable"}]
    /rest/sessions/GetGameState         {"PitEntryDist": lap distance of pit lane entry, ...}
    /rest/garage/summary                {"activeSetup": name, "unsavedChanges": bool, ...}
    /rest/watch/replays                 [{"id", "replayName", "size", "timestamp", "replayDirectory", "metadata": {...}}]
    /rest/watch/standings               [{"slotID", "position", "driverName", "carNumber", "carClass",
                                          "lapsCompleted", "bestLapTime", "timeBehindLeader", "hasFocus", "player", ...}]
    /rest/watch/focus                   slot id of car followed by replay camera, -1 if none
    /rest/watch/sessionInfo             {"currentEventTime": session time (replay time in replay), ...}
    /rest/replay/CameraController/getCameraInfo     {"cameraName": "ONBOARD03", "currentCameraGroup": "Onboard"}
"""

from __future__ import annotations

import math
import re
from typing import Any, NamedTuple

CHAT_TIME_SCALE = 1e-7  # chat timestamp unit: 100 ns
IMMOVABLE = "Immovable"  # contact with track objects (walls, barriers)
SAME_INCIDENT = 2.0  # seconds: contacts of the same cars this close are one incident
# Replay name: "<track name> <session code> <number>", session code P1, Q1, R1, W...
REPLAY_NAME = re.compile(r"^(?P<track>.+?)\s+(?P<code>[A-Z]{1,2}\d*\s+\d+)$")


class ChatMessage(NamedTuple):
    """Chat message"""

    time: float  # Unix time (seconds)
    text: str  # "Name: message"


class Contact(NamedTuple):
    """Contact of a car"""

    time: float  # session time (seconds)
    driver: str
    other: str  # other driver, or IMMOVABLE


class GameReplay(NamedTuple):
    """Replay saved by game"""

    id: int
    name: str
    event: str  # event title
    session: str
    track: str  # scene name
    time: float  # Unix time (seconds)
    size: int  # bytes
    event_type: str = ""  # daily, specialevent, Hosted, quick-race...
    folder: str = ""  # replay folder of game


class Incident(NamedTuple):
    """Contact between two cars (both sides listed by game merged), or of a car with track objects"""

    time: float  # session time (seconds) of first contact
    driver: str
    other: str  # other driver, or IMMOVABLE
    contacts: int  # contacts merged


class CarInfo(NamedTuple):
    """Car of session (watch standings)"""

    slot: int
    driver: str
    number: str
    car_class: str
    player: bool


class Standing(NamedTuple):
    """Car in watch standings (session or replay open in game)"""

    slot: int
    position: int
    driver: str
    number: str
    car_class: str
    vehicle: str
    team: str
    laps: int
    best: float  # lap time (seconds), 0 if none
    last: float
    gap: float  # behind leader (seconds)
    laps_behind: int  # laps behind leader
    pitstops: int
    in_pit: bool  # pit lane (entering, stopped, leaving)
    penalties: int
    finish: str  # FSTAT_NONE, FSTAT_FINISHED, FSTAT_DNF, FSTAT_DQ
    focus: bool  # followed by camera
    player: bool
    garage: bool = False  # in garage stall
    lap_start: float = 0.0  # session time of current lap start (seconds)
    into_lap: float = -1.0  # seconds into current lap, -1 if unknown
    estimated: float = 0.0  # estimated lap time (seconds)
    x: float = 0.0  # map position (trackmap coordinates: x, -z)
    y: float = 0.0
    energy: float = -1.0  # virtual energy left (0 to 1), -1 if hidden (other teams) or none
    fuel: float = -1.0  # fuel left (0 to 1), -1 if hidden or none
    speed: float = 0.0  # m/s
    distance: float = 0.0  # lap distance (meters into lap)
    sector: int = 0  # sector driven (1 to 3), 0 if unknown
    pit_state: str = "NONE"  # NONE, REQUEST, ENTERING, STOPPED, EXITING
    grid: int = 0  # qualifying place (starting grid), 0 if unknown
    # Sector times (seconds, -1 if none), sector 2 time includes sector 1 (as the game gives them)
    last_sector1: float = -1.0
    last_sector2: float = -1.0
    current_sector1: float = -1.0
    current_sector2: float = -1.0
    best_sector1: float = -1.0  # sectors of best lap
    best_sector2: float = -1.0
    blue: bool = False  # blue flag shown to car


def parse_chat(data: Any, default: tuple) -> tuple[ChatMessage, ...]:
    """Chat messages, oldest first"""
    if not isinstance(data, list):
        return default
    messages = []
    for entry in data:
        try:
            text = str(entry["message"]).strip()
            if text:
                messages.append(ChatMessage(_finite(entry["timestamp"]) * CHAT_TIME_SCALE, text))
        except (KeyError, OverflowError, TypeError, ValueError):
            continue
    messages.sort(key=lambda message: message.time)
    return tuple(messages)


def _contacts_of(entries: list) -> list[Contact]:
    """Contacts of incident list entries, invalid entries left out (list order)"""
    contacts = []
    for entry in entries:
        try:
            contacts.append(Contact(_finite(entry["et"]), str(entry["player"]), str(entry["contactWith"])))
        except (KeyError, OverflowError, TypeError, ValueError):
            continue
    return contacts


def _contact_time(contact: Contact) -> float:
    return contact.time


def parse_contacts(data: Any, default: tuple) -> tuple[Contact, ...]:
    """Contacts between cars (or with track objects), oldest first"""
    if not isinstance(data, list):
        return default
    contacts = _contacts_of(data)
    contacts.sort(key=_contact_time)
    return tuple(contacts)


class ContactsParser:
    """parse_contacts of a growing incident list (game appends new incidents): entries parsed before kept,
    only entries appended since last list parsed, same result & order as parse_contacts

    A list not starting with the entries parsed before (new session) is parsed again in full.
    """

    __slots__ = ("_last",)

    def __init__(self) -> None:
        # (entries parsed, first entry, last entry, contacts), replaced at once
        self._last: tuple[int, Any, Any, tuple[Contact, ...]] = (0, None, None, ())

    def __call__(self, data: Any, default: tuple) -> tuple[Contact, ...]:
        if not isinstance(data, list):
            self._last = (0, None, None, ())
            return default
        count, first, last, contacts = self._last
        total = len(data)
        if 0 < count <= total and data[0] == first and data[count - 1] == last:
            added = _contacts_of(data[count:])
            if added:
                added.sort(key=_contact_time)
                if contacts and added[0].time < contacts[-1].time:  # older entry appended: stable sort as before
                    merged = list(contacts)
                    merged.extend(added)
                    merged.sort(key=_contact_time)
                    contacts = tuple(merged)
                else:
                    contacts += tuple(added)
        else:
            contacts = parse_contacts(data, ())
        self._last = (total, data[0], data[-1], contacts) if total else (0, None, None, ())
        return contacts


def parse_setup_name(value: Any, default: str) -> str:
    """Setup name, game names between angle brackets (<Fixed setup>) kept as they are"""
    if not isinstance(value, str):
        return default
    return value.strip()


def parse_distance(value: Any, default: float) -> float:
    """Lap distance (meters), default if not a positive number"""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    return default


def distance_ahead(target: float, position: float, track_length: float) -> float:
    """Distance from position to target lap distance going forward (meters), -1 if unknown"""
    if target < 0 or track_length <= 0 or not 0 <= target <= track_length:
        return -1.0
    return (target - position) % track_length


def parse_replays(data: Any) -> list[GameReplay]:
    """Replays saved by game, newest first"""
    replays: list[GameReplay] = []
    if not isinstance(data, list):
        return replays
    for entry in data:
        try:
            metadata = entry.get("metadata") or {}
            replays.append(GameReplay(
                id=int(entry["id"]),
                name=str(entry.get("replayName") or ""),
                event=str(metadata.get("eventTitle") or ""),
                session=str(metadata.get("session") or ""),
                track=str(metadata.get("sceneDesc") or ""),
                time=_finite(entry.get("timestamp") or 0),
                size=int(entry.get("size") or 0),
                event_type=str(metadata.get("eventType") or ""),
                folder=str(entry.get("replayDirectory") or ""),
            ))
        except (AttributeError, KeyError, OverflowError, TypeError, ValueError):  # json: 1e999 is inf
            continue
    replays.sort(key=lambda replay: replay.time, reverse=True)
    return replays


def replay_title(name: str) -> tuple[str, str]:
    """Track name & session code of replay name: "Grand Prix of Long Beach R1 4" -> ("Grand Prix of Long Beach", "R1 4")"""
    match = REPLAY_NAME.match(name.strip())
    if match is None:
        return name.strip(), ""
    return match["track"], match["code"]


def parse_cars(standings: Any) -> dict[str, CarInfo]:
    """Cars of session by driver name (watch standings), to focus a car in game replay"""
    return {car.driver: CarInfo(car.slot, car.driver, car.number, car.car_class, car.player)
            for car in parse_standings(standings)}


def _number(value: Any, kind: type = float) -> Any:
    """Number of json value, 0 if not a finite number (json reads 1e999 as inf)"""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            if math.isfinite(value):
                return kind(value)
        except OverflowError:  # int too large for float
            pass
    return kind(0)


def _finite(value: Any) -> float:
    """Float of json value

    Raises:
        ValueError: not a number, NaN or infinite (json reads 1e999 as inf).
        OverflowError: int too large for float.
    """
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"not a finite number: {value}")
    return number


def _fraction(value: Any) -> float:
    """Fraction left (0 to 1) of game, -1 if not given: game sends 0 for cars of other teams (hidden)"""
    number = _number(value)
    return min(number, 1.0) if number > 0 else -1.0


def _time(value: Any) -> float:
    """Time (seconds) of json value, -1 if none (game sends -1 or 0)"""
    number = _number(value)
    return number if number > 0 else -1.0


def _sector(value: Any) -> int:
    """Sector driven of watch standings ("SECTOR2" -> 2), 0 if unknown"""
    text = str(value or "")
    return int(text[-1]) if text.startswith("SECTOR") and text[-1:] in ("1", "2", "3") else 0


class SessionState(NamedTuple):
    """Session state of watch session info: phase, flags, weather"""

    phase: int = -1  # game phase: 0 before, 3 formation, 4 countdown, 5 green, 6 full course yellow, 7 stopped, 8 over
    yellow: str = "NONE"  # full course yellow state: NONE, or the phase the game names
    sector_flags: tuple[bool, ...] = ()  # yellow flag in sector 1 to 3
    air: float = -999.0  # ambient temperature (Celsius), -999 if unknown
    track: float = -999.0  # track temperature (Celsius)
    rain: float = -1.0  # rain (0 to 1), -1 if unknown
    wetness: float = -1.0  # average wetness of racing line (0 to 1)


def parse_session_state(info: Any) -> SessionState:
    """Phase, flags & weather of watch session info"""
    if not isinstance(info, dict):
        return SessionState()
    phase = info.get("gamePhase")
    flags = info.get("sectorFlag")

    def value(name: str, default: float) -> float:
        number = info.get(name)
        if isinstance(number, (int, float)) and not isinstance(number, bool) and math.isfinite(number):
            return float(number)
        return default

    return SessionState(
        phase=phase if isinstance(phase, int) and not isinstance(phase, bool) else -1,
        yellow=str(info.get("yellowFlagState") or "NONE").upper(),
        sector_flags=tuple("YELLOW" in str(flag).upper() for flag in flags) if isinstance(flags, list) else (),
        air=value("ambientTemp", -999.0),
        track=value("trackTemp", -999.0),
        rain=value("raining", -1.0),
        wetness=value("averagePathWetness", -1.0),
    )


def parse_standings(standings: Any) -> list[Standing]:
    """Cars of watch standings by position"""
    cars: list[Standing] = []
    if not isinstance(standings, list):
        return cars
    for car in standings:
        try:
            pit_state = str(car.get("pitState") or "NONE")
            position = car.get("carPosition") if isinstance(car.get("carPosition"), dict) else {}
            velocity = car.get("carVelocity") if isinstance(car.get("carVelocity"), dict) else {}
            into_lap = car.get("timeIntoLap")
            cars.append(Standing(
                slot=int(car["slotID"]),
                position=_number(car.get("position"), int),
                driver=str(car["driverName"]),
                number=str(car.get("carNumber") or ""),
                car_class=str(car.get("carClass") or ""),
                vehicle=str(car.get("vehicleName") or ""),
                team=str(car.get("fullTeamName") or ""),
                laps=_number(car.get("lapsCompleted"), int),
                best=max(_number(car.get("bestLapTime")), 0.0),
                last=max(_number(car.get("lastLapTime")), 0.0),
                gap=max(_number(car.get("timeBehindLeader")), 0.0),
                laps_behind=max(_number(car.get("lapsBehindLeader"), int), 0),
                pitstops=_number(car.get("pitstops"), int),
                in_pit=car.get("pitting") is True or pit_state in ("ENTERING", "STOPPED", "EXITING"),
                penalties=_number(car.get("penalties"), int),
                finish=str(car.get("finishStatus") or "FSTAT_NONE"),
                focus=car.get("hasFocus") is True,
                player=car.get("player") is True,
                garage=car.get("inGarageStall") is True,
                lap_start=max(_number(car.get("lapStartET")), 0.0),
                into_lap=_number(into_lap) if isinstance(into_lap, (int, float)) and 0 <= into_lap < math.inf else -1.0,
                estimated=max(_number(car.get("estimatedLapTime")), 0.0),
                x=_number(position.get("x")),
                y=-_number(position.get("z")),
                energy=_fraction(car.get("veFraction")),
                fuel=_fraction(car.get("fuelFraction")),
                speed=max(_number(velocity.get("velocity")), 0.0),
                distance=max(_number(car.get("lapDistance")), 0.0),
                sector=_sector(car.get("sector")),
                pit_state=pit_state,
                grid=max(_number(car.get("qualification"), int), 0),
                last_sector1=_time(car.get("lastSectorTime1")),
                last_sector2=_time(car.get("lastSectorTime2")),
                current_sector1=_time(car.get("currentSectorTime1")),
                current_sector2=_time(car.get("currentSectorTime2")),
                best_sector1=_time(car.get("bestLapSectorTime1")),
                best_sector2=_time(car.get("bestLapSectorTime2")),
                blue=car.get("flag") == "BLUE",
            ))
        except (AttributeError, KeyError, OverflowError, TypeError, ValueError):  # json: 1e999 is inf
            continue
    cars.sort(key=lambda car: (car.position <= 0, car.position))
    return cars


def standings_time(cars: list[Standing]) -> float:
    """Session time of standings (replay time while a replay plays): lap start & time into lap of cars,
    median (cars on another frame), -1 if unknown"""
    times = sorted(car.lap_start + car.into_lap for car in cars if car.into_lap >= 0)
    return times[len(times) // 2] if times else -1.0


def parse_session_end(info: Any) -> float:
    """Session length (seconds) of watch session info, -1 if unknown or not timed"""
    if not isinstance(info, dict):
        return -1.0
    value = info.get("endEventTime")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value < 7 * 86400:
        return float(value)
    return -1.0


def parse_replay_folder(answer: Any) -> str:
    """Replay folder of game (custom, else default), "" if unknown"""
    if not isinstance(answer, dict):
        return ""
    return str(answer.get("custom") or answer.get("default") or "")


def parse_hud(answer: Any) -> dict[str, bool]:
    """HUD components shown (chat, mfd, speedo, timing, trackMap...)"""
    if not isinstance(answer, dict):
        return {}
    return {str(name): value for name, value in answer.items() if isinstance(value, bool)}


def parse_camera(info: Any) -> tuple[str, str]:
    """Camera group & camera name of game camera controller ("Driving", "TracksideCycle"...), ("", "") if unknown"""
    if not isinstance(info, dict):
        return "", ""
    return str(info.get("currentCameraGroup") or ""), str(info.get("cameraName") or "")


def merge_contacts(contacts: tuple[Contact, ...], window: float = SAME_INCIDENT) -> tuple[Incident, ...]:
    """Incidents of contacts, oldest first: game lists a contact of two cars from each side (A with B, then
    B with A), and repeated contacts of the same cars a moment apart, merged within window seconds"""
    incidents: list[Incident] = []
    # Cars (sorted names, or driver & IMMOVABLE): index of their last incident, time of their last contact
    last: dict[tuple[str, str], tuple[int, float]] = {}
    for contact in sorted(contacts, key=lambda item: item.time):
        first, second = ((contact.driver, contact.other) if contact.other == IMMOVABLE
                         else sorted((contact.driver, contact.other)))
        index, last_time = last.get((first, second), (-1, 0.0))
        if index >= 0 and contact.time - last_time <= window:
            incidents[index] = incidents[index]._replace(contacts=incidents[index].contacts + 1)
        else:
            index = len(incidents)
            incidents.append(Incident(contact.time, contact.driver, contact.other, 1))
        last[first, second] = (index, contact.time)
    return tuple(incidents)


def parse_focus(value: Any) -> int:
    """Slot id of car followed by replay camera, -1 if none"""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return -1


def parse_session_time(info: Any) -> float:
    """Session time (seconds) of watch session info, replay time while a replay plays, -1 if unknown"""
    if not isinstance(info, dict):
        return -1.0
    value = info.get("currentEventTime")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return float(value)
    return -1.0


def player_contacts(contacts: tuple, player: str) -> list[tuple[float, str]]:
    """Contacts of player: (session time, other driver or IMMOVABLE), oldest first"""
    result = []
    for contact in contacts:
        time, driver, other = contact[0], contact[1], contact[2]
        if driver == player:
            result.append((time, other))
        elif other == player:
            result.append((time, driver))
    return result
