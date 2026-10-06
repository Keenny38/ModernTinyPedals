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
Game Replays page state (LMU): replays saved by the game (watch in game, add, export, rename, protect,
delete to the recycle bin, clean up), playback, camera & HUD of the replay open in game, incidents,
standings & track map of the session, jump to an incident (a live session goes to its replay) with the
camera on a car, go to a lap of a car

Everything goes through the game Rest API in background (see game_rest): the game must be running,
replay state, incidents & standings need a session (or a replay) loaded in game. Game asked only while page
shown, with one connection per request: less often when game does not answer, more often while a replay is
open (camera car & replay time), standings only while shown (or a replay open, or incidents name new drivers).
"""

from __future__ import annotations

import csv
import io
import json
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Property, QDate, QDateTime, QLocale, QObject, QTime, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QFileDialog, QInputDialog

from ...formatter import random_color_class
from ...i18n import current_language, tr, trm
from ...process.game_info import (
    IMMOVABLE,
    CarInfo,
    Contact,
    GameReplay,
    Incident,
    Standing,
    merge_contacts,
    parse_camera,
    parse_contacts,
    parse_focus,
    parse_hud,
    parse_replay_folder,
    parse_replays,
    parse_session_end,
    parse_session_time,
    parse_standings,
    replay_title,
    standings_time,
)
from ...setting import cfg
from ...userfile import atomic_write
from ...userfile.track_geometry import parse_points
from .. import game_rest
from .._common import BaseDialog
from ..game_rest import GameConnection, GameRequest
from . import replay_files
from .game_pictures import LogoCache, notifier
from .lines import VertexStore, band
from .models import DictListModel

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
IDLE_REFRESH_MS = 15000  # game not running
REPLAYS_MAX_AGE = 60.0  # seconds: replays list asked again when page shown after this long
SESSION_END_DELAY_MS = 3000  # replays list asked again this long after a session ended (replay saved)
SECONDS_BEFORE = 5  # replay starts this long before incident (default)
TOP_DRIVERS = 10  # drivers with most incidents shown as filter chips
LAP_SEARCH_STEPS = 8  # replay moves to find a lap start
REPLAY_WAIT = 3.0  # seconds: live session going to its replay
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
# Camera groups of game camera controller: setCamera steps through angles of a group (direction -1 or 1)
CAMERA_GROUPS = ("Driving", "Onboard", "Trackside")
CAMERA_FOCUS = "/rest/watch/focus/{kind}/{group}/false"  # camera type & trackside group of game
NEXT_DRIVING = ("POST", SET_CAMERA_RESOURCE, json.dumps({"cameraGroup": "Driving", "direction": 1}))
# Cameras of game camera menu ("Change camera", same order): key (camera name told by game, TRACKSIDE<group>),
# label, group, game camera type & trackside group (seen live 2026-10-05: 1 cockpit, 2 nose, 3 swingman,
# 4 trackside group, 7 to 13 onboard 0 to 6), bonnet camera: next after cockpit in driving cameras
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
# Command to game: (method, resource), (method, resource, json body), or work on a game connection
Command = tuple[str, str] | tuple[str, str, str] | Callable[[GameConnection], bool]


def clock_text(seconds: float) -> str:
    """Session time as h:mm:ss"""
    seconds = max(int(seconds), 0)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}"


def size_text(size: float) -> str:
    """File size in MB, GB from 1 GB, with decimal separator & unit symbols of app language"""
    from ..lap_viewer import localized

    if size >= 1 << 30:
        return f"{localized(f'{size / (1 << 30):.1f}')} {tr('GB')}"
    megabytes = size / (1 << 20)
    return f"{localized(f'{megabytes:.1f}') if 0 < megabytes < 10 else f'{megabytes:.0f}'} {tr('MB')}"


def day_text(timestamp: float, today: QDate) -> str:
    """Day of a replay: Today, Yesterday, or long date in app language ("Samedi 3 octobre 2026")"""
    if timestamp <= 0:
        return tr("Unknown Date")
    date = QDateTime.fromSecsSinceEpoch(int(timestamp)).date()
    if date == today:
        return tr("Today")
    if date == today.addDays(-1):
        return tr("Yesterday")
    text = QLocale(current_language()).toString(date, QLocale.FormatType.LongFormat)
    return text[:1].upper() + text[1:]


def date_text(timestamp: float) -> str:
    """Short date & time in app language format, "" if none"""
    if timestamp <= 0:
        return ""
    date = QDateTime.fromSecsSinceEpoch(int(timestamp)).date()
    return f"{QLocale(current_language()).toString(date, QLocale.FormatType.ShortFormat)} {clock_minutes(timestamp)}"


def clock_minutes(timestamp: float) -> str:
    """Time of day as hh:mm"""
    return time.strftime("%H:%M", time.localtime(timestamp))


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


def class_color(car_class: str) -> str:
    """Color of vehicle class (vehicle class editor), made from name if not set"""
    style = cfg.user.classes.get(car_class)
    return str(style["color"]) if style else random_color_class(car_class)


def lap_text(seconds: float) -> str:
    """Lap time m:ss.sss, "-" if none"""
    from ... import calculation as calc

    return calc.sec2laptime_full(seconds) if seconds > 0 else "-"


def gap_text(car: Standing, race: bool = True, leader_best: float = 0.0) -> str:
    """Gap to leader, as the game shows it: race: "+12.345" or "+2 laps"; practice & qualifying: best lap
    behind best lap of leader ("-" without lap time); "" for leader"""
    from ..lap_viewer import localized

    if not race:
        if car.best <= 0:
            return "-"
        gap = car.best - leader_best
        return f"+{localized(f'{gap:.3f}')}" if leader_best > 0 and gap > 0.0005 else ""
    if car.position == 1:
        return ""
    if car.laps_behind > 0:
        return f"+{car.laps_behind} {tr('Lap') if car.laps_behind == 1 else tr('Laps')}"
    return f"+{localized(f'{car.gap:.3f}')}" if car.gap > 0 else ""


def energy_text(car: Standing) -> tuple[str, float]:
    """Virtual energy left (else fuel) of car as the game shows it: "73%" & fraction, ("", -1) if hidden"""
    level = car.energy if car.energy >= 0 else car.fuel
    return (f"{round(level * 100)}%", level) if level >= 0 else ("", -1.0)


def status_text(car: Standing) -> tuple[str, str]:
    """Status of car (garage, pit lane, finished, retired, disqualified) & its tone, ("", "") on track"""
    if car.finish == "FSTAT_DQ":
        return tr("Disqualified"), "loss"
    if car.finish == "FSTAT_DNF":
        return tr("Retired"), "loss"
    if car.finish == "FSTAT_FINISHED":
        return tr("Finished"), "gain"
    if car.garage:
        return tr("Garage"), "dim"
    if car.in_pit:
        return tr("In Pits"), "warning"
    return "", ""


def camera_group(group: str) -> str:
    """Camera group of setCamera from group reported by game ("TracksideCycle" -> "Trackside")"""
    lowered = group.lower()
    return next((name for name in CAMERA_GROUPS if lowered.startswith(name.lower())), group)


def lap_seconds(car: Standing) -> float:
    """Lap time of car to estimate lap starts: last, else best, else estimated by game, 0 if none"""
    return next((value for value in (car.last, car.best, car.estimated) if value > 0), 0.0)


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


# Background work (game connection)
def fetch_replays(connection: GameConnection) -> dict[str, Any]:
    """Replays saved by game & replay folder (known even without replay)"""
    return {"replays": connection.get(REPLAYS_RESOURCE), "folder": parse_replay_folder(connection.get(FOLDER_RESOURCE))}


def ask_state(connection: GameConnection, previous: tuple[Contact, ...], known_drivers: frozenset[str],
              want_standings: bool, map_track: str | None) -> dict[str, Any]:
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
        "contacts": parse_contacts(connection.get(INCIDENTS_RESOURCE), ()),
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


class GameReplaysBackend(QObject):
    """Game Replays page state (QML context property "backend")"""

    statusChanged = Signal()
    updatedChanged = Signal()
    replaysChanged = Signal()
    filterChanged = Signal()
    selectionChanged = Signal()
    incidentsChanged = Signal()
    standingsChanged = Signal()
    classesChanged = Signal()
    playbackChanged = Signal()
    replayTimeChanged = Signal()
    cameraChanged = Signal()
    hudChanged = Signal()
    lapsChanged = Signal()
    settingsChanged = Signal()
    filesChanged = Signal()
    noticeChanged = Signal()
    mapChanged = Signal()
    revisionChanged = Signal()
    copyProgressed = Signal(float)  # emitted by copy thread

    def __init__(self, parent: BaseDialog):
        super().__init__(parent)
        self._window = parent
        self.prefix = f"game_replays_{id(self)}|"
        settings = load_page_settings()
        self.replays: list[GameReplay] = []
        self.replays_time = 0.0  # monotonic time of replays list answer, 0 if never
        self.replays_answered = False
        self.folder = ""  # replay folder of game, kept when game closes
        self.temp: list[str] = []  # temporary files of game in replay folder
        self.protected: set[str] = {str(name) for name in settings.get("protected", []) if isinstance(name, str)}
        self.state = OFFLINE
        self.updated = ""
        self.last_session = False  # incidents & standings of a session left (game in menus)
        self.incidents: tuple[Incident, ...] = ()
        self.contacts: tuple[Contact, ...] = ()
        self.cars: dict[str, CarInfo] = {}  # by driver name, slots of replay or session open in game
        self.standings: list[Standing] = []
        self.class_list: list[dict] = []
        self.looked_up: set[str] = set()  # drivers looked up in standings
        self.focus = -1  # slot of car followed by replay camera
        self.camera = ("", "")  # camera group & name
        self.trackside_choice = ""  # trackside camera chosen from page (game tells group only for cycle)
        self.hud: dict[str, bool] = {}
        self.session_end = -1.0
        self.track = ""
        self.session_name = ""  # PRACTICE1, QUALIFY1, RACE1...
        self.live_time = -1.0  # live session time (seconds), -1 if unknown or replay
        self.lap_starts: dict[int, dict[int, float]] = {}  # slot: lap number: session time of start
        self.replay_time = -1.0
        self.replay_rate = 0.0  # replay seconds per second, measured between answers
        self.time_received = 0.0  # time.time() of replay time answer
        self.last_command = ""  # last playback command sent while replay open
        self.rewatching = False  # replay of live session opened from page (back to live possible)
        self.seconds_before = int(settings.get("seconds_before", SECONDS_BEFORE)) if isinstance(
            settings.get("seconds_before"), int) else SECONDS_BEFORE
        self.seconds_before = max(0, min(self.seconds_before, 60))
        self.session_filter = settings.get("session_filter", 0) if settings.get("session_filter") in range(
            len(SESSION_FILTERS)) else 0
        self.search_words: list[str] = []
        self.sort: str = str(settings.get("sort")) if settings.get("sort") in SORTS else SORTS[0]
        self.incident_filter = settings.get("incident_filter", 0) if settings.get("incident_filter") in range(
            len(INCIDENT_FILTERS)) else 0
        self.mine_only = False
        self.driver_filter = ""
        self.class_filter = ""
        self.panel = settings.get("panel", 0) if settings.get("panel") in range(len(PANELS)) else 0
        self.selected_replay = ""  # replay name (current row)
        self.checked: set[str] = set()  # replays selected (several with Ctrl / Shift)
        self.selected_incident = ""
        self.selected_car = ""  # slot of standings row
        self.copy_progress = -1.0  # replays being copied: 0 to 1, -1 if none
        self.copy_kind = "add"  # add (to game folder) or export
        self.copy_cancel = threading.Event()
        self.notice = ""
        self.notice_error = False
        self.notice_count = 0
        self.map_track: str | None = None  # track of map loaded, None if none
        self.map_center: list[tuple[float, float, float]] = []
        self.map_pit: list[tuple[float, float, float]] = []
        self.meters_per_pixel = 1.0
        self.revision = 0
        self._shown = False
        self._replays_model = DictListModel(
            ("key", "track", "code", "session", "sessionLabel", "event", "eventType", "section", "date",
             "size", "tip", "checked", "isProtected", "trackLogo"), self)
        self._incidents_model = DictListModel(
            ("key", "time", "timeText", "driver", "other", "wall", "mine", "count", "driverCar", "otherCar",
             "focused"), self)
        self._standings_model = DictListModel(
            ("key", "position", "classPosition", "number", "driver", "vehicle", "carClass", "classColor", "laps",
             "best", "last", "gap", "pits", "status", "statusTone", "penalties", "onCamera", "player", "fastest",
             "incidents", "energy", "energyLevel", "brandLogo"), self)
        self._map_model = DictListModel(
            ("key", "mapX", "mapY", "color", "number", "driver", "position", "onCamera", "player", "inPit"), self)
        self.logos = LogoCache()
        notifier().changed.connect(self.pictures_changed)
        self.request_replays = GameRequest(self, (), self.received_replays)
        self.request_state = GameRequest(self, (), self.received_state)
        self.request_command = GameRequest(self, (), self.command_done)
        self.request_copy = GameRequest(self, (), self.copy_done)
        self.command_queue: list[tuple[Command, ...]] = []  # commands waiting for the one sent
        self.copyProgressed.connect(self.set_copy_progress)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh_state)
        self._midnight = QTimer(self)  # day of replays (Today, Yesterday) changes at midnight
        self._midnight.setSingleShot(True)
        self._midnight.timeout.connect(self.new_day)
        self.schedule_midnight()

    # Page
    def page_shown(self):
        """Asked to game at once (replays list if old), then state again every few seconds while shown"""
        self._shown = True
        if not self.replays_answered or time.monotonic() - self.replays_time > REPLAYS_MAX_AGE:
            self.ask_replays()
        self.refresh_state()

    def page_hidden(self):
        self._shown = False
        self._timer.stop()

    def release(self):
        self.page_hidden()
        self.copy_cancel.set()
        VertexStore.remove_prefix(self.prefix)

    def notify(self, text: str, error: bool = False):
        """Message shown for a few seconds at the bottom of page"""
        self.notice, self.notice_error = text, error
        self.notice_count += 1
        self.noticeChanged.emit()

    def save_settings(self):
        save_page_settings({
            "seconds_before": self.seconds_before, "panel": self.panel, "sort": self.sort,
            "session_filter": self.session_filter, "incident_filter": self.incident_filter,
            "protected": sorted(self.protected),
        })

    def schedule_midnight(self):
        now = QDateTime.currentDateTime()
        midnight = QDateTime(now.date().addDays(1), QTime(0, 0, 1))
        self._midnight.start(max(int(now.msecsTo(midnight)), 1000))

    def new_day(self):
        self.update_replays()
        self.schedule_midnight()

    # Game requests
    @Slot()
    def refresh(self):
        """Replays list & state asked again"""
        self.ask_replays()
        self._timer.stop()
        self.refresh_state()

    def ask_replays(self):
        if self.request_replays.start(lambda: self.connected(fetch_replays)):
            self.statusChanged.emit()  # loading

    @staticmethod
    def connected(work: Callable[[GameConnection], Any]) -> Any:
        """Work done on a game connection (in background)"""
        with game_rest.GameConnection() as connection:
            return work(connection)

    def refresh_state(self):
        previous, known = self.contacts, frozenset(self.looked_up)
        panel = PANELS[self.panel]
        want_standings = panel in ("standings", "map")
        map_track = (self.map_track or "") if panel == "map" else None
        self.request_state.start(lambda: self.connected(
            lambda connection: ask_state(connection, previous, known, want_standings, map_track)))

    def schedule_state(self):
        """Next state request, sooner while a replay is open, later while game does not answer"""
        if self._shown and not self.request_state.busy:
            self._timer.start(REPLAY_REFRESH_MS if self.state == REPLAY
                              else IDLE_REFRESH_MS if self.state == OFFLINE else REFRESH_MS)

    def received_replays(self, answer: dict):
        folder = answer["folder"]
        if folder and folder != self.folder:
            self.folder = folder
        replays = answer["replays"]
        if replays is None:
            self.replays_answered = False
            if self.state == MENU:
                self.set_state(OFFLINE)
            self.update_files()
            self.statusChanged.emit()  # loaded
            return
        self.replays_answered = True
        self.replays_time = time.monotonic()
        self.replays = parse_replays(replays)
        if not self.folder:
            self.folder = next((replay.folder for replay in self.replays if replay.folder), "")
        if self.state == OFFLINE:
            self.set_state(MENU)
        self.statusChanged.emit()
        self.mark_updated()
        self.update_replays()
        self.update_files()

    def received_state(self, state: dict):
        active = state["active"]
        if active is None:  # session left: its incidents & standings kept until next one
            self.set_state(MENU if state["running"] else OFFLINE)
            if not state["running"]:
                self.replays_answered = False
            if (self.incidents or self.standings) and not self.last_session:
                self.last_session = True
                self.statusChanged.emit()
            self.update_replay_time(-1.0)
            self.schedule_state()
            return
        self.set_state(REPLAY if active else SESSION)
        if self.last_session:
            self.last_session = False
            self.statusChanged.emit()
        self.mark_updated()
        if state["camera"] != self.camera:  # trackside camera changes angle by itself
            self.camera = state["camera"]
            self.cameraChanged.emit()
        if state["hud"] != self.hud:  # HUD menu rebuilt only when HUD changed
            self.hud = state["hud"]
            self.hudChanged.emit()
        if state["end"] != self.session_end or state["track"] != self.track or state["session"] != self.session_name:
            self.session_end, self.track, self.session_name = state["end"], state["track"], state["session"]
            self.replayTimeChanged.emit()
            self.incidentsChanged.emit()  # timeline length
        if "map" in state:
            self.set_map(state["track"], state["map"])
        changed = "standings" in state and state["standings"] != self.standings
        if "standings" in state:  # drivers who left the session keep their car, not looked up again
            self.standings = state["standings"]
            self.cars.update({car.driver: CarInfo(car.slot, car.driver, car.number, car.car_class, car.player)
                              for car in self.standings})
            self.looked_up.update(state["looked_up"], self.cars)
        self.contacts = state["contacts"]
        incidents = merge_contacts(self.contacts)
        focus = state.get("focus", -1)
        if incidents != self.incidents or focus != self.focus or changed:
            self.incidents = incidents
            self.focus = focus
            self.update_incidents()
            self.update_standings()
        if "standings" in state:
            self.record_laps()
        replay_time = standings_time(self.standings) if active and "standings" in state else -1.0
        self.update_replay_time(replay_time if replay_time >= 0 or not active else state["time"])
        live_time = state["time"] if not active else -1.0
        if live_time != self.live_time:
            self.live_time = live_time
            self.time_received = time.time()
            self.replayTimeChanged.emit()
        self.schedule_state()

    def set_state(self, state: str):
        if state == self.state:
            return
        previous, self.state = self.state, state
        if state in (SESSION, REPLAY):  # another session or replay: slots differ
            self.cars.clear()
            self.looked_up.clear()
            if not self.rewatching:  # replay of live session: same laps
                self.lap_starts.clear()
                self.lapsChanged.emit()
        if state != REPLAY:
            self.last_command = ""
            self.rewatching = False
            self.playbackChanged.emit()
        if previous in (SESSION, REPLAY) and state == MENU:  # session ended: game saved its replay
            QTimer.singleShot(SESSION_END_DELAY_MS, self.ask_replays)
        self.statusChanged.emit()

    def mark_updated(self):
        updated = trm(f"Updated from game at {time.strftime('%H:%M:%S')}")
        if updated != self.updated:
            self.updated = updated
            self.updatedChanged.emit()

    def update_replay_time(self, replay_time: float):
        """Replay time & playback rate measured from last answer (playhead moves between answers)"""
        now = time.time()
        if replay_time < 0:
            rate = 0.0
        elif self.replay_time >= 0 and now - self.time_received > 0.2:
            rate = (replay_time - self.replay_time) / (now - self.time_received)
            rate = rate if abs(rate) < 50 else 0.0  # jumped: unknown
        else:
            rate = self.replay_rate
        if replay_time == self.replay_time and rate == self.replay_rate:
            return
        self.replay_time, self.replay_rate, self.time_received = replay_time, rate, now
        self.replayTimeChanged.emit()

    def command_done(self, accepted: bool):
        if not accepted:
            self.notify(tr("Game did not accept the command"), True)
        if self.command_queue:
            self.send()
        elif self._shown:
            self._timer.stop()
            self.refresh_state()

    def send(self, *commands: Command):
        """Commands to game in background, in order (stops at first refused), after commands sent before"""
        if commands:
            self.command_queue.append(commands)
        if self.request_command.busy or not self.command_queue:
            return
        batch = self.command_queue.pop(0)
        self.request_command.start(lambda: send_commands(batch))

    # Status
    @Property(str, notify=statusChanged)
    def gameState(self) -> str:
        """offline, menu, session or replay"""
        return self.state

    @Property(str, notify=statusChanged)
    def statusText(self) -> str:
        return tr(STATE_TEXTS[self.state])

    @Property(str, notify=updatedChanged)
    def updatedText(self) -> str:
        return self.updated

    @Property(bool, notify=statusChanged)
    def replayActive(self) -> bool:
        return self.state == REPLAY

    @Property(bool, notify=statusChanged)
    def inSession(self) -> bool:
        return self.state in (SESSION, REPLAY)

    @Property(bool, notify=statusChanged)
    def lastSession(self) -> bool:
        """Incidents & standings shown are those of the session left"""
        return self.last_session

    @Property(bool, notify=statusChanged)
    def loading(self) -> bool:
        """Replays list asked to game, no answer yet"""
        return self.request_replays.busy

    @Property(str, notify=noticeChanged)
    def noticeText(self) -> str:
        return self.notice

    @Property(bool, notify=noticeChanged)
    def noticeError(self) -> bool:
        return self.notice_error

    @Property(int, notify=noticeChanged)
    def noticeCount(self) -> int:
        """Changes with each message, same text again included"""
        return self.notice_count

    # Replays
    @Property(QObject, constant=True)
    def replayRows(self) -> DictListModel:
        return self._replays_model

    @Property(int, notify=replaysChanged)
    def replayCount(self) -> int:
        return len(self.replays)

    @Property(int, notify=replaysChanged)
    def shownCount(self) -> int:
        return len(self._replays_model.rows)

    @Property(str, notify=replaysChanged)
    def replaysSummary(self) -> str:
        """Replays shown & their size: "57 · 7.9 GB", "12 / 57 · 1.2 GB" when filtered"""
        shown = [replay for replay in self.replays if replay.name in self.shown_keys()]
        count = f"{len(shown)} / {len(self.replays)}" if len(shown) != len(self.replays) else f"{len(shown)}"
        return f"{count} · {size_text(sum(replay.size for replay in shown))}"

    @Property(str, notify=filesChanged)
    def replayFolder(self) -> str:
        """Replay folder of game, "" if unknown or not on this computer"""
        return self.replay_folder()

    def replay_folder(self) -> str:
        return self.folder if self.folder and os.path.isdir(self.folder) else ""

    @Property(int, notify=filterChanged)
    def sessionFilter(self) -> int:
        return self.session_filter

    @Property(str, notify=filterChanged)
    def sortKey(self) -> str:
        return self.sort

    @Property(str, notify=selectionChanged)
    def selectedReplay(self) -> str:
        return self.selected_replay

    @Property(int, notify=selectionChanged)
    def checkedCount(self) -> int:
        return len(self.checked)

    @Property(str, notify=selectionChanged)
    def checkedSummary(self) -> str:
        """Replays selected & their size: "3 · 412 MB" """
        return f"{len(self.checked)} · {size_text(sum(replay.size for replay in self.checked_replays()))}"

    @Property(bool, notify=selectionChanged)
    def selectedProtected(self) -> bool:
        return self.selected_replay in self.protected

    @Slot(int)
    def setSessionFilter(self, index: int):
        if 0 <= index < len(SESSION_FILTERS) and index != self.session_filter:
            self.session_filter = index
            self.filterChanged.emit()
            self.update_replays()
            self.save_settings()

    @Slot(str)
    def setSearch(self, text: str):
        words = text.lower().split()
        if words != self.search_words:
            self.search_words = words
            self.update_replays()

    @Slot(str)
    def setSort(self, key: str):
        if key in SORTS and key != self.sort:
            self.sort = key
            self.filterChanged.emit()
            self.update_replays()
            self.save_settings()

    @Slot(str)
    def selectReplay(self, key: str):
        """Replay selected alone"""
        self.clickReplay(key, 0)

    @Slot(str, int)
    def clickReplay(self, key: str, modifiers: int):
        """Replay clicked: selected alone, Ctrl: added to / removed from selection, Shift: range from current"""
        keys = [row["key"] for row in self._replays_model.rows]
        if modifiers & SHIFT and self.selected_replay in keys and key in keys:
            first, last = sorted((keys.index(self.selected_replay), keys.index(key)))
            checked = set(keys[first:last + 1])
        elif modifiers & CTRL and key:
            checked = self.checked ^ {key}
            self.selected_replay = key
        else:
            checked = {key} if key else set()
            self.selected_replay = key
        self.set_checked(checked)

    @Slot()
    def selectAllReplays(self):
        self.set_checked({row["key"] for row in self._replays_model.rows})

    def set_checked(self, checked: set[str]):
        self.checked = checked
        self._replays_model.update_rows(lambda row: {"checked": row["key"] in self.checked})
        self.selectionChanged.emit()

    @Slot(int)
    def moveReplaySelection(self, step: int):
        keys = [row["key"] for row in self._replays_model.rows]
        if keys:
            index = keys.index(self.selected_replay) + step if self.selected_replay in keys else 0
            self.selectReplay(keys[max(0, min(index, len(keys) - 1))])

    @Slot(str, result=int)
    def replayIndex(self, key: str) -> int:
        """Row of replay (list scrolled to it), -1 if not shown"""
        return next((index for index, row in enumerate(self._replays_model.rows) if row["key"] == key), -1)

    @Slot(str)
    def watchReplay(self, key: str):
        """Replay opened in game, after confirmation (warning in a live session)"""
        replay = self.replay_of(key)
        if replay is None:
            return
        if key not in self.checked:
            self.selectReplay(key)
        message = f"Open replay <b>{replay.name}</b> in the game?"
        if self.state == SESSION:
            message = f"You are in a session: opening a replay may leave it.<br><br>{message}"
        if self._window.confirm_operation("Watch in Game", message):
            self.send(play_replay(replay.name))

    @Slot()
    def openFolder(self):
        folder = self.replay_folder()
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    @Slot(str)
    def showInFolder(self, key: str):
        folder = self.replay_folder()
        if folder and self.replay_of(key) is not None:
            replay_files.show_in_folder(replay_files.replay_path(folder, key))

    def replay_of(self, key: str) -> GameReplay | None:
        return next((replay for replay in self.replays if replay.name == key), None)

    def checked_replays(self) -> list[GameReplay]:
        return [replay for replay in self.replays if replay.name in self.checked]

    def chosen_replays(self, key: str) -> list[GameReplay]:
        """Replays of an action on key: selected replays if key is one of them, else key"""
        return self.checked_replays() if key in self.checked else [replay for replay in self.replays
                                                                   if replay.name == key]

    def shown_keys(self) -> set[str]:
        return {row["key"] for row in self._replays_model.rows}

    def matches(self, replay: GameReplay) -> bool:
        session = SESSION_FILTERS[self.session_filter]
        if session and replay.session.upper() != session:
            return False
        if not self.search_words:
            return True
        text = " ".join((replay.name, replay.event, replay.track, session_text(replay.session),
                         event_type_text(replay.event_type))).lower()
        return all(word in text for word in self.search_words)

    @Slot()
    def pictures_changed(self):
        """Logos fetched from game meanwhile"""
        if self.replays:
            self.update_replays()
        if self.standings:
            self.update_standings()

    def update_replays(self):
        """Replays rows: filtered, sorted, section of each (day, track)"""
        replays = [replay for replay in self.replays if self.matches(replay)]
        if self.sort == "size":
            replays.sort(key=lambda replay: replay.size, reverse=True)
        elif self.sort == "track":
            replays.sort(key=lambda replay: (replay_title(replay.name)[0].lower(), -replay.time))
        today = QDate.currentDate()
        rows: list[dict[str, Any]] = []
        for replay in replays:
            track, code = replay_title(replay.name)
            by_date = self.sort == "date"
            rows.append({
                "key": replay.name,
                "track": track,
                "code": code,
                "session": replay.session.upper(),
                "sessionLabel": session_text(replay.session) if replay.session else "",
                "event": replay.event,
                "eventType": event_type_text(replay.event_type) if replay.event_type else "",
                "section": day_text(replay.time, today) if by_date else track if self.sort == "track" else "",
                "date": "" if replay.time <= 0 else clock_minutes(replay.time) if by_date else date_text(replay.time),
                "size": size_text(replay.size),
                "tip": f"{replay.name}\n{date_text(replay.time)}".strip(),
                "checked": replay.name in self.checked,
                "isProtected": replay.name in self.protected,
                "trackLogo": self.logos.track(track, replay.track),
            })
        self._replays_model.sync(rows)
        shown = self.shown_keys()
        if self.checked - shown:  # selected replays filtered out or deleted: no longer selected
            self.set_checked(self.checked & shown)
        if self.selected_replay not in shown:
            self.selectReplay(rows[0]["key"] if rows else "")
        self.replaysChanged.emit()

    # Replay files
    @Property(bool, notify=filesChanged)
    def copying(self) -> bool:
        return self.request_copy.busy

    @Property(float, notify=filesChanged)
    def copyProgress(self) -> float:
        """Replays being copied: 0 to 1"""
        return max(self.copy_progress, 0.0)

    @Property(str, notify=filesChanged)
    def copyKind(self) -> str:
        """add (to game folder) or export"""
        return self.copy_kind

    @Property(dict, notify=filesChanged)
    def folderInfo(self) -> dict:
        """Replays & temporary files of game folder: counts, sizes (texts)"""
        return {
            "replays": len(self.replays), "size": size_text(sum(replay.size for replay in self.replays)),
            "temp": len(self.temp), "tempSize": self.temp_size(), "protected": len(self.protected & {
                replay.name for replay in self.replays}),
        }

    def temp_size(self) -> str:
        return size_text(sum(os.path.getsize(path) for path in self.temp if os.path.exists(path)))

    def set_copy_progress(self, progress: float):
        self.copy_progress = progress
        self.filesChanged.emit()

    def update_files(self):
        """Temporary files of replay folder looked up again"""
        folder = self.replay_folder()
        self.temp = replay_files.temp_files(folder) if folder else []
        self.filesChanged.emit()

    @Slot()
    def addReplays(self):
        """Replay files chosen in a file dialog copied to replay folder of game"""
        if not self.replay_folder():
            self.notify(tr("Replay folder unknown: start LMU once so the page lists its replays."), True)
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self._window, tr("Add Replays"), os.path.expanduser("~"),
            f"{tr('LMU replays')} (*{replay_files.REPLAY_EXTENSION})")
        if paths:
            self.add_files(paths)

    @Slot(list)
    def addFiles(self, urls: list):
        """Replay files dropped on page (file urls) copied to replay folder of game"""
        self.add_files([(url if isinstance(url, QUrl) else QUrl(str(url))).toLocalFile() for url in urls])

    def add_files(self, paths: list[str]):
        folder = self.replay_folder()
        if not folder:
            self.notify(tr("Replay folder unknown: start LMU once so the page lists its replays."), True)
            return
        sources = [path for path in paths if replay_files.is_replay_file(path)]
        if not sources:
            self.notify(tr("No LMU replay file (.Vcr) to add."), True)
            return
        self.start_copy(sources, folder, "add")

    def start_copy(self, sources: list[str], folder: str, kind: str):
        if self.request_copy.busy:
            self.notify(tr("Replays are still being copied, try again once done."), True)
            return
        self.copy_progress, self.copy_kind = 0.0, kind
        self.copy_cancel = cancelled = threading.Event()
        progress = self.copyProgressed.emit
        self.request_copy.start(lambda: replay_files.copy_replays(sources, folder, progress, cancelled))
        self.filesChanged.emit()

    @Slot()
    def cancelCopy(self):
        self.copy_cancel.set()

    def copy_done(self, result: replay_files.CopyResult):
        self.copy_progress = -1.0
        self.filesChanged.emit()
        count = len(result.added)
        if result.cancelled:
            self.notify(trm(f"Copy cancelled, {count} replay(s) copied"), True)
        elif result.errors:
            self.notify(trm(f"Unable to copy: {'; '.join(result.errors)}"), True)
        elif self.copy_kind == "export":
            self.notify(trm(f"{count} replay(s) exported"))
        elif result.added:
            self.notify(trm(f"{count} replay(s) added to the game replay folder"))
        else:
            self.notify(tr("These replays are already in the game replay folder."))
        if result.added and self.copy_kind == "add":
            self.refresh_files(added=result.added)

    @Slot(str)
    def exportReplays(self, key: str):
        """Replay (selected replays if it is one of them) copied to a folder chosen in a dialog"""
        folder = self.replay_folder()
        replays = self.chosen_replays(key)
        if not folder or not replays:
            return
        target = QFileDialog.getExistingDirectory(self._window, tr("Export Replays"), os.path.expanduser("~"))
        if target:
            self.start_copy([replay_files.replay_path(folder, replay.name) for replay in replays], target, "export")

    @Slot(str)
    def renameReplay(self, key: str):
        """Replay file renamed (name given in a dialog), game lists it under its new name"""
        folder = self.replay_folder()
        if not folder or self.replay_of(key) is None:
            return
        name, accepted = QInputDialog.getText(self._window, tr("Rename Replay"), tr("New replay name:"), text=key)
        name = name.strip()
        if not accepted or not name or name == key:
            return
        error = replay_files.rename_replay(folder, key, name)
        if error:
            self.notify(trm(f"Unable to rename: {error}"), True)
            return
        if key in self.protected:
            self.protected = (self.protected - {key}) | {name}
            self.save_settings()
        replay = self.replay_of(key)
        self.replays = [entry._replace(name=name, id=-1) if entry is replay else entry for entry in self.replays]
        if self.selected_replay == key:
            self.selected_replay = name
        self.refresh_files()

    @Slot(str)
    def toggleProtected(self, key: str):
        """Replay (selected replays if it is one of them) protected from deletion & clean up, or no longer"""
        names = {replay.name for replay in self.chosen_replays(key)}
        if not names:
            return
        self.protected = self.protected - names if key in self.protected else self.protected | names
        self._replays_model.update_rows(lambda row: {"isProtected": row["key"] in self.protected})
        self.selectionChanged.emit()
        self.filesChanged.emit()
        self.save_settings()

    @Slot(str)
    def deleteReplays(self, key: str):
        """Replay (selected replays if it is one of them) moved to the recycle bin, after confirmation"""
        self.delete_replays(self.chosen_replays(key))

    def delete_replays(self, replays: list[GameReplay], title: str = "Delete Replays"):
        """Replays (protected ones kept) moved to the recycle bin, after confirmation"""
        folder = self.replay_folder()
        kept = [replay for replay in replays if replay.name in self.protected]
        replays = [replay for replay in replays if replay.name not in self.protected]
        if kept and not replays:
            self.notify(trm(f"{len(kept)} protected replay(s) kept"), True)
        if not folder or not replays:
            return
        size = size_text(sum(replay.size for replay in replays))
        message = (f"Move replay <b>{replays[0].name}</b> ({size}) to the recycle bin?" if len(replays) == 1
                   else f"Move <b>{len(replays)}</b> replays ({size}) to the recycle bin?")
        if not self._window.confirm_operation(title, message):
            return
        errors = replay_files.trash_replays([replay_files.replay_path(folder, replay.name) for replay in replays])
        deleted = [replay.name for replay in replays if f"{replay.name}{replay_files.REPLAY_EXTENSION}" not in errors]
        if errors:
            self.notify(trm(f"Unable to delete (replay open in game?): {', '.join(errors)}"), True)
        else:
            self.notify(trm(f"{len(deleted)} replay(s) moved to the recycle bin")
                        + (f" · {trm(f'{len(kept)} protected replay(s) kept')}" if kept else ""))
        if deleted:
            self.refresh_files(deleted=deleted)

    @Slot()
    def deleteOlderThan(self):
        """Replays older than a number of days (asked) moved to the recycle bin, protected ones kept"""
        days, accepted = QInputDialog.getInt(self._window, tr("Delete Old Replays"),
                                             tr("Delete replays older than (days):"), 30, 1, 3650)
        if accepted:
            limit = time.time() - days * 86400
            self.delete_replays([replay for replay in self.replays if 0 < replay.time < limit], "Delete Old Replays")

    @Slot()
    def keepLatest(self):
        """Replays but the latest ones (number asked) moved to the recycle bin, protected ones kept"""
        count, accepted = QInputDialog.getInt(self._window, tr("Keep Latest Replays"),
                                              tr("Number of latest replays kept:"), 20, 1, 1000)
        if accepted:
            latest = sorted(self.replays, key=lambda replay: replay.time, reverse=True)
            self.delete_replays(latest[count:], "Keep Latest Replays")

    @Slot()
    def deleteTempFiles(self):
        """Temporary files left by the game in replay folder moved to the recycle bin, after confirmation"""
        self.update_files()
        if not self.temp:
            self.notify(tr("No temporary file left by the game."))
            return
        size = self.temp_size()
        if not self._window.confirm_operation(
                "Delete Temporary Files", f"Move <b>{len(self.temp)}</b> temporary files ({size}) to the recycle bin?"):
            return
        errors = replay_files.trash_replays(self.temp)
        if errors:
            self.notify(trm(f"Unable to delete (replay open in game?): {', '.join(errors)}"), True)
        else:
            self.notify(trm(f"{len(self.temp)} temporary file(s) moved to the recycle bin"))
        self.update_files()

    def refresh_files(self, added: list[str] | None = None, deleted: list[str] | None = None):
        """Replays list updated after files changed: at once from files, then from game (ids, metadata)"""
        folder = self.replay_folder()
        replays = [replay for replay in self.replays if replay.name not in (deleted or ())]
        for name in added or ():
            path = replay_files.replay_path(folder, name)
            if os.path.exists(path):  # listed by game once asked again
                replays.append(GameReplay(-1, name, "", "", "", os.path.getmtime(path), os.path.getsize(path),
                                          "", folder))
        replays.sort(key=lambda replay: replay.time, reverse=True)
        self.replays = replays
        self.update_replays()
        self.update_files()
        if self.state != OFFLINE:
            self.ask_replays()

    # Playback, camera & HUD
    @Property(str, notify=playbackChanged)
    def lastCommand(self) -> str:
        return self.last_command

    @Property(bool, notify=playbackChanged)
    def canGoLive(self) -> bool:
        """Replay of live session opened from page: back to live possible"""
        return self.rewatching and self.state == REPLAY

    @Property(list, constant=True)
    def playbackModes(self) -> list[dict]:
        """Replay speeds (menu): command, label"""
        return [{"command": command, "text": tr(label)} for command, label in PLAYBACK]

    @Property(float, notify=replayTimeChanged)
    def replayTime(self) -> float:
        """Replay time (seconds), -1 if unknown"""
        return self.replay_time

    @Property(float, notify=replayTimeChanged)
    def replayRate(self) -> float:
        """Replay seconds per second, measured between answers"""
        return self.replay_rate

    @Property(float, notify=replayTimeChanged)
    def timeReceived(self) -> float:
        """When replay time was received, milliseconds since 1970 (QML Date.now())"""
        return self.time_received * 1000

    @Property(float, notify=replayTimeChanged)
    def liveTime(self) -> float:
        """Session time of live session (seconds, clock runs between answers), -1 if unknown or replay"""
        return self.live_time

    @Property(float, notify=replayTimeChanged)
    def sessionEnd(self) -> float:
        """Session length (seconds), -1 if unknown"""
        return self.session_end

    @Property(str, notify=cameraChanged)
    def cameraGroup(self) -> str:
        """Camera group shown in game: Driving, Onboard, Trackside, "" if unknown"""
        return camera_group(self.camera[0]) if self.state in (SESSION, REPLAY) else ""

    @Property(str, notify=cameraChanged)
    def cameraName(self) -> str:
        """Camera angle shown in game (ONBOARD03, TRACKING021...)"""
        return self.camera[1] if self.state in (SESSION, REPLAY) else ""

    @Property(str, notify=cameraChanged)
    def cameraKey(self) -> str:
        """Camera of camera menu shown in game (COCKPIT, ONBOARD02, TRACKSIDE0...), "" if unknown"""
        return self.camera_key()

    def camera_key(self) -> str:
        if self.state not in (SESSION, REPLAY):
            return ""
        group, name = self.camera
        if group.lower() == "tracksidecycle":
            return "TRACKSIDE0"
        if camera_group(group) == "Trackside":
            return self.trackside_choice if self.trackside_choice != "TRACKSIDE0" else ""
        return name if any(key == name for key, *_ in CAMERAS) else ""

    @Property(str, notify=cameraChanged)
    def cameraLabel(self) -> str:
        """Camera shown in game, as camera menu names it ("Onboard · Dash Camera"), "" if unknown"""
        key = self.camera_key()
        entry = next((entry for entry in CAMERAS if entry[0] == key), None)
        if entry is None:
            return f"{tr(camera_group(self.camera[0]))} · {self.camera[1]}" if self.camera[1] else ""
        label = tr(entry[1]).replace("%1", str(entry[4]))
        return f"{tr(entry[2])} · {label}"

    @Property(list, constant=True)
    def cameras(self) -> list[dict]:
        """Camera menu (as in game): key, label, group"""
        return [{"key": key, "text": tr(label).replace("%1", str(group_number)), "group": group}
                for key, label, group, _, group_number in CAMERAS]

    @Slot(str)
    def selectCamera(self, key: str):
        """Camera of camera menu shown in game (car followed kept)"""
        entry = next((entry for entry in CAMERAS if entry[0] == key), None)
        if entry is None or self.state not in (SESSION, REPLAY):
            return
        commands: list[Command] = [("PUT", CAMERA_FOCUS.format(kind=entry[3], group=entry[4]))]
        if key == "TVCOCKPIT":
            commands.append(NEXT_DRIVING)
        self.trackside_choice = key if entry[2] == "Trackside" else ""
        self.send(*commands)

    @Property(list, notify=hudChanged)
    def hudComponents(self) -> list[dict]:
        """HUD components of game: key, label, shown"""
        return [{"key": key, "text": tr(HUD_LABELS.get(key, key)), "shown": shown} for key, shown in self.hud.items()]

    @Property(bool, notify=hudChanged)
    def hudShown(self) -> bool:
        return any(self.hud.values()) if self.hud else True

    @Property(dict, notify=hudChanged)
    def hudState(self) -> dict:
        """HUD components shown in game (chat, mfd, speedo, timing, trackMap): component known if listed"""
        return dict(self.hud)

    @Property(str, notify=incidentsChanged)
    def focusedDriver(self) -> str:
        """Driver followed by camera, "" if unknown"""
        slot = self.focused_slot()
        return next((car.driver for car in self.standings if car.slot == slot), "") if slot >= 0 else ""

    def focused_slot(self) -> int:
        """Slot of car followed by camera: replay camera, else car with focus in standings, -1 if unknown"""
        if self.state not in (SESSION, REPLAY):
            return -1
        if self.state == REPLAY and self.focus >= 0:
            return self.focus
        return next((car.slot for car in self.standings if car.focus), -1)

    @Slot(str)
    def playback(self, command: str):
        if command in PLAYBACK_COMMANDS and self.state == REPLAY:
            self.last_command = command
            self.playbackChanged.emit()
            self.send(("PUT", f"/rest/watch/replayCommand/{command}"))

    @Slot(float)
    def seek(self, seconds: float):
        """Replay open in game goes to session time"""
        if self.state == REPLAY:
            self.send(("PUT", f"/rest/watch/replaytime/{max(int(seconds), 0)}"))

    @Slot()
    def togglePlay(self):
        """Pause replay if moving (last command), else play"""
        self.playback(PAUSE if self.last_command not in ("", PAUSE) else PLAY)

    @Slot(int)
    def focusCar(self, step: int):
        """Camera on previous (-1) or next (1) car"""
        if self.state in (SESSION, REPLAY):
            self.send(("PUT", "/rest/watch/focusForward" if step > 0 else "/rest/watch/focusBackward"))

    @Slot(str, int)
    def setCamera(self, group: str, direction: int):
        """Game camera: previous (-1) or next (1) angle of group (Driving, Onboard, Trackside), group shown"""
        if group in CAMERA_GROUPS and self.state in (SESSION, REPLAY):
            self.trackside_choice = ""  # other trackside camera: group no longer known
            body = json.dumps({"cameraGroup": group, "direction": -1 if direction < 0 else 1})
            self.send(("POST", SET_CAMERA_RESOURCE, body))

    @Slot(bool)
    def setHudShown(self, shown: bool):
        """Whole HUD of game (replay controls included) shown or hidden: clean pictures & videos"""
        if self.state not in (SESSION, REPLAY):
            return
        value = "true" if shown else "false"
        self.hud = dict.fromkeys(self.hud, shown)
        self.hudChanged.emit()
        self.send(("POST", f"/rest/hud/toggleAllComponents/{value}"), ("POST", "/rest/sessions/setHudOnWatchScreen", value),
                  ("POST", "/rest/watch/replay/setReplayUIVisible", value))

    @Slot()
    def toggleGameUi(self):
        """Whole game UI (top bar, standings, replay bar & HUD) shown or hidden, as a middle click in game does
        (no Rest API command for its web panels): middle click posted to game window"""
        from . import game_window

        if self.state not in (SESSION, REPLAY):
            return
        window = game_window.find_game_window()
        if not window[0]:
            self.notify(tr("Game window not found: LMU must be running on this computer."), True)
            return
        threading.Thread(target=game_window.middle_click, args=(window,), daemon=True, name="Game click").start()
        if self._shown:  # game shows or hides its HUD parts too: asked again once done
            QTimer.singleShot(700, self.refresh_state)

    @Slot(str)
    def toggleHudComponent(self, key: str):
        if key in self.hud and self.state in (SESSION, REPLAY):
            self.hud = {**self.hud, key: not self.hud[key]}
            self.hudChanged.emit()
            self.send(("POST", f"/rest/hud/toggle/{key}"))

    @Slot()
    def backToLive(self):
        """Replay of live session left: live session shown again"""
        if self.canGoLive:
            self.rewatching = False
            self.playbackChanged.emit()
            self.send(leave_replay)

    # Incidents
    @Property(QObject, constant=True)
    def incidentRows(self) -> DictListModel:
        return self._incidents_model

    @Property(int, notify=incidentsChanged)
    def incidentCount(self) -> int:
        return len(self.incidents)

    @Property(dict, notify=incidentsChanged)
    def counts(self) -> dict:
        """Incidents by kind: all, cars, walls, of player (mine), shown"""
        walls = sum(1 for incident in self.incidents if incident.other == IMMOVABLE)
        player = self.player_name()
        return {
            "all": len(self.incidents), "cars": len(self.incidents) - walls, "walls": walls,
            "mine": sum(1 for incident in self.incidents if player in (incident.driver, incident.other)) if player else 0,
            "shown": len(self._incidents_model.rows),
        }

    @Property(list, notify=incidentsChanged)
    def drivers(self) -> list[dict]:
        """Drivers with most incidents (filter chips): name, count, player, car"""
        counts = self.incident_counts()
        player = self.player_name()
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))[:TOP_DRIVERS]
        if self.driver_filter and self.driver_filter not in dict(ranked):
            ranked.append((self.driver_filter, counts.get(self.driver_filter, 0)))
        return [{"name": name, "count": count, "mine": name == player, "car": car_text(self.cars.get(name))}
                for name, count in ranked]

    @Property(dict, notify=incidentsChanged)
    def timeline(self) -> dict:
        """Session time span (session length if known) & incident markers: key, time, wall, mine, shown, label"""
        player = self.player_name()
        shown = {row["key"] for row in self._incidents_model.rows}
        end = max([incident.time for incident in self.incidents] + [self.replay_time, self.session_end / 1.02, 60.0])
        return {
            "end": end * 1.02,
            "markers": [{
                "key": incident_key(incident), "time": incident.time, "wall": incident.other == IMMOVABLE,
                "mine": bool(player) and player in (incident.driver, incident.other),
                "shown": incident_key(incident) in shown,
                "label": f"{clock_text(incident.time)}  {incident.driver} ↔ "
                         f"{tr('Wall') if incident.other == IMMOVABLE else incident.other}",
            } for incident in self.incidents],
        }

    @Property(int, notify=filterChanged)
    def incidentFilter(self) -> int:
        return self.incident_filter

    @Property(bool, notify=filterChanged)
    def mineOnly(self) -> bool:
        return self.mine_only

    @Property(str, notify=filterChanged)
    def driverFilter(self) -> str:
        return self.driver_filter

    @Property(str, notify=incidentsChanged)
    def playerName(self) -> str:
        return self.player_name()

    @Property(str, notify=selectionChanged)
    def selectedIncident(self) -> str:
        return self.selected_incident

    @Property(int, notify=settingsChanged)
    def secondsBefore(self) -> int:
        return self.seconds_before

    @Property(int, notify=settingsChanged)
    def panelIndex(self) -> int:
        """Shown under playback: 0 incidents, 1 standings, 2 track map"""
        return self.panel

    @Slot(int)
    def setPanel(self, index: int):
        if 0 <= index < len(PANELS) and index != self.panel:
            self.panel = index
            self.settingsChanged.emit()
            self.save_settings()
            if PANELS[index] != "incidents" and self._shown and self.state in (SESSION, REPLAY):
                self._timer.stop()
                self.refresh_state()

    @Slot(int)
    def setSecondsBefore(self, seconds: int):
        seconds = max(0, min(int(seconds), 60))
        if seconds != self.seconds_before:
            self.seconds_before = seconds
            self.settingsChanged.emit()
            self.save_settings()

    @Slot(int)
    def setIncidentFilter(self, index: int):
        if 0 <= index < len(INCIDENT_FILTERS) and index != self.incident_filter:
            self.incident_filter = index
            self.filterChanged.emit()
            self.update_incidents()
            self.save_settings()

    @Slot(bool)
    def setMineOnly(self, mine: bool):
        if mine != self.mine_only:
            self.mine_only = mine
            self.filterChanged.emit()
            self.update_incidents()

    @Slot(str)
    def setDriverFilter(self, name: str):
        """Incidents of a driver only ("" all drivers), same driver again: filter removed"""
        name = "" if name == self.driver_filter else name
        self.driver_filter = name
        self.filterChanged.emit()
        self.update_incidents()

    @Slot(str)
    def showDriverIncidents(self, name: str):
        """Incidents panel with incidents of driver only"""
        if name != self.driver_filter:
            self.setDriverFilter(name)
        self.setPanel(PANELS.index("incidents"))

    @Slot(str)
    def selectIncident(self, key: str):
        if key != self.selected_incident:
            self.selected_incident = key
            self.selectionChanged.emit()

    @Slot(int)
    def moveIncidentSelection(self, step: int):
        keys = [row["key"] for row in self._incidents_model.rows]
        if keys:
            index = keys.index(self.selected_incident) + step if self.selected_incident in keys else 0
            self.selectIncident(keys[max(0, min(index, len(keys) - 1))])

    @Slot(str, result=int)
    def incidentIndex(self, key: str) -> int:
        return next((index for index, row in enumerate(self._incidents_model.rows) if row["key"] == key), -1)

    @Slot(str, str)
    def jumpTo(self, key: str, driver: str):
        """Replay goes to incident (seconds before), camera on driver's car ("" player's car if involved,
        else first car). In a live session: its replay opened first (back to live later)."""
        incident = next((incident for incident in self.incidents if incident_key(incident) == key), None)
        if incident is None or self.state not in (SESSION, REPLAY) or self.last_session:
            return
        self.selectIncident(key)
        if not driver:
            player = self.player_name()
            driver = player if player and player in (incident.driver, incident.other) else incident.driver
        commands: list[Command] = []
        if self.state == SESSION:
            commands.append(enter_replay)
            self.rewatching = True
            self.playbackChanged.emit()
        car = self.cars.get(driver)
        if car is not None:
            commands.append(("PUT", f"/rest/watch/focus/{car.slot}"))
        replay_time = max(int(incident.time - self.seconds_before), 0)
        commands.append(("PUT", f"/rest/watch/replaytime/{replay_time}"))
        self.send(*commands)

    @Slot(int)
    def jumpNext(self, step: int):
        """Jump to previous (-1) or next (1) incident shown"""
        self.moveIncidentSelection(step)
        if self.selected_incident:
            self.jumpTo(self.selected_incident, "")

    @Slot()
    def copyIncidents(self):
        """Incidents shown copied to clipboard (tab separated: spreadsheet, chat)"""
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None and self._incidents_model.rows:
            clipboard.setText(self.incidents_text("\t"))
            self.notify(trm(f"{len(self._incidents_model.rows)} incident(s) copied to the clipboard"))

    @Slot()
    def exportIncidents(self):
        """Incidents shown saved to a CSV file chosen in a dialog"""
        if not self._incidents_model.rows:
            return
        filename, _ = QFileDialog.getSaveFileName(self._window, tr("Export Incidents"),
                                                  os.path.join(os.path.expanduser("~"), "incidents.csv"), "CSV (*.csv)")
        if not filename:
            return
        try:
            with open(filename, "w", encoding="utf-8-sig", newline="") as file:
                file.write(self.incidents_text(","))
        except OSError as error:
            self.notify(trm(f"Unable to save: {error.strerror or error}"), True)
            return
        self.notify(trm(f"{len(self._incidents_model.rows)} incident(s) exported"))

    def incidents_text(self, delimiter: str) -> str:
        output = io.StringIO()
        writer = csv.writer(output, delimiter=delimiter, lineterminator="\n")
        writer.writerow([tr("Time"), tr("Driver"), tr("Car"), tr("Contact With"), tr("Car"), tr("Contacts")])
        for row in self._incidents_model.rows:
            writer.writerow([row["timeText"], row["driver"], row["driverCar"], row["other"], row["otherCar"],
                             row["count"]])
        return output.getvalue()

    def player_name(self) -> str:
        return next((car.driver for car in self.cars.values() if car.player), "")

    def incident_counts(self) -> dict[str, int]:
        """Incidents of each driver"""
        counts: dict[str, int] = {}
        for incident in self.incidents:
            for name in (incident.driver, incident.other):
                if name != IMMOVABLE:
                    counts[name] = counts.get(name, 0) + 1
        return counts

    def incident_shown(self, incident: Incident, player: str) -> bool:
        kind = INCIDENT_FILTERS[self.incident_filter]
        wall = incident.other == IMMOVABLE
        if (kind == "cars" and wall) or (kind == "walls" and not wall):
            return False
        if self.mine_only and player not in (incident.driver, incident.other):
            return False
        return not self.driver_filter or self.driver_filter in (incident.driver, incident.other)

    def update_incidents(self):
        """Incident rows filtered, newest last (session order)"""
        player = self.player_name()
        focused = self.focusedDriver
        rows = []
        for incident in self.incidents:
            if not self.incident_shown(incident, player):
                continue
            wall = incident.other == IMMOVABLE
            rows.append({
                "key": incident_key(incident),
                "time": incident.time,
                "timeText": clock_text(incident.time),
                "driver": incident.driver,
                "other": tr("Wall") if wall else incident.other,
                "wall": wall,
                "mine": bool(player) and player in (incident.driver, incident.other),
                "count": incident.contacts,
                "driverCar": car_text(self.cars.get(incident.driver)),
                "otherCar": "" if wall else car_text(self.cars.get(incident.other)),
                "focused": "driver" if focused and focused == incident.driver
                else "other" if focused and focused == incident.other else "",
            })
        self._incidents_model.sync(rows)
        if self.selected_incident and self.selected_incident not in {row["key"] for row in rows}:
            self.selectIncident("")
        self.incidentsChanged.emit()

    # Standings
    @Property(QObject, constant=True)
    def standingRows(self) -> DictListModel:
        return self._standings_model

    @Property(int, notify=standingsChanged)
    def carCount(self) -> int:
        return len(self.standings)

    @Property(list, notify=classesChanged)
    def classes(self) -> list[dict]:
        """Vehicle classes of session (filter chips): name, color, count, in order of best position"""
        return self.class_list

    @Property(bool, notify=standingsChanged)
    def hasEnergy(self) -> bool:
        """Energy (or fuel) of some cars told by game (own team): column shown"""
        return any(car.energy >= 0 or car.fuel >= 0 for car in self.standings)

    @Property(str, notify=standingsChanged)
    def classFilter(self) -> str:
        return self.class_filter

    @Property(str, notify=standingsChanged)
    def selectedCar(self) -> str:
        return self.selected_car

    @Slot(str)
    def setClassFilter(self, name: str):
        """Cars of a class only ("" all), same class again: filter removed"""
        self.class_filter = "" if name == self.class_filter else name
        self.update_standings()

    @Slot(str)
    def selectCar(self, key: str):
        if key != self.selected_car:
            self.selected_car = key
            self.standingsChanged.emit()

    @Slot(int)
    def moveCarSelection(self, step: int):
        keys = [row["key"] for row in self._standings_model.rows]
        if keys:
            index = keys.index(self.selected_car) + step if self.selected_car in keys else 0
            self.selectCar(keys[max(0, min(index, len(keys) - 1))])

    @Slot(str, result=int)
    def carIndex(self, key: str) -> int:
        return next((index for index, row in enumerate(self._standings_model.rows) if row["key"] == key), -1)

    @Slot(str)
    def watchCar(self, key: str):
        """Camera on car of standings row (or map)"""
        car = self.car_of(key)
        if car is not None and self.state in (SESSION, REPLAY):
            self.selectCar(key)
            self.send(("PUT", f"/rest/watch/focus/{car.slot}"))

    def record_laps(self):
        """Session time of lap starts of each car, as seen (live session going on, replay playing)"""
        changed = False
        for car in self.standings:
            lap = car.laps + 1
            if car.lap_start > 0 or lap == 1:
                starts = self.lap_starts.setdefault(car.slot, {})
                if starts.get(lap) != car.lap_start:
                    starts[lap] = car.lap_start
                    changed = True
        if changed:
            self.lapsChanged.emit()

    @Property(list, notify=lapsChanged)
    def lapMarks(self) -> list[dict]:
        """Lap starts of car followed by camera seen so far (timeline): lap, time"""
        starts = self.lap_starts.get(self.focused_slot(), {})
        return [{"lap": lap, "time": start} for lap, start in sorted(starts.items()) if lap > 1]

    @Property(int, notify=lapsChanged)
    def cameraLap(self) -> int:
        """Lap driven by car followed by camera, 0 if unknown"""
        return self.camera_lap()

    def camera_lap(self) -> int:
        car = next((car for car in self.standings if car.slot == self.focused_slot()), None)
        return car.laps + 1 if car is not None else 0

    @Slot(int)
    def stepLap(self, step: int):
        """Replay goes to start of previous (-1) or next (1) lap of car followed by camera
        (lap start seen before: at once, else looked for)"""
        slot, lap = self.focused_slot(), self.camera_lap() + step
        if self.state != REPLAY or slot < 0 or lap < 1:
            return
        start = self.lap_starts.get(slot, {}).get(lap)
        if start is not None and (start > 0 or lap == 1):
            self.send(("PUT", f"/rest/watch/replaytime/{max(int(start), 0)}"))
        else:
            self.send(go_to_lap(slot, lap, 0))

    @Slot(str)
    def goToLap(self, key: str):
        """Replay goes to start of a lap (asked) of car, camera on car"""
        car = self.car_of(key)
        if car is None or self.state != REPLAY:
            return
        lap, accepted = QInputDialog.getInt(self._window, tr("Go to lap"), trm(f"Lap of {car.driver}:"),
                                            car.laps + 1, 1, max(car.laps + 1, 1))
        if accepted:
            self.selectCar(key)
            self.send(go_to_lap(car.slot, lap, self.seconds_before))

    def car_of(self, key: str) -> Standing | None:
        return next((car for car in self.standings if str(car.slot) == key), None)

    def update_standings(self):
        """Standings rows: position (class position), car, laps & times, gap, status, camera, incidents"""
        counts: dict[str, int] = {}
        for car in self.standings:
            counts[car.car_class] = counts.get(car.car_class, 0) + 1
        class_list = [{"name": name, "color": class_color(name), "count": count} for name, count in counts.items()]
        if class_list != self.class_list:
            self.class_list = class_list
            self.classesChanged.emit()
        if self.class_filter and self.class_filter not in counts:
            self.class_filter = ""
        focused = self.focused_slot()
        incidents = self.incident_counts()
        race = self.session_name.upper().startswith("RACE")
        leader_best = min((car.best for car in self.standings if car.best > 0), default=0.0)
        fastest = {car.car_class: min((other.best for other in self.standings
                                       if other.car_class == car.car_class and other.best > 0), default=0.0)
                   for car in self.standings}
        class_positions: dict[str, int] = {}
        rows = []
        for car in self.standings:
            class_positions[car.car_class] = class_positions.get(car.car_class, 0) + 1
            if self.class_filter and car.car_class != self.class_filter:
                continue
            status, tone = status_text(car)
            rows.append({
                "key": str(car.slot),
                "position": car.position,
                "classPosition": class_positions[car.car_class],
                "number": car.number,
                "driver": car.driver,
                "vehicle": car.team or car.vehicle,
                "carClass": car.car_class,
                "classColor": class_color(car.car_class),
                "laps": car.laps,
                "best": lap_text(car.best),
                "last": lap_text(car.last),
                "gap": gap_text(car, race, leader_best),
                "energy": energy_text(car)[0],
                "energyLevel": energy_text(car)[1],
                "pits": car.pitstops,
                "status": status,
                "statusTone": tone,
                "penalties": car.penalties,
                "onCamera": car.slot == focused,
                "player": car.player,
                "fastest": car.best > 0 and car.best == fastest.get(car.car_class),
                "incidents": incidents.get(car.driver, 0),
                "brandLogo": self.logos.brand(car.vehicle),
            })
        self._standings_model.sync(rows)
        if self.selected_car and self.selected_car not in {row["key"] for row in rows}:
            self.selected_car = ""
        self.standingsChanged.emit()
        self.lapsChanged.emit()  # car followed by camera may have changed
        self.update_map_cars()

    # Track map
    @Property(int, notify=revisionChanged)
    def mapRevision(self) -> int:
        return self.revision

    @Property(dict, notify=mapChanged)
    def mapView(self) -> dict:
        """Map bounds & vertex keys, {} if no map"""
        if not self.map_center:
            return {}
        xs = [point[0] for point in self.map_center + self.map_pit]
        ys = [point[1] for point in self.map_center + self.map_pit]
        return {"minX": min(xs), "minY": min(ys), "maxX": max(xs), "maxY": max(ys),
                "road": self.prefix + "road", "edge": self.prefix + "edge", "pit": self.prefix + "pit"}

    @Property(QObject, constant=True)
    def mapCars(self) -> DictListModel:
        """Cars on map: key (slot), map x & y, color, number, driver, position, followed by camera, player, in pits
        (rows kept by slot: cars move smoothly)"""
        return self._map_model

    def update_map_cars(self):
        focused = self.focused_slot()
        self._map_model.sync([{
            "key": str(car.slot), "mapX": car.x, "mapY": car.y, "color": class_color(car.car_class),
            "number": car.number or str(car.position), "driver": car.driver, "position": car.position,
            "onCamera": car.slot == focused, "player": car.player, "inPit": car.in_pit or car.garage,
        } for car in self.standings if car.x or car.y])

    def set_map(self, track: str, points: tuple[list, list] | None):
        """Track map of game (center path & pit lane), lines built for map scale"""
        self.map_track = track
        self.map_center, self.map_pit = points if points else ([], [])
        if len(self.map_center) < 3:
            self.map_center, self.map_pit = [], []
        self.build_map()
        self.mapChanged.emit()

    @Slot(float)
    def setMapScale(self, meters_per_pixel: float):
        """Map zoom settled: lines with a minimum pixel width rebuilt"""
        meters_per_pixel = max(meters_per_pixel, 1e-3)
        if abs(meters_per_pixel - self.meters_per_pixel) > 1e-6:
            self.meters_per_pixel = meters_per_pixel
            self.build_map()

    def build_map(self):
        if not self.map_center:
            VertexStore.remove_prefix(self.prefix)
        else:
            xs = [point[0] for point in self.map_center]
            ys = [point[1] for point in self.map_center]
            closed = abs(xs[0] - xs[-1]) + abs(ys[0] - ys[-1]) < 500
            road = max(ROAD_WIDTH, 4 * self.meters_per_pixel) / 2
            VertexStore.set(self.prefix + "road", band(xs, ys, road, closed))
            VertexStore.set(self.prefix + "edge", band(xs, ys, road + max(2.0, 1.5 * self.meters_per_pixel), closed))
            if self.map_pit:
                VertexStore.set(self.prefix + "pit", band([point[0] for point in self.map_pit],
                                                          [point[1] for point in self.map_pit],
                                                          max(PIT_WIDTH, 2 * self.meters_per_pixel) / 2))
        self.revision += 1
        self.revisionChanged.emit()
