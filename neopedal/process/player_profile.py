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
import sys
from typing import NamedTuple

from . import results_file as rf

STEAM_USER = re.compile(r'"(?P<id>\d{17})"\s*\{(?P<body>[^{}]*)\}')
MOST_RECENT = re.compile(r'"MostRecent"\s+"1"', re.I)
TIMESTAMP = re.compile(r'"Timestamp"\s+"(\d+)"', re.I)
PERSONA = re.compile(r'"PersonaName"\s+"([^"]*)"', re.I)
STEAM_ID_BASE = 76561197960265728  # SteamID64 of account ID 0 (individual accounts)


def active_steam_user() -> str:
    """SteamID64 of account signed in to running Steam (Windows registry, read only), "" if none or unknown"""
    if sys.platform != "win32":
        return ""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\ActiveProcess") as key:
            account, _ = winreg.QueryValueEx(key, "ActiveUser")
    except OSError:
        return ""
    return str(STEAM_ID_BASE + account) if isinstance(account, int) and account > 0 else ""


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
    except (OSError, ValueError, RecursionError):  # RecursionError: nested too deeply
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


class SteamAccount(NamedTuple):
    """Steam account of this computer: SteamID64, name shown in Steam, profile picture file ("" if none)"""

    steam_id: str
    name: str
    avatar: str


def steam_accounts(steam: str, active: str | None = None) -> list[SteamAccount]:
    """Steam accounts of this computer, account in use first: signed in to running Steam (active, read from
    registry if None), else marked most recent (older Steam), else last signed in (timestamp)"""
    if not steam:
        return []
    try:
        with open(os.path.join(steam, "config", "loginusers.vdf"), encoding="utf-8", errors="replace") as file:
            content = file.read()
    except OSError:
        return []
    users = []
    for match in STEAM_USER.finditer(content):
        stamp = TIMESTAMP.search(match["body"])
        persona = PERSONA.search(match["body"])
        avatar = os.path.join(steam, "config", "avatarcache", f"{match['id']}.png")
        account = SteamAccount(match["id"], persona.group(1) if persona else "", avatar if os.path.isfile(avatar) else "")
        users.append((account, bool(MOST_RECENT.search(match["body"])), int(stamp.group(1)) if stamp else 0))
    users.sort(key=lambda user: (user[1], user[2]), reverse=True)  # stable: file order when equal
    accounts = [account for account, _, _ in users]
    active = active_steam_user() if active is None else active
    in_use = next((account for account in accounts if account.steam_id == active), None)
    if in_use is not None:
        accounts.remove(in_use)
        accounts.insert(0, in_use)
    return accounts


def recent_steam_users(steam: str, active: str | None = None) -> list[str]:
    """Steam IDs (SteamID64) of accounts of this computer, account in use first (see steam_accounts)"""
    return [account.steam_id for account in steam_accounts(steam, active)]


def steam_avatar(steam: str) -> str:
    """Profile picture Steam keeps of account in use (else of another account), "" if none"""
    return next((account.avatar for account in steam_accounts(steam) if account.avatar), "")


def player_profile(results_folders: tuple[str, ...] = ()) -> PlayerProfile | None:
    """Driver profile of first game found (results folders chosen, else games of Steam libraries), with
    Steam profile picture"""
    folders = results_folders or tuple(rf.find_results_folders().values())
    for folder in folders:
        profile = read_profile(rf.game_root(folder))
        if profile is not None:
            return profile._replace(avatar=steam_avatar(rf.steam_folder()))
    return None
