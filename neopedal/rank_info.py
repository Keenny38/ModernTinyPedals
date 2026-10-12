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
Player Driver Rank & Safety Rank (Le Mans Ultimate), shared by overlay & Driver Stats page

Read from the game menu storage file of the game folder found like race results (folder chosen on
race results page, else Steam libraries), see process/driver_ranks.py.
"""

from __future__ import annotations

import os

from .process import driver_ranks as dr
from .process import player_profile as pp
from .process import results_file as rf
from .setting import cfg

GAME = "LMU"  # only game with ranks


def locate() -> dr.Located:
    """Storage file of game folder, Steam ID & names of player (game profile)"""
    for folder in rf.results_folders(rf.chosen_results_folder(cfg.path.config)):
        if rf.game_of_path(folder) != GAME:
            continue
        users = pp.recent_steam_users(rf.steam_folder())
        return dr.Located(os.path.join(rf.game_root(folder), dr.STORAGE_FILE), users[0] if users else "",
                          tuple(rf.profile_player_names(folder)))
    return dr.Located("", "", ())


def history_path() -> str:
    return os.path.join(cfg.path.config, dr.HISTORY_FILE)


ranks = dr.RankWatcher(locate, history_path)
