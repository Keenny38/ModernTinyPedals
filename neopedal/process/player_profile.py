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
Driver profile of the game (LMU, rFactor 2) and Steam profile picture, read from local files only

Game profile: "UserData/player/Settings.JSON" (DRIVER "Player Name", "Player Nick", "Nationality",
CUSTOMLIVERY "teamName", "vehicleNumber"). Profile picture: avatar Steam keeps of the account last signed in
("config/loginusers.vdf" MostRecent, "config/avatarcache/<SteamID64>.png"), nothing downloaded.
"""

from __future__ import annotations

import json
import os
import re
from typing import NamedTuple

from . import results_file as rf

STEAM_USER = re.compile(r'"(?P<id>\d{17})"\s*\{(?P<body>[^{}]*)\}')
MOST_RECENT = re.compile(r'"MostRecent"\s+"1"', re.I)


class PlayerProfile(NamedTuple):
    """Driver of game profile, "" when unknown"""

    name: str
    nickname: str
    nationality: str  # ISO country code: "FR"
    team: str
    number: str
    avatar: str  # Steam profile picture file


def _text(section: object, key: str) -> str:
    value = section.get(key) if isinstance(section, dict) else None
    return value.strip() if isinstance(value, str) else ""


def read_profile(game_root: str) -> PlayerProfile | None:
    """Game profile of game folder, None if not found"""
    path = os.path.join(game_root, "UserData", "player", "Settings.JSON")
    try:
        with open(path, encoding="utf-8", errors="replace") as file:
            settings = json.load(file)
    except (OSError, ValueError):
        return None
    if not isinstance(settings, dict):
        return None
    driver = settings.get("DRIVER")
    livery = settings.get("CUSTOMLIVERY")
    name = _text(driver, "Player Name")
    if not name:
        return None
    return PlayerProfile(name, _text(driver, "Player Nick"), _text(driver, "Nationality").upper()[:3],
                         _text(livery, "teamName"), _text(livery, "vehicleNumber"), "")


def steam_avatar(steam: str) -> str:
    """Profile picture Steam keeps of account last signed in, "" if none"""
    if not steam:
        return ""
    try:
        with open(os.path.join(steam, "config", "loginusers.vdf"), encoding="utf-8", errors="replace") as file:
            content = file.read()
    except OSError:
        return ""
    users = [(match["id"], bool(MOST_RECENT.search(match["body"]))) for match in STEAM_USER.finditer(content)]
    recent = [user for user, most_recent in users if most_recent] or [user for user, _ in users[:1]]
    for user in recent:
        path = os.path.join(steam, "config", "avatarcache", f"{user}.png")
        if os.path.isfile(path):
            return path
    return ""


def player_profile(results_folders: tuple[str, ...] = ()) -> PlayerProfile | None:
    """Driver profile of first game found (results folders chosen, else games of Steam libraries), with
    Steam profile picture"""
    folders = results_folders or tuple(rf.find_results_folders().values())
    for folder in folders:
        profile = read_profile(rf.game_root(folder))
        if profile is not None:
            return profile._replace(avatar=steam_avatar(rf.steam_folder()))
    return None
