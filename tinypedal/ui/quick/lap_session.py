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
Lap viewer session tab (mixin of LapViewerBackend): every lap of a session of current track, long run trend, tyre
wear, off tracks & track limits read from lap files in background
"""

from __future__ import annotations

import os

from PySide6.QtCore import Slot

from ...userfile.lap_geometry import session_values
from ...userfile.telemetry_lap import lap_number_of
from .. import lap_viewer
from ..lap_viewer import LapEntry, format_laptime
from .lap_base import BackendBase


def least_squares(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Slope & intercept of line fitting points, (0, mean) if x does not vary"""
    count = len(points)
    if not count:
        return 0.0, 0.0
    mean_x = sum(x for x, _ in points) / count
    mean_y = sum(y for _, y in points) / count
    spread = sum((x - mean_x) ** 2 for x, _ in points)
    if spread <= 0:
        return 0.0, mean_y
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / spread
    return slope, mean_y - slope * mean_x


class SessionTab(BackendBase):
    """Session tab of lap viewer page"""

    # Session: every lap of a session of current track (session tab)
    def session_groups(self) -> list[tuple[str, str, list[LapEntry]]]:
        """Sessions of current track, newest first: key, title, laps in driving order"""
        groups = []
        for group in self.track_sessions():
            header = self.session_row(group, False)
            groups.append((header["session"], f"{header['title']} · {len(group)}", group))
        return groups

    def session_key(self) -> str:
        """Session shown: chosen one, else session of reference lap, else newest"""
        groups = self.session_groups()
        keys = [key for key, _, _ in groups]
        if self._session_key in keys:
            return self._session_key
        for key, _, group in groups:  # session of reference lap, else newest
            if any(entry.file.path == self.reference_key for entry in group):
                return key
        return keys[0] if keys else ""

    @Slot(str)
    def setSession(self, key: str):
        self._session_key = key
        self.sessionChanged.emit()
        self.start_session_job()

    def session_data(self) -> dict:
        """Laps of shown session: number, time, valid, fuel & tyre wear used, off tracks, track limits, shown"""
        key = self.session_key()
        group = next((laps for name, _, laps in self.session_groups() if name == key), [])
        colors = {lap.key: lap.color.name() for lap in self.data.laps}
        units = lap_viewer.display_units()
        to_temperature = units["temperature"][0]
        rows = []
        for entry in group:
            info = entry.info
            extra = self._session_extra.get(entry.file.path, (0.0, {}))[1]
            fuel = -1.0
            start, end = info.get("fuel_start"), info.get("fuel_end")
            if isinstance(start, (int, float)) and isinstance(end, (int, float)) and start >= end:
                fuel = float(start - end)
            wear = extra.get("wear", -1.0)
            wear_start, wear_end = info.get("wear_start"), info.get("wear_end")
            if isinstance(wear_start, list) and isinstance(wear_end, list) and len(wear_start) == len(wear_end) == 4:
                wear = sum(first - last for first, last in zip(wear_start, wear_end)) / 4
            temperature = info.get("track_temperature")
            rows.append({
                "path": entry.file.path, "number": lap_number_of(entry.file.filename),
                "time": entry.file.lap_time, "text": format_laptime(entry.file.lap_time),
                "valid": entry.file.valid and info.get("kind", "lap") == "lap", "kind": str(info.get("kind", "lap")),
                "fuel": fuel, "wear": wear,
                "temp": (to_temperature(float(temperature)) if to_temperature else float(temperature))
                if isinstance(temperature, (int, float)) and not isinstance(temperature, bool) else None,
                "offtrack": extra.get("offtrack", -1), "limits": extra.get("limits", -1),
                "shown": entry.file.path in colors, "color": colors.get(entry.file.path, ""),
                "reference": entry.file.path == self.reference_key,
            })
        valid = [row["time"] for row in rows if row["valid"] and row["time"] > 0]
        fuel_unit = units["fuel"]
        return {
            "laps": rows, "best": min(valid, default=0.0), "worst": max(valid, default=0.0),
            "busy": self._session_busy, "fuelUnit": fuel_unit[1], "temperatureUnit": units["temperature"][1],
            "fuelScale": fuel_unit[0](1.0) if fuel_unit[0] else 1.0,
            "trend": self.session_trend(rows, group),
        }

    @staticmethod
    def session_trend(rows: list[dict], group: list[LapEntry]) -> dict:
        """Long run of session: clean laps without outliers (traffic, mistakes), pace, lap time trend per lap,
        per % of tyre wear; outlier laps flagged in rows"""
        clean = [(index, row["time"]) for index, row in enumerate(rows) if row["valid"] and row["time"] > 0]
        for row in rows:
            row["outlier"] = False
        if len(clean) < 3:
            return {}
        times = sorted(lap_time for _, lap_time in clean)
        quarter, three_quarters = times[len(times) // 4], times[(len(times) * 3) // 4]
        limit = min(three_quarters + 1.5 * (three_quarters - quarter), times[0] * 1.07)
        paced = [(index, lap_time) for index, lap_time in clean if lap_time <= limit + 1e-6]
        for index, lap_time in clean:
            if lap_time > limit + 1e-6:
                rows[index]["outlier"] = True
        result: dict = {"pace": sum(lap_time for _, lap_time in paced) / len(paced), "used": len(paced),
                        "left": len(clean) - len(paced)}
        if len(paced) >= 4:
            slope, intercept = least_squares([(float(index), lap_time) for index, lap_time in paced])
            first, last = paced[0][0], paced[-1][0]
            result.update({"slope": slope, "x0": first, "y0": intercept + slope * first, "x1": last,
                           "y1": intercept + slope * last})
            worn = []  # tread worn at lap start (%), lap time
            for index, lap_time in paced:
                start = group[index].info.get("wear_start") if index < len(group) else None
                if isinstance(start, list) and len(start) == 4 and all(isinstance(value, (int, float)) for value in start):
                    worn.append((100 - sum(start) / 4, lap_time))
            if len(worn) >= 4 and max(value for value, _ in worn) - min(value for value, _ in worn) >= 1:
                result["wearSlope"] = least_squares(worn)[0]
        return result

    def start_session_job(self):
        """Tyre wear, off tracks & track limits of session laps read from lap files in background (cached)

        Session chosen while a job runs: its laps read once the job is done (see done).
        """
        if self._session_busy:
            return
        key = self.session_key()
        group = next((laps for name, _, laps in self.session_groups() if name == key), [])
        todo = []
        for entry in group:
            try:
                mtime = os.path.getmtime(entry.file.path)
            except OSError:
                continue
            cached = self._session_extra.get(entry.file.path)
            if cached is None or cached[0] != mtime:
                todo.append((entry.file.path, mtime))
        if not todo:
            return
        self._session_busy = True
        self.sessionChanged.emit()  # busy indicator

        def done(found):
            self._session_busy = False
            found = found if isinstance(found, dict) else {}
            for path, mtime in todo:  # unreadable laps (or job failed) not read again until their file changes
                self._session_extra[path] = found.get(path, (mtime, {}))
            self.sessionChanged.emit()
            if self._side_tab == 4:  # session or track changed meanwhile
                self.start_session_job()

        self.run_process_job("session", done, session_values, self.folder, todo)
