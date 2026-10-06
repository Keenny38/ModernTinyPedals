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
Home page: state at a glance (game & session, overlay, preset, version, last session) & shortcuts

Header with version, what's new of running version (local changelog, works offline) and update
state. Cards are clickable (open their page), laid out in 1 to 3 columns following page width.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from typing import NamedTuple

from PySide6.QtCore import QDateTime, QLocale, QPointF, Qt, QTimer, Slot
from PySide6.QtGui import QFont, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import app_signal
from ..api_control import api
from ..calculation import sec2laptime_full
from ..const_app import APP_NAME, VERSION
from ..i18n import current_language, tr, trm
from ..module_control import mctrl, wctrl
from ..overlay_control import octrl
from ..setting import cfg
from ..update import changelog_sections, localized_changelog_name, update_checker
from ..userfile.custom_image import brand_logo_file, load_picture, logo_for_background
from ..userfile.driver_history import SessionRecord, last_record
from ..userfile.game_images import images
from . import app_icon_file, status_color
from ._common import UIScaler
from .nav_rail import RailEditor
from .ordered_picker import PickerEntry
from .quick.game_pictures import notifier

CHANGELOG_FILE = "CHANGELOG.md"  # next to app (release build) or project root (source)
SESSION_NAMES = ("Test day", "Practice", "Qualify", "Warmup", "Race")  # game session type index
FINISH_STATES = ("", "Finished", "DNF", "DQ")  # driver history finish state
# Card icons: Segoe Fluent Icons / MDL2 Assets glyph, letter if no icon font
GLYPH_GAME = ("", "G")  # game controller
GLYPH_LOCKED = ("", "L")  # lock
GLYPH_UNLOCKED = ("", "U")  # unlock
GLYPH_PRESET = ("", "P")  # library
GLYPH_OVERLAYS = ("", "O")  # view all
GLYPH_MODULES = ("", "M")  # processing
GLYPH_HISTORY = ("", "H")  # history
GLYPH_START = ("", "S")  # play
# Quick access actions (besides tools & pages): key: (label, glyph, letter)
QUICK_ACTIONS = {
    "command_palette": ("Command Palette", "\ue721", "C"),  # search
    "bug_report": ("Create Bug Report", "\uebe8", "B"),  # bug
    "check_updates": ("Check for Updates", "\ue895", "U"),  # sync
}
QUICK_SHORTCUTS = {"command_palette": "Ctrl+K"}  # shown after label
COLUMN_WIDTH = 30  # UIScaler size of one card column, page gets 2 or 3 columns from this width
QUICK_COLUMNS = {1: 1, 2: 3, 3: 5}  # quick access buttons per row for card columns


class QuickEntry(NamedTuple):
    """Quick access entry: tool, page or action"""

    key: str
    label: str  # untranslated
    glyph: str
    letter: str  # drawn without icon font
    kind: str  # "tool", "page" or "action"
    target: str = ""  # tool dialog path, page key


def quick_access_entries() -> dict[str, QuickEntry]:
    """Every possible quick access entry by key: tools, then pages (but home), then actions"""
    from .nav_rail import rail_entries

    tools, pages = {}, {}
    for key, entry in rail_entries().items():
        if entry.page >= 0:
            if key != "home":
                pages[key] = QuickEntry(key, entry.tooltip, entry.glyph, entry.letter, "page", key)
        else:
            tools[key] = QuickEntry(key, entry.tooltip, entry.glyph, entry.letter, "tool", entry.dialog)
    actions = {key: QuickEntry(key, label, glyph, letter, "action") for key, (label, glyph, letter) in QUICK_ACTIONS.items()}
    return {**tools, **pages, **actions}


def parse_quick_items(text: str) -> list[str]:
    """Known & unique entry keys of quick access setting text, in order"""
    from .tools_view import RENAMED_TOOL_KEYS

    known = quick_access_entries()
    keys: list[str] = []
    for key in (text or "").split(","):
        key = RENAMED_TOOL_KEYS.get(key.strip(), key.strip())  # merged tools: new tool
        if key in known and key not in keys:
            keys.append(key)
    return keys


def default_quick_items() -> list[str]:
    from ..template.setting_global import GLOBAL_DEFAULT

    application: dict = GLOBAL_DEFAULT["application"]  # type: ignore[assignment]
    return parse_quick_items(str(application["home_quick_access"]))


