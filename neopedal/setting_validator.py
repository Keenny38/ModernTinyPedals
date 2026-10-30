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
Setting validator function
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from . import regex_pattern as rxp
from . import version
from .const_common import VERSION_NA
from .hotkey.common import validate_hotkey
from .setting_preupdate import PENDING_STYLE_UPDATES, preupdate_global_setting, preupdate_user_setting
from .template.option_limits import clamp_to_limit
from .validator import is_clock_format, is_finite_number, is_hex_color
from .version_check import parse_version_string

logger = logging.getLogger(__name__)
# Values brought within limits by the last validation (option, value read, value kept): preset check, log.
# Cleared by each PresetValidator._validate (styles never clamp), so it holds one preset's values at most
CLAMPED: list[tuple[str, float, float]] = []


def clamp_value(key: str, dict_user: dict) -> None:
    """Number brought within the limit of its option (typed in file, imported, older limit): a value the
    options page refuses never reaches an overlay (huge sizes: memory, crash)"""
    value = dict_user[key]
    clamped = clamp_to_limit(key, value)
    if clamped != value:
        dict_user[key] = clamped
        CLAMPED.append((key, value, clamped))
        logger.info("SETTING: %s %s out of allowed values, %s used", key, value, clamped)


def normalize_display_orders(config: dict) -> dict:
    """Display orders made unique & not negative, order kept

    Same values (Overlay Options numbers the items it lists, options of the other design keep theirs) are
    shifted after one another in display order, then option order; a negative grid position crashes Qt
    layouts: all shifted. Shown order never changes.
    """
    keys = [key for key in config if key.startswith("display_order") and isinstance(config[key], int)
            and not isinstance(config[key], bool)]
    values = [config[key] for key in keys]
    if values and min(values) < 0:
        values = [value - min(values) for value in values]
        for key, value in zip(keys, values):
            config[key] = value
    if len(set(values)) == len(values):
        return config
    last: int | None = None
    for index in sorted(range(len(keys)), key=lambda index: (values[index], index)):
        value = values[index] if last is None else max(values[index], last + 1)
        config[keys[index]] = value
        last = value
    return config


def _get_preset_version(dict_user: dict, version_current: str) -> tuple[int, int, int]:
    """Get stored preset version, and update to current running version (never lowered)

    A file saved by a newer build (installed & source copies share settings folder) keeps its
    version: otherwise the newer build would run its one-time updates again on it.
    """
    # Check preset version
    preset_info = dict_user.get("preset")
    if not isinstance(preset_info, dict):
        dict_user["preset"] = {}  # create preset info section if missing
        preset_info = dict_user["preset"]
    preset_version = parse_version_string(preset_info.get("version", "0.0.0"))
    # Update preset version
    if not is_newer_version(preset_version, version_current):
        dict_user["preset"]["version"] = version_current
    return preset_version


def is_newer_version(preset_version: tuple[int, int, int], version_current: str) -> bool:
    """Preset saved by a newer build than this one"""
    return preset_version != VERSION_NA and preset_version > parse_version_string(version_current)


def _validate_style(dict_user: dict[str, dict], dict_def: Mapping[str, dict], info_def: Mapping[str, Any]) -> bool:
    """Validate style dict entries"""
    save_change = False
    for name, data in dict_user.items():
        # Reset invalid data set
        if not isinstance(data, dict):
            if name in dict_def:
                dict_user[name] = dict_def[name].copy()
            else:
                dict_user[name] = info_def.copy()
            save_change = True
            continue
        # Reset invalid value or add missing
        for key, default_value in info_def.items():
            # Accept int typed in float field (not bool)
            if (
                key in data
                and isinstance(default_value, float)
                and isinstance(data[key], int)
                and not isinstance(data[key], bool)
            ):
                data[key] = float(data[key])
                save_change = True
            if key not in data or not isinstance(data[key], type(default_value)):
                if name in dict_def:
                    data[key] = dict_def[name][key]
                else:
                    data[key] = default_value
                save_change = True
    return save_change


