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
Widget performance view
"""

from PySide6.QtCore import QBasicTimer, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..formatter import format_module_name
from ..i18n import tr, trm
from ..perf_monitor import PerfMonitor, ProcessMonitor
from ._common import BaseDialog, CompactButton, UIScaler, singleton_dialog

HEADER = ("Widget", "Event", "Calls/s", "Avg (ms)", "Max (ms)", "Total (ms)")
THREAD_HEADER = ("Thread", "CPU %", "CPU time (s)")


@singleton_dialog("performance", show_error=False)
class PerformanceView(BaseDialog):
    """Show update & paint time of each widget, to find expensive widgets"""

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Widget Performance"))
        self._update_timer = QBasicTimer()

        self.table = QTableWidget(0, len(HEADER), self)
        self.table.setHorizontalHeaderLabels([tr(text) for text in HEADER])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumSize(UIScaler.size(40), UIScaler.size(24))

        self.label_info = QLabel(self)

        # App & modules (threads)
        self.process_monitor = ProcessMonitor()
        self.label_process = QLabel(self)
        self.table_threads = QTableWidget(0, len(THREAD_HEADER), self)
        self.table_threads.setHorizontalHeaderLabels([tr(text) for text in THREAD_HEADER])
        self.table_threads.verticalHeader().setVisible(False)
        self.table_threads.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_threads.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tab_threads = QWidget(self)
        layout_threads = QVBoxLayout(tab_threads)
        layout_threads.setContentsMargins(0, 0, 0, 0)
        layout_threads.addWidget(self.label_process)
        layout_threads.addWidget(self.table_threads)

        tab_widgets = QWidget(self)
        layout_widgets = QVBoxLayout(tab_widgets)
        layout_widgets.setContentsMargins(0, 0, 0, 0)
        layout_widgets.addWidget(self.table)
        layout_widgets.addWidget(self.label_info)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(tab_widgets, tr("Widgets"))
        self.tabs.addTab(tab_threads, tr("App & modules"))

        checkbox_enable = QCheckBox(tr("Enable Monitoring"))
        checkbox_enable.setChecked(PerfMonitor.enabled)
        checkbox_enable.toggled.connect(self.toggle_monitor)

        button_reset = CompactButton(tr("Reset"))
        button_reset.clicked.connect(self.reset_data)

        button_close = CompactButton(tr("Close"))
        button_close.clicked.connect(self.reject)

        layout_button = QHBoxLayout()
        layout_button.addWidget(checkbox_enable)
        layout_button.addWidget(button_reset)
        layout_button.addStretch(1)
        layout_button.addWidget(button_close)

        layout_main = QVBoxLayout()
        layout_main.addWidget(self.tabs)
        layout_main.addLayout(layout_button)
        layout_main.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        self.setLayout(layout_main)

        self.refresh()
        self._update_timer.start(1000, self)

    def toggle_monitor(self, checked: bool):
        """Enable or disable monitoring"""
        PerfMonitor.set_enabled(checked)
        self.refresh()

    def reset_data(self):
        """Reset recorded data"""
        PerfMonitor.reset()
        self.refresh()

    def timerEvent(self, event):
        """Auto refresh"""
        self.refresh()

    def refresh(self):
        """Refresh tables"""
        self.refresh_widgets()
        self.refresh_threads()

    def refresh_threads(self):
        """Refresh app & thread CPU usage"""
        process, threads = self.process_monitor.sample()
        self.label_process.setText(trm(
            f"App: CPU {process.cpu_percent:.1f}%   Memory {process.memory_mb:.0f} MB   Threads {process.threads}"
        ))
        self.table_threads.setRowCount(len(threads))
        for row, item in enumerate(threads):
            for column, value in enumerate((item.name, round(item.cpu_percent, 1), round(item.cpu_seconds, 1))):
                cell = QTableWidgetItem()
                cell.setData(Qt.ItemDataRole.DisplayRole, value)
                self.table_threads.setItem(row, column, cell)

    def refresh_widgets(self):
        """Refresh widget table"""
        stats = PerfMonitor.stats()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(stats))
        for row, item in enumerate(stats):
            values = (
                format_module_name(item.name),
                item.event,
                round(item.rate, 1),
                round(item.average, 3),
                round(item.maximum, 3),
                round(item.total, 1),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem()
                cell.setData(Qt.ItemDataRole.DisplayRole, value)
                self.table.setItem(row, column, cell)
        self.table.setSortingEnabled(True)
        if not PerfMonitor.enabled:
            self.label_info.setText(tr("Monitoring is disabled. Enable it, then drive a few laps."))
        else:
            total = sum(item.total for item in stats)
            self.label_info.setText(trm(f"Total recorded time: {total:.1f} ms"))

    def closeEvent(self, event):
        """Stop refresh on close"""
        self._update_timer.stop()
        super().closeEvent(event)
