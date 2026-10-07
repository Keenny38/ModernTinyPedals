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
import os
import threading
from contextlib import suppress
from time import monotonic

import shiboken6
from PySide6.QtCore import QLocale, QObject, Qt, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ..const_app import APP_NAME
from ..i18n import current_language, tr, trm
from ..setting import cfg
from ..update import (
    DownloadCancelled,
    UnsignedInstallerError,
    can_auto_update,
    download_installer,
    is_portable_copy,
    release_url,
    run_installer,
    skip_version,
    update_checker,
)
from ._common import find_dialog_host

logger = logging.getLogger(__name__)

DOWNLOAD_CANCELLED = "cancelled"  # error message of cancelled download, see UpdateInstaller


def main_window() -> QWidget | None:
    """Main application window (has quit_app), None if not created"""
    for widget in QApplication.topLevelWidgets():
        if callable(getattr(widget, "quit_app", None)):
            return widget
    return None


def install_update(window: QWidget | None, path: str, repository: str | None = None) -> bool:
    """Run downloaded installer then quit, False if cancelled or installer not started

    Open pages are closed first (each may ask to save changes): cancelling keeps app as is,
    installer is only started once app can quit.

    Args:
        repository: update repository the installer was downloaded from, None for current setting.
    """
    close_pages = getattr(window, "close_pages_for_quit", None)
    if callable(close_pages) and not close_pages():
        return False
    try:
        run_installer(path, repository=repository)
    except (OSError, ValueError) as error:
        logger.error("UPDATES: unable to run installer: %s", error)
        cancel_quit = getattr(window, "cancel_quit", None)
        if callable(cancel_quit):
            cancel_quit()
        if isinstance(error, ValueError):  # broken signature: installer never kept
            with suppress(OSError):
                os.remove(path)
        if isinstance(error, UnsignedInstallerError):
            msg_text = tr("Installer of custom update repository is not signed, update was not installed.")
        elif isinstance(error, ValueError):
            msg_text = tr("Installer signature is not valid, update was not installed.")
        else:
            msg_text = trm(f"Unable to install update: {error}")
        QMessageBox.warning(window, tr("Error"), msg_text)
        return False
    quit_app = getattr(window, "quit_app", None)
    if callable(quit_app):
        quit_app()
    return True


def format_megabytes(size: int) -> str:
    """Size in MB, one decimal, in current language"""
    return QLocale(current_language()).toString(size / 1_000_000, "f", 1)


def download_progress_text(received: int, total: int) -> str:
    """Downloaded part: percent & size, or size only if total is unknown"""
    if total > 0:
        percent = min(round(received * 100 / total), 100)
        return trm(f"{percent}% ({format_megabytes(received)} / {format_megabytes(total)} MB)")
    return trm(f"{format_megabytes(received)} MB")


