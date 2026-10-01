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

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Slot
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QPalette,
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
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import app_signal, loader
from ..api_control import api
from ..const_app import APP_NAME, VERSION
from ..const_file import ConfigType
from ..i18n import install_qt_translation, set_language, tr, trm
from ..module_control import mctrl, wctrl
from ..overlay_control import octrl
from ..setting import cfg
from . import resolve_color_theme, set_style_palette, set_style_window
from ._common import DialogSingleton, UIScaler
from .hotkey_view import HotkeyList
from .menu import APIMenu, ConfigMenu, HelpMenu, OverlayMenu, ToolsMenu, WindowMenu, open_config_application
from .module_view import ModuleList
from .notification import NotifyBar
from .pace_notes_view import PaceNotesControl
from .preset_view import PresetList
from .spectate_view import SpectateList
from .tools_view import ToolsView

logger = logging.getLogger(__name__)


# Navigation pages: (key, label, icon glyph in Segoe Fluent Icons / MDL2 Assets, fallback letter)
NAV_PAGES = (
    ("widget", "Widget", "\ue71d", "W"),  # all apps grid
    ("module", "Module", "\ue9d9", "M"),  # diagnostic
    ("preset", "Preset", "\ue8f1", "P"),  # library
    ("spectate", "Spectate", "\ue890", "S"),  # view
    ("pacenotes", "Pacenotes", "\ue70b", "N"),  # quick note
    ("hotkey", "Hotkey", "\ue765", "H"),  # keyboard
    ("tools", "Tools", "\uec7a", "T"),  # developer tools
)
PAGE_INDEX = {key: index for index, (key, *_) in enumerate(NAV_PAGES)}

# Rail overlay toggles: (overlay option, tooltip, icon glyph, fallback letter)
RAIL_TOGGLES = (
    ("fixed_position", "Lock Overlay", "\ue72e", "L"),  # lock
    ("auto_hide", "Auto Hide", "\ue7b3", "H"),  # red eye
    ("vr_compatibility", "VR Compatibility", "\ue7f4", "V"),  # tv monitor
)
ICON_FONTS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")


def icon_font_family() -> str:
    """Installed icon font (Windows 10 / 11), "" if none: letters are drawn instead"""
    families = set(QFontDatabase.families())
    return next((family for family in ICON_FONTS if family in families), "")


