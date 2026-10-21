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
Driver card of Home page: game profile, Driver Rank & Safety Rank (progress, change since previous rank, rank over
time), badge, race record of results files, other game accounts of this computer

Results files & profile read on a worker thread (read_driver_data), card made on the UI thread (driver_card).
Same figures & rows as the driver card of Driver Stats Viewer.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

from ..i18n import tr, trm
from ..process import driver_ranks as dr
from ..process import results_file as rf
from ..process import results_index as ri
from ..process.player_profile import PlayerProfile, player_profile
from ..setting import cfg
from .quick.formatting import country_name, format_date, localized_number


class DriverData(NamedTuple):
    """Game profile & race record of results files (worker thread)"""

    profile: PlayerProfile | None
    record: ri.RaceRecord
    last_driver: str  # player name of newest results file, "" if none


def read_driver_data() -> DriverData:
    """Profile & race record of results folders of race results page (worker thread)

    Results files kept only while a page holds them (driver stats, race results): read once here, then dropped.
    Driver card rows module imported here too (not on the UI thread when ranks come).
    """
    from .quick import stats_common  # noqa: F401

    folders = rf.results_folders(rf.chosen_results_folder(cfg.path.config))
    ri.hold_files()
    try:
        summaries = ri.read_summaries(folders)
    finally:
        ri.release_files()
    return DriverData(player_profile(folders), ri.race_record(summaries),
                      summaries[-1].driver if summaries else "")


def record_figures(record: ri.RaceRecord) -> list[dict]:
    """Race record tiles: label & value, same labels as driver card of Driver Stats Viewer"""
    figures = [
        {"label": tr("Races"), "value": str(record.races)},
        {"label": tr("Wins"), "value": str(record.wins)},
        {"label": tr("Podiums"), "value": str(record.podiums)},
    ]
    if record.average_finish:
        figures.append({"label": tr("Avg. Finish"), "value": f"P{localized_number(record.average_finish, 1)}"})
    figures.append({"label": tr("Clean Races"), "value": f"{record.clean}/{record.races}"})
    return figures


def driver_card(player: dr.DriverRanks | None, remembered: bool, updated: float,
                history: Sequence[dr.HistoryEntry], data: DriverData | None,
                others: list[dr.OtherAccount] | None = None) -> dict | None:
    """Driver card of Home page, None if nothing known (card hidden)

    Args:
        player: ranks of game menu (see RankWatcher.player), remembered: last ranks seen (game cache emptied),
            updated: when ranks were seen.
        history: rank history (change since previous rank, rank over time).
        data: profile & race record, None until read.
        others: last ranks of other game accounts of this computer.

    Returns:
        name, ranks (label, value, colors of dark & light pages, progress, change & its tone, chart points),
        badge (name, description, icon, colors), identity line, race record figures, note (ranks remembered),
        other accounts (see stats_common.other_account_rows).
    """
    from .quick.stats_common import badge_card, other_account_rows, rank_rows

    profile = data.profile if data is not None else None
    record = data.record if data is not None else None
    others = others or []
    if player is None and profile is None and not (record and record.races) and not others:
        return None
    name = (profile.name or profile.nickname) if profile is not None else ""
    name = name or (player.name if player is not None else "") or (data.last_driver if data is not None else "")
    identity = ""
    if profile is not None:
        parts = (country_name(profile.nationality), profile.team, f"#{profile.number}" if profile.number else "")
        identity = " · ".join(part for part in parts if part)
    return {
        "name": name or tr("Driver"),
        "ranks": rank_rows(player, history),
        "badge": badge_card(player),
        "identity": identity,
        "figures": record_figures(record) if record is not None and record.races else [],
        "note": trm(f"Last ranks seen in game menu, {format_date(updated)}") if (
            player is not None and remembered and updated > 0) else "",
        "others": other_account_rows(others),
    }
