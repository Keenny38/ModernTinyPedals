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
Menu
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QActionGroup, QDesktopServices, QKeySequence
from PySide6.QtWidgets import QMenu, QMessageBox

from .. import app_signal, loader
from ..api_control import api
from ..const_app import PLATFORM, URL_FAQ, URL_USER_GUIDE
from ..const_file import ConfigType
from ..i18n import tr, trm
from ..i18n.options import option_label
from ..module_control import mctrl
from ..overlay_control import octrl
from ..setting import cfg
from ..update import update_checker
from ..web_dashboard import webdashboard
from .about import About
from .brake_editor import BrakeEditor
from .bug_report_view import BugReport
from .config import FontConfig, UserConfig
from .driver_stats_viewer import DriverStatsViewer
from .fuel_calculator import FuelCalculator
from .heatmap_editor import HeatmapEditor
from .lap_viewer import LapViewer
from .log_info import LogInfo
from .option_finder import OptionFinder
from .perf_view import PerformanceView
from .plugin_manager import PluginManager
from .preset_compare import PresetCompare
from .setup_wizard import SetupWizard
from .theme_editor import ThemeEditor
from .track_info_editor import TrackInfoEditor
from .track_map_viewer import TrackMapViewer
from .track_notes_editor import TrackNotesEditor
from .tyre_compound_editor import TyreCompoundEditor
from .tyre_strategy_planner import TyreStrategyPlanner
from .vehicle_brand_editor import VehicleBrandEditor
from .vehicle_class_editor import VehicleClassEditor


# Define menu command
def menu_reload_preset():
    """Command - full reload"""
    loader.reload(reload_preset=True)
    app_signal.refresh.emit(True)


def menu_reload_only():
    """Command - fast reload"""
    loader.reload(reload_preset=False)
    app_signal.refresh.emit(True)


def menu_refresh_only():
    """Command - refresh GUI"""
    app_signal.refresh.emit(True)


def menu_restart_api():
    """Command - restart api"""
    api.restart()
    app_signal.refresh.emit(True)


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
            self.loaded_preset.triggered.connect(self.open_preset_tab)
            self.aboutToShow.connect(self.refresh_preset_name)
            self.addSeparator()

            app_config = self.addAction(tr("Config"))
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
        menu_reset_data = ResetDataMenu("Reset Data", parent)
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
        """Refresh preset name"""
        loaded_preset = cfg.filename.setting[:-5]
        if len(loaded_preset) > 16:
            loaded_preset = f"{loaded_preset[:16]}..."
        self.loaded_preset.setText(loaded_preset)

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
            mctrl.reload("module_fuel")

    def reset_fueldelta(self):
        """Reset fuel delta data"""
        if self.__confirmation(
            data_type="fuel delta",
            extension="fuel",
            filepath=cfg.path.fuel_delta,
            filename=api.read.session.combo_name(),
        ):
            mctrl.reload("module_fuel")

    def reset_consumption(self):
        """Reset consumption history data"""
        if self.__confirmation(
            data_type="consumption history",
            extension="consumption",
            filepath=cfg.path.fuel_delta,
            filename=api.read.session.combo_name(),
        ):
            mctrl.reload("module_stint")

    def reset_sectorbest(self):
        """Reset sector best data"""
        if self.__confirmation(
            data_type="sector best",
            extension="sector",
            filepath=cfg.path.sector_best,
            filename=api.read.session.combo_name(),
        ):
            mctrl.reload("module_sectors")

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
        # Check if file exist
        filename_full = f"{filepath}{filename}.{extension}"
        if not os.path.exists(filename_full):
            QMessageBox.warning(
                self._parent,
                tr("Error"),
                trm(f"No {data_type} data found.<br><br>You can only reset data from active session."),
            )
            return False
        # Confirm reset
        msg_text = (
            f"Reset <b>{data_type}</b> data for<br>"
            f"<b>{filename}</b> ?<br><br>"
            "This cannot be undone!"
        )
        delete_msg = QMessageBox.question(
            self._parent, trm(f"Reset {data_type.title()}"), trm(msg_text),
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            defaultButton=QMessageBox.StandardButton.No,
        )
        if delete_msg != QMessageBox.StandardButton.Yes:
            return False
        # Delete file
        os.remove(filename_full)
        QMessageBox.information(
            self._parent,
            trm(f"Reset {data_type.title()}"),
            trm(f"{data_type.capitalize()} data has been reset for<br><b>{filename}</b>"),
        )
        return True