def current_quick_items() -> list[str]:
    """Quick access entry keys from setting (may be empty: user removed every entry)"""
    text = cfg.application.get("home_quick_access")
    return default_quick_items() if text is None else parse_quick_items(str(text))


class QuickAccessEditor(RailEditor):
    """Choose & order home page quick access entries"""

    TITLE = "Customize Quick Access"
    HELP = (
        "Buttons of home page: drag entries to reorder, or use the arrows. "
        "Add tools, pages or actions from the list on the right."
    )

    def picker_entries(self) -> dict[str, PickerEntry]:
        kinds = {
            "tool": (tr("Tools"), tr("Tool")), "page": (tr("Pages"), tr("Page")), "action": (tr("Actions"), tr("Action")),
        }
        return {
            key: PickerEntry(key, tr(entry.label), entry.glyph, entry.letter, kinds[entry.kind][0],
                             tag=kinds[entry.kind][1])
            for key, entry in quick_access_entries().items()
        }

    def badge_text(self, row: int) -> str:
        return str(row + 1)

    def current_items(self) -> list[str]:
        return current_quick_items()

    def default_items(self) -> list[str]:
        return default_quick_items()

    def save_items(self, keys: list[str]):
        cfg.application["home_quick_access"] = ",".join(keys)  # empty: no quick access button


def base_version(version: str = VERSION) -> str:
    """Version without development suffix: 0.19.1+3.g8a0f9f3 -> 0.19.1"""
    return version.split("+")[0].split("-")[0]


def read_changelog(filename: str) -> list[tuple[str, str]]:
    """Changelog sections (version, body), empty if no changelog"""
    try:
        with open(filename, encoding="utf-8") as file:
            return changelog_sections(file.read())
    except (OSError, UnicodeDecodeError):
        return []


def current_release_notes(filename: str = CHANGELOG_FILE, version: str = VERSION, language: str = "en") -> str:
    """Changelog section of running version in language (CHANGELOG.<code>.md), empty if no changelog

    Section of running version in language, else in English (not translated yet), else
    newest section (development version).
    """
    translated = read_changelog(localized_changelog_name(language, filename)) if language != "en" else []
    english = read_changelog(filename)
    base = base_version(version)
    for sections in (translated, english):
        body = next((body for name, body in sections if name == base), None)
        if body is not None:
            return body
    return (translated or english or [("", "")])[0][1]


def api_state_text() -> tuple[str, bool]:
    """API state text & whether game is running"""
    if cfg.api["enable_active_state_override"]:
        state = "overriding"
    else:
        state = api.read.state.version()
    return state, bool(state) and state not in ("not running", "0.0")


def session_text() -> str:
    """Current session (track, session, position, lap), empty if not on track"""
    read = api.read
    try:
        if not read.state.active():
            return ""
        session = read.session.session_type()
        parts = [
            read.session.track_name(),
            tr(SESSION_NAMES[session]) if 0 <= session < len(SESSION_NAMES) else "",
            f"P{read.vehicle.place()}/{read.vehicle.total_vehicles()}" if read.vehicle.total_vehicles() > 1 else "",
            f"{tr('Lap')} {read.lap.number()}",
        ]
    except (AttributeError, TypeError, ValueError, IndexError):
        return ""
    return " · ".join(html.escape(part) for part in parts if part)


def last_session() -> SessionRecord | None:
    """Last driven session (driver stats history, end of file read), None if none"""
    try:
        return last_record(cfg.path.config)
    except OSError:
        return None


def game_logos(track: str, vehicle_name: str = "", brand: str = "") -> tuple[str, ...]:
    """Circuit & car brand logo files of game (own brand logo first), those cached only"""
    light = QApplication.palette().color(QPalette.ColorRole.Window).lightness() > 128
    track_logo = logo_for_background(images.track_logo(track), light) if track else ""
    brand_logo = brand_logo_file(cfg.path.brand_logo, images.brand(vehicle_name, brand), light, vehicle_name)         if vehicle_name or brand else ""
    return tuple(path for path in (track_logo, brand_logo) if path)


