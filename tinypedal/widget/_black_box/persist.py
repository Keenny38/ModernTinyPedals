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
Black box widget, state kept across widget rebuilds

Changing an option rebuilds the widget. What the driver would lose with it (the geometry the
resize anchor works from, the recorded incidents, the event log) is kept here per widget name,
for the running application only, never saved to file.
"""

from __future__ import annotations

from dataclasses import dataclass

from .recorder import Event, EventLog, Incident, Recorder


@dataclass
class Memory:
    """What a rebuilt widget takes over from the one it replaces"""

    geometry: tuple[int, int, int, int] | None = None  # last on-screen x, y, width, height
    incidents: tuple[Incident, ...] = ()
    events: tuple[Event, ...] = ()
    last_damage: float = 0.0  # damage the event log already reported


MEMORY: dict[str, Memory] = {}


def memory(widget_name: str) -> Memory:
    """Memory of a widget, created on first use"""
    kept = MEMORY.get(widget_name)
    if kept is None:
        kept = MEMORY[widget_name] = Memory()
    return kept


def keep_records(widget_name: str, recorder: Recorder, event_log: EventLog):
    """Called when the widget stops: keep incidents & events for the next widget"""
    kept = memory(widget_name)
    kept.incidents = tuple(recorder.incidents)
    kept.events = tuple(event_log.events)
    kept.last_damage = event_log.last_damage


def restore_records(widget_name: str, recorder: Recorder, event_log: EventLog):
    """Give a new widget the incidents & events of the one it replaces (newest kept if fewer fit)"""
    kept = MEMORY.get(widget_name)
    if kept is None:
        return
    recorder.incidents.extend(kept.incidents)
    event_log.events.extend(kept.events)
    # Damage already logged is not logged again by the new widget
    recorder.last_damage = event_log.last_damage = kept.last_damage
