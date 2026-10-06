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
Sections of overlay options (Overlay Options page): every overlay gets its options in sections

Plain data & pure functions (no Qt). Overlays declaring their own sections (Black box, driver
lists, see template.widget.WIDGET_OPTION_UI) keep them. Others are cut from option order of their template:

    General             on/off, design, update rate, visibility, theme
    Position & Layout   position, opacity, layout, gaps & paddings
    Font                font name, size, weight & offset
    Options             other options not tied to one displayed item
    <item>              one section per displayed item: led by its on/off option ("Show Speed"),
                        or options of one item without on/off option (colors of "Remaining")
    Shown Items         on/off options having no other option (modern design)
    Columns             column on/off options (modern standings)
    Display Order       order of displayed items (display_order_* options)

Options of a section led by an on/off option depend on it: shown dimmed while it is off.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from typing import NamedTuple

from ...template.widget.black_box_ui import ORDER_LIST

SECTION_GENERAL = "general"
SECTION_LAYOUT = "layout"
SECTION_FONT = "font"
SECTION_OPTIONS = "options"
SECTION_SHOWN = "shown"
SECTION_COLUMNS = "columns"
SECTION_ORDER = "order"
ITEM_PREFIX = "item:"  # section of one displayed item: "item:" + its first option key
FIXED_TITLES = {
    SECTION_GENERAL: "General",
    SECTION_LAYOUT: "Position & Layout",
    SECTION_FONT: "Font",
    SECTION_OPTIONS: "Options",
    SECTION_SHOWN: "Shown Items",
    SECTION_COLUMNS: "Columns",
    SECTION_ORDER: "Display Order",
}

GENERAL_KEYS = (
    "enable", "enable_classic_layout", "update_interval", "visibility_context", "stream_visibility",
)
FONT_KEYS = ("font_name", "font_size", "font_weight", "enable_auto_font_offset", "font_offset_vertical")
_rex_layout = re.compile(
    r"^(position_[xy]|opacity|layout|global_scale|display_scale|display_(width|height|margin)"
    r"|bar_(padding|gap|width|height|edge_width|radius)(_\w+)?|(horizontal|vertical|inner)_gap"
    r"|text_alignment|swap_style|auto_compact_display_scale)$"
)
_rex_toggle = re.compile(r"^(show|enable)_")
_rex_order = re.compile(r"^display_order_")
# Option name prefix or suffix telling which item an option styles: "font_color_speed" styles "speed"
_rex_item_option = re.compile(
    r"^(decimal_places|font_color|background_color|prefix|caption_text|font_scale|highlight_color|warning_color"
    r"|text)_(player_)?(?P<item>.+)$"
)
_rex_item_suffix = re.compile(r"^(?P<item>.+)_(text|width|color|style|radius|offset|spacing|symbol)$")
LOOKAHEAD = 2  # options checked after one not belonging to an item: taken if one of them belongs
# Words that never tell which item an option belongs to
_STOP_WORDS = frozenset((
    "show", "enable", "in", "for", "only", "of", "and", "by", "from", "to", "on", "while", "as", "each", "with",
    "the", "if", "into", "per", "at", "player",
))
# Words describing a property, shared by options of different items ("name", "width"): matched only if
# an option has no other word ("background_color" belongs to "show_background")
_WEAK_WORDS = frozenset((
    "name", "time", "mark", "level", "color", "text", "width", "height", "style", "align", "center", "uppercase",
    "shorten", "threshold", "radiu", "scale", "size", "offset", "line", "minimum", "maximum", "high", "low",
    "decimal", "place", "font", "background", "prefix", "number", "highlight", "duration", "interval",
))


class Section(NamedTuple):
    """Section of overlay options"""

    key: str  # SECTION_* or ITEM_PREFIX + first option
    keys: tuple[str, ...]  # options in page order (on/off option of item first)
    toggle: str = ""  # on/off option leading section (item), "" if none
    title: str = ""  # English title (fixed & declared sections), item label key otherwise


def _word(word: str) -> str:
    """Singular word: "laps" & "lap" are the same item"""
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def _words(text: str) -> list[str]:
    return [_word(word) for word in text.split("_") if word not in _STOP_WORDS]


def _strong(text: str) -> set[str]:
    """Words telling the item of option: property words only if it has no other"""
    words = set(_words(text))
    return (words - _WEAK_WORDS) or words


def _toggle_item(key: str) -> str:
    return _rex_toggle.sub("", key, count=1)


def _option_item(key: str) -> str:
    """Item styled by option ("font_color_player_position", "position_text" -> "position"), "" if none"""
    matched = _rex_item_option.match(key) or _rex_item_suffix.match(key)
    return matched.group("item") if matched else ""


def is_toggle(key: str, value: object) -> bool:
    """On/off option able to lead a section"""
    return isinstance(value, bool) and bool(_rex_toggle.match(key))


