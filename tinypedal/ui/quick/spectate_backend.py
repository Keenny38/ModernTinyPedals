#  TinyPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of TinyPedal.
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
Spectate page backend (qml/Spectate.qml): drivers of the session, spectated driver, spectate mode

Drivers are read from the game twice a second, only while the page is shown and data is not paused.
Rows are synced in place (see DictListModel.sync): delegates, scroll position & animations are kept,
and the page is told only about values that changed. Spectated driver is saved as its slot id
(api player_index), which the game keeps while cars join or leave.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from ... import app_signal, realtime_state
from ...api_control import api
from ...formatter import random_color_class
from ...i18n import tr
from ...module_control import mctrl
from ...setting import cfg
from ..module_view import sort_key
from .game_pictures import LogoCache, car_picture_url, notifier
from .models import DictListModel

logger = logging.getLogger(__name__)

POLL_MS = 500
NO_DRIVER = -1  # player_index: no driver spectated
# Data modules recording the spectated driver: started again when another driver is followed
DATA_MODULES = ("module_delta", "module_fuel", "module_mapping", "module_sectors", "module_stint")
ROLES = (
    "key", "slot", "place", "name", "vehicle", "carClass", "classColor",
    "bestLap", "lastLap", "status", "player", "spectated", "brandLogo",
)
STATUS_GARAGE = "garage"
STATUS_PIT = "pit"


def class_color(car_class: str) -> str:
    """Color of vehicle class (vehicle class editor), made from name if not set"""
    style = cfg.user.classes.get(car_class)
    return str(style["color"]) if isinstance(style, dict) and "color" in style else random_color_class(car_class)


def lap_text(seconds: float) -> str:
    """Lap time m:ss.sss, "" if none"""
    from ... import calculation as calc

    return calc.sec2laptime_full(seconds) if 0 < seconds < 36000 else ""


def read_drivers(reader: Any) -> list[dict]:
    """Every car of the session (game order)"""
    vehicle, timing = reader.vehicle, reader.timing
    rows = []
    for index in range(vehicle.total_vehicles()):
        slot = vehicle.slot_id(index)
        car_class = vehicle.class_name(index)
        status = STATUS_GARAGE if vehicle.in_garage(index) else STATUS_PIT if vehicle.in_pits(index) else ""
        rows.append({
            "key": str(slot),
            "slot": slot,
            "place": vehicle.place(index),
            "name": vehicle.driver_name(index),
            "vehicle": vehicle.vehicle_name(index),
            "carClass": car_class,
            "classColor": class_color(car_class),
            "bestLap": lap_text(timing.best_laptime(index)),
            "lastLap": lap_text(timing.last_laptime(index)),
            "status": status,
            "player": bool(vehicle.is_player(index)),
        })
    return rows


def place_key(row: dict) -> tuple:
    """Sort by place, cars without place (0) last"""
    return (row["place"] <= 0, row["place"], sort_key(row["name"]))


