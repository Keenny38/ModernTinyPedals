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
First launch setup wizard: language, game, themes, starting preset & widgets
"""

from __future__ import annotations

import logging
from typing import NamedTuple

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from .. import app_signal, loader
from ..api_control import api
from ..const_file import ConfigType, FileExt
from ..formatter import strip_filename_extension
from ..i18n import LANGUAGES, tr
from ..i18n.options import module_label
from ..module_control import wctrl
from ..setting import cfg
from ..validator import is_allowed_filename
from ..widget._style import overlay_theme_names
from ._common import QVAL_FILENAME, UIScaler

logger = logging.getLogger(__name__)

# Starter pack: widgets useful for most drivers
STARTER_WIDGETS = (
    "relative", "standings", "deltabest", "fuel", "pedal", "gear",
    "tyre_temperature", "brake_temperature", "flag", "session", "weather", "radar",
)
DEFAULT_STARTER = ("relative", "deltabest", "fuel", "pedal", "gear", "flag")


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


def apply_global_choices(choices: SetupChoices) -> str:
    """Apply global (config.json) choices, returns preset file name to load, or "" """
    application = cfg.application
    application["language"] = choices.language
    application["window_color_theme"] = choices.window_theme
    application["show_setup_wizard_at_startup"] = False
    style = cfg.user.config["overlay_style"]
    style["overlay_theme"] = choices.overlay_theme
    style["enable_modern_font"] = choices.modern_font
    cfg.save(0, config_type=ConfigType.CONFIG)
    if choices.new_preset:
        filename = f"{choices.new_preset}{FileExt.JSON}"
        cfg.create(filename)
        return filename
    if choices.preset and not cfg.is_loaded(choices.preset):
        return choices.preset
    return ""


def apply_preset_choices(choices: SetupChoices) -> list[str]:
    """Apply preset choices (API, widgets) to loaded preset, returns newly enabled widgets"""
    if choices.api_name:
        cfg.api_name = choices.api_name
    enabled = []
    for name in choices.widgets:
        setting = cfg.user.setting.get(name)
        if isinstance(setting, dict) and not setting.get("enable", True):
            setting["enable"] = True
            enabled.append(name)
    cfg.save()
    return enabled


def run_setup(choices: SetupChoices):
    """Apply all choices and reload"""
    preset = apply_global_choices(choices)
    if preset:
        cfg.set_next_to_load(preset)
        loader.reload(reload_preset=True)
    enabled = apply_preset_choices(choices)
    loader.reload(reload_preset=False)  # restart API with selected game, start widgets
    logger.info("SETUP: completed, enabled widgets: %s", ", ".join(enabled) or "none")
    app_signal.refresh.emit(True)


class LanguagePage(QWizardPage):
    """Language & window theme"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle(tr("Welcome to TinyPedal"))
        self.setSubTitle(tr("A few questions to get you started. Every choice can be changed later."))
        self.language = QComboBox(self)
        self.language.addItems(tuple(LANGUAGES))
        self.language.setCurrentText(cfg.application["language"])
        self.window_theme = QComboBox(self)
        self.window_theme.addItems(("Dark", "Light"))
        self.window_theme.setCurrentText(cfg.application["window_color_theme"])
        layout = QGridLayout()
        layout.addWidget(QLabel(tr("Language")), 0, 0)
        layout.addWidget(self.language, 0, 1)
        layout.addWidget(QLabel(tr("Window theme")), 1, 0)
        layout.addWidget(self.window_theme, 1, 1)
        layout.setColumnStretch(1, 1)
        self.setLayout(layout)


class GamePage(QWizardPage):
    """Game (API) selection"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle(tr("Which game do you play?"))
        self.setSubTitle(tr("TinyPedal reads telemetry from the selected game."))
        self.group = QButtonGroup(self)
        layout = QVBoxLayout()
        for api_class in api.available:
            button = QRadioButton(api_class.NAME, self)
            button.setChecked(cfg.api_name == api_class.NAME)
            self.group.addButton(button)
            layout.addWidget(button)
        layout.addStretch(1)
        self.setLayout(layout)

    def api_name(self) -> str:
        button = self.group.checkedButton()
        return button.text() if button else ""


class StylePage(QWizardPage):
    """Overlay style"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle(tr("Overlay style"))
        self.setSubTitle(tr("Colors of the in-game widgets."))
        style = cfg.user.config["overlay_style"]
        self.overlay_theme = QComboBox(self)
        self.overlay_theme.addItems(overlay_theme_names())
        self.overlay_theme.setCurrentText(style["overlay_theme"])
        self.modern_font = QCheckBox(tr("Modern font (JetBrains Mono)"), self)
        self.modern_font.setChecked(style["enable_modern_font"])
        layout = QGridLayout()
        layout.addWidget(QLabel(tr("Overlay theme")), 0, 0)
        layout.addWidget(self.overlay_theme, 0, 1)
        layout.addWidget(self.modern_font, 1, 0, 1, 2)
        layout.setColumnStretch(1, 1)
        layout.setRowStretch(2, 1)
        self.setLayout(layout)


