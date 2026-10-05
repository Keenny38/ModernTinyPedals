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
Driver stats from recorded laps & session history (no Qt): stint pace & tyre degradation by compound, consistency
index, session history export, a friend's exported stats compared track by track

Recorded laps (lap viewer files) give every lap time of a session: stints are laps between pit exit (out lap) &
pit entry (in lap). Clean laps: valid timed laps, not out or in laps, without outliers (traffic, mistakes).
"""

from __future__ import annotations

import csv
import json
import math
import os
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from typing import NamedTuple

from ...userfile.driver_history import SessionRecord, parse_record
from ...userfile.telemetry_lap import group_sessions, lap_files, lap_timestamp_of, read_lap_info

HISTORY_FORMAT = "modern-tiny-pedals-driver-history"  # exported session history (JSON), friend's stats read back
HISTORY_VERSION = 1
OUTLIER_FACTOR = 1.07  # laps slower than fastest of session by this factor left out (traffic, mistakes)
MIN_CLEAN_LAPS = 3  # clean laps needed for a consistency index or a stint pace
MIN_TREND_LAPS = 4  # clean laps of a stint needed for its lap time trend (degradation)
UNKNOWN_COMPOUND = ""  # compound not recorded in lap info
STAT_KEYS = ("pb", "qb", "rb", "meters", "seconds", "valid", "invalid", "races", "wins", "podiums")


class StintLap(NamedTuple):
    """Recorded lap of a session (lap info)"""

    time: float  # lap time, 0 if unknown
    valid: bool
    kind: str  # lap, out, in
    compound: str  # tyre compound, "" if not recorded
    timestamp: float  # lap end
    session: str  # session type name
    session_start: float = 0.0


def lap_compound(info: dict) -> str:
    """Tyre compound of lap info ("" if not recorded): compound name, or front & rear names ("Soft/Medium")"""
    value = info.get("compound", info.get("tyre_compound"))
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        names = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        return "/".join(dict.fromkeys(names))
    return ""


def read_laps(folder: str, keep: Callable[[dict], bool] | None = None,
              cache: dict[str, tuple[float, dict]] | None = None) -> list[list[StintLap]]:
    """Recorded laps of a track & class folder grouped by session (newest session first, laps in driving order)

    Args:
        keep: lap info filter (vehicle of driver stats row), every lap if None.
        cache: lap path: (file time, lap info) kept between calls (only new or changed laps read).
    """
    entries = []
    for lap in lap_files(folder):
        try:
            mtime = os.path.getmtime(lap.path)
        except OSError:
            continue
        cached = cache.get(lap.path) if cache is not None else None
        info = cached[1] if cached is not None and cached[0] == mtime else read_lap_info(lap.path)
        if cache is not None:
            cache[lap.path] = (mtime, info)
        if keep is None or keep(info):
            entries.append((lap, info))
    sessions = []
    for group in group_sessions(entries, lambda entry: entry[0].filename, lambda entry: entry[1]):
        sessions.append([StintLap(
            lap.lap_time, lap.valid, str(info.get("kind", "lap")), lap_compound(info), lap_timestamp_of(lap.filename),
            str(info.get("session", "")),
            float(info["session_start"]) if isinstance(info.get("session_start"), (int, float)) else 0.0,
        ) for lap, info in group])
    return sessions


def clean_times(laps: Sequence[StintLap]) -> list[tuple[int, float]]:
    """Clean laps (position in laps, lap time): valid timed laps, not out or in laps, outliers left out (slower
    than fastest by OUTLIER_FACTOR, or far above the others: traffic, mistakes)"""
    timed = [(index, lap.time) for index, lap in enumerate(laps) if lap.valid and lap.time > 0 and lap.kind == "lap"]
    if len(timed) < MIN_CLEAN_LAPS:
        return timed
    times = sorted(lap_time for _, lap_time in timed)
    quarter, three_quarters = times[len(times) // 4], times[(len(times) * 3) // 4]
    limit = min(three_quarters + 1.5 * (three_quarters - quarter), times[0] * OUTLIER_FACTOR)
    return [(index, lap_time) for index, lap_time in timed if lap_time <= limit + 1e-6]


def variation(times: Sequence[float]) -> float | None:
    """Coefficient of variation of lap times (percent): standard deviation over mean, None under MIN_CLEAN_LAPS"""
    if len(times) < MIN_CLEAN_LAPS:
        return None
    mean = sum(times) / len(times)
    if mean <= 0:
        return None
    deviation = math.sqrt(sum((value - mean) ** 2 for value in times) / (len(times) - 1))
    return deviation / mean * 100


def trend(points: Sequence[tuple[float, float]]) -> float:
    """Slope of line fitting points (least squares), 0 if x does not vary"""
    count = len(points)
    if count < 2:
        return 0.0
    mean_x = sum(x for x, _ in points) / count
    mean_y = sum(y for _, y in points) / count
    spread = sum((x - mean_x) ** 2 for x, _ in points)
    if spread <= 0:
        return 0.0
    return sum((x - mean_x) * (y - mean_y) for x, y in points) / spread


def split_stints(laps: Sequence[StintLap]) -> list[list[StintLap]]:
    """Laps of a session split in stints: a stint starts with an out lap, ends with an in lap"""
    stints: list[list[StintLap]] = []
    current: list[StintLap] = []
    for lap in laps:
        if lap.kind == "out" and current:
            stints.append(current)
            current = []
        current.append(lap)
        if lap.kind == "in":
            stints.append(current)
            current = []
    if current:
        stints.append(current)
    return stints


def stint_summary(laps: Sequence[StintLap]) -> dict | None:
    """Stint pace (mean clean lap time), degradation (lap time trend, seconds per lap, MIN_TREND_LAPS clean laps
    or more), compound (most laps), lap counts, start time; None under MIN_CLEAN_LAPS clean laps"""
    clean = clean_times(laps)
    if len(clean) < MIN_CLEAN_LAPS:
        return None
    compounds = Counter(lap.compound for lap in laps if lap.compound)
    return {
        "compound": compounds.most_common(1)[0][0] if compounds else UNKNOWN_COMPOUND,
        "laps": len(laps), "clean": len(clean),
        "pace": sum(lap_time for _, lap_time in clean) / len(clean),
        "slope": trend([(float(index), lap_time) for index, lap_time in clean]) if len(clean) >= MIN_TREND_LAPS
        else None,
        "start": next((lap.timestamp - lap.time for lap in laps if lap.timestamp > 0), 0.0),
        "session": laps[0].session if laps else "",
    }


def compound_summary(stints: Iterable[dict]) -> list[dict]:
    """Stints grouped by compound: stints, clean laps, pace & degradation weighted by clean laps, fastest pace
    first"""
    groups: dict[str, list[dict]] = {}
    for stint in stints:
        groups.setdefault(stint["compound"], []).append(stint)
    rows = []
    for compound, items in groups.items():
        laps = sum(item["clean"] for item in items)
        trended = [item for item in items if item["slope"] is not None]
        trended_laps = sum(item["clean"] for item in trended)
        rows.append({
            "compound": compound, "stints": len(items), "laps": laps,
            "pace": sum(item["pace"] * item["clean"] for item in items) / laps,
            "slope": sum(item["slope"] * item["clean"] for item in trended) / trended_laps if trended_laps else None,
        })
    rows.sort(key=lambda row: row["pace"])
    return rows


def session_consistency(sessions: Iterable[Sequence[StintLap]]) -> list[dict]:
    """Consistency of each session with enough clean laps (newest first): start time, session, clean laps,
    coefficient of variation (percent), pace"""
    rows = []
    for laps in sessions:
        clean = [lap_time for _, lap_time in clean_times(laps)]
        index = variation(clean)
        if index is None:
            continue
        start = laps[0].session_start or next((lap.timestamp - lap.time for lap in laps if lap.timestamp > 0), 0.0)
        rows.append({"start": start, "session": laps[0].session, "clean": len(clean), "index": index,
                     "pace": sum(clean) / len(clean)})
    return rows


def track_consistency(rows: Sequence[dict]) -> float | None:
    """Consistency index of a track: median of session coefficients of variation, None if no session"""
    values = sorted(row["index"] for row in rows)
    if not values:
        return None
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


def stint_report(sessions: Sequence[Sequence[StintLap]]) -> dict:
    """Stints (newest first), compounds & consistency of recorded sessions"""
    stints = [summary for laps in sessions for stint in split_stints(laps)
              if (summary := stint_summary(stint)) is not None]
    consistency = session_consistency(sessions)
    return {"stints": stints, "compounds": compound_summary(stints), "sessions": consistency,
            "index": track_consistency(consistency)}


# Session history export & a friend's exported stats
def history_rows(records: Iterable[SessionRecord]) -> list[dict]:
    """Session records as plain values, oldest first"""
    return [record._asdict() for record in sorted(records, key=lambda record: record.time)]


def history_document(records: Iterable[SessionRecord], stats: dict, classes: dict[str, str], driver: str = "") -> dict:
    """Exported session history (JSON): format, records, best lap times & totals of each track & vehicle"""
    rows = history_rows(records)
    tracks = sorted({row["track"] for row in rows} | set(stats))
    best = {}
    for track in tracks:
        vehicles = stats.get(track, {})
        if not isinstance(vehicles, dict):
            continue
        best[track] = {
            vehicle: {key: values[key] for key in STAT_KEYS if isinstance(values.get(key), (int, float))}
            for vehicle, values in vehicles.items() if isinstance(values, dict)
        }
    return {"format": HISTORY_FORMAT, "version": HISTORY_VERSION, "exported": round(time.time()), "driver": driver,
            "classes": dict(classes), "stats": best, "sessions": rows}


def write_history_json(filename: str, document: dict):
    """Write exported session history, raises OSError"""
    with open(filename, "w", encoding="utf-8") as file:
        json.dump(document, file, ensure_ascii=False, indent=1)


def write_history_csv(filename: str, records: Iterable[SessionRecord], header: Sequence[str], session_names:
                      Sequence[str], decimal: str = "."):
    """Write session history as CSV (decimal comma: semicolon separator, for Excel), raises OSError"""
    delimiter = ";" if decimal == "," else ","

    def number(value: float, digits: int) -> str:
        text = f"{value:.{digits}f}"
        return text.replace(".", decimal) if decimal != "." else text

    with open(filename, "w", newline="", encoding="utf-8-sig") as file:  # BOM: Excel reads UTF-8
        writer = csv.writer(file, delimiter=delimiter)
        writer.writerow(header)
        for record in sorted(records, key=lambda item: item.time):
            writer.writerow([
                time.strftime("%Y-%m-%d %H:%M", time.localtime(record.time)), record.track, record.vehicle,
                record.vehicle_class,
                session_names[record.session] if 0 <= record.session < len(session_names) else str(record.session),
                number(record.best, 3) if record.best > 0 else "", record.valid, record.invalid,
                number(record.meters, 0), number(record.seconds, 0), record.position or "", record.finish,
            ])


def load_friend(filename: str) -> dict:
    """Friend's exported session history (JSON of history_document), raises ValueError if not one"""
    try:
        with open(filename, encoding="utf-8") as file:
            document = json.load(file)
    except (OSError, ValueError) as error:
        raise ValueError(str(error)) from error
    if not isinstance(document, dict) or document.get("format") != HISTORY_FORMAT:
        raise ValueError("not an exported session history")
    stats = document.get("stats")
    classes = document.get("classes")
    rows = document.get("sessions")
    stats = stats if isinstance(stats, dict) else {}
    classes = classes if isinstance(classes, dict) else {}
    sessions = [record for record in (parse_record(row) for row in (rows if isinstance(rows, list) else []))
                if record is not None]
    name = str(document.get("driver") or "") or os.path.splitext(os.path.basename(filename))[0]
    return {"name": name, "stats": stats, "classes": {str(key): str(value) for key, value in classes.items()},
            "sessions": sessions}


