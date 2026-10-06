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
Pace notes audio player (Qt Multimedia), only imported while pace notes playback is enabled
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import QBasicTimer, QUrl, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .. import overlay_signal, realtime_state
from ..api_control import api
from ..module_info import minfo
from ..setting import cfg
from ..userfile.track_notes import COLUMN_PACENOTE


class PaceNotesPlayer(QMediaPlayer):
    """Pace notes player"""

    def __init__(self, parent, config: dict):
        super().__init__(parent)
        self.mcfg = config
        self.audio_device = self.set_audio_device()

        # Set update timer
        self._update_timer = QBasicTimer()
        # Timer is not unregistered if widget is deleted by parent while Python object lives on
        self.destroyed.connect(self._update_timer.stop)

        # Last data
        self._vehicle_resets = None
        self._last_notes_index: int | None = None
        self._last_pit_notes_index: int | None = None
        self._play_queue: list[str] = []

        overlay_signal.paused.connect(self.__toggle_timer)
        if realtime_state.active:  # created while driving (playback just enabled)
            self.__toggle_timer(False)

    @Slot(bool)  # type: ignore[operator]
    def __toggle_timer(self, paused: bool):
        """Toggle widget timer state"""
        if paused:
            self._update_timer.stop()
        else:
            if self._vehicle_resets != realtime_state.resets:
                self.reset_playback(realtime_state.resets)
            update_interval = max(
                self.mcfg["update_interval"],
                cfg.application["minimum_update_interval"],
            )
            self._update_timer.start(update_interval, self)

    def set_audio_device(self) -> QAudioOutput:
        """Set audio device"""
        audio_device = QAudioOutput(self)
        self.setAudioOutput(audio_device)
        return audio_device

    def reset_playback(self, vehicle_resets=None):
        """Reset"""
        self._vehicle_resets = vehicle_resets
        self._last_notes_index = None
        self._last_pit_notes_index = None
        self._play_queue.clear()
        self.stop()
        self.set_volume(self.mcfg["pace_notes_sound_volume"])

    def timerEvent(self, event):
        """Update when vehicle on track"""
        # Out pit notes
        notes_index = minfo.pacenotes.out.currentIndex
        if self._last_notes_index != notes_index:
            self._last_notes_index = notes_index
            if not api.read.vehicle.in_pits():
                self.__update_queue(minfo.pacenotes.out.currentNote.get(COLUMN_PACENOTE))

        # In pit notes
        notes_index = minfo.pacenotes.pit.currentIndex
        if self._last_pit_notes_index != notes_index:
            self._last_pit_notes_index = notes_index
            if self.mcfg["enable_playback_while_in_pit"] and api.read.vehicle.in_pits() and not api.read.vehicle.in_garage():
                self.__update_queue(minfo.pacenotes.pit.currentNote.get(COLUMN_PACENOTE))

        # Playback
        if self._play_queue:
            self.__play_next_in_queue()

    def set_source(self) -> None:
        """Set sound source"""
        pace_note = self._play_queue[0]
        sound_path = self.mcfg["pace_notes_sound_path"]
        sound_format = self.mcfg["pace_notes_sound_format"].strip(".")
        sound_file = os.path.abspath(f"{sound_path}{pace_note}.{sound_format}")
        self.setSource(QUrl.fromLocalFile(sound_file))

    def set_volume(self, value: int) -> None:
        """Set volume (0 - 100)"""
        self.audio_device.setVolume(value / 100)

    def is_playing(self) -> bool:
        """Is playing state"""
        return self.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def __update_queue(self, pace_note: Any):
        """Update playback queue"""
        if (pace_note is not None
            and len(self._play_queue) < self.mcfg["pace_notes_sound_maximum_queue"]):
            self._play_queue.append(pace_note)

    def __play_next_in_queue(self):
        """Play next sound in playback queue"""
        # Wait if is playing & not exceeded max duration
        if (self.is_playing() and
            self.position() < self.mcfg["pace_notes_sound_maximum_duration"] * 1000):
            return
        # Play next sound in queue
        self.set_source()
        self.play()
        self._play_queue.pop(0)  # remove playing notes from queue
