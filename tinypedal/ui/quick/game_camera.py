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
Game camera of LMU through its Rest API: car followed & camera, live (spectator or driving) and in replays

Seen live 2026-10-05 (replay) & 2026-10-11 (online race as spectator): PUT /rest/watch/focus/{slot} puts the
camera on a car, PUT /rest/watch/focus/{type}/{group}/false changes camera (kept when the car changes).
No Qt: commands are sent on a game connection (see game_rest), in background.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from .. import game_rest
from ..game_rest import GameConnection

ACTIVE_RESOURCE = "/rest/replay/isActive"  # null outside a session, true while a replay is open
TOGGLE_REPLAY_RESOURCE = "/rest/replay/toggleactive"  # live session <-> its replay (no setter)
REPLAY_WAIT = 3.0  # seconds: live session going to its replay
REPLAY_READY = 1.0  # seconds after the replay opened before it takes commands
SEEK_WAIT = 0.6  # seconds: replay moved before the camera goes on the car
FOCUS_RESOURCE = "/rest/watch/focus"  # slot of car on camera, answers outside a session too (-1)
SESSION_RESOURCE = "/rest/watch/sessionInfo"
STANDINGS_RESOURCE = "/rest/watch/standings"
INCIDENTS_RESOURCE = "/rest/watch/getIncidentsList/1"
CAMERA_RESOURCE = "/rest/replay/CameraController/getCameraInfo"
SET_CAMERA_RESOURCE = "/rest/replay/CameraController/setCamera"
CAMERA_FOCUS = "/rest/watch/focus/{kind}/{group}/false"  # camera type & trackside group of game
NEXT_DRIVING = ("POST", SET_CAMERA_RESOURCE, json.dumps({"cameraGroup": "Driving", "direction": 1}))
CAMERA_GROUPS = ("Driving", "Onboard", "Trackside")
# Cameras of game camera menu, same order: key (camera name told by game, TRACKSIDE<group>), label, group,
# game camera type & trackside group (1 cockpit, 2 nose, 3 swingman, 4 trackside, 7 to 13 onboard 0 to 6),
# bonnet camera: next after cockpit in driving cameras
CAMERAS = (
    ("COCKPIT", "Cockpit", "Driving", 1, 0),
    ("SWINGMAN", "Swingman", "Driving", 3, 0),
    ("NOSECAM", "Nose Camera", "Driving", 2, 0),
    ("TVCOCKPIT", "Bonnet Camera", "Driving", 1, 0),
    ("ONBOARD00", "Roof Camera", "Onboard", 7, 0),
    ("ONBOARD01", "Cockpit", "Onboard", 8, 0),
    ("ONBOARD02", "Dash Camera", "Onboard", 9, 0),
    ("ONBOARD03", "Mirror", "Onboard", 10, 0),
    ("ONBOARD04", "Front Bumper", "Onboard", 11, 0),
    ("ONBOARD05", "Rear Bumper", "Onboard", 12, 0),
    ("ONBOARD06", "Rear Roof Camera", "Onboard", 13, 0),
    ("TRACKSIDE0", "Cycle All", "Trackside", 4, 0),
    ("TRACKSIDE1", "Group %1", "Trackside", 4, 1),
    ("TRACKSIDE2", "Group %1", "Trackside", 4, 2),
    ("TRACKSIDE3", "Group %1", "Trackside", 4, 3),
    ("TRACKSIDE4", "Group %1", "Trackside", 4, 4),
)
CAMERA_KEYS = frozenset(key for key, *_ in CAMERAS)
# Replay playback commands of game
PLAY, PAUSE, SLOW = "VCRCOMMAND_PLAY", "VCRCOMMAND_STOP", "VCRCOMMAND_SLOW"
PLAYBACK_COMMANDS = (PLAY, PAUSE, SLOW, "VCRCOMMAND_FORWARDSCAN", "VCRCOMMAND_REVERSESCAN")
# Command to game: (method, resource), (method, resource, json body), or work on a game connection
Command = tuple[str, str] | tuple[str, str, str] | Callable[[GameConnection], bool]


def camera_group(group: str) -> str:
    """Camera group of setCamera from group reported by game ("TracksideCycle" -> "Trackside")"""
    lowered = group.lower()
    return next((name for name in CAMERA_GROUPS if lowered.startswith(name.lower())), group)


def camera_key(group: str, name: str, trackside_choice: str = "") -> str:
    """Camera of camera menu shown in game from what the game tells (group & camera name), "" if unknown:
    the game tells the trackside group only for cycle, the one chosen from the page is kept for others"""
    if group.lower() == "tracksidecycle":
        return "TRACKSIDE0"
    if camera_group(group) == "Trackside":
        return trackside_choice if trackside_choice.startswith("TRACKSIDE") and trackside_choice != "TRACKSIDE0" else ""
    return name if name in CAMERA_KEYS else ""


def camera_commands(key: str) -> tuple[Command, ...]:
    """Commands showing camera of camera menu (car followed kept), none if unknown"""
    entry = next((entry for entry in CAMERAS if entry[0] == key), None)
    if entry is None:
        return ()
    commands: list[Command] = [("PUT", CAMERA_FOCUS.format(kind=entry[3], group=entry[4]))]
    if key == "TVCOCKPIT":
        commands.append(NEXT_DRIVING)
    return tuple(commands)


def focus_command(slot: int) -> Command:
    """Camera on car of slot"""
    return ("PUT", f"/rest/watch/focus/{int(slot)}")


def enter_replay(connection: GameConnection) -> bool:
    """Live session goes to its replay (game toggle has no setter: state read first)"""
    if connection.get(ACTIVE_RESOURCE) is True:
        return True
    if not connection.send("POST", TOGGLE_REPLAY_RESOURCE):
        return False
    end = time.monotonic() + REPLAY_WAIT
    while time.monotonic() < end:  # replay commands ignored until replay is open
        time.sleep(0.2)
        if connection.get(ACTIVE_RESOURCE) is True:
            return True
    return False


def seek_replay(seconds: int, slot: int) -> Command:
    """Replay moved to session time with the camera on a car, once the replay takes commands. Seen live
    2026-10-11 (online spectator): the replay of a live session rewinds, but standings & session info keep telling
    live values meanwhile, so where the replay is cannot be checked"""
    def run(connection: GameConnection) -> bool:
        time.sleep(REPLAY_READY)
        if not connection.send("PUT", f"/rest/watch/replaytime/{max(seconds, 0)}"):
            return False
        time.sleep(SEEK_WAIT)
        return connection.send("PUT", f"/rest/watch/focus/{int(slot)}")
    return run


def leave_replay(connection: GameConnection) -> bool:
    """Replay of live session left: back to live"""
    if connection.get(ACTIVE_RESOURCE) is not True:
        return True
    return connection.send("POST", TOGGLE_REPLAY_RESOURCE)


def send_commands(batch: tuple[Command, ...], address: tuple[str, int] | None = None) -> bool:
    """Commands to game in order on one connection (game of the app settings, or at address), stops at first
    refused, True if all accepted"""
    with game_rest.GameConnection(address=address) if address is not None else game_rest.GameConnection() as connection:
        for command in batch:
            if not (command(connection) if callable(command) else connection.send(*command)):
                return False
    return True
