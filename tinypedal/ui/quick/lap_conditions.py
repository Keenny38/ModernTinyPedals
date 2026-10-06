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
Lap viewer conditions (mixin of LapViewerBackend): reference lap driven in similar conditions (track temperature,
tyre compound, wetness), setup differences between two laps
"""

from __future__ import annotations

import html
from collections.abc import Sequence

from PySide6.QtCore import Slot

from ...i18n import tr, trm
from ...userfile.telemetry_lap import LapData, monotonic_distance, official_lap_time
from .. import lap_viewer
from ..lap_viewer import LapEntry, format_laptime, lap_label, number_text, save_viewer_setting
from .lap_base import BackendBase
from .stint_analysis import lap_compound

SIMILAR_TOLERANCES = (1, 2, 3, 5, 8)  # °C, track temperature difference of laps in similar conditions (setting)
SIMILAR_TOLERANCE = 3
SIMILAR_WETNESS = 0.1  # wetness difference (0 dry to 1 soaked) of laps in similar conditions
SETTING_ROWS = (  # driver settings recorded in lap samples: column, name, decimals
    ("brake_bias", "Brake Bias", 1), ("tc_level", "TC Level", 0), ("abs_level", "ABS Level", 0),
    ("engine_map", "Engine Map", 0),
)


def info_number(info: dict, key: str) -> float | None:
    """Number of lap info, None if not recorded"""
    value = info.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def similar_laps(entries: Sequence[LapEntry], target: dict, tolerance: float, exclude: str = "") -> list[LapEntry]:
    """Clean timed laps driven in conditions like target lap info: track temperature within tolerance (laps
    without temperature left out when target has one), same compound & wetness when both laps know them"""
    temperature = info_number(target, "track_temperature")
    compound = lap_compound(target)
    wetness = info_number(target, "wetness")
    found = []
    for entry in entries:
        if (entry.file.path == exclude or not entry.file.valid or entry.file.lap_time <= 0
                or entry.info.get("kind", "lap") != "lap"):
            continue
        if temperature is not None:
            other = info_number(entry.info, "track_temperature")
            if other is None or abs(other - temperature) > tolerance + 1e-6:
                continue
        other_compound = lap_compound(entry.info)
        if compound and other_compound and other_compound != compound:
            continue
        other_wetness = info_number(entry.info, "wetness")
        if wetness is not None and other_wetness is not None and abs(other_wetness - wetness) > SIMILAR_WETNESS + 1e-6:
            continue
        found.append(entry)
    return found


def similar_best(entries: Sequence[LapEntry], target: dict, tolerance: float, exclude: str = "") -> LapEntry | None:
    """Fastest clean lap driven in conditions like target lap info, None if none"""
    return min(similar_laps(entries, target, tolerance, exclude), key=lambda entry: entry.file.lap_time, default=None)


def lap_settings(lap: LapData | None) -> dict[str, tuple[float, float]]:
    """Driver settings recorded in lap samples: column: (value at lap start, value at lap end), cars without a
    setting (game gives -1) left out"""
    settings: dict[str, tuple[float, float]] = {}
    if lap is None:
        return settings
    for column, _, _ in SETTING_ROWS:
        if column not in lap.columns:
            continue
        values = [value for value in monotonic_distance(lap, column)[1] if value >= 0]
        if values:
            settings[column] = (float(values[0]), float(values[-1]))
    return settings


def setup_diff(info_a: dict, info_b: dict, lap_a: LapData | None, lap_b: LapData | None) -> dict:
    """Setup differences of two laps: state (same, different, unknown: no fingerprint), rows (name, values, differs)

    Setup values themselves are not recorded: setup name & fingerprint (same setup values, same fingerprint),
    driver settings recorded in lap samples (brake bias, TC, ABS, engine map) & starting fuel.
    """
    rows = []
    fingerprints = str(info_a.get("setup", "")), str(info_b.get("setup", ""))
    state = "unknown" if not all(fingerprints) else "same" if fingerprints[0] == fingerprints[1] else "different"

    def setup_name(info: dict) -> str:
        name = str(info.get("setup_name", ""))
        return f"{name}*" if name and info.get("setup_modified") else name

    names = setup_name(info_a), setup_name(info_b)
    if any(names):
        rows.append({"name": "Setup", "a": names[0] or "—", "b": names[1] or "—", "differs": names[0] != names[1]})
    if any(fingerprints):
        rows.append({"name": "Setup Fingerprint", "a": fingerprints[0] or "—", "b": fingerprints[1] or "—",
                     "differs": fingerprints[0] != fingerprints[1]})
    settings_a, settings_b = lap_settings(lap_a), lap_settings(lap_b)

    def setting_text(values: tuple[float, float] | None, decimals: int) -> str:
        if values is None:
            return "—"
        start, end = (number_text(value, decimals) for value in values)
        return start if start == end else f"{start} → {end}"  # changed during lap

    for column, name, decimals in SETTING_ROWS:
        if column not in settings_a and column not in settings_b:
            continue
        first, second = setting_text(settings_a.get(column), decimals), setting_text(settings_b.get(column), decimals)
        rows.append({"name": name, "a": first, "b": second, "differs": first != second})
    fuels = info_number(info_a, "fuel_start"), info_number(info_b, "fuel_start")
    if any(value is not None for value in fuels):
        convert, unit = lap_viewer.display_units()["fuel"]
        first, second = (f"{number_text(convert(value) if convert else value, 1)} {unit}" if value is not None else "—"
                         for value in fuels)
        rows.append({"name": "Starting Fuel", "a": first, "b": second, "differs": first != second})
    return {"state": state, "rows": rows}


class LapConditions(BackendBase):
    """Similar conditions reference & setup differences of lap viewer page"""

    def similar_target(self) -> LapEntry | None:
        """Lap looked at: first compared lap shown, else newest clean lap of track"""
        entries = {entry.file.path: entry for entry in self.all_entries()}
        compared = self.compared_lap()
        if compared is not None and compared.key in entries:
            return entries[compared.key]
        return next((entry for entry in self.entries if entry.file.valid and entry.info.get("kind", "lap") == "lap"),
                    None)

    @Slot()
    def compareSimilarConditions(self):
        """Lap looked at compared with fastest lap of track driven in similar conditions (track temperature
        within tolerance, same tyre compound & wetness when known), set as reference"""
        target = self.similar_target()
        if target is None:
            self.set_status(tr("No lap to compare."))
            return
        best = similar_best(self.entries, target.info, self._similar_tolerance, target.file.path)
        temperature = info_number(target.info, "track_temperature")
        convert, symbol = lap_viewer.display_units()["temperature"]
        tolerance = self._similar_tolerance * (1.8 if symbol.endswith("F") else 1.0)
        if best is None:
            self.set_status(trm(f"No other clean lap within ±{number_text(tolerance)}{symbol} of track temperature."))
            return
        self.reference_key = best.file.path
        self.checked = {best.file.path, target.file.path}
        self.fill_list()
        self.load_laps()
        details = []
        if temperature is not None:
            other = info_number(best.info, "track_temperature")
            if other is not None:
                details.append(f"{number_text(convert(other) if convert else other, 1)}{symbol}")
        compound = lap_compound(best.info)
        if compound:
            details.append(compound)
        label = html.escape(lap_label(best.file.filename))
        self.set_status(trm(f"Reference in similar conditions: {label}") + (f" ({', '.join(details)})" if details else ""))

    @Slot(int)
    def setSimilarTolerance(self, degrees: int):
        if degrees in SIMILAR_TOLERANCES and degrees != self._similar_tolerance:
            self._similar_tolerance = degrees
            save_viewer_setting(self.folder, similar_tolerance=degrees)
            self.optionsChanged.emit()

    @Slot(str, str, result=dict)
    def setupDiff(self, key_a: str, key_b: str) -> dict:
        """Setup differences of two shown laps (reference lap first if key_a empty): titles, state, rows"""
        laps = {lap.key: lap for lap in self.data.laps}
        first = laps.get(key_a) or self.data.reference
        second = laps.get(key_b)
        if first is None or second is None or first is second:
            return {}
        entries = {entry.file.path: entry for entry in self.all_entries()}
        info_a = entries[first.key].info if first.key in entries else first.data.meta
        info_b = entries[second.key].info if second.key in entries else second.data.meta
        result = setup_diff(info_a, info_b, first.data, second.data)
        notes = {
            "same": tr("Same setup: same fingerprint of setup values."),
            "different": tr("Different setup: setup values changed between these laps."),
            "unknown": tr("Setup not recorded for one of these laps."),
        }
        for row in result["rows"]:
            row["name"] = tr(row["name"])
        result.update({
            "a": self.short_label(first.key), "b": self.short_label(second.key),
            "colorA": first.color.name(), "colorB": second.color.name(),
            "timeA": format_laptime(official_lap_time(first.data) or first.data.lap_time),  # timed by game
            "timeB": format_laptime(official_lap_time(second.data) or second.data.lap_time),
            "note": notes[result["state"]],
            "values": tr("Setup values are not recorded, only a fingerprint: same or different setup. "
                         "Driver settings below are read from lap samples."),
        })
        return result
