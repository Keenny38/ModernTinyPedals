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
Setup wizard backend (qml/SetupWizard.qml): steps, choices & overlay previews in the chosen style

Texts follow the language picked in the wizard (own translation table, see SetupTranslator): the
wizard changes language at once, the app only when setup is finished. Overlay pictures are rendered
one per event loop tick once the Appearance step is reached, with the chosen theme (never saved),
and kept per style: going back to a theme shows its pictures at once.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import weakref
from collections import deque
from contextlib import suppress
from typing import NamedTuple

from PySide6.QtCore import Property, QObject, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QImage, QPalette

from ... import regex_pattern as rxp
from ...api_control import api
from ...const_api import API_LMU_NAME, API_LMULEGACY_NAME, API_RF2_NAME
from ...const_file import FileExt, ImageFile
from ...formatter import format_module_name, strip_filename_extension
from ...i18n import LANGUAGES, current_language, language_pack, load_translation, trm
from ...i18n.options import LABEL_LANGUAGES, load_data
from ...module_control import wctrl
from ...setting import cfg
from ...validator import is_allowed_filename
from ..setup_wizard import DEFAULT_STARTER, STARTER_WIDGETS, UNIT_SYSTEMS, UNITS_KEEP, SetupChoices
from . import Translator
from .models import DictListModel
from .overlay_backend import CATEGORY_COLORS, widget_category
from .preview_provider import STORE

logger = logging.getLogger(__name__)

# Steps: key, sidebar label, title, subtitle, glyph (Segoe Fluent Icons / MDL2 Assets)
STEP_WELCOME, STEP_GAME, STEP_UNITS, STEP_LOOK, STEP_OVERLAYS, STEP_READY = range(6)
STEPS = (
    ("welcome", "Welcome", "Welcome to Modern Tiny Pedals",
     "A few questions to get you started. Every choice can be changed later.", "\uE774"),  # globe
    ("game", "Game", "Which game do you play?",
     "Modern Tiny Pedals reads telemetry from the selected game.", "\uE804"),  # car
    ("units", "Units", "Units",
     "How overlays show speed, temperature, fuel, pressure and weight.", "\uEC48"),  # gauge
    ("look", "Appearance", "Appearance",
     "Colors of the app window and of the in-game overlays.", "\uE7F4"),  # monitor
    ("overlays", "Overlays", "Preset and overlays",
     "A preset stores the layout and options of all overlays.", "\uE81E"),  # layers
    ("ready", "Ready", "Ready to race",
     "Check your choices, then finish to start the overlays.", "\uE73E"),  # check
)
# Appearance step pictures, rendered first: overlays showing theme colors even without game data
STYLE_SAMPLES = ("fuel", "pedal", "gear", "flag")
THEME_SAMPLE = "session"  # overlay theme cards
PREVIEW_MAX = QSize(360, 240)  # tile picture, bigger overlays scaled down
PREVIEW_LOADING = 0
PREVIEW_READY = 1
PREVIEW_UNAVAILABLE = 2

UNIT_SYMBOLS = {  # shown on unit cards
    "KPH": "km/h", "MPH": "mph", "m/s": "m/s", "Celsius": "°C", "Fahrenheit": "°F",
    "Liter": "L", "Gallon": "gal", "Kilogram": "kg", "Pound": "lb",
}
UNIT_SAMPLE_KEYS = ("speed_unit", "temperature_unit", "fuel_unit", "tyre_pressure_unit", "weight_unit")

# Games: description, executable name prefixes (lower case, Linux cuts process names to 15 characters)
GAME_INFO = {
    API_LMU_NAME: ("Uses the shared memory of the game: nothing to install.", ("le mans ultima",)),
    API_LMULEGACY_NAME: ("Through the rF2 Shared Memory Map plugin (Linux, older game versions).", ("le mans ultima",)),
    API_RF2_NAME: ("Needs the rF2 Shared Memory Map plugin, enabled in the game.", ("rfactor2",)),
}
# Colors of window theme cards: palette role -> card part
MOCKUP_ROLES = {
    "window": QPalette.ColorRole.Window,
    "base": QPalette.ColorRole.Base,
    "text": QPalette.ColorRole.Text,
    "dim": QPalette.ColorRole.PlaceholderText,
    "accent": QPalette.ColorRole.Highlight,
    "border": QPalette.ColorRole.Mid,
    "raised": QPalette.ColorRole.Button,
}
TILE_ROLES = (
    "key", "label", "category", "tint", "checked", "sample",
    "preview", "previewWidth", "previewHeight", "previewState",
)


