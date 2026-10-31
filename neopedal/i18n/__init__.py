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
User interface translation

tr(text): translate English UI text to current language (text itself if not translated).
untr(text): get original English text from translated text (for menu action dispatch).
Qt built-in dialogs & standard buttons use Qt's own translation files.
"""

from __future__ import annotations

import functools
import logging
import os
import re
from re import _constants as _sre_constants  # type: ignore[attr-defined]
from re import _parser as _sre_parser  # type: ignore[attr-defined]
from types import MappingProxyType
from typing import Any

from ..const_app import FORMAT_PREFIX, LEGACY_FORMAT_PREFIX
from ..validator import json_loads_checked

logger = logging.getLogger(__name__)

# Display name: language code (built-in, then language packs found by load_language_packs)
_LANGUAGES = {
    "English": "en",
    "Français": "fr",
}
LANGUAGES = MappingProxyType(_LANGUAGES)
BUILTIN_CODES = frozenset(_LANGUAGES.values())

# Language pack: JSON file "<code>.json" in languages folder (see docs/customization.md)
LANGUAGE_PACK_FORMAT = f"{FORMAT_PREFIX}-language"
LANGUAGE_PACK_FORMATS = (LANGUAGE_PACK_FORMAT, f"{LEGACY_FORMAT_PREFIX}-language")  # packs of versions until 0.23.0 too
LANGUAGE_PACK_FOLDER = "languages"
MAX_PACK_SIZE = 5 * 1024 * 1024
_valid_code = re.compile(r"^[a-z]{2,3}(_[A-Za-z]{2,4})?$")
_packs: dict[str, dict] = {}
# Message rules of a pack (community regex run on every dialog message): pattern length, rules, unbounded
# repeats per pattern (each one multiplies backtracking on a long message)
MAX_RULE_PATTERN = 1000
MAX_RULES = 5000
MAX_RULE_REPEATS = 8
# HTML elements of Qt rich text & QML StyledText: a translation shown in a rich text dialog never gets one
# (link, image...) that its English text does not have
RICH_TEXT_TAGS = frozenset((
    "a", "address", "b", "big", "blockquote", "body", "br", "center", "cite", "code", "dd", "del", "dfn", "div",
    "dl", "dt", "em", "font", "h1", "h2", "h3", "h4", "h5", "h6", "head", "hr", "html", "i", "img", "kbd", "li",
    "link", "meta", "nobr", "ol", "p", "pre", "qt", "s", "samp", "small", "span", "strong", "style", "sub", "sup",
    "table", "tbody", "td", "tfoot", "th", "thead", "title", "tr", "tt", "u", "ul", "var",
))
_tag_text = re.compile(r"<\s*/?\s*([A-Za-z][A-Za-z0-9]*)[^<>]*(?:>|(?=<)|$)")  # unclosed tag too
_space = re.compile(r"\s+")

_translation: dict[str, str] = {}
_reverse: dict[str, str] = {}
_qt_translators: list = []  # keep reference, translator is removed if garbage collected
_message_rules: tuple = ()
_message_literals: tuple = ()  # literal text each rule needs in a message, "" if unknown (see pattern_literal)
_current_code = "en"
_overlay: dict[str, str] = {}  # modern overlay design labels


def current_language() -> str:
    """Current language code"""
    return _current_code


@functools.lru_cache(maxsize=8)
def _locale_decimal(code: str) -> str:
    from PySide6.QtCore import QLocale

    return QLocale(code).decimalPoint() or "."


def decimal_point() -> str:
    """Decimal separator of app language (comma in French), numbers shown in pages & stream graphics"""
    return _locale_decimal(current_language())


def localized(text: str) -> str:
    """Number text with decimal separator of app language (lap times keep their dot)"""
    point = decimal_point()
    return text if point == "." else text.replace(".", point)


def read_language_pack(filename: str) -> dict:
    """Read & validate language pack file

    Raises:
        ValueError: invalid language pack.
        OSError: file error.
    """
    with open(filename, encoding="utf-8-sig") as file:  # BOM of Notepad, PowerShell
        content = file.read(MAX_PACK_SIZE + 1)
    if len(content) > MAX_PACK_SIZE:
        raise ValueError("file too large")
    try:
        data = json_loads_checked(content)
    except RecursionError as error:
        raise ValueError("JSON data nested too deeply") from error
    if not isinstance(data, dict) or data.get("format") not in LANGUAGE_PACK_FORMATS:
        raise ValueError("not a language pack")
    name, code = data.get("name"), data.get("code")
    if not isinstance(name, str) or not name.strip() or not isinstance(code, str) or not _valid_code.match(code):
        raise ValueError("invalid language name or code")
    pack: dict[str, Any] = {"name": name.strip(), "code": code}
    for section in ("ui", "options", "option_help", "overlay"):
        values = data.get(section, {})
        if not isinstance(values, dict):
            raise ValueError(f"invalid {section} section")
        # Untranslated (empty) entries fall back to English, entries with markup their English text does not
        # have are left out (option labels are keyed by option name: English label has no markup)
        pack[section] = {
            str(key): value for key, value in values.items()
            if isinstance(value, str) and value and safe_markup(value, "" if section == "options" else str(key))
        }
    messages = data.get("messages", [])
    if not isinstance(messages, list):
        raise ValueError("invalid messages section")
    rules = []
    for rule in messages[:MAX_RULES]:
        if isinstance(rule, list) and len(rule) == 2 and all(isinstance(part, str) for part in rule) and rule[1]:
            # Bad replacement ("\9", "\g<x>") only raises at sub(), test it once here
            try:
                reason = unsafe_pattern(rule[0]) or ("" if safe_markup(rule[1], rule[0]) else "markup not in pattern")
                if reason:
                    raise re.error(reason)
                re.compile(rule[0], re.MULTILINE).sub(rule[1], "")
            except (re.error, IndexError, RecursionError, OverflowError) as error:
                logger.warning("I18N: invalid message rule skipped in %s: %r (%s)", filename, rule, error)
                continue
            rules.append((rule[0], rule[1]))
    pack["messages"] = tuple(rules)
    return pack


def markup_tags(text: str) -> set[str]:
    """Rich text tags of text (lower case, spaces collapsed: "<a href='x'>", "</b>"), unclosed tag too; text
    between angle brackets that is no HTML element ("<date time>") left out"""
    return {
        _space.sub(" ", match[0].lower()) for match in _tag_text.finditer(text)
        if match[1].lower() in RICH_TEXT_TAGS
    }


def safe_markup(translation: str, source: str) -> bool:
    """Whether translation has only rich text tags of its source (English text or message rule pattern)"""
    if "<" not in translation:
        return True
    return markup_tags(translation) <= markup_tags(source)


def unsafe_pattern(pattern: str) -> str:
    """Reason why a message rule pattern of a language pack could freeze the app (catastrophic backtracking),
    empty if safe

    Refused: too long, a repeat inside a repeat ("(a+)+", "(\\w*\\s)*"), alternatives inside a repeat
    ("(a|ab)*"), more than MAX_RULE_REPEATS unbounded repeats. Raises re.error if not a valid pattern.
    """
    if len(pattern) > MAX_RULE_PATTERN:
        return f"pattern longer than {MAX_RULE_PATTERN} characters"
    repeats = 0
    stack: list[tuple[Any, bool]] = [(_sre_parser.parse(pattern, re.MULTILINE), False)]  # (items, in a repeat)
    while stack:
        items, repeated = stack.pop()
        for op, value in items:
            if op in _REPEATS:
                high, body = value[1], value[2]
                if high > 1:
                    if repeated:
                        return "repeat inside a repeat"
                    if high == _sre_constants.MAXREPEAT:
                        repeats += 1
                        if repeats > MAX_RULE_REPEATS:
                            return f"more than {MAX_RULE_REPEATS} unbounded repeats"
                stack.append((body, repeated or high > 1))
            elif op == _sre_constants.BRANCH:
                if repeated:
                    return "alternatives inside a repeat"
                stack.extend((branch, repeated) for branch in value[1])
            elif op == _sre_constants.SUBPATTERN:
                stack.append((value[-1], repeated))
            elif op in (_sre_constants.ASSERT, _sre_constants.ASSERT_NOT):
                stack.append((value[1], repeated))
            elif op == _sre_constants.ATOMIC_GROUP:
                stack.append((value, repeated))
            elif op == _sre_constants.GROUPREF_EXISTS:
                stack.extend((branch, repeated) for branch in value[1:] if branch is not None)
    return ""


_REPEATS = (_sre_constants.MAX_REPEAT, _sre_constants.MIN_REPEAT, _sre_constants.POSSESSIVE_REPEAT)


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
            except (OSError, ValueError, TypeError, RecursionError) as error:
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
    global _translation, _reverse, _current_code, _overlay
    code = LANGUAGES.get(name, "en")
    _current_code = code
    _translation = load_translation(code)
    _overlay = load_overlay_labels(code)
    _reverse = {translated: original for original, translated in _translation.items()}
    if len(_reverse) != len(_translation):
        logger.warning("I18N: duplicated translation found, some menu actions may not work")
    _load_message_rules(code)
    logger.info("I18N: language %s (%s)", name, code)
    return code


def _load_message_rules(code: str):
    """Compile message translation rules"""
    global _message_rules, _message_literals
    rules: tuple = ()
    if code == "fr":
        from .fr_messages import MESSAGE_RULES

        rules = MESSAGE_RULES
    elif code in _packs:
        rules = _packs[code]["messages"]
    _message_rules = tuple(
        (re.compile(pattern, flags=re.MULTILINE), replacement) for pattern, replacement in rules
    )
    _message_literals = tuple(pattern_literal(pattern) for pattern, _ in rules)
    _translate_message.cache_clear()


def pattern_literal(pattern: str) -> str:
    """Literal text every match of pattern holds (its leading literal characters, anchors skipped), "" if it
    starts with anything else (alternatives, a class, a repeat, a flag...) or is case-insensitive

    A message without the literal cannot match the rule: _translate_message skips it without running the regex.
    """
    try:
        parsed = _sre_parser.parse(pattern, re.MULTILINE)
    except re.error:
        return ""
    if parsed.state.flags & re.IGNORECASE:
        return ""
    chars = []
    for op, value in parsed:
        if op == _sre_constants.AT:  # ^, \A, \b: no text of their own
            continue
        if op != _sre_constants.LITERAL:
            break
        chars.append(chr(value))
    return "".join(chars)


def tr(text: str) -> str:
    """Translate UI text"""
    return _translation.get(text, text)


def load_overlay_labels(code: str) -> dict[str, str]:
    """Overlay label dictionary by language code (language pack: optional "overlay" table)"""
    if code == "fr":
        from .fr_overlay import OVERLAY_LABELS

        return dict(OVERLAY_LABELS)
    if code in _packs:
        return dict(_packs[code].get("overlay", {}))
    return {}


def tr_overlay(text: str) -> str:
    """Translate label of modern overlay design (short labels, apart from UI translation)"""
    return _overlay.get(text, text)


@functools.lru_cache(maxsize=4096)
def _translate_message(text: str) -> str:
    """Apply message rules (cached, cleared whenever rules change): a rule whose literal text (see
    pattern_literal) is not in the message is skipped, its regex never run (hundreds of rules per message)"""
    for (pattern, replacement), literal in zip(_message_rules, _message_literals):
        if literal and literal not in text:
            continue
        text = pattern.sub(replacement, text)
    return text


def trm(text: str) -> str:
    """Translate dialog message with variable content (regex rules), keep text if no rule matches"""
    if not _message_rules or not isinstance(text, str):
        return text
    return _translate_message(text)


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
