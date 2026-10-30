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
Menu
"""

import html
import os
import sys
from contextlib import suppress

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QActionGroup, QDesktopServices, QFontMetrics, QKeySequence
from PySide6.QtWidgets import QMenu, QMessageBox

from .. import app_signal, loader
from ..api_control import api
from ..const_app import PLATFORM, URL_FAQ, URL_USER_GUIDE
from ..const_file import ConfigType, FileExt
from ..i18n import tr, trm
from ..i18n.options import option_label
from ..module_control import mctrl
from ..overlay_control import octrl
from ..setting import cfg
from ..userfile.tls_cert import fingerprint as certificate_fingerprint
from .toast import show_toast
from .tools_view import LISTED_TOOL_SECTIONS, open_tool

TRAY_PRESET_CHARS = 48  # loaded preset name in tray menu: whole, cut in the middle past this many characters
TRAY_PRESETS = 30  # presets listed in tray menu (newest first)


# Define menu command
def menu_reload_preset():
    """Command - full reload"""
    loader.reload(reload_preset=True)
    loader.after_reload(menu_refresh_only)


def menu_reload_only():
    """Command - fast reload"""
    loader.reload(reload_preset=False)
    loader.after_reload(menu_refresh_only)


def menu_refresh_only():
    """Command - refresh GUI"""
    app_signal.refresh.emit(True)


def menu_restart_api():
    """Command - restart api"""
    api.restart()
    app_signal.refresh.emit(True)


def open_config_application(parent, section: str = "application"):
    """Config page (global options of config.json) at category of config section ("": as left)"""
    from .app_settings import open_app_settings

    return open_app_settings(parent, section)


def open_preset_config(parent, name: str):
    """Settings kept in the loaded preset: "units", "font" (global font override), "api" (API options) or
    another section (module...): category of the Settings page"""
    from .app_settings import open_app_settings

    return open_app_settings(parent, name)


class OverlayMenu(QMenu):
    """Overlay menu, shared between main & tray menu"""

    def __init__(self, title, parent, is_tray: bool = False):
        super().__init__(title, parent)
        if is_tray:
            self._parent = parent
            loaded_preset_font = self.font()
            loaded_preset_font.setBold(True)
            self.loaded_preset = self.addAction("")
            self.loaded_preset.setFont(loaded_preset_font)
            self.loaded_preset.setToolTip(tr("Open Presets page"))
            self.loaded_preset.triggered.connect(self.open_preset_tab)
            self.aboutToShow.connect(self.refresh_preset_name)
            # Presets: switch preset from the tray (listed when shown)
            self.menu_presets = self.addMenu(tr("Presets"))
            self.menu_presets.aboutToShow.connect(self.refresh_presets)
            self.addSeparator()

            app_config = self.addAction(tr("Open NeoPedal"))
            app_config.triggered.connect(parent.show_app)
            self.addSeparator()

        # Lock overlay
        self.overlay_lock = self.addAction(tr("Lock Overlay"))
        self.overlay_lock.setCheckable(True)
        self.overlay_lock.triggered.connect(self.is_locked)

        # Auto hide
        self.overlay_hide = self.addAction(tr("Auto Hide"))
        self.overlay_hide.setCheckable(True)
        self.overlay_hide.triggered.connect(self.is_hidden)

        # Grid move
        self.overlay_grid = self.addAction(tr("Grid Move"))
        self.overlay_grid.setCheckable(True)
        self.overlay_grid.triggered.connect(self.has_grid)

        # VR Compatbiility
        self.overlay_vr = self.addAction(tr("VR Compatibility"))
        self.overlay_vr.setCheckable(True)
        self.overlay_vr.triggered.connect(self.vr_compatibility)

        # Reload preset (check for opened config dialog)
        reload_preset = self.addAction(tr("Reload"))
        reload_preset.triggered.connect(parent.reload_preset)
        self.addSeparator()

        # Reset submenu
        menu_reset_data = ResetDataMenu(tr("Reset Data"), parent)
        self.destroyed.connect(menu_reset_data.deleteLater)  # parented to window: menu rebuilt (language change)
        self.addMenu(menu_reset_data)
        self.addSeparator()

        # Quit
        app_quit = self.addAction(tr("Quit"))
        app_quit.triggered.connect(parent.quit_app)

        # Refresh menu
        self.aboutToShow.connect(self.refresh_menu)

    def refresh_menu(self):
        """Refresh menu"""
        self.overlay_lock.setChecked(cfg.overlay["fixed_position"])
        self.overlay_hide.setChecked(cfg.overlay["auto_hide"])
        self.overlay_grid.setChecked(cfg.overlay["enable_grid_move"])
        self.overlay_vr.setChecked(cfg.overlay["vr_compatibility"])

    def refresh_preset_name(self):
        """Loaded preset name, whole (cut in the middle only when very long)"""
        loaded_preset = cfg.filename.setting.removesuffix(FileExt.JSON)
        metrics = QFontMetrics(self.loaded_preset.font())
        width = metrics.averageCharWidth() * TRAY_PRESET_CHARS
        self.loaded_preset.setText(metrics.elidedText(loaded_preset, Qt.TextElideMode.ElideMiddle, width))

    def refresh_presets(self):
        """Presets submenu: every preset (newest first), loaded one checked, choosing one loads it"""
        from .command_palette import load_preset, preset_names

        menu = self.menu_presets
        menu.clear()
        loaded = cfg.filename.setting.removesuffix(FileExt.JSON)
        group = QActionGroup(menu)
        for name in preset_names()[:TRAY_PRESETS]:
            action = menu.addAction(name.replace("&", "&&"))
            action.setCheckable(True)
            action.setChecked(name == loaded)
            group.addAction(action)
            action.triggered.connect(lambda _=False, preset=name: load_preset(preset))
        if menu.isEmpty():
            menu.addAction(tr("No preset found")).setEnabled(False)

    def open_preset_tab(self):
        """Open preset tab"""
        self._parent.centralWidget().select_preset_tab()
        self._parent.show_app()

    @staticmethod
    def is_locked():
        """Check lock state"""
        octrl.toggle.lock()

    @staticmethod
    def is_hidden():
        """Check hide state"""
        octrl.toggle.hide()

    @staticmethod
    def has_grid():
        """Check grid move state"""
        octrl.toggle.grid()

    @staticmethod
    def vr_compatibility():
        """Check VR compatibility state"""
        octrl.toggle.vr()


class ResetDataMenu(QMenu):
    """Reset user data menu"""

    def __init__(self, title, parent):
        super().__init__(title, parent)
        self._parent = parent

        reset_deltabest = self.addAction(tr("Delta Best"))
        reset_deltabest.triggered.connect(self.reset_deltabest)

        reset_energydelta = self.addAction(tr("Energy Delta"))
        reset_energydelta.triggered.connect(self.reset_energydelta)

        reset_fueldelta = self.addAction(tr("Fuel Delta"))
        reset_fueldelta.triggered.connect(self.reset_fueldelta)

        reset_consumption = self.addAction(tr("Consumption History"))
        reset_consumption.triggered.connect(self.reset_consumption)

        reset_sectorbest = self.addAction(tr("Sector Best"))
        reset_sectorbest.triggered.connect(self.reset_sectorbest)

        reset_trackmap = self.addAction(tr("Track Map"))
        reset_trackmap.triggered.connect(self.reset_trackmap)

    def reset_deltabest(self):
        """Reset deltabest data"""
        if self.__confirmation(
            data_type="delta best",
            extension="csv",
            filepath=cfg.path.delta_best,
            filename=api.read.session.combo_name(),
        ):
            mctrl.reload("module_delta")

    def reset_energydelta(self):
        """Reset energy delta data"""
        if self.__confirmation(
            data_type="energy delta",
            extension="energy",
            filepath=cfg.path.energy_delta,
            filename=api.read.session.combo_name(),
        ):
            mctrl.reload("module_fuel", discard=True)  # stopping module must not save the deleted data back

    def reset_fueldelta(self):
        """Reset fuel delta data"""
        if self.__confirmation(
            data_type="fuel delta",
            extension="fuel",
            filepath=cfg.path.fuel_delta,
            filename=api.read.session.combo_name(),
        ):
            mctrl.reload("module_fuel", discard=True)  # stopping module must not save the deleted data back

    def reset_consumption(self):
        """Reset consumption history data"""
        if self.__confirmation(
            data_type="consumption history",
            extension="consumption",
            filepath=cfg.path.fuel_delta,
            filename=api.read.session.combo_name(),
        ):
            mctrl.reload("module_stint", discard=True)  # stopping module must not save the deleted data back

    def reset_sectorbest(self):
        """Reset sector best data"""
        if self.__confirmation(
            data_type="sector best",
            extension="sector",
            filepath=cfg.path.sector_best,
            filename=api.read.session.combo_name(),
        ):
            mctrl.reload("module_sectors", discard=True)  # stopping module must not save the deleted data back

    def reset_trackmap(self):
        """Reset trackmap data"""
        if self.__confirmation(
            data_type="track map",
            extension="svg",
            filepath=cfg.path.track_map,
            filename=api.read.session.track_name(),
        ):
            mctrl.reload("module_mapping")

    def __confirmation(self, data_type: str, extension: str, filepath: str, filename: str) -> bool:
        """Message confirmation, returns true if file deleted"""
        # Data name in current language (English one title-cased in title, capitalized in message)
        data_name = tr(data_type)
        translated = data_name != data_type
        # Check if file exist
        filename_full = f"{filepath}{filename}.{extension}"
        if not os.path.exists(filename_full):
            QMessageBox.warning(
                self._parent,
                tr("Error"),
                trm(f"No {data_name} data found.<br><br>You can only reset data from active session."),
            )
            return False
        # Confirm reset
        msg_text = (
            f"Reset <b>{data_name}</b> data for<br>"
            f"<b>{filename}</b> ?<br><br>"
            "This cannot be undone!"
        )
        from ._common import confirm_action

        if not confirm_action(self._parent, trm(f"Reset {data_name if translated else data_name.title()}"),
                              trm(msg_text), tr("Reset"), danger=True):
            return False
        # Delete file
        try:
            os.remove(filename_full)
        except OSError as error:  # in use (overlay reading it), read-only or already gone
            QMessageBox.warning(self._parent, tr("Error"), trm(
                f"Unable to reset {data_name} data: {error.strerror or error}"))
            return False
        show_toast(self._parent, trm(
            f"{data_name if translated else data_name.capitalize()} data has been reset for<br><b>{filename}</b>"))
        return True


class ConfigMenu(QMenu):
    """Config menu"""

    def __init__(self, title, parent):
        super().__init__(title, parent)
        self._parent = parent

        config_page = self.addAction(tr("Open Settings"))
        config_page.setShortcut(QKeySequence("Ctrl+,"))
        config_page.triggered.connect(lambda: open_config_application(self._parent, ""))
        # Ctrl+F finds in the shown page, Ctrl+Shift+F any option
        find_option = self.addAction(tr("Find Option…"))
        find_option.setShortcut(QKeySequence("Ctrl+Shift+F"))
        find_option.triggered.connect(self.open_option_finder)
        self.addSeparator()

        config_app = self.addAction(tr("Application"))
        config_app.triggered.connect(self.open_config_application)

        config_compat = self.addAction(tr("Compatibility"))
        config_compat.triggered.connect(self.open_config_compatibility)

        config_notify = self.addAction(tr("Notification"))
        config_notify.triggered.connect(self.open_config_notification)
        self.addSeparator()

        config_units = self.addAction(tr("Units"))
        config_units.triggered.connect(self.open_config_units)

        config_font = self.addAction(tr("Global Font Override"))
        config_font.triggered.connect(self.open_config_font)

        config_style = self.addAction(tr("Overlay Style"))
        config_style.triggered.connect(self.open_config_overlay_style)

        config_remote = self.addAction(tr("Remote Control"))
        config_remote.triggered.connect(self.open_config_remote_control)

        config_web = self.addAction(tr("Web Dashboard"))
        config_web.triggered.connect(self.open_config_web_dashboard)

        show_web = self.addAction(tr("Web Dashboard Address…"))
        show_web.triggered.connect(self.show_web_dashboard_address)

        config_vr = self.addAction(tr("VR Overlay (Experimental)"))
        config_vr.triggered.connect(self.open_config_vr_overlay)
        self.addSeparator()

        config_userpath = self.addAction(tr("User Path"))
        config_userpath.triggered.connect(self.open_config_userpath)

        open_folder = self.addMenu(tr("Open Folder"))
        for path_name in cfg.path.__slots__:
            _folder = open_folder.addAction(option_label(path_name))
            _folder.triggered.connect(lambda checked=True, p=path_name: self.open_folder(checked, p))

        # Global settings of another copy of the app (older version, other computer): applied after restart
        import_settings = self.addAction(tr("Import Settings…"))
        import_settings.triggered.connect(self.import_settings)

    def import_settings(self):
        """Import global settings from a chosen folder (app restarts)"""
        from .settings_import import import_settings

        import_settings(self._parent)

    def open_folder(self, checked: bool, path_name: str):
        """Open folder in file manager"""
        filepath = getattr(cfg.path, path_name)
        error = False
        if not os.path.isdir(filepath):  # missing, or a file (path set to a program: never run)
            error = True
        elif PLATFORM.WINDOWS:
            try:
                filepath = filepath.replace("/", "\\")
                if sys.platform == "win32":  # platform check also read by type checker
                    os.startfile(filepath)
            except (OSError, RuntimeError):  # missing folder, no associated application, access denied
                error = True
        else:  # Linux: opened asynchronously, GUI never waits for file manager
            error = not QDesktopServices.openUrl(QUrl.fromLocalFile(filepath))
        if error:
            QMessageBox.warning(
                self._parent,
                tr("Error"),
                trm(f"Cannot open folder:<br><b>{html.escape(filepath)}</b>"),
            )

    def open_option_finder(self):
        """Find option in all settings"""
        from .option_finder import OptionFinder

        _dialog = OptionFinder(self._parent)
        _dialog.show()

    def open_config_application(self):
        """Config global application"""
        open_config_application(self._parent)

    def open_config_compatibility(self):
        """Config global compatibility"""
        open_config_application(self._parent, "compatibility")

    def open_config_vr_overlay(self):
        """Config native VR overlay"""
        open_config_application(self._parent, "vr_overlay")

    def open_config_remote_control(self):
        """Config remote control (command server)"""
        open_config_application(self._parent, "remote_control")

    def open_config_web_dashboard(self):
        """Config web dashboard"""
        open_config_application(self._parent, "web_dashboard")

    def show_web_dashboard_address(self):
        """Show web dashboard address & access code"""
        if not cfg.user.config["web_dashboard"]["enable_web_dashboard"]:
            QMessageBox.information(
                self._parent, tr("Web Dashboard"),
                tr("Web dashboard is disabled. Turn it on in Settings > Web Dashboard."),
            )
            return
        webdashboard = loader.webdashboard  # imported once used (http.server, ssl)
        message = QMessageBox(self._parent)
        message.setWindowTitle(tr("Web Dashboard"))
        message.setTextFormat(Qt.TextFormat.RichText)
        message.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        fingerprint = certificate_fingerprint(cfg.path.config) if webdashboard.use_https() else ""

        def show_addresses():
            # Addresses known now (never waits for the host name lookup, up to a second on a slow DNS or VPN):
            # the dialog is updated once the lookup running in background finds other ones (app_signal.addresses)
            links = "<br>".join(f"<a href='{url}'>{url}</a>" for url in webdashboard.urls(wait=False))
            text = trm(
                f"Open one of these addresses in a browser:<br><br>{links}<br><br>"
                f"Access code: <b>{webdashboard.access_code()}</b>"
            )
            if fingerprint:
                text += "<br><br>" + trm(
                    "The browser warns once about this self-signed certificate. "
                    f"Accept it only if its SHA-256 fingerprint is:<br><code>{fingerprint}</code>"
                )
            message.setText(text)

        show_addresses()
        app_signal.addresses.connect(show_addresses)
        try:
            message.exec()
        finally:
            with suppress(RuntimeError, TypeError):
                app_signal.addresses.disconnect(show_addresses)

    def open_config_overlay_style(self):
        """Config global overlay style"""
        open_config_application(self._parent, "overlay_style")

    def open_config_userpath(self):
        """Config global user path"""
        open_config_application(self._parent, "user_path")

    def open_config_notification(self):
        """Config GUI notification"""
        open_config_application(self._parent, "notification")

    def open_config_units(self):
        """Config display units"""
        open_preset_config(self._parent, "units")

    def open_config_font(self):
        """Config global font"""
        open_preset_config(self._parent, "font")


class APIMenu(QMenu):
    """API menu"""

    def __init__(self, title, parent):
        super().__init__(title, parent)
        self._parent = parent
        self.actions_api: QActionGroup | None = None
        self.reset_menu()
        self.aboutToShow.connect(self.refresh_menu)

    def reset_menu(self):
        """Reset menu"""
        self.clear()
        if self.actions_api is not None:  # group is not deleted with menu actions
            self.actions_api.deleteLater()

        self.actions_api = self.__api_selector()
        self.addSeparator()

        self.api_selection = self.addAction(tr("Remember API Selection from Preset"))
        self.api_selection.setCheckable(True)
        self.api_selection.triggered.connect(self.toggle_api_selection)

        self.legacy_api = self.addAction(tr("Enable Legacy API Selection"))
        self.legacy_api.setCheckable(True)
        self.legacy_api.triggered.connect(self.toggle_legacy_api)

        self.carsetup_backup = self.addAction(tr("Enable Auto Backup Car Setup"))
        self.carsetup_backup.setCheckable(True)
        self.carsetup_backup.triggered.connect(self.toggle_carsetup_backup)

        config_api = self.addAction(tr("Options"))
        config_api.triggered.connect(self.open_config_api)
        self.addSeparator()

        restart_api = self.addAction(tr("Restart API"))
        restart_api.triggered.connect(menu_restart_api)

    def refresh_menu(self):
        """Refresh menu"""
        selected_api_name = cfg.api_name
        actions = self.actions_api.actions() if self.actions_api is not None else []
        for action in actions:
            if selected_api_name == action.text():
                action.setChecked(True)
                break
        self.api_selection.setChecked(cfg.telemetry["enable_api_selection_from_preset"])
        self.carsetup_backup.setChecked(cfg.telemetry["enable_auto_backup_car_setup"])
        self.legacy_api.setChecked(cfg.telemetry["enable_legacy_api_selection"])

    def toggle_api_selection(self):
        """Toggle API selection mode"""
        enabled = cfg.telemetry["enable_api_selection_from_preset"]
        cfg.telemetry["enable_api_selection_from_preset"] = not enabled
        cfg.save(config_type=ConfigType.CONFIG)
        menu_reload_only()

    def toggle_carsetup_backup(self):
        """Toggle auto car setup backup"""
        enabled = cfg.telemetry["enable_auto_backup_car_setup"]
        cfg.telemetry["enable_auto_backup_car_setup"] = not enabled
        cfg.save(config_type=ConfigType.CONFIG)
        menu_refresh_only()

    def toggle_legacy_api(self):
        """Toggle legacy API selection"""
        enabled = cfg.telemetry["enable_legacy_api_selection"]
        cfg.telemetry["enable_legacy_api_selection"] = not enabled
        cfg.save(config_type=ConfigType.CONFIG)
        menu_restart_api()
        self.reset_menu()

    def open_config_api(self):
        """Config API"""
        open_preset_config(self._parent, "api")

    def __api_selector(self):
        """Generate API selector"""
        actions_api = QActionGroup(self)

        for _api in api.available:
            api_name = _api.NAME
            option = self.addAction(api_name)
            option.setCheckable(True)
            option.triggered.connect(lambda checked=True, name=api_name: self.__toggle_option(checked, name))
            actions_api.addAction(option)
        return actions_api

    def __toggle_option(self, checked: bool, api_name: str):
        """Toggle option"""
        if cfg.api_name == api_name:
            return
        cfg.api_name = api_name
        if cfg.telemetry["enable_api_selection_from_preset"]:
            save_type = ConfigType.SETTING
        else:
            save_type = ConfigType.CONFIG
        cfg.save(config_type=save_type)
        menu_reload_only()


class ToolsMenu(QMenu):
    """Tools menu: Pages submenu (pages left out of the navigation bar), then same entries as tools page"""

    def __init__(self, title, parent):
        super().__init__(title, parent)
        self._parent = parent
        self.menu_pages = self.addMenu(tr("Pages"))
        self.menu_pages.aboutToShow.connect(self.refresh_pages)
        self.refresh_pages()
        for _, tools in LISTED_TOOL_SECTIONS:
            self.addSeparator()
            for label, _, dialog_path in tools:
                action = self.addAction(tr(label))
                action.triggered.connect(lambda _=False, path=dialog_path: open_tool(path, self._parent))

    def refresh_pages(self):
        """Pages not in the navigation bar (reachable from here, the More menu & the command palette)"""
        from .nav_rail import NAV_PAGES, current_rail_items, page_name

        menu = self.menu_pages
        menu.clear()
        shown = set(current_rail_items())
        for index, (key, *_) in enumerate(NAV_PAGES):
            if key not in shown:
                menu.addAction(page_name(index)).triggered.connect(lambda _=False, page=index: self.select_page(page))
        if menu.isEmpty():
            menu.addAction(tr("Every page is in the navigation bar")).setEnabled(False)

    def select_page(self, index: int):
        view = self._parent.centralWidget()
        select = getattr(view, "select_page", None)
        if callable(select):
            select(index)


class WindowMenu(QMenu):
    """Window menu"""

    def __init__(self, title, parent):
        super().__init__(title, parent)
        self.show_at_startup = self.addAction(tr("Show at Startup"))
        self.show_at_startup.setCheckable(True)
        self.show_at_startup.triggered.connect(self.is_show_at_startup)

        self.minimize_to_tray = self.addAction(tr("Minimize to Tray"))
        self.minimize_to_tray.setCheckable(True)
        self.minimize_to_tray.triggered.connect(self.is_minimize_to_tray)

        self.remember_position = self.addAction(tr("Remember Position"))
        self.remember_position.setCheckable(True)
        self.remember_position.triggered.connect(self.is_remember_position)

        self.remember_size = self.addAction(tr("Remember Size"))
        self.remember_size.setCheckable(True)
        self.remember_size.triggered.connect(self.is_remember_size)

        self.remember_open_pages = self.addAction(tr("Reopen Pages at Startup"))
        self.remember_open_pages.setCheckable(True)
        self.remember_open_pages.triggered.connect(self.is_remember_open_pages)

        reset_size = getattr(parent, "reset_window_size", None)
        if callable(reset_size):
            self.addAction(tr("Reset Window Size and Position")).triggered.connect(reset_size)
        self.addSeparator()

        restart_app = self.addAction(tr("Restart NeoPedal"))
        restart_app.triggered.connect(getattr(parent, "restart_app", loader.restart))

        self.aboutToShow.connect(self.refresh_menu)

    def refresh_menu(self):
        """Refresh menu"""
        self.show_at_startup.setChecked(cfg.application["show_at_startup"])
        self.minimize_to_tray.setChecked(cfg.application["minimize_to_tray"])
        self.remember_position.setChecked(cfg.application["remember_position"])
        self.remember_size.setChecked(cfg.application["remember_size"])
        self.remember_open_pages.setChecked(cfg.application["remember_open_pages"])

    def is_show_at_startup(self):
        """Toggle config window startup state"""
        self.__toggle_option("show_at_startup")

    def is_minimize_to_tray(self):
        """Toggle minimize to tray state"""
        self.__toggle_option("minimize_to_tray")

    def is_remember_position(self):
        """Toggle config window remember position state"""
        self.__toggle_option("remember_position")

    def is_remember_size(self):
        """Toggle config window remember size state"""
        self.__toggle_option("remember_size")

    def is_remember_open_pages(self):
        """Toggle reopening tool pages left open at quit"""
        self.__toggle_option("remember_open_pages")

    @staticmethod
    def __toggle_option(option_name: str):
        """Toggle option"""
        cfg.application[option_name] = not cfg.application[option_name]
        cfg.save(config_type=ConfigType.CONFIG)


class HelpMenu(QMenu):
    """Help menu"""

    def __init__(self, title, parent):
        super().__init__(title, parent)
        self._parent = parent

        app_guide = self.addAction(tr("User Guide"))
        app_guide.triggered.connect(self.open_user_guide)

        app_page_help = self.addAction(tr("Help for This Page"))
        app_page_help.triggered.connect(self.open_page_help)

        app_faq = self.addAction(tr("Frequently Asked Questions"))
        app_faq.triggered.connect(self.open_faq)

        # Shortcut shown only (window shortcut runs it: one registered sequence, never ambiguous)
        app_keys = self.addAction(f"{tr('Keyboard Shortcuts')}\tCtrl+/")
        app_keys.triggered.connect(self.show_shortcuts)
        self.addSeparator()

        app_log = self.addAction(tr("Show Log"))
        app_log.triggered.connect(self.show_log)

        app_report = self.addAction(tr("Create Bug Report…"))
        app_report.triggered.connect(self.show_bug_report)

        app_wizard = self.addAction(tr("Setup Wizard"))
        app_wizard.triggered.connect(self.show_setup_wizard)
        self.addSeparator()

        app_update = self.addAction(tr("Check for Updates"))
        app_update.triggered.connect(self.show_update)

        app_notes = self.addAction(tr("What's New"))
        app_notes.triggered.connect(self.show_whats_new)
        self.addSeparator()

        app_about = self.addAction(tr("About"))
        app_about.triggered.connect(self.show_about)

    def show_about(self):
        """Show about"""
        from .about import About

        _dialog = About(self._parent)
        _dialog.show()

    def show_setup_wizard(self):
        """Show setup wizard"""
        from .setup_wizard import SetupWizard

        _dialog = SetupWizard(self._parent)
        _dialog.open()

    def show_shortcuts(self):
        """Keyboard shortcuts sheet"""
        open_shortcuts = getattr(self._parent, "open_shortcuts", None)
        if callable(open_shortcuts):
            open_shortcuts()

    def show_whats_new(self):
        """What's new in running version"""
        from .release_notes import running_version_dialog

        running_version_dialog(self._parent).open()

    def open_page_help(self):
        """User guide page of the shown page"""
        view = self._parent.centralWidget()
        open_help = getattr(view, "open_page_help", None)
        if callable(open_help):
            open_help()
        else:
            self.open_user_guide()

    def show_bug_report(self):
        """Create bug report"""
        from .bug_report_view import BugReport

        _dialog = BugReport(self._parent)
        _dialog.show()

    def show_log(self):
        """Show log"""
        from .log_info import LogInfo

        _dialog = LogInfo(self._parent)
        _dialog.show()

    def show_update(self):
        """Show update"""
        loader.update_checker.check(True)  # update module imported once used

    def open_user_guide(self):
        """Open user guide link"""
        QDesktopServices.openUrl(URL_USER_GUIDE)

    def open_faq(self):
        """Open FAQ link"""
        QDesktopServices.openUrl(URL_FAQ)
