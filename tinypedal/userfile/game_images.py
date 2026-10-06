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
Car brand & circuit pictures of LMU, fetched from the game running on this computer, cached

Pictures (paths: process.game_images) are never shipped with the app: they are asked to the game
web server (Rest API address, see ui.game_rest) in background, saved in the game image folder
(cfg.path.game_image) and shown from there, also while the game does not run. Game lists (cars with
their brand & picture file, circuit names) are kept in catalog.json of the same folder.

Lookups never block nor touch the network: a picture not cached yet answers "" and is fetched in
background; listeners are told once it is saved (called on fetch thread: Qt code hands over to UI
thread, see ui.quick.game_pictures). `version` grows with each new picture or catalog, so users
caching "no picture" answers know when to look again.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import time
from collections.abc import Callable

from ..process import game_images as gi
from ..setting import cfg

CATALOG_FILE = "catalog.json"
MAX_PICTURE_BYTES = 8_000_000
RETRY_GAME = 60.0  # seconds before asking a game that did not answer again
RETRY_MISSING = 7 * 86400.0  # seconds before asking again a picture game does not have
QUEUE_WAIT = 30.0  # seconds, fetch thread wakes up to read game lists when game starts
_SAFE_NAME = re.compile(r"[^A-Za-z0-9 ._-]+")
PICTURE_SIGNATURES = (b"<", b"\xef\xbb\xbf<", b"\x89PNG", b"RIFF", b"\xff\xd8")  # svg, png, webp, jpeg

logger = logging.getLogger(__name__)


def fetch_from_game(resource: str) -> tuple[int, bytes]:
    """Status & body of game web server answer, (0, b"") if game does not answer"""
    from ..ui.game_rest import GameConnection  # Qt core only, imported when first needed

    with GameConnection() as connection:
        return connection.request("GET", resource)


def safe_name(key: str) -> str:
    """File name of picture key (brand, circuit or vehicle file name)"""
    return _SAFE_NAME.sub("_", key).strip(" .") or "_"


