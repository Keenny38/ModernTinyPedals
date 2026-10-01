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
User interface translation

tr(text): translate English UI text to current language (text itself if not translated).
untr(text): get original English text from translated text (for menu action dispatch).
Qt built-in dialogs & standard buttons use Qt's own translation files.
"""

from __future__ import annotations

import json
import logging
import os
import re
from types import MappingProxyType
from typing import Any

logger = logging.getLogger(__name__)

# Display name: language code (built-in, then language packs found by load_language_packs)
_LANGUAGES = {
    "English": "en",
    "Français": "fr",
}
LANGUAGES = MappingProxyType(_LANGUAGES)
BUILTIN_CODES = frozenset(_LANGUAGES.values())

# Language pack: JSON file "<code>.json" in languages folder (see docs/customization.md)
LANGUAGE_PACK_FORMAT = "modern-tiny-pedals-language"
LANGUAGE_PACK_FOLDER = "languages"
MAX_PACK_SIZE = 5 * 1024 * 1024
_valid_code = re.compile(r"^[a-z]{2,3}(_[A-Za-z]{2,4})?$")
_packs: dict[str, dict] = {}

_translation: dict[str, str] = {}
_reverse: dict[str, str] = {}
_qt_translators: list = []  # keep reference, translator is removed if garbage collected
_message_rules: tuple = ()
_current_code = "en"


def current_language() -> str:
    """Current language code"""
    return _current_code


def read_language_pack(filename: str) -> dict:
    """Read & validate language pack file

    Raises:
        ValueError: invalid language pack.
        OSError: file error.
    """
    with open(filename, encoding="utf-8") as file:
        content = file.read(MAX_PACK_SIZE + 1)
    if len(content) > MAX_PACK_SIZE:
        raise ValueError("file too large")
    data = json.loads(content)
    if not isinstance(data, dict) or data.get("format") != LANGUAGE_PACK_FORMAT:
        raise ValueError("not a language pack")
    name, code = data.get("name"), data.get("code")
    if not isinstance(name, str) or not name.strip() or not isinstance(code, str) or not _valid_code.match(code):
        raise ValueError("invalid language name or code")
    pack: dict[str, Any] = {"name": name.strip(), "code": code}
    for section in ("ui", "options", "option_help"):
        values = data.get(section, {})
        if not isinstance(values, dict):
            raise ValueError(f"invalid {section} section")
        # Untranslated (empty) entries fall back to English
        pack[section] = {str(key): value for key, value in values.items() if isinstance(value, str) and value}
    rules = []
    for rule in data.get("messages", []):
        if isinstance(rule, list) and len(rule) == 2 and all(isinstance(part, str) for part in rule) and rule[1]:
            try:
                re.compile(rule[0])
            except re.error:
                continue
            rules.append((rule[0], rule[1]))
    pack["messages"] = tuple(rules)
    return pack


def load_language_packs(*folders: str) -> list[str]:
    """Register language packs found in folders, returns names of loaded languages"""
    loaded = []
    for folder in folders:
        if not folder or not os.path.isdir(folder):
            continue
        for filename in sorted(os.listdir(folder)):
            if not filename.lower().endswith(".json"):
                continue
            try:
                pack = read_language_pack(os.path.join(folder, filename))
            except (OSError, ValueError, UnicodeDecodeError) as error:
                logger.error("I18N: invalid language pack %s: %s", filename, error)
                continue
            code, name = pack["code"], pack["name"]
            if code in BUILTIN_CODES or (name in _LANGUAGES and _LANGUAGES[name] != code):
                logger.warning("I18N: language pack %s skipped, %s already exists", filename, name)
                continue
            _packs[code] = pack
            _LANGUAGES[name] = code
            loaded.append(name)
            logger.info("I18N: language pack loaded: %s (%s)", name, code)
    from ..regex_pattern import LANGUAGE_NAMES

    LANGUAGE_NAMES[:] = list(_LANGUAGES)
    return loaded


def language_pack(code: str) -> dict:
    """Loaded language pack data, empty if not a pack"""
    return _packs.get(code, {})


def load_translation(code: str) -> dict[str, str]:
    """Load translation dictionary by language code"""
    if code == "fr":
        from .fr import TRANSLATION

        return dict(TRANSLATION)
    if code in _packs:
        return dict(_packs[code]["ui"])
    return {}


def set_language(name: str) -> str:
    """Set UI language by display name, returns language code"""
    global _translation, _reverse, _current_code
    code = LANGUAGES.get(name, "en")
    _current_code = code
    _translation = load_translation(code)
    _reverse = {translated: original for original, translated in _translation.items()}
    if len(_reverse) != len(_translation):
        logger.warning("I18N: duplicated translation found, some menu actions may not work")
    _load_message_rules(code)
    logger.info("I18N: language %s (%s)", name, code)
    return code


def _load_message_rules(code: str):
    """Compile message translation rules"""
    global _message_rules
    rules: tuple = ()
    if code == "fr":
        from .fr_messages import MESSAGE_RULES

        rules = MESSAGE_RULES
    elif code in _packs:
        rules = _packs[code]["messages"]
    _message_rules = tuple(
        (re.compile(pattern, flags=re.MULTILINE), replacement) for pattern, replacement in rules
    )


def tr(text: str) -> str:
    """Translate UI text"""
    return _translation.get(text, text)


def trm(text: str) -> str:
    """Translate dialog message with variable content (regex rules), keep text if no rule matches"""
    if not _message_rules or not isinstance(text, str):
        return text
    for pattern, replacement in _message_rules:
        text = pattern.sub(replacement, text)
    return text


def untr(text: str) -> str:
    """Get original (English) UI text from translated text"""
    return _reverse.get(text, text)


def install_qt_translation(app, code: str) -> bool:
    """Install Qt built-in translation (standard buttons & dialogs), replace previous one"""
    while _qt_translators:
        app.removeTranslator(_qt_translators.pop())
    if code == "en":
        return False
    from PySide6.QtCore import QLibraryInfo, QTranslator

    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    translator = QTranslator(app)
    if translator.load(f"qtbase_{code}", path):
        app.installTranslator(translator)
        _qt_translators.append(translator)
        return True
    logger.info("I18N: Qt translation qtbase_%s not found in %s", code, path)
    return False
