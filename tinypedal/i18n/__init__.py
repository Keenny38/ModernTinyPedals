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

import logging
import re
from types import MappingProxyType

logger = logging.getLogger(__name__)

# Display name: language code
LANGUAGES = MappingProxyType({
    "English": "en",
    "Français": "fr",
})

_translation: dict[str, str] = {}
_reverse: dict[str, str] = {}
_qt_translators: list = []  # keep reference, translator is removed if garbage collected
_message_rules: tuple = ()
_current_code = "en"


def current_language() -> str:
    """Current language code"""
    return _current_code


def load_translation(code: str) -> dict[str, str]:
    """Load translation dictionary by language code"""
    if code == "fr":
        from .fr import TRANSLATION

        return dict(TRANSLATION)
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
