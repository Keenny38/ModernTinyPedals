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
First launch setup wizard: language, game, units, themes, starting preset & overlays

Qt Quick page (qml/SetupWizard.qml) in its own window, state in quick/setup_backend.py.
Choices are applied only when finished (run_setup), never while browsing steps.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import NamedTuple

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout

from .. import app_signal, loader
from .. import regex_pattern as rxp
from ..const_file import ConfigType, FileExt
from ..i18n import set_language, tr
from ..setting import cfg
from ._common import UIScaler

logger = logging.getLogger(__name__)

# Starter pack: overlays useful for most drivers (also every overlay on in a new preset), recommended ones on
STARTER_WIDGETS = (
    "relative", "standings", "deltabest", "fuel", "virtual_energy", "pedal", "gear", "steering_wheel",
    "tyre_temperature", "brake_temperature", "flag", "session", "weather", "radar", "track_map", "trailing",
)
DEFAULT_STARTER = ("relative", "deltabest", "fuel", "pedal", "gear", "flag")
WINDOW_THEMES = rxp.THEME_NAMES
# Unit systems: every unit of preset "units" section
UNIT_SYSTEMS = {
    "Metric": {
        "distance_unit": "Meter",
        "fuel_unit": "Liter",
        "odometer_unit": "Kilometer",
        "power_unit": "Kilowatt",
        "speed_unit": "KPH",
        "temperature_unit": "Celsius",
        "turbo_pressure_unit": "bar",
        "tyre_pressure_unit": "kPa",
        "weight_unit": "Kilogram",
    },
    "Imperial": {
        "distance_unit": "Feet",
        "fuel_unit": "Gallon",
        "odometer_unit": "Mile",
        "power_unit": "Horsepower",
        "speed_unit": "MPH",
        "temperature_unit": "Fahrenheit",
        "turbo_pressure_unit": "psi",
        "tyre_pressure_unit": "psi",
        "weight_unit": "Pound",
    },
}
UNITS_KEEP = ""  # units of the preset kept


class SetupChoices(NamedTuple):
    """Wizard result"""

    language: str
    api_name: str
    window_theme: str
    overlay_theme: str
    modern_font: bool
    preset: str  # existing preset file name, "" to keep loaded preset
    new_preset: str  # new preset name (without extension), "" to not create
    widgets: tuple[str, ...]  # widgets to enable
    colorblind: bool = False  # colorblind safe overlay colors
    units: str = UNITS_KEEP  # unit system (UNIT_SYSTEMS), "" to keep preset units
    disabled: tuple[str, ...] = ()  # widgets to disable (starter widgets left unchecked)


def apply_global_choices(choices: SetupChoices) -> str:
    """Apply global (config.json) choices, returns preset file name to load, or "" """
    application = cfg.application
    application["language"] = choices.language
    application["window_color_theme"] = choices.window_theme
    application["show_setup_wizard_at_startup"] = False
    style = cfg.user.config["overlay_style"]
    style["overlay_theme"] = choices.overlay_theme
    style["enable_modern_font"] = choices.modern_font
    style["enable_colorblind_colors"] = choices.colorblind
    cfg.save(0, config_type=ConfigType.CONFIG)
    if choices.new_preset:
        filename = f"{choices.new_preset}{FileExt.JSON}"
        cfg.create(filename)
        return filename
    if choices.preset and not cfg.is_loaded(choices.preset):
        return choices.preset
    return ""


def apply_preset_choices(choices: SetupChoices) -> list[str]:
    """Apply preset choices (API, units, widgets) to loaded preset, returns newly enabled widgets"""
    if choices.api_name:
        cfg.api_name = choices.api_name
    units = cfg.user.setting.get("units")
    if choices.units in UNIT_SYSTEMS and isinstance(units, dict):
        units.update(UNIT_SYSTEMS[choices.units])
    enabled = []
    for name in choices.widgets:
        setting = cfg.user.setting.get(name)
        if isinstance(setting, dict) and not setting.get("enable", True):
            setting["enable"] = True
            enabled.append(name)
    for name in choices.disabled:
        setting = cfg.user.setting.get(name)
        if isinstance(setting, dict) and name not in choices.widgets:
            setting["enable"] = False
    cfg.save()
    return enabled


def run_setup(choices: SetupChoices):
    """Apply all choices and reload"""
    preset = apply_global_choices(choices)
    # Overlays created below with labels of chosen language (window rebuilt after, see retranslate)
    set_language(choices.language)
    if preset:
        cfg.set_next_to_load(preset)
        loader.reload(reload_preset=True)
    enabled = apply_preset_choices(choices)
    loader.reload(reload_preset=False)  # restart API with selected game, start widgets
    logger.info("SETUP: completed, enabled widgets: %s", ", ".join(enabled) or "none")
    app_signal.refresh.emit(True)


class SetupWizard(QDialog):
    """First launch setup wizard window"""

    def __init__(self, parent, detect_games: bool = True):
        from .quick import create_quick_view
        from .quick.setup_backend import SetupBackend

        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)  # not kept once finished
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumSize(UIScaler.size(40), UIScaler.size(30))
        self.resize(UIScaler.size(60), UIScaler.size(40))
        self.backend = SetupBackend(self, detect_games=detect_games)
        # Queued: closing deletes the QML page, never inside the click handler of its button (crash)
        self.backend.finished.connect(self.accept, Qt.ConnectionType.QueuedConnection)
        self.backend.skipped.connect(self.skip_now, Qt.ConnectionType.QueuedConnection)
        self.backend.languageChanged.connect(self.retranslate)
        self.view = create_quick_view(
            self, "SetupWizard.qml", {"backend": self.backend, "i18n": self.backend.translator}, samples=0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.setFocusProxy(self.view)
        self.retranslate()
        app = QApplication.instance()
        if app is not None:  # app quit while open: QML gone before the backend it binds to
            app.aboutToQuit.connect(self.release_page)

    def retranslate(self):
        """Window & QML texts in language picked in the wizard (app language changed once finished)"""
        self.setWindowTitle(self.backend.tr("Setup Wizard"))
        self.view.rootContext().setContextProperty("i18n", self.backend.translator)  # bindings read texts again

    def choices(self) -> SetupChoices:
        """Collect choices from pages"""
        return self.backend.choices()

    def accept(self):
        """Apply choices"""
        choices = self.choices()
        parent = self.parentWidget()
        super().accept()
        run_setup(choices)
        if parent is not None:
            from .toast import show_toast

            show_toast(parent, tr("Setup complete. Overlays show once you are driving."))

    def reject(self):
        """Esc or window close: quit confirmed in the page first (closed at once if the page failed to load)"""
        if self.view.rootObject() is None:
            self.skip_now()
        else:
            self.backend.skipRequested.emit()

    def skip_now(self):
        """Quit confirmed: choices dropped"""
        self.skip()
        super().reject()

    def skip(self):
        """Do not show again after skipped"""
        if cfg.application.get("show_setup_wizard_at_startup", False):
            cfg.application["show_setup_wizard_at_startup"] = False
            cfg.save(0, config_type=ConfigType.CONFIG)

    def release_page(self):
        """Rendering stopped, QML gone before the backend it binds to"""
        self.backend.stop_previews()
        with suppress(RuntimeError):
            self.view.setSource(QUrl())

    def done(self, result: int):
        """Closed"""
        self.release_page()
        super().done(result)