class SpectateBackend(QObject):
    """Spectate page state & actions

    Args:
        parent: page widget.
        reader: game data reader (api.read), read when needed: API restarts replace it.
    """

    driversChanged = Signal()  # counts, classes, spectated driver card
    stateChanged = Signal()  # spectate mode on or off, spectated slot
    filterChanged = Signal()

    def __init__(self, parent=None, reader: Callable[[], Any] = lambda: api.read):
        super().__init__(parent)
        self._reader = reader
        self.model = DictListModel(ROLES, self)
        self._drivers: list[dict] = []  # every car, game order
        self._words: tuple[str, ...] = ()
        self._search = ""
        self._class = ""
        self._sort_name = False
        self._active = False
        self._followed = ""  # driver followed by the API, see follow_changed
        self._enabled = bool(cfg.api["enable_player_index_override"])
        self._timer = QTimer(self)  # deleted with backend: never fires on a deleted model
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.poll)
        self.logos = LogoCache()
        notifier().changed.connect(self.pictures_changed)

    # Reading
    def set_active(self, active: bool):
        """Page shown or hidden: drivers read only while shown"""
        self._active = active
        if active:
            self.poll()
            self._timer.start()
        else:
            self._timer.stop()

    @Slot()
    def poll(self):
        """Read drivers from game (not while data is paused), page told about changes only"""
        if realtime_state.paused and self._drivers:
            return
        try:
            drivers = read_drivers(self._reader())
        except (AttributeError, TypeError, ValueError, IndexError) as error:  # API restarting
            logger.debug("Spectate: drivers not read: %s", error)
            return
        for row in drivers:
            row["brandLogo"] = self.logos.brand(row["vehicle"])
        self.set_drivers(drivers)
        if self._enabled:
            self.follow_changed()

    @Slot()
    def pictures_changed(self):
        """Logos & pictures fetched from game meanwhile"""
        if self._drivers:
            self.set_drivers([{**row, "brandLogo": self.logos.brand(row["vehicle"])} for row in self._drivers])

    def set_drivers(self, drivers: list[dict]):
        """Drivers of session, rows updated in place"""
        if drivers == self._drivers:
            return
        self._drivers = drivers
        if self._class and not any(row["carClass"] == self._class for row in drivers):
            self._class = ""  # class left the session
            self.filterChanged.emit()
        self._sync_rows()
        self.driversChanged.emit()

    def _sync_rows(self):
        slot = self.spectated_slot()
        rows = [
            {**row, "spectated": self._enabled and row["slot"] == slot}
            for row in self._drivers if self._accepts(row)
        ]
        rows.sort(key=(lambda row: (sort_key(row["name"]), row["place"])) if self._sort_name else place_key)
        self.model.sync(rows)

    def _accepts(self, row: dict) -> bool:
        if self._class and row["carClass"] != self._class:
            return False
        text = sort_key(f"{row['name']} {row['vehicle']} {row['carClass']}")
        return all(word in text for word in self._words)

    def follow_changed(self):
        """Driver followed by API changed (selected here, hotkey, car left): data modules restarted"""
        try:
            name = self._reader().vehicle.driver_name() if self._enabled else ""
        except (AttributeError, TypeError, ValueError, IndexError):
            return
        if name == self._followed:
            return
        self._followed = name
        if name:
            logger.info("Spectating: %s", name)
        if realtime_state.active:
            for module_name in DATA_MODULES:
                mctrl.reload(module_name)

    @staticmethod
    def spectated_slot() -> int:
        return int(cfg.api["player_index"])

    # Properties
    @Property(QObject, constant=True)
    def drivers(self) -> QObject:
        return self.model

    @Property(bool, notify=stateChanged)
    def enabled(self) -> bool:
        return self._enabled

    @Property(int, notify=stateChanged)
    def spectatedSlot(self) -> int:
        return self.spectated_slot() if self._enabled else NO_DRIVER

    @Property(dict, notify=driversChanged)
    def spectated(self) -> dict:
        """Spectated driver card: found False if no driver spectated or not in session"""
        slot = self.spectated_slot()
        row = next((row for row in self._drivers if row["slot"] == slot), None) if self._enabled else None
        if row is None:
            return {"found": False, "slot": slot if self._enabled else NO_DRIVER}
        return {"found": True, **row, "carPicture": car_picture_url(row["vehicle"], large=True)}

    @Property(int, notify=driversChanged)
    def driverCount(self) -> int:
        return len(self._drivers)

    @Property(int, notify=driversChanged)
    def shownCount(self) -> int:
        return self.model.rowCount()

    @Property(list, notify=driversChanged)
    def classes(self) -> list[dict]:
        """Class filter chips: classes of session with their number of cars, 2 classes or more"""
        counts: dict[str, int] = {}
        for row in self._drivers:
            counts[row["carClass"]] = counts.get(row["carClass"], 0) + 1
        if len(counts) < 2:
            return []
        return [
            {"key": name, "label": name or tr("Unknown"), "color": class_color(name), "count": count}
            for name, count in sorted(counts.items(), key=lambda item: sort_key(item[0]))
        ]

    @Property(str, notify=filterChanged)
    def searchText(self) -> str:
        return self._search

    @Property(str, notify=filterChanged)
    def classFilter(self) -> str:
        return self._class

    @Property(bool, notify=filterChanged)
    def sortByName(self) -> bool:
        return self._sort_name

    @Property(bool, notify=filterChanged)
    def filtered(self) -> bool:
        return bool(self._words or self._class)

    # Filters
    def _filter_changed(self):
        self._sync_rows()
        self.filterChanged.emit()
        self.driversChanged.emit()

    @Slot(str)
    def setSearch(self, text: str):
        self._search = text
        words = tuple(sort_key(text).split())
        if words != self._words:
            self._words = words
            self._filter_changed()
        else:
            self.filterChanged.emit()

    @Slot(str)
    def setClassFilter(self, name: str):
        if name != self._class:
            self._class = name
            self._filter_changed()

    @Slot(bool)
    def setSortByName(self, by_name: bool):
        if by_name != self._sort_name:
            self._sort_name = by_name
            self._filter_changed()

    @Slot()
    def clearFilters(self):
        self._search, self._words, self._class = "", (), ""
        self._filter_changed()

    # Actions
    @Slot()
    def refresh(self):
        """Spectate mode or driver changed elsewhere (hotkey, API menu): shown state only, nothing saved"""
        enabled = bool(cfg.api["enable_player_index_override"])
        if enabled != self._enabled:
            self._enabled = enabled
            logger.info("%s: spectate mode", "ENABLED" if enabled else "DISABLED")
            if not enabled:
                self._followed = ""
        self.stateChanged.emit()
        self._sync_rows()
        self.driversChanged.emit()

    @Slot(bool)
    def setEnabled(self, enabled: bool):
        """Turn spectate mode on or off: saved, API set up again"""
        if enabled == bool(cfg.api["enable_player_index_override"]):
            return
        cfg.api["enable_player_index_override"] = enabled
        cfg.save()
        api.setup()
        app_signal.refresh.emit(True)  # notification bar, other pages, this page (see refresh)
        self.refresh()
        if enabled:
            self.follow_changed()

    @Slot(int)
    def spectate(self, slot: int):
        """Spectate driver of slot (NO_DRIVER: nobody), spectate mode turned on if off"""
        if cfg.api["player_index"] != slot:
            cfg.api["player_index"] = slot
            if cfg.api["enable_player_index_override"]:
                api.setup()
                cfg.save()
        if not cfg.api["enable_player_index_override"]:
            self.setEnabled(True)  # saves & sets API up
            return
        self.refresh()
        self.follow_changed()

    @Slot(int)
    def step(self, offset: int):
        """Spectate next (1) or previous (-1) driver by place, wraps around"""
        ordered = sorted(self._drivers, key=place_key)
        if not ordered:
            return
        slots = [row["slot"] for row in ordered]
        slot = self.spectated_slot()
        if slot in slots:
            target = slots[(slots.index(slot) + offset) % len(slots)]
        else:
            target = slots[0] if offset > 0 else slots[-1]
        self.spectate(target)

    @Slot()
    def stopSpectating(self):
        """Nobody spectated: spectate mode kept"""
        if cfg.api["enable_player_index_override"]:
            self.spectate(NO_DRIVER)

    def release(self):
        self._timer.stop()
