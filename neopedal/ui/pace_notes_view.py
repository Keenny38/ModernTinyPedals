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
Pace notes playback & page

Settings of pace notes playback are a category of the Settings page (qml/Settings.qml, see
quick/settings_backend.py): the Pace Notes page shows that category alone, with its on / off switch
and a test sound. Audio playback is kept by the main view while the page may not be built.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QUrl, Slot
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..i18n import tr, trm
from ..setting import cfg
from .settings_host import SettingsHostMixin

if TYPE_CHECKING:
    from PySide6.QtQuickWidgets import QQuickWidget

    from .pace_notes_player import PaceNotesPlayer
    from .quick.settings_backend import SettingsBackend

logger = logging.getLogger(__name__)
CATEGORY = "pace_notes_playback"


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
                logger.info("ENABLED: pace notes sounds playback")
            self.player.mcfg = mcfg
        elif self.player is not None:
            self.player.stop()
            self.player.deleteLater()
            self.player = None
            logger.info("DISABLED: pace notes sounds playback")

    def reset_playback(self):
        if self.player is not None:
            self.player.reset_playback()

    def set_volume(self, volume: int):
        if self.player is not None:
            self.player.set_volume(volume)


def test_sound_file(sound_path: str, sound_format: str) -> str:
    """First sound file (name order) of the pace notes sound folder in the sound format, "" if none

    Same checks as a pace note played while driving (see track_notes.pace_note_sound_file): only a file of
    the sound folder, never a network path.
    """
    from ..userfile.track_notes import pace_note_sound_file
    from ..validator import is_network_path

    if not isinstance(sound_path, str) or not isinstance(sound_format, str):
        return ""
    extension = f".{sound_format.strip().strip('.')}".lower()
    folder = os.path.dirname(os.path.abspath(f"{sound_path}_"))
    if is_network_path(sound_path) or is_network_path(folder):
        return ""  # never listed: a network host would be contacted (sign-in hash sent) before the refusal below
    try:
        names = sorted(name for name in os.listdir(folder) if name.lower().endswith(extension))
    except OSError:
        return ""
    for name in names:
        sound_file = pace_note_sound_file(sound_path, name[:-len(extension)], sound_format)
        if sound_file and os.path.isfile(sound_file):
            return sound_file
    return ""


def play_test_sound(owner: QObject, values: dict) -> str:
    """Play a sound of the sound folder with the volume of values (pace notes settings shown, not saved
    yet), "" if played, else why not (translated). One test player per owner page, kept while it lives."""
    sound_format = str(values.get("pace_notes_sound_format", "wav"))
    sound_file = test_sound_file(str(values.get("pace_notes_sound_path", "")), sound_format)
    if not sound_file:
        return trm(f"No .{sound_format.strip().strip('.')} sound in the sound folder")
    from .pace_notes_player import PaceNotesPlayer

    player = owner.findChild(PaceNotesPlayer, "testSoundPlayer")
    if player is None:
        # Own copy of settings with playback off: never plays notes while driving
        player = PaceNotesPlayer(owner, {**cfg.user.setting["pace_notes_playback"], "enable": False})
        player.setObjectName("testSoundPlayer")
    player.stop()
    volume = values.get("pace_notes_sound_volume", 50)
    player.set_volume(int(volume) if isinstance(volume, (int, float)) else 50)
    player.setSource(QUrl.fromLocalFile(sound_file))
    player.play()
    return trm(f"Playing {os.path.basename(sound_file)}")


class PaceNotesControl(SettingsHostMixin, QWidget):
    """Pace Notes page: pace notes category of the Settings page alone (QML page created when first shown)

    Args:
        playback: audio playback of main view (kept as is: follows saved settings by app refresh).
    """

    def __init__(self, parent, playback: PaceNotesPlayback | None = None):
        super().__init__(parent)
        self.playback = playback
        self.backend: SettingsBackend | None = None
        self.view: QQuickWidget | None = None  # see ensure_view
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def ensure_view(self) -> QQuickWidget | None:
        if self.view is None:
            from .quick import create_quick_view
            from .quick.settings_backend import SettingsBackend

            self.backend = SettingsBackend(self, self, only=CATEGORY)
            view = create_quick_view(self, "Settings.qml", {"backend": self.backend}, samples=0)
            view.setAcceptDrops(False)  # preset & plugin files dropped go to main window
            self._layout.addWidget(view)
            view.show()  # child added to a shown page is not shown by itself
            self.setFocusProxy(view)
            self.view = view
        return self.view

    def showEvent(self, event):
        self.ensure_view()
        if self.backend is not None:
            self.backend.refresh()  # preset loaded or settings changed while hidden
        super().showEvent(event)

    def closeEvent(self, event):
        super().closeEvent(event)
        self.release_page()

    def release_page(self):
        """Page closed or released (see LazyPage.release): QML gone before the backend it binds to"""
        if self.view is not None:
            view, self.view = self.view, None
            view.setSource(QUrl())
            view.deleteLater()

    @Slot(bool)  # type: ignore[operator]
    def refresh(self, *_):
        """Setting or preset changed elsewhere: shown values read again (once shown if hidden)"""
        if self.backend is not None and self.isVisible():
            self.backend.refresh()

    # Settings host
    def confirm(self, text: str) -> bool:
        from ._common import confirm_action

        return confirm_action(self, tr("Confirm"), text, tr("Confirm"))

    def applied(self, sections: set[str], restart: list[str]):
        """Only pace notes settings (preset) are shown here: nothing of config.json saved"""
