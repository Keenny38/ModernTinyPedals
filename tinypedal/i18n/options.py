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
Help: generated from documentation (tools/gen_option_help.py), English only.
"""

from __future__ import annotations

import re
from fnmatch import fnmatchcase
from functools import lru_cache

from ..formatter import format_module_name, format_option_name
from . import current_language


@lru_cache(maxsize=4)
def _labels(code: str) -> dict[str, str]:
    """Option labels of language"""
    if code == "fr":
        from .fr_options import OPTIONS

        return OPTIONS
    return {}


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
    from .option_help import COMMON, HELP

    return HELP, COMMON


# Generic words documented once in common terms, matched as part of other keys
_GENERIC = ("color", "decimal_places", "display_order", "prefix", "text_alignment", "font_name", "font_size", "font_weight")


def option_help(section: str, key: str) -> str:
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


def option_tooltip(section: str, key: str) -> str:
    """Tooltip text: description (if documented) and option key"""
    text = option_help(section, key)
    if text:
        return f"<p style='white-space:pre-wrap'>{_escape(text)}</p><p><i>{key}</i></p>"
    return f"<i>{key}</i>"


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
