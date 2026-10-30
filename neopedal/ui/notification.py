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
Notification
"""

from __future__ import annotations

import logging
import sys
import threading
import weakref
from collections.abc import Callable
from functools import partial
from time import monotonic

import shiboken6
from PySide6.QtCore import QDateTime, QLocale, QObject, Qt, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QWidget,
)

from ..const_app import APP_NAME
from ..i18n import current_language, tr, trm
from ..jobs import Job, WorkerPool, get_courier, weak_callback
from ..lazy_service import update_checker
from ..setting import cfg
from ._common import UIScaler, confirm_action, find_dialog_host

logger = logging.getLogger(__name__)

DOWNLOAD_CANCELLED = "cancelled"  # error message of cancelled download, see UpdateInstaller


def main_window() -> QWidget | None:
    """Main application window (has quit_app), None if not created"""
    for widget in QApplication.topLevelWidgets():
        if callable(getattr(widget, "quit_app", None)):
            return widget
    return None


# Update module (http.client, urllib, zipfile...) imported once used: not at start, see lazy_service
def can_auto_update() -> bool:
    """See update.can_auto_update"""
    from ..update import can_auto_update as found

    return found()


def is_portable_copy() -> bool:
    """See update.is_portable_copy"""
    from ..update import is_portable_copy as found

    return found()


def release_url() -> str:
    """See update.release_url"""
    from ..update import release_url as found

    return found()


def skip_version(version_tuple: tuple[int, int, int]):
    """See update.skip_version"""
    from ..update import skip_version as found

    found(version_tuple)


def discard_installer(path: str) -> None:
    """See update.discard_installer"""
    from ..update import discard_installer as found

    found(path)


def download_installer(asset, **kwargs) -> str:
    """See update.download_installer"""
    from ..update import download_installer as found

    return found(asset, **kwargs)


def run_installer(path: str, folder: str | None = None, repository: str | None = None,
                  signer: str | None = None) -> None:
    """See update.run_installer"""
    from ..update import run_installer as found

    found(path, folder, repository, signer)


def installer_signer(path: str, repository: str | None = None) -> str:
    """See update.installer_signer"""
    from ..update import installer_signer as found

    return found(path, repository)


def is_official_repository(repo: str) -> bool:
    """See update.is_official_repository"""
    from ..update import is_official_repository as found

    return found(repo)


def update_repository() -> str:
    """See update.update_repository"""
    from ..update import update_repository as found

    return found()


def install_error_text(error: Exception) -> str:
    """Message of installer refused or not started (run_installer, installer_signer errors)"""
    from ..update import InstallerChangedError, RevocationUnknownError, UnsignedInstallerError

    if isinstance(error, UnsignedInstallerError):
        return tr("Installer of custom update repository is not signed, update was not installed.")
    if isinstance(error, RevocationUnknownError):
        return tr("Revocation of the installer signing certificate could not be checked (server unreachable), "
                  "update was not installed. Try again later.")
    if isinstance(error, InstallerChangedError):
        return tr("Installer changed after it was downloaded, update was not installed.")
    if isinstance(error, ValueError):
        return tr("Installer signature is not valid, update was not installed.")
    return trm(f"Unable to install update: {error}")


def display_signer(signer: str) -> str:
    """Signer name shown in a message (certificate text: no markup, no control character, bounded)"""
    return "".join(char for char in signer if char not in "<>&" and char.isprintable())[:200]


def install_update(window: QWidget | None, path: str, repository: str | None = None,
                   signer: str | None = None) -> bool:
    """Run downloaded installer then quit, False if cancelled or installer not started

    Open pages are closed first (each may ask to save changes): cancelling keeps app as is,
    installer is only started once app can quit. Installer not started: removed (downloaded again next time).

    Args:
        repository: update repository the installer was downloaded from, None for current setting.
        signer: signer shown to user (custom repository), installer refused if signed by another one.
    """
    close_pages = getattr(window, "close_pages_for_quit", None)
    if callable(close_pages) and not close_pages():
        discard_installer(path)
        return False
    try:
        run_installer(path, repository=repository, signer=signer)
    except (OSError, ValueError) as error:
        logger.error("UPDATES: unable to run installer: %s", error)
        cancel_quit = getattr(window, "cancel_quit", None)
        if callable(cancel_quit):
            cancel_quit()
        discard_installer(path)  # broken signature never kept, unstartable one never left in temp folder
        QMessageBox.warning(window, tr("Error"), install_error_text(error))
        return False
    quit_app = getattr(window, "quit_app", None)
    if callable(quit_app):
        quit_app()
    return True


def format_megabytes(size: int) -> str:
    """Size in MB, one decimal, in current language"""
    return QLocale(current_language()).toString(size / 1_000_000, "f", 1)


def _download(asset, report: Callable[[int, int], None], cancel: threading.Event) -> tuple[str, str, str | None]:
    """Installer downloaded (download thread): path, error message ("" if downloaded) & signer

    Installer of a custom update repository: signature verified (revocation checked online, off the UI
    thread), its signer shown before installing; refused one removed, error is then the full message.
    Signer None: official release (signed manifest verified at check time).
    """
    from ..update import DownloadCancelled

    try:
        path = download_installer(asset, progress=report, cancelled=cancel)
    except DownloadCancelled:
        logger.info("UPDATES: download cancelled")
        return "", DOWNLOAD_CANCELLED, None
    except Exception as error:  # OSError, ValueError, or unexpected: never left busy
        logger.error("UPDATES: download failed: %s", error)
        return "", trm(f"Unable to download update: {error}"), None
    repository = asset.repository or update_repository()
    if is_official_repository(repository):
        return path, "", None
    try:
        return path, "", installer_signer(path, repository)
    except Exception as error:  # refused (ValueError), unreadable (OSError) or unexpected: never left busy
        logger.error("UPDATES: installer refused: %s", error)
        discard_installer(path)
        return "", install_error_text(error), None


_download_workers: WorkerPool | None = None


def _download_pool() -> WorkerPool:
    """Worker thread of update downloads, created when first needed (UI thread)"""
    global _download_workers
    if _download_workers is None:
        _download_workers = WorkerPool(1, "Update download")
    return _download_workers


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
    PROGRESS_INTERVAL = 0.1  # seconds between progress signals

    def __init__(self):
        super().__init__()
        self.busy = False
        self.received = 0
        self.total = 0
        self._auto_install = False
        self._repository: str | None = None  # update repository of downloading installer
        self._cancel = threading.Event()
        self._serial = 0
        self._ref = weakref.ref(self)
        get_courier()  # created on the UI thread (hands the download result over)
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

        def report(received: int, total: int):  # download thread: progress signal of this app-lifetime object
            now = monotonic()
            if now - last_report[0] >= self.PROGRESS_INTERVAL or received >= total > 0:
                last_report[0] = now
                self.progress.emit(received, total)

        # Job of its own worker thread (a download of minutes never holds back page jobs), handed over on the UI
        # thread by the jobs courier (deliver_job)
        self._serial += 1
        _download_pool().submit(Job(self._serial, None, "download", "Update", partial(_download, asset, report, cancel),
                                    weak_callback(None), weak_callback(None), False, self._ref))
        return True

    def deliver_job(self, job: Job):
        """Download over (UI thread): installer run, or error shown"""
        ok, value = job.outcome or (False, None)
        job.release()
        if not ok:  # unexpected error of the download thread: never left busy
            logger.error("UPDATES: download failed: %s", value)
        path, message, signer = value if ok else ("", trm(f"Unable to download update: {value}"), None)
        self.install_downloaded(path, message, signer)

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

    def install_downloaded(self, path: str, error: str, signer: str | None = None):
        """Run installer and quit, installer restarts NeoPedal when done

        Args:
            error: full message of failed download (empty if downloaded).
            signer: signer of installer of a custom update repository (see _download): always asked first,
                with update repository & signer shown. None: official release.
        """
        self.busy = False
        self.busy_changed.emit(False)
        auto_install, self._auto_install = self._auto_install, False
        window = main_window()
        if error == DOWNLOAD_CANCELLED:
            return
        if not path:
            QMessageBox.warning(window, tr("Error"), error)
            return
        if signer is not None:  # custom update repository: publisher shown, never installed without asking
            repository = self._repository or update_repository()
            publisher = display_signer(signer) or tr("unknown publisher")
            question = trm(f"Update downloaded from {repository}, installer signed by {publisher}. "
                           "Install it only if you trust this publisher. Close NeoPedal and install it now?")
        elif not auto_install:
            question = tr("Update downloaded. Close NeoPedal and install it now?")
        else:
            question = ""
        if question and not confirm_action(window, tr("Download And Install"), question, tr("Install Now"),
                                           default_action=signer is None):
            discard_installer(path)  # declined: never left in temp folder
            return
        if signer is None:
            install_update(window, path, self._repository)
        else:
            install_update(window, path, self._repository, signer=signer)


_update_installer: UpdateInstaller | None = None


def update_installer() -> UpdateInstaller:
    """Update download & install (created once, after QApplication)"""
    global _update_installer
    if _update_installer is None:
        _update_installer = UpdateInstaller()
    return _update_installer


# Status chips of the status band: (attribute, notice name of colors & option, text, notification center action)
NOTICE_CHIPS = (
    ("presetlocked", "locked_preset", "Preset Locked", "page:preset"),
    ("spectate", "spectate_mode", "Spectate Mode Enabled", "page:spectate"),
    ("pacenotes", "pace_notes_playback", "Pace Notes Playback Enabled", "page:pacenotes"),
    ("hotkey", "global_hotkey", "Global Hotkey Enabled", "page:hotkey"),
    ("carsetup", "auto_backup_car_setup", "Auto Backup Car Setup Enabled", ""),
    ("director", "broadcast_director", "Broadcast Director On", "tool:broadcast_director.BroadcastDirector"),
)
MIN_CONTRAST = 4.5  # WCAG AA, text of chips on their background


def _luminance(color: QColor) -> float:
    channels = [value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
                for value in (color.redF(), color.greenF(), color.blueF())]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(first: QColor, second: QColor) -> float:
    """WCAG contrast ratio of two colors"""
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def readable_colors(font: str, background: str) -> tuple[str, str]:
    """Text & background colors of a chip with at least MIN_CONTRAST: user colors kept when readable, else the
    background is darkened (light text) or lightened (dark text) in its hue, else the text turned black or white"""
    text, fill = QColor(font), QColor(background)
    if not text.isValid():
        text = QColor("white")
    if not fill.isValid():
        fill = QColor("#5E6670")
    text.setAlpha(255)
    fill.setAlpha(255)
    light_text = _luminance(text) >= _luminance(fill)
    for _ in range(40):
        if contrast(text, fill) >= MIN_CONTRAST:
            break
        fill = QColor((fill.darker(106) if light_text else fill.lighter(106)).name())  # 8-bit, as written
    if contrast(text, fill) < MIN_CONTRAST:
        text = QColor("black") if contrast(QColor("black"), fill) > contrast(QColor("white"), fill) else QColor("white")
    return text.name(), fill.name()


class NotifyBar(QWidget):
    """Status chips of the window status band: preset locked, spectate, pace notes, global hotkey, car setup
    backup, Broadcast Director on, update available. One line (chips side by side), colors of Notification
    settings kept readable (see readable_colors). Shown notices are listed in the notification center too."""

    def __init__(self, parent):
        super().__init__(parent)
        layout = QHBoxLayout()
        layout.setSpacing(UIScaler.pixel(4))
        layout.setContentsMargins(0, 0, 0, 0)
        for attribute, _, text, _ in NOTICE_CHIPS:
            button = QPushButton(tr(text))
            button.setObjectName("statusChip")
            button.setVisible(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            setattr(self, attribute, button)
            layout.addWidget(button)

        self.updates = UpdatesNotifyButton("")
        self.updates.setVisible(False)
        self.updates.setStyleSheet(self.chip_style())
        layout.addWidget(self.updates)
        layout.addStretch(1)
        self.setLayout(layout)

    presetlocked: QPushButton
    spectate: QPushButton
    pacenotes: QPushButton
    hotkey: QPushButton
    carsetup: QPushButton
    director: QPushButton

    @staticmethod
    def chip_style(font: str = "", background: str = "") -> str:
        """Style sheet of a chip: rounded, compact, colors if set"""
        colors = f"color: {font}; background: {background};" if font and background else ""
        return (f"QPushButton {{ {colors} border: none; border-radius: {UIScaler.pixel(9)}px; "
                f"padding: {UIScaler.pixel(1)}px {UIScaler.pixel(9)}px; margin: {UIScaler.pixel(2)}px 0; }}")

    @Slot(bool)  # type: ignore[operator]
    def refresh(self):
        """Refresh & update style"""
        notification = cfg.notification
        self.set_notice(
            self.presetlocked, "locked_preset",
            notification["notify_locked_preset"] and cfg.filename.setting in cfg.user.filelock)
        self.set_notice(
            self.spectate, "spectate_mode",
            notification["notify_spectate_mode"] and cfg.api["enable_player_index_override"])
        self.set_notice(
            self.pacenotes, "pace_notes_playback",
            notification["notify_pace_notes_playback"] and cfg.user.setting["pace_notes_playback"]["enable"])
        self.set_notice(
            self.hotkey, "global_hotkey",
            notification["notify_global_hotkey"] and cfg.application["enable_global_hotkey"])
        self.set_notice(
            self.carsetup, "auto_backup_car_setup",
            notification["notify_auto_backup_car_setup"] and cfg.telemetry["enable_auto_backup_car_setup"])
        self.refresh_director()

    def refresh_director(self):
        """Broadcast Director page open with the director on (it asks the game while hidden too), each second"""
        module = sys.modules.get("neopedal.ui.quick.director_backend")  # imported only by the page
        running = module is not None and module.director_status() == "on"
        self.set_notice(self.director, "broadcast_director", cfg.notification["notify_broadcast_director"] and running)

    def set_notice(self, button: QPushButton, name: str, shown: bool):
        """Notice shown or hidden, its colors set only when changed (style sheet parsed again on each set)"""
        shown = bool(shown)
        if button.isHidden() == shown:
            button.setVisible(shown)
            self.publish_active()
        if not shown:
            return
        style = self.chip_style(*readable_colors(
            cfg.notification[f"font_color_{name}"], cfg.notification[f"background_color_{name}"]))
        if button.styleSheet() != style:
            button.setStyleSheet(style)

    def active_notices(self) -> list[tuple[str, str]]:
        """Shown notices: (text, notification center action)"""
        return [(tr(text), action) for attribute, _, text, action in NOTICE_CHIPS
                if not getattr(self, attribute).isHidden()]

    def publish_active(self):
        """Shown notices listed in the notification center"""
        notification_store().set_active(self.active_notices())


class UpdatesNotifyButton(QPushButton):
    """Updates notify button

    Prompted version & dismissed message are shared by buttons (rebuilt on language change).
    """

    prompted_version = ""  # update already proposed, see prompt_update
    dismissed_message = ""  # update message hidden by user, see dismiss
    logged_message = ""  # update message added to the notification center (once)

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
            # Show checking message only with manual checking, notice shown kept while checking automatically
            if not update_checker.is_manual():
                return
            self.setText(tr("Checking for updates…"))
            self.setVisible(True)
        else:
            # Hide message if no updates (or version skipped, or dismissed) and not manual checking.
            # Release refused (signed manifest not verified): shown like an update, without install
            skipped = update_checker.is_skipped()
            dismissed = update_checker.message() == self.dismissed_message
            noticed = (update_checker.is_updates() and not skipped) or update_checker.is_refused()
            self.setText(trm(update_checker.message()))
            self.setVisible(update_checker.is_manual() or (noticed and not dismissed))
            if noticed and UpdatesNotifyButton.logged_message != update_checker.message():
                UpdatesNotifyButton.logged_message = update_checker.message()  # once per version
                updates = update_checker.is_updates()
                notification_store().add(trm(update_checker.message()), "info" if updates else "warning",
                                         ((tr("What's New"), "updates"),) if updates else ())
            self.view_notes.setVisible(update_checker.is_updates() and bool(update_checker.notes(current_language())))
            self.skip_update.setVisible(update_checker.is_updates())
            self.install_update.setVisible(self.can_install())
            if self.install_update.isVisible() and not skipped:
                self.prompt_update()
            self.download_state(update_installer().busy)

    def restore(self):
        """Show result of last check again (button rebuilt on language change), unless dismissed"""
        if not update_checker.imported:  # never checked (window built at start): nothing to show
            return
        if update_checker.is_checking():
            self.checking(True)
        elif (((update_checker.is_updates() and not update_checker.is_skipped()) or update_checker.is_refused())
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
        text = tr("Downloading Update…")
        if received:
            text = f"{text} {download_progress_text(received, total)}"
        self.setText(text)

    def prompt_update(self):
        """Ask once per version to install available update (what's new shown), install downloads it

        Window hidden (tray) or minimized, game likely running: never popped up, what's new page
        waits inside app and a tray message tells about the update. Found by automatic check while app
        runs: popped up only if window is the active one (not over the game on another screen).
        """
        version_text = update_checker.message()
        if self.prompted_version == version_text:
            return
        UpdatesNotifyButton.prompted_version = version_text
        window = self.window()
        if (window.isVisible() and not window.isMinimized()
                and (not update_checker.is_scheduled() or window.isActiveWindow())):
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
            installer=update_installer(), can_skip=update_checker.is_updates(),
            earlier=update_checker.earlier_notes(current_language()))
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
        from .release_notes import open_notes_page

        shown = open_notes_page(self, tr("Update Available") if prompt else tr("What's New"),
                                update_checker.latest_version())
        if shown is not None:  # notes of this update already open: shown again, no second page built
            if bring_to_front:
                shown.open()
            return
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


# Notification center: messages of the app kept with their time & level (errors of background work, saving
# failures, updates found), shown notices of the status band, read from the bell of the navigation rail
SEVERITIES = ("error", "warning", "info")
MAX_NOTIFICATIONS = 100
TRAY_MESSAGE_INTERVAL = 60.0  # seconds: at most one tray message this often (more messages: count told)


class NotificationStore(QObject):
    """Messages of the notification center (newest first) & notices shown in the status band

    Emits changed when messages, their read state or the shown notices change, added with each new message.
    A message repeating the last one is counted on it (time updated) instead of added again.
    """

    changed = Signal()
    added = Signal(dict)

    def __init__(self):
        super().__init__()
        self._entries: list[dict] = []
        self._active: list[tuple[str, str]] = []
        self._next_id = 1

    def add(self, text: str, severity: str = "error", actions: tuple[tuple[str, str], ...] = ()) -> dict:
        """Message added (severity: "error", "warning" or "info"), actions: (label, action key) of its buttons,
        see run_notification_action"""
        if severity not in SEVERITIES:
            severity = "error"
        now = QDateTime.currentDateTime()
        last = self._entries[0] if self._entries else None
        if last is not None and last["text"] == text and last["severity"] == severity:
            last["count"] += 1
            last["time"] = now
            last["read"] = False
            entry = last
        else:
            entry = {"id": self._next_id, "text": text, "severity": severity, "time": now, "count": 1,
                     "read": False, "actions": [{"label": label, "key": key} for label, key in actions]}
            self._next_id += 1
            self._entries.insert(0, entry)
            del self._entries[MAX_NOTIFICATIONS:]
        self.changed.emit()
        self.added.emit(entry)
        return entry

    def entries(self) -> list[dict]:
        """Messages, newest first"""
        return list(self._entries)

    def unread_count(self) -> int:
        return sum(not entry["read"] for entry in self._entries)

    def mark_all_read(self):
        if any(not entry["read"] for entry in self._entries):
            for entry in self._entries:
                entry["read"] = True
            self.changed.emit()

    def remove(self, entry_id: int):
        entries = [entry for entry in self._entries if entry["id"] != entry_id]
        if len(entries) != len(self._entries):
            self._entries = entries
            self.changed.emit()

    def clear(self):
        if self._entries:
            self._entries = []
            self.changed.emit()

    def active(self) -> list[tuple[str, str]]:
        """Notices shown in the status band: (text, action key)"""
        return list(self._active)

    def set_active(self, notices: list[tuple[str, str]]):
        if notices != self._active:
            self._active = list(notices)
            self.changed.emit()


_notification_store: NotificationStore | None = None


def notification_store() -> NotificationStore:
    """Notification center messages (created once, after QApplication)"""
    global _notification_store
    if _notification_store is None:
        _notification_store = NotificationStore()
    return _notification_store


def error_actions() -> tuple[tuple[str, str], ...]:
    """Buttons of an error message: log & bug report"""
    return ((tr("View Log"), "log"), (tr("Create Bug Report…"), "bug_report"))


def run_notification_action(window: QWidget | None, key: str):
    """Action of a notification center button: "log", "bug_report", "updates" (what's new of available update),
    "page:<page key>" (main window page), "tool:<module.DialogClass>" (tool page)"""
    if window is None:
        return
    show_app = getattr(window, "show_app", None)
    if callable(show_app):
        show_app()
    if key == "log":
        from .log_info import LogInfo

        LogInfo(window).show()
    elif key == "bug_report":
        from .bug_report_view import BugReport

        BugReport(window).show()
    elif key == "updates":
        for button in window.findChildren(UpdatesNotifyButton):
            button.show_release_notes()
            break
    elif key.startswith("page:"):
        from .nav_rail import PAGE_INDEX

        view = getattr(window, "centralWidget", lambda: None)()
        index = PAGE_INDEX.get(key.removeprefix("page:"))
        select_page = getattr(view, "select_page", None)
        if index is not None and callable(select_page):
            select_page(index)
    elif key.startswith("tool:"):
        from .tools_view import open_tool

        open_tool(key.removeprefix("tool:"), window)


class TrayRelay(QObject):
    """New error or warning while the main window is hidden in tray or minimized (racing): a tray message
    (system notification, never a window over the game), at most one per TRAY_MESSAGE_INTERVAL, the next one
    telling how many came meanwhile. Only with the tray icon shown (Minimize to Tray)."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        self._last = -TRAY_MESSAGE_INTERVAL
        self._waiting = 0  # messages not told since last tray message
        notification_store().added.connect(self.message_added)

    def message_added(self, entry: dict):
        window = self._window
        if entry["severity"] == "info" or (window.isVisible() and not window.isMinimized()):
            return
        tray_icon = window.findChild(QSystemTrayIcon)
        if tray_icon is None or not tray_icon.isVisible() or not QSystemTrayIcon.supportsMessages():
            return
        self._waiting += 1
        now = monotonic()
        if now - self._last < TRAY_MESSAGE_INTERVAL:
            return
        text = entry["text"] if self._waiting == 1 else trm(f"{self._waiting} new messages, last one: {entry['text']}")
        self._last, self._waiting = now, 0
        show_app = getattr(window, "show_app", None)
        if callable(show_app):
            tray_icon.messageClicked.connect(show_app, Qt.ConnectionType.UniqueConnection)
        icon = (QSystemTrayIcon.MessageIcon.Critical if entry["severity"] == "error"
                else QSystemTrayIcon.MessageIcon.Warning)
        tray_icon.showMessage(APP_NAME, text, icon, 10000)


def open_notification_center(window: QWidget, anchor: QWidget):
    """Notification center popup next to anchor (bell of the rail)"""
    from .quick.notify_backend import NotificationCenter

    NotificationCenter.open_at(window, anchor)
