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
Session debrief card of Home page: best lap against personal best, pace & consistency, theoretical best,
fuel per lap, corners to work on (each opens the telemetry viewer on it), and the lap time goal of the track &
vehicle (set on driver stats page, which also announces it once beaten)

Debrief read on a worker thread (read_debrief: lap infos, two laps loaded for corner tips), card made on
the UI thread (debrief_card: texts translated, colors left to the page).
"""

from __future__ import annotations

from typing import NamedTuple

from .. import units
from ..calculation import sec2laptime_full
from ..i18n import localized, tr, trm
from ..setting import cfg
from ..userfile.driver_history import SessionRecord, load_history
from ..userfile.driver_stats import load_driver_stats
from ..userfile.session_debrief import CornerTip, Debrief, build_debrief, corner_tips

GOAL_PRECISION = 0.0005  # lap times compared as shown (milliseconds), as driver stats page


class GoalProgress(NamedTuple):
    """Lap time goal of track & vehicle against personal best"""

    goal: float  # lap time goal (seconds)
    best: float  # personal best (seconds), 0 if none
    ratio: float  # 0 to 1: from first best lap of history to goal, -1 if unknown

    @property
    def reached(self) -> bool:
        return 0 < self.best <= self.goal + GOAL_PRECISION

    @property
    def gap(self) -> float:
        """Time still to find (seconds), 0 once reached or unknown"""
        return max(self.best - self.goal, 0.0) if self.best > 0 and not self.reached else 0.0


class DebriefData(NamedTuple):
    """Debrief of last stint (worker thread)"""

    debrief: Debrief
    tips: list[CornerTip]
    goal: GoalProgress | None  # lap time goal of track & vehicle, None if none


def stats_goal(track: str, vehicle: str) -> float:
    """Lap time goal of a track & vehicle set on driver stats page (viewer setting), 0 if none (UI thread)"""
    from .quick.stats_common import CONFIG_NAME

    goals = cfg.user.config.get(CONFIG_NAME, {}).get("goals")
    value = goals.get(f"{track}|{vehicle}") if isinstance(goals, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < 99999:
        return 0.0
    return float(value)


def goal_progress(goal: float, best: float, record: SessionRecord, records: list[SessionRecord]) -> GoalProgress:
    """Progress from the first best lap of history to the goal, as driver stats page shows it"""
    first = next((other.best for other in records if other.track == record.track
                  and other.vehicle == record.vehicle and other.best > 0), best)
    progress = GoalProgress(goal, best, -1.0)
    if progress.reached:
        return progress._replace(ratio=1.0)
    if best > 0 and first > goal:
        return progress._replace(ratio=min(max((first - best) / (first - goal), 0.0), 1.0))
    return progress


def read_debrief(record: SessionRecord, goal: float = 0.0) -> DebriefData:
    """Debrief of a stint & progress of its lap time goal (goal: 0 if none), worker thread"""
    records = load_history(cfg.path.config)
    best = load_driver_stats((record.track, record.vehicle), cfg.path.config).pb
    best = best if 0 < best < 99999 else 0.0  # 99999: no lap
    debrief = build_debrief(record, records, cfg.path.telemetry, best)
    tips = corner_tips(debrief.reference_path, debrief.compared_path, record.track)
    progress = goal_progress(goal, best, record, records) if goal > 0 else None
    return DebriefData(debrief, tips, progress)


def worth_showing(data: DebriefData) -> bool:
    """Debrief has laps or a best lap (else nothing to tell)"""
    return bool(data.debrief.laps) or data.debrief.best > 0


def seconds_text(value: float, decimals: int = 3) -> str:
    """Signed seconds, minus sign as typeset (U+2212): "+0.512 s" """
    text = localized(f"{value:+.{decimals}f}")
    return f"{text} s".replace("-", chr(0x2212))


def cause_text(kind: str, value: float) -> str:
    """Likely cause of time lost in a corner, as the Corners tab of the lap viewer says it"""
    from .lap_viewer import display_units, distance_text, number_text

    convert, unit = display_units()["speed"]
    speed = convert(value) if convert is not None else value
    texts = {
        "brake_early": lambda: trm(f"Brakes {distance_text(value)} earlier"),
        "brake_late": lambda: trm(f"Brakes {distance_text(value)} later, runs wide"),
        "min_speed": lambda: trm(f"Minimum speed {speed:.0f} {unit} lower"),
        "throttle_late": lambda: trm(f"Full throttle {distance_text(value)} later"),
        "coasting": lambda: trm(f"Coasting {number_text(value, 1)} s longer"),
        "overlap": lambda: trm(f"Throttle & brake together {number_text(value, 1)} s longer"),
        "exit_speed": lambda: trm(f"Exit speed {speed:.0f} {unit} lower"),
    }
    text = texts.get(kind)
    return text() if text is not None else ""


def goal_text(progress: GoalProgress) -> str:
    """Goal line: lap time goal, then reached or time still to find with progress"""
    line = f"{tr('Goal')} {sec2laptime_full(progress.goal)}"
    if progress.reached:
        return f"{line}: {tr('reached')}"
    if progress.gap > 0:
        text = f"{seconds_text(progress.gap).lstrip('+')} {tr('to find')}"
        if progress.ratio >= 0:
            text += f" ({localized(f'{progress.ratio * 100:.0f}')}%)"
        return f"{line}: {text}"
    return line


def goal_card(progress: GoalProgress) -> dict:
    """Goal of debrief card: goal lap time, state ("reached", "gap" or "" unknown), time to find, progress bar
    (0-1, -1 none)"""
    gap = progress.gap
    return {
        "goal": sec2laptime_full(progress.goal),
        "state": "reached" if progress.reached else "gap" if gap > 0 else "",
        "gap": f"{seconds_text(gap).lstrip('+')} {tr('to find')}" if gap > 0 else "",
        "ratio": progress.ratio,
        "percent": f"{localized(f'{progress.ratio * 100:.0f}')}%" if progress.ratio >= 0 else "",
        "text": goal_text(progress),  # screen readers
    }


def debrief_card(data: DebriefData) -> dict:
    """Debrief card of Home page (texts translated): best lap & personal best state, figures, corners to work on
    (index, label, time lost, likely cause), goal; laps recorded: the card opens them in the telemetry viewer"""
    debrief = data.debrief
    record = debrief.record
    personal = ""  # "new" personal best, "slower" than it, "" unknown
    personal_text = ""
    if debrief.best > 0 and debrief.new_personal_best:
        personal = "new"
        personal_text = tr("New personal best")
        if debrief.previous_best > 0:
            personal_text += f" ({seconds_text(debrief.gain)})"
    elif debrief.best > 0 and debrief.previous_best > 0:
        personal = "slower"
        personal_text = f"{seconds_text(debrief.gain)} {tr('vs personal best')}"
    figures = [f"{len(debrief.laps) or record.valid + record.invalid} {tr('Laps').lower()}"]
    if debrief.pace > 0:
        figures.append(f"{tr('Pace')} {sec2laptime_full(debrief.pace)} ± {localized(f'{debrief.consistency:.2f}')} s")
    if debrief.theoretical > 0 and debrief.theoretical < debrief.best - 0.0005:
        figures.append(f"{tr('Theoretical')} {sec2laptime_full(debrief.theoretical)}")
    if debrief.fuel_per_lap > 0:
        fuel_unit = cfg.units["fuel_unit"]
        fuel = units.set_unit_fuel(fuel_unit)(debrief.fuel_per_lap)
        figures.append(f"{tr('Fuel')} {localized(f'{fuel:.2f}')} {units.set_symbol_fuel(fuel_unit)}/{tr('lap')}")
    tips = []
    for index, tip in enumerate(data.tips):
        causes = [text for text in (cause_text(kind, amount) for kind, amount in tip.causes[:1]) if text]
        tips.append({"index": index, "label": tip.label, "loss": seconds_text(tip.loss, 2),
                     "cause": causes[0] if causes else "", "apex": tip.apex})
    against = ""
    if tips:
        against = tr("vs your personal best lap") if debrief.reference_kind == "personal_best" else tr(
            "typical lap vs your best lap of the session")
    return {
        "best": sec2laptime_full(debrief.best) if debrief.best > 0 else "",
        "track": record.track,
        "personal": personal,
        "personalText": personal_text,
        "figures": figures,
        "tips": tips,
        "against": against,
        "goal": goal_card(data.goal) if data.goal is not None else {},
        "canOpen": bool(debrief.best_path or debrief.reference_path),
    }


def debrief_laps(data: DebriefData) -> tuple[str, str]:
    """Laps the telemetry viewer opens on: reference lap, compared lap ("" if none), both "" if none recorded"""
    debrief = data.debrief
    if debrief.reference_path and debrief.compared_path:
        return debrief.reference_path, debrief.compared_path
    return debrief.best_path or debrief.reference_path, ""
