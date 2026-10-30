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
First launch setup wizard: language, game, units, themes, starting preset & overlays, streaming (optional)

Qt Quick page (qml/SetupWizard.qml) in its own window, state in quick/setup_backend.py.
Choices are applied only when finished (run_setup), never while browsing steps. Once finished, the Overlays page
can open in Screen view (where overlays are placed) and overlays on screen can show a simulated race.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
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
        "wind_speed_unit": "m/s",
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
        "wind_speed_unit": "MPH",
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
    stream: bool = False  # stream overlay server on (overlays as browser sources in streaming software)
    open_screen_view: bool = False  # Overlays page shown in Screen view once finished
    test_on_screen: bool = False  # overlays on screen show a simulated race once finished


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
    if choices.stream:  # server started by the reload
        cfg.user.config["stream_overlay"]["enable_stream_overlay"] = True
    if choices.open_screen_view:
        application["show_overlay_screen_view"] = True
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


def run_setup(choices: SetupChoices, done: Callable[[], object] | None = None):
    """Apply all choices and reload, done called once overlays are running with them"""
    preset = apply_global_choices(choices)
    # Overlays created below with labels of chosen language (window rebuilt after, see retranslate)
    set_language(choices.language)
    if preset:
        cfg.set_next_to_load(preset)
        loader.reload(reload_preset=True)
    loader.after_reload(lambda: finish_setup(choices, done))  # choices applied to new preset once loaded


def finish_setup(choices: SetupChoices, done: Callable[[], object] | None = None):
    """Apply preset choices to loaded preset and reload"""
    enabled = apply_preset_choices(choices)
    loader.reload(reload_preset=False)  # restart API with selected game, start widgets
    logger.info("SETUP: completed, enabled widgets: %s", ", ".join(enabled) or "none")

    def reloaded():
        app_signal.refresh.emit(True)
        if done is not None:
            done()

    loader.after_reload(reloaded)


def show_overlays_page(window, screen_view: bool):
    """Overlays page of main window shown (in Screen view: where each overlay is placed)"""
    from .nav_rail import PAGE_INDEX

    view = window.centralWidget() if hasattr(window, "centralWidget") else None
    select_page = getattr(view, "select_page", None)
    if not callable(select_page):
        return
    select_page(PAGE_INDEX["widget"])
    if screen_view:
        from .overlay_view import OverlayView
        from .quick.overlay_backend import VIEW_SCREEN

        page = window.findChild(OverlayView)
        if page is not None:  # page built before: view of its own (setting read when built)
            page.backend.setViewMode(VIEW_SCREEN)


def test_overlays_on_screen(parent):
    """Overlays on screen show a simulated race for a few seconds, how many told (none: why)"""
    import shiboken6

    from ..i18n import trm
    from .overlay_test import TEST_SECONDS, overlay_test
    from .toast import show_toast

    shown = overlay_test().start()
    if parent is None or not shiboken6.isValid(parent):
        return
    if shown:
        show_toast(parent, trm(f"{shown} overlay(s) on screen show this situation for {TEST_SECONDS} s "
                               "(saved values)"))
    else:
        show_toast(parent, tr("No overlay on screen now: enable overlays, unlock them or start the game"))


class SetupWizard(QDialog):
    """First launch setup wizard window"""

    def __init__(self, parent, detect_games: bool = True):
        from .quick import create_quick_view
        from .quick.preview_provider import install_provider as install_preview_provider
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
        install_preview_provider(self.view.engine())  # overlay pictures (image://overlaypreview)
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
        """Apply choices, then the Overlays page shown & overlays tested on screen if chosen"""
        choices = self.choices()
        parent = self.parentWidget()
        super().accept()
        done = (lambda: test_overlays_on_screen(parent)) if choices.test_on_screen else None
        run_setup(choices, done)
        if parent is not None:
            from .toast import show_toast

            if choices.open_screen_view:
                show_overlays_page(parent, True)
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
