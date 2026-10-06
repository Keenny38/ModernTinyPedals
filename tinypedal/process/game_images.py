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
Images of LMU web UI: car brand logos, circuit logos, car & circuit pictures

The game serves its menu pictures on its local web server (same port as Rest API). Nothing is
shipped with the app: pictures are fetched from the game running on the user's computer and
cached (see userfile.game_images). Paths below are those of the game UI (start page bundle):

    /start/images/manufacturer/Brand=<manufacturer>[ Dark].svg     (.png for some brands)
    /start/images/tracks/{logos|cards|backgrounds}/<track key>.{svg|webp}
    /start/images/cars/{FrontThumbnail/|FrontLarge/}<vehicle file name>_frontAngle.webp

    /rest/race/car                  [{"desc": vehicle name, "manufacturer"}]  (rF2: "name", "vehFile")
    /rest/sessions/getAllVehicles   [{"name", "manufacturer", "vehFile", "fullPathTree", ...}]
    /rest/sessions/getTracksAll     [{"name", "properTrackName", "trackName", "sceneDesc", ...}]
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, NamedTuple

# Kinds of picture
BRAND = "brand"  # car brand logo (light logo, for dark backgrounds)
BRAND_DARK = "brand_dark"  # car brand logo for light backgrounds (game has it for some brands)
TRACK_LOGO = "track_logo"  # circuit logo
TRACK_CARD = "track_card"  # circuit picture (card size)
TRACK_BACKGROUND = "track_background"  # circuit picture (large)
CAR_THUMBNAIL = "car_thumbnail"  # car front angle picture (small)
CAR_PICTURE = "car_picture"  # car front angle picture (large)
KINDS = (BRAND, BRAND_DARK, TRACK_LOGO, TRACK_CARD, TRACK_BACKGROUND, CAR_THUMBNAIL, CAR_PICTURE)

CARS_ROUTE = "/rest/race/car"
VEHICLES_ROUTE = "/rest/sessions/getAllVehicles"
TRACKS_ROUTE = "/rest/sessions/getTracksAll"

# Brands with a dark logo variant in game (logo on light background)
DARK_BRANDS = frozenset((
    "Alpine", "Aston Martin", "BMW", "Cadillac", "Isotto Fraschini", "Lexus", "Oreca", "Ligier", "Toyota",
    "Vanwall", "Genesis",
))
PNG_BRANDS = frozenset(("Porsche", "Chevrolet"))  # brand logos in PNG (others SVG)
# Brands of game cars, to find brand in a car model text ("Ferrari 499P") before the game car list
# was read once (names as game spells them in its logo files)
KNOWN_BRANDS = (
    "ADESS", "Alpine", "Aston Martin", "BMW", "Cadillac", "Chevrolet", "Corvette", "Duqueine", "Ferrari", "Ford",
    "Genesis", "Ginetta", "Glickenhaus", "Isotta Fraschini", "Lamborghini", "Lexus", "Ligier", "McLaren",
    "Mercedes-AMG", "Oreca", "Peugeot", "Porsche", "Toyota", "Vanwall",
)

# Circuit picture name of game -> words found in names of that circuit (scene, venue, layout or
# official name, lower case letters & digits only). Most specific first.
TRACK_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bahrainwec", ("bahrain", "sakhir")),
    ("cotawec", ("cota", "circuitoftheamericas", "americas", "austin")),
    ("fujiwec", ("fuji",)),
    ("imolawec", ("imola", "enzoedinoferrari")),
    ("interlagoswec", ("interlagos", "josecarlospace", "carlospace", "saopaulo")),
    ("lemanswec", ("lemans", "sarthe", "mulsanne")),
    ("monzawec", ("monza",)),
    ("portimaowec", ("portimao", "algarve")),
    ("qatarwec", ("qatar", "losail", "lusail")),
    ("sebringwec", ("sebring",)),
    ("silverstoneelms", ("silverstone",)),
    ("paulricardelms", ("paulricard", "castellet", "ricard")),
    ("barcelonaelms", ("barcelona", "catalunya", "catalonia", "montmelo")),
    ("lagunaseca", ("lagunaseca", "laguna", "weathertechraceway")),
    ("roadatlanta", ("roadatlanta", "michelinraceway", "atlanta")),
    ("longbeach", ("longbeach",)),
    ("daytona", ("daytona",)),
    ("spawec", ("spafrancorchamps", "francorchamps", "spa")),  # last: "spa" is a short word
)
TRACK_KEYS = frozenset(key for key, _ in TRACK_WORDS)
_NOT_WORD = re.compile(r"[^a-z0-9]+")
_ACCENTS = str.maketrans("àáâãäåçèéêëìíîïñòóôõöùúûüýÿ", "aaaaaaceeeeiiiinooooouuuuyy")


