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
Laps of a results file recorded by the Recorder module (lap telemetry viewer): the race results page opens the
telemetry of a lap of the player's car

Recorded laps are in a folder per track & class ("<track> - <class>"), named after the time they were saved
(end of lap), their lap number & time. A lap of the results file is the recorded lap of the same session
window with the same lap time (lap number within one: the game may count it late), the one saved closest to
the end of that lap.
"""

from __future__ import annotations

import os

from ...formatter import strip_invalid_char
from ...process.results_file import Entry, SessionResult
from ...userfile.telemetry_lap import lap_files, lap_folder_name, lap_number_of, lap_timestamp_of

SAME_LAP_TIME = 0.05  # s: recorded lap time measured from telemetry, results time from game
SAVED_AFTER_END = 90.0  # s: lap file saved this long after the end of lap at most (validation wait, clock drift)
SAVED_BEFORE_END = 30.0  # s: clock of the game session start & of this computer apart
SESSION_MARGIN = 600.0  # s: laps saved before session start / after its last lap (unknown lap starts)


def lap_folders(result: SessionResult, entry: Entry) -> list[str]:
    """Recorded laps folder names of the car of entry: event name, then venue (game track name is one of them)"""
    names = dict.fromkeys(name for name in (result.track, result.venue) if name)
    return [lap_folder_name(strip_invalid_char(f"{name} - {entry.car_class}")) for name in names]


def session_window(result: SessionResult, entry: Entry) -> tuple[float, float]:
    """Unix times laps of entry were saved between (session start, end of its last lap with margins)"""
    ends = [lap.start + lap.time for lap in entry.laps if lap.start >= 0 and lap.time > 0]
    span = max(ends) if ends else max(result.minutes * 60.0, 0.0) + SESSION_MARGIN * 6
    return result.time - SESSION_MARGIN, result.time + span + SESSION_MARGIN


def recorded_laps(telemetry_folder: str, result: SessionResult, entry: Entry) -> dict[int, str]:
    """Recorded lap file of each lap of entry (lap number: path), laps without a file left out

    Reads the lap folders (file names only): run in background.
    """
    if result.time <= 0 or not entry.laps:
        return {}
    first, last = session_window(result, entry)
    files = []
    for folder in lap_folders(result, entry):
        for lap_file in lap_files(os.path.join(telemetry_folder, folder)):
            saved = lap_timestamp_of(lap_file.filename)
            if first <= saved <= last:
                files.append((lap_file, saved, lap_number_of(lap_file.filename)))
    found: dict[int, str] = {}
    used: set[str] = set()
    starts = {lap.number: lap.start for lap in entry.laps if lap.start >= 0}
    for lap in entry.laps:
        if lap.start >= 0 and lap.time > 0:
            end = result.time + lap.start + lap.time
        else:  # untimed lap: ends as next lap starts
            end = result.time + starts[lap.number + 1] if lap.number + 1 in starts else -1.0
        best_path, best_distance = "", float("inf")
        for lap_file, saved, number in files:
            if lap_file.path in used or abs(number - lap.number) > 1:
                continue
            if lap.time > 0:
                if lap_file.lap_time <= 0 or abs(lap_file.lap_time - lap.time) > SAME_LAP_TIME:
                    continue
            elif number != lap.number or end < 0:  # untimed lap: same number, saved at its end
                continue
            if end >= 0 and not -SAVED_BEFORE_END <= saved - end <= SAVED_AFTER_END:
                continue
            distance = abs(saved - end) if end >= 0 else abs(number - lap.number)
            if distance < best_distance:
                best_path, best_distance = lap_file.path, distance
        if best_path:
            found[lap.number] = best_path
            used.add(best_path)
    return found
