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
Telemetry replay control
"""

import os
import time

from PySide6.QtCore import QBasicTimer, Qt
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
    QVBoxLayout,
)

from .. import app_signal
from ..api_control import api
from ..const_api import API_LMU_NAME, API_RF2_NAME
from ..i18n import tr, trm
from ..replay import FILE_EXT, REPLAY_FAMILIES, SPEEDS, replay, replay_compatible
from ..setting import cfg
from ._common import BaseDialog, UIScaler, singleton_dialog


def format_time(seconds: float) -> str:
    """Format seconds as m:ss"""
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes}:{seconds:02d}"


def restart_api():
    """Restart API so it switches between game and replay"""
    api.restart()
    app_signal.refresh.emit(True)


@singleton_dialog("replay", show_error=False)
class ReplayView(BaseDialog):
    """Record LMU shared memory, and replay it through all widgets without the game"""

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Telemetry Replay"))
        self._update_timer = QBasicTimer()

        # Recording
        self.button_record = QPushButton(self)
        self.button_record.clicked.connect(self.toggle_recording)
        self.label_record = QLabel(self)
        box_record = QGroupBox(tr("Recording"), self)
        layout_record = QVBoxLayout(box_record)
        layout_record.addWidget(QLabel(tr("Record Le Mans Ultimate shared memory while driving."), self))
        layout_record.addWidget(self.button_record)
        layout_record.addWidget(self.label_record)

        # Replay
        self.button_open = QPushButton(tr("Open Replay..."), self)
        self.button_open.clicked.connect(self.open_replay)
        self.button_stop = QPushButton(tr("Back to Game"), self)
        self.button_stop.clicked.connect(self.stop_replay)
        self.button_play = QPushButton(self)
        self.button_play.clicked.connect(self.toggle_pause)
        self.combo_speed = QComboBox(self)
        for speed in SPEEDS:
            self.combo_speed.addItem(f"{speed:g}x", speed)
        self.combo_speed.setCurrentIndex(SPEEDS.index(1.0))
        self.combo_speed.currentIndexChanged.connect(self.set_speed)
        self.check_loop = QCheckBox(tr("Loop"), self)
        self.check_loop.setChecked(True)
        self.check_loop.toggled.connect(self.set_loop)
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setMinimumWidth(UIScaler.size(24))
        self.slider.sliderMoved.connect(self.seek)
        self.label_position = QLabel(self)
        self.label_file = QLabel(self)

        box_replay = QGroupBox(tr("Replay"), self)
        layout_replay = QGridLayout(box_replay)
        layout_files = QHBoxLayout()
        layout_files.addWidget(self.button_open)
        layout_files.addWidget(self.button_stop)
        layout_replay.addLayout(layout_files, 0, 0, 1, 4)
        layout_replay.addWidget(self.label_file, 1, 0, 1, 4)
        layout_replay.addWidget(self.button_play, 2, 0)
        layout_replay.addWidget(self.combo_speed, 2, 1)
        layout_replay.addWidget(self.check_loop, 2, 2)
        layout_replay.addWidget(self.label_position, 2, 3)
        layout_replay.addWidget(self.slider, 3, 0, 1, 4)

        layout_main = QVBoxLayout(self)
        layout_main.addWidget(box_record)
        layout_main.addWidget(box_replay)
        layout_main.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)

        self.refresh()
        self._update_timer.start(200, self)

    def timerEvent(self, event):
        """Update position & recording state"""
        self.refresh()

    def closeEvent(self, event):
        """Stop refresh timer, replay & recording keep running"""
        self._update_timer.stop()
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
        self.button_record.setEnabled(not replay.active)

        player = replay.player
        for widget in (self.button_stop, self.button_play, self.combo_speed, self.check_loop, self.slider):
            widget.setEnabled(player is not None)
        if player is None:
            self.label_file.setText(tr("Not replaying, reading from game."))
            self.label_position.setText("")
            self.button_play.setText(tr("Pause"))
            return
        duration = player.replay.duration
        position = player.position
        self.label_file.setText(os.path.basename(player.replay.filename))
        self.label_position.setText(f"{format_time(position)} / {format_time(duration)}")
        self.button_play.setText(tr("Play") if player.paused else tr("Pause"))
        if not self.slider.isSliderDown():
            self.slider.setRange(0, int(duration * 10))
            self.slider.setValue(int(position * 10))

    def toggle_recording(self):
        """Start or stop recording"""
        if replay.recording:
            replay.stop_recording()
        elif self.check_lmu_api():
            filename = os.path.join(
                cfg.path.telemetry or ".", time.strftime(f"replay-%Y-%m-%d-%H-%M-%S{FILE_EXT}")
            )
            replay.start_recording(filename, api.raw_data, rest_source=api.rest_data, header_extra=api.replay_header())
        self.refresh()

    def open_replay(self):
        """Load replay file and switch API to it"""
        if not self.check_lmu_api():
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, tr("Open Replay..."), cfg.path.telemetry, f"Modern Tiny Pedals Replay (*{FILE_EXT})"
        )
        if not filename:
            return
        if replay.recording:
            replay.stop_recording()
        try:
            player = replay.load(filename)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, tr("Error"), trm(f"Unable to open replay file: {error}"))
            return
        if not replay_compatible(player.replay.source, api.name):
            replay.unload()
            QMessageBox.warning(
                self, tr("Error"),
                trm(f"Replay recorded with {player.replay.source} API, select {player.replay.source} API to play it."))
            return
        restart_api()
        self.set_speed()
        self.set_loop(self.check_loop.isChecked())
        self.refresh()

    def stop_replay(self):
        """Leave replay mode, read from game again"""
        replay.unload()
        restart_api()
        self.refresh()

    def toggle_pause(self):
        """Pause or resume replay"""
        if replay.player is not None:
            replay.player.set_paused(not replay.player.paused)
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
            replay.player.seek(value / 10)
            self.refresh()

    def check_lmu_api(self) -> bool:
        """Replay supports LMU, rF2 & LMU legacy shared memory APIs"""
        if any(api.name in family for family in REPLAY_FAMILIES):
            return True
        QMessageBox.information(
            self, tr("Telemetry Replay"), trm(f"Select {API_LMU_NAME} / {API_RF2_NAME} API to record or replay telemetry.")
        )
        return False
