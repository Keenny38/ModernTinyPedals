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
Log window
"""

from PySide6.QtCore import QBasicTimer
from PySide6.QtGui import QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QTextBrowser,
    QVBoxLayout,
)

from ..const_file import FileFilter
from ..i18n import tr, trm
from ..main import log_stream
from ._common import BaseDialog, CompactButton, UIScaler, singleton_dialog, translate_filter
from .toast import show_toast


@singleton_dialog("log", show_error=False)
class LogInfo(BaseDialog):
    """Create log info dialog"""

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Log"))

        self._update_timer = QBasicTimer()
        # Timer is not unregistered if widget is deleted by parent while Python object lives on
        self.destroyed.connect(self._update_timer.stop)
        self.last_text = ""  # log shown, see timerEvent

        # Text view
        self.log_view = QTextBrowser(self)
        self.log_view.setMinimumSize(UIScaler.size(42), UIScaler.size(22))
        self.log_view.setWordWrapMode(QTextOption.WrapMode.NoWrap)
        self.refresh_log()

        # Check box
        checkbox_autorefresh = QCheckBox(tr("Auto Refresh"))
        checkbox_autorefresh.setChecked(False)
        checkbox_autorefresh.toggled.connect(self.toggle_auto_refresh)

        # Button
        button_save = CompactButton(tr("Save"))
        button_save.clicked.connect(self.save_log)

        button_copy = CompactButton(tr("Copy"))
        button_copy.clicked.connect(self.copy_log)

        button_clear = CompactButton(tr("Clear"))
        button_clear.clicked.connect(self.clear_log)

        self.button_refresh = CompactButton(tr("Refresh"))
        self.button_refresh.clicked.connect(self.refresh_log)

        button_close = CompactButton(tr("Close"))
        button_close.clicked.connect(self.reject)

        # Layout
        layout_button = QHBoxLayout()
        layout_button.addWidget(button_save)
        layout_button.addWidget(button_copy)
        layout_button.addWidget(button_clear)
        layout_button.addWidget(self.button_refresh)
        layout_button.addWidget(checkbox_autorefresh)
        layout_button.addStretch(1)
        layout_button.addWidget(button_close)

        layout_main = QVBoxLayout()
        layout_main.addWidget(self.log_view)
        layout_main.addLayout(layout_button)
        layout_main.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        self.setLayout(layout_main)

    def timerEvent(self, event):
        """Refresh log"""
        if not self.isVisible():  # hidden page (other page shown) or window: nothing to refresh
            return
        if self.last_text != log_stream.getvalue():
            self.refresh_log()

    def toggle_auto_refresh(self, checked: bool):
        """Toggle auto refresh"""
        if checked:
            self._update_timer.start(200, self)
            self.button_refresh.setDisabled(True)
        else:
            self._update_timer.stop()
            self.button_refresh.setDisabled(False)

    def refresh_log(self):
        """Refresh log"""
        self.last_text = log_stream.getvalue()
        self.log_view.setPlainText(self.last_text)
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)

    def clear_log(self):
        """Clear log"""
        if self.confirm_operation(message=tr("Clear all log?")):
            log_stream.truncate(0)
            log_stream.seek(0)
            self.refresh_log()

    def copy_log(self):
        """Copy log"""
        self.log_view.selectAll()
        self.log_view.copy()
        show_toast(self, tr("Copied all log to Clipboard."))

    def save_log(self):
        """Save log"""
        filename_full = QFileDialog.getSaveFileName(
            self,
            dir="log",
            filter=translate_filter(";;".join((FileFilter.TXT, FileFilter.LOG, FileFilter.ALL))),
        )[0]
        if not filename_full:
            return
        # Copy of log text: log stream itself is never moved (new lines keep being appended)
        try:
            with open(filename_full, "w", newline="", encoding="utf-8") as log_file:
                log_file.write(log_stream.getvalue())
        except OSError as error:
            QMessageBox.warning(self, tr("Error"), trm(f"Unable to save log: {error}"))