def update_former_compound_colors(dict_user: dict[str, dict]) -> bool:
    """Compounds still at their former default color (by symbol, or gray of compounds added on the fly) take
    the color of their name, colors you chose kept

    Returns:
        True if a color changed (file saved, old one backed up).
    """
    from .template.setting_compounds import FORMER_DEFAULT_COLORS, UNKNOWN_COMPOUND_COLOR, name_color

    changed = False
    for name, data in dict_user.items():
        symbol = data.get("symbol", "")
        color = data.get("color", "")
        if not isinstance(symbol, str) or not isinstance(color, str):
            continue
        if color.upper() not in (FORMER_DEFAULT_COLORS.get(symbol), UNKNOWN_COMPOUND_COLOR):
            continue
        new_color = name_color(name)
        if new_color != color.upper():
            data["color"] = new_color
            changed = True
    return changed


def update_former_class_colors(dict_user: dict[str, dict]) -> bool:
    """Classes still at their former default color take the new class color, colors you chose kept

    Returns:
        True if a color changed (file saved, old one backed up).
    """
    from .template.setting_classes import CLASS_COLORS, FORMER_DEFAULT_COLORS

    changed = False
    for name, data in dict_user.items():
        color = data.get("color", "")
        if isinstance(color, str) and name in FORMER_DEFAULT_COLORS and color.upper() == FORMER_DEFAULT_COLORS[name]:
            data["color"] = CLASS_COLORS[name]
            changed = True
    return changed


class StyleValidator:
    """Style validator"""

    @staticmethod
    def classes(dict_user: dict[str, dict]) -> bool:
        """Classes style validator"""
        from .template.setting_classes import CLASSES_DEFAULT, CLASSINFO_DEFAULT

        save_change = _validate_style(dict_user, CLASSES_DEFAULT, CLASSINFO_DEFAULT)
        if "class_colors" in PENDING_STYLE_UPDATES:
            PENDING_STYLE_UPDATES.discard("class_colors")
            save_change = update_former_class_colors(dict_user) or save_change
        return save_change

    @staticmethod
    def brands(dict_user: dict[str, Any]) -> bool:
        """Brands validator: vehicle name to brand name, other entries removed"""
        invalid = [key for key, value in dict_user.items() if not isinstance(key, str) or not isinstance(value, str)]
        for key in invalid:
            del dict_user[key]
        return bool(invalid)

    @staticmethod
    def brakes(dict_user: dict[str, dict]) -> bool:
        """Brakes style validator"""
        from .template.setting_brakes import BRAKEINFO_DEFAULT, BRAKES_DEFAULT

        return _validate_style(dict_user, BRAKES_DEFAULT, BRAKEINFO_DEFAULT)

    @staticmethod
    def compounds(dict_user: dict[str, dict]) -> bool:
        """Compounds style validator"""
        from .template.setting_compounds import COMPOUNDINFO_DEFAULT, COMPOUNDS_DEFAULT

        save_change = _validate_style(dict_user, COMPOUNDS_DEFAULT, COMPOUNDINFO_DEFAULT)
        if "compound_colors" in PENDING_STYLE_UPDATES:
            PENDING_STYLE_UPDATES.discard("compound_colors")
            save_change = update_former_compound_colors(dict_user) or save_change
        return save_change

    @staticmethod
    def heatmap(dict_user: dict[str, dict]) -> bool:
        """Heatmap style validator"""
        from .template.setting_heatmap import HEATMAP_DEFAULT

        save_change = PresetValidator.add_missing_key(dict_user, HEATMAP_DEFAULT)
        # Sort styles
        if save_change:
            # Place default keys in front
            key_list_def = list(HEATMAP_DEFAULT)
            # Append user keys at end
            for key in dict_user:
                if key not in HEATMAP_DEFAULT:
                    key_list_def.append(key)
            for d_key in key_list_def:
                dict_user[d_key] = dict_user.pop(d_key)
        return save_change

    @staticmethod
    def tracks(dict_user: dict[str, dict]) -> bool:
        """Tracks style validator"""
        from .template.setting_tracks import TRACKINFO_DEFAULT, TRACKS_DEFAULT

        return _validate_style(dict_user, TRACKS_DEFAULT, TRACKINFO_DEFAULT)

    @staticmethod
    def filelock(dict_user: dict[str, dict]) -> bool:
        """File lock validator"""
        from .template.setting_filelock import FILELOCK_DEFAULT, FILELOCKINFO_DEFAULT

        return _validate_style(dict_user, FILELOCK_DEFAULT, FILELOCKINFO_DEFAULT)


