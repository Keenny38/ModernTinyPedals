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
Qt Quick (QML) pages hosted inside widget dialogs

QML files are in ui/qml, Python items (GPU drawn lines) registered as "NeoPedal" QML module.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import weakref
from collections.abc import Mapping

from PySide6.QtCore import Property, QEvent, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication, QPalette, QSurfaceFormat
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlIncubationController
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from ...i18n import tr, trm
from ...regex_pattern import COMMON_TYRE_COMPOUNDS
from ...template.setting_compounds import COMPOUND_COLORS, COMPOUND_SYMBOLS, compound_letter
from ...template.setting_status_colors import STATUS_COLORS
from .. import UIScaler, colorblind_state, set_colorblind  # noqa: F401  # set_colorblind: tests & pages

logger = logging.getLogger(__name__)

QML_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "qml")
# QML files are in subfolders: components (shared Tp* controls, imported by pages with import "../components")
# and one folder per zone (home, config, overlays, director, telemetry, analysis)
QML_COMPONENTS = os.path.join(QML_FOLDER, "components")
_QML_INDEX: dict[str, dict[str, str]] = {}
QML_TYPES = {"bool": "bool", "QColor": "color", "double": "real", "int": "int", "QString": "string"}  # Theme property types
_registered = False

# Design tokens of QML pages (theme.fontSmall, theme.radiusMd...): pages use these, not their own numbers
# (tests/test_qml_design_tokens.py keeps the scale). Font sizes: factor of base point size.
FONT_SCALE = {
    "fontMicro": 0.62,  # chart ticks, tiny chips
    "fontTiny": 0.7,
    "fontCaption": 0.78,  # captions, column headers
    "fontSmall": 0.85,  # secondary text, details
    "fontLabel": 0.9,
    "fontSubtitle": 1.1,  # card & section titles
    "fontHeading": 1.25,  # dialog & panel titles
    "fontLarge": 1.4,
    "fontTitle": 1.5,  # page titles, key figures
    "fontDisplay": 1.75,
}
# Corner radius: factor of em
RADIUS_SCALE = {"radiusXs": 0.2, "radiusSm": 0.3, "radiusMd": 0.45, "radiusLg": 0.6, "radiusXl": 0.75}
# Page width breakpoints: factor of em (pages with content-tuned widths keep their own, commented)
BREAKPOINTS = {"bpCompact": 40, "bpNarrow": 56, "bpWide": 70}
# Spacing: factor of em. space1..6 for gaps inside a block, pad* for the margins of a page, card, popup
SPACE_SCALE = {
    "space1": 0.2, "space2": 0.3, "space3": 0.4, "space4": 0.6, "space5": 0.8, "space6": 1.2,
    "padPage": 0.8,  # page margins
    "padCard": 0.7,  # card & panel padding
    "padPopup": 1.0,  # popup & dialog padding
}
# Control & row heights: factor of em
SIZE_SCALE = {
    "controlHeight": 2.3,  # buttons, switches, segmented controls, search fields
    "controlHeightSm": 1.85,  # compact toolbars, buttons inside rows
    "controlHeightXs": 1.5,  # buttons inside chips & tags
    "fieldHeight": 2.05,  # text & number fields, combo boxes
    "rowCompact": 2.1,  # dense tables, menus
    "row": 2.8,  # lists
    "rowTall": 3.4,  # lists with two text lines
}
# Animation durations (ms), 0 when Windows animations are off
MOTION = {"motionFast": 120, "motionBase": 180, "motionSlow": 250}
# Tint alpha (color over a surface): named levels of theme.tint(color, level)
TINT_LEVELS = {"subtle": 0.1, "selected": 0.18, "strong": 0.28}
TINT_SELECTED_LIGHT = 0.12  # selected rows of light themes (dim text stays 4.5:1 on them)
INK_DARK = "#111111"  # text on light fills
# Colorblind safe status colors (Okabe-Ito like overlays: green -> blue, red -> vermillion, purple -> reddish
# purple), (on dark background, on light background): app pages follow the overlay style option
COLORBLIND_STATUS = {
    "gain": ("#56B4E9", "#0067A8"),
    "loss": ("#F08A50", "#B04A00"),
    "warning": ("#E6A100", "#8F5F00"),
    "purple": ("#E08AC0", "#A33D80"),
}
# Overlay preview stage (always dark: overlays are drawn for a game screen)
STAGE_COLORS = {"stageTop": "#2B313A", "stageBottom": "#14171C", "stageText": "#AEB5BF"}
# Session kind colors: race, qualifying, practice (theme color names), others dim
SESSION_TONES = {"R": "warning", "RACE": "warning", "Q": "purple", "QUALIFY": "purple", "P": "accent",
                 "PRACTICE": "accent"}


