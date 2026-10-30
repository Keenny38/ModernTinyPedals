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
Settings page backend (qml/Settings.qml): every global option of config.json, by category, and the
settings kept in the loaded preset (units, API options, global font override, pace notes, module options)

Categories are sections of config.json (Application, Overlay Style, Compatibility...), then sections of
the loaded preset ("In the loaded preset"). Options shown in groups with their description, an editor
matching their kind (switch, choice, number, color, folder...) and a reset to default. A group may list
options of another section ("section/key"): they are shown there only. Edits stay pending (undo & redo)
until applied: invalid values are marked at once and block Apply. Undo goes on past Apply: an applied
edit undone is pending again. A search looks through every category.

Section mode: a section of the loaded preset (module options from the Modules page, any preset section
from option search) is opened as an extra category, kept until the page closes. Its on / off switch
("enable") is not a pending row: switched at once in the page header, like on the Modules page.
Global font override: choices that change the font of every overlay once applied (then back to
"no change", never added twice), a preview of the font sizes they give, Undo in the applied toast.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from functools import partial
from typing import Any, NamedTuple, Protocol

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication

from ... import app_signal
from ...const_file import ConfigType
from ...i18n import current_language, tr, trm
from ...i18n.options import option_help_specific, option_label
from ...setting import cfg
from ..config import HIDDEN_OPTIONS
from ..module_view import highlight, sort_key
from . import font_override
from .models import DictListModel
from .option_kinds import (
    KIND_BOOL,
    KIND_CHOICE,
    KIND_COLOR,
    KIND_FONT,
    KIND_IMAGE,
    KIND_INTEGER,
    KIND_PATH,
    NUMBER_KINDS,
    OptionKind,
    check_value,
    choice_label,
    choice_values,
    decimals,
    display_text,
    display_value,
    number_range,
    number_text,
    parse_path,
    value_kind,
)

OTHER_GROUP = "Other"
GROUP_SEPARATOR = chr(0x203A)  # single right-pointing angle quotation mark
ROLES = (
    "key", "section", "option", "label", "help", "kind", "group", "first", "last",
    "checked", "choices", "choiceIndex", "text", "number", "decimals", "step", "minimum", "maximum",
    "color", "modified", "changed", "error", "defaultText", "applies", "marked",
)
TYPING_GROUP_SECONDS = 1.5  # keys typed in one option within this time: one undo step
TYPING_REFRESH_MS = 150  # typing paused this long: counts, navigation entries & font preview updated (see typed)
# When an option takes effect, if not at Apply: read when app starts (restart offered) or at next start only
APPLIES_RESTART = "restart"
APPLIES_NEXT_START = "next_start"
APPLIES_AT = {
    "application/enable_high_dpi_scaling": APPLIES_RESTART,
    "compatibility/enable_x11_platform_plugin_override": APPLIES_RESTART,
    "application/show_at_startup": APPLIES_NEXT_START,
    "application/show_setup_wizard_at_startup": APPLIES_NEXT_START,
    "application/check_for_updates_on_startup": APPLIES_NEXT_START,
}
# Where options are kept: config.json, loaded preset, or global font override choices (applied to the preset)
STORE_CONFIG = "config"
STORE_PRESET = "preset"
STORE_FONT = "font"
PRESET_PREFIX = "preset:"  # option id of a loaded preset option: "preset:section/key"
FONT_PREFIX = "font:"  # option id of a global font override choice: "font:key"
FONT_CATEGORY = "font"
API_CATEGORY = "api"  # options of the selected game API (section of cfg.api_key)
ENABLE_KEY = "enable"  # on / off of a preset section: header switch, not a row
# Switches turning a feature on or off: saved & applied at once, as on their own page (Hotkeys, Presets,
# Overlays, Stream Overlays) or like a module switch, never pending until Apply. Value: what is applied.
SWITCH_HOTKEYS = "hotkeys"
SWITCH_SERVERS = "servers"
SWITCH_STREAM = "stream"
SWITCH_VR = "vr"
IMMEDIATE_SWITCHES = {
    "application/enable_global_hotkey": SWITCH_HOTKEYS,
    "application/enable_auto_load_preset": "",
    "application/show_overlay_previews": "",
    "remote_control/enable_remote_control": SWITCH_SERVERS,
    "web_dashboard/enable_web_dashboard": SWITCH_SERVERS,
    "stream_overlay/enable_stream_overlay": SWITCH_STREAM,
    "vr_overlay/enable_vr_overlay": SWITCH_VR,
}
KIND_FILE = "file"  # file chosen in a file dialog (pace notes file), empty for none
FILE_FILTERS = {"pace_notes_playback/pace_notes_file_name": "TPPN"}  # FileFilter attribute of file options
MODULE_GLYPH = ""  # diagnostic (Modules page)
SAMPLE_MAX_PIXELS = 48  # global font override preview: larger sample texts shown at this size
# Global font override choices: label, help (English) & editor
FONT_LABELS = {
    "font_name": "Font Name",
    "font_size_addend": "Font Size Addend",
    "font_weight": "Font Weight",
    "enable_auto_font_offset": "Enable Auto Font Offset",
    "font_offset_vertical_addend": "Font Offset Vertical Addend",
}
FONT_HELP = {
    "font_name": "Font of every overlay",
    "font_size_addend": "Added to the font size of every overlay, once (from -20 to +20)",
    "font_weight": "Font weight of every overlay",
    "enable_auto_font_offset": "Vertical position of text set from the font, in every overlay",
    "font_offset_vertical_addend": "Added to the vertical text offset of every overlay, once (from -20 to +20)",
}


def apply_switch(kind: str):
    """Part of the app reading a feature switch just saved: started or stopped (see IMMEDIATE_SWITCHES)"""
    from ... import loader, safe_mode

    if kind == SWITCH_HOTKEYS:
        loader.kctrl.reload()
    elif kind == SWITCH_SERVERS:
        loader.enable_servers()
    elif kind == SWITCH_STREAM:
        loader.enable_stream_overlay()
    elif kind == SWITCH_VR:
        loader.vroverlay().disable()
        if not safe_mode.state.enabled:
            loader.vroverlay().enable()


class Category(NamedTuple):
    """Settings page category: one section of config.json or of the loaded preset, options in groups"""

    key: str  # config.json or preset section (API options: API_CATEGORY, font override: FONT_CATEGORY)
    label: str
    glyph: str  # Segoe Fluent Icons / MDL2 Assets
    description: str
    groups: tuple[tuple[str, tuple[str, ...]], ...] = ()  # (title, option keys), others in "Other"
    store: str = STORE_CONFIG


