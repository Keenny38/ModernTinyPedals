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
Lap time reference: community LMU lap times by track & class (published Google Sheet)

The sheet lists, for each track & class, the class reference hotlap ("Class avgW"), a race pace
ladder from ~100% (Alien) to 107% (Offline) of it, and the fastest car with its lap time.
Downloaded as CSV, kept in config folder (works offline), matched to driver stats: LMU track
name & vehicle class to sheet track & class.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vTN03UvJDm99byA6vQPZHKOCYVvfxLu1zkJAzdaKyROykzEKY2-"
    "Xl1rl1q5znZEf36m88dxMKsY2eaO/pubhtml#gid=1766901750"
)
SHEET_SOURCE = "ohne_speed"  # sheet author, credited in viewer
SHEET_SOURCE_URL = "https://www.youtube.com/@ohne_speed"
CACHE_NAME = "lap_reference.csv"
SHEET_CLASSES = ("LMH", "LMP2wec", "LMP2elms", "LMP3", "LMGT3", "GTE")
MAX_SIZE = 2 * 1024 * 1024

# Level of each ladder step: ~100%, 101%, 102%, 103%, 104%, 105%, 106%, 107% (and slower)
LEVELS = ("Alien", "Competitive", "Good", "Midpack", "Tail-ender", "Offline")
LADDER_LEVEL = (0, 1, 2, 3, 3, 4, 4, 5)
LEVEL_COLORS = ("#C060FF", "#4C8DFF", "#3FB950", "#D4A72C", "#F0883E", "#8B949E")

# Columns of sheet rows: key, track, patch, class best, ladder x8, fastest car, its lap time, best/avg,
# average, class, cars
COL_TRACK, COL_PATCH, COL_BEST, COL_LADDER, COL_CAR, COL_CAR_TIME, COL_CLASS = 1, 2, 3, 4, 12, 13, 16

# Vehicle class (driver stats key, LMU class name) to sheet class
CLASS_ALIASES = {
    "hyper": "LMH", "hypercar": "LMH", "lmh": "LMH", "lmdh": "LMH",
    "lmp2_elms": "LMP2elms", "lmp2elms": "LMP2elms", "elms_lmp2": "LMP2elms",
    "lmp2": "LMP2wec", "lmp2_wec": "LMP2wec", "lmp2wec": "LMP2wec",
    "lmp3": "LMP3",
    "gt3": "LMGT3", "lmgt3": "LMGT3",
    "gte": "GTE", "lmgte": "GTE", "gte_pro": "GTE", "gte_am": "GTE",
}

# Sheet track: (circuit words, any one), (layout words, all required), (words excluded); first match wins
TRACK_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...] = (
    ("Bahrain (endurance)", ("bahrain", "sakhir"), ("endurance",), ()),
    ("Bahrain (outer)", ("bahrain", "sakhir"), ("outer",), ()),
    ("Bahrain (paddock)", ("bahrain", "sakhir"), ("paddock",), ()),
    ("Bahrain (wec)", ("bahrain", "sakhir"), (), ()),
    ("Barcelona", ("barcelona", "catalunya"), (), ()),
    ("Circuit de la Sarthe (straight)", ("sarthe", "le mans"), ("mulsanne",), ()),
    ("Circuit de la Sarthe (straight)", ("sarthe", "le mans"), ("straight",), ()),
    ("Circuit de la Sarthe", ("sarthe", "le mans"), (), ()),
    ("COTA (national)", ("americas", "cota"), ("national",), ()),
    ("COTA", ("americas", "cota"), (), ()),
    ("Daytona", ("daytona",), (), ()),
    ("Fuji (classic)", ("fuji",), ("classic",), ()),
    ("Fuji (chicane)", ("fuji",), (), ()),
    ("Imola", ("imola", "enzo e dino ferrari"), (), ()),
    ("Interlagos", ("interlagos", "carlos pace"), (), ()),
    ("Laguna Seca", ("laguna seca",), (), ()),
    ("Long Beach", ("long beach",), (), ()),
    ("Monza (curvagrande)", ("monza",), ("curva",), ()),
    ("Monza", ("monza",), (), ()),
    ("Paul Ricard (1A v2 short)", ("ricard",), ("1a", "v2", "short"), ()),
    ("Paul Ricard (1A v2)", ("ricard",), ("1a", "v2"), ()),
    ("Paul Ricard (1A)", ("ricard",), ("1a",), ()),
    ("Paul Ricard (3A)", ("ricard",), ("3a",), ()),
    ("Paul Ricard", ("ricard",), (), ()),
    ("Portimao", ("portimao", "algarve"), (), ()),
    ("Qatar (short)", ("qatar", "lusail"), ("short",), ()),
    ("Qatar", ("qatar", "lusail"), (), ()),
    ("Road Atlanta", ("road atlanta",), (), ()),
    ("Silverstone (National)", ("silverstone",), ("national",), ("international",)),
    ("Silverstone (International)", ("silverstone",), ("international",), ()),
    ("Silverstone (GP)", ("silverstone",), (), ()),
    ("Sebring (school)", ("sebring",), ("school",), ()),
    ("Sebring", ("sebring",), (), ()),
    ("Spa", ("spa",), (), ()),
)


