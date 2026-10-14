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
Broadcast Director camera desk (QML: backend.camera): camera of the game, HUD parts shown, replay playback, commands
sent to the game in background, in order (cuts of the director & operator go through send)
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Property, QTimer, Signal, Slot

from ...game_rest import GameRequest
from ...game_rest_cache import rest_cache
from ...i18n import tr
from ...process import director as dr
from . import game_camera as gc
from .director_shared import GAME_UI_DELAY_MS, HUD_RESOURCE, REPLAY, SESSION, DirectorPart

if TYPE_CHECKING:
    from .director_backend import DirectorBackend


class CameraDesk(DirectorPart):
    """Camera & HUD of the game, replay playback, commands queue"""

    cameraChanged = Signal()
    hudChanged = Signal()
    playbackChanged = Signal()

    def __init__(self, page: DirectorBackend):
        super().__init__(page)
        self.camera = ("", "")  # group & name told by game
        self.hud: dict[str, bool] = {}  # HUD parts of the game shown (HUD menu), asked when the menu opens
        self.trackside_choice = ""
        self.last_command = ""  # replay playback command sent last
        self._cameras: list[dict] | None = None
        self.request_command = GameRequest(self, (), self.command_done, self.command_failed)
        self.command_queue: list[tuple[gc.Command, ...]] = []

    def stop(self):
        """Page closed: commands not sent yet dropped"""
        self.command_queue.clear()

    def answered(self, state: dict[str, Any]):
        """Camera & HUD parts told by a new answer of the game"""
        if state["camera"] != self.camera:
            self.camera = state["camera"]
            self.cameraChanged.emit()
        if "hud" in state:
            self.page.game.need_hud = False
            if state["hud"] != self.hud:
                self.hud = state["hud"]
                self.hudChanged.emit()

    def state_changed(self, state: str):
        """Game state changed: playback command forgotten out of replays"""
        if state != REPLAY and self.last_command:
            self.last_command = ""
            self.playbackChanged.emit()

    # Commands
    def send(self, *commands: gc.Command):
        """Commands to game in background, in order, after commands sent before"""
        if commands:
            self.command_queue.append(commands)
        if self.request_command.busy or not self.command_queue:
            return
        batch = self.command_queue.pop(0)
        address = self.page.game.game_address()
        self.request_command.start(lambda: gc.send_commands(batch, address))

    def command_done(self, accepted: bool):
        for resource in (gc.ACTIVE_RESOURCE, gc.FOCUS_RESOURCE, gc.CAMERA_RESOURCE, HUD_RESOURCE):  # changed: asked again
            rest_cache.forget(resource)
        page = self.page
        if not self.command_queue:
            page.commands_sent(accepted)
        if not accepted:
            page.notify(tr("Game did not accept the command"), True)
        if self.command_queue:
            self.send()

    def command_failed(self):
        self.command_done(False)

    # Camera
    def camera_key(self) -> str:
        return gc.camera_key(*self.camera, self.trackside_choice) if self.page.state in (SESSION, REPLAY) else ""

    @Property(str, notify=cameraChanged)
    def cameraKey(self) -> str:
        return self.camera_key()

    @Property(str, notify=cameraChanged)
    def cameraLabel(self) -> str:
        key = self.camera_key()
        entry = next((entry for entry in gc.CAMERAS if entry[0] == key), None)
        if entry is None:
            return f"{tr(gc.camera_group(self.camera[0]))} · {self.camera[1]}" if self.camera[1] else ""
        return f"{tr(entry[2])} · {tr(entry[1]).replace('%1', str(entry[4]))}"

    @Property(list, constant=True)
    def cameras(self) -> list[dict]:
        return self.camera_list()

    def camera_list(self) -> list[dict]:
        """Cameras of camera desk: key, label, group (made once)"""
        if self._cameras is None:
            self._cameras = [{"key": key, "text": tr(label).replace("%1", str(group_number)), "group": group,
                              "groupText": tr(group)}
                             for key, label, group, _, group_number in gc.CAMERAS]
        return self._cameras

    @Property(dict, constant=True)
    def camerasByGroup(self) -> dict[str, list[dict]]:
        """Cameras of each camera group (desk buttons, no filtering in QML)"""
        groups: dict[str, list[dict]] = {}
        for camera in self.camera_list():
            groups.setdefault(camera["group"], []).append(camera)
        return groups

    @Slot(str)
    def selectCamera(self, key: str):
        """Operator camera on car on air (director held a while)"""
        page = self.page
        if not page.can_command() or key not in gc.CAMERA_KEYS:
            return
        self.trackside_choice = key if key.startswith("TRACKSIDE") else ""
        self.send(*gc.camera_commands(key))
        page.last_cut = time.monotonic()
        slot = page.on_air_slot if page.on_air_slot >= 0 else page.focus
        if slot >= 0:
            page.director.manual(slot, key, time.monotonic())
            page.set_on_air(slot, dr.MANUAL)
        self.cameraChanged.emit()

    @Slot(str, int)
    def stepCamera(self, group: str, direction: int):
        """Previous (-1) or next (1) angle of camera group (Driving, Onboard, Trackside)"""
        if group in gc.CAMERA_GROUPS and self.page.can_command():
            self.trackside_choice = ""
            body = json.dumps({"cameraGroup": group, "direction": -1 if direction < 0 else 1})
            self.send(("POST", gc.SET_CAMERA_RESOURCE, body))
            self.page.last_cut = time.monotonic()

    # HUD of the game (as the Game Replays page): all or each part, clean pictures for the stream
    @Property(dict, notify=hudChanged)
    def hudState(self) -> dict:
        """HUD parts shown in game (chat, mfd, speedo, timing, trackMap): part known if listed"""
        return dict(self.hud)

    @Slot()
    def refreshHud(self):
        """HUD menu opened: parts shown asked again with the next game state (asked now)"""
        if self.page.can_command():
            game = self.page.game
            game.need_hud = True
            if not game.request_state.busy:
                game.refresh()

    @Slot(bool)
    def setHudShown(self, shown: bool):
        """Whole HUD of the game (replay controls included) shown or hidden"""
        if not self.page.can_command():
            return
        value = "true" if shown else "false"
        self.hud = dict.fromkeys(self.hud, shown)
        self.hudChanged.emit()
        self.send(("POST", f"/rest/hud/toggleAllComponents/{value}"), ("POST", "/rest/sessions/setHudOnWatchScreen", value),
                  ("POST", "/rest/watch/replay/setReplayUIVisible", value))

    @Slot(str)
    def toggleHudComponent(self, key: str):
        if key in self.hud and self.page.can_command():
            self.hud = {**self.hud, key: not self.hud[key]}
            self.hudChanged.emit()
            self.send(("POST", f"/rest/hud/toggle/{key}"))

    @Slot()
    def toggleGameUi(self):
        """Whole game UI (top bar, standings, replay bar & HUD) shown or hidden, as a middle click in game does
        (no Rest API command for its web panels): middle click posted to the game window of this computer"""
        page = self.page
        if not page.can_command():
            return
        if not gc.click_game_ui(page.game.local_game()):
            page.notify(tr("Game window not found: LMU must be running on this computer."), True)
            return
        QTimer.singleShot(GAME_UI_DELAY_MS, self, self.refreshHud)

    # Replay playback
    @Property(str, notify=playbackChanged)
    def lastCommand(self) -> str:
        return self.last_command

    @Slot(str)
    def playback(self, command: str):
        if command in gc.PLAYBACK_COMMANDS and self.page.state == REPLAY:
            self.last_command = command
            self.playbackChanged.emit()
            self.send(("PUT", f"/rest/watch/replayCommand/{command}"))

    @Slot()
    def togglePlay(self):
        self.playback(gc.PAUSE if self.last_command not in ("", gc.PAUSE) else gc.PLAY)

    @Slot(int)
    def jump(self, seconds: int):
        """Replay moves back (negative) or forward"""
        page = self.page
        if page.state == REPLAY and page.session_time >= 0:
            self.send(("PUT", f"/rest/watch/replaytime/{max(int(page.session_time + seconds), 0)}"))
