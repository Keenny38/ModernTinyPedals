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
Import global settings from a folder chosen by user (Config menu)

Applied on next start, before settings are loaded (see userfile/settings_import.py): the app
asks, saves the request, then restarts.
"""

from __future__ import annotations

import os

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from .. import loader
from ..const_app import PLATFORM
from ..i18n import tr
from ..setting import cfg
from ..userfile import settings_import


def start_folder() -> str:
    """Folder shown first: where apps keep their settings folders"""
    if PLATFORM.WINDOWS:
        return os.getenv("APPDATA", os.path.expanduser("~"))
    return os.getenv("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")


def import_settings(parent: QWidget | None) -> None:
    """Choose a settings folder, confirm, then restart to import it"""
    source = QFileDialog.getExistingDirectory(parent, tr("Import Settings..."), start_folder())
    if not source:
        return
    if not settings_import.is_settings_folder(source, cfg.path.config):
        QMessageBox.warning(parent, tr("Import Settings"), tr(
            "This folder has no global settings (config.json or shortcuts.json).\n\n"
            "Choose the global settings folder of the other copy of the app, "
            "for example in %APPDATA% on Windows or ~/.config on Linux."))
        return
    answer = QMessageBox.question(
        parent, tr("Import Settings"),
        tr("Import settings from this folder?") + f"\n{os.path.normpath(source)}\n\n" + tr(
            "Options, shortcuts, driver stats, language packs and Dashboard HUD incidents are copied, "
            "the folder is not changed. Current settings are set aside in a backup folder (never "
            "deleted), then the app restarts with the imported settings."),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return
    if not settings_import.request_import(cfg.path.config, source):
        QMessageBox.warning(parent, tr("Import Settings"), tr("Request not saved, see log."))
        return
    restart_app = getattr(parent, "restart_app", None)
    if callable(restart_app):
        restart_app()
    else:
        loader.restart()
    # Only reached if restart was cancelled (unsaved page) or failed: request kept for next start
    QMessageBox.information(parent, tr("Import Settings"), tr("Applied at next start of NeoPedal."))
