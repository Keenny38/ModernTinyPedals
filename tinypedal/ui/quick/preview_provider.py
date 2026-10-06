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
Overlay pictures served to QML pages by an image provider (image://overlaypreview/<key>?v=<serial>)

Pictures live in one store shared by every QML engine (Overlays page, Overlay Options, Setup Wizard):
each engine gets its own provider reading the store (an engine owns its providers). The serial in the
URL changes only when the picture of a key changes, so QML Image caches stay valid and a page reloads
only the pictures that changed (no PNG encoding, no base64 strings in models).

Async QML Images call the provider from Qt's image reader thread: the store is guarded by a lock and
hands out copies.
"""

from __future__ import annotations

import itertools
import threading
from urllib.parse import quote, unquote

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlEngine, QQmlImageProviderBase
from PySide6.QtQuick import QQuickImageProvider

PROVIDER_ID = "overlaypreview"
URL_PREFIX = f"image://{PROVIDER_ID}/"


class PreviewStore:
    """Thread-safe pictures by key, each with a serial changed when its picture changes"""

    def __init__(self):
        self._lock = threading.Lock()
        self._images: dict[str, tuple[int, QImage]] = {}
        self._serials = itertools.count(1)
        self._owners = itertools.count(1)

    def new_prefix(self, name: str) -> str:
        """Unique key prefix of a picture owner (backend), see release"""
        return f"{name}{next(self._owners)}/"

    def put(self, key: str, image: QImage) -> str:
        """Store picture of key, URL for QML (same URL if picture unchanged)"""
        with self._lock:
            current = self._images.get(key)
            if current is not None and current[1] == image:
                return preview_url(key, current[0])
            serial = next(self._serials)
            self._images[key] = (serial, QImage(image))  # implicitly shared copy: caller may paint on its own
        return preview_url(key, serial)

    def get(self, key: str) -> QImage | None:
        """Copy of picture of key (any thread), None if missing"""
        with self._lock:
            current = self._images.get(key)
            return None if current is None else current[1].copy()

    def discard(self, key: str):
        with self._lock:
            self._images.pop(key, None)

    def release(self, prefix: str):
        """Drop pictures of keys starting with prefix (owner deleted)"""
        with self._lock:
            for key in [key for key in self._images if key.startswith(prefix)]:
                del self._images[key]

    def __len__(self) -> int:
        with self._lock:
            return len(self._images)


STORE = PreviewStore()


def preview_url(key: str, serial: int) -> str:
    return f"{URL_PREFIX}{quote(key, safe='')}?v={serial}"


def key_of(image_id: str) -> str:
    """Store key from image provider id ('<key>?v=<serial>', maybe still percent encoded)"""
    return unquote(image_id.split("?", 1)[0])


class PreviewProvider(QQuickImageProvider):
    """Image provider of one QML engine, reads the shared store"""

    def __init__(self, store: PreviewStore = STORE):
        super().__init__(QQmlImageProviderBase.ImageType.Image)
        self._store = store

    def requestImage(self, id: str, size: QSize, requestedSize: QSize) -> QImage:
        image = self._store.get(key_of(id))
        if image is None:
            return QImage()
        if size is not None:
            size.setWidth(image.width())
            size.setHeight(image.height())
        return fit_image(image, requestedSize)


def fit_image(image: QImage, requested: QSize) -> QImage:
    """Picture scaled down to requested size (QML sourceSize), never scaled up"""
    if requested.width() <= 0 and requested.height() <= 0:
        return image
    width = requested.width() if requested.width() > 0 else image.width()
    height = requested.height() if requested.height() > 0 else image.height()
    if image.width() <= width and image.height() <= height:
        return image
    scaled = image.scaled(
        QSize(width, height), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    scaled.setDevicePixelRatio(1)
    return scaled


def install_provider(engine: QQmlEngine):
    """Serve image://overlaypreview/ in engine (once per engine), before loading a page using it"""
    if engine.imageProvider(PROVIDER_ID) is None:
        engine.addImageProvider(PROVIDER_ID, PreviewProvider())
