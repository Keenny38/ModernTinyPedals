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
Settings page backend (qml/Settings.qml): every global option of config.json, by category

Categories are sections of config.json (Application, Overlay Style, Compatibility...), options shown
in groups with their description, an editor matching their kind (switch, choice, number, color,
folder...) and a reset to default. Edits stay pending (undo & redo) until applied: invalid values
are marked at once and block Apply. A search looks through every category.
"""

from __future__ import annotations

import os
import time
from typing import Any, NamedTuple, Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication

from ... import app_signal
from ...const_file import ConfigType
from ...i18n import current_language, tr, trm
from ...i18n.options import option_help_specific, option_label
from ...setting import cfg
from ..config import HIDDEN_OPTIONS
from ..module_view import sort_key
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
    decimals,
    display_text,
    font_families,
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
    "color", "modified", "changed", "error", "defaultText", "applies",
)
TYPING_GROUP_SECONDS = 1.5  # keys typed in one option within this time: one undo step
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


class Category(NamedTuple):
    """Settings page category: one section of config.json, options in groups"""

    key: str  # config.json section
    label: str
    glyph: str  # Segoe Fluent Icons / MDL2 Assets
    description: str
    groups: tuple[tuple[str, tuple[str, ...]], ...] = ()  # (title, option keys), others in "Other"


CATEGORIES = (
    Category("application", "Application", "\ue713", "Interface, startup, updates, presets & backups, overlay editing", (
        ("Interface", (
            "language", "window_color_theme", "enable_high_dpi_scaling", "show_overlay_previews",
            "show_option_group_title", "show_confirmation_for_batch_toggle",
        )),
        ("Startup & Window", (
            "show_at_startup", "minimize_to_tray", "remember_position", "remember_size", "remember_open_pages",
            "show_setup_wizard_at_startup",
        )),
        ("Updates", ("check_for_updates_on_startup", "update_repository")),
        ("Presets & Backups", (
            "enable_auto_load_preset", "number_of_automatic_backups", "number_of_days_to_keep_deleted_presets",
            "maximum_loading_attempts", "maximum_saving_attempts",
        )),
        ("Overlay Editing", (
            "enable_edit_mode_on_unlock", "enable_magnetic_snap", "snap_distance", "snap_gap", "show_layout_guides",
            "grid_move_size", "enable_layout_per_screen_setup",
        )),
        ("Performance & Hotkeys", ("minimum_update_interval", "enable_global_hotkey")),
    )),
    Category("overlay_style", "Overlay Style", "\ue790", "Modern design, theme, fonts & size of every overlay", (
        ("Design", (
            "overlay_theme", "enable_colorblind_colors", "enable_depth_effects", "enable_fade_animation",
            "corner_radius_scale", "minimum_bar_gap",
        )),
        ("Font", ("enable_modern_font", "modern_font_name", "modern_design_font_name")),
        ("Size", ("overlay_scale",)),
    )),
    Category("notification", "Notification", "\uea8f", "Notices shown at the bottom of the main window", (
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
    )),
    Category("compatibility", "Compatibility", "\ue7f8", "Window manager, transparency & positions on some systems"),
    Category("remote_control", "Remote Control", "\ue704", "Run hotkey commands from a Stream Deck or a script"),
    Category("web_dashboard", "Web Dashboard", "\ue774", "Overlays in a browser of your phone, tablet or PC"),
    Category("stream_overlay", "Stream Overlay", "\ue93e",
             "Overlays in OBS, Streamlabs, XSplit or vMix: addresses on the Stream Overlays page"),
    Category("vr_overlay", "VR Overlay", "\ue7f4", "Experimental: overlays in your VR headset, OpenXR & SteamVR games", (
        ("VR Overlay", ("enable_vr_overlay", "enable_openxr_layer", "enable_attach_to_headset", "update_interval")),
        ("Placement", (
            "overlay_width_meters", "distance_meters", "vertical_offset_meters", "horizontal_offset_meters")),
        ("Mirror Window", ("enable_vr_mirror_window", "mirror_background_color")),
    )),
    Category("user_path", "User Path", "\ue8b7", "Folders of presets, data & recorded laps"),
)
CATEGORY_KEYS = tuple(category.key for category in CATEGORIES)
# Notice previews (Notification category): group title -> font & background color options
NOTICE_COLORS = {
    title: (keys[1], keys[2]) for title, keys in CATEGORIES[CATEGORY_KEYS.index("notification")].groups
}


class SettingsHost(Protocol):
    """Page hosting the backend: dialogs & applying saved settings"""

    def confirm(self, text: str) -> bool: ...
    def pick_color(self, color: str) -> str: ...
    def pick_folder(self, folder: str) -> str: ...
    def pick_image(self, filename: str) -> str: ...
    def open_folder(self, folder: str) -> None: ...
    def applied(self, sections: set[str], restart: list[str]) -> None: ...
    def open_link(self, name: str) -> None: ...


class OptionInfo(NamedTuple):
    """Option shown by the page"""

    section: str
    key: str
    group: str  # English group title
    kind: OptionKind

    @property
    def id(self) -> str:
        return f"{self.section}/{self.key}"


def category_options(category: Category) -> list[OptionInfo]:
    """Options of category in page order: groups, then options of no group ("Other")"""
    options = cfg.user.config.get(category.key, {})
    hidden = HIDDEN_OPTIONS.get(category.key, ())
    keys = [key for key in options if key not in hidden]
    defaults = cfg.default.config.get(category.key, {})
    infos: list[OptionInfo] = []
    grouped: set[str] = set()
    for title, group_keys in category.groups:
        for key in group_keys:
            if key in options and key not in hidden:
                infos.append(OptionInfo(category.key, key, title, value_kind(key, defaults.get(key, options[key]))))
                grouped.add(key)
    rest = [key for key in keys if key not in grouped]
    rest_title = OTHER_GROUP if category.groups else category.label
    infos.extend(
        OptionInfo(category.key, key, rest_title, value_kind(key, defaults.get(key, options[key]))) for key in rest)
    return infos


class SettingsBackend(QObject):
    """Settings page state & actions

    Args:
        parent: page dialog.
        host: dialogs (color, folder...) & what to do once settings are saved.
    """

    categoryChanged = Signal()
    stateChanged = Signal()  # pending edits, errors, undo & redo
    filterChanged = Signal()
    infoChanged = Signal()  # saved values: status cards (web dashboard, remote control)
    highlightChanged = Signal()

    def __init__(self, parent, host: SettingsHost):
        super().__init__(parent)
        self._host = host
        self.model = DictListModel(ROLES, self)
        self._infos: dict[str, OptionInfo] = {}
        self._category = CATEGORY_KEYS[0]
        self._pending: dict[str, Any] = {}  # option id: valid value not saved yet
        self._invalid: dict[str, tuple[str, str]] = {}  # option id: (typed text, English reason)
        self._typed: dict[str, str] = {}  # option id: text being typed, shown as typed (not reformatted)
        self._typing = ("", 0.0)  # option typed last & when, see typeText
        self._undo: list[tuple[dict, dict]] = []
        self._redo: list[tuple[dict, dict]] = []
        self._search = ""
        self._words: tuple[str, ...] = ()
        self._highlight = ""
        # Navigation entries (read several times per change by the page): made again once state changes
        self._categories: tuple[str, list[dict]] | None = None  # (language, entries)
        self.stateChanged.connect(self._drop_categories)  # before page bindings: connected first
        app_signal.addresses.connect(self.infoChanged)  # LAN addresses found in background
        app_signal.servers.connect(self.infoChanged)  # server listening once its port is available again
        self.load_options()

    # Options
    def load_options(self):
        """Options of every category (config.json may gain options after an update)"""
        self._infos = {
            info.id: info for category in CATEGORIES for info in category_options(category)
        }
        self.update_rows()

    @staticmethod
    def saved(info: OptionInfo) -> Any:
        return cfg.user.config[info.section][info.key]

    @staticmethod
    def default(info: OptionInfo) -> Any:
        return cfg.default.config.get(info.section, {}).get(info.key)

    def value(self, info: OptionInfo) -> Any:
        """Edited value (pending), else saved"""
        return self._pending.get(info.id, self.saved(info))

    def shown_infos(self) -> list[OptionInfo]:
        """Options of current category, or matching search in every category"""
        if self._words:
            return [info for info in self._infos.values() if self.matches(info)]
        return [info for info in self._infos.values() if info.section == self._category]

    def matches(self, info: OptionInfo) -> bool:
        category = CATEGORIES[CATEGORY_KEYS.index(info.section)]
        text = sort_key(
            f"{option_label(info.key)} {info.key.replace('_', ' ')} {info.key} {tr(info.group)} {tr(category.label)}")
        return all(word in text for word in self._words)

    def group_title(self, info: OptionInfo) -> str:
        """Group title of option, "" for the only group of a category (page title says it)"""
        category = CATEGORIES[CATEGORY_KEYS.index(info.section)]
        if not self._words:
            return "" if info.group == category.label else tr(info.group)
        if info.group == category.label:
            return tr(category.label)
        return f"{tr(category.label)}  {GROUP_SEPARATOR}  {tr(info.group)}"

    def row(self, info: OptionInfo) -> dict:
        kind = info.kind
        value = self.value(info)
        default = self.default(info)
        invalid = self._invalid.get(info.id)
        row: dict[str, Any] = {
            "key": info.id,
            "section": info.section,
            "option": info.key,
            "label": option_label(info.key),
            "help": option_help_specific(info.section, info.key),
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
            "defaultText": display_text(kind, default) if default is not None else "",
            "applies": APPLIES_AT.get(info.id, ""),
        }
        if kind.kind in (KIND_CHOICE, KIND_FONT):
            values = list(choice_values(kind))
            if value not in values:
                values.insert(0, value)  # uninstalled font, removed language pack: kept until changed
            row["choices"] = [choice_label(kind, choice) for choice in values]
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
        self.update_rows()
        self.stateChanged.emit()

    # Properties
    @Property(QObject, constant=True)
    def options(self) -> QObject:
        return self.model

    @Slot()
    def _drop_categories(self):
        self._categories = None

    @Property(list, notify=stateChanged)
    def categories(self) -> list[dict]:
        """Navigation entries: pending edits, invalid values & search matches of each category

        Kept until state changes (edits, search, category, refresh: stateChanged) or language changes.
        """
        language = current_language()
        if self._categories is not None and self._categories[0] == language:
            return self._categories[1]
        entries = []
        for category in CATEGORIES:
            infos = [info for info in self._infos.values() if info.section == category.key]
            entries.append({
                "key": category.key,
                "label": tr(category.label),
                "glyph": category.glyph,
                "changed": sum(info.id in self._pending or info.id in self._invalid for info in infos),
                "errors": sum(info.id in self._invalid for info in infos),
                "matches": sum(self.matches(info) for info in infos) if self._words else 0,
            })
        self._categories = (language, entries)
        return entries

    @Property(str, notify=categoryChanged)
    def category(self) -> str:
        return self._category

    @Property(dict, notify=categoryChanged)
    def categoryInfo(self) -> dict:
        category = CATEGORIES[CATEGORY_KEYS.index(self._category)]
        return {
            "key": category.key,
            "label": tr(category.label),
            "glyph": category.glyph,
            "description": tr(category.description),
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
                return f"{option_label(info.key)}: {trm(tr(self._invalid[info.id][1]))}"
        return ""

    @Property(bool, notify=stateChanged)
    def canUndo(self) -> bool:
        return bool(self._undo)

    @Property(bool, notify=stateChanged)
    def canRedo(self) -> bool:
        return bool(self._redo)

    @Property(str, notify=filterChanged)
    def searchText(self) -> str:
        return self._search

    @Property(bool, notify=filterChanged)
    def searching(self) -> bool:
        return bool(self._words)

    @Property(int, notify=filterChanged)
    def matchCount(self) -> int:
        return self.model.rowCount() if self._words else 0

    @Property(str, notify=highlightChanged)
    def highlightKey(self) -> str:
        """Option to scroll to & flash (opened from option search)"""
        return self._highlight

    @Property(dict, notify=stateChanged)
    def previews(self) -> dict:
        """Notice previews of Notification category: group title -> text, font & background colors"""
        result = {}
        for title, (font_key, background_key) in NOTICE_COLORS.items():
            font = self._color_value("notification", font_key)
            background = self._color_value("notification", background_key)
            result[tr(title)] = {"text": tr(title), "color": font, "background": background}
        return result

    def _color_value(self, section: str, key: str) -> str:
        info = self._infos.get(f"{section}/{key}")
        value = self.value(info) if info is not None else ""
        return value if isinstance(value, str) and check_value(key, OptionKind(KIND_COLOR), value) == "" else ""

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
        return {
            "enabled": bool(setting["enable_remote_control"]),
            "running": cmdserver.running,
            "command": f'curl -X POST -H "{REQUIRED_HEADER}: 1" http://{address}/command/overlay_lock',
            "commands": f"http://{address}/commands",
            "stream": f"ws://{address}/stream",
        }

    @Property(str, constant=True)
    def configFile(self) -> str:
        return os.path.abspath(os.path.join(cfg.path.config, cfg.filename.config))

    # Navigation & search
    @Slot(str)
    def selectCategory(self, key: str):
        if key not in CATEGORY_KEYS:
            return
        if self._words:  # leave search for the category
            self._search, self._words = "", ()
            self.filterChanged.emit()
        if key != self._category:
            self._category = key
            self.categoryChanged.emit()
        self.update_rows()
        self.stateChanged.emit()

    @Slot(str)
    def setSearch(self, text: str):
        self._search = text
        words = tuple(sort_key(text).split())
        if words != self._words:
            self._words = words
            self.update_rows()
            self.stateChanged.emit()  # category match counts
        self.filterChanged.emit()

    def focus_option(self, section: str, key: str):
        """Show category of option & flash it (option search)"""
        option_id = f"{section}/{key}"
        if section in CATEGORY_KEYS:
            self.selectCategory(section)
        if option_id in self._infos:
            self._highlight = ""
            self.highlightChanged.emit()  # same option again: flashed again
            self._highlight = option_id
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
        reason = check_value(info.key, info.kind, value) if text is None else text_reason(info, text)
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
        self.changed()

    @Slot(str, bool)
    def setBool(self, option_id: str, value: bool):
        self._edit(option_id, bool(value))

    @Slot(str, int)
    def setChoice(self, option_id: str, index: int):
        info = self._infos.get(option_id)
        if info is None:
            return
        values = list(choice_values(info.kind))
        current = self.value(info)
        if current not in values:
            values.insert(0, current)
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
        if info is not None and self.default(info) is not None:
            self._edit(option_id, self.default(info))

    @Slot()
    def resetCategory(self):
        """Every option of shown category back to default, after confirmation"""
        category = CATEGORIES[CATEGORY_KEYS.index(self._category)]
        text = (f"Reset all <b>{tr(category.label)}</b> options to default?<br><br>"
                "Changes are only saved after clicking Apply or Save Button.")
        if not self._host.confirm(trm(text)):
            return
        before = self._snapshot()
        for info in self._infos.values():
            if info.section != category.key:
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

    def _restore(self, state: tuple[dict, dict]):
        self._pending, self._invalid = state
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

    @Slot(result=bool)
    def apply(self) -> bool:
        """Save pending edits & apply them, False (nothing saved) if a value is invalid

        Folders are checked (and created) now: a folder that cannot be used is marked invalid.
        """
        for info in self._infos.values():
            if info.kind.kind == KIND_PATH and info.id in self._pending:
                path = parse_path(str(self._pending[info.id]))
                if path is None:
                    self._invalid[info.id] = (str(self._pending.pop(info.id)), "Folder cannot be used")
                else:
                    self._pending[info.id] = path
        if self._invalid:
            self.changed()
            self.show_first_error()
            return False
        if not self._pending:
            return True
        sections: set[str] = set()
        restart: list[str] = []  # options read when app starts
        for option_id, value in self._pending.items():
            info = self._infos[option_id]
            cfg.user.config[info.section][info.key] = value
            sections.add(info.section)
            if APPLIES_AT.get(option_id) == APPLIES_RESTART:
                restart.append(option_label(info.key))
        self._pending.clear()
        self._typed.clear()
        self._undo.clear()
        self._redo.clear()
        if "user_path" in sections:
            cfg.update_path()
        cfg.save(0, config_type=ConfigType.CONFIG)
        self.changed()
        self._host.applied(sections, restart)
        return True

    def show_first_error(self):
        option_id = next((info.id for info in self._infos.values() if info.id in self._invalid), "")
        if option_id:
            section, key = option_id.split("/", 1)
            if self._words and not self.matches(self._infos[option_id]):
                self.setSearch("")
            if not self._words:
                self.focus_option(section, key)

    @Slot()
    def refresh(self):
        """Saved settings changed elsewhere (menus, other pages): shown values & status cards updated"""
        known = set(self._infos)
        self._infos = {info.id: info for category in CATEGORIES for info in category_options(category)}
        for option_id in list(self._pending):
            if option_id not in self._infos:
                self._pending.pop(option_id)
            elif self._pending[option_id] == self.saved(self._infos[option_id]):
                self._pending.pop(option_id)  # same value saved meanwhile
        if known != set(self._infos):
            self._invalid = {key: value for key, value in self._invalid.items() if key in self._infos}
        self.changed()
        self.infoChanged.emit()

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
        """Choose folder (path option) or image file"""
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
        """Settings kept elsewhere: units, global font override, API options"""
        self._host.open_link(name)

    @Slot(str)
    def copyText(self, text: str):
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)


def choice_values(kind: OptionKind) -> tuple[str, ...]:
    return font_families() if kind.kind == KIND_FONT else kind.choices


def display_value(kind: OptionKind, value: Any) -> str:
    """Editable text of value (text fields)"""
    if kind.kind in NUMBER_KINDS:
        return number_text(value)
    return str(value)


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

