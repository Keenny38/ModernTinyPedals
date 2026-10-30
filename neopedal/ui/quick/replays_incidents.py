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
Game Replays page incidents (mixin of GameReplaysBackend): incidents list & timeline of the session (filters,
driver chips), jump to an incident (a live session goes to its replay), copy & export
"""

from __future__ import annotations

import csv
import io
from typing import Any

from PySide6.QtCore import Property, QObject, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog

from ...i18n import tr, trm
from ...process.game_info import IMMOVABLE, Incident
from . import last_folder
from .game_camera import Command
from .models import DictListModel
from .replays_base import ReplaysBase
from .replays_common import (
    INCIDENT_FILTERS,
    PANELS,
    REPLAY,
    SESSION,
    TOP_DRIVERS,
    car_text,
    clock_text,
    enter_replay,
    incident_key,
    move_selection,
    timeline_end,
)


class ReplaysIncidents(ReplaysBase):
    """Incidents of Game Replays page"""

    # Incidents
    @Property(QObject, constant=True)
    def incidentRows(self) -> DictListModel:
        return self._incidents_model

    @Property(int, notify=ReplaysBase.incidentsChanged)
    def incidentCount(self) -> int:
        return len(self.incidents)

    @Property(dict, notify=ReplaysBase.incidentsChanged)
    def counts(self) -> dict:
        """Incidents by kind: all, cars, walls, of player (mine), shown (made once incidents or rows changed)"""
        return self._counts

    @Property(QObject, constant=True)
    def driverChips(self) -> DictListModel:
        """Drivers with most incidents (filter chips): name, incidents, mine (player), car (synced by name)"""
        return self._chips_model

    @Property(QObject, constant=True)
    def incidentMarkers(self) -> DictListModel:
        """Timeline markers of every incident: key, time, wall, mine, shown (listed), label, selected
        (synced by incident: a new incident adds its marker, others stay)"""
        return self._markers_model

    @Property(float, notify=ReplaysBase.timelineEndChanged)
    def timelineEnd(self) -> float:
        """Session span of timeline (seconds), see timeline_end"""
        return self.timeline_end

    def update_timeline_end(self):
        """Timeline span told once changed (replay time answers: whole minutes, rarely)"""
        if self._last_incident[0] is not self.incidents:  # incidents replaced (never changed in place)
            self._last_incident = (self.incidents, max((incident.time for incident in self.incidents), default=0.0))
        end = timeline_end(self._last_incident[1], self.replay_time, self.session_end)
        if end != self.timeline_end:
            self.timeline_end = end
            self.timelineEndChanged.emit()

    @Property(int, notify=ReplaysBase.filterChanged)
    def incidentFilter(self) -> int:
        return self.incident_filter

    @Property(bool, notify=ReplaysBase.filterChanged)
    def mineOnly(self) -> bool:
        return self.mine_only

    @Property(str, notify=ReplaysBase.filterChanged)
    def driverFilter(self) -> str:
        return self.driver_filter

    @Property(str, notify=ReplaysBase.incidentsChanged)
    def playerName(self) -> str:
        return self.player_name()

    @Property(str, notify=ReplaysBase.incidentSelectionChanged)
    def selectedIncident(self) -> str:
        return self.selected_incident

    @Property(int, notify=ReplaysBase.settingsChanged)
    def secondsBefore(self) -> int:
        return self.seconds_before

    @Property(int, notify=ReplaysBase.settingsChanged)
    def panelIndex(self) -> int:
        """Shown under playback: 0 incidents, 1 standings, 2 track map"""
        return self.panel

    @Slot(int)
    def setPanel(self, index: int):
        if 0 <= index < len(PANELS) and index != self.panel:
            self.panel = index
            self.settingsChanged.emit()
            self.save_settings()
            if PANELS[index] == "map":
                self.update_map_cars()
            self.update_live_timer()
            if PANELS[index] != "incidents" and self._shown and self.state in (SESSION, REPLAY):
                self._timer.stop()
                self.refresh_state()

    @Slot(int)
    def setSecondsBefore(self, seconds: int):
        seconds = max(0, min(int(seconds), 60))
        if seconds != self.seconds_before:
            self.seconds_before = seconds
            self.settingsChanged.emit()
            self.save_settings()

    @Slot(int)
    def setIncidentFilter(self, index: int):
        if 0 <= index < len(INCIDENT_FILTERS) and index != self.incident_filter:
            self.incident_filter = index
            self.filterChanged.emit()
            self.update_incidents()
            self.save_settings()

    @Slot(bool)
    def setMineOnly(self, mine: bool):
        if mine != self.mine_only:
            self.mine_only = mine
            self.filterChanged.emit()
            self.update_incidents()

    @Slot(str)
    def setDriverFilter(self, name: str):
        """Incidents of a driver only ("" all drivers), same driver again: filter removed"""
        name = "" if name == self.driver_filter else name
        self.driver_filter = name
        self.filterChanged.emit()
        self.update_incidents()

    @Slot(str)
    def showDriverIncidents(self, name: str):
        """Incidents panel with incidents of driver only"""
        if name != self.driver_filter:
            self.setDriverFilter(name)
        self.setPanel(PANELS.index("incidents"))

    @Slot(str)
    def selectIncident(self, key: str):
        """Incident row & timeline marker selected: selected role of former & new ones changed"""
        old = self.selected_incident
        if key == old:
            return
        self.selected_incident = key
        move_selection(self._incidents_model, old, key)
        move_selection(self._markers_model, old, key)
        self.incidentSelectionChanged.emit()

    @Slot(int)
    def moveIncidentSelection(self, step: int):
        keys = [row["key"] for row in self._incidents_model.rows]
        if keys:
            index = keys.index(self.selected_incident) + step if self.selected_incident in keys else 0
            self.selectIncident(keys[max(0, min(index, len(keys) - 1))])

    @Slot(str, result=int)
    def incidentIndex(self, key: str) -> int:
        return self._incidents_model.index_of(key)  # cached row index

    @Slot(str, str)
    def jumpTo(self, key: str, driver: str):
        """Replay goes to incident (seconds before), camera on driver's car ("" player's car if involved,
        else first car). In a live session: its replay opened first (back to live later)."""
        incident = next((incident for incident in self.incidents if incident_key(incident) == key), None)
        if incident is None or self.state not in (SESSION, REPLAY) or self.last_session:
            return
        self.selectIncident(key)
        if not driver:
            player = self.player_name()
            driver = player if player and player in (incident.driver, incident.other) else incident.driver
        commands: list[Command] = []
        if self.state == SESSION:
            commands.append(enter_replay)
            self.rewatching = True
            self.playbackChanged.emit()
        car = self.cars.get(driver)
        if car is not None:
            commands.append(("PUT", f"/rest/watch/focus/{car.slot}"))
        replay_time = max(int(incident.time - self.seconds_before), 0)
        commands.append(("PUT", f"/rest/watch/replaytime/{replay_time}"))
        self.send(*commands)

    @Slot(int)
    def jumpNext(self, step: int):
        """Jump to previous (-1) or next (1) incident shown"""
        self.moveIncidentSelection(step)
        if self.selected_incident:
            self.jumpTo(self.selected_incident, "")

    @Slot()
    def copyIncidents(self):
        """Incidents shown copied to clipboard (tab separated: spreadsheet, chat)"""
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None and self._incidents_model.rows:
            clipboard.setText(self.incidents_text("\t"))
            self.notify(trm(f"{len(self._incidents_model.rows)} incident(s) copied"))

    @Slot()
    def exportIncidents(self):
        """Incidents shown saved to a CSV file chosen in a dialog"""
        if not self._incidents_model.rows:
            return
        filename, _ = QFileDialog.getSaveFileName(self._window, tr("Export Incidents"),
                                                  last_folder.start_path("incidents_export", "incidents.csv"),
                                                  "CSV (*.csv)")
        if not filename:
            return
        last_folder.remember("incidents_export", filename)
        try:
            with open(filename, "w", encoding="utf-8-sig", newline="") as file:
                file.write(self.incidents_text(","))
        except OSError as error:
            self.notify(trm(f"Unable to save: {error.strerror or error}"), True)
            return
        self.notify(trm(f"{len(self._incidents_model.rows)} incident(s) exported"))

    def incidents_text(self, delimiter: str) -> str:
        output = io.StringIO()
        writer = csv.writer(output, delimiter=delimiter, lineterminator="\n")
        writer.writerow([tr("Time"), tr("Driver"), tr("Car"), tr("Contact With"), tr("Car"), tr("Contacts")])
        for row in self._incidents_model.rows:
            writer.writerow([row["timeText"], row["driver"], row["driverCar"], row["other"], row["otherCar"],
                             row["count"]])
        return output.getvalue()

    def player_name(self) -> str:
        return next((car.driver for car in self.cars.values() if car.player), "")

    def incident_counts(self) -> dict[str, int]:
        """Incidents of each driver (counted once per incidents list: chips & standings rows)"""
        if self._incident_counts[0] is not self.incidents:  # incidents replaced (never changed in place)
            counts: dict[str, int] = {}
            for incident in self.incidents:
                for name in (incident.driver, incident.other):
                    if name != IMMOVABLE:
                        counts[name] = counts.get(name, 0) + 1
            self._incident_counts = (self.incidents, counts)
        return self._incident_counts[1]

    def incident_shown(self, incident: Incident, player: str) -> bool:
        kind = INCIDENT_FILTERS[self.incident_filter]
        wall = incident.other == IMMOVABLE
        if (kind == "cars" and wall) or (kind == "walls" and not wall):
            return False
        if self.mine_only and player not in (incident.driver, incident.other):
            return False
        return not self.driver_filter or self.driver_filter in (incident.driver, incident.other)

    def update_incidents(self):
        """Incident rows filtered, newest last (session order)"""
        player = self.player_name()
        focused = self.focusedDriver
        rows: list[dict[str, Any]] = []
        for incident in self.incidents:
            if not self.incident_shown(incident, player):
                continue
            wall = incident.other == IMMOVABLE
            key = incident_key(incident)
            rows.append({
                "key": key,
                "time": incident.time,
                "timeText": clock_text(incident.time),
                "driver": incident.driver,
                "other": tr("Wall") if wall else incident.other,
                "wall": wall,
                "mine": bool(player) and player in (incident.driver, incident.other),
                "count": incident.contacts,
                "driverCar": car_text(self.cars.get(incident.driver)),
                "otherCar": "" if wall else car_text(self.cars.get(incident.other)),
                "focused": "driver" if focused and focused == incident.driver
                else "other" if focused and focused == incident.other else "",
                "selected": key == self.selected_incident,
            })
        shown = {row["key"] for row in rows}
        cleared = bool(self.selected_incident) and self.selected_incident not in shown
        if cleared:  # selected incident filtered out: no longer selected (no row has it)
            self.selected_incident = ""
        self._incidents_model.sync(rows)
        made_from = self._markers_from
        if cleared or made_from is None or made_from[0] is not self.incidents or made_from[1:] != (player, shown):
            self.update_markers(player, shown)
        self.update_chips(player)
        walls = sum(1 for incident in self.incidents if incident.other == IMMOVABLE)
        counts = {
            "all": len(self.incidents), "cars": len(self.incidents) - walls, "walls": walls,
            "mine": sum(1 for incident in self.incidents if player in (incident.driver, incident.other)) if player else 0,
            "shown": len(rows),
        }
        view = (counts, player, focused)
        if view != self._incident_view:  # counts & names told only when changed
            self._incident_view = view
            self._counts = counts
            self.incidentsChanged.emit()
        if cleared:
            self.incidentSelectionChanged.emit()
        self.update_timeline_end()

    def update_markers(self, player: str, shown: set[str]):
        """Timeline markers of every incident (shown: incidents listed), synced in place by incident"""
        self._markers_from = (self.incidents, player, shown)
        wall_text = tr("Wall")
        markers = []
        for incident in self.incidents:
            key = incident_key(incident)
            wall = incident.other == IMMOVABLE
            markers.append({
                "key": key, "time": incident.time, "wall": wall,
                "mine": bool(player) and player in (incident.driver, incident.other),
                "shown": key in shown,
                "label": f"{clock_text(incident.time)}  {incident.driver} ↔ {wall_text if wall else incident.other}",
                "selected": key == self.selected_incident,
            })
        self._markers_model.sync(markers)

    def update_chips(self, player: str):
        """Drivers with most incidents (filter chips), driver filtered kept, synced in place by name"""
        counts = self.incident_counts()
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))[:TOP_DRIVERS]
        if self.driver_filter and self.driver_filter not in dict(ranked):
            ranked.append((self.driver_filter, counts.get(self.driver_filter, 0)))
        self._chips_model.sync([{"name": name, "incidents": count, "mine": name == player,
                                 "car": car_text(self.cars.get(name))} for name, count in ranked], "name")