class ValueValidator:
    """Value validator"""

    @staticmethod
    def boolean(key: str, dict_user: dict) -> bool:
        """Value - Boolean"""
        if not re.search(rxp.CFG_BOOL, key):
            return False
        value = dict_user[key]
        if not isinstance(value, bool):
            if type(value) is int and value in (0, 1):
                dict_user[key] = bool(value)
            else:  # "false" etc: restore default (not bool("false") = True)
                dict_user.pop(key)
        return True

    @staticmethod
    def choice_units(key: str, dict_user: dict) -> bool:
        """Value - units choice list"""
        for ref_key, choice_list in rxp.CHOICE_UNITS.items():
            if re.search(ref_key, key):
                if dict_user[key] not in choice_list:
                    dict_user.pop(key)
                return True
        return False

    @staticmethod
    def choice_common(key: str, dict_user: dict) -> bool:
        """Value - common choice list"""
        for ref_key, choice_list in rxp.CHOICE_COMMON.items():
            if re.search(ref_key, key):
                if dict_user[key] not in choice_list:
                    dict_user.pop(key)
                return True
        return False

    @staticmethod
    def color(key: str, dict_user: dict) -> bool:
        """Value - Color string"""
        if not re.search(rxp.CFG_COLOR, key):
            return False
        if not is_hex_color(dict_user[key]):
            dict_user.pop(key)
        return True

    @staticmethod
    def clock_format(key: str, dict_user: dict) -> bool:
        """Value - clock format string"""
        if not re.search(rxp.CFG_CLOCK_FORMAT, key):
            return False
        if not is_clock_format(dict_user[key]):
            dict_user.pop(key)
        return True

    @staticmethod
    def string(key: str, dict_user: dict) -> bool:
        """Value - string"""
        for strings in (
            rxp.CFG_FONT_NAME,
            rxp.CFG_HEATMAP,
            rxp.CFG_USER_PATH,
            rxp.CFG_USER_IMAGE,
            rxp.CFG_STRING,
        ):
            if re.search(strings, key):
                break
        else:
            return False
        if not isinstance(dict_user[key], str):
            dict_user.pop(key)
        return True

    @staticmethod
    def integer(key: str, dict_user: dict) -> bool:
        """Value - integer"""
        if not re.search(rxp.CFG_INTEGER, key):
            return False
        if not isinstance(dict_user[key], int) or isinstance(dict_user[key], bool):
            dict_user.pop(key)
        elif key.endswith("_port") and not 0 <= dict_user[key] <= 65535:
            dict_user.pop(key)  # out of range port raises OverflowError at bind
        else:
            clamp_value(key, dict_user)
        return True

    @staticmethod
    def numeric(key: str, dict_user: dict) -> bool:
        """Value - numeric (finite: JSON NaN & Infinity not allowed)"""
        if not is_finite_number(dict_user[key]):
            dict_user.pop(key)
        else:
            clamp_value(key, dict_user)
        return True


