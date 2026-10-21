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
Game Replays page state (LMU): replays saved by the game (watch in game, add, export, rename, protect,
delete to the recycle bin, clean up), playback, camera & HUD of the replay open in game, incidents,
standings & track map of the session, jump to an incident (a live session goes to its replay) with the
camera on a car, go to a lap of a car

Everything goes through the game Rest API in background (see game_rest): the game must be running,
replay state, incidents & standings need a session (or a replay) loaded in game. Game asked only while page
shown, with one connection per request: less often when game does not answer, more often while a replay is
open (camera car & replay time), standings only while shown (or a replay open, or incidents name new drivers).
Track map shown: car positions read 10 times a second from the shared memory of the game (as Broadcast Director),
moved along the track between game answers when not readable.

Page made of parts (mixins sharing the page state & signals, see replays_base.ReplaysBase): replays_list (list,
selection, watch in game), replays_folder (replay files), replays_playback (playback, camera & HUD),
replays_incidents, replays_standings (standings & laps), replays_map (track map); plain helpers & work on a
game connection in replays_common.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Property, QDateTime, QTime, QTimer, Slot
from PySide6.QtWidgets import QFileDialog, QInputDialog  # noqa: F401  (re-exported: tests patch their dialogs)

from ... import game_rest
from ...adapter.restapi_connector import AppendedListDecoder
from ...game_rest import GameConnection, GameRequest
from ...i18n import tr, trm
from ...process.game_info import (
    CarInfo,
    Contact,
    ContactsParser,
    GameReplay,
    Incident,
    Standing,
    merge_contacts,
    parse_replays,
    standings_time,
)
from .._common import BaseDialog
from . import page_settings
from .formatting import clock_seconds, date_text, day_text  # noqa: F401  (date_text & day_text re-exported)
from .game_camera import (  # noqa: F401  (CAMERAS & camera_group re-exported)
    CAMERAS,
    Command,
    camera_group,
    click_game_ui,
)
from .game_pictures import LogoCache, notifier
from .lines import VertexStore
from .models import DictListModel
from .page_backend import PageBackend
from .replays_base import ReplaysBase
from .replays_common import (  # noqa: F401  (re-exported: replays_backend.size_text...)
    ACTION_SETTLE,
    ACTION_WAIT,
    ACTIVE_RESOURCE,
    CAMERA_RESOURCE,
    CTRL,
    EVENT_TYPES,
    FOCUS_RESOURCE,
    FOLDER_RESOURCE,
    HUD_LABELS,
    HUD_RESOURCE,
    IDLE_REFRESH_MS,
    INCIDENT_FILTERS,
    INCIDENTS_RESOURCE,
    JUMP,
    LAP_SEARCH_STEPS,
    LIVE_MS,
    MAX_GO_TO_LAP,
    MAX_PATH_SPEED,
    MENU,
    OFF_TRACK,
    OFFLINE,
    PANELS,
    PAUSE,
    PIT_WIDTH,
    PLAY,
    PLAYBACK,
    PLAYBACK_COMMANDS,
    REFRESH_MS,
    REPLAY,
    REPLAY_REFRESH_MS,
    REPLAY_WAIT,
    REPLAYS_MAX_AGE,
    REPLAYS_RESOURCE,
    ROAD_WIDTH,
    SECONDS_BEFORE,
    SESSION,
    SESSION_END_DELAY_MS,
    SESSION_FILTERS,
    SESSION_RESOURCE,
    SESSIONS,
    SET_CAMERA_RESOURCE,
    SETTINGS_FILE,
    SHIFT,
    SORTS,
    STANDINGS_RESOURCE,
    STATE_TEXTS,
    TOGGLE_REPLAY_RESOURCE,
    TOP_DRIVERS,
    TRACKMAP_RESOURCE,
    ReplayAction,
    ask_state,
    car_text,
    clock_text,
    copy_reporter,
    energy_text,
    enter_replay,
    event_type_text,
    fetch_replays,
    file_size,
    gap_text,
    go_to_lap,
    incident_key,
    lap_seconds,
    lap_text,
    leave_replay,
    load_page_settings,
    move_selection,
    play_replay,
    send_commands,
    session_text,
    size_text,
    timeline_end,
)
from .replays_folder import ReplaysFolder
from .replays_incidents import ReplaysIncidents
from .replays_list import ReplaysList
from .replays_map import ReplaysMap
from .replays_playback import ReplaysPlayback
from .replays_standings import ReplaysStandings
from .track_path import TrackPath