def qml_path(qml_name: str) -> str:
    """Full path of a QML (or JS) file of QML_FOLDER by file name, whatever its subfolder (index made once per
    folder), QML_FOLDER/qml_name if unknown"""
    folder = QML_FOLDER
    index = _QML_INDEX.get(folder)
    if index is None:
        index = {}
        for root, _folders, names in os.walk(folder):
            for name in names:
                if name.endswith((".qml", ".js")):
                    index.setdefault(name, os.path.join(root, name))
        _QML_INDEX[folder] = index
    return index.get(qml_name, os.path.join(folder, qml_name))


def qml_folder_imports() -> str:
    """QML import lines of every subfolder of QML_FOLDER (components & zones): QML text written outside these
    folders (tests, tools) uses any page component by name"""
    folders = sorted(entry.path for entry in os.scandir(QML_FOLDER) if entry.is_dir() and not entry.name.startswith("_"))
    return "\n".join(f'import "{QUrl.fromLocalFile(folder).toString()}"' for folder in folders)


def qml_files() -> list[str]:
    """Full paths of every QML file of QML_FOLDER (subfolders included), sorted by file name"""
    qml_path("")  # index made
    return sorted((path for name, path in _QML_INDEX[QML_FOLDER].items() if name.endswith(".qml")),
                  key=os.path.basename)


def compound_key(name: str) -> str:
    """COMPOUND_COLORS key of a compound name ("Soft", "Q-Soft", "Medium #2", "Hyper - Soft") or game
    letter ("S")"""
    key = name.split("#")[0].split(" - ")[-1].strip().lower()
    key = key.removeprefix("q-")
    return COMPOUND_SYMBOLS.get(key, key)


def ink_on(color: QColor) -> QColor:
    """Readable text color on a color fill: dark on light colors, white on dark ones"""
    luma = 0.299 * color.redF() + 0.587 * color.greenF() + 0.114 * color.blueF()
    return QColor(INK_DARK if luma > 0.6 else "white")


def contrast_ratio(first: QColor, second: QColor) -> float:
    """WCAG contrast ratio of two colors"""
    def luminance(color: QColor) -> float:
        channels = [
            value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
            for value in (color.redF(), color.greenF(), color.blueF())
        ]
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def readable_on(color: QColor, background: QColor, toward: QColor, minimum: float = 4.5) -> QColor:
    """color moved toward another color (text) until it reaches the contrast ratio on background"""
    if contrast_ratio(color, background) >= minimum:
        return QColor(color)
    for step in range(1, 11):
        mix = step / 10
        mixed = QColor.fromRgbF(color.redF() + (toward.redF() - color.redF()) * mix,
                                color.greenF() + (toward.greenF() - color.greenF()) * mix,
                                color.blueF() + (toward.blueF() - color.blueF()) * mix)
        if contrast_ratio(mixed, background) >= minimum:
            return mixed
    return QColor(toward)


def blended(color: QColor, background: QColor, alpha: float) -> QColor:
    """Opaque color of a translucent color over a background"""
    return QColor.fromRgbF(*(top * alpha + bottom * (1 - alpha) for top, bottom in (
        (color.redF(), background.redF()), (color.greenF(), background.greenF()), (color.blueF(), background.blueF()))))


