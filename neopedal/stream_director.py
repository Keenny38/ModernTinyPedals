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
Broadcast graphics of the Broadcast Director page, as a browser source of the stream overlay server

The page (ui/quick/director_graphics) publishes what is on air (car, story, battle, race events, standings,
clock, weather, instant replay...) to DirectorFeed; the source (/director, transparent 1920x1080 page) asks
/api/director again and again, each answer as soon as something changed (long poll), and draws TV graphics:
standings tower, driver card on each cut, battle card & battle train, banners (fastest lap, penalty, flags,
lead change, heavy contact), replay graphics, session clock & weather, onboard, qualifying lap, track map,
and on demand starting grid, event card, classification & championship standings.

Onboard & track map positions change many times a second: second feed (live_feed, /api/director/live). Track
outline asked once per track (/api/director/track). Places of graphics moved in the layout editor
(/director?edit=1, demo data) kept in director_layout (config file), sent with every answer.
No Qt: server threads read, page thread writes.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from collections.abc import Iterable
from html import escape
from typing import Any

from .template.setting_compounds import COMPOUND_SYMBOLS, letter_color
from .template.setting_status_colors import ENERGY_LOW, ENERGY_MEDIUM, status_css

logger = logging.getLogger(__name__)

WAIT_SECONDS = 1.0  # request waits this long for a change
WATCH_SECONDS = 5.0  # source counted as shown this long after its last request
# Graphics placed by the layout editor (element ids of the page)
GRAPHIC_IDS = ("tower", "card", "battle", "train", "banners", "pitradar", "replay", "clock", "onboard", "quali", "map",
               "grid", "event", "results", "champ", "message", "countdown", "logo", "sponsors")
LAYOUT_PRESETS = ("", "pre", "race", "post")  # layouts of the editor: default, pre-race, race, post-race
SCALE_LIMITS = (0.3, 3.0)  # size factor of a placed graphic
PLACE_LIMITS = (-0.5, 1.5)  # place of a graphic (fractions of the canvas), a little outside allowed
MAX_LAYOUT_BODY = 64 * 1024  # bytes: layout sent by an editor
BRAND_FOLDER = "broadcast_branding"  # config folder: league logo & sponsors pictures (sponsors subfolder)
BRAND_FILE = re.compile(r"^(sponsors/)?[A-Za-z0-9 ._()-]{1,96}\.(png|jpg|jpeg|webp|svg)$", re.I)
BRAND_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
               "svg": "image/svg+xml"}
MAX_SPONSORS = 24


class DirectorFeed:
    """Last state published by the Broadcast Director page, numbered: sources wait for the next one"""

    def __init__(self):
        self._condition = threading.Condition()
        self._version = 0
        self._body = b"{}"
        self._asked = 0.0  # monotonic time of last request

    def publish(self, data: dict[str, Any]):
        """New state (page thread): waiting sources answered at once"""
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with self._condition:
            if body == self._body:
                return
            self._version += 1
            self._body = body
            self._condition.notify_all()

    def bump(self):
        """Same state, new version (layout changed): waiting sources answered at once"""
        with self._condition:
            self._version += 1
            self._condition.notify_all()

    def clear(self):
        self.publish({})

    def wait(self, after: int, timeout: float = WAIT_SECONDS) -> tuple[int, bytes]:
        """State newer than version after (server thread), or the same one once timeout passed"""
        with self._condition:
            self._asked = time.monotonic()
            if self._version <= after:
                self._condition.wait(timeout)
            return self._version, self._body

    def watched(self) -> bool:
        """A source asked lately (state worth making)"""
        return time.monotonic() - self._asked < WATCH_SECONDS

    @property
    def version(self) -> int:
        return self._version


class SectionFeed(DirectorFeed):
    """State made of sections (tower, onAir, map...): a source gets only the sections changed since the version
    it has (all of them on its first request)"""

    def __init__(self):
        super().__init__()
        self._sections: dict[str, bytes] = {}
        self._changed: dict[str, int] = {}  # section: version it last changed

    def publish(self, data: dict[str, Any]):
        encoded = {key: json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                   for key, value in data.items()}
        with self._condition:
            changed = [key for key, body in encoded.items() if self._sections.get(key) != body]
            gone = [key for key, body in self._sections.items() if key not in encoded and body != b"null"]
            if not changed and not gone:
                return
            self._version += 1
            for key in changed:
                self._sections[key] = encoded[key]
                self._changed[key] = self._version
            for key in gone:
                self._sections[key] = b"null"
                self._changed[key] = self._version
            self._condition.notify_all()

    def sections(self, after: int, timeout: float = WAIT_SECONDS) -> tuple[int, dict[str, bytes], bool]:
        """Sections changed after version "after" (all of them if 0 or unknown), waits for a change up to timeout:
        version, sections, whether all sections"""
        with self._condition:
            self._asked = time.monotonic()
            if after > self._version:  # page opened again (versions from 0): everything
                after = 0
            if 0 < after == self._version:
                self._condition.wait(timeout)
            if after <= 0:
                return self._version, dict(self._sections), True
            return self._version, {key: self._sections[key] for key, version in self._changed.items()
                                   if version > after}, False

    def wait(self, after: int, timeout: float = WAIT_SECONDS) -> tuple[int, bytes]:
        version, sections, _ = self.sections(after, timeout)
        return version, sections_json(sections)

    @property
    def state(self) -> dict[str, Any]:
        """Every section (tests)"""
        with self._condition:
            return {key: json.loads(body) for key, body in self._sections.items()}


def sections_json(sections: dict[str, bytes]) -> bytes:
    return b"{" + b",".join(json.dumps(key).encode("utf-8") + b":" + body for key, body in sections.items()) + b"}"


def clean_placements(data: Any, names: Iterable[str] | None = None,
                     pattern: re.Pattern | None = None) -> dict[str, list[float]]:
    """Places sent by a layout editor (untrusted): name: [x, y, scale], x & y fractions of the canvas, known
    names only, values brought into limits, wrong entries left out"""
    result: dict[str, list[float]] = {}
    if not isinstance(data, dict):
        return result
    allowed = set(names) if names is not None else None
    for name, value in data.items():
        if not isinstance(name, str) or (allowed is not None and name not in allowed) or (
                pattern is not None and not pattern.match(name)):
            continue
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            continue
        try:
            x, y, scale = (float(item) for item in value)
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(item) for item in (x, y, scale)):
            continue
        low, high = PLACE_LIMITS
        result[name] = [round(min(max(x, low), high), 5), round(min(max(y, low), high), 5),
                        round(min(max(scale, SCALE_LIMITS[0]), SCALE_LIMITS[1]), 3)]
    return result


class PlacementStore:
    """Places saved by a layout editor (browser), by section, kept in a config file (any thread)

    Args:
        filename: file name in config folder.
        names: names allowed (graphic ids), None: any name matching pattern.
        pattern: names allowed (overlay names), None: any.
        sections: sections allowed (layout presets), None: any.
    """

    ACTIVE = "__active__"  # file key of the section in use

    def __init__(self, filename: str, names: Iterable[str] | None = None, pattern: re.Pattern | None = None,
                 sections: Iterable[str] | None = None):
        self.filename = filename
        self._names = tuple(names) if names is not None else None
        self._pattern = pattern
        self._sections = tuple(sections) if sections is not None else None
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, list[float]]] | None = None
        self._active = ""
        self._folder = ""
        self.version = 0

    @staticmethod
    def folder() -> str:
        from .setting import cfg

        return cfg.path.config

    def _load(self) -> dict[str, dict[str, list[float]]]:
        folder = self.folder()
        if self._data is None or folder != self._folder:  # first use, or another config folder
            self._folder = folder
            try:
                with open(os.path.join(folder, self.filename), encoding="utf-8") as file:
                    raw = json.load(file)
            except (OSError, ValueError):
                raw = {}
            if not isinstance(raw, dict):
                raw = {}
            active = raw.get(self.ACTIVE)
            self._active = active if isinstance(active, str) and self.allowed(active) else ""
            self._data = {str(section): clean_placements(value, self._names, self._pattern)
                          for section, value in raw.items() if section != self.ACTIVE and self.allowed(str(section))}
        return self._data

    def allowed(self, section: str) -> bool:
        return self._sections is None or section in self._sections

    def get(self, section: str | None = None) -> dict[str, list[float]]:
        """Places of a section (None: section in use)"""
        with self._lock:
            data = self._load()
            return dict(data.get(self._active if section is None else section, {}))

    def active(self) -> str:
        with self._lock:
            self._load()
            return self._active

    def set_active(self, section: str) -> bool:
        """Section used by sources (layout preset), saved; False if unknown"""
        if not self.allowed(section):
            return False
        with self._lock:
            self._load()
            if section == self._active:
                return True
            self._active = section
            self.version += 1
            self._save()
        return True

    def set(self, section: str, placements: Any) -> dict[str, list[float]]:
        """Places of section replaced (empty: section reset to default places), saved, returns places kept"""
        if not self.allowed(section):
            return {}
        cleaned = clean_placements(placements, self._names, self._pattern)
        with self._lock:
            data = self._load()
            if cleaned:
                data[section] = cleaned
            else:
                data.pop(section, None)
            self.version += 1
            self._save()
        return cleaned

    def _save(self):
        from .userfile import atomic_write

        data: dict[str, Any] = dict(self._data or {})
        if self._active:
            data[self.ACTIVE] = self._active
        try:
            with atomic_write(os.path.join(self._folder, self.filename)) as file:
                file.write(json.dumps(data, indent=1))
        except OSError as error:
            logger.warning("STREAM OVERLAY: layout not saved: %s", error)


class TrackOutline:
    """Track outline of the session (racing line & pit lane, world coordinates) for the track map graphic"""

    def __init__(self):
        self._lock = threading.Lock()
        self.key = ""
        self._body = b'{"key":""}'

    def set(self, key: str, racing: list[tuple[float, float]], pit: list[tuple[float, float]]):
        points = racing + pit
        if not points:
            body = b'{"key":""}'
        else:
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            body = json.dumps({
                "key": key, "minX": round(min(xs), 1), "minY": round(min(ys), 1),
                "width": round(max(max(xs) - min(xs), 1.0), 1), "height": round(max(max(ys) - min(ys), 1.0), 1),
                "points": [[round(x, 1), round(y, 1)] for x, y in racing],
                "pit": [[round(x, 1), round(y, 1)] for x, y in pit],
            }, separators=(",", ":")).encode("utf-8")
        with self._lock:
            self.key = key
            self._body = body

    def body(self) -> bytes:
        with self._lock:
            return self._body


director_feed = SectionFeed()
live_feed = DirectorFeed()  # onboard & car positions, several times a second
director_layout = PlacementStore("broadcast_layout.json", GRAPHIC_IDS, sections=LAYOUT_PRESETS)
track_outline = TrackOutline()


def preset_of(query: str | None) -> str | None:
    """Layout preset asked by a source (preset=race), None: preset in use"""
    return query if query in LAYOUT_PRESETS else None


def layout_json(preset: str | None = None) -> bytes:
    return json.dumps(director_layout.get(preset), separators=(",", ":")).encode("utf-8")


def answer(after: int, preset: str | None = None) -> bytes:
    """Answer of /api/director: version, layout, sections of state changed since version "after" ("full": every
    section)"""
    version, sections, full = director_feed.sections(after)
    return (b'{"v":' + str(version).encode("ascii") + b',"full":' + (b"true" if full else b"false")
            + b',"preset":' + json.dumps(director_layout.active()).encode("utf-8")
            + b',"layout":' + layout_json(preset) + b',"state":' + sections_json(sections) + b"}")


def answer_live(after: int) -> bytes:
    """Answer of /api/director/live: version & onboard, car positions"""
    version, body = live_feed.wait(after)
    return b'{"v":' + str(version).encode("ascii") + b',"live":' + body + b"}"


