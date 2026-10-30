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
Command palette (Ctrl+K): find & run anything, pages, tools, every menu command, settings, overlays, modules,
presets, options

Commands are built when the palette opens (states are current): pages & tools, every action of the window menus
(read from the menus themselves, so the palette never misses one), app commands without a menu, settings
categories, overlays & modules (on / off, options), presets. Results are scored (whole title, start of title,
start of a word, inside the title, keywords, letters in order), recent commands first when nothing is typed.
Prefixes: ">" commands only, "@" options only, "#" presets only. Qt Quick popup (qml/shell/CommandPalette.qml),
state in quick/palette_backend.py.
"""

from __future__ import annotations

import heapq
import os
import re
import sys
from collections.abc import Callable
from functools import partial
from typing import NamedTuple

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenu

from .. import app_signal
from ..const_file import ConfigType, FileExt
from ..i18n import tr, untr
from ..i18n.options import module_label
from ..module_control import ModuleControl, mctrl, wctrl
from ..setting import cfg
from .module_view import sort_key

MAX_COMMANDS = 60
MAX_OPTIONS = 30
MAX_RECENT = 8
SEARCH_DELAY = 100  # ms, results refreshed once typing pauses
PREFIX_COMMANDS = ">"
PREFIX_OPTIONS = "@"
PREFIX_PRESETS = "#"

# Groups (shown in this order when nothing is typed), icon glyph of entries without their own
GROUP_RECENT = "Recent"
GROUP_PAGES = "Pages"
GROUP_TOOLS = "Tools"
GROUP_COMMANDS = "Commands"
GROUP_SETTINGS = "Settings"
GROUP_OVERLAYS = "Overlays"
GROUP_MODULES = "Modules"
GROUP_PRESETS = "Presets"
GROUP_OPTIONS = "Options"
GROUP_GLYPHS = {
    GROUP_RECENT: "\ue81c",  # history
    GROUP_COMMANDS: "\ue945",  # lightning
    GROUP_SETTINGS: "\ue713",  # settings
    GROUP_OVERLAYS: "\ue71d",  # all apps
    GROUP_MODULES: "\ue9d9",  # pulse
    GROUP_PRESETS: "\ue8f1",  # library
    GROUP_OPTIONS: "\ue713",  # settings
}
# Window menus not read for commands: their entries are pages & tools of their own groups
SKIPPED_MENUS = ("ToolsMenu",)


class Command(NamedTuple):
    """Palette entry"""

    title: str
    kind: str  # group (translated), shown as section
    text: str  # lowercase searchable text, both languages
    run: Callable[[], object]
    glyph: str = ""  # icon (Segoe Fluent Icons / MDL2 Assets), group icon if empty
    shortcut: str = ""  # key sequence shown on the right
    key: str = ""  # stable id (recent commands)
    detail: str = ""  # menu path, page description
    folded: str = ""  # sort_key(title), worked out once (see folded_commands), not per search

    @property
    def folded_title(self) -> str:
        return self.folded or sort_key(self.title)


def folded_commands(commands: list[Command]) -> list[Command]:
    """Commands with their folded title filled in (scored on every search)"""
    return [command if command.folded else command._replace(folded=sort_key(command.title)) for command in commands]


def search_text(*parts: str) -> str:
    """Lowercase, accent-free search text"""
    return sort_key(" ".join(parts))


def is_subsequence(word: str, text: str) -> bool:
    """Letters of word found in text in the same order ("rclc" in "race calculator")"""
    position = 0
    for char in word:
        position = text.find(char, position) + 1
        if not position:
            return False
    return True


def word_patterns(words: list[str]) -> list[re.Pattern]:
    """Pattern of each search word starting a title word, compiled once per search (not once per command)"""
    return [re.compile(rf"(^|[\s(/-]){re.escape(word)}") for word in words]


def command_score(command: Command, words: list[str], patterns: list[re.Pattern] | None = None) -> int:
    """Rank of command for search words, 0 if a word is not found: whole title first, then title starting
    with a word, a word starting a title word, inside the title, in keywords (other language, former names),
    letters in order in the title

    Args:
        patterns: word_patterns(words), compiled here if not given.
    """
    if patterns is None:
        patterns = word_patterns(words)
    title = command.folded_title
    score = 0
    for word, pattern in zip(words, patterns):
        if title.startswith(word):
            score += 100
        elif pattern.search(title):
            score += 70
        elif word in title:
            score += 50
        elif word in command.text:
            score += 30
        elif len(word) >= 2 and is_subsequence(word, title):
            score += 10
        else:
            return 0
    if " ".join(words) == title:
        score += 200
    return score


def match_commands(commands: list[Command], query: str, limit: int = MAX_COMMANDS) -> list[Command]:
    """Commands matching every word of query (any order), best first, palette order kept among equals"""
    words = search_text(query).split()
    if not words:
        return commands[:limit]
    patterns = word_patterns(words)
    scored = [(command_score(command, words, patterns), index, command) for index, command in enumerate(commands)]
    found = [item for item in scored if item[0] > 0]
    if 0 < limit < len(found):  # only the limit best sorted
        found = heapq.nsmallest(limit, found, key=lambda item: (-item[0], item[1]))
    else:
        found.sort(key=lambda item: (-item[0], item[1]))
    return [command for _, _, command in found[:limit]]


def split_prefix(query: str) -> tuple[str, str]:
    """Search prefix (">", "@", "#" or "") and text after it"""
    text = query.lstrip()
    if text[:1] in (PREFIX_COMMANDS, PREFIX_OPTIONS, PREFIX_PRESETS):
        return text[:1], text[1:].strip()
    return "", query.strip()


def state_text(enabled: bool) -> str:
    return tr("On") if enabled else tr("Off")


def module_commands(control: ModuleControl, kind: str, parent) -> list[Command]:
    """Toggle & configure commands of every widget or module"""
    def toggle(name: str):
        control.toggle(name)
        app_signal.refresh.emit(True)

    def configure(name: str):
        if control.type_id == ConfigType.WIDGET:  # one page for every overlay
            from .overlay_options import open_overlay_options

            open_overlay_options(parent, name)
            return
        from .app_settings import open_app_settings  # module options: Settings page at the module category

        open_app_settings(parent, name)

    group = tr(GROUP_OVERLAYS if control.type_id == ConfigType.WIDGET else GROUP_MODULES)
    glyph = GROUP_GLYPHS[GROUP_OVERLAYS if control.type_id == ConfigType.WIDGET else GROUP_MODULES]
    commands = []
    for name in control.names:
        label = module_label(name)
        state = state_text(cfg.user.setting[name]["enable"])
        commands.append(Command(
            f"{label}  ({state})", group, search_text(label, name, kind, "toggle enable disable"),
            partial(toggle, name), glyph, key=f"{kind}:{name}:toggle"))
        commands.append(Command(
            f"{label}  {chr(0x2699)}", group, search_text(label, name, kind, "config settings options"),
            partial(configure, name), "\ue713", key=f"{kind}:{name}:config", detail=tr("Options")))
    return commands


def menu_commands(menu: QMenu, path: str = "") -> list[Command]:
    """Every enabled action of menu & its submenus (states refreshed first), run by triggering the action"""
    menu.aboutToShow.emit()  # menus refresh checked states when shown
    commands = []
    for action in menu.actions():
        if action.isSeparator() or not action.isVisible() or not action.isEnabled() or not action.text():
            continue
        title, _, shown_keys = action.text().replace("&", "").partition("\t")  # "Text\tKeys": keys shown only
        submenu = action.menu()
        if isinstance(submenu, QMenu):
            commands += menu_commands(submenu, f"{path} \u203a {title}" if path else title)
            continue
        shown = f"{title}  ({state_text(action.isChecked())})" if action.isCheckable() else title
        shortcut = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText) or shown_keys
        commands.append(Command(
            shown, tr(GROUP_COMMANDS), search_text(title, untr(title), path, untr(path), "menu"),
            action_trigger(action), shortcut=shortcut, key=f"menu:{untr(path)}/{untr(title)}", detail=path))
    return commands


def action_trigger(action: QAction) -> Callable[[], object]:
    """Trigger action later if it still exists (menus rebuilt on language change)"""
    import shiboken6

    def trigger():
        if shiboken6.isValid(action):
            action.trigger()
    return trigger


def app_commands(window) -> list[Command]:
    """App commands without a menu entry of their own: themes, rail, help pages, notifications, preset comparison"""
    from ..regex_pattern import THEME_NAMES
    from .tools_view import SHOW_PRESET_COMPARE, open_tool

    group = tr(GROUP_COMMANDS)
    commands = []
    current = cfg.application["window_color_theme"]
    for theme in THEME_NAMES:
        title = f"{tr('Window theme')}: {tr(theme)}"
        commands.append(Command(
            f"{title}  ({tr('On')})" if theme == current else title, group,
            search_text(title, "window color theme ui dark light modern legacy", theme), partial(set_color_theme, theme),
            "\ue790", key=f"theme:{theme}"))
    view = window.centralWidget()
    for label, english, run, glyph, shortcut in (
        (tr("Customize Navigation Bar…"), "customize navigation bar rail", getattr(view, "open_rail_editor", None),
         "\ue700", ""),
        (tr("Notifications"), "notifications messages errors bell", getattr(view, "show_notification_center", None),
         "\uea8f", ""),
        (tr("What's New"), "what's new release notes changelog version", partial(open_whats_new, window), "\ue946", ""),
        (tr("Preset Comparison"), "preset comparison compare presets differences comparer comparaison",
         partial(open_tool, SHOW_PRESET_COMPARE, window), "\ue8ab", ""),  # compare panel of the Presets page
        (tr("Keyboard Shortcuts"), "keyboard shortcuts keys cheat sheet", getattr(window, "open_shortcuts", None),
         "\ue765", "Ctrl+/"),
        (tr("Help for This Page"), "help user guide wiki page", getattr(view, "open_page_help", None), "\ue897", ""),
        (tr("Back"), "back previous page", getattr(window, "go_back", None), "\ue72b", "Alt+Left"),
        (tr("Forward"), "forward next page", getattr(window, "go_forward", None), "\ue72a", "Alt+Right"),
    ):
        if callable(run):
            commands.append(Command(label, group, search_text(label, english), run, glyph, shortcut,
                                    key=f"app:{english.split()[0]}"))
    director = director_page()
    if director is not None:  # Broadcast Director page open: director on or off
        label = tr("Broadcast Director")
        commands.append(Command(
            f"{label}  ({state_text(director.enabled)})", group,
            search_text(label, "Broadcast Director", "broadcast director regie toggle enable disable on off"),
            toggle_director, "\ue9e9", key="app:director"))
    race = race_page()
    if race is not None:  # Race Calculator page open: calculator on or off
        label = tr("Race Calculator")
        commands.append(Command(
            f"{label}  ({state_text(race.game_data)})", group,
            search_text(label, "Race Calculator", "race calculator fuel game data toggle enable disable on off"),
            toggle_race_game_data, "\ue8ef", key="app:race"))
    return commands


def build_commands(window) -> list[Command]:
    """All palette commands (options & presets apart, see option_results & preset_commands), built when palette
    opens (states are current)"""
    from ..template.page_registry import page_spec
    from .menu import open_config_application
    from .nav_rail import NAV_PAGES, current_rail_items, page_name
    from .tools_view import LISTED_TOOL_SECTIONS, TOOL_KEYWORDS, open_tool

    tab_view = window.centralWidget()
    rail = current_rail_items()
    commands: list[Command] = []
    for index, (key, label, glyph, _) in enumerate(NAV_PAGES):
        spec = page_spec(key)
        position = rail.index(key) + 1 if key in rail else 0
        commands.append(Command(
            page_name(index), tr(GROUP_PAGES), search_text(page_name(index), tr(label), label, key, "page go"),
            partial(tab_view.select_page, index), glyph, f"Ctrl+{position}" if 0 < position <= 9 else "",
            key=f"page:{key}", detail=tr(spec.description) if spec is not None and spec.description else ""))
    settings = tr(GROUP_SETTINGS)
    commands.append(Command(
        settings, settings, search_text(settings, "settings config configuration options preferences parametres"),
        partial(open_config_application, window, ""), GROUP_GLYPHS[GROUP_SETTINGS], "Ctrl+,", key="settings:"))
    for _, tools in LISTED_TOOL_SECTIONS:
        for label, glyph, dialog_path in tools:
            spec = page_spec(dialog_path)
            name = dialog_path.split(".", 1)[0]
            position = rail.index(name) + 1 if name in rail else 0
            description = tr(spec.description) if spec is not None and spec.description else ""
            commands.append(Command(
                tr(label), tr(GROUP_TOOLS),
                search_text(tr(label), label, "tool", description, TOOL_KEYWORDS.get(dialog_path, "")),
                partial(open_tool, dialog_path, window), glyph, f"Ctrl+{position}" if 0 < position <= 9 else "",
                key=f"tool:{dialog_path}", detail=description))
    commands += app_commands(window)
    titles = {command.title for command in commands}
    for menu in menu_bar_menus(window):
        if type(menu).__name__ in SKIPPED_MENUS:
            continue
        commands += [command for command in menu_commands(menu, menu.title().replace("&", ""))
                     if command.title not in titles]
    from .quick.settings_backend import CATEGORIES

    for category in CATEGORIES:  # settings page categories (config.json)
        commands.append(Command(
            tr(category.label), settings,
            search_text(tr(category.label), category.label, tr(category.description), "config settings"),
            partial(open_config_application, window, category.key), category.glyph,
            key=f"settings:{category.key}", detail=tr(category.description)))
    commands += module_commands(wctrl, "Overlays", window)
    commands += module_commands(mctrl, "Module", window)
    return folded_commands(commands)


def menu_bar_menus(window) -> list[QMenu]:
    """Menus of the window menu bar, in order"""
    menus = []
    for action in window.menuBar().actions():
        menu = action.menu()
        if isinstance(menu, QMenu):
            menus.append(menu)
    return menus


def preset_commands() -> list[Command]:
    """Load commands of every preset (newest first), loaded one marked"""
    loaded = cfg.filename.setting.removesuffix(FileExt.JSON)
    group = tr(GROUP_PRESETS)
    return folded_commands([Command(
        f"{name}  ({tr('Loaded')})" if name == loaded else name, group, search_text(name, "preset load"),
        partial(load_preset, name), GROUP_GLYPHS[GROUP_PRESETS], key=f"preset:{name}")
        for name in preset_names()])


def option_commands(window, text: str, limit: int = MAX_OPTIONS) -> list[Command]:
    """Options found for text (Find Option search: both languages, ranked), opening their settings page"""
    from ..i18n.options import option_label
    from .option_finder import cached_index, open_option, search_options

    group = tr(GROUP_OPTIONS)
    return [Command(
        option_label(entry.key), group, entry.text, partial(open_option, window, entry), GROUP_GLYPHS[GROUP_OPTIONS],
        key=f"option:{entry.section}/{entry.key}", detail=module_label(entry.section))
        for entry in search_options(cached_index(), text, limit)]


def recent_keys() -> list[str]:
    """Keys of commands run last, newest first (saved)"""
    return [key for key in cfg.application.get("command_palette_recent", "").split("\n") if key][:MAX_RECENT]


def remember_recent(key: str):
    """Command run: first of recent commands (saved)"""
    if not key:
        return
    keys = [key, *(other for other in recent_keys() if other != key)][:MAX_RECENT]
    text = "\n".join(keys)
    if cfg.application.get("command_palette_recent", "") != text:
        cfg.application["command_palette_recent"] = text
        cfg.save(config_type=ConfigType.CONFIG)


def set_color_theme(theme: str):
    """Window color theme set & saved (was the status bar theme button)"""
    if cfg.application["window_color_theme"] != theme:
        cfg.application["window_color_theme"] = theme
        cfg.save(config_type=ConfigType.CONFIG)
        app_signal.refresh.emit(True)


def open_whats_new(window):
    """What's new in running version"""
    from .release_notes import running_version_dialog

    running_version_dialog(window).open()


