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
Game data notification: wake data module threads on new game data instead of polling
"""

from __future__ import annotations

import threading


class DataNotifier:
    """Wake data module threads when shared memory connector got new game data

    Connector update thread attaches while running and notifies once game data visible to modules changed
    (new sample, player index, resets, pause state). Each data module thread subscribes its own wake event,
    set on notification (kept set until module consumes it, never missed). Derived notification wakes
    only modules subscribed to it (delta module position update).
    Without any connector attached (other API, tests), modules keep polling at fixed interval.
    """

    __slots__ = (
        "_lock",
        "_sources",
        "_data_events",
        "_derived_events",
    )

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sources = 0
        # Copy on write, notify iterates current tuple without lock
        self._data_events: tuple[threading.Event, ...] = ()
        self._derived_events: tuple[threading.Event, ...] = ()

    @property
    def available(self) -> bool:
        """Whether a connector notifies new game data"""
        return self._sources > 0

    def attach(self) -> None:
        """Connector update thread started notifying"""
        with self._lock:
            self._sources += 1
        self.notify()

    def detach(self) -> None:
        """Connector update thread stopped notifying, modules woken (back to polling)"""
        with self._lock:
            self._sources = max(self._sources - 1, 0)
        self.notify()

    def subscribe(self, event: threading.Event, derived: bool = False) -> None:
        """Set event on new game data, also on derived data if derived"""
        with self._lock:
            if event not in self._data_events:
                self._data_events += (event,)
            if derived and event not in self._derived_events:
                self._derived_events += (event,)

    def unsubscribe(self, event: threading.Event) -> None:
        """Stop setting event"""
        with self._lock:
            self._data_events = tuple(_event for _event in self._data_events if _event is not event)
            self._derived_events = tuple(_event for _event in self._derived_events if _event is not event)

    def notify(self) -> None:
        """New game data available"""
        for event in self._data_events:
            event.set()

    def notify_derived(self) -> None:
        """Data derived by a module changed (delta module position)"""
        for event in self._derived_events:
            event.set()


notifier = DataNotifier()
