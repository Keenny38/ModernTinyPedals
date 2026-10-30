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
Home page backend (qml/home/Home.qml): status banner (verdict of game & checks, version, update), game & session,
overlays, preset, last session & its debrief, driver, quick access

Each card is one property, told to the page only when its value changed (see publish). Read only while the page is
shown: game state every second (LIVE_MS), session history, driver ranks & game window every few seconds (SLOW_TICKS);
files (debrief laps, profile & results) on worker threads, cards waiting for them told by loading (the page keeps
their place). Work asked while hidden runs once shown again.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable
from time import monotonic
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from ... import app_signal
from ...api_control import api
from ...const_api import API_LMU_NAME
from ...const_app import APP_NAME, VERSION
from ...const_file import FileExt
from ...i18n import current_language, tr, trm
from ...lazy_service import update_checker
from ...module_control import mctrl, wctrl
from ...overlay_control import octrl
from ...setting import cfg
from ...userfile.driver_history import SessionRecord
from .game_pictures import LogoCache, notifier
from .page_backend import PageBackend

logger = logging.getLogger(__name__)

LIVE_MS = 1000  # game, overlay & checks
SLOW_TICKS = 5  # live ticks between reads of session history, driver ranks & game window
DRIVER_DATA_SECONDS = 600.0  # profile & results files read again this often while the page shows
PRESET_MENU_COUNT = 10  # presets in the preset card menu (newest first)
SESSION_NAMES = ("Test day", "Practice", "Qualify", "Warmup", "Race")  # game session type index
FINISH_STATES = ("", "Finished", "DNF", "DQ")  # driver history finish state


def vehicle_logo(logos: LogoCache, vehicle: str, vehicle_class: str = "") -> str:
    """Brand logo of a session record vehicle key ("Class - Brand", or vehicle name), none for a class"""
    if " - " in vehicle:
        return logos.brand("", vehicle.split(" - ", 1)[1].strip())
    if vehicle and vehicle != vehicle_class:
        return logos.brand(vehicle)
    return ""


def session_name(index: int) -> str:
    return tr(SESSION_NAMES[index]) if 0 <= index < len(SESSION_NAMES) else ""


def record_result(record: SessionRecord) -> str:
    """Race place, else finish state ("" if none)"""
    if record.session == 4 and record.finish == 1 and record.position > 0:
        return f"P{record.position}"
    if 0 < record.finish < len(FINISH_STATES):
        return tr(FINISH_STATES[record.finish])
    return ""


def last_session_card(record: SessionRecord, logos: LogoCache) -> dict:
    """Last session card: track, vehicle, session, best lap, result, date, logos"""
    from PySide6.QtCore import QDateTime, QLocale

    from ...calculation import sec2laptime_full

    when = QDateTime.fromSecsSinceEpoch(int(record.time))
    return {
        "track": record.track,
        "vehicle": record.vehicle,
        "session": session_name(record.session),
        "best": sec2laptime_full(record.best) if record.best > 0 else "",
        "result": record_result(record),
        "date": QLocale(current_language()).toString(when, QLocale.FormatType.ShortFormat),
        "trackLogo": logos.track(record.track) if record.track else "",
        "brandLogo": vehicle_logo(logos, record.vehicle, record.vehicle_class),
    }


# Highlights of "This week": kind, glyph (check, star, target), noun (one, many), tone
WEEK_HIGHLIGHTS = (
    ("goal_reached", "\ue73e", ("goal reached", "goals reached"), "gain"),
    ("record", "\ue735", ("new personal best", "new personal bests"), "gain"),
    ("goal_near", "\uf272", ("goal within reach", "goals within reach"), "accent"),
)


def week_card(items: list[dict]) -> dict:
    """"This week" card of Home (stats_analysis.weekly_progress items, texts translated): summary as on the Driver
    Stats page ("3 sessions · 1 h 05 min · 42 laps") & counts of goals reached, new personal bests & goals within
    reach (kind, glyph, text, tone); empty when nothing was driven"""
    from .stats_common import format_duration, plural

    if not items or items[0].get("kind") != "summary":
        return {}
    summary = items[0]
    counts: dict[str, int] = {}
    for item in items[1:]:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    return {
        "summary": " · ".join((plural(summary["sessions"], "session", "sessions"),
                               format_duration(summary["seconds"]), plural(summary["laps"], "lap", "laps"))),
        "highlights": [{"kind": kind, "glyph": glyph, "text": plural(counts[kind], *nouns), "tone": tone}
                       for kind, glyph, nouns, tone in WEEK_HIGHLIGHTS if counts.get(kind)],
    }


