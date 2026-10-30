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
import lzma
import os
import zipfile
import zlib
from collections.abc import Mapping, Sequence
from contextlib import suppress
from typing import Any, NamedTuple

from ..const_app import LEGACY_PACKAGE
from ..const_file import FileExt
from ..validator import is_allowed_filename, is_reserved_filename, load_json_strict
from . import atomic_replace, replace_retry, sync_folder
from .private_option import keep_receiver_options

logger = logging.getLogger(__name__)

PACKAGE_FORMAT = "neopedal-preset-package"
PACKAGE_FORMATS = (PACKAGE_FORMAT, f"{LEGACY_PACKAGE}-preset-package")  # packages of versions until 0.23.0 too
PACKAGE_VERSION = 1
STYLE_FILES = tuple(
    f"{name}{FileExt.JSON}" for name in ("brakes", "brands", "classes", "compounds", "heatmap", "tracks")
)
NOTES_FOLDERS = {  # package folder: allowed file extensions
    "tracknotes": (FileExt.TPTN,),
    "pacenotes": (FileExt.TPPN,),
}
MAX_FILE_SIZE = 50 * 1024 * 1024  # refuse suspiciously large entry
MAX_MANIFEST_SIZE = 64 * 1024  # manifest is a few lines
# Whole package refused above these (zip bomb filling the disk): one preset, styles & notes of a few tracks
# weigh a few MB, a package of many presets a few tens
MAX_ENTRIES = 1000
MAX_PRESETS = 200
MAX_TOTAL_SIZE = 100 * 1024 * 1024  # uncompressed size of every entry, as announced by the zip directory
WINDOWS_RESERVED_CHARS = frozenset('<>:"|?*')  # ":" would write an NTFS alternate stream


