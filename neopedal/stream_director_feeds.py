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
Broadcast graphics state shared by the Broadcast Director page (writer) & the stream server threads (readers):
feeds answered as soon as they change (long poll), places of graphics moved in a layout editor (config file),
track outline of the session (see stream_director)
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
from typing import Any

logger = logging.getLogger(__name__)

WAIT_SECONDS = 1.0  # request waits this long for a change
WATCH_SECONDS = 5.0  # source counted as shown this long after its last request
SCALE_LIMITS = (0.3, 3.0)  # size factor of a placed graphic
PLACE_LIMITS = (-0.5, 1.5)  # place of a graphic (fractions of the canvas), a little outside allowed


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
