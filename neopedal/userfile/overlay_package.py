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
Overlay settings package: settings of one or several overlays as single zip file, to share

Package layout:
    manifest.json        format, app & setting version, screen of positions, overlay names
    overlays/<name>.json options changed from default, plus position

Only options changed from default are written (small file): the receiver gets default values plus
these ones, so the overlay looks the same. Overlay state ("enable") and options pointing to local
files (folders, pictures, file names) are never shared. Unknown overlays & options (other app
version) are left out when read, values of the wrong type too.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import zipfile
from collections.abc import Collection, Mapping
from contextlib import suppress
from typing import Any, NamedTuple

from .. import regex_pattern as rxp
from ..const_common import VERSION_NA
from ..validator import load_json_strict
from . import replace_retry
from .preset_package import MAX_MANIFEST_SIZE, read_entry

logger = logging.getLogger(__name__)

PACKAGE_FORMAT = "neopedal-overlay-package"
PACKAGE_VERSION = 1
FOLDER = "overlays"
POSITION_KEYS = ("position_x", "position_y")
NOT_SHARED = frozenset(("enable",))  # receiver's overlay state kept
PRIVATE_OPTION = re.compile(f"{rxp.CFG_USER_PATH}|{rxp.CFG_USER_IMAGE}|file_name")
MAX_OVERLAY_SIZE = 1024 * 1024  # one overlay file: a few KB
MAX_ENTRIES = 1000
MAX_POSITION = 100_000
DEFAULT_SCREEN = (0, 0, 1920, 1080)


class OverlayPackage(NamedTuple):
    """Overlay settings read from package"""

    overlays: dict[str, dict]  # overlay name: options (known options of valid type)
    app_version: str  # app version that made the package, "" if unknown
    screen: tuple[int, int, int, int]  # screen positions were placed on (x, y, width, height)
    unknown: list[str]  # overlays not available in this version
    skipped: int  # options left out (unknown or wrong type)


def is_private(key: str) -> bool:
    """Option pointing to a local file or folder"""
    return bool(PRIVATE_OPTION.search(key))


def is_shared(key: str) -> bool:
    """Option written in package (overlay state & local files never)"""
    return key not in NOT_SHARED and not is_private(key)


def changed_options(options: Mapping[str, Any], default: Mapping[str, Any]) -> dict:
    """Shared options changed from default (positions not counted)"""
    return {
        key: value for key, value in options.items()
        if key in default and key not in POSITION_KEYS and is_shared(key) and default[key] != value
    }


def overlay_data(options: Mapping[str, Any], default: Mapping[str, Any]) -> dict:
    """Overlay options written in package: changed options, plus position"""
    data = changed_options(options, default)
    for key in POSITION_KEYS:
        if key in options:
            data[key] = options[key]
    return data


def export_overlay_package(
    zip_filename: str,
    overlays: Mapping[str, Mapping[str, Any]],
    defaults: Mapping[str, Mapping[str, Any]],
    app_version: str,
    setting_version: str,
    screen: tuple[int, int, int, int] = DEFAULT_SCREEN,
) -> int:
    """Export overlay settings package

    Args:
        zip_filename: output zip file full path.
        overlays: overlay name: options.
        defaults: default options of every overlay.
        app_version: app version (shown to receiver).
        setting_version: setting format version (older option names renamed when read).
        screen: screen positions are placed on (x, y, width, height).

    Written to temporary file, then replaces target: existing file kept on error.

    Returns:
        Number of overlays added.
    """
    temp_name = f"{zip_filename}.part"
    try:
        count = write_overlay_package(temp_name, overlays, defaults, app_version, setting_version, screen)
        replace_retry(temp_name, zip_filename)
    except BaseException:
        with suppress(OSError):
            os.remove(temp_name)
        raise
    logger.info("USERDATA: exported settings of %s overlay(s) to %s", count, zip_filename)
    return count