class ImportResult(NamedTuple):
    """Import result"""

    presets: list[str]  # imported preset file names (may be renamed)
    styles: list[str]  # imported style preset file names
    notes: int  # number of imported notes files
    skipped: list[str]  # skipped entries
    kept: tuple[str, ...] = ()  # "preset: section.option" given the receiver's value (local file, game connection)


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

    Written to temporary file, then replaces target: existing package kept on error.

    Returns:
        Number of files added.
    """
    temp_name = f"{zip_filename}.part"
    try:
        count = write_preset_package(temp_name, settings_path, preset_filename, include_styles, notes_paths)
        replace_retry(temp_name, zip_filename)
    except BaseException:
        with suppress(OSError):
            os.remove(temp_name)
        raise
    logger.info("USERDATA: exported %s files to %s", count, zip_filename)
    return count


def write_preset_package(
    zip_filename: str,
    settings_path: str,
    preset_filename: str,
    include_styles: bool,
    notes_paths: dict[str, str] | None,
) -> int:
    """Write preset package zip file, returns number of files added"""
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
    """Read & verify package manifest, raise ValueError if invalid (also encrypted or corrupted)"""
    try:
        info = package.getinfo("manifest.json")
        if info.file_size > MAX_MANIFEST_SIZE:  # never inflated whole (zip bomb)
            raise ValueError("manifest too large")
        manifest = load_json_strict(read_entry(package, info).decode("utf-8"))
    except (KeyError, ValueError) as error:  # UnicodeDecodeError & JSONDecodeError included
        raise ValueError("not a NeoPedal preset package") from error
    if not isinstance(manifest, dict) or manifest.get("format") not in PACKAGE_FORMATS:
        raise ValueError("not a NeoPedal preset package")
    version = manifest.get("version", 0)
    if not isinstance(version, (int, float)) or isinstance(version, bool):  # never a TypeError below
        raise ValueError("not a NeoPedal preset package")
    if version > PACKAGE_VERSION:
        raise ValueError("package made by newer NeoPedal version")
    return manifest


def import_preset_package(
    zip_filename: str,
    settings_path: str,
    overwrite_styles: bool = False,
    notes_paths: dict[str, str] | None = None,
    receiver: Mapping[str, Mapping[str, Any]] | None = None,
) -> ImportResult:
    """Import preset package

    Presets are never overwritten (renamed if exists). Style presets are imported
    only if overwrite_styles is True. Notes are imported only if not exist.
    Only file name of each entry is used, so package cannot write outside target folders.
    Local file & game connection options of presets get the values of receiver (loaded preset),
    see private_option. Package of too many entries or too large is refused before anything is written.

    Raises:
        ValueError: invalid package.
        OSError: file error.
    """
    presets: list[str] = []
    styles: list[str] = []
    notes = 0
    skipped: list[str] = []
    kept: list[str] = []
    written_folders: set[str] = set()  # flushed to disk once, files are written without fsync
    notes_paths = notes_paths or {}
    with zipfile.ZipFile(zip_filename, "r") as package:
        read_manifest(package)
        check_package_size(package.infolist())
        for info in package.infolist():
            if info.is_dir() or info.filename == "manifest.json":
                continue
            folder, _, filename = info.filename.replace("\\", "/").rpartition("/")
            filename = os.path.basename(filename)
            if not filename or "/" in folder or info.file_size > MAX_FILE_SIZE:
                skipped.append(info.filename)
                continue
            if not is_windows_filename(filename):  # never a stray file or failed import of the rest
                logger.info("USERDATA: skipped package entry of invalid file name %r", info.filename)
                skipped.append(info.filename)
                continue
            data = read_entry(package, info)
            if folder == "presets" and filename.lower().endswith(FileExt.JSON):
                preset = load_json_dict(data)
                if not is_allowed_filename(filename[:-len(FileExt.JSON)]) or preset is None:
                    skipped.append(info.filename)
                    continue
                changed = keep_receiver_options(preset, receiver)
                if changed:  # written again from parsed data, else bytes kept as they are
                    data = json.dumps(preset, indent=4).encode("utf-8")
                target = unique_filename(settings_path, filename)
                write_file(f"{settings_path}{target}", data, written_folders)
                presets.append(target)
                kept.extend(f"{target[:-len(FileExt.JSON)]}: {option}" for option in changed)
            elif folder == "styles" and filename in STYLE_FILES:
                if not overwrite_styles or not is_json_dict(data):
                    skipped.append(info.filename)
                    continue
                write_file(f"{settings_path}{filename}", data, written_folders, fsync=True)  # replaces user's file
                styles.append(filename)
            elif folder in NOTES_FOLDERS and filename.lower().endswith(NOTES_FOLDERS[folder]):
                filepath = notes_paths.get(folder, "")
                if not filepath or os.path.exists(os.path.join(filepath, filename)):
                    skipped.append(info.filename)
                    continue
                write_file(os.path.join(filepath, filename), data, written_folders)
                notes += 1
            else:
                skipped.append(info.filename)
    for folder in written_folders:
        sync_folder(folder)
    logger.info(
        "USERDATA: imported %s preset(s), %s style(s), %s notes from %s",
        len(presets), len(styles), notes, zip_filename,
    )
    if kept:
        logger.info("USERDATA: local file & game connection options kept as receiver's: %s", ", ".join(kept))
    return ImportResult(presets, styles, notes, skipped, tuple(kept))


def check_package_size(infos: Sequence[zipfile.ZipInfo]) -> None:
    """Refuse package of too many entries, presets, or too large once uncompressed (sizes of zip directory:
    reading an entry never inflates more than its announced size), raise ValueError"""
    if len(infos) > MAX_ENTRIES:
        raise ValueError("too many files in package")
    if sum(1 for info in infos if info.filename.replace("\\", "/").startswith("presets/")) > MAX_PRESETS:
        raise ValueError("too many presets in package")
    if sum(info.file_size for info in infos) > MAX_TOTAL_SIZE:
        raise ValueError("package too large once uncompressed")


def is_windows_filename(filename: str) -> bool:
    """Check file name can be written as is on Windows (no reserved character, device name, trailing dot)"""
    return (
        not any(char in WINDOWS_RESERVED_CHARS or ord(char) < 32 for char in filename)
        and not filename.endswith((".", " "))
        and not is_reserved_filename(filename)
    )


def read_entry(package: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """Read package entry, raise ValueError if corrupted, encrypted or unsupported compression"""
    try:
        return package.read(info)
    except (zipfile.BadZipFile, zlib.error, lzma.LZMAError, EOFError, RuntimeError, NotImplementedError) as error:
        raise ValueError(f"unable to read {info.filename} ({error})") from error


def is_json_dict(data: bytes) -> bool:
    """Check if data is valid json object (NaN & Infinity not allowed)"""
    return load_json_dict(data) is not None


def load_json_dict(data: bytes) -> dict | None:
    """Valid json object of data (NaN & Infinity not allowed), None if invalid"""
    try:
        value = load_json_strict(data.decode("utf-8-sig"))
    except ValueError:  # UnicodeDecodeError & JSONDecodeError included
        return None
    return value if isinstance(value, dict) else None


def write_file(filename: str, data: bytes, written_folders: set[str] | None = None, fsync: bool = False) -> None:
    """Write file atomically (temporary file replaces target): existing file never left half-written

    New files (presets, notes) are not flushed to disk one by one (an import of many files runs on the GUI
    thread, and can be done again): their folder is noted in written_folders, flushed once by the caller
    (see sync_folder). A file replacing the user's own (styles) is flushed before the replace, as always.
    """
    atomic_replace(filename, data, fsync=fsync)
    if written_folders is not None:
        written_folders.add(os.path.dirname(filename))