def clock_text(seconds: float) -> str:
    """Time left: h:mm:ss, m:ss under an hour"""
    total = max(int(seconds), 0)
    hours, minutes = divmod(total // 60, 60)
    return f"{hours}:{minutes:02d}:{total % 60:02d}" if hours else f"{minutes}:{total % 60:02d}"


def find_game_window() -> bool:
    """Le Mans Ultimate window open (worker thread), False off Windows"""
    if sys.platform != "win32":
        return False
    from .game_window import find_game_window as find

    return find()[0] != 0


class HomeBackend(PageBackend):
    """Home page state & actions

    Args:
        parent: page widget.
        window: main window (tools, dialogs & command palette opened from it).
        select_page: shows a main window page by navigation key.
    """

    headerChanged = Signal()
    gameChanged = Signal()
    overlayChanged = Signal()
    presetChanged = Signal()
    countsChanged = Signal()
    lastSessionChanged = Signal()
    debriefChanged = Signal()
    driverChanged = Signal()
    checksChanged = Signal()
    quickChanged = Signal()
    statusChanged = Signal()
    loadingChanged = Signal()
    weekChanged = Signal()

    def __init__(self, parent: QObject | None, window: Any, select_page: Callable[[str], object]):
        super().__init__(parent, "Home")
        self._window = window
        self._select_page = select_page
        self.logos = LogoCache()
        self._values: dict[str, Any] = {
            "header": {}, "game": {}, "overlay": {}, "preset": {}, "counts": {}, "lastSession": {}, "debrief": {},
            "driver": {}, "checks": [], "quick": [], "status": {}, "week": {},
            # read in background: card place kept meanwhile
            "loading": {"debrief": False, "driver": True, "week": True},
        }
        self._tick = 0
        self._record: SessionRecord | None = None
        self._record_read = False  # last session read once at least
        self._debrief_key: tuple | None = None  # stint, goal & language of debrief shown (read again if changed)
        self._debrief_data: Any = None  # DebriefData of debrief card, None if none
        self._driver_data: Any = None  # DriverData once read
        self._driver_read_time = -DRIVER_DATA_SECONDS
        self._driver_key: tuple | None = None  # what driver card shows (made again only when changed)
        self._driver_loaded = False  # profile & race record read once (driver card known, or nothing to show)
        self._records: list[SessionRecord] | None = None  # session history read with the debrief (None: not yet)
        self._week_key: tuple | None = None  # what "This week" card was made from (made again only when changed)
        self._game_window = False  # game window found while game sends no data
        self._timer = self.page_timer(self.poll, LIVE_MS)
        notifier().changed.connect(self.pictures_changed)  # logos fetched from game meanwhile
        app_signal.updates.connect(self.updates_changed)

    # Publishing
    def publish(self, name: str, value: Any, signal: Any):
        """Card value told to the page only if changed"""
        if self._values.get(name) != value:
            self._values[name] = value
            signal.emit()

    @Property(dict, notify=headerChanged)
    def header(self) -> dict:
        """Version, game & update state ("checking", "available" or ""), latest version, update tooltip"""
        return self._values["header"]

    @Property(dict, notify=gameChanged)
    def game(self) -> dict:
        """Game name, data received, state text, session (track, session, place, lap) & logos"""
        return self._values["game"]

    @Property(dict, notify=overlayChanged)
    def overlay(self) -> dict:
        return self._values["overlay"]

    @Property(dict, notify=presetChanged)
    def preset(self) -> dict:
        return self._values["preset"]

    @Property(dict, notify=countsChanged)
    def counts(self) -> dict:
        """Overlays & modules enabled and total"""
        return self._values["counts"]

    @Property(dict, notify=lastSessionChanged)
    def lastSession(self) -> dict:
        """Last driven session (see last_session_card), empty if none"""
        return self._values["lastSession"]

    @Property(dict, notify=debriefChanged)
    def debrief(self) -> dict:
        """Debrief of last session (see home_debrief.debrief_card), empty if nothing to tell"""
        return self._values["debrief"]

    @Property(dict, notify=driverChanged)
    def driver(self) -> dict:
        """Driver card (see home_driver.driver_card), empty if nothing known"""
        return self._values["driver"]

    @Property(list, notify=checksChanged)
    def checks(self) -> list:
        """Checks (see home_checks.home_checks), most important first"""
        return self._values["checks"]

    @Property(list, notify=quickChanged)
    def quick(self) -> list:
        """Quick access buttons: key, label, glyph, letter"""
        return self._values["quick"]

    @Property(dict, notify=statusChanged)
    def status(self) -> dict:
        """Status banner (see home_checks.home_status): verdict level, title, text, action & other check rows"""
        return self._values["status"]

    @Property(dict, notify=loadingChanged)
    def loading(self) -> dict:
        """Cards still read in background: debrief, driver, week"""
        return self._values["loading"]

    @Property(dict, notify=weekChanged)
    def week(self) -> dict:
        """Progress of the last 7 days (see week_card): summary & highlights, empty when nothing was driven"""
        return self._values["week"]

    def set_loading(self, name: str, value: bool):
        loading = self._values["loading"]
        if loading.get(name) != value:
            self.publish("loading", {**loading, name: value}, self.loadingChanged)

    # Page state
    def page_shown(self):
        self._timer.start()
        self.refresh_all()

    def page_hidden(self):
        self._timer.stop()  # nothing read while another page (or the race) is shown

    def release_resources(self):
        self._timer.stop()

    @Slot()
    def refresh(self):
        """Setting, preset or language changed: every card made again (once shown if hidden)"""
        if self.defer_while_hidden(self.refresh):
            return
        self._debrief_key = self._driver_key = self._week_key = None  # texts in the language set
        self._record_read = False
        self.refresh_all()

    def refresh_all(self):
        self.refresh_header()
        self.refresh_preset()
        self.refresh_counts()
        self.refresh_quick()
        self.refresh_slow()
        self.refresh_live()

    def poll(self):
        """Game state every tick, files & ranks every SLOW_TICKS"""
        if not self.page_visible:
            return
        self._tick += 1
        if self._tick % SLOW_TICKS == 0:
            self.refresh_slow()
        self.refresh_live()

    def refresh_slow(self):
        """Session history (last session & debrief, this week), driver ranks & data, game window"""
        self.refresh_last_session()
        self.refresh_week()
        self.refresh_driver()
        self.check_game_window()

    # Header, preset, counts, quick access
    def refresh_header(self):
        checked = update_checker.imported  # update module imported by first check, not at start for this
        state = latest = tip = ""
        if checked and update_checker.is_checking():
            state = "checking"
        elif checked and update_checker.is_updates():
            state = "available"
            latest = ".".join(str(part) for part in update_checker.latest_version())
        elif checked:
            tip = trm(update_checker.message())
        from PySide6.QtCore import QUrl

        from .. import app_icon_file

        self.publish("header", {
            "app": APP_NAME, "version": VERSION, "game": api.name if cfg.user.setting else "",
            "icon": QUrl.fromLocalFile(app_icon_file(True)).toString(),  # dark pages
            "iconLight": QUrl.fromLocalFile(app_icon_file(False)).toString(),
            "update": state, "latest": latest, "tip": tip,
        }, self.headerChanged)

    @Slot(bool)
    def updates_changed(self, _checking: bool = False):
        if self.defer_while_hidden(self.updates_changed):
            return
        self.refresh_header()
        self.refresh_checks()

    def refresh_preset(self):
        filename = cfg.filename.setting
        self.publish("preset", {
            "name": filename[:-len(FileExt.JSON)] if filename.endswith(FileExt.JSON) else filename,
            "locked": filename in cfg.user.filelock,
            "autoLoad": bool(cfg.application["enable_auto_load_preset"]),
        }, self.presetChanged)

    def refresh_counts(self):
        self.publish("counts", {
            "overlays": wctrl.number_active, "overlayTotal": wctrl.number_total,
            "modules": mctrl.number_active, "moduleTotal": mctrl.number_total,
        }, self.countsChanged)

    def refresh_quick(self):
        from ..home_view import QUICK_SHORTCUTS, current_quick_items, quick_access_entries

        entries = quick_access_entries()
        rows = []
        for key in current_quick_items():
            entry = entries[key]
            rows.append({"key": key, "label": tr(entry.label), "glyph": entry.glyph, "letter": entry.letter,
                         "shortcut": QUICK_SHORTCUTS.get(key, "")})
        self.publish("quick", rows, self.quickChanged)

    # Game, overlay & checks
    def refresh_live(self):
        from ..home_view import api_state_text

        state, running = api_state_text()
        session = self.session_info() if running else {}
        if running:
            status = tr("Running")
        else:
            status = tr("Not running") if state == "not running" else tr(state)
        self.publish("game", {"name": api.name, "running": running, "status": status, "lmu": api.name == API_LMU_NAME,
                              **session}, self.gameChanged)
        overlay = cfg.overlay
        self.publish("overlay", {
            "locked": bool(overlay["fixed_position"]), "autoHide": bool(overlay["auto_hide"]),
            "vr": bool(overlay["vr_compatibility"]),
        }, self.overlayChanged)
        self.refresh_counts()  # overlays turned on or off from rail, hotkeys, tray
        self.refresh_checks()

    def session_info(self) -> dict:
        """Current session: track, session, place ("P3/24", "P3" & "/24" apart), lap (of laps in a lap race), time
        left (timed session), vehicle & logos, empty if not on track"""
        read = api.read
        try:
            if not read.state.active():
                return {}
            track = read.session.track_name()
            total = read.vehicle.total_vehicles()
            place = read.vehicle.place()
            lap = f"{tr('Lap')} {read.lap.completed_laps() + 1}"  # LMU lap number = completed laps
            finish = read.session.finish_type()
            laps = read.lap.maximum() if finish in (1, 2) else 0
            if 0 < laps < 100000:  # lap race: total laps (huge when unlimited)
                lap += f"/{laps}"
            remaining = read.session.remaining() if finish != 1 else 0.0
            info = {
                "track": track,
                "session": session_name(read.session.session_type()),
                "place": f"P{place}/{total}" if total > 1 else "",
                "position": f"P{place}" if total > 1 and place > 0 else "",
                "total": f"/{total}" if total > 1 and place > 0 else "",
                "lap": lap,
                "timeLeft": clock_text(remaining) if 0 < remaining < 360000 else "",
                "vehicle": read.vehicle.vehicle_name(),
            }
        except (AttributeError, TypeError, ValueError, IndexError):
            return {}
        info["trackLogo"] = self.logos.track(track) if track else ""
        info["brandLogo"] = self.logos.brand(info["vehicle"]) if info["vehicle"] else ""
        return info

    def refresh_checks(self):
        from ..home_checks import CheckState, home_checks, home_status

        recorder = cfg.user.setting.get("module_recorder", {})
        state = self._values["game"]
        latest = self._values["header"].get("latest", "")
        rows = home_checks(CheckState(
            game=api.name,
            running=bool(state.get("running")),
            game_window=self._game_window,
            override=bool(cfg.api["enable_active_state_override"]),
            spectate=bool(cfg.api["enable_player_index_override"]),
            overlays=wctrl.number_active,
            recorder=bool(recorder.get("enable", True)) and bool(recorder.get("enable_lap_recording", True)),
            update=latest,
        ))
        self.publish("checks", rows, self.checksChanged)
        self.publish("status", home_status(rows, state), self.statusChanged)

    def check_game_window(self):
        """Le Mans Ultimate window looked for (worker thread) while no data comes: plugins off in game"""
        looked_for = api.name == API_LMU_NAME and not self._values["game"].get("running", False)
        if not looked_for:
            if self._game_window:
                self._game_window = False
                self.refresh_checks()
            return
        self.jobs.run("game window", find_game_window, self.game_window_found, key="window")

    def game_window_found(self, found: bool):
        found = found and not self._values["game"].get("running", False)
        if found != self._game_window:
            self._game_window = found
            self.refresh_checks()

    def pictures_changed(self):
        """Logos fetched from game: logos of cards looked for again"""
        if self.defer_while_hidden(self.pictures_changed):
            return
        if self._record is not None:
            self.publish("lastSession", last_session_card(self._record, self.logos), self.lastSessionChanged)
        self.refresh_live()

    # Last session & debrief
    def refresh_last_session(self):
        """Last driven session from driver stats history (file read again only once changed)"""
        from ..home_view import last_session

        record = last_session()
        if self._record_read and record == self._record:
            return
        self._record_read = True
        self._record = record
        self.publish("lastSession", last_session_card(record, self.logos) if record is not None else {},
                     self.lastSessionChanged)
        self.refresh_debrief(record)

    def refresh_debrief(self, record: SessionRecord | None):
        """Debrief of last session read in background, again once session or its lap time goal changed"""
        if record is None:
            self._debrief_key = self._debrief_data = None
            self.publish("debrief", {}, self.debriefChanged)
            self.set_loading("debrief", False)
            self._records = []  # nothing driven: no week either
            self.refresh_week()
            return
        from ..home_debrief import read_session_history, stats_goal

        goal = stats_goal(record.track, record.vehicle)  # set on driver stats page
        key = (record, goal, current_language())
        if key == self._debrief_key:
            return
        self._debrief_key = key
        self.set_loading("debrief", True)
        self.jobs.run("session debrief", lambda: read_session_history(record, goal), self.history_read,
                      self.debrief_failed, key="debrief")

    def history_read(self, result: tuple[Any, list[SessionRecord]]):
        """Debrief & session history read (one disk pass): debrief card, then "This week" from the same records"""
        data, records = result
        self._records = records
        self.debrief_read(data)
        self.refresh_week()

    def debrief_read(self, data: Any):
        from ..home_debrief import debrief_card, worth_showing

        self._debrief_data = data if data is not None and worth_showing(data) else None
        self.publish("debrief", debrief_card(data) if self._debrief_data is not None else {}, self.debriefChanged)
        self.set_loading("debrief", False)

    def debrief_failed(self, error: BaseException):
        """Laps unreadable: no debrief (its place freed), error logged"""
        logger.warning("HOME: session debrief not read: %s", error)
        self.debrief_read(None)
        if self._records is None:  # history unreadable: no week (place freed)
            self._records = []
            self.refresh_week()

    # This week
    def refresh_week(self):
        """Progress of the last 7 days from the session history read with the debrief (no disk pass here), made
        in background again once history, lap time goals, language or the hour changed"""
        records = self._records
        if records is None:  # read with the debrief: card place kept meanwhile
            return
        from .stats_analysis import parse_goals, weekly_progress
        from .stats_common import CONFIG_NAME

        goals = parse_goals(cfg.user.config.get(CONFIG_NAME, {}).get("goals"))
        now = time.time()
        key = (id(records), len(records), int(now // 3600), tuple(sorted(goals.items())), current_language())
        if key == self._week_key:
            return
        self._week_key = key
        self.jobs.run("weekly progress", lambda: weekly_progress(records, goals, now), self.week_read,
                      self.week_failed, key="week")

    def week_read(self, items: list[dict]):
        self.publish("week", week_card(items), self.weekChanged)
        self.set_loading("week", False)

    def week_failed(self, error: BaseException):
        logger.warning("HOME: weekly progress not made: %s", error)
        self.week_read([])

    # Driver
    def read_driver_data(self):
        """Profile & race record read in background, again once DRIVER_DATA_SECONDS passed (page shown)"""
        from ..home_driver import read_driver_data

        self._driver_read_time = monotonic()
        self.jobs.run("driver card", read_driver_data, self.driver_data_read, self.driver_data_failed, key="driver")

    def driver_data_read(self, data: Any):
        self._driver_data = data
        self._driver_loaded = True
        self.refresh_driver()
        self.set_loading("driver", False)

    def driver_data_failed(self, error: BaseException):
        """Profile or results unreadable: card from what was read before (or ranks only, or none), error logged"""
        logger.warning("HOME: driver card data not read: %s", error)
        self.driver_data_read(self._driver_data)

    def refresh_driver(self):
        """Driver card: ranks checked in background (game menu file changed), made again only when changed"""
        from ...rank_info import ranks

        ranks.poll()
        if monotonic() - self._driver_read_time >= DRIVER_DATA_SECONDS:
            self.read_driver_data()
        key = (ranks.serial, id(self._driver_data), len(ranks.others), current_language())
        if key == self._driver_key:
            return
        self._driver_key = key
        if self._driver_data is None and ranks.player is None and not ranks.others:
            return  # nothing known yet: profile & results read meanwhile
        from ..home_driver import driver_card

        player = ranks.player
        history = ranks.history_of(player.steam_id) if player is not None else ()  # in memory: no file read here
        card = driver_card(player, ranks.remembered, ranks.updated, history, self._driver_data, ranks.others)
        self.publish("driver", card or {}, self.driverChanged)

    # Actions
    def open_tool(self, path: str) -> Any:
        from ..tools_view import open_tool

        return open_tool(path, self._window)

    @Slot(str)
    def openPage(self, key: str):
        """Main window page by navigation key (widget, module, preset, spectate...)"""
        self._select_page(key)

    @Slot()
    def openGameSettings(self):
        """API settings of selected game"""
        from ..menu import open_preset_config

        open_preset_config(self._window, "api")

    @Slot()
    def toggleLock(self):
        octrl.toggle.lock()
        self.refresh_live()

    @Slot()
    def updateAction(self):
        """Update available: its notes & install, else check now"""
        if update_checker.is_updates():
            from ..notification import UpdatesNotifyButton

            button = self._window.findChild(UpdatesNotifyButton)
            if button is not None:
                button.show_release_notes()
                return
        update_checker.check(True)
        self.refresh_header()

    @Slot()
    def showReleaseNotes(self):
        """What's new in running version (local changelog in app language, works offline)"""
        from ..release_notes import running_version_dialog

        running_version_dialog(self._window).open()

    @Slot(str)
    def runQuick(self, key: str):
        """Quick access entry: open tool or page, or run action"""
        from ..home_view import quick_access_entries

        entry = quick_access_entries().get(key)
        if entry is None:
            return
        if entry.kind == "tool":
            self.open_tool(entry.target)
        elif entry.kind == "page":
            self._select_page(entry.target)
        elif key == "command_palette":
            self._window.open_command_palette()
        elif key == "bug_report":
            from ..bug_report_view import BugReport

            BugReport(self._window).show()
        elif key == "check_updates":
            update_checker.check(True)
            self.refresh_header()

    @Slot()
    def customizeQuick(self):
        """Choose & order quick access entries (page inside app)"""
        from ..home_view import QuickAccessEditor

        QuickAccessEditor(self._window, self.refresh_quick).open()

    @Slot(str)
    def runCheck(self, action: str):
        """Action of a check row"""
        if action == "api":
            self.openGameSettings()
        elif action == "update":
            self.updateAction()
        elif action in ("overlays", "spectate", "modules"):
            self._select_page({"overlays": "widget", "modules": "module"}.get(action, action))

    @Slot(result=list)
    def presetList(self) -> list:
        """Presets of preset card menu, newest first: file, name, loaded, locked"""
        from .preset_backend import list_presets

        return [
            {"file": filename, "name": filename[:-len(FileExt.JSON)], "loaded": filename == cfg.filename.setting,
             "locked": filename in cfg.user.filelock}
            for filename, _stat in list_presets(cfg.path.settings)[:PRESET_MENU_COUNT]
        ]

    @Slot(str)
    def loadPreset(self, filename: str):
        """Load preset (whole app reloaded), unless loaded or gone"""
        if filename == cfg.filename.setting or not os.path.isfile(os.path.join(cfg.path.settings, filename)):
            return
        cfg.set_next_to_load(filename)
        app_signal.reload.emit(True)

    @Slot()
    def openLastSession(self):
        """Driver stats of last session track & vehicle"""
        viewer = self.open_tool("driver_stats_viewer.DriverStatsViewer")
        backend = getattr(viewer, "backend", None)
        record = self._record
        if backend is not None and record is not None:
            backend.show_combo(record.track, record.vehicle)

    @Slot()
    def openLiveCalculator(self):
        """Race Calculator on its Live tab (plan of the session going on)"""
        dialog = self.open_tool("race_calculator.RaceCalculator")
        backend = getattr(dialog, "backend", None)
        if backend is not None:
            from .race_base import TABS

            backend.setTab(TABS.index("live"))

    @Slot()
    def openDirector(self):
        """Broadcast Director (Le Mans Ultimate)"""
        self.open_tool("broadcast_director.BroadcastDirector")

    @Slot()
    def openDriverStats(self):
        self.open_tool("driver_stats_viewer.DriverStatsViewer")

    @Slot()
    def openDebrief(self):
        """Telemetry of last session: its laps compared as in the debrief"""
        self.show_debrief_laps(-1.0)

    @Slot(int)
    def openCorner(self, index: int):
        """Telemetry of last session on a corner to work on (charts zoomed on it)"""
        tips = self._values["debrief"].get("tips", [])
        if 0 <= index < len(tips):
            self.show_debrief_laps(float(tips[index]["apex"]))

    def show_debrief_laps(self, apex: float):
        from ..home_debrief import debrief_laps

        data = self._debrief_data
        reference, compared = debrief_laps(data) if data is not None else ("", "")
        viewer = self.open_tool("lap_viewer.LapViewer")
        backend = getattr(viewer, "backend", None)
        if backend is None or not reference:
            return
        from .lap_focus import show_laps

        if not show_laps(backend, reference, compared, apex):
            logger.info("HOME: debrief lap not in a track folder: %s", reference)