CATEGORIES = (
    Category("application", "Application", "", "Interface, startup, updates, presets & backups", (
        ("Interface", (
            "language", "window_color_theme", "enable_high_dpi_scaling", "show_overlay_previews",
            "show_option_group_title",
        )),
        ("Startup & Window", (
            "show_at_startup", "minimize_to_tray", "remember_position", "remember_size", "remember_open_pages",
            "keep_director_and_calculator_running_while_hidden", "show_setup_wizard_at_startup",
        )),
        ("Updates", ("check_for_updates_on_startup", "number_of_hours_between_update_checks", "update_repository")),
        ("Online", ("enable_online_driver_ranks",)),
        ("Presets & Backups", (
            "enable_auto_load_preset", "number_of_automatic_backups", "number_of_days_to_keep_deleted_presets",
            "maximum_saving_attempts",
        )),
        ("Performance & Hotkeys", ("minimum_update_interval", "enable_global_hotkey")),
    )),
    Category("overlay_style", "Overlay Style", "",
             "Modern design, theme, fonts, size & editing of every overlay", (
        ("Design", (
            "overlay_theme", "enable_colorblind_colors", "overlay_opacity_percentage", "background_opacity_percentage",
            "enable_black_background", "enable_depth_effects", "enable_fade_animation", "corner_radius_scale", "minimum_bar_gap",
        )),
        ("Font", ("enable_modern_font", "modern_font_name", "modern_design_font_name")),
        ("Size", ("overlay_scale",)),
        ("Overlay Editing", (  # saved in application section
            "application/enable_edit_mode_on_unlock", "application/enable_magnetic_snap", "application/snap_distance",
            "application/snap_gap", "application/show_layout_guides", "application/grid_move_size",
            "application/enable_layout_per_screen_setup",
        )),
    )),
    Category("notification", "Notification", "", "Notices shown at the bottom of the main window", (
        ("Preset Locked", ("notify_locked_preset", "font_color_locked_preset", "background_color_locked_preset")),
        ("Spectate Mode Enabled", (
            "notify_spectate_mode", "font_color_spectate_mode", "background_color_spectate_mode")),
        ("Pace Notes Playback Enabled", (
            "notify_pace_notes_playback", "font_color_pace_notes_playback", "background_color_pace_notes_playback")),
        ("Global Hotkey Enabled", (
            "notify_global_hotkey", "font_color_global_hotkey", "background_color_global_hotkey")),
        ("Auto Backup Car Setup Enabled", (
            "notify_auto_backup_car_setup", "font_color_auto_backup_car_setup",
            "background_color_auto_backup_car_setup")),
        ("Broadcast Director On", (
            "notify_broadcast_director", "font_color_broadcast_director", "background_color_broadcast_director")),
    )),
    Category("compatibility", "Compatibility", "", "Window manager, transparency & positions on some systems"),
    Category("remote_control", "Remote Control", "", "Run hotkey commands from a Stream Deck or a script"),
    Category("web_dashboard", "Web Dashboard", "", "Overlays in a browser of your phone, tablet or PC"),
    Category("stream_overlay", "Stream Overlay", "",
             "Overlays in OBS, Streamlabs, XSplit or vMix: addresses on the Stream Overlays page"),
    Category("vr_overlay", "VR Overlay", "", "Experimental: overlays in your VR headset, OpenXR & SteamVR games", (
        ("VR Overlay", ("enable_vr_overlay", "enable_openxr_layer", "enable_attach_to_headset", "update_interval")),
        ("Placement", (
            "overlay_width_meters", "distance_meters", "vertical_offset_meters", "horizontal_offset_meters")),
        ("Mirror Window", ("enable_vr_mirror_window", "mirror_background_color")),
    )),
    Category("user_path", "User Path", "", "Folders of presets, data & recorded laps"),
)
CATEGORY_KEYS = tuple(category.key for category in CATEGORIES)  # config.json categories
# Settings kept in the loaded preset (listed after config.json categories, under "In the loaded preset")
PRESET_CATEGORIES = (
    Category("units", "Units", "", "Units of the values shown by every overlay", store=STORE_PRESET),
    Category(FONT_CATEGORY, "Global Font Override", "",
             "Font of every overlay changed at once: applied once, then back to no change", store=STORE_FONT),
    Category("pace_notes_playback", "Pace Notes Playback", "", "Sound played for each pace note while driving", (
        ("Sound Playback", (
            "pace_notes_sound_volume", "enable_playback_while_in_pit", "pace_notes_sound_maximum_duration",
            "pace_notes_sound_maximum_queue", "pace_notes_global_offset",
        )),
        ("Sound Files", (
            "pace_notes_sound_path", "pace_notes_sound_format", "enable_manual_file_selector", "pace_notes_file_name",
        )),
    ), store=STORE_PRESET),
    Category(API_CATEGORY, "API Options", "", "Connection to the game, for the selected game API",
             store=STORE_PRESET),
)
STATIC_CATEGORIES = CATEGORIES + PRESET_CATEGORIES
# Options shown in a category of another config.json section: option id -> category key
MOVED_OPTIONS = {
    option: category.key for category in CATEGORIES for _, keys in category.groups for option in keys if "/" in option
}
# Notice previews (Notification category): group title -> font & background color options
NOTICE_COLORS = {
    title: (keys[1], keys[2]) for title, keys in CATEGORIES[CATEGORY_KEYS.index("notification")].groups
}


class SettingsHost(Protocol):
    """Page hosting the backend: dialogs & applying saved settings

    Optional: toast, applied_preset (preset settings saved), pick_file, test_sound.
    """

    def confirm(self, text: str) -> bool: ...
    def pick_color(self, color: str) -> str: ...
    def pick_folder(self, folder: str) -> str: ...
    def pick_image(self, filename: str) -> str: ...
    def open_folder(self, folder: str) -> None: ...
    def applied(self, sections: set[str], restart: list[str]) -> None: ...
    def open_link(self, name: str) -> None: ...
    def toast(self, text: str) -> None: ...  # short notice at bottom of page (optional)


class OptionInfo(NamedTuple):
    """Option shown by the page"""

    section: str
    key: str
    group: str  # English group title
    kind: OptionKind
    category: str  # page category showing it: section, or another one (MOVED_OPTIONS)
    store: str = STORE_CONFIG

    @property
    def id(self) -> str:
        if self.store == STORE_PRESET:
            return f"{PRESET_PREFIX}{self.section}/{self.key}"
        if self.store == STORE_FONT:
            return f"{FONT_PREFIX}{self.key}"
        return f"{self.section}/{self.key}"


def option_id(section: str, key: str, store: str = STORE_CONFIG) -> str:
    return OptionInfo(section, key, "", OptionKind(KIND_BOOL), "", store).id


def category_section(category: Category) -> str:
    """Section of config.json or of loaded preset holding the options of category"""
    if category.key == API_CATEGORY and category.store == STORE_PRESET:
        return cfg.api_key
    return category.key