class UpdateInstaller(QObject):
    """Download & install of update: one download at a time, whatever button or page asked it

    Notify buttons are rebuilt on language change and what's new pages can be reopened,
    so download state (busy, progress) is kept here, not in them.
    """

    busy_changed = Signal(bool)
    progress = Signal(int, int)  # received, total bytes (0 if unknown), from download thread
    downloaded = Signal(str, str)  # installer path, error message (from download thread)
    PROGRESS_INTERVAL = 0.1  # seconds between progress signals

    def __init__(self):
        super().__init__()
        self.busy = False
        self.received = 0
        self.total = 0
        self._auto_install = False
        self._repository: str | None = None  # update repository of downloading installer
        self._cancel = threading.Event()
        self.downloaded.connect(self.install_downloaded)
        self.progress.connect(self.store_progress)

    def download(self, auto_install: bool = False) -> bool:
        """Download installer in background thread, False if none or already downloading"""
        asset = update_checker.installer
        if asset is None or self.busy:
            return False
        self.busy = True
        self.received = self.total = 0
        self._auto_install = auto_install
        # Repository of release found at check time: setting may change before installing
        self._repository = asset.repository or None
        self._cancel = cancel = threading.Event()
        self.busy_changed.emit(True)
        last_report = [0.0]

        def report(received: int, total: int):
            now = monotonic()
            if now - last_report[0] >= self.PROGRESS_INTERVAL or received >= total > 0:
                last_report[0] = now
                self.progress.emit(received, total)

        def download():
            try:
                path, message = download_installer(asset, progress=report, cancelled=cancel), ""
            except DownloadCancelled:
                logger.info("UPDATES: download cancelled")
                path, message = "", DOWNLOAD_CANCELLED
            except Exception as error:  # OSError, ValueError, or unexpected: never left busy
                logger.error("UPDATES: download failed: %s", error)
                path, message = "", str(error)
            self.downloaded.emit(path, message)

        threading.Thread(target=download, daemon=True, name="Update download").start()
        return True

    def cancel(self) -> bool:
        """Stop download (partial file removed), False if not downloading"""
        if not self.busy:
            return False
        self._cancel.set()
        return True

    @Slot(int, int)  # type: ignore[operator]
    def store_progress(self, received: int, total: int):
        """Progress kept for buttons & pages shown later"""
        self.received, self.total = received, total

    def progress_text(self) -> str:
        """Downloaded part of current download"""
        return download_progress_text(self.received, self.total)

    @Slot(str, str)  # type: ignore[operator]
    def install_downloaded(self, path: str, error: str):
        """Run installer and quit, installer restarts TinyPedal when done"""
        self.busy = False
        self.busy_changed.emit(False)
        auto_install, self._auto_install = self._auto_install, False
        window = main_window()
        if error == DOWNLOAD_CANCELLED:
            return
        if not path:
            QMessageBox.warning(window, tr("Error"), trm(f"Unable to download update: {error}"))
            return
        if not auto_install:
            confirm = QMessageBox.question(
                window, tr("Download And Install"),
                tr("Update downloaded. Close Modern Tiny Pedals and install it now?"),
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
        install_update(window, path, self._repository)


_update_installer: UpdateInstaller | None = None


def update_installer() -> UpdateInstaller:
    """Update download & install (created once, after QApplication)"""
    global _update_installer
    if _update_installer is None:
        _update_installer = UpdateInstaller()
    return _update_installer


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
    """Updates notify button

    Prompted version & dismissed message are shared by buttons (rebuilt on language change).
    """

    prompted_version = ""  # update already proposed, see prompt_update
    dismissed_message = ""  # update message hidden by user, see dismiss

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        version_menu = QMenu(self)

        self.install_update = version_menu.addAction(tr("Download And Install"))
        self.install_update.triggered.connect(self.download_update)
        self.install_update.setVisible(False)
        self._auto_install = False
        installer = update_installer()
        installer.busy_changed.connect(self.download_state)
        installer.progress.connect(self.download_progress)

        self.cancel_download = version_menu.addAction(tr("Cancel Download"))
        self.cancel_download.triggered.connect(lambda: update_installer().cancel())
        self.cancel_download.setVisible(False)

        self.view_notes = version_menu.addAction(tr("What's New"))
        self.view_notes.triggered.connect(lambda: self.show_release_notes())
        self.view_notes.setVisible(False)

        view_update = version_menu.addAction(tr("View Updates On GitHub"))
        view_update.triggered.connect(self.open_release)
        version_menu.addSeparator()

        self.skip_update = version_menu.addAction(tr("Skip This Version"))
        self.skip_update.setToolTip(tr("Not shown again for this version, shown again for a newer one"))
        self.skip_update.triggered.connect(self.skip)
        self.skip_update.setVisible(False)

        dismiss_msg = version_menu.addAction(tr("Dismiss"))
        dismiss_msg.triggered.connect(self.dismiss)

        self.setMenu(version_menu)

    def open_release(self):
        """Open release link"""
        QDesktopServices.openUrl(release_url())

    def dismiss(self):
        """Hide message, kept hidden when button is rebuilt (language change)"""
        UpdatesNotifyButton.dismissed_message = update_checker.message()
        self.hide()

    def skip(self):
        """Skip version of available update: notice not shown again (a newer version is), saved"""
        skip_update_version()
        self.hide()

    def can_install(self) -> bool:
        """Update available & app can download and run its installer"""
        return can_auto_update() and update_checker.is_updates() and update_checker.installer is not None

    @Slot(bool)  # type: ignore[operator]
    def checking(self, checking: bool):
        """Checking updates"""
        if checking:
            # Show checking message only with manual checking
            self.setText(tr("Checking For Updates..."))
            self.setVisible(update_checker.is_manual())
        else:
            # Hide message if no updates (or version skipped) and not manual checking
            skipped = update_checker.is_skipped()
            self.setText(trm(update_checker.message()))
            self.setVisible(update_checker.is_manual() or (update_checker.is_updates() and not skipped))
            self.view_notes.setVisible(update_checker.is_updates() and bool(update_checker.notes(current_language())))
            self.skip_update.setVisible(update_checker.is_updates())
            self.install_update.setVisible(self.can_install())
            if self.install_update.isVisible() and not skipped:
                self.prompt_update()
            self.download_state(update_installer().busy)

    def restore(self):
        """Show result of last check again (button rebuilt on language change), unless dismissed"""
        if update_checker.is_checking():
            self.checking(True)
        elif (update_checker.is_updates() and not update_checker.is_skipped()
                and update_checker.message() != self.dismissed_message):
            self.checking(False)

    @Slot(bool)  # type: ignore[operator]
    def download_state(self, busy: bool):
        """Downloading update: shown on button (with progress), install entry disabled, cancel shown"""
        self.install_update.setEnabled(not busy)
        self.cancel_download.setVisible(busy)
        if busy:
            installer = update_installer()
            self.download_progress(installer.received, installer.total)
        elif update_checker.is_updates():
            self.setText(trm(update_checker.message()))

    @Slot(int, int)  # type: ignore[operator]
    def download_progress(self, received: int, total: int):
        """Downloaded part shown on button"""
        if not update_installer().busy:
            return
        text = tr("Downloading Update...")
        if received:
            text = f"{text} {download_progress_text(received, total)}"
        self.setText(text)

    def prompt_update(self):
        """Ask once per version to install available update (what's new shown), install downloads it

        Window hidden (tray) or minimized, game likely running: never popped up, what's new page
        waits inside app and a tray message tells about the update.
        """
        version_text = update_checker.message()
        if self.prompted_version == version_text:
            return
        UpdatesNotifyButton.prompted_version = version_text
        window = self.window()
        if window.isVisible() and not window.isMinimized():
            self.show_release_notes(prompt=True)
            return
        self.show_release_notes(prompt=True, bring_to_front=False)
        tray_icon = window.findChild(QSystemTrayIcon)
        if tray_icon is not None and tray_icon.isVisible():
            show_app = getattr(window, "show_app", None)
            if callable(show_app):
                tray_icon.messageClicked.connect(show_app, Qt.ConnectionType.UniqueConnection)
            version = ".".join(str(number) for number in update_checker.latest_version())
            tray_icon.showMessage(
                APP_NAME, trm(f"Update available: v{version}. Open {APP_NAME} to see what's new and install it."),
                QSystemTrayIcon.MessageIcon.Information, 15000)

    def release_notes_dialog(self, prompt: bool = False):
        """What's new page of available update, install button when it can install"""
        from .release_notes import ReleaseNotesDialog

        portable = is_portable_copy()
        installer = update_checker.installer
        dialog = ReleaseNotesDialog(
            self, update_checker.notes(current_language()), update_checker.latest_version(), update_checker.latest_date(),
            can_install=self.can_install(), prompt=prompt,
            download_url=installer.url if installer is not None and not portable else "", portable=portable,
            installer=update_installer(), can_skip=update_checker.is_updates())
        # Page may outlive this button (kept when view is rebuilt in new language): not only bound to it
        dialog.install_requested.connect(
            lambda button=self: button.install_from_notes() if shiboken6.isValid(button) else install_from_notes())
        dialog.skip_requested.connect(skip_from_notes)
        dialog.skip_requested.connect(self.hide)
        return dialog

    def show_release_notes(self, prompt: bool = False, bring_to_front: bool = True):
        """Show release notes (changelog) of available update

        Not brought to front: shown as page of hidden window, seen once window is opened.
        """
        dialog = self.release_notes_dialog(prompt)
        if bring_to_front:
            dialog.open()
            return
        host = find_dialog_host(self)
        if host is None or not host.show_dialog_page(dialog, bring_to_front=False):
            dialog.deleteLater()  # no page to wait in: tray message only

    def install_from_notes(self):
        """Install asked from what's new page: installs once downloaded, no second question"""
        self._auto_install = True
        self.download_update()

    def download_update(self):
        """Download installer in background thread (once, while not already downloading)"""
        auto_install, self._auto_install = self._auto_install, False
        update_installer().download(auto_install)


def install_from_notes():
    """Install asked from what's new page: installs once downloaded, no second question"""
    update_installer().download(auto_install=True)


def skip_update_version():
    """Version of available update skipped (saved): notice not shown again, a newer version is"""
    skip_version(update_checker.latest_version())
    UpdatesNotifyButton.dismissed_message = update_checker.message()


def skip_from_notes():
    """Skip asked from what's new page: version skipped, update notices of main window hidden"""
    skip_update_version()
    window = main_window()
    if window is not None:
        for button in window.findChildren(UpdatesNotifyButton):
            button.hide()