def fill_for_white_text(color: QColor, minimum: float = 4.5) -> QColor:
    """Color darkened until white text on it reaches the contrast ratio (same hue)"""
    white = QColor("white")
    fill = QColor(color)
    for _ in range(40):
        if contrast_ratio(fill, white) >= minimum:
            break
        fill = fill.darker(104)
    return fill


def system_animations() -> bool:
    """Windows "Animation effects" setting (Accessibility > Visual effects), on elsewhere"""
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes

    enabled = wintypes.BOOL(True)
    spi_getclientareaanimation = 0x1042
    if not ctypes.windll.user32.SystemParametersInfoW(spi_getclientareaanimation, 0, ctypes.byref(enabled), 0):
        return True  # older Windows: no such setting
    return bool(enabled.value)


_ANIMATIONS: list[bool] = []  # system setting, read once by the first Theme


def _font_token(name: str) -> Property:
    return Property(float, lambda self: UIScaler.FONT_POINT * FONT_SCALE[name], constant=True, doc=f"Font point size {name}")


def _size_token(scale: Mapping[str, float], name: str) -> Property:
    return Property(float, lambda self: UIScaler.FONT_PIXEL_SCALED * scale[name], constant=True, doc=f"Pixel size {name}")


def _motion_token(name: str) -> Property:
    return Property(int, lambda self: MOTION[name] if _ANIMATIONS[0] else 0, constant=True, doc=f"Duration (ms) {name}")


