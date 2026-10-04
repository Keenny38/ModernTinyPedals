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
Notification
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr, trm
from ..setting import cfg
from ..update import can_auto_update, download_installer, release_url, run_installer, update_checker

logger = logging.getLogger(__name__)


class NotifyBar(QWidget):
    """Notify bar"""

    def __init__(self, parent):
        super().__init__(parent)
        self.presetlocked = QPushButton(tr("Preset Locked"))
        self.presetlocked.setVisible(False)

        self.spectate = QPushButton(tr("Spectate Mode Enabled"))
        self.spectate.setVisible(False)

        self.pacenotes = QPushButton(tr("Pace Notes Playback Enabled"))
        self.pacenotes.setVisible(False)

        self.hotkey = QPushButton(tr("Global Hotkey Enabled"))
        self.hotkey.setVisible(False)

        self.carsetup = QPushButton(tr("Auto Backup Car Setup Enabled"))
        self.carsetup.setVisible(False)

        self.updates = UpdatesNotifyButton("")
        self.updates.setVisible(False)

        layout = QVBoxLayout()
        layout.addWidget(self.presetlocked)
        layout.addWidget(self.spectate)
        layout.addWidget(self.pacenotes)
        layout.addWidget(self.hotkey)
        layout.addWidget(self.carsetup)
        layout.addWidget(self.updates)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

    @Slot(bool)  # type: ignore[operator]
    def refresh(self):
        """Refresh & update style"""
        # Locked preset
        self.presetlocked.setVisible(
            cfg.notification["notify_locked_preset"]
            and cfg.filename.setting in cfg.user.filelock
        )
        if self.presetlocked.isVisible():
            self.presetlocked.setStyleSheet(
                f"color: {cfg.notification['font_color_locked_preset']};"
                f"background: {cfg.notification['background_color_locked_preset']};"
            )
        # Spectate mode
        self.spectate.setVisible(
            cfg.notification["notify_spectate_mode"]
            and cfg.api["enable_player_index_override"]
        )
        if self.spectate.isVisible():
            self.spectate.setStyleSheet(
                f"color: {cfg.notification['font_color_spectate_mode']};"
                f"background: {cfg.notification['background_color_spectate_mode']};"
            )
        # Pace notes playback
        self.pacenotes.setVisible(
            cfg.notification["notify_pace_notes_playback"]
            and cfg.user.setting["pace_notes_playback"]["enable"]
        )
        if self.pacenotes.isVisible():
            self.pacenotes.setStyleSheet(
                f"color: {cfg.notification['font_color_pace_notes_playback']};"
                f"background: {cfg.notification['background_color_pace_notes_playback']};"
            )
        # Global hotkey
        self.hotkey.setVisible(
            cfg.notification["notify_global_hotkey"]
            and cfg.application["enable_global_hotkey"]
        )
        if self.hotkey.isVisible():
            self.hotkey.setStyleSheet(
                f"color: {cfg.notification['font_color_global_hotkey']};"
                f"background: {cfg.notification['background_color_global_hotkey']};"
            )
        # Auto backup car setup
        self.carsetup.setVisible(
            cfg.notification["notify_auto_backup_car_setup"]
            and cfg.telemetry["enable_auto_backup_car_setup"]
        )
        if self.carsetup.isVisible():
            self.carsetup.setStyleSheet(
                f"color: {cfg.notification['font_color_auto_backup_car_setup']};"
                f"background: {cfg.notification['background_color_auto_backup_car_setup']};"
            )


class UpdatesNotifyButton(QPushButton):
    """Updates notify button"""

    downloaded = Signal(str, str)  # installer path, error message

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        version_menu = QMenu(self)

        self.install_update = version_menu.addAction(tr("Download And Install"))
        self.install_update.triggered.connect(self.download_update)
        self.install_update.setVisible(False)
        self.downloaded.connect(self.install_downloaded)
        self._auto_install = False
        self._prompted_version = ""

        self.view_notes = version_menu.addAction(tr("What's New"))
        self.view_notes.triggered.connect(self.show_release_notes)
        self.view_notes.setVisible(False)

        view_update = version_menu.addAction(tr("View Updates On GitHub"))
        view_update.triggered.connect(self.open_release)
        version_menu.addSeparator()

        dismiss_msg = version_menu.addAction(tr("Dismiss"))
        dismiss_msg.triggered.connect(self.hide)

        self.setMenu(version_menu)

    def open_release(self):
        """Open release link"""
        QDesktopServices.openUrl(release_url())

    @Slot(bool)  # type: ignore[operator]
    def checking(self, checking: bool):
        """Checking updates"""
        if checking:
            # Show checking message only with manual checking
            self.setText(tr("Checking For Updates..."))
            self.setVisible(update_checker.is_manual())
        else:
            # Hide message if no unpdates and not manual checking
            self.setText(trm(update_checker.message()))
            self.setVisible(update_checker.is_manual() or update_checker.is_updates())
            self.view_notes.setVisible(update_checker.is_updates() and bool(update_checker.release_notes))
            self.install_update.setVisible(
                can_auto_update() and update_checker.is_updates() and update_checker.installer is not None
            )
            if self.install_update.isVisible():
                self.prompt_update()

    def prompt_update(self):
        """Ask once per version to install available update (what's new shown), install downloads it"""
        version_text = update_checker.message()
        if self._prompted_version == version_text:
            return
        self._prompted_version = version_text
        self.show_release_notes(prompt=True)

    def release_notes_dialog(self, prompt: bool = False):
        """What's new page of available update, install button when it can install"""
        from .release_notes import ReleaseNotesDialog

        dialog = ReleaseNotesDialog(
            self, update_checker.release_notes, update_checker.latest_version(), update_checker.latest_date(),
            can_install=can_auto_update() and update_checker.is_updates() and update_checker.installer is not None,
            prompt=prompt, download_url=update_checker.installer.url if update_checker.installer else "")
        dialog.install_requested.connect(self.install_from_notes)
        return dialog

    def show_release_notes(self, prompt: bool = False):
        """Show release notes (changelog) of available update"""
        self.release_notes_dialog(prompt).open()

    def install_from_notes(self):
        """Install asked from what's new page: installs once downloaded, no second question"""
        self._auto_install = True
        self.download_update()

    def download_update(self):
        """Download installer in background thread"""
        asset = update_checker.installer
        if asset is None:
            return
        self.install_update.setEnabled(False)
        self.setText(tr("Downloading Update..."))

        def download():
            try:
                self.downloaded.emit(download_installer(asset), "")
            except (OSError, ValueError) as error:
                logger.error("UPDATES: download failed: %s", error)
                self.downloaded.emit("", str(error))

        threading.Thread(target=download, daemon=True, name="Update download").start()

    @Slot(str, str)  # type: ignore[operator]
    def install_downloaded(self, path: str, error: str):
        """Run installer and quit, installer restarts TinyPedal when done"""
        self.install_update.setEnabled(True)
        self.setText(trm(update_checker.message()))
        auto_install, self._auto_install = self._auto_install, False
        if not path:
            QMessageBox.warning(self, tr("Error"), trm(f"Unable to download update: {error}"))
            return
        if not auto_install:
            confirm = QMessageBox.question(
                self, tr("Download And Install"),
                tr("Update downloaded. Close Modern Tiny Pedals and install it now?"),
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
        run_installer(path)
        window = self.window()
        quit_app = getattr(window, "quit_app", None)
        if callable(quit_app):
            quit_app()
