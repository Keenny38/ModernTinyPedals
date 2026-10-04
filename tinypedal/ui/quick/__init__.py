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
Qt Quick (QML) pages hosted inside widget dialogs

QML files are in ui/qml, Python items (GPU drawn lines) registered as "TinyPedal" QML module.
"""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication, QPalette, QSurfaceFormat
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication, QWidget

from ...i18n import tr, trm
from .. import UIScaler

logger = logging.getLogger(__name__)

QML_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "qml")
MSAA_SAMPLES = 4  # smooth chart lines
_registered = False


def register_types():
    """Register Python QML types & controls style once, before first QML page is loaded"""
    global _registered
    if _registered:
        return
    from PySide6.QtQuickControls2 import QQuickStyle

    from .lines import register_line_types

    # Basic style follows palette & is fully restyled in QML (Fusion & native styles ignore theme)
    QQuickStyle.setStyle("Basic")
    register_line_types()
    _registered = True


class Theme(QObject):
    """App palette & sizes for QML, updated when app theme changes"""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        app = QApplication.instance()
        if isinstance(app, QGuiApplication):
            app.paletteChanged.connect(self.changed)

    @staticmethod
    def _color(role: QPalette.ColorRole, group=QPalette.ColorGroup.Active) -> QColor:
        return QApplication.palette().color(group, role)

    @Property(bool, notify=changed)
    def dark(self) -> bool:
        return self._color(QPalette.ColorRole.Window).lightness() < 128

    @Property(QColor, notify=changed)
    def window(self) -> QColor:
        return self._color(QPalette.ColorRole.Window)

    @Property(QColor, notify=changed)
    def base(self) -> QColor:
        return self._color(QPalette.ColorRole.Base)

    @Property(QColor, notify=changed)
    def alternate(self) -> QColor:
        return self._color(QPalette.ColorRole.AlternateBase)

    @Property(QColor, notify=changed)
    def text(self) -> QColor:
        return self._color(QPalette.ColorRole.Text)

    @Property(QColor, notify=changed)
    def dimText(self) -> QColor:
        return self._color(QPalette.ColorRole.PlaceholderText)

    @Property(QColor, notify=changed)
    def accent(self) -> QColor:
        return self._color(QPalette.ColorRole.Highlight)

    @Property(QColor, notify=changed)
    def border(self) -> QColor:
        return self._color(QPalette.ColorRole.Mid)

    @Property(QColor, notify=changed)
    def raised(self) -> QColor:
        return self._color(QPalette.ColorRole.Button)

    @Property(QColor, notify=changed)
    def hover(self) -> QColor:
        return self._color(QPalette.ColorRole.Midlight)

    # Status colors, darker on light theme for contrast
    def _status(self, dark: str, light: str) -> QColor:
        return QColor(dark if self._color(QPalette.ColorRole.Window).lightness() < 128 else light)

    @Property(QColor, notify=changed)
    def gold(self) -> QColor:
        """Fastest lap star"""
        return self._status("#FACC15", "#B45309")

    @Property(QColor, notify=changed)
    def purple(self) -> QColor:
        """Best sector, theoretical best"""
        return self._status("#C084FC", "#7E22CE")

    @Property(QColor, notify=changed)
    def warning(self) -> QColor:
        return self._status("#FB923C", "#C2410C")

    @Property(QColor, notify=changed)
    def gain(self) -> QColor:
        return self._status("#4ADE80", "#15803D")

    @Property(QColor, notify=changed)
    def loss(self) -> QColor:
        return self._status("#F87171", "#B91C1C")

    @Property(float, constant=True)
    def em(self) -> float:
        """Base font size in pixels, sizes scale with it like UIScaler.size"""
        return float(UIScaler.FONT_PIXEL_SCALED)

    @Property(float, constant=True)
    def fontPoint(self) -> float:
        return float(UIScaler.FONT_POINT)

    @Property(str, constant=True)
    def iconFont(self) -> str:
        """Segoe Fluent Icons / MDL2 Assets, "" if none (icons hidden)"""
        from ..app import icon_font_family

        return icon_font_family()


class Translator(QObject):
    """UI text translation for QML: i18n.tr("Text"), i18n.trm("Lap 3")

    Slots are called by Python method name: "tr" must be this class's own method, else QML gets
    QObject.tr (Qt translator, no translation) and pages stay in English.
    """

    @Slot(str, result=str)
    def tr(self, text: str) -> str:  # type: ignore[override]  # replaces QObject.tr for QML
        return tr(text)

    @Slot(str, result=str)
    def trm(self, text: str) -> str:
        return trm(text)


def create_quick_view(parent: QWidget, qml_name: str, context: dict[str, QObject]) -> QQuickWidget:
    """QML page from ui/qml file in a widget, context objects available by name in QML"""
    register_types()
    view = QQuickWidget(parent)
    surface = QSurfaceFormat(view.format())
    surface.setSamples(MSAA_SAMPLES)
    view.setFormat(surface)
    view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
    view.setClearColor(QApplication.palette().color(QPalette.ColorRole.Window))
    view.engine().addImportPath(QML_FOLDER)
    root_context = view.rootContext()
    for name, value in {"theme": Theme(view), "i18n": Translator(view), **context}.items():
        root_context.setContextProperty(name, value)
    view.setSource(QUrl.fromLocalFile(os.path.join(QML_FOLDER, qml_name)))
    for error in view.errors():
        logger.error("QML: %s", error.toString())
    return view
