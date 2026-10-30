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
Game Replays page standings (mixin of GameReplaysBackend): standings rows of the session (class filter,
selected car), lap starts seen of each car, go to a lap of a car
"""

from __future__ import annotations

import html

from PySide6.QtCore import Property, QObject, Slot

from ...formatter import class_alias, class_color
from ...i18n import tr
from ...process.game_info import Standing
from . import dialogs
from .director_shared import status_text  # same status & colors as Broadcast Director
from .models import DictListModel
from .replays_base import ReplaysBase
from .replays_common import (
    MAX_GO_TO_LAP,
    PANELS,
    REPLAY,
    SESSION,
    energy_text,
    gap_text,
    go_to_lap,
    lap_text,
    move_selection,
)


class ReplaysStandings(ReplaysBase):
    """Standings of Game Replays page"""

    # Standings
    @Property(QObject, constant=True)
    def standingRows(self) -> DictListModel:
        return self._standings_model

    @Property(int, notify=ReplaysBase.carCountChanged)
    def carCount(self) -> int:
        return self.car_count

    @Property(list, notify=ReplaysBase.classesChanged)
    def classes(self) -> list[dict]:
        """Vehicle classes of session (filter chips): name, color, count, in order of best position"""
        return self.class_list

    @Property(bool, notify=ReplaysBase.energyColumnChanged)
    def hasEnergy(self) -> bool:
        """Energy (or fuel) of some cars told by game (own team): column shown (found once per game answer)"""
        return self.has_energy

    @Property(str, notify=ReplaysBase.classFilterChanged)
    def classFilter(self) -> str:
        return self.class_filter

    @Property(str, notify=ReplaysBase.selectedCarChanged)
    def selectedCar(self) -> str:
        return self.selected_car

    @Slot(str)
    def setClassFilter(self, name: str):
        """Cars of a class only ("" all), same class again: filter removed"""
        name = "" if name == self.class_filter else name
        if name != self.class_filter:
            self.class_filter = name
            self.classFilterChanged.emit()
            self.update_standings()

    @Slot(str)
    def selectCar(self, key: str):
        """Standings row selected: selected role of former & new rows changed"""
        old = self.selected_car
        if key == old:
            return
        self.selected_car = key
        move_selection(self._standings_model, old, key)
        self.selectedCarChanged.emit()

    @Slot(int)
    def moveCarSelection(self, step: int):
        keys = [row["key"] for row in self._standings_model.rows]
        if keys:
            index = keys.index(self.selected_car) + step if self.selected_car in keys else 0
            self.selectCar(keys[max(0, min(index, len(keys) - 1))])

    @Slot(str, result=int)
    def carIndex(self, key: str) -> int:
        return self._standings_model.index_of(key)  # cached row index

    @Slot(str)
    def watchCar(self, key: str):
        """Camera on car of standings row (or map)"""
        car = self.car_of(key)
        if car is not None and self.state in (SESSION, REPLAY):
            self.selectCar(key)
            self.send(("PUT", f"/rest/watch/focus/{car.slot}"))

    def record_laps(self):
        """Session time of lap starts of each car, as seen (live session going on, replay playing)"""
        changed = False
        for car in self.standings:
            lap = car.laps + 1
            if car.lap_start > 0 or lap == 1:
                starts = self.lap_starts.setdefault(car.slot, {})
                if starts.get(lap) != car.lap_start:
                    starts[lap] = car.lap_start
                    changed = True
        if changed:
            self.laps_changed()

    def laps_changed(self):
        """lapsChanged emitted only when lap marks or lap of car followed by camera changed
        (lap starts of other cars are not shown)"""
        slot = self.focused_slot()
        view = (slot, self.camera_lap(), tuple(sorted(self.lap_starts.get(slot, {}).items())))
        if view != self._lap_view:
            self._lap_view = view
            self.lapsChanged.emit()

    @Property(list, notify=ReplaysBase.lapsChanged)
    def lapMarks(self) -> list[dict]:
        """Lap starts of car followed by camera seen so far (timeline): lap, time"""
        starts = self.lap_starts.get(self.focused_slot(), {})
        return [{"lap": lap, "time": start} for lap, start in sorted(starts.items()) if lap > 1]

    @Property(int, notify=ReplaysBase.lapsChanged)
    def cameraLap(self) -> int:
        """Lap driven by car followed by camera, 0 if unknown"""
        return self.camera_lap()

    def camera_lap(self) -> int:
        car = next((car for car in self.standings if car.slot == self.focused_slot()), None)
        return car.laps + 1 if car is not None else 0

    @Slot(int)
    def stepLap(self, step: int):
        """Replay goes to start of previous (-1) or next (1) lap of car followed by camera
        (lap start seen before: at once, else looked for)"""
        slot, lap = self.focused_slot(), self.camera_lap() + step
        if self.state != REPLAY or slot < 0 or lap < 1:
            return
        start = self.lap_starts.get(slot, {}).get(lap)
        if start is not None and (start > 0 or lap == 1):
            self.send(("PUT", f"/rest/watch/replaytime/{max(int(start), 0)}"))
        else:
            self.send(go_to_lap(slot, lap, 0))

    @Slot(str)
    def goToLap(self, key: str):
        """Replay goes to start of a lap (asked in the page) of car, camera on car"""
        car = self.car_of(key)
        if car is None or self.state != REPLAY:
            return

        def go(lap: int):
            if self.state == REPLAY and self.car_of(key) is not None:  # replay closed meanwhile: nothing sent
                self.selectCar(key)
                self.send(go_to_lap(car.slot, lap, self.seconds_before))

        # Any lap, also ahead of replay time (go_to_lap searches forward): not ahead of current lap only
        dialogs.ask_number(self._window, tr("Go to lap"),
                           tr("Lap of %1:").replace("%1", f"<b>{html.escape(car.driver)}</b>"),
                           go, car.laps + 1, 1, max(car.laps + 1, MAX_GO_TO_LAP))

    def car_of(self, key: str) -> Standing | None:
        return next((car for car in self.standings if str(car.slot) == key), None)

    def update_standings(self):
        """Standings rows: position (class position), car, laps & times, gap, status, camera, incidents"""
        counts: dict[str, int] = {}
        for car in self.standings:
            counts[car.car_class] = counts.get(car.car_class, 0) + 1
        class_list = [{"name": name, "color": class_color(name), "count": count} for name, count in counts.items()]
        if class_list != self.class_list:
            self.class_list = class_list
            self.classesChanged.emit()
        if self.class_filter and self.class_filter not in counts:
            self.class_filter = ""
            self.classFilterChanged.emit()
        if len(self.standings) != self.car_count:
            self.car_count = len(self.standings)
            self.carCountChanged.emit()
        has_energy = any(car.energy >= 0 or car.fuel >= 0 for car in self.standings)
        if has_energy != self.has_energy:
            self.has_energy = has_energy
            self.energyColumnChanged.emit()
        focused = self.focused_slot()
        incidents = self.incident_counts()
        race = self.session_name.upper().startswith("RACE")
        leader_best = min((car.best for car in self.standings if car.best > 0), default=0.0)
        fastest = {car.car_class: min((other.best for other in self.standings
                                       if other.car_class == car.car_class and other.best > 0), default=0.0)
                   for car in self.standings}
        class_positions: dict[str, int] = {}
        rows = []
        for car in self.standings:
            class_positions[car.car_class] = class_positions.get(car.car_class, 0) + 1
            if self.class_filter and car.car_class != self.class_filter:
                continue
            status, tone = status_text(car)
            rows.append({
                "key": str(car.slot),
                "position": car.position,
                "classPosition": class_positions[car.car_class],
                "number": car.number,
                "driver": car.driver,
                "vehicle": car.team or car.vehicle,
                "carClass": car.car_class,
                "classColor": class_color(car.car_class), "classAlias": class_alias(car.car_class),
                "laps": car.laps,
                "best": lap_text(car.best),
                "last": lap_text(car.last),
                "gap": gap_text(car, race, leader_best),
                "energy": energy_text(car)[0],
                "energyLevel": energy_text(car)[1],
                "pits": car.pitstops,
                "status": status,
                "statusTone": tone,
                "penalties": car.penalties,
                "onCamera": car.slot == focused,
                "player": car.player,
                "fastest": car.best > 0 and car.best == fastest.get(car.car_class),
                "incidents": incidents.get(car.driver, 0),
                "brandLogo": self.logos.brand(car.vehicle),
                "selected": str(car.slot) == self.selected_car,
            })
        cleared = bool(self.selected_car) and not any(row["selected"] for row in rows)
        if cleared:  # car selected left the session or filtered out
            self.selected_car = ""
        self._standings_model.sync(rows)
        if cleared:
            self.selectedCarChanged.emit()
        self.laps_changed()  # car followed by camera may have changed
        if PANELS[self.panel] == "map":  # hidden map refreshed once shown
            self.update_map_cars()
