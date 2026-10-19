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
Launcher
"""

import ctypes
import hashlib
import logging
import os
import sys
import tempfile
from glob import glob
from time import monotonic, sleep

from PySide6.QtCore import QLocale, Qt
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QIcon, QPixmapCache
from PySide6.QtWidgets import QApplication, QMessageBox

from . import realtime_state, safe_mode, version_check
from .const_app import APP_NAME, CONFIG_ID, DESKTOP_FILE_NAME, PLATFORM, RESTART_ENVIRONMENT, VERSION
from .const_file import ConfigType, FontFile, LogFile
from .i18n import LANGUAGE_PACK_FOLDER, install_qt_translation, load_language_packs, set_language, tr
from .log_handler import BoundedLogStream, install_exception_hooks, set_logging_level
from .setting import cfg
from .userfile import settings_import_folders
from .userfile.settings_import import apply_pending_import, log_import_report, read_request, record_message

logger = logging.getLogger(__package__)
UI_FONT_FAMILIES = ("Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans")  # app UI, not overlays
log_stream = BoundedLogStream()  # latest log text only (log dialog, bug report), see getvalue()
INSTANCE_LOCK_RESTART_WAIT = 10.0  # seconds restarted app waits for previous one to exit (releasing its lock)
INSTANCE_LOCK_RETRY = 0.05  # seconds between lock tries while waiting
ERROR_ACCESS_DENIED = 5  # Windows error codes
ERROR_ALREADY_EXISTS = 183
SYNCHRONIZE = 0x00100000  # Windows access right, enough to tell a mutex exists
_instance_lock: int | None = None  # mutex handle (Windows) or locked file descriptor, held until process ends


def instance_lock_name() -> str:
    """Lock name of config folder in use: one running instance per config folder (user or portable)"""
    folder = os.path.normcase(os.path.abspath(cfg.path.config))
    return f"{CONFIG_ID}-{hashlib.sha1(folder.encode('utf-8', 'surrogatepass')).hexdigest()[:16]}"


def instance_lock_file() -> str:
    """Lock file (Linux), outside config folder (replaced by settings import while locked)"""
    folder = os.getenv("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return os.path.join(folder, f"{instance_lock_name()}.lock")


def lock_instance() -> bool:
    """Take lock of this instance (one step: two instances started together never both get it),
    False if held by another running instance. Lock released by OS when process ends (crash too).

    Raises:
        OSError: lock not available (single instance not enforced).
    """
    global _instance_lock
    if sys.platform == "win32":
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        handle = kernel32.CreateMutexW(None, False, f"Local\\{instance_lock_name()}")  # user session
        error = ctypes.get_last_error()
        if not handle:
            if error == ERROR_ACCESS_DENIED:  # created by another instance of other rights
                return False
            raise ctypes.WinError(error)
        if error == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(wintypes.HANDLE(handle))
            return False
        _instance_lock = handle
        return True
    import fcntl

    descriptor = os.open(instance_lock_file(), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        return False
    except OSError:
        os.close(descriptor)
        raise
    _instance_lock = descriptor
    return True


def acquire_instance_lock(wait: float = 0.0) -> bool:
    """Lock of this instance taken, waiting up to wait seconds for another instance to release it,
    False if still held by another running instance (lock not available: True, not enforced)"""
    deadline = monotonic() + wait
    while True:
        try:
            if lock_instance():
                return True
        except OSError as error:
            logger.warning("Single instance lock not available: %s", error)
            return True
        if monotonic() >= deadline:
            return False
        sleep(INSTANCE_LOCK_RETRY)


def other_instance_running() -> bool:
    """Another instance running in single instance mode (holding lock of config folder), lock not taken"""
    if sys.platform == "win32":
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.OpenMutexW.restype = wintypes.HANDLE
        handle = kernel32.OpenMutexW(SYNCHRONIZE, False, f"Local\\{instance_lock_name()}")
        if handle:
            kernel32.CloseHandle(wintypes.HANDLE(handle))
            return True
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED
    import fcntl

    try:
        descriptor = os.open(instance_lock_file(), os.O_RDWR)
    except OSError:  # no lock file: never locked since system start
        return False
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    except BlockingIOError:
        return True
    except OSError:
        return False
    finally:
        os.close(descriptor)
    return False


def single_instance_check(is_single_instance: bool):
    """Single instance check"""
    realtime_state.singleton = is_single_instance
    # Check if single instance mode enabled
    if not is_single_instance:
        logger.info("Single instance mode: OFF")
        return
    logger.info("Single instance mode: ON")
    # Restarted: always let in, lock taken once previous instance (exiting) released it
    if os.getenv(RESTART_ENVIRONMENT) == "TRUE":
        os.environ.pop(RESTART_ENVIRONMENT, None)
        if not acquire_instance_lock(INSTANCE_LOCK_RESTART_WAIT):
            logger.warning("Single instance lock still held by previous instance, started anyway")
        return
    if acquire_instance_lock():
        return
    # Show warning to console and popup dialog
    warning_text = (
        "NeoPedal is already running.\n\n"
        "Only one NeoPedal may be run at a time.\n"
        "Check system tray for hidden icon."
    )
    logger.warning(warning_text)
    root = QApplication(sys.argv)
    set_app_icon(root)
    QMessageBox.warning(None, f"{APP_NAME} v{VERSION}", warning_text)
    sys.exit()


def apply_settings_import():
    """Settings import asked last run, applied once this is the only running instance, before settings
    are loaded (a running instance would save its settings over imported ones, or hold its files)"""
    config_folder, data_folder = settings_import_folders()
    if not read_request(config_folder.rstrip("/\\")):
        return
    if not realtime_state.singleton and other_instance_running():  # multiple instances allowed: another one running
        record_message(logging.WARNING, "IMPORT: another NeoPedal is running, settings imported on next start")
        return
    apply_pending_import(config_folder, data_folder)


def get_version():
    """Get version info"""
    logger.info("NeoPedal: %s", VERSION)
    logger.info("Python: %s", version_check.python())
    logger.info("Qt: %s", version_check.qt())
    logger.info("PySide: %s", version_check.pyside())
    logger.info("psutil: %s", version_check.psutil())


def load_ui_language_packs():
    """Register language packs, before global config is loaded (validates language name)"""
    load_language_packs(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "i18n", "data", LANGUAGE_PACK_FOLDER),
        os.path.join(cfg.path.config, LANGUAGE_PACK_FOLDER),
    )


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
        root.setDesktopFileName(DESKTOP_FILE_NAME)


def load_bundled_fonts():
    """Load bundled font files (used by overlay modern style)"""
    for font_file in sorted(glob(f"{FontFile.FOLDER}*.ttf")):
        if QFontDatabase.addApplicationFont(font_file) < 0:
            logger.warning("Failed loading font: %s", font_file)
    logger.info("Bundled font: %s", "loaded" if FontFile.MODERN_FAMILY in QFontDatabase.families() else "not found")


def set_app_font(root: QApplication):
    """Set APP default font: modern UI font family if installed, else system UI font

    Family is set on app font, not by style sheet "font-family" (about 20 MB more memory).
    """
    font = root.font()
    font.setFamilies([*UI_FONT_FAMILIES, font.family()])
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


def ask_safe_mode() -> bool:
    """Previous start did not finish: ask whether to start in safe mode"""
    from .ui._common import confirm_action

    return confirm_action(
        None,
        f"{APP_NAME} v{VERSION}",
        tr("NeoPedal did not finish starting last time.\n\n"
           "Start in safe mode? Plugins and overlays are not started, so settings can be fixed, "
           "then NeoPedal restarted normally (Window menu, Restart NeoPedal)."),
        tr("Start in Safe Mode"), cancel_text=tr("Start Normally"), default_action=True,
    )


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
    apply_settings_import()
    unset_environment()
    set_logging_level(logger, cfg.path.config, LogFile.APP_LOG, log_stream, cli_args.log_level)
    install_exception_hooks(logger)
    get_version()
    log_import_report()  # settings import, done before logging was set
    # load global config (language packs first, else a pack language is reset to English)
    load_ui_language_packs()
    cfg.load_global()
    cfg.save(config_type=ConfigType.CONFIG)
    cfg.save(config_type=ConfigType.SHORTCUTS)
    set_environment()
    # Main GUI
    root = init_gui()
    # Safe mode decided before widgets & plugins are imported
    check_safe_mode(bool(getattr(cli_args, "safe_mode", False)))
    # Load core modules
    from . import loader
    loader.start()
    # Start mainloop
    sys.exit(root.exec())
