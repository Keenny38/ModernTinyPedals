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
Launcher
"""

import logging
import os
import sys
from glob import glob

import psutil
from PySide6.QtCore import QLocale, Qt
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QIcon, QPixmapCache
from PySide6.QtWidgets import QApplication, QMessageBox

from . import realtime_state, safe_mode, version_check
from .const_app import APP_NAME, PLATFORM, VERSION
from .const_file import ConfigType, FontFile, LogFile
from .i18n import LANGUAGE_PACK_FOLDER, install_qt_translation, load_language_packs, set_language, tr
from .log_handler import BoundedLogStream, set_logging_level
from .setting import cfg

logger = logging.getLogger(__package__)
log_stream = BoundedLogStream()  # latest log text only (log dialog, bug report), see getvalue()


def save_pid_file():
    """Save PID info to file"""
    with open(f"{cfg.path.config}{LogFile.PID}", "w", encoding="utf-8") as f:
        current_pid = os.getpid()
        pid_create_time = psutil.Process(current_pid).create_time()
        pid_str = f"{current_pid},{pid_create_time}"
        f.write(pid_str)


def is_pid_exist() -> bool:
    """Check and verify PID existence"""
    try:
        # Load last recorded PID and creation time from pid log file
        with open(f"{cfg.path.config}{LogFile.PID}", encoding="utf-8") as f:
            pid_read = f.readline()
        pid = pid_read.split(",")
        pid_last = int(pid[0])
        pid_last_create_time = pid[1]
        # Verify if last PID is running and belongs to TinyPedal
        if psutil.pid_exists(pid_last) and str(psutil.Process(pid_last).create_time()) == pid_last_create_time:
            return True  # already running
    except (ProcessLookupError, psutil.NoSuchProcess, ValueError, IndexError, FileNotFoundError):
        logger.info("PID not found or invalid")
    return False  # no running


def single_instance_check(is_single_instance: bool):
    """Single instance check"""
    realtime_state.singleton = is_single_instance
    # Check if single instance mode enabled
    if not is_single_instance:
        logger.info("Single instance mode: OFF")
        return
    logger.info("Single instance mode: ON")
    # Skip if restarted
    if os.getenv("TINYPEDAL_RESTART") == "TRUE":
        os.environ.pop("TINYPEDAL_RESTART", None)
        save_pid_file()
        return
    # Check existing PID file first, then exe PID
    if not is_pid_exist():  # (is_pid_exist() or is_exe_running())
        save_pid_file()
        return
    # Show warning to console and popup dialog
    warning_text = (
        "Modern Tiny Pedals is already running.\n\n"
        "Only one Modern Tiny Pedals may be run at a time.\n"
        "Check system tray for hidden icon."
    )
    logger.warning(warning_text)
    root = QApplication(sys.argv)
    set_app_icon(root)
    QMessageBox.warning(None, f"{APP_NAME} v{VERSION}", warning_text)
    sys.exit()


def get_version():
    """Get version info"""
    logger.info("Modern Tiny Pedals: %s", VERSION)
    logger.info("Python: %s", version_check.python())
    logger.info("Qt: %s", version_check.qt())
    logger.info("PySide: %s", version_check.pyside())
    logger.info("psutil: %s", version_check.psutil())


def init_gui() -> QApplication:
    """Initialize Qt Gui"""
    # Set global locale
    loc = QLocale(QLocale.Language.C)
    loc.setNumberOptions(QLocale.NumberOption.RejectGroupSeparator)
    QLocale.setDefault(loc)
    # Set DPI scale (always enabled in Qt6, can be force disabled via environment)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    # Set GUI
    QApplication.setStyle("Fusion")
    root = QApplication(sys.argv)
    # Set UI language (main window is rebuilt when changed later)
    load_language_packs(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "i18n", "data", LANGUAGE_PACK_FOLDER),
        os.path.join(cfg.path.config, LANGUAGE_PACK_FOLDER),
    )
    language_code = set_language(cfg.application["language"])
    install_qt_translation(root, language_code)
    root.setQuitOnLastWindowClosed(False)
    root.setApplicationName(APP_NAME)
    set_app_icon(root)
    set_app_font(root)
    load_bundled_fonts()
    # Disable global pixmap cache
    QPixmapCache.setCacheLimit(0)
    logger.info("Screen pixel ratio: %s", root.devicePixelRatio())
    logger.info("Platform plugin: %s", root.platformName())
    return root


def set_app_icon(root: QApplication):
    """Set APP icon, matching OS light / dark mode (updated on change by main window)"""
    from .ui import app_icon_file, system_dark_mode  # require QApplication (UI scaler)

    root.setWindowIcon(QIcon(app_icon_file(system_dark_mode())))
    # Set window icon for X11/Wayland (workaround)
    if not PLATFORM.WINDOWS:
        root.setDesktopFileName("TinyPedal-overlay")


def load_bundled_fonts():
    """Load bundled font files (used by overlay modern style)"""
    for font_file in sorted(glob(f"{FontFile.FOLDER}*.ttf")):
        if QFontDatabase.addApplicationFont(font_file) < 0:
            logger.warning("Failed loading font: %s", font_file)
    logger.info("Bundled font: %s", "loaded" if FontFile.MODERN_FAMILY in QFontDatabase.families() else "not found")


def set_app_font(root: QApplication):
    """Set APP default font"""
    font = root.font()
    # Keep system UI font family (Segoe UI on Windows), only normalize size
    font.setPointSize(10)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    root.setFont(font)


def unset_environment():
    """Clear any previous environment variable (required after auto-restarted APP)"""
    os.environ.pop("QT_QPA_PLATFORM", None)
    os.environ.pop("QT_ENABLE_HIGHDPI_SCALING", None)
    os.environ.pop("QT_MEDIA_BACKEND", None)


def set_environment():
    """Set environment before starting GUI"""
    # Windows only
    if PLATFORM.WINDOWS:
        # Use "freetype" to avoid high memory usage
        # Match system dark-mode on windows
        os.environ["QT_QPA_PLATFORM"] = "windows:darkmode=2:fontengine=freetype"
        os.environ["QT_MEDIA_BACKEND"] = "windows"

    # Linux only
    else:
        if cfg.compatibility["enable_x11_platform_plugin_override"]:
            os.environ["QT_QPA_PLATFORM"] = "xcb"

    # Common
    if cfg.application["enable_high_dpi_scaling"]:
        logger.info("High DPI scaling: ON")
    else:
        os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"  # force disable
        logger.info("High DPI scaling: OFF")


def load_overlay_themes():
    """Load custom overlay themes"""
    from .userfile.overlay_theme import load_custom_themes
    from .widget._style import BUILTIN_THEMES, set_custom_themes

    set_custom_themes(load_custom_themes(cfg.path.config, BUILTIN_THEMES))


def ask_safe_mode() -> bool:
    """Previous start did not finish: ask whether to start in safe mode"""
    answer = QMessageBox.question(
        None,
        f"{APP_NAME} v{VERSION}",
        tr("Modern Tiny Pedals did not finish starting last time.\n\n"
           "Start in safe mode? Plugins and overlays are not started, so settings can be fixed, "
           "then Modern Tiny Pedals restarted normally (Window menu, Restart Modern Tiny Pedals)."),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    return answer == QMessageBox.StandardButton.Yes


def check_safe_mode(flag: bool):
    """Safe mode from command line flag, or asked when previous start did not finish (start
    marked as under way until it finishes, see loader.start)"""
    if flag:
        safe_mode.state.enable("flag")
    elif safe_mode.unfinished_start(cfg.path.config):
        logger.warning("SAFE MODE: previous start did not finish")
        if ask_safe_mode():
            safe_mode.state.enable("crash")
        else:
            logger.info("SAFE MODE: declined, normal start")
    safe_mode.write_marker(cfg.path.config)


def start_app(cli_args):
    """Init main window"""
    single_instance_check(bool(cli_args.single_instance))
    unset_environment()
    set_logging_level(logger, cfg.path.config, LogFile.APP_LOG, log_stream, cli_args.log_level)
    get_version()
    # load global config
    cfg.load_global()
    cfg.save(config_type=ConfigType.CONFIG)
    cfg.save(config_type=ConfigType.SHORTCUTS)
    set_environment()
    # Main GUI
    root = init_gui()
    # Safe mode decided before widgets & plugins are imported (overlay themes import them)
    check_safe_mode(bool(getattr(cli_args, "safe_mode", False)))
    load_overlay_themes()
    # Load core modules
    from . import loader
    loader.start()
    # Start mainloop
    sys.exit(root.exec())