def _is_sub_item(item: str, parent: str) -> bool:
    """On/off option of an item is about parent item ("raw_throttle" of "throttle", "compound_for_each_wheel"
    of "tyre_compound", "current_speed_while_limiter_on" of "speed_limiter")"""
    words, parent_words = _words(item), _words(parent)
    if not words or not parent_words:
        return False
    if f"_{'_'.join(parent_words)}_" in f"_{'_'.join(words)}_":
        return True
    if words[0] == parent_words[-1]:
        return True
    return len(set(words) & set(parent_words)) >= 2


class _Block:
    __slots__ = ("keys", "toggle", "item", "vocabulary")

    def __init__(self, first: str, toggle: str, item: str):
        self.keys = [first]
        self.toggle = toggle
        self.item = item
        self.vocabulary = _strong(item)  # words of item & of its options

    def belongs(self, key: str) -> bool:
        """Option (not on/off) belongs to item of block

        Options of an item without on/off option are the ones styling that same item. Options of an
        item with on/off option share a word with it or with its options (see take).
        """
        if not self.toggle:
            return _option_item(key) == self.item
        return bool(_strong(key) & self.vocabulary)

    def take(self, key: str):
        """Option added, its words too: "garage_status_text" after "pit_status_text" brings "font_color_garage" """
        self.keys.append(key)
        if self.toggle:
            self.vocabulary |= _strong(key)


def _item_blocks(keys: Sequence[str], values: Mapping[str, object], orders: set[str]) -> list[_Block | str]:
    """Options cut into item blocks, in order; options of no item stay plain keys"""
    result: list[_Block | str] = []
    block: _Block | None = None
    for index, key in enumerate(keys):
        value = values.get(key)
        if is_toggle(key, value):
            item = _toggle_item(key)
            # Option of current item ("show_raw_throttle" after "show_throttle"), unless an item of its own
            if (block is not None and block.toggle and _is_sub_item(item, block.item)
                    and not (item in orders and item != block.item)):
                block.take(key)  # "show_circle_background" brings "background_color_circle"
                continue
            block = _Block(key, key, item)
            result.append(block)
            continue
        if block is not None and block.belongs(key):
            block.take(key)
            continue
        # Option between options of the item ("low_energy_text" among low fuel options)
        if block is not None and block.toggle and any(
                block.belongs(other) for other in keys[index + 1:index + 1 + LOOKAHEAD]
                if not is_toggle(other, values.get(other))):
            block.take(key)
            continue
        item = _option_item(key)
        if item:  # first option styling an item without on/off option
            block = _Block(key, "", item)
            result.append(block)
            continue
        block = None
        result.append(key)
    return result


def _common_prefix(keys: Sequence[str]) -> str:
    """Words starting every key: "speed_range" of "speed_range_1_start", "speed_range_2_end"..."""
    split = [key.split("_") for key in keys]
    words = []
    for parts in zip(*split):
        if len(set(parts)) != 1:
            break
        words.append(parts[0])
    return "_".join(words)


def _split_runs(keys: Sequence[str]) -> tuple[list[str], list[Section]]:
    """Runs of options starting with the same word ("prediction_1_...", "prediction_2_...") as sections,
    other options kept"""
    rest: list[str] = []
    sections: list[Section] = []
    run: list[str] = []

    def first_word(key: str) -> str:
        word = key.split("_", 1)[0]
        return "" if _word(word) in _WEAK_WORDS or word in _STOP_WORDS else word

    def flush():
        if len(run) >= MIN_RUN:
            sections.append(Section(ITEM_PREFIX + run[0], tuple(run), "", _common_prefix(run)))
        else:
            rest.extend(run)
        run.clear()

    for key in keys:
        if run and (not first_word(key) or first_word(key) != first_word(run[0])):
            flush()
        run.append(key)
    flush()
    return rest, sections


MIN_RUN = 3  # options starting with same word making a section of their own


