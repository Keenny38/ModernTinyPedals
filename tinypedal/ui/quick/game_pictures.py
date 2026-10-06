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
Game pictures for app pages: car brand & circuit logos, car & circuit pictures as file URLs

Pictures come from the game (userfile.game_images), own brand logos (brand logo folder) first.
Logos too close to page background get a readable copy (white logo on light theme, black logo on dark). Pages ask again when pictures
arrive (`notifier().changed`, grouped: game lists bring dozens of logos at once).
"""

from __future__ import annotations

import os
from contextlib import suppress

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QGuiApplication, QPalette

from ...setting import cfg
from ...userfile.custom_image import brand_logo_file, logo_for_background
from ...userfile.game_images import images

REFRESH_DELAY = 400  # ms, pictures arriving together refresh pages once


def file_url(path: str) -> str:
    """URL of local file for QML Image, empty if no file"""
    return QUrl.fromLocalFile(os.path.abspath(path)).toString() if path else ""


def light_theme() -> bool:
    """Whether app pages are light (dark logos needed)"""
    app = QGuiApplication.instance()
    if app is None:
        return False
    return QGuiApplication.palette().color(QPalette.ColorRole.Window).lightness() > 128


def brand_logo_url(vehicle_name: str = "", brand: str = "") -> str:
    """Logo of car brand: brand of game car list by vehicle name, else brand or car model text"""
    if not vehicle_name and not brand:
        return ""
    return file_url(brand_logo_file(cfg.path.brand_logo, images.brand(vehicle_name, brand), light_theme(),
                                    vehicle_name))


def track_logo_url(*names: str) -> str:
    """Logo of circuit from any of its names"""
    return file_url(logo_for_background(images.track_logo(*names), light_theme()))


def track_picture_url(*names: str, large: bool = False) -> str:
    """Picture of circuit from any of its names (card size, or large)"""
    return file_url(images.track_picture(*names, large=large))


def car_picture_url(vehicle_name: str, large: bool = False) -> str:
    """Front picture of car by vehicle name (thumbnail, or large)"""
    return file_url(images.car_picture(vehicle_name, large=large))


class LogoCache:
    """URLs of logos asked on every update (live lists): looked for once per name, again once game
    pictures change"""

    def __init__(self):
        self._urls: dict[tuple[str, str, str], str] = {}
        self._version = -1

    def _get(self, kind: str, first: str, second: str) -> str:
        if self._version != images.version:
            self._version = images.version
            self._urls.clear()
        key = (kind, first, second)
        url = self._urls.get(key)
        if url is None:
            url = self._urls[key] = brand_logo_url(first, second) if kind == "brand" else track_logo_url(first, second)
        return url

    def brand(self, vehicle_name: str, brand: str = "") -> str:
        return self._get("brand", vehicle_name, brand)

    def track(self, name: str, other_name: str = "") -> str:
        return self._get("track", name, other_name)


class PictureNotifier(QObject):
    """Tells pages game pictures changed (UI thread, grouped)"""

    changed = Signal()
    _arrived = Signal()  # emitted on fetch thread, delivered in UI thread

    def __init__(self):
        super().__init__()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REFRESH_DELAY)
        self._timer.timeout.connect(self.changed)
        self._arrived.connect(self._timer.start)
        images.add_listener(self._picture_arrived)

    def _picture_arrived(self):
        """Fetch thread: hand over to UI thread (nothing once app objects are gone)"""
        with suppress(RuntimeError):
            self._arrived.emit()


_notifier: PictureNotifier | None = None


def notifier() -> PictureNotifier:
    """Notifier of game picture changes (created in UI thread on first use, lives with app)"""
    global _notifier
    if _notifier is None:
        _notifier = PictureNotifier()
    return _notifier
