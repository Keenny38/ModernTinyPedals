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
Session recorder page state (ui/qml/telemetry/SessionRecorder.qml): shared memory recording, replay files list,
replay playback (play, speed, loop, position, laps & incidents) and replay sections saved to new files

Replay files are listed, loaded (indexed) and sections saved in background: the page never waits for a file.
Position & recording state are read from the replay module a few times a second while the page is shown
(no signal for them: the player follows the wall clock), each part told to QML only when it changed.
"""

from __future__ import annotations

import html
import logging
import os
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from typing import Any

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QWidget

from ... import app_signal
from ...api_control import api
from ...const_api import API_LMU_NAME, API_RF2_NAME
from ...i18n import tr, trm
from ...process.results_text import number_text
from ...replay import (
    FILE_EXT,
    SPEEDS,
    ReplayFile,
    ReplayInfo,
    ReplayLoadCancelled,
    ReplayMismatch,
    list_replays,
    replay,
    same_file,
)
from ...replay_session import api_supported, section_filename, start_api_recording
from ...setting import cfg
from .._common import translate_filter
from . import dialogs
from .formatting import date_text
from .page_backend import PageBackend

logger = logging.getLogger(__name__)

SEEK_STEP = 5.0  # seconds, arrow keys
INCIDENT_LEAD = 3.0  # seconds shown before an incident
REFRESH_PLAYING = 100  # ms between position reads while a replay plays (scrub handle moves smoothly)
REFRESH_IDLE = 250  # ms between reads otherwise (recorded frames, paused replay changed elsewhere)


def format_time(seconds: float) -> str:
    """Format seconds as m:ss (h:mm:ss over an hour)"""
    minutes, seconds = divmod(int(seconds), 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def format_size(size: int) -> str:
    """File size in MB"""
    return f"{number_text(size / 1048576, 1)} MB"


def restart_api():
    """Restart API so it switches between game and replay"""
    api.restart()
    app_signal.refresh.emit(True)


def _get(name: str) -> Callable[[SessionRecorderBackend], Any]:
    """Property getter of a page state value"""
    return lambda backend: backend._state[name]


def api_hint() -> str:
    """Why recording & replay are off with the API selected"""
    return trm(f"Select {API_LMU_NAME} / {API_RF2_NAME} API to record or replay telemetry.")


def replay_row(item: ReplayInfo) -> dict:
    """Row of replay list (QML): file, texts of columns"""
    info = item.info
    session = info.get("session")
    return {
        "file": item.filename,
        "name": os.path.basename(item.filename),
        "date": date_text(item.created),
        "track": str(info.get("track", "")),
        "vehicle": str(info.get("vehicle", "")),
        "session": tr(str(session)) if session else "",
        "duration": format_time(item.duration) if item.duration >= 0 else "?",
        "size": format_size(item.size),
    }


class SectionExport(QObject):
    """Save replay section in background (about 3s per recorded minute), results in user interface thread

    Signals:
        progress: frames done, frames total.
        finished: file name, number of frames, error (empty if saved).
    """

    progress = Signal(int, int)
    finished = Signal(str, int, str)

    def __init__(self, parent: QObject):
        super().__init__(parent)
        self._thread: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        """Whether a section is being saved"""
        return self._thread is not None and self._thread.is_alive()

    def start(self, replay_file: ReplayFile, filename: str, start: float, end: float) -> bool:
        """Start saving section, False if already saving one"""
        if self.busy:
            return False

        def export():
            error = ""
            frames = 0
            try:
                frames = replay_file.export(filename, start, end, self._report)
            except (OSError, ValueError) as export_error:
                error = str(export_error)
            with suppress(RuntimeError):  # page closed meanwhile
                self.finished.emit(filename, frames, error)

        self._thread = threading.Thread(target=export, daemon=True, name="Replay export")
        self._thread.start()
        return True

    def _report(self, done: int, total: int):
        with suppress(RuntimeError):  # page closed meanwhile
            self.progress.emit(done, total)

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for saving to finish, returns True if finished"""
        if self._thread is not None:
            self._thread.join(timeout)
        return not self.busy


