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
Game Replays page playback (mixin of GameReplaysBackend): playback commands, replay time, camera & HUD of the
replay open in game, car followed by camera
"""

from __future__ import annotations

import json

from PySide6.QtCore import Property, Slot

from ...i18n import tr
from .game_camera import CAMERA_GROUPS, CAMERAS, camera_commands, camera_group, camera_key
from .replays_base import ReplaysBase
from .replays_common import (
    HUD_LABELS,
    PAUSE,
    PLAY,
    PLAYBACK,
    PLAYBACK_COMMANDS,
    REPLAY,
    SESSION,
    SET_CAMERA_RESOURCE,
    leave_replay,
)


class ReplaysPlayback(ReplaysBase):
    """Playback, camera & HUD of Game Replays page"""

    # Playback, camera & HUD
    @Property(str, notify=ReplaysBase.playbackChanged)
    def lastCommand(self) -> str:
        return self.last_command

    @Property(bool, notify=ReplaysBase.playbackChanged)
    def canGoLive(self) -> bool:
        """Replay of live session opened from page: back to live possible"""
        return self.rewatching and self.state == REPLAY

    @Property(list, constant=True)
    def playbackModes(self) -> list[dict]:
        """Replay speeds (menu): command, label"""
        return [{"command": command, "text": tr(label)} for command, label in PLAYBACK]

    @Property(float, notify=ReplaysBase.replayTimeChanged)
    def replayTime(self) -> float:
        """Replay time (seconds), -1 if unknown"""
        return self.replay_time

    @Property(float, notify=ReplaysBase.replayTimeChanged)
    def replayRate(self) -> float:
        """Replay seconds per second, measured between answers"""
        return self.replay_rate

    @Property(float, notify=ReplaysBase.replayTimeChanged)
    def timeReceived(self) -> float:
        """When replay time was received, milliseconds since 1970 (QML Date.now())"""
        return self.time_received * 1000

    @Property(float, notify=ReplaysBase.replayTimeChanged)
    def liveTime(self) -> float:
        """Session time of live session (seconds, clock runs between answers), -1 if unknown or replay"""
        return self.live_time

    @Property(float, notify=ReplaysBase.replayTimeChanged)
    def sessionEnd(self) -> float:
        """Session length (seconds), -1 if unknown"""
        return self.session_end

    @Property(str, notify=ReplaysBase.cameraChanged)
    def cameraGroup(self) -> str:
        """Camera group shown in game: Driving, Onboard, Trackside, "" if unknown"""
        return camera_group(self.camera[0]) if self.state in (SESSION, REPLAY) else ""

    @Property(str, notify=ReplaysBase.cameraChanged)
    def cameraName(self) -> str:
        """Camera angle shown in game (ONBOARD03, TRACKING021...)"""
        return self.camera[1] if self.state in (SESSION, REPLAY) else ""

    @Property(str, notify=ReplaysBase.cameraChanged)
    def cameraKey(self) -> str:
        """Camera of camera menu shown in game (COCKPIT, ONBOARD02, TRACKSIDE0...), "" if unknown"""
        return self.camera_key()

    def camera_key(self) -> str:
        return camera_key(*self.camera, self.trackside_choice) if self.state in (SESSION, REPLAY) else ""

    @Property(str, notify=ReplaysBase.cameraChanged)
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
        self.trackside_choice = key if entry[2] == "Trackside" else ""
        self.send(*camera_commands(key))

    @Property(list, notify=ReplaysBase.hudChanged)
    def hudComponents(self) -> list[dict]:
        """HUD components of game: key, label, shown"""
        return [{"key": key, "text": tr(HUD_LABELS.get(key, key)), "shown": shown} for key, shown in self.hud.items()]

    @Property(bool, notify=ReplaysBase.hudChanged)
    def hudShown(self) -> bool:
        return any(self.hud.values()) if self.hud else True

    @Property(dict, notify=ReplaysBase.hudChanged)
    def hudState(self) -> dict:
        """HUD components shown in game (chat, mfd, speedo, timing, trackMap): component known if listed"""
        return dict(self.hud)

    @Property(str, notify=ReplaysBase.incidentsChanged)
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