class Preview(NamedTuple):
    """Overlay picture as PNG data URL & size in logical pixels, empty url if it cannot be drawn"""

    url: str
    width: int
    height: int


def running_games() -> set[str]:
    """Names of games (API names) running now"""
    import psutil

    prefixes = {name: info[1] for name, info in GAME_INFO.items()}
    found: set[str] = set()
    for process in psutil.process_iter(["name"]):
        process_name = (process.info.get("name") or "").lower()
        found.update(name for name, starts in prefixes.items() if process_name.startswith(starts))
    return found


def unit_system(units: dict) -> str:
    """Unit system of preset units, "" if mixed"""
    for name, system in UNIT_SYSTEMS.items():
        if all(units.get(key) == value for key, value in system.items()):
            return name
    return UNITS_KEEP


def unit_samples(units: dict) -> list[str]:
    """Short unit symbols shown on unit cards"""
    return [UNIT_SYMBOLS.get(units.get(key, ""), units.get(key, "")) for key in UNIT_SAMPLE_KEYS]


def option_labels(code: str) -> dict[str, str]:
    """Widget & option labels of language (i18n.options labels, for a language not loaded in the app)"""
    if code in LABEL_LANGUAGES:
        return load_data(f"{code}_options.json")
    return dict(language_pack(code).get("options", {}))


def theme_mockup(name: str) -> dict[str, str]:
    """Colors of window theme card, from palette of theme"""
    from .. import palette_dark, palette_legacy_dark, palette_legacy_light, palette_light

    if name.startswith("Legacy"):
        palette = palette_legacy_light() if name.endswith("Light") else palette_legacy_dark()
    else:
        palette = palette_light() if name.endswith("Light") else palette_dark()
    colors = {role: active for active, _, _, role in palette}
    return {part: str(colors.get(role, "#808080")) for part, role in MOCKUP_ROLES.items()}


class StyleUser:
    """User setting with overlay style of the wizard (presets & other config read through)"""

    def __init__(self, user, style: dict):
        self._user = user
        self.config = {**user.config, "overlay_style": style}

    def __getattr__(self, name):
        return getattr(self._user, name)


class StyleSetting:
    """Setting proxy rendering overlays with wizard style, never saves"""

    def __init__(self, config, style: dict):
        self._cfg = config
        self.user = StyleUser(config.user, style)

    def __getattr__(self, name):
        return getattr(self._cfg, name)

    def save(self, *args, **kwargs):
        """Never save preview setting"""