class ReplayLoad(QObject):
    """Load replay file in background (indexing a long recording takes seconds), result in user interface thread

    Only last started loading is delivered: starting another one or cancelling stops the previous
    one, a result arriving later is dropped (file closed).

    Signals:
        finished: loaded replay file (None on error), error (None if loaded).
    """

    finished = Signal(object, object)
    _done = Signal(int, object, object)  # loading number, replay file, error (from loading thread)

    def __init__(self, parent: QObject):
        super().__init__(parent)
        self._threads: list[threading.Thread] = []
        self._cancel = threading.Event()
        self._number = 0
        self.filename = ""  # file being loaded, empty if none
        self.percent = 0  # loading progress
        self._done.connect(self._deliver)

    @property
    def busy(self) -> bool:
        """Whether a file is being loaded"""
        return bool(self.filename)

    def start(self, filename: str, api_name: str = "", layout: Sequence[Sequence] | None = None):
        """Load file (checked with API name & layout, see ReplayControl.prepare), previous loading cancelled"""
        self.cancel()
        self._number += 1
        number = self._number
        cancel = self._cancel = threading.Event()
        self.filename = filename
        self.percent = 0

        def report(done: int, total: int):
            if number == self._number:
                self.percent = done * 100 // max(total, 1)

        def load():
            replay_file: ReplayFile | None = None
            error: Exception | None = None
            try:
                replay_file = replay.prepare(filename, api_name, layout, cancel, report)
            except ReplayLoadCancelled:
                return
            except (OSError, ValueError) as load_error:
                error = load_error
            except Exception as load_error:  # never leave loading thread with unexpected error unlogged
                logger.exception("replay: loading failed, %s", filename)
                error = load_error
            if not cancel.is_set():
                try:
                    self._done.emit(number, replay_file, error)
                    return
                except RuntimeError:  # page closed meanwhile
                    pass
            if replay_file is not None:
                replay_file.close()

        self._threads = [thread for thread in self._threads if thread.is_alive()]
        thread = threading.Thread(target=load, daemon=True, name="Replay load")
        self._threads.append(thread)
        thread.start()

    def cancel(self):
        """Stop loading, result not delivered"""
        self._cancel.set()
        self._number += 1
        self.filename = ""

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for loading threads to end (cancelled or result sent), returns True if ended"""
        deadline = None if timeout is None else time.monotonic() + timeout
        for thread in self._threads:
            thread.join(None if deadline is None else max(deadline - time.monotonic(), 0.0))
        self._threads = [thread for thread in self._threads if thread.is_alive()]
        return not self._threads

    def _deliver(self, number: int, replay_file: ReplayFile | None, error: Exception | None):
        if number != self._number:  # stale: other file opened or cancelled meanwhile
            if replay_file is not None:
                replay_file.close()
            return
        self.filename = ""
        self.finished.emit(replay_file, error)


class SessionRecorderBackend(PageBackend):
    """Session recorder page: recording, replay list & playback

    Signals (each emitted only when its part changed):
        recordChanged: recording, recordText, recordError, canRecord, apiSupported.
        loadChanged: loading, loadText.
        playerChanged: active, fileName, filePath, duration, speed, loop.
        markersChanged: laps, lapItems, incidents (replay opened).
        positionChanged: position, positionText, paused.
        sectionChanged: sectionStart, sectionEnd, canSave, saving, sectionText.
        replaysChanged: replays, listing.
        message: text, error (toast).
    """

    recordChanged = Signal()
    loadChanged = Signal()
    playerChanged = Signal()
    markersChanged = Signal()
    positionChanged = Signal()
    sectionChanged = Signal()
    replaysChanged = Signal()
    message = Signal(str, bool)

    def __init__(self, window: QWidget | None = None, ctx=None):
        super().__init__(window, "Session recorder", ctx)
        self._window = window
        self._state: dict[str, Any] = {
            # recordChanged
            "recording": False, "recordText": "", "recordError": False, "canRecord": False, "apiSupported": False,
            # loadChanged
            "loading": False, "loadText": "", "loadingFile": "",
            # playerChanged
            "active": False, "fileName": "", "filePath": "", "duration": 0.0, "laps": [], "lapItems": [], "incidents": [],
            "speed": 1.0, "loop": True,
            # positionChanged
            "position": 0.0, "positionText": "", "paused": False,
            # sectionChanged
            "sectionStart": -1.0, "sectionEnd": -1.0, "canSave": False, "saving": False, "sectionText": "",
            # replaysChanged
            "replays": [], "listing": False,
        }
        self._groups = {
            "recordChanged": ("recording", "recordText", "recordError", "canRecord", "apiSupported"),
            "loadChanged": ("loading", "loadText", "loadingFile"),
            "playerChanged": ("active", "fileName", "filePath", "duration", "speed", "loop"),
            "markersChanged": ("laps", "lapItems", "incidents"),
            "positionChanged": ("position", "positionText", "paused"),
            "sectionChanged": ("sectionStart", "sectionEnd", "canSave", "saving", "sectionText"),
            "replaysChanged": ("replays", "listing"),
        }
        self._loaded_file = ""  # replay file markers were read from
        self._section: list[float | None] = [None, None]
        self._section_text = ""
        self._speed = 1.0  # speed & loop kept between replays (set on each loaded one)
        self._loop = True
        self.last_message = ""  # last toast text (tests)
        self._on_loaded: Callable[[], None] | None = None
        self.export = SectionExport(self)
        self.export.progress.connect(self.export_progress)
        self.export.finished.connect(self.export_finished)
        self.loader = ReplayLoad(self)
        self.loader.finished.connect(self.load_finished)
        self._timer = self.page_timer(self.refresh, REFRESH_IDLE)
        self.refresh()

    # State told to QML
    def _publish(self, **values):
        """Set state values, each group signal emitted once if one of its values changed"""
        changed = set()
        for name, value in values.items():
            if self._state[name] != value:
                self._state[name] = value
                changed.add(name)
        if not changed:
            return
        for signal_name, names in self._groups.items():
            if changed.intersection(names):
                getattr(self, signal_name).emit()

    recording = Property(bool, _get("recording"), notify=recordChanged)
    recordText = Property(str, _get("recordText"), notify=recordChanged)
    recordError = Property(bool, _get("recordError"), notify=recordChanged)
    canRecord = Property(bool, _get("canRecord"), notify=recordChanged)
    apiSupported = Property(bool, _get("apiSupported"), notify=recordChanged)
    loading = Property(bool, _get("loading"), notify=loadChanged)
    loadText = Property(str, _get("loadText"), notify=loadChanged)
    loadingFile = Property(str, _get("loadingFile"), notify=loadChanged)
    active = Property(bool, _get("active"), notify=playerChanged)
    fileName = Property(str, _get("fileName"), notify=playerChanged)
    filePath = Property(str, _get("filePath"), notify=playerChanged)
    duration = Property(float, _get("duration"), notify=playerChanged)
    laps = Property(list, _get("laps"), notify=markersChanged)
    lapItems = Property(list, _get("lapItems"), notify=markersChanged)
    incidents = Property(list, _get("incidents"), notify=markersChanged)
    speed = Property(float, _get("speed"), notify=playerChanged)
    loop = Property(bool, _get("loop"), notify=playerChanged)
    position = Property(float, _get("position"), notify=positionChanged)
    positionText = Property(str, _get("positionText"), notify=positionChanged)
    paused = Property(bool, _get("paused"), notify=positionChanged)
    sectionStart = Property(float, _get("sectionStart"), notify=sectionChanged)
    sectionEnd = Property(float, _get("sectionEnd"), notify=sectionChanged)
    canSave = Property(bool, _get("canSave"), notify=sectionChanged)
    saving = Property(bool, _get("saving"), notify=sectionChanged)
    sectionText = Property(str, _get("sectionText"), notify=sectionChanged)
    replays = Property(list, _get("replays"), notify=replaysChanged)
    listing = Property(bool, _get("listing"), notify=replaysChanged)

    @Property(list, constant=True)
    def speeds(self) -> list:
        return list(SPEEDS)

    @Property(str, constant=True)
    def apiHint(self) -> str:
        """Why recording & replay are off with the API selected"""
        return api_hint()

    def show_message(self, text: str, error: bool = False):
        """Toast of page (TpDialogHost; page hidden: none), plain text"""
        self.last_message = text
        self.message.emit(text, error)
        bridge = dialogs.page_bridge(self._window)
        if bridge is not None:
            bridge.show_toast(html.escape(text), "error" if error else "success")

    # Page shown / hidden
    def page_shown(self):
        self.refresh()
        self._timer.start()
        self.refreshList()

    def page_hidden(self):
        self._timer.stop()  # hidden page: nothing read, replay & recording keep running

    def release_resources(self):
        """Page closed: replay loading stopped (file closed), replay & recording keep running"""
        self._timer.stop()
        self._on_loaded = None
        self.loader.cancel()
        # Short join only: the daemon thread sees the cancel at its next check (a few ms) and closes the file itself
        # (a stale result is never delivered); a 2 s join froze the UI thread on a slow read (network disk)
        self.loader.wait(0.1)

    @Slot()
    def refresh(self):
        """Read recording & playback state"""
        supported = api_supported()
        loading = self.loader.busy
        if replay.recording:
            record_text = trm(f"{replay.recorded_frames} frames: {os.path.basename(replay.recording_file)}")
            record_error = False
        elif replay.recording_error:
            record_text = trm(f"Recording stopped: {replay.recording_error}")
            record_error = True
        elif not replay.recording_file:
            record_text, record_error = "", False
        else:  # stopped on request: last recording named
            record_text, record_error = self._state["recordText"], self._state["recordError"]
        self._publish(
            recording=replay.recording, recordText=record_text, recordError=record_error, apiSupported=supported,
            canRecord=replay.recording or (supported and not replay.active and not loading),  # stop always possible
            loading=loading,
            loadText=trm(f"Loading replay {os.path.basename(self.loader.filename)}: {self.loader.percent}%")
            if loading else "",
            loadingFile=self.loader.filename,
        )
        player = replay.player
        if player is None:
            if self._loaded_file:
                self.load_markers()
            self._publish(active=False, fileName="", filePath="", duration=0.0, position=0.0, positionText="", paused=False)
        else:
            if player.replay.filename != self._loaded_file:
                self.load_markers()
            duration = player.replay.duration
            position = player.position
            self._publish(
                active=True, fileName=os.path.basename(player.replay.filename), filePath=player.replay.filename,
                duration=duration,
                speed=player.speed, loop=player.loop,
                position=position, positionText=f"{format_time(position)} / {format_time(duration)}",
                paused=player.paused,
            )
        self._publish_section()
        interval = REFRESH_PLAYING if player is not None and not player.paused else REFRESH_IDLE
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)

    def load_markers(self):
        """Lap & incident markers of loaded replay, section cleared"""
        player = replay.player
        self._loaded_file = player.replay.filename if player is not None else ""
        self._section = [None, None]
        self._section_text = ""
        if player is None:
            laps: list[float] = []
            items: list[dict] = []
            incidents: list[float] = []
        else:
            markers = player.replay.markers_of("lap")
            laps = [marker.time for marker in markers]
            items = [{"text": trm(f"Lap {marker.text} ({format_time(marker.time)})"), "time": marker.time}
                     for marker in markers]
            incidents = [marker.time for marker in player.replay.markers_of("incident")]
        self._publish(laps=laps, lapItems=items, incidents=incidents)
        self._publish_section()

    def _publish_section(self):
        start, end = self._section
        self._publish(
            sectionStart=-1.0 if start is None else start, sectionEnd=-1.0 if end is None else end,
            canSave=replay.player is not None and None not in self._section and not self.export.busy,
            saving=self.export.busy, sectionText=self._section_text,
        )

    # Replay list
    @Slot()
    def refreshList(self):
        """List replay files of telemetry folder (headers read in background)"""
        folder = cfg.path.telemetry or "."
        self._publish(listing=True)
        self.jobs.run("replay list", lambda: [replay_row(item) for item in list_replays(folder)],
                      self.list_done, self.list_failed, key="list")

    def list_done(self, rows: list[dict]):
        self._publish(replays=rows, listing=False)

    def list_failed(self, error: BaseException):
        logger.error("replay: unable to list replays: %s", error)
        self._publish(listing=False)

    @Slot()
    def openFolder(self):
        folder = os.path.abspath(cfg.path.telemetry or ".")
        with suppress(OSError):  # a file of that name: not opened below
            os.makedirs(folder, exist_ok=True)
        if os.path.isdir(folder):  # never a file (would be run)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    # Recording
    @Slot()
    def toggleRecording(self):
        """Start or stop recording"""
        if replay.recording:
            replay.stop_recording()
            self.refreshList()
        elif self.check_api():
            start_api_recording()
        self.refresh()

    # Playback
    @Slot()
    def openReplay(self):
        """Choose replay file and switch API to it"""
        if not self.check_api():
            return
        filename, _ = QFileDialog.getOpenFileName(
            self._window, tr("Open Replay…"), cfg.path.telemetry, translate_filter(f"NeoPedal Replay (*{FILE_EXT})")
        )
        if filename:
            self.open_file(filename)

    @Slot(str)
    def openFile(self, filename: str):
        """Replay of list opened"""
        if filename:
            self.open_file(filename)

    def open_file(self, filename: str, on_loaded: Callable[[], None] | None = None):
        """Load replay file in background, then switch API to it

        Replay being played goes on while loading, opening another file meanwhile replaces this one.
        Recording goes on while loading too, stopped only once file is loaded (kept on error or cancel).

        Args:
            on_loaded: called once replay is loaded & played (not on error or if replaced).
        """
        if not self.check_api():
            return
        self._on_loaded = on_loaded
        self.loader.start(filename, api.name, api.replay_layout())
        self.refresh()

    def load_finished(self, replay_file: ReplayFile | None, error: Exception | None):
        """Replay file loaded in background: play it, or report error"""
        on_loaded, self._on_loaded = self._on_loaded, None
        if replay_file is None:
            if isinstance(error, ReplayMismatch):
                if error.reason == "source":
                    text = trm(f"Replay recorded with {error.source} API, select {error.source} API to play it.")
                else:
                    text = tr("Replay recorded with another game data structure (older game or app version), "
                              "it cannot be played.")
            else:
                text = trm(f"Unable to open replay file: {error}")
            self.refresh()
            self.show_message(text, True)
            return
        if replay.recording:  # recording kept while loading, or started meanwhile (recorder module)
            replay.stop_recording()
        replay.activate(replay_file)
        restart_api()
        if replay.player is not None:
            replay.player.set_speed(self._speed)
            replay.player.loop = self._loop
        self.load_markers()
        self.refresh()
        if on_loaded is not None:
            on_loaded()

    @Slot()
    def backToGame(self):
        """Leave replay mode, read from game again"""
        self._on_loaded = None
        self.loader.cancel()
        replay.unload()
        restart_api()
        self.refresh()

    @Slot()
    def togglePause(self):
        """Pause or resume replay"""
        if replay.player is not None:
            replay.player.set_paused(not replay.player.paused)
            self.refresh()

    @Slot(int)
    def step(self, frames: int):
        """Pause and move by frames"""
        if replay.player is not None:
            replay.player.step(frames)
            self.refresh()

    @Slot(float)
    def seekRelative(self, seconds: float):
        if replay.player is not None:
            replay.player.seek(replay.player.position + seconds)
            self.refresh()

    @Slot(float)
    def seek(self, position: float):
        """Jump to replay time"""
        if replay.player is not None:
            replay.player.seek(position)
            self.refresh()

    @Slot(float)
    def setSpeed(self, speed: float):
        """Set replay speed (kept for next replays)"""
        self._speed = speed
        if replay.player is not None:
            replay.player.set_speed(speed)
        self._publish(speed=speed)

    @Slot(bool)
    def setLoop(self, loop: bool):
        """Set replay looping (kept for next replays)"""
        self._loop = loop
        if replay.player is not None:
            replay.player.loop = loop
        self._publish(loop=loop)

    @Slot(int)
    def gotoLap(self, index: int):
        items = self._state["lapItems"]
        if replay.player is not None and 0 <= index < len(items):
            replay.player.seek(float(items[index]["time"]))
            self.refresh()

    @Slot(int)
    def gotoIncident(self, direction: int):
        """Jump to next or previous incident (3 seconds before it)"""
        player = replay.player
        incidents = self._state["incidents"]
        if player is None or not incidents:
            return
        position = player.position
        if direction > 0:
            later = [t for t in incidents if t - INCIDENT_LEAD > position + 0.5]
            target = later[0] if later else incidents[0]
        else:
            earlier = [t for t in incidents if t - INCIDENT_LEAD < position - 0.5]
            target = earlier[-1] if earlier else incidents[-1]
        player.seek(max(target - INCIDENT_LEAD, 0.0))
        self.refresh()

    # Section saved to a new file
    @Slot(int)
    def setSection(self, index: int):
        """Set section start (0) or end (1) at current position"""
        if replay.player is None or index not in (0, 1):
            return
        self._section[index] = replay.player.position
        start, end = self._section
        if start is not None and end is not None and end < start:
            self._section = [end, start]
        self._publish_section()

    @Slot()
    def saveSection(self):
        """Save replay section to new file, in background (overlays keep running)"""
        player = replay.player
        start, end = self._section
        if player is None or start is None or end is None or self.export.busy:
            return
        default = section_filename(player.replay.filename, start, end)
        filename, _ = QFileDialog.getSaveFileName(
            self._window, tr("Save Section…"), default, translate_filter(f"NeoPedal Replay (*{FILE_EXT})"))
        if not filename:
            return
        if same_file(filename, player.replay.filename):
            self.show_message(tr("Choose another file name than the open replay."), True)
            return
        if self.export.start(player.replay, filename, start, end):
            self._section_text = tr("Saving section…")
            self._publish_section()

    def export_progress(self, done: int, total: int):
        """Show section saving progress"""
        self._section_text = trm(f"Saving section: {done * 100 // max(total, 1)}%")
        self._publish_section()

    def export_finished(self, filename: str, frames: int, error: str):
        """Section saved or failed"""
        if error:
            self._section_text = ""
            self.show_message(trm(f"Unable to save replay section: {error}"), True)
        else:
            self._section_text = trm(f"{frames} frames: {os.path.basename(filename)}")
            self.refreshList()
        self._publish_section()

    def check_api(self) -> bool:
        """Replay supports LMU, rF2 & LMU legacy shared memory APIs"""
        if api_supported():
            return True
        self.show_message(api_hint(), True)
        return False