def _stage_token(name: str) -> Property:
    return Property(QColor, lambda self: QColor(STAGE_COLORS[name]), constant=True, doc=f"Preview stage color {name}")


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
        if not _ANIMATIONS:
            _ANIMATIONS.append(system_animations())
        app = QApplication.instance()
        if isinstance(app, QGuiApplication):
            app.paletteChanged.connect(self.changed)
        colorblind_state().changed.connect(self.changed)

    @staticmethod
    def _color(role: QPalette.ColorRole, group=QPalette.ColorGroup.Active) -> QColor:
        return QApplication.palette().color(group, role)

    def _is_dark(self) -> bool:
        return self._color(QPalette.ColorRole.Window).lightness() < 128

    def _tint_selected(self) -> float:
        return TINT_LEVELS["selected"] if self._is_dark() else TINT_SELECTED_LIGHT

    def _role(self, name: str) -> QColor:
        """Status color of a role (STATUS_COLORS), colorblind safe variant when that option is on"""
        pair = COLORBLIND_STATUS[name] if colorblind_state().enabled and name in COLORBLIND_STATUS else STATUS_COLORS[name]
        return QColor(pair[0] if self._is_dark() else pair[1])

    @Property(bool, notify=changed)
    def colorblind(self) -> bool:
        """Colorblind safe status colors (overlay style option): gain blue, loss orange..."""
        return colorblind_state().enabled

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
        """Accent for text, lines & tints"""
        return self._color(QPalette.ColorRole.Highlight)

    @Property(QColor, notify=changed)
    def accentFill(self) -> QColor:
        """Accent filling a control under white text (darker when needed: 4.5:1 contrast)"""
        return fill_for_white_text(self._color(QPalette.ColorRole.Highlight))

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
        """Fastest lap star, yellow flag"""
        return self._role("gold")

    @Property(QColor, notify=changed)
    def purple(self) -> QColor:
        """Best sector, theoretical best"""
        return self._role("purple")

    @Property(QColor, notify=changed)
    def warning(self) -> QColor:
        return self._role("warning")

    @Property(QColor, notify=changed)
    def gain(self) -> QColor:
        return self._role("gain")

    @Property(QColor, notify=changed)
    def loss(self) -> QColor:
        return self._role("loss")

    @Property(QColor, notify=changed)
    def lossFill(self) -> QColor:
        """Loss / error color filling a badge under white text (4.5:1 contrast)"""
        return fill_for_white_text(self._role("loss"))

    @Property(QColor, notify=changed)
    def silver(self) -> QColor:
        """Second place"""
        return self._status("#C3CAD4", "#64748B")

    @Property(QColor, notify=changed)
    def bronze(self) -> QColor:
        """Third place"""
        return self._status("#D99A62", "#9A5B2C")

    @Property(QColor, notify=changed)
    def live(self) -> QColor:
        """Live game data"""
        return self._status("#3DDC84", "#15803D")

    # Data series colors, same meaning on every page (charts, tiles, strips)
    @Property(QColor, notify=changed)
    def seriesFuel(self) -> QColor:
        return self._status("#4C9AFF", "#2563EB")

    @Property(QColor, notify=changed)
    def seriesEnergy(self) -> QColor:
        return self._status("#F5A623", "#C2410C")

    @Property(QColor, notify=changed)
    def seriesTyre(self) -> QColor:
        return self._status("#F5B342", "#A16207")

    @Property(QColor, notify=changed)
    def seriesWear(self) -> QColor:
        return self._status("#F59E0B", "#B45309")

    @Property(QColor, notify=changed)
    def seriesStint(self) -> QColor:
        return self._status("#7ED321", "#4D7C0F")

    @Property(QColor, notify=changed)
    def seriesRefill(self) -> QColor:
        return self._status("#50E3C2", "#0F766E")

    @Slot(str, result=QColor)
    def compound(self, name: str) -> QColor:
        """Tyre compound color by name or letter, dim text if unknown (theme copy has the same in JavaScript)"""
        pair = COMPOUND_COLORS.get(compound_key(name))
        if pair is None:
            return self._color(QPalette.ColorRole.PlaceholderText)
        return QColor(pair[0] if self.dark else pair[1])

    @Slot(str, result=str)
    def compoundLetter(self, name: str) -> str:
        """Badge letter of a compound name (theme copy has the same in JavaScript)"""
        return compound_letter(name)

    @Slot(QColor, result=QColor)
    def inkOn(self, color: QColor) -> QColor:
        return ink_on(color)

    @Slot(bool, bool, result=QColor)
    def rowColor(self, hovered: bool, selected: bool) -> QColor:
        """List row background: selected (accent tint, a third stronger hovered), hovered, else transparent"""
        if selected:
            color = QColor(self._color(QPalette.ColorRole.Highlight))
            color.setAlphaF(self._tint_selected() * (4 / 3 if hovered else 1))
            return color
        return self._color(QPalette.ColorRole.Midlight) if hovered else QColor(0, 0, 0, 0)

    @Slot(QColor, "QVariant", result=QColor)
    def tint(self, color: QColor, level=None) -> QColor:
        """Translucent color: level "subtle" / "selected" / "strong" (TINT_LEVELS) or an alpha number"""
        tinted = QColor(color)
        if isinstance(level, (int, float)) and not isinstance(level, bool):
            tinted.setAlphaF(max(0.0, min(1.0, float(level))))
        else:
            tinted.setAlphaF(self._tint_selected() if level == "selected" else TINT_LEVELS.get(level, TINT_LEVELS["subtle"]))
        return tinted

    @Slot(QColor, result=QColor)
    def dimOn(self, background: QColor) -> QColor:
        """Dim text readable (4.5:1) on a background: dim text itself, else moved toward text color.
        Translucent backgrounds are taken over the page background (window)."""
        window = self._color(QPalette.ColorRole.Window)
        surface = blended(background, window, background.alphaF()) if background.alphaF() < 1 else background
        return readable_on(self._color(QPalette.ColorRole.PlaceholderText), surface, self._color(QPalette.ColorRole.Text))

    @Slot(str, result=QColor)
    def tone(self, name: str) -> QColor:
        """Theme color of a semantic name sent by backends ("gain", "loss", "fastest"...), dim text if unknown"""
        return QColor(getattr(self, _TONE_NAMES.get(name, "dimText")))

    @Slot(str, result=QColor)
    def sessionColor(self, code: str) -> QColor:
        """Session kind color: race, qualifying, practice ("R" / "RACE"...), dim text for others"""
        return QColor(getattr(self, SESSION_TONES.get(str(code).upper(), "dimText")))

    @Property(QColor, notify=changed)
    def cardBorder(self) -> QColor:
        """Border of cards & list rows (lighter than base on dark themes)"""
        base = self._color(QPalette.ColorRole.Base)
        return base.lighter(135) if self._is_dark() else self._color(QPalette.ColorRole.Mid)

    @Property(QColor, notify=changed)
    def plotBase(self) -> QColor:
        """Chart plot background"""
        base = self._color(QPalette.ColorRole.Base)
        return base.darker(118) if self._is_dark() else base.darker(102)

    @Property(QColor, notify=changed)
    def plotBorder(self) -> QColor:
        base = self._color(QPalette.ColorRole.Base)
        return base.lighter(130) if self._is_dark() else self._color(QPalette.ColorRole.Mid)

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
        from ...i18n import decimal_point

        return decimal_point()

    @Property(str, constant=True)
    def iconFont(self) -> str:
        """Segoe Fluent Icons / MDL2 Assets, "" if none (icons hidden)"""
        from ..app import icon_font_family

        return icon_font_family()

    @Property(str, constant=True)
    def monoFont(self) -> str:
        """Fixed width font: hotkeys, formulas (Consolas on Windows, system fixed font elsewhere)"""
        if "Consolas" in QFontDatabase.families():
            return "Consolas"
        return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()

    @Property(bool, constant=True)
    def animate(self) -> bool:
        """Animations on (Windows animation effects setting): looping animations run only then"""
        return _ANIMATIONS[0]

    # Design tokens (constant)
    fontMicro = _font_token("fontMicro")
    fontTiny = _font_token("fontTiny")
    fontCaption = _font_token("fontCaption")
    fontSmall = _font_token("fontSmall")
    fontLabel = _font_token("fontLabel")
    fontSubtitle = _font_token("fontSubtitle")
    fontHeading = _font_token("fontHeading")
    fontLarge = _font_token("fontLarge")
    fontTitle = _font_token("fontTitle")
    fontDisplay = _font_token("fontDisplay")
    radiusXs = _size_token(RADIUS_SCALE, "radiusXs")
    radiusSm = _size_token(RADIUS_SCALE, "radiusSm")
    radiusMd = _size_token(RADIUS_SCALE, "radiusMd")
    radiusLg = _size_token(RADIUS_SCALE, "radiusLg")
    radiusXl = _size_token(RADIUS_SCALE, "radiusXl")
    bpCompact = _size_token(BREAKPOINTS, "bpCompact")
    bpNarrow = _size_token(BREAKPOINTS, "bpNarrow")
    bpWide = _size_token(BREAKPOINTS, "bpWide")
    motionFast = _motion_token("motionFast")
    motionBase = _motion_token("motionBase")
    motionSlow = _motion_token("motionSlow")
    tipDelay = Property(int, lambda self: 500, constant=True, doc="Tooltip delay (ms)")
    disabledOpacity = Property(float, lambda self: 0.45, constant=True, doc="Opacity of disabled controls")
    tintSubtle = Property(float, lambda self: TINT_LEVELS["subtle"], constant=True, doc="Alpha of a light color tint (hover)")
    tintStrong = Property(float, lambda self: TINT_LEVELS["strong"], constant=True, doc="Alpha of a strong tint (active state)")
    tintSelected = Property(float, lambda self: self._tint_selected(),
                            notify=changed, doc="Alpha of a selected / checked tint (lighter on light themes)")
    space1 = _size_token(SPACE_SCALE, "space1")
    space2 = _size_token(SPACE_SCALE, "space2")
    space3 = _size_token(SPACE_SCALE, "space3")
    space4 = _size_token(SPACE_SCALE, "space4")
    space5 = _size_token(SPACE_SCALE, "space5")
    space6 = _size_token(SPACE_SCALE, "space6")
    padPage = _size_token(SPACE_SCALE, "padPage")
    padCard = _size_token(SPACE_SCALE, "padCard")
    padPopup = _size_token(SPACE_SCALE, "padPopup")
    controlHeight = _size_token(SIZE_SCALE, "controlHeight")
    controlHeightSm = _size_token(SIZE_SCALE, "controlHeightSm")
    controlHeightXs = _size_token(SIZE_SCALE, "controlHeightXs")
    fieldHeight = _size_token(SIZE_SCALE, "fieldHeight")
    rowCompact = _size_token(SIZE_SCALE, "rowCompact")
    row = _size_token(SIZE_SCALE, "row")
    rowTall = _size_token(SIZE_SCALE, "rowTall")
    stageTop = _stage_token("stageTop")
    stageBottom = _stage_token("stageBottom")
    stageText = _stage_token("stageText")