def director_page():
    """Director of the Broadcast Director page if open (its module is imported only by the page)"""
    module = sys.modules.get("neopedal.ui.quick.director_backend")
    return module.director_page() if module is not None else None


def toggle_director():
    """Director on or off, page looked for again (closed while the palette was open: nothing)"""
    director = director_page()
    if director is not None:
        director.setEnabled(not director.enabled)


def race_page():
    """Backend of the Race Calculator page if open (its module is imported only by the page)"""
    module = sys.modules.get("neopedal.ui.quick.race_backend")
    return module.race_page() if module is not None else None


def toggle_race_game_data():
    """Race Calculator on or off, page looked for again (closed meanwhile: nothing)"""
    race = race_page()
    if race is not None:
        race.setGameData(not race.game_data)


_preset_names: tuple[tuple, list[str]] | None = None


def preset_names() -> list[str]:
    """Preset names (newest first), folder read again only when a file was added, removed or saved"""
    global _preset_names
    folder = cfg.path.settings
    try:
        changed = os.stat(folder).st_mtime_ns
    except OSError:
        changed = 0
    key = folder, changed, cfg.version_update
    if _preset_names is None or _preset_names[0] != key:
        _preset_names = key, cfg.preset_files()
    return list(_preset_names[1])


def load_preset(preset_name: str):
    """Load preset by name (without extension)"""
    cfg.set_next_to_load(f"{preset_name}{FileExt.JSON}")
    app_signal.reload.emit(True)


def CommandPalette(window):  # class-like factory: palette popup of window
    """Command palette popup of window (Qt Quick), see quick.palette_backend.PalettePopup"""
    from .quick.palette_backend import PalettePopup

    return PalettePopup.open_for(window)
