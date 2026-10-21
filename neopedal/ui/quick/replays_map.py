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
Game Replays page track map (mixin of GameReplaysBackend): track lines of the game map, cars moved along the
track between game answers, live positions read from the shared memory of the game
"""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Property, QObject, Slot

from ...formatter import class_color
from ...process.game_info import Standing
from .lines import VertexStore, band
from .models import DictListModel
from .replays_base import ReplaysBase
from .replays_common import JUMP, MAX_PATH_SPEED, OFF_TRACK, PANELS, PIT_WIDTH, REPLAY, ROAD_WIDTH, SESSION
from .track_path import TrackPath


class ReplaysMap(ReplaysBase):
    """Track map of Game Replays page"""

    # Track map
    @Property(int, notify=ReplaysBase.revisionChanged)
    def mapRevision(self) -> int:
        return self.revision

    @Property(dict, notify=ReplaysBase.mapChanged)
    def mapView(self) -> dict:
        """Map bounds & vertex keys, {} if no map"""
        if not self.map_center:
            return {}
        xs = [point[0] for point in self.map_center + self.map_pit]
        ys = [point[1] for point in self.map_center + self.map_pit]
        return {"minX": min(xs), "minY": min(ys), "maxX": max(xs), "maxY": max(ys),
                "road": self.prefix + "road", "edge": self.prefix + "edge", "pit": self.prefix + "pit"}

    @Property(QObject, constant=True)
    def mapCars(self) -> DictListModel:
        """Cars on map: key (slot), map x & y, color, number, driver, position, followed by camera, player, in pits
        (rows kept by slot: cars move smoothly)"""
        return self._map_model

    @Property(dict, notify=ReplaysBase.mapChanged)
    def mapPath(self) -> dict:
        """Track path cars move along between answers: points, distance of each, length, closed; {} if no map"""
        path = self.track_path
        if path is None:
            return {}
        return {"xs": path.xs, "ys": path.ys, "s": path.s, "length": path.length, "closed": path.closed}

    def update_map_cars(self):
        focused = self.focused_slot()
        rows = []
        seen = set()
        for car in self.standings:
            if not (car.x or car.y):
                continue
            seen.add(car.slot)
            rows.append({
                "key": str(car.slot), "mapX": car.x, "mapY": car.y, "color": class_color(car.car_class),
                "number": car.number or str(car.position), "driver": car.driver, "position": car.position,
                "onCamera": car.slot == focused, "player": car.player, "inPit": car.in_pit or car.garage,
                **self.car_track(car),
            })
        for slot in set(self._car_tracks) - seen:
            del self._car_tracks[slot]
        self._map_model.sync(rows)

    def car_track(self, car: Standing) -> dict:
        """Place of car on track path & speed along it (moved by page between answers at playback rate), easing
        from where page showed it (correction, meters) to new place"""
        off = {"onTrack": False, "pathS": 0.0, "speed": 0.0, "sampleTime": 0.0, "correction": 0.0, "receivedMs": 0.0}
        path = self.track_path
        if path is None or car.in_pit or car.garage:
            self._car_tracks.pop(car.slot, None)
            return off
        sample = car.lap_start + car.into_lap if car.into_lap >= 0 else -1.0
        old = self._car_tracks.get(car.slot)
        if old is not None and sample == old[1]:  # same answer again (panel shown...): unchanged
            s, sample, speed, segment, eased, received = old
        else:
            s, gap, segment = path.project(car.x, car.y, old[3] if old is not None else -1)
            if gap > OFF_TRACK or sample < 0:
                self._car_tracks.pop(car.slot, None)
                return off
            if old is not None and old[2]:  # speed measured before, kept if this move is no speed (jump)
                speed = old[2]
            else:
                speed = self._direction * path.length / car.estimated if car.estimated > 0 else 0.0
            eased = 0.0
            if old is not None and sample > old[1]:
                moved = path.delta(old[0], s) / (sample - old[1])
                if abs(moved) < MAX_PATH_SPEED:
                    speed = moved if not old[2] else (old[2] + moved) / 2
                    if abs(moved) > 5:  # driving: direction of path learned from cars
                        self._direction = 1.0 if moved > 0 else -1.0
                expected = old[0] + old[2] * (sample - old[1])
                eased = path.delta(s, expected)
                if abs(eased) > JUMP:
                    eased = 0.0
            received = time.time() * 1000
            self._car_tracks[car.slot] = (s, sample, speed, segment, eased, received)
        return {"onTrack": True, "pathS": s, "speed": speed, "sampleTime": sample, "correction": eased,
                "receivedMs": received}

    # Live positions: shared memory of the game on this computer, read every LIVE_MS like the Broadcast Director
    # track map; between game answers cars are then where the game shows them, not moved by guess along the track
    @Property(dict, notify=ReplaysBase.mapLiveChanged)
    def mapLive(self) -> dict:
        """Map x & y of each car (slot) read from shared memory, {} if not read (cars moved along track instead)"""
        return self.map_live

    @staticmethod
    def reader() -> Any:
        """Game data of the app (shared memory), None if not readable"""
        from ...api_control import api

        return getattr(api, "read", None)

    def live_wanted(self) -> bool:
        return self._shown and PANELS[self.panel] == "map" and self.state in (SESSION, REPLAY) and bool(
            self.map_center)

    def update_live_timer(self):
        if self.live_wanted():
            if not self._live_timer.isActive():
                self._live_timer.start()
                self.read_live_positions()
        else:
            self._live_timer.stop()
            self.set_live({})

    def read_live_positions(self):
        if not self.live_wanted():
            self.update_live_timer()
            return
        positions: dict[str, list[float]] = {}
        reader = self.reader()
        if reader is not None:
            try:
                for index in range(reader.vehicle.total_vehicles()):
                    x, _, z = reader.vehicle.position_xyz(index)
                    if x or z:
                        positions[str(reader.vehicle.slot_id(index))] = [round(x, 2), round(-z, 2)]
            except (AttributeError, IndexError, TypeError, ValueError):
                positions = {}
        # Shared memory of the session open in game: its cars are those of the game answer, else not used
        if not positions.keys() & {str(car.slot) for car in self.standings}:
            positions = {}
        self.set_live(positions)

    def set_live(self, positions: dict[str, list[float]]):
        if positions != self.map_live:
            self.map_live = positions
            self.mapLiveChanged.emit()

    def set_map(self, track: str, points: tuple[list, list] | None):
        """Track map of game (center path & pit lane), lines built for map scale"""
        self.map_track = track
        self.map_center, self.map_pit = points if points else ([], [])
        if len(self.map_center) < 3:
            self.map_center, self.map_pit = [], []
        self._car_tracks.clear()
        if self.map_center:
            xs = [point[0] for point in self.map_center]
            ys = [point[1] for point in self.map_center]
            self.track_path = TrackPath(xs, ys, abs(xs[0] - xs[-1]) + abs(ys[0] - ys[-1]) < 500)
        else:
            self.track_path = None
        self.build_map()
        self.mapChanged.emit()
        self.update_live_timer()

    @Slot(float)
    def setMapScale(self, meters_per_pixel: float):
        """Map zoom settled: lines with a minimum pixel width rebuilt"""
        meters_per_pixel = max(meters_per_pixel, 1e-3)
        if abs(meters_per_pixel - self.meters_per_pixel) > 1e-6:
            self.meters_per_pixel = meters_per_pixel
            self.build_map()

    def build_map(self):
        if not self.map_center:
            VertexStore.remove_prefix(self.prefix)
        else:
            xs = [point[0] for point in self.map_center]
            ys = [point[1] for point in self.map_center]
            closed = abs(xs[0] - xs[-1]) + abs(ys[0] - ys[-1]) < 500
            road = max(ROAD_WIDTH, 4 * self.meters_per_pixel) / 2
            VertexStore.set(self.prefix + "road", band(xs, ys, road, closed))
            VertexStore.set(self.prefix + "edge", band(xs, ys, road + max(2.0, 1.5 * self.meters_per_pixel), closed))
            if self.map_pit:
                VertexStore.set(self.prefix + "pit", band([point[0] for point in self.map_pit],
                                                          [point[1] for point in self.map_pit],
                                                          max(PIT_WIDTH, 2 * self.meters_per_pixel) / 2))
        self.revision += 1
        self.revisionChanged.emit()