def live_logos() -> tuple[str, ...]:
    """Logos of current track & player car, none if not on track"""
    read = api.read
    try:
        if not read.state.active():
            return ()
        return game_logos(read.session.track_name(), read.vehicle.vehicle_name())
    except (AttributeError, TypeError, ValueError, IndexError):
        return ()


def record_logos(record: SessionRecord) -> tuple[str, ...]:
    """Logos of track & car brand of a session record (vehicle key "Class - Brand", or vehicle name)"""
    if " - " in record.vehicle:
        return game_logos(record.track, brand=record.vehicle.split(" - ", 1)[1].strip())
    if record.vehicle and record.vehicle != record.vehicle_class:
        return game_logos(record.track, record.vehicle)
    return game_logos(record.track)


def session_record_text(record: SessionRecord) -> tuple[str, str]:
    """Value & detail of a session record: track, then vehicle, session, best lap, result, date"""
    when = QDateTime.fromSecsSinceEpoch(int(record.time))
    session = tr(SESSION_NAMES[record.session]) if 0 <= record.session < len(SESSION_NAMES) else ""
    result = ""
    if record.session == 4 and record.finish == 1 and record.position > 0:
        result = f"P{record.position}"
    elif 0 < record.finish < len(FINISH_STATES):
        result = tr(FINISH_STATES[record.finish])
    parts = (
        record.vehicle,
        session,
        f"{tr('Best')} {sec2laptime_full(record.best)}" if record.best > 0 else "",
        result,
        QLocale(current_language()).toString(when, QLocale.FormatType.ShortFormat),
    )
    return f"<b>{html.escape(record.track)}</b>", " · ".join(html.escape(part) for part in parts if part)


