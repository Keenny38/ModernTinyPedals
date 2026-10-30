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
Broadcast Director timing table (QML: backend.timing): race, qualifying & pits views, columns ordered & chosen per
view (page settings), rows made at each answer while the table is shown
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from ...formatter import driver_display_name
from ...i18n import tr
from ...process import director as dr
from ...template.setting_status_colors import energy_tone
from .director_shared import (
    TIMING_COLUMN_ROLES,
    TIMING_COLUMNS,
    TIMING_ROLES,
    TIMING_VIEWS,
    DirectorPart,
    class_color,
    delta_text,
    gap_tone,
    interval,
    interval_text,
    lap_text,
    localized,
    seconds_text,
    sector_tone,
    status_text,
    timing_setting,
)
from .models import DictListModel

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .director_backend import DirectorBackend

# Rows: values of every column (Python callers) & cells of the columns shown (QML reads one role per row, not one
# Python data() call per cell & value)
TIMING_CELL_ROLES = (*TIMING_ROLES, "cells")
TONE_MARKS = {"fastest": "◆ ", "gain": "● "}  # marks besides colors (colorblind): best of class, personal best
# Lap & sector times: record mark right of the time, as every page (TpLapTime: ◆ purple first, ● green)
TIME_KEYS = frozenset(("best", "last", "s1", "s2", "s3"))
TIME_MARKS = {"fastest": " ◆", "gain": " ●"}


def timing_cell(row: dict[str, Any], key: str) -> dict[str, Any]:
    """Cell of column key: text (marks included) & tone (theme.tone name, "" plain), tyres & energy level for the
    badges & bar drawn under their cells"""
    if key == "tyres":
        return {"text": "", "tone": "", "tyres": row["tyreList"]}
    value, tone = row[key], row.get(f"{key}Tone", "")
    if key == "interval" and row["battle"]:  # battle: trend arrow, accent unless the gap has its own color
        trend = row["trend"]
        return {"text": ("▼ " if trend < 0 else "▲ " if trend > 0 else "• ") + value, "tone": tone or "accent"}
    if key == "change":
        return {"text": value, "tone": ("gain" if row["changeValue"] > 0 else "loss") if value else ""}
    if key in TIME_KEYS:
        return {"text": value + TIME_MARKS.get(tone, "") if value else value, "tone": tone}
    cell = {"text": TONE_MARKS.get(tone, "") + value, "tone": tone}
    if key == "energy":
        cell["level"] = row["energyLevel"]
    return cell


def timing_cells(row: dict[str, Any], keys: Iterable[str]) -> list[dict[str, Any]]:
    """Cells of the columns shown, in their order"""
    return [timing_cell(row, key) for key in keys]