def font_kind(key: str) -> OptionKind:
    """Editor of a global font override choice ("no change" first in choice lists)"""
    if key == "font_name":
        return OptionKind(KIND_FONT)
    if key == "font_weight":
        from ... import regex_pattern as rxp

        return OptionKind(KIND_CHOICE, (font_override.NO_CHANGE, *rxp.CHOICE_COMMON[rxp.CFG_FONT_WEIGHT]))
    if key == "enable_auto_font_offset":
        return OptionKind(KIND_CHOICE, font_override.AUTO_OFFSET_CHOICES, True)
    return OptionKind(KIND_INTEGER)


def option_info(section: str, key: str, group: str, category: str, store: str = STORE_CONFIG) -> OptionInfo | None:
    """Option of section shown in category, None if not saved or hidden"""
    if store == STORE_FONT:
        return OptionInfo(section, key, group, font_kind(key), category, store)
    if store == STORE_PRESET:
        options = cfg.user.setting.get(section, {})
        if not isinstance(options, dict) or key not in options or key == ENABLE_KEY:
            return None
        default = cfg.default.setting.get(section, {}).get(key, options[key])
    else:
        options = cfg.user.config.get(section, {})
        if key not in options or key in HIDDEN_OPTIONS.get(section, ()):
            return None
        default = cfg.default.config.get(section, {}).get(key, options[key])
    if f"{section}/{key}" in FILE_FILTERS:
        return OptionInfo(section, key, group, OptionKind(KIND_FILE), category, store)
    return OptionInfo(section, key, group, value_kind(key, default), category, store)


def category_options(category: Category) -> list[OptionInfo]:
    """Options of category in page order: groups, then options of no group ("Other")

    Options of the section moved to another category (MOVED_OPTIONS) are left for it.
    """
    infos: list[OptionInfo] = []
    grouped: set[str] = set()
    store = category.store
    section_name = category_section(category)
    for title, group_keys in category.groups:
        for option in group_keys:
            section, key = option.split("/", 1) if "/" in option else (section_name, option)
            info = option_info(section, key, title, category.key, store)
            if info is not None:
                infos.append(info)
                grouped.add(info.id)
    rest_title = OTHER_GROUP if category.groups else category.label
    if store == STORE_FONT:
        keys: Any = font_override.CHOICE_KEYS
    elif store == STORE_PRESET:
        options = cfg.user.setting.get(section_name, {})
        keys = options if isinstance(options, dict) else ()
    else:
        keys = cfg.user.config.get(section_name, {})
    for key in keys:
        info = option_info(section_name, key, rest_title, category.key, store)
        if info is not None and info.id not in grouped and info.id not in MOVED_OPTIONS:
            infos.append(info)
    return infos


def category_label(category: Category) -> str:
    """Category name in app language (extra category of a module: module name)"""
    if category.label:
        return tr(category.label)
    from .module_backend import module_title

    return module_title(category.key)


def preset_section_category(section: str) -> Category | None:
    """Extra category of a section of the loaded preset (module options...), None if not editable here
    (overlays have the Overlay Options page, preset info is set elsewhere)"""
    from ...module_control import wctrl

    options = cfg.user.setting.get(section)
    if not isinstance(options, dict) or section == "preset" or section in wctrl.names:
        return None
    from .module_backend import MODULE_SPECS

    spec = MODULE_SPECS.get(section)
    return Category(
        section, "", spec.glyph if spec else MODULE_GLYPH,  # label in app language when shown (category_label)
        spec.description if spec else "", store=STORE_PRESET)