# Semantic color names sent by backends (tone strings) -> Theme property
_TONE_NAMES = {
    "loss": "loss", "gain": "gain", "warning": "warning", "accent": "accent", "fastest": "purple", "purple": "purple",
    "yellow": "gold", "gold": "gold", "live": "live", "silver": "silver", "bronze": "bronze", "text": "text",
    "dim": "dimText",
}


# Theme slots in JavaScript (same results as Theme.compound / compoundLetter / inkOn / rowColor / tint / dimOn /
# tone / sessionColor, no Python call per binding)
_THEME_FUNCTIONS_QML = """    readonly property var compoundColors: (%s)
    readonly property var compoundLetters: (%s)
    readonly property var compoundPatterns: (%s)
    function compound(name) {
        var key = String(name === undefined || name === null ? "" : name).split("#")[0].split(" - ").pop().trim().toLowerCase()
        if (key.indexOf("q-") === 0)
            key = key.slice(2)
        var pair = compoundColors[compoundLetters[key] || key]
        return pair ? (dark ? pair[0] : pair[1]) : dimText
    }
    function compoundLetter(name) {
        var tyre = String(name === undefined || name === null ? "" : name).split("#")[0].split(" - ").pop().trim()
        if (tyre.length <= 1)
            return tyre.toUpperCase()
        for (var i = 0; i < compoundPatterns.length; ++i)
            if (new RegExp(compoundPatterns[i][0], "i").test(tyre))
                return compoundPatterns[i][1]
        return tyre.charAt(0).toUpperCase()
    }
    readonly property var tintLevels: (%s)
    function rowColor(hovered, selected) {
        return selected ? Qt.rgba(accent.r, accent.g, accent.b, hovered ? tintSelected * 4 / 3 : tintSelected)
             : hovered ? hover : "transparent"
    }
    function tint(color, level) {
        var c = typeof color === "string" ? Qt.color(color) : color
        if (!c || c.r === undefined)
            return "transparent"
        var alpha = typeof level === "number" ? Math.max(0, Math.min(1, level))
                  : level === "selected" ? tintSelected
                  : tintLevels[level] !== undefined ? tintLevels[level] : tintLevels.subtle
        return Qt.rgba(c.r, c.g, c.b, alpha)
    }
    function luminance(c) {
        function channel(v) { return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }
        return 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b)
    }
    function contrast(first, second) {
        var a = luminance(first), b = luminance(second)
        return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
    }
    function dimOn(background) {
        var bg = typeof background === "string" ? Qt.color(background) : background
        if (!bg || bg.r === undefined)
            return dimText
        if (bg.a < 1)
            bg = Qt.rgba(bg.r * bg.a + window.r * (1 - bg.a), bg.g * bg.a + window.g * (1 - bg.a),
                         bg.b * bg.a + window.b * (1 - bg.a), 1)
        if (contrast(dimText, bg) >= 4.5)
            return dimText
        for (var step = 1; step <= 10; ++step) {
            var mix = step / 10
            var mixed = Qt.rgba(dimText.r + (text.r - dimText.r) * mix, dimText.g + (text.g - dimText.g) * mix,
                                dimText.b + (text.b - dimText.b) * mix, 1)
            if (contrast(mixed, bg) >= 4.5)
                return mixed
        }
        return text
    }
    function tone(name) {
        switch (name) {
%s
        default: return dimText
        }
    }
    function sessionColor(code) {
        switch (String(code).toUpperCase()) {
%s
        default: return dimText
        }
    }
    function inkOn(color) {
        var c = typeof color === "string" && color !== "" ? Qt.color(color) : color
        if (!c || c.r === undefined)
            return "white"
        return 0.299 * c.r + 0.587 * c.g + 0.114 * c.b > 0.6 ? "%s" : "white"
    }"""


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
    tones = "\n".join(f'        case "{name}": return {prop}' for name, prop in _TONE_NAMES.items())
    sessions = "\n".join(f'        case "{code}": return {prop}' for code, prop in SESSION_TONES.items())
    lines.append(_THEME_FUNCTIONS_QML % (json.dumps(dict(COMPOUND_COLORS)), json.dumps(dict(COMPOUND_SYMBOLS)),
                                         json.dumps(COMMON_TYRE_COMPOUNDS), json.dumps(TINT_LEVELS), tones, sessions,
                                         INK_DARK))
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


