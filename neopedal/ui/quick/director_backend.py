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
Broadcast Director page state (LMU, qml/BroadcastDirector.qml): camera desk, director & commentator screen

The game is asked about once a second while the page is open (shown or not: the director keeps cutting while
another page is looked at): standings, contacts, camera & car followed, session time. Race events & battles
come from process/director.RaceWatcher, shots from process/director.Director. Modes: manual (operator cuts
only), assisted (stories worth showing listed, taken in one click), automatic (director cuts by itself,
an operator cut holds it a while). Live session (driving or spectating) and replays alike.

Parts of the page (child QObjects, QML: backend.<part>, settings & texts in director_shared):
game (director_game: state requests, connection), camera (director_camera: camera, HUD, playback, commands sent),
graphics (director_graphics: broadcast graphics, on demand graphics, branding), timing (director_timing: timing
table), log (director_log: events log). The page keeps the session state, the director & its cuts, the lists of
the commentator screen and the car sheet; it owns the jobs, the page settings file & release of its parts.
"""

from __future__ import annotations

import time
import weakref
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Property, QCoreApplication, QObject, QTimer, Signal, Slot

from ... import app_signal
from ...i18n import tr
from ...process import director as dr
from ...process.driver_history import history as driver_history
from ...process.game_info import IMMOVABLE, Contact, SessionState, Standing, merge_contacts
from ...setting import cfg
from . import game_camera as gc
from . import page_settings
from .director_camera import CameraDesk
from .director_game import GameStatePoll
from .director_graphics import BroadcastGraphics
from .director_log import EventsLog
from .director_shared import (
    BATTLE_ROLES,
    CAMERA_STYLE_TEXTS,
    CAR_ROLES,
    CLASS_ROLES,
    COMMENTARY_TABS,
    FEED_FILTERS,
    FEED_KINDS,
    FEED_ROLES,
    FOCUS_GRACE,
    GAME_FOCUS,
    HISTORY_EVERY,
    INCIDENT_KINDS,
    INSTANT_LIMIT,
    KIND_GLYPHS,
    KIND_TEXTS,
    KIND_TONES,
    LAP_ROLES,
    MENU,
    MODES,
    OFFLINE,
    PIT_ROLES,
    POST_ROLL,
    RADAR_ROLES,
    RECENT,
    REPLAY,
    SAVE_DELAY_MS,
    SECONDS_BEFORE,
    SESSION,
    SESSION_TEXTS,
    SETTINGS_FILE,
    SHEET_LIVE,
    STATE_TEXTS,
    SUGGESTION_ROLES,
    SUGGESTIONS,
    car_label,
    class_alias,
    class_color,
    clock_text,
    fold,
    gap_tone,
    interval,
    interval_text,
    lap_text,
    load_page_settings,
    localized,
    number_setting,
    parse_forecast,
    read_tyres,
    scan_history,
    seconds_text,
    sector_tone,
    status_text,
    temperature_text,
)
from .director_timing import TimingTable
from .game_pictures import LogoCache, car_picture_url, notifier
from .models import DictListModel
from .page_backend import PageBackend

_active: weakref.ReferenceType | None = None  # director of open page (hotkeys)


def director_page() -> DirectorBackend | None:
    """Director of the Broadcast Director page if open, turned on or off"""
    return _active() if _active is not None else None


def active_director() -> DirectorBackend | None:
    """Director of the Broadcast Director page if open & turned on"""
    director = director_page()
    return director if director is not None and director.enabled else None


def director_status() -> str:
    """"on" (page open, director on), "off" (page open, turned off), "" (page closed): rail dot, notification"""
    director = director_page()
    return "" if director is None else "on" if director.enabled else "off"


class DirectorBackend(PageBackend):
    """Broadcast Director page state (QML context property "backend"), parts as QML properties (backend.timing...)"""

    statusChanged = Signal()
    clockChanged = Signal()
    modeChanged = Signal()
    settingsChanged = Signal()
    onAirChanged = Signal()
    carsChanged = Signal()
    classFilterChanged = Signal()
    suggestionsChanged = Signal()
    feedChanged = Signal()
    battlesChanged = Signal()
    classesChanged = Signal()
    pitsChanged = Signal()
    sheetChanged = Signal()
    noticeChanged = Signal()
    lockChanged = Signal()
    instantChanged = Signal()
    weatherChanged = Signal()
    forecastChanged = Signal()
    lapsChanged = Signal()
    pitRadarChanged = Signal()
    sheetCarChanged = Signal()
    sheetLiveChanged = Signal()
    unseenChanged = Signal()
    feedFilterChanged = Signal()
    enabledChanged = Signal()

    # Parts of the page: QML properties (backend.timing.timingRows...), typed for Python callers
    if TYPE_CHECKING:
        game: GameStatePoll
        camera: CameraDesk
        graphics: BroadcastGraphics
        timing: TimingTable
        log: EventsLog
    else:
        game = Property(QObject, lambda self: self._game, constant=True)
        camera = Property(QObject, lambda self: self._camera, constant=True)
        graphics = Property(QObject, lambda self: self._graphics, constant=True)
        timing = Property(QObject, lambda self: self._timing, constant=True)
        log = Property(QObject, lambda self: self._log, constant=True)

    def __init__(self, parent: QObject):
        global _active
        super().__init__(parent, "Broadcast director")
        settings = load_page_settings()
        saved_mode = settings.get("mode")
        # Automatic cuts never start by themselves: page opens assisted when it was left automatic
        self.mode = "assist" if saved_mode == "auto" or saved_mode not in MODES else str(saved_mode)
        style = settings.get("camera_style")
        self.director = dr.Director(dr.DirectorSettings(
            min_shot=number_setting(settings, "min_shot", 8.0, 3.0, 60.0),
            max_shot=number_setting(settings, "max_shot", 30.0, 5.0, 300.0),
            battle_gap=number_setting(settings, "battle_gap", 1.0, 0.2, 3.0),
            camera_style=str(style) if style in dr.CAMERA_STYLES else "mixed",
        ))
        self.director.settings.max_shot = max(self.director.settings.max_shot, self.director.settings.min_shot)
        self.watcher = dr.RaceWatcher(self.director.settings.battle_gap)
        self.follow_overlays = settings.get("follow_overlays") is True
        self.seconds_before = int(number_setting(settings, "seconds_before", SECONDS_BEFORE, 0, 60))
        self.post_roll = int(number_setting(settings, "post_roll", POST_ROLL, 0, 60))
        # Car chosen in the game (or by another app): operator cut holding the director, or just followed
        self.follow_game_cuts = settings.get("follow_game_cuts") is not False
        # Director turned off (page switch): game never asked, no cut, graphics empty, hotkeys as page closed
        self._enabled = settings.get("enabled") is not False
        self.is_open = True  # page not closed yet (release)
        self._shown = False
        self.tyres: dict[int, tuple[str, str]] = {}
        self.forecast: list[dict] = []
        self.logos = LogoCache()
        # Parts (children: deleted with the page, stopped by release_resources), their settings from the same file
        self._game = GameStatePoll(self, settings)
        self._camera = CameraDesk(self)
        self._graphics = BroadcastGraphics(self, settings)
        self._timing = TimingTable(self, settings)
        self._log = EventsLog(self, settings)
        self.page_file = page_settings.PageSettings(SETTINGS_FILE, SAVE_DELAY_MS, self, self.page_settings)
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.app_quitting)
        self.commentary_tab = 0  # commentator screen tab shown: lists of other tabs made once shown
        self._tabs_stale: set[str] = set()
        self._battle_count = 0
        self._sectors: tuple[list[Standing], tuple[dict, dict]] | None = None  # best sectors of the last answer
        self._camera_styles: list[str] | None = None
        self._unseen = 0
        self.instant_event: dr.Event | None = None  # event of the instant replay shown
        self._history_asked = False  # race results files read once the director is on (see read_history)
        if self._enabled:
            self.read_history()
        self.session_end = -1.0
        notifier().changed.connect(self.pictures_changed)
        self.search_words: list[str] = []
        self._stale = False  # answers came while page hidden: models refreshed when shown
        self._fronts: dict[int, Standing] = {}  # car ahead in class of each car (slot), each answer
        self._grid: dict[int, int] = {}  # class place on starting grid of each car (slot), each answer
        self._texts: dict[str, tuple[str, str]] = {}  # event key: title & detail
        self._laps_view: tuple | None = None  # what lap rows were made from
        self._feed_view: tuple | None = None  # what feed rows were made from
        self.locked = False  # car on air kept: director does not cut
        self.seen: set[str] = set()  # incidents looked at (shown on air, replayed, clicked)
        self.instant = False  # instant replay of a live session shown
        self.instant_waiting = False  # instant replay asked, not playing yet
        self.session_info = SessionState()
        self.laps_slot = -1  # car of lap history shown, -1 if none
        self._weather: list[str] = []
        notes = settings.get("notes")
        self.notes: dict[str, str] = ({str(key): str(value) for key, value in notes.items() if value}
                                      if isinstance(notes, dict) else {})
        self.state = OFFLINE
        self.session_key: tuple[str, str, float] = ("", "", 0)
        self.session_time = -1.0
        self.time_received = 0.0  # time.time() of session time
        self.replay_rate = 0.0
        self.track_length = 0.0
        self.standings: list[Standing] = []
        self.by_slot: dict[int, Standing] = {}
        self.places: dict[int, int] = {}
        self.contacts: tuple[Contact, ...] = ()
        self.incident_counts: dict[str, int] = {}
        self.events: list[dr.Event] = []  # oldest first
        self.event_index: dict[str, dr.Event] = {}
        self._events_revision = 0  # bumped when events change (feed made again, even at feed limit)
        self.candidates: list[dr.Candidate] = []
        self.focus = -1  # car followed by camera (game)
        self.last_cut = 0.0  # monotonic time of last cut sent
        self.on_air_slot = -1  # car on air (director or operator), -1 if none
        self.on_air_kind = ""
        self.on_air_start = 0.0  # time.time() shot started
        self.selected = -1  # car of sheet
        self.class_filter = ""
        self.feed_filter = 0
        self.notice = ""
        self.notice_error = False
        self._cars_model = DictListModel(CAR_ROLES, self)
        self._feed_model = DictListModel(FEED_ROLES, self)
        self._suggestions_model = DictListModel(SUGGESTION_ROLES, self)
        self._battles_model = DictListModel(BATTLE_ROLES, self)
        self._classes_model = DictListModel(CLASS_ROLES, self)
        self._pits_model = DictListModel(PIT_ROLES, self)
        self._laps_model = DictListModel(LAP_ROLES, self)
        self._class_list: list[dict] = []
        self._on_air: dict[str, Any] = {}  # card of the car on air & its pit radar (radar has its own model)
        self._radar_model = DictListModel(RADAR_ROLES, self)
        self._sheet: dict[str, Any] = {}  # car sheet: every value (Python), QML binds sheetCar & sheetLive
        self._sheet_car: dict[str, Any] = {}
        self._sheet_live: dict[str, Any] = {}
        self._hold = (0.0, 0.0)  # director hold (monotonic), same as time.time()
        self._instant_timer = QTimer(self)  # instant replay over: back to live
        self._instant_timer.setSingleShot(True)
        self._instant_timer.timeout.connect(self.backToLive)
        _active = weakref.ref(self)

    @property
    def shown(self) -> bool:
        """Page shown (hidden: director & watcher go on, lists made again once shown)"""
        return self._shown

    @property
    def is_enabled(self) -> bool:
        """Director on (QML: enabled)"""
        return self._enabled

    # Page
    def page_shown(self):
        """Game asked at once; then about every second until the page closes (hidden too: director runs)"""
        self._shown = True
        if self._stale:
            self.refresh_models()
        self._timing.page_shown()
        game = self._game
        if not game.request_state.busy:
            game.refresh()

    def page_hidden(self):
        self._shown = False

    def release_resources(self):
        global _active
        self._graphics.release()  # last graphics setting change sent
        self.flush_settings()
        self.is_open = False
        self._game.stop()
        self._instant_timer.stop()
        self._camera.stop()  # events log lines still written in background: page never waits (see WRITER)
        self._history_asked = False
        driver_history.clear()  # race history of every driver (up to MAX_FILES files) read again once opened
        if _active is not None and _active() is self:
            _active = None
            from ...stream_director import director_feed, live_feed

            # No more updates: broadcast graphics emptied (as director off), never left frozen on air
            director_feed.clear()
            live_feed.clear()

    def refresh_models(self):
        """Every list & card of the page made again from the last answer (lists of hidden tabs once shown)"""
        self._stale = False
        self.update_feed()
        self.update_suggestions()
        self.update_laps()
        self.update_cars()
        self.update_tabs()
        self.update_sheet()
        self.update_on_air()

    def update_tabs(self):
        """Lists of the commentator tab shown made again, others marked stale (battle count told anyway)"""
        self._tabs_stale.update(COMMENTARY_TABS[1:])  # events: feed made apart (unseen count, filter)
        self.fresh_tab(COMMENTARY_TABS[self.commentary_tab])
        if len(self.watcher.battles) != self._battle_count:
            self._battle_count = len(self.watcher.battles)
            self.battlesChanged.emit()

    def fresh_tab(self, name: str):
        """List of a tab made again if answers came while it was hidden"""
        if name in self._tabs_stale:
            self._tabs_stale.discard(name)
            getattr(self, f"update_{name}")()

    @Slot(int)
    def setCommentaryTab(self, index: int):
        """Commentator screen tab shown: its list made at each answer (others once shown again)"""
        if 0 <= index < len(COMMENTARY_TABS) and index != self.commentary_tab:
            self.commentary_tab = index
            self.fresh_tab(COMMENTARY_TABS[index])

    def save_settings(self):
        """Settings written once changes pause (number arrows held: one write)"""
        self.page_file.save()

    def flush_settings(self):
        """Settings changed written now (page closing, app quitting)"""
        self.page_file.flush()

    def app_quitting(self):
        """Settings & events log lines not written yet written (app closing with the page open)"""
        self.flush_settings()
        self._log.flush()

    def page_settings(self) -> dict[str, Any]:
        settings = self.director.settings
        return {
            "mode": self.mode, "min_shot": settings.min_shot, "max_shot": settings.max_shot,
            "battle_gap": settings.battle_gap, "camera_style": settings.camera_style,
            "follow_overlays": self.follow_overlays, "seconds_before": self.seconds_before,
            "post_roll": self.post_roll, "follow_game_cuts": self.follow_game_cuts,
            **self._game.page_settings(), **self._log.page_settings(), **self._graphics.page_settings(),
            "notes": dict(sorted(self.notes.items())), **self._timing.page_settings(), "enabled": self._enabled,
        }

    def notify(self, text: str, error: bool = False):
        self.notice, self.notice_error = text, error
        self.noticeChanged.emit()

    # Game answers
    def received_state(self, state: dict):
        """Answer of the game (GameStatePoll): every part & list made again, next request scheduled last"""
        if not self.is_open or not self._enabled:  # answer of a request sent before the director was turned off
            return
        game, graphics = self._game, self._graphics
        active = state["active"]
        if active is None:
            self.set_state(MENU if state["running"] else OFFLINE)
            game.schedule()
            return
        self.set_state(REPLAY if active else SESSION)
        key = (state["track"], state["session"], state.get("start", 0))
        # Another session (other track or session, or same session started again): everything starts again
        if key[:2] != self.session_key[:2] or (key[2] and self.session_key[2] and key[2] != self.session_key[2]):
            self.session_key = key
            self.new_session()
        self.session_key = key
        self.session_end = state.get("end", -1.0)
        self.track_length = state["length"]
        self.update_clock(state["time"])
        self.standings = state["standings"]
        self._sectors = None
        self.index_cars()
        if state["contacts"] != self.contacts:
            self.contacts = state["contacts"]
            self.incident_counts = self.count_incidents()
        self._camera.answered(state)
        self.update_weather(state["info"])
        if "forecast" in state:
            forecast = parse_forecast(state["forecast"], self.session_key[1])
            if forecast != self.forecast:
                self.forecast = forecast
                self.forecastChanged.emit()
        self.tyres = self.read_tyres() if game.local_game() else {}
        if "trackmap" in state:
            graphics.set_track(state["trackmap"])
        if self.instant:  # instant replay: replay frames are not the race going on, director waits
            if self._shown:
                self.update_cars()
                self.update_on_air()
            graphics.publish_graphics()
            game.schedule()
            return
        self.follow_game_focus(state["focus"] if state["focus"] >= 0
                               else next((car.slot for car in self.standings if car.focus), -1))
        new_events = self.watcher.update(self.standings, self.contacts, self.session_time, state["session"],
                                         self.track_length, state["info"])
        self._sectors = None  # laps & sectors seen by the watcher
        if new_events:
            self.add_events(new_events)
        graphics.note_sector_ends()
        graphics.auto_graphics(new_events)
        if game.polls % HISTORY_EVERY == 0:
            self.read_history()
        self.direct()
        if self._shown:  # hidden: director & watcher go on, lists made again once shown
            self.refresh_models()
        else:
            self._stale = True
        self._timing.answered(self._shown)
        graphics.publish_graphics()
        game.schedule()

    @staticmethod
    def read_tyres() -> dict[int, tuple[str, str]]:
        """Tyres of every car while the API reads the game (shared memory)"""
        from ...api_control import api

        reader = getattr(api, "read", None)
        return read_tyres(reader) if reader is not None else {}

    def pictures_changed(self):
        """Car brand logos & pictures arrived from the game"""
        if self._shown:
            self._sheet = self._sheet_car = {}
            self._on_air = {}
            self.update_cars()
            self.update_sheet()
            self.update_on_air()

    def class_fastest(self) -> dict[str, float]:
        """Best lap of each class"""
        fastest: dict[str, float] = {}
        for car in self.standings:
            if car.best > 0 and (fastest.get(car.car_class, 0.0) <= 0 or car.best < fastest[car.car_class]):
                fastest[car.car_class] = car.best
        return fastest

    def index_cars(self):
        """Indexes of the cars of last answer: by slot, class place, car ahead in class, class place on grid"""
        self.by_slot = {car.slot: car for car in self.standings}
        self.places = dr.class_places(self.standings)
        last: dict[str, Standing] = {}
        self._fronts = {}
        for car in self.standings:
            if car.car_class in last:
                self._fronts[car.slot] = last[car.car_class]
            last[car.car_class] = car
        counts: dict[str, int] = {}
        self._grid = {}
        for car in sorted((car for car in self.standings if car.grid > 0), key=lambda item: item.grid):
            counts[car.car_class] = counts.get(car.car_class, 0) + 1
            self._grid[car.slot] = counts[car.car_class]

    def set_state(self, state: str):
        if state == self.state:
            return
        self.state = state
        self._camera.state_changed(state)
        if state in (OFFLINE, MENU) and self.instant:
            self.instant = False
            self.instant_event = None
            self._instant_timer.stop()
            self.instantChanged.emit()
        if state in (OFFLINE, MENU):
            self.candidates = []
            self._suggestions_model.reset([])
            self.suggestionsChanged.emit()
        self.statusChanged.emit()

    def new_session(self):
        self.watcher.reset()
        self._sectors = None
        self.director.reset()
        self.events.clear()
        self.event_index.clear()
        self._events_revision += 1
        self.contacts = ()
        self.incident_counts = {}
        self.on_air_slot = -1
        self.on_air_kind = ""
        self.selected = -1
        self.seen.clear()
        self.laps_slot = -1
        self._texts.clear()
        self._game.need_track = True
        self.instant_event = None
        self._graphics.new_session()
        self.update_unseen()
        self.update_feed()
        self.update_laps()

    def update_clock(self, session_time: float):
        now = time.time()
        if self.session_time >= 0 and session_time >= 0 and now - self.time_received > 0.2:
            rate = (session_time - self.session_time) / (now - self.time_received)
            self.replay_rate = rate if abs(rate) < 50 else 0.0
        self.session_time, self.time_received = session_time, now
        self.clockChanged.emit()

    def count_incidents(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for incident in merge_contacts(self.contacts):
            for name in (incident.driver, incident.other):
                if name != IMMOVABLE:
                    counts[name] = counts.get(name, 0) + 1
        return counts

    def follow_game_focus(self, focus: int):
        """Car followed by game camera: another car chosen in game (or elsewhere) is an operator cut"""
        self.focus = focus
        if focus < 0 or focus == self.on_air_slot or time.monotonic() - self.last_cut < FOCUS_GRACE:
            return
        if self.follow_game_cuts:  # operator in game: director held a while
            self.director.manual(focus, "", time.monotonic())
        elif self.director.shot is not None:  # another app cuts too: car followed, director goes on
            self.director.shot = self.director.shot._replace(slot=focus)
        self.set_on_air(focus, GAME_FOCUS)

    # Director
    def direct(self):
        """Stories worth showing listed, best one cut to in automatic mode"""
        recent = [event for event in self.events[-200:] if self.session_time - event.time <= RECENT]
        clock = time.monotonic()
        race = dr.is_race(self.session_key[1])
        leader = next((car for car in self.standings if car.position == 1), None)
        phase = self.session_info.phase
        start = phase in dr.START_PHASES or (phase == dr.GREEN_PHASE and leader is not None and leader.laps < 1)
        gained = {slot: place - self.places.get(slot, place) for slot, place in self._grid.items()} if race else {}
        self.candidates = self.director.candidates(recent, list(self.watcher.battles.values()), self.standings,
                                                   self.session_time, clock, race, start, self.watcher.severity,
                                                   seen=self.seen, gained=gained)
        if self.mode == "auto" and not self.locked:
            pick = self.director.decide(self.candidates, clock)
            if pick is not None:
                self.cut(self.director.take(pick, clock))
        if self._shown:
            self.update_suggestions()

    def cut(self, shot: dr.Shot):
        """Car & camera of shot on air: commands to game, overlays follow if wanted"""
        camera = self._camera
        commands: list[gc.Command] = []
        if shot.slot != self.focus:
            commands.append(gc.focus_command(shot.slot))
        if shot.camera and shot.camera != camera.camera_key():
            commands.extend(gc.camera_commands(shot.camera))
            camera.trackside_choice = shot.camera if shot.camera.startswith("TRACKSIDE") else ""
        if commands:
            self.last_cut = time.monotonic()
            camera.send(*commands)
        self.focus = shot.slot
        if shot.key in self.event_index and shot.key not in self.seen:
            self.seen.add(shot.key)
            self.update_unseen()
            if self._shown:
                self.update_feed()
        self.set_on_air(shot.slot, shot.kind)
        if self.follow_overlays:
            self.overlays_follow(shot.slot)

    def set_on_air(self, slot: int, kind: str):
        if slot != self.on_air_slot or kind != self.on_air_kind:
            if slot != self.on_air_slot:
                self.on_air_start = time.time()
                self._graphics.new_cut()
            self.on_air_slot, self.on_air_kind = slot, kind
            self._graphics.publish_graphics()
            if self._shown:
                self.update_on_air()
                self.update_cars()

    # Car followed by overlays: written at most every FOLLOW_SAVE_MS (cuts every few seconds in automatic mode)
    # and before preset reload, restart & quit, see save_followed_later
    FOLLOW_SAVE_MS = 30000
    _follow_unsaved = False  # car followed not written yet (any page)
    _follow_save_due = 0.0  # time.monotonic() of the save scheduled, see save_followed_later

    def overlays_follow(self, slot: int):
        """Overlays (stream sources too) show the car on air: spectate mode on that car

        Spectate mode turned on: saved & whole GUI refreshed (notification bar). Another car (each cut): only the
        Spectate page told (spectate_changed), saved later (see save_followed_later).
        """
        from ...api_control import api

        setting = cfg.api
        if setting["player_index"] == slot and setting["enable_player_index_override"]:
            return
        turned_on = not setting["enable_player_index_override"]
        setting["player_index"] = slot
        setting["enable_player_index_override"] = True
        api.setup()
        if turned_on:
            DirectorBackend._follow_unsaved = False
            cfg.save()
            app_signal.refresh.emit(True)
        else:
            self.save_followed_later()
            app_signal.spectate_changed.emit(slot)

    def save_followed_later(self):
        """Car followed written within FOLLOW_SAVE_MS (one save for many cuts), or before preset reload, restart &
        quit (a preset file loaded again would bring back the car saved before)"""
        from ... import loader

        cls = DirectorBackend
        cls._follow_unsaved = True
        now = time.monotonic()
        if now >= cls._follow_save_due:  # none scheduled, or its page deleted before (written by loader anyway)
            cls._follow_save_due = now + cls.FOLLOW_SAVE_MS / 1000
            QTimer.singleShot(cls.FOLLOW_SAVE_MS, self, cls.save_followed)
        loader.on_pending_write(cls.save_followed_now)

    @staticmethod
    def save_followed(delay: int = 66):
        """Car followed by overlays written, if not yet (cfg.save delay)"""
        if DirectorBackend._follow_unsaved:
            DirectorBackend._follow_unsaved = False
            cfg.save(delay)

    @staticmethod
    def save_followed_now():
        """Preset reload, restart or quit: car followed written at once (saving thread waited by interpreter exit)"""
        DirectorBackend.save_followed(0)

    def can_command(self) -> bool:
        return self.state in (SESSION, REPLAY)

    def commands_sent(self, accepted: bool):
        """Commands of the camera desk all sent: instant replay playing, back to live counted from now (game
        refused it: live again at once)"""
        if self.instant_waiting:
            self.instant_waiting = False
            if self.instant and not accepted:
                self.backToLive()
            if self.instant:
                self._instant_timer.start(int((self.seconds_before + self.post_roll) * 1000))

    # Texts
    def event_texts(self, event: dr.Event) -> tuple[str, str]:
        """Title & detail of event, made once (when its cars are known)"""
        texts = self._texts.get(event.key)
        if texts is None:
            texts = self.make_event_texts(event)
            if all(slot in self.by_slot for slot in event.slots):
                self._texts[event.key] = texts
        return texts

    def make_event_texts(self, event: dr.Event) -> tuple[str, str]:
        cars = [self.by_slot.get(slot) for slot in event.slots]
        first = car_label(cars[0] if cars else None, event.drivers[0] if event.drivers else "")
        second = car_label(cars[1] if len(cars) > 1 else None, event.drivers[1] if len(event.drivers) > 1 else "")
        place = f"P{event.position} {event.car_class}".strip() if event.position else event.car_class
        kind = event.kind
        if kind == dr.BATTLE:
            return tr("Battle for P%1").replace("%1", str(event.position)), \
                f"{first} · {second} · {seconds_text(event.value)} · {event.car_class}"
        if kind == dr.OVERTAKE:
            return tr("%1 passes %2").replace("%1", first).replace("%2", second), place
        if kind == dr.LEAD:
            return tr("%1 takes the lead").replace("%1", first), f"{event.car_class} · {second}"
        if kind == dr.CONTACT:
            return tr("Contact: %1 and %2").replace("%1", first).replace("%2", second), \
                tr("%1 contacts").replace("%1", str(int(event.value))) if event.value > 1 else event.car_class
        if kind == dr.WALL:
            return tr("%1 hits the wall").replace("%1", first), event.car_class
        if kind == dr.STOPPED:
            return tr("%1 stopped on track").replace("%1", first), place
        if kind == dr.PIT_IN:
            return tr("%1 enters the pits").replace("%1", first), place
        if kind == dr.PIT_OUT:
            stop = f" · {tr('Stopped %1').replace('%1', seconds_text(event.extra))}" if event.extra > 0 else ""
            return tr("%1 leaves the pits").replace("%1", first), \
                f"{place} · {tr('%1 in pit lane').replace('%1', seconds_text(event.value))}{stop}"
        if kind == dr.FASTEST:
            return tr("Fastest lap: %1").replace("%1", first), f"{lap_text(event.value)} · {event.car_class}"
        if kind == dr.FINISH:
            return tr("%1 finishes").replace("%1", first), place
        if kind == dr.WINNER:
            return tr("%1 wins").replace("%1", first), event.car_class
        if kind == dr.RETIRED:
            text = "%1 disqualified" if event.value > 0 else "%1 retires"
            return tr(text).replace("%1", first), place
        if kind == dr.PENALTY:
            return tr("Penalty for %1").replace("%1", first), \
                tr("%1 pending").replace("%1", str(int(event.value)))
        if kind == dr.SLOW:
            return tr("%1 slow on track").replace("%1", first), place
        if kind == dr.YELLOW:
            return tr("Yellow flag in sector %1").replace("%1", str(int(event.value))), \
                tr("Slowest car: %1").replace("%1", first) if event.slots else ""
        if kind == dr.FCY:
            return tr("Full course yellow"), ""
        if kind == dr.GREEN:
            return tr("Green flag: racing again"), ""
        return first, ""

    def candidate_texts(self, candidate: dr.Candidate) -> tuple[str, str]:
        if candidate.event is not None:
            return self.event_texts(candidate.event)
        car = self.by_slot.get(candidate.slot)
        if candidate.battle is not None:
            battle = candidate.battle
            ahead = self.by_slot.get(battle.ahead)
            return tr("Battle for P%1").replace("%1", str(battle.position)), \
                f"{car_label(car)} → {car_label(ahead)} · {seconds_text(battle.gap)}"
        place = self.places.get(candidate.slot, 0)
        if candidate.kind == dr.START:
            return tr("Race start: %1 leads").replace("%1", car_label(car)), \
                f"P{place} {car.car_class}" if car is not None else ""
        return car_label(car), f"P{place} {car.car_class}" if car is not None else ""

    # Models
    def add_events(self, events: list[dr.Event]):
        added = False
        for event in events:
            if event.key in self.event_index:
                continue
            self.event_index[event.key] = event
            self.events.append(event)
            added = True
        if added:
            self._events_revision += 1
        if len(self.events) > dr.FEED_LIMIT:
            for event in self.events[:-dr.FEED_LIMIT]:  # texts & looked at mark dropped with the event
                self.event_index.pop(event.key, None)
                self._texts.pop(event.key, None)
                self.seen.discard(event.key)
            del self.events[:-dr.FEED_LIMIT]
        self.events.sort(key=lambda event: event.time)
        if self._log.log_events:
            self._log.write_log([event for event in events if event.live])
        self.update_unseen()
        if self._shown:
            self.update_feed()

    def update_feed(self):
        # Made again only when events, incidents seen, filter or known cars changed (not at every answer)
        view = (self._events_revision, len(self.seen), self.feed_filter, len(self._texts),
                self.watcher.severity_version)
        if view == self._feed_view:
            return
        self._feed_view = view
        kinds = FEED_KINDS.get(FEED_FILTERS[self.feed_filter])
        rows = []
        for event in reversed(self.events):
            if kinds is not None and event.kind not in kinds:
                continue
            title, detail = self.event_texts(event)
            rows.append({
                "key": event.key, "timeText": clock_text(event.time), "kind": event.kind,
                "kindText": self.kind_text(event), "glyph": KIND_GLYPHS[event.kind],
                "tone": KIND_TONES.get(event.kind, "dim"), "title": title, "detail": detail, "live": event.live,
                "classColor": class_color(event.car_class) if event.car_class else "",
                "unseen": self.unseen(event), "canReplay": bool(event.slots),
            })
        if self._feed_model.sync(rows, reset_if_mostly_new=True):
            self.feedChanged.emit()

    def kind_text(self, event: dr.Event) -> str:
        """Kind of event, contacts with their severity (speed lost by the cars)"""
        lost = self.watcher.severity.get(event.key, -1.0)
        if event.kind in (dr.CONTACT, dr.WALL) and lost >= dr.HEAVY:
            return tr("Heavy Contact") if event.kind == dr.CONTACT else tr("Heavy Wall Contact")
        if event.kind in (dr.CONTACT, dr.WALL) and 0 <= lost < dr.LIGHT:
            return tr("Light Contact")
        return tr(KIND_TEXTS[event.kind])

    def unseen(self, event: dr.Event) -> bool:
        """Incident nobody looked at yet (live ones only)"""
        return event.live and event.kind in INCIDENT_KINDS and event.key not in self.seen

    def update_unseen(self):
        """Incidents nobody looked at counted again (events or incidents seen changed)"""
        count = sum(1 for event in self.events if self.unseen(event))
        if count != self._unseen:
            self._unseen = count
            self.unseenChanged.emit()

    def mark_seen(self, key: str):
        if key in self.event_index and key not in self.seen:
            self.seen.add(key)
            self.update_unseen()
            self.update_feed()

    def update_suggestions(self):
        rows = []
        shot = self.director.shot
        on_air = shot.key if shot is not None and shot.slot == self.on_air_slot else ""
        waiting = [candidate for candidate in self.candidates if candidate.key != on_air]  # story on air left out
        stories = [candidate for candidate in waiting if candidate.kind != dr.ROAM]
        shown = stories[:SUGGESTIONS] if stories else waiting[:3]
        for index, candidate in enumerate(shown):
            car = self.by_slot.get(candidate.slot)
            title, detail = self.candidate_texts(candidate)
            rows.append({
                "key": candidate.key, "slot": candidate.slot, "kind": candidate.kind,
                "kindText": tr(KIND_TEXTS[candidate.kind]), "glyph": KIND_GLYPHS[candidate.kind],
                "tone": KIND_TONES.get(candidate.kind, "dim"), "title": title, "detail": detail,
                "number": car.number if car is not None else "",
                "classColor": class_color(car.car_class) if car is not None else "",
                "score": round(max(min(candidate.score, 100.0), 0.0)), "best": index == 0,
            })
        if self._suggestions_model.sync(rows):
            self.suggestionsChanged.emit()

    def update_cars(self):
        counts: dict[str, int] = {}
        for car in self.standings:
            counts[car.car_class] = counts.get(car.car_class, 0) + 1
        class_list = [{"name": name, "color": class_color(name), "count": count} for name, count in counts.items()]
        if class_list != self._class_list:
            self._class_list = class_list
            if self.class_filter and self.class_filter not in counts:
                self.class_filter = ""
            self.classFilterChanged.emit()
        fastest: dict[str, float] = {}
        for car in self.standings:
            if car.best > 0 and (fastest.get(car.car_class, 0.0) <= 0 or car.best < fastest[car.car_class]):
                fastest[car.car_class] = car.best
        in_battle = {slot for battle in self.watcher.battles.values() for slot in (battle.ahead, battle.behind)}
        ahead_of = self.class_ahead()
        personal, class_best = self.best_sectors()
        grid = self.class_grid() if dr.is_race(self.session_key[1]) else {}
        rows = []
        for car in self.standings:
            if (self.class_filter and car.car_class != self.class_filter) or not self.matches(car):
                continue
            status, tone = status_text(car)
            ahead = ahead_of.get(car.slot)
            seconds, laps = interval(ahead, car, self.track_length) if ahead is not None else (-1.0, 0)
            sectors = self.shown_sectors(car)
            bests, class_bests = personal.get(car.slot, [-1.0] * 3), class_best.get(car.car_class, [-1.0] * 3)
            tones = [sector_tone(value, bests[index], class_bests[index]) for index, value in enumerate(sectors)]
            rows.append({
                "intervalTone": gap_tone(seconds) if laps == 0 else "",
                "gained": grid[car.slot] - self.places.get(car.slot, 0) if car.slot in grid else 0,
                "s1Tone": tones[0], "s2Tone": tones[1], "s3Tone": tones[2],
                "sectorTip": " · ".join(f"S{index} {lap_text(value) if value >= 60 else localized(f'{value:.3f}')}"
                                        for index, value in enumerate(sectors, 1) if value > 0),
                "key": str(car.slot), "slot": car.slot, "position": car.position,
                "classPosition": self.places.get(car.slot, 0), "number": car.number, "driver": car.driver,
                "team": car.team or car.vehicle, "carClass": car.car_class, "classColor": class_color(car.car_class),
                "classAlias": class_alias(car.car_class),
                "interval": interval_text(ahead_of.get(car.slot), car, self.track_length),
                "laps": car.laps, "best": lap_text(car.best), "last": lap_text(car.last),
                "fastest": car.best > 0 and car.best == fastest.get(car.car_class), "pits": car.pitstops,
                "status": status, "statusTone": tone, "onAir": car.slot == self.on_air_slot,
                "battle": car.slot in in_battle, "incidents": self.incident_counts.get(car.driver, 0),
                "selected": car.slot == self.selected,
                "brandLogo": self.logos.brand(car.vehicle),
                "tyreFront": self.tyres.get(car.slot, ("", ""))[0], "tyreRear": self.tyres.get(car.slot, ("", ""))[1],
            })
        if self._cars_model.sync(rows):
            self.carsChanged.emit()

    def shown_sectors(self, car: Standing) -> tuple[float, float, float]:
        """Sectors of the lap being driven when done (as they complete), else of last lap"""
        current = dr.current_sectors(car)
        last = dr.last_sectors(car)
        if current[0] > 0:
            return current[0], current[1], -1.0
        return last

    def best_sectors(self) -> tuple[dict[int, list[float]], dict[str, list[float]]]:
        """Best sectors of every car & class (watcher), made once per answer for every list"""
        if self._sectors is None or self._sectors[0] is not self.standings:
            self._sectors = (self.standings, self.watcher.best_sectors(self.standings))
        return self._sectors[1]

    def class_grid(self) -> dict[int, int]:
        """Class place on the starting grid of each car (slot), from qualifying places of the game"""
        return self._grid

    def class_ahead(self) -> dict[int, Standing]:
        """Car ahead in class of each car (slot)"""
        return self._fronts

    def matches(self, car: Standing) -> bool:
        """Car found by search words: number (from its start, "7" finds #7 & #77) or driver, team, car, class"""
        if not self.search_words:
            return True
        text = fold(f"{car.driver} {car.team} {car.vehicle} {car.car_class}")
        return all(car.number.startswith(word.lstrip("#")) or word in text for word in self.search_words)

    def update_battles(self):
        rows = []
        battles = sorted(self.watcher.battles.values(), key=lambda battle: (battle.position, battle.gap))
        for battle in battles:
            ahead, behind = self.by_slot.get(battle.ahead), self.by_slot.get(battle.behind)
            rows.append({
                "key": f"{battle.ahead}-{battle.behind}", "behindSlot": battle.behind, "carClass": battle.car_class,
                "classColor": class_color(battle.car_class), "position": battle.position,
                "ahead": car_label(ahead), "behind": car_label(behind), "gap": seconds_text(battle.gap),
                "trend": -1 if battle.trend < -0.02 else 1 if battle.trend > 0.02 else 0,
                "duration": clock_text(max(self.session_time - battle.since, 0.0)),
                "onAir": battle.behind == self.on_air_slot or battle.ahead == self.on_air_slot,
                "gapTone": gap_tone(battle.gap),
                "trendText": self.trend_text(battle, behind),
            })
        if self._battles_model.sync(rows):
            self.battlesChanged.emit()

    @staticmethod
    def trend_text(battle: dr.Battle, behind: Standing | None) -> str:
        """Gap change per lap of a battle: "-0.3 s/lap" closing, "" if steady or unknown"""
        lap_time = next((value for value in (behind.last, behind.best) if value > 0), 0.0) if behind else 0.0
        per_lap = battle.trend * lap_time
        if lap_time <= 0 or abs(per_lap) < 0.05:
            return ""
        return tr("%1/lap").replace("%1", f"{'+' if per_lap > 0 else '-'}{seconds_text(abs(per_lap))}")

    def update_classes(self):
        rows = []
        by_class: dict[str, list[Standing]] = {}
        for car in self.standings:
            by_class.setdefault(car.car_class, []).append(car)
        battles: dict[str, int] = {}
        for battle in self.watcher.battles.values():
            battles[battle.car_class] = battles.get(battle.car_class, 0) + 1
        for name, cars in by_class.items():
            leader = cars[0]
            timed = [car for car in cars if car.best > 0]
            best = min(timed, key=lambda car: car.best) if timed else None
            rows.append({
                "key": name, "name": name or tr("Unknown"), "classColor": class_color(name), "count": len(cars),
                "leader": leader.driver, "leaderNumber": leader.number,
                "bestLap": lap_text(best.best) if best is not None else "-",
                "bestDriver": car_label(best) if best is not None else "", "battles": battles.get(name, 0),
            })
        if self._classes_model.sync(rows):
            self.classesChanged.emit()

    def update_pits(self):
        ordered: list[tuple[tuple[bool, float, int], dict]] = []  # in pit lane first, then latest stop
        for car in self.standings:
            stops = self.watcher.pit_stops.get(car.slot, [])
            if not stops and car.pitstops <= 0 and not car.in_pit:
                continue
            last = stops[-1] if stops else None
            if last is None:
                last_text = ""
            elif last.duration > 0:
                last_text = tr("Lap %1").replace("%1", str(last.lap)) + f" · {seconds_text(last.duration)}"
                if last.stopped > 0:
                    last_text += f" · {tr('Stopped %1').replace('%1', seconds_text(last.stopped))}"
            else:
                last_text = tr("Lap %1").replace("%1", str(last.lap))
            status, _ = status_text(car)
            state = self.watcher.cars.get(car.slot)
            if car.in_pit and not car.garage and state is not None and state.pit_since >= 0:
                lane = max(self.session_time - state.pit_since, 0.0)
                status = tr("Pit lane %1").replace("%1", seconds_text(lane, 0))
                if car.pit_state == "STOPPED" and state.box_since >= 0:
                    stopped = state.box_time + max(self.session_time - state.box_since, 0.0)
                    status += f" · {tr('Stopped %1').replace('%1', seconds_text(stopped, 0))}"
            ordered.append(((not car.in_pit, -(last.time if last is not None else -1.0), car.position), {
                "key": str(car.slot), "slot": car.slot, "number": car.number, "driver": car.driver,
                "classColor": class_color(car.car_class), "stops": car.pitstops, "lastStop": last_text,
                "stint": self.watcher.stint_laps(car), "inPit": car.in_pit, "status": status,
            }))
        ordered.sort(key=lambda item: item[0])
        if self._pits_model.sync([row for _, row in ordered]):
            self.pitsChanged.emit()

    def update_sheet(self):
        car = self.by_slot.get(self.selected)
        if car is None:
            sheet: dict[str, Any] = {}
        else:
            fronts = self.class_ahead()
            ahead = fronts.get(car.slot)
            behind = next((other for other, front in fronts.items() if front.slot == car.slot), None)
            behind_car = self.by_slot.get(behind) if behind is not None else None
            status, tone = status_text(car)
            sheet = {
                "brandLogo": self.logos.brand(car.vehicle), "carPicture": car_picture_url(car.vehicle),
                "tyres": "/".join(dict.fromkeys(self.tyres.get(car.slot, ()))),
                "slot": car.slot, "driver": car.driver, "number": car.number, "team": car.team,
                "vehicle": car.vehicle, "carClass": car.car_class, "classColor": class_color(car.car_class),
                "position": car.position, "classPosition": self.places.get(car.slot, 0),
                "ahead": car_label(ahead) if ahead is not None else "",
                "intervalAhead": interval_text(ahead, car, self.track_length),
                "behind": car_label(behind_car) if behind_car is not None else "",
                "intervalBehind": interval_text(car, behind_car, self.track_length) if behind_car is not None else "",
                "best": lap_text(car.best), "last": lap_text(car.last), "laps": car.laps, "pits": car.pitstops,
                "stint": self.watcher.stint_laps(car), "incidents": self.incident_counts.get(car.driver, 0),
                "penalties": car.penalties, "status": status, "statusTone": tone,
                "note": self.notes.get(car.driver, ""), "onAir": car.slot == self.on_air_slot,
                "gained": self.class_grid().get(car.slot, 0) - self.places.get(car.slot, 0)
                if dr.is_race(self.session_key[1]) and car.grid > 0 else 0,
                "sectors": self.sector_cells(car), "energy": self.energy_text(car),
                "lapCount": len(self.watcher.laps.get(car.slot, ())),
                "history": self.history_text(car),
                "headToHead": self.head_to_head_text(car, ahead, behind_car),
            }
        if sheet == self._sheet:
            return
        self._sheet = sheet
        live = {key: sheet[key] for key in SHEET_LIVE if key in sheet}
        fixed = {key: value for key, value in sheet.items() if key not in live}
        if fixed != self._sheet_car:
            self._sheet_car = fixed
            self.sheetCarChanged.emit()
        if live != self._sheet_live:
            self._sheet_live = live
            self.sheetLiveChanged.emit()
        self.sheetChanged.emit()

    def sector_cells(self, car: Standing) -> list[dict]:
        """Sectors shown for car: text & color"""
        personal, class_best = self.best_sectors()
        bests, class_bests = personal.get(car.slot, [-1.0] * 3), class_best.get(car.car_class, [-1.0] * 3)
        return [{"text": localized(f"{value:.3f}") if value > 0 else "-",
                 "tone": sector_tone(value, bests[index], class_bests[index])}
                for index, value in enumerate(self.shown_sectors(car))]

    def energy_text(self, car: Standing) -> str:
        """Energy (else fuel) left, used per lap over 3 & 5 laps, laps left: "62% · 3.9%/lap (5: 4.0%) · 15 laps"
        "" if hidden"""
        left = dr.level(car)
        if left < 0:
            return ""
        parts = [f"{round(left * 100)}%"]
        three, five = self.watcher.energy_average(car.slot, 3), self.watcher.energy_average(car.slot, 5)
        if three > 0:
            per_lap = tr("%1/lap").replace("%1", f"{localized(f'{three * 100:.1f}')}%")
            if five > 0:
                per_lap += f" (5: {localized(f'{five * 100:.1f}')}%)"
            parts.append(per_lap)
            parts.append(tr("%1 laps").replace("%1", str(int(left / three))))
        return " · ".join(parts)

    def update_laps(self):
        """Lap history of the car asked (laps seen while the page watched)"""
        car = self.by_slot.get(self.laps_slot)
        records: dr.LapHistory | list[dr.LapRecord] = (
            self.watcher.laps.get(self.laps_slot, []) if car is not None else [])
        personal, class_best = self.best_sectors()
        bests = personal.get(self.laps_slot, [-1.0] * 3)
        class_bests = class_best.get(car.car_class, [-1.0] * 3) if car is not None else [-1.0] * 3
        class_lap = min((other.best for other in self.standings if car is not None
                         and other.car_class == car.car_class and other.best > 0), default=-1.0)
        view = (self.laps_slot, len(records), records[-1].lap if records else 0, tuple(bests), tuple(class_bests),
                class_lap, car.best if car is not None else 0.0)
        if view == self._laps_view:
            return
        self._laps_view = view
        rows = []
        for record in reversed(records):
            sectors = record.sectors
            rows.append({
                "key": str(record.lap), "lap": record.lap, "time": lap_text(record.time),
                "s1": localized(f"{sectors[0]:.3f}") if sectors[0] > 0 else "-",
                "s2": localized(f"{sectors[1]:.3f}") if sectors[1] > 0 else "-",
                "s3": localized(f"{sectors[2]:.3f}") if sectors[2] > 0 else "-",
                "timeTone": sector_tone(record.time, car.best if car is not None else -1.0, class_lap),
                "s1Tone": sector_tone(sectors[0], bests[0], class_bests[0]),
                "s2Tone": sector_tone(sectors[1], bests[1], class_bests[1]),
                "s3Tone": sector_tone(sectors[2], bests[2], class_bests[2]),
                "pit": record.pit, "energy": f"{localized(f'{record.energy * 100:.1f}')}%" if record.energy >= 0 else "",
                "position": record.position,
            })
        if self._laps_model.sync(rows):
            self.lapsChanged.emit()

    def update_weather(self, info: SessionState):
        self.session_info = info
        weather = [text for text in (
            tr("Air %1").replace("%1", temperature_text(info.air)) if info.air > -999 else "",
            tr("Track %1").replace("%1", temperature_text(info.track)) if info.track > -999 else "",
            tr("Rain %1").replace("%1", f"{round(info.rain * 100)}%") if info.rain > 0.005 else "",
            tr("Wet %1").replace("%1", f"{round(info.wetness * 100)}%") if info.wetness > 0.005 else "",
        ) if text]
        flag = "" if info.yellow in ("NONE", "INVALID", "") else tr("Full course yellow")
        weather = [flag, *weather] if flag else weather
        if weather != self._weather:
            self._weather = weather
            self.weatherChanged.emit()

    def update_on_air(self):
        """Card of the car on air (onAirChanged) & its pit radar (own model: distances change at every answer)"""
        car = self.by_slot.get(self.on_air_slot)
        radar = self._graphics.pit_neighbours(car)[:4] if car is not None else []
        if self._radar_model.sync([{**row, "key": f"{row['number']}|{row['name']}"} for row in radar]):
            self.pitRadarChanged.emit()
        if car is None:
            on_air: dict[str, Any] = {}
        else:
            kind = self.on_air_kind or dr.MANUAL
            on_air = {
                "brandLogo": self.logos.brand(car.vehicle), "carPicture": car_picture_url(car.vehicle),
                "slot": car.slot, "driver": car.driver, "number": car.number, "carClass": car.car_class,
                "classColor": class_color(car.car_class), "classPosition": self.places.get(car.slot, 0),
                "position": car.position, "kindText": tr(KIND_TEXTS.get(kind, "")),
                "glyph": KIND_GLYPHS.get(kind, ""), "tone": KIND_TONES.get(kind, "dim"),
                "startMs": self.on_air_start * 1000,
                "holdMs": self.hold_end() * 1000 if self.mode == "auto" else 0.0,
                "locked": self.locked,
                "minShotMs": self.director.settings.min_shot * 1000 if self.mode == "auto" else 0.0,
            }
        if on_air != {key: value for key, value in self._on_air.items() if key != "pitRadar"}:
            self._on_air = {**on_air, "pitRadar": radar} if on_air else {}
            self.onAirChanged.emit()
        elif on_air:
            self._on_air["pitRadar"] = radar

    def hold_end(self) -> float:
        """time.time() the director cuts again after an operator cut, 0 if not held"""
        hold = self.director.hold_until
        if hold != self._hold[0]:
            remaining = hold - time.monotonic()
            self._hold = (hold, time.time() + remaining if remaining > 0 else 0.0)
        return self._hold[1]

    # Properties
    @Property(str, notify=statusChanged)
    def gameState(self) -> str:
        return self.state

    @Property(str, notify=statusChanged)
    def statusText(self) -> str:
        return tr(STATE_TEXTS[self.state])

    @Property(bool, notify=statusChanged)
    def inSession(self) -> bool:
        return self.state in (SESSION, REPLAY)

    @Property(bool, notify=statusChanged)
    def replayActive(self) -> bool:
        return self.state == REPLAY

    @Property(str, notify=clockChanged)
    def sessionText(self) -> str:
        track, session = self.session_key[:2]
        if not self.can_command():
            return ""
        kind = next((text for prefix, text in SESSION_TEXTS.items() if session.upper().startswith(prefix)), "")
        return " · ".join(part for part in (track, tr(kind) if kind else session.title()) if part)

    @Property(float, notify=clockChanged)
    def sessionTime(self) -> float:
        return self.session_time

    @Property(float, notify=clockChanged)
    def timeReceived(self) -> float:
        return self.time_received * 1000

    @Property(float, notify=clockChanged)
    def clockRate(self) -> float:
        """Session seconds per second (live 1, replay its speed), 0 if unknown"""
        return self.replay_rate if self.state == REPLAY else 1.0 if self.state == SESSION else 0.0

    @Property(int, notify=modeChanged)
    def modeIndex(self) -> int:
        return MODES.index(self.mode)

    @Property(str, notify=modeChanged)
    def modeName(self) -> str:
        return self.mode

    @Property(dict, notify=onAirChanged)
    def onAir(self) -> dict:
        """Card of the car on air, "pitRadar" as last made (QML: pitRadarRows, own signal)"""
        return self._on_air

    @Property(QObject, constant=True)
    def pitRadarRows(self) -> DictListModel:
        """Cars near the car on air in the pit lane: number, name, color, distance, alongside, ahead"""
        return self._radar_model

    @Property(int, notify=pitRadarChanged)
    def pitRadarCount(self) -> int:
        return self._radar_model.rowCount()

    @Property(QObject, constant=True)
    def carRows(self) -> DictListModel:
        return self._cars_model

    @Property(int, notify=carsChanged)
    def carCount(self) -> int:
        return len(self.standings)

    @Property(list, notify=classFilterChanged)
    def classes(self) -> list[dict]:
        return self._class_list

    @Property(str, notify=classFilterChanged)
    def classFilter(self) -> str:
        return self.class_filter

    @Property(QObject, constant=True)
    def suggestionRows(self) -> DictListModel:
        return self._suggestions_model

    @Property(QObject, constant=True)
    def feedRows(self) -> DictListModel:
        return self._feed_model

    @Property(int, notify=feedFilterChanged)
    def feedFilter(self) -> int:
        return self.feed_filter

    @Property(QObject, constant=True)
    def battleRows(self) -> DictListModel:
        self.fresh_tab("battles")
        return self._battles_model

    @Property(int, notify=battlesChanged)
    def battleCount(self) -> int:
        return len(self.watcher.battles)

    @Property(QObject, constant=True)
    def classRows(self) -> DictListModel:
        self.fresh_tab("classes")
        return self._classes_model

    @Property(QObject, constant=True)
    def pitRows(self) -> DictListModel:
        self.fresh_tab("pits")
        return self._pits_model

    @Property(dict, notify=sheetChanged)
    def sheet(self) -> dict:
        """Car sheet, every value (QML binds sheetCar & sheetLive: a lap or interval does not touch the rest)"""
        return self._sheet

    @Property(dict, notify=sheetCarChanged)
    def sheetCar(self) -> dict:
        """Car sheet: driver, car, pictures, note, history (changes seldom)"""
        return self._sheet_car

    @Property(dict, notify=sheetLiveChanged)
    def sheetLive(self) -> dict:
        """Car sheet: places, intervals, laps, sectors, energy... (see SHEET_LIVE, changes at most answers)"""
        return self._sheet_live

    @Property(str, notify=noticeChanged)
    def noticeText(self) -> str:
        return self.notice

    @Property(bool, notify=noticeChanged)
    def noticeError(self) -> bool:
        return self.notice_error

    @Property(bool, notify=lockChanged)
    def carLocked(self) -> bool:
        return self.locked

    @Property(int, notify=unseenChanged)
    def unseenCount(self) -> int:
        return self._unseen

    @Property(bool, notify=instantChanged)
    def instantReplay(self) -> bool:
        return self.instant

    @Property(list, notify=weatherChanged)
    def weather(self) -> list[str]:
        """Full course yellow, air & track temperatures, rain, wet track"""
        return self._weather

    @Property(QObject, constant=True)
    def lapRows(self) -> DictListModel:
        return self._laps_model

    @Property(bool, notify=lapsChanged)
    def lapsOpen(self) -> bool:
        return self.laps_slot >= 0

    @Property(str, notify=lapsChanged)
    def lapsTitle(self) -> str:
        return car_label(self.by_slot.get(self.laps_slot))

    @Property(int, notify=settingsChanged)
    def postRoll(self) -> int:
        return self.post_roll

    # Settings
    @Property(float, notify=settingsChanged)
    def minShot(self) -> float:
        return self.director.settings.min_shot

    @Property(float, notify=settingsChanged)
    def maxShot(self) -> float:
        return self.director.settings.max_shot

    @Property(float, notify=settingsChanged)
    def battleGap(self) -> float:
        return self.director.settings.battle_gap

    @Property(int, notify=settingsChanged)
    def cameraStyle(self) -> int:
        return dr.CAMERA_STYLES.index(self.director.settings.camera_style)

    @Property(list, constant=True)
    def cameraStyles(self) -> list[str]:
        if self._camera_styles is None:
            self._camera_styles = [tr(text) for text in CAMERA_STYLE_TEXTS]
        return self._camera_styles

    @Property(bool, notify=settingsChanged)
    def followOverlays(self) -> bool:
        return self.follow_overlays

    @Property(int, notify=settingsChanged)
    def secondsBefore(self) -> int:
        return self.seconds_before

    @Slot(str, float)
    def setNumber(self, name: str, value: float):
        """Director setting: minShot, maxShot, battleGap, secondsBefore"""
        settings = self.director.settings
        if name == "minShot":
            settings.min_shot = min(max(value, 3.0), 60.0)
            settings.max_shot = max(settings.max_shot, settings.min_shot)
        elif name == "maxShot":
            settings.max_shot = min(max(value, settings.min_shot, 5.0), 300.0)
        elif name == "battleGap":
            settings.battle_gap = min(max(value, 0.2), 3.0)
            self.watcher.battle_gap = settings.battle_gap
        elif name == "secondsBefore":
            self.seconds_before = int(min(max(value, 0), 60))
        elif name == "postRoll":
            self.post_roll = int(min(max(value, 0), 60))
        else:
            return
        self.save_settings()
        self.settingsChanged.emit()

    @Slot(int)
    def setCameraStyle(self, index: int):
        if 0 <= index < len(dr.CAMERA_STYLES):
            self.director.settings.camera_style = dr.CAMERA_STYLES[index]
            self.save_settings()
            self.settingsChanged.emit()

    @Slot(bool)
    def setFollowOverlays(self, follow: bool):
        self.follow_overlays = follow
        self.save_settings()
        self.settingsChanged.emit()
        if follow and self.on_air_slot >= 0:
            self.overlays_follow(self.on_air_slot)
        elif not follow:
            self.overlays_stop_following()

    @staticmethod
    def overlays_stop_following():
        """Overlays back to the player car: spectate mode turned off (as turning the option on turned it on)"""
        from ...api_control import api

        if not cfg.api["enable_player_index_override"]:
            return
        cfg.api["enable_player_index_override"] = False
        cfg.save()
        api.setup()
        app_signal.refresh.emit(True)

    # Actions
    @Property(bool, notify=enabledChanged)
    def enabled(self) -> bool:
        return self._enabled

    @Slot(bool)
    def setEnabled(self, enabled: bool):
        """Director on or off. Off: game no longer asked, automatic cuts stopped, instant replay left, overlays
        back to the player car (spectate mode off), broadcast graphics emptied; events & notes of the session kept"""
        from ...stream_director import director_feed, live_feed

        if enabled == self._enabled:
            return
        self._enabled = enabled
        self.save_settings()
        self.enabledChanged.emit()
        app_signal.refresh.emit(True)  # notification bar & navigation bar dot
        if enabled:
            if not self._history_asked:  # page opened with the director off: never read yet
                self.read_history()
            if not self._game.request_state.busy:  # busy: its answer is read (director on again)
                self._game.refresh()
            return
        self._game.stop()  # no more requests, connection kept from answer to answer closed
        self._graphics.stop()
        self._graphics.end_auto_event()  # event card shown by the director at session start: hidden
        self.backToLive()  # instant replay shown: live session again in the game
        if self.mode == "auto":  # automatic cuts never start by themselves (as when the page opens)
            self.setMode(MODES.index("assist"))
        self.overlays_stop_following()  # spectate mode off, whoever turned it on: overlays on the player car
        self.set_state(OFFLINE)
        director_feed.clear()
        live_feed.clear()

    @Slot(int)
    def setMode(self, index: int):
        """Manual, assisted or automatic: automatic cuts at once if nothing is on air"""
        if not 0 <= index < len(MODES) or MODES[index] == self.mode:
            return
        self.mode = MODES[index]
        self.director.hold_until = 0.0
        self.save_settings()
        self.modeChanged.emit()
        self.update_on_air()
        if self.mode == "auto" and self.can_command():
            self.direct()

    @Property(str, notify=classFilterChanged)
    def searchText(self) -> str:
        return " ".join(self.search_words)

    @Slot(str)
    def setSearch(self, text: str):
        words = [fold(word) for word in text.split()]
        if words != self.search_words:
            self.search_words = words
            self.classFilterChanged.emit()
            self.update_cars()

    @Slot()
    def cutToFirstMatch(self):
        """Search confirmed (Enter): first car found on air"""
        car = next((car for car in self.standings if self.matches(car)
                    and (not self.class_filter or car.car_class == self.class_filter)), None)
        if car is not None:
            self.cutToCar(car.slot)

    @Slot(int)
    def takeSuggestionAt(self, index: int):
        """Suggestion of the list by place (keys 1 to 6)"""
        rows = self._suggestions_model.rows
        if 0 <= index < len(rows):
            self.takeSuggestion(rows[index]["key"])

    @Property(list, notify=forecastChanged)
    def forecastNodes(self) -> list[dict]:
        return self.forecast

    @Property(bool, notify=settingsChanged)
    def followGameCuts(self) -> bool:
        return self.follow_game_cuts

    @Slot(bool)
    def setFollowGameCuts(self, follow: bool):
        self.follow_game_cuts = follow
        self.save_settings()
        self.settingsChanged.emit()

    @Slot()
    def toggleLock(self):
        """Car on air kept (automatic mode does not cut) or let go"""
        self.locked = not self.locked
        self.lockChanged.emit()
        self.update_on_air()

    @Slot()
    def markAllSeen(self):
        self.seen.update(event.key for event in self.events if event.kind in INCIDENT_KINDS)
        self.update_unseen()
        self.update_feed()

    @Slot()
    def toggleAuto(self):
        self.setMode(MODES.index("assist") if self.mode == "auto" else MODES.index("auto"))

    @Slot(int)
    def cutToCar(self, slot: int):
        """Operator cut: camera on car (camera kept), director held a while"""
        if not self.can_command() or slot not in self.by_slot:
            return
        self.cut(self.director.manual(slot, "", time.monotonic()))
        self.update_on_air()

    @Slot(int)
    def stepCar(self, offset: int):
        """Operator cut to next (1) or previous (-1) car by place from the car on air"""
        ordered = [car.slot for car in self.standings if not self.class_filter or car.car_class == self.class_filter]
        if not ordered:
            return
        current = self.on_air_slot if self.on_air_slot >= 0 else self.focus
        if current in ordered:
            target = ordered[(ordered.index(current) + offset) % len(ordered)]
        else:
            target = ordered[0] if offset > 0 else ordered[-1]
        self.cutToCar(target)

    @Slot(str)
    def takeSuggestion(self, key: str):
        """Story cut to by operator: shown at least the shortest shot"""
        candidate = next((candidate for candidate in self.candidates if candidate.key == key), None)
        if candidate is None or not self.can_command():
            return
        clock = time.monotonic()
        self.cut(self.director.take(candidate, clock))
        self.director.hold_until = clock + self.director.settings.min_shot
        self.update_on_air()
        self.update_suggestions()

    @Slot()
    def takeBest(self):
        best = next((candidate for candidate in self.candidates if candidate.slot != self.on_air_slot), None)
        if best is not None:
            self.takeSuggestion(best.key)

    @Slot(str)
    def showEvent(self, key: str):
        """Event of feed shown: replay goes a little before it with the camera on its car, live: camera on car"""
        event = self.event_index.get(key)
        if event is None or not event.slots or not self.can_command():
            return
        slot = event.slots[0]
        if slot not in self.by_slot:
            return
        clock = time.monotonic()
        camera = "" if self.director.settings.camera_style == "keep" else self.director.camera_for(event.kind)
        shot = self.director.manual(slot, camera, clock)
        self.cut(shot)
        self.mark_seen(key)
        if self.state == REPLAY:
            self._camera.send(("PUT", f"/rest/watch/replaytime/{max(int(event.time) - self.seconds_before, 0)}"))
        self.update_on_air()

    @Slot(str)
    def replayEvent(self, key: str):
        """Instant replay (live session): the game goes to the replay of the session a little before the event,
        camera on its car, plays it, then back to live after the event (in a replay: same as showEvent)"""
        event = self.event_index.get(key)
        if event is None or not event.slots or event.slots[0] not in self.by_slot:
            return
        if self.state == REPLAY and not self.instant:
            self.showEvent(key)
            return
        if self.state != SESSION and not self.instant:
            return
        slot = event.slots[0]
        self.mark_seen(key)
        self.instant = True
        self.instant_event = event
        self.instantChanged.emit()
        camera = "" if self.director.settings.camera_style == "keep" else self.director.camera_for(event.kind)
        self.director.manual(slot, camera, time.monotonic())
        self.last_cut = time.monotonic()
        commands: list[gc.Command] = [gc.enter_replay,
                                      gc.seek_replay(int(event.time) - self.seconds_before, slot),
                                      *gc.camera_commands(camera), ("PUT", f"/rest/watch/replayCommand/{gc.PLAY}")]
        self.instant_waiting = True  # back to live counted from when the replay plays there
        self._camera.send(*commands)
        self.set_on_air(slot, event.kind)
        self._instant_timer.start(int(INSTANT_LIMIT * 1000))

    @Slot()
    def backToLive(self):
        """Instant replay over: live session shown again (director goes on)"""
        self._instant_timer.stop()
        if not self.instant:
            return
        self.instant = False
        self.instant_event = None
        self.instantChanged.emit()
        self.last_cut = time.monotonic()
        self.director.hold_until = time.monotonic() + self.director.settings.urgent_after
        self._camera.send(gc.leave_replay)

    @Slot(int)
    def showLaps(self, slot: int):
        """Lap history of car (-1: closed)"""
        self.laps_slot = slot
        self._laps_model.reset([])
        self.update_laps()
        self.lapsChanged.emit()

    @Slot(int)
    def selectCar(self, slot: int):
        """Car of sheet (no cut)"""
        self.selected = slot if slot != self.selected else -1
        self.update_sheet()
        self.update_cars()

    @Slot(str)
    def setNote(self, text: str):
        """Note of commentator on driver of sheet, kept between sessions"""
        car = self.by_slot.get(self.selected)
        if car is not None:
            self.setDriverNote(car.driver, text)

    @Slot(str, str)
    def setDriverNote(self, driver: str, text: str):
        """Note of commentator on driver (sheet: driver shown when the edit began, not the car picked since)"""
        if not driver:
            return
        text = text.strip()
        if text == self.notes.get(driver, ""):
            return
        if text:
            self.notes[driver] = text
        else:
            self.notes.pop(driver, None)
        self.save_settings()
        self.update_sheet()

    @Slot(str)
    def setClassFilter(self, name: str):
        self.class_filter = "" if name == self.class_filter else name
        self.classFilterChanged.emit()
        self.update_cars()

    @Slot(int)
    def setFeedFilter(self, index: int):
        if 0 <= index < len(FEED_FILTERS) and index != self.feed_filter:
            self.feed_filter = index
            self._feed_model.reset([])
            self._feed_view = None
            self.update_feed()
            self.feedFilterChanged.emit()

    # Race history of the drivers (results files read in background)
    def read_history(self):
        """Race results files read again in background (one read at a time): driver_history swaps its tables
        whole under its lock, the page reads them through its locked accessors"""
        self._history_asked = True
        if not self.jobs.is_busy("history"):
            self.jobs.run("race history", scan_history, self.history_read, key="history")

    def history_read(self, changed: bool):
        if changed and self._shown:
            self.update_sheet()

    def history_text(self, car: Standing) -> str:
        """Races of the driver: starts, wins & podiums in class, best finish on this track, last races"""
        stats = driver_history.stats(car.driver, self.session_key[0])
        if stats is None:
            return ""
        parts = [tr("%1 races").replace("%1", str(stats.starts)), tr("%1 wins").replace("%1", str(stats.wins)),
                 tr("%1 podiums").replace("%1", str(stats.podiums))]
        if stats.best_here:
            parts.append(tr("Best here: P%1").replace("%1", str(stats.best_here)))
        last = ", ".join(f"{'P' + str(record.class_position) if record.finished else tr('DNF')} {record.track}"
                         for record in stats.last)
        return " · ".join(parts) + (f"  —  {tr('Last')}: {last}" if last else "")

    def head_to_head_text(self, car: Standing, *others: Standing | None) -> str:
        """Races the driver ran with the cars ahead & behind: who finished ahead"""
        parts = []
        for other in others:
            if other is None:
                continue
            ahead, behind = driver_history.head_to_head(car.driver, other.driver)
            if ahead or behind:
                parts.append(tr("vs #%1: %2").replace("%1", other.number).replace("%2", f"{ahead}-{behind}"))
        return " · ".join(parts)
