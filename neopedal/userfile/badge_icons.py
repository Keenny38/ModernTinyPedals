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
Le Mans Ultimate driver badges: game names, descriptions & icons (cached)

The game menu shows the player's badge ("sr-clean"...) as an SVG icon of Studio 397's public image server
(no sign-in), not stored in the game folder: the icon is downloaded once in background, saved in the game
image folder (badge/<badge>.svg) and shown from there. Only badges of the game list are asked for. Lookups
never block nor touch the network: an icon not cached yet answers "" and is fetched.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
import urllib.request
from typing import NamedTuple

from ..setting import cfg
from . import atomic_replace

ICON_HOST = "https://rf2-ui-images-prod.s3.eu-west-1.amazonaws.com"  # game menu image server (production)
ICON_FOLDER = "badge"
MAX_ICON_BYTES = 1_000_000
RETRY_SECONDS = 600.0  # icon asked again after a failed download
TIMEOUT = 10.0


class Badge(NamedTuple):
    """Game name & description (English, as game menu), colors of its icon (dark & light theme)"""

    name: str
    description: str
    color: str
    light_color: str


ROOKIE = Badge("Rookie", "New to Le Mans Ultimate", "#9AA3AE", "#5F6873")
WARNING = Badge("Warning", "Has recently been involved in a higher number of incidents", "#F0A23C", "#B26A00")
# Badges of game (menu code)
BADGES = {
    "sr-noob": ROOKIE,
    "sr-rookie": ROOKIE,
    "sr-probation": Badge("Probation", "Returning from a ban", "#E2574C", "#B3261E"),
    "sr-warning": WARNING,
    "sr-danger": WARNING,
    "sr-clean": Badge("Good Driver", "This driver has a low number of incidents per race", "#5B95D6", "#2F64A8"),
    "sr-saint": Badge("Trusted Racer", "One of the safest players on the service", "#1EFF6B", "#0F8F3C"),
    "s397": Badge("S397", "A staff member from Studio 397", "#E8C14A", "#A07A00"),
    "irl-driver": Badge("IRL Driver", "A validated real-world racing driver", "#E8C14A", "#A07A00"),
    "content-creator": Badge("Content Creator", "A recognised content creator", "#B48CF2", "#6D3FC0"),
    "early-access": Badge("Early Access", "An early access player", "#7FD6DF", "#1C8A96"),
    "test-driver": Badge("Test Driver", "A Le Mans Ultimate test driver", "#7FD6DF", "#1C8A96"),
}

logger = logging.getLogger(__name__)


def badge_info(badge: str) -> Badge | None:
    """Game name, description & colors of badge, None if not a game badge"""
    return BADGES.get(badge.strip().lower())


def icon_url(badge: str) -> str:
    return f"{ICON_HOST}/badges/{badge}.svg"


def download(url: str) -> bytes:
    """Body of url, empty if failed or too large"""
    request = urllib.request.Request(url, headers={"User-Agent": "NeoPedal"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            if response.status != 200:
                return b""
            body = response.read(MAX_ICON_BYTES + 1)
    except (OSError, ValueError):
        return b""
    return body if len(body) <= MAX_ICON_BYTES else b""


class BadgeIcons:
    """Cache of badge icons, fetched in background"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._queued: set[str] = set()
        self._failed: dict[str, float] = {}  # badge -> time download failed
        self._thread: threading.Thread | None = None
        self.version = 0  # grows with each icon saved

    def icon_file(self, badge: str) -> str:
        """Cache file of badge icon (may not exist), "" if badge not in game list"""
        key = badge.strip().lower()
        if key not in BADGES:
            return ""
        return os.path.join(cfg.path.game_image, ICON_FOLDER, f"{key}.svg")

    def file(self, badge: str) -> str:
        """Cached icon file, "" if not cached yet (then fetched in background) or unknown badge"""
        path = self.icon_file(badge)
        if not path:
            return ""
        if os.path.isfile(path):
            return path
        self.request(badge.strip().lower())
        return ""

    def request(self, key: str) -> None:
        with self._lock:
            if key in self._queued or time.time() - self._failed.get(key, -RETRY_SECONDS) < RETRY_SECONDS:
                return
            self._queued.add(key)
            self._jobs.put(key)  # under lock: thread never leaves with this job waiting
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, daemon=True, name="Badge icons")
                self._thread.start()

    def _run(self) -> None:
        while True:
            try:
                key = self._jobs.get(timeout=5.0)
            except queue.Empty:
                with self._lock:
                    if self._jobs.empty():
                        self._thread = None
                        return
                continue
            try:
                self.fetch(key)
            except Exception:  # fetching stops for this icon only
                logger.exception("BADGE ICONS: fetch failed")
            finally:
                with self._lock:
                    self._queued.discard(key)

    def fetch(self, key: str) -> bool:
        """Icon downloaded & saved in cache, True if saved"""
        target = self.icon_file(key)
        if not target or os.path.isfile(target):
            return False
        body = download(icon_url(key))
        if not body.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"<"):  # not an SVG
            with self._lock:
                self._failed[key] = time.time()
            return False
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            atomic_replace(target, body, fsync=False)  # cache: downloaded again if lost
        except OSError:
            logger.warning("BADGE ICONS: icon not saved: %s", target)
            return False
        with self._lock:
            self.version += 1
        return True


icons = BadgeIcons()
