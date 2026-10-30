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
Main application window

Page area of the window (navigation rail, pages, tool dialogs shown as pages): TabView in app_tab_view.
"""

import logging
import sys
from collections.abc import Callable
from functools import partial

import shiboken6
from PySide6.QtCore import QEvent, QMetaObject, QRect, QSize, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import (
    QGuiApplication,
    QIcon,
    QKeySequence,
    QScreen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QSystemTrayIcon,
    QWidget,
)

from .. import app_signal, loader
from ..const_app import APP_NAME, VERSION
from ..const_file import ConfigType
from ..i18n import install_qt_translation, set_language, tr, trm
from ..module_control import wctrl
from ..setting import cfg
from ..userfile.layout_profile import screen_key
from . import (
    app_icon_file,
    install_message_icons,
    resolve_color_theme,
    set_colorblind,
    set_style_palette,
    set_style_window,
    status_color,  # noqa: F401  (re-exported)
    system_dark_mode,
)
from ._common import MODIFIED_MARKER, DialogSingleton
from .animation_rate import AnimationRate
from .app_tab_view import (  # noqa: F401  (re-exported)
    PAGE_SWITCHES,
    RAIL_TOGGLES,
    DialogPage,
    NavButton,
    ScrollFade,
    TabView,
    build_page,
    kept_when_hidden,
    show_restored,
)
from .lazy_page import release_quick_views
from .menu import APIMenu, ConfigMenu, HelpMenu, OverlayMenu, ToolsMenu, WindowMenu
from .nav_rail import NAV_PAGES, PAGE_INDEX  # noqa: F401  (PAGE_INDEX re-exported)
from .ordered_picker import icon_font_family  # noqa: F401  (re-exported)
from .toast import show_toast
from .window_geometry import (
    default_frame_rect,
    keep_on_screen,
    screen_for,
    set_frame_rect,
)

logger = logging.getLogger(__name__)
UPDATE_CHECK_POLL_MS = 600000  # whether automatic update check is due, every 10 minutes
SCREEN_SETTLE_MS = 500  # screen setup checked once screen signals stopped this long (several in a row)
SCREEN_RETRY_MS = 3000  # screen setup applied again this often while config pages hold unsaved changes


def force_foreground(window: QWidget):
    """Window put in front & focused though another app (game) has focus (Windows)

    Windows only flashes the taskbar button of an app activating its window without the last input
    (global hotkey key state is polled, remote control): input of the foreground window thread is
    shared during the call, as Qt does with its AlwaysActivateWindow behavior.
    """
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32")  # own prototypes, not shared ctypes.windll ones
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
    user32.BringWindowToTop.argtypes = (wintypes.HWND,)
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    hwnd = int(window.winId())
    foreground = user32.GetForegroundWindow()
    if not foreground or foreground == hwnd:
        return
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
    current_thread = ctypes.WinDLL("kernel32").GetCurrentThreadId()
    attached = bool(
        foreground_thread and foreground_thread != current_thread
        and user32.AttachThreadInput(current_thread, foreground_thread, True)
    )
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(current_thread, foreground_thread, False)


def safe_mode_enabled() -> bool:
    """App started in safe mode: tool pages left open are not reopened (one may have crashed it)"""
    from .. import safe_mode

    return safe_mode.state.enabled


def apply_title_bar_scheme(dark: bool) -> bool:
    """Native title bar of windows in app theme colors (Windows: dark or light frame), True if asked

    Qt follows the color scheme asked of its style hints: Windows window frames (title bar) of the app are drawn
    dark or light like the app, not like the Windows setting. Windows only: elsewhere the OS color scheme stays
    the one read (app icon follows the taskbar, see system_dark_mode).
    """
    if sys.platform != "win32":
        return False
    hints = QGuiApplication.styleHints()
    set_scheme = getattr(hints, "setColorScheme", None)  # Qt 6.8 and later
    if not callable(set_scheme):
        return False
    scheme = Qt.ColorScheme.Dark if dark else Qt.ColorScheme.Light
    if hints.colorScheme() != scheme:
        set_scheme(scheme)
    return True


def focus_search_field(page: QWidget) -> bool:
    """Search field of page focused, its text selected (Ctrl+F of pages without their own), True if found

    Qt Quick pages: first shown TpSearchField. Widget pages: first shown line edit named like a search box.
    """
    for view in page.findChildren(QWidget):
        if not view.inherits("QQuickWidget") or not view.isVisible():
            continue
        root_object = getattr(view, "rootObject", None)
        root = root_object() if callable(root_object) else None
        items = [root] if root is not None else []
        while items:
            item = items.pop(0)
            if item.metaObject().className().startswith("TpSearchField") and item.isVisible():
                view.setFocus(Qt.FocusReason.ShortcutFocusReason)
                QMetaObject.invokeMethod(item, "forceActiveFocus")
                QMetaObject.invokeMethod(item, "selectAll")
                return True
            items.extend(item.childItems())
    for edit in page.findChildren(QLineEdit):
        if edit.isVisible() and "search" in f"{edit.objectName()} {edit.placeholderText()}".lower():
            edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
            edit.selectAll()
            return True
    return False


class StatusButtonBar(QStatusBar):
    """Status band of main window: status chips (see notification.NotifyBar, added by the page view), saving
    state on the right. Background errors go to the notification center (bell of the rail), with a toast while
    the window is shown. Game & API state is on the rail (API button), theme & scaling in Settings."""

    def __init__(self, parent):
        super().__init__(parent)
        self.label_saving = QLabel(tr("Saving\u2026"))
        self.label_saving.setObjectName("labelSaving")
        self.label_saving.setVisible(False)
        self.addPermanentWidget(self.label_saving)

        app_signal.saving.connect(self.label_saving.setVisible)
        app_signal.error.connect(self.show_error)
        from ..userfile.json_setting import notices_ready
        notices_ready()  # messages sent before window was ready (settings file locked at start)

    @Slot(str)  # type: ignore[operator]
    def show_error(self, message: str):
        """Background error (thread crash, save failure): kept in notification center, toast while shown"""
        from .notification import error_actions, notification_store

        text = trm(message)
        notification_store().add(text, "error", error_actions())
        window = self.window()
        if window.isVisible() and not window.isMinimized():
            view = window.centralWidget() if isinstance(window, QMainWindow) else None
            show_center = getattr(view, "show_notification_center", None)
            show_toast(window, f"⚠ {text}", action_text=tr("Details") if callable(show_center) else "",
                       action=show_center if callable(show_center) else None)


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

        self._theme_timer = QTimer(self)  # OS theme changed: app icon checked once events settle
        self._theme_timer.setSingleShot(True)
        self._theme_timer.setInterval(250)
        self._theme_timer.timeout.connect(self.refresh_icon)
        install_message_icons()  # message box icons drawn in window color theme
        # Color theme set before widgets are built & shown: first frame was painted in Qt default palette
        # (OS dark mode gray & Windows accent color) until refresh below
        self.apply_color_theme()

        # Status bar
        self.setStatusBar(StatusButtonBar(self))

        # Menu bar
        self.set_menu_bar()

        # Tab view
        self.setCentralWidget(TabView(self))

        # Tray icon
        self.set_tray_icon()

        # Window shortcuts, described (whatsThis) in the keyboard shortcuts sheet
        for keys, run, text in (
            ("Ctrl+K", self.open_command_palette, "Command Palette"),
            ("Alt+Left", self.go_back, "Back"),  # previous page, like a browser
            ("Alt+Right", self.go_forward, "Forward"),
            (QKeySequence.StandardKey.Save, self.save_current_page, "Save shown page (editors, settings)"),
            ("Ctrl+F", self.find_in_page, "Find in page (command palette on pages without search)"),
            ("Ctrl+/", self.open_shortcuts, "Keyboard Shortcuts"),
        ):
            shortcut = QShortcut(QKeySequence(keys), self, run)
            shortcut.setWhatsThis(tr(text))

        # Import preset, preset package or plugin by drag & drop
        self.setAcceptDrops(True)

        # Screen setup changed (screen plugged, resolution changed): reload widget positions, checked once
        # screen signals settle (several in a row), again later while config pages hold unsaved changes
        self._screen_key = screen_key()
        self._screen_timer = QTimer(self)
        self._screen_timer.setSingleShot(True)
        self._screen_timer.timeout.connect(self.check_screen_setup)
        app = QGuiApplication.instance()
        if isinstance(app, QGuiApplication):
            app.screenAdded.connect(self.screen_added)
            app.screenRemoved.connect(self.screen_setup_changed)
            for screen in app.screens():
                self.watch_screen(screen)

        # Updates checked again while app runs, see number_of_hours_between_update_checks
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(lambda: loader.update_checker.check_due())  # imported once used
        self._update_timer.start(UPDATE_CHECK_POLL_MS)

        # Animations stepped at the refresh rate of the window screen (Qt default: 60 Hz on any screen),
        # left to Qt in safe mode (calls into Qt Core)
        self.animation_rate = None if safe_mode_enabled() else AnimationRate(self)

        # Window state
        self.set_window_state()
        self.__connect_signal()
        QTimer.singleShot(0, self.restore_open_pages)  # once window is shown: faster startup
        # Follow OS light / dark switch: app icon matches taskbar
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _: app_signal.refresh.emit(True))
        # Errors & warnings told by a tray message while window is hidden in tray or minimized
        from .notification import TrayRelay

        self._tray_relay = TrayRelay(self)
        # Window title: shown page & its unsaved changes marker
        self.connect_page_title()

        # Refresh GUI
        app_signal.refresh.emit(True)

        # First launch: setup wizard
        QTimer.singleShot(600, self.first_launch_steps)

    def first_launch_steps(self):
        """Setup wizard, else what's new once after an update"""
        from .release_notes import remember_version_run, show_notes_after_update

        previous = remember_version_run()
        if cfg.application["show_setup_wizard_at_startup"]:
            self.open_setup_wizard()
        else:
            show_notes_after_update(self, previous)

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

    def watch_screen(self, screen: QScreen):
        """Screen resolution or position changes followed"""
        screen.geometryChanged.connect(self.screen_setup_changed)
        screen.availableGeometryChanged.connect(self.screen_setup_changed)

    def screen_added(self, screen: QScreen):
        self.watch_screen(screen)
        self.screen_setup_changed()

    def screen_setup_changed(self, *_args):
        """Screen plugged, unplugged or changed: setup checked once signals settle"""
        self._screen_timer.start(SCREEN_SETTLE_MS)

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
            self._screen_timer.start(SCREEN_RETRY_MS)  # retried once config changes are saved or cancelled
            return
        self._screen_key = key
        if cfg.application["enable_layout_per_screen_setup"]:
            logger.info("LAYOUT: screen setup changed to %s", key)
            loader.reload()
            loader.after_reload(partial(app_signal.refresh.emit, True))

    def dragEnterEvent(self, event):
        """Accept preset, zip & MoTeC files"""
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
        CommandPalette(self)

    def open_shortcuts(self):
        """Keyboard shortcuts sheet (Ctrl+/, F1), closed if open"""
        from .quick.shell_shortcuts_backend import ShortcutsSheet

        self.show_app()
        ShortcutsSheet.toggle(self)

    def find_in_page(self):
        """Ctrl+F not taken by the shown page: its search field focused (text selected), else command palette"""
        view = self.centralWidget()
        current = view.current_page() if isinstance(view, TabView) else None
        if current is None or not focus_search_field(current):
            self.open_command_palette()

    def open_setup_wizard(self):
        """Open first launch setup wizard"""
        from .setup_wizard import SetupWizard

        # Only shown on first launch, regardless of how the wizard is closed
        cfg.application["show_setup_wizard_at_startup"] = False
        cfg.save(0, config_type=ConfigType.CONFIG)
        self.show_app()
        SetupWizard(self).open()

    def apply_color_theme(self):
        """Window style palette & style sheet of color theme, if changed"""
        style = cfg.application["window_color_theme"]
        if self.last_style == style:
            return
        self.last_style = style
        set_style_palette(style)
        apply_title_bar_scheme(resolve_color_theme(style) == "Dark")
        # Applied at QApplication level (not just this window), so every dialog picks up the
        # style even if not a visual child of AppWindow at the time it is shown, including
        # QMessageBox, QColorDialog and other Qt-built top-level windows.
        app_instance = QApplication.instance()
        if isinstance(app_instance, QApplication):
            app_instance.setStyleSheet(set_style_window(QApplication.font().pointSize()))
        logger.info("GUI: loading window color theme: %s", style)

    @Slot(bool)  # type: ignore[operator]
    def refresh(self):
        """Refresh GUI"""
        self.apply_color_theme()
        # Status colors of QML pages follow the overlay "colorblind safe colors" option
        set_colorblind(bool(cfg.user.config["overlay_style"].get("enable_colorblind_colors", False)))
        self.refresh_icon()
        # Language
        if self.last_language != cfg.application["language"]:
            self.last_language = cfg.application["language"]
            QTimer.singleShot(0, self.retranslate)  # rebuild after refresh signal finished

    def refresh_icon(self):
        """App icon (window, taskbar, tray): follow OS taskbar light / dark mode"""
        icon_dark = system_dark_mode()
        if self.last_icon_dark != icon_dark:
            self.last_icon_dark = icon_dark
            QApplication.setWindowIcon(QIcon(app_icon_file(icon_dark)))
            tray_icon = self.findChild(QSystemTrayIcon)
            if tray_icon is not None:
                tray_icon.setIcon(QApplication.windowIcon())

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
            # Kept pages shown page was opened from (editor of a name input...): back to them once it closes
            openers: list[DialogPage] = []
            opener = shown.opener
            while opener is not None and opener in kept and opener not in openers:
                openers.append(opener)
                opener = opener.opener
            for opener in reversed(openers):
                tab_view.remember_shown(opener, shown)
        tab_view.track_pages = True
        self.connect_page_title()
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
        # Settings menu
        menu_config = ConfigMenu(tr("Settings"), self)
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

    def bring_to_front(self):
        """Show app window in front of the game (show_main_window hotkey), also hidden in tray or minimized"""
        self.show_app()
        self.raise_()
        force_foreground(self)

    def go_back(self):
        """Previous page"""
        view = self.centralWidget()
        if isinstance(view, TabView):
            view.go_back()

    def go_forward(self):
        """Page left by going back"""
        view = self.centralWidget()
        if isinstance(view, TabView):
            view.go_forward()

    def connect_page_title(self):
        """Window title follows shown page of view (set again when view is rebuilt)"""
        view = self.centralWidget()
        if isinstance(view, TabView):
            view.page_shown.connect(self.update_window_title)
        self.update_window_title()

    def update_window_title(self):
        """Window title: shown page, unsaved changes marker ("*"), app name & version"""
        view = self.centralWidget()
        page = view.page_title().removeprefix(MODIFIED_MARKER) if isinstance(view, TabView) else ""
        base = f"{APP_NAME} v{VERSION}"
        current = self.windowTitle()
        suffix = current.split(base, 1)[1] if base in current else ""  # " - Safe Mode" added at start, kept
        title = f"{page}[*] - {base}{suffix}" if page else f"{base}{suffix}"
        if self.windowTitle() != title:
            self.setWindowTitle(title)
        self.setWindowModified(isinstance(view, TabView) and view.page_modified())

    def save_current_page(self) -> bool:
        """Save shown page (Ctrl+S), False if it has nothing to save"""
        view = self.centralWidget()
        return isinstance(view, TabView) and view.save_current_page()

    def keyPressEvent(self, event):
        """F1 not taken by the shown page (charts show their own help): keyboard shortcuts sheet"""
        if event.key() == Qt.Key.Key_F1 and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self.open_shortcuts()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        """Mouse back & forward buttons: previous & next page (clicks not used by widget under mouse come here)"""
        if event.button() == Qt.MouseButton.BackButton:
            self.go_back()
            event.accept()
            return
        if event.button() == Qt.MouseButton.ForwardButton:
            self.go_forward()
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
        # OS light / dark switch while the app asks its own color scheme (title bar, see apply_title_bar_scheme):
        # style hints keep the asked one, so the app icon follows the taskbar from this event (once settled)
        theme_timer = getattr(self, "_theme_timer", None)  # events sent while window is built
        if event.type() == QEvent.Type.ThemeChange and theme_timer is not None and not theme_timer.isActive():
            theme_timer.start()
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
        open_pages = ",".join(view.open_page_paths(released=True)) if cfg.application["remember_open_pages"] else ""
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
            if not self.isVisible() and not cfg.application["show_at_startup"]:
                view.defer_pages(paths)  # started hidden in tray (game starting): built once window is shown
            else:
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
        self.cancel_quit()  # pages opened from now on asked to save on quit again
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
        cfg.flush()  # window state written before the process ends (as restart does)
        self.__break_signal()
        tray_icon = self.findChild(QSystemTrayIcon)
        if tray_icon is not None:  # tray is optional (not supported on some desktops)
            tray_icon.hide()  # workaround tray icon not removed after exited
        self.unload_quick_views()
        QApplication.quit()
        return True

    def unload_quick_views(self):
        """QML of every page unloaded while backends still exist

        Rail pages (spectate, presets...) never get a close event: deleted with the window, their
        backend (created first) went before their QML view, whose bindings then read a null backend.
        """
        from PySide6.QtQuickWidgets import QQuickWidget

        for view in self.findChildren(QQuickWidget):
            view.setSource(QUrl())

    def closeEvent(self, event):
        """Minimize to tray, else quit: window kept (with tray icon & pages) if quit is cancelled"""
        if cfg.application["minimize_to_tray"]:
            event.ignore()
            self.hide()
            self.tell_closed_to_tray()
        elif not self.quit_app():
            event.ignore()

    def tell_closed_to_tray(self):
        """First close to tray: tray message telling the app still runs (once, saved)"""
        if cfg.application.get("close_to_tray_notice_shown", True):
            return
        tray_icon = self.findChild(QSystemTrayIcon)
        if tray_icon is None or not tray_icon.isVisible():
            return
        cfg.application["close_to_tray_notice_shown"] = True
        cfg.save(config_type=ConfigType.CONFIG)
        tray_icon.showMessage(APP_NAME, trm(
            f"{APP_NAME} keeps running in the notification area. Right-click its icon to quit, "
            "or turn off Minimize to Tray in the Window menu."), QSystemTrayIcon.MessageIcon.Information, 10000)

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
        loader.after_reload(partial(app_signal.refresh.emit, True))

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
