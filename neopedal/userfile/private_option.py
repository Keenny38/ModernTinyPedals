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
Options that belong to the computer a preset runs on: local files & folders, game API connection

A preset made elsewhere (preset package, dropped preset file) gets the receiver's own values of these
options. Its paths could point to a network share (checked or opened at once: Windows sign-in hash sent
to the share host), its game API address to another host (every game REST request, pit menu writes &
camera changes sent there, its answers read by the app). Overlay settings packages never write them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .. import regex_pattern as rxp

PRIVATE_OPTION = re.compile(f"{rxp.CFG_USER_PATH}|{rxp.CFG_USER_IMAGE}|file_name")
CONNECTION_OPTIONS = frozenset(("url_host", "url_port"))  # game API sections (LMU, rF2)


def is_private(key: str) -> bool:
    """Option pointing to a local file or folder"""
    return bool(PRIVATE_OPTION.search(key))


def is_receiver_option(key: str) -> bool:
    """Option of an imported preset replaced by the receiver's value (local file, game connection)"""
    return key in CONNECTION_OPTIONS or is_private(key)


def keep_receiver_options(preset: dict, receiver: Mapping[str, Mapping[str, Any]] | None = None) -> list[str]:
    """Replace local file & game connection options of an imported preset by the receiver's values (in place)

    Args:
        preset: imported preset (section: options).
        receiver: receiver's preset of same structure (loaded preset). Option it has not: removed, so loading
            the preset uses the default value.

    Returns:
        "section.option" of each option changed or removed (same value as receiver's not listed).
    """
    changed: list[str] = []
    receiver = receiver or {}
    for section, options in preset.items():
        if not isinstance(options, dict):
            continue
        own = receiver.get(section)
        for key in [key for key in options if isinstance(key, str) and is_receiver_option(key)]:
            if isinstance(own, Mapping) and key in own:
                if options[key] != own[key]:
                    options[key] = own[key]
                    changed.append(f"{section}.{key}")
            else:
                del options[key]
                changed.append(f"{section}.{key}")
    return changed
