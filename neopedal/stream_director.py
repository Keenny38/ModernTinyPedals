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

Parts: stream_director_feeds (feeds, layout places store, track outline), stream_director_demo (sample state of
the layout editor, texts of the graphics), stream_director_page (page HTML & style) & stream_director_script
(its script); answers of the server & league branding here.
"""

from __future__ import annotations

import json
import os
import re

from .stream_director_demo import demo_labels, demo_state, labels  # noqa: F401  (demo_labels & labels re-exported)
from .stream_director_feeds import (  # noqa: F401  (re-exported: stream_director.PlacementStore...)
    PLACE_LIMITS,
    SCALE_LIMITS,
    WAIT_SECONDS,
    WATCH_SECONDS,
    DirectorFeed,
    PlacementStore,
    SectionFeed,
    TrackOutline,
    clean_placements,
    sections_json,
)
from .stream_director_page import DIRECTOR_HTML, director_html, tyre_badges  # noqa: F401  (re-exported)
from .validator import load_json_strict

# Graphics placed by the layout editor (element ids of the page)
GRAPHIC_IDS = ("tower", "card", "battle", "train", "banners", "pitradar", "replay", "clock", "onboard", "quali", "map",
               "grid", "event", "results", "champ", "message", "countdown", "logo", "sponsors")
LAYOUT_PRESETS = ("", "pre", "race", "post")  # layouts of the editor: default, pre-race, race, post-race
MAX_LAYOUT_BODY = 64 * 1024  # bytes: layout sent by an editor
BRAND_FOLDER = "broadcast_branding"  # config folder: league logo & sponsors pictures (sponsors subfolder)
BRAND_FILE = re.compile(r"^(sponsors/)?[A-Za-z0-9 ._()-]{1,96}\.(png|jpg|jpeg|webp|svg)$", re.I)
BRAND_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
               "svg": "image/svg+xml"}
MAX_SPONSORS = 24


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
    """Layout sent by the editor (POST body JSON) for a preset (None: preset in use), sources told at once

    Raises:
        ValueError: invalid JSON (also nested too deeply, NaN), UnicodeDecodeError.
    """
    chosen = preset if preset is not None else director_layout.active()
    placements = director_layout.set(chosen, load_json_strict(body.decode("utf-8")) if body.strip() else {})
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