def demo_answer(preset: str | None = None) -> bytes:
    """Answer of /api/director?demo=1 (layout editor): every graphic shown with sample data"""
    data = json.dumps(demo_state(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    chosen = preset if preset is not None else director_layout.active()
    return (b'{"v":1,"full":true,"preset":' + json.dumps(chosen).encode("utf-8") + b',"layout":'
            + layout_json(chosen) + b',"state":' + data + b"}")


def save_layout(body: bytes, preset: str | None = None) -> dict[str, list[float]]:
    """Layout sent by the editor (POST body JSON) for a preset (None: preset in use), sources told at once"""
    chosen = preset if preset is not None else director_layout.active()
    placements = director_layout.set(chosen, json.loads(body.decode("utf-8")) if body.strip() else {})
    director_feed.bump()
    return placements


# League branding: logo & sponsors pictures in config folder
def brand_folder() -> str:
    from .setting import cfg

    return os.path.join(cfg.path.config, BRAND_FOLDER)


def brand_file(name: str) -> str:
    """File of a branding picture address part (logo.png, sponsors/<name>), "" if invalid or missing"""
    from urllib.parse import unquote

    name = unquote(name)
    if not BRAND_FILE.match(name) or ".." in name:
        return ""
    base = os.path.abspath(brand_folder())
    path = os.path.abspath(os.path.join(base, *name.split("/")))
    if not path.startswith(base + os.sep) or not os.path.isfile(path):
        return ""
    return path


def brand_pictures() -> tuple[str, list[str]]:
    """League logo & sponsors pictures (addresses on the stream server, with file time: changed file asked again)"""
    from urllib.parse import quote

    folder = brand_folder()
    logo = ""
    try:
        for entry in sorted(os.scandir(folder), key=lambda item: item.name):
            if entry.is_file() and entry.name.lower().startswith("logo.") and BRAND_FILE.match(entry.name):
                logo = f"/api/director/brand/{quote(entry.name)}?t={int(entry.stat().st_mtime)}"
                break
    except OSError:
        pass
    sponsors = []
    try:
        for entry in sorted(os.scandir(os.path.join(folder, "sponsors")), key=lambda item: item.name.casefold()):
            name = f"sponsors/{entry.name}"
            if entry.is_file() and BRAND_FILE.match(name):
                sponsors.append(f"/api/director/brand/{quote(name)}?t={int(entry.stat().st_mtime)}")
            if len(sponsors) >= MAX_SPONSORS:
                break
    except OSError:
        pass
    return logo, sponsors


def brand_type(path: str) -> str:
    return BRAND_TYPES[path.rsplit(".", 1)[-1].lower()]


def demo_state() -> dict[str, Any]:
    """Sample state showing every graphic (layout editor), texts in app language"""
    from .i18n import tr

    colors = ("#E5484D", "#3E8EF7", "#30A46C")
    classes = ("Hypercar", "LMP2", "LMGT3")
    names = ("A. Martin", "L. Hartmann", "K. Sato", "M. Rossi", "J. Novak", "E. Dubois", "T. Becker", "S. Lindqvist",
             "R. Costa", "P. Walsh", "N. Ivanova", "D. Okafor")
    tower = []
    for index, name in enumerate(names):
        cls = index // 4
        tower.append({
            "pos": index + 1, "classPos": index % 4 + 1, "cls": classes[cls], "color": colors[cls],
            "number": str(7 + index * 3), "name": name, "gap": f"+{0.4 + index * 1.7:.1f}" if index else "",
            "gapClass": f"+{0.4 + index % 4 * 1.3:.1f}" if index % 4 else "",
            "gapLeader": f"+{index * 4.1:.1f}" if index else "",
            "gapClassLeader": f"+{index % 4 * 3.2:.1f}" if index % 4 else "", "close": index == 2,
            "pit": index == 9, "air": index == 2, "change": (1, 0, 2, -1, 0, 0, -2, 1, 0, 0, 0, 0)[index],
            "lap": "1:35.418" if index == 4 else "", "lapId": 1, "lapTone": "fastest" if index == 4 else "",
            "tyres": ["M"] if index % 3 else ["S", "M"], "pen": 1 if index == 7 else 0,
            "fastest": index in (1, 4, 9), "stops": 2 if index % 2 else 1,
        })
    car = {"number": "13", "name": "Kenji Sato", "team": "Vortex Racing", "cls": "Hypercar", "color": colors[0],
           "classPos": 3, "logo": "", "picture": "",
           "stats": [[tr("Best"), "1:34.902"], [tr("Last"), "1:35.211"], [tr("Laps"), "42"], [tr("Places"), "+2"], ["DR", "S2"], ["SR", "P3"]],
           "story": tr("Battle for P%1").replace("%1", "2"), "storyTone": "accent"}
    side = {"number": "10", "name": "L. Hartmann", "team": "Apex Motorsport"}
    other = {"number": "13", "name": "K. Sato", "team": "Vortex Racing"}
    train = [{"number": str(7 + index * 3), "name": names[index], "classPos": index + 1,
              "gap": "" if index == 0 else f"+{0.3 + index * 0.2:.1f}", "air": index == 2, "color": colors[0]}
             for index in range(5)]
    grid = [{"pos": index + 1, "number": tower[index]["number"], "name": names[index], "team": "Vortex Racing",
             "cls": tower[index]["cls"], "color": tower[index]["color"], "time": f"1:3{3 + index // 4}.{412 + index * 37}",
             "picture": ""} for index in range(8)]
    rows = [{"pos": row["pos"], "classPos": row["classPos"], "cls": row["cls"], "color": row["color"],
             "number": row["number"], "name": row["name"], "team": "Vortex Racing", "laps": 42 - index // 4,
             "gap": row["gap"] or tr("Leader"), "best": f"1:3{4 + index // 4}.{100 + index * 41}", "pits": 2,
             "status": tr("Retired") if index == 11 else ""} for index, row in enumerate(tower)]
    champ = [{"pos": index + 1, "name": names[index], "team": "Vortex Racing", "cls": "Hypercar", "color": colors[0],
              "points": 120 - index * 14, "medal": index + 1 if index < 3 else 0} for index in range(8)]
    return {
        "live": True, "demo": True, "cut": 1, "tower": tower, "onAir": car, "events": [],
        "graphics": {"tower": True, "towerMode": "all", "towerRows": 12, "towerCycle": 10, "card": True,
                     "cardSeconds": 0, "cardPicture": False, "battle": True, "train": True, "banners": True,
                     "bannerSeconds": 6, "replay": True, "clock": True, "hidden": False, "pitRadar": True,
                     "onboard": True, "onboardStyle": "dash", "quali": True, "map": True, "towerLaps": True,
                     "towerTyres": True, "towerPenalties": True, "towerFastest": True, "towerStops": True,
                     "towerGap": "interval", "towerGroup": False, "opacity": 92, "pageSeconds": 10,
                     "resultsRows": 10, "gridSeconds": 8, "replayGraphics": True, "mapRotation": 0, "mapDots": 100,
                     "accent": "#e5383b", "logo": True, "sponsors": True, "sponsorSeconds": 8},
        "battle": {"title": f"{tr('Battle for P%1').replace('%1', '2')} · Hypercar", "color": colors[0],
                   "gap": "0.4 s", "trend": tr("%1/lap").replace("%1", "-0.1 s"), "trendClass": "closing",
                   "ahead": side, "behind": other},
        "train": {"title": f"{tr('Battle for P%1').replace('%1', '1')} · Hypercar", "color": colors[0], "cars": train},
        "replay": True, "replayInfo": None,
        "clock": {"text": "2:41:07", "label": tr("Remaining")}, "flag": "",
        "weather": [tr("Air %1").replace("%1", "24°C"), tr("Track %1").replace("%1", "33°C")],
        "pitRadar": {"title": tr("Pit lane"), "count": tr("%1 cars approaching").replace("%1", "1"),
                     "rows": [{"number": "22", "name": "J. Novak", "color": colors[1], "distance": "38 m",
                               "alongside": False, "ahead": True},
                              {"number": "31", "name": "T. Becker", "color": colors[2], "distance": "",
                               "alongside": True, "ahead": False}]},
        "onboard": {"number": "13", "name": "K. Sato", "color": colors[0], "cls": "Hypercar", "rpmMax": 9000,
                    "ahead": "#10 +0.4"},
        "quali": {"number": "13", "name": "K. Sato", "color": colors[0], "position": "P3", "lapStart": 0.0,
                  "now": 61.4, "running": True, "best": "1:34.902", "target": "1:34.511", "targetLabel": tr("Pole"),
                  "delta": "-0.124", "deltaTone": "gain", "status": tr("Improving"),
                  "sectors": [{"text": "31.204", "tone": "fastest"}, {"text": "30.019", "tone": "gain"},
                              {"text": "-", "tone": ""}]},
        "map": {"track": "", "yellow": -1, "cars": {}, "sectors": [0.3, 0.65], "yellowSectors": [False, True, False]},
        "grid": {"title": tr("Starting Grid"), "cars": grid},
        "event": {"track": "Circuit de la Sarthe", "logo": "", "session": tr("Race"),
                  "conditions": [tr("Air %1").replace("%1", "24°C"), tr("Track %1").replace("%1", "33°C")],
                  "forecast": [{"label": tr("Start"), "sky": "Clear", "temperature": "24°C", "rain": "0%", "wet": False},
                               {"label": "50%", "sky": "Light clouds", "temperature": "26°C", "rain": "10%",
                                "wet": False},
                               {"label": tr("Finish"), "sky": "Rain", "temperature": "21°C", "rain": "60%",
                                "wet": True}],
                  "schedule": [[tr("Session length"), "6:00:00"], [tr("Remaining"), "2:41:07"]]},
        "results": {"title": tr("Classification"), "subtitle": tr("Lap %1").replace("%1", "42"), "rows": rows},
        "champ": {"title": "Endurance Cup", "subtitle": "Hypercar", "rows": champ},
        "message": {"id": 1, "title": tr("Race control"), "text": tr("Red flag: restart in 10 minutes")},
        "countdown": {"label": tr("Race starts in"), "endsAt": 0, "seconds": 299},
        "brand": {"name": "Endurance Cup · Round 3", "logo": "", "sponsors": [],
                  "names": ["Sponsor A", "Sponsor B", "Sponsor C"]},
        "labels": demo_labels(),
    }


def demo_labels() -> dict[str, Any]:
    from .i18n import tr

    return labels(tr)


def labels(tr) -> dict[str, Any]:
    """Texts of the graphics page in app language"""
    from .i18n import tr_overlay

    return {
        "overall": tr("Overall"), "pit": tr("Pit").upper(), "replay": tr("Replay").upper(),
        "garage": tr_overlay("GAR"), "dnf": tr_overlay("DNF"), "dq": tr_overlay("DQ"),  # tower status, as overlays
        "alongside": tr("Alongside").upper(), "pen": tr("PEN"), "laps": tr("Laps"), "gap": tr("Gap"),
        "best": tr("Best"), "pits": tr("Pit Stops"), "points": tr("Points"), "lap": tr("Lap"), "gear": tr("Gear"),
        "throttle": tr("Throttle"), "brake": tr("Brake"), "energy": tr("Energy"), "fastestTag": tr("FL"),
        "save": tr("Save"), "reset": tr("Reset"), "resetAll": tr("Reset All"), "saved": tr("Layout saved"),
        "undo": tr("Undo"), "preset": tr("Layout"),
        "editHint": tr("Drag a graphic to move it, mouse wheel to resize it, double click: back to its place.") + "  "
        + tr("Arrows: move by one pixel, Ctrl+Z: undo, H: hide these bars"),
        "notSaved": tr("Layout not saved"), "neutral": "N", "reverse": "R",
        "presets": {"": tr("Default"), "pre": tr("Pre-race"), "race": tr("Race"), "post": tr("Post-race")},
        "names": {
            "tower": tr("Standings tower"), "card": tr("Driver Card"), "battle": tr("Battle"),
            "train": tr("Battle train"), "banners": tr("Banners"), "pitradar": tr("Pit radar"), "replay": tr("Replay"),
            "clock": tr("Session clock & weather"), "onboard": tr("Onboard"), "quali": tr("Qualifying"),
            "map": tr("Track Map"), "grid": tr("Starting Grid"), "event": tr("Event card"),
            "results": tr("Classification"), "champ": tr("Championship"), "message": tr("Message"),
            "countdown": tr("Countdown"), "logo": tr("League logo"), "sponsors": tr("Sponsors"),
        },
    }


def tyre_badges() -> dict[str, tuple[str, str]]:
    """Compound badge of each letter, as in overlays: (fill, readable letter color)"""
    badges = {}
    for letter in COMPOUND_SYMBOLS:
        fill = letter_color(letter)
        red, green, blue = (int(fill[index:index + 2], 16) / 255 for index in (1, 3, 5))
        light = 0.2126 * red + 0.7152 * green + 0.0722 * blue > 0.55
        badges[letter.upper()] = (fill, "#0E1116" if light else "#F4F6F9")
    return badges


def director_html(language: str, title: str) -> str:
    return (DIRECTOR_HTML.replace("@@lang@@", escape(language)).replace("@@title@@", escape(title))
            .replace("@@tyres@@", json.dumps(tyre_badges())).replace("@@status@@", status_css())
            .replace("@@energyLow@@", str(ENERGY_LOW)).replace("@@energyMedium@@", str(ENERGY_MEDIUM)))


# Transparent 16:9 page, sized from the page height (vh): 1920x1080 browser source in OBS, Streamlabs, vMix...
# Query: animate=0 (no animation), once=1 (asked once: screenshots), scale=<factor>, only=<ids> (these graphics
# only, e.g. only=tower,map: graphics split over several sources), preset=<pre|race|post> (layout preset of this
# source, else the one in use), edit=1 (layout editor: sample data, drag graphics to move them, wheel to resize,
# saved for every source)
DIRECTOR_HTML = """<!doctype html><html lang="@@lang@@"><head><meta charset="utf-8"><title>@@title@@</title>
<style>
@font-face{font-family:"Barlow Semi Condensed";font-weight:500;src:url(/fonts/BarlowSemiCondensed-Medium.ttf)}
@font-face{font-family:"Barlow Semi Condensed";font-weight:600;src:url(/fonts/BarlowSemiCondensed-SemiBold.ttf)}
@font-face{font-family:"Barlow Semi Condensed";font-weight:700;src:url(/fonts/BarlowSemiCondensed-Bold.ttf)}
:root{--u:1vh;--op:.92;--panel:rgba(11,13,19,var(--op));--panel2:rgba(22,25,34,var(--op));--line:rgba(255,255,255,.08);
--text:#f5f7fb;--dim:rgba(230,235,244,.64);--accent:#e5383b;@@status@@
--blue:#60a5fa;--ar:229,56,59;--ease:cubic-bezier(.2,.8,.2,1)}
*{box-sizing:border-box}
html,body{margin:0;height:100%;overflow:hidden;background:transparent}
body{font-family:"Barlow Semi Condensed","Segoe UI",sans-serif;color:var(--text);font-weight:500;
font-variant-numeric:tabular-nums;font-size:calc(var(--u)*2)}
.panel{background:var(--panel);border-radius:calc(var(--u)*.9);box-shadow:0 calc(var(--u)*1) calc(var(--u)*3.4) rgba(0,0,0,.45);overflow:hidden}
.g{position:absolute}
.g.off{display:none!important}
.show{opacity:1!important;transform:none!important}
.still *{transition:none!important;animation:none!important}
.hidden-all>.g{opacity:0!important}
.accentbg{background:linear-gradient(90deg,var(--accent),rgba(var(--ar),.35) 70%,rgba(var(--ar),0))}
/* Tower: rows placed by translateY (moves animated) */
#tower{left:calc(var(--u)*2.6);top:calc(var(--u)*3);width:calc(var(--u)*38);opacity:0;
transform:translateX(calc(var(--u)*-3));transition:opacity .5s,transform .5s var(--ease)}
#tower header{display:flex;align-items:center;gap:calc(var(--u)*1);padding:calc(var(--u)*1) calc(var(--u)*1.4);font-weight:700}
#towerTitle{font-size:calc(var(--u)*2.1);letter-spacing:.06em;text-transform:uppercase;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#towerSub{font-size:calc(var(--u)*1.6);color:rgba(255,255,255,.85)}
#towerRows{position:relative;overflow:hidden;transition:height .4s var(--ease)}
#towerThumb{position:absolute;right:calc(var(--u)*.15);top:0;width:calc(var(--u)*.4);z-index:1;display:none;background:rgba(255,255,255,.5);
border-radius:calc(var(--u)*.2);transition:top .6s var(--ease),height .4s var(--ease)}
.trow{position:absolute;left:0;right:0;top:0;display:grid;grid-template-columns:calc(var(--u)*3.4) calc(var(--u)*.45) calc(var(--u)*4.6) minmax(0,1fr) auto calc(var(--u)*7.6);
align-items:center;column-gap:calc(var(--u)*.9);height:calc(var(--u)*3.3);padding:0 calc(var(--u)*1.2);
border-bottom:1px solid var(--line);transition:transform .6s var(--ease),background .3s,opacity .4s}
.trow.new{opacity:0}
.trow.air{background:linear-gradient(90deg,rgba(var(--ar),.42),rgba(var(--ar),.08))}
.thead{position:absolute;left:0;right:0;top:0;height:calc(var(--u)*2.4);display:flex;align-items:center;gap:calc(var(--u)*.8);
padding:0 calc(var(--u)*1.2);font-size:calc(var(--u)*1.5);font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--dim);
background:rgba(255,255,255,.04);transition:transform .6s var(--ease)}
.thead i{width:calc(var(--u)*1.1);height:calc(var(--u)*1.1);border-radius:50%}
.tpos{font-weight:700;text-align:right;font-size:calc(var(--u)*2.1)}
.tbar{height:62%;border-radius:calc(var(--u)*.3)}
.tnum{color:var(--dim);font-size:calc(var(--u)*1.7)}
.tname{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-transform:uppercase;letter-spacing:.02em}
.tgap{text-align:right;color:var(--dim);font-size:calc(var(--u)*1.8);white-space:nowrap}
.tgap.close{color:var(--loss);font-weight:700}
.tgap.lap{color:var(--gold);font-weight:700}.tgap.lap.fastest{color:var(--purple)}
.tgap .tpit{display:inline-block;padding:0 calc(var(--u)*.6);border-radius:calc(var(--u)*.4);background:rgba(251,146,60,.22);color:var(--warn);font-weight:700;font-size:calc(var(--u)*1.5)}
.tgap .tpit.garage{background:rgba(255,255,255,.1);color:var(--dim)}.tgap .tpit.dnf,.tgap .tpit.dq{background:rgba(248,113,113,.22);color:var(--loss)}
.tchange{font-size:calc(var(--u)*1.2);margin-left:calc(var(--u)*.4)}
.tchange.up{color:var(--gain)}.tchange.down{color:var(--loss)}
.tmarks{display:flex;align-items:center;gap:calc(var(--u)*.3)}
.tyre{width:calc(var(--u)*1.7);height:calc(var(--u)*1.7);border-radius:calc(var(--u)*.34);display:flex;
align-items:center;justify-content:center;font-size:calc(var(--u)*1);font-weight:700}
.tpen{padding:0 calc(var(--u)*.45);border-radius:calc(var(--u)*.3);background:var(--loss);color:#fff;font-weight:700;font-size:calc(var(--u)*1.25)}
.tfl{padding:0 calc(var(--u)*.45);border-radius:calc(var(--u)*.3);background:var(--purple);color:#111;font-weight:700;font-size:calc(var(--u)*1.25)}
.tstops{color:var(--dim);font-size:calc(var(--u)*1.3);font-weight:700}
/* Driver card */
#card{left:calc(var(--u)*6);bottom:calc(var(--u)*7);min-width:calc(var(--u)*62);max-width:calc(var(--u)*92);
display:flex;align-items:stretch;opacity:0;transform:translateY(calc(var(--u)*3));transition:opacity .45s,transform .55s var(--ease)}
#cardPlace{display:flex;flex-direction:column;align-items:center;justify-content:center;min-width:calc(var(--u)*11);
padding:0 calc(var(--u)*1.6);font-weight:700;background:var(--accent)}
#cardPlace b{font-size:calc(var(--u)*5.6);line-height:1}
#cardPlace span{font-size:calc(var(--u)*1.6);letter-spacing:.12em;text-transform:uppercase;opacity:.9}
#cardBody{flex:1;padding:calc(var(--u)*1.2) calc(var(--u)*2);display:flex;flex-direction:column;justify-content:center;
gap:calc(var(--u)*.3);background:var(--panel)}
#cardTop{display:flex;align-items:center;gap:calc(var(--u)*1.2)}
#cardNum{font-size:calc(var(--u)*2.6);color:var(--dim);font-weight:700}
#cardName{font-size:calc(var(--u)*4);font-weight:700;line-height:1.05;text-transform:uppercase;letter-spacing:.02em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#cardLogo{height:calc(var(--u)*3.6);max-width:calc(var(--u)*9);object-fit:contain;margin-left:auto;display:none}
#cardTeam{color:var(--dim);font-size:calc(var(--u)*2.1);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#cardStats{display:flex;gap:calc(var(--u)*2.2);font-size:calc(var(--u)*1.9);margin-top:calc(var(--u)*.3)}
#cardStats i{font-style:normal;color:var(--dim);margin-right:calc(var(--u)*.5);text-transform:uppercase;font-size:calc(var(--u)*1.5);letter-spacing:.08em}
#cardStory{align-self:flex-start;margin-top:calc(var(--u)*.4);padding:calc(var(--u)*.2) calc(var(--u)*1);border-radius:calc(var(--u)*.5);
background:rgba(255,255,255,.1);font-size:calc(var(--u)*1.5);font-weight:700;letter-spacing:.1em;text-transform:uppercase;display:none}
#cardPicture{width:calc(var(--u)*22);object-fit:cover;display:none;background:var(--panel2)}
/* Battle: two cars, or contact of an instant replay */
#battle{left:calc(50vw - var(--u)*39);bottom:calc(var(--u)*7);width:calc(var(--u)*78);
opacity:0;transform:translateY(calc(var(--u)*3));transition:opacity .45s,transform .55s var(--ease)}
#battle header,#train header{text-align:center;padding:calc(var(--u)*.7);font-weight:700;letter-spacing:.14em;text-transform:uppercase;
font-size:calc(var(--u)*1.8);background:linear-gradient(90deg,rgba(var(--ar),0),var(--accent),rgba(var(--ar),0))}
#battleBody{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;padding:calc(var(--u)*1.4) calc(var(--u)*2)}
.bside{display:flex;flex-direction:column;gap:calc(var(--u)*.2);min-width:0}
.bside.right{text-align:right}
.bnum{color:var(--dim);font-weight:700;font-size:calc(var(--u)*2)}
.bname{font-size:calc(var(--u)*3);font-weight:700;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bteam{color:var(--dim);font-size:calc(var(--u)*1.7);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#battleGap{text-align:center;padding:0 calc(var(--u)*2.4)}
#battleGap b{display:block;font-size:calc(var(--u)*4.4);line-height:1}
#battleGap span{font-size:calc(var(--u)*1.6);color:var(--dim)}
#battleGap span.closing{color:var(--loss)}#battleGap span.opening{color:var(--gain)}
/* Battle train: up to 6 cars of a class close together */
#train{left:calc(50vw - var(--u)*60);bottom:calc(var(--u)*7);width:calc(var(--u)*120);opacity:0;
transform:translateY(calc(var(--u)*3));transition:opacity .45s,transform .55s var(--ease)}
#trainCars{display:flex;padding:calc(var(--u)*1) calc(var(--u)*1.2);gap:calc(var(--u)*.8)}
.tcard{flex:1;min-width:0;display:flex;flex-direction:column;gap:calc(var(--u)*.2);padding:calc(var(--u)*.8) calc(var(--u)*1);
border-radius:calc(var(--u)*.6);background:var(--panel2);border-top:calc(var(--u)*.4) solid #888}
.tcard.air{background:rgba(var(--ar),.32)}
.tcard b{font-size:calc(var(--u)*2.6);line-height:1}
.tcard .bname{font-size:calc(var(--u)*2)}
.tcard .tgap{text-align:left}
/* Banners */
#banners{left:50%;top:calc(var(--u)*3);transform:translateX(-50%);display:flex;flex-direction:column;
align-items:center;gap:calc(var(--u)*.8)}
.banner{display:flex;align-items:stretch;opacity:0;transform:translateY(calc(var(--u)*-2));transition:opacity .4s,transform .5s var(--ease)}
.banner .tag{padding:calc(var(--u)*.8) calc(var(--u)*1.4);font-weight:700;letter-spacing:.12em;text-transform:uppercase;
font-size:calc(var(--u)*1.7);display:flex;align-items:center;color:#111}
.banner .txt{padding:calc(var(--u)*.8) calc(var(--u)*1.8);background:var(--panel);display:flex;flex-direction:column;justify-content:center}
.banner .txt b{font-size:calc(var(--u)*2.3);white-space:nowrap}
.banner .txt span{font-size:calc(var(--u)*1.6);color:var(--dim);white-space:nowrap}
/* Replay & clock */
#replay{right:calc(var(--u)*3);top:calc(var(--u)*3);padding:calc(var(--u)*.9) calc(var(--u)*1.8);
background:var(--accent);font-weight:700;letter-spacing:.24em;font-size:calc(var(--u)*2.4);border-radius:calc(var(--u)*.6);
opacity:0;transition:opacity .35s;display:flex;align-items:center;gap:calc(var(--u)*1)}
#replay i{width:calc(var(--u)*1.4);height:calc(var(--u)*1.4);border-radius:50%;background:#fff}
#replay.show i{animation:blink 1.2s infinite}
@keyframes blink{50%{opacity:.25}}
#clock{right:calc(var(--u)*3);bottom:calc(var(--u)*3);display:flex;align-items:center;
gap:calc(var(--u)*1.4);padding:calc(var(--u)*.9) calc(var(--u)*1.6);opacity:0;transition:opacity .5s}
#clockTime{font-size:calc(var(--u)*2.8);font-weight:700}
#clockLabel{font-size:calc(var(--u)*1.4);color:var(--dim);letter-spacing:.12em;text-transform:uppercase}
#clockFlag{padding:calc(var(--u)*.2) calc(var(--u)*.8);border-radius:calc(var(--u)*.4);background:var(--gold);color:#111;font-weight:700;
font-size:calc(var(--u)*1.5);display:none}
#weather{font-size:calc(var(--u)*1.7);color:var(--dim)}
/* Pit radar: cars near the car on air in the pit lane */
#pitradar{right:calc(var(--u)*3);top:calc(var(--u)*46);width:calc(var(--u)*36);opacity:0;
transform:translateX(calc(var(--u)*3));transition:opacity .4s,transform .5s var(--ease)}
#pitradar header{display:flex;align-items:baseline;gap:calc(var(--u)*1);padding:calc(var(--u)*.8) calc(var(--u)*1.4);
background:linear-gradient(90deg,var(--warn),rgba(251,146,60,.25));color:#111;font-weight:700}
#pitTitle{letter-spacing:.14em;text-transform:uppercase;font-size:calc(var(--u)*1.8)}
#pitCount{margin-left:auto;font-size:calc(var(--u)*1.6)}
.prow{display:grid;grid-template-columns:calc(var(--u)*.45) calc(var(--u)*4.6) minmax(0,1fr) auto;align-items:center;
column-gap:calc(var(--u)*.9);height:calc(var(--u)*3.2);padding:0 calc(var(--u)*1.2);border-bottom:1px solid var(--line)}
.prow .tname{font-size:calc(var(--u)*1.9)}
.pdist{text-align:right;font-weight:700;font-size:calc(var(--u)*2)}
.pdist.near{padding:0 calc(var(--u)*.7);border-radius:calc(var(--u)*.4);background:var(--loss);color:#fff;letter-spacing:.1em}
.pdist i{font-style:normal;color:var(--dim);font-weight:500;margin-right:calc(var(--u)*.5)}
/* Onboard: shift lights, speed, gear, pedals, energy & hybrid of the car on air */
#onboard{right:calc(var(--u)*3);bottom:calc(var(--u)*11);opacity:0;transform:translateY(calc(var(--u)*2));
transition:opacity .4s,transform .5s var(--ease)}
.ob-head{display:flex;align-items:center;gap:calc(var(--u)*.8);padding:calc(var(--u)*.6) calc(var(--u)*1.2);font-weight:700;
font-size:calc(var(--u)*1.7);text-transform:uppercase;letter-spacing:.04em;border-left:calc(var(--u)*.5) solid #888}
.ob-head span{color:var(--dim)}
.ob-head em{margin-left:auto;font-style:normal;color:var(--gold);font-size:calc(var(--u)*1.6)}
.ob-leds{display:flex;gap:calc(var(--u)*.4);justify-content:center;padding:calc(var(--u)*.5) calc(var(--u)*1.4) 0}
.ob-leds i{width:calc(var(--u)*1.5);height:calc(var(--u)*1.5);border-radius:50%;background:rgba(255,255,255,.1)}
/* led-* classes: "g" is the class of every graphic (absolute place), never on a part of one */
.ob-leds i{flex:none}.ob-leds i.on.led-g{background:var(--gain)}.ob-leds i.on.led-y{background:var(--gold)}
.ob-leds i.on.led-r{background:var(--loss)}
.ob-leds.flash i{background:var(--blue)!important;animation:blink .25s infinite}
.ob-main{display:flex;align-items:stretch;gap:calc(var(--u)*1.2);padding:calc(var(--u)*1) calc(var(--u)*1.4)}
.ob-speed{display:flex;flex-direction:column;justify-content:center;min-width:calc(var(--u)*10)}
.ob-speed b{font-size:calc(var(--u)*5);line-height:1}
.ob-speed span{color:var(--dim);font-size:calc(var(--u)*1.5);text-transform:uppercase;letter-spacing:.1em}
.ob-gear{display:flex;align-items:center;justify-content:center;min-width:calc(var(--u)*7);font-size:calc(var(--u)*6);font-weight:700;
border-radius:calc(var(--u)*.7);background:var(--panel2)}
.ob-pedals{display:flex;gap:calc(var(--u)*.6);align-items:flex-end}
.ob-pedal{width:calc(var(--u)*1.6);height:calc(var(--u)*7);border-radius:calc(var(--u)*.4);background:rgba(255,255,255,.08);
position:relative;overflow:hidden}
.ob-pedal i{position:absolute;left:0;right:0;bottom:0;height:0}
.ob-energy{display:flex;align-items:center;gap:calc(var(--u)*.8);padding:calc(var(--u)*.4) calc(var(--u)*1.4) calc(var(--u)*.6);
color:var(--dim);font-size:calc(var(--u)*1.4);text-transform:uppercase;letter-spacing:.08em}
.ob-energy:last-child{padding-bottom:calc(var(--u)*1)}
.ob-energy span{min-width:calc(var(--u)*8)}
.ob-energy div{flex:1;height:calc(var(--u)*.7);border-radius:calc(var(--u)*.35);background:rgba(255,255,255,.08);overflow:hidden}
.ob-energy i{display:block;height:100%;background:var(--gain);transition:width .2s linear,background-color .3s}
#onboard.cockpit .ob-main{flex-direction:column;align-items:center}
#onboard.cockpit .ob-gear{min-width:calc(var(--u)*14);min-height:calc(var(--u)*11);border-radius:50%;font-size:calc(var(--u)*7)}
#onboard.cockpit .ob-speed{align-items:center}
#onboard.helmet{border-radius:calc(var(--u)*.5)}
#onboard.helmet .ob-main{padding:calc(var(--u)*.5) calc(var(--u)*1)}
#onboard.helmet .ob-gear{min-width:calc(var(--u)*4.5);font-size:calc(var(--u)*3.4);background:none}
#onboard.helmet .ob-speed b{font-size:calc(var(--u)*3.4)}
#onboard.helmet .ob-pedal{width:calc(var(--u)*1);height:calc(var(--u)*4)}
#onboard.helmet .ob-head,#onboard.helmet .ob-energy{display:none}
/* Qualifying lap of the car on air */
#quali{left:calc(50vw - var(--u)*40);bottom:calc(var(--u)*7);width:calc(var(--u)*80);opacity:0;
transform:translateY(calc(var(--u)*3));transition:opacity .45s,transform .55s var(--ease)}
.q-top{display:flex;align-items:center;gap:calc(var(--u)*1.2);padding:calc(var(--u)*1) calc(var(--u)*1.6);border-left:calc(var(--u)*.6) solid #888}
.q-pos{font-size:calc(var(--u)*3.4);font-weight:700}
.q-name{flex:1;min-width:0;font-size:calc(var(--u)*2.8);font-weight:700;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.q-time{font-size:calc(var(--u)*4);font-weight:700}
.q-status{padding:calc(var(--u)*.2) calc(var(--u)*.9);border-radius:calc(var(--u)*.4);background:rgba(255,255,255,.12);font-weight:700;
font-size:calc(var(--u)*1.5);letter-spacing:.1em;text-transform:uppercase}
.q-bottom{display:grid;grid-template-columns:repeat(3,1fr) auto;gap:calc(var(--u)*.6);padding:0 calc(var(--u)*1.6) calc(var(--u)*1.2)}
.q-sector{padding:calc(var(--u)*.4) calc(var(--u)*.8);border-radius:calc(var(--u)*.4);background:var(--panel2);text-align:center;
font-size:calc(var(--u)*1.9);font-weight:700;border-bottom:calc(var(--u)*.4) solid rgba(255,255,255,.12)}
.q-target{display:flex;flex-direction:column;align-items:flex-end;justify-content:center;font-size:calc(var(--u)*1.5);color:var(--dim)}
.q-target b{font-size:calc(var(--u)*2.4)}
/* Track map: no panel, shadow keeps it readable on any picture. Shadow of the track lines drawn once in its own
svg layer behind (blurred copy: two shadows of 0.35 & 0.9 u as before), never blurred again while cars move */
#map{right:calc(var(--u)*3);top:calc(var(--u)*11);width:calc(var(--u)*40);padding:calc(var(--u)*1.2);opacity:0;transition:opacity .5s}
#map svg{display:block;width:100%;height:auto;overflow:visible;position:relative}
#map svg#mapShade{position:absolute;left:calc(var(--u)*1.2);top:calc(var(--u)*1.2);width:calc(100% - var(--u)*2.4);
will-change:transform;pointer-events:none}
#mapSvg{will-change:transform}
.msector{fill:none;stroke:rgba(255,255,255,.92);stroke-linejoin:round;stroke-linecap:round;transition:stroke .4s}
.msector.yellow{stroke:var(--gold)}
#mapPit{fill:none;stroke:rgba(255,255,255,.45);stroke-dasharray:6 6}
.mcar{transition:transform .22s linear,opacity .4s}
.mcar.pit{opacity:.35}
.mcar text{font-weight:700;fill:#fff;text-anchor:middle;dominant-baseline:central}
.myellow{animation:blink 0.8s infinite}
/* On demand: starting grid, event card, classification, championship */
.board{left:calc(50vw - var(--u)*62);top:calc(var(--u)*14);width:calc(var(--u)*124);opacity:0;transform:translateY(calc(var(--u)*3));
transition:opacity .5s,transform .6s var(--ease)}
.board header{display:flex;align-items:center;gap:calc(var(--u)*1.4);padding:calc(var(--u)*1.4) calc(var(--u)*2)}
.board header b{font-size:calc(var(--u)*3);font-weight:700;text-transform:uppercase;letter-spacing:.06em}
.board header span{font-size:calc(var(--u)*2);color:rgba(255,255,255,.85)}
.board header em{margin-left:auto;font-style:normal;font-size:calc(var(--u)*1.6);color:rgba(255,255,255,.8)}
#gridCars{display:grid;grid-template-columns:1fr 1fr;gap:calc(var(--u)*1) calc(var(--u)*2);padding:calc(var(--u)*1.6) calc(var(--u)*2)}
.gcar{display:flex;align-items:center;gap:calc(var(--u)*1.2);padding:calc(var(--u)*.8) calc(var(--u)*1.2);border-radius:calc(var(--u)*.6);
background:var(--panel2);border-left:calc(var(--u)*.6) solid #888}
.gcar:nth-child(even){margin-top:calc(var(--u)*3)}
.gcar b{font-size:calc(var(--u)*3.4);min-width:calc(var(--u)*4.4);text-align:center}
.gcar div{flex:1;min-width:0}
.gcar img{height:calc(var(--u)*6);width:calc(var(--u)*13);object-fit:cover;border-radius:calc(var(--u)*.4)}
.gtime{font-size:calc(var(--u)*2);font-weight:700}
#eventBody{display:grid;grid-template-columns:auto 1fr;gap:calc(var(--u)*2);padding:calc(var(--u)*2)}
#eventLogo{height:calc(var(--u)*14);max-width:calc(var(--u)*30);object-fit:contain;display:none}
.ev-cond{font-size:calc(var(--u)*2.2);margin-bottom:calc(var(--u)*1.2)}
.ev-cast{display:flex;gap:calc(var(--u)*1);margin-bottom:calc(var(--u)*1.4)}
.ev-node{flex:1;padding:calc(var(--u)*.8);border-radius:calc(var(--u)*.6);background:var(--panel2);text-align:center}
.ev-node.wet{background:rgba(96,165,250,.25)}
.ev-node b{display:block;font-size:calc(var(--u)*2.2)}
.ev-node span{display:block;color:var(--dim);font-size:calc(var(--u)*1.5)}
.ev-row{display:flex;justify-content:space-between;font-size:calc(var(--u)*2);padding:calc(var(--u)*.4) 0;border-bottom:1px solid var(--line)}
.ev-row span{color:var(--dim)}
.rrow{display:grid;grid-template-columns:calc(var(--u)*4) calc(var(--u)*.5) calc(var(--u)*5) minmax(0,1.4fr) minmax(0,1fr) calc(var(--u)*6) calc(var(--u)*11) calc(var(--u)*11) calc(var(--u)*6);
align-items:center;column-gap:calc(var(--u)*1.2);height:calc(var(--u)*3.6);padding:0 calc(var(--u)*2);border-bottom:1px solid var(--line);font-size:calc(var(--u)*2)}
.rrow.head{height:calc(var(--u)*3);color:var(--dim);font-size:calc(var(--u)*1.5);letter-spacing:.1em;text-transform:uppercase}
.rrow .r{text-align:right}.rrow .out{color:var(--loss);font-weight:700}
.crow{display:grid;grid-template-columns:calc(var(--u)*5) calc(var(--u)*.5) minmax(0,1.4fr) minmax(0,1fr) calc(var(--u)*16);
align-items:center;column-gap:calc(var(--u)*1.2);height:calc(var(--u)*3.8);padding:0 calc(var(--u)*2);border-bottom:1px solid var(--line);font-size:calc(var(--u)*2.1)}
.medal{display:inline-flex;align-items:center;justify-content:center;width:calc(var(--u)*3.2);height:calc(var(--u)*3.2);border-radius:50%;font-weight:700}
.medal.m1{background:#facc15;color:#111}.medal.m2{background:#cbd5e1;color:#111}.medal.m3{background:#d97706;color:#111}
.cpts{text-align:right;font-weight:700;font-size:calc(var(--u)*2.4);white-space:nowrap}
.pagebar{height:calc(var(--u)*.4);background:var(--accent);width:0}
/* Message of the operator (lower third), countdown, league logo, sponsors */
#message{left:calc(var(--u)*6);bottom:calc(var(--u)*24);display:flex;align-items:stretch;max-width:calc(var(--u)*110);opacity:0;
transform:translateX(calc(var(--u)*-3));transition:opacity .45s,transform .55s var(--ease)}
#messageTitle{padding:calc(var(--u)*1) calc(var(--u)*1.6);background:var(--accent);font-weight:700;letter-spacing:.12em;text-transform:uppercase;
font-size:calc(var(--u)*1.8);display:flex;align-items:center}
#messageText{padding:calc(var(--u)*1) calc(var(--u)*2);font-size:calc(var(--u)*2.6);font-weight:700}
#countdown{left:calc(50vw - var(--u)*30);top:calc(var(--u)*36);width:calc(var(--u)*60);text-align:center;opacity:0;
transform:scale(.96);transition:opacity .5s,transform .6s var(--ease)}
#countdown header{padding:calc(var(--u)*1);font-weight:700;letter-spacing:.2em;text-transform:uppercase;font-size:calc(var(--u)*2)}
#countdownTime{font-size:calc(var(--u)*11);font-weight:700;line-height:1.1;padding:calc(var(--u)*1) 0 calc(var(--u)*2)}
#logo{left:calc(var(--u)*42);top:calc(var(--u)*3);display:flex;align-items:center;gap:calc(var(--u)*1.2);opacity:0;transition:opacity .5s}
#logo img{height:calc(var(--u)*7);max-width:calc(var(--u)*24);object-fit:contain;display:none;filter:drop-shadow(0 0 calc(var(--u)*.4) rgba(0,0,0,.6))}
#logoName{font-size:calc(var(--u)*2.4);font-weight:700;text-transform:uppercase;letter-spacing:.08em;text-shadow:0 0 calc(var(--u)*.6) rgba(0,0,0,.9)}
#sponsors{left:calc(50vw - var(--u)*16);bottom:calc(var(--u)*1.2);width:calc(var(--u)*32);height:calc(var(--u)*5);opacity:0;transition:opacity .5s}
#sponsors img,#sponsors span{position:absolute;inset:0;margin:auto;max-width:100%;max-height:100%;object-fit:contain;opacity:0;transition:opacity .8s}
#sponsors span{display:flex;align-items:center;justify-content:center;font-weight:700;font-size:calc(var(--u)*2.2);text-transform:uppercase;letter-spacing:.1em}
#sponsors .on{opacity:1}
/* Layout editor */
body.edit{background:repeating-conic-gradient(#1b1f27 0 25%,#232833 0 50%) 0 0/40px 40px}
body.edit .g{opacity:1!important;transform:none!important;cursor:move;outline:2px dashed rgba(250,204,21,.55);outline-offset:3px}
body.edit .g.sel{outline:2px solid #facc15}
body.edit #banners .banner{opacity:1;transform:none}
.glabel{position:absolute;left:0;top:calc(var(--u)*-2.6);padding:2px 8px;border-radius:4px;background:#facc15;color:#111;
font:600 12px "Segoe UI",sans-serif;white-space:nowrap;pointer-events:none;display:none}
body.edit .glabel{display:block}
.guide{position:fixed;background:#22d3ee;z-index:9;display:none;pointer-events:none}
#guideX{top:0;bottom:0;width:1px}#guideY{left:0;right:0;height:1px}
#toolbar{position:fixed;left:50%;bottom:12px;transform:translateX(-50%);display:none;align-items:center;gap:8px;padding:8px 12px;
border-radius:10px;background:rgba(15,17,23,.96);box-shadow:0 4px 24px rgba(0,0,0,.6);font:500 13px "Segoe UI",sans-serif;z-index:10}
body.edit #toolbar{display:flex}
#toolbar button,#toolbar select{font:600 13px "Segoe UI",sans-serif;padding:6px 14px;border-radius:6px;border:1px solid #3a4150;background:#262b36;color:#fff;cursor:pointer}
#toolbar button.main{background:#e5383b;border-color:#e5383b}
#toolbar span{color:#aab2c0;max-width:460px}
#toolbar b{color:#facc15;font-weight:600;min-width:150px}
#chips{position:fixed;left:50%;top:8px;transform:translateX(-50%);display:none;flex-wrap:wrap;justify-content:center;gap:6px;
max-width:96vw;padding:6px 10px;border-radius:10px;background:rgba(15,17,23,.92);z-index:10}
body.edit #chips{display:flex}
body.edit.bare #chips,body.edit.bare #toolbar{display:none}
#chips button{font:600 12px "Segoe UI",sans-serif;padding:3px 10px;border-radius:12px;border:1px solid #facc15;background:#facc15;color:#111;cursor:pointer}
#chips button.off{background:transparent;color:#aab2c0;border-color:#3a4150}
</style></head><body>
<div id="tower" class="g panel"><header class="accentbg"><div id="towerTitle"></div><div id="towerSub"></div></header><div id="towerRows"><div id="towerThumb"></div></div></div>
<div id="card" class="g panel"><div id="cardPlace"><b id="cardPos"></b><span id="cardClass"></span></div>
<div id="cardBody"><div id="cardTop"><span id="cardNum"></span><span id="cardName"></span><img id="cardLogo" alt=""></div>
<div id="cardTeam"></div><div id="cardStats"></div><div id="cardStory"></div></div><img id="cardPicture" alt=""></div>
<div id="battle" class="g panel"><header id="battleTitle"></header><div id="battleBody">
<div class="bside"><span class="bnum" id="bAheadNum"></span><span class="bname" id="bAheadName"></span><span class="bteam" id="bAheadTeam"></span></div>
<div id="battleGap"><b id="bGap"></b><span id="bTrend"></span></div>
<div class="bside right"><span class="bnum" id="bBehindNum"></span><span class="bname" id="bBehindName"></span><span class="bteam" id="bBehindTeam"></span></div>
</div></div>
<div id="train" class="g panel"><header id="trainTitle"></header><div id="trainCars"></div></div>
<div id="banners" class="g"></div>
<div id="pitradar" class="g panel"><header><span id="pitTitle"></span><span id="pitCount"></span></header><div id="pitRows"></div></div>
<div id="replay" class="g"><i></i><span id="replayText"></span></div>
<div id="clock" class="g panel"><span id="clockFlag"></span><div><div id="clockTime"></div><div id="clockLabel"></div></div><div id="weather"></div></div>
<div id="onboard" class="g panel"><div class="ob-head" id="obHead"><b id="obNum"></b><span id="obName"></span><em id="obAhead"></em></div>
<div class="ob-leds" id="obLeds"></div>
<div class="ob-main"><div class="ob-speed"><b id="obSpeed"></b><span id="obUnit"></span></div><div class="ob-gear" id="obGear"></div>
<div class="ob-pedals"><div class="ob-pedal"><i id="obThrottle" style="background:var(--gain)"></i></div><div class="ob-pedal"><i id="obBrake" style="background:var(--loss)"></i></div></div></div>
<div class="ob-energy" id="obEnergyRow"><span id="obEnergyLabel"></span><div><i id="obEnergy"></i></div></div>
</div>
<div id="quali" class="g panel"><div class="q-top" id="qTop"><span class="q-pos" id="qPos"></span><span class="q-name" id="qName"></span>
<span class="q-status" id="qStatus"></span><span class="q-time" id="qTime"></span></div>
<div class="q-bottom"><div class="q-sector" id="qS1"></div><div class="q-sector" id="qS2"></div><div class="q-sector" id="qS3"></div>
<div class="q-target"><span id="qTargetLabel"></span><b id="qDelta"></b></div></div></div>
<div id="map" class="g"><svg id="mapShade" viewBox="0 0 1000 1000" aria-hidden="true"><defs>
<filter id="mapGlow" x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur in="SourceAlpha" stdDeviation="4.65" result="near"/>
<feComponentTransfer in="near" result="near"><feFuncA type="linear" slope=".85"/></feComponentTransfer>
<feGaussianBlur in="SourceAlpha" stdDeviation="12" result="far"/>
<feComponentTransfer in="far" result="far"><feFuncA type="linear" slope=".5"/></feComponentTransfer>
<feMerge><feMergeNode in="far"/><feMergeNode in="near"/></feMerge></filter></defs>
<g filter="url(#mapGlow)"><use href="#mapPit"></use><use href="#mapS1"></use><use href="#mapS2"></use><use href="#mapS3"></use></g></svg>
<svg id="mapSvg" viewBox="0 0 1000 1000"><path id="mapPit"></path><path id="mapS1" class="msector"></path>
<path id="mapS2" class="msector"></path><path id="mapS3" class="msector"></path><g id="mapCars"></g></svg></div>
<div id="grid" class="g panel board"><header class="accentbg"><b id="gridTitle"></b><em id="gridPage"></em></header><div id="gridCars"></div><div class="pagebar" id="gridBar"></div></div>
<div id="event" class="g panel board"><header class="accentbg"><b id="eventTrack"></b><span id="eventSession"></span></header>
<div id="eventBody"><img id="eventLogo" alt=""><div><div class="ev-cond" id="eventCond"></div><div class="ev-cast" id="eventCast"></div><div id="eventSchedule"></div></div></div></div>
<div id="results" class="g panel board"><header class="accentbg"><b id="resultsTitle"></b><span id="resultsSub"></span><em id="resultsPage"></em></header>
<div id="resultsRows"></div><div class="pagebar" id="resultsBar"></div></div>
<div id="champ" class="g panel board"><header class="accentbg"><b id="champTitle"></b><span id="champSub"></span><em id="champPage"></em></header>
<div id="champRows"></div><div class="pagebar" id="champBar"></div></div>
<div id="message" class="g panel"><div id="messageTitle"></div><div id="messageText"></div></div>
<div id="countdown" class="g panel"><header class="accentbg" id="countdownLabel"></header><div id="countdownTime"></div></div>
<div id="logo" class="g"><img id="logoImage" alt=""><span id="logoName"></span></div>
<div id="sponsors" class="g"></div>
<div class="guide" id="guideX"></div><div class="guide" id="guideY"></div>
<div id="chips"></div>
<div id="toolbar"><select id="tbPreset"></select><button class="main" id="tbSave"></button><button id="tbUndo"></button><button id="tbReset"></button>
<button id="tbResetAll"></button><b id="tbPlace"></b><span id="tbHint"></span></div>
<script>
"use strict";
const query=new URLSearchParams(location.search);
const token=query.get("token")||"";
const edit=query.get("edit")==="1";
const animate=query.get("animate")!=="0"&&!edit;
const once=query.get("once")==="1"||edit;
const scale=Math.max(parseFloat(query.get("scale")||"1")||1,0.3);
const only=(query.get("only")||"").split(",").map(text=>text.trim()).filter(Boolean);
const sourcePreset=query.has("preset")?query.get("preset"):null;
const IDS=["tower","card","battle","train","banners","pitradar","replay","clock","onboard","quali","map","grid","event","results",
"champ","message","countdown","logo","sponsors"];
if(!animate)document.documentElement.classList.add("still");
document.documentElement.style.setProperty("--u",scale+"vh");
const $=id=>document.getElementById(id);
const TONES={fastest:"var(--purple)",loss:"var(--loss)",warning:"var(--warn)",gain:"var(--gain)",accent:"var(--accent)",
yellow:"var(--gold)",dim:"#9aa3b2"};
const TYRES=@@tyres@@;  // letter: [fill, letter color], as compound badges of overlays
const ROW=3.3,HEAD=2.4;  // tower row & class title heights (u)
const picture=link=>link?link+(link.includes("?")?"&":"?")+"token="+encodeURIComponent(token):"";
let state={},layout={},preset="",version=0,lastCut=-1,cardTimer=0,towerPage=0,towerScroll=0,towerScrolls=1,towerTimer=0,shownBanners=new Set(),bannerQueue=[],bannerBusy=false;
let wasReplay=false,received=Date.now(),replayEnded=0,lastTrain=null,trainUntil=0,laps=new Map(),live={},liveVersion=0,trackKey=null,track=null;
const pages={grid:0,results:0,champ:0},pageTimers={},towerLines=new Map(),recentBanners=new Map();
let sponsorIndex=0,sponsorTimer=0,sponsorKey="";
function set(id,value){const el=typeof id==="string"?$(id):id;const text=value==null?"":String(value);if(el.textContent!==text)el.textContent=text}
function toggle(id,on){$(id).classList.toggle("show",!!on)}
function image(id,link){const el=$(id);const src=picture(link);if(src){if(el.getAttribute("src")!==src)el.src=src;el.style.display="block"}else el.style.display="none"}
function cell(className,value){const div=document.createElement("div");div.className=className;div.textContent=value==null?"":String(value);return div}
function labels(){return state.labels||{}}
// Places of the layout editor: left & top (fractions of the canvas), size factor (--u of the graphic)
function applyLayout(){
  for(const id of IDS){
    const el=$(id),place=layout[id];
    if(place){el.style.left=(place[0]*100)+"vw";el.style.top=(place[1]*100)+"vh";el.style.right="auto";el.style.bottom="auto";
      el.style.setProperty("--u",(scale*place[2])+"vh");if(id==="banners")el.style.transform="none"}
    else{for(const name of ["left","top","right","bottom","transform","--u"])el.style.removeProperty(name)}
  }
}
function tyreMark(letter){const mark=cell("tyre",letter),badge=TYRES[letter]||["#AAAAAA","#0E1116"];
  mark.style.background=badge[0];mark.style.color=badge[1];return mark}
// Tower: one element per car, kept from answer to answer (texts changed only when they change, moves animated)
function towerLine(key,header){
  let line=towerLines.get(key);
  if(!line){
    line=document.createElement("div");
    if(header){line.className="thead";line.innerHTML="<i></i><span></span>"}
    else{line.className="trow new";line.innerHTML='<div class="tpos"></div><div class="tbar"></div><div class="tnum"></div><div class="tname"><span></span><span class="tchange"></span></div><div class="tmarks"></div><div class="tgap"></div>'}
    line.style.transition="none";line.dataset.fresh="1";$("towerRows").append(line);towerLines.set(key,line);
  }
  return line;
}
function placeLine(line,y){
  line.style.transform="translateY(calc(var(--u)*"+y+"))";
  if(line.dataset.fresh){delete line.dataset.fresh;void line.offsetWidth;
    requestAnimationFrame(()=>{line.style.removeProperty("transition");line.classList.remove("new")})}
}
function towerEntries(group){
  if(!group.grouped)return group.rows.map(row=>({row}));
  // Overall by class: class title then its cars (best placed class first)
  const classes=[...new Set(group.rows.map(row=>row.cls))],entries=[];
  for(const cls of classes){const rows=group.rows.filter(row=>row.cls===cls);entries.push({header:cls,color:rows[0].color});for(const row of rows)entries.push({row})}
  return entries;
}
// Carousel: more cars than the tower height (cars shown): pages of whole rows in turn, sliding up, the last one
// ending on the last car; a page never ends on a class title
function towerPages(entries,height){
  const tops=[];let total=0;
  for(const entry of entries){tops.push(total);total+=entry.header?HEAD:ROW}
  tops.push(total);
  if(total<=height+.01)return {pages:[{offset:0,height:total}],total};
  let last=entries.length;while(last>0&&total-tops[last-1]<=height+.01)last--;
  const pages=[];
  for(let start=0;start<last;){
    let end=start;while(end<entries.length&&tops[end+1]-tops[start]<=height+.01)end++;
    if(end<entries.length&&end-1>start&&entries[end-1].header)end--;
    end=Math.max(end,start+1);pages.push({offset:tops[start],height:tops[end]-tops[start]});start=end;
  }
  pages.push({offset:tops[last],height:total-tops[last]});
  return {pages,total};
}
function tower(){
  const g=state.graphics||{},rows=state.tower||[];
  if(!g.tower||!rows.length){toggle("tower",false);return}
  let groups=[{title:labels().overall,rows,grouped:!!g.towerGroup}];
  if(g.towerMode==="class"){
    const names=[...new Set(rows.map(row=>row.cls))];
    groups=names.map(name=>({title:name,rows:rows.filter(row=>row.cls===name),byClass:true}));
  }else if(g.towerMode==="air"&&state.onAir){
    const cls=state.onAir.cls;groups=[{title:cls,rows:rows.filter(row=>row.cls===cls),byClass:true}];
  }
  const group=groups[towerPage%groups.length];
  set("towerTitle",group.title);set("towerSub",state.clock?state.clock.text:"");
  const entries=towerEntries(group),height=(g.towerRows||12)*ROW+(group.grouped?HEAD:0);
  const {pages,total}=towerPages(entries,height),page=pages[towerScroll%pages.length],offset=page.offset;towerScrolls=pages.length;
  const now=Date.now(),used=new Set(),leader=g.towerGap==="leader";let y=-offset;
  for(const entry of entries){
    if(entry.header){
      const key="h|"+entry.header,line=towerLine(key,true);used.add(key);
      line.firstChild.style.background=entry.color;set(line.lastChild,entry.header);
      placeLine(line,y);y+=HEAD;continue;
    }
    const row=entry.row,key="c|"+row.number+"|"+row.cls,line=towerLine(key,false);used.add(key);
    const [pos,bar,num,name,marks,gapBox]=line.children;
    line.classList.toggle("air",!!row.air);
    set(pos,group.byClass?row.classPos:row.pos);bar.style.background=row.color;set(num,"#"+row.number);
    set(name.firstChild,row.name);
    const change=name.lastChild;set(change,row.change?(row.change>0?"\\u25b2":"\\u25bc")+Math.abs(row.change):"");
    change.className="tchange "+(row.change>0?"up":row.change<0?"down":"");
    const sig=[g.towerPenalties&&row.pen,g.towerFastest&&row.fastest,g.towerStops&&row.stops,g.towerTyres&&(row.tyres||[]).join("")].join("|");
    if(marks.dataset.sig!==sig){marks.dataset.sig=sig;marks.innerHTML="";
      if(g.towerPenalties&&row.pen>0)marks.append(cell("tpen",labels().pen+(row.pen>1?" "+row.pen:"")));
      if(g.towerFastest&&row.fastest)marks.append(cell("tfl",labels().fastestTag));
      if(g.towerStops&&row.stops>0)marks.append(cell("tstops",row.stops+"\\u00d7"));
      if(g.towerTyres)for(const letter of row.tyres||[])marks.append(tyreMark(letter))}
    // Lap just completed: its time shown a few seconds in place of the gap (gold, purple for the fastest)
    const lapKey=row.number+"|"+row.cls,seen=laps.get(lapKey);
    if(row.lap&&(!seen||seen.id!==row.lapId)){
      const until=state.demo?Infinity:seen||state.version?now+5000:0;laps.set(lapKey,{id:row.lapId,until});
      if(until>now&&until<Infinity)setTimeout(tower,5100)}
    const flash=g.towerLaps&&row.lap&&laps.get(lapKey)&&laps.get(lapKey).until>now;
    const status=row.state||(row.pit?"pit":"");  // pit lane, garage, retired, disqualified: colored as in the app
    if(status){if(gapBox.dataset.mode!==status){gapBox.dataset.mode=status;gapBox.className="tgap";gapBox.innerHTML="";
      const tag=document.createElement("span");tag.className="tpit "+status;tag.textContent=labels()[status]||status;gapBox.append(tag)}}
    else{gapBox.dataset.mode="";gapBox.className="tgap"+(flash?" lap"+(row.lapTone==="fastest"?" fastest":""):row.close&&!leader?" close":"");
      set(gapBox,flash?row.lap:group.byClass?(leader?row.gapClassLeader:row.gapClass):(leader?row.gapLeader:row.gap))}
    placeLine(line,y);y+=ROW;
  }
  for(const [key,line] of towerLines)if(!used.has(key)){line.remove();towerLines.delete(key)}
  $("towerRows").style.height="calc(var(--u)*"+page.height+")";
  // Scroll mark: part of the cars shown (carousel only)
  const thumb=$("towerThumb");thumb.style.display=pages.length>1?"block":"none";
  if(pages.length>1){thumb.style.top="calc(var(--u)*"+(offset/total*page.height)+")";thumb.style.height="calc(var(--u)*"+(page.height/total*page.height)+")"}
  toggle("tower",true);
}
// Every few seconds: next page of the carousel, then next class (each class in turn)
function cycleTower(){clearTimeout(towerTimer);towerTimer=setTimeout(()=>{if(++towerScroll>=towerScrolls){towerScroll=0;towerPage++}tower();cycleTower()},(state.graphics&&state.graphics.towerCycle||10)*1000)}
function fillCard(car,story,storyTone){
  const g=state.graphics||{};
  set("cardPos","P"+car.classPos);set("cardClass",car.cls);$("cardPlace").style.background=car.color||"var(--accent)";
  set("cardNum","#"+car.number);set("cardName",car.name);set("cardTeam",car.team);
  image("cardLogo",car.logo);image("cardPicture",g.cardPicture?car.picture:"");
  const stats=$("cardStats");stats.innerHTML="";
  for(const [label,value] of car.stats||[]){if(!value)continue;const span=document.createElement("span");const tag=document.createElement("i");tag.textContent=label;span.append(tag,value);stats.append(span)}
  const box=$("cardStory");box.textContent=story||"";box.style.display=story?"block":"none";
  box.style.background=storyTone?TONES[storyTone]||"rgba(255,255,255,.1)":"rgba(255,255,255,.1)";box.style.color=storyTone?"#111":"";
}
function card(){
  const g=state.graphics||{},car=state.onAir,info=g.replayGraphics?state.replayInfo:null;
  // Instant replay of a flag or a stopped car: driver card of the car all along the replay
  if(info&&info.mode==="driver"&&info.car){fillCard(info.car,info.kind,info.tone);toggle("card",true);return}
  // Battle card on air tells both drivers: it takes the place of the driver card
  if(!g.card||!car||(g.battle&&(state.battle||state.train))||(info&&info.mode==="duel")||(g.quali&&state.quali)){toggle("card",false);if(car)lastCut=state.cut;return}
  fillCard(car,car.story,car.storyTone);
  if(state.cut!==lastCut){lastCut=state.cut;clearTimeout(cardTimer);toggle("card",true);
    if(g.cardSeconds>0)cardTimer=setTimeout(()=>toggle("card",false),g.cardSeconds*1000)}
  else if(g.cardSeconds<=0)toggle("card",true);
}
function battle(){
  const g=state.graphics||{},info=g.replayGraphics?state.replayInfo:null;
  let fight=state.battle;
  if(info&&info.mode==="duel")fight={title:info.kind,color:TONES[info.tone]||"var(--accent)",gap:info.center||"",trend:"",ahead:info.ahead,behind:info.behind};
  else if(!g.battle||(g.train&&trainShown()))fight=null;
  if(!fight){toggle("battle",false);return}
  fillBattle(fight);toggle("battle",true);
}
function fillBattle(fight){
  set("battleTitle",fight.title);
  set("bAheadNum","#"+fight.ahead.number);set("bAheadName",fight.ahead.name);set("bAheadTeam",fight.ahead.team);
  set("bBehindNum","#"+fight.behind.number);set("bBehindName",fight.behind.name);set("bBehindTeam",fight.behind.team);
  set("bGap",fight.gap);const trend=$("bTrend");trend.textContent=fight.trend||"";trend.className=fight.trendClass||"";
  $("battle").querySelector("header").style.background="linear-gradient(90deg,transparent,"+(fight.color||"var(--accent)")+",transparent)";
}
// Battle train kept 10 s after it broke up (no flicker on the gap threshold)
function trainShown(){const g=state.graphics||{};return !!(g.battle&&g.train&&(state.train||(lastTrain&&Date.now()<trainUntil)))&&!(state.replayInfo&&g.replayGraphics)}
function train(){
  if(state.train){lastTrain=state.train;trainUntil=Date.now()+10000}
  const fight=state.train||lastTrain;
  if(!trainShown()||!fight){toggle("train",false);return}
  set("trainTitle",fight.title);$("train").querySelector("header").style.background="linear-gradient(90deg,transparent,"+(fight.color||"var(--accent)")+",transparent)";
  const box=$("trainCars");box.innerHTML="";
  for(const car of fight.cars){
    const div=document.createElement("div");div.className="tcard"+(car.air?" air":"");div.style.borderTopColor=car.color;
    const top=document.createElement("b");top.textContent="P"+car.classPos;
    div.append(top,cell("bnum","#"+car.number),cell("bname",car.name),cell("tgap",car.gap));box.append(div);
  }
  toggle("train",true);
}
// Banners: most important first, the same news not told twice in 30 s, 4 waiting at most
function banners(){
  const g=state.graphics||{},now=Date.now();
  for(const event of state.events||[]){
    if(shownBanners.has(event.id))continue;shownBanners.add(event.id);
    if(!g.banners)continue;
    const same=(event.type||event.kind)+"|"+event.title;
    if(now-(recentBanners.get(same)||-1e9)<30000)continue;
    recentBanners.set(same,now);
    bannerQueue.push(event);
  }
  bannerQueue.sort((a,b)=>(b.priority||0)-(a.priority||0));
  if(bannerQueue.length>4)bannerQueue.length=4;
  if(!bannerBusy)nextBanner();
}
// Banners wait during a replay, then 5 s after it, so viewers see them live
function bannersHeld(){return !!(state.replay&&(state.graphics||{}).replayGraphics)||Date.now()<replayEnded+5000}
function nextBanner(){
  if(bannersHeld()&&bannerQueue.length){bannerBusy=true;setTimeout(nextBanner,500);return}
  const event=bannerQueue.shift();if(!event){bannerBusy=false;return}
  bannerBusy=true;
  const box=document.createElement("div");box.className="banner panel";
  const tag=cell("tag",event.kind);tag.style.background=TONES[event.tone]||"var(--accent)";
  const text=document.createElement("div");text.className="txt";
  const title=document.createElement("b");title.textContent=event.title;text.append(title);
  if(event.detail){const detail=document.createElement("span");detail.textContent=event.detail;text.append(detail)}
  box.append(tag,text);$("banners").append(box);
  requestAnimationFrame(()=>requestAnimationFrame(()=>box.classList.add("show")));
  const seconds=(state.graphics&&state.graphics.bannerSeconds)||6;
  setTimeout(()=>{box.classList.remove("show");setTimeout(()=>{box.remove();nextBanner()},animate?500:0)},seconds*1000);
}
function pitRadar(){
  const radar=state.pitRadar;
  if(!radar){toggle("pitradar",false);return}
  set("pitTitle",radar.title);set("pitCount",radar.count);
  const box=$("pitRows");box.innerHTML="";
  for(const row of radar.rows){
    const line=document.createElement("div");line.className="prow";
    const bar=cell("tbar","");bar.style.background=row.color;
    const distance=document.createElement("div");distance.className="pdist"+(row.alongside?" near":"");
    if(row.alongside)distance.textContent=labels().alongside;
    else{const arrow=document.createElement("i");arrow.textContent=row.ahead?"\\u25b2":"\\u25bc";distance.append(arrow,row.distance)}
    line.append(bar,cell("tnum","#"+row.number),cell("tname",row.name),distance);box.append(line);
  }
  toggle("pitradar",true);
}
function chrome(){
  const g=state.graphics||{};
  set("replayText",labels().replay||"");toggle("replay",g.replay&&state.replay);
  if(g.clock&&state.clock){set("clockTime",state.clock.text);set("clockLabel",state.clock.label);set("weather",(state.weather||[]).join("  \\u00b7  "));
    const flag=$("clockFlag");flag.textContent=state.flag||"";flag.style.display=state.flag?"block":"none";toggle("clock",true)}
  else toggle("clock",false);
}
function onboardStatic(){
  const g=state.graphics||{},car=state.onboard;
  const box=$("onboard");box.classList.remove("dash","cockpit","helmet");box.classList.add(g.onboardStyle||"dash");
  if(!g.onboard||!car){toggle("onboard",false);return}
  set("obNum","#"+car.number);set("obName",car.name);set("obAhead",car.ahead||"");$("obHead").style.borderLeftColor=car.color;
  set("obEnergyLabel",labels().energy);toggle("onboard",true);onboardLive();
}
// Onboard values eased each frame toward the last sample (10 a second): speed counts, pedals & lights move
// smoothly instead of jumping; a sample far from the shown value (car changed, replay jump) is taken at once
const ease={speed:null,rpm:0,throttle:0,brake:0,frame:0,last:0};
function onboardData(){return (live&&live.onboard)||(state.demo?{speed:247,gear:5,rpm:8420,rpmMax:9000,throttle:.92,brake:0,energy:.64,unit:"km/h"}:null)}
function onboardFrame(now){
  ease.frame=0;
  const data=onboardData();
  if(!data||!state.onboard||!(state.graphics||{}).onboard||document.hidden)return;
  const dt=Math.min(Math.max((now-(ease.last||now))/1000,0),0.25);ease.last=now;
  const k=animate?1-Math.exp(-dt/0.07):1;  // about 0.1 s to reach a new sample
  const speed=Number(data.speed)||0;
  ease.speed=ease.speed==null||Math.abs(speed-ease.speed)>60?speed:ease.speed+(speed-ease.speed)*k;
  ease.rpm+=((data.rpm||0)-ease.rpm)*k;ease.throttle+=((data.throttle||0)-ease.throttle)*k;ease.brake+=((data.brake||0)-ease.brake)*k;
  drawOnboard(data);
  const settled=Math.abs(speed-ease.speed)<.05&&Math.abs((data.rpm||0)-ease.rpm)<5&&Math.abs((data.throttle||0)-ease.throttle)<.005
    &&Math.abs((data.brake||0)-ease.brake)<.005;
  if(!settled)ease.frame=requestAnimationFrame(onboardFrame);else ease.last=0;
}
function onboardLive(){if(!ease.frame)ease.frame=requestAnimationFrame(onboardFrame)}
function drawOnboard(data){
  set("obSpeed",Math.round(ease.speed));set("obUnit",data.unit);
  set("obGear",data.gear==null?"-":data.gear<0?labels().reverse:data.gear===0?labels().neutral:data.gear);
  const max=data.rpmMax||state.onboard.rpmMax||1,ratio=Math.min(Math.max(ease.rpm/max,0),1);
  // Shift lights: from 70 % of the highest rpm, green, yellow then red, all blue (flashing) to shift up
  const leds=$("obLeds");if(leds.children.length!==10){leds.textContent="";for(let i=0;i<10;i++){const led=document.createElement("i");led.className=i<4?"led-g":i<7?"led-y":"led-r";leds.append(led)}}
  const lit=data.gear==null?0:Math.round(Math.min(Math.max((ratio-.7)/.27,0),1)*10);
  [...leds.children].forEach((led,i)=>led.classList.toggle("on",i<lit));leds.classList.toggle("flash",data.gear!=null&&ratio>=.97);
  $("obThrottle").style.height=(ease.throttle*100).toFixed(1)+"%";$("obBrake").style.height=(ease.brake*100).toFixed(1)+"%";
  $("obEnergyRow").style.display=data.energy>=0?"flex":"none";$("obEnergy").style.width=Math.max(data.energy,0)*100+"%";
  $("obEnergy").style.background=data.energy<=@@energyLow@@?"var(--loss)":data.energy<=@@energyMedium@@?"var(--warn)":"var(--gain)";  // as overlays
}
function lapClock(seconds){if(seconds<0)return "";const minutes=Math.floor(seconds/60),rest=seconds-minutes*60;
  return minutes+":"+(rest<10?"0":"")+rest.toFixed(1)}
function quali(){
  const g=state.graphics||{},lap=state.quali;
  if(!g.quali||!lap||(state.replayInfo&&g.replayGraphics)){toggle("quali",false);return}
  set("qPos",lap.position);set("qName","#"+lap.number+"  "+lap.name);$("qTop").style.borderLeftColor=lap.color;
  set("qStatus",lap.status);$("qStatus").style.display=lap.status?"block":"none";
  ["qS1","qS2","qS3"].forEach((id,index)=>{const sector=lap.sectors[index]||{text:"-",tone:""};set(id,sector.text);
    $(id).style.borderBottomColor=sector.tone?TONES[sector.tone]:"rgba(255,255,255,.12)"});
  set("qTargetLabel",lap.targetLabel+" "+lap.target);set("qDelta",lap.delta);$("qDelta").style.color=lap.deltaTone?TONES[lap.deltaTone]:"";
  qualiTime();toggle("quali",true);
}
function qualiTime(){
  const lap=state.quali;if(!lap)return;
  if(!lap.running){set("qTime",lap.best);return}
  set("qTime",lapClock(lap.now+(state.demo?0:(Date.now()-received)/1000)-lap.lapStart));
}
// Track map: world positions turned (map rotation) & scaled to the picture, sectors of the racing line
function turn(x,y){const angle=((state.graphics||{}).mapRotation||0)*Math.PI/180;if(!angle)return [x,y];
  const c=Math.cos(angle),s=Math.sin(angle);return [x*c-y*s,x*s+y*c]}
function fit(points){
  const turned=points.map(p=>turn(p[0],p[1])),xs=turned.map(p=>p[0]),ys=turned.map(p=>p[1]);
  const minX=Math.min(...xs),minY=Math.min(...ys),width=Math.max(Math.max(...xs)-minX,1),height=Math.max(Math.max(...ys)-minY,1);
  const f=Math.min(1000/width,1000/height)*.92;return {minX,minY,width,height,f,ox:(1000-width*f)/2,oy:(1000-height*f)/2}
}
function toMap(x,y){const [tx,ty]=turn(x,y);return [(tx-track.minX)*track.f+track.ox,(ty-track.minY)*track.f+track.oy]}
function polyline(points){return points.map((p,i)=>{const [x,y]=toMap(p[0],p[1]);return (i?"L":"M")+x.toFixed(1)+" "+y.toFixed(1)}).join(" ")}
function setupTrack(data){
  track={...data,rotation:(state.graphics||{}).mapRotation||0,...fit([...data.points,...data.pit])};
  const viewBox="0 "+Math.round(track.oy-20)+" 1000 "+Math.round(track.height*track.f+40);
  $("mapSvg").setAttribute("viewBox",viewBox);$("mapShade").setAttribute("viewBox",viewBox);
  // Length along the racing line of each point (sectors cut by fraction of the lap)
  const cum=[0];for(let i=1;i<data.points.length;i++){const a=data.points[i-1],b=data.points[i];cum.push(cum[i-1]+Math.hypot(b[0]-a[0],b[1]-a[1]))}
  track.cum=cum;track.total=cum[cum.length-1]||1;track.sectorKey="";
  $("mapPit").setAttribute("d",data.pit.length?polyline(data.pit):"");$("mapPit").style.strokeWidth=5;
  for(const id of ["mapS1","mapS2","mapS3"])$(id).style.strokeWidth=10;
  mapSectors(true);
}
function mapSectors(force){
  if(!track)return;
  const info=state.map||{},cuts=(info.sectors||[]).length===2?info.sectors:[],yellow=info.yellowSectors||[];
  const key=cuts.join(",")+"|"+yellow.join(",");if(!force&&key===track.sectorKey)return;track.sectorKey=key;
  const points=track.points,ends=[0,...cuts.map(cut=>cut*track.total),track.total+1];
  ["mapS1","mapS2","mapS3"].forEach((id,index)=>{
    const part=points.filter((p,i)=>track.cum[i]>=ends[index]-1&&track.cum[i]<=ends[index+1]+1);
    if(cuts.length&&index<2&&points.length){const next=points.find((p,i)=>track.cum[i]>ends[index+1]);if(next)part.push(next)}
    const whole=!cuts.length&&index===0;
    $(id).setAttribute("d",whole?polyline(points)+"Z":cuts.length&&part.length>1?polyline(part)+(index===2?" L"+toMap(points[0][0],points[0][1]).map(v=>v.toFixed(1)).join(" "):""):"");
    $(id).classList.toggle("yellow",!!yellow[index]);
  });
}
async function loadTrack(key){
  trackKey=key;
  try{const response=await fetch("/api/director/track?token="+encodeURIComponent(token),{cache:"no-store"});
    const data=await response.json();if(!data.key){track=null;return}
    setupTrack(data);mapCars();
  }catch(error){trackKey=null}
}
function mapCars(){
  const info=state.map;if(!info||!track)return;
  const g=state.graphics||{},size=(g.mapDots||100)/100;
  const box=$("mapCars"),positions=new Map(),flat=(live&&live.cars)||[];
  for(let i=0;i+2<flat.length;i+=3)positions.set(String(flat[i]),[flat[i+1],flat[i+2]]);
  const seen=new Set();
  for(const [slot,car] of Object.entries(info.cars||{})){
    const at=positions.get(slot)||[car[0],car[1]];seen.add(slot);
    let dot=box.querySelector('[data-slot="'+slot+'"]');
    if(!dot){dot=document.createElementNS("http://www.w3.org/2000/svg","g");dot.setAttribute("class","mcar");dot.dataset.slot=slot;
      dot.innerHTML='<circle r="14"></circle><text font-size="16"></text>';box.append(dot)}
    const air=car[4],yellow=String(info.yellow)===slot,circle=dot.firstChild,text=dot.lastChild;
    circle.setAttribute("r",(air?24:13)*size);circle.setAttribute("fill",yellow?"#facc15":car[2]);
    circle.setAttribute("stroke",air?"#fff":"rgba(0,0,0,.6)");circle.setAttribute("stroke-width",(air?5:3)*size);
    dot.classList.toggle("myellow",yellow);dot.classList.toggle("pit",!!car[5]&&!air);
    text.textContent=air?car[3]:"";text.setAttribute("font-size",22*size);
    const [x,y]=toMap(at[0],at[1]);
    dot.style.transform="translate("+x.toFixed(1)+"px,"+y.toFixed(1)+"px)";
    if(air&&box.lastChild!==dot)box.append(dot);
  }
  for(const dot of [...box.children])if(!seen.has(dot.dataset.slot))dot.remove();
}
// Layout editor: a sample circuit with a few cars
function demoTrack(){
  const points=[],cars={};
  for(let i=0;i<120;i++){const a=i/120*Math.PI*2;points.push([Math.cos(a)*(900+Math.sin(a*3)*120),Math.sin(a)*(420+Math.cos(a*2)*60)])}
  trackKey="demo";setupTrack({key:"demo",points,pit:[]});
  const colors=["#E5484D","#3E8EF7","#30A46C"];
  for(let i=0;i<10;i++){const p=points[(i*11+5)%points.length];cars[i]=[p[0],p[1],colors[i%3],String(7+i*3),i===2,i===8]}
  state.map={...state.map,track:"demo",yellow:6,cars};mapSectors(true);
}
function map(){
  const g=state.graphics||{};
  if(state.demo&&g.map&&(!track||track.key!=="demo"||track.rotation!==(g.mapRotation||0)))demoTrack();
  const info=state.map;
  if(!g.map||!info){toggle("map",false);return}
  if(!state.demo&&(info.track!==trackKey||(track&&track.rotation!==(g.mapRotation||0))))loadTrack(info.track);
  mapSectors(false);mapCars();toggle("map",!!track||state.demo);
}
function cyclePages(id,count,draw){
  const seconds=(id==="grid"?(state.graphics||{}).gridSeconds:(state.graphics||{}).pageSeconds)||10;
  if(pageTimers[id]||count<=1)return;
  const bar=$(id+"Bar");
  const tick=()=>{pages[id]=(pages[id]+1)%Math.max(count,1);draw();
    if(animate){bar.style.transition="none";bar.style.width="0";requestAnimationFrame(()=>requestAnimationFrame(()=>{bar.style.transition="width "+seconds+"s linear";bar.style.width="100%"}))}};
  pageTimers[id]=setInterval(tick,seconds*1000);
  if(animate){bar.style.transition="width "+seconds+"s linear";requestAnimationFrame(()=>bar.style.width="100%")}
}
function stopPages(id){clearInterval(pageTimers[id]);pageTimers[id]=0;pages[id]=0;$(id+"Bar").style.width="0"}
function pageOf(id,rows,per){const count=Math.max(Math.ceil(rows.length/per),1);const page=pages[id]%count;
  set(id+"Page",count>1?(page+1)+" / "+count:"");return {rows:rows.slice(page*per,page*per+per),count}}
function grid(){
  const info=state.grid;
  if(!info){toggle("grid",false);stopPages("grid");return}
  set("gridTitle",info.title);
  const page=pageOf("grid",info.cars,8),box=$("gridCars");box.innerHTML="";
  for(const car of page.rows){
    const div=document.createElement("div");div.className="gcar";div.style.borderLeftColor=car.color;
    const pos=document.createElement("b");pos.textContent=car.pos;
    const text=document.createElement("div");text.append(cell("bname","#"+car.number+"  "+car.name),cell("bteam",car.team),cell("gtime",car.time));
    div.append(pos,text);
    if(car.picture){const img=document.createElement("img");img.alt="";img.src=picture(car.picture);div.append(img)}
    box.append(div);
  }
  toggle("grid",true);cyclePages("grid",page.count,grid);
}
function eventCard(){
  const info=state.event;
  if(!info){toggle("event",false);return}
  set("eventTrack",info.track);set("eventSession",info.session);image("eventLogo",info.logo);
  set("eventCond",(info.conditions||[]).join("  \\u00b7  "));
  const cast=$("eventCast");cast.innerHTML="";
  for(const node of info.forecast||[]){const div=document.createElement("div");div.className="ev-node"+(node.wet?" wet":"");
    const label=document.createElement("span");label.textContent=node.label;const value=document.createElement("b");value.textContent=node.temperature;
    const sky=document.createElement("span");sky.textContent=[node.sky,node.rain].filter(Boolean).join(" \\u00b7 ");div.append(label,value,sky);cast.append(div)}
  const box=$("eventSchedule");box.innerHTML="";
  for(const [label,value] of info.schedule||[]){const row=document.createElement("div");row.className="ev-row";
    const name=document.createElement("span");name.textContent=label;const text=document.createElement("b");text.textContent=value;row.append(name,text);box.append(row)}
  toggle("event",true);
}
function results(){
  const info=state.results;
  if(!info){toggle("results",false);stopPages("results");return}
  set("resultsTitle",info.title);set("resultsSub",info.subtitle);
  const per=(state.graphics||{}).resultsRows||10,page=pageOf("results",info.rows,per),box=$("resultsRows");box.innerHTML="";
  const head=document.createElement("div");head.className="rrow head";const l=labels();
  head.append(cell("r","P"),cell("",""),cell("","#"),cell("",""),cell("",""),cell("r",l.laps),cell("r",l.gap),cell("r",l.best),cell("r",l.pits));box.append(head);
  for(const row of page.rows){
    const line=document.createElement("div");line.className="rrow";const bar=cell("tbar","");bar.style.background=row.color;
    line.append(cell("tpos",row.pos),bar,cell("tnum","#"+row.number),cell("tname",row.name),cell("bteam",row.team),cell("r",row.laps),
      cell("r"+(row.status?" out":""),row.status||row.gap),cell("r",row.best),cell("r",row.pits));box.append(line);
  }
  toggle("results",true);cyclePages("results",page.count,results);
}
function champ(){
  const info=state.champ;
  if(!info){toggle("champ",false);stopPages("champ");return}
  set("champTitle",info.title);set("champSub",info.subtitle);
  const per=(state.graphics||{}).resultsRows||10,page=pageOf("champ",info.rows,per),box=$("champRows");box.innerHTML="";
  for(const row of page.rows){
    const line=document.createElement("div");line.className="crow";
    const pos=document.createElement("div");if(row.medal){const medal=document.createElement("span");medal.className="medal m"+row.medal;medal.textContent=row.pos;pos.append(medal)}else{pos.className="tpos";pos.textContent=row.pos}
    const bar=cell("tbar","");bar.style.background=row.color||"transparent";
    line.append(pos,bar,cell("tname",row.name),cell("bteam",row.team),cell("cpts",row.points+" "+(labels().points||"").toLowerCase()));box.append(line);
  }
  toggle("champ",true);cyclePages("champ",page.count,champ);
}
function message(){
  const info=state.message;
  if(!info||!info.text){toggle("message",false);return}
  set("messageTitle",info.title||"");$("messageTitle").style.display=info.title?"flex":"none";set("messageText",info.text);toggle("message",true);
}
function clockText(seconds){seconds=Math.max(Math.ceil(seconds),0);const h=Math.floor(seconds/3600),m=Math.floor(seconds/60)%60,s=seconds%60;
  return (h?h+":"+(m<10?"0":""):"")+m+":"+(s<10?"0":"")+s}
function countdown(){
  const info=state.countdown;
  if(!info){toggle("countdown",false);return}
  set("countdownLabel",info.label);countdownTime();toggle("countdown",true);
}
function countdownTime(){const info=state.countdown;if(!info)return;
  set("countdownTime",clockText(info.endsAt>0?(info.endsAt-Date.now())/1000:info.seconds||0))}
// League logo & name, sponsors pictures in turn
function brand(){
  const g=state.graphics||{},info=state.brand||{};
  if(/^#[0-9a-fA-F]{6}$/.test(g.accent||"")){const root=document.documentElement.style,value=parseInt(g.accent.slice(1),16);
    root.setProperty("--accent",g.accent);root.setProperty("--ar",(value>>16)+","+(value>>8&255)+","+(value&255))}
  const logo=$("logoImage");if(info.logo){const src=picture(info.logo);if(logo.getAttribute("src")!==src)logo.src=src;logo.style.display="block"}else logo.style.display="none";
  set("logoName",info.name||"");toggle("logo",g.logo&&(info.logo||info.name));
  const items=(info.sponsors||[]).length?info.sponsors:(state.demo?info.names||[]:[]),box=$("sponsors"),key=items.join("|");
  if(key!==sponsorKey){sponsorKey=key;box.innerHTML="";sponsorIndex=0;
    for(const item of items){let el;if((info.sponsors||[]).length){el=document.createElement("img");el.alt="";el.src=picture(item)}else{el=document.createElement("span");el.textContent=item}box.append(el)}
    if(box.firstChild)box.firstChild.classList.add("on")}
  clearInterval(sponsorTimer);
  if(items.length>1&&!edit)sponsorTimer=setInterval(()=>{const children=box.children;if(!children.length)return;
    children[sponsorIndex%children.length].classList.remove("on");sponsorIndex++;children[sponsorIndex%children.length].classList.add("on")},(g.sponsorSeconds||8)*1000);
  toggle("sponsors",g.sponsors&&items.length);
}
function draw(){
  const g=state.graphics||{};
  document.documentElement.style.setProperty("--op",String(Math.min(Math.max((g.opacity||92)/100,.2),1)));
  document.body.classList.toggle("hidden-all",!edit&&(!!g.hidden||!state.live));
  if(!state.replay&&wasReplay)replayEnded=Date.now();wasReplay=!!state.replay;
  if(only.length&&!edit)for(const id of IDS)$(id).classList.toggle("off",!only.includes(id));
  applyLayout();brand();
  tower();train();card();battle();banners();pitRadar();chrome();onboardStatic();quali();map();grid();eventCard();results();champ();message();countdown();
  if(edit){if(state.onAir)fillCard(state.onAir,state.onAir.story,state.onAir.storyTone);if(state.battle)fillBattle(state.battle);editDraw()}
}
setInterval(()=>{if(state.quali&&state.quali.running)qualiTime();if(state.countdown)countdownTime();
  if(lastTrain&&trainUntil&&Date.now()>trainUntil&&!state.train){trainUntil=0;train();battle()}},100);
async function poll(){
  try{
    const asked=edit&&chosenPreset!==null?chosenPreset:sourcePreset;
    const response=await fetch("/api/director?v="+version+(edit?"&demo=1":"")+(asked!==null?"&preset="+encodeURIComponent(asked):"")
      +"&token="+encodeURIComponent(token),{cache:"no-store"});
    if(response.ok){const data=await response.json();
      if(data.v!==version||edit){const first=version===0;version=data.v;
        // Only the parts of the state that changed come, every part on the first answer
        if(data.full||first)state=data.state||{};else Object.assign(state,data.state||{});
        state.version=first?0:version;layout=data.layout||{};preset=data.preset||"";received=Date.now();
        if(first)for(const event of state.events||[])if(!event.fresh)shownBanners.add(event.id);
        draw();if(first)cycleTower()}}
  }catch(error){await new Promise(done=>setTimeout(done,1000))}
  if(!once)setTimeout(poll,0);
}
async function pollLive(){
  try{
    const response=await fetch("/api/director/live?v="+liveVersion+"&token="+encodeURIComponent(token),{cache:"no-store"});
    if(response.ok){const data=await response.json();if(data.v!==liveVersion){liveVersion=data.v;live=data.live||{};onboardLive();mapCars()}}
  }catch(error){await new Promise(done=>setTimeout(done,1000))}
  if(!once)setTimeout(pollLive,0);
}
// Layout editor: graphics dragged (snapped to the others & the middle), resized with the wheel, moved with the arrows,
// undone with Ctrl+Z, saved for a layout preset
let selected=null,drag=null,undo=[],chosenPreset=null,wheelUndo=0;
const EDIT_HIDDEN=new Set(["train","quali","event","results","champ","countdown"]);
function editPreset(){return chosenPreset!==null?chosenPreset:(sourcePreset!==null?sourcePreset:"")}
function remember(){undo.push(JSON.stringify(layout));if(undo.length>100)undo.shift()}
function editDraw(){
  const l=labels(),names=l.names||{};set("tbSave",l.save);set("tbReset",l.reset);set("tbResetAll",l.resetAll);set("tbUndo",l.undo);set("tbHint",l.editHint);
  const select=$("tbPreset");
  if(!select.options.length){for(const [value,text] of Object.entries(l.presets||{})){const option=document.createElement("option");option.value=value;option.textContent=(l.preset||"")+": "+text;select.append(option)}}
  if(chosenPreset===null)chosenPreset=preset;select.value=chosenPreset;
  const chips=$("chips");
  for(const id of IDS){const el=$(id);if(!el.querySelector(".glabel")){const tag=document.createElement("div");tag.className="glabel";tag.textContent=names[id]||id;el.append(tag)}
    el.classList.add("show");el.classList.toggle("off",EDIT_HIDDEN.has(id)||(only.length>0&&!only.includes(id)));
    let chip=chips.querySelector('[data-id="'+id+'"]');
    if(!chip){chip=document.createElement("button");chip.dataset.id=id;chip.textContent=names[id]||id;chips.append(chip);
      chip.onclick=()=>{if(EDIT_HIDDEN.has(id))EDIT_HIDDEN.delete(id);else EDIT_HIDDEN.add(id);editDraw()}}
    chip.classList.toggle("off",EDIT_HIDDEN.has(id))}
  if(!$("banners").querySelector(".banner")){const demo={kind:"FASTEST LAP",title:"K. Sato 1:34.902"};
    const box=document.createElement("div");box.className="banner panel";const tag=cell("tag",demo.kind);tag.style.background=TONES.fastest;
    const text=document.createElement("div");text.className="txt";const title=document.createElement("b");title.textContent=demo.title;text.append(title);box.append(tag,text);$("banners").prepend(box)}
  showPlace();
}
function placeOf(id){const el=$(id),rect=el.getBoundingClientRect();const current=layout[id];
  return [rect.left/innerWidth,rect.top/innerHeight,current?current[2]:1]}
function select(id){selected=id;for(const other of IDS)$(other).classList.toggle("sel",other===id);showPlace()}
function showPlace(){if(!selected){set("tbPlace","");return}const rect=$(selected).getBoundingClientRect(),place=layout[selected];
  set("tbPlace",((labels().names||{})[selected]||selected)+"  "+Math.round(rect.left/innerWidth*1920)+", "+Math.round(rect.top/innerHeight*1080)+"  "+Math.round((place?place[2]:1)*100)+"%")}
// Edges & middles of the other graphics shown, and of the screen: a dragged graphic snaps to them (6 px)
function snap(id,x,y){
  const el=$(id),rect=el.getBoundingClientRect(),w=rect.width,h=rect.height;let left=x*innerWidth,top=y*innerHeight,gx=null,gy=null;
  const xs=[innerWidth/2],ys=[innerHeight/2];
  for(const other of IDS){if(other===id)continue;const box=$(other);if(box.classList.contains("off"))continue;const r=box.getBoundingClientRect();if(!r.width)continue;
    xs.push(r.left,r.right,r.left+r.width/2);ys.push(r.top,r.bottom,r.top+r.height/2)}
  let best=7;for(const target of xs)for(const [offset,edge] of [[0,left],[w,left+w],[w/2,left+w/2]])if(Math.abs(edge-target)<best){best=Math.abs(edge-target);gx=target;left=target-offset}
  best=7;for(const target of ys)for(const [offset,edge] of [[0,top],[h,top+h],[h/2,top+h/2]])if(Math.abs(edge-target)<best){best=Math.abs(edge-target);gy=target;top=target-offset}
  $("guideX").style.display=gx===null?"none":"block";if(gx!==null)$("guideX").style.left=gx+"px";
  $("guideY").style.display=gy===null?"none":"block";if(gy!==null)$("guideY").style.top=gy+"px";
  return [left/innerWidth,top/innerHeight];
}
async function loadPreset(name){chosenPreset=name;version=0;undo=[];await poll()}
function setupEditor(){
  document.body.classList.add("edit");
  for(const id of IDS){const el=$(id);
    el.addEventListener("pointerdown",event=>{event.preventDefault();select(id);remember();const place=placeOf(id);
      drag={id,x:event.clientX,y:event.clientY,place};el.setPointerCapture(event.pointerId)});
    el.addEventListener("pointermove",event=>{if(!drag||drag.id!==id)return;
      let x=drag.place[0]+(event.clientX-drag.x)/innerWidth,y=drag.place[1]+(event.clientY-drag.y)/innerHeight;
      if(!event.shiftKey)[x,y]=snap(id,x,y);
      layout[id]=[x,y,drag.place[2]];applyLayout();showPlace()});
    el.addEventListener("pointerup",()=>{drag=null;$("guideX").style.display="none";$("guideY").style.display="none"});
    el.addEventListener("wheel",event=>{event.preventDefault();select(id);if(Date.now()-wheelUndo>800)remember();wheelUndo=Date.now();
      const place=placeOf(id);const size=Math.min(Math.max(place[2]*(event.deltaY<0?1.05:1/1.05),.3),3);
      layout[id]=[place[0],place[1],Math.round(size*1000)/1000];applyLayout();showPlace()},{passive:false});
    el.addEventListener("dblclick",()=>{remember();delete layout[id];applyLayout();showPlace()});
  }
  addEventListener("keydown",event=>{
    if(event.key==="h"||event.key==="H"){document.body.classList.toggle("bare");return}
    if((event.ctrlKey||event.metaKey)&&(event.key==="z"||event.key==="Z")){event.preventDefault();if(undo.length){layout=JSON.parse(undo.pop());applyLayout();showPlace()}return}
    const moves={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
    if(selected&&moves[event.key]){event.preventDefault();remember();const step=event.shiftKey?10:1,place=placeOf(selected);
      layout[selected]=[place[0]+moves[event.key][0]*step/innerWidth,place[1]+moves[event.key][1]*step/innerHeight,place[2]];applyLayout();showPlace()}
  });
  $("tbPreset").onchange=event=>loadPreset(event.target.value);
  $("tbUndo").onclick=()=>{if(undo.length){layout=JSON.parse(undo.pop());applyLayout();showPlace()}};
  $("tbReset").onclick=()=>{if(selected){remember();delete layout[selected];applyLayout();showPlace()}};
  $("tbResetAll").onclick=()=>{remember();layout={};applyLayout();showPlace()};
  $("tbSave").onclick=async()=>{
    try{const response=await fetch("/api/director/layout?preset="+encodeURIComponent(editPreset())+"&token="+encodeURIComponent(token),
      {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(layout)});
      set("tbHint",response.ok?labels().saved:labels().notSaved)}catch(error){set("tbHint",labels().notSaved)}};
}
if(edit)setupEditor();
poll();
if(!edit)pollLive();
</script></body></html>"""
