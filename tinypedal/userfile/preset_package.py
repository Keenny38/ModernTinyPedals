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
Preset package: export & import preset, style presets and notes as single zip file

Package layout:
    manifest.json
    presets/<preset>.json
    styles/<brakes|brands|classes|compounds|heatmap|tracks>.json
    tracknotes/<track>.tptn
    pacenotes/<track>.tppn
"""

from __future__ import annotations

import json
import logging
import os
import zipfile
from typing import NamedTuple

from ..const_file import FileExt
from ..validator import is_allowed_filename

logger = logging.getLogger(__name__)

PACKAGE_FORMAT = "tinypedal-preset-package"
PACKAGE_VERSION = 1
STYLE_FILES = tuple(
    f"{name}{FileExt.JSON}" for name in ("brakes", "brands", "classes", "compounds", "heatmap", "tracks")
)
NOTES_FOLDERS = {  # package folder: allowed file extensions
    "tracknotes": (FileExt.TPTN,),
    "pacenotes": (FileExt.TPPN,),
}
MAX_FILE_SIZE = 50 * 1024 * 1024  # refuse suspiciously large entry


class ImportResult(NamedTuple):
    """Import result"""

    presets: list[str]  # imported preset file names (may be renamed)
    styles: list[str]  # imported style preset file names
    notes: int  # number of imported notes files
    skipped: list[str]  # skipped entries


def export_preset_package(
    zip_filename: str,
    settings_path: str,
    preset_filename: str,
    include_styles: bool = True,
    notes_paths: dict[str, str] | None = None,
) -> int:
    """Export preset package

    Args:
        zip_filename: output zip file full path.
        settings_path: preset folder.
        preset_filename: preset file name (with extension).
        include_styles: include style presets.
        notes_paths: package notes folder (key of NOTES_FOLDERS): user notes folder path.

    Returns:
        Number of files added.
    """
    count = 0
    with zipfile.ZipFile(zip_filename, "w", compression=zipfile.ZIP_DEFLATED) as package:
        manifest = {
            "format": PACKAGE_FORMAT,
            "version": PACKAGE_VERSION,
            "preset": preset_filename,
        }
        package.writestr("manifest.json", json.dumps(manifest, indent=4))
        package.write(f"{settings_path}{preset_filename}", f"presets/{preset_filename}")
        count += 1
        if include_styles:
            for style_file in STYLE_FILES:
                if os.path.exists(f"{settings_path}{style_file}"):
                    package.write(f"{settings_path}{style_file}", f"styles/{style_file}")
                    count += 1
        for folder, filepath in (notes_paths or {}).items():
            extensions = NOTES_FOLDERS.get(folder, ())
            if not filepath or not os.path.isdir(filepath):
                continue
            for filename in sorted(os.listdir(filepath)):
                if filename.lower().endswith(extensions):
                    package.write(os.path.join(filepath, filename), f"{folder}/{filename}")
                    count += 1
    logger.info("USERDATA: exported %s files to %s", count, zip_filename)
    return count


def unique_filename(filepath: str, filename: str) -> str:
    """Get unique file name in folder, add " (n)" suffix if exists"""
    basename, extension = os.path.splitext(filename)
    candidate = filename
    index = 1
    while os.path.exists(f"{filepath}{candidate}"):
        index += 1
        candidate = f"{basename} ({index}){extension}"
    return candidate


def read_manifest(package: zipfile.ZipFile) -> dict:
    """Read & verify package manifest, raise ValueError if invalid"""
    try:
        manifest = json.loads(package.read("manifest.json").decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("not a TinyPedal preset package") from error
    if not isinstance(manifest, dict) or manifest.get("format") != PACKAGE_FORMAT:
        raise ValueError("not a TinyPedal preset package")
    if manifest.get("version", 0) > PACKAGE_VERSION:
        raise ValueError("package made by newer Modern Tiny Pedals version")
    return manifest


def import_preset_package(
    zip_filename: str,
    settings_path: str,
    overwrite_styles: bool = False,
    notes_paths: dict[str, str] | None = None,
) -> ImportResult:
    """Import preset package

    Presets are never overwritten (renamed if exists). Style presets are imported
    only if overwrite_styles is True. Notes are imported only if not exist.
    Only file name of each entry is used, so package cannot write outside target folders.

    Raises:
        ValueError: invalid package.
        OSError: file error.
    """
    presets: list[str] = []
    styles: list[str] = []
    notes = 0
    skipped: list[str] = []
    notes_paths = notes_paths or {}
    with zipfile.ZipFile(zip_filename, "r") as package:
        read_manifest(package)
        for info in package.infolist():
            if info.is_dir() or info.filename == "manifest.json":
                continue
            folder, _, filename = info.filename.replace("\\", "/").rpartition("/")
            filename = os.path.basename(filename)
            if not filename or "/" in folder or info.file_size > MAX_FILE_SIZE:
                skipped.append(info.filename)
                continue
            data = package.read(info)
            if folder == "presets" and filename.lower().endswith(FileExt.JSON):
                if not is_allowed_filename(filename[:-len(FileExt.JSON)]) or not is_json_dict(data):
                    skipped.append(info.filename)
                    continue
                target = unique_filename(settings_path, filename)
                write_file(f"{settings_path}{target}", data)
                presets.append(target)
            elif folder == "styles" and filename in STYLE_FILES:
                if not overwrite_styles or not is_json_dict(data):
                    skipped.append(info.filename)
                    continue
                write_file(f"{settings_path}{filename}", data)
                styles.append(filename)
            elif folder in NOTES_FOLDERS and filename.lower().endswith(NOTES_FOLDERS[folder]):
                filepath = notes_paths.get(folder, "")
                if not filepath or os.path.exists(os.path.join(filepath, filename)):
                    skipped.append(info.filename)
                    continue
                write_file(os.path.join(filepath, filename), data)
                notes += 1
            else:
                skipped.append(info.filename)
    logger.info(
        "USERDATA: imported %s preset(s), %s style(s), %s notes from %s",
        len(presets), len(styles), notes, zip_filename,
    )
    return ImportResult(presets, styles, notes, skipped)


def is_json_dict(data: bytes) -> bool:
    """Check if data is valid json object"""
    try:
        return isinstance(json.loads(data.decode("utf-8")), dict)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False


def write_file(filename: str, data: bytes):
    """Write file"""
    with open(filename, "wb") as file:
        file.write(data)
