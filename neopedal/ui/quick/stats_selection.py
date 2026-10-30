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
Driver stats viewer part (StatsSelection, mixin of DriverStatsBackend): Selected vehicle: lap time reference (level scale), progression chart & sessions, stints & consistency of recorded laps, other tools of the selection
"""

from __future__ import annotations

import time
from contextlib import suppress
from functools import partial
from typing import Any

from PySide6.QtCore import (
    Property,
    Slot,
)

from ... import calculation as calc
from ...const_common import MAX_SECONDS
from ...formatter import strip_invalid_char
from ...i18n import tr, trm
from ...process.results_text import MISSING, laptime_text
from ...setting import cfg
from ...userfile import lap_reference
from ...userfile.driver_history import (
    SESSION_GROUPS,
    SessionRecord,
    best_lap_date,
    best_progression,
    filter_sessions,
)
from ...userfile.lap_reference import LEVELS, LapReference
from ..lap_viewer import number_text, signed
from ..track_map_viewer import TrackMapViewer
from .formatting import format_date
from .stats_analysis import parse_goals
from .stats_common import (
    CONDITION_FILTERS,
    GOAL_RANGE,
    GOAL_STEP,
    MAX_SESSIONS,
    MAX_STINTS,
    ONLINE_FILTERS,
    SELECTION_BURST,
    SESSION_FILTERS,
    chart_ticks,
    combo_name,
    conditions_text,
    folder_stamp,
    format_duration,
    format_header_key,
    lap_matches_vehicle,
    level_letter,
    level_text,
    list_lap_folders,
    parse_display_value,
    parse_laptime,
    places_gained,
    plural,
    race_result,
    result_details,
    result_tone,
    session_code,
    session_kind,
    session_name,
    signed_places,
    summary_rank,
    valid_laptime,
    version_key,
)
from .stats_core import StatsCore
from .stats_io import (
    StatsHost,
    read_stints_report,
)


class StatsSelection(StatsHost):
    """Selected vehicle: lap time reference (level scale), progression chart & sessions, stints & consistency of recorded laps, other tools of the selection"""

    # Selection: reference, progression & sessions of selected vehicle
    @Property(str, notify=StatsCore.selectedKeyChanged)
    def selectedKey(self) -> str:
        return self._selected[self.mode]

    @Slot(str)
    def selectRow(self, key: str):
        if key == self._selected[self.mode] or key not in self.row_keys():
            return
        self._selected[self.mode] = key
        self.update_selection()

    def selected_index(self) -> int:
        keys = self.row_keys()
        return keys.index(self._selected[self.mode]) if self._selected[self.mode] in keys else -1

    @Property(int, notify=StatsCore.rowIndexChanged)
    def selectedIndex(self) -> int:
        return self.selected_index()

    @Slot(int)
    def moveSelection(self, step: int):
        """Keyboard: select previous or next row"""
        keys = self.row_keys()
        if keys:
            index = self.selected_index()
            key = keys[min(max(index + step, 0), len(keys) - 1) if index >= 0 else 0]
            if key != self._selected[self.mode]:
                self._selected[self.mode] = key
                self.update_selection(keyboard=True)

    def selected_row_key(self) -> str:
        return self._selected[self.mode]

    @Slot(str)
    def openRow(self, key: str):
        """All Tracks: double click or Enter shows vehicles of track"""
        if not self.selected_stats_key and key in self.stats_temp:
            self.selectTrack(key)

    def update_selection(self, keyboard: bool = False):
        """Selected row told at once; its reference, progression & sessions too, unless moved by keyboard quickly
        (arrow key held: shown once it settles, page not rebuilt for each row passed)"""
        burst = False
        if keyboard:
            now = time.monotonic()
            burst = now - self._selection_time < SELECTION_BURST
            self._selection_time = now
        if burst:
            self.publish("selectedKey", self._selected[self.mode], self.selectedKeyChanged)
            self.publish("rowIndex", self.selected_index(), self.rowIndexChanged)
            self.selection_timer.start()
            return
        self.selection_timer.stop()
        self.publish_selection()

    @Slot()
    def publish_selection(self):
        """Reference, progression & sessions of selected row, told only if changed (stats saved every lap)"""
        if self._released:
            return
        self.publish("selectedKey", self._selected[self.mode], self.selectedKeyChanged)
        self._reference = self.reference_data()
        self._progression, self._sessions = self.history_data()
        self._has_laps = bool(self.lap_folder())
        self.publish("selection", (self.mode, self._selected[self.mode], self._session_filter, self._reference,
                                   self._progression, self._sessions, self._has_laps), self.selectionChanged)
        since, choices = self.since_version, self.version_choices()
        index = next((index for index, entry in enumerate(choices) if entry["value"] == since), 0)
        self.publish("filters", (self.condition_filter, self.online_filter, since, choices, index), self.filtersChanged)
        self._goal = self.goal_data()
        self.publish("goal", self._goal, self.goalChanged)
        self.publish("rowIndex", self.selected_index(), self.rowIndexChanged)
        self.update_stints()

    # Session filters of selected vehicle (saved): road conditions, online or offline, since a game version
    @property
    def condition_filter(self) -> int:
        value = self.viewer_config().get("condition_filter", 0)
        return value if isinstance(value, int) and 0 <= value < len(CONDITION_FILTERS) else 0

    @property
    def online_filter(self) -> int:
        value = self.viewer_config().get("online_filter", 0)
        return value if isinstance(value, int) and 0 <= value < len(ONLINE_FILTERS) else 0

    @property
    def since_version(self) -> str:
        value = self.viewer_config().get("since_version", "")
        return value if isinstance(value, str) and version_key(value)[0] >= 0 else ""

    def filters_active(self) -> bool:
        return bool(self.condition_filter or self.online_filter or self.since_version)

    def record_kept(self, record: SessionRecord) -> bool:
        """Session kept by the filters (unknown conditions, server or version left out while filtered)"""
        condition = self.condition_filter
        if condition and (not record.conditions_known or record.wet != (condition == 2)):
            return False
        online = self.online_filter
        if online and self.record_online(record) != (1 if online == 1 else 0):
            return False
        since = self.since_version
        return not since or version_key(self.record_version(record)) >= version_key(since)

    def version_choices(self) -> list[dict]:
        """Version filter entries: all versions, then since each game version of selected vehicle sessions (newest
        first), version chosen kept even if this vehicle has none"""
        vehicle = self._selected["vehicles"] if self.selected_stats_key else ""
        records = self.history_index.get((self.selected_stats_key, vehicle), []) if vehicle else []
        versions = {self.record_version(record) for record in records} | {self.since_version}
        ordered = sorted((version for version in versions if version_key(version)[0] >= 0), key=version_key,
                         reverse=True)
        return [{"text": tr("All Versions"), "value": ""}] + [
            {"text": trm(f"Since v{version}"), "value": version} for version in ordered]

    def filter_text(self) -> str:
        """Filters in use: "Dry · Online · since v1.42", "" if none"""
        parts = []
        if self.condition_filter:
            parts.append(tr(CONDITION_FILTERS[self.condition_filter]))
        if self.online_filter:
            parts.append(tr(ONLINE_FILTERS[self.online_filter]))
        if self.since_version:
            parts.append(trm(f"Since v{self.since_version}"))
        return " · ".join(parts)

    @Property(list, constant=True)
    def conditionFilters(self) -> list[str]:
        return self._filter_names[0]

    @Property(list, constant=True)
    def onlineFilters(self) -> list[str]:
        return self._filter_names[1]

    @Property(int, notify=StatsCore.filtersChanged)
    def conditionFilter(self) -> int:
        return self._published.get("filters", (0,))[0]

    @Property(int, notify=StatsCore.filtersChanged)
    def onlineFilter(self) -> int:
        return self._published.get("filters", (0, 0))[1]

    @Property(list, notify=StatsCore.filtersChanged)
    def versionChoices(self) -> list[dict]:
        return self._published.get("filters", (0, 0, "", []))[3]

    @Property(int, notify=StatsCore.filtersChanged)
    def versionIndex(self) -> int:
        """Entry of version filter in use (versionChoices)"""
        return self._published.get("filters", (0, 0, "", [], 0))[4]

    @Property(bool, notify=StatsCore.filtersChanged)
    def filtered(self) -> bool:
        filters = self._published.get("filters", (0, 0, ""))
        return bool(filters[0] or filters[1] or filters[2])

    @Slot(int)
    def setConditionFilter(self, index: int):
        self.save_viewer_config(condition_filter=index if 0 <= index < len(CONDITION_FILTERS) else 0)
        self.update_selection()

    @Slot(int)
    def setOnlineFilter(self, index: int):
        self.save_viewer_config(online_filter=index if 0 <= index < len(ONLINE_FILTERS) else 0)
        self.update_selection()

    @Slot(int)
    def setVersionFilter(self, index: int):
        """Sessions since a game version (entry of versionChoices, 0: all versions)"""
        choices = self.version_choices()
        self.save_viewer_config(since_version=choices[index]["value"] if 0 <= index < len(choices) else "")
        self.update_selection()

    @Slot()
    def clearFilters(self):
        self.save_viewer_config(condition_filter=0, online_filter=0, since_version="")
        self.update_selection()

    @Property(list, notify=StatsCore.filtersChanged)
    def filterChips(self) -> list[dict]:
        """Filters in use, each removable on its own: key ("road", "server", "version"), text"""
        condition, online, since = self._published.get("filters", (0, 0, ""))[:3]
        chips = []
        if 0 < condition < len(CONDITION_FILTERS):
            chips.append({"key": "road", "text": tr(CONDITION_FILTERS[condition])})
        if 0 < online < len(ONLINE_FILTERS):
            chips.append({"key": "server", "text": tr(ONLINE_FILTERS[online])})
        if since:
            chips.append({"key": "version", "text": trm(f"Since v{since}")})
        return chips

    @Slot(str)
    def clearFilter(self, key: str):
        """One filter removed (chip of filterChips), others kept"""
        names = {"road": ("condition_filter", 0), "server": ("online_filter", 0), "version": ("since_version", "")}
        if key in names:
            name, value = names[key]
            self.save_viewer_config(**{name: value})
            self.update_selection()

    # Lap time goal of selected vehicle (saved by track & vehicle), suggested: next level of community lap times
    def goal_key(self, vehicle: str = "") -> str:
        vehicle = vehicle or (self._selected["vehicles"] if self.selected_stats_key else "")
        return f"{self.selected_stats_key}|{vehicle}" if self.selected_stats_key and vehicle else ""

    def goals(self) -> dict[str, float]:
        """Goals of every track & vehicle (valid lap times only)"""
        return parse_goals(self.viewer_config().get("goals", {}))

    def goal_of(self, track: str, vehicle: str) -> float:
        return self.goals().get(f"{track}|{vehicle}", 0.0)

    def suggested_goal(self, vehicle: str) -> tuple[float, str]:
        """Goal to propose: limit of next level of community lap times, else personal best minus a few tenths"""
        best = valid_laptime(self.selected_stats_dict.get(vehicle, {}).get("pb", 0))
        reference = self.reference_of(vehicle)
        if reference is not None and best > 0:
            level, to_find = reference.next_level(best)
            if level >= 0:
                return best - to_find, tr(LEVELS[level])
        if reference is not None and best <= 0 and reference.reference > 0:
            return reference.reference, tr("Reference")
        return (round(best - GOAL_STEP, 1), "") if best > GOAL_STEP else (0.0, "")

    def goal_data(self) -> dict:
        """Goal card of selected vehicle: goal, gap of personal best, reached, suggestion (none: hidden)"""
        vehicle = self._selected["vehicles"] if self.selected_stats_key else ""
        if not vehicle or vehicle not in self.selected_stats_dict:
            return {"visible": False}
        goal = self.goal_of(self.selected_stats_key, vehicle)
        best = valid_laptime(self.selected_stats_dict[vehicle].get("pb", 0))
        suggested, level = self.suggested_goal(vehicle)
        data = {"visible": True, "set": goal > 0, "time": calc.sec2laptime_full(goal) if goal else "",
                "best": laptime_text(best), "reached": False, "gap": "", "gapColor": "",
                "suggestion": "", "ratio": -1.0}
        if suggested > 0:
            text = calc.sec2laptime_full(suggested)
            data["suggestion"] = trm(f"Suggested: {text} ({level})") if level else trm(f"Suggested: {text}")
        if goal and best:
            gap = best - goal
            data["reached"] = gap <= 0.0005
            data["gap"] = tr("Reached") if data["reached"] else trm(f"{signed(gap, 3)} s to find")
            data["gapColor"] = "gain" if data["reached"] else "loss"
        if goal and best:
            # Progress from the first best lap of history to the goal (1: reached)
            records = self.history_index.get((self.selected_stats_key, vehicle), [])
            first = next((record.best for record in records if record.best > 0), best)
            span = first - goal
            data["ratio"] = 1.0 if data["reached"] else max(min((first - best) / span, 1.0), 0.0) if span > 0 else 0.0
        return data

    @Property(dict, notify=StatsCore.goalChanged)
    def goal(self) -> dict:
        """Goal of selected vehicle: visible, set, time, best, reached, gap, gapColor, suggestion, ratio"""
        return self._goal

    @Slot()
    def editGoal(self):
        """Ask the goal lap time of selected vehicle (empty: removed), suggested one proposed"""
        key = self.goal_key()
        if not key:
            return
        vehicle = key.split("|", 1)[1]
        goal = self.goal_of(self.selected_stats_key, vehicle) or self.suggested_goal(vehicle)[0]
        self.ask_goal(key, calc.sec2laptime_full(goal) if goal else "")

    def ask_goal(self, key: str, text: str):
        """Goal lap time of a vehicle asked (in the page); not a lap time: told, then asked again with the text"""
        from . import dialogs

        def accept(typed: str) -> bool:
            typed = typed.strip()
            if not typed:
                self.set_goal(key, 0.0)
                return True
            laptime = parse_laptime(typed)
            if not laptime:
                dialogs.alert(self._window, tr("Error"), tr("Not a lap time: write it as 1:52.300 or 112.3"), "warning",
                              lambda: self.ask_goal(key, typed))
                return True
            self.set_goal(key, laptime)
            return True

        vehicle = key.split("|", 1)[1]
        dialogs.ask_text(self._window, tr("Lap Time Goal…"), trm(f"Lap time goal of {vehicle} (empty to remove it):"),
                         accept, text)

    @Slot()
    def clearGoal(self):
        key = self.goal_key()
        if key:
            self.set_goal(key, 0.0)

    def set_goal(self, key: str, laptime: float):
        """Goal saved (0 removes it), announced again once reached"""
        goals = {name: value for name, value in self.goals().items() if name != key}
        if laptime > 0:
            goals[key] = round(laptime, 3)
        reached = [name for name in self.reached_goals() if name != key]
        track, _, vehicle = key.partition("|")
        best = valid_laptime(self.stats_temp.get(track, {}).get(vehicle, {}).get("pb", 0))
        if laptime > 0 and best and best <= laptime + 0.0005:
            reached.append(key)  # beaten already: nothing to announce
        self.save_viewer_config(goals=goals, goals_reached=reached)
        self.update_selection()

    def reached_goals(self) -> list[str]:
        reached = self.viewer_config().get("goals_reached", [])
        return [str(name) for name in reached] if isinstance(reached, list) else []

    def check_goals(self):
        """Stats read: goals beaten since last time announced once (toast), also when beaten while page closed"""
        goals = self.goals()
        if not goals:
            return
        reached = self.reached_goals()
        beaten = []
        for key, goal in goals.items():
            if key in reached:
                continue
            track, _, vehicle = key.partition("|")
            vehicles = self.stats_temp.get(track)
            data = vehicles.get(vehicle) if isinstance(vehicles, dict) else None
            best = valid_laptime(data.get("pb", 0)) if isinstance(data, dict) else 0.0
            if best and best <= goal + 0.0005:
                beaten.append((track, vehicle, best))
                reached.append(key)
        if not beaten:
            return
        self.save_viewer_config(goals_reached=reached)
        from ..toast import show_toast

        track, vehicle, best = beaten[-1]
        with suppress(RuntimeError):  # page window closing
            show_toast(self._window, trm(f"Goal reached: <b>{track}</b> · {vehicle} · {calc.sec2laptime_full(best)}"))

    # Stints & consistency of selected vehicle: recorded laps of its track & class folder
    def update_stints(self, background: bool = True):
        """Recorded laps of selected vehicle read (in a thread if background): stint pace & degradation by tyre
        compound, consistency of each session & of the track"""
        vehicle = self._selected["vehicles"] if self.selected_stats_key else ""
        folder = self.lap_folder(vehicle) if vehicle else ""
        laps = f"{folder}|{vehicle}"
        key = f"{laps}|{self.lap_folders().get(folder, 0)}" if folder else laps
        if not vehicle or not folder:
            self._laps_generation += 1  # running or waiting read ignored
            self._laps_job = None
            self.laps_timer.stop()
        if not vehicle:
            self._laps_key, self._stints = key, {}
            self.lapsChanged.emit()
            return
        if not folder:
            self._laps_key = key
            self._stints = {"visible": True, "busy": False,
                            "note": tr("No recorded lap for this car class: enable the Recorder module, then drive a few laps.")}
            self.lapsChanged.emit()
            return
        if key == self._laps_key and self._stints.get("visible"):
            return  # same laps shown (read again once laps folder changed: lap recorded or removed)
        same_laps = self._laps_key.rpartition("|")[0] == laps and self._stints.get("visible") and "note" not in self._stints
        self._laps_key = key
        if same_laps:  # new lap recorded: stints shown kept while read again
            self._stints = {**self._stints, "busy": True}
        else:
            self._stints = {"visible": True, "busy": True, "note": tr("Reading recorded laps…")}
        self.lapsChanged.emit()
        self._laps_generation += 1
        job = (key, folder, vehicle, self._laps_generation)
        if not background:
            self.read_stints(*job)
            return
        self._laps_job = job
        self.laps_timer.start()  # selection changing quickly (arrow keys): read once it settles

    @Slot()
    def start_laps_read(self):
        """Debounced read started in background, once the running read (if any) has finished"""
        if self._laps_running or self._laps_job is None:
            return  # started when running read is loaded
        job, self._laps_job = self._laps_job, None
        self._laps_running = job[3]
        # Lap infos of last folders read only (one read at a time), result handed over on the UI thread
        self.jobs.run("laps", partial(read_stints_report, self._lap_infos, *job), self.stints_read)

    def read_stints(self, key: str, folder: str, vehicle: str, generation: int):
        """Recorded laps read now (UI thread)"""
        self.stints_read(read_stints_report(self._lap_infos, key, folder, vehicle, generation))

    def stints_read(self, result: tuple[str, int, dict | None]):
        self.stints_loaded(*result)

    def stints_loaded(self, key: str, generation: int, report):
        """Recorded laps read: stints & consistency shown if still selected & latest read (an older read of
        same laps finishing later never overwrites newer laps)"""
        if generation == self._laps_running:
            self._laps_running = 0
            if self._laps_job is not None and not self.laps_timer.isActive():
                self.start_laps_read()  # read asked while this one was running
        if key != self._laps_key or generation != self._laps_generation:
            return
        self._stints = self.stints_data(report) if isinstance(report, dict) else {
            "visible": True, "busy": False, "note": tr("Unable to read recorded laps.")}
        self.lapsChanged.emit()

    def stints_data(self, report: dict) -> dict:
        """Stints, compounds & consistency as shown: lap times, degradation per lap, coefficient of variation"""

        def slope_text(slope: float | None) -> str:
            return f"{signed(slope, 3)} s/{tr('lap')}" if slope is not None else "—"

        def slope_color(slope: float | None) -> str:
            return "" if slope is None or abs(slope) < 0.02 else "loss" if slope > 0 else "gain"

        def compound(name: str) -> str:
            return name or tr("Compound not recorded")

        def session(name: str) -> str:
            return tr(name) if name else tr("Session")

        compounds = [{"compound": compound(row["compound"]),
                      "names": row["compound"].split("/") if row["compound"] else [],  # badges: front, rear
                      "stints": row["stints"], "laps": row["laps"],
                      "pace": calc.sec2laptime_full(row["pace"]), "slope": slope_text(row["slope"]),
                      "slopeColor": slope_color(row["slope"])} for row in report["compounds"]]
        stints = [{"date": format_date(row["start"]), "session": session(row["session"]),
                   "compound": compound(row["compound"]), "laps": f"{row['clean']}/{row['laps']}",
                   "pace": calc.sec2laptime_full(row["pace"]), "slope": slope_text(row["slope"]),
                   "slopeColor": slope_color(row["slope"])}
                  for row in sorted(report["stints"], key=lambda row: -row["start"])[:MAX_STINTS]]
        sessions = [{"date": format_date(row["start"]), "session": session(row["session"]), "laps": row["clean"],
                     "index": f"{number_text(row['index'], 2)} %", "pace": calc.sec2laptime_full(row["pace"])}
                    for row in sorted(report["sessions"], key=lambda row: -row["start"])[:MAX_STINTS]]
        index = report["index"]
        return {
            "visible": True, "busy": False, "compounds": compounds, "stints": stints, "sessions": sessions,
            "index": f"{number_text(index, 2)} %" if index is not None else "",
            "indexInfo": f"{tr('Median of')} {plural(len(report['sessions']), 'session', 'sessions')}"
            if index is not None else "",
            "note": "" if stints or sessions else tr("3 clean laps or more needed in a session."),
        }

    @Property(dict, notify=StatsCore.lapsChanged)
    def stints(self) -> dict:
        """Stints & consistency of selected vehicle: visible, busy, note, index, compounds, stints, sessions"""
        return self._stints

    def reference_data(self) -> dict:
        """Level ladder of selected vehicle, gap to reference, next level, fastest car (empty: reason)"""
        vehicle = self._selected["vehicles"] if self.selected_stats_key else ""
        if not self.selected_stats_key:
            return {"visible": False, "reason": ""}
        if not vehicle:
            return {"visible": False, "reason": tr("Select a car to compare its lap times.")}
        data = self.selected_stats_dict.get(vehicle, {})
        reference = self.reference_of(vehicle)
        if reference is None:
            if not self.references.entries:
                reason = tr("Community lap times not downloaded yet.")
            elif not lap_reference.vehicle_class_of(vehicle) and not lap_reference.vehicle_class_of(
                    self.classes.get(vehicle, "")):
                reason = tr("Vehicle class unknown: set vehicle classification to class (Class - Brand) to compare.")
            else:
                reason = trm(f"No community lap time for {self.selected_stats_key} in this class.")
            return {"visible": False, "reason": reason, "vehicle": vehicle}
        best = valid_laptime(data.get("pb", 0))
        marks = [(tr("PB"), best), (tr("Qualifying"), valid_laptime(data.get("qb", 0))),
                 (tr("Race"), valid_laptime(data.get("rb", 0)))]
        marks_by_level: dict[int, list[str]] = {}
        for text, laptime in marks:
            if laptime > 0:
                marks_by_level.setdefault(reference.level(laptime), []).append(text)
        ladder = []
        for level, name in enumerate(LEVELS):
            limit = reference.level_limit(level)
            faster_limit = reference.level_limit(level - 1) if level > 0 else 0.0
            if level == len(LEVELS) - 1 and faster_limit:
                limit_text = f"> {calc.sec2laptime_full(faster_limit)}"
            else:
                limit_text = f"≤ {calc.sec2laptime_full(limit)}" if limit else MISSING
            mark = marks_by_level.get(level, [])
            ladder.append({"name": tr(name), "color": self.level_color(level), "limit": limit_text,
                           "marks": "  ".join(f"← {text}" for text in mark), "active": bool(mark), "pills": mark,
                           "letter": level_letter(level)})
        patch = f" · {tr('patch')} {reference.patch}" if reference.patch else ""
        next_level = {}
        if best > 0:
            gap = best - reference.reference
            gap_text = trm(f"Personal best {calc.sec2laptime_full(best)}: {signed(gap, 2)} s "
                           f"({number_text(reference.percent(best), 2)} %) "
                           f"to reference {calc.sec2laptime_full(reference.reference)}")
            level, to_find = reference.next_level(best)
            if level >= 0:
                next_text = trm(f"Next level {tr(LEVELS[level])}: {number_text(to_find, 2)} s to find")
                next_level = {"name": tr(LEVELS[level]), "color": self.level_color(level), "letter": level_letter(level),
                              "toFind": signed(-to_find, 2, " s")}
            else:
                next_text = tr("Top level reached") if reference.level(best) == 0 else ""
        else:
            gap_text = trm(f"Reference {calc.sec2laptime_full(reference.reference)}, no personal best yet")
            next_text = ""
        fastest = ""
        if reference.fastest_car and reference.fastest_time:
            fastest = trm(f"Fastest car: {reference.fastest_car} · {calc.sec2laptime_full(reference.fastest_time)}")
        level = reference.level(best) if best > 0 else -1
        return {"visible": True, "reason": "", "vehicle": vehicle,
                "detail": f"{reference.track} · {reference.vehicle_class}{patch}", "ladder": ladder,
                "gap": gap_text, "next": next_text, "fastest": fastest, "gauge": self.gauge_data(reference, marks),
                "level": level_text(level) if level >= 0 else "", "levelColor": self.level_color(level),
                "letter": level_letter(level), "percent": f"{number_text(reference.percent(best), 2)} %" if best > 0 else "",
                "best": calc.sec2laptime_full(best) if best > 0 else "", "nextLevel": next_level,
                "referenceTime": calc.sec2laptime_full(reference.reference) if reference.reference > 0 else "",
                "gapTime": signed(best - reference.reference, 2, " s") if best > 0 and reference.reference > 0 else ""}

    def gauge_data(self, reference: LapReference, marks: list[tuple[str, float]]) -> dict:
        """Level scale: levels from slowest (left) to fastest (right), positions (0-1) of lap time marks

        Levels take the same width, a lap time is placed in its level by its share of the level lap time range
        (Alien & Offline as wide as their neighbor). Empty if ladder unknown.
        """
        count = len(LEVELS)
        limits = [reference.level_limit(level) for level in range(count - 1)]
        if not all(limits):
            return {}
        ranges = []  # (fastest, slowest) lap time of each level
        for level in range(count):
            if level == 0:
                ranges.append((limits[0] - (limits[1] - limits[0]), limits[0]))
            elif level == count - 1:
                ranges.append((limits[-1], limits[-1] + (limits[-1] - limits[-2])))
            else:
                ranges.append((limits[level - 1], limits[level]))

        def position(laptime: float) -> float:
            level = reference.level(laptime)
            fast, slow = ranges[level]
            share = (slow - laptime) / (slow - fast) if slow > fast else 0.5
            return (count - 1 - level + min(max(share, 0.0), 1.0)) / count

        segments = []
        for level in reversed(range(count)):
            fast, slow = ranges[level]
            if level == count - 1:
                limit = f"> {calc.sec2laptime_full(fast)}"
            else:
                limit = f"≤ {calc.sec2laptime_full(slow)}"
            segments.append({"name": tr(LEVELS[level]), "letter": level_letter(level), "color": self.level_color(level),
                             "limit": limit})
        markers = []
        for index, (name, laptime) in enumerate(marks):
            if laptime <= 0:
                continue
            level = reference.level(laptime)
            markers.append({
                "label": name, "short": name[:1].upper(), "main": index == 0, "pos": round(position(laptime), 4),
                "time": calc.sec2laptime_full(laptime), "color": self.level_color(level),
                "tip": f"{name} {calc.sec2laptime_full(laptime)} · {level_text(level)} · {number_text(reference.percent(laptime), 2)} %",
            })
        markers.sort(key=lambda marker: bool(marker["main"]))  # personal best drawn last (on top)
        return {"segments": segments, "markers": markers}

    def history_data(self) -> tuple[dict, list[dict]]:
        """Progression chart (best lap of each session, personal best so far) & sessions list"""
        vehicle = self._selected["vehicles"] if self.selected_stats_key else ""
        if not vehicle:
            return {"visible": False, "points": [], "info": ""}, []
        data = self.selected_stats_dict.get(vehicle, {})
        best = valid_laptime(data.get("pb", 0))
        records = filter_sessions(self.history_index.get((self.selected_stats_key, vehicle), []), self._session_filter)
        filters = self.filters_active()
        if filters:
            records = [record for record in records if self.record_kept(record)]
        progression = best_progression(records, best)
        reference = self.reference_of(vehicle)
        chart = self.chart_data(progression, reference, self.goal_of(self.selected_stats_key, vehicle))
        lines = []
        if filters:  # best of the sessions kept, filters named
            kept = [record.best for record in records if record.best > 0 and not (best and record.best < best - 0.0005)]
            if kept:
                lines.append(trm(f"Best with filters {calc.sec2laptime_full(min(kept))} ({self.filter_text()})"))
            else:
                lines.append(trm(f"No lap time with filters ({self.filter_text()})"))
        if best > 0:
            date = best_lap_date(records, best)
            pb_record = next((record for record in records if record.time == date), None) if date else None
            version = self.record_version(pb_record) if pb_record is not None else ""
            if not date:  # lap time completed from race results, or recorded before session history
                pb_result = self.best_lap_result(self.selected_stats_key, vehicle, best)
                if pb_result is not None:
                    date, version = pb_result.end, pb_result.game_version
            if date:
                line = trm(f"PB {calc.sec2laptime_full(best)} set on {format_date(date)}")
                lines.append(f"{line} · {tr('Version')} {version}" if version else line)
        if records:
            lines.append(f"{plural(len(records), 'session', 'sessions')} · {tr('last driven')} "
                         f"{format_date(records[-1].time)}")
        else:
            lines.append(tr("No session recorded yet: history starts with your next session."))
        chart["info"] = "\n".join(lines)
        chart["sessions"] = len(records)  # all sessions (list shows the newest MAX_SESSIONS)
        sessions = []
        shown = records[-MAX_SESSIONS:]
        # Chart point of each session & session of each point (hovered in one, shown in the other)
        point_of = {id(record): index for index, (record, _) in enumerate(progression)} if chart["visible"] else {}
        for row, record in enumerate(reversed(shown)):
            if id(record) in point_of:
                chart["points"][point_of[id(record)]]["session"] = row
        for record in reversed(shown):
            laptime = record.best if record.best > 0 and not (best and record.best < best - 0.0005) else 0.0
            summary = self.record_result(record)
            version = record.game_version or (summary.game_version if summary is not None else "")
            tip = [f"{format_duration(record.seconds)} · {parse_display_value('meters', record.meters)} "
                   f"{tr(format_header_key('meters')).lower()}"]
            conditions = conditions_text(record)
            if conditions:
                tip.append(f"{conditions} · {record.compound}" if record.compound else conditions)
            gained = places_gained(record, summary)
            if gained is not None:
                tip.append(trm(f"Start P{record.position + gained} · finish P{record.position} "
                               f"({signed_places(gained)})"))
            online = self.record_online(record)
            if summary is not None:
                tip += result_details(summary)
                tip.append(tr("Click to show race results"))
            else:
                if online >= 0:
                    tip.append(tr("Online") if online else tr("Single Player"))
                if version:
                    tip.append(f"{tr('Version')} {version}")
            sessions.append({
                "point": point_of.get(id(record), -1),
                "wet": record.conditions_known and record.wet,
                "online": online,
                "gained": signed_places(gained) if gained else "",
                "gainedColor": "" if not gained else "gain" if gained > 0 else "loss",
                "date": format_date(record.time),
                "session": session_name(record.session),
                "kind": session_kind(record.session),
                "code": session_code(record.session),
                "best": laptime_text(laptime),
                "laps": f"{record.valid}/{record.valid + record.invalid}",
                "result": race_result(record),
                "resultTone": result_tone(record),
                "podium": record.position if record.finish == 1 and 0 < record.position <= 3 else 0,
                "pb": bool(best and laptime and abs(laptime - best) < 0.0005),
                "tip": "\n".join(tip),
                "rank": summary_rank(summary) if summary is not None and not race_result(record) else "",
                "incidents": summary.contacts + summary.penalties if summary is not None else 0,
                "version": version,
                "results": summary.path if summary is not None else "",
            })
        return chart, sessions

    def chart_data(self, progression: list[tuple[SessionRecord, float]], reference: LapReference | None,
                   goal: float = 0.0) -> dict:
        """Points in chart coordinates (0-1, faster higher), level limits, goal, labels & date marks (each point:
        row of its session in sessions list, -1 if not listed)"""
        if len(progression) < 2:
            return {"visible": False, "points": [], "limits": [], "dates": [], "top": "", "bottom": "", "goalY": -1.0}
        fastest = min(best for _, best in progression)
        slowest = min(max(record.best for record, _ in progression), fastest * 1.04)  # slow sessions clipped
        slowest = max(slowest, fastest + 0.5)
        margin = (slowest - fastest) * 0.08
        low, high = fastest - margin, slowest + margin
        if fastest * (1 - GOAL_RANGE) < goal < low:  # goal a little faster than personal best: shown above it
            low = goal - margin * 0.5

        def y_of(laptime: float) -> float:
            return (min(max(laptime, low), high) - low) / (high - low)

        count = len(progression)
        points = []
        last_best = MAX_SECONDS
        for index, (record, best_so_far) in enumerate(progression):
            new_best = record.best < last_best
            tip = f"{format_date(record.time)} · {session_name(record.session)}\n{calc.sec2laptime_full(record.best)}"
            if new_best:
                tip += f" · {tr('PB')}"
            conditions = conditions_text(record)
            if conditions:
                tip += f"\n{conditions}"
            points.append({"x": index / (count - 1), "y": y_of(record.best), "pbY": y_of(best_so_far),
                           "newPb": new_best, "clipped": record.best > high, "tip": tip,
                           "kind": session_kind(record.session), "wet": record.conditions_known and record.wet,
                           "session": -1})
            last_best = best_so_far
        limits = []
        if reference is not None:
            for level in range(len(LEVELS) - 1):
                limit = reference.level_limit(level)
                if low < limit < high:
                    limits.append({"y": y_of(limit), "color": self.level_color(level), "name": tr(LEVELS[level]),
                                   "letter": level_letter(level)})
        marks = sorted({0, count // 2, count - 1}) if count >= 3 else [0, count - 1]
        dates = [{"x": index / (count - 1), "text": format_date(progression[index][0].time)} for index in marks]
        ticks = [{"y": y_of(value), "text": calc.sec2laptime_full(value)} for value in chart_ticks(low, high)]
        return {"visible": True, "points": points, "limits": limits, "dates": dates, "ticks": ticks,
                "top": calc.sec2laptime_full(fastest), "bottom": calc.sec2laptime_full(high), "pbY": y_of(fastest),
                "goalY": y_of(goal) if low < goal < high else -1.0,
                "goal": calc.sec2laptime_full(goal) if low < goal < high else ""}

    @Property(dict, notify=StatsCore.selectionChanged)
    def reference(self) -> dict:
        return self._reference

    @Property(dict, notify=StatsCore.selectionChanged)
    def progression(self) -> dict:
        return self._progression

    @Property(list, notify=StatsCore.selectionChanged)
    def sessions(self) -> list[dict]:
        return self._sessions

    @Property(list, constant=True)
    def sessionFilters(self) -> list[str]:
        return [tr(name) for name in SESSION_FILTERS]

    @Property(int, notify=StatsCore.selectionChanged)
    def sessionFilter(self) -> int:
        return self._session_filter

    @Slot(int)
    def setSessionFilter(self, index: int):
        """Progression & sessions of a session type: all, practice, qualifying, race"""
        self._session_filter = index if 0 <= index < len(SESSION_GROUPS) else 0
        self.update_selection()

    # Other tools
    def lap_folder(self, key: str = "") -> str:
        """Recorded laps folder (track & class) of vehicle (All Tracks: of a class of track), empty if none"""
        key = key or self.selected_row_key()
        if not key:
            return ""
        if self.selected_stats_key:
            return self.lap_folder_of(self.selected_stats_key, key)
        return self.lap_folder_of(key, "")

    def lap_folders(self) -> dict[str, int]:
        """Recorded laps folders (name: stamp) listed by the last reload; listed again only once the telemetry
        folder changed since (folder added or removed: one stat here, never a check per vehicle)"""
        stamp = folder_stamp(cfg.path.telemetry)
        if stamp != self._lap_folders[0]:
            self._lap_folders = list_lap_folders()
        return self._lap_folders[1]

    def lap_folder_of(self, track: str, vehicle: str) -> str:
        """Recorded laps folder (track & class) of a track & vehicle (no vehicle: of any vehicle class of the track
        in stats), empty if none"""
        if not track:
            return ""
        vehicles = [vehicle] if vehicle else [str(name) for name in self.stats_temp.get(track, {})]
        folders = self.lap_folders()
        for name in vehicles:
            folder = combo_name(track, self.class_of(name))
            if folder in folders:
                return folder
        return ""

    @Property(bool, notify=StatsCore.selectionChanged)
    def hasLaps(self) -> bool:
        """Recorded laps of selected row (checked when selected)"""
        return self._has_laps

    @Slot()
    def openLapViewer(self):
        """Recorded laps of selected vehicle class in lap telemetry viewer, its personal best lap as reference"""
        if self.selected_stats_key:
            self.open_laps(self.selected_stats_key, self.selected_row_key())
        else:
            self.open_laps(self.selected_row_key(), "")

    def open_laps(self, track: str, vehicle: str) -> bool:
        """Recorded laps of a track & vehicle class in lap telemetry viewer, the vehicle personal best lap as
        reference (no vehicle: laps of a class of the track), False with a warning if none recorded"""
        folder = self.lap_folder_of(track, vehicle)
        if not folder:
            self.warning(tr("No recorded lap for this car class: enable the Recorder module, then drive a few laps."))
            return False
        from ..tools_view import open_tool

        viewer = open_tool("lap_viewer.LapViewer", self._window)
        backend = getattr(viewer, "backend", None)
        if backend is None:
            return False
        if folder not in backend.tracks:  # recorded since lap viewer opened
            backend.refresh()
        backend.currentTrack = folder
        if vehicle:
            path = self.best_lap_path(backend, vehicle, track)
            if path:
                backend.setReference(path)
        return True

    def best_lap_path(self, lap_backend, vehicle: str, track: str = "") -> str:
        """Recorded lap file of vehicle personal best (else its fastest valid lap), empty if none (track: of
        selected track)"""
        other_track = bool(track) and track != self.selected_stats_key
        vehicles = self.stats_temp.get(track, {}) if other_track else self.selected_stats_dict
        data = vehicles.get(vehicle, {}) if isinstance(vehicles, dict) else {}
        best = valid_laptime(data.get("pb", 0) if isinstance(data, dict) else 0)
        laps = [entry for entry in getattr(lap_backend, "entries", [])
                if entry.file.valid and entry.file.lap_time > 0 and lap_matches_vehicle(entry.info, vehicle)]
        if not laps:
            return ""
        fastest = min(laps, key=lambda entry: entry.file.lap_time)
        exact = [entry for entry in laps if best and abs(entry.file.lap_time - best) < 0.002]
        return (exact[0] if exact else fastest).file.path

    @Slot()
    def openMap(self):
        """Track map of selected track"""
        if not self.selected_stats_key:
            return
        viewer = TrackMapViewer(self._window)
        viewer.show()
        # Loaded in the page shown: viewer already open as page is shown instead (this copy deleted)
        shown: Any = viewer.shown_dialog()
        shown.backend.load_map(cfg.path.track_map, strip_invalid_char(self.selected_stats_key))