class ConfigMenu(QMenu):
    """Config menu"""

    def __init__(self, title, parent):
        super().__init__(title, parent)
        self._parent = parent

        find_option = self.addAction(tr("Find Option..."))
        find_option.setShortcut(QKeySequence.StandardKey.Find)
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

        show_web = self.addAction(tr("Web Dashboard Address..."))
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

    def open_folder(self, checked: bool, path_name: str):
        """Open folder in file manager"""
        filepath = getattr(cfg.path, path_name)
        error = False
        if PLATFORM.WINDOWS:
            try:
                filepath = filepath.replace("/", "\\")
                os.startfile(filepath)
            except (FileNotFoundError, RuntimeError):
                error = True
        else:  # Linux
            try:
                import subprocess
                subprocess.run(["xdg-open", filepath], check=True)
            except (FileNotFoundError, subprocess.SubprocessError):
                error = True
        if error:
            QMessageBox.warning(
                self._parent,
                tr("Error"),
                trm(f"Cannot open folder:<br><b>{filepath}</b>"),
            )

    def open_option_finder(self):
        """Find option in all settings"""
        _dialog = OptionFinder(self._parent)
        _dialog.show()

    def open_config_application(self):
        """Config global application"""
        _dialog = UserConfig(
            parent=self._parent,
            key_name="application",
            preset_name=cfg.filename.config,
            config_type=ConfigType.CONFIG,
            user_setting=cfg.user.config,
            default_setting=cfg.default.config,
            reload_func=menu_reload_preset,
        )
        _dialog.open()

    def open_config_compatibility(self):
        """Config global compatibility"""
        _dialog = UserConfig(
            parent=self._parent,
            key_name="compatibility",
            preset_name=cfg.filename.config,
            config_type=ConfigType.CONFIG,
            user_setting=cfg.user.config,
            default_setting=cfg.default.config,
            reload_func=menu_reload_preset,
        )
        _dialog.open()

    def open_config_vr_overlay(self):
        """Config native VR overlay"""
        _dialog = UserConfig(
            parent=self._parent,
            key_name="vr_overlay",
            preset_name=cfg.filename.config,
            config_type=ConfigType.CONFIG,
            user_setting=cfg.user.config,
            default_setting=cfg.default.config,
            reload_func=menu_reload_preset,
        )
        _dialog.open()

    def open_config_remote_control(self):
        """Config remote control (command server)"""
        _dialog = UserConfig(
            parent=self._parent,
            key_name="remote_control",
            preset_name=cfg.filename.config,
            config_type=ConfigType.CONFIG,
            user_setting=cfg.user.config,
            default_setting=cfg.default.config,
            reload_func=menu_reload_preset,
        )
        _dialog.open()

    def open_config_web_dashboard(self):
        """Config web dashboard"""
        _dialog = UserConfig(
            parent=self._parent,
            key_name="web_dashboard",
            preset_name=cfg.filename.config,
            config_type=ConfigType.CONFIG,
            user_setting=cfg.user.config,
            default_setting=cfg.default.config,
            reload_func=menu_reload_preset,
        )
        _dialog.open()

    def show_web_dashboard_address(self):
        """Show web dashboard address & access code"""
        if not cfg.user.config["web_dashboard"]["enable_web_dashboard"]:
            QMessageBox.information(
                self._parent, tr("Web Dashboard"),
                tr("Web dashboard is disabled. Enable it from Config menu, Web Dashboard."),
            )
            return
        links = "<br>".join(f"<a href='{url}'>{url}</a>" for url in webdashboard.urls())
        message = QMessageBox(self._parent)
        message.setWindowTitle(tr("Web Dashboard"))
        message.setTextFormat(Qt.TextFormat.RichText)
        message.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        message.setText(trm(
            f"Open one of these addresses in a browser:<br><br>{links}<br><br>"
            f"Access code: <b>{webdashboard.access_code()}</b>"
        ))
        message.exec()

    def open_config_overlay_style(self):
        """Config global overlay style"""
        _dialog = UserConfig(
            parent=self._parent,
            key_name="overlay_style",
            preset_name=cfg.filename.config,
            config_type=ConfigType.CONFIG,
            user_setting=cfg.user.config,
            default_setting=cfg.default.config,
            reload_func=menu_reload_preset,
        )
        _dialog.open()

    def open_config_userpath(self):
        """Config global user path"""
        _dialog = UserConfig(
            parent=self._parent,
            key_name="user_path",
            preset_name=cfg.filename.config,
            config_type=ConfigType.CONFIG,
            user_setting=cfg.user.config,
            default_setting=cfg.default.config,
            reload_func=menu_reload_preset,
            option_width=22,
        )
        _dialog.open()

    def open_config_notification(self):
        """Config GUI notification"""
        _dialog = UserConfig(
            parent=self._parent,
            key_name="notification",
            preset_name=cfg.filename.config,
            config_type=ConfigType.CONFIG,
            user_setting=cfg.user.config,
            default_setting=cfg.default.config,
            reload_func=menu_refresh_only,
        )
        _dialog.open()

    def open_config_units(self):
        """Config display units"""
        _dialog = UserConfig(
            parent=self._parent,
            key_name="units",
            preset_name=cfg.filename.setting,
            config_type=ConfigType.SETTING,
            user_setting=cfg.user.setting,
            default_setting=cfg.default.setting,
            reload_func=menu_reload_only,
        )
        _dialog.open()

    def open_config_font(self):
        """Config global font"""
        _dialog = FontConfig(
            parent=self._parent,
            user_setting=cfg.user.setting,
            reload_func=menu_reload_only,
        )
        _dialog.open()


