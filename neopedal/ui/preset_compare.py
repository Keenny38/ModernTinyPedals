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
Preset comparison files: presets read & copied values saved for the compare panel of the Presets page
(qml/config/PresetComparePanel.qml, quick/preset_tools_backend.py). The former Preset Comparison tool page
opens that panel (tools_view.show_preset_compare).
"""

from __future__ import annotations

from typing import Any

from .. import loader
from ..setting import RELOAD_ACCESS_TIMEOUT, cfg, load_setting_json_file, save_and_verify_json_file
from ..userfile.json_setting import copy_setting


def load_preset(filename: str) -> dict:
    """Load preset file (validated, missing options filled with default)"""
    if cfg.is_loaded(filename):
        return copy_setting(cfg.user.setting)
    return load_preset_file(filename)


def load_preset_file(filename: str) -> dict:
    """Load preset file not loaded by app (thread safe: file read & validation only)

    Short retry on a locked file (RELOAD_ACCESS_TIMEOUT): called on the GUI thread, never waits seconds.
    """
    return load_setting_json_file(filename=filename, filepath=cfg.path.settings, dict_def=cfg.default.setting,
                                  access_timeout=RELOAD_ACCESS_TIMEOUT)


def save_preset_edits(edits: dict[str, dict[tuple[str, str], Any]]) -> list[str]:
    """Write copied values (file name: value by (section, key)) into a fresh copy of each preset

    Presets are read when shown, then may change elsewhere (loaded preset: overlays moved, options edited),
    so only copied values are written. Loaded preset is live (saved by app, then reloaded), others are read
    from file again.

    Returns:
        Presets not saved (locked or file not written).
    """
    reload_loaded = False
    failed = []
    for filename in sorted(edits):
        if filename in cfg.user.filelock:  # locked meanwhile: never changed
            failed.append(filename)
            continue
        is_loaded = cfg.is_loaded(filename)
        preset = cfg.user.setting if is_loaded else load_preset(filename)
        for (section, key), value in edits[filename].items():
            preset.setdefault(section, {})[key] = value
        if is_loaded:
            cfg.save(0)
            reload_loaded = True
        elif not save_and_verify_json_file(
                dict_user=preset, filename=filename, filepath=cfg.path.settings,
                max_attempts=cfg.max_saving_attempts):
            failed.append(filename)
    if reload_loaded:
        cfg.set_next_to_load(cfg.filename.setting)
        loader.reload(reload_preset=True)  # waits for saving
    return failed