class PresetValidator:
    """Preset validator"""

    # Set validator methods in order
    _value_validators = tuple(
        getattr(ValueValidator, key)
        for key, value in ValueValidator.__dict__.items()
        if isinstance(value, staticmethod)
    )

    @classmethod
    def remove_invalid_key(cls, dict_user: dict, dict_def: dict, keep_unknown: bool = False) -> None:
        """Remove invalid key & value from user dictionary

        Args:
            keep_unknown: keep keys unknown to this build (options of a newer build), as they are.
        """
        key_list_user = tuple(dict_user)  # create user key list

        for key in key_list_user:  # loop through user key list
            # Remove invalid key
            if key not in dict_def:  # check in default list
                if not keep_unknown:
                    dict_user.pop(key)
                continue
            # Skip sub_level dict, remove dict set in place of a value (default restored later)
            if isinstance(dict_user[key], dict):
                if not isinstance(dict_def[key], dict):
                    dict_user.pop(key)
                continue
            # Validate values
            for _validator in cls._value_validators:
                if _validator(key, dict_user):
                    break

    @staticmethod
    def add_missing_key(dict_user: dict, dict_def: dict) -> bool:
        """Add missing default key to user list"""
        is_modified = False
        key_list_user = tuple(dict_user)  # create user key list

        for key in dict_def:  # loop through default keys
            if key not in key_list_user:  # check each default key in user list
                data_def = dict_def[key]
                # Add missing item to user
                if isinstance(data_def, dict):
                    dict_user[key] = data_def.copy()  # copy sub-dict
                else:
                    dict_user[key] = data_def
                is_modified = True

        return is_modified

    @staticmethod
    def sort_key_order(dict_user: dict, dict_def: dict) -> None:
        """Sort user key order according to default key list"""
        for d_key in dict_def:  # loop through default keys
            dict_user[d_key] = dict_user.pop(d_key)  # append user key at the end

    @classmethod
    def validate_key_pair(cls, dict_user: dict, dict_def: dict, keep_unknown: bool = False) -> None:
        """Create key-only check list, then validate key"""
        cls.remove_invalid_key(dict_user, dict_def, keep_unknown)
        cls.add_missing_key(dict_user, dict_def)
        cls.sort_key_order(dict_user, dict_def)

    @classmethod
    def global_preset(cls, dict_user: dict, dict_def: dict) -> dict:
        """Validate global preset"""
        # Pre update global preset, run before validation
        preset_version = _get_preset_version(dict_user, version.SETTING_VERSION)
        build_version = parse_version_string(version.SETTING_VERSION)
        if preset_version == VERSION_NA or preset_version < build_version:
            preupdate_global_setting(preset_version, dict_user)
        # Validate preset, options of a newer build kept
        return cls._validate(dict_user, dict_def, preset_version > build_version)

    @classmethod
    def user_preset(cls, dict_user: dict, dict_def: dict) -> dict:
        """Validate user preset"""
        # Pre update user preset, run before validation
        preset_version = _get_preset_version(dict_user, version.SETTING_VERSION)
        build_version = parse_version_string(version.SETTING_VERSION)
        if preset_version == VERSION_NA or preset_version < build_version:
            preupdate_user_setting(preset_version, dict_user)
        # Validate preset, options of a newer build kept
        return cls._validate(dict_user, dict_def, preset_version > build_version)

    @classmethod
    def shortcuts_preset(cls, dict_user: dict, dict_def: dict) -> dict:
        """Validate global keyboard shortcuts preset"""
        dict_user = cls._validate(dict_user, dict_def)
        for options in dict_user.values():
            options["bind"] = validate_hotkey(options["bind"])
        return dict_user

    @classmethod
    def _validate(cls, dict_user: dict, dict_def: dict, keep_unknown: bool = False) -> dict:
        """Validate setting, invalid section (not a dict) reset to default (rest of preset kept)

        Args:
            keep_unknown: keep keys & sections unknown to this build (preset of a newer build), as they are.
        """
        CLAMPED.clear()  # values of this validation only (never grows over the session)
        # Check top-level key
        cls.validate_key_pair(dict_user, dict_def, keep_unknown)
        # Check sub-level key
        for item in dict_user:
            if item not in dict_def or not isinstance(dict_def[item], dict):
                continue
            if not isinstance(dict_user[item], dict):
                dict_user[item] = dict_def[item].copy()
                continue
            cls.validate_key_pair(dict_user[item], dict_def[item], keep_unknown)
            normalize_display_orders(dict_user[item])
        return dict_user
