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
Personal best share code: one line of text pasted in a chat (Discord...), read back by Driver Stats Viewer

    NP1:pb:<base64url of zlib of JSON {"d": data, "v": app version}>

Data: track, vehicle (driver stats keys), class, lap time (s), date (Unix time, 0 if unknown), game version &
driver name. A code is found anywhere inside pasted text; anything not matching is refused (None).
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
import zlib
from typing import NamedTuple

PREFIX = "NP1:pb:"
CODE = re.compile(r"NP1:pb:([A-Za-z0-9_\-]+=*)")
MAX_CODE = 4096  # characters of a code read (a code is about 200)
MAX_TEXT = 200  # characters kept of each text field


class SharedBest(NamedTuple):
    """Personal best of a share code"""

    track: str
    vehicle: str
    vehicle_class: str
    laptime: float
    time: float = 0.0
    game_version: str = ""
    driver: str = ""


def encode(best: SharedBest, app_version: str = "") -> str:
    """Share code of a personal best"""
    data = {"track": best.track, "vehicle": best.vehicle, "class": best.vehicle_class,
            "laptime": round(best.laptime, 3), "time": round(best.time), "version": best.game_version,
            "driver": best.driver}
    payload = json.dumps({"d": data, "v": app_version}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return PREFIX + base64.urlsafe_b64encode(zlib.compress(payload, 9)).decode("ascii")


def _text(value: object) -> str:
    """Text field, stripped of markup characters (shown in rich text)"""
    if not isinstance(value, str):
        return ""
    return re.sub(r"[<>&]", "", value).strip()[:MAX_TEXT]


def decode(text: str) -> SharedBest | None:
    """Personal best of the first share code found in text, None if none or not valid"""
    match = CODE.search(text or "")
    if match is None or len(match[1]) > MAX_CODE:
        return None
    try:
        raw = zlib.decompressobj().decompress(base64.urlsafe_b64decode(match[1]), 64 * 1024)
        document = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, zlib.error, UnicodeDecodeError):
        return None
    data = document.get("d") if isinstance(document, dict) else None
    if not isinstance(data, dict):
        return None
    laptime = data.get("laptime")
    when = data.get("time", 0)
    if (isinstance(laptime, bool) or not isinstance(laptime, (int, float)) or not math.isfinite(laptime)
            or not 0 < laptime < 3600):
        return None
    if isinstance(when, bool) or not isinstance(when, (int, float)) or not math.isfinite(when) or when < 0:
        when = 0
    track, vehicle = _text(data.get("track")), _text(data.get("vehicle"))
    if not track or not vehicle:
        return None
    return SharedBest(track, vehicle, _text(data.get("class")), float(laptime), float(when),
                      _text(data.get("version")), _text(data.get("driver")))
