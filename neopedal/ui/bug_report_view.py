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
Bug report dialog
"""

import logging
import os

from PySide6.QtCore import QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QVBoxLayout

from ..bug_report import create_bug_report, default_report_filename, snapshot_report
from ..i18n import tr, trm
from ._common import BaseDialog, CompactButton, UIScaler, singleton_dialog

logger = logging.getLogger(__name__)


@singleton_dialog("bug_report")
class BugReport(BaseDialog):
    """Create bug report zip"""

    def __init__(self, parent):
        from .quick.background import BackgroundJobs  # Qt Quick package imported when used

        super().__init__(parent)
        self.set_utility_title(tr("Create Bug Report"))
        self._jobs = BackgroundJobs(self, "Bug report")
        self._report_filename = ""
        info = QLabel(tr(
            "Creates a zip file with logs, settings and system info, to attach to a bug report.\n"
            "Your user folder name, access codes and repository names are removed."
        ))
        info.setWordWrap(True)
        self.edit_description = QPlainTextEdit(self)
        self.edit_description.setPlaceholderText(tr("Describe the problem: what you did, what happened, what you expected."))
        self.edit_description.setMinimumSize(UIScaler.size(30), UIScaler.size(10))

        self.button_save = button_save = CompactButton(tr("Save Report..."))
        button_save.clicked.connect(self.save_report)
        button_close = CompactButton(tr("Close"))
        button_close.clicked.connect(self.reject)
        layout_button = QHBoxLayout()
        layout_button.addStretch(1)
        layout_button.addWidget(button_save)
        layout_button.addWidget(button_close)

        layout = QVBoxLayout()
        layout.addWidget(info)
        layout.addWidget(self.edit_description, stretch=1)
        layout.addLayout(layout_button)
        layout.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        self.setLayout(layout)

    def is_saving(self) -> bool:
        """Report zip being written in background"""
        return self._jobs.is_busy("report")

    def save_report(self):
        if self.is_saving():
            return
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        filename, _ = QFileDialog.getSaveFileName(
            self, tr("Save Report..."), os.path.join(folder, default_report_filename()), "Zip (*.zip)"
        )
        if not filename:
            return
        from ..main import log_stream

        # App state taken here, logs read & zip written in background (button disabled meanwhile)
        snapshot = snapshot_report()
        session_log = log_stream.getvalue()
        description = self.edit_description.toPlainText()
        self._report_filename = filename
        self.button_save.setEnabled(False)
        self.setCursor(Qt.CursorShape.BusyCursor)
        self._jobs.run(
            "write report", lambda: create_bug_report(filename, session_log, description, snapshot),
            self.report_saved, self.report_failed, key="report")

    def report_failed(self, error: BaseException):
        self.button_save.setEnabled(True)
        self.unsetCursor()
        if not isinstance(error, OSError):
            logger.error("BUG REPORT: failed", exc_info=(type(error), error, error.__traceback__))
        QMessageBox.warning(self, tr("Error"), trm(f"Unable to create bug report:<br>{error}"))

    def report_saved(self, files: list[str]):
        self.button_save.setEnabled(True)
        self.unsetCursor()
        filename = self._report_filename
        if not self.isVisible():  # closed meanwhile: report saved (logged), nothing to ask
            return
        answer = QMessageBox.question(
            self, tr("Create Bug Report"),
            trm(f"Bug report saved ({len(files)} files):<br><b>{filename}</b><br><br>Open folder?"),
        )
        if answer == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(filename)))
        self.accept()