def render_overlay(name: str, setting: dict, style: dict) -> QImage | None:
    """Overlay picture with widget setting & overlay style, None if it cannot be drawn"""
    from ...widget._painter import OverlayStyle
    from ..widget_preview import render_widget

    shared = OverlayStyle.corner_scale, OverlayStyle.depth_effects  # set by widget: running overlays keep theirs
    try:
        pixmap = render_widget(StyleSetting(cfg, style), name, dict(setting))  # type: ignore[arg-type]
    except Exception as error:  # never break the wizard
        logger.debug("SETUP: preview error: %s: %s", name, error, exc_info=True)
        return None
    finally:
        OverlayStyle.corner_scale, OverlayStyle.depth_effects = shared
    if pixmap.isNull():
        return None
    ratio = pixmap.devicePixelRatio() or 1
    limit = PREVIEW_MAX * ratio
    if pixmap.width() > limit.width() or pixmap.height() > limit.height():
        pixmap = pixmap.scaled(limit, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        pixmap.setDevicePixelRatio(ratio)
    return pixmap.toImage()


def read_preset(filename: str) -> dict:
    """Widget sections of preset file, empty if unreadable"""
    try:
        with open(f"{cfg.path.settings}{filename}", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError) as error:
        logger.info("SETUP: unable to read preset %s: %s", filename, error)
        return {}
    return data if isinstance(data, dict) else {}


class SetupTranslator(Translator):
    """UI texts of QML page in the language picked in the wizard"""

    def __init__(self, parent, language: str):
        super().__init__(parent)
        self.code = LANGUAGES.get(language, "en")
        self.table = load_translation(self.code)

    @Slot(str, result=str)
    def tr(self, text: str) -> str:  # type: ignore[override]  # replaces QObject.tr for QML
        return self.table.get(text, text)

    @Slot(str, result=str)
    def trm(self, text: str) -> str:
        return trm(text) if self.code == current_language() else text


class SetupBackend(QObject):
    """Setup wizard state: steps, choices, overlay tiles & previews"""

    stepChanged = Signal()
    navigationChanged = Signal()  # step or preset name changed: Next & Finish enabled or not
    languageChanged = Signal()
    choicesChanged = Signal()
    gamesChanged = Signal()
    presetChanged = Signal()
    tilesChanged = Signal()
    themeSamplesChanged = Signal()
    finished = Signal()
    skipped = Signal()
    skipRequested = Signal()  # Esc or window close: page asks before quitting
    gamesDetected = Signal(list)

    def __init__(self, parent=None, detect_games: bool = True):
        super().__init__(parent)
        self._step = STEP_WELCOME
        self._language = cfg.application["language"] if cfg.application["language"] in LANGUAGES else "English"
        self.translator = SetupTranslator(self, self._language)
        self._labels = option_labels(self.translator.code)
        theme = cfg.application["window_color_theme"]
        self._window_theme = theme if theme in rxp.THEME_NAMES else rxp.THEME_NAMES[0]
        style = cfg.user.config["overlay_style"]
        theme = style.get("overlay_theme")
        self._overlay_theme = theme if theme in rxp.THEME_NAMES else rxp.THEME_NAMES[0]
        self._colorblind = bool(style.get("enable_colorblind_colors", False))
        self._modern_font = bool(style.get("enable_modern_font", True))
        self._games = [api_class.NAME for api_class in api.available]
        self._game = cfg.api_name if cfg.api_name in self._games else (self._games[0] if self._games else "")
        self._game_picked = False  # user choice wins over detected game
        self._running: set[str] = set()
        self._units = unit_system(cfg.user.setting.get("units", {}))
        # Presets: loaded first, then by date
        loaded = cfg.filename.setting
        names = cfg.preset_files()
        self._presets = sorted(names, key=lambda name: f"{name}{FileExt.JSON}" != loaded)
        self._preset_index = 0
        self._new_preset = True
        self._name_edited = False
        self._new_name = self.default_name()
        self._preset_cache: dict[str, dict] = {}
        self._checked: dict[str, set[str]] = {}  # checked overlays per preset choice
        self._names = [name for name in STARTER_WIDGETS if name in wctrl.names]
        # Overlay previews
        self._previews: dict[tuple, Preview] = {}  # (style, preset, overlay) -> picture
        self._store_prefix = STORE.new_prefix("setup")  # pictures served to QML by preview_provider
        weakref.finalize(self, STORE.release, self._store_prefix)
        self._shown: dict[str, Preview] = {}  # tile picture shown until the one of new style is ready
        self._queue: deque[tuple] = deque()
        self._queued: set[tuple] = set()
        self._rendering = False
        self._timer = QTimer(self)  # deleted with backend: never renders for a deleted page
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._render_next)
        self.tiles = DictListModel(TILE_ROLES, self)
        self.tiles.reset(self._tile_rows())
        self.gamesDetected.connect(self._games_detected)
        if detect_games:
            threading.Thread(target=self._detect_games, name="SetupGameDetect", daemon=True).start()

    def tr(self, text: str) -> str:  # type: ignore[override]  # wizard language
        return self.translator.table.get(text, text)

    # Steps
    @Property(int, notify=stepChanged)
    def step(self) -> int:
        return self._step

    @Property(int, constant=True)
    def stepCount(self) -> int:
        return len(STEPS)

    @Property(list, notify=languageChanged)
    def steps(self) -> list[dict]:
        return [
            {"key": key, "label": self.tr(label), "title": self.tr(title), "subtitle": self.tr(subtitle), "glyph": glyph}
            for key, label, title, subtitle, glyph in STEPS
        ]

    @Slot(int)
    def goTo(self, step: int):
        step = max(0, min(step, len(STEPS) - 1))
        if step == self._step:
            return
        self._step = step
        if step >= STEP_LOOK:
            self.start_previews()
        self.stepChanged.emit()
        self.navigationChanged.emit()

    @Slot()
    def next(self):
        if self.canGoNext:
            self.goTo(self._step + 1)

    @Slot()
    def back(self):
        self.goTo(self._step - 1)

    @Property(bool, notify=navigationChanged)
    def canGoNext(self) -> bool:
        return self._step != STEP_OVERLAYS or self.nameError == ""

    @Property(bool, notify=navigationChanged)
    def canFinish(self) -> bool:
        return self.nameError == ""

    @Slot()
    def finish(self):
        """Choices applied by the wizard window"""
        if self.canFinish:
            self.stop_previews()
            self.finished.emit()

    @Slot()
    def skip(self):
        """Quit confirmed: choices dropped"""
        self.stop_previews()
        self.skipped.emit()

    # Language
    @Property(list, constant=True)
    def languages(self) -> list[dict]:
        """Languages with their own greeting"""
        rows = []
        for name, code in LANGUAGES.items():
            greeting = load_translation(code).get("Welcome", "Welcome")
            rows.append({"name": name, "code": code.upper(), "greeting": greeting})
        return rows

    @Property(str, notify=languageChanged)
    def language(self) -> str:
        return self._language

    @Slot(str)
    def setLanguage(self, name: str):
        if name == self._language or name not in LANGUAGES:
            return
        self._language = name
        self.translator = SetupTranslator(self, name)
        self._labels = option_labels(self.translator.code)
        if not self._name_edited:
            self._new_name = self.default_name()
        self.tiles.update_rows(lambda row: {
            "label": self.widget_label(row["key"]), "category": self.tr(widget_category(row["key"]))})
        self.languageChanged.emit()
        self.choicesChanged.emit()
        self.gamesChanged.emit()
        self.preset_changed()

    def widget_label(self, name: str) -> str:
        return self._labels.get(name) or format_module_name(name)

    # Themes
    @Property(list, notify=languageChanged)
    def windowThemes(self) -> list[dict]:
        return [
            {"name": name, "label": self.tr(name), "legacy": name.startswith("Legacy"), **theme_mockup(name)}
            for name in rxp.THEME_NAMES
        ]

    @Property(str, notify=choicesChanged)
    def windowTheme(self) -> str:
        return self._window_theme

    @Slot(str)
    def setWindowTheme(self, name: str):
        if name in rxp.THEME_NAMES and name != self._window_theme:
            self._window_theme = name
            self.choicesChanged.emit()

    @Property(list, notify=themeSamplesChanged)
    def overlayThemes(self) -> list[dict]:
        """Overlay themes with picture of sample overlay in each theme"""
        rows = []
        for name in rxp.THEME_NAMES:
            preview = self.preview(THEME_SAMPLE, self.style_key(name)) if THEME_SAMPLE in self._names else None
            if preview is None:
                state = PREVIEW_LOADING if THEME_SAMPLE in self._names else PREVIEW_UNAVAILABLE
            else:
                state = PREVIEW_READY if preview.url else PREVIEW_UNAVAILABLE
            rows.append({
                "name": name, "label": self.tr(name), "light": name.endswith("Light"),
                "preview": preview.url if preview else "", "previewWidth": preview.width if preview else 0,
                "previewHeight": preview.height if preview else 0, "previewState": state,
            })
        return rows

    @Property(str, notify=choicesChanged)
    def overlayTheme(self) -> str:
        return self._overlay_theme

    @Slot(str)
    def setOverlayTheme(self, name: str):
        if name in rxp.THEME_NAMES and name != self._overlay_theme:
            self._overlay_theme = name
            self.style_changed()

    @Property(bool, notify=choicesChanged)
    def colorblind(self) -> bool:
        return self._colorblind

    @Slot(bool)
    def setColorblind(self, enabled: bool):
        if enabled != self._colorblind:
            self._colorblind = enabled
            self.style_changed()

    @Property(bool, notify=choicesChanged)
    def modernFont(self) -> bool:
        return self._modern_font

    @Slot(bool)
    def setModernFont(self, enabled: bool):
        if enabled != self._modern_font:
            self._modern_font = enabled
            self.style_changed()

    def style_changed(self):
        self.choicesChanged.emit()
        self.refresh_tiles()
        self.themeSamplesChanged.emit()

    # Game
    @Property(list, notify=gamesChanged)
    def games(self) -> list[dict]:
        return [
            {"name": name, "detail": self.tr(GAME_INFO.get(name, ("",))[0]), "running": name in self._running}
            for name in self._games
        ]

    @Property(str, notify=gamesChanged)
    def game(self) -> str:
        return self._game

    @Slot(str)
    def setGame(self, name: str):
        if name in self._games:
            self._game_picked = True
            if name != self._game:
                self._game = name
                self.gamesChanged.emit()

    def _detect_games(self):
        """Running games (thread: process list read in background)"""
        try:
            running = running_games()
        except Exception as error:  # psutil access denied, platform without process list
            logger.debug("SETUP: game detection failed: %s", error)
            return
        with suppress(RuntimeError):  # wizard closed meanwhile
            self.gamesDetected.emit(sorted(running))

    @Slot(list)
    def _games_detected(self, running: list):
        self._running = set(running) & set(self._games)
        if not self._game_picked and self._running and self._game not in self._running:
            self._game = sorted(self._running, key=lambda name: name == API_LMULEGACY_NAME)[0]  # native API first
        self.gamesChanged.emit()

    # Units
    @Property(list, notify=languageChanged)
    def unitSystems(self) -> list[dict]:
        return self.unit_rows()

    def unit_rows(self) -> list[dict]:
        """Unit system cards: metric, imperial, mixed units of loaded preset (kept)"""
        rows = [
            {"key": name, "label": self.tr(name), "units": unit_samples(units)}
            for name, units in UNIT_SYSTEMS.items()
        ]
        current = cfg.user.setting.get("units", {})
        if unit_system(current) == UNITS_KEEP:
            rows.append({"key": UNITS_KEEP, "label": self.tr("Keep current units"), "units": unit_samples(current)})
        return rows

    @Property(str, notify=choicesChanged)
    def units(self) -> str:
        return self._units

    @Slot(str)
    def setUnits(self, name: str):
        if (name in UNIT_SYSTEMS or name == UNITS_KEEP) and name != self._units:
            self._units = name
            self.choicesChanged.emit()

    # Preset
    @Property(list, notify=presetChanged)
    def presets(self) -> list[str]:
        return list(self._presets)

    @Property(str, constant=True)
    def loadedPreset(self) -> str:
        return strip_filename_extension(cfg.filename.setting or "", FileExt.JSON)

    @Property(int, notify=presetChanged)
    def presetIndex(self) -> int:
        return self._preset_index

    @Slot(int)
    def setPresetIndex(self, index: int):
        if 0 <= index < len(self._presets) and index != self._preset_index:
            self._preset_index = index
            self.preset_changed()

    @Property(bool, notify=presetChanged)
    def newPreset(self) -> bool:
        return self._new_preset or not self._presets

    @Slot(bool)
    def setNewPreset(self, new: bool):
        if new != self._new_preset:
            self._new_preset = new
            self.preset_changed()

    @Property(str, notify=presetChanged)
    def newName(self) -> str:
        return self._new_name

    @Slot(str)
    def setNewName(self, name: str):
        self._name_edited = True
        if name != self._new_name:
            self._new_name = name
            self.presetChanged.emit()  # name checked while typing
            self.navigationChanged.emit()

    @Property(str, constant=True)
    def filenamePattern(self) -> str:
        """Characters accepted in preset names (QML text field validator)"""
        return '[^\\\\/:*?"<>|]*'

    @Property(str, notify=presetChanged)
    def nameError(self) -> str:
        if not self.newPreset:
            return ""
        name = self.new_preset_name()
        if not name:
            return self.tr("Enter a preset name")
        if not is_allowed_filename(name):
            return self.tr("This name is reserved, choose another one")
        if name.lower() in {preset.lower() for preset in cfg.preset_files()}:
            return self.tr("A preset with this name already exists")
        return ""

    def default_name(self) -> str:
        """Name proposed for new preset, in wizard language, not used by a preset yet"""
        name = self.tr("my overlay")
        existing = {preset.lower() for preset in cfg.preset_files()}
        number = 1
        proposed = name
        while proposed.lower() in existing:
            number += 1
            proposed = f"{name} {number}"
        return proposed

    def new_preset_name(self) -> str:
        return strip_filename_extension(self._new_name.strip(), FileExt.JSON)

    def preset_file(self) -> str:
        """Chosen existing preset file name, "" for a new preset"""
        if self.newPreset:
            return ""
        return f"{self._presets[self._preset_index]}{FileExt.JSON}"

    def preset_changed(self):
        self.presetChanged.emit()
        self.navigationChanged.emit()
        self.refresh_tiles()

    def preset_sections(self, filename: str) -> dict:
        """Widget sections of preset choice: loaded preset, file of other preset, template of new preset"""
        if not filename:
            return cfg.default.setting  # type: ignore[return-value]
        if cfg.is_loaded(filename):
            return cfg.user.setting  # type: ignore[return-value]
        if filename not in self._preset_cache:
            self._preset_cache[filename] = read_preset(filename)
        return self._preset_cache[filename]

    def widget_setting(self, name: str, filename: str) -> dict:
        default = cfg.default.setting[name]
        section = self.preset_sections(filename).get(name)
        return {**default, **section} if isinstance(section, dict) else dict(default)

    def checked(self) -> set[str]:
        """Checked overlays of preset choice: recommended ones for a new preset, else those already on"""
        filename = self.preset_file()
        if filename not in self._checked:
            if filename:
                self._checked[filename] = {
                    name for name in self._names if self.widget_setting(name, filename).get("enable", False)}
            else:
                self._checked[filename] = {name for name in DEFAULT_STARTER if name in self._names}
        return self._checked[filename]

    # Overlay tiles
    def _tile_rows(self) -> list[dict]:
        checked = self.checked()
        rows = []
        for name in self._names:
            category = widget_category(name)
            rows.append({
                "key": name, "label": self.widget_label(name), "category": self.tr(category),
                "tint": CATEGORY_COLORS.get(category, CATEGORY_COLORS["Other"]), "checked": name in checked,
                "sample": name in STYLE_SAMPLES, **self.tile_preview(name),
            })
        return rows

    def refresh_tiles(self):
        checked = self.checked()
        self.tiles.update_rows(lambda row: {"checked": row["key"] in checked, **self.tile_preview(row["key"])})
        self.tilesChanged.emit()

    @Property(QObject, constant=True)
    def tileModel(self) -> QObject:
        return self.tiles

    @Property(int, constant=True)
    def sampleCount(self) -> int:
        return sum(name in STYLE_SAMPLES for name in self._names)

    @Property(int, constant=True)
    def tileCount(self) -> int:
        return len(self._names)

    @Property(int, notify=tilesChanged)
    def checkedCount(self) -> int:
        return len(self.checked())

    @Property(bool, notify=presetChanged)
    def otherOverlaysKept(self) -> bool:
        """Overlays not listed keep their state (existing preset)"""
        return not self.newPreset

    @Slot(str)
    def toggleOverlay(self, name: str):
        checked = self.checked()
        if name not in self._names:
            return
        checked.symmetric_difference_update((name,))
        self.tiles.update_rows(lambda row: {"checked": row["key"] in checked})
        self.tilesChanged.emit()

    @Slot(str)
    def checkOverlays(self, which: str):
        """Check all, none or recommended overlays"""
        checked = self.checked()
        checked.clear()
        if which == "all":
            checked.update(self._names)
        elif which == "recommended":
            checked.update(name for name in DEFAULT_STARTER if name in self._names)
        self.tiles.update_rows(lambda row: {"checked": row["key"] in checked})
        self.tilesChanged.emit()

    # Overlay previews
    @staticmethod
    def style(style_key: tuple) -> dict:
        """Overlay style setting of style key (theme, colorblind, modern font)"""
        theme, colorblind, modern_font = style_key
        return {
            **cfg.user.config["overlay_style"],
            "overlay_theme": theme,
            "enable_colorblind_colors": colorblind,
            "enable_modern_font": modern_font,
        }

    def style_key(self, theme: str = "") -> tuple:
        return theme or self._overlay_theme, self._colorblind, self._modern_font

    def preview(self, name: str, style_key: tuple, filename: str | None = None) -> Preview | None:
        """Picture of overlay in style, render queued if missing"""
        key = (style_key, self.preset_file() if filename is None else filename, name)
        preview = self._previews.get(key)
        if preview is None:
            self.request(key)
        return preview

    def tile_preview(self, name: str) -> dict:
        preview = self.preview(name, self.style_key())
        if preview is not None:
            self._shown[name] = preview
        shown = self._shown.get(name)
        if shown is None:
            state = PREVIEW_LOADING
        else:
            state = PREVIEW_READY if shown.url else PREVIEW_UNAVAILABLE
        return {
            "preview": shown.url if shown else "", "previewWidth": shown.width if shown else 0,
            "previewHeight": shown.height if shown else 0, "previewState": state,
        }

    def request(self, key: tuple):
        if key not in self._queued:
            self._queued.add(key)
            if key[2] in STYLE_SAMPLES or key[2] == THEME_SAMPLE:
                self._queue.appendleft(key)  # Appearance step pictures first
            else:
                self._queue.append(key)
            self._wake()

    def start_previews(self):
        """Render pictures from now on (Appearance step reached)"""
        if not self._rendering:
            self._rendering = True
            self._wake()

    def stop_previews(self):
        self._rendering = False
        self._timer.stop()
        self._queue.clear()
        self._queued.clear()

    def pending(self) -> int:
        return len(self._queue)

    def _wake(self):
        if self._rendering and self._queue and not self._timer.isActive():
            self._timer.start()

    def _render_next(self):
        if not self._queue or not self._rendering:
            self._timer.stop()
            return
        key = self._queue.popleft()
        self._queued.discard(key)
        self.render_now(key)
        if not self._queue:
            self._timer.stop()

    def render_now(self, key: tuple):
        """Render overlay picture of (style, preset, overlay), pages told if it is shown"""
        style_key, filename, name = key
        if key in self._previews:
            return
        image = render_overlay(name, self.widget_setting(name, filename), self.style(style_key))
        if image is None:
            preview = Preview("", 0, 0)
        else:
            ratio = image.devicePixelRatio() or 1
            url = STORE.put(self._store_prefix + "/".join(map(str, key)), image)
            preview = Preview(url, round(image.width() / ratio), round(image.height() / ratio))
        self._previews[key] = preview
        if style_key == self.style_key() and filename == self.preset_file():
            self.tiles.update_rows(lambda row: self.tile_preview(name) if row["key"] == name else {})
        if name == THEME_SAMPLE and filename == self.preset_file():
            self.themeSamplesChanged.emit()

    # Summary
    @Property(list, notify=stepChanged)
    def summary(self) -> list[dict]:
        units = {row["key"]: row for row in self.unit_rows()}.get(self._units)
        units_text = f"{units['label']} ({', '.join(units['units'])})" if units else ""
        overlay = self.tr(self._overlay_theme)
        if self._colorblind:
            overlay = f"{overlay} · {self.tr('Colorblind safe colors')}"
        if self.newPreset:
            preset = f"{self.new_preset_name()} ({self.tr('new')})"
        else:
            preset = self._presets[self._preset_index]
        labels = sorted(self.widget_label(name) for name in self.checked())
        return [
            {"label": self.tr("Language"), "value": self._language, "step": STEP_WELCOME, "glyph": "\uE774"},
            {"label": self.tr("Game"), "value": self._game, "step": STEP_GAME, "glyph": "\uE804"},
            {"label": self.tr("Units"), "value": units_text, "step": STEP_UNITS, "glyph": "\uEC48"},
            {"label": self.tr("Window theme"), "value": self.tr(self._window_theme), "step": STEP_LOOK,
             "glyph": "\uE7F4"},
            {"label": self.tr("Overlay theme"), "value": overlay, "step": STEP_LOOK, "glyph": "\uE7F4"},
            {"label": self.tr("Preset to use"), "value": preset, "step": STEP_OVERLAYS, "glyph": "\uE838"},
            {"label": self.tr("Overlays"), "value": ", ".join(labels) or self.tr("None"), "step": STEP_OVERLAYS,
             "glyph": "\uE81E"},
        ]

    @Property(str, constant=True)
    def appIcon(self) -> str:
        """App icon file URL (white & gold on dark theme)"""
        from PySide6.QtCore import QUrl

        from .. import resolve_color_theme

        dark = resolve_color_theme(cfg.application["window_color_theme"]) == "Dark"
        filename = ImageFile.APP_ICON_DARK if dark else ImageFile.APP_ICON
        return QUrl.fromLocalFile(os.path.abspath(filename)).toString()

    def choices(self) -> SetupChoices:
        """Wizard result"""
        checked = self.checked()
        filename = self.preset_file()
        return SetupChoices(
            language=self._language,
            api_name=self._game,
            window_theme=self._window_theme,
            overlay_theme=self._overlay_theme,
            modern_font=self._modern_font,
            preset=filename,
            new_preset=self.new_preset_name() if self.newPreset else "",
            widgets=tuple(name for name in self._names if name in checked),
            colorblind=self._colorblind,
            units=self._units,
            disabled=tuple(name for name in self._names if name not in checked),
        )
