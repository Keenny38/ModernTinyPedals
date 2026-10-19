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
race results page, else Steam libraries), see process/driver_ranks.py. Read online from RaceControl when
enable_online_driver_ranks is on (game no longer keeps them in that file), see process/raceos.py, with ranks of
the other drivers of an online session (RaceControl profiles by name), see process/field_ranks.py.
"""

from __future__ import annotations

import os
from typing import NamedTuple

from .process import driver_ranks as dr
from .process import field_ranks as fr
from .process import player_profile as pp
from .process import results_file as rf
from .setting import cfg

GAME = "LMU"  # only game with ranks
PROBE_ROUTE = "/rest/watch/focus"  # cheap answer of a running game (in menus too)
JOIN_ROUTE = "/rest/multiplayer/join/state"  # "JOIN_JOINED_SERVER" while on an online server
GAME_TIMEOUT = 3.0


def locate() -> dr.Located:
    """Storage file of game folder, Steam ID & names of player (game profile)"""
    for folder in rf.results_folders(rf.chosen_results_folder(cfg.path.config)):
        if rf.game_of_path(folder) != GAME:
            continue
        accounts = pp.steam_accounts(rf.steam_folder())
        return dr.Located(os.path.join(rf.game_root(folder), dr.STORAGE_FILE),
                          accounts[0].steam_id if accounts else "", tuple(rf.profile_player_names(folder)),
                          tuple((account.steam_id, account.name, account.avatar) for account in accounts),
                          folder)
    return dr.Located("", "", ())


def history_path() -> str:
    return os.path.join(cfg.path.config, dr.HISTORY_FILE)


def _game_get(route: str) -> tuple[int, bytes]:
    """Status & body of game Rest API GET route, (0, b"") if game not running or access disabled"""
    from .game_rest_cache import fetch_game, lmu_address

    address = lmu_address()
    return fetch_game(address, route, GAME_TIMEOUT) if address is not None else (0, b"")


_client = None


def online_client():
    """RaceControl client shared by player & field ranks (one sign in at a time)"""
    global _client
    if _client is None:
        from .const_app import APP_NAME, VERSION
        from .process import raceos

        _client = raceos.RaceOSClient(lambda: raceos.game_ticket(_game_get), user_agent=f"{APP_NAME}/{VERSION}")
    return _client


def online_enabled() -> bool:
    return bool(cfg.application.get("enable_online_driver_ranks", True))


class OnlineRanks:
    """Player ranks of RaceControl (option enable_online_driver_ranks, on by default), see dr.OnlineSource"""

    enabled = staticmethod(online_enabled)

    @staticmethod
    def game_running() -> bool:
        return _game_get(PROBE_ROUTE)[0] != 0

    @staticmethod
    def fetch(account: str) -> dr.DriverRanks | None:
        return online_client().fetch(account)

    @staticmethod
    def forget() -> None:
        if _client is not None:
            _client.forget()


class FieldReads:
    """Reads of field ranks, see fr.FieldSource"""

    enabled = staticmethod(online_enabled)

    @staticmethod
    def joined() -> bool:
        status, body = _game_get(JOIN_ROUTE)
        return status == 200 and b"JOIN_JOINED_SERVER" in body

    @staticmethod
    def post(path: str, payload):
        return online_client().post(path, payload, ranks.account)


def _session_ended() -> None:
    field.session_ended()


ranks = dr.RankWatcher(locate, lambda: history_path(), active_account=pp.active_steam_user, online=OnlineRanks(),
                       session_ended=_session_ended)
field = fr.FieldRanks(FieldReads())


def poll_field(names) -> None:
    """Player, team & field ranks read in background when due (names of drivers of session)"""
    ranks.poll()
    field.poll(names)


# Lookups of overlays (each row, each update) kept until ranks change: drivers list & field ranks are replaced whole
# when they change (never changed in place), compared by identity, serials & size (a dict filled in place is seen)
MEMO_NAMES = 1024  # names kept at most (memo emptied beyond: names of many sessions while ranks never change)
MEMO_LEVELS = 64  # driver lists kept at most (field level of each class)


class _Memo(NamedTuple):
    drivers: list[dr.DriverRanks]  # ranks.drivers when made
    known: dict[str, dr.DriverRanks]  # field.known when made
    key: tuple[int, int, int]  # ranks.serial, field.serial, len(known)
    ranks: dict[str, dr.DriverRanks | None]  # name -> ranks found
    levels: dict[tuple[str, ...], fr.FieldLevel]  # names of drivers -> field level


_memo = _Memo([], {}, (-1, -1, -1), {}, {})


def _current_memo() -> _Memo:
    """Memo of current ranks, new one once they changed (any thread: replaced whole)"""
    global _memo
    drivers, known = ranks.drivers, field.known
    key = (ranks.serial, field.serial, len(known))
    memo = _memo
    if memo.drivers is not drivers or memo.known is not known or memo.key != key:
        memo = _memo = _Memo(drivers, known, key, {}, {})
    return memo


def field_level(names) -> fr.FieldLevel:
    """Average ranks of drivers of session whose ranks are known (player, team members & online field)"""
    names = tuple(names)
    levels = _current_memo().levels
    level = levels.get(names)
    if level is None:
        if len(levels) >= MEMO_LEVELS:
            levels.clear()
        level = levels[names] = fr.average_level(
            found for name in {fr.driver_key(name): name for name in names}.values()
            if (found := driver_ranks(name)) is not None)
    return level


def driver_ranks(name: str) -> dr.DriverRanks | None:
    """Ranks of a driver of session: player & team members (game menu, RaceControl), else RaceControl profile of
    a driver of the online session (option on), None if unknown"""
    found_by_name = _current_memo().ranks
    try:
        return found_by_name[name]
    except KeyError:  # first lookup of name since ranks changed
        pass
    if len(found_by_name) >= MEMO_NAMES:
        found_by_name.clear()
    found = found_by_name[name] = ranks.find_name(fr.strip_suffix(name)) or field.ranks_of(name)
    return found
