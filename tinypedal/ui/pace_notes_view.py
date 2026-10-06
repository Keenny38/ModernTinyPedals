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
Pace notes view & playback
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .. import app_signal
from ..const_file import FileFilter
from ..i18n import tr, trm
from ..module_control import mctrl
from ..setting import cfg
from ..userfile import set_relative_path
from ._common import CompactButton, UIScaler, translate_filter

if TYPE_CHECKING:
    from .pace_notes_player import PaceNotesPlayer

logger = logging.getLogger(__name__)


class PaceNotesPlayback(QObject):
    """Pace notes audio playback, kept by main view while pace notes page may not be built

    Player only exists while playback is enabled: Qt Multimedia (and its media backend) is
    not loaded otherwise. Call refresh after setting changed (app refresh signal).
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.player: PaceNotesPlayer | None = None
        self.refresh()

    @Slot(bool)  # type: ignore[operator]
    def refresh(self, *_):
        """Create or release player to match playback setting (preset may have changed)"""
        mcfg = cfg.user.setting["pace_notes_playback"]
        if mcfg["enable"]:
            if self.player is None:
                from .pace_notes_player import PaceNotesPlayer

                self.player = PaceNotesPlayer(self, mcfg)
            self.player.mcfg = mcfg
        elif self.player is not None:
            self.player.stop()
            self.player.deleteLater()
            self.player = None

    def reset_playback(self):
        if self.player is not None:
            self.player.reset_playback()

    def set_volume(self, volume: int):
        if self.player is not None:
            self.player.set_volume(volume)


class PaceNotesControl(QWidget):
    """Pace notes control

    Args:
        playback: audio playback of main view, own one if not given.
    """

    def __init__(self, parent, playback: PaceNotesPlayback | None = None):
        super().__init__(parent)
        self.last_enabled = None

        self.mcfg = cfg.user.setting["pace_notes_playback"]
        if playback is None:
            playback = PaceNotesPlayback(self)
            app_signal.refresh.connect(playback.refresh)
        self.playback = playback

        # Pace notes file selector
        self.checkbox_file = QCheckBox(tr("Manually Select Pace Notes File"))
        self.checkbox_file.toggled.connect(self.toggle_selector_state)

        self.file_selector = QLineEdit()
        self.file_selector.setReadOnly(True)
        self.button_openfile = CompactButton(tr("Open"))
        self.button_openfile.clicked.connect(self.set_notes_path)

        # Sound path selector
        label_path = QLabel(tr("Sound File Path:"))
        self.path_selector = QLineEdit()
        self.path_selector.setReadOnly(True)
        button_openpath = CompactButton(tr("Open"))
        button_openpath.clicked.connect(self.set_sound_path)

        # Sound file format
        label_format = QLabel(tr("Sound Format:"))
        self.combobox_format = QComboBox()
        self.combobox_format.setEditable(True)
        self.combobox_format.addItems(("wav", "mp3", "aac"))

        # Global Offset
        label_offset = QLabel(tr("Global Offset:"))
        self.spinbox_offset = QDoubleSpinBox()
        self.spinbox_offset.setRange(-9999, 9999)
        self.spinbox_offset.setSingleStep(1)
        self.spinbox_offset.setDecimals(2)
        self.spinbox_offset.setSuffix("m")

        # Max playback duration per sound
        label_max_duration = QLabel(tr("Maximum Duration:"))
        self.spinbox_max_duration = QDoubleSpinBox()
        self.spinbox_max_duration.setRange(0.2, 60)
        self.spinbox_max_duration.setSingleStep(1)
        self.spinbox_max_duration.setDecimals(3)
        self.spinbox_max_duration.setSuffix("s")

        # Max playback queue
        label_max_queue = QLabel(tr("Maximum Queue:"))
        self.spinbox_max_queue = QDoubleSpinBox()
        self.spinbox_max_queue.setRange(1, 50)
        self.spinbox_max_queue.setSingleStep(1)
        self.spinbox_max_queue.setDecimals(0)

        # Sound volumn slider
        self.label_volume = QLabel(tr("Playback Volume: 0%"))
        self.slider_volume = QSlider(Qt.Orientation.Horizontal)
        self.slider_volume.setRange(0, 100)
        self.slider_volume.valueChanged.connect(self.set_sound_volume)

        # Playback option
        self.checkbox_playinpit = QCheckBox(tr("Enable Playback While in Pit Lane"))
        self.checkbox_playinpit.toggled.connect(self.toggle_playinpit_state)

        # Frame layout
        layout_file = QGridLayout()
        layout_file.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout_file.addWidget(self.checkbox_file, 0, 0, 1, 2)
        layout_file.addWidget(self.file_selector, 1, 0)
        layout_file.addWidget(self.button_openfile, 1, 1)

        layout_file.addWidget(label_path, 2, 0, 1, 2)
        layout_file.addWidget(self.path_selector, 3, 0)
        layout_file.addWidget(button_openpath, 3, 1)

        layout_inner = QGridLayout()
        layout_inner.addWidget(label_format, 0, 0)
        layout_inner.addWidget(self.combobox_format, 1, 0)

        layout_inner.addWidget(label_offset, 0, 1)
        layout_inner.addWidget(self.spinbox_offset, 1, 1)

        layout_inner.addWidget(label_max_duration, 2, 0)
        layout_inner.addWidget(self.spinbox_max_duration, 3, 0)

        layout_inner.addWidget(label_max_queue, 2, 1)
        layout_inner.addWidget(self.spinbox_max_queue, 3, 1)

        layout_setting = QVBoxLayout()
        margin = UIScaler.pixel(5)
        layout_setting.setContentsMargins(margin, margin, margin, margin)
        layout_setting.addLayout(layout_file)
        layout_setting.addLayout(layout_inner)
        layout_setting.addStretch(1)
        layout_setting.addWidget(self.label_volume)
        layout_setting.addWidget(self.slider_volume)
        layout_setting.addWidget(self.checkbox_playinpit)

        self.frame_control = QFrame(self)
        self.frame_control.setFrameShape(QFrame.Shape.StyledPanel)
        self.frame_control.setLayout(layout_setting)

        # Button
        self.button_apply = QPushButton(tr("Apply"))
        self.button_apply.clicked.connect(self.set_playback_setting)

        self.button_toggle = QPushButton("")
        self.button_toggle.setCheckable(True)
        self.button_toggle.clicked.connect(self.toggle_button_state)

        layout_button = QHBoxLayout()
        layout_button.addWidget(self.button_apply)
        layout_button.addStretch(1)
        layout_button.addWidget(self.button_toggle)

        # Layout
        layout_main = QVBoxLayout()
        layout_main.addWidget(self.frame_control, stretch=1)
        layout_main.addLayout(layout_button)
        margin = UIScaler.pixel(6)
        layout_main.setContentsMargins(margin, margin, margin, margin)
        self.setLayout(layout_main)

    @Slot(bool)  # type: ignore[operator]
    def refresh(self):
        """Refresh state"""
        self.mcfg = cfg.user.setting["pace_notes_playback"]
        enabled = self.mcfg["enable"]

        self.toggle_playinpit_state(self.mcfg["enable_playback_while_in_pit"])
        self.toggle_selector_state(self.mcfg["enable_manual_file_selector"])
        self.file_selector.setText(self.mcfg["pace_notes_file_name"])
        self.path_selector.setText(self.mcfg["pace_notes_sound_path"])
        self.combobox_format.setEditText(self.mcfg["pace_notes_sound_format"])
        self.spinbox_offset.setValue(self.mcfg["pace_notes_global_offset"])
        self.spinbox_max_duration.setValue(self.mcfg["pace_notes_sound_maximum_duration"])
        self.spinbox_max_queue.setValue(self.mcfg["pace_notes_sound_maximum_queue"])
        self.slider_volume.setValue(self.mcfg["pace_notes_sound_volume"])

        # Update button state only if changed
        if self.last_enabled != enabled:
            self.last_enabled = enabled
            self.set_enable_state(enabled)

    def set_enable_state(self, enabled: bool):
        """Set enabled state"""
        if enabled:
            self.button_toggle.setText(tr("  Playback Enabled  "))
            logger.info("ENABLED: pace notes sounds playback")
        else:
            self.button_toggle.setText(tr("  Playback Disabled  "))
            logger.info("DISABLED: pace notes sounds playback")
        self.button_toggle.setChecked(enabled)
        self.button_apply.setDisabled(not enabled)
        self.frame_control.setDisabled(not enabled)
        self.playback.reset_playback()

    def set_notes_path(self):
        """Set pace notes file path"""
        filepath = self.mcfg["pace_notes_file_name"]
        filename_full = QFileDialog.getOpenFileName(self, dir=filepath, filter=translate_filter(FileFilter.TPPN))[0]
        if not filename_full:
            return
        self.file_selector.setText(filename_full)
        self.playback.reset_playback()
        if self.update_config("pace_notes_file_name", filename_full):
            mctrl.reload("module_notes")  # reload path in module notes

    def set_sound_path(self):
        """Set sounds folder path"""
        filepath = self.mcfg["pace_notes_sound_path"]
        filename_full = QFileDialog.getExistingDirectory(self, dir=filepath)
        if not filename_full:
            return
        filename_full = set_relative_path(filename_full)
        self.path_selector.setText(filename_full)
        self.update_config("pace_notes_sound_path", filename_full)

    def set_playback_setting(self):
        """Set sound playback setting"""
        sound_format = self.combobox_format.currentText()
        self.update_config("pace_notes_sound_format", sound_format)

        global_offset = self.spinbox_offset.value()
        self.update_config("pace_notes_global_offset", global_offset)

        max_duration = self.spinbox_max_duration.value()
        self.update_config("pace_notes_sound_maximum_duration", max_duration)

        max_queue = int(self.spinbox_max_queue.value())
        self.update_config("pace_notes_sound_maximum_queue", max_queue)

    def set_sound_volume(self, volume: int):
        """Set sound volume"""
        self.label_volume.setText(trm(f"Playback Volume: {volume}%"))
        if self.update_config("pace_notes_sound_volume", volume):
            self.playback.set_volume(volume)

    def toggle_selector_state(self, checked: bool):
        """Toggle file selector state"""
        self.checkbox_file.setChecked(checked)
        self.file_selector.setText(self.mcfg["pace_notes_file_name"])
        self.file_selector.setDisabled(not checked)
        self.button_openfile.setDisabled(not checked)

        if self.update_config("enable_manual_file_selector", checked):
            mctrl.reload("module_notes")  # reload file in module notes

    def toggle_playinpit_state(self, checked: bool):
        """Toggle playback in pit state"""
        self.checkbox_playinpit.setChecked(checked)
        self.update_config("enable_playback_while_in_pit", checked)

    def toggle_button_state(self, checked: bool):
        """Toggle button state"""
        self.update_config("enable", checked)
        app_signal.refresh.emit(True)

    def update_config(self, key: str, value: float | str) -> bool:
        """Update pace note playback setting, save if changed"""
        if self.mcfg[key] == value:
            return False
        self.mcfg[key] = value
        cfg.save()
        return True