class SettingsBackend(QObject):
    """Settings page state & actions

    Args:
        parent: page dialog.
        host: dialogs (color, folder...) & what to do once settings are saved.
        only: category shown alone (page of one category: no navigation nor search), "" for every category.
    """

    categoryChanged = Signal()
    stateChanged = Signal()  # pending edits & errors
    historyChanged = Signal()  # undo & redo available (with stateChanged)
    filterChanged = Signal()
    infoChanged = Signal()  # saved values: status cards (web dashboard, remote control)
    highlightChanged = Signal()
    sectionChanged = Signal()  # header of preset category: on / off, loaded preset & lock
    fontPreviewChanged = Signal()  # global font override preview (pending font edits)

    def __init__(self, parent, host: SettingsHost, only: str = ""):
        super().__init__(parent)
        self._host = host
        self._only = only
        self.model = DictListModel(ROLES, self)
        self._infos: dict[str, OptionInfo] = {}
        self._extra: list[Category] = []  # preset sections opened (section mode), kept until page closes
        self._category = only or CATEGORY_KEYS[0]
        self._pending: dict[str, Any] = {}  # option id: valid value not saved yet
        self._invalid: dict[str, tuple[str, str]] = {}  # option id: (typed text, English reason)
        self._typed: dict[str, str] = {}  # option id: text being typed, shown as typed (not reformatted)
        self._typing = ("", 0.0)  # option typed last & when, see typeText
        self._undo: list[tuple[dict, dict]] = []
        self._redo: list[tuple[dict, dict]] = []
        self._search = ""
        self._words: tuple[str, ...] = ()
        self._changed_only = False  # options changed from default or not saved, of every category
        self._highlight = ""
        # Preset that pending preset edits were made on: another one loaded meanwhile is asked before saving
        self._preset_file = cfg.filename.setting
        # Navigation entries (read several times per change by the page): made again once state changes
        self._categories: tuple[str, list[dict]] | None = None  # (language, entries)
        self._font_preview: dict = {}  # see update_font_preview
        self.applied_options: list[str] = []  # config.json option ids saved by the last apply (host reads them)
        # Text being typed: its row updated alone at once, the rest (counts, font preview) once typing pauses
        self._typing_timer = QTimer(self)
        self._typing_timer.setSingleShot(True)
        self._typing_timer.setInterval(TYPING_REFRESH_MS)
        self._typing_timer.timeout.connect(self.changed)
        app_signal.addresses.connect(self.infoChanged)  # LAN addresses found in background
        app_signal.servers.connect(self.infoChanged)  # server listening once its port is available again
        if only and only not in {category.key for category in STATIC_CATEGORIES}:
            extra = preset_section_category(only)
            if extra is not None:
                self._extra.append(extra)
        self.load_options()
        self.update_font_preview()

    # Categories
    def category_list(self) -> tuple[Category, ...]:
        if self._only:
            return tuple(category for category in (*STATIC_CATEGORIES, *self._extra) if category.key == self._only)
        return (*STATIC_CATEGORIES, *self._extra)

    def category_of(self, key: str) -> Category:
        for category in (*STATIC_CATEGORIES, *self._extra):
            if category.key == key:
                return category
        return CATEGORIES[0]

    # Options
    def load_options(self):
        """Options of every category (config.json may gain options after an update)"""
        self._infos = {info.id: info for category in self.category_list() for info in category_options(category)}
        self.update_rows()

    def saved(self, info: OptionInfo) -> Any:
        if info.store == STORE_FONT:
            return getattr(font_override.NEUTRAL, info.key)
        if info.store == STORE_PRESET:
            return cfg.user.setting.get(info.section, {}).get(info.key)
        return cfg.user.config[info.section][info.key]

    def default(self, info: OptionInfo) -> Any:
        if info.store == STORE_FONT:
            return getattr(font_override.NEUTRAL, info.key)
        if info.store == STORE_PRESET:
            return cfg.default.setting.get(info.section, {}).get(info.key)
        return cfg.default.config.get(info.section, {}).get(info.key)

    def value(self, info: OptionInfo) -> Any:
        """Edited value (pending), else saved"""
        return self._pending.get(info.id, self.saved(info))

    def choices(self, info: OptionInfo) -> list:
        """Saved values of a choice list (current value first if not in it)"""
        values = list(choice_values(info.kind))
        if info.store == STORE_FONT and info.kind.kind == KIND_FONT:
            values.insert(0, font_override.NO_CHANGE)
        current = self.value(info)
        if current not in values:
            values.insert(0, current)  # uninstalled font, removed language pack: kept until changed
        return values

    def choice_text(self, info: OptionInfo, value: Any) -> str:
        if value == font_override.NO_CHANGE and info.store == STORE_FONT:
            return tr(font_override.NO_CHANGE)
        return choice_label(info.kind, value)

    def filtering(self) -> bool:
        """Search or "Changed Only" filter: matching options of every category shown"""
        return bool(self._words) or self._changed_only

    def shown_infos(self) -> list[OptionInfo]:
        """Options of current category, or matching search & filter in every category"""
        if self.filtering():
            return [info for info in self._infos.values() if self.matches(info)]
        return [info for info in self._infos.values() if info.category == self._category]

    def label(self, info: OptionInfo) -> str:
        if info.store == STORE_FONT:
            return tr(FONT_LABELS[info.key])
        return option_label(info.key)

    def is_customized(self, info: OptionInfo) -> bool:
        """Changed from default (pending value counted) or edit not saved"""
        default = self.default(info)
        return (default is not None and self.value(info) != default) or info.id in self._pending or info.id in self._invalid

    def matches(self, info: OptionInfo) -> bool:
        if self._changed_only and not self.is_customized(info):
            return False
        if not self._words:
            return True
        category = self.category_of(info.category)
        text = sort_key(
            f"{self.label(info)} {info.key.replace('_', ' ')} {info.key} {tr(info.group)} {category_label(category)}")
        return all(word in text for word in self._words)

    def group_title(self, info: OptionInfo) -> str:
        """Group title of option, "" for the only group of a category (page title says it)"""
        category = self.category_of(info.category)
        if not self.filtering():
            return "" if info.group == category.label else tr(info.group)
        if info.group == category.label:
            return category_label(category)
        return f"{category_label(category)}  {GROUP_SEPARATOR}  {tr(info.group)}"

    def help_text(self, info: OptionInfo) -> str:
        if info.store == STORE_FONT:
            return tr(FONT_HELP[info.key])
        return option_help_specific(info.section, info.key)

    def row(self, info: OptionInfo) -> dict:
        kind = info.kind
        value = self.value(info)
        default = self.default(info)
        invalid = self._invalid.get(info.id)
        row: dict[str, Any] = {
            "key": info.id,
            "section": info.section,
            "option": info.key,
            "label": self.label(info),
            "help": self.help_text(info),
            "kind": kind.kind,
            "group": self.group_title(info),
            "first": False,
            "last": False,
            "checked": bool(value) if kind.kind == KIND_BOOL else False,
            "choices": [],
            "choiceIndex": -1,
            "text": self._typed[info.id] if info.id in self._typed else invalid[0] if invalid
                    else "" if kind.kind == KIND_BOOL else display_value(kind, value),
            "number": 0.0,
            "decimals": 0,
            "step": 1.0,
            "minimum": 0.0,
            "maximum": 0.0,
            "color": value if kind.kind == KIND_COLOR and not invalid and isinstance(value, str) else "",
            "modified": default is not None and value != default,
            "changed": info.id in self._pending or info.id in self._invalid,
            "error": trm(tr(invalid[1])) if invalid else "",
            "defaultText": (self.choice_text(info, default) if kind.kind in (KIND_CHOICE, KIND_FONT)
                            else display_text(kind, default)) if default is not None else "",
            "applies": APPLIES_AT.get(info.id, ""),
            "marked": highlight(self.label(info), self._words) if self._words else "",  # searched words in bold
        }
        if kind.kind in (KIND_CHOICE, KIND_FONT):
            values = self.choices(info)
            row["choices"] = [self.choice_text(info, choice) for choice in values]
            row["choiceIndex"] = values.index(value)
        elif kind.kind in NUMBER_KINDS and isinstance(value, (int, float)):
            places = decimals(value, default) if kind.kind != KIND_INTEGER else 0
            minimum, maximum = number_range(info.key)
            row.update(number=float(value), decimals=places, step=10 ** -places if places else 1.0,
                       minimum=float(minimum), maximum=float(maximum))
        return row

    def update_rows(self):
        """Rows of shown options, synced in place (editors keep focus & typed text)"""
        rows = [self.row(info) for info in self.shown_infos()]
        for number, row in enumerate(rows):
            row["first"] = number == 0 or rows[number - 1]["group"] != row["group"]
            row["last"] = number == len(rows) - 1 or rows[number + 1]["group"] != row["group"]
        self.model.sync(rows)

    def changed(self):
        """Pending edits changed: rows, counts & page marker"""
        self._typing_timer.stop()
        if not self.preset_pending():
            self._preset_file = cfg.filename.setting  # next preset edits made on the loaded preset
        self.update_rows()
        self.update_font_preview()
        self.notify_state()

    def typed(self, option_id: str):
        """A key typed in a field: its row alone updated now (text, error, changed marker), every other row,
        the counts of the navigation entries & the font preview once typing pauses (see changed)"""
        info = self._infos.get(option_id)
        number = self.model.index_of(option_id)
        if info is None or number < 0:
            self.changed()
            return
        row = self.row(info)
        row.pop("first", None)  # group bounds of the shown rows unchanged
        row.pop("last", None)
        self.model.update_row(number, row)
        self._typing_timer.start()

    def preset_pending(self) -> bool:
        """Edits of the loaded preset (or font override) pending"""
        return any(key.startswith((PRESET_PREFIX, FONT_PREFIX)) for key in self._pending.keys() | self._invalid.keys())

    # Properties
    @Property(QObject, constant=True)
    def options(self) -> QObject:
        return self.model

    def notify_state(self):
        """State changed: navigation entries made again (dropped before the signal, as QML bindings
        notified by it may read them before any other connected slot runs)"""
        self._categories = None
        self.stateChanged.emit()
        self.historyChanged.emit()

    @Property(list, notify=stateChanged)
    def categories(self) -> list[dict]:
        """Navigation entries: pending edits, invalid values & search matches of each category, heading
        above the first category kept in the loaded preset

        Kept until state changes (edits, search, category, refresh: stateChanged) or language changes.
        """
        language = current_language()
        if self._categories is not None and self._categories[0] == language:
            return self._categories[1]
        entries = []
        heading_shown = False
        for category in self.category_list():
            infos = [info for info in self._infos.values() if info.category == category.key]
            preset = category.store != STORE_CONFIG
            entries.append({
                "key": category.key,
                "label": category_label(category),
                "glyph": category.glyph,
                "preset": preset,
                "heading": tr("In the loaded preset") if preset and not heading_shown else "",
                "changed": sum(info.id in self._pending or info.id in self._invalid for info in infos),
                "errors": sum(info.id in self._invalid for info in infos),
                "matches": sum(self.matches(info) for info in infos) if self.filtering() else 0,
            })
            heading_shown = heading_shown or preset
        self._categories = (language, entries)
        return entries

    @Property(str, notify=categoryChanged)
    def category(self) -> str:
        return self._category

    @Property(dict, notify=categoryChanged)
    def categoryInfo(self) -> dict:
        category = self.category_of(self._category)
        return {
            "key": category.key,
            "label": category_label(category),
            "glyph": category.glyph,
            "description": tr(category.description) if category.description else "",
            "preset": category.store != STORE_CONFIG,
            "font": category.store == STORE_FONT,
            "paceNotes": category.key == "pace_notes_playback",
        }

    @Property(bool, constant=True)
    def singleCategory(self) -> bool:
        """Page of one category: no navigation nor search"""
        return bool(self._only)

    @Property(dict, notify=sectionChanged)
    def sectionState(self) -> dict:
        """Header of a category kept in the loaded preset: preset name & lock, on / off switch of its section"""
        category = self.category_of(self._category)
        if category.store == STORE_CONFIG:
            return {"preset": "", "locked": False, "switchable": False, "enabled": False}
        options = cfg.user.setting.get(category_section(category), {})
        switchable = category.store == STORE_PRESET and isinstance(options, dict) and ENABLE_KEY in options
        return {
            "preset": cfg.filename.setting.removesuffix(".json"),
            "locked": cfg.filename.setting in cfg.user.filelock,
            "switchable": switchable,
            "enabled": bool(options.get(ENABLE_KEY)) if switchable else False,
        }

    @Property(int, notify=stateChanged)
    def pendingCount(self) -> int:
        return len(self._pending.keys() | self._invalid.keys())

    @Property(int, notify=stateChanged)
    def errorCount(self) -> int:
        return len(self._invalid)

    @Property(str, notify=stateChanged)
    def firstError(self) -> str:
        """First invalid option: label & reason"""
        for info in self._infos.values():
            if info.id in self._invalid:
                return f"{self.label(info)}: {trm(tr(self._invalid[info.id][1]))}"
        return ""

    @Property(bool, notify=historyChanged)
    def canUndo(self) -> bool:
        return bool(self._undo)

    @Property(bool, notify=historyChanged)
    def canRedo(self) -> bool:
        return bool(self._redo)

    @Property(str, notify=filterChanged)
    def searchText(self) -> str:
        return self._search

    @Property(bool, notify=filterChanged)
    def searching(self) -> bool:
        """Results of search or "Changed Only" filter shown (every category)"""
        return self.filtering()

    @Property(bool, notify=filterChanged)
    def changedOnly(self) -> bool:
        return self._changed_only

    @Property(int, notify=stateChanged)
    def matchCount(self) -> int:
        return self.model.rowCount() if self.filtering() else 0

    @Property(str, notify=highlightChanged)
    def highlightKey(self) -> str:
        """Option to scroll to & flash (opened from option search)"""
        return self._highlight

    @Property(dict, notify=stateChanged)
    def previews(self) -> dict:
        """Notice previews of Notification category: group title -> text, font & background colors"""
        from ..notification import readable_colors  # as the notices show them: text kept readable (4.5:1)

        result = {}
        for title, (font_key, background_key) in NOTICE_COLORS.items():
            font = self._color_value("notification", font_key)
            background = self._color_value("notification", background_key)
            if font and background:
                font, background = readable_colors(font, background)
            result[tr(title)] = {"text": tr(title), "color": font, "background": background}
        return result

    def _color_value(self, section: str, key: str) -> str:
        info = self._infos.get(f"{section}/{key}")
        value = self.value(info) if info is not None else ""
        return value if isinstance(value, str) and check_value(key, OptionKind(KIND_COLOR), value) == "" else ""

    def font_choice(self) -> font_override.FontChoice:
        """Global font override choices (pending)"""
        values = {
            key: self._pending[f"{FONT_PREFIX}{key}"] for key in font_override.CHOICE_KEYS
            if f"{FONT_PREFIX}{key}" in self._pending
        }
        return font_override.FontChoice(**values)

    @Property(dict, notify=fontPreviewChanged)
    def fontPreview(self) -> dict:
        """Global font override: font sizes now & after Apply (smallest, largest), overlays changed, chosen
        font family & weight for the sample text"""
        return self._font_preview

    def update_font_preview(self):
        """fontPreview worked out once per change of pending edits, fontPreviewChanged sent if it changed"""
        from ...regex_pattern import FONT_WEIGHT_MAP

        choice = self.font_choice()
        result = font_override.preview(cfg.user.setting, choice)
        weight = FONT_WEIGHT_MAP.get(choice.font_weight)
        preview = {
            "neutral": choice.is_neutral(),
            "sizeNow": [number_text(size) for size in result.size_now],
            "sizeAfter": [number_text(size) for size in result.size_after],
            "sections": result.sections,
            "options": result.options,
            # Sample text sizes (pixels): sizes of overlays, the largest kept within the page
            "sampleSmall": min(result.size_after[0], SAMPLE_MAX_PIXELS),
            "sampleLarge": min(result.size_after[1], SAMPLE_MAX_PIXELS),
            "family": choice.font_name if choice.font_name != font_override.NO_CHANGE else "",
            "weightValue": weight or 0,
        }
        if preview != self._font_preview:
            self._font_preview = preview
            self.fontPreviewChanged.emit()

    @Property(dict, notify=infoChanged)
    def webDashboard(self) -> dict:
        """Web dashboard status card: addresses & access code while enabled (saved setting)"""
        from ...web_dashboard import webdashboard

        setting = cfg.user.config["web_dashboard"]
        if not setting["enable_web_dashboard"]:
            return {"enabled": False, "running": webdashboard.running, "urls": [], "code": "", "fingerprint": ""}
        fingerprint = ""
        if webdashboard.use_https():
            try:
                from ...userfile.tls_cert import fingerprint as certificate_fingerprint

                fingerprint = certificate_fingerprint(cfg.path.config)
            except ImportError:  # cryptography missing
                fingerprint = ""
        return {
            "enabled": True,
            "running": webdashboard.running,
            "urls": webdashboard.urls(),
            "code": webdashboard.access_code(),
            "fingerprint": fingerprint,
        }

    @Property(dict, notify=infoChanged)
    def remoteControl(self) -> dict:
        from ...command_server import HOST, REQUIRED_HEADER, cmdserver

        setting = cfg.user.config["remote_control"]
        address = f"{HOST}:{setting['remote_control_port']}"
        # Access token (enable_access_token): header value of commands, token query of the stream
        token = cmdserver.access_token() if setting["enable_remote_control"] else ""
        return {
            "enabled": bool(setting["enable_remote_control"]),
            "running": cmdserver.running,
            "command": f'curl -X POST -H "{REQUIRED_HEADER}: {token or 1}" http://{address}/command/overlay_lock',
            "commands": f"http://{address}/commands",
            "stream": f"ws://{address}/stream" + (f"?token={token}" if token else ""),
        }

    @Property(str, constant=True)
    def configFile(self) -> str:
        return os.path.abspath(os.path.join(cfg.path.config, cfg.filename.config))

    # Navigation & search
    @Slot(str)
    def selectCategory(self, key: str):
        if key not in {category.key for category in self.category_list()}:
            return
        if self.filtering():  # leave search & filter for the category
            self._search, self._words, self._changed_only = "", (), False
            self.filterChanged.emit()
        if key != self._category:
            self._category = key
            self.categoryChanged.emit()
            self.sectionChanged.emit()
        self.update_rows()
        self.notify_state()

    def open_section(self, section: str) -> bool:
        """Show category of a section of the loaded preset ("units", "api", "font", "pace_notes_playback",
        a module...), opened as an extra category if not listed, False if it has no options here"""
        if section == cfg.api_key:
            section = API_CATEGORY
        known = {category.key for category in self.category_list()}
        if section not in known:
            if self._only:
                return False
            extra = preset_section_category(section)
            if extra is None:
                return False
            self._extra.append(extra)
            self.load_options()
        self.selectCategory(section)
        return True

    @Slot(str)
    def setSearch(self, text: str):
        if self._only:
            return  # one category: no search
        self._search = text
        words = tuple(sort_key(text).split())
        if words != self._words:
            self._words = words
            self.update_rows()
            self.notify_state()  # category match counts
        self.filterChanged.emit()

    @Slot(bool)
    def setChangedOnly(self, changed_only: bool):
        """Options changed from default (or not saved) of every category only"""
        if self._only or changed_only == self._changed_only:
            return
        self._changed_only = changed_only
        self.update_rows()
        self.notify_state()  # category match counts
        self.filterChanged.emit()

    def focus_option(self, section: str, key: str):
        """Show category of option & flash it (option search): config.json option, else of loaded preset"""
        config_id = option_id(section, key)
        if config_id in self._infos or (section in CATEGORY_KEYS and not self._only):
            category = MOVED_OPTIONS.get(config_id, section)
            if category in CATEGORY_KEYS:
                self.selectCategory(category)
            target = config_id
        else:
            if not self.open_section(section):
                return
            target = option_id(section, key, STORE_PRESET)
        if target in self._infos:
            self._highlight = ""
            self.highlightChanged.emit()  # same option again: flashed again
            self._highlight = target
            self.highlightChanged.emit()

    @Slot(str, result=int)
    def optionIndex(self, option_id: str) -> int:
        """Row of option shown, -1 if not shown"""
        return next((number for number, row in enumerate(self.model.rows) if row["key"] == option_id), -1)

    @Slot()
    def clearHighlight(self):
        self._highlight = ""

    # Edits
    def _snapshot(self) -> tuple[dict, dict]:
        return dict(self._pending), dict(self._invalid)

    def check(self, info: OptionInfo, value: Any) -> str:
        """Why value is invalid for option (English), "" if valid"""
        if info.kind.kind == KIND_FILE:
            if not isinstance(value, str):
                return "Text required"
            return "" if not value.strip() or os.path.isfile(value) else "File not found"
        return check_value(info.key, info.kind, value)

    def _edit(self, option_id: str, value: Any = None, text: str | None = None, typing: bool = False):
        """Edit option: valid value pending (dropped if same as saved), invalid typed text marked

        Args:
            typing: text being typed: shown as typed, keys typed in a row are one undo step.
        """
        info = self._infos.get(option_id)
        if info is None:
            return
        before = self._snapshot()
        now = time.monotonic()
        # Keys typed in a row, and the text once the field is left: one undo step
        same_typing = text is not None and self._typing[0] == option_id and (
            not typing or now - self._typing[1] < TYPING_GROUP_SECONDS)
        self._typing = (option_id, now) if typing else ("", 0.0)
        if typing and text is not None:
            self._typed[option_id] = text
        else:
            self._typed.pop(option_id, None)
        reason = self.check(info, value) if text is None else self.text_reason(info, text)
        if text is not None and not reason:
            value = text_value(info, text)
        if reason:
            self._invalid[option_id] = (text if text is not None else str(value), reason)
            self._pending.pop(option_id, None)
        else:
            self._invalid.pop(option_id, None)
            if value == self.saved(info):
                self._pending.pop(option_id, None)
            else:
                self._pending[option_id] = value
        if self._snapshot() != before and not same_typing:
            self._undo.append(before)
            del self._undo[:-100]
            self._redo.clear()
        if typing:
            self.typed(option_id)
        else:
            self.changed()

    def text_reason(self, info: OptionInfo, text: str) -> str:
        if info.kind.kind == KIND_FILE:
            return self.check(info, text)
        return text_reason(info, text)

    @Slot(str, bool)
    def setBool(self, option_id: str, value: bool):
        if option_id in IMMEDIATE_SWITCHES:
            self.switch_now(option_id, bool(value))
        else:
            self._edit(option_id, bool(value))

    def switch_now(self, option_id: str, value: bool):
        """Feature switch saved & applied at once (see IMMEDIATE_SWITCHES), other pending edits kept"""
        info = self._infos.get(option_id)
        if info is None:
            return
        self._pending.pop(option_id, None)
        self._invalid.pop(option_id, None)
        if bool(self.saved(info)) == value:
            self.changed()
            return
        cfg.user.config[info.section][info.key] = value
        cfg.save(config_type=ConfigType.CONFIG)
        apply_switch(IMMEDIATE_SWITCHES[option_id])
        self.changed()
        self.sectionChanged.emit()
        app_signal.refresh.emit(True)  # its own page, notices & status cards follow

    @Slot(str, int)
    def setChoice(self, option_id: str, index: int):
        info = self._infos.get(option_id)
        if info is None:
            return
        values = self.choices(info)
        if 0 <= index < len(values):
            self._edit(option_id, values[index])

    @Slot(str, str)
    def setText(self, option_id: str, text: str):
        """Text of a field once typed (Enter, field left): value taken & shown as saved"""
        self._edit(option_id, text=text)

    @Slot(str, str)
    def typeText(self, option_id: str, text: str):
        """Text being typed: taken at once (unsaved changes bar, Apply, Ctrl+S see it), checked as typed"""
        self._edit(option_id, text=text, typing=True)

    @Slot(str, float)
    def setNumber(self, option_id: str, number: float):
        info = self._infos.get(option_id)
        if info is None:
            return
        value: int | float = number
        if info.kind.kind == KIND_INTEGER or float(number).is_integer():
            value = round(number)
        self._edit(option_id, value)

    @Slot(str)
    def revertOption(self, option_id: str):
        """Saved value back in field (Esc in a field)"""
        info = self._infos.get(option_id)
        if info is not None and (option_id in self._pending or option_id in self._invalid):
            self._edit(option_id, self.saved(info))

    @Slot(str)
    def resetOption(self, option_id: str):
        """Option back to default (pending until applied)"""
        info = self._infos.get(option_id)
        if info is None or self.default(info) is None:
            return
        if option_id in IMMEDIATE_SWITCHES:
            self.switch_now(option_id, bool(self.default(info)))
        else:
            self._edit(option_id, self.default(info))

    @Slot()
    def resetCategory(self):
        """Every option of shown category back to default, after confirmation"""
        category = self.category_of(self._category)
        text = trm(f"Reset all <b>{category_label(category)}</b> options to default?<br><br>"
                   "Changes are only saved after clicking Apply or Save Button.")
        ask = getattr(self._host, "ask", None)  # over the page, answer by callback
        if callable(ask):
            ask(text, tr("Reset Section"), partial(self._reset_category, category.key))
        else:
            self._reset_category(category.key, self._host.confirm(text))

    def _reset_category(self, key: str, confirmed: bool):
        """Every option of category back to default (pending) once confirmed"""
        if not confirmed:
            return
        category = self.category_of(key)
        before = self._snapshot()
        for info in self._infos.values():
            if info.category != category.key:
                continue
            default = self.default(info)
            if default is None:
                continue
            self._invalid.pop(info.id, None)
            if default == self.saved(info):
                self._pending.pop(info.id, None)
            else:
                self._pending[info.id] = default
        if self._snapshot() != before:
            self._undo.append(before)
            del self._undo[:-100]
            self._redo.clear()
        self.changed()

    def _rebased(self, state: tuple[dict, dict], replaced: dict[str, Any]) -> tuple[dict, dict]:
        """Undo or redo state on newly saved values: same values shown, pending where they differ

        Global font override choices are dropped: applied once, never pending again (would apply twice).

        Args:
            replaced: option id: value saved before (state pending edits were relative to it).
        """
        pending = {key: value for key, value in state[0].items() if not key.startswith(FONT_PREFIX)}
        invalid = {key: value for key, value in state[1].items() if not key.startswith(FONT_PREFIX)}
        for option_id, previous in replaced.items():
            if option_id in invalid or option_id not in self._infos:
                continue  # typed text shown, nothing pending
            value = pending.get(option_id, previous)
            if value == self.saved(self._infos[option_id]):
                pending.pop(option_id, None)
            else:
                pending[option_id] = value
        return pending, invalid

    def _restore(self, state: tuple[dict, dict]):
        # Options gone from config.json since (history kept across Apply & refresh) skipped
        self._pending = {key: value for key, value in state[0].items() if key in self._infos}
        self._invalid = {key: value for key, value in state[1].items() if key in self._infos}
        self._typed.clear()  # fields show restored values
        self._typing = ("", 0.0)
        self.changed()

    @Slot()
    def undo(self):
        if self._undo:
            self._redo.append(self._snapshot())
            self._restore(self._undo.pop())

    @Slot()
    def redo(self):
        if self._redo:
            self._undo.append(self._snapshot())
            self._restore(self._redo.pop())

    @Slot()
    def discard(self):
        """Drop every pending edit"""
        if self._pending or self._invalid:
            self._undo.append(self._snapshot())
            del self._undo[:-100]
            self._redo.clear()
            self._pending.clear()
            self._invalid.clear()
            self._typed.clear()
            self.changed()

    def is_modified(self) -> bool:
        return bool(self._pending or self._invalid)

    def _check_paths(self):
        """Folders checked (config.json folders created) now: a folder that cannot be used is marked invalid"""
        for info in self._infos.values():
            if info.kind.kind != KIND_PATH or info.id not in self._pending:
                continue
            text = str(self._pending[info.id])
            if info.store == STORE_PRESET:  # folder read only (pace notes sounds): never created
                from ...userfile import set_relative_path

                path = set_relative_path(text.strip()) if text.strip() else None
            else:
                path = parse_path(text)
            if path is None:
                self._invalid[info.id] = (str(self._pending.pop(info.id)), "Folder cannot be used")
            else:
                self._pending[info.id] = path

    @Slot(result=bool)
    def apply(self) -> bool:
        """Save pending edits & apply them, False (nothing saved) if a value is invalid or saving into
        another preset than the one edited is refused

        Settings of config.json and of the loaded preset are saved each in their file, global font
        override choices are applied to every overlay of the loaded preset (Undo offered by the host).
        """
        self._check_paths()
        if self._invalid:
            self.changed()
            self.show_first_error()
            return False
        if not self._pending:
            return True
        font_edits = [option for option in self._pending if option.startswith(FONT_PREFIX)]
        if self.preset_pending() and cfg.filename.setting != self._preset_file:
            name = cfg.filename.setting.removesuffix(".json")
            if not self._host.confirm(trm(
                    f"Preset <b>{name}</b> was loaded since this page was opened."
                    f"<br><br>Save changed options to <b>{name}</b>?")):
                return False
            self._preset_file = cfg.filename.setting
        sections: set[str] = set()  # config.json
        preset_sections: set[str] = set()
        restart: list[str] = []  # options read when app starts
        saved_options: list[str] = []  # config.json option ids saved, see applied_options
        replaced: dict[str, Any] = {}  # option id: value saved before
        choice = self.font_choice()
        for option, value in self._pending.items():
            info = self._infos[option]
            if info.store == STORE_FONT:
                continue
            replaced[option] = self.saved(info)
            if info.store == STORE_PRESET:
                cfg.user.setting[info.section][info.key] = value
                preset_sections.add(info.section)
            else:
                cfg.user.config[info.section][info.key] = value
                sections.add(info.section)
                saved_options.append(option)
            if APPLIES_AT.get(option) == APPLIES_RESTART:
                restart.append(option_label(info.key))
        font_undo: dict = {}
        if font_edits:
            font_undo = font_override.apply_changes(
                cfg.user.setting, font_override.font_changes(cfg.user.setting, choice))
        self._pending.clear()
        self._typed.clear()
        self._typing = ("", 0.0)  # keys typed next: a new undo step
        # History kept: undoing an applied edit makes the previous value pending again (Apply needed)
        self._undo = [self._rebased(state, replaced) for state in self._undo]
        self._redo = [self._rebased(state, replaced) for state in self._redo]
        if "user_path" in sections:
            cfg.update_path()
        if sections:
            cfg.save(0, config_type=ConfigType.CONFIG)
        if preset_sections or font_undo:
            cfg.save(0)
        self.changed()
        self.sectionChanged.emit()
        if sections:
            self.applied_options = saved_options  # the host picks what to refresh or restart from them
            self._host.applied(sections, restart)
        if preset_sections or font_edits:
            applied_preset = getattr(self._host, "applied_preset", None)
            if callable(applied_preset):
                undo = self._font_undo(font_undo) if font_undo else None
                applied_preset(preset_sections, sections, len({section for section, _ in font_undo}), undo)
        return True

    def _font_undo(self, replaced: dict) -> Callable[[], bool]:
        """Undo of an applied global font override: values put back if the same preset is still loaded"""
        preset_file = cfg.filename.setting

        def undo() -> bool:
            if cfg.filename.setting != preset_file:
                return False
            font_override.apply_changes(cfg.user.setting, replaced)
            cfg.save(0)
            self.update_font_preview()
            self.notify_state()
            return True

        return undo

    @Slot()
    def showFirstError(self):
        """Show the first invalid value (Show button of the unsaved changes bar)"""
        self.show_first_error()

    def show_first_error(self):
        option = next((info.id for info in self._infos.values() if info.id in self._invalid), "")
        if not option:
            return
        info = self._infos[option]
        if self.filtering() and not self.matches(info):
            self.setChangedOnly(False)
            self.setSearch("")
        if not self.filtering():
            if info.store == STORE_CONFIG:
                self.focus_option(info.section, info.key)
            else:
                self.selectCategory(info.category)
                self._highlight = ""
                self.highlightChanged.emit()
                self._highlight = option
                self.highlightChanged.emit()

    @Slot()
    def refresh(self):
        """Saved settings changed elsewhere (menus, other pages, preset loaded): shown values & status
        cards updated"""
        known = set(self._infos)
        self._infos = {info.id: info for category in self.category_list() for info in category_options(category)}
        for option in list(self._pending):
            if option not in self._infos:
                self._pending.pop(option)
            elif self._pending[option] == self.saved(self._infos[option]):
                self._pending.pop(option)  # same value saved meanwhile
        if known != set(self._infos):
            self._invalid = {key: value for key, value in self._invalid.items() if key in self._infos}
        self.changed()
        self.infoChanged.emit()
        self.sectionChanged.emit()

    # Preset section on / off (at once, like the Modules page)
    @Slot(bool)
    def setSectionEnabled(self, enabled: bool):
        category = self.category_of(self._category)
        section = category_section(category)
        options = cfg.user.setting.get(section)
        if category.store != STORE_PRESET or not isinstance(options, dict) or ENABLE_KEY not in options:
            return
        if bool(options[ENABLE_KEY]) == enabled:
            return
        from ...module_control import mctrl

        if section in mctrl.names:
            mctrl.toggle(section)  # module started or stopped, saved
        else:
            options[ENABLE_KEY] = enabled
            cfg.save()
        self.sectionChanged.emit()
        app_signal.refresh.emit(True)  # other pages, notices, pace notes player

    # Dialogs & links
    @Slot(str)
    def pickColor(self, option_id: str):
        info = self._infos.get(option_id)
        if info is None:
            return
        color = self._host.pick_color(str(self.value(info)))
        if color:
            self._edit(option_id, color)

    @Slot(str)
    def browse(self, option_id: str):
        """Choose folder (path option), image file or other file"""
        info = self._infos.get(option_id)
        if info is None:
            return
        current = str(self.value(info))
        if info.kind.kind == KIND_PATH:
            from ...userfile import set_relative_path

            folder = self._host.pick_folder(current)
            if folder:
                self._edit(option_id, text=set_relative_path(folder))
        elif info.kind.kind == KIND_IMAGE:
            filename = self._host.pick_image(current)
            if filename:
                self._edit(option_id, text=filename)
        elif info.kind.kind == KIND_FILE:
            pick_file = getattr(self._host, "pick_file", None)
            filename = pick_file(current, FILE_FILTERS.get(f"{info.section}/{info.key}", "")) if callable(pick_file) else ""
            if filename:
                self._edit(option_id, text=filename)

    @Slot(str)
    def openFolder(self, option_id: str):
        """Open folder of path option (saved value) in file manager"""
        info = self._infos.get(option_id)
        if info is not None:
            self._host.open_folder(os.path.abspath(str(self.saved(info))))

    @Slot()
    def openConfigFolder(self):
        self._host.open_folder(os.path.abspath(cfg.path.config))

    @Slot(str)
    def openLink(self, name: str):
        """Settings kept elsewhere"""
        self._host.open_link(name)

    @Slot()
    def testSound(self):
        """Pace notes: a sound of the sound folder played with the volume shown (pending values)"""
        test_sound = getattr(self._host, "test_sound", None)
        if not callable(test_sound):
            return
        values = {
            info.key: self.value(info) for info in self._infos.values()
            if info.store == STORE_PRESET and info.section == "pace_notes_playback"
        }
        message = test_sound(values)
        if message:
            self._toast(message)

    def _toast(self, text: str):
        toast = getattr(self._host, "toast", None)
        if callable(toast):
            toast(text)

    @Slot(str)
    def copyText(self, text: str):
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
            self._toast(tr("Copied"))  # told: nothing else shows the copy


def text_reason(info: OptionInfo, text: str) -> str:
    """Why typed text is invalid (English), "" if valid"""
    if info.kind.kind in NUMBER_KINDS:
        from .option_kinds import parse_number

        value = parse_number(info.kind, text)
        return "Number required" if value is None else check_value(info.key, info.kind, value)
    return check_value(info.key, info.kind, text)


def text_value(info: OptionInfo, text: str) -> Any:
    """Value of valid typed text"""
    if info.kind.kind in NUMBER_KINDS:
        from .option_kinds import parse_number

        return parse_number(info.kind, text)
    if info.kind.kind == KIND_COLOR:
        return text.strip().upper()
    return text