class NavButton(QAbstractButton):
    """Navigation rail entry: icon over a short label, accent pill when selected"""

    def __init__(self, text: str, glyph: str, letter: str, icon_family: str, parent=None, compact: bool = False):
        super().__init__(parent)
        self.compact = compact  # icon only, label in tooltip
        self.dot_color: QColor | None = None  # status dot drawn at top right
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(text)
        self.glyph = glyph if icon_family else letter
        self.icon_font = QFont(icon_family) if icon_family else QFont(self.font())
        if not icon_family:
            self.icon_font.setBold(True)

    def sizeHint(self) -> QSize:
        line = self.fontMetrics().height()
        if self.compact:
            return QSize(round(line * 2.2), round(line * 2.2))
        return QSize(round(line * 4.4), round(line * 3.4))

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
        label = QFontMetricsF(label_font).elidedText(self.text(), Qt.TextElideMode.ElideRight, label_rect.width())
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label)


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

        # Pages
        widget_tab = ModuleList(self, wctrl)
        module_tab = ModuleList(self, mctrl)
        preset_tab = PresetList(self)
        spectate_tab = SpectateList(self)
        pacenotes_tab = PaceNotesControl(self)
        hotkey_tab = HotkeyList(self)
        icon_family = icon_font_family()
        tools_tab = ToolsView(self, icon_family, parent)
        self._pages = QStackedWidget(self)
        self._pages.setObjectName("pageStack")
        for page in (widget_tab, module_tab, preset_tab, spectate_tab, pacenotes_tab, hotkey_tab, tools_tab):
            self._pages.addWidget(page)

        # Navigation rail
        rail = QWidget(self)
        rail.setObjectName("navRail")
        layout_rail = QVBoxLayout(rail)
        margin = UIScaler.pixel(6)
        layout_rail.setContentsMargins(margin, margin, margin, margin)
        layout_rail.setSpacing(UIScaler.pixel(2))
        self._nav = QButtonGroup(self)
        self._nav.setExclusive(True)
        for index, (_, label, glyph, letter) in enumerate(NAV_PAGES):
            button = NavButton(tr(label), glyph, letter, icon_family, rail)
            button.setToolTip(f"{tr(label)} (Ctrl+{index + 1})")
            self._nav.addButton(button, index)
            layout_rail.addWidget(button)
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self)
            shortcut.activated.connect(lambda page=index: self.select_page(page))
        layout_rail.addStretch(1)
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
        button_config = NavButton(tr("Application"), "\ue713", "C", icon_family, rail, compact=True)  # settings
        button_config.setCheckable(False)
        button_config.clicked.connect(lambda: open_config_application(parent))
        layout_quick.addWidget(button_config, 1, 1)
        self._button_api = NavButton(tr("API"), "\ue968", "A", icon_family, rail, compact=True)  # network
        self._button_api.setCheckable(False)
        self._button_api.clicked.connect(self.show_api_menu)
        self._menu_api = APIMenu(tr("API"), parent)
        layout_quick.addWidget(self._button_api, 2, 1)
        button_search = NavButton(f"{tr('Command Palette')} (Ctrl+K)", "", "K", icon_family, rail, compact=True)
        button_search.setCheckable(False)
        button_search.clicked.connect(parent.open_command_palette)
        layout_quick.addWidget(button_search, 2, 0)
        layout_rail.addLayout(layout_quick)
        self._rail_timer = QTimer(self)
        self._rail_timer.timeout.connect(self.refresh_rail)
        self._rail_timer.start(1000)  # also follows changes from hotkeys, tray menu & API
        self.refresh_rail()

        last_page = cfg.application["last_page_index"]
        self.set_current_index(last_page if 0 <= last_page < len(NAV_PAGES) else 0)

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
        app_signal.refresh.connect(notify_bar.refresh)

        app_signal.refresh.connect(widget_tab.refresh)
        app_signal.refresh.connect(module_tab.refresh)
        app_signal.refresh.connect(preset_tab.refresh)
        app_signal.refresh.connect(spectate_tab.refresh)
        app_signal.refresh.connect(pacenotes_tab.refresh)
        app_signal.refresh.connect(hotkey_tab.refresh)
        app_signal.refresh.connect(self.refresh_rail)

    def current_index(self) -> int:
        """Current page index"""
        return self._pages.currentIndex()

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
        dot_color = QColor("#3DDC84") if running else QColor("#808080")
        tooltip = f"{api.alias} \u00b7 {api_state}"
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
        self._pages.setCurrentIndex(index)
        button = self._nav.button(index)
        if button is not None and not button.isChecked():
            button.setChecked(True)

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
        self.button_api.setText(f"\u25cf  {api.alias} \u00b7 {text_api_status}")

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
        loader.restart()

    def toggle_color_theme(self):
        """Toggle color theme: Dark, Light, System"""
        themes = ("Dark", "Light", "System")
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
        self.last_language = cfg.application["language"]

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

        # Window state
        self.set_window_state()
        self.__connect_signal()
        # Follow OS light / dark switch when window color theme is "System"
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _: app_signal.refresh.emit(True))

        # Refresh GUI
        app_signal.refresh.emit(True)

        # First launch setup
        if cfg.application["show_setup_wizard_at_startup"]:
            QTimer.singleShot(600, self.open_setup_wizard)

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
        style = resolve_color_theme(cfg.application["window_color_theme"])
        if self.last_style != style:
            self.last_style = style
            set_style_palette(self.last_style)
            # Applied at QApplication level (not just this window), so every dialog picks up the
            # style even if not a visual child of AppWindow at the time it is shown, including
            # QMessageBox, QColorDialog and other Qt-built top-level windows.
            app_instance = QApplication.instance()
            if app_instance is not None:
                app_instance.setStyleSheet(set_style_window(QApplication.font().pointSize()))
            logger.info("GUI: loading window color theme: %s", style)
        # Language
        if self.last_language != cfg.application["language"]:
            self.last_language = cfg.application["language"]
            QTimer.singleShot(0, self.retranslate)  # rebuild after refresh signal finished

    def retranslate(self):
        """Apply new UI language without restart, rebuild menus, tabs, status bar"""
        language_code = set_language(cfg.application["language"])
        install_qt_translation(QApplication.instance(), language_code)
        tab_view = self.centralWidget()
        tab_index = tab_view.current_index() if isinstance(tab_view, TabView) else 0
        self.setStatusBar(StatusButtonBar(self))  # old widgets are deleted by Qt
        self.menuBar().clear()
        self.set_menu_bar()
        tab_view = TabView(self)
        self.setCentralWidget(tab_view)
        tab_view.set_current_index(tab_index)
        tray_icon = self.findChild(QSystemTrayIcon)
        if tray_icon is not None:
            old_menu = tray_icon.contextMenu()
            tray_icon.setContextMenu(OverlayMenu(tr("Overlay"), self, True))
            if old_menu is not None:
                old_menu.deleteLater()
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
        self.statusBar().button_api.setMenu(menu_api)
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
        tray_icon.activated.connect(self.tray_doubleclick)
        # Add tray menu
        tray_menu = OverlayMenu(tr("Overlay"), self, True)
        tray_icon.setContextMenu(tray_menu)
        tray_icon.show()

    def tray_doubleclick(self, active_reason: QSystemTrayIcon.ActivationReason):
        """Tray doubleclick"""
        if active_reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_app()

    def set_window_state(self):
        """Set initial window state"""
        self.setMinimumSize(UIScaler.size(23), UIScaler.size(36))

        if cfg.application["remember_size"]:
            self.resize(
                cfg.application["window_width"],
                cfg.application["window_height"],
            )

        if cfg.application["remember_position"]:
            self.load_window_position()

        if cfg.compatibility["enable_window_position_correction"]:
            self.verify_window_position()

        if cfg.application["show_at_startup"]:
            self.showNormal()
        elif not cfg.application["minimize_to_tray"]:
            self.showMinimized()

    def load_window_position(self):
        """Load window position"""
        logger.info("GUI: loading window setting")
        app_pos_x = cfg.application["position_x"]
        app_pos_y = cfg.application["position_y"]
        # Save new x,y position if preset value at 0,0
        if 0 == app_pos_x == app_pos_y:
            self.save_window_state()
        else:
            self.move(app_pos_x, app_pos_y)

    def verify_window_position(self):
        """Verify window position"""
        # Get screen size from the screen where app window located
        screen_geo = self.screen().geometry()
        # Limiting position value if out of screen range
        app_pos_x = min(
            max(self.x(), screen_geo.left()),
            screen_geo.right() - self.minimumWidth(),
        )
        app_pos_y = min(
            max(self.y(), screen_geo.top()),
            screen_geo.bottom() - self.minimumHeight(),
        )
        # Re-adjust position only if mismatched
        if self.x() != app_pos_x or self.y() != app_pos_y:
            self.move(app_pos_x, app_pos_y)
            logger.info("GUI: window position corrected")

    def save_window_state(self):
        """Save window state"""
        if self.isMaximized() or self.isFullScreen():
            return  # keep last normal size & position
        save_changes = False

        if cfg.application["remember_position"]:
            last_pos = cfg.application["position_x"], cfg.application["position_y"]
            new_pos = self.x(), self.y()
            if last_pos != new_pos:
                cfg.application["position_x"] = new_pos[0]
                cfg.application["position_y"] = new_pos[1]
                save_changes = True

        if cfg.application["remember_size"]:
            last_size = cfg.application["window_width"], cfg.application["window_height"]
            new_size = self.width(), self.height()
            if last_size != new_size:
                cfg.application["window_width"] = new_size[0]
                cfg.application["window_height"] = new_size[1]
                save_changes = True

        if save_changes:
            cfg.save(0, config_type=ConfigType.CONFIG)

    def show_app(self):
        """Show app window"""
        self.showNormal()
        self.activateWindow()
        app_signal.refresh.emit(True)

    @Slot(bool)  # type: ignore[operator]
    def quit_app(self):
        """Quit manager"""
        loader.close()  # must close this first
        self.save_window_state()
        self.__break_signal()
        tray_icon = self.findChild(QSystemTrayIcon)
        if tray_icon is not None:  # tray is optional (not supported on some desktops)
            tray_icon.hide()  # workaround tray icon not removed after exited
        QApplication.quit()

    def closeEvent(self, event):
        """Minimize to tray"""
        if cfg.application["minimize_to_tray"]:
            event.ignore()
            self.hide()
        else:
            self.quit_app()

    @Slot(bool)  # type: ignore[operator]
    def reload_preset(self, check_singleton: bool):
        """Reload current preset"""
        # Cancel loading while any config dialog opened
        if check_singleton and DialogSingleton.is_opened(ConfigType.CONFIG):
            msg_text = "Cannot load preset while Config dialog is opened."
            QMessageBox.warning(self, tr("Error"), trm(msg_text))
            cfg.set_next_to_load("")
            return
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
