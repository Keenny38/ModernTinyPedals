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
Tools page: utilities & editors as tiles, opening tools by path
"""

import logging
from importlib import import_module

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..template.page_registry import tool_pages, tool_sections
from . import draw_focus_ring
from ._common import find_dialog_host

logger = logging.getLogger(__name__)

# Sections: (title, ((label, icon glyph in Segoe Fluent Icons / MDL2 Assets, "module.DialogClass"), ...)),
# see template.page_registry.PAGES. Dialog modules are imported when first opened, to keep startup light
TOOL_SECTIONS = tool_sections()
# Tools of Tools page & Tools menu (Settings left out: own menu, gear button of the rail & Ctrl+,)
LISTED_TOOL_SECTIONS = tool_sections(listed_only=True)


# Former tools merged into another one: old path (saved open pages, navigation bar) -> new path
RENAMED_TOOLS = {
    "fuel_calculator.FuelCalculator": "race_calculator.RaceCalculator",
    "tyre_strategy_planner.TyreStrategyPlanner": "race_calculator.RaceCalculator",
    "game_replays.GameReplays": "race_results_viewer.RaceResultsViewer",  # replays list of results & replays
}
SHOW_REPLAYS = "game_replays.GameReplays"  # former path: replays list shown
# Former Preset Comparison tool: compare panel of the Presets page (path kept: palette, saved pages & shortcuts)
SHOW_PRESET_COMPARE = "preset_compare.PresetCompare"
RENAMED_TOOL_KEYS = {old.split(".", 1)[0]: new.split(".", 1)[0] for old, new in RENAMED_TOOLS.items()}
RENAMED_TOOL_KEYS["preset_compare"] = "preset"  # navigation bar & quick access entry: Presets page
PAGE_PATH = "page:"  # "page:<key>" path of a main window page (Pages section of the Tools page)
# Extra words finding a tool in command palette (former names, what it covers), both languages
TOOL_KEYWORDS = {page.dialog: page.keywords for page in tool_pages() if page.keywords}


def open_tool(dialog_path: str, parent):
    """Open tool dialog from "module.DialogClass" path relative to ui package, opened dialog returned

    Returns:
        Dialog shown (already open one brought to front), None if unable to open.
    """
    if dialog_path == SHOW_REPLAYS:
        dialog = open_tool(RENAMED_TOOLS[dialog_path], parent)
        show_replays = getattr(dialog, "show_replays", None)
        if callable(show_replays):
            show_replays()
        return dialog
    if dialog_path == SHOW_PRESET_COMPARE:
        return show_preset_compare(parent)
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
        from .quick import dialogs

        dialogs.alert(parent, tr("Error"), tr("Unable to open tool, see log for details."))
        return None
    _dialog = dialog_class(parent)
    _dialog.show()
    return _dialog


def show_preset_compare(parent):
    """Presets page shown with its compare panel open (loaded preset with another one), the page returned, None if
    no main window"""
    from .nav_rail import PAGE_INDEX
    from .preset_view import PresetList

    host = find_dialog_host(parent)
    if host is None:
        return None
    host.select_page(PAGE_INDEX["preset"])
    page = host.window().findChild(PresetList)
    if page is None or page.ensure_view() is None:
        return None
    QTimer.singleShot(0, page, lambda: page.backend.openPage("compare"))  # once the page is shown & laid out
    return page


def open_page_or_tool(path: str, parent):
    """Open "page:<key>" main window page (Pages section of the Tools page), else tool by dialog path"""
    if not path.startswith(PAGE_PATH):
        return open_tool(path, parent)
    from .nav_rail import PAGE_INDEX

    host = find_dialog_host(parent)
    index = PAGE_INDEX.get(path.removeprefix(PAGE_PATH), -1)
    if host is not None and index >= 0:
        host.select_page(index)
    return None


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
        draw_focus_ring(painter, self, area, radius)
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
    """Tools page: Qt Quick page (qml/shell/Tools.qml), tiles of listed tools by section with what each is for,
    live state of tools with an on / off switch, search; state & actions in quick/shell_tools_backend.py"""

    def __init__(self, parent, icon_family: str = "", dialog_parent=None):
        from .quick import create_quick_view
        from .quick.shell_tools_backend import ToolsBackend

        super().__init__(parent)
        dialog_parent = dialog_parent or parent
        self.backend = ToolsBackend(self, lambda path: open_page_or_tool(path, dialog_parent))
        self.view = create_quick_view(self, "Tools.qml", {"backend": self.backend})
        layout_main = QVBoxLayout(self)
        layout_main.setContentsMargins(0, 0, 0, 0)
        layout_main.addWidget(self.view)
        self.setFocusProxy(self.view)

    def set_statuses(self, statuses: dict[str, str]):
        """Live state of tools with an on / off switch (dialog class name: "on", "off", "" closed), each second"""
        self.backend.set_statuses(statuses)

    def refresh(self):
        """Navigation bar entries may have changed (tiles mark tools of the bar)"""
        self.backend.refresh()
