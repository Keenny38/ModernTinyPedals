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
Session recorder: telemetry recording & replay control
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import suppress

from PySide6.QtCore import QBasicTimer, QObject, QRect, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .. import app_signal
from ..api_control import api
from ..const_api import API_LMU_NAME, API_RF2_NAME
from ..i18n import tr, trm
from ..replay import (
    FILE_EXT,
    SPEEDS,
    ReplayFile,
    ReplayLoadCancelled,
    ReplayMismatch,
    list_replays,
    replay,
    same_file,
)
from ..replay_session import api_supported, section_filename, start_api_recording
from ..setting import cfg
from ._common import BaseDialog, UIScaler, singleton_dialog, translate_filter

logger = logging.getLogger(__name__)

SLIDER_SCALE = 10  # slider steps per second
SEEK_STEP = 5.0  # seconds, arrow keys


def format_time(seconds: float) -> str:
    """Format seconds as m:ss (h:mm:ss over an hour)"""
    minutes, seconds = divmod(int(seconds), 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def format_size(size: int) -> str:
    """File size in MB"""
    return f"{size / 1048576:.1f} MB"


def restart_api():
    """Restart API so it switches between game and replay"""
    api.restart()
    app_signal.refresh.emit(True)


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
            with suppress(RuntimeError):  # window closed meanwhile
                self.finished.emit(filename, frames, error)

        self._thread = threading.Thread(target=export, daemon=True, name="Replay export")
        self._thread.start()
        return True

    def _report(self, done: int, total: int):
        with suppress(RuntimeError):  # window closed meanwhile
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
                except RuntimeError:  # window closed meanwhile
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


class MarkerSlider(QSlider):
    """Position slider showing lap & incident markers, and section to save"""

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.laps: list[float] = []
        self.incidents: list[float] = []
        self.section: tuple[float | None, float | None] = (None, None)

    def groove(self) -> QRect:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        return self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self)

    def x_of(self, seconds: float, groove: QRect) -> float:
        span = max(self.maximum() - self.minimum(), 1)
        handle = self.style().pixelMetric(QStyle.PixelMetric.PM_SliderLength, None, self)
        left = groove.left() + handle / 2
        return left + (seconds * SLIDER_SCALE - self.minimum()) / span * (groove.width() - handle)

    def paintEvent(self, event):
        groove = self.groove()
        painter = QPainter(self)
        start, end = self.section
        if start is not None or end is not None:
            left = self.x_of(start or 0.0, groove)
            right = self.x_of(end if end is not None else self.maximum() / SLIDER_SCALE, groove)
            painter.fillRect(int(left), 0, max(int(right - left), 1), self.height(), QColor(56, 189, 248, 60))
        painter.setPen(QPen(QColor(150, 150, 150), 1))
        for seconds in self.laps:
            x = int(self.x_of(seconds, groove))
            painter.drawLine(x, 0, x, self.height() // 4)
        painter.setPen(QPen(QColor("#F43F5E"), 2))
        for seconds in self.incidents:
            x = int(self.x_of(seconds, groove))
            painter.drawLine(x, self.height() * 3 // 4, x, self.height())
        painter.end()
        super().paintEvent(event)


@singleton_dialog("replay", show_error=False)
class ReplayView(BaseDialog):
    """Record shared memory, and replay it through all widgets without the game"""

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Session Recorder"))
        self._update_timer = QBasicTimer()
        self._loaded_file = ""

        # Recording
        self.button_record = QPushButton(self)
        self.button_record.clicked.connect(self.toggle_recording)
        self.label_record = QLabel(self)
        box_record = QGroupBox(tr("Recording"), self)
        layout_record = QVBoxLayout(box_record)
        layout_record.addWidget(QLabel(tr("Record Le Mans Ultimate shared memory while driving."), self))
        layout_record.addWidget(self.button_record)
        layout_record.addWidget(self.label_record)

        # Replay list
        self.replay_list = QTreeWidget(self)
        self.replay_list.setRootIsDecorated(False)
        self.replay_list.setHeaderLabels(
            [tr("Date"), tr("Track"), tr("Vehicle"), tr("Session"), tr("Duration"), tr("Size")])
        self.replay_list.itemDoubleClicked.connect(self.open_selected)
        self.replay_list.setMinimumHeight(UIScaler.size(8))
        button_open = QPushButton(tr("Open"), self)
        button_open.clicked.connect(self.open_selected)
        self.button_open = QPushButton(tr("Open Replay..."), self)
        self.button_open.clicked.connect(self.open_replay)
        button_refresh = QPushButton(tr("Refresh"), self)
        button_refresh.clicked.connect(self.refresh_list)
        button_folder = QPushButton(tr("Open Folder"), self)
        button_folder.clicked.connect(self.open_folder)
        box_list = QGroupBox(tr("Replays"), self)
        layout_list = QVBoxLayout(box_list)
        layout_list.addWidget(self.replay_list)
        layout_list_buttons = QHBoxLayout()
        for button in (button_open, self.button_open, button_refresh, button_folder):
            layout_list_buttons.addWidget(button)
        layout_list.addLayout(layout_list_buttons)

        # Playback
        self.button_stop = QPushButton(tr("Back to Game"), self)
        self.button_stop.clicked.connect(self.stop_replay)
        self.button_prev = QPushButton("|◀", self)
        self.button_prev.setToolTip(tr("Previous frame (Shift+Left)"))
        self.button_prev.clicked.connect(lambda: self.step(-1))
        self.button_play = QPushButton(self)
        self.button_play.clicked.connect(self.toggle_pause)
        self.button_next = QPushButton("▶|", self)
        self.button_next.setToolTip(tr("Next frame (Shift+Right)"))
        self.button_next.clicked.connect(lambda: self.step(1))
        self.combo_speed = QComboBox(self)
        for speed in SPEEDS:
            self.combo_speed.addItem(f"{speed:g}x", speed)
        self.combo_speed.setCurrentIndex(SPEEDS.index(1.0))
        self.combo_speed.currentIndexChanged.connect(self.set_speed)
        self.check_loop = QCheckBox(tr("Loop"), self)
        self.check_loop.setChecked(True)
        self.check_loop.toggled.connect(self.set_loop)
        self.slider = MarkerSlider(self)
        self.slider.setMinimumWidth(UIScaler.size(24))
        self.slider.sliderMoved.connect(self.seek)
        self.label_position = QLabel(self)
        self.label_file = QLabel(self)

        self.combo_lap = QComboBox(self)
        self.combo_lap.activated.connect(self.goto_lap)
        self.button_prev_incident = QPushButton(tr("◀ Incident"), self)
        self.button_prev_incident.clicked.connect(lambda: self.goto_incident(-1))
        self.button_next_incident = QPushButton(tr("Incident ▶"), self)
        self.button_next_incident.clicked.connect(lambda: self.goto_incident(1))

        self.button_section_start = QPushButton(tr("Set Start"), self)
        self.button_section_start.clicked.connect(lambda: self.set_section(0))
        self.button_section_end = QPushButton(tr("Set End"), self)
        self.button_section_end.clicked.connect(lambda: self.set_section(1))
        self.button_section_save = QPushButton(tr("Save Section..."), self)
        self.button_section_save.setToolTip(tr("Save part of replay between start & end to a new file"))
        self.button_section_save.clicked.connect(self.save_section)
        self.label_section = QLabel(self)
        self.export = SectionExport(self)
        self.export.progress.connect(self.export_progress)
        self.export.finished.connect(self.export_finished)
        self.loader = ReplayLoad(self)
        self.loader.finished.connect(self.load_finished)
        self._on_loaded: Callable[[], None] | None = None

        box_replay = QGroupBox(tr("Replay"), self)
        layout_replay = QGridLayout(box_replay)
        layout_top = QHBoxLayout()
        layout_top.addWidget(self.label_file, stretch=1)
        layout_top.addWidget(self.button_stop)
        layout_replay.addLayout(layout_top, 0, 0, 1, 6)
        layout_replay.addWidget(self.button_prev, 1, 0)
        layout_replay.addWidget(self.button_play, 1, 1)
        layout_replay.addWidget(self.button_next, 1, 2)
        layout_replay.addWidget(self.combo_speed, 1, 3)
        layout_replay.addWidget(self.check_loop, 1, 4)
        layout_replay.addWidget(self.label_position, 1, 5)
        layout_replay.addWidget(self.slider, 2, 0, 1, 6)
        layout_jump = QHBoxLayout()
        layout_jump.addWidget(QLabel(tr("Go to lap"), self))
        layout_jump.addWidget(self.combo_lap, stretch=1)
        layout_jump.addWidget(self.button_prev_incident)
        layout_jump.addWidget(self.button_next_incident)
        layout_replay.addLayout(layout_jump, 3, 0, 1, 6)
        layout_section = QHBoxLayout()
        layout_section.addWidget(self.button_section_start)
        layout_section.addWidget(self.button_section_end)
        layout_section.addWidget(self.button_section_save)
        layout_section.addWidget(self.label_section, stretch=1)
        layout_replay.addLayout(layout_section, 4, 0, 1, 6)
        layout_replay.addWidget(
            QLabel(tr("Space: play/pause, Left/Right: 5 s, Shift+Left/Right: one frame."), self), 5, 0, 1, 6)

        layout_main = QVBoxLayout(self)
        layout_main.addWidget(box_record)
        layout_main.addWidget(box_list, stretch=1)
        layout_main.addWidget(box_replay)
        layout_main.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)

        for keys, action in (
            ("Space", self.toggle_pause),
            ("Left", lambda: self.seek_relative(-SEEK_STEP)),
            ("Right", lambda: self.seek_relative(SEEK_STEP)),
            ("Shift+Left", lambda: self.step(-1)),
            ("Shift+Right", lambda: self.step(1)),
        ):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(action)

        self.section: list[float | None] = [None, None]
        self.resize(UIScaler.size(44), UIScaler.size(40))
        self.refresh_list()
        self.refresh()
        self._update_timer.start(200, self)

    def timerEvent(self, event):
        """Update position & recording state"""
        if not self.isVisible():  # hidden page (other page shown) or window: nothing to refresh
            return
        self.refresh()

    def closeEvent(self, event):
        """Stop refresh timer & replay loading, replay & recording keep running"""
        self._update_timer.stop()
        self._on_loaded = None
        self.loader.cancel()
        self.loader.wait(2)  # scanning stops at next check, file closed
        super().closeEvent(event)

    def refresh(self):
        """Refresh controls"""
        if replay.recording:
            self.button_record.setText(tr("Stop Recording"))
            self.label_record.setText(
                trm(f"{replay.recorded_frames} frames: {os.path.basename(replay.recording_file)}")
            )
        else:
            self.button_record.setText(tr("Start Recording"))
            if not replay.recording_file:
                self.label_record.setText("")
        loading = self.loader.busy
        self.button_record.setEnabled(not replay.active and not loading)

        player = replay.player
        for widget in (
            self.button_stop, self.button_play, self.button_prev, self.button_next, self.combo_speed,
            self.check_loop, self.slider, self.combo_lap, self.button_section_start, self.button_section_end,
        ):
            widget.setEnabled(player is not None)
        has_incidents = player is not None and bool(self.slider.incidents)
        self.button_prev_incident.setEnabled(has_incidents)
        self.button_next_incident.setEnabled(has_incidents)
        self.button_section_save.setEnabled(player is not None and None not in self.section and not self.export.busy)
        if loading:  # replay being played (if any) goes on meanwhile
            self.label_file.setText(
                trm(f"Loading replay {os.path.basename(self.loader.filename)}: {self.loader.percent}%"))
        if player is None:
            if not loading:
                self.label_file.setText(tr("Not replaying, reading from game."))
            self.label_position.setText("")
            self.button_play.setText(tr("Pause"))
            if self._loaded_file:
                self.load_markers()
            return
        if player.replay.filename != self._loaded_file:
            self.load_markers()
        duration = player.replay.duration
        position = player.position
        if not loading:
            self.label_file.setText(os.path.basename(player.replay.filename))
        self.label_position.setText(f"{format_time(position)} / {format_time(duration)}")
        self.button_play.setText(tr("Play") if player.paused else tr("Pause"))
        if not self.slider.isSliderDown():
            self.slider.setRange(0, int(duration * SLIDER_SCALE))
            self.slider.setValue(int(position * SLIDER_SCALE))

    def load_markers(self):
        """Lap & incident markers of loaded replay"""
        player = replay.player
        self._loaded_file = player.replay.filename if player is not None else ""
        self.section = [None, None]
        self.combo_lap.clear()
        if player is None:
            self.slider.laps, self.slider.incidents = [], []
        else:
            laps = player.replay.markers_of("lap")
            self.slider.laps = [marker.time for marker in laps]
            self.slider.incidents = [marker.time for marker in player.replay.markers_of("incident")]
            for marker in laps:
                self.combo_lap.addItem(trm(f"Lap {marker.text} ({format_time(marker.time)})"), marker.time)
        self.slider.section = (None, None)
        self.slider.update()

    # Replay list
    def refresh_list(self):
        """List replay files in telemetry folder"""
        self.replay_list.clear()
        for item_info in list_replays(cfg.path.telemetry or "."):
            info = item_info.info
            item = QTreeWidgetItem(self.replay_list, [
                time.strftime("%Y-%m-%d %H:%M", time.localtime(item_info.created)),
                str(info.get("track", "")),
                str(info.get("vehicle", "")),
                tr(str(info.get("session", ""))) if info.get("session") else "",
                format_time(item_info.duration) if item_info.duration >= 0 else "?",
                format_size(item_info.size),
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, item_info.filename)
            item.setToolTip(0, os.path.basename(item_info.filename))
        for column in range(self.replay_list.columnCount()):
            self.replay_list.resizeColumnToContents(column)

    def open_selected(self, *_):
        item = self.replay_list.currentItem()
        if item is not None:
            self.open_file(item.data(0, Qt.ItemDataRole.UserRole))

    def open_folder(self):
        folder = os.path.abspath(cfg.path.telemetry or ".")
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    # Recording
    def toggle_recording(self):
        """Start or stop recording"""
        if replay.recording:
            replay.stop_recording()
            self.refresh_list()
        elif self.check_lmu_api():
            start_api_recording()
        self.refresh()

    # Playback
    def open_replay(self):
        """Choose replay file and switch API to it"""
        if not self.check_lmu_api():
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, tr("Open Replay..."), cfg.path.telemetry, translate_filter(f"Modern Tiny Pedals Replay (*{FILE_EXT})")
        )
        if filename:
            self.open_file(filename)

    def open_file(self, filename: str, on_loaded: Callable[[], None] | None = None):
        """Load replay file in background, then switch API to it

        Replay being played goes on while loading, opening another file meanwhile replaces this one.

        Args:
            on_loaded: called once replay is loaded & played (not on error or if replaced).
        """
        if not self.check_lmu_api():
            return
        if replay.recording:
            replay.stop_recording()
        self._on_loaded = on_loaded
        self.loader.start(filename, api.name, api.replay_layout())
        self.refresh()

    def load_finished(self, replay_file: ReplayFile | None, error: Exception | None):
        """Replay file loaded in background: play it, or report error"""
        on_loaded, self._on_loaded = self._on_loaded, None
        if replay_file is None:
            if isinstance(error, ReplayMismatch):
                if error.reason == "source":
                    message = trm(f"Replay recorded with {error.source} API, select {error.source} API to play it.")
                else:
                    message = tr("Replay recorded with another game data structure (older game or app version), "
                                 "it cannot be played.")
            else:
                message = trm(f"Unable to open replay file: {error}")
            self.refresh()
            QMessageBox.warning(self, tr("Error"), message)
            return
        if replay.recording:  # started meanwhile (recorder module)
            replay.stop_recording()
        replay.activate(replay_file)
        restart_api()
        self.set_speed()
        self.set_loop(self.check_loop.isChecked())
        self.load_markers()
        self.refresh()
        if on_loaded is not None:
            on_loaded()

    def stop_replay(self):
        """Leave replay mode, read from game again"""
        self._on_loaded = None
        self.loader.cancel()
        replay.unload()
        restart_api()
        self.refresh()

    def toggle_pause(self):
        """Pause or resume replay"""
        if replay.player is not None:
            replay.player.set_paused(not replay.player.paused)
            self.refresh()

    def step(self, frames: int):
        """Pause and move by frames"""
        if replay.player is not None:
            replay.player.step(frames)
            self.refresh()

    def seek_relative(self, seconds: float):
        if replay.player is not None:
            replay.player.seek(replay.player.position + seconds)
            self.refresh()

    def set_speed(self, *_):
        """Set replay speed"""
        if replay.player is not None:
            replay.player.set_speed(float(self.combo_speed.currentData()))

    def set_loop(self, checked: bool):
        """Set replay looping"""
        if replay.player is not None:
            replay.player.loop = checked

    def seek(self, value: int):
        """Jump to slider position"""
        if replay.player is not None:
            replay.player.seek(value / SLIDER_SCALE)
            self.refresh()

    def goto_lap(self, index: int):
        if replay.player is not None and index >= 0:
            replay.player.seek(float(self.combo_lap.itemData(index)))
            self.refresh()

    def goto_incident(self, direction: int):
        """Jump to next or previous incident (3 seconds before it)"""
        player = replay.player
        if player is None or not self.slider.incidents:
            return
        position = player.position
        if direction > 0:
            later = [t for t in self.slider.incidents if t - 3 > position + 0.5]
            target = later[0] if later else self.slider.incidents[0]
        else:
            earlier = [t for t in self.slider.incidents if t - 3 < position - 0.5]
            target = earlier[-1] if earlier else self.slider.incidents[-1]
        player.seek(max(target - 3, 0.0))
        self.refresh()

    def set_section(self, index: int):
        """Set section start or end at current position"""
        if replay.player is None:
            return
        self.section[index] = replay.player.position
        start, end = self.section
        if start is not None and end is not None and end < start:
            self.section = [end, start]
        self.slider.section = (self.section[0], self.section[1])
        self.slider.update()
        self.refresh()

    def save_section(self):
        """Save replay section to new file, in background (overlays keep running)"""
        player = replay.player
        start, end = self.section
        if player is None or start is None or end is None or self.export.busy:
            return
        default = section_filename(player.replay.filename, start, end)
        filename, _ = QFileDialog.getSaveFileName(
            self, tr("Save Section..."), default, translate_filter(f"Modern Tiny Pedals Replay (*{FILE_EXT})"))
        if not filename:
            return
        if same_file(filename, player.replay.filename):
            QMessageBox.warning(self, tr("Error"), tr("Choose another file name than the open replay."))
            return
        if self.export.start(player.replay, filename, start, end):
            self.label_section.setText(tr("Saving section…"))
            self.refresh()

    def export_progress(self, done: int, total: int):
        """Show section saving progress"""
        self.label_section.setText(trm(f"Saving section: {done * 100 // max(total, 1)}%"))

    def export_finished(self, filename: str, frames: int, error: str):
        """Section saved or failed"""
        if error:
            self.label_section.setText("")
            QMessageBox.warning(self, tr("Error"), trm(f"Unable to save replay section: {error}"))
        else:
            self.label_section.setText(trm(f"{frames} frames: {os.path.basename(filename)}"))
            self.refresh_list()
        self.refresh()

    def check_lmu_api(self) -> bool:
        """Replay supports LMU, rF2 & LMU legacy shared memory APIs"""
        if api_supported():
            return True
        QMessageBox.information(
            self, tr("Session Recorder"), trm(f"Select {API_LMU_NAME} / {API_RF2_NAME} API to record or replay telemetry.")
        )
        return False
