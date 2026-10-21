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
Game Replays page helpers (see replays_backend): game resources & timings, texts (clock, size, session,
lap, gap...), copy progress handed to the UI thread, work on a game connection (state, commands, replay
actions)
"""

from __future__ import annotations

import math
import os
import time
import weakref
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING, Any, NamedTuple

from PySide6.QtCore import QObject, Qt, Signal, Slot
from shiboken6 import isValid

from ... import game_rest
from ...game_rest import GameConnection
from ...i18n import tr
from ...process.game_info import (
    IMMOVABLE,
    CarInfo,
    Contact,
    Incident,
    Standing,
    parse_camera,
    parse_contacts,
    parse_focus,
    parse_hud,
    parse_replay_folder,
    parse_replays,
    parse_session_end,
    parse_session_time,
    parse_standings,
)
from ...process.results_text import gap_seconds_text, laps_behind_text
from ...template.setting_status_colors import SAME_TIME
from ...userfile.track_geometry import parse_points
from . import page_settings
from .game_camera import Command
from .models import DictListModel

if TYPE_CHECKING:
    from .replays_base import ReplaysBase

REPLAYS_RESOURCE = "/rest/watch/replays"
FOLDER_RESOURCE = "/rest/watch/replay/getReplayFolder"
ACTIVE_RESOURCE = "/rest/replay/isActive"  # null outside a session
TOGGLE_REPLAY_RESOURCE = "/rest/replay/toggleactive"  # live session <-> its replay (no setter)
INCIDENTS_RESOURCE = "/rest/watch/getIncidentsList/1"
FOCUS_RESOURCE = "/rest/watch/focus"  # answers outside a session too (-1): tells game is running
SESSION_RESOURCE = "/rest/watch/sessionInfo"
STANDINGS_RESOURCE = "/rest/watch/standings"
TRACKMAP_RESOURCE = "/rest/watch/trackmap"
CAMERA_RESOURCE = "/rest/replay/CameraController/getCameraInfo"  # answers in sessions too
SET_CAMERA_RESOURCE = "/rest/replay/CameraController/setCamera"
HUD_RESOURCE = "/rest/hud"
REFRESH_MS = 5000  # replay state & incidents asked again while page shown
REPLAY_REFRESH_MS = 2000  # while a replay is open: camera car & replay time follow playback
OFF_TRACK = 30.0  # meters from track path: car placed at its position (pit lane, off track), not on the track
MAX_PATH_SPEED = 120.0  # m/s: faster move between answers (jump, other lap) not taken as speed
JUMP = 150.0  # meters: car this far from where it was expected jumps (seek), no easing toward new place
LIVE_MS = 100  # map shown: car positions read again from the game shared memory (as Broadcast Director)
IDLE_REFRESH_MS = 15000  # game not running
REPLAYS_MAX_AGE = 60.0  # seconds: replays list asked again when page shown after this long
SESSION_END_DELAY_MS = 3000  # replays list asked again this long after a session ended (replay saved)
SECONDS_BEFORE = 5  # replay starts this long before incident (default)
TOP_DRIVERS = 10  # drivers with most incidents shown as filter chips
LAP_SEARCH_STEPS = 8  # replay moves to find a lap start
REPLAY_WAIT = 3.0  # seconds: live session going to its replay
ACTION_WAIT = 90.0  # seconds: replay asked by race results (event, lap) given this long to open in game
ACTION_SETTLE = 3.0  # seconds: replay open command accepted, game loading it (state of former replay meanwhile)
SETTINGS_FILE = "game_replays.json"
ROAD_WIDTH, PIT_WIDTH = 14.0, 6.0  # map line widths (meters), at least a few pixels
CTRL, SHIFT = 0x04000000, 0x02000000  # Qt.KeyboardModifier values of QML mouse events

# Game state: no answer, game in menus, in a session, replay open
OFFLINE, MENU, SESSION, REPLAY = "offline", "menu", "session", "replay"
STATE_TEXTS = {
    OFFLINE: "Game not answering: LMU not running, or Rest API access disabled",
    MENU: "LMU running, not in a session",
    SESSION: "In session, no replay open: watch one, or open the replay of this session in the game",
    REPLAY: "Replay open in game",
}
# Replay playback commands of game: (command, label), slowest to fastest backwards then forwards
PLAYBACK = (
    ("VCRCOMMAND_REVERSESCANFAST", "Rewind fast"),
    ("VCRCOMMAND_REVERSESCAN", "Rewind"),
    ("VCRCOMMAND_PLAYBACKWARDS", "Play backwards"),
    ("VCRCOMMAND_SLOWBACKWARDS", "Play slowly backwards"),
    ("VCRCOMMAND_STOP", "Pause replay"),
    ("VCRCOMMAND_SLOW", "Play slowly"),
    ("VCRCOMMAND_PLAY", "Play replay"),
    ("VCRCOMMAND_FORWARDSCAN", "Play fast"),
    ("VCRCOMMAND_FORWARDSCANFAST", "Play very fast"),
)
PLAYBACK_COMMANDS = tuple(command for command, _ in PLAYBACK)
PAUSE, PLAY = "VCRCOMMAND_STOP", "VCRCOMMAND_PLAY"
HUD_LABELS = {"chat": "Chat", "mfd": "MFD", "speedo": "Car HUD", "timing": "Timing", "trackMap": "Track Map"}
SESSIONS = {"PRACTICE": "Practice", "QUALIFY": "Qualify", "WARMUP": "Warmup", "RACE": "Race"}
SESSION_FILTERS = ("", "PRACTICE", "QUALIFY", "RACE")  # filter index: session type ("" all)
EVENT_TYPES = {
    "daily": "Daily Race", "specialevent": "Special Event", "hosted": "Hosted Session",
    "quick-race": "Quick Race", "championship": "Championship",
}
SORTS = ("date", "size", "track")
INCIDENT_FILTERS = ("all", "cars", "walls")
PANELS = ("incidents", "standings", "map")


def clock_text(seconds: float) -> str:
    """Session time as h:mm:ss"""
    seconds = max(int(seconds), 0)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}"


def timeline_end(last_incident: float, replay_time: float, session_end: float) -> float:
    """Session span of incidents timeline (seconds): session length if known, else up to last incident or replay
    time in whole minutes (span not changed by every replay time answer), a minute at least, a little room after"""
    end = max(last_incident, replay_time, session_end / 1.02, 60.0) * 1.02
    return end if session_end > 0 else math.ceil(end / 60) * 60.0


def size_text(size: float) -> str:
    """File size in MB, GB from 1 GB, with decimal separator & unit symbols of app language"""
    from ..lap_viewer import localized

    if size >= 1 << 30:
        return f"{localized(f'{size / (1 << 30):.1f}')} {tr('GB')}"
    megabytes = size / (1 << 20)
    return f"{localized(f'{megabytes:.1f}') if 0 < megabytes < 10 else f'{megabytes:.0f}'} {tr('MB')}"


def file_size(path: str) -> int:
    """File size, 0 if missing or removed meanwhile (temporary files deleted by game while listed)"""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def session_text(session: str) -> str:
    """Session type of game (PRACTICE...) in app language"""
    return tr(SESSIONS.get(session.upper(), session.title()))


def event_type_text(event_type: str) -> str:
    """Event type of game (daily, quick-race...) in app language"""
    label = EVENT_TYPES.get(event_type.lower())
    return tr(label) if label else event_type.replace("-", " ").title()


def incident_key(incident: Incident) -> str:
    return f"{incident.time:.3f}|{incident.driver}|{incident.other}"


def car_text(car: CarInfo | None) -> str:
    """Car number & class: "#7 · Hypercar", "" if unknown"""
    if car is None:
        return ""
    return " · ".join(part for part in (f"#{car.number}" if car.number else "", car.car_class) if part)


def lap_text(seconds: float) -> str:
    """Lap time m:ss.sss, "-" if none"""
    from ... import calculation as calc

    return calc.sec2laptime_full(seconds) if seconds > 0 else "-"


def gap_text(car: Standing, race: bool = True, leader_best: float = 0.0) -> str:
    """Gap to leader, as the game shows it: race: "+12.345" or "+2 laps"; practice & qualifying: best lap
    behind best lap of leader ("-" without lap time); "" for leader"""
    if not race:
        if car.best <= 0:
            return "-"
        gap = car.best - leader_best
        return gap_seconds_text(gap) if leader_best > 0 and gap > SAME_TIME else ""
    if car.position == 1:
        return ""
    if car.laps_behind > 0:
        return laps_behind_text(car.laps_behind)
    return gap_seconds_text(car.gap) if car.gap > 0 else ""


def energy_text(car: Standing) -> tuple[str, float]:
    """Virtual energy left (else fuel) of car as the game shows it: "73%" & fraction, ("", -1) if hidden"""
    level = car.energy if car.energy >= 0 else car.fuel
    return (f"{round(level * 100)}%", level) if level >= 0 else ("", -1.0)


def move_selection(model: DictListModel, old: str, new: str):
    """Selected role moved from row of key old to row of key new (rows found by index, other rows untouched)"""
    for key, selected in ((old, False), (new, True)):
        number = model.index_of(key) if key else -1
        if number >= 0:
            model.update_row(number, {"selected": selected})


def lap_seconds(car: Standing) -> float:
    """Lap time of car to estimate lap starts: last, else best, else estimated by game, 0 if none"""
    return next((value for value in (car.last, car.best, car.estimated) if value > 0), 0.0)


# Page settings (user config folder), kept between sessions
def load_page_settings() -> dict[str, Any]:
    """Page settings (changes of an open page written first)"""
    return page_settings.load_settings(SETTINGS_FILE)


class _CopyProgress(QObject):
    """Copy (or recycle bin) progress handed from the file thread to its page on the UI thread (page held weakly: a
    page closed during a copy is never touched by the copy thread)"""

    progressed = Signal(object, str, float)

    def __init__(self):
        super().__init__()
        self.progressed.connect(self.hand_over, Qt.ConnectionType.QueuedConnection)

    @Slot(object, str, float)
    def hand_over(self, page: weakref.ReferenceType, setter: str, progress: float):
        backend = page()
        if backend is not None and isValid(backend):
            getattr(backend, setter)(progress)


_copy_progress: _CopyProgress | None = None


def copy_reporter(backend: ReplaysBase, setter: str = "set_copy_progress") -> Callable[[float], None]:
    """Progress callback of a copy thread (made on the UI thread), setter: page method given the progress"""
    global _copy_progress
    if _copy_progress is None or not isValid(_copy_progress):
        _copy_progress = _CopyProgress()
    courier, page = _copy_progress, weakref.ref(backend)

    def progress(value: float):
        with suppress(RuntimeError):  # app closing: courier deleted, progress dropped
            courier.progressed.emit(page, setter, value)
    return progress


# Background work (game connection)
def fetch_replays(connection: GameConnection) -> dict[str, Any]:
    """Replays saved by game & replay folder (known even without replay)"""
    return {"replays": connection.get(REPLAYS_RESOURCE), "folder": parse_replay_folder(connection.get(FOLDER_RESOURCE))}


def ask_state(connection: GameConnection, previous: tuple[Contact, ...], known_drivers: frozenset[str],
              want_standings: bool, map_track: str | None, decode_incidents: Callable[[str], Any] | None = None,
              contacts_of: Callable[[Any, tuple], tuple[Contact, ...]] = parse_contacts) -> dict[str, Any]:
    """Game state (in background): replay open, incidents, session (track, length), camera & HUD;
    car followed while a replay is open; standings if wanted, while a replay is open (replay time),
    or when contacts changed (slot of a driver can differ in another session or replay) or name drivers
    not looked up yet (known_drivers); track map if wanted (map_track not None) and track changed"""
    active = connection.get(ACTIVE_RESOURCE)
    if active is None:  # not in a session: game running if it answers anything
        connection.get(FOCUS_RESOURCE)
        return {"active": None, "running": connection.answered}
    info = connection.get(SESSION_RESOURCE)
    state: dict[str, Any] = {
        "active": active is True, "running": True,
        "contacts": contacts_of(connection.get(INCIDENTS_RESOURCE, decode_incidents), ()),
        "camera": parse_camera(connection.get(CAMERA_RESOURCE)),
        "hud": parse_hud(connection.get(HUD_RESOURCE)),
        "end": parse_session_end(info), "time": parse_session_time(info),
        "track": str(info.get("trackName") or "") if isinstance(info, dict) else "",
        "session": str(info.get("session") or "") if isinstance(info, dict) else "",
    }
    if active is True:
        state["focus"] = parse_focus(connection.get(FOCUS_RESOURCE))
    drivers = {name for contact in state["contacts"] for name in (contact.driver, contact.other)} - {IMMOVABLE}
    if want_standings or active is True or (drivers and (state["contacts"] != previous or drivers - known_drivers)):
        state["standings"] = parse_standings(connection.get(STANDINGS_RESOURCE))
        state["looked_up"] = drivers
    if map_track is not None and state["track"] != map_track:
        state["map"] = parse_points(points) if isinstance(points := connection.get(TRACKMAP_RESOURCE), list) else None
    return state


def send_commands(batch: tuple[Command, ...]) -> bool:
    """Commands to game in order on one connection, stops at first refused, True if all accepted"""
    with game_rest.GameConnection() as connection:
        for command in batch:
            if not (command(connection) if callable(command) else connection.send(*command)):
                return False
    return True


class ReplayAction(NamedTuple):
    """Where a replay asked from race results goes once open in game: session time (event, lap start), else lap
    looked for, camera on the car of drivers (all drivers of a team car: game names the one driving)"""

    replay: str  # replay name
    time: float = -1.0  # session time (seconds), -1 if none
    drivers: tuple[str, ...] = ()  # camera on car of these drivers (empty: camera kept)
    lap: int = 0  # lap of car, looked for if time unknown (0 if none)
    lead: float = -1.0  # seconds before time (-1: seconds before of page settings)


def play_replay(name: str) -> Command:
    """Open replay in game: its id looked up when sent (ids are positions in game list, they change
    when replay files are added or deleted)"""
    def run(connection: GameConnection) -> bool:
        replay = next((replay for replay in parse_replays(connection.get(REPLAYS_RESOURCE)) if replay.name == name),
                      None)
        return replay is not None and connection.send("GET", f"/rest/watch/play/{replay.id}")
    return run


def enter_replay(connection: GameConnection) -> bool:
    """Live session goes to its replay (game toggle has no setter: state read first)"""
    if connection.get(ACTIVE_RESOURCE) is True:
        return True
    if not connection.send("POST", TOGGLE_REPLAY_RESOURCE):
        return False
    end = time.monotonic() + REPLAY_WAIT
    while time.monotonic() < end:  # replay time ignored until replay is open
        time.sleep(0.2)
        if connection.get(ACTIVE_RESOURCE) is True:
            return True
    return False


def leave_replay(connection: GameConnection) -> bool:
    """Replay of live session left: back to live"""
    if connection.get(ACTIVE_RESOURCE) is not True:
        return True
    return connection.send("POST", TOGGLE_REPLAY_RESOURCE)


MAX_GO_TO_LAP = 9999  # lap asked by Go to lap at most


def go_to_lap(slot: int, lap: int, seconds_before: int) -> Command:
    """Replay goes to start of lap of car (seconds before), camera on car: lap start estimated from lap times
    of car, then replay moved until car is in that lap"""
    def run(connection: GameConnection) -> bool:
        connection.send("PUT", f"/rest/watch/focus/{slot}")
        for _ in range(LAP_SEARCH_STEPS):
            car = next((car for car in parse_standings(connection.get(STANDINGS_RESOURCE)) if car.slot == slot), None)
            if car is None:
                return False
            current = car.laps + 1  # lap being driven
            if (current == lap and car.lap_start > 0) or (lap <= 1 and current <= 1):
                return connection.send("PUT", f"/rest/watch/replaytime/{max(int(car.lap_start) - seconds_before, 0)}")
            lap_time = lap_seconds(car)
            if lap_time <= 0:
                return False
            target = car.lap_start + (lap - current) * lap_time + (lap_time * 0.05 if lap > current else 0.0)
            if not connection.send("PUT", f"/rest/watch/replaytime/{max(int(target), 0)}"):
                return False
            time.sleep(0.4)  # standings follow replay time
        return False
    return run
