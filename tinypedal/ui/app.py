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
Main application window
"""

import logging
from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, cast

import shiboken6
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPalette,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import app_signal, loader
from .. import regex_pattern as rxp
from ..api_control import api
from ..const_app import APP_NAME, VERSION
from ..const_file import ConfigType
from ..i18n import install_qt_translation, set_language, tr, trm
from ..module_control import mctrl, wctrl
from ..overlay_control import octrl
from ..setting import cfg
from ..userfile.layout_profile import screen_key
from . import (
    app_icon_file,
    draw_focus_ring,
    install_message_icons,
    resolve_color_theme,
    set_style_palette,
    set_style_window,
    status_color,
    system_dark_mode,
)
from ._common import MODIFIED_MARKER, BaseDialog, DialogSingleton, UIScaler
from .lazy_page import LazyPage, PageRelease, release_quick_views
from .menu import APIMenu, ConfigMenu, HelpMenu, OverlayMenu, ToolsMenu, WindowMenu, open_config_application
from .nav_rail import NAV_PAGES, PAGE_INDEX, RailEditor, current_rail_items, rail_entries
from .notification import NotifyBar
from .ordered_picker import icon_font_family
from .pace_notes_view import PaceNotesControl, PaceNotesPlayback
from .toast import show_toast
from .tools_view import RENAMED_TOOLS, TOOL_SECTIONS, ToolsView, open_tool
from .window_geometry import (
    default_frame_rect,
    keep_on_screen,
    max_content_size,
    page_minimum_size,
    screen_for,
    set_frame_rect,
)

if TYPE_CHECKING:
    from .preset_view import PresetList

logger = logging.getLogger(__name__)


# Rail overlay toggles: (overlay option, tooltip, icon glyph, fallback letter)
RAIL_TOGGLES = (
    ("fixed_position", "Lock Overlay", "\ue72e", "L"),  # lock
    ("auto_hide", "Auto Hide", "\ue7b3", "H"),  # red eye
    ("vr_compatibility", "VR Compatibility", "\ue7f4", "V"),  # tv monitor
)


def show_restored(window: QWidget):
    """Show hidden (tray) or minimized window as it was: maximized stays maximized"""
    if window.isFullScreen():
        window.showFullScreen()
    elif window.isMaximized():
        window.showMaximized()
    else:
        window.showNormal()


def build_page(key: str, host: QWidget, view: "TabView", window: QWidget, icon_family: str) -> QWidget:
    """Main window page of navigation key, its module imported on first use (see LazyPage)"""
    if key == "home":
        from .home_view import HomeView

        return HomeView(host, window, lambda name: view.select_page(PAGE_INDEX[name]), icon_family)
    if key == "widget":
        from .overlay_view import OverlayView

        return OverlayView(host, wctrl)
    if key == "module":
        from .module_view import ModuleList

        return ModuleList(host, mctrl)
    if key == "preset":
        from .preset_view import PresetList

        return PresetList(host)
    if key == "spectate":
        from .spectate_view import SpectateList

        return SpectateList(host)
    if key == "pacenotes":
        return PaceNotesControl(host, view.pace_notes)
    if key == "hotkey":
        from .hotkey_view import HotkeyList

        return HotkeyList(host)
    return ToolsView(host, icon_family, window)


def safe_mode_enabled() -> bool:
    """App started in safe mode: tool pages left open are not reopened (one may have crashed it)"""
    from .. import safe_mode

    return safe_mode.state.enabled


class NavButton(QAbstractButton):
    """Navigation rail entry: icon over a short label, accent pill when selected"""

    def __init__(self, text: str, glyph: str, letter: str, icon_family: str, parent=None, compact: bool = False):
        super().__init__(parent)
        self.compact = compact  # icon only, label in tooltip
        self.dot_color: QColor | None = None  # status dot drawn at top right
        self.modified = False  # page has unsaved changes: marker before label, see set_modified
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(text)
        # Same size whatever window height: rail entries scroll instead of shrinking
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.glyph = glyph if icon_family else letter
        self.icon_font = QFont(icon_family) if icon_family else QFont(self.font())
        if not icon_family:
            self.icon_font.setBold(True)

    def sizeHint(self) -> QSize:
        line = self.fontMetrics().height()
        if self.compact:
            return QSize(round(line * 2.2), round(line * 2.2))
        return QSize(round(line * 4.4), round(line * 3.4))

    def set_modified(self, modified: bool):
        """Page of entry has unsaved changes: marker before label, noted in tooltip"""
        if modified == self.modified:
            return
        self.modified = modified
        tooltip = self.toolTip().removeprefix(MODIFIED_MARKER)
        self.setToolTip(f"{MODIFIED_MARKER}{tooltip}" if modified else tooltip)
        self.setAccessibleDescription(tr("Unsaved changes") if modified else "")
        self.update()

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
        muted = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText)
        area = QRectF(self.rect()).adjusted(4, 2, -4, -2)
        radius = area.height() * 0.22
        if self.isChecked():
            fill = QColor(accent)
            fill.setAlphaF(0.18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(area, radius, radius)
            if not self.compact:  # page marker, toggles only use the fill
                bar_h = area.height() * 0.42
                painter.setBrush(accent)
                painter.drawRoundedRect(QRectF(area.left() - 3, area.center().y() - bar_h / 2, 3, bar_h), 1.5, 1.5)
        elif self.underMouse():
            fill = QColor(text)
            fill.setAlphaF(0.07)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(area, radius, radius)
        draw_focus_ring(painter, self, area, radius)
        color = accent if self.isChecked() else (text if self.underMouse() else muted)
        painter.setPen(color)
        icon_font = QFont(self.icon_font)
        if self.compact:
            icon_font.setPixelSize(round(area.height() * 0.44))
            painter.setFont(icon_font)
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, self.glyph)
            if self.dot_color is not None:
                dot = area.height() * 0.22
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self.dot_color)
                painter.drawEllipse(QRectF(area.right() - dot * 1.4, area.top() + dot * 0.4, dot, dot))
            return
        icon_font.setPixelSize(round(area.height() * 0.34))
        painter.setFont(icon_font)
        icon_rect = QRectF(area.left(), area.top() + area.height() * 0.1, area.width(), area.height() * 0.5)
        painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, self.glyph)
        label_font = QFont(self.font())
        label_font.setPixelSize(max(round(area.height() * 0.2), 8))
        label_font.setBold(self.isChecked())
        painter.setFont(label_font)
        painter.setPen(text if self.isChecked() else color)
        label_rect = QRectF(area.left(), area.top() + area.height() * 0.6, area.width(), area.height() * 0.32)
        label_text = f"{MODIFIED_MARKER}{self.text()}" if self.modified else self.text()
        label = QFontMetricsF(label_font).elidedText(label_text, Qt.TextElideMode.ElideRight, label_rect.width())
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label)


class ScrollFade(QWidget):
    """Fade over top or bottom edge of a scroll area, shown while entries are hidden that way"""

    def __init__(self, scroll: QScrollArea, at_top: bool):
        super().__init__(scroll)
        self._scroll = scroll
        self.at_top = at_top
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        bar = scroll.verticalScrollBar()
        bar.valueChanged.connect(self.update_state)
        bar.rangeChanged.connect(self.update_state)
        scroll.installEventFilter(self)
        self.update_state()

    def eventFilter(self, watched, event):
        if watched is self._scroll and event.type() == QEvent.Type.Resize:
            self.update_state()
        return super().eventFilter(watched, event)

    def update_state(self, *_):
        bar = self._scroll.verticalScrollBar()
        hidden = bar.value() > bar.minimum() if self.at_top else bar.value() < bar.maximum()
        viewport = self._scroll.viewport().geometry()
        height = max(self.fontMetrics().height() * 2, 1)
        top = viewport.top() if self.at_top else viewport.bottom() + 1 - height
        self.setGeometry(viewport.left(), top, viewport.width(), height)
        self.setVisible(hidden)
        if hidden:
            self.raise_()

    def paintEvent(self, event):
        painter = QPainter(self)
        color = self.palette().color(QPalette.ColorGroup.Active, QPalette.ColorRole.Window)
        clear = QColor(color)
        clear.setAlpha(0)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, color if self.at_top else clear)
        gradient.setColorAt(1, clear if self.at_top else color)
        painter.fillRect(self.rect(), gradient)
        # Chevron toward hidden entries
        pen = QPen(self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText))
        pen.setWidthF(1.5)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(pen)
        center = self.width() / 2
        size = self.height() * 0.18
        y = self.height() * (0.3 if self.at_top else 0.7)
        tip = y - size / 2 if self.at_top else y + size / 2
        base = y + size / 2 if self.at_top else y - size / 2
        painter.drawLine(QPointF(center - size, base), QPointF(center, tip))
        painter.drawLine(QPointF(center, tip), QPointF(center + size, base))


class DialogPage(QWidget):
    """Dialog shown as page inside app: title & close button, then dialog (scrolled if larger than page)

    Emits closed when dialog closes itself (close button, Save & close, Esc): page is then removed.
    Emits modified_changed when dialog unsaved changes marker is shown or cleared.
    Emits minimum_changed when page area minimum asked by dialog changes, see minimum_size.
    """

    closed = Signal(QWidget)
    modified_changed = Signal()
    minimum_changed = Signal()

    def __init__(self, dialog: BaseDialog, parent=None, opener: "DialogPage | None" = None):
        super().__init__(parent)
        self.setObjectName("dialogPage")
        # Page never sets main window minimum size (open pages are kept, hidden, in page stack)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.dialog = dialog
        self.opener = opener  # page this one was opened from (lap library of lap viewer...), kept open with it
        self._closed = False
        self._closable = True  # see set_closable
        self._own_close_buttons: list[QAbstractButton] | None = None
        self.title = title = dialog.windowTitle().removesuffix(f" - {APP_NAME}")
        label_title = QLabel(title, self)
        label_title.setObjectName("dialogPageTitle")
        font = label_title.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.15)
        label_title.setFont(font)
        self._label_title = label_title
        dialog.modified_changed.connect(self.show_modified)
        self.show_modified()
        button_close = QPushButton(tr("Close"), self)
        button_close.setToolTip(tr("Close and go back to previous page"))
        button_close.clicked.connect(dialog.close)
        self._button_close = button_close
        layout_title = QHBoxLayout()
        layout_title.setContentsMargins(UIScaler.pixel(10), UIScaler.pixel(6), UIScaler.pixel(10), 0)
        layout_title.addWidget(label_title, stretch=1)
        layout_title.addWidget(button_close)
        self._layout_title = layout_title

        dialog.in_app_page = True  # shown as page, see embedded_host
        # Size the dialog was designed for as window (resize & minimum size), main window grows
        # to it if screen allows, while page itself only needs its layout minimum (scrolled below)
        preferred = dialog.minimumSize().expandedTo(dialog.minimumSizeHint())
        if dialog.testAttribute(Qt.WidgetAttribute.WA_Resized):
            preferred = preferred.expandedTo(dialog.size())
        self.preferred_size = preferred
        page_minimum_changed = getattr(dialog, "page_minimum_changed", None)
        if page_minimum_changed is not None:
            page_minimum_changed.connect(self.minimum_changed)
        dialog.setMinimumSize(0, 0)
        dialog.setWindowFlags(Qt.WindowType.Widget)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(dialog)
        dialog.installEventFilter(self)
        dialog.destroyed.connect(self._dialog_destroyed)
        dialog.show()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(layout_title)
        layout.addWidget(scroll, stretch=1)

    def is_modified(self) -> bool:
        """Dialog shows unsaved changes marker"""
        return self.dialog is not None and self.dialog.is_marked_modified()

    def has_unsaved_changes(self) -> bool:
        """Closing would ask to save changes (marker shown or not)"""
        return self.is_modified() or (self.dialog is not None and self.dialog.has_unsaved_changes())

    def display_title(self) -> str:
        """Title with unsaved changes marker (page title, open pages menu)"""
        return f"{MODIFIED_MARKER}{self.title}" if self.is_modified() else self.title

    def show_modified(self, *_):
        """Unsaved changes marker shown or cleared"""
        modified = self.is_modified()
        self._label_title.setText(self.display_title())
        self._label_title.setToolTip(tr("Unsaved changes") if modified else "")
        self.modified_changed.emit()

    def set_closable(self, closable: bool):
        """Close buttons (title & dialog own) & Esc key, off for tools of navigation rail (pages like any other)"""
        if closable == self._closable:
            return
        self._closable = closable
        self._button_close.setVisible(closable)
        if self._own_close_buttons is None:  # found once, dialog layout does not change
            self._own_close_buttons = self.dialog_close_buttons()
        for button in self._own_close_buttons:
            button.setVisible(closable)

    def dialog_close_buttons(self) -> list[QAbstractButton]:
        """Close buttons of dialog itself (not of dialogs opened from it)"""
        if self.dialog is None:
            return []
        close_text = tr("Close")
        buttons = []
        for button in self.dialog.findChildren(QAbstractButton):
            if button.text() != close_text:
                continue
            owner = button.parentWidget()
            while owner is not None and not isinstance(owner, BaseDialog):
                owner = owner.parentWidget()
            if owner is self.dialog:
                buttons.append(button)
        return buttons

    @property
    def minimum_size(self) -> QSize:
        """Page area minimum while page is shown (QML toolbars & panels are cut below it, they do not
        scroll): dialog page_minimum_size(), if any, see TabView.update_page_minimum"""
        minimum = getattr(self.dialog, "page_minimum_size", None)
        return minimum() if callable(minimum) else QSize(0, 0)

    def title_height(self) -> int:
        return self._layout_title.sizeHint().height()

    def eventFilter(self, watched, event):
        # Hidden by itself (not because page is hidden): dialog closed
        if watched is self.dialog and event.type() == QEvent.Type.Hide and self.dialog.isHidden():
            self.notify_closed()
        # Esc does not close pages without close button
        if (watched is self.dialog and not self._closable and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape):
            return True
        return super().eventFilter(watched, event)

    def _dialog_destroyed(self, *_):
        self.dialog = None  # type: ignore[assignment]
        self.notify_closed()

    def notify_closed(self):
        if not self._closed:
            self._closed = True
            self.closed.emit(self)


class TabView(QWidget):
    """Main view: navigation rail on the left, page on the right"""

    def __init__(self, parent):
        super().__init__(parent)
        # Notify bar
        notify_bar = NotifyBar(self)
        notify_bar.presetlocked.clicked.connect(self.select_preset_tab)
        notify_bar.spectate.clicked.connect(self.select_spectate_tab)
        notify_bar.pacenotes.clicked.connect(self.select_pacenotes_tab)
        notify_bar.hotkey.clicked.connect(self.select_hotkey_tab)

        # Pages: each built when first shown or selected (memory, startup time)
        icon_family = icon_font_family()
        self.pace_notes = PaceNotesPlayback(self)  # pace notes audio plays while its page is not built
        self._lazy_pages = {
            key: LazyPage(self, partial(build_page, key, view=self, window=parent, icon_family=icon_family))
            for key, *_ in NAV_PAGES
        }
        self._pages = QStackedWidget(self)
        self._pages.setObjectName("pageStack")
        # Pages never squeezed until they show broken: window minimum follows (window layout)
        self._pages.setMinimumSize(page_minimum_size())
        for page in self._lazy_pages.values():
            self._pages.addWidget(page)
        self._page_release = PageRelease(self, self._lazy_pages.values())  # window hidden: pages freed

        # Navigation rail
        rail = QWidget(self)
        rail.setObjectName("navRail")
        # Rail keeps its width when window is at its minimum size (squeezed, its entries vanished)
        rail.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        layout_rail = QVBoxLayout(rail)
        margin = UIScaler.pixel(6)
        layout_rail.setContentsMargins(margin, margin, margin, margin)
        layout_rail.setSpacing(UIScaler.pixel(2))
        self._nav = QButtonGroup(self)
        self._nav.setExclusive(True)
        self._icon_family = icon_family
        self._dialog_parent = parent
        self._return_index = 0  # page shown again when last dialog page closes
        self._page_history: list[QWidget] = []  # pages shown before, see previous_shown
        self._going_back = False
        self._restoring_pages = False  # reopening pages: window not brought to front
        self._closing_pages = False  # closing several pages (quit, Close All) or view replaced: left pages not closed
        self._left_pages_timer = QTimer(self)  # pages left for another one closed once page change is done
        self._left_pages_timer.setSingleShot(True)
        self._left_pages_timer.timeout.connect(self.close_left_pages)
        self.track_pages = False  # shown page remembered on change, once startup pages are restored
        self._size_before_pages: QSize | None = None  # window size before a dialog page grew it
        self._pos_before_pages: QPoint | None = None  # window position before growing moved it inside screen
        self._user_resized = False  # window resized by user while grown
        self._user_moved = False  # window moved by user while grown
        self._grown_for: set[QWidget] = set()  # open pages needing grown window size
        self._fit_pending: list[DialogPage] = []  # pages shown before view was laid out, see fit_window
        self._rail = rail
        # Rail entries scrolled (wheel or thin scroll bar) when window is too short, quick actions stay below
        rail_list = QWidget()
        rail_list.setObjectName("navRailList")
        layout_list = QVBoxLayout(rail_list)
        layout_list.setContentsMargins(0, 0, 0, 0)
        layout_list.setSpacing(0)
        self._rail_items = QVBoxLayout()
        self._rail_items.setSpacing(UIScaler.pixel(2))
        layout_list.addLayout(self._rail_items)
        layout_list.addStretch(1)
        self._rail_list = rail_list
        self._rail_scroll = QScrollArea(rail)
        self._rail_scroll.setObjectName("navRailScroll")
        self._rail_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._rail_scroll.setWidgetResizable(True)
        self._rail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rail_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._rail_scroll.setWidget(rail_list)
        self._rail_fades = (ScrollFade(self._rail_scroll, True), ScrollFade(self._rail_scroll, False))
        self._rail_scroll.viewport().setAutoFillBackground(False)
        rail_list.setAutoFillBackground(False)
        self._rail_shortcuts: list[QShortcut] = []
        self.build_rail_items()
        for widget in (rail, rail_list):
            widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            widget.customContextMenuRequested.connect(
                lambda position, source=widget: self.show_rail_menu(source.mapTo(rail, position)))
        layout_rail.addWidget(self._rail_scroll, stretch=1)
        self._nav.idClicked.connect(self.select_page)

        # Quick actions: overlay toggles, settings, API status
        layout_quick = QGridLayout()
        layout_quick.setSpacing(UIScaler.pixel(2))
        self._toggles: dict[str, NavButton] = {}
        for index, (option, label, glyph, letter) in enumerate(RAIL_TOGGLES):
            button = NavButton(tr(label), glyph, letter, icon_family, rail, compact=True)
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, name=option: self.toggle_overlay(name))
            self._toggles[option] = button
            layout_quick.addWidget(button, index // 2, index % 2)
        button_config = NavButton(f"{tr('Config')} (Ctrl+,)", "\ue713", "C", icon_family, rail, compact=True)
        button_config.setCheckable(False)
        button_config.clicked.connect(lambda: open_config_application(parent, ""))  # page as left
        layout_quick.addWidget(button_config, 1, 1)
        self._button_api = NavButton(tr("API"), "\ue968", "A", icon_family, rail, compact=True)  # network
        self._button_api.setCheckable(False)
        self._button_api.clicked.connect(self.show_api_menu)
        self._menu_api = APIMenu(tr("API"), parent)
        layout_quick.addWidget(self._button_api, 2, 1)
        button_search = NavButton(f"{tr('Command Palette')} (Ctrl+K)", "\ue721", "K", icon_family, rail, compact=True)
        button_search.setCheckable(False)
        button_search.clicked.connect(parent.open_command_palette)
        layout_quick.addWidget(button_search, 2, 0)
        # Pages of tools & config dialogs left open, shown while any
        self._button_pages = NavButton(tr("Open Pages"), "", "P", icon_family, rail, compact=True)
        self._button_pages.setCheckable(False)
        self._button_pages.clicked.connect(self.show_pages_menu)
        self._button_pages.setVisible(False)
        layout_quick.addWidget(self._button_pages, 3, 0)
        layout_rail.addLayout(layout_quick)
        self._rail_timer = QTimer(self)
        self._rail_timer.timeout.connect(self.refresh_rail)
        self._rail_timer.start(1000)  # also follows changes from hotkeys, tray menu & API
        self.refresh_rail()

        last_page = cfg.application["last_page_index"]
        self.set_current_index(last_page if 0 <= last_page < len(NAV_PAGES) else 0)
        self._pages.currentChanged.connect(self.page_changed)
        self._pages.currentChanged.connect(self.schedule_close_left_pages)
        self._pages.currentChanged.connect(self.update_page_minimum)

        layout_body = QHBoxLayout()
        layout_body.setContentsMargins(0, 0, 0, 0)
        layout_body.setSpacing(0)
        layout_body.addWidget(rail)
        layout_body.addWidget(self._pages, stretch=1)

        # Main view
        layout_main = QVBoxLayout()
        layout_main.setContentsMargins(0, 0, 0, 0)
        layout_main.setSpacing(0)
        layout_main.addLayout(layout_body, stretch=1)
        layout_main.addWidget(notify_bar)
        self.setLayout(layout_main)

        # Connect app signal
        app_signal.updates.connect(notify_bar.updates.checking)
        notify_bar.updates.restore()  # view rebuilt (language change): update notice kept
        app_signal.refresh.connect(notify_bar.refresh)

        app_signal.refresh.connect(self.pace_notes.refresh)
        for page in self._lazy_pages.values():
            app_signal.refresh.connect(page.refresh)
        app_signal.refresh.connect(self.refresh_rail)

    @property
    def preset_tab(self) -> "PresetList":
        """Preset page (built if not shown yet)"""
        return cast("PresetList", self._lazy_pages["preset"].ensure_page())

    def build_rail_items(self):
        """(Re)create rail entries from setting, Ctrl+1..9 open the first 9 entries"""
        for button in self._nav.buttons():
            self._nav.removeButton(button)
        while self._rail_items.count():
            item = self._rail_items.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        for shortcut in self._rail_shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._rail_shortcuts = []
        entries = rail_entries()
        for position, key in enumerate(current_rail_items(), 1):
            entry = entries[key]
            button = NavButton(tr(entry.label), entry.glyph, entry.letter, self._icon_family, self._rail)
            hint = f" (Ctrl+{position})" if position <= 9 else ""
            button.setToolTip(f"{tr(entry.tooltip)}{hint}")
            if entry.page >= 0:
                self._nav.addButton(button, entry.page)
                action = (lambda page=entry.page: self.select_page(page))
            else:  # tool: its page selected like other pages, see sync_rail_selection
                button.setObjectName(f"railTool:{entry.dialog}")
                action = (lambda path=entry.dialog: open_tool(path, self._dialog_parent))
                button.clicked.connect(lambda _=False, run=action: (run(), self.sync_rail_selection()))
            self._rail_items.addWidget(button)
            if position <= 9:
                shortcut = QShortcut(QKeySequence(f"Ctrl+{position}"), self)
                shortcut.activated.connect(action)
                self._rail_shortcuts.append(shortcut)
        button = self._nav.button(self._pages.currentIndex())
        if button is not None:
            button.setChecked(True)
        # Rail keeps its width when scroll bar shows (entries never squeezed)
        scroll_bar = self._rail_scroll.verticalScrollBar().sizeHint().width()
        self._rail_scroll.setMinimumWidth(self._rail_list.sizeHint().width() + scroll_bar)
        if hasattr(self, "_button_pages"):
            self.refresh_open_pages()

    def show_rail_menu(self, position):
        """Rail context menu: customize entries"""
        menu = QMenu(self)
        menu.addAction(tr("Customize Navigation Bar...")).triggered.connect(self.open_rail_editor)
        menu.exec(self._rail.mapToGlobal(position))

    def open_rail_editor(self):
        RailEditor(self, self.build_rail_items).open()

    # Dialogs shown as pages inside app (tools, config, about...), see BaseDialog.show
    def dialog_pages(self) -> list["DialogPage"]:
        """Open dialog pages"""
        return [
            page for page in (self._pages.widget(index) for index in range(self._pages.count()))
            if isinstance(page, DialogPage)
        ]

    def find_dialog_page(self, class_name: str, title: str = "") -> DialogPage | None:
        """Open dialog page of class (and title if set), None if not found"""
        for page in self.dialog_pages():
            dialog = page.dialog
            if dialog is not None and type(dialog).__name__ == class_name and (not title or dialog.windowTitle() == title):
                return page
        return None

    def activate_dialog_page(self, class_name: str, title: str = "") -> bool:
        """Show open dialog page of class (and title if set), True if found"""
        page = self.find_dialog_page(class_name, title)
        if page is not None:
            self.show_page_widget(page)
        return page is not None

    def show_dialog_page(self, dialog, bring_to_front: bool = True) -> bool:
        """Show dialog as page, same dialog already open is shown instead, True if shown in app

        Not brought to front: page shown in app without showing a hidden or minimized window.
        """
        restoring, self._restoring_pages = self._restoring_pages, self._restoring_pages or not bring_to_front
        try:
            existing = self.find_dialog_page(type(dialog).__name__, dialog.windowTitle())
            if existing is not None:
                dialog.shown_instead = existing.dialog  # caller works on open one, see shown_dialog
                self.show_page_widget(existing)
                dialog.deleteLater()  # second copy of open dialog: never shown
                return True
            page = DialogPage(dialog, self._pages, self.page_of(dialog.parentWidget()))
            page.closed.connect(self.close_dialog_page)
            page.modified_changed.connect(self.refresh_open_pages)
            page.modified_changed.connect(self.schedule_close_left_pages)
            page.minimum_changed.connect(self.update_page_minimum)
            self._pages.addWidget(page)
            self.show_page_widget(page)
            self.refresh_open_pages()
        finally:
            self._restoring_pages = restoring
        return True

    @staticmethod
    def page_of(widget: QWidget | None) -> DialogPage | None:
        """Dialog page showing widget, None if widget is not on a dialog page"""
        while widget is not None:
            if isinstance(widget, DialogPage):
                return widget
            widget = widget.parentWidget()
        return None

    def show_dialog(self, dialog: QWidget) -> bool:
        """Show page of open dialog (or its window), True if found"""
        for page in self.dialog_pages():
            if page.dialog is dialog:
                self.show_page_widget(page)
                return True
        if dialog.isWindow() and dialog.isVisible():
            dialog.raise_()
            dialog.activateWindow()
            return True
        return False

    def fit_window(self, page: "DialogPage", resize: bool = True):
        """Grow main window to page preferred size (within screen)

        Size is kept while browsing pages (no resize back and forth), restored once every page
        needing it is closed, see close_dialog_page. Grown window frame (title bar included)
        stays inside screen: window moved if it would go past screen edge, moved back once restored.
        """
        window = self.window()
        if window.isMaximized() or window.isFullScreen():
            return
        if not self.isVisible():  # view not laid out yet (startup, rebuilt in new language): fitted once shown
            self._fit_pending.append(page)
            return
        extra_width = window.width() - self._pages.width()  # rail & margins
        extra_height = window.height() - self._pages.height() + page.title_height()  # menu, status, title
        largest = max_content_size(window)
        width = min(page.preferred_size.width() + extra_width, largest.width())
        height = min(page.preferred_size.height() + extra_height, largest.height())
        before = self._size_before_pages
        if before is not None and (width > before.width() or height > before.height()):
            self._grown_for.add(page)  # relies on grown size
        if not resize or (width <= window.width() and height <= window.height()):
            return
        if self._size_before_pages is None:
            self._size_before_pages = window.size()
            self._pos_before_pages = window.pos()
            self._user_resized = self._user_moved = False
        self._grown_for.add(page)
        window.resize(max(width, window.width()), max(height, window.height()))
        keep_on_screen(window)

    def restore_window_size(self):
        """Size (and position) before a page grew window, unless user resized (or moved) window meanwhile"""
        if self._size_before_pages is None:
            return
        window = self.window()
        if not window.isMaximized() and not window.isFullScreen():
            if not self._user_resized:
                window.resize(self._size_before_pages)
            if not self._user_moved and self._pos_before_pages is not None:
                window.move(self._pos_before_pages)
        self._size_before_pages = self._pos_before_pages = None

    def window_resized_by_user(self):
        """Size chosen by user is kept when leaving dialog pages"""
        self._user_resized = True

    def window_moved_by_user(self):
        """Position chosen by user is kept when leaving dialog pages"""
        self._user_moved = True

    def window_base_geometry(self) -> tuple[QSize | None, QPoint | None]:
        """Window size & position before a page grew it, each None if not grown or changed by user
        since: saved for next startup instead of grown ones (page grows window again if reopened)"""
        if self._size_before_pages is None:
            return None, None
        size = None if self._user_resized else self._size_before_pages
        pos = None if self._user_moved else self._pos_before_pages
        return size, pos

    def window_growth(self) -> tuple[QSize | None, QPoint | None, bool, bool]:
        """Window size & position before pages grew it, and whether user changed them since"""
        return self._size_before_pages, self._pos_before_pages, self._user_resized, self._user_moved

    def adopt_window_growth(self, growth: tuple[QSize | None, QPoint | None, bool, bool]):
        """Growth of previous view (rebuilt in new language): size before pages restored once they close"""
        self._size_before_pages, self._pos_before_pages, self._user_resized, self._user_moved = growth

    def fit_pending_pages(self):
        """Pages shown while view was not laid out: window grown for the one shown now, the others noted
        as needing grown size (window back to its size once every such page is closed)"""
        pages, self._fit_pending = self._fit_pending, []
        current = self._pages.currentWidget()
        for page in dict.fromkeys(pages):
            if shiboken6.isValid(page) and self._pages.indexOf(page) >= 0:
                self.fit_window(page, resize=page is current)

    def forget_window_growth(self):
        """Window size set anew (reset): not restored to size before pages anymore"""
        self._size_before_pages = self._pos_before_pages = None
        self._grown_for.clear()

    def showEvent(self, event):
        super().showEvent(event)
        self.update_page_minimum()  # window laid out on its screen: minimum kept within it
        if self._fit_pending:
            QTimer.singleShot(0, self.fit_pending_pages)  # once view geometry is set by window layout

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.scroll_to_selected_entry()  # window made shorter: selected rail entry kept in view

    def rail_fade_height(self) -> int:
        """Height of rail scroll fades (see ScrollFade): entry scrolled into view is kept clear of them"""
        return max(self.fontMetrics().height() * 2, 1)

    def scroll_to_selected_entry(self):
        """Selected rail entry (page or tool) scrolled into view when rail is too short for every entry"""
        for index in range(self._rail_items.count()):
            item = self._rail_items.itemAt(index)
            button = item.widget() if item is not None else None
            if isinstance(button, NavButton) and button.isChecked():
                self._rail_scroll.ensureWidgetVisible(button, 0, self.rail_fade_height())
                return

    def update_page_minimum(self, *_):
        """Page area never squeezed until pages show broken (overlapped or cut): base minimum for
        every page, more for shown page needing it (telemetry viewer...), window minimum follows

        Kept within screen of window (title bar, rail, menu & status bars included), so window
        always fits its screen.
        """
        minimum = page_minimum_size()
        current = self._pages.currentWidget()
        if isinstance(current, DialogPage):
            minimum = minimum.expandedTo(current.minimum_size)
        window = self.window()
        if window.isVisible() and not self._pages.size().isEmpty():
            bars = window.size() - self._pages.size()  # rail, menu & status bars
            minimum = minimum.boundedTo(max_content_size(window) - bars)
        if minimum != self._pages.minimumSize():
            self._pages.setMinimumSize(minimum)
            # Window minimum applied now, not at next layout pass: restoring size before a page
            # (closed now) is not blocked by minimum of that page
            view_layout = self.layout()
            if view_layout is not None:
                view_layout.activate()  # nested layouts too (page stack is in a nested one)
            self.updateGeometry()  # cached minimum of this view in window layout dropped
            window_layout = window.layout()
            if window_layout is not None:
                window_layout.activate()

    def rail_tool_buttons(self) -> dict[str, NavButton]:
        """Rail tool entries by dialog class name"""
        buttons = {}
        for index in range(self._rail_items.count()):
            item = self._rail_items.itemAt(index)
            button = item.widget() if item is not None else None
            if isinstance(button, NavButton) and button.objectName().startswith("railTool:"):
                buttons[button.objectName().rsplit(".", 1)[-1]] = button
        return buttons

    def is_rail_page(self, page: DialogPage) -> bool:
        """Page of a tool in navigation rail: kept like other pages, not listed as open page"""
        return page.dialog is not None and type(page.dialog).__name__ in self.rail_tool_buttons()

    def other_pages(self) -> list[DialogPage]:
        """Open dialog pages not reachable from navigation rail (config, other tools...)"""
        return [page for page in self.dialog_pages() if not self.is_rail_page(page)]

    def sync_rail_selection(self):
        """Rail tool entry selected while its page shows"""
        current = self._pages.currentWidget()
        dialog = current.dialog if isinstance(current, DialogPage) else None
        shown = type(dialog).__name__ if dialog is not None else ""
        for name, button in self.rail_tool_buttons().items():
            if button.isChecked() != (name == shown):
                button.setChecked(name == shown)
            if name == shown:
                self._rail_scroll.ensureWidgetVisible(button, 0, self.rail_fade_height())

    def shown_pages(self) -> set[QWidget]:
        """Shown page & pages it was opened from (lap viewer of its lap library...)"""
        pages: set[QWidget] = set()
        page: QWidget | None = self._pages.currentWidget()
        while page is not None and page not in pages:
            pages.add(page)
            page = page.opener if isinstance(page, DialogPage) else None
        return pages

    def schedule_close_left_pages(self, *_):
        self._left_pages_timer.start(0)

    def close_left_pages(self):
        """Pages left for another one are closed, kept open: shown page (and pages it was opened
        from), pages with unsaved changes (closing would ask to save) & tools of navigation rail"""
        if self._restoring_pages or self._closing_pages:
            return
        if QApplication.activeModalWidget() is not None:  # message box (may be closing pages)
            self._left_pages_timer.start(250)
            return
        pages = self.dialog_pages()
        kept = self.shown_pages()
        for page in pages:
            if self.is_rail_page(page) or page.has_unsaved_changes():
                opener: DialogPage | None = page
                while opener is not None and opener not in kept:
                    kept.add(opener)
                    opener = opener.opener
        closed = False
        for page in reversed(pages):  # pages opened from a page closed first
            if page not in kept and page.dialog is not None and self._pages.indexOf(page) >= 0:
                if page.dialog.close():
                    page.notify_closed()  # hidden page: no hide event, page removed at once
                    closed = True
        if closed:
            self.page_changed(self._pages.currentIndex())  # open pages remembered for next startup
        self.refresh_open_pages()

    def refresh_open_pages(self):
        """Close button on pages, open pages button (shown while pages outside rail are kept
        open behind shown page, ex. with unsaved changes), unsaved changes marker on rail entries
        & open pages button"""
        modified_tools = set()
        for page in self.dialog_pages():
            page.set_closable(not self.is_rail_page(page))
            if page.is_modified():
                modified_tools.add(type(page.dialog).__name__)
        for name, button in self.rail_tool_buttons().items():
            button.set_modified(name in modified_tools)
        pages = self.other_pages()
        modified = sum(page.is_modified() for page in pages)
        accent = self.palette().color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight)
        shown = self.shown_pages()
        behind = any(page not in shown for page in pages)
        self._button_pages.setVisible(behind)
        self._button_pages.dot_color = (QColor(status_color("warning")) if modified else accent) if behind else None
        tooltip = trm(f"Open pages: {len(pages)}")
        if modified:
            tooltip = f"{tooltip}\n{MODIFIED_MARKER}{trm(f'Unsaved changes: {modified}')}"
        self._button_pages.setToolTip(tooltip)
        self._button_pages.update()
        self.sync_rail_selection()

    def save_current_page(self) -> bool:
        """Ctrl+S: save shown page (editor, config page...), False if it has nothing to save"""
        current = self._pages.currentWidget()
        if isinstance(current, DialogPage) and current.dialog is not None:
            return current.dialog.save_by_shortcut()
        return False

    def show_pages_menu(self):
        """Menu of open pages (outside rail): show one, or close all"""
        menu = QMenu(self)
        current = self._pages.currentWidget()
        for page in self.other_pages():
            action = menu.addAction(page.display_title())
            action.setCheckable(True)
            action.setChecked(page is current)
            action.triggered.connect(lambda _=False, target=page: self.show_page_widget(target))
        menu.addSeparator()
        menu.addAction(tr("Close All")).triggered.connect(lambda: self.close_all_pages(self.other_pages()))
        button = self._button_pages
        menu.exec(button.mapToGlobal(button.rect().topRight()))

    def open_page_paths(self) -> list[str]:
        """Tool dialog paths of open pages in order, shown page marked with leading "*" """
        tools = {path.rsplit(".", 1)[-1]: path for _, entries in TOOL_SECTIONS for _, _, path in entries}
        current = self._pages.currentWidget()
        paths = []
        for page in self.dialog_pages():
            path = tools.get(type(page.dialog).__name__) if page.dialog is not None else None
            if path:
                paths.append(f"*{path}" if page is current else path)
        return paths

    def detach_pages(self) -> tuple[list[str], list[DialogPage], DialogPage | None]:
        """Before view is rebuilt (language change): tool pages to reopen translated (paths),
        other pages (config, unsaved edits) taken out as they are, and shown page if taken out
        """
        tools = {path.rsplit(".", 1)[-1]: path for _, entries in TOOL_SECTIONS for _, _, path in entries}
        self._closing_pages = True  # view replaced: its pages are not left for another one
        current = self._pages.currentWidget()
        paths: list[str] = []
        kept: list[DialogPage] = []
        shown = None
        for page in self.dialog_pages():
            dialog = page.dialog
            if dialog is None:
                continue
            is_modified = getattr(dialog, "is_modified", None)
            path = tools.get(type(dialog).__name__)
            if path and not (callable(is_modified) and is_modified()):
                paths.append(f"*{path}" if page is current else path)
                continue
            page.closed.disconnect(self.close_dialog_page)
            page.modified_changed.disconnect(self.refresh_open_pages)
            page.modified_changed.disconnect(self.schedule_close_left_pages)
            page.minimum_changed.disconnect(self.update_page_minimum)
            self._pages.removeWidget(page)
            page.setParent(None)
            kept.append(page)
            if page is current:
                shown = page
        return paths, kept, shown

    def adopt_pages(self, pages: list[DialogPage]):
        """Pages taken out of previous view, see detach_pages"""
        for page in pages:
            if not any(page.opener is other for other in pages):  # tool page reopened as new page
                page.opener = None
            page.closed.connect(self.close_dialog_page)
            page.modified_changed.connect(self.refresh_open_pages)
            page.modified_changed.connect(self.schedule_close_left_pages)
            page.minimum_changed.connect(self.update_page_minimum)
            self._pages.addWidget(page)
        self.refresh_open_pages()

    def restore_pages(self, paths: list[str]):
        """Reopen tool pages (unknown tools skipped), shown page shown again, else current page kept

        Pages left for another one are closed (see close_left_pages): only shown page & tools
        of navigation rail are reopened.
        """
        known = {path for _, entries in TOOL_SECTIONS for _, _, path in entries}
        rail_tools = self.rail_tool_buttons()
        index = self._pages.currentIndex()
        shown = None
        self._restoring_pages = True
        try:
            for entry in paths:
                path = entry.strip().removeprefix("*")
                path = RENAMED_TOOLS.get(path, path)  # merged tools: new tool
                if path not in known:
                    continue
                if not entry.strip().startswith("*") and path.rsplit(".", 1)[-1] not in rail_tools:
                    continue
                try:
                    open_tool(path, self._dialog_parent)
                except Exception:  # never block startup
                    logger.exception("GUI: unable to reopen %s", path)
                    continue
                if entry.strip().startswith("*"):
                    shown = self._pages.currentWidget()
        finally:
            self._restoring_pages = False
        if isinstance(shown, DialogPage):
            self.show_page_widget(shown, bring_to_front=False)
        elif isinstance(self._pages.currentWidget(), DialogPage):
            self.set_current_index(index if index < len(NAV_PAGES) else self._return_index)
        self.schedule_close_left_pages()

    def close_all_pages(self, pages: list[DialogPage] | None = None) -> bool:
        """Close every (or given) dialog page (each may ask to save), True if all closed"""
        self._closing_pages = True
        try:
            for page in reversed(self.dialog_pages() if pages is None else pages):
                if page.dialog is not None and not page.dialog.close():
                    self.show_page_widget(page)
                    return False
            return True
        finally:
            self._closing_pages = False
            self.schedule_close_left_pages()

    def show_page_widget(self, page: QWidget, bring_to_front: bool = True):
        """Show dialog page, main window brought to front"""
        current = self._pages.currentWidget()
        if not isinstance(current, DialogPage):
            self._return_index = self._pages.currentIndex()  # back to this page when closed
        self.remember_shown(current, page)
        if isinstance(page, DialogPage):
            self.fit_window(page)  # before showing it: its minimum (see update_page_minimum) fits grown window
        self._pages.setCurrentWidget(page)
        self._nav.setExclusive(False)  # no rail page selected while dialog page shows
        for button in self._nav.buttons():
            button.setChecked(False)
        self._nav.setExclusive(True)
        self.sync_rail_selection()
        if not bring_to_front or self._restoring_pages:
            return
        window = self.window()
        if not window.isVisible() or window.isMinimized():
            show_restored(window)
        window.raise_()
        window.activateWindow()

    @Slot(QWidget)  # type: ignore[operator]
    def close_dialog_page(self, page: QWidget):
        """Dialog closed itself: remove its page, back to previous page"""
        was_current = self._pages.currentWidget() is page
        self._pages.removeWidget(page)
        page.deleteLater()
        for other in self.dialog_pages():
            if other.opener is page:
                other.opener = None
        self._page_history = [shown for shown in self._page_history if shown is not page]
        self._grown_for.discard(page)
        if not self._grown_for:  # no open page needs grown window anymore
            self.restore_window_size()
        self.refresh_open_pages()
        if was_current:
            previous = self.previous_shown(page)
            if isinstance(previous, DialogPage):
                self.show_page_widget(previous)
            elif previous is not None:
                self.set_current_index(self._pages.indexOf(previous))
            else:
                self.set_current_index(min(self._return_index, len(NAV_PAGES) - 1))

    def remember_shown(self, current: QWidget | None, new: QWidget | None):
        """Page left for another one, shown again when that one closes or going back"""
        if current is None or current is new or self._going_back:
            return
        if current in self._page_history:
            self._page_history.remove(current)
        self._page_history.append(current)
        del self._page_history[:-20]

    def previous_shown(self, closed: QWidget | None) -> QWidget | None:
        """Last page shown before, still open"""
        while self._page_history:
            page = self._page_history.pop()
            if page is not closed and self._pages.indexOf(page) >= 0:
                return page
        return None

    def go_back(self) -> bool:
        """Show page shown before current one (Alt+Left, mouse back button), True if any"""
        previous = self.previous_shown(self._pages.currentWidget())
        if previous is None:
            return False
        self._going_back = True  # page left now is not remembered: going back again goes further back
        try:
            if isinstance(previous, DialogPage):
                self.show_page_widget(previous, bring_to_front=False)
            else:
                self.set_current_index(self._pages.indexOf(previous))
        finally:
            self._going_back = False
        return True

    def current_index(self) -> int:
        """Current page index"""
        return self._pages.currentIndex()

    def page_changed(self, index: int):
        """Shown page remembered at once, so a restart reopens it even after a crash or a
        system shutdown (not only after Quit)"""
        if not self.track_pages or self._restoring_pages:
            return
        remember = getattr(self.window(), "remember_shown_page", None)
        if callable(remember):
            remember(index)

    @Slot(bool)  # type: ignore[operator]
    def refresh_rail(self):
        """Sync quick action states with config & API"""
        for option, button in self._toggles.items():
            if button.isChecked() != cfg.overlay[option]:
                button.setChecked(cfg.overlay[option])
        if cfg.api["enable_active_state_override"]:
            api_state = "overriding"
        else:
            api_state = api.read.state.version()
        running = bool(api_state) and api_state not in ("not running", "0.0")
        dot_color = QColor(status_color("success" if running else "inactive"))
        tooltip = f"{api.alias} \u00b7 {tr(api_state)}"
        if self._button_api.dot_color != dot_color or self._button_api.toolTip() != tooltip:
            self._button_api.dot_color = dot_color
            self._button_api.setToolTip(tooltip)
            self._button_api.update()

    def toggle_overlay(self, option: str):
        """Toggle overlay option from rail"""
        if option == "fixed_position":
            octrl.toggle.lock()
        elif option == "auto_hide":
            octrl.toggle.hide()
        elif option == "vr_compatibility":
            octrl.toggle.vr()
        self.refresh_rail()

    def show_api_menu(self):
        """Show API menu next to API button"""
        button = self._button_api
        self._menu_api.exec(button.mapToGlobal(button.rect().topRight()))

    def select_page(self, index: int):
        """Select page from rail or shortcut, remembered for next launch"""
        self.set_current_index(index)
        if cfg.application["last_page_index"] != index:
            cfg.application["last_page_index"] = index
            cfg.save(config_type=ConfigType.CONFIG)

    def set_current_index(self, index: int):
        """Select page by index"""
        page = self._pages.widget(index)
        if isinstance(page, LazyPage):
            page.ensure_page()  # built even while window hidden: page state readable once selected
        self.remember_shown(self._pages.currentWidget(), self._pages.widget(index))
        self._pages.setCurrentIndex(index)
        self.sync_rail_selection()
        button = self._nav.button(index)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        if button is not None:
            self._rail_scroll.ensureWidgetVisible(button, 0, self.rail_fade_height())  # selected entry scrolled into view

    def select_preset_tab(self):
        """Select preset tab"""
        self.set_current_index(PAGE_INDEX["preset"])

    def select_spectate_tab(self):
        """Select spectate tab"""
        self.set_current_index(PAGE_INDEX["spectate"])

    def select_pacenotes_tab(self):
        """Select pace notes tab"""
        self.set_current_index(PAGE_INDEX["pacenotes"])

    def select_hotkey_tab(self):
        """Select hotkey tab"""
        self.set_current_index(PAGE_INDEX["hotkey"])


class StatusButtonBar(QStatusBar):
    """Status button bar"""

    def __init__(self, parent):
        super().__init__(parent)
        self.button_api = QPushButton("")
        self.button_api.setObjectName("pillApi")
        self.button_api.clicked.connect(self.refresh)
        self.button_api.setToolTip(tr("Config Telemetry API"))

        self.button_style = QPushButton("")
        self.button_style.setObjectName("pill")
        self.button_style.clicked.connect(self.toggle_color_theme)
        self.button_style.setToolTip(tr("Toggle Window Color Theme"))

        self.button_dpiscale = QPushButton("")
        self.button_dpiscale.setObjectName("pill")
        self.button_dpiscale.clicked.connect(self.toggle_dpi_scaling)
        self.button_dpiscale.setToolTip(tr("Toggle High DPI Scaling"))
        self._last_dpi_scaling = cfg.application["enable_high_dpi_scaling"]

        self.label_saving = QLabel(tr("Saving…"))
        self.label_saving.setObjectName("labelSaving")
        self.label_saving.setVisible(False)

        self.addPermanentWidget(self.label_saving)
        self.addPermanentWidget(self.button_api)
        self.addWidget(self.button_style)
        self.addWidget(self.button_dpiscale)

        app_signal.refresh.connect(self.refresh)
        app_signal.saving.connect(self.label_saving.setVisible)
        app_signal.error.connect(self.show_error)
        from ..userfile.json_setting import notices_ready
        notices_ready()  # messages sent before window was ready (settings file locked at start)

    @Slot(str)  # type: ignore[operator]
    def show_error(self, message: str):
        """Show background error message (thread crash, save failure)"""
        self.showMessage(f"⚠ {trm(message)}", 15000)

    @Slot(bool)  # type: ignore[operator]
    def refresh(self):
        """Refresh status bar"""
        if cfg.api["enable_active_state_override"]:
            text_api_status = "overriding"
        else:
            text_api_status = api.read.state.version()
        # Dot: green while the game is running (API reports a version), grey otherwise
        running = bool(text_api_status) and text_api_status not in ("not running", "0.0")
        self.button_api.setProperty("running", running)
        self.button_api.style().unpolish(self.button_api)
        self.button_api.style().polish(self.button_api)
        self.button_api.setText(f"\u25cf  {api.alias} \u00b7 {tr(text_api_status)}")

        dark = resolve_color_theme(cfg.application["window_color_theme"]) == "Dark"
        # Moon & sun glyphs without a color emoji form, so they stay monochrome like the text
        glyph = "\u263e " if dark else "\u263c "
        self.button_style.setText(glyph + trm(f"UI: {cfg.application['window_color_theme']}"))

        if cfg.application["enable_high_dpi_scaling"]:
            text_dpi = "Auto"
        else:
            text_dpi = "Off"
        if self._last_dpi_scaling != cfg.application["enable_high_dpi_scaling"]:
            text_need_restart = "*"
        else:
            text_need_restart = ""
        self.button_dpiscale.setText(trm(f"Scale: {text_dpi}{text_need_restart}"))

    def toggle_dpi_scaling(self):
        """Toggle DPI scaling"""
        if cfg.application["enable_high_dpi_scaling"]:
            state = "Disable"
            desc = "not be scaled under high DPI screen resolution."
        else:
            state = "Enable"
            desc = "be auto-scaled according to system DPI scaling setting."
        msg_text = (
            f"{state} <b>High DPI Scaling</b> and restart <b>Modern Tiny Pedals</b>?<br><br>"
            f"<b>Window</b> and <b>Overlay</b> size and position will {desc}"
        )
        restart_msg = QMessageBox.question(
            self, tr("High DPI Scaling"), trm(msg_text),
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            defaultButton=QMessageBox.StandardButton.No,
        )
        if restart_msg != QMessageBox.StandardButton.Yes:
            return

        cfg.application["enable_high_dpi_scaling"] = not cfg.application["enable_high_dpi_scaling"]
        cfg.save(config_type=ConfigType.CONFIG)
        window = self.window()
        if isinstance(window, AppWindow):
            window.restart_app()  # tool pages reopened
        else:
            loader.restart()

    def toggle_color_theme(self):
        """Toggle color theme: Modern Dark, Modern Light, Legacy Dark, Legacy Light"""
        themes = rxp.THEME_NAMES
        current = cfg.application["window_color_theme"]
        index = themes.index(current) if current in themes else -1
        cfg.application["window_color_theme"] = themes[(index + 1) % len(themes)]
        cfg.save(config_type=ConfigType.CONFIG)
        app_signal.refresh.emit(True)


class AppWindow(QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.last_style = None
        self.last_icon_dark = None
        self.last_language = cfg.application["language"]
        self._pages_closed = False  # pages closed for quit or restart, see close_pages_for_quit
        # Window size & position saved shortly after each change (kept after a crash or system
        # shutdown, not only after Quit), once set at startup, see set_window_state
        self._track_geometry = False
        self._normal_rect: QRect | None = None  # normal geometry before maximized, see changeEvent
        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setInterval(1000)
        self._geometry_timer.timeout.connect(lambda: self.save_window_state(delay=66))

        install_message_icons()  # message box icons drawn in window color theme

        # Status bar
        self.setStatusBar(StatusButtonBar(self))

        # Menu bar
        self.set_menu_bar()

        # Tab view
        self.setCentralWidget(TabView(self))

        # Tray icon
        self.set_tray_icon()

        # Command palette
        QShortcut(QKeySequence("Ctrl+K"), self, self.open_command_palette)
        # Previous page, like a browser
        QShortcut(QKeySequence("Alt+Left"), self, self.go_back)
        # Save shown page (editors, config pages)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Save), self, self.save_current_page)

        # Import preset, preset package or plugin by drag & drop
        self.setAcceptDrops(True)

        # Screen setup changed (screen plugged, resolution changed): reload widget positions
        self._screen_key = screen_key()
        self._screen_timer = QTimer(self)
        self._screen_timer.timeout.connect(self.check_screen_setup)
        self._screen_timer.start(3000)

        # Window state
        self.set_window_state()
        self.__connect_signal()
        QTimer.singleShot(0, self.restore_open_pages)  # once window is shown: faster startup
        # Follow OS light / dark switch: app icon matches taskbar
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _: app_signal.refresh.emit(True))

        # Refresh GUI
        app_signal.refresh.emit(True)

        # First launch setup
        if cfg.application["show_setup_wizard_at_startup"]:
            QTimer.singleShot(600, self.open_setup_wizard)

    @staticmethod
    def config_dialogs(preset_only: bool = False) -> list:
        """Open config dialogs (pages or windows), only those editing loaded preset options if set"""
        dialogs = DialogSingleton.dialogs(ConfigType.CONFIG)
        if preset_only:
            dialogs = [dialog for dialog in dialogs if getattr(dialog, "is_preset_setting", lambda: False)()]
        return dialogs

    def modified_config_dialogs(self, preset_only: bool = False) -> list:
        """Open config dialogs with unsaved changes"""
        return [
            dialog for dialog in self.config_dialogs(preset_only)
            if getattr(dialog, "is_modified", lambda: False)()
        ]

    def check_screen_setup(self):
        """Reload overlay with positions of new screen setup"""
        key = screen_key()
        if key == self._screen_key:
            return
        view = self.centralWidget()
        if isinstance(view, TabView):
            view.update_page_minimum()  # minimum within new screen size
        if cfg.compatibility["enable_window_position_correction"] and self.isVisible():
            keep_on_screen(self)  # screen unplugged or resolution lowered
        if self.modified_config_dialogs():
            return  # retried once config changes are saved or cancelled
        self._screen_key = key
        if cfg.application["enable_layout_per_screen_setup"]:
            logger.info("LAYOUT: screen setup changed to %s", key)
            loader.reload()
            app_signal.refresh.emit(True)

    def dragEnterEvent(self, event):
        """Accept preset & zip files"""
        from .file_drop import dropped_files

        if dropped_files(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        """Import dropped files"""
        from .file_drop import dropped_files, handle_drop

        paths = dropped_files(event.mimeData())
        if not paths:
            return
        event.acceptProposedAction()
        messages = handle_drop(self, paths)
        if messages:
            show_toast(self, "<br>".join(messages))

    def open_command_palette(self):
        """Open command palette, search & run anything"""
        from .command_palette import CommandPalette

        self.show_app()
        CommandPalette(self).open()

    def open_setup_wizard(self):
        """Open first launch setup wizard"""
        from .setup_wizard import SetupWizard

        # Only shown on first launch, regardless of how the wizard is closed
        cfg.application["show_setup_wizard_at_startup"] = False
        cfg.save(0, config_type=ConfigType.CONFIG)
        self.show_app()
        SetupWizard(self).open()

    @Slot(bool)  # type: ignore[operator]
    def refresh(self):
        """Refresh GUI"""
        # Window style
        style = cfg.application["window_color_theme"]
        if self.last_style != style:
            self.last_style = style
            set_style_palette(style)
            # Applied at QApplication level (not just this window), so every dialog picks up the
            # style even if not a visual child of AppWindow at the time it is shown, including
            # QMessageBox, QColorDialog and other Qt-built top-level windows.
            app_instance = QApplication.instance()
            if isinstance(app_instance, QApplication):
                app_instance.setStyleSheet(set_style_window(QApplication.font().pointSize()))
            logger.info("GUI: loading window color theme: %s", style)
        # App icon (window, taskbar, tray): follow OS taskbar light / dark mode
        icon_dark = system_dark_mode()
        if self.last_icon_dark != icon_dark:
            self.last_icon_dark = icon_dark
            QApplication.setWindowIcon(QIcon(app_icon_file(icon_dark)))
            tray_icon = self.findChild(QSystemTrayIcon)
            if tray_icon is not None:
                tray_icon.setIcon(QApplication.windowIcon())
        # Language
        if self.last_language != cfg.application["language"]:
            self.last_language = cfg.application["language"]
            QTimer.singleShot(0, self.retranslate)  # rebuild after refresh signal finished

    def retranslate(self):
        """Apply new UI language without restart, rebuild menus, tabs, status bar"""
        language_code = set_language(cfg.application["language"])
        install_qt_translation(QApplication.instance(), language_code)
        tab_view = self.centralWidget()
        tab_index = 0
        open_pages: list[str] = []
        kept: list[DialogPage] = []
        shown = None
        growth = None
        if isinstance(tab_view, TabView):
            growth = tab_view.window_growth()  # window grown for a wide page: back to size before once closed
            tab_index = tab_view.current_index()
            if tab_index >= len(NAV_PAGES):  # dialog page shown: app page shown before it
                tab_index = tab_view._return_index
            open_pages, kept, shown = tab_view.detach_pages()
        self.setStatusBar(StatusButtonBar(self))  # old widgets are deleted by Qt
        for action in self.menuBar().actions():  # clear() keeps menus parented to window: delete them
            old_menu = action.menu()
            if old_menu is not None:
                old_menu.deleteLater()
        self.menuBar().clear()
        self.set_menu_bar()
        old_view = self.centralWidget()
        if old_view is not None:  # deleted by Qt once replaced: QML views unloaded before their backends
            release_quick_views(old_view)
        tab_view = TabView(self)
        self.setCentralWidget(tab_view)
        if growth is not None:
            tab_view.adopt_window_growth(growth)
        tab_view.set_current_index(tab_index)
        tab_view.adopt_pages(kept)  # config & edited pages kept as they are (no edit lost)
        tab_view.restore_pages(open_pages)  # tool pages reopened in new language
        if shown is not None:
            tab_view.show_page_widget(shown, bring_to_front=False)
        tab_view.track_pages = True
        tray_icon = self.findChild(QSystemTrayIcon)
        if tray_icon is not None:
            old_menu = tray_icon.contextMenu()
            tray_icon.setContextMenu(OverlayMenu(tr("Overlay"), self, True))
            if old_menu is not None:
                old_menu.deleteLater()
        # Running overlays rebuilt with labels of new language (sized to fit them)
        for name in tuple(wctrl.active_modules):
            wctrl.reload(name)
        app_signal.refresh.emit(True)
        logger.info("GUI: language changed to %s", self.last_language)

    def set_menu_bar(self):
        """Set menu bar"""
        logger.info("GUI: loading window menu")
        menu = self.menuBar()
        # Overlay menu
        menu_overlay = OverlayMenu(tr("Overlay"), self)
        menu.addMenu(menu_overlay)
        # API menu
        menu_api = APIMenu(tr("API"), self)
        menu.addMenu(menu_api)
        cast(StatusButtonBar, self.statusBar()).button_api.setMenu(menu_api)
        # Config menu
        menu_config = ConfigMenu(tr("Config"), self)
        menu.addMenu(menu_config)
        # Tools menu
        menu_tools = ToolsMenu(tr("Tools"), self)
        menu.addMenu(menu_tools)
        # Window menu
        menu_window = WindowMenu(tr("Window"), self)
        menu.addMenu(menu_window)
        # Help menu
        menu_help = HelpMenu(tr("Help"), self)
        menu.addMenu(menu_help)

    def set_tray_icon(self):
        """Set tray icon"""
        logger.info("GUI: loading tray icon")
        tray_icon = QSystemTrayIcon(self)
        # Config tray icon
        tray_icon.setIcon(self.windowIcon())
        tray_icon.setToolTip(self.windowTitle())
        tray_icon.activated.connect(self.tray_activated)
        # Add tray menu
        tray_menu = OverlayMenu(tr("Overlay"), self, True)
        tray_icon.setContextMenu(tray_menu)
        tray_icon.show()

    def tray_activated(self, active_reason: QSystemTrayIcon.ActivationReason):
        """Tray click or double click: show window (right click opens tray menu)"""
        if active_reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_app()

    def set_window_state(self):
        """Set initial window state: last size & position (comfortable size centered on screen at
        first launch), kept inside screens, maximized again if it was

        Minimum size is the one of window layout (rail & widest page): never below, so pages
        are never cut.
        """
        logger.info("GUI: loading window setting")
        self.winId()  # native window created: frame size (title bar) known to fit window inside screen
        default = default_frame_rect(self)
        width, height = cfg.application["window_width"], cfg.application["window_height"]
        if cfg.application["remember_size"] and width > 0 and height > 0:
            self.resize(width, height)
        else:
            set_frame_rect(self, default)
        pos_x, pos_y = cfg.application["position_x"], cfg.application["position_y"]
        if cfg.application["remember_position"] and (pos_x, pos_y) != (0, 0):  # 0, 0: not saved yet
            self.move(pos_x, pos_y)
        else:  # centered on screen
            frame = self.frameGeometry()
            frame.moveCenter(default.center())
            self.move(frame.topLeft())

        if cfg.compatibility["enable_window_position_correction"]:
            self.verify_window_position()

        if cfg.application["remember_size"] and cfg.application["window_maximized"]:
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)
        if cfg.application["show_at_startup"]:
            show_restored(self)
        elif not cfg.application["minimize_to_tray"]:
            self.showMinimized()
        self._track_geometry = True

    def verify_window_position(self):
        """Keep window inside screen showing most of it (nearest one if on none: screen unplugged),
        shrunk to fit if larger (resolution lowered), title bar never off screen"""
        if keep_on_screen(self):
            logger.info("GUI: window position corrected")

    def save_window_state(self, delay: int = 0):
        """Save window size, position & maximized state

        While maximized, normal size & position are saved (shown again once un-maximized). While
        a page grew window, size & position before it are saved unless user changed them since:
        page grows window again when reopened, grown size never becomes window size.
        """
        maximized = self.isMaximized() or self.isFullScreen()
        rect = self.normalGeometry() if maximized else self.geometry()
        if rect.isEmpty():
            rect = self.geometry()
        size = rect.size()
        pos = rect.topLeft() - (self.geometry().topLeft() - self.pos())  # frame position, as move()
        view = self.centralWidget()
        if isinstance(view, TabView):
            base_size, base_pos = view.window_base_geometry()
            if base_size is not None:
                size = base_size
            if base_pos is not None:
                pos = base_pos
        values: dict[str, int | bool] = {}
        if cfg.application["remember_position"]:
            values.update(position_x=pos.x(), position_y=pos.y())
        if cfg.application["remember_size"]:
            values.update(window_width=size.width(), window_height=size.height(), window_maximized=self.isMaximized())
        changed = {key: value for key, value in values.items() if cfg.application[key] != value}
        if changed:
            cfg.application.update(changed)
            cfg.save(delay, config_type=ConfigType.CONFIG)

    def reset_window_size(self):
        """Window back to default size, centered on its screen (Window menu, command palette)"""
        view = self.centralWidget()
        if isinstance(view, TabView):
            view.forget_window_growth()
        if self.isMaximized() or self.isFullScreen() or self.isMinimized():
            self.showNormal()  # un-maximized first, default geometry applied once done
            QTimer.singleShot(0, self.reset_window_size)
            return
        set_frame_rect(self, default_frame_rect(self, screen_for(self.frameGeometry())))
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.save_window_state()

    def show_app(self):
        """Show app window (from tray, notification...), maximized window stays maximized"""
        show_restored(self)
        self.activateWindow()
        app_signal.refresh.emit(True)

    def go_back(self):
        """Previous page"""
        view = self.centralWidget()
        if isinstance(view, TabView):
            view.go_back()

    def save_current_page(self) -> bool:
        """Save shown page (Ctrl+S), False if it has nothing to save"""
        view = self.centralWidget()
        return isinstance(view, TabView) and view.save_current_page()

    def mousePressEvent(self, event):
        """Mouse back button: previous page (clicks not used by widget under mouse come here)"""
        if event.button() == Qt.MouseButton.BackButton:
            self.go_back()
            event.accept()
            return
        super().mousePressEvent(event)

    def changed_by_user(self, event: QEvent) -> bool:
        """Resize or move done by user (window manager): not by app, nor by (un)maximizing"""
        return event.spontaneous() and not (self.isMaximized() or self.isFullScreen() or self.isMinimized())

    def resizeEvent(self, event):
        if self.changed_by_user(event):
            if self._normal_rect is not None and event.size() == self._normal_rect.size():
                self._normal_rect.setSize(QSize())  # un-maximized: back to normal size
            else:
                view = self.centralWidget()
                if isinstance(view, TabView):
                    view.window_resized_by_user()
        self.geometry_changed()
        super().resizeEvent(event)

    def moveEvent(self, event):
        if self.changed_by_user(event):
            if self._normal_rect is not None and event.pos() == self._normal_rect.topLeft():
                self._normal_rect = None  # un-maximized: back to normal position
            else:
                view = self.centralWidget()
                if isinstance(view, TabView):
                    view.window_moved_by_user()
        self.geometry_changed()
        super().moveEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            sized = Qt.WindowState.WindowMaximized | Qt.WindowState.WindowFullScreen
            if self.windowState() & sized and not event.oldState() & sized:
                self._normal_rect = self.geometry()  # un-maximizing comes back to it: not a user change
            self.geometry_changed()
        super().changeEvent(event)

    def geometry_changed(self):
        """Window size, position or state changed: saved once changes settle"""
        if self._track_geometry:
            self._geometry_timer.start()

    def save_open_pages(self, delay: int = 0):
        """Remember tool pages left open (shown one marked), reopened at next startup"""
        view = self.centralWidget()
        if not isinstance(view, TabView):
            return
        open_pages = ",".join(view.open_page_paths()) if cfg.application["remember_open_pages"] else ""
        if cfg.application["open_pages"] != open_pages:
            cfg.application["open_pages"] = open_pages
            cfg.save(delay, config_type=ConfigType.CONFIG)

    def remember_shown_page(self, index: int):
        """Shown page changed: app page index & open tool pages saved for next startup"""
        if 0 <= index < len(NAV_PAGES) and cfg.application["last_page_index"] != index:
            cfg.application["last_page_index"] = index
            cfg.save(config_type=ConfigType.CONFIG)
        self.save_open_pages(delay=66)

    def restore_open_pages(self):
        """Reopen tool pages left open at last quit, then follow page changes"""
        if not shiboken6.isValid(self):  # closed before event loop ran
            return
        view = self.centralWidget()
        if not isinstance(view, TabView):
            return
        paths = [path for path in cfg.application["open_pages"].split(",") if path.strip()]
        if cfg.application["remember_open_pages"] and paths and not safe_mode_enabled():
            view.restore_pages(paths)
        view.track_pages = True

    def close_pages_for_quit(self) -> bool:
        """Before quit or restart: tool pages left open remembered (reopened at next startup),
        then every page closed, each may ask to save changes

        Returns:
            False if cancelled (unsaved changes kept): pages kept open, app must not quit.
        """
        view = self.centralWidget()
        if not isinstance(view, TabView) or self._pages_closed:
            return True
        self.save_open_pages()
        view.track_pages = False  # pages closing now: saved state kept
        if not view.close_all_pages():
            view.track_pages = True
            return False
        self._pages_closed = True
        return True

    def cancel_quit(self):
        """Quit or restart failed after pages were closed (installer not started): app goes on"""
        self._pages_closed = False
        view = self.centralWidget()
        if isinstance(view, TabView):
            view.track_pages = True

    def restart_app(self) -> bool:
        """Restart app, tool pages left open reopened, False if cancelled (unsaved changes)"""
        if not self.close_pages_for_quit():
            return False
        tray_icon = self.findChild(QSystemTrayIcon)
        if tray_icon is not None:
            tray_icon.hide()  # no ghost tray icon left by exited process
        loader.restart()  # only returns if relaunch failed (app reloaded & kept running)
        if tray_icon is not None:
            tray_icon.show()
        return True

    def quit_app(self) -> bool:
        """Quit manager, open pages with unsaved changes are asked first

        Returns:
            False if cancelled: app kept open.
        """
        if not self.close_pages_for_quit():
            return False
        release_quick_views(self)  # QML views unloaded before their backends are deleted
        loader.close()  # must close this first
        self.save_window_state()
        self.__break_signal()
        tray_icon = self.findChild(QSystemTrayIcon)
        if tray_icon is not None:  # tray is optional (not supported on some desktops)
            tray_icon.hide()  # workaround tray icon not removed after exited
        QApplication.quit()
        return True

    def closeEvent(self, event):
        """Minimize to tray, else quit: window kept (with tray icon & pages) if quit is cancelled"""
        if cfg.application["minimize_to_tray"]:
            event.ignore()
            self.hide()
        elif not self.quit_app():
            event.ignore()

    @Slot(bool)  # type: ignore[operator]
    def reload_preset(self, check_singleton: bool):
        """Reload current preset

        Open config pages of preset options (they show options of preset loaded before) are
        closed first. Loading asked by user is cancelled while one has unsaved changes (shown
        instead), auto-loading goes on (saving those changes then asks first).

        Args:
            check_singleton: loading asked by user (list, hotkey, menu), False for auto-loading.
        """
        dialogs = self.config_dialogs(preset_only=True)
        modified = self.modified_config_dialogs(preset_only=True)
        if check_singleton and modified:
            view = self.centralWidget()
            if isinstance(view, TabView):
                view.show_dialog(modified[0])
            title = modified[0].windowTitle().removesuffix(f" - {APP_NAME}")
            msg_text = (
                f"Cannot load preset while <b>{title}</b> has unsaved changes."
                "<br><br>Save or cancel its changes first."
            )
            QMessageBox.warning(self, tr("Error"), trm(msg_text))
            cfg.set_next_to_load("")
            return
        for dialog in dialogs:
            if dialog not in modified:
                dialog.close()
        loader.reload(reload_preset=True)
        app_signal.refresh.emit(True)

    @Slot(object)  # type: ignore[operator]
    def hotkey_command(self, hotkey_func: Callable):
        """Hotkey command must be run in main thread"""
        hotkey_func()

    def __connect_signal(self):
        """Connect signal"""
        app_signal.hotkey.connect(self.hotkey_command)
        app_signal.refresh.connect(self.refresh)
        app_signal.quitapp.connect(self.quit_app)
        app_signal.reload.connect(self.reload_preset)
        logger.info("GUI: connect signals")

    def __break_signal(self):
        """Disconnect signal"""
        app_signal.hotkey.disconnect()
        app_signal.updates.disconnect()
        app_signal.refresh.disconnect()
        app_signal.quitapp.disconnect()
        app_signal.reload.disconnect()
        logger.info("GUI: disconnect signals")
