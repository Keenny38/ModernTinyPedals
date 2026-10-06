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
Navigation rail entries: pages of main window & tool dialogs, chosen & ordered by user

Rail content is saved in application setting "rail_items": entry keys separated by comma,
page keys (see NAV_PAGES) or tool dialog module names (see tools_view.TOOL_SECTIONS).
Pages left out of the rail stay reachable from command palette (Ctrl+K).
"""

from __future__ import annotations

from typing import NamedTuple

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from ..const_file import ConfigType
from ..i18n import tr
from ..setting import cfg
from ..template.setting_global import GLOBAL_DEFAULT
from ._common import BaseEditor, FocusRingButton, UIScaler
from .ordered_picker import OrderedPicker, PickerEntry, icon_font_family
from .tools_view import RENAMED_TOOL_KEYS, TOOL_SECTIONS

# Pages: (key, label, icon glyph in Segoe Fluent Icons / MDL2 Assets, fallback letter)
NAV_PAGES = (
    ("home", "Home", "", "A"),  # home
    ("widget", "Overlays", "", "W"),  # all apps grid
    ("module", "Module", "", "M"),  # diagnostic
    ("preset", "Preset", "", "P"),  # library
    ("spectate", "Spectate", "", "S"),  # view
    ("pacenotes", "Pacenotes", "", "N"),  # quick note
    ("hotkey", "Hotkey", "", "H"),  # keyboard
    ("tools", "Tools", "", "T"),  # developer tools
)
PAGE_INDEX = {key: index for index, (key, *_) in enumerate(NAV_PAGES)}

# Short rail label of tools (rail buttons are narrow), full name in tooltip
TOOL_SHORT_LABELS = {
    "race_calculator": "Race",
    "driver_stats_viewer": "Stats",
    "track_map_viewer": "Map",
    "lap_viewer": "Telemetry",
    "replay_view": "Recorder",
    "game_replays": "Replays",
    "race_results_viewer": "Results",
    "stream_overlay_view": "Stream",
    "heatmap_editor": "Heatmap",
    "brake_editor": "Brakes",
    "tyre_compound_editor": "Compounds",
    "vehicle_brand_editor": "Brands",
    "vehicle_class_editor": "Classes",
    "track_info_editor": "Tracks",
    "track_notes_editor": "Notes",
    "layout_editor": "Layout",
    "preset_compare": "Compare",
    "plugin_manager": "Plugins",
    "perf_view": "Performance",
}


class RailEntry(NamedTuple):
    """Navigation rail entry"""

    key: str
    label: str  # short label under icon
    tooltip: str  # full name
    glyph: str
    letter: str  # drawn without icon font
    page: int = -1  # page index, -1 for tool
    dialog: str = ""  # "module.DialogClass" of tool


def rail_entries() -> dict[str, RailEntry]:
    """Every possible rail entry by key, pages first then tools"""
    entries = {
        key: RailEntry(key, label, label, glyph, letter, page=index)
        for index, (key, label, glyph, letter) in enumerate(NAV_PAGES)
    }
    for _, tools in TOOL_SECTIONS:
        for label, glyph, dialog_path in tools:
            key = dialog_path.split(".", 1)[0]
            short = TOOL_SHORT_LABELS.get(key, label)
            entries[key] = RailEntry(key, short, label, glyph, short[:1], dialog=dialog_path)
    return entries


def parse_rail_items(text: str) -> list[str]:
    """Known & unique entry keys of rail setting text, in order"""
    known = rail_entries()
    keys: list[str] = []
    for key in (text or "").split(","):
        key = RENAMED_TOOL_KEYS.get(key.strip(), key.strip())  # merged tools: new tool
        if key in known and key not in keys:
            keys.append(key)
    return keys


def default_rail_items() -> list[str]:
    application: dict = GLOBAL_DEFAULT["application"]  # type: ignore[assignment]
    return parse_rail_items(str(application["rail_items"]))


def current_rail_items() -> list[str]:
    """Rail entry keys from setting, default rail if setting has no valid entry"""
    return parse_rail_items(cfg.application.get("rail_items", "")) or default_rail_items()


class RailEditor(BaseEditor):
    """Choose & order navigation rail entries (shown entries & available ones, see OrderedPicker)

    Subclass for another list of entries: override TITLE, HELP, picker_entries, badge_text,
    current_items, default_items & save_items. Changes are marked unsaved, Ctrl+S saves (page kept
    open), Save saves & closes, Ctrl+Z / Ctrl+Y undo & redo.
    """

    TITLE = "Customize Navigation Bar"
    HELP = (
        "Drag entries to reorder, or use the arrows. Add entries from the list on the right. "
        "Ctrl+1 to Ctrl+9 open the first 9 entries, hidden pages stay in command palette (Ctrl+K)."
    )

    def __init__(self, parent, on_saved=None):
        super().__init__(parent)
        self.set_utility_title(tr(self.TITLE))
        self.setMinimumSize(UIScaler.size(26), UIScaler.size(30))
        self.resize(UIScaler.size(48), UIScaler.size(36))
        self._on_saved = on_saved
        label = QLabel(tr(self.HELP))
        label.setObjectName("pickerHelp")
        label.setWordWrap(True)
        self.picker = OrderedPicker(self, self.picker_entries(), self.current_items(), icon_font_family(),
                                    badge=self.badge_text)
        self.picker.changed.connect(self.set_modified)
        self.list_entries = self.picker.shown_list
        self.enable_undo(self.picker.shown_keys, lambda keys: self.picker.set_shown(keys, notify=False))

        self.button_reset = FocusRingButton(tr("Reset"))
        self.button_reset.setToolTip(tr("Back to default entries"))
        self.button_reset.clicked.connect(self.reset)
        self.button_cancel = FocusRingButton(tr("Close"))
        self.button_cancel.clicked.connect(self.close)
        self.button_save = FocusRingButton(tr("Save"))
        self.button_save.setObjectName("editorPrimary")
        self.button_save.setDefault(True)
        self.button_save.clicked.connect(self.save_and_close)
        layout_button = QHBoxLayout()
        layout_button.addWidget(self.button_reset)
        self.add_undo_buttons(layout_button)
        layout_button.addStretch(1)
        layout_button.addWidget(self.button_cancel)
        layout_button.addWidget(self.button_save)

        layout = QVBoxLayout(self)
        layout.setSpacing(UIScaler.pixel(10))
        layout.addWidget(label)
        layout.addWidget(self.picker, stretch=1)
        layout.addLayout(layout_button)
        layout.setContentsMargins(self.MARGIN * 2, self.MARGIN * 2, self.MARGIN * 2, self.MARGIN * 2)

    def showEvent(self, event):
        """Shown as page: page has its own Close button"""
        super().showEvent(event)
        if self.in_app_page:
            self.button_cancel.hide()

    # Entries
    def picker_entries(self) -> dict[str, PickerEntry]:
        """Every possible entry: pages, then tools"""
        kinds = {True: (tr("Pages"), tr("Page")), False: (tr("Tools"), tr("Tool"))}
        return {
            key: PickerEntry(key, tr(entry.tooltip), entry.glyph, entry.letter, kinds[entry.page >= 0][0],
                             tag=kinds[entry.page >= 0][1])
            for key, entry in rail_entries().items()
        }

    def badge_text(self, row: int) -> str:
        """Shortcut of entry (first 9 entries)"""
        return f"Ctrl+{row + 1}" if row < 9 else ""

    def current_items(self) -> list[str]:
        return current_rail_items()

    def default_items(self) -> list[str]:
        return default_rail_items()

    def save_items(self, keys: list[str]):
        cfg.application["rail_items"] = ",".join(keys) if keys else ",".join(default_rail_items())

    # Editing
    def checked_items(self) -> list[str]:
        """Shown entries in order"""
        return self.picker.shown_keys()

    def fill(self, shown: list[str]):
        self.picker.set_shown(shown)

    def move_current(self, step: int):
        self.picker.move_selected(step)

    def reset(self):
        """Default entries (saved with Save)"""
        if self.checked_items() != self.default_items():
            self.picker.set_shown(self.default_items())

    def applying(self):
        """Save, editor kept open (Ctrl+S)"""
        self.save_items(self.checked_items())
        cfg.save(config_type=ConfigType.CONFIG)
        if self._on_saved is not None:
            self._on_saved()
        self.set_unmodified()

    def saving(self):
        """Save (also asked when closing with unsaved changes)"""
        self.applying()

    def save_and_close(self):
        self.applying()
        self.accept()