class GameImages:
    """Cache of game pictures & lists, fetched in background"""

    def __init__(self):
        self._lock = threading.RLock()
        self._jobs: queue.SimpleQueue[tuple[str, str] | None] = queue.SimpleQueue()
        self._queued: set[tuple[str, str]] = set()
        self._thread: threading.Thread | None = None
        self._listeners: list[Callable[[], None]] = []
        self._loaded_folder = ""
        self._catalog_read = False  # game lists read from game during this run
        self._game_retry = 0.0  # time game may be asked again (did not answer)
        self.vehicles: dict[str, gi.VehicleInfo] = {}  # vehicle name (lower case) -> car
        self.brands: dict[str, str] = {}  # brand (normalized) -> brand as game names it
        self.tracks: dict[str, str] = {}  # circuit name (lower case) -> circuit picture name
        self.missing: dict[str, float] = {}  # picture path on game server -> time game did not have it
        self.version = 0

    # Folder & catalog
    @property
    def folder(self) -> str:
        return cfg.path.game_image

    def picture_file(self, kind: str, key: str) -> str:
        """Cache file of picture (may not exist)"""
        return os.path.join(self.folder, kind, safe_name(key) + gi.image_extension(kind, key))

    def load_catalog(self):
        """Game lists saved by an earlier run (once per game image folder)"""
        folder = self.folder
        with self._lock:
            if self._loaded_folder == folder:
                return
            self._loaded_folder = folder
            self.vehicles.clear()
            self.brands.clear()
            self.tracks.clear()
            self.missing.clear()
        try:
            with open(os.path.join(folder, CATALOG_FILE), encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        vehicles = [gi.VehicleInfo(*item[:4]) for item in data.get("vehicles", ())
                    if isinstance(item, list) and len(item) >= 4 and all(isinstance(value, str) for value in item[:4])]
        with self._lock:
            self.set_vehicles(vehicles)
            tracks = data.get("tracks", {})
            if isinstance(tracks, dict):
                self.tracks.update((str(name), str(key)) for name, key in tracks.items() if key in gi.TRACK_KEYS)
            missing = data.get("missing", {})
            if isinstance(missing, dict):
                self.missing.update((str(path), float(stamp)) for path, stamp in missing.items()
                                    if isinstance(stamp, (int, float)))

    def save_catalog(self):
        """Game lists & pictures game does not have, for next runs"""
        with self._lock:
            data = {
                "vehicles": sorted({tuple(car) for car in self.vehicles.values()}),
                "tracks": dict(sorted(self.tracks.items())),
                "missing": dict(sorted(self.missing.items())),
            }
        path = os.path.join(self.folder, CATALOG_FILE)
        try:
            os.makedirs(self.folder, exist_ok=True)
            with open(f"{path}.tmp", "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=1)
            os.replace(f"{path}.tmp", path)
        except OSError:
            logger.warning("GAME IMAGES: catalog not saved in %s", self.folder)

    def set_vehicles(self, vehicles: list[gi.VehicleInfo]):
        """Cars of game lists (later names replace earlier ones, picture file kept if new one has none)"""
        with self._lock:
            for car in vehicles:
                key = car.name.lower()
                known = self.vehicles.get(key)
                if known is not None and not car.file and known.file:
                    car = car._replace(file=known.file, car_class=car.car_class or known.car_class)
                self.vehicles[key] = car
                self.brands[gi.normalized(car.manufacturer)] = car.manufacturer

    # Lookups (any thread, never blocking)
    def vehicle(self, name: str) -> gi.VehicleInfo | None:
        """Car of game list by vehicle name, None if unknown"""
        self.start()
        return self.vehicles.get(name.strip().lower()) if name else None

    def brand(self, vehicle_name: str = "", hint: str = "") -> str:
        """Brand of car as game names it (logo file name): from game car list by vehicle name, else
        from brand or car model text given as hint ("Ferrari", "Ferrari 499P"), else hint"""
        car = self.vehicle(vehicle_name)
        if car is not None:
            return car.manufacturer
        if not hint:
            return gi.brand_in(vehicle_name, self.known_brands())
        known = self.brands.get(gi.normalized(hint))
        if known:
            return known
        return gi.brand_in(hint, self.known_brands()) or hint.strip()

    def known_brands(self) -> list[str]:
        with self._lock:
            return [*self.brands.values(), *gi.KNOWN_BRANDS]

    def track(self, *names: str) -> str:
        """Circuit picture name of any circuit name (game lists first), empty if unknown"""
        self.start()
        for name in names:
            key = self.tracks.get(name.strip().lower()) if name else None
            if key:
                return key
        return gi.track_key(*names)

    def file(self, kind: str, key: str) -> str:
        """Cached picture file, "" if not cached yet (then fetched in background) or game has none"""
        if not key:
            return ""
        self.start()
        path = self.picture_file(kind, key)
        if os.path.isfile(path):
            return path
        self.request(kind, key)
        return ""

    def brand_logo(self, brand: str, dark: bool = False) -> str:
        """Logo file of brand (game name, see brand()); dark: logo for light background if game has one"""
        if dark and brand in gi.DARK_BRANDS:
            path = self.file(gi.BRAND_DARK, brand)
            if path:
                return path
        return self.file(gi.BRAND, brand)

    def track_logo(self, *names: str) -> str:
        return self.file(gi.TRACK_LOGO, self.track(*names))

    def track_picture(self, *names: str, large: bool = False) -> str:
        return self.file(gi.TRACK_BACKGROUND if large else gi.TRACK_CARD, self.track(*names))

    def car_picture(self, vehicle_name: str, large: bool = False) -> str:
        car = self.vehicle(vehicle_name)
        if car is None or not car.file:
            return ""
        return self.file(gi.CAR_PICTURE if large else gi.CAR_THUMBNAIL, car.file)

    # Listeners
    def add_listener(self, callback: Callable[[], None]):
        """Called (on fetch thread) after a picture is saved or game lists are read"""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[], None]):
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def changed(self):
        with self._lock:
            self.version += 1
            listeners = tuple(self._listeners)
        for callback in listeners:
            try:
                callback()
            except Exception:  # a listener never stops fetching
                logger.exception("GAME IMAGES: listener failed")

    # Background fetch
    def start(self):
        """Saved lists loaded & fetch thread running (first lookup starts it)"""
        if self._loaded_folder != self.folder:
            self.load_catalog()
        if self._thread is None:
            with self._lock:
                if self._thread is None:
                    self._thread = threading.Thread(target=self._run, daemon=True, name="Game images")
                    self._thread.start()

    def request(self, kind: str, key: str):
        """Fetch picture in background, unless queued, game has none or game did not answer lately"""
        path = gi.image_path(kind, key)
        now = time.time()
        with self._lock:
            if (kind, key) in self._queued or now < self._game_retry:
                return
            if now - self.missing.get(path, -RETRY_MISSING) < RETRY_MISSING:
                return
            self._queued.add((kind, key))
        self._jobs.put((kind, key))

    def _run(self):
        while True:
            try:
                job = self._jobs.get(timeout=QUEUE_WAIT)
            except queue.Empty:
                job = None
            try:
                if not self._catalog_read and time.time() >= self._game_retry:
                    self.read_game_lists()
                if job is not None:
                    self.fetch_picture(*job)
            except Exception:  # fetching stops for this job only
                logger.exception("GAME IMAGES: fetch failed")
            finally:
                if job is not None:
                    with self._lock:
                        self._queued.discard(job)

    def game_answered(self, status: int) -> bool:
        """Whether game answered; if not, game left alone for a while"""
        if status:
            return True
        with self._lock:
            self._game_retry = time.time() + RETRY_GAME
        return False

    def read_game_lists(self) -> bool:
        """Car & circuit lists of game (brands, picture files), logos of every brand & circuit queued"""
        vehicles: list[gi.VehicleInfo] = []
        tracks: dict[str, str] = {}
        for route in (gi.VEHICLES_ROUTE, gi.CARS_ROUTE, gi.TRACKS_ROUTE):
            status, body = fetch_from_game(route)
            if not self.game_answered(status):
                return False
            if status != 200:
                continue
            try:
                data = json.loads(body)
            except ValueError:
                continue
            if route == gi.TRACKS_ROUTE:
                tracks.update(gi.parse_tracks(data))
            else:
                vehicles.extend(gi.parse_vehicles(data))
        self._catalog_read = True
        if not vehicles and not tracks:
            return False
        with self._lock:
            self.set_vehicles(vehicles)
            self.tracks.update(tracks)
            brands = sorted({car.manufacturer for car in vehicles})
            track_keys = sorted(set(tracks.values()))
        self.save_catalog()
        self.changed()
        for brand in brands:  # small logos: all of them, shown for cars never met yet
            self.file(gi.BRAND, brand)
            if brand in gi.DARK_BRANDS:
                self.file(gi.BRAND_DARK, brand)
        for key in track_keys:
            self.file(gi.TRACK_LOGO, key)
        return True

    def fetch_picture(self, kind: str, key: str) -> bool:
        """Picture from game saved in cache, True if saved"""
        target = self.picture_file(kind, key)
        if os.path.isfile(target):
            return False
        resource = gi.image_path(kind, key)
        status, body = fetch_from_game(resource.replace(" ", "%20"))
        if not self.game_answered(status):
            return False
        if status != 200 or not body or len(body) > MAX_PICTURE_BYTES or not body.startswith(PICTURE_SIGNATURES):
            with self._lock:
                self.missing[resource] = time.time()
            self.save_catalog()
            return False
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(f"{target}.tmp", "wb") as file:
                file.write(body)
            os.replace(f"{target}.tmp", target)
        except OSError:
            logger.warning("GAME IMAGES: picture not saved: %s", target)
            return False
        self.changed()
        return True


images = GameImages()
