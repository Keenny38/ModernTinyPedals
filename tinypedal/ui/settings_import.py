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
Settings imported from TinyPedal: keep them, or start with default settings, import again

Folder changes are applied on next start, before settings are loaded (see
userfile/folder_migration.py): a running app would save its settings over them.
"""

from __future__ import annotations

import logging
import os

from PySide6.QtWidgets import QMessageBox, QWidget

from .. import loader
from ..i18n import tr
from ..setting import cfg
from ..userfile import folder_migration as fm

logger = logging.getLogger(__name__)


def import_pending() -> bool:
    """Settings copied from TinyPedal, user not asked yet"""
    return fm.read_state(cfg.path.config).get("state") == fm.STATE_PENDING


def ask_imported_settings(parent: QWidget | None) -> None:
    """Ask once whether to keep imported settings (default settings: app restarts)"""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(tr("Settings Imported from TinyPedal"))
    box.setText(tr(
        "Your TinyPedal settings were copied to NeoPedal: options, shortcuts, driver stats, "
        "language packs and Black box incidents. TinyPedal keeps its own settings, unchanged.\n\n"
        "Keep these settings, or start NeoPedal with default settings? Imported settings "
        "are then set aside in a backup folder, never deleted."
    ))
    button_keep = box.addButton(tr("Keep Imported Settings"), QMessageBox.ButtonRole.AcceptRole)
    button_default = box.addButton(tr("Use Default Settings"), QMessageBox.ButtonRole.DestructiveRole)
    box.setDefaultButton(button_keep)
    box.setEscapeButton(button_keep)  # closed: nothing changes
    box.exec()
    if box.clickedButton() is button_default:
        logger.info("MIGRATION: default settings chosen")
        request_and_restart(parent, fm.STATE_RESET)
        return
    fm.write_state(cfg.path.config, fm.STATE_KEPT)
    logger.info("MIGRATION: imported settings kept")


def confirm_change(parent: QWidget | None, state: str) -> None:
    """Ask before default settings or new copy (menu), then restart"""
    if state == fm.STATE_REIMPORT:
        text = tr(
            "Import settings from TinyPedal again?\n\n"
            "Current NeoPedal settings are set aside in a backup folder, then NeoPedal "
            "restarts with a new copy of TinyPedal settings."
        )
    else:
        text = tr(
            "Start with default settings?\n\n"
            "Current NeoPedal settings are set aside in a backup folder, then NeoPedal "
            "restarts with default settings."
        )
    answer = QMessageBox.question(
        parent, tr("TinyPedal Settings"), text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    if answer == QMessageBox.StandardButton.Yes:
        request_and_restart(parent, state)


def request_and_restart(parent: QWidget | None, state: str) -> None:
    """Save request, then restart: applied before settings are loaded"""
    if not fm.request_change(cfg.path.config, state):
        message = (tr("TinyPedal settings folder not found.") if state == fm.STATE_REIMPORT
                   else tr("Request not saved, see log."))
        QMessageBox.warning(parent, tr("TinyPedal Settings"), message)
        return
    restart_app = getattr(parent, "restart_app", None)
    if callable(restart_app):
        restart_app()
    else:
        loader.restart()
    # Only reached if restart was cancelled (unsaved page) or failed: request kept for next start
    QMessageBox.information(parent, tr("TinyPedal Settings"), tr("Applied at next start of NeoPedal."))


def legacy_folder_found() -> bool:
    """TinyPedal settings folder exists (import again possible)"""
    return os.path.isdir(fm.legacy_config_folder())