def best_by_class(stats: dict, track: str, class_of: Callable[[str], str]) -> dict[str, float]:
    """Fastest personal best of each vehicle class on track"""
    best: dict[str, float] = {}
    vehicles = stats.get(track, {})
    if not isinstance(vehicles, dict):
        return best
    for vehicle, values in vehicles.items():
        laptime = values.get("pb") if isinstance(values, dict) else None
        if not isinstance(laptime, (int, float)) or isinstance(laptime, bool) or not 0 < laptime < 86400:
            continue
        vehicle_class = class_of(str(vehicle)) or str(vehicle)
        if laptime < best.get(vehicle_class, math.inf):
            best[vehicle_class] = float(laptime)
    return best


def compare_friend(mine: dict, mine_class: Callable[[str], str], friend: dict, tracks: Iterable[str] | None = None,
                   ) -> list[dict]:
    """Personal bests against friend's on same track & vehicle class: track, class, mine, friend's, gap (mine minus
    friend's, 0 when one is missing); every track both drove if tracks is None"""
    friend_stats = friend.get("stats", {})
    friend_classes = friend.get("classes", {})

    def friend_class(vehicle: str) -> str:
        return friend_classes.get(vehicle) or vehicle.split(" - ", 1)[0].strip()

    names = sorted(set(mine) & set(friend_stats), key=str.lower) if tracks is None else list(tracks)
    rows = []
    for track in names:
        own, theirs = best_by_class(mine, track, mine_class), best_by_class(friend_stats, track, friend_class)
        for vehicle_class in sorted(set(own) | set(theirs), key=str.lower):
            first, second = own.get(vehicle_class, 0.0), theirs.get(vehicle_class, 0.0)
            if tracks is None and not (first and second):
                continue
            rows.append({"track": track, "class": vehicle_class, "mine": first, "friend": second,
                         "gap": first - second if first and second else 0.0})
    return rows