class APIMenu(QMenu):
    """API menu"""

    def __init__(self, title, parent):
        super().__init__(title, parent)
        self._parent = parent
        self.reset_menu()
        self.aboutToShow.connect(self.refresh_menu)

    def reset_menu(self):
        """Reset menu"""
        self.clear()

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
        for action in self.actions_api.actions():
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
        _dialog = UserConfig(
            parent=self._parent,
            key_name=cfg.api_key,
            preset_name=cfg.filename.setting,
            config_type=ConfigType.SETTING,
            user_setting=cfg.user.setting,
            default_setting=cfg.default.setting,
            reload_func=menu_restart_api,
        )
        _dialog.open()

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
    """Tools menu"""

    def __init__(self, title, parent):
        super().__init__(title, parent)
        self._parent = parent

        utility_fuelcalc = self.addAction(tr("Fuel Calculator"))
        utility_fuelcalc.triggered.connect(self.open_utility_fuelcalc)

        utility_tyreplanner = self.addAction(tr("Tyre Strategy Planner"))
        utility_tyreplanner.triggered.connect(self.open_utility_tyreplanner)

        utility_driverstats = self.addAction(tr("Driver Stats Viewer"))
        utility_driverstats.triggered.connect(self.open_utility_driverstats)

        utility_mapviewer = self.addAction(tr("Track Map Viewer"))
        utility_mapviewer.triggered.connect(self.open_utility_mapviewer)

        utility_lapviewer = self.addAction(tr("Lap Telemetry Viewer"))
        utility_lapviewer.triggered.connect(self.open_utility_lapviewer)
        self.addSeparator()

        editor_heatmap = self.addAction(tr("Heatmap Editor"))
        editor_heatmap.triggered.connect(self.open_editor_heatmap)

        editor_brakes = self.addAction(tr("Brake Editor"))
        editor_brakes.triggered.connect(self.open_editor_brakes)

        editor_compounds = self.addAction(tr("Tyre Compound Editor"))
        editor_compounds.triggered.connect(self.open_editor_compounds)

        editor_brands = self.addAction(tr("Vehicle Brand Editor"))
        editor_brands.triggered.connect(self.open_editor_brands)

        editor_classes = self.addAction(tr("Vehicle Class Editor"))
        editor_classes.triggered.connect(self.open_editor_classes)

        editor_trackinfo = self.addAction(tr("Track Info Editor"))
        editor_trackinfo.triggered.connect(self.open_editor_trackinfo)

        editor_tracknotes = self.addAction(tr("Track Notes Editor"))
        editor_tracknotes.triggered.connect(self.open_editor_tracknotes)

        editor_theme = self.addAction(tr("Overlay Theme Editor"))
        editor_theme.triggered.connect(self.open_editor_theme)

        utility_compare = self.addAction(tr("Preset Comparison"))
        utility_compare.triggered.connect(self.open_preset_compare)

        utility_plugins = self.addAction(tr("Plugin Manager"))
        utility_plugins.triggered.connect(self.open_plugin_manager)

    def open_utility_fuelcalc(self):
        """Fuel calculator"""
        _dialog = FuelCalculator(self._parent)
        _dialog.show()

    def open_utility_tyreplanner(self):
        """Tyre strategy planner"""
        _dialog = TyreStrategyPlanner(self._parent)
        _dialog.show()

    def open_utility_driverstats(self):
        """Track driver stats viewer"""
        _dialog = DriverStatsViewer(self._parent)
        _dialog.show()

    def open_utility_mapviewer(self):
        """Track map viewer"""
        _dialog = TrackMapViewer(self._parent)
        _dialog.show()

    def open_editor_heatmap(self):
        """Edit heatmap preset"""
        _dialog = HeatmapEditor(self._parent)
        _dialog.show()

    def open_editor_brakes(self):
        """Edit brakes preset"""
        _dialog = BrakeEditor(self._parent)
        _dialog.show()

    def open_editor_compounds(self):
        """Edit compounds preset"""
        _dialog = TyreCompoundEditor(self._parent)
        _dialog.show()

    def open_editor_brands(self):
        """Edit brands preset"""
        _dialog = VehicleBrandEditor(self._parent)
        _dialog.show()

    def open_editor_classes(self):
        """Edit classes preset"""
        _dialog = VehicleClassEditor(self._parent)
        _dialog.show()

    def open_editor_trackinfo(self):
        """Edit track info"""
        _dialog = TrackInfoEditor(self._parent)
        _dialog.show()

    def open_editor_tracknotes(self):
        """Edit track notes"""
        _dialog = TrackNotesEditor(self._parent)
        _dialog.show()

    def open_utility_lapviewer(self):
        """Recorded lap viewer"""
        _dialog = LapViewer(self._parent)
        _dialog.show()

    def open_plugin_manager(self):
        """Manage widget plugins"""
        _dialog = PluginManager(self._parent)
        _dialog.show()

    def open_preset_compare(self):
        """Compare presets"""
        _dialog = PresetCompare(self._parent)
        _dialog.show()

    def open_editor_theme(self):
        """Edit custom overlay themes"""
        _dialog = ThemeEditor(self._parent)
        _dialog.show()


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
        self.addSeparator()

        restart_app = self.addAction(tr("Restart TinyPedal"))
        restart_app.triggered.connect(loader.restart)

        self.aboutToShow.connect(self.refresh_menu)

    def refresh_menu(self):
        """Refresh menu"""
        self.show_at_startup.setChecked(cfg.application["show_at_startup"])
        self.minimize_to_tray.setChecked(cfg.application["minimize_to_tray"])
        self.remember_position.setChecked(cfg.application["remember_position"])
        self.remember_size.setChecked(cfg.application["remember_size"])

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

        app_faq = self.addAction(tr("Frequently Asked Questions"))
        app_faq.triggered.connect(self.open_faq)

        app_log = self.addAction(tr("Show Log"))
        app_log.triggered.connect(self.show_log)

        app_report = self.addAction(tr("Create Bug Report..."))
        app_report.triggered.connect(self.show_bug_report)

        app_perf = self.addAction(tr("Widget Performance"))
        app_perf.triggered.connect(self.show_performance)

        app_wizard = self.addAction(tr("Setup Wizard"))
        app_wizard.triggered.connect(self.show_setup_wizard)
        self.addSeparator()

        app_update = self.addAction(tr("Check for Updates"))
        app_update.triggered.connect(self.show_update)
        self.addSeparator()

        app_about = self.addAction(tr("About"))
        app_about.triggered.connect(self.show_about)

    def show_about(self):
        """Show about"""
        _dialog = About(self._parent)
        _dialog.show()

    def show_setup_wizard(self):
        """Show setup wizard"""
        _dialog = SetupWizard(self._parent)
        _dialog.open()

    def show_performance(self):
        """Show widget performance"""
        _dialog = PerformanceView(self._parent)
        _dialog.show()

    def show_bug_report(self):
        """Create bug report"""
        _dialog = BugReport(self._parent)
        _dialog.show()

    def show_log(self):
        """Show log"""
        _dialog = LogInfo(self._parent)
        _dialog.show()

    def show_update(self):
        """Show update"""
        update_checker.check(True)

    def open_user_guide(self):
        """Open user guide link"""
        QDesktopServices.openUrl(URL_USER_GUIDE)

    def open_faq(self):
        """Open FAQ link"""
        QDesktopServices.openUrl(URL_FAQ)