def write_overlay_package(
    zip_filename: str,
    overlays: Mapping[str, Mapping[str, Any]],
    defaults: Mapping[str, Mapping[str, Any]],
    app_version: str,
    setting_version: str,
    screen: tuple[int, int, int, int],
) -> int:
    """Write overlay settings package zip file, returns number of overlays added"""
    names = [name for name in overlays if name in defaults]
    with zipfile.ZipFile(zip_filename, "w", compression=zipfile.ZIP_DEFLATED) as package:
        manifest = {
            "format": PACKAGE_FORMAT,
            "version": PACKAGE_VERSION,
            "app_version": app_version,
            "setting_version": setting_version,
            "screen": list(screen),
            "overlays": names,
        }
        package.writestr("manifest.json", json.dumps(manifest, indent=4))
        for name in names:
            data = overlay_data(overlays[name], defaults[name])
            package.writestr(f"{FOLDER}/{name}.json", json.dumps(data, indent=4, sort_keys=True))
    return len(names)


def package_format(zip_filename: str) -> str:
    """Format of package manifest ("" if not a package, unreadable or damaged)"""
    try:
        with zipfile.ZipFile(zip_filename) as package:
            info = package.getinfo("manifest.json")
            if info.file_size > MAX_MANIFEST_SIZE:
                return ""
            manifest = load_json_strict(read_entry(package, info).decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return ""
    fmt = manifest.get("format") if isinstance(manifest, dict) else None
    return fmt if isinstance(fmt, str) else ""


def is_overlay_package(zip_filename: str) -> bool:
    """File is an overlay settings package"""
    return package_format(zip_filename) == PACKAGE_FORMAT


def read_manifest(package: zipfile.ZipFile) -> dict:
    """Read & verify package manifest, raise ValueError if invalid (also encrypted or corrupted)"""
    try:
        info = package.getinfo("manifest.json")
        if info.file_size > MAX_MANIFEST_SIZE:  # never inflated whole (zip bomb)
            raise ValueError("manifest too large")
        manifest = load_json_strict(read_entry(package, info).decode("utf-8"))
    except (KeyError, ValueError) as error:  # UnicodeDecodeError & JSONDecodeError included
        raise ValueError("not a NeoPedal overlay settings package") from error
    if not isinstance(manifest, dict) or manifest.get("format") != PACKAGE_FORMAT:
        raise ValueError("not a NeoPedal overlay settings package")
    version = manifest.get("version", 0)
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValueError("not a NeoPedal overlay settings package")
    if version > PACKAGE_VERSION:
        raise ValueError("package made by newer NeoPedal version")
    return manifest


def _number(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and abs(value) <= MAX_POSITION


def manifest_screen(manifest: Mapping[str, Any]) -> tuple[int, int, int, int]:
    """Screen positions were placed on, default screen if missing or invalid"""
    screen = manifest.get("screen")
    if (isinstance(screen, list) and len(screen) == 4 and all(map(_number, screen))
            and screen[2] > 0 and screen[3] > 0):
        return screen[0], screen[1], screen[2], screen[3]
    return DEFAULT_SCREEN


def same_type(value: Any, default: Any) -> bool:
    """Value can replace default value: on/off, number or text as default"""
    if isinstance(default, bool) or isinstance(value, bool):
        return isinstance(value, bool) and isinstance(default, bool)
    if isinstance(default, (int, float)):
        return isinstance(value, (int, float))
    return isinstance(value, str) and isinstance(default, str)


def updated_options(overlays: dict[str, dict], setting_version: Any) -> dict[str, dict]:
    """Options of older setting version renamed to current names (preset updates), as is if it fails"""
    from ..setting_preupdate import preupdate_user_setting
    from ..version_check import parse_version_string

    if not isinstance(setting_version, str):  # version unknown: no update guessed
        return overlays
    version = parse_version_string(setting_version)
    if version == VERSION_NA:
        return overlays
    updated = copy.deepcopy(overlays)
    try:
        preupdate_user_setting(version, updated)
    except Exception as error:  # update made for whole presets: options kept as written
        logger.info("USERDATA: overlay package not updated from setting version %s: %s", setting_version, error)
        return overlays
    return {name: options for name, options in updated.items() if isinstance(options, dict)}


def read_overlay_package(zip_filename: str, defaults: Mapping[str, Mapping[str, Any]]) -> OverlayPackage:
    """Read overlay settings package

    Args:
        zip_filename: package file.
        defaults: default options of every overlay available here.

    Only file name of each entry is used. Overlays not in defaults are listed as unknown, options not
    in defaults or of another type than default are left out (counted as skipped).

    Raises:
        ValueError: invalid package.
        OSError: file error.
    """
    overlays: dict[str, dict] = {}
    unknown: list[str] = []
    with zipfile.ZipFile(zip_filename, "r") as package:
        manifest = read_manifest(package)
        infos = package.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ValueError("too many files in package")
        for info in infos:
            folder, _, filename = info.filename.replace("\\", "/").rpartition("/")
            if info.is_dir() or folder != FOLDER or not filename.endswith(".json"):
                continue
            name = filename[:-5]
            if not name or name in overlays or name in unknown:
                continue
            if name not in defaults:
                unknown.append(name)
                continue
            if info.file_size > MAX_OVERLAY_SIZE:
                raise ValueError(f"{info.filename} too large")
            try:
                data = load_json_strict(read_entry(package, info).decode("utf-8-sig"))
            except ValueError as error:  # UnicodeDecodeError & JSONDecodeError included
                raise ValueError(f"unable to read {info.filename} ({error})") from error
            if not isinstance(data, dict):
                raise ValueError(f"unable to read {info.filename} (not overlay options)")
            overlays[name] = data
    overlays = updated_options(overlays, manifest.get("setting_version"))
    skipped = 0
    valid: dict[str, dict] = {}
    for name, options in overlays.items():
        default = defaults.get(name)
        if default is None:  # renamed by update to unknown name
            unknown.append(name)
            continue
        kept = {}
        for key, value in options.items():
            if (isinstance(key, str) and key in default and is_shared(key) and same_type(value, default[key])
                    and (key not in POSITION_KEYS or _number(value))):
                kept[key] = value
            else:
                skipped += 1
        valid[name] = kept
    app_version = manifest.get("app_version")
    return OverlayPackage(
        valid,
        app_version if isinstance(app_version, str) else "",
        manifest_screen(manifest),
        sorted(unknown),
        skipped,
    )


def scale_position(
    x: int, y: int, source: tuple[int, int, int, int], target: tuple[int, int, int, int],
) -> tuple[int, int]:
    """Position moved from source screen to target screen (same place in proportion)"""
    return (
        target[0] + round((x - source[0]) * target[2] / source[2]),
        target[1] + round((y - source[1]) * target[3] / source[3]),
    )


def overlay_values(
    options: Mapping[str, Any],
    saved: Mapping[str, Any],
    default: Mapping[str, Any],
    keep_positions: bool = True,
    source: tuple[int, int, int, int] = DEFAULT_SCREEN,
    target: tuple[int, int, int, int] = DEFAULT_SCREEN,
) -> dict:
    """Values set by imported overlay settings: every shared option of the package, default value for the
    ones not in it (sender kept them at default). State & local files untouched, position kept or taken
    from package (moved to this screen)

    Args:
        options: overlay options read from package.
        saved: overlay options of loaded preset.
        default: default options of overlay.
        keep_positions: receiver's position kept.
        source: screen of package positions.
        target: screen of this computer.
    """
    values = {
        key: options.get(key, default[key]) for key in saved
        if key in default and key not in POSITION_KEYS and is_shared(key)
    }
    if not keep_positions and all(key in options and key in saved for key in POSITION_KEYS):
        values["position_x"], values["position_y"] = scale_position(
            options["position_x"], options["position_y"], source, target)
    return values


def package_filename(labels: Collection[str]) -> str:
    """Default file name of package: overlay name if only one, else number of overlays"""
    if len(labels) == 1:
        label = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", next(iter(labels))).strip(" .") or "1"
        return f"NeoPedal-overlay-{label}.zip"
    return f"NeoPedal-overlays-{len(labels)}.zip"
