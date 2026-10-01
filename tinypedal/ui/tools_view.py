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

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPalette
from PySide6.QtWidgets import QAbstractButton, QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..i18n import tr
from ._common import UIScaler
from .brake_editor import BrakeEditor
from .driver_stats_viewer import DriverStatsViewer
from .fuel_calculator import FuelCalculator
from .heatmap_editor import HeatmapEditor
from .lap_viewer import LapViewer
from .layout_editor import LayoutEditor
from .perf_view import PerformanceView
from .plugin_manager import PluginManager
from .preset_compare import PresetCompare
from .replay_view import ReplayView
from .theme_editor import ThemeEditor
from .track_info_editor import TrackInfoEditor
from .track_map_viewer import TrackMapViewer
from .track_notes_editor import TrackNotesEditor
from .tyre_compound_editor import TyreCompoundEditor
from .tyre_strategy_planner import TyreStrategyPlanner
from .vehicle_brand_editor import VehicleBrandEditor
from .vehicle_class_editor import VehicleClassEditor

# Sections: (title, ((label, icon glyph in Segoe Fluent Icons / MDL2 Assets, dialog class), ...))
TOOL_SECTIONS = (
    ("Utilities", (
        ("Fuel Calculator", "", FuelCalculator),  # calculator
        ("Tyre Strategy Planner", "", TyreStrategyPlanner),  # flag
        ("Driver Stats Viewer", "", DriverStatsViewer),  # contact
        ("Track Map Viewer", "", TrackMapViewer),  # map pin
        ("Lap Telemetry Viewer", "", LapViewer),  # area chart
        ("Telemetry Replay", "", ReplayView),  # play
    )),
    ("Editors", (
        ("Heatmap Editor", "", HeatmapEditor),  # color
        ("Brake Editor", "", BrakeEditor),  # edit
        ("Tyre Compound Editor", "", TyreCompoundEditor),  # edit
        ("Vehicle Brand Editor", "", VehicleBrandEditor),  # tag
        ("Vehicle Class Editor", "", VehicleClassEditor),  # car
        ("Track Info Editor", "", TrackInfoEditor),  # info
        ("Track Notes Editor", "", TrackNotesEditor),  # quick note
        ("Layout Editor", "", LayoutEditor),  # view all
        ("Overlay Theme Editor", "", ThemeEditor),  # personalize
    )),
    ("Management", (
        ("Preset Comparison", "", PresetCompare),  # switch
        ("Plugin Manager", "", PluginManager),  # puzzle
        ("Widget Performance", "", PerformanceView),  # speed
    )),
)


def open_tool(dialog_class, parent):
    """Open tool dialog"""
    _dialog = dialog_class(parent)
    _dialog.show()


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
            for index, (label, glyph, dialog_class) in enumerate(tools):
                card = ToolCard(tr(label), glyph, icon_family, content)
                card.clicked.connect(lambda _=False, cls=dialog_class: open_tool(cls, dialog_parent))
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
