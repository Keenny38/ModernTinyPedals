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
"""

import logging
import os
import signal
import subprocess
import sys
import time

from .api_control import api
from .command_server import cmdserver
from .const_file import FileExt
from .hotkey_control import kctrl
from .module_control import mctrl, wctrl
from .overlay_control import octrl
from .setting import cfg
from .update import update_checker
from .vr_overlay import vroverlay
from .web_dashboard import webdashboard

logger = logging.getLogger(__name__)


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
    cfg.save()
    # 2 start api
    api.connect()
    api.start()
    # 3 start modules
    mctrl.start()
    # 4 start widgets
    wctrl.start()
    # 5 start main window
    from .ui.app import AppWindow
    AppWindow()
    # Finalize loading after main GUI fully loaded
    logger.info("FINALIZING............")
    # 1 Enable overlay control
    octrl.enable()
    # 2 Enable hotkey control
    kctrl.enable()
    # 3 Enable remote control & VR overlay
    cmdserver.enable()
    webdashboard.enable()
    vroverlay().enable()
    # 4 Check for updates
    if cfg.application["check_for_updates_on_startup"]:
        update_checker.check(False)


def close():
    """Close api, modules, widgets. Call before quit APP."""
    logger.info("CLOSING............")
    # 1 unload modules
    unload_modules()
    # 2 stop & close api
    api.stop()
    api.close()
    logger.info("API: closed")


def restart():
    """Restart APP"""
    logger.info("RESTARTING............")
    # 0 must close first
    close()
    # 1 wait unfinished saving
    if cfg.is_saving:
        # Trigger immediate saving from queue
        cfg.save(next_task=True)
        while cfg.is_saving:
            time.sleep(0.01)
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
    """Command line to relaunch APP"""
    if getattr(sys, "frozen", False) or "tinypedal.exe" in sys.executable:  # if run as exe
        return [sys.executable, *sys.argv[1:]]
    return [sys.executable, *sys.argv]  # if run as script


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
    if cfg.is_saving:
        # Trigger immediate saving from queue
        cfg.save(next_task=True)
        while cfg.is_saving:
            time.sleep(0.01)
    # 1 unload modules
    unload_modules()
    # 2 reload user preset from file
    if reload_preset:
        cfg.load_user()
        cfg.save(0)  # save new changes in case preset was edited externally
    # 3 restart api
    api.restart()
    # 4 load modules
    load_modules()


def load_modules():
    """Load modules, widgets"""
    octrl.enable()  # 1 overlay control
    mctrl.start()  # 2 module
    wctrl.start()  # 3 widget
    kctrl.enable()  # 4 hotkey
    cmdserver.enable()  # 5 remote control
    webdashboard.enable()  # 5 web dashboard
    vroverlay().enable()  # 6 vr overlay


def unload_modules():
    """Unload modules, widgets"""
    vroverlay().disable()  # 0 vr overlay
    cmdserver.disable()  # 0 remote control
    webdashboard.disable()  # 0 web dashboard
    kctrl.disable()  # 1 hotkey
    wctrl.close()  # 2 widget
    mctrl.close()  # 3 module
    octrl.disable()  # 4 overlay control