class PresetPage(QWizardPage):
    """Starting preset & widgets"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle(tr("Preset and widgets"))
        self.setSubTitle(tr("A preset stores the layout and options of all widgets."))
        self.preset = QComboBox(self)
        self.preset.addItem(tr("Create a new preset"), "")
        for name in cfg.preset_files():
            self.preset.addItem(name, f"{name}{FileExt.JSON}")
        loaded = cfg.filename.setting
        index = self.preset.findData(loaded)
        self.preset.setCurrentIndex(max(index, 0))
        self.new_name = QLineEdit(self)
        self.new_name.setPlaceholderText(tr("Enter a new preset name"))
        self.new_name.setValidator(QVAL_FILENAME)
        self.new_name.setText("my overlay")
        self.preset.currentIndexChanged.connect(self.update_name_state)

        layout = QGridLayout()
        layout.addWidget(QLabel(tr("Preset")), 0, 0)
        layout.addWidget(self.preset, 0, 1)
        layout.addWidget(self.new_name, 1, 1)
        layout.addWidget(QLabel(tr("Enable widgets:")), 2, 0, 1, 2)
        self.widgets: dict[str, QCheckBox] = {}
        for index, name in enumerate(name for name in STARTER_WIDGETS if name in wctrl.names):
            checkbox = QCheckBox(module_label(name), self)
            checkbox.setChecked(name in DEFAULT_STARTER)
            self.widgets[name] = checkbox
            layout.addWidget(checkbox, 3 + index // 2, index % 2)
        layout.setColumnStretch(1, 1)
        self.setLayout(layout)
        self.update_name_state()

    def update_name_state(self):
        self.new_name.setEnabled(self.preset.currentData() == "")
        self.completeChanged.emit()

    def new_preset_name(self) -> str:
        if self.preset.currentData() != "":
            return ""
        return strip_filename_extension(self.new_name.text().strip(), FileExt.JSON)

    def isComplete(self) -> bool:
        if self.preset.currentData() != "":
            return True
        name = self.new_preset_name()
        existing = {preset.lower() for preset in cfg.preset_files()}
        return is_allowed_filename(name) and name.lower() not in existing


class SetupWizard(QWizard):
    """First launch setup wizard"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("Setup Wizard"))
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setMinimumSize(UIScaler.size(34), UIScaler.size(26))
        self.page_language = LanguagePage(self)
        self.page_game = GamePage(self)
        self.page_style = StylePage(self)
        self.page_preset = PresetPage(self)
        for page in (self.page_language, self.page_game, self.page_style, self.page_preset):
            self.addPage(page)
        self.rejected.connect(self.skip)

    def choices(self) -> SetupChoices:
        """Collect choices from pages"""
        return SetupChoices(
            language=self.page_language.language.currentText(),
            api_name=self.page_game.api_name(),
            window_theme=self.page_language.window_theme.currentText(),
            overlay_theme=self.page_style.overlay_theme.currentText(),
            modern_font=self.page_style.modern_font.isChecked(),
            preset=self.page_preset.preset.currentData() or "",
            new_preset=self.page_preset.new_preset_name(),
            widgets=tuple(name for name, box in self.page_preset.widgets.items() if box.isChecked()),
        )

    def accept(self):
        """Apply choices"""
        choices = self.choices()
        super().accept()
        run_setup(choices)

    def skip(self):
        """Do not show again after skipped"""
        if cfg.application.get("show_setup_wizard_at_startup", False):
            cfg.application["show_setup_wizard_at_startup"] = False
            cfg.save(0, config_type=ConfigType.CONFIG)
