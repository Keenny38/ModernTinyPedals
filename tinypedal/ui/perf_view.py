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

from ..i18n import tr, trm
from ..i18n.options import module_label
from ..perf_monitor import PerfMonitor, ProcessMonitor, connection_health, endpoint_rows
from ._common import BaseDialog, CompactButton, UIScaler, singleton_dialog

HEADER = ("Widget", "Event", "Calls/s", "Avg (ms)", "Max (ms)", "Total (ms)")
THREAD_HEADER = ("Thread", "CPU %", "CPU time (s)")
REST_HEADER = ("Rest API resource", "Status", "Last answer (s ago)", "Last error")
# Rest API resource state & error (see adapter.restapi_connector.EndpointStatus): display text
REST_STATES = {
    "idle": "Not on track",
    "disabled": "Disabled",
    "waiting": "Connecting",
    "active": "Receiving data",
    "missing": "No data yet",
    "dead": "Stopped after error",
}
REST_ERRORS = {
    "timeout": "Timeout",
    "connection failed": "Connection failed",
    "no answer": "No answer",
    "invalid answer": "Invalid answer",
    "invalid JSON": "Invalid JSON",
    "no data": "No data (null)",
    "parser error": "Unreadable data",
    "unexpected error": "Unexpected error",
}


def shared_memory_status() -> str:
    """Shared memory connection state text"""
    health = connection_health()
    if health is None:
        return tr("API not connected")
    if health.error:
        return trm(f"Shared memory unavailable: {health.error}")
    if health.data_age < 0:
        return tr("Shared memory: no data yet")
    if health.replaying:
        return trm(f"Replay: last frame change {health.data_age:.1f} s ago")
    if health.paused:
        return trm(f"Shared memory: paused, last update {health.data_age:.1f} s ago")
    return trm(f"Shared memory: last update {health.data_age:.1f} s ago")


@singleton_dialog("performance", show_error=False)
class PerformanceView(BaseDialog):
    """Show update & paint time of each widget, to find expensive widgets"""

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Widget Performance"))
        self._update_timer = QBasicTimer()
        self.destroyed.connect(self._update_timer.stop)  # page deleted without close (language change)

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

        # Game data connection (shared memory, Rest API)
        self.label_connection = QLabel(self)
        self.label_connection.setWordWrap(True)
        self.table_rest = QTableWidget(0, len(REST_HEADER), self)
        self.table_rest.setHorizontalHeaderLabels([tr(text) for text in REST_HEADER])
        self.table_rest.verticalHeader().setVisible(False)
        self.table_rest.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_rest.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tab_connection = QWidget(self)
        layout_connection = QVBoxLayout(tab_connection)
        layout_connection.setContentsMargins(0, 0, 0, 0)
        layout_connection.addWidget(self.label_connection)
        layout_connection.addWidget(self.table_rest)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(tab_widgets, tr("Widgets"))
        self.tabs.addTab(tab_threads, tr("App & modules"))
        self.tabs.addTab(tab_connection, tr("Game data"))

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
        if not self.isVisible():  # hidden page (other page shown) or window: nothing to refresh
            return
        self.refresh()

    def refresh(self):
        """Refresh tables"""
        self.refresh_widgets()
        self.refresh_threads()
        self.refresh_connection()

    def refresh_connection(self):
        """Refresh game data connection state: shared memory update age, Rest API resources"""
        self.label_connection.setText(shared_memory_status())
        health = connection_health()
        rows = endpoint_rows(health) if health is not None else []
        if health is not None and health.replaying:
            self.label_connection.setText(
                f"{self.label_connection.text()}\n{tr('Rest API data read from replay file.')}")
        self.table_rest.setRowCount(len(rows))
        for row, item in enumerate(rows):
            values = (
                item.path,
                tr(REST_STATES.get(item.state, item.state)),
                round(item.age, 1) if item.age >= 0 else "-",
                tr(REST_ERRORS.get(item.error, item.error)),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem()
                cell.setData(Qt.ItemDataRole.DisplayRole, value)
                self.table_rest.setItem(row, column, cell)

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
                module_label(item.name),
                tr(item.event),
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
