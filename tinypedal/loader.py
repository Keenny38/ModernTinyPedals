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
Loader function

Important: DO NOT call those functions in non-main thread.

Safe mode (see safe_mode): overlays (widgets & VR overlay) not started at start and reload,
a widget can still be turned on by hand; restart starts normally.
"""

import logging
import os
import signal
import subprocess
import sys

from . import safe_mode
from .api_control import api
from .command_server import cmdserver
from .const_file import FileExt
from .hotkey_control import kctrl
from .module.module_recorder import wait_lap_saver
from .module_control import mctrl, wctrl
from .overlay_control import octrl
from .replay import replay
from .setting import cfg
from .stream_overlay import streamoverlay
from .update import update_checker
from .vr_overlay import vroverlay
from .web_dashboard import webdashboard

logger = logging.getLogger(__name__)
LAP_SAVER_TIMEOUT = 10.0  # seconds to wait for lap files being written before restart


def int_signal_handler(sign, frame):
    """Quit by keyboard interrupt"""
    close()
    sys.exit()


def start():
    """Start api, modules, widgets, etc. Call once per launch."""
    logger.info("STARTING............")
    signal.signal(signal.SIGINT, int_signal_handler)
    # 1 load user preset
    cfg.set_next_to_load(f"{cfg.preset_files()[0]}{FileExt.JSON}")
    cfg.load_user()
    sync_screen_layout()
    cfg.save()
    # 2 start api
    api.connect()
    api.start()
    # 3 start modules
    mctrl.start()
    # 4 start widgets
    if not safe_mode.state.enabled:
        wctrl.start()
    # 5 start main window
    from .ui.app import AppWindow
    window = AppWindow()
    # Finalize loading after main GUI fully loaded
    logger.info("FINALIZING............")
    # 1 Enable overlay control
    octrl.enable()
    # 2 Enable hotkey control
    kctrl.enable()
    # 3 Enable remote control & VR overlay
    cmdserver.enable()
    webdashboard.enable()
    if not safe_mode.state.enabled:
        vroverlay().enable()
        streamoverlay.enable()
    # 4 Check for updates
    if cfg.application["check_for_updates_on_startup"]:
        update_checker.check(False)
    # 5 Start finished once window & overlays are up for a while (startup marker removed)
    from PySide6.QtCore import QTimer
    QTimer.singleShot(safe_mode.SETTLE_MS, finish_start)
    if safe_mode.state.enabled:
        QTimer.singleShot(0, lambda: show_safe_mode_notice(window))


def finish_start():
    """Start finished (main window & overlays up): next start is a normal one"""
    safe_mode.clear_marker(cfg.path.config)
    logger.info("STARTED: startup marker removed")


def show_safe_mode_notice(window):
    """Safe mode: shown in window title, notice offering to restart normally"""
    import shiboken6
    from PySide6.QtWidgets import QMessageBox

    from .i18n import tr

    if window is not None and not shiboken6.isValid(window):
        window = None
    if window is not None:
        window.setWindowTitle(f"{window.windowTitle()} - {tr('Safe Mode')}")
    box = QMessageBox(window if window is not None and window.isVisible() else None)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(tr("Safe Mode"))
    box.setText(tr("Safe mode: plugins are not loaded and overlays are not started.\n\n"
                   "Fix the settings that stopped Modern Tiny Pedals from starting, "
                   "then restart normally."))
    button_restart = box.addButton(tr("Restart Normally"), QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Close)
    box.exec()
    if box.clickedButton() is not button_restart:
        return
    restart_app = getattr(window, "restart_app", None)
    if callable(restart_app):
        restart_app()  # open pages may ask to save first
    else:
        restart()


def close():
    """Close api, modules, widgets. Call before quit APP."""
    logger.info("CLOSING............")
    # 1 unload modules (recorder module saves last lap)
    unload_modules()
    # 2 finish replay recording (manual recording is not stopped by recorder module)
    replay.stop_recording()
    # 3 stop & close api
    api.stop()
    api.close()
    logger.info("API: closed")
    # 4 quitting or restarting before start finished is no crash
    safe_mode.clear_marker(cfg.path.config)


def restart():
    """Restart APP"""
    logger.info("RESTARTING............")
    # 0 must close first
    close()
    # 1 wait unfinished saving (settings, recorded laps: process exits without waiting threads)
    cfg.flush()
    if not wait_lap_saver(LAP_SAVER_TIMEOUT):
        logger.warning("RESTARTING: lap saving not finished")
    # 2 set restart env for skipping single instance check
    os.environ["TINYPEDAL_RESTART"] = "TRUE"
    command = restart_command()
    if sys.platform == "win32":
        # os.execl does not quote arguments on Windows, which breaks path with spaces
        subprocess.Popen(command, close_fds=True)
        logging.shutdown()
        os._exit(0)
    os.execv(command[0], command)


def restart_command() -> list[str]:
    """Command line to relaunch APP, normal start (safe mode flag left out)"""
    arguments = safe_mode.restart_arguments(sys.argv)
    if getattr(sys, "frozen", False) or "tinypedal.exe" in sys.executable:  # if run as exe
        return [sys.executable, *arguments[1:]]
    return [sys.executable, *arguments]  # if run as script


def reload(reload_preset: bool = False):
    """Reload preset, api, modules, widgets

    Args:
        reload_preset:
            Whether to reload preset file.
            Should only done if changed global setting,
            or reloading from preset tab,
            or auto-loading preset.
    """
    logger.info("RELOADING............")
    # 0 wait unfinished saving
    cfg.flush()
    # 1 unload modules
    unload_modules()
    # 2 reload user preset from file
    if reload_preset:
        cfg.load_user()
        cfg.save(0)  # save new changes in case preset was edited externally
    # 3 widget positions of current screen setup
    sync_screen_layout()
    # 4 restart api
    api.restart()
    # 5 load modules
    load_modules()


def sync_screen_layout():
    """Restore widget positions saved for current screen setup (single, triple screen...)"""
    if not cfg.application["enable_layout_per_screen_setup"]:
        return
    from .template.setting_widget import WIDGET_FILENAME
    from .userfile.layout_profile import profile_filename, screen_key, sync_layout

    filename = profile_filename(cfg.path.settings, cfg.filename.setting)
    if sync_layout(cfg.user.setting, WIDGET_FILENAME, filename, screen_key()):
        cfg.save(0)


def load_modules():
    """Load modules, widgets (overlays kept off in safe mode)"""
    octrl.enable()  # 1 overlay control
    mctrl.start()  # 2 module
    if not safe_mode.state.enabled:
        wctrl.start()  # 3 widget
    kctrl.enable()  # 4 hotkey
    cmdserver.enable()  # 5 remote control
    webdashboard.enable()  # 5 web dashboard
    if not safe_mode.state.enabled:
        vroverlay().enable()  # 6 vr overlay
        streamoverlay.enable()  # 7 stream overlay


def unload_modules():
    """Unload modules, widgets"""
    vroverlay().disable()  # 0 vr overlay
    streamoverlay.disable()  # 0 stream overlay
    cmdserver.disable()  # 0 remote control
    webdashboard.disable()  # 0 web dashboard
    kctrl.disable()  # 1 hotkey
    wctrl.close()  # 2 widget
    mctrl.close()  # 3 module
    octrl.disable()  # 4 overlay control
