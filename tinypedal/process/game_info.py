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
Game info of LMU Rest API: chat, contacts between cars, pit entry, setup name, replays

    /rest/chat/                         [{"message": "Name: text", "timestamp": 100 ns since 1970}]
    /rest/watch/getIncidentsList/{s}    [{"et": session time, "player": name, "contactWith": name or "Immovable"}]
    /rest/sessions/GetGameState         {"PitEntryDist": lap distance of pit lane entry, ...}
    /rest/garage/summary                {"activeSetup": name, "unsavedChanges": bool, ...}
    /rest/watch/replays                 [{"id", "replayName", "size", "timestamp", "metadata": {...}}]
"""

from __future__ import annotations

from typing import Any, NamedTuple

CHAT_TIME_SCALE = 1e-7  # chat timestamp unit: 100 ns
IMMOVABLE = "Immovable"  # contact with track objects (walls, barriers)


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


def parse_chat(data: Any, default: tuple) -> tuple[ChatMessage, ...]:
    """Chat messages, oldest first"""
    if not isinstance(data, list):
        return default
    messages = []
    for entry in data:
        try:
            text = str(entry["message"]).strip()
            if text:
                messages.append(ChatMessage(float(entry["timestamp"]) * CHAT_TIME_SCALE, text))
        except (KeyError, TypeError, ValueError):
            continue
    messages.sort(key=lambda message: message.time)
    return tuple(messages)


def parse_contacts(data: Any, default: tuple) -> tuple[Contact, ...]:
    """Contacts between cars (or with track objects), oldest first"""
    if not isinstance(data, list):
        return default
    contacts = []
    for entry in data:
        try:
            contacts.append(Contact(float(entry["et"]), str(entry["player"]), str(entry["contactWith"])))
        except (KeyError, TypeError, ValueError):
            continue
    contacts.sort(key=lambda contact: contact.time)
    return tuple(contacts)


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
    replays = []
    if not isinstance(data, list):
        return replays
    for entry in data:
        try:
            metadata = entry.get("metadata") or {}
            replays.append(GameReplay(
                id=int(entry["id"]),
                name=str(entry.get("replayName", "")),
                event=str(metadata.get("eventTitle", "")),
                session=str(metadata.get("session", "")),
                track=str(metadata.get("sceneDesc", "")),
                time=float(entry.get("timestamp") or 0),
                size=int(entry.get("size") or 0),
            ))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    replays.sort(key=lambda replay: replay.time, reverse=True)
    return replays


def driver_slots(standings: Any) -> dict[str, int]:
    """Slot id of each driver name (watch standings), to focus a car in game replay"""
    slots = {}
    if isinstance(standings, list):
        for car in standings:
            try:
                slots[str(car["driverName"])] = int(car["slotID"])
            except (KeyError, TypeError, ValueError):
                continue
    return slots


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
