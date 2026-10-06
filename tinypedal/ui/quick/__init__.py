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

import contextlib
import logging
import os

from PySide6.QtCore import Property, QEvent, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication, QPalette, QSurfaceFormat
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication, QWidget

from ...i18n import tr, trm
from .. import UIScaler

logger = logging.getLogger(__name__)

QML_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "qml")
MSAA_SAMPLES = 4  # smooth chart lines
QML_TYPES = {"bool": "bool", "QColor": "color", "double": "real", "QString": "string"}  # Theme property types
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
    """App palette, sizes & number format for QML, updated when app theme changes"""

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
    def decimalPoint(self) -> str:
        """Decimal separator of app language (comma in French): numbers formatted in QML pages"""
        from ..lap_viewer import decimal_point

        return decimal_point()

    @Property(str, constant=True)
    def iconFont(self) -> str:
        """Segoe Fluent Icons / MDL2 Assets, "" if none (icons hidden)"""
        from ..app import icon_font_family

        return icon_font_family()


def theme_copy(engine: QQmlEngine, theme: Theme) -> QObject:
    """QML object with Theme values (updated when theme changes), Theme itself if it cannot be made

    QML bindings read theme values thousands of times per second while charts zoom: from a QML object,
    no Python call (and no wait for interpreter lock held by a background thread).
    """
    meta = Theme.staticMetaObject  # type: ignore[attr-defined]  # PySide6 stubs lack it on subclasses
    lines = ["import QtQuick", "QtObject {", "    required property QtObject source"]  # QtQuick: color type
    for number in range(meta.propertyOffset(), meta.propertyCount()):
        prop = meta.property(number)
        kind = QML_TYPES.get(prop.typeName())
        if kind is None:
            logger.error("QML: theme property %s type %s not copied", prop.name(), prop.typeName())
            return theme
        lines.append(f"    readonly property {kind} {prop.name()}: source.{prop.name()}")
    lines.append("}")
    component = QQmlComponent(engine)
    component.setData("\n".join(lines).encode(), QUrl("theme_copy.qml"))
    copy = component.createWithInitialProperties({"source": theme}) if component.isReady() else None
    if copy is None:
        logger.error("QML: theme copy: %s", component.errorString())
        return theme
    copy.setParent(theme)  # kept as long as theme
    return copy


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


# i18n.tr in JavaScript: same lookup as i18n.tr (table of current language, text itself if missing).
# Non-string keys (numbers) are converted like the Python slot's str argument; "toString" & other
# Object prototype names are not table strings, so they give the text back too.
_TRANSLATOR_QML = """import QtQuick
QtObject {
    required property QtObject source
    required property var table
    function tr(text) {
        var key = typeof text === "string" ? text : (text === undefined || text === null ? "" : String(text))
        var value = table[key]
        return typeof value === "string" ? value : key
    }
    function trm(text) { return source.trm(text) }
}
"""


def translator_copy(engine: QQmlEngine, translator: Translator) -> QObject:
    """QML object translating i18n.tr() in JavaScript, Translator itself if it cannot be made

    QML pages call i18n.tr() from about 1400 bindings: a Python slot call each (interpreter lock,
    argument conversion), a JavaScript table lookup here. Table is the language when the page is
    created: app language change rebuilds pages (MainWindow.retranslate), like Translator before
    (no notify, bindings never read texts again). trm (regex rules) stays in Python, rarely used.
    """
    from ...i18n import current_language, load_translation

    component = QQmlComponent(engine)
    component.setData(_TRANSLATOR_QML.encode(), QUrl("translator_copy.qml"))
    copy = None
    if component.isReady():
        table = load_translation(current_language())
        copy = component.createWithInitialProperties({"source": translator, "table": table})
    if copy is None:
        logger.error("QML: translator copy: %s", component.errorString())
        return translator
    copy.setParent(translator)  # kept as long as translator
    return copy


class PageState(QObject):
    """Page shown on screen or not, "pageState.active" in QML: timers & animations stop while hidden

    A QQuickWidget page keeps its QML root visible when the widget, a parent (stacked page, closed
    tab) or its window (minimized, tray) is hidden: QML "visible" guards never stop timers. Follows
    Show / Hide events of the view (sent for hidden parents too) & window state of its window.
    """

    activeChanged = Signal()

    def __init__(self, view: QWidget):
        super().__init__(view)
        self._view = view
        self._window: QWidget | None = None
        self._active = False
        view.installEventFilter(self)
        self._update()

    @Property(bool, notify=activeChanged)
    def active(self) -> bool:
        return self._active

    def _watch_window(self):
        """Window state changes (minimized) seen on the view's current window (page may be moved)"""
        window = self._view.window()
        if window is self._window:
            return
        if self._window is not None:
            with contextlib.suppress(RuntimeError):  # window already deleted
                self._window.removeEventFilter(self)
        self._window = window if window is not self._view else None
        if self._window is not None:
            self._window.installEventFilter(self)

    def _update(self):
        self._watch_window()
        window = self._view.window()
        active = self._view.isVisible() and not window.isMinimized()
        if active != self._active:
            self._active = active
            self.activeChanged.emit()

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind in _PAGE_STATE_EVENTS:
            if kind == QEvent.Type.Hide and watched is self._view:
                if self._active:  # hidden, spontaneous too (window minimized: isVisible() stays True)
                    self._active = False
                    self.activeChanged.emit()
            else:
                self._update()
        return False


_PAGE_STATE_EVENTS = frozenset((
    QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.WindowStateChange, QEvent.Type.ParentChange,
))


def create_quick_view(
    parent: QWidget,
    qml_name: str,
    context: dict[str, QObject],
    samples: int = MSAA_SAMPLES,
) -> QQuickWidget:
    """QML page from ui/qml file in a widget, context objects available by name in QML

    Args:
        samples: multisample antialiasing, 0 for pages without chart lines (less GPU memory).
    """
    register_types()
    view = QQuickWidget(parent)
    if samples:
        surface = QSurfaceFormat(view.format())
        surface.setSamples(samples)
        view.setFormat(surface)
    view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
    view.setClearColor(QApplication.palette().color(QPalette.ColorRole.Window))
    view.engine().addImportPath(QML_FOLDER)
    root_context = view.rootContext()
    engine = view.engine()
    theme = theme_copy(engine, Theme(view))
    # Context properties (not required properties / singletons): they only block qmlsc / AOT compiled
    # bindings, and QML files are not compiled ahead of time (loaded from ui/qml, no qmlcachegen step in
    # build_pyinstaller.py): bindings run in the same JIT either way. Set once, before setSource. Child
    # QML files read backend / theme / i18n / pageState by name through the context chain.
    shared = {"theme": theme, "i18n": translator_copy(engine, Translator(view)), "pageState": PageState(view)}
    for name, value in {**shared, **context}.items():
        root_context.setContextProperty(name, value)
    from .preview_provider import install_provider
    install_provider(engine)  # overlay pictures (image://overlaypreview/), registered before loading
    view.setSource(QUrl.fromLocalFile(os.path.join(QML_FOLDER, qml_name)))
    for error in view.errors():
        logger.error("QML: %s", error.toString())
    return view