def auto_sections(keys: Sequence[str], values: Mapping[str, object]) -> list[Section]:
    """Sections of overlay options cut from option order (see module doc)

    Args:
        keys: shown options in template order.
        values: option values (types tell on/off options).
    """
    general = [key for key in GENERAL_KEYS if key in keys]
    font = [key for key in FONT_KEYS if key in keys]
    taken = {*general, *font}
    layout = [key for key in keys if key not in taken and _rex_layout.match(key)]
    if len(font) == 1:  # font size of modern design: with sizes
        layout.extend(font)
        font = []
    taken.update(layout)
    order = [key for key in keys if _rex_order.match(key)]
    if len(order) < 2:  # one item: nothing to order
        order = []
    taken.update(order)
    columns = [key for key in keys if key.startswith("column_") and isinstance(values.get(key), bool)]
    taken.update(columns)
    rest = [key for key in keys if key not in taken]
    orders = {_rex_order.sub("", key, count=1) for key in order}

    options: list[str] = []
    shown: list[str] = []
    items: list[Section] = []
    shown_index = -1  # "Shown Items" placed where its first on/off option was
    for entry in _item_blocks(rest, values, orders):
        if isinstance(entry, str):
            options.append(entry)
            continue
        if entry.toggle and len(entry.keys) == 1:  # on/off option alone
            if shown_index < 0:
                shown_index = len(items)
            shown.append(entry.toggle)
            continue
        if not entry.toggle and len(entry.keys) == 1:  # one option styling an item: no section of its own
            options.append(entry.keys[0])
            continue
        items.append(Section(ITEM_PREFIX + entry.keys[0], tuple(entry.keys), entry.toggle, entry.item))
    if len(shown) == 1:  # single on/off option: with other options
        options.extend(shown)
        shown = []
    if shown:
        items.insert(shown_index, Section(SECTION_SHOWN, tuple(shown), "", FIXED_TITLES[SECTION_SHOWN]))
    options, runs = _split_runs(options)
    items[:0] = runs

    sections = []
    for name, section_keys in ((SECTION_GENERAL, general), (SECTION_LAYOUT, layout), (SECTION_FONT, font),
                               (SECTION_OPTIONS, options)):
        if section_keys:
            sections.append(Section(name, tuple(section_keys), "", FIXED_TITLES[name]))
    sections.extend(items)
    if columns:
        sections.append(Section(SECTION_COLUMNS, tuple(columns), "", FIXED_TITLES[SECTION_COLUMNS]))
    if order:
        sections.append(Section(SECTION_ORDER, tuple(order), "", FIXED_TITLES[SECTION_ORDER]))
    return sections


def declared_sections(keys: Sequence[str], titles: Mapping[str, str]) -> list[Section]:
    """Sections declared by overlay: {first option of section: title}, options before first one in General

    Common options (visibility...) go to General wherever they are, display order options make the
    display order list (titled as declared).
    """
    general = [key for key in keys if key in GENERAL_KEYS]
    orders = [key for key in keys if _rex_order.match(key)]
    if len(orders) < 2:  # one item: nothing to order
        orders = []
    order_title = next((titles[key] for key in orders if key in titles), FIXED_TITLES[SECTION_ORDER])
    skipped = {*general, *orders}
    sections: list[Section] = []
    current: list[str] = list(general)
    title = FIXED_TITLES[SECTION_GENERAL]
    name = SECTION_GENERAL
    for key in keys:
        if key in skipped:
            continue
        if key in titles and current:
            sections.append(Section(name, tuple(current), "", title))
            current = []
        if key in titles:
            title = titles[key]
            name = f"declared:{key}"
        current.append(key)
    if current:
        sections.append(Section(name, tuple(current), "", title))
    if orders:
        sections.append(Section(SECTION_ORDER, tuple(orders), "", order_title))
    return sections


def listed_sections(keys: Sequence[str], layout: Sequence[tuple[str, Sequence[str]]], order_title: str = "",
                    in_order_list: Collection[str] = ()) -> list[Section]:
    """Sections listed by overlay in page order: (title, options), options not shown by current design
    left out. ORDER_LIST among options places the display order list; options listed nowhere go to an
    Options section after the last one (General keeps common options).

    Args:
        in_order_list: on/off options switched in the display order list (no row of their own).
    """
    present = set(keys)
    general = [key for key in keys if key in GENERAL_KEYS]
    orders = [key for key in keys if _rex_order.match(key)]
    if len(orders) < 2:  # one item: nothing to order
        orders = []
    # Display order list: display order options, then on/off options switched in it
    order_section = Section(SECTION_ORDER, (*orders, *(key for key in keys if key in in_order_list)) if orders else (),
                            "", order_title or FIXED_TITLES[SECTION_ORDER])
    used = {*general, *order_section.keys}
    sections: list[Section] = [Section(SECTION_GENERAL, tuple(general), "", FIXED_TITLES[SECTION_GENERAL])]
    order_placed = False
    for title, options in layout:
        if ORDER_LIST in options:
            sections.append(order_section)
            order_placed = True
            continue
        shown = [key for key in options if key in present and key not in used]
        if shown:
            sections.append(Section(f"declared:{shown[0]}", tuple(shown), "", title))
            used.update(shown)
    rest = [key for key in keys if key not in used]
    if rest:
        sections.append(Section(SECTION_OPTIONS, tuple(rest), "", FIXED_TITLES[SECTION_OPTIONS]))
    if not order_placed:
        sections.append(order_section)
    return [section for section in sections if section.keys]


def order_keys(section: Section) -> tuple[str, ...]:
    """Display order options of display order list (without on/off options switched in it)"""
    return tuple(key for key in section.keys if _rex_order.match(key))


def section_dependencies(sections: Sequence[Section]) -> dict[str, str]:
    """Option: on/off option leading its section (options used only while it is on)"""
    return {key: section.toggle for section in sections if section.toggle for key in section.keys
            if key != section.toggle}