class HomeCard(QFrame):
    """Card: icon & title, value, detail, optional buttons; whole card opens on_click (mouse, Enter, Space)"""

    def __init__(self, parent, title: str, glyph: tuple[str, str], icon_family: str,
                 on_click: Callable[[], object] | None = None, tooltip: str = ""):
        super().__init__(parent)
        self.setObjectName("homeCard")
        self.on_click = on_click
        self.icon_family = icon_family
        if on_click is not None:
            self.setProperty("clickable", True)
            self.setAttribute(Qt.WidgetAttribute.WA_Hover)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setToolTip(tooltip)
        self.label_glyph = QLabel(self)
        self.label_glyph.setObjectName("homeGlyph")
        if icon_family:
            font = QFont(icon_family)
            font.setPixelSize(UIScaler.pixel(16))
            self.label_glyph.setFont(font)
        self.set_glyph(glyph)
        self.label_title = QLabel(tr(title), self)
        self.label_title.setObjectName("homeCardTitle")
        self.label_logos = QLabel(self)  # circuit & car brand logos of game
        self.label_logos.hide()
        self.logos: tuple[str, ...] = ()
        layout_title = QHBoxLayout()
        layout_title.setSpacing(UIScaler.pixel(6))
        layout_title.addWidget(self.label_glyph)
        layout_title.addWidget(self.label_title, stretch=1)
        layout_title.addWidget(self.label_logos)

        self.label_value = QLabel("", self)
        self.label_value.setObjectName("homeValue")
        self.label_value.setTextFormat(Qt.TextFormat.RichText)
        self.label_detail = QLabel("", self)
        self.label_detail.setObjectName("homeDetail")
        self.label_detail.setTextFormat(Qt.TextFormat.RichText)
        self.label_detail.setWordWrap(True)
        self.layout_actions = QHBoxLayout()
        self.layout_actions.setSpacing(UIScaler.pixel(6))

        layout = QVBoxLayout(self)
        margin = UIScaler.pixel(12)
        layout.setContentsMargins(margin, UIScaler.pixel(10), margin, margin)
        layout.setSpacing(UIScaler.pixel(3))
        layout.addLayout(layout_title)
        layout.addWidget(self.label_value)
        layout.addWidget(self.label_detail)
        layout.addStretch(1)
        layout.addLayout(self.layout_actions)

    def set_glyph(self, glyph: tuple[str, str]):
        text = glyph[0] if self.icon_family else glyph[1]
        if self.label_glyph.text() != text:
            self.label_glyph.setText(text)

    def set_logos(self, paths: tuple[str, ...]):
        """Logos side by side next to title (hidden if none)"""
        if paths == self.logos:
            return
        self.logos = paths
        height = UIScaler.pixel(22)
        ratio = self.devicePixelRatioF()
        pictures = [load_picture(path, height * 3, height, ratio) for path in paths]
        pictures = [picture for picture in pictures if not picture.isNull()]
        if not pictures:
            self.label_logos.hide()
            return
        gap = UIScaler.pixel(8)
        width = sum(picture.width() / ratio for picture in pictures) + gap * (len(pictures) - 1)
        row = QPixmap(max(round(width * ratio), 1), round(height * ratio))
        row.setDevicePixelRatio(ratio)
        row.fill(Qt.GlobalColor.transparent)
        painter = QPainter(row)
        left = 0.0
        for picture in pictures:
            top = (height - picture.height() / ratio) / 2
            painter.drawPixmap(QPointF(left, top), picture)
            left += picture.width() / ratio + gap
        painter.end()
        self.label_logos.setPixmap(row)
        self.label_logos.show()

    def add_action(self, text: str, action: Callable[[], object], primary: bool = False) -> QPushButton:
        """Button at bottom of card"""
        button = QPushButton(tr(text), self)
        if primary:
            button.setObjectName("homePrimary")
        button.clicked.connect(action)
        if self.layout_actions.count() == 0:
            self.layout_actions.addStretch(1)  # buttons kept right, stretch moved first
        self.layout_actions.insertWidget(self.layout_actions.count() - 1, button)
        return button

    def set_text(self, value: str, detail: str = ""):
        if self.label_value.text() != value:
            self.label_value.setText(value)
        if self.label_detail.text() != detail:
            self.label_detail.setText(detail)
        self.label_detail.setHidden(not detail)

    def mouseReleaseEvent(self, event):
        if (self.on_click is not None and event.button() == Qt.MouseButton.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self.on_click()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if self.on_click is not None and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.on_click()
            return
        super().keyPressEvent(event)


class HomeView(QWidget):
    """Home page"""

    def __init__(self, parent, window, select_page: Callable[[str], object], icon_family: str = ""):
        super().__init__(parent)
        self._window = window
        self._columns = 0
        content = QWidget(self)
        content.setObjectName("pageStack")
        layout_content = QVBoxLayout(content)
        margin = UIScaler.pixel(12)
        layout_content.setContentsMargins(margin, margin, margin, margin)
        layout_content.setSpacing(UIScaler.pixel(10))

        # Header: app, version, what's new & update
        hero = QFrame(content)
        hero.setObjectName("homeHero")
        self.label_icon = QLabel(hero)
        self.label_title = QLabel(f"<b>{APP_NAME}</b>", hero)
        self.label_title.setObjectName("homeHeader")
        self.label_version = QLabel("", hero)
        self.label_version.setObjectName("homeSubtitle")
        self.chip_update = QLabel("", hero)
        self.chip_update.setObjectName("homeChip")
        self.chip_update.setHidden(True)
        layout_version = QHBoxLayout()
        layout_version.setSpacing(UIScaler.pixel(8))
        layout_version.addWidget(self.label_version)
        layout_version.addWidget(self.chip_update)
        layout_version.addStretch(1)
        layout_text = QVBoxLayout()
        layout_text.setSpacing(UIScaler.pixel(2))
        layout_text.addWidget(self.label_title)
        layout_text.addLayout(layout_version)
        self.button_notes = QPushButton(tr("Release Notes"), hero)
        self.button_notes.setToolTip(tr("What's new in this version"))
        self.button_notes.clicked.connect(self.show_release_notes)
        self.button_update = QPushButton("", hero)
        self.button_update.clicked.connect(self.update_action)
        layout_hero = QHBoxLayout(hero)
        hero_margin = UIScaler.pixel(14)
        layout_hero.setContentsMargins(hero_margin, hero_margin, hero_margin, hero_margin)
        layout_hero.setSpacing(UIScaler.pixel(12))
        layout_hero.addWidget(self.label_icon)
        layout_hero.addLayout(layout_text, stretch=1)
        layout_hero.addWidget(self.button_notes)
        layout_hero.addWidget(self.button_update)
        layout_content.addWidget(hero)

        # State cards
        self.card_game = HomeCard(content, "Game", GLYPH_GAME, icon_family)
        self.card_overlay = HomeCard(content, "Overlay", GLYPH_LOCKED, icon_family)
        self.button_lock = self.card_overlay.add_action("Lock Overlay", self.toggle_lock, primary=True)
        self.card_preset = HomeCard(content, "Preset", GLYPH_PRESET, icon_family,
                                    lambda: select_page("preset"), tr("Open presets"))
        self.card_widget = HomeCard(content, "Overlays", GLYPH_OVERLAYS, icon_family,
                                    lambda: select_page("widget"), tr("Open overlays"))
        self.card_module = HomeCard(content, "Module", GLYPH_MODULES, icon_family,
                                    lambda: select_page("module"), tr("Open modules"))
        self.card_last = HomeCard(content, "Last Session", GLYPH_HISTORY, icon_family,
                                  lambda: self.open_tool("driver_stats_viewer.DriverStatsViewer"),
                                  tr("Open driver stats"))
        self.card_start = HomeCard(content, "Before Driving", GLYPH_START, icon_family)
        self.card_start.set_text(
            f"<b>{html.escape(tr('Game Setup'))}</b>",
            html.escape(tr("Set the game display mode to Borderless or Windowed (exclusive fullscreen hides "
                           "the overlay). Le Mans Ultimate: enable Settings > Gameplay > Enable plugins. "
                           "rFactor 2: install the shared memory plugin.")))
        self.cards = (
            self.card_game, self.card_overlay, self.card_preset,
            self.card_widget, self.card_module, self.card_last,
        )
        self.grid = QGridLayout()
        self.grid.setSpacing(UIScaler.pixel(10))
        layout_content.addLayout(self.grid)

        # Quick access: tools, pages & actions chosen by user (Customize, or right-click)
        self._select_page = select_page
        self._icon_family = icon_family
        label_quick = QLabel(tr("Quick Access"), content)
        label_quick.setObjectName("homeSectionTitle")
        self.button_customize = QPushButton(tr("Customize..."), content)
        self.button_customize.setObjectName("homeLink")
        self.button_customize.setToolTip(tr("Add, remove or reorder quick access buttons"))
        self.button_customize.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button_customize.clicked.connect(self.customize_quick_access)
        layout_quick_title = QHBoxLayout()
        layout_quick_title.addWidget(label_quick)
        layout_quick_title.addWidget(self.button_customize)
        layout_quick_title.addStretch(1)
        layout_content.addLayout(layout_quick_title)
        self.quick_box = QWidget(content)
        self.quick_box.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.quick_box.customContextMenuRequested.connect(self.show_quick_menu)
        self.quick_grid = QGridLayout(self.quick_box)
        self.quick_grid.setContentsMargins(0, 0, 0, 0)
        self.quick_grid.setSpacing(UIScaler.pixel(8))
        self.label_quick_empty = QLabel(
            tr("No quick access button: use Customize... to add tools, pages or actions."), self.quick_box)
        self.label_quick_empty.setEnabled(False)
        self.quick_buttons: list[QWidget] = []
        self.build_quick_buttons()
        layout_content.addWidget(self.quick_box)

        tip = QLabel(tr("Tip: press Ctrl+K to find any widget, option, tool or preset. "
                        "Drop a preset or plugin file on this window to import it."), content)
        tip.setWordWrap(True)
        tip.setEnabled(False)
        layout_content.addWidget(tip)
        layout_content.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        layout_main = QVBoxLayout(self)
        layout_main.setContentsMargins(0, 0, 0, 0)
        layout_main.addWidget(scroll)

        self.arrange(self.column_count(self.width()))
        app_signal.updates.connect(self.refresh_version)
        # Game state changes without refresh signal
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_live)
        self._timer.start(1000)
        notifier().changed.connect(self.refresh_last_session)  # logos fetched from game meanwhile
        self.refresh()

    # Quick access
    def build_quick_buttons(self):
        """Quick access buttons from setting, in order (rebuilt after customizing)"""
        from .tools_view import ToolCard

        for button in self.quick_buttons:
            self.quick_grid.removeWidget(button)
            button.deleteLater()
        entries = quick_access_entries()
        self.quick_buttons = []
        for key in current_quick_items():
            entry = entries[key]
            label = tr(entry.label)
            if key in QUICK_SHORTCUTS:
                label = f"{label} ({QUICK_SHORTCUTS[key]})"
            glyph = entry.glyph if self._icon_family else entry.letter
            card = ToolCard(label, glyph, self._icon_family, self.quick_box)
            card.setObjectName(f"quick_{key}")
            card.clicked.connect(lambda _=False, entry=entry: self.run_quick_entry(entry))
            self.quick_buttons.append(card)
        self.label_quick_empty.setHidden(bool(self.quick_buttons))
        self.rearrange()

    def run_quick_entry(self, entry: QuickEntry):
        """Open tool or page, or run action"""
        if entry.kind == "tool":
            self.open_tool(entry.target)
        elif entry.kind == "page":
            self._select_page(entry.target)
        elif entry.key == "command_palette":
            self._window.open_command_palette()
        elif entry.key == "bug_report":
            from .bug_report_view import BugReport

            BugReport(self._window).show()
        elif entry.key == "check_updates":
            update_checker.check(True)
            self.refresh_version()

    def customize_quick_access(self):
        """Choose & order quick access entries (page inside app)"""
        QuickAccessEditor(self._window, self.build_quick_buttons).open()

    def show_quick_menu(self, position):
        menu = QMenu(self)
        menu.addAction(tr("Customize Quick Access...")).triggered.connect(self.customize_quick_access)
        menu.exec(self.quick_box.mapToGlobal(position))

    # Layout
    def column_count(self, width: int) -> int:
        """Card columns for page width: 1 narrow, 2, 3 wide"""
        column = UIScaler.size(COLUMN_WIDTH)
        return max(1, min(3, width // column)) if column > 0 else 2

    def arrange(self, columns: int):
        """Place cards & quick access in columns"""
        if columns == self._columns:
            return
        self._columns = columns
        cards = [card for card in self.cards if not card.isHidden()]
        for card in (*self.cards, self.card_start):
            self.grid.removeWidget(card)
        for index, card in enumerate(cards):
            self.grid.addWidget(card, index // columns, index % columns)
        if not self.card_start.isHidden():  # game setup reminder: full width row below cards
            self.grid.addWidget(self.card_start, (len(cards) + columns - 1) // columns, 0, 1, columns)
        for column in range(3):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)
        for button in (*self.quick_buttons, self.label_quick_empty):
            self.quick_grid.removeWidget(button)
        quick_columns = max(1, min(len(self.quick_buttons), QUICK_COLUMNS[columns]))
        for index, button in enumerate(self.quick_buttons):
            self.quick_grid.addWidget(button, index // quick_columns, index % quick_columns)
        if not self.quick_buttons:
            self.quick_grid.addWidget(self.label_quick_empty, 0, 0)
        for column in range(6):
            self.quick_grid.setColumnStretch(column, 1 if column < quick_columns else 0)

    def rearrange(self):
        """Cards shown or hidden: placed again"""
        columns, self._columns = self._columns, 0
        self.arrange(columns or self.column_count(self.width()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange(self.column_count(event.size().width()))

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_last_session()  # session saved while page was hidden
        self.refresh_live()

    # Actions
    def open_tool(self, path: str):
        from .tools_view import open_tool

        open_tool(path, self._window)

    def toggle_lock(self):
        octrl.toggle.lock()
        self.refresh_live()

    def show_release_notes(self):
        """What's new in running version (local changelog in app language, works offline)"""
        from ..version_check import parse_version_string
        from .release_notes import ReleaseNotesDialog

        dialog = ReleaseNotesDialog(self._window, current_release_notes(language=current_language()),
                                    parse_version_string(base_version()), (0, 0, 0))
        dialog.button_install.hide()  # running version: nothing to install
        dialog.open()

    def update_action(self):
        """Update available: its notes & install, else check now"""
        if update_checker.is_updates():
            from .notification import UpdatesNotifyButton

            button = self._window.findChild(UpdatesNotifyButton)
            if button is not None:
                button.show_release_notes()
                return
        update_checker.check(True)
        self.refresh_version()

    # Refresh
    @Slot(bool)  # type: ignore[operator]
    def refresh(self):
        """Refresh all cards"""
        preset = html.escape(cfg.filename.setting[:-5])
        locked = f" <span style='font-weight:normal'>({tr('locked')})</span>" if (
            cfg.filename.setting in cfg.user.filelock) else ""
        autoload = tr("Auto Load Primary Preset") + ": " + (
            tr("On") if cfg.application["enable_auto_load_preset"] else tr("Off"))
        self.card_preset.set_text(f"<b>{preset}</b>{locked}", autoload)
        self.card_widget.set_text(
            f"<b>{wctrl.number_active}</b> / {wctrl.number_total}", tr("Enabled"))
        self.card_module.set_text(
            f"<b>{mctrl.number_active}</b> / {mctrl.number_total}", tr("Enabled"))
        self.refresh_header()
        self.refresh_version()
        self.refresh_last_session()
        self.refresh_live()

    def refresh_header(self):
        """App icon matching app theme (light / dark)"""
        dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        size = UIScaler.pixel(48)
        pixmap = QPixmap(app_icon_file(dark))
        if not pixmap.isNull():
            ratio = self.devicePixelRatioF()
            pixmap = pixmap.scaled(round(size * ratio), round(size * ratio), Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            pixmap.setDevicePixelRatio(ratio)
        self.label_icon.setPixmap(pixmap)
        self.label_icon.setHidden(pixmap.isNull())

    @Slot(bool)  # type: ignore[operator]
    def refresh_version(self, _checking: bool = False):
        """Version, update chip & button"""
        game = api.name if cfg.user.setting else ""
        self.label_version.setText(" · ".join(text for text in (f"{tr('Version')} {VERSION}", game) if text))
        if update_checker.is_checking():
            self.chip_update.setHidden(True)
            self.button_update.setText(tr("Checking..."))
            self.button_update.setEnabled(False)
            self.button_update.setObjectName("")
        elif update_checker.is_updates():
            version = ".".join(str(part) for part in update_checker.latest_version())
            self.chip_update.setText(f"{tr('Update Available')} · v{version}")
            self.chip_update.setHidden(False)
            self.button_update.setText(tr("See Update"))
            self.button_update.setEnabled(True)
            self.button_update.setObjectName("homePrimary")
        else:
            self.chip_update.setHidden(True)
            self.button_update.setText(tr("Check for Updates"))
            self.button_update.setEnabled(True)
            self.button_update.setObjectName("")
            self.button_update.setToolTip(trm(update_checker.message()))
        self.button_update.style().unpolish(self.button_update)  # object name changes style
        self.button_update.style().polish(self.button_update)

    def refresh_last_session(self):
        """Last driven session from driver stats, card hidden if none (refreshed when page shown)"""
        if not self.isVisible():  # hidden page or window: refreshed by showEvent
            return
        record = last_session()
        hidden = record is None
        if record is not None:
            self.card_last.set_text(*session_record_text(record))
            self.card_last.set_logos(record_logos(record))
        if self.card_last.isHidden() != hidden:
            self.card_last.setHidden(hidden)
            self.rearrange()

    def refresh_live(self):
        """Refresh game, session & overlay state"""
        if not self.isVisible():  # hidden page (other page shown) or window: nothing to refresh
            return
        state, running = api_state_text()
        dot = status_color("success" if running else "inactive")
        session = session_text() if running else ""
        if session:
            detail = session
        elif running:
            detail = tr("Running")
        else:
            detail = tr("Not running") if state == "not running" else tr(state)
        self.card_game.set_text(f"<span style='color:{dot}'>●</span> <b>{html.escape(api.name)}</b>", detail)
        self.card_game.set_logos(live_logos() if session else ())
        if self.card_start.isHidden() != running:  # game setup reminder while game not running
            self.card_start.setHidden(running)
            self.rearrange()

        locked = cfg.overlay["fixed_position"]
        self.card_overlay.set_glyph(GLYPH_LOCKED if locked else GLYPH_UNLOCKED)
        flags = (
            tr("Auto Hide") if cfg.overlay["auto_hide"] else "",
            tr("VR Compatibility") if cfg.overlay["vr_compatibility"] else "",
        )
        detail = " · ".join(flag for flag in flags if flag)
        if not locked:
            detail = " · ".join(text for text in (tr("Drag overlays to move them"), detail) if text)
        self.card_overlay.set_text(f"<b>{tr('Locked') if locked else tr('Unlocked')}</b>", detail)
        text = tr("Unlock Overlay") if locked else tr("Lock Overlay")
        if self.button_lock.text() != text:
            self.button_lock.setText(text)