def reload_in_language(view: QQuickWidget) -> None:
    """QML page loaded again in current app language (backend & pending edits kept)

    i18n holds the translation table of the language when it was made: replaced by a new one first,
    old one (& its translator) deleted.
    """
    source = view.source()
    view.setSource(QUrl())
    context = view.rootContext()
    old = context.contextProperty("i18n")
    context.setContextProperty("i18n", translator_copy(view.engine(), Translator(view)))
    owner = old if isinstance(old, Translator) else old.parent() if isinstance(old, QObject) else None
    if isinstance(owner, Translator):
        owner.deleteLater()
    view.setSource(source)


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
        if kind in _PAGE_STATE_EVENTS and isValid(self._view):  # view being destroyed: its wrapper is gone first
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

INCUBATE_MS = 6  # QML objects built per event loop pass while some are incubating (a frame stays responsive)


class _IncubationController(QQmlIncubationController):
    """Tells its Incubator when QML objects wait to be built (held weakly: no reference cycle)"""

    def __init__(self, incubator: Incubator):
        super().__init__()
        self._incubator = weakref.ref(incubator)

    def incubatingObjectCountChanged(self, count: int):
        incubator = self._incubator()
        if incubator is not None and isValid(incubator):  # page being deleted: nothing left to drive
            with contextlib.suppress(RuntimeError):  # timer already deleted
                incubator.count_changed(count)