@dataclass(frozen=True)
class LapReference:
    """Reference lap times of a track & class (seconds, 0 when unknown)"""

    track: str
    vehicle_class: str
    patch: str
    class_best: float  # class reference hotlap
    ladder: tuple[float, ...]  # ~100% to 107% race pace steps
    fastest_car: str
    fastest_time: float

    @property
    def reference(self) -> float:
        """Lap time 100% stands for: class reference hotlap, else from first ladder step"""
        return self.class_best or (self.ladder[0] / 1.005 if self.ladder and self.ladder[0] else 0.0)

    def percent(self, laptime: float) -> float:
        """Lap time in percent of reference (0 if unknown)"""
        reference = self.reference
        return laptime / reference * 100 if reference > 0 and laptime > 0 else 0.0

    def level(self, laptime: float) -> int:
        """Level index (LEVELS) of a lap time on the race pace ladder, -1 if unknown"""
        if laptime <= 0 or not self.ladder or not all(self.ladder):
            return -1
        for step, limit in enumerate(self.ladder):
            if laptime <= limit:
                return LADDER_LEVEL[step]
        return LADDER_LEVEL[-1]

    def level_limit(self, level: int) -> float:
        """Slowest lap time of a level (its last ladder step), 0 if unknown or Offline (no limit)"""
        if not 0 <= level < LADDER_LEVEL[-1] or not self.ladder or not all(self.ladder):
            return 0.0
        return max(limit for limit, step_level in zip(self.ladder, LADDER_LEVEL) if step_level == level)

    def next_level(self, laptime: float) -> tuple[int, float]:
        """Next better level of a lap time & time to find (seconds), (-1, 0) if top level or unknown"""
        level = self.level(laptime)
        if level <= 0:
            return -1, 0.0
        limit = self.level_limit(level - 1)
        return (level - 1, laptime - limit) if limit else (-1, 0.0)


@dataclass
class LapReferenceTable:
    """References by (sheet track, sheet class), sheet update date"""

    entries: dict[tuple[str, str], LapReference] = field(default_factory=dict)
    updated: str = ""
    # Sheet tracks & matched sheet track of each track name, computed once (entries set at parse)
    _tracks: set[str] | None = field(default=None, repr=False, compare=False)
    _matches: dict[str, str] = field(default_factory=dict, repr=False, compare=False)

    @property
    def tracks(self) -> set[str]:
        if self._tracks is None:
            self._tracks = {track for track, _ in self.entries}
        return self._tracks

    def sheet_track(self, track_name: str) -> str:
        """Sheet track of an LMU track name (cached), empty if none"""
        track = self._matches.get(track_name)
        if track is None:
            track = self._matches[track_name] = match_track(track_name, self.tracks)
        return track

    def find(self, track_name: str, vehicle_key: str, vehicle_class: str = "") -> LapReference | None:
        """Reference of an LMU track name & driver stats vehicle key (class - brand), None if no match

        Args:
            vehicle_class: game class name, when vehicle key has no class (vehicle name).
        """
        track = self.sheet_track(track_name)
        sheet_class = vehicle_class_of(vehicle_key) or (vehicle_class_of(vehicle_class) if vehicle_class else "")
        if not track or not sheet_class:
            return None
        return self.entries.get((track, sheet_class))


def parse_time(text: str) -> float:
    """Lap time "m:ss.xx" to seconds, 0 if not a lap time"""
    match = re.fullmatch(r"\s*(\d+):(\d{1,2}(?:\.\d+)?)\s*", text or "")
    if not match:
        return 0.0
    seconds = int(match.group(1)) * 60 + float(match.group(2))
    return seconds if seconds > 0 else 0.0