class TimingTable(DirectorPart):
    """Timing table of the page (separate panel): rows of every column, columns of the view shown"""

    timingChanged = Signal()
    timingColumnsChanged = Signal()

    def __init__(self, page: DirectorBackend, settings: dict[str, Any]):
        super().__init__(page)
        self.timing_columns = timing_setting(settings.get("timing"))
        view = settings.get("timing_view")
        self.timing_view = view if view in TIMING_VIEWS else "race"
        self.timing_open = False  # timing table shown: its rows made at each answer
        self._timing_stale = False  # answers came while the page was hidden: timing rows made once shown
        self._timing_model = DictListModel(TIMING_CELL_ROLES, self)
        self._timing_column_model = DictListModel(TIMING_COLUMN_ROLES, self)
        self.sync_timing_columns()

    def page_settings(self) -> dict[str, Any]:
        return {"timing": self.timing_columns, "timing_view": self.timing_view}

    def page_shown(self):
        """Rows made again if answers came while the page was hidden"""
        if self._timing_stale and self.timing_open:
            self.update_timing()

    def answered(self, shown: bool):
        """New answer of the game: rows made now (page shown), or once shown"""
        if self.timing_open and shown:
            self.update_timing()
        elif self.timing_open:
            self._timing_stale = True

    @Property(QObject, constant=True)
    def timingRows(self) -> QObject:
        return self._timing_model

    @Property(int, notify=timingColumnsChanged)
    def timingViewIndex(self) -> int:
        return list(TIMING_VIEWS).index(self.timing_view)

    @Property(list, notify=timingColumnsChanged)
    def timingColumns(self) -> list[dict]:
        """Columns of the view shown: key, title, width (em), alignment"""
        return [{"key": key, "title": tr(TIMING_COLUMNS[key][0]), "width": TIMING_COLUMNS[key][1],
                 "align": TIMING_COLUMNS[key][2]} for key in self.timing_columns[self.timing_view]]

    @Property(list, notify=timingColumnsChanged)
    def timingChoices(self) -> list[dict]:
        """Every column: key, title, shown in the view"""
        shown = self.timing_columns[self.timing_view]
        return [{"key": key, "title": tr(title), "shown": key in shown} for key, (title, _, _) in TIMING_COLUMNS.items()]

    @Property(QObject, constant=True)
    def timingColumnRows(self) -> DictListModel:
        """Columns of the view shown (key, title, size in em, align): a column moved or toggled is moved, inserted or
        removed alone (cells of other columns kept)"""
        return self._timing_column_model

    def sync_timing_columns(self):
        self._timing_column_model.sync([
            {"key": key, "title": tr(TIMING_COLUMNS[key][0]), "size": TIMING_COLUMNS[key][1],
             "align": TIMING_COLUMNS[key][2]} for key in self.timing_columns[self.timing_view]])

    def timing_columns_changed(self):
        self.page.save_settings()
        self.sync_timing_columns()
        if self.timing_open:  # cells of the columns shown (gap of the view too: qualifying gap to pole)
            self.update_timing()
        self.timingColumnsChanged.emit()

    @Slot(bool)
    def setTimingOpen(self, shown: bool):
        """Timing table shown: rows made at each answer (none while closed or page hidden)"""
        self.timing_open = shown
        if shown:
            self.update_timing()

    @Slot(int)
    def setTimingView(self, index: int):
        views = list(TIMING_VIEWS)
        if 0 <= index < len(views) and views[index] != self.timing_view:
            self.timing_view = views[index]
            self.timing_columns_changed()

    @Slot(int, int)
    def moveTimingColumn(self, source: int, target: int):
        """Column of the view moved (dragged) to another place"""
        columns = self.timing_columns[self.timing_view]
        if not (0 <= source < len(columns) and 0 <= target < len(columns)) or source == target:
            return
        columns.insert(target, columns.pop(source))
        self.timing_columns_changed()

    @Slot(str)
    def toggleTimingColumn(self, key: str):
        """Column shown or hidden in the view (one column at least stays)"""
        columns = self.timing_columns[self.timing_view]
        if key in columns:
            if len(columns) > 1:
                columns.remove(key)
        elif key in TIMING_COLUMNS:
            columns.append(key)
        else:
            return
        self.timing_columns_changed()

    @Slot()
    def resetTimingColumns(self):
        self.timing_columns[self.timing_view] = list(TIMING_VIEWS[self.timing_view])
        self.timing_columns_changed()

    def update_timing(self):
        """Rows of the timing table: every column of every view (columns shown chosen by the page)"""
        self._timing_stale = False
        page = self.page
        watcher, track_length, session_time = page.watcher, page.track_length, page.session_time
        places, fronts, tyres = page.places, page.class_ahead(), page.tyres
        qualifying = self.timing_view == "qualifying"
        race = dr.is_race(page.session_key[1])
        grid = page.class_grid() if race else {}
        fastest = page.class_fastest()
        personal, class_best = page.best_sectors()
        in_battle: dict[int, int] = {}
        for battle in watcher.battles.values():
            trend = -1 if battle.trend < -0.02 else 1 if battle.trend > 0.02 else 0
            in_battle[battle.ahead] = in_battle.get(battle.ahead, trend)
            in_battle[battle.behind] = trend
        leader = page.standings[0] if page.standings else None
        slow = {event.slots[0] for event in page.events[-80:] if event.kind in (dr.SLOW, dr.STOPPED, dr.YELLOW)
                and event.slots and session_time - event.time < 30}
        shown = self.timing_columns[self.timing_view]
        rows = []
        for car in page.standings:
            status, tone = status_text(car)
            ahead = fronts.get(car.slot)
            seconds, laps = interval(ahead, car, track_length) if ahead is not None else (-1.0, 0)
            sectors = page.shown_sectors(car)
            bests, class_bests = personal.get(car.slot, [-1.0] * 3), class_best.get(car.car_class, [-1.0] * 3)
            tones = [sector_tone(value, bests[index], class_bests[index]) for index, value in enumerate(sectors)]
            pole = fastest.get(car.car_class, 0.0)
            if qualifying:
                gap = delta_text(car.best - pole) if car.best > 0 and pole > 0 and car.best > pole else ""
            else:
                gap = "" if car is leader else interval_text(leader, car, track_length)
            stops = watcher.pit_stops.get(car.slot, [])
            state = watcher.cars.get(car.slot)
            if car.in_pit and not car.garage and state is not None and state.pit_since >= 0:
                pit_time = seconds_text(max(session_time - state.pit_since, 0.0), 0)
            elif stops and stops[-1].duration > 0:
                pit_time = seconds_text(stops[-1].duration)
            else:
                pit_time = ""
            level = dr.level(car)
            stint = watcher.stint_laps(car)
            change = grid[car.slot] - places.get(car.slot, 0) if car.slot in grid else 0
            car_tyres = [letter for letter in dict.fromkeys(tyres.get(car.slot, ())) if letter]
            row: dict[str, Any] = {
                "key": str(car.slot), "slot": car.slot, "classColor": class_color(car.car_class),
                "onAir": car.slot == page.on_air_slot, "battle": car.slot in in_battle,
                "trend": in_battle.get(car.slot, 0), "yellow": car.slot in slow,
                "energyLevel": level, "energyTone": energy_tone(level) if level >= 0 else "", "tyreList": car_tyres,
                "intervalTone": gap_tone(seconds) if laps == 0 else "", "gapTone": "",
                "bestTone": "fastest" if car.best > 0 and car.best <= pole + 0.0005 else "",
                "lastTone": sector_tone(car.last, car.best, pole), "s1Tone": tones[0], "s2Tone": tones[1],
                "s3Tone": tones[2], "changeValue": change, "statusTone": tone,
                "pos": str(car.position), "classPos": str(places.get(car.slot, 0)),
                "change": (f"▲{change}" if change > 0 else f"▼{-change}") if change else "",
                "number": f"#{car.number}" if car.number else "", "driver": driver_display_name(car.driver),
                "team": car.team or car.vehicle, "laps": str(car.laps),
                "interval": interval_text(ahead, car, track_length), "gap": gap,
                "best": lap_text(car.best), "last": lap_text(car.last),
                "s1": localized(f"{sectors[0]:.3f}") if sectors[0] > 0 else "",
                "s2": localized(f"{sectors[1]:.3f}") if sectors[1] > 0 else "",
                "s3": localized(f"{sectors[2]:.3f}") if sectors[2] > 0 else "",
                "pits": str(car.pitstops), "stint": str(stint) if stint >= 0 else "",
                "pitTime": pit_time, "energy": f"{round(level * 100)}%" if level >= 0 else "",
                "tyres": "/".join(car_tyres), "penalties": str(car.penalties) if car.penalties else "",
                "status": status,
            }
            row["cells"] = timing_cells(row, shown)
            rows.append(row)
        if self._timing_model.sync(rows):
            self.timingChanged.emit()