class VehicleInfo(NamedTuple):
    """Car of game vehicle list"""

    name: str  # livery name, as vehicle name of game data
    manufacturer: str  # brand, as named by game (logo file name)
    file: str  # vehicle file name without extension (car picture file name)
    car_class: str = ""


def normalized(text: str) -> str:
    """Lower case letters & digits only (accents removed)"""
    return _NOT_WORD.sub("", text.lower().translate(_ACCENTS))


def track_key(*names: str) -> str:
    """Circuit picture name of game from any name of circuit (scene, venue, layout, official
    name, replay name...), empty if unknown"""
    texts = [normalized(name) for name in names if name]
    for key, words in TRACK_WORDS:
        for text in texts:
            if any(word in text for word in words):
                return key
    return ""


def vehicle_file_name(path: str) -> str:
    """Vehicle file name without folders & extension (game paths use backslash)"""
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


def car_class_of(path_tree: str) -> str:
    """Car class from game path tree ("LMU, GT3, McLaren...": second part)"""
    parts = [part.strip() for part in path_tree.split(",")]
    return parts[1] if len(parts) > 1 else ""


def parse_vehicles(data: Any) -> list[VehicleInfo]:
    """Cars of game vehicle lists (all vehicles, or race cars: "desc" is vehicle name), one per name
    of a car (entries without name or brand skipped)"""
    vehicles: list[VehicleInfo] = []
    if not isinstance(data, list):
        return vehicles
    for item in data:
        if not isinstance(item, dict):
            continue
        manufacturer = str(item.get("manufacturer") or "").strip()
        if not manufacturer:
            continue
        file = vehicle_file_name(str(item.get("vehFile") or ""))
        car_class = car_class_of(str(item.get("fullPathTree") or ""))
        names = {str(item.get(field) or "").strip() for field in ("name", "desc")} - {""}
        vehicles.extend(VehicleInfo(name, manufacturer, file, car_class) for name in sorted(names))
    return vehicles


def brand_in(text: str, brands: Iterable[str] = KNOWN_BRANDS) -> str:
    """Brand a text starts with ("Aston Martin Vantage AMR" -> "Aston Martin"), longest brand first,
    empty if none"""
    found = normalized(text)
    if not found:
        return ""
    best = ""
    for brand in brands:
        key = normalized(brand)
        if key and found.startswith(key) and len(brand) > len(best):
            best = brand
    return best


def parse_tracks(data: Any) -> dict[str, str]:
    """Names of game track list -> circuit picture name (every name of a track entry, lower case)"""
    tracks: dict[str, str] = {}
    if not isinstance(data, list):
        return tracks
    for item in data:
        if not isinstance(item, dict):
            continue
        names = [str(item.get(field) or "") for field in ("sceneDesc", "properTrackName", "trackName", "name",
                                                           "layoutName", "eventName")]
        key = track_key(*names)
        if not key:
            continue
        for name in names:
            if name:
                tracks[name.strip().lower()] = key
    return tracks


def image_path(kind: str, key: str) -> str:
    """Path of picture on game web server (key: brand, circuit picture name or vehicle file name)"""
    if kind in (BRAND, BRAND_DARK):
        suffix = " Dark" if kind == BRAND_DARK and key in DARK_BRANDS else ""
        ext = "png" if key in PNG_BRANDS else "svg"
        return f"/start/images/manufacturer/Brand={key}{suffix}.{ext}"
    if kind == TRACK_LOGO:
        return f"/start/images/tracks/logos/{key}.svg"
    if kind == TRACK_CARD:
        return f"/start/images/tracks/cards/{key}.webp"
    if kind == TRACK_BACKGROUND:
        return f"/start/images/tracks/backgrounds/{key}.webp"
    if kind == CAR_THUMBNAIL:
        return f"/start/images/cars/FrontThumbnail/{key}_frontAngle.webp"
    if kind == CAR_PICTURE:
        return f"/start/images/cars/FrontLarge/{key}_frontAngle.webp"
    raise ValueError(f"unknown picture kind {kind!r}")


def image_extension(kind: str, key: str) -> str:
    """File extension of picture (with dot)"""
    return "." + image_path(kind, key).rsplit(".", 1)[-1]
