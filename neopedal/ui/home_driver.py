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
Driver card of Home page: game profile, Driver Rank & Safety Rank (with change since previous rank and badge),
race record of results files

Results files & profile read on a worker thread (read_driver_data), card text made on the UI thread
(driver_card_text). Same figures as the driver card of Driver Stats Viewer.
"""

from __future__ import annotations

import html
from typing import NamedTuple

from ..i18n import tr, trm
from ..process import driver_ranks as dr
from ..process import results_file as rf
from ..process import results_index as ri
from ..process.player_profile import PlayerProfile, player_profile
from ..setting import cfg
from ..template.setting_status_colors import STATUS_COLORS
from ..userfile.badge_icons import badge_info
from .quick.formatting import country_name, format_date, localized_number

RANK_FIELDS = (("DR", "driver"), ("SR", "safety"))  # short label, field of DriverRanks


class DriverData(NamedTuple):
    """Game profile & race record of results files (worker thread)"""

    profile: PlayerProfile | None
    record: ri.RaceRecord
    last_driver: str  # player name of newest results file, "" if none


def read_driver_data() -> DriverData:
    """Profile & race record of results folders of race results page (worker thread)

    Results files kept only while a page holds them (driver stats, race results): read once here, then dropped.
    """
    folders = rf.results_folders(rf.chosen_results_folder(cfg.path.config))
    ri.hold_files()
    try:
        summaries = ri.read_summaries(folders)
    finally:
        ri.release_files()
    return DriverData(player_profile(folders), ri.race_record(summaries),
                      summaries[-1].driver if summaries else "")


def rank_text(label: str, rank: dr.Rank, change: int, light: bool) -> str:
    """Rank in its color, progress & change since previous rank: "DR Silver 2 40% ▲ +10%" """
    colors = dr.RANK_COLORS_LIGHT if light else dr.RANK_COLORS
    color = colors.get(rank.name.casefold(), "")
    name = html.escape(rank.text)
    text = f"<span style='color:{color}'>{label} {name}</span>" if color else f"{label} {name}"
    text = f"<b>{text}</b> {max(min(rank.progress, 100), 0)}%"
    if change:
        arrow = "▲" if change > 0 else "▼"
        color = STATUS_COLORS["gain" if change > 0 else "loss"][light]  # as every gain / loss
        text += f" <span style='color:{color}'>{arrow} {change:+d}%</span>"
    return text


def other_account_text(other: dr.OtherAccount, light: bool) -> str:
    """Line of another game account: Steam name, last ranks seen (colors), badge, date"""
    colors = dr.RANK_COLORS_LIGHT if light else dr.RANK_COLORS
    parts = []
    for label, field in RANK_FIELDS:
        rank = getattr(other.ranks, field)
        if rank is not None:
            color = colors.get(rank.name.casefold(), "")
            text = html.escape(f"{label} {rank.text}")
            parts.append(f"<span style='color:{color}'>{text}</span>" if color else text)
    if other.ranks.badge:
        info = badge_info(other.ranks.badge)
        parts.append(html.escape(tr(info.name) if info is not None else other.ranks.badge))
    name = html.escape(other.name or tr("Other account"))
    return f"{name}: " + " \u00b7 ".join(parts) + f" ({html.escape(format_date(other.time))})"


def driver_card_text(player: dr.DriverRanks | None, remembered: bool, updated: float,
                     history: list[dr.HistoryEntry], data: DriverData | None, light: bool,
                     others: list[dr.OtherAccount] | None = None) -> tuple[str, str] | None:
    """Value & detail of driver card, None if nothing known (card hidden)

    Args:
        player: ranks of game menu (see RankWatcher.player), remembered: last ranks seen (game cache emptied),
            updated: when ranks were seen.
        history: rank history (change since previous rank).
        data: profile & race record, None until read.
        light: light app theme (rank colors).
    """
    profile = data.profile if data is not None else None
    record = data.record if data is not None else None
    others = others or []
    if player is None and profile is None and not (record and record.races) and not others:
        return None
    name = (profile.name or profile.nickname) if profile is not None else ""
    name = name or (player.name if player is not None else "") or (data.last_driver if data is not None else "")
    lines = [f"<b>{html.escape(name)}</b>" if name else f"<b>{html.escape(tr('Driver'))}</b>"]
    if player is not None:
        ranks = [rank_text(label, rank, dr.rank_change_since(history, field, rank), light)
                 for label, field in RANK_FIELDS if (rank := getattr(player, field)) is not None]
        if player.badge:  # game badge in its color
            info = badge_info(player.badge)
            badge = html.escape(tr(info.name) if info is not None else player.badge)
            color = (info.light_color if light else info.color) if info is not None else ""
            ranks.append(f"<span style='color:{color}'>{badge}</span>" if color else badge)
        if ranks:
            lines.append(" · ".join(ranks))
    details = []
    if profile is not None:
        identity = (country_name(profile.nationality), profile.team, f"#{profile.number}" if profile.number else "")
        if any(identity):
            details.append(html.escape(" · ".join(part for part in identity if part)))
    if record is not None and record.races:
        figures = [  # same labels as driver card of Driver Stats Viewer
            f"{tr('Races')} {record.races}",
            f"{tr('Wins')} {record.wins}",
            f"{tr('Podiums')} {record.podiums}",
            f"{tr('Avg. Finish')} P{localized_number(record.average_finish, 1)}" if record.average_finish else "",
            f"{tr('Clean Races')} {record.clean}/{record.races}",
        ]
        details.append(html.escape(" · ".join(figure for figure in figures if figure)))
    if player is not None and remembered and updated > 0:
        details.append(html.escape(trm(f"Last ranks seen in game menu, {format_date(updated)}")))
    details.extend(other_account_text(other, light) for other in others)  # other game accounts of this computer
    return "<br>".join(lines), "<br>".join(details)
