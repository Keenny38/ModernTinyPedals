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
Checks card of Home page: what keeps overlays from showing right, found from app & game state

Game closed: game setup reminder of the selected game (display mode, plugin). Le Mans Ultimate running without
data (its window found, shared memory empty): plugins not enabled in game. Then app settings that change what
overlays show (active state override, spectate mode, no overlay enabled), update available, lap recording off
(session debrief & telemetry). Nothing wrong while driving: ready.
"""

from __future__ import annotations

from typing import NamedTuple

from ..const_api import API_LMU_NAME
from ..i18n import tr

LEVELS = ("error", "warning", "info", "success")  # most important first


class CheckState(NamedTuple):
    """App & game state checks are made from"""

    game: str  # API name of selected game
    running: bool  # game data received
    game_window: bool  # game window found while no data is received (Le Mans Ultimate, Windows)
    override: bool  # API active state override: overlays shown whatever the game does
    spectate: bool  # spectate mode: overlays show another driver
    overlays: int  # overlays enabled
    recorder: bool  # laps recorded (Recorder module & its lap recording on)
    update: str  # newer version available ("1.2.3"), "" if none


def check(key: str, level: str, title: str, text: str, action: str = "", action_text: str = "") -> dict:
    """Check row: key, level ("error", "warning", "info" or "success"), translated texts, action key (see
    HomeBackend.runCheck) & its button text"""
    return {"key": key, "level": level, "title": title, "text": text, "action": action, "actionText": action_text}


def setup_text(game: str) -> str:
    """Game setup reminder of selected game"""
    if game == API_LMU_NAME:
        return tr("Set the game display mode to Borderless or Windowed (exclusive fullscreen hides the overlay), "
                  "then enable Settings > Gameplay > Enable plugins.")
    return tr("Set the game display mode to Borderless or Windowed (exclusive fullscreen hides the overlay), "
              "then install the rFactor 2 shared memory plugin.")


def home_checks(state: CheckState) -> list[dict]:
    """Checks to show, most important first: a "ready" row while driving with nothing wrong"""
    rows = []
    if not state.running and state.game_window and not state.override:
        rows.append(check("plugin", "error", tr("Game running without data"),
                          tr("Enable Settings > Gameplay > Enable plugins in the game, then restart it.")))
    elif not state.running and not state.override:
        rows.append(check("game", "info", tr("Game not running"), setup_text(state.game), "api", tr("API Options")))
    if state.override:
        rows.append(check("override", "warning", tr("Active State Override is on"),
                          tr("Overlays stay shown whatever the game does."), "api", tr("API Options")))
    if state.overlays <= 0:
        rows.append(check("overlays", "warning", tr("No overlay enabled"),
                          tr("Turn on overlays to see them in game."), "overlays", tr("Open Overlays")))
    if state.spectate:
        rows.append(check("spectate", "info", tr("Spectate Mode Enabled"),
                          tr("Your overlays show another driver."), "spectate", tr("Open Spectate")))
    if not state.recorder:
        rows.append(check("recorder", "info", tr("Lap recording is off"),
                          tr("Session debrief & telemetry need recorded laps: turn on the Recorder module."),
                          "modules", tr("Open Modules")))
    if state.update:
        rows.append(check("update", "info", tr("Update Available"), f"v{state.update}", "update", tr("See Update")))
    rows.sort(key=lambda row: LEVELS.index(row["level"]))  # stable: order above kept within a level
    if state.running and not any(row["level"] in ("error", "warning") for row in rows):
        rows.insert(0, check("ready", "success", tr("Ready"), tr("Game connected, overlays on.")))
    return rows
