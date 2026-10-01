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
Preset share code: whole preset as one line of text, to paste in a chat or forum

Format: "MTP1:" + urlsafe base64 of zlib compressed preset json.
"""

from __future__ import annotations

import base64
import binascii
import json
import zlib
from typing import NamedTuple

from . import write_text_file

SHARE_PREFIX = "MTP1:"
MAX_PRESET_SIZE = 4 * 1024 * 1024  # decompressed bytes


class PresetSummary(NamedTuple):
    """Shown before import"""

    widgets: tuple[str, ...]  # enabled widgets
    modules: tuple[str, ...]  # enabled modules
    sections: int


def encode_preset(preset: dict) -> str:
    """Preset to share code"""
    raw = json.dumps(preset, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return SHARE_PREFIX + base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode("ascii")


def decode_preset(code: str) -> dict[str, dict]:
    """Share code to preset

    Raises:
        ValueError: invalid share code.
    """
    code = "".join(code.split())  # line breaks added by chat apps
    if not code.startswith(SHARE_PREFIX):
        raise ValueError("not a Modern Tiny Pedals share code")
    try:
        compressed = base64.urlsafe_b64decode(code[len(SHARE_PREFIX):].encode("ascii"))
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(compressed, MAX_PRESET_SIZE)
        if decompressor.unconsumed_tail:
            raise ValueError("preset too large")
        data = json.loads(raw.decode("utf-8"))
    except (binascii.Error, zlib.error, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("damaged share code, copy it again") from error
    if not isinstance(data, dict) or not data or not all(
            isinstance(key, str) and isinstance(value, dict) for key, value in data.items()):
        raise ValueError("share code does not contain a preset")
    return data


def save_preset_data(folder: str, filename: str, preset: dict) -> bool:
    """Write imported preset file"""
    return write_text_file(f"{folder}{filename}", json.dumps(preset, indent=4))


def summarize_preset(preset: dict, widget_names, module_names) -> PresetSummary:
    """Enabled widgets & modules of preset"""
    widgets = set(widget_names)
    modules = set(module_names)
    enabled = [name for name, options in preset.items() if isinstance(options, dict) and options.get("enable")]
    return PresetSummary(
        tuple(sorted(name for name in enabled if name in widgets)),
        tuple(sorted(name for name in enabled if name in modules)),
        len(preset),
    )
