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
Option labels & help (tooltips) for config dialogs

Labels: generated per language (tools/gen_fr_options.py), English label is formatted from key.
Help: generated from documentation (tools/gen_option_help.py) in English, translated per language
    in <code>_option_help.json (English text -> translation). Help edited in documentation shows
    in English until its translation is updated.
Both are stored as JSON data files in "data" folder, loaded on first use.
"""

from __future__ import annotations

import json
import logging
import os
import re
from fnmatch import fnmatchcase
from functools import lru_cache

from ..formatter import format_module_name, format_option_name
from . import current_language, language_pack

logger = logging.getLogger(__name__)

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
LABEL_LANGUAGES = ("fr",)  # languages with option label file: <code>_options.json


def load_data(filename: str) -> dict:
    """Load i18n JSON data file, empty dict if missing or invalid (UI falls back to English)"""
    try:
        with open(os.path.join(DATA_PATH, filename), encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError) as error:
        logger.error("I18N: unable to load %s: %s", filename, error)
        return {}
    if not isinstance(data, dict):
        logger.error("I18N: invalid data in %s", filename)
        return {}
    return data


@lru_cache(maxsize=4)
def _labels(code: str) -> dict[str, str]:
    """Option labels of language"""
    if code in LABEL_LANGUAGES:
        return load_data(f"{code}_options.json")
    return dict(language_pack(code).get("options", {}))


def option_label(key: str) -> str:
    """Option display name in current language"""
    return _labels(current_language()).get(key) or format_option_name(key)


def module_label(name: str) -> str:
    """Widget or module display name in current language"""
    labels = _labels(current_language())
    if labels:
        label = labels.get(name.removeprefix("module_")) or labels.get(name)
        if label:
            return label
    return format_module_name(name)


def search_text(key: str) -> str:
    """All searchable names of option: displayed label, English label, key"""
    return f"{option_label(key)} {format_option_name(key)} {key}".lower()


@lru_cache(maxsize=1)
def _help() -> tuple[dict, str]:
    data = load_data("option_help.json")
    return data.get("help", {}), data.get("common", "")


# Generic words documented once in common terms, matched as part of other keys
_GENERIC = ("color", "decimal_places", "display_order", "prefix", "text_alignment", "font_name", "font_size", "font_weight")


@lru_cache(maxsize=4)
def _help_translations(code: str) -> dict[str, str]:
    """Translated option help of language: English text -> translation"""
    if code in LABEL_LANGUAGES:
        return load_data(f"{code}_option_help.json")
    return dict(language_pack(code).get("option_help", {}))


def option_help(section: str, key: str) -> str:
    """Option description in current language (English if not translated), empty if not documented"""
    text = option_help_english(section, key)
    if text:
        return _help_translations(current_language()).get(text, text)
    return text


def option_help_english(section: str, key: str) -> str:
    """Option description from documentation, empty if not documented"""
    helps, common = _help()
    section_help = helps.get(section, {})
    common_help = helps.get(common, {})
    for source in (section_help, common_help):
        if key in source:
            return source[key]
    for source in (section_help, common_help):
        for pattern, text in source.items():
            if "*" in pattern and fnmatchcase(key, pattern):
                return text
    for word in _GENERIC:
        if word in common_help and re.search(rf"(^|_){word}(_|$)", key):
            return common_help[word]
    return ""


def option_help_specific(section: str, key: str) -> str:
    """Option description (current language), empty if only a generic text of common terms matches
    (colors, fonts, decimal places...): pages listing many such options skip the repeated text"""
    text = option_help_english(section, key)
    if not text:
        return ""
    helps, common = _help()
    common_help = helps.get(common, {})
    if key not in common_help and key not in helps.get(section, {}):
        generic = {common_help[word] for word in _GENERIC if word in common_help}
        if text in generic:
            return ""
    return _help_translations(current_language()).get(text, text)


def option_tooltip(section: str, key: str) -> str:
    """Tooltip text: description (if documented) and option key"""
    text = option_help(section, key)
    if text:
        return f"<p style='white-space:pre-wrap'>{_escape(text)}</p><p><i>{key}</i></p>"
    return f"<i>{key}</i>"


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