def parse_lap_references(text: str) -> LapReferenceTable:
    """References from sheet CSV text (rows that are not reference rows skipped)"""
    table = LapReferenceTable()
    for row in csv.reader(io.StringIO(text)):
        if not table.updated:
            for cell in row:
                if cell.startswith("Last updated:"):
                    table.updated = cell.removeprefix("Last updated:").strip()
        if len(row) <= COL_CLASS or row[COL_CLASS] not in SHEET_CLASSES or not row[COL_TRACK]:
            continue
        ladder = tuple(parse_time(cell) for cell in row[COL_LADDER:COL_LADDER + 8])
        reference = LapReference(
            track=row[COL_TRACK].strip(),
            vehicle_class=row[COL_CLASS],
            patch=row[COL_PATCH].strip() if row[COL_PATCH].strip() != "N/A" else "",
            class_best=parse_time(row[COL_BEST]),
            ladder=ladder,
            fastest_car=row[COL_CAR].strip(),
            fastest_time=parse_time(row[COL_CAR_TIME]),
        )
        if reference.reference > 0:
            table.entries[(reference.track, reference.vehicle_class)] = reference
    return table


def normalize(text: str) -> str:
    """Lower case, accents & punctuation removed, single spaces"""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def match_track(track_name: str, tracks: set[str] | None = None) -> str:
    """Sheet track of an LMU track name (layout words decide the layout), empty if none"""
    name = f" {normalize(track_name)} "
    for track, circuits, layout, excluded in TRACK_RULES:
        if tracks is not None and track not in tracks:
            continue
        if not any(f" {word} " in name or (" " in word and word in name) for word in circuits):
            continue
        if all(f" {word} " in name for word in layout) and not any(f" {word} " in name for word in excluded):
            return track
    return ""


def vehicle_class_of(vehicle_key: str) -> str:
    """Sheet class of a driver stats vehicle key ("LMP2_ELMS - Oreca", "Hyper", "GT3"), empty if unknown"""
    class_name = vehicle_key.split(" - ", 1)[0].strip().lower().replace(" ", "_").replace("-", "_")
    return CLASS_ALIASES.get(class_name, "")


def csv_url(url: str) -> str:
    """CSV export url of a published Google Sheet url (pubhtml, pub, with or without gid)"""
    parts = urllib.parse.urlsplit(url.strip())
    gid = ""
    for source in (parts.fragment, parts.query):
        found = re.search(r"gid=(\d+)", source)
        if found:
            gid = found.group(1)
            break
    path = re.sub(r"/pubhtml$|/pub$|/edit$|/htmlview$", "", parts.path.rstrip("/"))
    if "/d/e/" in path:
        path += "/pub"
        query = {"output": "csv", "single": "true"} if gid else {"output": "csv"}
    else:
        path += "/export"
        query = {"format": "csv"}
    if gid:
        query["gid"] = gid
    return urllib.parse.urlunsplit(("https", parts.netloc or "docs.google.com", path, urllib.parse.urlencode(query), ""))


def fetch_sheet(url: str, timeout: float = 15) -> str:
    """Download sheet as CSV text (raise OSError or ValueError)"""
    target = csv_url(url)
    if not target.startswith("https://docs.google.com/"):
        raise ValueError("not a Google Sheets url")
    with urllib.request.urlopen(target, timeout=timeout) as response:
        data = response.read(MAX_SIZE + 1)
    if len(data) > MAX_SIZE:
        raise ValueError("sheet too large")
    text = data.decode("utf-8-sig", "replace")
    if not parse_lap_references(text).entries:
        raise ValueError("no lap time reference found in sheet")
    return text


def load_cache(filepath: str) -> tuple[str, float]:
    """Cached sheet CSV text & its time (0 if none)"""
    path = os.path.join(filepath, CACHE_NAME)
    try:
        with open(path, encoding="utf-8") as file:
            return file.read(MAX_SIZE), os.path.getmtime(path)
    except OSError:
        return "", 0.0


def cache_time(filepath: str) -> float:
    """Time of cached sheet (0 if none), without reading it"""
    try:
        return os.path.getmtime(os.path.join(filepath, CACHE_NAME))
    except OSError:
        return 0.0


def save_cache(filepath: str, text: str):
    """Keep sheet CSV text for offline use"""
    from . import atomic_write

    with atomic_write(os.path.join(filepath, CACHE_NAME)) as file:
        file.write(text)