class Incubator(QObject):
    """Asynchronous QML incubation of a QQuickWidget page (Loader { asynchronous: true }, Repeater delegates of an
    asynchronous Loader...): built a few milliseconds per event loop pass instead of all at once

    A QQuickWidget engine has no incubation controller (unlike QQuickView): asynchronous loaders were built at once.
    Child of the view: controller (engine holds a plain pointer to it) lives as long as the view, the engine (also
    deleted with the view) and the controller each let go of the other when deleted first.
    """

    def __init__(self, view: QQuickWidget):
        super().__init__(view)
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.incubate)
        self.controller = _IncubationController(self)
        view.engine().setIncubationController(self.controller)

    @property
    def active(self) -> bool:
        """Objects being incubated"""
        return self._timer.isActive()

    def count_changed(self, count: int):
        if count and not self._timer.isActive():
            self._timer.start()
        elif not count:
            self._timer.stop()

    @Slot()
    def incubate(self):
        self.controller.incubateFor(INCUBATE_MS)


def install_incubator(view: QQuickWidget) -> Incubator | None:
    """Incubation controller set on view engine (before setSource), None if the engine already has one"""
    if view.engine().incubationController() is not None:
        return None
    return Incubator(view)


def create_quick_view(
    parent: QWidget,
    qml_name: str,
    context: dict[str, QObject],
    samples: int = 0,
) -> QQuickWidget:
    """QML page from ui/qml file in a widget, context objects available by name in QML

    Args:
        samples: window multisample antialiasing, 0: none. Chart & map lines are drawn in a multisampled
            layer while the page is shown instead (window MSAA keeps its GPU memory while hidden).
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
    install_incubator(view)  # asynchronous loaders really asynchronous, set before loading
    view.setSource(QUrl.fromLocalFile(qml_path(qml_name)))
    for error in view.errors():
        logger.error("QML: %s", error.toString())
    return view
