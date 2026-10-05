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
Tools page: utilities & editors as a grid of cards
"""

import logging
from importlib import import_module

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QGridLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ._common import UIScaler, find_dialog_host

logger = logging.getLogger(__name__)

# Sections: (title, ((label, icon glyph in Segoe Fluent Icons / MDL2 Assets, "module.DialogClass"), ...))
# Dialog modules are imported when first opened, to keep startup light
TOOL_SECTIONS = (
    ("Utilities", (
        ("Race Calculator", "\ue8ef", "race_calculator.RaceCalculator"),  # calculator
        ("Driver Stats Viewer", "\ue77b", "driver_stats_viewer.DriverStatsViewer"),  # contact
        ("Track Map Viewer", "\ue707", "track_map_viewer.TrackMapViewer"),  # map pin
        ("Lap Telemetry Viewer", "\ue9d2", "lap_viewer.LapViewer"),  # area chart
        ("Telemetry Replay", "\ue768", "replay_view.ReplayView"),  # play
        ("Game Replays", "\ue714", "game_replays.GameReplays"),  # video
    )),
    ("Editors", (
        ("Heatmap Editor", "\ue790", "heatmap_editor.HeatmapEditor"),  # color
        ("Brake Editor", "\ue70f", "brake_editor.BrakeEditor"),  # edit
        ("Tyre Compound Editor", "\ue70f", "tyre_compound_editor.TyreCompoundEditor"),  # edit
        ("Vehicle Brand Editor", "\ue8ec", "vehicle_brand_editor.VehicleBrandEditor"),  # tag
        ("Vehicle Class Editor", "\ue804", "vehicle_class_editor.VehicleClassEditor"),  # car
        ("Track Info Editor", "\ue946", "track_info_editor.TrackInfoEditor"),  # info
        ("Track Notes Editor", "\ue70b", "track_notes_editor.TrackNotesEditor"),  # quick note
        ("Layout Editor", "\ue8a9", "layout_editor.LayoutEditor"),  # view all
        ("Overlay Theme Editor", "\ue771", "theme_editor.ThemeEditor"),  # personalize
    )),
    ("Management", (
        ("Preset Comparison", "\ue8ab", "preset_compare.PresetCompare"),  # switch
        ("Plugin Manager", "\uea86", "plugin_manager.PluginManager"),  # puzzle
        ("Widget Performance", "\uec4a", "perf_view.PerformanceView"),  # speed
    )),
)


# Former tools merged into another one: old path (saved open pages, navigation bar) -> new path
RENAMED_TOOLS = {
    "fuel_calculator.FuelCalculator": "race_calculator.RaceCalculator",
    "tyre_strategy_planner.TyreStrategyPlanner": "race_calculator.RaceCalculator",
}
RENAMED_TOOL_KEYS = {old.split(".", 1)[0]: new.split(".", 1)[0] for old, new in RENAMED_TOOLS.items()}
# Extra words finding a tool in command palette (former names, what it covers), both languages
TOOL_KEYWORDS = {
    "game_replays.GameReplays": (
        "lmu replay incident contact crash watch rediffusion incidents contacts accrochage revoir"
    ),
    "race_calculator.RaceCalculator": (
        "fuel calculator tyre tire strategy planner energy pit stop stint "
        "carburant calculateur pneus strategie energie arret relais"
    ),
}


def open_tool(dialog_path: str, parent):
    """Open tool dialog from "module.DialogClass" path relative to ui package, opened dialog returned

    Returns:
        Dialog shown (already open one brought to front), None if unable to open.
    """
    dialog_path = RENAMED_TOOLS.get(dialog_path, dialog_path)
    module_name, class_name = dialog_path.rsplit(".", 1)
    host = find_dialog_host(parent)
    if host is not None and host.activate_dialog_page(class_name):  # already open as page in app
        return next((page.dialog for page in host.dialog_pages()
                     if page.dialog is not None and type(page.dialog).__name__ == class_name), None)
    for widget in QApplication.topLevelWidgets():  # already open: bring to front instead of warning
        if type(widget).__name__ == class_name and widget.isVisible():
            if widget.isMinimized():
                widget.showNormal()
            widget.raise_()
            widget.activateWindow()
            return widget
    try:
        dialog_class = getattr(import_module(f"{__package__}.{module_name}"), class_name)
    except (ImportError, AttributeError):  # slot exceptions are silent in the windowed build
        logger.exception("TOOLS: unable to open %s", dialog_path)
        QMessageBox.warning(parent, tr("Error"), tr("Unable to open tool, see log for details."))
        return None
    _dialog = dialog_class(parent)
    _dialog.show()
    return _dialog


class ToolCard(QAbstractButton):
    """Tool entry: icon then label, outlined card highlighted on hover"""

    def __init__(self, text: str, glyph: str, icon_family: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setToolTip(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.glyph = glyph if icon_family else text[:1]
        self.icon_font = QFont(icon_family) if icon_family else QFont(self.font())
        if not icon_family:
            self.icon_font.setBold(True)

    def sizeHint(self) -> QSize:
        line = self.fontMetrics().height()
        return QSize(round(line * 11), round(line * 2.6))

    def minimumSizeHint(self) -> QSize:
        line = self.fontMetrics().height()
        return QSize(round(line * 6), round(line * 2.6))

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = self.palette()
        accent = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight)
        text = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.WindowText)
        border = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Mid)
        area = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        radius = area.height() * 0.2
        hover = self.underMouse()
        fill = QColor(accent if hover else text)
        fill.setAlphaF(0.12 if hover else 0.04)
        painter.setPen(accent if hover else border)
        painter.setBrush(fill)
        painter.drawRoundedRect(area, radius, radius)
        # Icon
        icon_size = area.height()
        icon_font = QFont(self.icon_font)
        icon_font.setPixelSize(round(icon_size * 0.38))
        painter.setFont(icon_font)
        painter.setPen(accent)
        painter.drawText(QRectF(area.left(), area.top(), icon_size, icon_size), Qt.AlignmentFlag.AlignCenter, self.glyph)
        # Label
        painter.setFont(self.font())
        painter.setPen(text)
        label_rect = QRectF(area.left() + icon_size, area.top(), area.width() - icon_size * 1.2, area.height())
        label = QFontMetricsF(self.font()).elidedText(self.text(), Qt.TextElideMode.ElideRight, label_rect.width())
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)


class ToolsView(QWidget):
    """Tools page"""

    def __init__(self, parent, icon_family: str, dialog_parent=None):
        super().__init__(parent)
        dialog_parent = dialog_parent or parent
        content = QWidget(self)
        content.setObjectName("pageStack")
        layout_content = QVBoxLayout(content)
        margin = UIScaler.pixel(10)
        layout_content.setContentsMargins(margin, margin, margin, margin)
        layout_content.setSpacing(UIScaler.pixel(6))

        for title, tools in TOOL_SECTIONS:
            header = QLabel(tr(title), content)
            header_font = header.font()
            header_font.setBold(True)
            header.setFont(header_font)
            layout_content.addWidget(header)
            grid = QGridLayout()
            grid.setSpacing(UIScaler.pixel(6))
            for index, (label, glyph, dialog_path) in enumerate(tools):
                card = ToolCard(tr(label), glyph, icon_family, content)
                card.clicked.connect(lambda _=False, path=dialog_path: open_tool(path, dialog_parent))
                grid.addWidget(card, index // 2, index % 2)
            layout_content.addLayout(grid)
            layout_content.addSpacing(UIScaler.pixel(4))
        layout_content.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        layout_main = QVBoxLayout(self)
        layout_main.setContentsMargins(0, 0, 0, 0)
        layout_main.addWidget(scroll)

    def refresh(self):
        """Nothing to refresh, kept for page interface"""