class GameReplaysBackend(ReplaysList, ReplaysFolder, ReplaysPlayback, ReplaysIncidents, ReplaysStandings,
                         ReplaysMap, PageBackend):
    """Game Replays page state (QML context property "backend")"""

    def __init__(self, parent: BaseDialog):
        super().__init__(parent, "Game replays")
        self._window = parent
        self.prefix = f"game_replays_{id(self)}|"
        settings = load_page_settings()
        self.page_file = page_settings.PageSettings(SETTINGS_FILE, page_settings.SAVE_DELAY_MS, self)
        self.replays: list[GameReplay] = []
        self.replays_time = 0.0  # monotonic time of replays list answer, 0 if never
        self.replays_answered = False
        self.pending_watch = ""  # replay to open once game lists it (race results page)
        self.pending_action: ReplayAction | None = None  # replay to open with what it does once game lists it
        self.action: ReplayAction | None = None  # done once replay opened by page is open in game
        self.action_deadline = 0.0  # monotonic time action is given up
        self.action_generation = 0  # state answers asked before replay was opened ignored for action
        self.state_generation = 0
        self.action_after = 0.0  # monotonic time from which action may be done (replay loaded by game)
        self.play_command: Command | None = None  # replay open command of action, until game answered it
        self.sending: tuple[Command, ...] = ()  # batch of commands being sent
        self.playing = ""  # replay opened from page (game tells no name): open again only if another one
        self.play_sent: Command | None = None  # open command of playing, until game answered it (refused: forgotten)
        self.results_links: dict[str, str] = {}  # replay name: results file of its session (race results page)
        self.folder = ""  # replay folder of game, kept when game closes
        self.temp: list[str] = []  # temporary files of game in replay folder
        self.protected: set[str] = {str(name) for name in settings.get("protected", []) if isinstance(name, str)}
        self.state = OFFLINE
        self.updated = ""
        self.last_session = False  # incidents & standings of a session left (game in menus)
        self.incidents: tuple[Incident, ...] = ()
        self.contacts: tuple[Contact, ...] = ()
        # Incidents (growing list): only entries added since last answer decoded & parsed
        self._decode_incidents = AppendedListDecoder()
        self._contacts_of = ContactsParser()
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
        self._folder_info: tuple[tuple, dict] | None = None  # (replays, temp, protected) it was made from, info
        # Values told to QML, made when what they come from changes (getters only return them, signals only
        # emitted when they change)
        self.checked_summary = ""  # replays selected & their size: "3 · 412 MB"
        self.selected_protected = False
        self._counts: dict[str, int] = {"all": 0, "cars": 0, "walls": 0, "mine": 0, "shown": 0}
        self._incident_view: tuple | None = None  # what incidentsChanged last told
        self._incident_counts: tuple[tuple, dict[str, int]] = ((), {})  # (incidents counted, incidents of drivers)
        self._markers_from: tuple | None = None  # (incidents, player, keys listed) timeline markers made from
        self._last_incident: tuple[tuple, float] = ((), 0.0)  # (incidents, time of last one)
        self.timeline_end = timeline_end(0.0, -1.0, -1.0)  # seconds: session span of timeline
        self.car_count = 0
        self.has_energy = False
        self._lap_view: tuple | None = None  # what lapsChanged last told
        self.copy_kind = "add"  # add (to game folder) or export
        self.copy_cancel = threading.Event()
        self.trash_progress = -1.0  # files being moved to the recycle bin: 0 to 1, -1 if none
        self.trash_kind = "replays"  # replays or temp (temporary files of game)
        self.trash_kept = 0  # protected replays left out of the deletion running (told once done)
        self.trash_cancel = threading.Event()
        self.notice = ""
        self.notice_error = False
        self.notice_count = 0
        self.map_track: str | None = None  # track of map loaded, None if none
        self.map_center: list[tuple[float, float, float]] = []
        self.map_pit: list[tuple[float, float, float]] = []
        self.meters_per_pixel = 1.0
        self.revision = 0
        self._shown = False
        # Selection is a role of rows (changed rows told), never compared to the selected key in every delegate
        self._replays_model = DictListModel(
            ("key", "track", "code", "session", "sessionLabel", "event", "eventType", "section", "date",
             "size", "tip", "checked", "selected", "isProtected", "trackLogo", "hasResults"), self)
        self._incidents_model = DictListModel(
            ("key", "time", "timeText", "driver", "other", "wall", "mine", "count", "driverCar", "otherCar",
             "focused", "selected"), self)
        # Timeline markers (every incident, hundreds in long races) & driver chips: synced in place, markers kept
        self._markers_model = DictListModel(("key", "time", "wall", "mine", "shown", "label", "selected"), self)
        self._chips_model = DictListModel(("name", "incidents", "mine", "car"), self)
        self._standings_model = DictListModel(
            ("key", "position", "classPosition", "number", "driver", "vehicle", "carClass", "classColor", "classAlias", "laps",
             "best", "last", "gap", "pits", "status", "statusTone", "penalties", "onCamera", "player", "fastest",
             "incidents", "energy", "energyLevel", "brandLogo", "selected"), self)
        self._map_model = DictListModel(
            ("key", "mapX", "mapY", "color", "number", "driver", "position", "onCamera", "player", "inPit",
             "onTrack", "pathS", "speed", "sampleTime", "correction", "receivedMs"), self)
        self.track_path: TrackPath | None = None
        self._car_tracks: dict[int, tuple] = {}  # slot: s, sample time, speed, segment, easing, received ms
        self._direction = 1.0  # cars drive toward increasing path distance (+1) or decreasing (-1)
        self.map_live: dict[str, list[float]] = {}  # slot: map x & y read from shared memory, {} if not read
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(LIVE_MS)
        self._live_timer.timeout.connect(self.read_live_positions)
        self.logos = LogoCache()
        notifier().changed.connect(self.pictures_changed)
        self.request_replays = GameRequest(self, (), self.received_replays)
        self.request_state = GameRequest(self, (), self.received_state, self.schedule_state)
        self.request_command = GameRequest(self, (), self.command_done, self.command_failed)
        self.request_copy = GameRequest(self, (), self.copy_done, self.copy_failed)
        self.request_trash = GameRequest(self, (), self.trash_done, self.trash_failed)
        self.command_queue: list[tuple[Command, ...]] = []  # commands waiting for the one sent
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
        self.update_live_timer()

    def page_hidden(self):
        self._shown = False
        self._timer.stop()
        self.update_live_timer()

    def release_resources(self):
        self.page_hidden()
        self.copy_cancel.set()
        self.page_file.flush()
        VertexStore.remove_prefix(self.prefix)

    def notify(self, text: str, error: bool = False):
        """Message shown for a few seconds at the bottom of page"""
        self.notice, self.notice_error = text, error
        self.notice_count += 1
        self.noticeChanged.emit()

    def save_settings(self):
        """Settings written once changes pause (number arrows held: one write)"""
        self.page_file.save(self.page_settings())

    def page_settings(self) -> dict[str, Any]:
        return {
            "seconds_before": self.seconds_before, "panel": self.panel, "sort": self.sort,
            "session_filter": self.session_filter, "incident_filter": self.incident_filter,
            "protected": sorted(self.protected),
        }

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
        decode, contacts_of = self._decode_incidents, self._contacts_of
        generation = self.state_generation
        self.request_state.start(lambda: {**self.connected(
            lambda connection: ask_state(connection, previous, known, want_standings, map_track, decode, contacts_of)),
            "generation": generation})

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
            self.watch_pending()
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
        self.watch_pending()

    def received_state(self, state: dict):
        if state.get("generation", self.state_generation) < self.state_generation:  # asked before a replay opened
            self.schedule_state()
            return
        active = state["active"]
        if active is None:  # session left: its incidents & standings kept until next one
            self.set_state(MENU if state["running"] else OFFLINE)
            if not state["running"]:
                self.replays_answered = False
            if (self.incidents or self.standings) and not self.last_session:
                self.last_session = True
                self.statusChanged.emit()
            self.update_replay_time(-1.0)
            self.check_action(state)
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
            self.update_timeline_end()
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
        self.check_action(state)
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
                self.laps_changed()
        if state != REPLAY:
            self.last_command = ""
            self.rewatching = False
            self.playing = ""
            self.playbackChanged.emit()
        if previous in (SESSION, REPLAY) and state == MENU:  # session ended: game saved its replay
            QTimer.singleShot(SESSION_END_DELAY_MS, self, self.ask_replays)  # context: never after page freed
        self.update_live_timer()
        self.statusChanged.emit()

    def mark_updated(self):
        updated = trm("Updated from game at {}").replace("{}", clock_seconds(), 1)
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
        self.update_timeline_end()

    def command_done(self, accepted: bool):
        if self.play_sent is not None and self.play_sent in self.sending:
            self.play_sent = None
            if not accepted:  # replay not opened: never taken as open by a later action (done without asking)
                self.playing = ""
        if self.play_command is not None and self.play_command in self.sending:  # replay of action opening
            self.play_command = None
            if accepted:
                self.state_generation += 1  # standings of replay open before never used for action
                self.action_generation = self.state_generation
                self.action_after = time.monotonic() + ACTION_SETTLE
            else:
                self.action = None
        self.sending = ()
        if not accepted:
            self.notify(tr("Game did not accept the command"), True)
        if self.command_queue:
            self.send()
        elif self._shown:
            self._timer.stop()
            self.refresh_state()

    def command_failed(self):
        """Command job raised (error logged): same as refused, queued commands still sent"""
        self.command_done(False)

    def send(self, *commands: Command):
        """Commands to game in background, in order (stops at first refused), after commands sent before"""
        if commands:
            self.command_queue.append(commands)
        if self.request_command.busy or not self.command_queue:
            return
        batch = self.command_queue.pop(0)
        self.sending = batch
        self.request_command.start(lambda: send_commands(batch))

    # Status
    @Property(str, notify=ReplaysBase.statusChanged)
    def gameState(self) -> str:
        """offline, menu, session or replay"""
        return self.state

    @Property(str, notify=ReplaysBase.statusChanged)
    def statusText(self) -> str:
        return tr(STATE_TEXTS[self.state])

    @Property(str, notify=ReplaysBase.updatedChanged)
    def updatedText(self) -> str:
        return self.updated

    @Property(bool, notify=ReplaysBase.statusChanged)
    def replayActive(self) -> bool:
        return self.state == REPLAY

    @Property(bool, notify=ReplaysBase.statusChanged)
    def inSession(self) -> bool:
        return self.state in (SESSION, REPLAY)

    @Property(bool, notify=ReplaysBase.statusChanged)
    def lastSession(self) -> bool:
        """Incidents & standings shown are those of the session left"""
        return self.last_session

    @Property(bool, notify=ReplaysBase.statusChanged)
    def loading(self) -> bool:
        """Replays list asked to game, no answer yet"""
        return self.request_replays.busy

    @Property(str, notify=ReplaysBase.noticeChanged)
    def noticeText(self) -> str:
        return self.notice

    @Property(bool, notify=ReplaysBase.noticeChanged)
    def noticeError(self) -> bool:
        return self.notice_error

    @Property(int, notify=ReplaysBase.noticeChanged)
    def noticeCount(self) -> int:
        """Changes with each message, same text again included"""
        return self.notice_count

    # Kept on the page module: file_size & click_game_ui looked up here (tests patch them on replays_backend)
    def temp_size(self) -> str:
        return size_text(sum(file_size(path) for path in self.temp))

    @Slot()
    def toggleGameUi(self):
        """Whole game UI (top bar, standings, replay bar & HUD) shown or hidden, as a middle click in game does
        (no Rest API command for its web panels): middle click posted to game window"""
        if self.state not in (SESSION, REPLAY):
            return
        if not click_game_ui():
            self.notify(tr("Game window not found: LMU must be running on this computer."), True)
            return
        if self._shown:  # game shows or hides its HUD parts too: asked again once done
            QTimer.singleShot(700, self, self.refresh_state)  # context: never after page freed
